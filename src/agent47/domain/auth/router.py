from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent47.config.config import FRONTEND_URL
from agent47.config.database import get_db
from agent47.domain.auth.service import AuthService
from agent47.domain.auth.session import Session as SessionModel
from agent47.domain.user.model import User
from agent47.domain.user.service import UserService
from agent47.domain.repository.model import Repository
from agent47.domain.build.model import Build
from agent47.domain.contract.model import Contract


router = APIRouter(prefix="/auth", tags=["auth"])


# Response schemas

class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    avatar_url: str
    email: str
    created_at: str


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


# Endpoints

@router.get("/login")
def login():
    return {"url": AuthService.get_oauth_login_url()}


@router.get("/github/callback")
async def oauth_callback(code: str, db: Session = Depends(get_db)):
    
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
        created_at=user.created_at.isoformat(),
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


@router.get("/profile-stats")
def profile_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repos_count = db.query(Repository).filter(Repository.user_id == user.id, Repository.is_active == True).count()
    
    builds = db.query(Build).filter(Build.user_id == user.id).all()
    total_builds = len(builds)
    
    durations = [b.duration_ms for b in builds if b.duration_ms is not None]
    avg_duration_sec = (sum(durations) / len(durations) / 1000) if durations else 0.0
    avg_duration_str = f"{avg_duration_sec:.1f}s"
    
    contracts = db.query(Contract).filter(Contract.user_id == user.id).all()
    fixed_contracts = [c for c in contracts if c.status == "fixed"]
    resolution_rate = (len(fixed_contracts) / len(contracts) * 100) if contracts else 0.0
    resolution_rate_str = f"{resolution_rate:.1f}%"

    def get_naive(dt):
        if dt is None:
            return datetime.min
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    activities = []
    
    user_repos = db.query(Repository).filter(Repository.user_id == user.id).order_by(Repository.created_at.desc()).limit(10).all()
    for r in user_repos:
        activities.append({
            "title": "New Repository tracked",
            "desc": f"Connected repository {r.full_name} to monitoring",
            "time": r.created_at.isoformat(),
            "type": "repo_add",
            "timestamp": r.created_at
        })
        
    user_builds = db.query(Build).filter(Build.user_id == user.id).order_by(Build.created_at.desc()).limit(10).all()
    for b in user_builds:
        repo_name = r.full_name if (r := db.query(Repository).filter(Repository.id == b.repo_id).first()) else "repository"
        status_str = "succeeded" if b.status == "success" else "failed"
        activities.append({
            "title": f"CI Pipeline run {status_str}",
            "desc": f"Build '{b.id[:8]}' on repository {repo_name} {status_str} ({b.commit_title[:50]})",
            "time": b.created_at.isoformat(),
            "type": "ci_pass" if b.status == "success" else "ci_fail",
            "timestamp": b.created_at
        })
        
    user_contracts = db.query(Contract).filter(Contract.user_id == user.id).order_by(Contract.created_at.desc()).limit(10).all()
    for c in user_contracts:
        is_comment = c.trigger_event in ("issue_comment", "pull_request_review_comment")
        activities.append({
            "title": "PR comment trigger parsed" if is_comment else "GitHub hook processed",
            "desc": f"Comment trigger received on branch {c.source_branch} on repo {c.repo_id}" if is_comment else f"Push event tracked on branch {c.source_branch} on repo {c.repo_id}",
            "time": c.created_at.isoformat(),
            "type": "webhook",
            "timestamp": c.created_at
        })
        
        if c.status in ("fixed", "failed") and c.completed_at:
            fix_time = c.completed_at
            if c.status == "fixed":
                activities.append({
                    "title": "Automated suggestions posted" if is_comment else "Automated Fix PR Opened",
                    "desc": f"Verified code suggestions posted on Pull Request #{c.pr_number or ''} for {c.repo_id}" if is_comment else f"Pull Request #{c.pr_number or ''} created: 'Automated Code Fix: Agent47 Resolution' on {c.repo_id}",
                    "time": fix_time.isoformat(),
                    "type": "fix",
                    "timestamp": fix_time
                })
            else:
                activities.append({
                    "title": "AI Fix failed",
                    "desc": f"Failed to resolve comments on PR #{c.pr_number or ''} of {c.repo_id}" if is_comment else f"Failed to fix CI failure on branch {c.source_branch} of {c.repo_id} after {c.attempts} attempts",
                    "time": fix_time.isoformat(),
                    "type": "fix_fail",
                    "timestamp": fix_time
                })

    activities.sort(key=lambda x: get_naive(x["timestamp"]), reverse=True)
    
    for act in activities:
        act.pop("timestamp", None)
        
    return {
        "stats": [
            {
                "label": "Tracked Repositories",
                "value": repos_count,
                "icon": "GitBranch",
                "color": "text-cyan-400 bg-cyan-950/40 border border-cyan-900/60"
            },
            {
                "label": "Total Builds Run",
                "value": total_builds,
                "icon": "Box",
                "color": "text-violet-400 bg-violet-950/40 border border-violet-900/60"
            },
            {
                "label": "AI Resolution Rate",
                "value": resolution_rate_str,
                "icon": "CheckCircle2",
                "color": "text-emerald-400 bg-emerald-950/40 border border-emerald-900/60"
            },
            {
                "label": "Avg CI Duration",
                "value": avg_duration_str,
                "icon": "Clock",
                "color": "text-amber-400 bg-amber-950/40 border border-amber-900/60"
            }
        ],
        "activities": activities[:5]
    }
