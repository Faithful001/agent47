import os
import shutil
import stat

os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")
from git import Repo

from agent47.config.config import WORKSPACE_BASE_DIR


def _remove_readonly(func, path, _):
    """Clear the readonly bit and reattempt the removal."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


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

    if os.path.exists(os.path.join(workspace_dir, ".git")):
        pull_repo(workspace_dir, authed_url, branch)
    else:
        if os.path.exists(workspace_dir):
            shutil.rmtree(workspace_dir, onexc=_remove_readonly)
            
        Repo.clone_from(
            url=authed_url,
            to_path=workspace_dir,
            branch=branch,
        )
    return workspace_dir


def pull_repo(repo_dir: str, authed_url: str, branch: str) -> None:
    """Fetch and reset an existing locally cloned repo to match remote."""
    repo = Repo(repo_dir)

    # Ensure authenticated URL is set
    repo.remotes.origin.set_url(authed_url)
    repo.git.fetch("origin")
    
    # Clean up any local changes or untracked files before checkout
    repo.git.reset("--hard")
    repo.git.clean("-fdx")
    
    repo.git.checkout(branch)
    repo.git.reset("--hard", f"origin/{branch}")


def create_fix_branch(repo_dir: str, branch_name: str) -> None:
    """Create and check out a new branch for the fix.

    Flowchart step: 'Create a new branch — {repo_name}-agent47'.
    Uses -B to create or reset the branch to current HEAD, preserving
    any uncommitted working-tree changes.
    """
    repo = Repo(repo_dir)
    repo.git.checkout("-B", branch_name)


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


def parse_git_diff_to_suggestions(diff_text: str) -> list[dict]:
    """Parse git diff output into a list of inline GitHub suggestions."""
    import re
    suggestions = []
    current_file = None
    
    # Split by diff sections
    files_diffs = diff_text.split("diff --git ")
    for file_diff in files_diffs:
        if not file_diff.strip():
            continue
        
        lines = file_diff.splitlines()
        # Find file path from the 'diff --git a/path b/path' line
        match_file = re.search(r" b/(.+)$", lines[0])
        if not match_file:
            continue
        current_file = match_file.group(1).strip()
        
        hunk_headers = []
        hunk_indices = []
        for idx, line in enumerate(lines):
            if line.startswith("@@"):
                hunk_headers.append(line)
                hunk_indices.append(idx)
        
        for h_idx in range(len(hunk_indices)):
            header = hunk_headers[h_idx]
            start_line_idx = hunk_indices[h_idx]
            end_line_idx = hunk_indices[h_idx + 1] if h_idx + 1 < len(hunk_indices) else len(lines)
            
            # Parse header: @@ -start,len +start,len @@
            hunk_match = re.match(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", header)
            if not hunk_match:
                continue
                
            orig_start = int(hunk_match.group(1))
            orig_len = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            
            hunk_lines = lines[start_line_idx + 1:end_line_idx]
            
            replacement_lines = []
            in_change = False
            change_start_offset = 0
            original_offset = 0
            
            for hl in hunk_lines:
                if hl.startswith("-"):
                    if not in_change:
                        in_change = True
                        change_start_offset = original_offset
                    original_offset += 1
                elif hl.startswith("+"):
                    if not in_change:
                        in_change = True
                        change_start_offset = original_offset
                    replacement_lines.append(hl[1:])
                elif hl.startswith(" "):
                    if in_change:
                        s_line_start = orig_start + change_start_offset
                        s_line_end = orig_start + original_offset - 1
                        
                        comment_body = f"```suggestion\n" + "\n".join(replacement_lines) + "\n```"
                        comment = {
                            "path": current_file,
                            "body": comment_body,
                        }
                        
                        if s_line_start < s_line_end:
                            comment["start_line"] = s_line_start
                            comment["line"] = s_line_end
                            comment["side"] = "RIGHT"
                            comment["start_side"] = "RIGHT"
                        else:
                            comment["line"] = s_line_start
                            comment["side"] = "RIGHT"
                            
                        suggestions.append(comment)
                        in_change = False
                        replacement_lines = []
                    original_offset += 1
            
            if in_change:
                s_line_start = orig_start + change_start_offset
                s_line_end = orig_start + original_offset - 1
                comment_body = f"```suggestion\n" + "\n".join(replacement_lines) + "\n```"
                comment = {
                    "path": current_file,
                    "body": comment_body,
                }
                if s_line_start < s_line_end:
                    comment["start_line"] = s_line_start
                    comment["line"] = s_line_end
                    comment["side"] = "RIGHT"
                    comment["start_side"] = "RIGHT"
                else:
                    comment["line"] = s_line_start
                    comment["side"] = "RIGHT"
                suggestions.append(comment)
                
    return suggestions


def get_git_diff_suggestions(repo_dir: str) -> list[dict]:
    """Stage all changes, retrieve the git diff against HEAD, and return review suggestions."""
    repo = Repo(repo_dir)
    try:
        repo.git.add(A=True)
        # diff HEAD to capture staged changes as well
        diff_text = repo.git.diff("HEAD", M=True)
        return parse_git_diff_to_suggestions(diff_text)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to generate git diff suggestions: %s", e)
        return []
