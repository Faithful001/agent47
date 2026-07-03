import json
import logging
import time
import os

from langgraph.graph import StateGraph, END

from agent47.state import ContractState
from agent47.agents.handler import handler_agent, HandlerResponse
from agent47.agents.operative import operative_agent, OperativeResponse
from agent47.infra.sandbox.tools import sandbox
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
                "504", "502", "503", "429", "rate_limit",
                "aborted", "timed out", "timeout",
                "tool_use_failed",
                "RESOURCE_EXHAUSTED",
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
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("API retry limit reached without catching any exception")


def _parse_json_response(content: str, model_class, agent_name: str):
    """Extract and parse a JSON object from a model's final message content."""
    clean = content.strip()

    # Try to extract content inside markdown code block first
    import re
    code_block_match = re.search(r"```(?:json)?\n(.*?)\n```", clean, re.DOTALL)
    if code_block_match:
        clean = code_block_match.group(1).strip()
    else:
        # Fallback: find the first '{' and the last '}'
        start_idx = clean.find("{")
        end_idx = clean.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            clean = clean[start_idx:end_idx + 1].strip()

    try:
        parsed = json.loads(clean)
        return model_class(**parsed)
    except Exception as e:
        logger.error(
            "%s failed to parse structured response: %s\nRaw content: %s",
            agent_name, e, content,
        )
        raise RuntimeError(
            f"{agent_name} failed to produce a valid structured response: {e}"
        )


# --- Nodes ---

def setup_sandbox_node(state: ContractState):
    workspace = state.get("workspace_dir", "")

    import subprocess
    import uuid

    railpack_image_name = None

    custom_rules = []
    custom_test_cmd = None

    if workspace:
        abs_workspace = os.path.abspath(workspace)
        image_name = f"sandbox_img_{uuid.uuid4().hex}"
        logger.info("Building sandbox image with Railpack: %s from %s", image_name, abs_workspace)
        try:
            sandbox.image = detect_base_image(abs_workspace)
            railpack_image_name = None
        except subprocess.CalledProcessError as e:
            logger.warning("Railpack build failed: %s. Falling back to heuristic detection.", e.stderr)
            sandbox.image = detect_base_image(abs_workspace)
        except FileNotFoundError:
            logger.warning("Railpack CLI not found. Falling back to heuristic detection.")
            sandbox.image = detect_base_image(abs_workspace)

        # Parse custom .agent47.yaml configuration
        config_path = os.path.join(abs_workspace, ".agent47.yaml")
        if os.path.exists(config_path):
            try:
                import yaml
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                    if isinstance(cfg, dict):
                        custom_rules = cfg.get("rules", [])
                        if not isinstance(custom_rules, list):
                            custom_rules = [str(custom_rules)]
                        # Clean up rule strings
                        custom_rules = [str(r).strip() for r in custom_rules if r]
                        custom_test_cmd = cfg.get("test_command")
                        if custom_test_cmd:
                            custom_test_cmd = str(custom_test_cmd).strip()
                logger.info("Loaded custom config from .agent47.yaml: rules=%s, test_command=%s", custom_rules, custom_test_cmd)
            except Exception as e:
                logger.warning("Failed to parse .agent47.yaml: %s", e)
    else:
        sandbox.image = "ubuntu:22.04"

    sandbox.start()

    if workspace:
        sandbox.execute_command("mkdir -p /workspace")
        sandbox.copy_repo_to_container(abs_workspace, "/workspace")

    return {
        "repo_path": "/workspace",
        "railpack_image_name": railpack_image_name,
        "custom_rules": custom_rules,
        "custom_test_command": custom_test_cmd,
    }


def handler_node(state: ContractState):
    error_msg = state.get("error_message", "")
    bug = state.get("bug_description", "") or error_msg
    local_repo = state.get("workspace_dir", "")

    response = handler_agent(repo_path=local_repo, bug=bug)

    logger.info(
        "Handler identified %d relevant files: %s",
        len(response.relevant_files), response.relevant_files,
    )

    return {"relevant_files": response.relevant_files}


