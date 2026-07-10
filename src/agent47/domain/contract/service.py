import logging
from datetime import datetime, timezone

from github import Github
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent47.domain.contract.model import Contract
from agent47.domain.user.model import User
from agent47.domain.build.model import Build
from agent47.infra.git.service import clone_repo, create_fix_branch, commit_and_push
from agent47.agents.graph import workflow


logger = logging.getLogger(__name__)


def _get_valid_lines_from_patch(patch_text: str) -> set[int]:
    import re
    if not patch_text:
        return set()
    valid_lines = set()
    hunk_header_re = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")
    
    current_line = 0
    lines = patch_text.splitlines()
    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(3))
        elif line.startswith("+") or line.startswith(" "):
            valid_lines.add(current_line)
            current_line += 1
        elif line.startswith("-"):
            valid_lines.add(current_line)
    return valid_lines


class ContractService:
    """Handles contract DB operations and pipeline orchestration."""

    def __init__(self, db: Session):
        self.db = db

    # --- Database ---

    def create_contract(self, **kwargs) -> Contract:
        """Create and persist a new contract."""
        contract = Contract(**kwargs)
        self.db.add(contract)
        self.db.commit()
        self.db.refresh(contract)
        return contract

    def get_contract(self, contract_id: str) -> Contract | None:
        """Get a contract by ID."""
        return self.db.get(Contract, contract_id)

    def list_contracts(self, user_id: str) -> list[Contract]:
        """List all contracts for a user."""
        stmt = select(Contract).where(Contract.user_id == user_id)
        return list(self.db.execute(stmt).scalars().all())

    def update_contract(self, contract: Contract) -> Contract:
        """Persist changes to a contract."""
        self.db.commit()
        self.db.refresh(contract)
        return contract

    # --- GitHub PR ---

    @staticmethod
    def _create_pull_request(
        token: str,
        repo_full_name: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> str:
        """Open a pull request and return the PR URL."""
        gh = Github(token)
        repo = gh.get_repo(repo_full_name)
        pr = repo.create_pull(title=title, body=body, head=head, base=base)
        return pr.html_url

    def _generate_review_body(self, contract: Contract, test_output: str) -> str:
        """Generate a structured, polished PR review body with an AI walkthrough and Mermaid diagram."""
        from langchain_core.messages import SystemMessage, HumanMessage
        from agent47.config.config import get_user_models
        from agent47.domain.apikey.service import ApiKeyService
        
        user_api_key = ApiKeyService(self.db).get_user_api_key(contract.user_id)
        basic_model, _ = get_user_models(user_api_key=user_api_key, user_id=contract.user_id)
        
        system_prompt = (
            "You are Agent47. Synthesize a concise explanation of the bug fix you just applied. "
            "Explain the root cause and the fix in developer-friendly terms. "
            "Output your response in Markdown. Include a brief section with a Mermaid.js diagram illustrating the bug and the fix. "
            "Do NOT include standard markdown backticks around the mermaid block; use '```mermaid' tags."
        )
        
        user_message = (
            f"Bug Description:\n{contract.error_message}\n\n"
            f"Verification Test Output:\n{test_output[-1500:]}\n"
        )
        
        try:
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_message)]
            res = basic_model.invoke(messages)
            ai_explanation = res.content.strip()
        except Exception as e:
            logger.warning("Failed to generate AI review body: %s", e)
            ai_explanation = (
                f"### Root Cause & Fix Details\n\n"
                f"Agent47 resolved the build failure by applying verified patches.\n\n"
                f"**Verification Results:**\n```\n{test_output[-500:]}\n```"
            )
            
        body = (
            f"## 🎯 Agent47 Verified Fix Proposal\n\n"
            f"I have successfully tested and verified a fix for this build failure inside a secure Docker sandbox.\n\n"
            f"{ai_explanation}\n\n"
            f"---\n"
            f"*Resolution Attempts: {contract.attempts}*"
        )
        return body

    # --- Pipeline ---

    def run_contract(
        self,
        contract: Contract,
        user: User,
        repo_url: str,
    ) -> Contract:
        """Execute the full Agent47 pipeline for a single bug contract.

        Flow:
            1. Clone the repo branch
            2. Run the LangGraph workflow (sandbox → handler → operative loop)
            3. If fixed: create fix branch, commit, push, open PR
            4. Update the contract in the database
        """
        from agent47.domain.apikey.model import ApiKey
        active_key = self.db.query(ApiKey).filter(ApiKey.user_id == user.id, ApiKey.is_active == True).first()
        if not active_key:
            contract.status = "failed"
            contract.error_message = "No active API Key configured. Please configure and select an active API Key in settings."
            self._publish_contract_update(contract)
            self.db.commit()
            logger.error("Failed to execute contract: No active API Key found.")
            return contract

        contract.status = "in_progress"
        
        repo_name = contract.repo_id.split("/")[-1] if "/" in contract.repo_id else contract.repo_id
        fix_branch = f"{repo_name}-agent47"
        contract.fix_branch = fix_branch

        self._publish_contract_update(contract)
        self.db.commit()

        try:
            # Step 1: Clone
            logger.info(
                "Cloning %s branch '%s'...",
                repo_url, contract.source_branch,
            )
            clean_url = f"https://github.com/{contract.repo_id}.git"
            workspace_dir = clone_repo(
                # repo_url=repo_url,
                repo_url=clean_url,
                branch=contract.source_branch,
                token=user.github_access_token,
            )

            # Step 2: Run the LangGraph workflow
            logger.info("Running Agent47 pipeline...")
            from agent47.domain.apikey.service import ApiKeyService
            user_api_key = ApiKeyService(self.db).get_user_api_key(user.id)
            
            result = workflow.invoke({
                "messages": [],
                "bug_description": contract.error_message,
                "repo_path": "/workspace",
                "repo_full_name": contract.repo_id,
                "source_branch": contract.source_branch,
                "fix_branch": fix_branch,
                "workspace_dir": workspace_dir,
                "error_message": contract.error_message,
                "relevant_files": [],
                "test_output": "",
                "is_resolved": False,
                "attempt_count": 0,
                "user_api_key": user_api_key,
                "user_id": user.id,
                "custom_rules": [],
                "custom_test_command": None,
            })

            contract.attempts = result.get("attempt_count", 0)
            is_resolved = result.get("is_resolved", False)

            if is_resolved:
                logger.info("Fix successful! Preparing resolution...")

                # If there's an existing PR associated, post review comments directly
                if contract.pr_number:
                    logger.info("Existing PR found (PR #%d). Generating inline suggestions...", contract.pr_number)
                    from agent47.infra.git.service import get_git_diff_suggestions
                    
                    suggestions = get_git_diff_suggestions(workspace_dir)
                    if suggestions:
                        try:
                            # Post inline review comments on the PR
                            gh = Github(user.github_access_token)
                            repo = gh.get_repo(contract.repo_id)
                            pr = repo.get_pull(contract.pr_number)
                            
                            # Filter suggestions to only include files and line numbers inside the PR's diff hunks
                            pr_files = {f.filename: f for f in pr.get_files()}
                            filtered = []
                            for s in suggestions:
                                file_path = s.get("path")
                                if file_path in pr_files:
                                    pr_file = pr_files[file_path]
                                    if pr_file.patch:
                                        valid_lines = _get_valid_lines_from_patch(pr_file.patch)
                                        if s.get("line") in valid_lines:
                                            filtered.append(s)
                                        else:
                                            logger.info("Filtered suggestion on %s:%d - line not in PR diff", file_path, s.get("line"))
                                    else:
                                        # No patch content, keep it just in case
                                        filtered.append(s)
                            
                            pr_files_set = set(pr_files.keys())
                            
                            if not filtered:
                                logger.info(
                                    "All %d suggestion(s) are outside the PR diff (PR files: %s, suggestion files: %s). Posting summary comment instead.",
                                    len(suggestions), pr_files_set, {s.get("path") for s in suggestions}
                                )
                                # Post a summary comment with the changes instead
                                from git import Repo as GitRepo
                                diff_repo = GitRepo(workspace_dir)
                                diff_text = diff_repo.git.diff("HEAD", M=True)
                                pr.create_issue_comment(
                                    f"**Agent47 Fix Complete**\n\n"
                                    f"I found a fix but the modified files are outside this PR's changeset, "
                                    f"so I can't post inline suggestions. Here's the diff:\n\n"
                                    f"```diff\n{diff_text[:3000]}\n```\n\n"
                                    f"*Resolved in {contract.attempts} attempt(s) - Contract `{contract.id}`*"
                                )
                                contract.pr_url = pr.html_url
                            else:
                                if len(filtered) < len(suggestions):
                                    logger.info("Filtered %d/%d suggestions to match PR diff", len(filtered), len(suggestions))
                                
                                # Build the review body (walkthrough + Mermaid diagram)
                                review_body = self._generate_review_body(contract, result.get("test_output", ""))
                                
                                # Get the head commit of the PR to comment on
                                pr_commit = repo.get_commit(contract.commit_sha)
                                
                                pr.create_review(
                                    commit=pr_commit,
                                    body=review_body,
                                    event="COMMENT",
                                    comments=filtered,
                                )
                                logger.info("Successfully posted review with %d suggestions to PR #%d", len(filtered), contract.pr_number)
                                contract.pr_url = pr.html_url
                                # Post completion comment
                                try:
                                    pr.create_issue_comment(
                                        f"**Agent47 Fix Complete**\n\n"
                                        f"I've posted **{len(filtered)} inline suggestion(s)** on this PR. "
                                        f"Head over to the **Files Changed** tab to review and apply them with one click.\n\n"
                                        f"*Resolved in {contract.attempts} attempt(s) - Contract `{contract.id}`*"
                                    )
                                except Exception:
                                    pass
                        except Exception as pr_exc:
                            logger.error("Failed to post inline review comments: %s", pr_exc)
                            # Fallback: comment on the PR directly with a summary if inline review fails
                            try:
                                pr.create_issue_comment(
                                    f"### Agent47 Fix Verification\n\n"
                                    f"I successfully verified a fix inside the sandbox, but failed to post inline suggestions.\n\n"
                                    f"**Fix Summary:**\n```\n{result.get('test_output', '')[-500:]}\n```"
                                )
                                contract.pr_url = pr.html_url
                            except Exception:
                                pass
                    else:
                        logger.info("No modifications detected in git diff - skipping PR comments.")
                    
                    contract.status = "fixed"
                    contract.fix_summary = result.get("test_output", "")
                    self._publish_contract_update(contract)
                else:
                    logger.info("No existing PR number. Creating branch and new PR...")
                    create_fix_branch(workspace_dir, fix_branch)
                    commit_and_push(
                        repo_dir=workspace_dir,
                        message=(
                            f"fix: Agent47 automated fix\n\n"
                            f"{contract.error_message}"
                        ),
                        token=user.github_access_token,
                    )

                    pr_url = self._create_pull_request(
                        token=user.github_access_token,
                        repo_full_name=contract.repo_id,
                        head=fix_branch,
                        base="main",
                        title=f"Automated Code Fix: Agent47 Resolution",
                        body=(
                            "## Automated Fix by Agent47\n\n"
                            "This pull request contains an automated fix for a recent build failure or merge conflict.\n\n"
                            f"**Error Addressed:**\n```\n{contract.error_message}\n```\n\n"
                            f"**Resolution Attempts:** {contract.attempts}\n\n"
                            "Please review the changes carefully before merging."
                        ),
                    )
                    contract.pr_url = pr_url
                    contract.status = "fixed"
                    contract.fix_summary = result.get("test_output", "")
                    self._publish_contract_update(contract)
            else:
                contract.status = "failed"
                contract.fix_summary = (
                    f"Failed after {contract.attempts} attempts. "
                    f"Last output: {result.get('test_output', 'N/A')}"
                )
                self._publish_contract_update(contract)

                # Post failure comment on the PR if one exists
                if contract.pr_number:
                    try:
                        gh = Github(user.github_access_token)
                        repo = gh.get_repo(contract.repo_id)
                        pr = repo.get_pull(contract.pr_number)
                        last_output = result.get('test_output', 'N/A')[-500:]
                        pr.create_issue_comment(
                            f"**Agent47 Could Not Resolve This**\n\n"
                            f"I attempted to fix the issue **{contract.attempts} time(s)** inside a secure Docker sandbox, "
                            f"but was unable to produce a passing solution.\n\n"
                            f"**Last Output:**\n```\n{last_output}\n```\n\n"
                            f"*Contract `{contract.id}`*"
                        )
                    except Exception:
                        pass

        except Exception as exc:
            logger.exception("Pipeline failed: %s", exc)
            contract.status = "failed"
            contract.fix_summary = f"Pipeline error: {exc}"

        contract.completed_at = datetime.now(timezone.utc)
        self._publish_contract_update(contract)

        try:
            build = self.db.query(Build).filter(
                Build.commit_sha == contract.commit_sha,
                Build.user_id == user.id
            ).order_by(Build.created_at.desc()).first()
            if build:
                build.fix_summary = contract.fix_summary
                issues = []
                if contract.error_message:
                    lines = contract.error_message.splitlines()
                    title = "CI Build/Test Failure"
                    desc = contract.error_message[:200]
                    if len(lines) > 0:
                        err_line = next((l for l in lines if "error" in l.lower() or "fail" in l.lower()), lines[0])
                        title = err_line.strip()[:100]
                        desc = "\n".join(lines[:5])
                    
                    issues.append({
                        "title": title,
                        "description": desc,
                        "severity": "critical",
                    })
                build.identified_issues = issues
        except Exception as e:
            logger.warning("Could not associate build summary/issues: %s", e)

        self.db.commit()
        self.db.refresh(contract)
        return contract

    def _publish_contract_update(self, contract: Contract):
        import json
        import redis as sync_redis
        from agent47.config.redis import REDIS_URL

        message = {
            "type": "contract_update",
            "contract_id": str(contract.id),
            "repo_id": contract.repo_id,
            "commit_sha": contract.commit_sha,
            "status": contract.status,
            "attempts": contract.attempts,
            "pr_url": contract.pr_url,
            "fix_summary": contract.fix_summary,
            "error_message": contract.error_message,
            "updated_at": contract.updated_at.isoformat() if contract.updated_at else None
        }

        channel = f"contract:user:{contract.user_id}"

        try:
            r = sync_redis.from_url(REDIS_URL, decode_responses=True)
            r.publish(channel, json.dumps(message))
            r.close()
        except Exception as exc:
            logger.warning("Failed to publish contract update via Redis: %s", exc)