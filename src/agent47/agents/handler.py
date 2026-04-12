"""
The Handler Agent (Diana).
Analyzes the user's bug report / contract and identifies
which files in the repo are relevant to the issue.
"""

from typing import Literal

from pydantic import BaseModel
from langchain.agents import create_agent
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy
from langgraph.checkpoint.memory import InMemorySaver

from agent47.config.config import basic_model


# --- Structured Output ---

class HandlerResponse(BaseModel):
    """The Handler's structured analysis of the bug contract."""
    issue_summary: str
    relevant_files: list[str]
    suggested_fix_approach: str
    severity: Literal["low", "medium", "high", "critical"]


# --- Tools ---

@tool
def list_repo_files(repo_path: str) -> str:
    """List all files in the target repository to help identify relevant ones."""
    import os
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in filenames:
            rel_path = os.path.relpath(os.path.join(root, f), repo_path)
            files.append(rel_path)
    return "\n".join(files) if files else "No files found."


@tool
def read_file(filepath: str) -> str:
    """Read the contents of a file to analyze it for bugs."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File '{filepath}' not found."
    except UnicodeDecodeError:
        return f"Error: File '{filepath}' is not a text file."


# --- System Prompt ---

HANDLER_SYSTEM_PROMPT = """You are Diana Burnwood — the Handler for Agent 47.

Your job is to analyze a bug report (the "Contract") and prepare a briefing
for Agent 47 (the Operative) so he can execute the fix with surgical precision.

You have access to these tools:
- list_repo_files: Use this to see all files in the target repository.
- read_file: Use this to read a specific file and analyze it for the reported bug.

Your task:
1. Read the bug description carefully.
2. Use list_repo_files to understand the project structure.
3. Use read_file to inspect suspicious files.
4. Return a structured analysis with:
   - A concise summary of the issue
   - The list of files relevant to the bug
   - A suggested approach for fixing it
   - The severity level (low / medium / high / critical)

Be precise. Agent 47 does not tolerate sloppy intel."""


# --- Agent Definition ---

checkpointer = InMemorySaver()

handler_agent = create_agent(
    model=basic_model,
    system_prompt=HANDLER_SYSTEM_PROMPT,
    tools=[list_repo_files, read_file],
    response_format=ToolStrategy(HandlerResponse),
    checkpointer=checkpointer
)
