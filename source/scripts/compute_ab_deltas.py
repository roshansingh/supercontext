from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


MCP_PACKET_NAVIGATION_COUNTER_KEYS = (
    "mcp_packet_file_reference_count",
    "mcp_packet_jq_attempt_count",
    "mcp_packet_saved_file_count",
    "mcp_packet_saved_file_bytes_best_effort",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute paired SuperContext A/B deltas.")
    parser.add_argument("--traces", required=True, help="Input traces JSONL from pull_ab_traces.")
    parser.add_argument("--out", required=True, help="Output deltas JSONL path.")
    parser.add_argument("--allow-unpaired", action="store_true", help="Skip incomplete run pairs instead of failing.")
    parser.add_argument(
        "--allow-mcp-tool-failures",
        action="store_true",
        help="Allow mcp_on rows with denied/errored SuperContext tool calls instead of failing closed.",
    )
    parser.add_argument(
        "--allow-incomplete-background-tasks",
        action="store_true",
        help="Allow rows with incomplete Claude SDK background-task markers instead of failing closed.",
    )
    args = parser.parse_args()

    rows = compute_deltas(
        load_jsonl(Path(args.traces)),
        allow_unpaired=args.allow_unpaired,
        allow_mcp_tool_failures=args.allow_mcp_tool_failures,
        allow_incomplete_background_tasks=args.allow_incomplete_background_tasks,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def compute_deltas(
    traces: list[dict[str, Any]],
    *,
    allow_unpaired: bool = False,
    allow_mcp_tool_failures: bool = False,
    allow_incomplete_background_tasks: bool = False,
) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for trace in traces:
        run_group_id = _required_string(trace, "run_group_id")
        task_id = _required_string(trace, "task_id")
        arm = _required_string(trace, "arm")
        if arm not in {"mcp_on", "mcp_off"}:
            raise ValueError(f"unsupported arm: {arm!r}")
        key = (run_group_id, task_id)
        if arm in pairs[key]:
            raise ValueError(f"duplicate trace for run_group_id={run_group_id!r} task_id={task_id!r} arm={arm!r}")
        pairs[key][arm] = trace

    deltas = []
    for (run_group_id, task_id), arms in sorted(pairs.items()):
        if set(arms) != {"mcp_on", "mcp_off"}:
            if allow_unpaired:
                continue
            present = ", ".join(sorted(arms))
            raise ValueError(
                f"unpaired traces for run_group_id={run_group_id!r} task_id={task_id!r}; present arms: {present}"
            )
        on = arms["mcp_on"]
        off = arms["mcp_off"]
        if not allow_incomplete_background_tasks:
            _reject_incomplete_background_tasks(on, run_group_id=run_group_id, task_id=task_id, arm="mcp_on")
            _reject_incomplete_background_tasks(off, run_group_id=run_group_id, task_id=task_id, arm="mcp_off")
        if not allow_mcp_tool_failures:
            _reject_mcp_on_tool_failures(on, run_group_id=run_group_id, task_id=task_id)
        cost_status = _paired_cost_status(on, off)
        deltas.append(
            {
                "run_group_id": run_group_id,
                "task_id": task_id,
                "phase": on.get("phase") or off.get("phase"),
                "difficulty": on.get("difficulty") or off.get("difficulty"),
                "quality_verdict": "ungraded",
                "quality_grading_mode": _quality_grading_mode(on, off),
                "cost_status": cost_status,
                "dollars_delta": _number_delta(off.get("total_cost"), on.get("total_cost"))
                if cost_status == "available"
                else None,
                "deltas": {
                    "tool_calls": _tool_count(off) - _tool_count(on),
                    "mcp_calls": _list_len(off, "mcp_tools_called") - _list_len(on, "mcp_tools_called"),
                    "mcp_tool_attempts": _int_delta(
                        _int_field(off, "mcp_tool_attempt_count", fallback=_list_len(off, "mcp_tools_called")),
                        _int_field(on, "mcp_tool_attempt_count", fallback=_list_len(on, "mcp_tools_called")),
                    ),
                    "mcp_tool_successes": _int_delta(
                        _int_field(off, "mcp_tool_success_count"),
                        _int_field(on, "mcp_tool_success_count"),
                    ),
                    "mcp_tool_denials": _int_delta(
                        _int_field(off, "mcp_tool_denial_count"),
                        _int_field(on, "mcp_tool_denial_count"),
                    ),
                    "mcp_tool_errors": _int_delta(
                        _int_field(off, "mcp_tool_error_count"),
                        _int_field(on, "mcp_tool_error_count"),
                    ),
                    "mcp_packet_file_references": _int_delta(
                        _int_field(off, "mcp_packet_file_reference_count"),
                        _int_field(on, "mcp_packet_file_reference_count"),
                    ),
                    "mcp_packet_jq_attempts": _int_delta(
                        _int_field(off, "mcp_packet_jq_attempt_count"),
                        _int_field(on, "mcp_packet_jq_attempt_count"),
                    ),
                    "mcp_packet_saved_files": _int_delta(
                        _int_field(off, "mcp_packet_saved_file_count"),
                        _int_field(on, "mcp_packet_saved_file_count"),
                    ),
                    "mcp_packet_saved_file_bytes_best_effort": _int_delta(
                        _int_field(off, "mcp_packet_saved_file_bytes_best_effort"),
                        _int_field(on, "mcp_packet_saved_file_bytes_best_effort"),
                    ),
                    "non_mcp_calls": _list_len(off, "non_mcp_tools_called") - _list_len(on, "non_mcp_tools_called"),
                    "non_mcp_tool_attempts": _int_delta(
                        _int_field(
                            off,
                            "non_mcp_tool_attempt_count",
                            fallback=_list_len(off, "non_mcp_tools_called"),
                        ),
                        _int_field(
                            on,
                            "non_mcp_tool_attempt_count",
                            fallback=_list_len(on, "non_mcp_tools_called"),
                        ),
                    ),
                    "tokens_in": _number_delta(off.get("tokens_in"), on.get("tokens_in")),
                    "tokens_out": _number_delta(off.get("tokens_out"), on.get("tokens_out")),
                    "wall_time_seconds": _number_delta(off.get("wall_time_seconds"), on.get("wall_time_seconds")),
                    "citations_count": _list_len(off, "final_answer_citations")
                    - _list_len(on, "final_answer_citations"),
                },
                "on": _arm_summary(on),
                "off": _arm_summary(off),
            }
        )
    return deltas


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(row)
    return rows


def _arm_summary(trace: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "answer": trace.get("final_answer"),
        "mcp_tools_called": _list(trace, "mcp_tools_called"),
        "mcp_tool_attempt_count": _int_field(
            trace, "mcp_tool_attempt_count", fallback=_list_len(trace, "mcp_tools_called")
        ),
        "mcp_tool_success_count": _int_field(trace, "mcp_tool_success_count"),
        "mcp_tool_denial_count": _int_field(trace, "mcp_tool_denial_count"),
        "mcp_tool_error_count": _int_field(trace, "mcp_tool_error_count"),
        "mcp_tool_successes": _list(trace, "mcp_tool_successes"),
        "mcp_tool_denials": _list(trace, "mcp_tool_denials"),
        "mcp_tool_errors": _list(trace, "mcp_tool_errors"),
        "non_mcp_tools_called": _list(trace, "non_mcp_tools_called"),
        "non_mcp_tool_attempt_count": _int_field(
            trace, "non_mcp_tool_attempt_count", fallback=_list_len(trace, "non_mcp_tools_called")
        ),
        "non_mcp_tool_attempts": _list(trace, "non_mcp_tool_attempts"),
        "tokens_in": trace.get("tokens_in"),
        "tokens_out": trace.get("tokens_out"),
        "total_cost": trace.get("total_cost"),
        "cost_status": trace.get("cost_status"),
        "wall_time_seconds": trace.get("wall_time_seconds"),
        "incomplete_background_task_ids": _string_list(trace, "incomplete_background_task_ids"),
    }
    for key in MCP_PACKET_NAVIGATION_COUNTER_KEYS:
        summary[key] = _int_field(trace, key)
    return summary


def _paired_cost_status(on: dict[str, Any], off: dict[str, Any]) -> str:
    if (
        on.get("cost_status") == "available"
        and off.get("cost_status") == "available"
        and on.get("total_cost") is not None
        and off.get("total_cost") is not None
    ):
        return "available"
    return "unavailable"


def _quality_grading_mode(on: dict[str, Any], off: dict[str, Any]) -> str:
    return "auto_eligible" if (on.get("difficulty") or off.get("difficulty")) == "Low" else "manual_required"


def _required_string(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"trace missing required string field {key!r}")
    return value


def _tool_count(trace: dict[str, Any]) -> int:
    # In normal mode mcp_on denials/errors fail closed before this point. The attempt
    # count is still used for explicit forensic runs with --allow-mcp-tool-failures.
    return _int_field(trace, "mcp_tool_attempt_count", fallback=_list_len(trace, "mcp_tools_called")) + _int_field(
        trace, "non_mcp_tool_attempt_count", fallback=_list_len(trace, "non_mcp_tools_called")
    )


def _reject_mcp_on_tool_failures(on: dict[str, Any], *, run_group_id: str, task_id: str) -> None:
    denial_count = _int_field(on, "mcp_tool_denial_count", fallback=_list_len(on, "mcp_tool_denials"))
    error_count = _int_field(on, "mcp_tool_error_count", fallback=_list_len(on, "mcp_tool_errors"))
    if denial_count or error_count:
        raise ValueError(
            f"invalid mcp_on trace for run_group_id={run_group_id!r} task_id={task_id!r}: "
            f"SuperContext MCP denials={denial_count} errors={error_count}"
        )


def _reject_incomplete_background_tasks(trace: dict[str, Any], *, run_group_id: str, task_id: str, arm: str) -> None:
    task_ids = _string_list(trace, "incomplete_background_task_ids")
    if not task_ids:
        return
    raise ValueError(
        f"invalid trace for run_group_id={run_group_id!r} task_id={task_id!r} arm={arm!r}: "
        f"incomplete background tasks={', '.join(task_ids)}"
    )


def _list_len(trace: dict[str, Any], key: str) -> int:
    return len(_list(trace, key))


def _string_list(trace: dict[str, Any], key: str) -> list[str]:
    values = _list(trace, key)
    if any(not isinstance(value, str) for value in values):
        raise ValueError(f"trace field {key!r} must be a list of strings")
    return values


def _list(trace: dict[str, Any], key: str) -> list[Any]:
    value = trace.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"trace field {key!r} must be a list")
    return value


def _int_field(trace: dict[str, Any], key: str, *, fallback: int = 0) -> int:
    value = trace.get(key)
    if value is None:
        return fallback
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"trace field {key!r} must be an integer")
    if value < 0:
        raise ValueError(f"trace field {key!r} must be non-negative")
    return value


def _int_delta(off_value: int, on_value: int) -> int:
    return off_value - on_value


def _number_delta(off_value: Any, on_value: Any) -> float | int | None:
    if isinstance(off_value, bool) or isinstance(on_value, bool):
        return None
    if isinstance(off_value, (int, float)) and isinstance(on_value, (int, float)):
        return off_value - on_value
    return None


if __name__ == "__main__":
    main()
