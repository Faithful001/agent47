"""
Shared state schema for the Agent47 LangGraph workflow.
"""

from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class ContractState(TypedDict):
    """The state that flows through the entire Agent47 pipeline."""

    # The conversation messages (managed by LangGraph)
    messages: Annotated[list, add_messages]

    # The bug description / contract from the user
    bug_description: str

    # --- Repository context ---

    # The repo path to operate on (inside the sandbox)
    repo_path: str

    # Full repo name on GitHub (e.g. "owner/repo")
    repo_full_name: str

    # The branch the error came from
    source_branch: str

    # The fix branch name (e.g. "{repo}-agent47")
    fix_branch: str

    # Local workspace directory (where the repo is cloned)
    workspace_dir: str

    # CI error message that triggered the contract
    error_message: str

    # --- Handler output ---

    # The Handler's analysis of which files are relevant
    relevant_files: list[str]

    # --- Operative output ---

    # Test results from the Verifier
    test_output: str

    # Whether the fix was successful
    is_resolved: bool

    # How many fix attempts the Operative has made
    attempt_count: int
