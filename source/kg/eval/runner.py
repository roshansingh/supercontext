from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from source.kg.eval.corpus import EvalTask
from source.kg.product.claude_tool_policy import (
    DEFAULT_CLAUDE_PERMISSION_MODE,
    resolve_claude_cli_path,
)
from source.kg.product.mcp_tools import tool_definitions


Arm = Literal["mcp_on", "mcp_off"]
DEFAULT_EVAL_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_HARNESS_VERSION = "ab-eval-v1"
DEFAULT_MCP_URL = "http://127.0.0.1:3845/mcp"
# A/B eval needs the same ordinary inspection surface agents used in the baseline arm.
# The prompt forbids edits and explicit edit/write tools are denied below; Bash remains
# available because prior baseline runs relied on jq/grep-style snapshot inspection.
EVAL_ALLOWED_ORDINARY_TOOLS = ("Read", "Grep", "Glob", "LS", "Bash", "ToolSearch")
EVAL_DISALLOWED_EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")


@dataclass(frozen=True)
class RunRecord:
    run_group_id: str
    arm: Arm
    task_id: str
    phase: str
    host: str
    repo_fixture: str
    difficulty: str
    harness_version: str
    task_prompt: str
    snapshot_path: str
    mcp_tools_called: list[str]
    non_mcp_tools_called: list[str]
    tokens_in: int | None
    tokens_out: int | None
    wall_time_seconds: float
    final_answer: str
    final_answer_citations: list[str]
    host_session_log_path: str
    model: str
    random_seed: int
    pre_arm_host_config_command: tuple[str, ...] = ()
    post_arm_host_config_command: tuple[str, ...] = ()
    cost_status: str = "not_uploaded"
    non_mcp_tool_attempt_count: int = 0
    non_mcp_tool_attempts: list[str] = field(default_factory=list)
    mcp_tool_attempt_count: int = 0
    mcp_tool_success_count: int = 0
    mcp_tool_denial_count: int = 0
    mcp_tool_error_count: int = 0
    mcp_tool_successes: list[str] = field(default_factory=list)
    mcp_tool_denials: list[str] = field(default_factory=list)
    mcp_tool_errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunnerConfig:
    model: str = DEFAULT_EVAL_MODEL
    max_turns: int | None = None
    load_timeout_ms: int = 180_000
    permission_mode: str = DEFAULT_CLAUDE_PERMISSION_MODE
    claude_cli_path: str | None = None
    mcp_url: str = DEFAULT_MCP_URL


def run_single_task(
    task: EvalTask,
    *,
    arm: Arm,
    snapshot: str | Path,
    output_dir: str | Path,
    host: str = "claude_code",
    run_group_id: str | None = None,
    random_seed: int = 0,
    pre_arm_host_config_command: tuple[str, ...] = (),
    post_arm_host_config_command: tuple[str, ...] = (),
    config: RunnerConfig | None = None,
) -> RunRecord:
    return asyncio.run(
        async_run_single_task(
            task,
            arm=arm,
            snapshot=snapshot,
            output_dir=output_dir,
            host=host,
            run_group_id=run_group_id,
            random_seed=random_seed,
            pre_arm_host_config_command=pre_arm_host_config_command,
            post_arm_host_config_command=post_arm_host_config_command,
            config=config,
        )
    )


