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

    # The repo path to operate on
    repo_path: str

    # The Handler's analysis of which files are relevant
    relevant_files: list[str]

    # Test results from the Verifier
    test_output: str

    # Whether the fix was successful
    is_resolved: bool

    # How many fix attempts the Operative has made (to prevent infinite loops)
    attempt_count: int
