"""Contract model — SQLAlchemy table for bug-fix mission lifecycle."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from agent47.config.database import Base


class Contract(Base):
    """Tracks a single bug-fix lifecycle from webhook trigger to PR."""

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    repo_id: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    trigger_event: Mapped[str] = mapped_column(String, nullable=False)
    error_message: Mapped[str] = mapped_column(String, nullable=False)
    source_branch: Mapped[str] = mapped_column(String, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String, default="")
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Populated during / after the fix
    fix_branch: Mapped[str] = mapped_column(String, default="")
    pr_url: Mapped[str] = mapped_column(String, default="")
    fix_summary: Mapped[str] = mapped_column(String, default="")

    status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending | in_progress | fixed | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self):
        return (
            f"Contract(id={self.id!r}, repo={self.repo_id!r}, "
            f"status={self.status!r})"
        )
