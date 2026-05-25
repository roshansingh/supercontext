from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import json
import random
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast, get_origin, get_type_hints
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen
from uuid import uuid4

from source.kg.eval.corpus import DEFAULT_QUERY_SET, EvalTask, default_v1_tasks, parse_query_set
from source.kg.eval.runner import Arm, RunRecord, RunnerConfig, run_single_task


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SuperContext MCP A/B evaluation tasks.",
        epilog=(
            "When mcp_on is selected without --mcp-url, the harness starts a local MCP server "
            "for the supplied snapshot. Sequential execution still sets Claude Code "
            "SuperContext MCP registration before each arm. Parallel execution uses per-run "
            "SDK MCP config and does not mutate shared Claude registration."
        ),
    )
    parser.add_argument("--query-set", default=str(DEFAULT_QUERY_SET), help="Product query set markdown path.")
    parser.add_argument("--snapshot", help="KG snapshot path. Required unless --print-tasks is used.")
    parser.add_argument(
        "--fixture-overrides",
        default=None,
        help="Optional YAML file with private fixture bindings and fixture_input overrides keyed by task ID.",
    )
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
    parser.add_argument(
        "--reuse-mcp-off-from",
        default=None,
        help=(
            "Existing A/B run directory to reuse compatible mcp_off record.json files from. "
            "Use only for iterative MCP-on experiments; omit for fresh merge-gating runs. "
            "Only cached mcp_off host calls are skipped; mcp_on still applies its normal host setup."
        ),
    )
    parser.add_argument(
        "--parallelism",
        type=_positive_int,
        default=1,
        help=(
            "Maximum concurrent arm runs. Values greater than 1 skip shared Claude MCP "
            "registration and rely on per-run SDK MCP config to avoid cross-arm races."
        ),
    )
    parser.add_argument("--upload-to-langsmith", action="store_true", help="Upload the local run record to LangSmith.")
    parser.add_argument("--print-tasks", action="store_true", help="Print selected tasks and exit.")
    args = parser.parse_args()

    tasks = _select_tasks(
        query_set=Path(args.query_set),
        tasks_arg=args.tasks,
        seed=args.seed,
        fixture_overrides_path=Path(args.fixture_overrides) if args.fixture_overrides else None,
    )
    if args.print_tasks:
        for task in tasks:
            print(f"{task.task_id}\t{task.difficulty}\t{task.phase}")
        return

    arms = _parse_arms(args.arms)
    if not args.snapshot:
        parser.error("--snapshot is required unless --print-tasks is used")

    with _managed_mcp_url(snapshot=args.snapshot, arms=arms, explicit_mcp_url=args.mcp_url) as mcp_url:
        config_kwargs = {}
        if args.model:
            config_kwargs["model"] = args.model
        if mcp_url:
            config_kwargs["mcp_url"] = mcp_url
        config = RunnerConfig(**config_kwargs)
        records = _run_paired_tasks(
            tasks,
            arms=arms,
            snapshot=args.snapshot,
            output_dir=args.out,
            host=args.host,
            seed=args.seed,
            config=config,
            parallelism=args.parallelism,
            reuse_mcp_off_from=Path(args.reuse_mcp_off_from) if args.reuse_mcp_off_from else None,
        )
    for record in records:
        payload = record.to_json()
        if args.upload_to_langsmith:
            payload["langsmith_run_url"] = _upload_to_langsmith(record)
        print(json.dumps(payload, sort_keys=True))


def _select_tasks(
    *,
    query_set: Path,
    tasks_arg: str,
    seed: int,
    fixture_overrides_path: Path | None = None,
) -> list[EvalTask]:
    manifest_tasks = default_v1_tasks(
        query_set_path=query_set,
        fixture_overrides_path=fixture_overrides_path,
        seed=seed,
    )
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


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--parallelism must be at least 1")
    return parsed


@contextmanager
def _managed_mcp_url(
    *,
    snapshot: str | Path,
    arms: list[Arm],
    explicit_mcp_url: str | None,
):
    if "mcp_on" not in arms:
        yield explicit_mcp_url
        return
    if explicit_mcp_url:
        _wait_for_mcp_health(explicit_mcp_url, timeout_seconds=10.0)
        yield explicit_mcp_url
        return
    with _local_mcp_server(snapshot) as mcp_url:
        yield mcp_url


