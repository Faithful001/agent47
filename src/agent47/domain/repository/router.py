"""
Repositories router — connect, track, and manage GitHub repos.
"""

from agent47.utils.crypto import decrypt_value
from agent47.domain.repository.dto.update_repo_dto import UpdateRepoDto
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent47.config.database import get_db
from agent47.config.config import GITHUB_WEBHOOK_SECRET, WEBHOOK_CALLBACK_URL
from agent47.domain.auth.router import get_current_user
from agent47.domain.user.model import User
from agent47.domain.repository.service import RepositoryService


router = APIRouter(prefix="/repos", tags=["repos"])


class TrackRepoRequest(BaseModel):
    """Request body for tracking a new repo."""
    repo_full_name: str
    webhook_callback_url: str = WEBHOOK_CALLBACK_URL
    install_command: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    test_command: str | None = None
    env_vars: str | None = None
    root_directory: str | None = None


@router.get("/")
def list_user_repos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all repos accessible to the user on GitHub.

    Flowchart step: 'Connect repos and orgs'.
    """
    repos = RepositoryService.list_repos(user.github_access_token)
    return {"message": "All repos", "data": repos}


@router.get("/orgs")
def list_user_orgs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all orgs the user belongs to."""
    orgs = RepositoryService.list_orgs(user.github_access_token)
    return orgs


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
    existing_tracked = repo_svc.get_tracked_repo_by_full_name(request.repo_full_name, user.id)
    if existing_tracked and existing_tracked.user_id == user.id:
        # Already tracked — update the configuration and webhook URL
        from agent47.utils.crypto import encrypt_value
        existing_tracked.install_command = request.install_command
        existing_tracked.build_command = request.build_command
        existing_tracked.start_command = request.start_command
        existing_tracked.test_command = request.test_command
        existing_tracked.env_vars = encrypt_value(request.env_vars)
        existing_tracked.root_directory = request.root_directory
        db.commit()

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
        install_command=request.install_command,
        build_command=request.build_command,
        start_command=request.start_command,
        test_command=request.test_command,
        env_vars=request.env_vars,
        root_directory=request.root_directory,
    )
    return {"tracked_repo_id": tracked.id, "full_name": tracked.full_name}


@router.get("/tracked")
def list_tracked_repos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all repos the user is currently tracking."""
    repos = RepositoryService(db).get_tracked_repos(user.id)
    return  [
                {
                    "id": r.id,
                    "name": r.name,
                    "full_name": r.full_name,
                    "is_active": r.is_active,
                }
                for r in repos
        ]


@router.get("/{repo_id}")
def get_repo(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific repo."""
    repo = RepositoryService(db).get_tracked_repo(repo_id, user.id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")
    repo.env_vars = decrypt_value(repo.env_vars)
    return {"message": "Repo found", "data": repo}


@router.post("/untrack/{repo_id}")
def untrack_repo(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop tracking a repo. remove the webhook."""
    repo_svc = RepositoryService(db)
    tracked = repo_svc.get_tracked_repo(repo_id, user.id)
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
    return f"Stopped tracking {tracked.full_name}"


@router.patch("/{repo_id}")
def update_repo(repo_id: str, payload: UpdateRepoDto, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    repo_svc = RepositoryService(db)
    tracked = repo_svc.get_tracked_repo(repo_id, user.id)
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked repo not found")
    repo_svc.update_repo(repo_id, user.id, payload)
    return "Repo updated successfully"
    


@router.delete("/{repo_id}")
def delete_repo(
    repo_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a tracked repo from the database."""
    repo_svc = RepositoryService(db)
    tracked = repo_svc.get_tracked_repo(repo_id, user.id)
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

    repo_svc.delete_repo(repo_id, user.id)
    return f"Deleted {tracked.full_name}"