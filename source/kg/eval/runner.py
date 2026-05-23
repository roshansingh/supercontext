from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from source.kg.eval.corpus import EvalTask
from source.kg.product.claude_tool_policy import (
    DEFAULT_CLAUDE_PERMISSION_MODE,
    resolve_claude_cli_path,
)


Arm = Literal["mcp_on", "mcp_off"]
DEFAULT_EVAL_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_HARNESS_VERSION = "ab-eval-v1"
DEFAULT_MCP_URL = "http://127.0.0.1:3845/mcp"


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
    cost_status: str = "not_uploaded"

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
    run_group_id: str | None = None,
    random_seed: int = 0,
    config: RunnerConfig | None = None,
) -> RunRecord:
    return asyncio.run(
        async_run_single_task(
            task,
            arm=arm,
            snapshot=snapshot,
            output_dir=output_dir,
            run_group_id=run_group_id,
            random_seed=random_seed,
            config=config,
        )
    )


async def async_run_single_task(
    task: EvalTask,
    *,
    arm: Arm,
    snapshot: str | Path,
    output_dir: str | Path,
    run_group_id: str | None = None,
    random_seed: int = 0,
    config: RunnerConfig | None = None,
) -> RunRecord:
    if arm not in {"mcp_on", "mcp_off"}:
        raise ValueError(f"Unsupported A/B arm: {arm}")
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
    arm_dir = Path(output_dir) / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
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
                permission_mode=resolved_config.permission_mode,
                cli_path=resolve_claude_cli_path(resolved_config.claude_cli_path),
                mcp_servers=_mcp_servers(arm, resolved_config),
                cwd=Path.cwd(),
                extra_args={"bare": None},
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
    tokens_in, tokens_out = _usage_tokens(serialized_messages)
    mcp_tools, non_mcp_tools = _tool_calls(serialized_messages)
    record = RunRecord(
        run_group_id=group_id,
        arm=arm,
        task_id=task.task_id,
        phase=task.phase,
        host="claude_code",
        repo_fixture=task.fixture,
        difficulty=task.difficulty,
        harness_version=DEFAULT_HARNESS_VERSION,
        task_prompt=task.prompt,
        snapshot_path=str(snapshot_path),
        mcp_tools_called=mcp_tools,
        non_mcp_tools_called=non_mcp_tools,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        wall_time_seconds=round(time.monotonic() - start, 3),
        final_answer=final_answer,
        final_answer_citations=[],
        host_session_log_path=str(messages_path),
        model=resolved_config.model,
        random_seed=random_seed,
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


def _task_prompt(task: EvalTask, *, snapshot_path: Path, arm: Arm) -> str:
    return f"""Run this BetterContext A/B evaluation task.

Task ID: {task.task_id}
Difficulty: {task.difficulty}
Phase: {task.phase}
Fixture: {task.fixture}
Snapshot path: {snapshot_path}
Arm: {arm}

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
    total = _sum_int_keys_inner(value, keys)
    return total if total > 0 else None


def _sum_int_keys_inner(value: Any, keys: set[str]) -> int:
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            if key in keys and isinstance(item, int) and not isinstance(item, bool):
                total += item
        for item in value.values():
            total += _sum_int_keys_inner(item, keys)
        return total
    elif isinstance(value, list):
        return sum(_sum_int_keys_inner(item, keys) for item in value)
    return 0


def _tool_calls(messages: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    names = sorted(set(_tool_names(messages)))
    mcp = [name for name in names if name.startswith("mcp__bettercontext__")]
    non_mcp = [name for name in names if name not in mcp]
    return mcp, non_mcp


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
