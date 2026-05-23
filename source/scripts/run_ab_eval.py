from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

from source.kg.eval.corpus import DEFAULT_QUERY_SET, EvalTask, default_v1_tasks, parse_query_set
from source.kg.eval.runner import Arm, RunRecord, RunnerConfig, run_single_task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SuperContext MCP A/B evaluation tasks.",
        epilog=(
            "Execution sets Claude Code SuperContext MCP registration before each arm and leaves "
            "SuperContext registered when the run completes."
        ),
    )
    parser.add_argument("--query-set", default=str(DEFAULT_QUERY_SET), help="Product query set markdown path.")
    parser.add_argument("--snapshot", help="KG snapshot path. Required unless --print-tasks is used.")
    parser.add_argument("--host", choices=["claude_code"], default="claude_code")
    parser.add_argument("--tasks", default="default-v1", help="Comma-separated task IDs or default-v1.")
    parser.add_argument("--arms", default="mcp_on,mcp_off", help="Comma-separated arms: mcp_on, mcp_off.")
    parser.add_argument("--out", default="data/ab_runs/smoke", help="Output directory for local run records.")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Deterministically permutes paired arm order. Does not alter default-v1 membership.",
    )
    parser.add_argument("--model", default=None, help="Claude model for host-agent execution.")
    parser.add_argument("--mcp-url", default=None, help="SuperContext HTTP MCP URL for mcp_on runs.")
    parser.add_argument("--upload-to-langsmith", action="store_true", help="Upload the local run record to LangSmith.")
    parser.add_argument("--print-tasks", action="store_true", help="Print selected tasks and exit.")
    args = parser.parse_args()

    tasks = _select_tasks(query_set=Path(args.query_set), tasks_arg=args.tasks, seed=args.seed)
    if args.print_tasks:
        for task in tasks:
            print(f"{task.task_id}\t{task.difficulty}\t{task.phase}")
        return

    arms = _parse_arms(args.arms)
    if not args.snapshot:
        parser.error("--snapshot is required unless --print-tasks is used")

    config_kwargs = {}
    if args.model:
        config_kwargs["model"] = args.model
    if args.mcp_url:
        config_kwargs["mcp_url"] = args.mcp_url
    config = RunnerConfig(**config_kwargs)
    records = _run_paired_tasks(
        tasks,
        arms=arms,
        snapshot=args.snapshot,
        output_dir=args.out,
        host=args.host,
        seed=args.seed,
        config=config,
    )
    for record in records:
        payload = record.to_json()
        if args.upload_to_langsmith:
            payload["langsmith_run_url"] = _upload_to_langsmith(record)
        print(json.dumps(payload, sort_keys=True))


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


def _parse_arms(arms_arg: str) -> list[Arm]:
    arms = [arm.strip() for arm in arms_arg.split(",") if arm.strip()]
    if not arms:
        raise SystemExit("--arms must contain at least one arm")
    unsupported = [arm for arm in arms if arm not in {"mcp_on", "mcp_off"}]
    if unsupported:
        raise SystemExit(f"--arms contains unsupported value(s): {', '.join(unsupported)}")
    if len(set(arms)) != len(arms):
        raise SystemExit("--arms must not contain duplicate arms")
    return cast(list[Arm], arms)


def _run_paired_tasks(
    tasks: list[EvalTask],
    *,
    arms: list[Arm],
    snapshot: str | Path,
    output_dir: str | Path,
    host: str,
    seed: int,
    config: RunnerConfig,
    run_task=run_single_task,
    run_host_command=None,
    group_id_factory=uuid4,
) -> list[RunRecord]:
    if run_host_command is None:
        run_host_command = _run_host_config_command
    rng = random.Random(seed)
    records: list[RunRecord] = []
    for task in tasks:
        run_group_id = str(group_id_factory())
        ordered_arms = list(arms)
        rng.shuffle(ordered_arms)
        for arm in ordered_arms:
            pre_command = _pre_arm_host_config_command(arm=arm, host=host, mcp_url=config.mcp_url)
            post_command = _post_arm_host_config_command(arm=arm, host=host, mcp_url=config.mcp_url)
            primary_error: BaseException | None = None
            try:
                run_host_command(pre_command)
                record = run_task(
                    task,
                    arm=arm,
                    snapshot=snapshot,
                    output_dir=output_dir,
                    host=host,
                    run_group_id=run_group_id,
                    random_seed=seed,
                    pre_arm_host_config_command=pre_command,
                    post_arm_host_config_command=post_command,
                    config=config,
                )
                if arm == "mcp_off" and record.mcp_tools_called:
                    raise RuntimeError("mcp_off run unexpectedly called SuperContext MCP tools")
                records.append(record)
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                if post_command:
                    try:
                        run_host_command(post_command)
                    except Exception as cleanup_error:
                        if primary_error is not None:
                            primary_error.add_note(f"post-arm host config command failed: {cleanup_error}")
                        else:
                            raise
    return records


def _pre_arm_host_config_command(*, arm: Arm, host: str, mcp_url: str) -> tuple[str, ...]:
    if host != "claude_code":
        raise ValueError(f"Unsupported A/B host: {host}")
    command = (
        sys.executable,
        "-m",
        "source.scripts.register_mcp",
        "--agent",
        "claude",
        "--on-error",
        "error",
        "--url",
        mcp_url,
    )
    if arm == "mcp_off":
        return (
            sys.executable,
            "-m",
            "source.scripts.register_mcp",
            "--agent",
            "claude",
            "--on-error",
            "error",
            "--remove",
        )
    return command


def _post_arm_host_config_command(*, arm: Arm, host: str, mcp_url: str) -> tuple[str, ...]:
    if host != "claude_code":
        raise ValueError(f"Unsupported A/B host: {host}")
    if arm == "mcp_off":
        return (
            sys.executable,
            "-m",
            "source.scripts.register_mcp",
            "--agent",
            "claude",
            "--on-error",
            "error",
            "--url",
            mcp_url,
        )
    return ()


def _run_host_config_command(command: tuple[str, ...]) -> None:
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(f"host config command failed with exit code {exc.returncode}{detail}") from exc


def _upload_to_langsmith(record: RunRecord) -> str:
    if not record.host_session_log_path:
        raise RuntimeError("messages log not captured; cannot upload A/B eval run to LangSmith")

    from source.kg.eval.langsmith_emitter import emit_run

    return emit_run(record, Path(record.host_session_log_path))


if __name__ == "__main__":
    main()
