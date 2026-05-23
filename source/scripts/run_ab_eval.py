from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.eval.corpus import DEFAULT_QUERY_SET, EvalTask, default_v1_tasks, parse_query_set
from source.kg.eval.runner import RunnerConfig, run_single_task


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BetterContext MCP A/B evaluation tasks.")
    parser.add_argument("--query-set", default=str(DEFAULT_QUERY_SET), help="Product query set markdown path.")
    parser.add_argument("--snapshot", help="KG snapshot path. Required unless --print-tasks is used.")
    parser.add_argument("--host", choices=["claude_code"], default="claude_code")
    parser.add_argument("--tasks", default="default-v1", help="Comma-separated task IDs or default-v1.")
    parser.add_argument("--arms", default="mcp_on", help="PR1 supports exactly one arm: mcp_on or mcp_off.")
    parser.add_argument("--out", default="data/ab_runs/smoke", help="Output directory for local run records.")
    parser.add_argument("--seed", type=int, default=0, help="Execution seed. Does not alter default-v1 membership.")
    parser.add_argument("--model", default=None, help="Claude model for host-agent execution.")
    parser.add_argument("--mcp-url", default=None, help="BetterContext HTTP MCP URL for mcp_on runs.")
    parser.add_argument("--print-tasks", action="store_true", help="Print selected tasks and exit.")
    args = parser.parse_args()

    tasks = _select_tasks(query_set=Path(args.query_set), tasks_arg=args.tasks, seed=args.seed)
    if args.print_tasks:
        for task in tasks:
            print(f"{task.task_id}\t{task.difficulty}\t{task.phase}")
        return

    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if len(tasks) != 1:
        parser.error("PR1 supports exactly one task for execution; use --print-tasks for manifests")
    if len(arms) != 1:
        parser.error("PR1 supports exactly one arm for execution")
    arm = arms[0]
    if arm not in {"mcp_on", "mcp_off"}:
        parser.error("--arms must contain mcp_on or mcp_off")
    if not args.snapshot:
        parser.error("--snapshot is required unless --print-tasks is used")

    config_kwargs = {}
    if args.model:
        config_kwargs["model"] = args.model
    if args.mcp_url:
        config_kwargs["mcp_url"] = args.mcp_url
    config = RunnerConfig(**config_kwargs)
    record = run_single_task(
        tasks[0],
        arm=arm,  # type: ignore[arg-type]
        snapshot=args.snapshot,
        output_dir=args.out,
        random_seed=args.seed,
        config=config,
    )
    print(json.dumps(record.to_json(), sort_keys=True))


def _select_tasks(*, query_set: Path, tasks_arg: str, seed: int) -> list[EvalTask]:
    manifest_tasks = default_v1_tasks(query_set_path=query_set, seed=seed)
    if tasks_arg == "default-v1":
        return manifest_tasks

    tasks_by_id = {task.task_id: task for task in manifest_tasks}
    rows_by_id = {row.task_id: row for row in parse_query_set(query_set)}
    selected: list[EvalTask] = []
    for task_id in [item.strip() for item in tasks_arg.split(",") if item.strip()]:
        if task_id not in rows_by_id:
            raise SystemExit(f"Unknown task ID: {task_id}")
        task = tasks_by_id.get(task_id)
        if task is None:
            raise SystemExit(
                f"Task {task_id} is outside default-v1; PR1 only executes tasks with manifest phases"
            )
        selected.append(task)
    if not selected:
        raise SystemExit("--tasks must name at least one task")
    return selected


if __name__ == "__main__":
    main()
