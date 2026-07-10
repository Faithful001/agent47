import json
from typing import Literal
from pydantic import BaseModel
from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from agent47.config.config import basic_model


class HandlerResponse(BaseModel):
    issue_summary: str
    relevant_files: list[str]
    suggested_fix_approach: str
    severity: Literal["low", "medium", "high", "critical"]


@tool
def list_repo_files(repo_path: str) -> str:
    """List all files in the target repository to help identify relevant ones."""
    import os
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in filenames:
            rel_path = os.path.relpath(os.path.join(root, f), repo_path)
            rel_path = rel_path.replace(os.sep, "/")
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


HANDLER_SYSTEM_PROMPT = """You are Diana Burnwood — the Handler for Agent 47.

Your job is to analyze a bug report and identify which files are relevant.

You will be given a bug description and a file listing of the repo.
If needed, file contents will also be provided.

Output a raw JSON object with exactly these fields (no markdown, no code fences):
{
  "issue_summary": "concise description of the bug",
  "relevant_files": ["path/to/file1"],
  "suggested_fix_approach": "how to fix it",
  "severity": "low" | "medium" | "high" | "critical"
}"""


def handler_agent(repo_path: str, bug: str, model=None) -> HandlerResponse:
    """
    Direct LLM call — no agent loop needed.
    Lists repo files, optionally reads suspicious ones, returns structured analysis.
    """
    # Step 1: get file listing
    file_listing = list_repo_files.func(repo_path)

    # Step 2: ask the model to identify relevant files and the fix approach
    messages = [
        SystemMessage(content=HANDLER_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Bug report:\n{bug}\n\n"
            f"Repo files:\n{file_listing}\n\n"
            f"Based on the bug report and file listing, identify the relevant files "
            f"and suggest a fix approach. If the relevant file is obvious from the "
            f"error message, you do not need to read it."
        )),
    ]

    active_model = model or basic_model
    response = active_model.invoke(messages)
    content = response.content.strip()

    # Strip markdown fences if present
    if content.startswith("```"):
        lines = content.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    parsed = json.loads(content)
    return HandlerResponse(**parsed)