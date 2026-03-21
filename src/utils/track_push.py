import logging
from sqlalchemy.orm import Session
from src.domain.build.model import Build

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
        commit_message = head_commit.get("message", "")
        commit_parts = commit_message.split("\n\n", 1)
        commit_title = commit_parts[0].strip()
        commit_description = commit_parts[1].strip() if len(commit_parts) > 1 else ""

        pusher_info = push_data.get("pusher") or {}
        pusher = pusher_info.get("name", "")

        build_record = Build(
            repo_id=repo_full_name,
            branch=branch,
            commit_title=commit_title,
            commit_description=commit_description,
            commit_sha=commit_sha,
            pusher=pusher,
        )
        self.db.add(build_record)
        self.db.commit()