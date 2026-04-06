"""Repository model — SQLAlchemy table for tracked GitHub repos."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.config.database import Base


class Repository(Base):
    """A GitHub repo the user has chosen to track for CI failures."""

    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False
    )
    user: Mapped["User"] = relationship("User", back_populates="repositories")
    builds: Mapped[list["Build"]] = relationship(
        "Build", back_populates="repo", cascade="all, delete-orphan", order_by="desc(Build.created_at)"
    )
    owner: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, default="main")
    webhook_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    install_command: Mapped[str | None] = mapped_column(String, nullable=True)
    build_command: Mapped[str | None] = mapped_column(String, nullable=True)
    start_command: Mapped[str | None] = mapped_column(String, nullable=True)
    test_command: Mapped[str | None] = mapped_column(String, nullable=True)
    env_vars: Mapped[str | None] = mapped_column(String, nullable=True)
    root_directory: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f"Repository(id={self.id!r}, "
            f"full_name={self.full_name!r}, active={self.is_active})"
        )