@contextmanager
def _local_mcp_server(
    snapshot: str | Path,
    *,
    port_factory=None,
    popen=subprocess.Popen,
    health_check=None,
):
    port = (port_factory or _free_loopback_port)()
    mcp_url = f"http://127.0.0.1:{port}/mcp"
    command = (
        sys.executable,
        "-m",
        "source.scripts.mcp_server",
        "--snapshot",
        str(snapshot),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    )
    process = popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    checker = health_check or _wait_for_mcp_health
    try:
        checker(mcp_url, process=process)
        yield mcp_url
    finally:
        _stop_mcp_server(process)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_mcp_health(mcp_url: str, *, timeout_seconds: float = 10.0, process=None) -> None:
    health_url = _mcp_health_url(mcp_url)
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process is not None:
            returncode = process.poll()
            if returncode is not None:
                detail = _read_process_stderr(process)
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"SuperContext MCP server exited before becoming healthy{suffix}")
        try:
            with urlopen(health_url, timeout=1.0) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("status") == "ok":
                        return
                    last_error = f"unexpected health payload: {payload!r}"
                else:
                    last_error = f"unexpected HTTP status {response.status}"
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise RuntimeError(f"SuperContext MCP server is not healthy at {health_url}: {last_error or 'timed out'}")


def _mcp_health_url(mcp_url: str) -> str:
    parsed = urlsplit(mcp_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"SuperContext MCP URL must be HTTP(S) with a host: {mcp_url!r}")
    return urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))


def _stop_mcp_server(process) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _read_process_stderr(process) -> str:
    stderr = getattr(process, "stderr", None)
    if stderr is None:
        return ""
    try:
        return (stderr.read() or "").strip()
    except OSError:
        return ""


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
    parallelism: int = 1,
    reuse_mcp_off_from: Path | None = None,
) -> list[RunRecord]:
    if parallelism < 1:
        raise ValueError("parallelism must be at least 1")
    if run_host_command is None:
        run_host_command = _run_host_config_command
    cached_mcp_off = (
        _load_cached_mcp_off_records(
            reuse_mcp_off_from,
            tasks=tasks,
            snapshot=snapshot,
            host=host,
            config=config,
        )
        if reuse_mcp_off_from is not None
        else {}
    )
    rng = random.Random(seed)
    jobs: list[tuple[int, EvalTask, str, Arm]] = []
    for task in tasks:
        run_group_id = str(group_id_factory())
        ordered_arms = list(arms)
        rng.shuffle(ordered_arms)
        for arm in ordered_arms:
            jobs.append((len(jobs), task, run_group_id, arm))
    if parallelism > 1:
        return _run_paired_tasks_parallel(
            jobs,
            snapshot=snapshot,
            output_dir=output_dir,
            host=host,
            seed=seed,
            config=config,
            run_task=run_task,
            parallelism=parallelism,
            cached_mcp_off=cached_mcp_off,
        )

    records: list[RunRecord] = []
    for _, task, run_group_id, arm in jobs:
        if arm == "mcp_off" and task.task_id in cached_mcp_off:
            records.append(
                _materialize_cached_mcp_off_record(
                    cached_mcp_off[task.task_id],
                    output_dir=output_dir,
                    run_group_id=run_group_id,
                    random_seed=seed,
                )
            )
            continue
        pre_command = _pre_arm_host_config_command(arm=arm, host=host, mcp_url=config.mcp_url)
        post_command = _post_arm_host_config_command(arm=arm, host=host, mcp_url=config.mcp_url)
        primary_error: BaseException | None = None
        try:
            run_host_command(pre_command)
            record = _run_arm_task(
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
                run_task=run_task,
            )
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


def _run_paired_tasks_parallel(
    jobs: list[tuple[int, EvalTask, str, Arm]],
    *,
    snapshot: str | Path,
    output_dir: str | Path,
    host: str,
    seed: int,
    config: RunnerConfig,
    run_task,
    parallelism: int,
    cached_mcp_off: dict[str, RunRecord],
) -> list[RunRecord]:
    records_by_index: dict[int, RunRecord] = {}
    pending_jobs = []
    for index, task, run_group_id, arm in jobs:
        if arm == "mcp_off" and task.task_id in cached_mcp_off:
            records_by_index[index] = _materialize_cached_mcp_off_record(
                cached_mcp_off[task.task_id],
                output_dir=output_dir,
                run_group_id=run_group_id,
                random_seed=seed,
            )
        else:
            pending_jobs.append((index, task, run_group_id, arm))
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = {
            executor.submit(
                _run_arm_task,
                task,
                arm=arm,
                snapshot=snapshot,
                output_dir=output_dir,
                host=host,
                run_group_id=run_group_id,
                random_seed=seed,
                pre_arm_host_config_command=(),
                post_arm_host_config_command=(),
                config=config,
                run_task=run_task,
            ): index
            for index, task, run_group_id, arm in pending_jobs
        }
        try:
            for future in as_completed(futures):
                index = futures[future]
                records_by_index[index] = future.result()
        except BaseException:
            for future in futures:
                # Running arms cannot be cancelled; the executor context waits for them.
                # This only prevents queued arms from starting after the first failure.
                future.cancel()
            raise
    return [records_by_index[index] for index in range(len(jobs))]


