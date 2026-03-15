"""
Auth router — GitHub OAuth login and callback endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.domain.auth.service import (
    AuthService
)
from src.domain.user.service import UserService


router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCallbackResponse(BaseModel):
    """Response after successful OAuth callback."""
    user_id: str
    username: str
    is_new_user: bool


@router.get("/login")
def login():
    """Return the GitHub OAuth URL the frontend should redirect to.

    Flowchart step: 'Register with GitHub'.
    """
    return {"url": AuthService.get_oauth_login_url()}


@router.get("/callback", response_model=AuthCallbackResponse)
async def oauth_callback(code: str, db: Session = Depends(get_db)):
    """Handle the GitHub OAuth callback.

    Flowchart steps:
    'Account exists?' → 'Create user account' → 'Log the user in'.
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
        is_new = False
    else:
        user = user_svc.create_user(
            username=info["login"],
            github_access_token=token,
            github_id=info["id"],
            avatar_url=info["avatar_url"],
            email=info["email"],
        )
        is_new = True

    return AuthCallbackResponse(
        user_id=user.id,
        username=user.username,
        is_new_user=is_new,
    )
