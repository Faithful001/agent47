"""TrackedRepository model — SQLAlchemy table for tracked GitHub repos."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class TrackedRepository(Base):
    """A GitHub repo the user has chosen to track for CI failures."""

    __tablename__ = "tracked_repositories"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)  # "owner/repo"
    default_branch: Mapped[str] = mapped_column(String, default="main")
    webhook_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f"TrackedRepository(id={self.id!r}, "
            f"full_name={self.full_name!r}, active={self.is_active})"
        )
