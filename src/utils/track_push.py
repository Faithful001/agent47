import logging
from sqlalchemy.orm import Session
from src.domain.repositories.models import TrackedPush

logger = logging.getLogger(__name__)


class TrackPush:
    def __init__(self, db: Session):
        self.db = db

    def track_push(self, repo_full_name: str, push_data: dict) -> None:
        """Extract push info and save to DB."""
        logger.info("Push made on repo %s", repo_full_name)
        ref = push_data.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        head_commit = push_data.get("head_commit") or {}
        commit_sha = head_commit.get("id", "")
        pusher_info = push_data.get("pusher") or {}
        pusher = pusher_info.get("name", "")

        push_record = TrackedPush(
            repo_full_name=repo_full_name,
            branch=branch,
            commit_sha=commit_sha,
            pusher=pusher,
        )
        self.db.add(push_record)
        self.db.commit()