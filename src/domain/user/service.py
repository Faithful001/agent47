"""
User service — database operations for the User model.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.user.model import User


class UserService:
    """Handles all user-related database operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: str) -> User | None:
        """Look up a user by their internal ID."""
        return self.db.get(User, user_id)

    def get_user_by_github_id(self, github_id: int) -> User | None:
        """Look up a user by their GitHub ID."""
        stmt = select(User).where(User.github_id == github_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def create_user(
        self,
        username: str,
        github_access_token: str,
        github_id: int,
        first_name: str = "",
        last_name: str = "",
        avatar_url: str = "",
        email: str = "",
    ) -> User:
        """Create a new user and persist to the database."""
        user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            github_access_token=github_access_token,
            github_id=github_id,
            avatar_url=avatar_url,
            email=email,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_token(self, user: User, new_token: str) -> User:
        """Update a user's GitHub access token."""
        user.github_access_token = new_token
        self.db.commit()
        self.db.refresh(user)
        return user