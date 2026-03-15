"""
Auth service — GitHub OAuth flow.
"""

import httpx
from github import Github

from src.config.config import (
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_REDIRECT_URI,
)

class AuthService:

    @staticmethod
    def get_oauth_login_url() -> str:
        """Return the GitHub OAuth authorization URL the frontend should
        redirect the user to."""
        return (
            "https://github.com/login/oauth/authorize"
            f"?client_id={GITHUB_CLIENT_ID}"
            f"&redirect_uri={GITHUB_REDIRECT_URI}"
            "&scope=repo,read:org"
        )

    @staticmethod
    async def exchange_code_for_token(code: str) -> str:
        """Exchange a temporary OAuth code for a GitHub access token."""
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
        return {
            "login": user.login,
            "id": user.id,
            "avatar_url": user.avatar_url,
            "email": user.email or "",
        }
