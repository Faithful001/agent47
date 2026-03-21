"""
Auth router — GitHub OAuth login/callback, session management, and
the ``get_current_user`` dependency used by protected endpoints.
"""

from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.config import FRONTEND_URL
from src.config.database import get_db
from src.domain.auth.service import AuthService
from src.domain.auth.session import Session as SessionModel
from src.domain.user.model import User
from src.domain.user.service import UserService


router = APIRouter(prefix="/auth", tags=["auth"])


# ── Response schemas ─────────────────────────────────────────────

class UserInfoResponse(BaseModel):
    """Returned by /auth/me."""
    user_id: str
    username: str
    avatar_url: str
    email: str


# ── Dependency: get_current_user ────────────────────────────────

async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # 1. Decode JWT
    try:
        payload = AuthService.verify_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # 2. Check that the session row still exists (not revoked / logged-out)
    session_id = payload.get("session_id")
    stmt = select(SessionModel).where(SessionModel.id == session_id)
    session = db.execute(stmt).scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=401, detail="Session revoked")

    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")

    # 3. Load the user
    user_svc = UserService(db)
    user = user_svc.get_user(payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/login")
def login():
    """Return the GitHub OAuth URL the frontend should redirect to.

    Flowchart step: 'Register with GitHub'.
    """
    return {"url": AuthService.get_oauth_login_url()}


@router.get("/github/callback")
async def oauth_callback(code: str, db: Session = Depends(get_db)):
    """Handle the GitHub OAuth callback.

    1. Exchange code for GitHub token
    2. Fetch GitHub user info
    3. Create or update the local user
    4. Create a DB-backed session + sign a JWT
    5. Set the JWT as an HttpOnly cookie
    6. Redirect to the frontend dashboard
    """
    try:
        token = await AuthService.exchange_code_for_token(code)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange OAuth code: {exc}",
        ) from exc

    info = AuthService.get_user_info(token)
    user_svc = UserService(db)
    existing = user_svc.get_user_by_github_id(info["id"])

    if existing:
        user = user_svc.update_token(existing, token)
    else:
        user = user_svc.create_user(
            username=info["login"],
            github_access_token=token,
            github_id=info["id"],
            avatar_url=info["avatar_url"],
            email=info["email"],
        )

    # Create a server-side session and get a signed JWT
    session_jwt = AuthService.create_session(db, user.id)

    # Redirect to the frontend and set the session cookie
    response = RedirectResponse(url=f"{FRONTEND_URL}/dashboard")
    response.set_cookie(
        key="session_token",
        value=session_jwt,
        httponly=True,      # JS cannot read this cookie (XSS protection)
        secure=False,       # Set to True in production (requires HTTPS)
        samesite="lax",     # CSRF protection
        max_age=7 * 24 * 3600,  # 7 days in seconds
        path="/",
    )
    return response


@router.get("/me", response_model=UserInfoResponse)
def me(user: User = Depends(get_current_user)):
    """Return info about the currently authenticated user.

    The browser automatically sends the HttpOnly cookie — no need
    for the frontend to manually attach any token.
    """
    return UserInfoResponse(
        user_id=user.id,
        username=user.username,
        avatar_url=user.avatar_url,
        email=user.email,
    )


@router.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    """Revoke the current session and clear the cookie.

    After this, the JWT is useless even if someone captured it,
    because the session row no longer exists in the database.
    """
    token = request.cookies.get("session_token")
    if token:
        try:
            payload = AuthService.verify_token(token)
            AuthService.revoke_session(db, payload["session_id"])
        except Exception:
            pass  # Token was already invalid — still clear the cookie

    response = RedirectResponse(url=f"{FRONTEND_URL}", status_code=303)
    response.delete_cookie(key="session_token", path="/")
    return response