async def async_run_single_task(
    task: EvalTask,
    *,
    arm: Arm,
    snapshot: str | Path,
    output_dir: str | Path,
    host: str = "claude_code",
    run_group_id: str | None = None,
    random_seed: int = 0,
    pre_arm_host_config_command: tuple[str, ...] = (),
    post_arm_host_config_command: tuple[str, ...] = (),
    config: RunnerConfig | None = None,
) -> RunRecord:
    if arm not in {"mcp_on", "mcp_off"}:
        raise ValueError(f"Unsupported A/B arm: {arm}")
    if host != "claude_code":
        raise ValueError(f"Unsupported A/B host: {host}")
    snapshot_path = Path(snapshot).expanduser()
    if not snapshot_path.exists():
        raise ValueError(f"Snapshot path does not exist: {snapshot_path}")

    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage
    except ImportError as exc:
        raise RuntimeError(
            "claude-agent-sdk is required for A/B eval runs. Install with `pip install -e '.[agent]'`."
        ) from exc

    resolved_config = config or RunnerConfig()
    group_id = run_group_id or str(uuid4())
    arm_dir = _prepare_arm_output_dir(Path(output_dir), group_id=group_id, arm=arm)
    messages_path = arm_dir / "messages.jsonl"

    prompt = _task_prompt(task, snapshot_path=snapshot_path, arm=arm)
    start = time.monotonic()
    final_answer = ""
    serialized_messages: list[dict[str, Any]] = []
    with messages_path.open("w", encoding="utf-8") as message_stream:
        async with ClaudeSDKClient(
            options=ClaudeAgentOptions(
                model=resolved_config.model,
                max_turns=resolved_config.max_turns,
                allowed_tools=_allowed_tools(arm),
                disallowed_tools=list(EVAL_DISALLOWED_EDIT_TOOLS),
                permission_mode=resolved_config.permission_mode,
                cli_path=resolve_claude_cli_path(resolved_config.claude_cli_path),
                mcp_servers=_mcp_servers(arm, resolved_config),
                cwd=Path.cwd(),
                extra_args=_claude_extra_args(),
                load_timeout_ms=resolved_config.load_timeout_ms,
                system_prompt=_system_prompt(),
            )
        ) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                serialized = _message_to_json(message)
                serialized_messages.append(serialized)
                message_stream.write(json.dumps(serialized, sort_keys=True) + "\n")
                message_stream.flush()
                if isinstance(message, ResultMessage):
                    final_answer = str(getattr(message, "result", ""))
    _raise_for_host_error_messages(serialized_messages)
    tokens_in, tokens_out = _usage_tokens(serialized_messages)
    mcp_tools, non_mcp_tools = _tool_calls(serialized_messages)
    tool_attempts = _tool_attempts(serialized_messages)
    non_mcp_tool_attempts = [name for name in tool_attempts if not name.startswith("mcp__bettercontext__")]
    mcp_observations = _mcp_tool_observations(serialized_messages)
    if arm == "mcp_on":
        _raise_for_mcp_tool_failures(mcp_observations)
    record = RunRecord(
        run_group_id=group_id,
        arm=arm,
        task_id=task.task_id,
        phase=task.phase,
        host=host,
        repo_fixture=task.fixture,
        difficulty=task.difficulty,
        harness_version=DEFAULT_HARNESS_VERSION,
        task_prompt=task.prompt,
        snapshot_path=str(snapshot_path),
        mcp_tools_called=mcp_tools,
        non_mcp_tools_called=non_mcp_tools,
        non_mcp_tool_attempt_count=len(non_mcp_tool_attempts),
        non_mcp_tool_attempts=non_mcp_tool_attempts,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        wall_time_seconds=round(time.monotonic() - start, 3),
        final_answer=final_answer,
        final_answer_citations=[],
        host_session_log_path=str(messages_path),
        model=resolved_config.model,
        random_seed=random_seed,
        pre_arm_host_config_command=pre_arm_host_config_command,
        post_arm_host_config_command=post_arm_host_config_command,
        mcp_tool_attempt_count=len(mcp_observations["attempts"]),
        mcp_tool_success_count=len(mcp_observations["successes"]),
        mcp_tool_denial_count=len(mcp_observations["denials"]),
        mcp_tool_error_count=len(mcp_observations["errors"]),
        mcp_tool_successes=mcp_observations["successes"],
        mcp_tool_denials=mcp_observations["denials"],
        mcp_tool_errors=mcp_observations["errors"],
    )
    (arm_dir / "record.json").write_text(json.dumps(record.to_json(), indent=2, sort_keys=True), encoding="utf-8")
    return record


