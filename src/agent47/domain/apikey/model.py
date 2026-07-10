from __future__ import annotations

from sqlalchemy import String, ForeignKey, DateTime, Float, Boolean
from datetime import datetime, timezone
from agent47.domain.user.model import User
from sqlalchemy.orm import relationship, mapped_column, Mapped
import uuid
from agent47.config.database import Base

class ApiKey(Base):
    __tablename__ = "apikeys"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    user: Mapped[User] = relationship("User", back_populates="apikeys")
    model: Mapped[str | None] = mapped_column(String, default="gemini-1.5-pro", nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, default=0.2, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    