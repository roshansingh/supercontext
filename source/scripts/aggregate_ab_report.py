from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from source.scripts.compute_ab_deltas import load_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Render BetterContext A/B delta reports.")
    parser.add_argument("--deltas", required=True, help="Input deltas JSONL.")
    parser.add_argument("--out", required=True, help="Output report directory.")
    args = parser.parse_args()

    rows = load_jsonl(Path(args.deltas))
    render_report(rows, Path(args.out))


def render_report(rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"rows": rows, "phase_aggregates": _phase_aggregates(rows)}
    (out_dir / "ab-report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "ab-report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    rows = report["rows"]
    lines = [
        "# BetterContext A/B Report",
        "",
        "## Per Task",
        "",
        "| Task | Phase | Quality | Tool Delta | Token Delta | Dollar Delta | Cost |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        deltas = row.get("deltas", {})
        token_delta = _sum_pair(deltas.get("tokens_in"), deltas.get("tokens_out"))
        lines.append(
            "| {task} | {phase} | {quality} | {tools} | {tokens} | {dollars} | {cost} |".format(
                task=row.get("task_id", ""),
                phase=row.get("phase", ""),
                quality=row.get("quality_verdict", ""),
                tools=_format_number(deltas.get("tool_calls")),
                tokens=_format_number(token_delta),
                dollars=_format_dollars(row.get("dollars_delta"), row.get("cost_status")),
                cost=row.get("cost_status", ""),
            )
        )

    lines.extend(
        [
            "",
            "## Phase Aggregates",
            "",
            "| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for phase, aggregate in sorted(report["phase_aggregates"].items()):
        lines.append(
            f"| {phase} | {aggregate['tasks']} | {_format_number(aggregate['avg_tool_calls_delta'])} | "
            f"{_format_number(aggregate['avg_token_delta'])} | {_format_number(aggregate['avg_wall_time_delta'])} |"
        )

    lines.extend(["", "## Where MCP Hurts", ""])
    hurts = [row for row in rows if _mcp_hurts(row)]
    if not hurts:
        lines.append("None.")
    else:
        for row in hurts:
            lines.append(f"- {row.get('task_id')}: {row.get('phase')} delta={row.get('deltas', {})}")
    lines.append("")
    return "\n".join(lines)


def _phase_aggregates(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_phase: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_phase[str(row.get("phase") or "unknown")].append(row)
    return {phase: _aggregate_phase(phase_rows) for phase, phase_rows in by_phase.items()}


def _aggregate_phase(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tasks": len(rows),
        "avg_tool_calls_delta": _average(row.get("deltas", {}).get("tool_calls") for row in rows),
        "avg_token_delta": _average(
            _sum_pair(row.get("deltas", {}).get("tokens_in"), row.get("deltas", {}).get("tokens_out"))
            for row in rows
        ),
        "avg_wall_time_delta": _average(row.get("deltas", {}).get("wall_time_seconds") for row in rows),
    }


def _mcp_hurts(row: dict[str, Any]) -> bool:
    deltas = row.get("deltas", {})
    return any(
        _is_number(value) and value < 0
        for value in (
            deltas.get("tool_calls"),
            deltas.get("tokens_in"),
            deltas.get("tokens_out"),
            deltas.get("wall_time_seconds"),
            row.get("dollars_delta"),
        )
    ) or (_is_number(deltas.get("citations_count")) and deltas.get("citations_count") > 0)


def _average(values: Any) -> float | None:
    numeric = [value for value in values if _is_number(value)]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 3)


def _sum_pair(left: Any, right: Any) -> float | int | None:
    if (
        not _is_number(left)
        or not _is_number(right)
    ):
        return None
    return left + right


def _format_number(value: Any) -> str:
    if _is_number(value):
        return str(value)
    return "n/a"


def _format_dollars(value: Any, cost_status: Any) -> str:
    if cost_status != "available" or value is None:
        return "unavailable"
    if not _is_number(value):
        return "unavailable"
    return _format_number(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


if __name__ == "__main__":
    main()
