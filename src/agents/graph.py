"""
LangGraph workflow that connects the Handler and Operative agents,
with sandbox setup and PR creation nodes.
"""

from langgraph.graph import StateGraph, END

from src.state import ContractState
from src.agents.handler import handler_agent
from src.agents.operative import operative_agent
from src.sandbox.tools import sandbox


MAX_ATTEMPTS = 5


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

    result = handler_agent.invoke(
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
        }
    )

    response = result["structured_response"]
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

    result = operative_agent.invoke(
        {"messages": [{"role": "user", "content": briefing}]}
    )

    response = result["structured_response"]
    return {
        "test_output": response.test_output,
        "is_resolved": response.status == "fixed",
        "attempt_count": attempt,
    }


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
graph.add_node("teardown_sandbox", teardown_sandbox_node)

graph.set_entry_point("setup_sandbox")
graph.add_edge("setup_sandbox", "handler")
graph.add_edge("handler", "operative")
graph.add_conditional_edges(
    "operative",
    should_retry,
    {"retry": "operative", "done": "teardown_sandbox"},
)
graph.add_edge("teardown_sandbox", END)

workflow = graph.compile()