def _system_prompt() -> str:
    return (
        "You are evaluating a BetterContext MCP-enabled coding agent workflow. "
        "Answer the task using ordinary safe source-inspection tools when needed. "
        "Do not edit files. Cite file paths, symbols, or evidence when available."
    )


def _mcp_servers(arm: Arm, config: RunnerConfig) -> dict[str, dict[str, str]]:
    if arm == "mcp_off":
        return {}
    return {"bettercontext": {"type": "http", "url": config.mcp_url}}


def _allowed_tools(arm: Arm) -> list[str]:
    tools = list(EVAL_ALLOWED_ORDINARY_TOOLS)
    if arm == "mcp_on":
        tools.extend(f"mcp__bettercontext__{tool['name']}" for tool in tool_definitions())
    return tools


def _claude_extra_args() -> dict[str, str | None]:
    return {}


def _prepare_arm_output_dir(output_dir: Path, *, group_id: str, arm: Arm) -> Path:
    arm_dir = output_dir / group_id / arm
    if arm_dir.exists():
        raise ValueError(f"A/B eval output already exists for run group {group_id!r} arm {arm!r}: {arm_dir}")
    arm_dir.mkdir(parents=True)
    return arm_dir


def _task_prompt(task: EvalTask, *, snapshot_path: Path, arm: Arm) -> str:
    fixture_input = f"\nFixture input:\n{task.fixture_input}\n" if task.fixture_input else ""
    return f"""Run this BetterContext A/B evaluation task.

Task ID: {task.task_id}
Difficulty: {task.difficulty}
Phase: {task.phase}
Fixture: {task.fixture}
Snapshot path: {snapshot_path}
Arm: {arm}
{fixture_input}

User question:
{task.prompt}

Expected answer shape:
{task.row.expected_answer_shape}

Rules:
- Do not modify files.
- Use the same ordinary source-inspection behavior you would use for a real coding task.
- If BetterContext MCP tools are available, use them when they are relevant to the question.
- If BetterContext cannot prove a fact, say what is unknown rather than guessing.
"""


def _message_to_json(message: object) -> dict[str, Any]:
    return {
        "type": type(message).__name__,
        "data": _jsonable(message),
        "repr": repr(message),
    }


def _raise_for_host_error_messages(messages: list[dict[str, Any]]) -> None:
    saw_result_message = False
    for message in messages:
        data = message.get("data")
        if not isinstance(data, dict):
            continue
        if message.get("type") == "ResultMessage":
            saw_result_message = True
            if data.get("is_error") is True:
                detail = (
                    data.get("result")
                    or data.get("api_error_status")
                    or data.get("errors")
                    or "unknown host error"
                )
                raise RuntimeError(f"Claude host run failed: {detail}")
        elif data.get("error"):
            raise RuntimeError(f"Claude host message failed: {data.get('error')}")
    if not saw_result_message:
        raise RuntimeError("Claude host run failed: missing ResultMessage")


def _raise_for_mcp_tool_failures(observations: dict[str, list[str]]) -> None:
    denials = observations["denials"]
    errors = observations["errors"]
    if denials:
        names = ", ".join(sorted(set(denials)))
        raise RuntimeError(f"Claude host denied BetterContext MCP tool permission(s): {names}")
    if errors:
        names = ", ".join(sorted(set(errors)))
        raise RuntimeError(f"Claude host returned BetterContext MCP tool error(s): {names}")


def _jsonable(value: object, *, depth: int = 0) -> Any:
    if depth > 8:
        return repr(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item, depth=depth + 1) for item in value]
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value), depth=depth + 1)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(), depth=depth + 1)
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value), depth=depth + 1)
    return repr(value)


