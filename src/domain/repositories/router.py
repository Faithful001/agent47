"""
Repositories router — connect, track, and manage GitHub repos.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.config.config import GITHUB_WEBHOOK_SECRET
from src.domain.user.service import UserService
from src.domain.repositories.service import RepositoryService


router = APIRouter(prefix="/repos", tags=["repos"])


class TrackRepoRequest(BaseModel):
    """Request body for tracking a new repo."""
    user_id: str
    repo_full_name: str
    webhook_callback_url: str = "http://localhost:8000/webhooks/github"


@router.get("/list")
def list_user_repos(user_id: str, db: Session = Depends(get_db)):
    """List all repos accessible to the user on GitHub.

    Flowchart step: 'Connect repos and orgs'.
    """
    user = UserService(db).get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    repos = RepositoryService.list_repos(user.github_access_token)
    return {"repos": repos}


@router.get("/orgs")
def list_user_orgs(user_id: str, db: Session = Depends(get_db)):
    """List all orgs the user belongs to."""
    user = UserService(db).get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    orgs = RepositoryService.list_orgs(user.github_access_token)
    return {"orgs": orgs}


@router.post("/track")
def track_repo(request: TrackRepoRequest, db: Session = Depends(get_db)):
    """Start tracking a repo — register a webhook for CI failure events.

    Flowchart step: 'Select repos to track bugs'.
    """
    user = UserService(db).get_user(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    repo_svc = RepositoryService(db)

    try:
        webhook_id = RepositoryService.create_webhook(
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

    parts = request.repo_full_name.split("/")
    owner, name = parts[0], parts[1]

    tracked = repo_svc.track_repo(
        user_id=request.user_id,
        owner=owner,
        name=name,
        full_name=request.repo_full_name,
        webhook_id=webhook_id,
    )
    return {"tracked_repo_id": tracked.id, "full_name": tracked.full_name}


@router.get("/tracked")
def list_tracked_repos(user_id: str, db: Session = Depends(get_db)):
    """List all repos the user is currently tracking."""
    repos = RepositoryService(db).get_tracked_repos(user_id)
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
def untrack_repo(repo_id: str, db: Session = Depends(get_db)):
    """Stop tracking a repo — remove the webhook."""
    repo_svc = RepositoryService(db)
    tracked = repo_svc.get_tracked_repo(repo_id)
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked repo not found")

    user = UserService(db).get_user(tracked.user_id)
    if user and tracked.webhook_id:
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
