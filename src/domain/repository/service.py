"""
Repositories service — repo listing, webhook management, and DB operations.
"""

from github import Github
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.repository.model import Repository


class RepositoryService:
    """Handles all repository-related database and GitHub API operations."""

    def __init__(self, db: Session):
        self.db = db

    # --- GitHub API ---

    @staticmethod
    def list_repos(token: str) -> list[dict]:
        """List all repos accessible to the authenticated user."""
        gh = Github(token)
        repos = []
        for repo in gh.get_user().get_repos():
            repos.append({
                "full_name": repo.full_name,
                "owner": repo.owner.login,
                "name": repo.name,
                "default_branch": repo.default_branch,
                "private": repo.private,
            })
        return repos

    @staticmethod
    def list_orgs(token: str) -> list[dict]:
        """List all organisations the authenticated user belongs to."""
        gh = Github(token)
        orgs = []
        for org in gh.get_user().get_orgs():
            orgs.append({
                "login": org.login,
                "id": org.id,
                "avatar_url": org.avatar_url,
            })
        return orgs

    @staticmethod
    def get_or_create_webhook(
        token: str,
        repo_full_name: str,
        callback_url: str,
        secret: str = "",
    ) -> int:
        """Register a webhook on a GitHub repo, or return the existing one's ID."""
        from github import GithubException

        gh = Github(token)
        repo = gh.get_repo(repo_full_name)
        config = {"url": callback_url, "content_type": "json"}
        if secret:
            config["secret"] = secret

        try:
            hook = repo.create_hook(
                name="web",
                config=config,
                events=["check_suite", "check_run", "workflow_run", "pull_request"],
                active=True,
            )
            return hook.id
        except GithubException as exc:
            if exc.status != 422:
                raise
            # Webhook already exists — find it and update its URL
            for hook in repo.get_hooks():
                hook.edit(
                    name="web",
                    config=config,
                    events=["check_run", "pull_request", "status"],
                    active=True,
                )
                return hook.id
            raise  # No hooks found despite the 422 — re-raise

    @staticmethod
    def update_webhook(
        token: str,
        repo_full_name: str,
        webhook_id: int,
        callback_url: str,
        secret: str = "",
    ) -> None:
        """Update a webhook's callback URL and config."""
        gh = Github(token)
        repo = gh.get_repo(repo_full_name)
        hook = repo.get_hook(webhook_id)
        config = {"url": callback_url, "content_type": "json"}
        if secret:
            config["secret"] = secret
        hook.edit(
            name="web",
            config=config,
            events=["check_run", "pull_request", "status"],
            active=True,
        )


    @staticmethod
    def remove_webhook(
        token: str,
        repo_full_name: str,
        webhook_id: int,
    ) -> None:
        """Remove a webhook from a GitHub repo."""
        gh = Github(token)
        repo = gh.get_repo(repo_full_name)
        hook = repo.get_hook(webhook_id)
        hook.delete()

    # --- Database ---

    def track_repo(
        self,
        user_id: str,
        owner: str,
        name: str,
        full_name: str,
        webhook_id: int,
    ) -> Repository:
        """Save a newly tracked repository to the database."""
        tracked = Repository(
            user_id=user_id,
            owner=owner,
            name=name,
            full_name=full_name,
            webhook_id=webhook_id,
        )
        self.db.add(tracked)
        self.db.commit()
        self.db.refresh(tracked)
        return tracked

    def get_tracked_repos(self, user_id: str) -> list[Repository]:
        """List all active tracked repos for a user."""
        stmt = (
            select(Repository)
            .where(
                Repository.user_id == user_id,
                Repository.is_active.is_(True),
            )
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_tracked_repo(self, repo_id: str, user_id: str) -> Repository | None:
        """Get a tracked repo by its ID."""
        stmt = (
            select(Repository)
            .where(
                Repository.id == repo_id,
                Repository.user_id == user_id,
                Repository.is_active.is_(True),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_tracked_repo_by_full_name(
        self, full_name: str, user_id: str
    ) -> Repository | None:
        """Look up a tracked repo by its GitHub full name (owner/repo)."""
        stmt = (
            select(Repository)
            .where(
                Repository.full_name == full_name,
                Repository.user_id == user_id,
                Repository.is_active.is_(True),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_webhook_tracked_repo_by_full_name(
        self, full_name: str
    ) -> Repository | None:
        """Look up a tracked repo by full name WITHOUT user_id (for webhook endpoints)."""
        stmt = (
            select(Repository)
            .where(
                Repository.full_name == full_name,
                Repository.is_active.is_(True),
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def untrack_repo(self, tracked: Repository) -> None:
        """Mark a tracked repo as inactive."""
        tracked.is_active = False
        self.db.commit()
