"""
Git Service
"""

import os
import shutil

from git import Repo

from src.config.config import WORKSPACE_BASE_DIR


def clone_repo(
    repo_url: str,
    branch: str,
    token: str,
    workspace_name: str | None = None,
) -> str:
    """Clone a GitHub repo branch into a local workspace directory.

    Flowchart step: 'Clone the branch with the error'.
    Returns the absolute path to the cloned repo.
    """
    authed_url = repo_url.replace(
        "https://github.com", f"https://{token}@github.com"
    )

    if workspace_name is None:
        workspace_name = repo_url.rstrip("/").split("/")[-1]

    workspace_dir = os.path.join(WORKSPACE_BASE_DIR, workspace_name)

    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)

    Repo.clone_from(
        url=authed_url,
        to_path=workspace_dir,
        branch=branch,
    )
    return workspace_dir


def create_fix_branch(repo_dir: str, branch_name: str) -> None:
    """Create and check out a new branch for the fix.

    Flowchart step: 'Create a new branch — {repo_name}-agent47'.
    """
    repo = Repo(repo_dir)
    repo.git.checkout("-b", branch_name)


def commit_and_push(
    repo_dir: str,
    message: str,
    token: str,
) -> None:
    """Stage all changes, commit, and push the fix branch."""
    repo = Repo(repo_dir)

    origin = repo.remote("origin")
    original_url = origin.url
    authed_url = original_url.replace(
        "https://github.com", f"https://{token}@github.com"
    )
    origin.set_url(authed_url)

    repo.git.add(A=True)
    repo.index.commit(message)
    repo.git.push("--set-upstream", "origin", repo.active_branch.name)


def get_changed_files(repo_dir: str) -> list[str]:
    """Return a list of files modified in the working tree."""
    repo = Repo(repo_dir)
    changed = [item.a_path for item in repo.index.diff("HEAD")]
    untracked = repo.untracked_files
    return changed + untracked
