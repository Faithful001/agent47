"""
Contracts service — pipeline orchestration, DB operations, and PR creation.
"""

import logging
from datetime import datetime, timezone

from github import Github
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.contracts.models import Contract
from src.domain.user.model import User
from src.git.service import clone_repo, create_fix_branch, commit_and_push
from src.agents.graph import workflow

logger = logging.getLogger(__name__)


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
        contract.status = "in_progress"
        repo_name = contract.repo_id.split("/")[-1] if "/" in contract.repo_id else contract.repo_id
        fix_branch = f"{repo_name}-agent47"
        contract.fix_branch = fix_branch
        self.db.commit()

        try:
            # Step 1: Clone
            logger.info(
                "Cloning %s branch '%s'...",
                repo_url, contract.source_branch,
            )
            workspace_dir = clone_repo(
                repo_url=repo_url,
                branch=contract.source_branch,
                token=user.github_access_token,
            )

            # Step 2: Run the LangGraph workflow
            logger.info("Running Agent47 pipeline...")
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
            })

            contract.attempts = result.get("attempt_count", 0)
            is_resolved = result.get("is_resolved", False)

            if is_resolved:
                # Step 3: Branch, commit, push, PR
                logger.info("Fix successful! Creating branch and PR...")

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
            else:
                contract.status = "failed"
                contract.fix_summary = (
                    f"Failed after {contract.attempts} attempts. "
                    f"Last output: {result.get('test_output', 'N/A')}"
                )

        except Exception as exc:
            logger.exception("Pipeline failed: %s", exc)
            contract.status = "failed"
            contract.fix_summary = f"Pipeline error: {exc}"

        contract.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(contract)
        return contract
