"""
Webhooks router — receive and process GitHub webhook events.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, HTTPException, status
from redis.asyncio import Redis, RedisError
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agent47.config.database import get_db
from agent47.domain.contract.service import ContractService
from agent47.domain.repository.service import RepositoryService
from agent47.domain.user.service import UserService
from agent47.domain.auth.router import get_current_user
from agent47.domain.user.model import User
from agent47.domain.webhook.parser import verify_signature, parse_webhook_event
from agent47.infra.queue.tasks.run_pipeline import run_pipeline_task
from agent47.config.redis import get_redis
from agent47.utils.track_push import TrackPush

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def receive_github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Dict[str, Any]:
    """
    GitHub webhook receiver with deduplication and fast acknowledgment.

    1. Quick duplicate checks (delivery + commit)
    2. CI failure detection & agent triggering
    3. Push event tracking (non-blocking side effect)
    """
    # Security & fast path
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature):
        logger.warning("Invalid webhook signature received")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "unknown")
    delivery_id = request.headers.get("X-GitHub-Delivery", "unknown")

    logger.debug("Webhook delivery %s - event: %s", delivery_id, event_type)

    try:
        payload: Dict = await request.json()
    except Exception as exc:
        logger.error("Invalid JSON in webhook payload", exc_info=exc)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Quick duplicate check: same delivery ID
    delivery_key = f"webhook:processed:{delivery_id}"
    try:
        if await redis.exists(delivery_key):
            logger.debug("Duplicate delivery skipped: %s", delivery_id)
            return {
                "status": "duplicate",
                "reason": "Already processed this delivery",
                "delivery": delivery_id,
            }
    except RedisError as exc:
        logger.warning("Redis unavailable during delivery check", exc_info=exc)

    # Parse failure (only if relevant)
    failure = parse_webhook_event(event_type, payload)

    # Get the repo immediately to know context
    repo_data = payload.get("repository", {})
    repo_full_name = (repo_data.get("full_name") or "").strip()

    if not repo_full_name:
        return _default_response(event_type, delivery_id)

    repo_svc = RepositoryService(db)
    tracked_repo = repo_svc.get_webhook_tracked_repo_by_full_name(repo_full_name)

    if not tracked_repo:
        logger.info("Ignored: repo not tracked → %s", repo_full_name)
        return {
            "status": "ignored",
            "reason": f"Repository {repo_full_name} is not tracked",
            "delivery": delivery_id,
        }

    # If it's just a push event, track it against the known repo and exit
    if failure is None:
        if event_type == "push":
            await _track_push_non_blocking(tracked_repo, db, payload)
        return _default_response(event_type, delivery_id)

    # Normalize & validate failure
    commit_sha = (failure.commit_sha or "").strip()
    if not commit_sha:
        logger.warning("Incomplete failure data - sha missing")
        return _default_response(event_type, delivery_id)

    # Business deduplication: one agent run per broken commit
    commit_key = f"agent:processed:{repo_full_name}:{commit_sha}"

    try:
        if await redis.get(commit_key):
            logger.info(
                "Skipping duplicate failure processing → repo=%s commit=%s",
                repo_full_name, commit_sha[:8]
            )
            return {
                "status": "skipped",
                "reason": "Already processing / processed this commit failure",
                "delivery": delivery_id,
            }
    except RedisError as exc:
        logger.warning("Redis unavailable - proceeding without dedup", exc_info=exc)

    # Get user
    user_svc = UserService(db)
    user = user_svc.get_user(tracked_repo.user_id)

    if not user:
        logger.error("No user found for tracked repo: %s", repo_full_name)
        raise HTTPException(500, "Tracked repository has no associated user")

    # Create contract
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=1, max=5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def create_contract_with_retry():
        contract_svc = ContractService(db)
        return contract_svc.create_contract(
            repo_id=tracked_repo.full_name,
            user_id=user.id,
            trigger_event=event_type,
            error_message=failure.error_message,
            source_branch=failure.branch,
            commit_sha=commit_sha,
            pr_number=failure.pr_number,
            delivery_id=delivery_id,
        )

    try:
        contract = create_contract_with_retry()
    except Exception as exc:
        logger.exception("Failed to create contract after retries")
        raise HTTPException(500, "Failed to create contract")

    # Enqueue pipeline
    repo_url_with_token = f"https://oauth2:{user.github_access_token}@github.com/{repo.full_name}.git"
    run_pipeline_task.delay(
        contract_id=contract.id,
        user_id=user.id,
        repo_url=repo_url_with_token,
    )

    logger.info(
        "Pipeline enqueued → contract=%s repo=%s commit=%s delivery=%s",
        contract.id, repo_full_name, commit_sha[:8], delivery_id
    )

    # Mark as processed (both levels)
    try:
        pipe = redis.pipeline()
        pipe.set(delivery_key, "done", ex=86400 * 2)          # 2 days
        pipe.set(commit_key, "done", ex=86400 * 14)           # 2 weeks
        await pipe.execute()
    except RedisError as exc:
        logger.warning("Failed to set dedup keys - non-critical", exc_info=exc)

    return {
        "status": "triggered",
        "contract_id": str(contract.id),
        "delivery": delivery_id,
        "commit_sha": commit_sha,
    }


# Helpers

async def _track_push_non_blocking(tracked_repo, db: Session, payload: Dict):
    try:
        TrackPush(db).track_push(tracked_repo, payload)
        logger.debug("Push tracked: %s", tracked_repo.full_name)
    except Exception:
        logger.exception("Push tracking failed (non-fatal) - repo: %s", tracked_repo.full_name)


def _default_response(event_type: str, delivery_id: str) -> Dict[str, Any]:
    return {
        "status": "accepted",
        "reason": f"Event '{event_type}' processed (no action taken)",
        "delivery": delivery_id,
    }