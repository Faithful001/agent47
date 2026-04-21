"""
LangGraph workflow that connects the Handler and Operative agents,
with sandbox setup and PR creation nodes.
"""

import logging
import time

from langgraph.graph import StateGraph, END

from agent47.state import ContractState
from agent47.agents.handler import handler_agent
from agent47.agents.operative import operative_agent
from agent47.sandbox.tools import sandbox

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
API_MAX_RETRIES = 6
API_BASE_DELAY = 10  # seconds


def _invoke_with_retry(agent, input_data, agent_name: str, max_retries=API_MAX_RETRIES):
    """Invoke an agent with retry + exponential backoff for transient API errors.

    Retries on: 504 timeouts, 429 rate limits, 502/503 gateway errors,
    and connection-level failures from flaky providers.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return agent.invoke(input_data)
        except (ValueError, Exception) as exc:
            exc_str = str(exc)
            is_transient = any(code in exc_str for code in ("504", "502", "503", "429", "400", "aborted", "timed out", "timeout", "RESOURCE_EXHAUSTED", "tool_use_failed"))
            if not is_transient or attempt == max_retries:
                raise
            delay = API_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "%s agent API error (attempt %d/%d), retrying in %ds: %s",
                agent_name, attempt, max_retries, delay, exc_str[:200],
            )
            last_exc = exc
            time.sleep(delay)
    raise last_exc  # should not reach here, but just in case


# --- Nodes ---

def setup_sandbox_node(state: ContractState):
    """Start the Docker sandbox and copy the cloned repo into it."""
    workspace = state.get("workspace_dir", "")

    sandbox.start()

    if workspace:
        sandbox.execute_command("mkdir -p /workspace")
        sandbox.copy_repo_to_container(workspace, "/workspace")

    return {"repo_path": "/workspace"}


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
