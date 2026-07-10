from __future__ import annotations

from agent47.domain.repository.model import Repository
from agent47.domain.user.model import User
from typing import Optional
from sqlalchemy import String, ForeignKey, DateTime, JSON, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import uuid
from agent47.config.database import Base

class Build(Base):
    __tablename__ = "builds"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    repo_id: Mapped[str] = mapped_column(
        String, ForeignKey("repositories.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    user: Mapped[User] = relationship("User", back_populates="builds")
    repo: Mapped[Repository] = relationship("Repository", back_populates="builds")
    branch: Mapped[str] = mapped_column(String, nullable=False)
    commit_title: Mapped[str] = mapped_column(String, nullable=False)
    commit_description: Mapped[str] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    pusher: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    status: Mapped[Optional[str]] = mapped_column(String, default="pending", nullable=True)
    files_changed: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    log_sections: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    fix_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    identified_issues: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    total_additions: Mapped[Optional[int]] = mapped_column(Integer, default=0, nullable=True)
    total_deletions: Mapped[Optional[int]] = mapped_column(Integer, default=0, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self):
        return (
            f"Build(id={self.id!r}, "
            f"commit_title={self.commit_title!r},"
        )
