from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
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
    report = {"rows": rows, "phase_aggregates": _phase_aggregates(rows), "rubric_aggregates": _rubric_aggregates(rows)}
    (out_dir / "ab-report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "ab-report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    rows = report["rows"]
    lines = [
        "# BetterContext A/B Report",
        "",
        "Quality is the gating dimension. Cost, token, and latency deltas are secondary unless answer quality is tied or better.",
        "",
        "## Rubric Aggregates",
        "",
        "| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |",
        "|---|---:|---:|---:|---:|",
    ]
    for aspect, counts in report["rubric_aggregates"].items():
        lines.append(
            f"| {aspect} | {counts.get('mcp_off', 0)} | {counts.get('mcp_on', 0)} | "
            f"{counts.get('tie', 0)} | {counts.get('unknown', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Per Task",
            "",
            "| Task | Phase | Quality | Correctness | Evidence | Completeness | Actionability | "
            "MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Cost |",
            "|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        deltas = row.get("deltas", {})
        token_delta = _sum_pair(deltas.get("tokens_in"), deltas.get("tokens_out"))
        aspects = _aspect_winners(row)
        on = row.get("on") if isinstance(row.get("on"), dict) else {}
        lines.append(
            "| {task} | {phase} | {quality} | {correctness} | {evidence} | {completeness} | "
            "{actionability} | {mcp_ok} | {mcp_denied} | {tools} | {tokens} | {dollars} | {cost} |".format(
                task=row.get("task_id", ""),
                phase=row.get("phase", ""),
                quality=row.get("judge_winner") or row.get("quality_verdict", ""),
                correctness=aspects["correctness"],
                evidence=aspects["evidence"],
                completeness=aspects["completeness"],
                actionability=aspects["actionability"],
                mcp_ok=_format_number(on.get("mcp_tool_success_count")),
                mcp_denied=_format_number(on.get("mcp_tool_denial_count")),
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

    lines.extend(["", "## Potential Resource Regressions", ""])
    regressions = [row for row in rows if _mcp_uses_more_resources(row)]
    if not regressions:
        lines.append("None.")
    else:
        for row in regressions:
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


def _rubric_aggregates(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {aspect: dict(Counter(_aspect_winners(row)[aspect] for row in rows)) for aspect in _rubric_aspects()}


def _aspect_winners(row: dict[str, Any]) -> dict[str, str]:
    raw = row.get("judge_aspect_winners")
    source = raw if isinstance(raw, dict) else {}
    return {
        aspect: winner if (winner := source.get(aspect)) in {"mcp_off", "mcp_on", "tie"} else "unknown"
        for aspect in _rubric_aspects()
    }


def _rubric_aspects() -> tuple[str, ...]:
    return ("correctness", "evidence", "completeness", "actionability")


def _mcp_uses_more_resources(row: dict[str, Any]) -> bool:
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
    )


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
