"""
Webhooks router — receive and process GitHub webhook events.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from src.config.database import get_db, SessionLocal
from src.domain.webhooks.parser import verify_signature, parse_webhook_event
from src.domain.contracts.service import ContractService
from src.domain.user.service import UserService
from src.domain.repositories.service import RepositoryService
from src.utils.track_push import TrackPush


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def receive_github_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive a GitHub webhook event, parse it, and trigger Agent47.

    Flowchart steps:
    - 'Listen for failed PRs (or via webhook)'
    - 'Trigger Agent 47'
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event_type == "push":
        repo_data = payload.get("repository", {})
        repo_full_name = repo_data.get("full_name", "")
        if repo_full_name:
            TrackPush(db).track_push(repo_full_name, payload)
        return {"status": "tracked", "reason": "Push event recorded"}

    failure = parse_webhook_event(event_type, payload)
    if failure is None:
        return {"status": "ignored", "reason": "Not a CI failure event"}

    repo_svc = RepositoryService(db)
    tracked_repo = repo_svc.get_tracked_repo_by_full_name(
        failure.repo_full_name
    )
    if not tracked_repo:
        return {
            "status": "ignored",
            "reason": f"Repo {failure.repo_full_name} is not tracked",
        }

    user = UserService(db).get_user(tracked_repo.user_id)
    if not user:
        raise HTTPException(
            status_code=500,
            detail="Tracked repo has no associated user",
        )

    # Create contract in the DB
    contract_svc = ContractService(db)
    contract = contract_svc.create_contract(
        repo_id=tracked_repo.full_name,
        user_id=user.id,
        trigger_event=event_type,
        error_message=failure.error_message,
        source_branch=failure.branch,
        commit_sha=failure.commit_sha,
        pr_number=failure.pr_number,
    )

    # Store the user token for background task (user obj will be detached)
    user_id = user.id
    repo_url = f"https://github.com/{tracked_repo.full_name}.git"
    contract_id = contract.id

    asyncio.create_task(
        _run_pipeline_background(contract_id, user_id, repo_url)
    )

    return {
        "status": "triggered",
        "contract_id": contract.id,
        "error_message": failure.error_message,
    }


async def _run_pipeline_background(contract_id, user_id, repo_url):
    """Run the Agent47 pipeline in a background task with its own session."""
    db = SessionLocal()
    try:
        contract = ContractService(db).get_contract(contract_id)
        user = UserService(db).get_user(user_id)

        if not contract or not user:
            logger.error("Contract or user not found for background task")
            return

        contract_svc = ContractService(db)
        await contract_svc.run_contract(contract, user, repo_url)
        logger.info(
            "Contract %s completed: status=%s, pr=%s",
            contract.id, contract.status, contract.pr_url,
        )
    except Exception:
        logger.exception(
            "Background pipeline failed for contract %s", contract_id
        )
    finally:
        db.close()
