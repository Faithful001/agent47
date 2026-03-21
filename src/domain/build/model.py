from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import uuid
from src.config.database import Base

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
    user: Mapped["User"] = relationship("User", back_populates="builds")
    repo: Mapped["Repository"] = relationship("Repository", back_populates="builds")
    branch: Mapped[str] = mapped_column(String, nullable=False)
    commit_title: Mapped[str] = mapped_column(String, nullable=False)
    commit_description: Mapped[str] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    pusher: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f"Build(id={self.id!r}, "
            f"commit_title={self.commit_title!r},"
        )