def operative_node(state: ContractState):
    """The Operative reads, fixes, and verifies the bug inside the sandbox."""
    error_msg = state.get("error_message", "")
    bug = state.get("bug_description", "") or error_msg
    relevant_files = state.get("relevant_files", [])
    attempt = state.get("attempt_count", 0) + 1
    previous_output = state.get("test_output", "")

    custom_rules = state.get("custom_rules", [])
    custom_test_cmd = state.get("custom_test_command")

    briefing_parts = [
        f"## Contract (Attempt {attempt}/{MAX_ATTEMPTS})",
        f"**Bug:** {bug}",
        f"**Relevant files (in the sandbox at /workspace):** {', '.join(relevant_files)}",
        f"**Working directory:** Always run commands from /workspace. Example: `cd /workspace && npm run build`",
        f"**Important:** Read the relevant files FIRST before attempting any fix. Do not guess — find the exact syntax error in the file.",
    ]

    if custom_rules:
        rules_str = "\n".join(f"- {rule}" for rule in custom_rules)
        briefing_parts.append(f"**Custom Repository Coding Guidelines & Constraints:**\n{rules_str}")

    if custom_test_cmd:
        briefing_parts.append(
            f"**Custom Test Command:** You must verify your fix using this command: `{custom_test_cmd}`. "
            f"Always run this test command from /workspace (e.g. `cd /workspace && {custom_test_cmd}`)."
        )
    if previous_output:
        previous_output = previous_output[-500:]  # trim to avoid token bloat
        briefing_parts.append(
            f"**Previous test output (fix failed):**\n```\n{previous_output}\n```"
        )

    briefing = "\n\n".join(briefing_parts)

    result = _invoke_with_retry(
        operative_agent,
        {"messages": [{"role": "user", "content": briefing}]},
        agent_name="Operative",
    )

    messages = result.get("messages", [])
    if not messages:
        raise RuntimeError("Operative returned no messages")

    last_message = messages[-1]
    content = last_message.content if hasattr(last_message, "content") else str(last_message)

    logger.info("Operative last message: %s", content[:500])

    try:
        response = _parse_json_response(content, OperativeResponse, "Operative")
    except RuntimeError:
        # Recovery: the model forgot to output JSON. Re-prompt with all
        # prior messages asking it to produce the required JSON report.
        logger.warning("Operative did not produce valid JSON. Attempting recovery re-prompt...")
        from agent47.config.config import advanced_model

        recovery_messages = list(messages) + [
            {"role": "user", "content": (
                "Your last message was not valid JSON. You MUST respond with ONLY "
                "a raw JSON object containing these exact fields:\n"
                "{\"fix_summary\": \"...\", \"files_modified\": [\"...\"], "
                "\"test_command\": \"...\", \"test_output\": \"...\", "
                "\"status\": \"fixed|partial|failed\"}\n"
                "Output ONLY the JSON. No explanation, no markdown, no code fences."
            )}
        ]
        recovery_result = _invoke_with_retry(
            advanced_model,
            recovery_messages,
            agent_name="Operative-Recovery",
            max_retries=2,
        )
        recovery_content = recovery_result.content if hasattr(recovery_result, "content") else str(recovery_result)
        logger.info("Operative recovery response: %s", recovery_content[:500])
        response = _parse_json_response(recovery_content, OperativeResponse, "Operative")

    logger.info(
        "Operative attempt %d/%d — status: %s", attempt, MAX_ATTEMPTS, response.status
    )

    return {
        "test_output": response.test_output,
        "is_resolved": response.status == "fixed",
        "attempt_count": attempt,
    }


def sync_from_sandbox_node(state: ContractState):
    """Copy modified files from sandbox back to the local workspace."""
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
            logger.warning(
                "Could not remove Railpack sandbox image %s: %s", railpack_image_name, e
            )

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