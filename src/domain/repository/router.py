"""
Repositories router — connect, track, and manage GitHub repos.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.config.config import GITHUB_WEBHOOK_SECRET, WEBHOOK_CALLBACK_URL
from src.domain.auth.router import get_current_user
from src.domain.user.model import User
from src.domain.repository.service import RepositoryService


router = APIRouter(prefix="/repos", tags=["repos"])


class TrackRepoRequest(BaseModel):
    """Request body for tracking a new repo."""
    repo_full_name: str
    webhook_callback_url: str = WEBHOOK_CALLBACK_URL


@router.get("/list")
def list_user_repos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all repos accessible to the user on GitHub.

    Flowchart step: 'Connect repos and orgs'.
    """
    repos = RepositoryService.list_repos(user.github_access_token)
    return {"repos": repos}


@router.get("/orgs")
def list_user_orgs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all orgs the user belongs to."""
    orgs = RepositoryService.list_orgs(user.github_access_token)
    return {"orgs": orgs}


@router.post("/track")
def track_repo(
    request: TrackRepoRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start tracking a repo — register a webhook for CI failure events.

    If the repo is already tracked, updates the webhook URL and returns
    the existing record instead of failing.
    """
    repo_svc = RepositoryService(db)
    parts = request.repo_full_name.split("/")
    owner, name = parts[0], parts[1]

    # Check if we're already tracking this repo
    existing_tracked = repo_svc.get_tracked_repo_by_full_name(request.repo_full_name)
    if existing_tracked and existing_tracked.user_id == user.id:
        # Already tracked — update the webhook URL on GitHub and return
        if existing_tracked.webhook_id:
            try:
                RepositoryService.update_webhook(
                    token=user.github_access_token,
                    repo_full_name=request.repo_full_name,
                    webhook_id=existing_tracked.webhook_id,
                    callback_url=request.webhook_callback_url,
                    secret=GITHUB_WEBHOOK_SECRET,
                )
            except Exception:
                pass  # Best-effort update
        return {
            "tracked_repo_id": existing_tracked.id,
            "full_name": existing_tracked.full_name,
            "updated": True,
        }

    # New repo — find or create the webhook on GitHub
    try:
        webhook_id = RepositoryService.get_or_create_webhook(
            token=user.github_access_token,
            repo_full_name=request.repo_full_name,
            callback_url=request.webhook_callback_url,
            secret=GITHUB_WEBHOOK_SECRET,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to create webhook: {exc}",
        ) from exc

    tracked = repo_svc.track_repo(
        user_id=user.id,
        owner=owner,
        name=name,
        full_name=request.repo_full_name,
        webhook_id=webhook_id,
    )
    return {"tracked_repo_id": tracked.id, "full_name": tracked.full_name}


@router.get("/tracked")
def list_tracked_repos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all repos the user is currently tracking."""
    repos = RepositoryService(db).get_tracked_repos(user.id)
    return {
        "repos": [
            {
                "id": r.id,
                "full_name": r.full_name,
                "is_active": r.is_active,
            }
            for r in repos
        ]
    }


@router.delete("/untrack/{repo_id}")
def untrack_repo(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop tracking a repo — remove the webhook."""
    repo_svc = RepositoryService(db)
    tracked = repo_svc.get_tracked_repo(repo_id)
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked repo not found")

    # Ensure the repo belongs to the authenticated user
    if tracked.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your repository")

    if tracked.webhook_id:
        try:
            RepositoryService.remove_webhook(
                token=user.github_access_token,
                repo_full_name=tracked.full_name,
                webhook_id=tracked.webhook_id,
            )
        except Exception:
            pass  # Best-effort cleanup

    repo_svc.untrack_repo(tracked)
    return {"message": f"Stopped tracking {tracked.full_name}"}
