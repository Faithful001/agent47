"""
GitHub Webhook Parser — extracts CI failure info from webhook payloads.
"""

import hashlib
import hmac
from dataclasses import dataclass

from agent47.config.config import GITHUB_WEBHOOK_SECRET


@dataclass
class WebhookFailure:
    """Structured data extracted from a CI-failure webhook event."""

    repo_full_name: str
    branch: str
    error_message: str
    commit_sha: str
    pr_number: int | None = None


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """Verify the webhook payload was sent by GitHub using the shared secret."""
    if not GITHUB_WEBHOOK_SECRET:
        return True  # Skip verification if no secret is configured

    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def parse_webhook_event(event_type: str, payload: dict) -> WebhookFailure | None:
    if event_type == "check_suite":
        return _parse_check_suite(payload)
    if event_type == "check_run":
        return _parse_check_run(payload)
    if event_type == "workflow_run":
        return _parse_workflow_run(payload)
    if event_type == "pull_request":
        return _parse_pull_request(payload)
    return None

def _parse_check_suite(payload: dict) -> WebhookFailure | None:
    suite = payload.get("check_suite", {})
    action = payload.get("action")

    if action != "completed":
        return None

    conclusion = suite.get("conclusion")
    if conclusion not in ("failure", "timed_out", "cancelled"):
        return None

    repo = payload.get("repository", {})
    head_branch = suite.get("head_branch", "")
    head_sha = suite.get("head_sha", "")

    # Try to get PR context if available
    prs = suite.get("pull_requests", [])
    pr_number = prs[0].get("number") if prs else None

    # Best effort error message
    error_message = f"Check suite failed ({conclusion})"
    if suite.get("latest_check_runs_count", 0) > 0:
        failed_count = suite.get("failure_check_runs_count", 0)
        error_message += f" — {failed_count} check(s) failed"

    return WebhookFailure(
        repo_full_name=repo.get("full_name", ""),
        branch=head_branch,
        error_message=error_message,
        commit_sha=head_sha,
        pr_number=pr_number,
    )


def _parse_check_run(payload: dict) -> WebhookFailure | None:
    """Extract failure info from a check_run event."""
    check_run = payload.get("check_run", {})
    action = payload.get("action")
    conclusion = check_run.get("conclusion")

    if action != "completed" or conclusion not in ("failure", "timed_out"):
        return None

    repo = payload.get("repository", {})
    head_sha = check_run.get("head_sha", "")

    branch = ""
    prs = check_run.get("pull_requests", [])
    pr_number = None
    if prs:
        branch = prs[0].get("head", {}).get("ref", "")
        pr_number = prs[0].get("number")

    output = check_run.get("output", {})
    error_message = (
        output.get("summary")
        or output.get("title")
        or check_run.get("name", "Check run failed")
    )

    return WebhookFailure(
        repo_full_name=repo.get("full_name", ""),
        branch=branch,
        error_message=error_message,
        commit_sha=head_sha,
        pr_number=pr_number,
    )

def _parse_workflow_run(payload: dict) -> WebhookFailure | None:
    run = payload.get("workflow_run", {})
    action = payload.get("action")

    if action != "completed":
        return None

    conclusion = run.get("conclusion")
    if conclusion not in ("failure", "timed_out", "cancelled"):
        return None

    repo = payload.get("repository", {})
    head_branch = run.get("head_branch", "")
    head_sha = run.get("head_sha", "")

    return WebhookFailure(
        repo_full_name=repo.get("full_name", ""),
        branch=head_branch,
        error_message=f"Workflow '{run.get('name')}' {conclusion}",
        commit_sha=head_sha,
        pr_number=run.get("pull_requests", [{}])[0].get("number"),
    )


def _parse_status(payload: dict) -> WebhookFailure | None:
    """Extract failure info from a commit status event."""
    state = payload.get("state")
    if state not in ("failure", "error"):
        return None

    repo = payload.get("repository", {})
    branches = payload.get("branches", [])
    branch = branches[0].get("name", "") if branches else ""

    return WebhookFailure(
        repo_full_name=repo.get("full_name", ""),
        branch=branch,
        error_message=payload.get("description", "CI status failed"),
        commit_sha=payload.get("sha", ""),
    )


def _parse_pull_request(payload: dict) -> WebhookFailure | None:
    """Extract info from a pull_request event if checks failed."""
    action = payload.get("action")
    if action not in ("opened", "synchronize"):
        return None

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    mergeable_state = pr.get("mergeable_state", "")
    if mergeable_state not in ("dirty", "unstable"):
        return None

    return WebhookFailure(
        repo_full_name=repo.get("full_name", ""),
        branch=pr.get("head", {}).get("ref", ""),
        error_message=f"PR #{pr.get('number')} has failing checks",
        commit_sha=pr.get("head", {}).get("sha", ""),
        pr_number=pr.get("number"),
    )
