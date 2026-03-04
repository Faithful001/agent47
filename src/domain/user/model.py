"""User model — SQLAlchemy table for authenticated GitHub users."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base


class User(Base):
    """A registered Agent47 user linked to their GitHub account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex
    )
    github_username: Mapped[str] = mapped_column(String, nullable=False)
    github_access_token: Mapped[str] = mapped_column(String, nullable=False)
    github_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    avatar_url: Mapped[str] = mapped_column(String, default="")
    email: Mapped[str] = mapped_column(String, unique=True, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f"User(id={self.id!r}, username={self.github_username!r}, "
            f"email={self.email!r})"
        )