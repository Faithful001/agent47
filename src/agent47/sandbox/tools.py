"""
Sandbox tools exposed to the Operative agent.

Each tool wraps the Docker sandbox so Agent 47 can read, write,
and execute commands inside the isolated container.
"""

from langchain.tools import tool

from agent47.sandbox.docker_client import Sandbox

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
        output = sandbox.execute_command(command)
        MAX_CHARS = 3000
        if len(output) > MAX_CHARS:
            return f"{output[:500]}\n\n...[TRUNCATED {len(output) - MAX_CHARS} chars]...\n\n{output[-2500:]}"
        return output
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
def replace_in_sandbox_file(filepath: str, old_content: str, new_content: str) -> str:
    """Replace a specific string in a file in the Docker sandbox.

    Use this instead of modify_sandbox_file when making small, targeted fixes.
    Provide the EXACT string to find (old_content) and what to replace it with (new_content).
    The replacement is literal — it will fail if old_content is not found exactly.
    Always use absolute paths inside the container.
    """
    try:
        current = sandbox.read_file_from_container(filepath)
        if old_content not in current:
            return f"Error: Could not find the target string in {filepath}. Read the file first and verify the exact content."
        updated = current.replace(old_content, new_content, 1)
        return sandbox.write_file_in_container(filepath, updated)
    except RuntimeError as exc:
        return f"Sandbox error: {exc}"