from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from source.scripts.aggregate_ab_report import render_report
from source.scripts.compute_ab_deltas import compute_deltas, load_jsonl
from source.scripts.judge_ab_quality import judge_rows


# Workspace-local judge alias used by the A/B judge runner in this repo. Do
# not substitute a public model name here; if the provider rejects this alias,
# the gate should fail so the baseline is re-judged intentionally.
DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"
DEFAULT_PROTECTED_WINNERS = ("mcp_on", "tie")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a prior-loss quality-floor A/B gate by reusing cached mcp_off rows, "
            "recomputing mcp_on, judging quality, and failing on protected regressions."
        )
    )
    parser.add_argument("--snapshot", required=True, help="KG snapshot path.")
    parser.add_argument(
        "--baseline-judged-deltas",
        required=True,
        help="Baseline judged-deltas.jsonl. Rows selected for the gate must have judge_winner set.",
    )
    parser.add_argument(
        "--reuse-mcp-off-from",
        default=None,
        help="A/B run directory containing compatible cached mcp_off record.json files. Defaults to the baseline run dir.",
    )
    parser.add_argument("--out", required=True, help="Output A/B run directory for this gate.")
    parser.add_argument("--query-set", default=None, help="Optional product query set markdown path.")
    parser.add_argument("--fixture-overrides", default=None, help="Optional fixture overrides YAML.")
    parser.add_argument("--tasks", default=None, help="Comma-separated task IDs. Defaults to all tasks in baseline rows.")
    parser.add_argument("--model", default=None, help="Claude model for mcp_on host-agent execution.")
    parser.add_argument("--seed", type=int, default=0, help="A/B and judge seed.")
    parser.add_argument("--parallelism", type=int, default=1, help="run_ab_eval parallelism.")
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_JUDGE_MODEL,
        help=(
            "Judge model. Defaults to gpt-5.4-mini. Baseline judged rows selected for the gate must use "
            "the same judge model and --seed."
        ),
    )
    parser.add_argument(
        "--protected-baseline-winners",
        default=",".join(DEFAULT_PROTECTED_WINNERS),
        help="Comma-separated baseline winners that must not become mcp_off. Defaults to mcp_on,tie.",
    )
    args = parser.parse_args()

    baseline_rows = load_jsonl(Path(args.baseline_judged_deltas))
    task_ids = _selected_task_ids(baseline_rows, tasks_arg=args.tasks)
    selected_baseline_rows = _filter_rows_by_task_ids(baseline_rows, task_ids=task_ids)
    _validate_baseline_judge_contract(selected_baseline_rows, judge_model=args.judge_model, seed=args.seed)
    _validate_baseline_winners(selected_baseline_rows)
    out_dir = Path(args.out)
    reuse_dir = Path(args.reuse_mcp_off_from) if args.reuse_mcp_off_from else Path(args.baseline_judged_deltas).parent

    _run_ab_eval(
        snapshot=Path(args.snapshot),
        out_dir=out_dir,
        reuse_mcp_off_from=reuse_dir,
        task_ids=task_ids,
        query_set=Path(args.query_set) if args.query_set else None,
        fixture_overrides=Path(args.fixture_overrides) if args.fixture_overrides else None,
        model=args.model,
        seed=args.seed,
        parallelism=args.parallelism,
    )

    traces_path = out_dir / "traces.jsonl"
    deltas_path = out_dir / "deltas.jsonl"
    judged_path = out_dir / "judged-deltas.jsonl"
    _write_local_records_as_traces(out_dir, traces_path)
    deltas = compute_deltas(load_jsonl(traces_path))
    _write_jsonl(deltas_path, deltas)
    judged = judge_rows(deltas, judge_model=args.judge_model, seed=args.seed)
    _write_jsonl(judged_path, judged)
    render_report(judged, out_dir / "report")

    failures = quality_floor_failures(
        selected_baseline_rows,
        judged,
        protected_winners=_parse_winner_set(args.protected_baseline_winners),
    )
    if failures:
        failure_path = out_dir / "quality-floor-failures.json"
        failure_path.write_text(json.dumps(failures, indent=2, sort_keys=True), encoding="utf-8")
        raise SystemExit(f"Quality floor failed for {len(failures)} task(s); see {failure_path}")


def quality_floor_failures(
    baseline_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    protected_winners: set[str],
) -> list[dict[str, Any]]:
    baseline_by_task = _rows_by_task_id(baseline_rows)
    current_by_task = _rows_by_task_id(current_rows)
    failures = []
    for task_id, baseline in sorted(baseline_by_task.items()):
        baseline_winner = _winner(baseline)
        if baseline_winner not in protected_winners:
            continue
        current = current_by_task.get(task_id)
        if current is None:
            failures.append(
                {
                    "task_id": task_id,
                    "reason": "missing_current_row",
                    "baseline_winner": baseline_winner,
                    "current_winner": None,
                }
            )
            continue
        current_winner = _optional_winner(current)
        if current_winner is None:
            failures.append(
                {
                    "task_id": task_id,
                    "reason": "current_row_not_judged",
                    "baseline_winner": baseline_winner,
                    "current_winner": None,
                    "current_quality_verdict": current.get("quality_verdict"),
                    "current_judge_error": current.get("judge_error"),
                }
            )
            continue
        if current_winner == "mcp_off":
            failures.append(
                {
                    "task_id": task_id,
                    "reason": "protected_baseline_row_became_mcp_off_win",
                    "baseline_winner": baseline_winner,
                    "current_winner": current_winner,
                    "current_reasoning": current.get("judge_reasoning"),
                }
            )
    return failures


