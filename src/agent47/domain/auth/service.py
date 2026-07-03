import logging
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from github import Github
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
import logging

from agent47.config.config import (
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_REDIRECT_URI,
    JWT_SECRET_KEY,
    JWT_EXPIRY_DAYS,
)
from agent47.domain.auth.session import Session

logger = logging.getLogger(__name__)

class AuthService:

    @staticmethod
    def get_oauth_login_url() -> str:
        """Return the GitHub OAuth authorization URL the frontend should
        redirect the user to."""
        return (
            "https://github.com/login/oauth/authorize"
            f"?client_id={GITHUB_CLIENT_ID}"
            f"&redirect_uri={GITHUB_REDIRECT_URI}"
            "&scope=repo,read:org,user:email"
        )

    @staticmethod
    async def exchange_code_for_token(code: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        token = data.get("access_token")
        if not token:
            raise ValueError(
                f"GitHub OAuth failed: {data.get('error_description', data)}"
            )
        return token

    @staticmethod
    def get_user_info(token: str) -> dict:
        """Fetch the authenticated user's GitHub profile."""
        gh = Github(token)
        user = gh.get_user()
        logger.info("user from github %s", user)

        email = user.email or ""
        if not email:
            try:
                emails = user.get_emails()
                for e in emails:
                    if e.primary:
                        email = e.email
                        break
                    elif e.verified and not email:
                        email = e.email
                if not email and emails:
                    email = emails[0].email
            except Exception as ex:
                logger.warning("Could not fetch user emails: %s", ex)

        return {
            "login": user.login,
            "id": user.id,
            "avatar_url": user.avatar_url,
            "email": email,
        }

    # JWT Session Management

    @staticmethod
    def create_session(db: DBSession, user_id: str) -> str:
        """Create a database session row and return a signed JWT."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=JWT_EXPIRY_DAYS)

        session = Session(user_id=user_id, expires_at=expires)
        db.add(session)
        db.commit()
        db.refresh(session)

        payload = {
            "session_id": session.id,
            "user_id": user_id,
            "exp": expires,
            "iat": now,
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

    @staticmethod
    def verify_token(token: str) -> dict:
        """Decode and verify a JWT. Returns the payload dict.
        Raises jwt.InvalidTokenError on failure."""
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])

    @staticmethod
    def revoke_session(db: DBSession, session_id: str) -> None:
        """Delete a session row, immediately invalidating its JWT."""
        stmt = select(Session).where(Session.id == session_id)
        session = db.execute(stmt).scalar_one_or_none()
        if session:
            db.delete(session)
            db.commit()

