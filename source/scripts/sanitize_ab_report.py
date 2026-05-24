from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from source.scripts.compute_ab_deltas import load_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Render sanitized checked-in SuperContext A/B reports.")
    parser.add_argument("--judged-deltas", required=True, help="Judged deltas JSONL.")
    parser.add_argument("--raw-report", required=True, help="Raw aggregate ab-report.json.")
    parser.add_argument("--out", required=True, help="Output docs directory.")
    parser.add_argument("--run-id", required=True, help="Stable run id.")
    parser.add_argument("--date", required=True, help="Run date in YYYY-MM-DD form.")
    parser.add_argument("--judge-model", required=True, help="Judge model used for quality verdicts.")
    parser.add_argument("--seed", type=int, required=True, help="Judge presentation seed.")
    args = parser.parse_args()

    render_sanitized_report(
        rows=load_jsonl(Path(args.judged_deltas)),
        raw_report=json.loads(Path(args.raw_report).read_text(encoding="utf-8")),
        out_dir=Path(args.out),
        run_id=args.run_id,
        run_date=args.date,
        judge_model=args.judge_model,
        seed=args.seed,
    )


def render_sanitized_report(
    *,
    rows: list[dict[str, Any]],
    raw_report: dict[str, Any],
    out_dir: Path,
    run_id: str,
    run_date: str,
    judge_model: str,
    seed: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sanitized_rows = [_sanitize_row(row) for row in rows]
    summary = _summary(
        rows=rows,
        sanitized_rows=sanitized_rows,
        raw_report=raw_report,
        run_id=run_id,
        run_date=run_date,
        judge_model=judge_model,
    )
    (out_dir / "ab-report.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "ab-report.md").write_text(
        _report_markdown(summary, run_id=run_id, run_date=run_date, judge_model=judge_model, seed=seed),
        encoding="utf-8",
    )
    (out_dir / "trace-analysis.md").write_text(
        _trace_analysis(summary, run_id=run_id, run_date=run_date, judge_model=judge_model, seed=seed),
        encoding="utf-8",
    )


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    deltas = row.get("deltas", {})
    token_delta = _sum_numbers(deltas.get("tokens_in"), deltas.get("tokens_out"))
    aspects = _sanitize_aspect_winners(row.get("judge_aspect_winners"))
    on = row.get("on") if isinstance(row.get("on"), dict) else {}
    return {
        "task_id": row.get("task_id"),
        "phase": row.get("phase") or "unknown",
        "difficulty": row.get("difficulty") or "unknown",
        "quality_verdict": row.get("quality_verdict") or "unknown",
        "judge_winner": row.get("judge_winner") or "unknown",
        "judge_aspect_winners": aspects,
        "judge_confidence": _round_number(row.get("judge_confidence")),
        "cost_status": row.get("cost_status"),
        "dollars_delta": _round_number(row.get("dollars_delta")),
        "mcp_on_tool_health": {
            "attempts": _round_number(on.get("mcp_tool_attempt_count")),
            "successes": _round_number(on.get("mcp_tool_success_count")),
            "denials": _round_number(on.get("mcp_tool_denial_count")),
            "errors": _round_number(on.get("mcp_tool_error_count")),
        },
        "deltas": {
            "tool_calls": _round_number(deltas.get("tool_calls")),
            "mcp_calls": _round_number(deltas.get("mcp_calls")),
            "mcp_tool_attempts": _round_number(deltas.get("mcp_tool_attempts")),
            "mcp_tool_successes": _round_number(deltas.get("mcp_tool_successes")),
            "mcp_tool_denials": _round_number(deltas.get("mcp_tool_denials")),
            "mcp_tool_errors": _round_number(deltas.get("mcp_tool_errors")),
            "non_mcp_calls": _round_number(deltas.get("non_mcp_calls")),
            "tokens_in": _round_number(deltas.get("tokens_in")),
            "tokens_out": _round_number(deltas.get("tokens_out")),
            "tokens_total": _round_number(token_delta),
            "wall_time_seconds": _round_number(deltas.get("wall_time_seconds")),
            "citations_count": _round_number(deltas.get("citations_count")),
        },
    }


def _summary(
    *,
    rows: list[dict[str, Any]],
    sanitized_rows: list[dict[str, Any]],
    raw_report: dict[str, Any],
    run_id: str,
    run_date: str,
    judge_model: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "date": run_date,
        "task_count": len(rows),
        "arm_count": len(rows) * 2,
        "delta_orientation": (
            "off_minus_on; positive means mcp_on used less or cost less, "
            "negative means mcp_on used more or cost more"
        ),
        "judge_model": judge_model,
        "quality_verdicts": dict(Counter(row.get("quality_verdict") for row in sanitized_rows)),
        "judge_winners": dict(Counter(row.get("judge_winner") for row in sanitized_rows)),
        "judge_aspect_winners": _aspect_winner_counts(sanitized_rows),
        "phase_aggregates": _round_nested(raw_report.get("phase_aggregates", {})),
        "rows": sanitized_rows,
        "privacy_note": (
            "Sanitized artifact. Raw traces, answers, judge reasoning, SDK messages, and LangSmith URLs "
            "remain under ignored data/ab_runs/ and are not committed."
        ),
    }


def _report_markdown(
    summary: dict[str, Any],
    *,
    run_id: str,
    run_date: str,
    judge_model: str,
    seed: int,
) -> str:
    winners = summary["judge_winners"]
    aspect_counts = summary["judge_aspect_winners"]
    lines = [
        f"# SuperContext A/B Report - {run_id} - {run_date}",
        "",
        "Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than "
        "`mcp_off`; negative values mean `mcp_on` used more.",
        "",
        f"This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, "
        f"and downloaded traces remain under ignored `data/ab_runs/{run_id}/`.",
        "",
        "## Summary",
        "",
        f"- Tasks: {summary['task_count']} paired tasks / {summary['arm_count']} host runs",
        f"- Quality judge: `{judge_model}`, blinded A/B answer order, seed `{seed}`",
        f"- Overall quality winners: `mcp_off={winners.get('mcp_off', 0)}`, `mcp_on={winners.get('mcp_on', 0)}`, "
        f"`tie={winners.get('tie', 0)}`",
        "- Quality gate: answer quality must be at least tied before token, cost, or latency wins matter.",
        f"- Cost availability: `{dict(Counter(row.get('cost_status') for row in summary['rows']))}`",
        "",
        "## Rubric Summary",
        "",
        "| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |",
        "|---|---:|---:|---:|---:|",
    ]
    for aspect in ("correctness", "evidence", "completeness", "actionability"):
        counts = aspect_counts.get(aspect, {})
        lines.append(
            f"| {aspect} | {counts.get('mcp_off', 0)} | {counts.get('mcp_on', 0)} | "
            f"{counts.get('tie', 0)} | {counts.get('unknown', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Per Task",
            "",
            "| Task | Phase | Difficulty | Overall | Correctness | Evidence | Completeness | Actionability | "
            "MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |",
            "|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["rows"]:
        deltas = row["deltas"]
        aspects = row["judge_aspect_winners"]
        mcp_health = row["mcp_on_tool_health"]
        lines.append(
            f"| {row['task_id']} | {row['phase']} | {row['difficulty']} | "
            f"{row['judge_winner']} ({_format_number(row['judge_confidence'])}) | "
            f"{aspects['correctness']} | {aspects['evidence']} | {aspects['completeness']} | "
            f"{aspects['actionability']} | {_format_number(mcp_health['successes'])} | "
            f"{_format_number(mcp_health['denials'])} | {_format_number(deltas['tool_calls'])} | "
            f"{_format_number(deltas['tokens_total'])} | {_format_number(row['dollars_delta'])} | "
            f"{_format_number(deltas['wall_time_seconds'])} |"
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
    for phase, aggregate in sorted(summary["phase_aggregates"].items()):
        lines.append(
            f"| {phase} | {aggregate['tasks']} | {_format_number(aggregate['avg_tool_calls_delta'])} | "
            f"{_format_number(aggregate['avg_token_delta'])} | "
            f"{_format_number(aggregate['avg_wall_time_delta'])} |"
        )
    return "\n".join(lines) + "\n"


def _trace_analysis(
    summary: dict[str, Any],
    *,
    run_id: str,
    run_date: str,
    judge_model: str,
    seed: int,
) -> str:
    rows = summary["rows"]
    winner_by_phase: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        winner_by_phase[str(row["phase"])][str(row["judge_winner"])] += 1
    token_totals = [row["deltas"]["tokens_total"] for row in rows]
    total_token_delta = _sum_complete_numbers(token_totals)
    dollar_deltas = [row["dollars_delta"] for row in rows]
    total_dollar_delta = _sum_complete_numbers(dollar_deltas)
    total_tool_delta = _sum_existing_numbers(row["deltas"]["tool_calls"] for row in rows)
    mcp_on_wins = _join_task_ids(rows, winner="mcp_on")
    mcp_off_wins = _join_task_ids(rows, winner="mcp_off")
    mcp_on_win_count = summary["judge_winners"].get("mcp_on", 0)
    mcp_off_win_count = summary["judge_winners"].get("mcp_off", 0)
    tie_count = summary["judge_winners"].get("tie", 0)
    judged_count = mcp_on_win_count + mcp_off_win_count + tie_count
    quality_resource_sentence = _quality_resource_sentence(
        mcp_on_win_count=mcp_on_win_count,
        mcp_off_win_count=mcp_off_win_count,
        tie_count=tie_count,
    )
    blocking_gap_sentence = _blocking_gap_sentence(
        rows,
        mcp_on_win_count=mcp_on_win_count,
        mcp_off_win_count=mcp_off_win_count,
        tie_count=tie_count,
        judged_count=judged_count,
    )
    tool_delta_sentence = _tool_delta_sentence(total_tool_delta)
    phase_rows = "\n".join(
        f"| {phase} | {counts.get('mcp_off', 0)} | {counts.get('mcp_on', 0)} | {counts.get('tie', 0)} |"
        for phase, counts in sorted(winner_by_phase.items())
    )
    available_cost_rows = sum(row.get("cost_status") == "available" for row in rows)
    available_token_rows = sum(_is_number(row["deltas"]["tokens_total"]) for row in rows)
    aspect_rows = _aspect_markdown_rows(summary["judge_aspect_winners"])
    return f"""# Trace Analysis - {run_id} - {run_date}

## Current Validation Status

This run completed the `{run_id}` A/B measurement: {summary['task_count']} paired tasks, {summary['arm_count']} Claude Code host runs, local SuperContext MCP server, LangSmith upload, pulled traces, paired deltas, and blinded quality judging.

The product signal is rubric-based, not a single scoreboard. Quality comes first: the judge preferred `mcp_off` overall on {summary['judge_winners'].get('mcp_off', 0)} tasks, `mcp_on` on {summary['judge_winners'].get('mcp_on', 0)} tasks, and marked {summary['judge_winners'].get('tie', 0)} ties. A cost, token, or latency win matters only after answer quality is at least tied.

| Phase | mcp_off wins | mcp_on wins | Ties |
|---|---:|---:|---:|
{phase_rows}

| Quality Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
{aspect_rows}

## Strongest Product-Value Signal

Cost data was available for {available_cost_rows} of {summary['task_count']} rows. Token data was available for {available_token_rows} of {summary['task_count']} rows. Aggregate deltas use `off_minus_on`, so positive values mean SuperContext used less of that resource than the non-MCP arm.

- Total dollar delta: `{_format_number(total_dollar_delta)}` in favor of `mcp_on` overall. This is `n/a` unless every paired row has cost data.
- Total token delta: `{_format_number(total_token_delta)}` in favor of `mcp_on` overall. This is `n/a` unless every paired row has token data.
- Positive dollar deltas appeared on {sum((row['dollars_delta'] or 0) > 0 for row in rows)} of {available_cost_rows} cost-available rows.

{quality_resource_sentence}

## Weakest Blocking Gap

{blocking_gap_sentence}

{tool_delta_sentence}

## Where MCP Helped

`mcp_on` won on {mcp_on_wins}. These should be inspected first because they are the success cases that show when the MCP surface is adding value.

## Where MCP Hurt

`mcp_off` won on {mcp_off_wins}. These are the priority failure cases. Do not optimize tokens or costs until these quality losses are understood.

## Next Recommended PR

Add a trace-inspection report that classifies each `mcp_on` loss into one of these buckets without using repo-specific keyword rules:

- MCP not used early enough
- MCP returned insufficient/ambiguous context
- MCP result was ignored or contradicted by later source search
- agent over-trusted partial KG context
- ordinary source search found evidence missing from KG

Expected movement: after classification, choose one repeated failure family and fix either host skill guidance, MCP response shape, or KG retrieval. Verification should rerun `{run_id}` and require quality movement first, with token/cost deltas reported only after quality is not worse.

## Verification Commands

```bash
.venv/bin/python -m source.scripts.pull_ab_traces --project supercontext-ab-eval --run-group-ids <18-run-group-ids> --limit 100 --out data/ab_runs/{run_id}/traces.jsonl
.venv/bin/python -m source.scripts.compute_ab_deltas --traces data/ab_runs/{run_id}/traces.jsonl --out data/ab_runs/{run_id}/deltas.jsonl
.venv/bin/python -m source.scripts.judge_ab_quality --judge-model {judge_model} --deltas data/ab_runs/{run_id}/deltas.jsonl --out data/ab_runs/{run_id}/judged-deltas.jsonl --seed {seed}
.venv/bin/python -m source.scripts.aggregate_ab_report --deltas data/ab_runs/{run_id}/judged-deltas.jsonl --out data/ab_runs/{run_id}/report
.venv/bin/python -m source.scripts.sanitize_ab_report --judged-deltas data/ab_runs/{run_id}/judged-deltas.jsonl --raw-report data/ab_runs/{run_id}/report/ab-report.json --out docs/evaluation/ab-runs/{run_id} --run-id {run_id} --date {run_date} --judge-model {judge_model} --seed {seed}
```
"""


def _quality_resource_sentence(*, mcp_on_win_count: int, mcp_off_win_count: int, tie_count: int) -> str:
    if mcp_on_win_count > mcp_off_win_count:
        return (
            "This says MCP improved judged answer quality on more tasks and can reduce spend or tokens in many cases. "
            "That is a positive product signal, but the task-level losses still gate any broad rollout claim."
        )
    if mcp_off_win_count > mcp_on_win_count:
        return (
            "This says MCP can reduce spend or tokens in some cases, but that signal is secondary because "
            "`mcp_off` won judged answer quality on more tasks."
        )
    if mcp_on_win_count or mcp_off_win_count or tie_count:
        return (
            "This says resource deltas are secondary: judged answer quality was tied overall, so the next decision "
            "depends on task-level quality and reliability."
        )
    return "This run has no judged quality winners yet, so resource deltas are diagnostic only."


def _blocking_gap_sentence(
    rows: list[dict[str, Any]],
    *,
    mcp_on_win_count: int,
    mcp_off_win_count: int,
    tie_count: int,
    judged_count: int,
) -> str:
    zero_mcp_rows = sum(row.get("mcp_on_tool_health", {}).get("attempts") == 0 for row in rows)
    non_winning_rows = mcp_off_win_count + tie_count
    if mcp_on_win_count > mcp_off_win_count:
        return (
            "The blocking gap is consistency, not trace capture. The installed skill and MCP server were available, "
            f"but `mcp_on` did not win {non_winning_rows} of {judged_count} judged tasks"
            f"{_zero_mcp_clause(zero_mcp_rows)}. The next work should classify the loss/tie rows before optimizing "
            "cost or latency."
        )
    return (
        "The blocking gap is skill/tool adoption quality, not trace capture. The installed skill and MCP server were "
        f"available, but `mcp_on` only won {mcp_on_win_count} of {judged_count} judged tasks"
        f"{_zero_mcp_clause(zero_mcp_rows)}. The likely failure pattern is that the host either used MCP too late, "
        "accepted partial KG context, or found better evidence through ordinary source inspection."
    )


def _zero_mcp_clause(zero_mcp_rows: int) -> str:
    if zero_mcp_rows:
        return f", and {zero_mcp_rows} `mcp_on` rows made zero MCP calls"
    return ""


def _tool_delta_sentence(total_tool_delta: int | float | None) -> str:
    if not _is_number(total_tool_delta):
        return "Total tool-call delta was `n/a`, so tool-use efficiency cannot be aggregated for this run."
    direction = "used fewer" if total_tool_delta > 0 else "used more" if total_tool_delta < 0 else "used the same number of"
    return (
        f"The report also shows aggregate tool-use behavior: total tool-call delta was "
        f"`{_format_number(total_tool_delta)}`, so `mcp_on` {direction} tool calls overall."
    )


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _sanitize_aspect_winners(value: Any) -> dict[str, str]:
    aspects = {}
    source = value if isinstance(value, dict) else {}
    for aspect in ("correctness", "evidence", "completeness", "actionability"):
        winner = source.get(aspect)
        aspects[aspect] = winner if winner in {"mcp_off", "mcp_on", "tie"} else "unknown"
    return aspects


def _aspect_winner_counts(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts = {}
    for aspect in ("correctness", "evidence", "completeness", "actionability"):
        counts[aspect] = dict(Counter(row["judge_aspect_winners"][aspect] for row in rows))
    return counts


def _aspect_markdown_rows(aspect_counts: dict[str, dict[str, int]]) -> str:
    return "\n".join(
        f"| {aspect} | {counts.get('mcp_off', 0)} | {counts.get('mcp_on', 0)} | "
        f"{counts.get('tie', 0)} | {counts.get('unknown', 0)} |"
        for aspect, counts in aspect_counts.items()
    )


def _round_number(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, 6)
        if rounded == 0:
            return 0
        return rounded
    return value


def _round_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _round_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_nested(item) for item in value]
    return _round_number(value)


def _sum_numbers(left: Any, right: Any) -> int | float | None:
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left + right
    return None


def _sum_existing_numbers(values: Any) -> int | float:
    total: int | float = 0
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += value
    return total


def _sum_complete_numbers(values: list[Any]) -> int | float | None:
    if not values:
        return 0
    if not all(_is_number(value) for value in values):
        return None
    return sum(values)


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _join_task_ids(rows: list[dict[str, Any]], *, winner: str) -> str:
    task_ids = [str(row["task_id"]) for row in rows if row["judge_winner"] == winner]
    if not task_ids:
        return "none"
    return ", ".join(task_ids)


if __name__ == "__main__":
    main()
