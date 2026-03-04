"""
Sandbox tools exposed to the Operative agent.

Each tool wraps the Docker sandbox so Agent 47 can read, write,
and execute commands inside the isolated container.
"""

from langchain.tools import tool

from src.sandbox.docker_client import Sandbox

# A module-level sandbox instance shared across all tools.
# start() must be called before any tool is used (the graph handles this).
sandbox = Sandbox()


@tool
def execute_sandbox_command(command: str) -> str:
    """Run a shell command inside the Docker sandbox and return its output.

    Use this to install dependencies, run tests (e.g. `pytest`),
    or inspect the project structure (`ls`, `find`, etc.).
    """
    try:
        return sandbox.execute_command(command)
    except RuntimeError as exc:
        return f"Sandbox error: {exc}"


@tool
def read_sandbox_file(filepath: str) -> str:
    """Read a file from the Docker sandbox.

    Use this to inspect source code, test files, config files, etc.
    Always use absolute paths inside the container (e.g. `/workspace/src/app.py`).
    """
    try:
        return sandbox.read_file_from_container(filepath)
    except RuntimeError as exc:
        return f"Sandbox error: {exc}"


@tool
def modify_sandbox_file(filepath: str, content: str) -> str:
    """Write content to a file in the Docker sandbox, creating or overwriting it.

    Use this to apply your code fix. Provide the FULL file content —
    this tool overwrites the entire file.
    Always use absolute paths inside the container (e.g. `/workspace/src/app.py`).
    """
    try:
        return sandbox.write_file_in_container(filepath, content)
    except RuntimeError as exc:
        return f"Sandbox error: {exc}"