def _usage_tokens(messages: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    input_tokens = _sum_int_keys(messages, {"input_tokens", "prompt_tokens"})
    output_tokens = _sum_int_keys(messages, {"output_tokens", "completion_tokens"})
    return input_tokens, output_tokens


def _sum_int_keys(value: Any, keys: set[str]) -> int | None:
    found, total = _sum_int_keys_inner(value, keys)
    return total if found else None


def _sum_int_keys_inner(value: Any, keys: set[str]) -> tuple[bool, int]:
    if isinstance(value, dict):
        found = False
        total = 0
        for key, item in value.items():
            if key in keys and isinstance(item, int) and not isinstance(item, bool):
                found = True
                total += item
        if found:
            return True, total
        for key, item in value.items():
            if key in keys:
                continue
            child_found, child_total = _sum_int_keys_inner(item, keys)
            found = found or child_found
            total += child_total
        return found, total
    elif isinstance(value, list):
        found = False
        total = 0
        for item in value:
            child_found, child_total = _sum_int_keys_inner(item, keys)
            found = found or child_found
            total += child_total
        return found, total
    return False, 0


def _tool_calls(messages: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    names = sorted(set(_tool_names(messages)))
    # The eval harness only attaches the BetterContext MCP server. Keep this
    # scope aligned with _mcp_tool_observations so aggregate tool counts match.
    mcp = [name for name in names if name.startswith("mcp__bettercontext__")]
    non_mcp = [name for name in names if name not in mcp]
    return mcp, non_mcp


def _tool_attempts(messages: list[dict[str, Any]]) -> list[str]:
    attempts: list[str] = []
    for message in messages:
        for block in _content_blocks(message):
            tool_id = block.get("id")
            name = block.get("name")
            if isinstance(tool_id, str) and isinstance(name, str) and name:
                attempts.append(name)
    return attempts


def _mcp_tool_observations(messages: list[dict[str, Any]]) -> dict[str, list[str]]:
    tool_use_names: dict[str, str] = {}
    permission_denials_by_id: dict[str, str] = {}
    attempts: list[str] = []
    successes: list[str] = []
    denials: list[str] = []
    errors: list[str] = []
    observed_denial_ids: set[str] = set()

    for message in messages:
        data = message.get("data")
        if not isinstance(data, dict):
            continue
        for denial in data.get("permission_denials") or []:
            if not isinstance(denial, dict):
                continue
            name = denial.get("tool_name")
            tool_id = denial.get("tool_use_id")
            if (
                isinstance(tool_id, str)
                and isinstance(name, str)
                and name.startswith("mcp__bettercontext__")
            ):
                permission_denials_by_id[tool_id] = name

    for message in messages:
        for block in _content_blocks(message):
            tool_id = block.get("id")
            name = block.get("name")
            if isinstance(tool_id, str) and isinstance(name, str) and name.startswith("mcp__bettercontext__"):
                tool_use_names[tool_id] = name
                attempts.append(name)

            result_id = block.get("tool_use_id")
            if isinstance(result_id, str) and result_id in tool_use_names:
                result_name = tool_use_names[result_id]
                if result_id in permission_denials_by_id or _tool_result_is_denial(block):
                    denials.append(result_name)
                    observed_denial_ids.add(result_id)
                elif block.get("is_error") is True:
                    errors.append(result_name)
                else:
                    successes.append(result_name)

    for tool_id, name in permission_denials_by_id.items():
        if tool_id not in observed_denial_ids:
            denials.append(name)

    return {
        "attempts": attempts,
        "successes": successes,
        "denials": denials,
        "errors": errors,
    }


def _content_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    data = message.get("data")
    if not isinstance(data, dict):
        return []
    content = data.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _tool_result_is_denial(block: dict[str, Any]) -> bool:
    if block.get("is_error") is not True:
        return False
    content = block.get("content")
    if not isinstance(content, str):
        return False
    return "requested permissions to use" in content.lower()


def _tool_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        if _looks_like_tool_call(value):
            name = value.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        for item in value.values():
            names.extend(_tool_names(item))
    elif isinstance(value, list):
        for item in value:
            names.extend(_tool_names(item))
    return names


def _looks_like_tool_call(value: dict[str, Any]) -> bool:
    block_type = value.get("type")
    if block_type in {"tool_use", "tool_result"}:
        return True
    return "name" in value and ("input" in value or "arguments" in value)