def _run_arm_task(
    task: EvalTask,
    *,
    arm: Arm,
    snapshot: str | Path,
    output_dir: str | Path,
    host: str,
    run_group_id: str,
    random_seed: int,
    pre_arm_host_config_command: tuple[str, ...],
    post_arm_host_config_command: tuple[str, ...],
    config: RunnerConfig,
    run_task,
) -> RunRecord:
    record = run_task(
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
    if arm == "mcp_off" and record.mcp_tools_called:
        raise RuntimeError("mcp_off run unexpectedly called SuperContext MCP tools")
    return record


def _load_cached_mcp_off_records(
    cache_dir: Path,
    *,
    tasks: list[EvalTask],
    snapshot: str | Path,
    host: str,
    config: RunnerConfig,
) -> dict[str, RunRecord]:
    if not cache_dir.exists():
        raise ValueError(f"--reuse-mcp-off-from does not exist: {cache_dir}")
    expected_tasks = {task.task_id: task for task in tasks}
    records: dict[str, RunRecord] = {}
    for record_path in sorted(cache_dir.glob("*/mcp_off/record.json")):
        record = _read_run_record(record_path)
        if record.task_id not in expected_tasks:
            continue
        if record.task_id in records:
            raise ValueError(f"Multiple cached mcp_off records found for task {record.task_id}")
        _validate_cached_mcp_off_record(
            record,
            record_path=record_path,
            task=expected_tasks[record.task_id],
            snapshot=snapshot,
            host=host,
            config=config,
        )
        records[record.task_id] = record

    missing = sorted(set(expected_tasks) - set(records))
    if missing:
        raise ValueError(f"Missing cached mcp_off record(s) for task ID(s): {', '.join(missing)}")
    return records


def _read_run_record(record_path: Path) -> RunRecord:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("record JSON must be an object")
        return _run_record_from_payload(payload)
    except TypeError as exc:
        raise ValueError(f"Cached run record has incompatible schema: {record_path}") from exc


def _run_record_from_payload(payload: dict[str, object]) -> RunRecord:
    normalized = dict(payload)
    type_hints = get_type_hints(RunRecord)
    for field_name, field_type in type_hints.items():
        if get_origin(field_type) is not tuple or field_name not in normalized:
            continue
        value = normalized[field_name]
        if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"Cached run record field {field_name!r} must be a list of strings")
        normalized[field_name] = tuple(value)
    return RunRecord(**normalized)


def _validate_cached_mcp_off_record(
    record: RunRecord,
    *,
    record_path: Path,
    task: EvalTask,
    snapshot: str | Path,
    host: str,
    config: RunnerConfig,
) -> None:
    if record.arm != "mcp_off":
        raise ValueError(f"Cached record is not mcp_off: {record_path}")
    if record.mcp_tools_called:
        raise ValueError(f"Cached mcp_off record unexpectedly used MCP tools: {record_path}")
    expected = {
        "phase": task.phase,
        "difficulty": task.difficulty,
        "repo_fixture": task.fixture,
        "task_prompt": task.prompt,
        "host": host,
        "model": config.model,
    }
    actual = {
        "phase": record.phase,
        "difficulty": record.difficulty,
        "repo_fixture": record.repo_fixture,
        "task_prompt": record.task_prompt,
        "host": record.host,
        "model": record.model,
    }
    for field, expected_value in expected.items():
        if actual[field] != expected_value:
            raise ValueError(
                f"Cached mcp_off record {record_path} has incompatible {field}: "
                f"{actual[field]!r} != {expected_value!r}"
            )
    if _resolved_path(record.snapshot_path) != _resolved_path(snapshot):
        raise ValueError(
            f"Cached mcp_off record {record_path} has incompatible snapshot: "
            f"{record.snapshot_path!r} != {str(snapshot)!r}"
        )


def _materialize_cached_mcp_off_record(
    cached: RunRecord,
    *,
    output_dir: str | Path,
    run_group_id: str,
    random_seed: int,
) -> RunRecord:
    arm_dir = Path(output_dir) / run_group_id / "mcp_off"
    if arm_dir.exists():
        raise ValueError(f"A/B eval output already exists for cached mcp_off arm: {arm_dir}")
    arm_dir.mkdir(parents=True)
    if not cached.host_session_log_path:
        raise ValueError("Cached mcp_off record is missing host_session_log_path")
    source_log = Path(cached.host_session_log_path).expanduser()
    if not source_log.exists():
        raise ValueError(f"Cached mcp_off host session log does not exist: {source_log}")
    target_log = arm_dir / "messages.jsonl"
    shutil.copyfile(source_log, target_log)
    host_session_log_path = str(target_log)
    record = replace(
        cached,
        run_group_id=run_group_id,
        random_seed=random_seed,
        pre_arm_host_config_command=(),
        post_arm_host_config_command=(),
        host_session_log_path=host_session_log_path,
    )
    (arm_dir / "record.json").write_text(json.dumps(record.to_json(), indent=2, sort_keys=True), encoding="utf-8")
    return record


def _resolved_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


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
