import logging
from sqlalchemy.orm import Session
from agent47.domain.build.model import Build
from agent47.domain.repository.service import RepositoryService
from agent47.infra.queue.tasks.run_ci_task import run_ci_task

logger = logging.getLogger(__name__)


class TrackPush:
    def __init__(self, db: Session):
        self.db = db

    def track_push(self, tracked_repo, push_data: dict):
        """Extract push info and save to DB."""
        logger.info("Push made on repo %s", tracked_repo.full_name)

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
            repo_id=tracked_repo.id,
            user_id=tracked_repo.user_id,
            branch=branch,
            commit_title=commit_title,
            commit_description=commit_description,
            commit_sha=commit_sha,
            pusher=pusher,
        )
        self.db.add(build_record)
        self.db.commit()

        # Trigger the custom CI task
        logger.info("About to run the custom CI task for build %s", build_record.id)
        run_ci_task.delay(build_id=str(build_record.id), repo_id=str(tracked_repo.id))