def _run_ab_eval(
    *,
    snapshot: Path,
    out_dir: Path,
    reuse_mcp_off_from: Path,
    task_ids: list[str],
    query_set: Path | None,
    fixture_overrides: Path | None,
    model: str | None,
    seed: int,
    parallelism: int,
) -> None:
    command = [
        sys.executable,
        "-m",
        "source.scripts.run_ab_eval",
        "--snapshot",
        str(snapshot),
        "--out",
        str(out_dir),
        "--tasks",
        ",".join(task_ids),
        "--arms",
        "mcp_on,mcp_off",
        "--reuse-mcp-off-from",
        str(reuse_mcp_off_from),
        "--seed",
        str(seed),
        "--parallelism",
        str(parallelism),
    ]
    if query_set is not None:
        command.extend(["--query-set", str(query_set)])
    if fixture_overrides is not None:
        command.extend(["--fixture-overrides", str(fixture_overrides)])
    if model is not None:
        command.extend(["--model", model])
    subprocess.run(command, check=True)


def _write_local_records_as_traces(run_dir: Path, out_path: Path) -> None:
    rows = []
    # run_ab_eval writes each arm at <out>/<run_group_id>/<arm>/record.json.
    # async_run_single_task writes recomputed mcp_on rows; cached mcp_off rows
    # are materialized to the same layout by _materialize_cached_mcp_off_record.
    for record_path in sorted(run_dir.glob("*/mcp_*/record.json")):
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"record JSON must be an object: {record_path}")
        rows.append(payload)
    if not rows:
        raise ValueError(f"no local record.json files found under {run_dir}")
    _write_jsonl(out_path, rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def _selected_task_ids(rows: list[dict[str, Any]], *, tasks_arg: str | None) -> list[str]:
    if tasks_arg:
        task_ids = [item.strip() for item in tasks_arg.split(",") if item.strip()]
    else:
        task_ids = [_required_task_id(row) for row in rows]
    deduped = list(dict.fromkeys(task_ids))
    if not deduped:
        raise ValueError("no task IDs selected")
    return deduped


def _rows_by_task_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = _required_task_id(row)
        if task_id in indexed:
            raise ValueError(f"duplicate judged row for task {task_id}")
        indexed[task_id] = row
    return indexed


def _filter_rows_by_task_ids(rows: list[dict[str, Any]], *, task_ids: list[str]) -> list[dict[str, Any]]:
    indexed = _rows_by_task_id(rows)
    missing = [task_id for task_id in task_ids if task_id not in indexed]
    if missing:
        raise ValueError(f"baseline judged rows are missing selected task ID(s): {', '.join(missing)}")
    return [indexed[task_id] for task_id in task_ids]


def _validate_baseline_judge_contract(rows: list[dict[str, Any]], *, judge_model: str, seed: int) -> None:
    mismatches = []
    for row in rows:
        task_id = _required_task_id(row)
        row_model = row.get("judge_model")
        row_seed = row.get("judge_prompt_seed")
        if row_model != judge_model or row_seed != seed:
            mismatches.append(
                {
                    "task_id": task_id,
                    "judge_model": row_model,
                    "judge_prompt_seed": row_seed,
                }
            )
    if mismatches:
        sample = ", ".join(
            f"{row['task_id']} model={row['judge_model']!r} seed={row['judge_prompt_seed']!r}"
            for row in mismatches[:5]
        )
        raise ValueError(
            "baseline judged rows must use the same judge model and seed as this gate "
            f"(expected model={judge_model!r}, seed={seed}); mismatches: {sample}"
        )


def _validate_baseline_winners(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        _winner(row)


def _required_task_id(row: dict[str, Any]) -> str:
    task_id = row.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("judged row missing task_id")
    return task_id.strip()


def _winner(row: dict[str, Any]) -> str:
    winner = _optional_winner(row)
    if winner is None:
        task_id = row.get("task_id")
        prefix = f"task {task_id}: " if isinstance(task_id, str) and task_id else ""
        raise ValueError(
            f"{prefix}judged row has invalid judge_winner: {row.get('judge_winner')!r}; "
            "run source.scripts.judge_ab_quality first and use a fully judged baseline."
        )
    return winner


def _optional_winner(row: dict[str, Any]) -> str | None:
    winner = row.get("judge_winner")
    return winner if winner in {"mcp_on", "mcp_off", "tie"} else None


def _parse_winner_set(value: str) -> set[str]:
    winners = {item.strip() for item in value.split(",") if item.strip()}
    unsupported = sorted(winners - set(DEFAULT_PROTECTED_WINNERS))
    if unsupported:
        raise ValueError(f"unsupported winner value(s): {', '.join(unsupported)}")
    if not winners:
        raise ValueError("--protected-baseline-winners must not be empty")
    return winners


if __name__ == "__main__":
    main()
