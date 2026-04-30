"""
LangGraph workflow that connects the Handler and Operative agents,
with sandbox setup and PR creation nodes.
"""

import logging
import time
import os

from langgraph.graph import StateGraph, END

from agent47.state import ContractState
from agent47.agents.handler import handler_agent
from agent47.agents.operative import operative_agent
from agent47.sandbox.tools import sandbox
from agent47.utils.docker_utils import detect_base_image

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
API_MAX_RETRIES = 6
API_BASE_DELAY = 10  # seconds


def _invoke_with_retry(agent, input_data, agent_name: str, max_retries=API_MAX_RETRIES):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return agent.invoke(input_data)
        except (ValueError, Exception) as exc:
            exc_str = str(exc)
            is_transient = any(code in exc_str for code in (
                "504", "502", "503", "aborted", "timed out", "timeout",
                "RESOURCE_EXHAUSTED", "tool_use_failed"
            ))
            if not is_transient or attempt == max_retries:
                raise
            delay = API_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "%s agent API error (attempt %d/%d), retrying in %ds: %s",
                agent_name, attempt, max_retries, delay, exc_str[:200],
            )
            last_exc = exc
            time.sleep(delay)
    raise last_exc


# --- Nodes ---

def setup_sandbox_node(state: ContractState):
    workspace = state.get("workspace_dir", "")

    import subprocess
    import time
    import uuid

    railpack_image_name = None

    if workspace:
        abs_workspace = os.path.abspath(workspace)
        # Use uuid, not timestamp — timestamp collides if two runs start in the same second
        image_name = f"sandbox_img_{uuid.uuid4().hex}"
        logger.info("Building sandbox image with Railpack: %s from %s", image_name, abs_workspace)
        try:
            # subprocess.run(
            #     ["railpack", "build", "--name", image_name, abs_workspace],
            #     check=True,
            #     capture_output=True,
            #     text=True,
            # )
            # sandbox.image = image_name
            # railpack_image_name = image_name
             
            sandbox.image = detect_base_image(abs_workspace)
            railpack_image_name = None 
        except subprocess.CalledProcessError as e:
            logger.warning("Railpack build failed: %s. Falling back to heuristic detection.", e.stderr)
            sandbox.image = detect_base_image(abs_workspace)
        except FileNotFoundError:
            logger.warning("Railpack CLI not found. Falling back to heuristic detection.")
            sandbox.image = detect_base_image(abs_workspace)
    else:
        sandbox.image = "ubuntu:22.04"

    sandbox.start()

    if workspace:
        sandbox.execute_command("mkdir -p /workspace")
        sandbox.copy_repo_to_container(abs_workspace, "/workspace")

    # Pass the image name through state so teardown can clean it up
    return {"repo_path": "/workspace", "railpack_image_name": railpack_image_name}


def handler_node(state: ContractState):
    """The Handler analyses the bug report and identifies relevant files."""
    error_msg = state.get("error_message", "")
    bug = state.get("bug_description", "") or error_msg
    local_repo = state.get("workspace_dir", "")

    result = _invoke_with_retry(
        handler_agent,
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Analyze this bug in repo at {local_repo}: {bug}\n"
                        f"Note: Use absolute paths when calling read_file by joining the repo path with the relative paths."
                    ),
                }
            ]
        },
        agent_name="Handler",
    )

    response = result.get("structured_response")
    if response is None:
        last_msg = result.get("messages", [])[-1] if result.get("messages") else None
        logger.error(
            "Handler agent did not return a structured response. "
            "Last message: %s", last_msg
        )
        raise RuntimeError(
            "Handler failed to produce a structured analysis. "
            "The model may not support structured output - check model config."
        )
    return {
        "relevant_files": response.relevant_files,
    }


def operative_node(state: ContractState):
    """The Operative reads, fixes, and verifies the bug inside the sandbox."""
    error_msg = state.get("error_message", "")
    bug = state.get("bug_description", "") or error_msg
    relevant_files = state.get("relevant_files", [])
    attempt = state.get("attempt_count", 0) + 1
    previous_output = state.get("test_output", "")

    briefing_parts = [
        f"## Contract (Attempt {attempt}/{MAX_ATTEMPTS})",
        f"**Bug:** {bug}",
        f"**Relevant files:** {', '.join(relevant_files)}",
    ]
    if previous_output:
        briefing_parts.append(
            f"**Previous test output (fix failed):**\n```\n"
            f"{previous_output}\n```"
        )

    briefing = "\n\n".join(briefing_parts)

    result = _invoke_with_retry(
        operative_agent,
        {"messages": [{"role": "user", "content": briefing}]},
        agent_name="Operative",
    )

    response = result.get("structured_response")
    if response is None:
        last_msg = result.get("messages", [])[-1] if result.get("messages") else None
        logger.error(
            "Operative agent did not return a structured response. "
            "Last message: %s", last_msg
        )
        raise RuntimeError(
            "Operative failed to produce a structured report. "
            "The model may not support structured output - check model config."
        )
    return {
        "test_output": response.test_output,
        "is_resolved": response.status == "fixed",
        "attempt_count": attempt,
    }


def sync_from_sandbox_node(state: ContractState):
    """Copy modified files from sandbox back to the local workspace.

    This MUST run before teardown so the local clone reflects
    whatever the Operative changed inside the container.
    """
    workspace = state.get("workspace_dir", "")
    if workspace and state.get("is_resolved"):
        sandbox.copy_repo_from_container("/workspace", workspace)
    return {}


def teardown_sandbox_node(state: ContractState):
    """Stop and clean up the Docker sandbox."""
    sandbox.stop()

    railpack_image_name = state.get("railpack_image_name")
    if railpack_image_name:
        try:
            import docker
            client = docker.from_env()
            client.images.remove(railpack_image_name, force=True)
            logger.info("Removed Railpack sandbox image %s", railpack_image_name)
        except Exception as e:
            logger.warning("Could not remove Railpack sandbox image %s: %s", railpack_image_name, e)

    return {}


def should_retry(state: ContractState) -> str:
    """Decide whether the Operative should retry or we're done."""
    if state.get("is_resolved"):
        return "done"
    if state.get("attempt_count", 0) >= MAX_ATTEMPTS:
        return "done"
    return "retry"


# --- Build the graph ---

graph = StateGraph(ContractState)

graph.add_node("setup_sandbox", setup_sandbox_node)
graph.add_node("handler", handler_node)
graph.add_node("operative", operative_node)
graph.add_node("sync_from_sandbox", sync_from_sandbox_node)
graph.add_node("teardown_sandbox", teardown_sandbox_node)

graph.set_entry_point("setup_sandbox")
graph.add_edge("setup_sandbox", "handler")
graph.add_edge("handler", "operative")
graph.add_conditional_edges(
    "operative",
    should_retry,
    {"retry": "operative", "done": "sync_from_sandbox"},
)
graph.add_edge("sync_from_sandbox", "teardown_sandbox")
graph.add_edge("teardown_sandbox", END)

workflow = graph.compile()
