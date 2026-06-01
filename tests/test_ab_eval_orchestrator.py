from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.eval import runner as eval_runner
from source.kg.eval.corpus import CorpusRow, EvalTask
from source.kg.eval.runner import (
    DEFAULT_HARNESS_VERSION,
    Arm,
    RunRecord,
    RunnerConfig,
    async_run_single_task,
    _allowed_tools,
    _claude_extra_args,
    _incomplete_background_task_ids,
    _mcp_packet_navigation_stats,
    _mcp_saved_result_paths,
    _mcp_tool_observations,
    _raise_for_host_error_messages,
    _raise_for_mcp_tool_failures,
    render_task_prompt,
    _tool_calls,
)
from source.scripts.run_ab_eval import (
    _local_mcp_server,
    _managed_mcp_url,
    _mcp_health_url,
    _parse_arms,
    _positive_int,
    _post_arm_host_config_command,
    _pre_arm_host_config_command,
    _read_run_record,
    _run_host_config_command,
    _run_paired_tasks,
)


class AbEvalOrchestratorTest(unittest.TestCase):
    def test_paired_tasks_share_group_randomize_order_and_record_host_commands(self) -> None:
        task = _task()
        commands: list[tuple[str, ...]] = []
        calls: list[dict[str, object]] = []

        def fake_run_task(
            task_arg: EvalTask,
            *,
            arm: str,
            snapshot: str | Path,
            output_dir: str | Path,
            host: str,
            run_group_id: str,
            random_seed: int,
            pre_arm_host_config_command: tuple[str, ...],
            post_arm_host_config_command: tuple[str, ...],
            config: RunnerConfig,
        ) -> RunRecord:
            calls.append(
                {
                    "task": task_arg,
                    "arm": arm,
                    "snapshot": snapshot,
                    "output_dir": output_dir,
                    "host": host,
                    "run_group_id": run_group_id,
                    "random_seed": random_seed,
                    "config": config,
                    "pre": pre_arm_host_config_command,
                    "post": post_arm_host_config_command,
                }
            )
            return _record(
                task=task_arg,
                arm=arm,
                run_group_id=run_group_id,
                pre=pre_arm_host_config_command,
                post=post_arm_host_config_command,
            )

        records = _run_paired_tasks(
            [task],
            arms=["mcp_on", "mcp_off"],
            snapshot="snapshot-dir",
            output_dir="out-dir",
            host="claude_code",
            seed=1,
            config=RunnerConfig(model="test-model"),
            run_task=fake_run_task,
            run_host_command=commands.append,
            group_id_factory=lambda: "group-1",
        )

        self.assertEqual({record.run_group_id for record in records}, {"group-1"})
        self.assertEqual({record.arm for record in records}, {"mcp_on", "mcp_off"})
        self.assertEqual(len(calls), 2)
        self.assertEqual([call["arm"] for call in calls], ["mcp_off", "mcp_on"])
        self.assertEqual({call["task"] for call in calls}, {task})
        self.assertEqual({call["snapshot"] for call in calls}, {"snapshot-dir"})
        self.assertEqual({call["output_dir"] for call in calls}, {"out-dir"})
        self.assertEqual({call["host"] for call in calls}, {"claude_code"})
        self.assertEqual({call["random_seed"] for call in calls}, {1})
        self.assertEqual({call["config"].model for call in calls}, {"test-model"})  # type: ignore[union-attr]

        off_record = next(record for record in records if record.arm == "mcp_off")
        on_record = next(record for record in records if record.arm == "mcp_on")
        self.assertEqual(off_record.mcp_tools_called, [])
        self.assertIn("--remove", off_record.pre_arm_host_config_command)
        self.assertNotIn("--remove", off_record.post_arm_host_config_command)
        self.assertNotIn("--remove", on_record.pre_arm_host_config_command)
        self.assertEqual(on_record.post_arm_host_config_command, ())

        expected_commands = []
        for call in calls:
            expected_commands.append(call["pre"])
            if call["post"]:
                expected_commands.append(call["post"])
        self.assertEqual(commands, expected_commands)

    def test_parallel_paired_tasks_skip_shared_registration_and_keep_grouping(self) -> None:
        task_a = _task("Q003")
        task_b = _task("Q016")
        commands: list[tuple[str, ...]] = []
        calls: list[dict[str, object]] = []

        def fake_run_task(
            task_arg: EvalTask,
            *,
            arm: str,
            snapshot: str | Path,
            output_dir: str | Path,
            host: str,
            run_group_id: str,
            random_seed: int,
            pre_arm_host_config_command: tuple[str, ...],
            post_arm_host_config_command: tuple[str, ...],
            config: RunnerConfig,
        ) -> RunRecord:
            calls.append(
                {
                    "task_id": task_arg.task_id,
                    "arm": arm,
                    "run_group_id": run_group_id,
                    "pre": pre_arm_host_config_command,
                    "post": post_arm_host_config_command,
                }
            )
            return _record(
                task=task_arg,
                arm=arm,
                run_group_id=run_group_id,
                pre=pre_arm_host_config_command,
                post=post_arm_host_config_command,
            )

        records = _run_paired_tasks(
            [task_a, task_b],
            arms=["mcp_on", "mcp_off"],
            snapshot="snapshot-dir",
            output_dir="out-dir",
            host="claude_code",
            seed=1,
            config=RunnerConfig(),
            run_task=fake_run_task,
            run_host_command=commands.append,
            group_id_factory=iter(["group-1", "group-2"]).__next__,
            parallelism=2,
        )

        self.assertEqual(commands, [])
        self.assertEqual([record.task_id for record in records], ["Q003", "Q003", "Q016", "Q016"])
        self.assertEqual({record.run_group_id for record in records[:2]}, {"group-1"})
        self.assertEqual({record.run_group_id for record in records[2:]}, {"group-2"})
        self.assertEqual({record.arm for record in records[:2]}, {"mcp_on", "mcp_off"})
        self.assertEqual({record.arm for record in records[2:]}, {"mcp_on", "mcp_off"})
        self.assertTrue(all(call["pre"] == () and call["post"] == () for call in calls))

    def test_parallel_mcp_off_rejects_supercontext_tool_calls_without_registration_cleanup(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_task(
            task_arg: EvalTask,
            *,
            arm: str,
            snapshot: str | Path,
            output_dir: str | Path,
            host: str,
            run_group_id: str,
            random_seed: int,
            pre_arm_host_config_command: tuple[str, ...],
            post_arm_host_config_command: tuple[str, ...],
            config: RunnerConfig,
        ) -> RunRecord:
            return _record(
                task=task_arg,
                arm=arm,
                run_group_id=run_group_id,
                pre=pre_arm_host_config_command,
                post=post_arm_host_config_command,
                mcp_tools=["mcp__supercontext__planning_context"],
            )

        with self.assertRaisesRegex(RuntimeError, "mcp_off"):
            _run_paired_tasks(
                [_task()],
                arms=["mcp_off"],
                snapshot="snapshot-dir",
                output_dir="out-dir",
                host="claude_code",
                seed=0,
                config=RunnerConfig(),
                run_task=fake_run_task,
                run_host_command=commands.append,
                group_id_factory=lambda: "group-1",
                parallelism=2,
            )

        self.assertEqual(commands, [])

    def test_run_record_stores_expanded_task_prompt(self) -> None:
        captured_prompts: list[str] = []

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

        class ResultMessage:
            def __init__(self, result: str) -> None:
                self.result = result

        class ClaudeSDKClient:
            def __init__(self, options: ClaudeAgentOptions) -> None:
                self.options = options

            async def __aenter__(self) -> "ClaudeSDKClient":
                return self

            async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
                return None

            async def query(self, prompt: str) -> None:
                captured_prompts.append(prompt)

            async def receive_response(self):
                yield ResultMessage("final answer")

        fake_sdk = types.SimpleNamespace(
            ClaudeAgentOptions=ClaudeAgentOptions,
            ClaudeSDKClient=ClaudeSDKClient,
            ResultMessage=ResultMessage,
        )

        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {"claude_agent_sdk": fake_sdk}):
            root = Path(tmp)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            output = root / "out"
            task = _task()

            record = asyncio.run(
                async_run_single_task(
                    task,
                    arm="mcp_on",
                    snapshot=snapshot,
                    output_dir=output,
                    run_group_id="group-1",
                    config=RunnerConfig(model="test-model", claude_cli_path="/bin/echo"),
                )
            )

            stored = json.loads((output / "group-1" / "mcp_on" / "record.json").read_text(encoding="utf-8"))

        self.assertEqual(captured_prompts, [record.task_prompt])
        self.assertEqual(stored["task_prompt"], record.task_prompt)
        self.assertIn("Run this SuperContext A/B evaluation task.", record.task_prompt)
        self.assertIn("Snapshot path:", record.task_prompt)
        self.assertIn("SuperContext MCP skill routing guidance", record.task_prompt)
        self.assertIn("User question:\nWho calls load_model?", record.task_prompt)
        self.assertNotEqual(record.task_prompt, task.prompt)

    def test_reuse_mcp_off_from_cache_materializes_record_and_skips_host_run(self) -> None:
        task = _task()
        commands: list[tuple[str, ...]] = []
        calls: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_arm_dir = root / "cache" / "old-group" / "mcp_off"
            cache_arm_dir.mkdir(parents=True)
            cached_messages = cache_arm_dir / "messages.jsonl"
            cached_messages.write_text('{"cached": true}\n', encoding="utf-8")
            cached_payload = _record(
                task=task,
                arm="mcp_off",
                run_group_id="old-group",
                pre=("--remove",),
                post=("restore",),
            ).to_json()
            cached_payload["host_session_log_path"] = str(cached_messages)
            (cache_arm_dir / "record.json").write_text(json.dumps(cached_payload), encoding="utf-8")

            def fake_run_task(
                task_arg: EvalTask,
                *,
                arm: str,
                snapshot: str | Path,
                output_dir: str | Path,
                host: str,
                run_group_id: str,
                random_seed: int,
                pre_arm_host_config_command: tuple[str, ...],
                post_arm_host_config_command: tuple[str, ...],
                config: RunnerConfig,
            ) -> RunRecord:
                calls.append(arm)
                return _record(
                    task=task_arg,
                    arm=arm,
                    run_group_id=run_group_id,
                    pre=pre_arm_host_config_command,
                    post=post_arm_host_config_command,
                )

            records = _run_paired_tasks(
                [task],
                arms=["mcp_on", "mcp_off"],
                snapshot="snapshot-dir",
                output_dir=root / "out",
                host="claude_code",
                seed=1,
                config=RunnerConfig(model="test-model"),
                run_task=fake_run_task,
                run_host_command=commands.append,
                group_id_factory=lambda: "new-group",
                reuse_mcp_off_from=root / "cache",
            )

            self.assertEqual(calls, ["mcp_on"])
            self.assertFalse(any("--remove" in command for command in commands))
            self.assertEqual({record.arm for record in records}, {"mcp_on", "mcp_off"})
            cached_record = next(record for record in records if record.arm == "mcp_off")
            self.assertEqual(cached_record.run_group_id, "new-group")
            self.assertEqual(cached_record.pre_arm_host_config_command, ())
            self.assertEqual(cached_record.post_arm_host_config_command, ())
            self.assertEqual(Path(cached_record.host_session_log_path).read_text(encoding="utf-8"), '{"cached": true}\n')
            self.assertTrue((root / "out" / "new-group" / "mcp_off" / "record.json").exists())

    def test_reuse_mcp_off_from_cache_rejects_missing_session_log(self) -> None:
        task = _task()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_arm_dir = root / "cache" / "old-group" / "mcp_off"
            cache_arm_dir.mkdir(parents=True)
            cached_payload = _record(task=task, arm="mcp_off", run_group_id="old-group", pre=(), post=()).to_json()
            cached_payload["host_session_log_path"] = str(cache_arm_dir / "missing-messages.jsonl")
            (cache_arm_dir / "record.json").write_text(json.dumps(cached_payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "host session log does not exist"):
                _run_paired_tasks(
                    [task],
                    arms=["mcp_off"],
                    snapshot="snapshot-dir",
                    output_dir=root / "out",
                    host="claude_code",
                    seed=1,
                    config=RunnerConfig(model="test-model"),
                    run_task=lambda *args, **kwargs: self.fail("cache hit should skip host run"),
                    run_host_command=lambda command: self.fail(f"unexpected host command: {command}"),
                    group_id_factory=lambda: "new-group",
                    reuse_mcp_off_from=root / "cache",
                )

    def test_reuse_mcp_off_from_cache_rejects_raw_task_prompt_record(self) -> None:
        task = _task()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_arm_dir = root / "cache" / "old-group" / "mcp_off"
            cache_arm_dir.mkdir(parents=True)
            cached_messages = cache_arm_dir / "messages.jsonl"
            cached_messages.write_text('{"cached": true}\n', encoding="utf-8")
            cached_payload = _record(task=task, arm="mcp_off", run_group_id="old-group", pre=(), post=()).to_json()
            cached_payload["task_prompt"] = task.prompt
            cached_payload["host_session_log_path"] = str(cached_messages)
            (cache_arm_dir / "record.json").write_text(json.dumps(cached_payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "incompatible task_prompt"):
                _run_paired_tasks(
                    [task],
                    arms=["mcp_off"],
                    snapshot="snapshot-dir",
                    output_dir=root / "out",
                    host="claude_code",
                    seed=1,
                    config=RunnerConfig(model="test-model"),
                    run_task=lambda *args, **kwargs: self.fail("cache hit should skip host run"),
                    run_host_command=lambda command: self.fail(f"unexpected host command: {command}"),
                    group_id_factory=lambda: "new-group",
                    reuse_mcp_off_from=root / "cache",
                )

    def test_reuse_mcp_off_from_cache_rejects_stale_harness_version(self) -> None:
        task = _task()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_arm_dir = root / "cache" / "old-group" / "mcp_off"
            cache_arm_dir.mkdir(parents=True)
            cached_messages = cache_arm_dir / "messages.jsonl"
            cached_messages.write_text('{"cached": true}\n', encoding="utf-8")
            cached_payload = _record(task=task, arm="mcp_off", run_group_id="old-group", pre=(), post=()).to_json()
            cached_payload["harness_version"] = "ab-eval-v1"
            cached_payload["host_session_log_path"] = str(cached_messages)
            (cache_arm_dir / "record.json").write_text(json.dumps(cached_payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "incompatible harness_version"):
                _run_paired_tasks(
                    [task],
                    arms=["mcp_off"],
                    snapshot="snapshot-dir",
                    output_dir=root / "out",
                    host="claude_code",
                    seed=1,
                    config=RunnerConfig(model="test-model"),
                    run_task=lambda *args, **kwargs: self.fail("cache hit should skip host run"),
                    run_host_command=lambda command: self.fail(f"unexpected host command: {command}"),
                    group_id_factory=lambda: "new-group",
                    reuse_mcp_off_from=root / "cache",
                )

    def test_read_run_record_restores_tuple_command_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "record.json"
            payload = _record(
                task=_task(),
                arm="mcp_off",
                run_group_id="group-1",
                pre=("claude", "mcp", "remove"),
                post=("claude", "mcp", "add"),
            ).to_json()
            record_path.write_text(json.dumps(payload), encoding="utf-8")

            record = _read_run_record(record_path)

        self.assertEqual(record.pre_arm_host_config_command, ("claude", "mcp", "remove"))
        self.assertEqual(record.post_arm_host_config_command, ("claude", "mcp", "add"))

    def test_mcp_off_rejects_supercontext_tool_calls_and_restores_registration(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_run_task(
            task_arg: EvalTask,
            *,
            arm: str,
            snapshot: str | Path,
            output_dir: str | Path,
            host: str,
            run_group_id: str,
            random_seed: int,
            pre_arm_host_config_command: tuple[str, ...],
            post_arm_host_config_command: tuple[str, ...],
            config: RunnerConfig,
        ) -> RunRecord:
            return _record(
                task=task_arg,
                arm=arm,
                run_group_id=run_group_id,
                pre=pre_arm_host_config_command,
                post=post_arm_host_config_command,
                mcp_tools=["mcp__supercontext__planning_context"],
            )

        with self.assertRaisesRegex(RuntimeError, "mcp_off"):
            _run_paired_tasks(
                [_task()],
                arms=["mcp_off"],
                snapshot="snapshot-dir",
                output_dir="out-dir",
                host="claude_code",
                seed=0,
                config=RunnerConfig(),
                run_task=fake_run_task,
                run_host_command=commands.append,
                group_id_factory=lambda: "group-1",
            )

        self.assertEqual(len(commands), 2)
        self.assertIn("--remove", commands[0])
        self.assertNotIn("--remove", commands[1])

    def test_mcp_off_restores_registration_when_pre_command_fails(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fail_on_remove(command: tuple[str, ...]) -> None:
            commands.append(command)
            if "--remove" in command:
                raise RuntimeError("remove failed")

        with self.assertRaisesRegex(RuntimeError, "remove failed"):
            _run_paired_tasks(
                [_task()],
                arms=["mcp_off"],
                snapshot="snapshot-dir",
                output_dir="out-dir",
                host="claude_code",
                seed=0,
                config=RunnerConfig(),
                run_task=lambda *args, **kwargs: self.fail("run_task should not execute"),
                run_host_command=fail_on_remove,
                group_id_factory=lambda: "group-1",
            )

        self.assertEqual(len(commands), 2)
        self.assertIn("--remove", commands[0])
        self.assertNotIn("--remove", commands[1])

    def test_parse_arms_rejects_duplicates_and_unknown_values(self) -> None:
        self.assertEqual(_parse_arms("mcp_on,mcp_off"), ["mcp_on", "mcp_off"])
        with self.assertRaisesRegex(SystemExit, "duplicate"):
            _parse_arms("mcp_on,mcp_on")
        with self.assertRaisesRegex(SystemExit, "unsupported"):
            _parse_arms("mcp_on,other")

    def test_positive_int_rejects_non_positive_parallelism(self) -> None:
        self.assertEqual(_positive_int("2"), 2)
        with self.assertRaisesRegex(Exception, "at least 1"):
            _positive_int("0")

    def test_mcp_health_url_targets_loopback_health_endpoint(self) -> None:
        self.assertEqual(
            _mcp_health_url("http://127.0.0.1:3845/mcp?ignored=true"),
            "http://127.0.0.1:3845/health",
        )
        with self.assertRaisesRegex(ValueError, "HTTP"):
            _mcp_health_url("stdio://supercontext")

    def test_managed_mcp_url_health_checks_explicit_url_without_starting_server(self) -> None:
        with patch("source.scripts.run_ab_eval._wait_for_mcp_health") as health_mock:
            with _managed_mcp_url(
                snapshot="snapshot-dir",
                arms=["mcp_on"],
                explicit_mcp_url="http://127.0.0.1:9999/mcp",
            ) as mcp_url:
                self.assertEqual(mcp_url, "http://127.0.0.1:9999/mcp")

        health_mock.assert_called_once_with("http://127.0.0.1:9999/mcp", timeout_seconds=10.0)

    def test_local_mcp_server_starts_for_snapshot_and_stops_on_exit(self) -> None:
        process = _FakeProcess()
        commands: list[tuple[str, ...]] = []
        health_calls: list[tuple[str, object]] = []

        def fake_popen(command: tuple[str, ...], **kwargs: object) -> _FakeProcess:
            commands.append(command)
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
            self.assertTrue(kwargs["text"])
            return process

        def fake_health(mcp_url: str, *, process: object) -> None:
            health_calls.append((mcp_url, process))

        with _local_mcp_server(
            "snapshot-dir",
            port_factory=lambda: 4545,
            popen=fake_popen,
            health_check=fake_health,
        ) as mcp_url:
            self.assertEqual(mcp_url, "http://127.0.0.1:4545/mcp")
            self.assertFalse(process.terminated)

        self.assertTrue(process.terminated)
        self.assertEqual(health_calls, [("http://127.0.0.1:4545/mcp", process)])
        self.assertIn("source.scripts.mcp_server", commands[0])
        self.assertIn("--snapshot", commands[0])
        self.assertIn("snapshot-dir", commands[0])
        self.assertIn("--port", commands[0])
        self.assertIn("4545", commands[0])

    def test_host_config_commands_use_claude_registration_contract(self) -> None:
        on_command = _pre_arm_host_config_command(
            arm="mcp_on", host="claude_code", mcp_url="http://127.0.0.1:9999/mcp"
        )
        off_command = _pre_arm_host_config_command(
            arm="mcp_off", host="claude_code", mcp_url="http://127.0.0.1:9999/mcp"
        )
        restore_command = _post_arm_host_config_command(
            arm="mcp_off", host="claude_code", mcp_url="http://127.0.0.1:9999/mcp"
        )

        self.assertEqual(
            on_command[-8:],
            (
                "-m",
                "source.scripts.register_mcp",
                "--agent",
                "claude",
                "--on-error",
                "error",
                "--url",
                "http://127.0.0.1:9999/mcp",
            ),
        )
        self.assertEqual(
            off_command[-7:],
            ("-m", "source.scripts.register_mcp", "--agent", "claude", "--on-error", "error", "--remove"),
        )
        self.assertEqual(
            restore_command[-8:],
            (
                "-m",
                "source.scripts.register_mcp",
                "--agent",
                "claude",
                "--on-error",
                "error",
                "--url",
                "http://127.0.0.1:9999/mcp",
            ),
        )

    def test_host_config_command_suppresses_registration_stdout(self) -> None:
        with patch("source.scripts.run_ab_eval.subprocess.run") as run_mock:
            _run_host_config_command(("register", "mcp"))

        run_mock.assert_called_once()
        _, kwargs = run_mock.call_args
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.PIPE)
        self.assertTrue(kwargs["text"])

    def test_host_config_command_includes_stderr_in_failure(self) -> None:
        error = subprocess.CalledProcessError(2, ("register", "mcp"), stderr="bad config\n")
        with patch("source.scripts.run_ab_eval.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "bad config"):
                _run_host_config_command(("register", "mcp"))

    def test_cleanup_failure_does_not_mask_primary_run_failure(self) -> None:
        def fake_run_task(*args, **kwargs) -> RunRecord:
            raise RuntimeError("primary run failed")

        def fail_restore(command: tuple[str, ...]) -> None:
            if "--remove" not in command:
                raise RuntimeError("restore failed")

        with self.assertRaisesRegex(RuntimeError, "primary run failed") as context:
            _run_paired_tasks(
                [_task()],
                arms=["mcp_off"],
                snapshot="snapshot-dir",
                output_dir="out-dir",
                host="claude_code",
                seed=0,
                config=RunnerConfig(),
                run_task=fake_run_task,
                run_host_command=fail_restore,
                group_id_factory=lambda: "group-1",
            )

        self.assertIn("restore failed", "\n".join(context.exception.__notes__))

    def test_host_error_result_messages_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Not logged in"):
            _raise_for_host_error_messages(
                [
                    {
                        "type": "ResultMessage",
                        "data": {
                            "is_error": True,
                            "result": "Not logged in · Please run /login",
                        },
                    }
                ]
            )

    def test_non_error_result_messages_do_not_fail(self) -> None:
        _raise_for_host_error_messages(
            [
                {
                    "type": "ResultMessage",
                    "data": {
                        "is_error": False,
                        "result": "answer",
                    },
                }
            ]
        )

    def test_host_message_errors_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "authentication_failed"):
            _raise_for_host_error_messages(
                [
                    {
                        "type": "AssistantMessage",
                        "data": {"error": "authentication_failed"},
                    }
                ]
            )

    def test_missing_result_message_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing ResultMessage"):
            _raise_for_host_error_messages([{"type": "SystemMessage", "data": {"subtype": "init"}}])

    def test_incomplete_background_task_fails_closed(self) -> None:
        messages = [
            {
                "type": "SystemMessage",
                "data": {
                    "data": {
                        "subtype": "task_updated",
                        "task_id": "bbgn0p55y",
                        "patch": {"is_backgrounded": True},
                    }
                },
            },
            {
                "type": "UserMessage",
                "data": {
                    "content": [
                        {
                            "tool_use_id": "toolu_1",
                            "is_error": False,
                            "content": (
                                "Command running in background with ID: bbgn0p55y. "
                                "Output is being written to a task file."
                            ),
                        }
                    ],
                    "tool_use_result": {
                        "backgroundTaskId": "bbgn0p55y",
                        "assistantAutoBackgrounded": False,
                        "stdout": "",
                        "stderr": "",
                    },
                },
            },
            {
                "type": "ResultMessage",
                "data": {
                    "is_error": False,
                    "result": "The dependency path is mercury_ml_api -> mercury_ml.",
                },
            },
        ]

        self.assertEqual(_incomplete_background_task_ids(messages), {"bbgn0p55y"})
        with self.assertRaisesRegex(RuntimeError, "incomplete background task.*bbgn0p55y"):
            _raise_for_host_error_messages(messages, fail_on_incomplete_background_tasks=True)

    def test_system_background_patch_alone_fails_closed(self) -> None:
        messages = [
            {
                "type": "SystemMessage",
                "data": {
                    "data": {
                        "subtype": "task_updated",
                        "task_id": "bg-from-system",
                        "patch": {"is_backgrounded": True},
                    }
                },
            },
            {
                "type": "ResultMessage",
                "data": {
                    "is_error": False,
                    "result": "The dependency path is mercury_ml_api -> mercury_ml.",
                },
            },
        ]

        self.assertEqual(_incomplete_background_task_ids(messages), {"bg-from-system"})
        with self.assertRaisesRegex(RuntimeError, "incomplete background task.*bg-from-system"):
            _raise_for_host_error_messages(messages, fail_on_incomplete_background_tasks=True)

    def test_successful_eval_run_can_ignore_incomplete_background_task_marker(self) -> None:
        messages = [
            {
                "type": "UserMessage",
                "data": {
                    "tool_use_result": {
                        "backgroundTaskId": "bg-1",
                        "stdout": "",
                        "stderr": "",
                    }
                },
            },
            {
                "type": "ResultMessage",
                "data": {
                    "is_error": False,
                    "result": "Final answer already produced.",
                },
            },
        ]

        self.assertEqual(_incomplete_background_task_ids(messages), {"bg-1"})
        _raise_for_host_error_messages(messages, fail_on_incomplete_background_tasks=False)

    def test_run_record_defaults_incomplete_background_task_ids(self) -> None:
        record = _record(
            task=_task(),
            arm="mcp_on",
            run_group_id="group-1",
            pre=(),
            post=(),
        )

        self.assertEqual(record.incomplete_background_task_ids, [])
        self.assertEqual(record.to_json()["incomplete_background_task_ids"], [])

    def test_completed_background_task_does_not_fail(self) -> None:
        _raise_for_host_error_messages(
            [
                {
                    "type": "UserMessage",
                    "data": {
                        "tool_use_result": {
                            "backgroundTaskId": "bg-1",
                            "stdout": "",
                            "stderr": "",
                        }
                    },
                },
                {
                    "type": "SystemMessage",
                    "data": {
                        "data": {
                            "subtype": "task_completed",
                            "task_id": "bg-1",
                        }
                    },
                },
                {
                    "type": "ResultMessage",
                    "data": {
                        "is_error": False,
                        "result": "The dependency path is mercury_ml_api -> mercury_ml.",
                    },
                },
            ]
        )

    def test_eval_runner_allows_safe_read_tools_and_mcp_only_for_on_arm(self) -> None:
        on_tools = _allowed_tools("mcp_on")
        off_tools = _allowed_tools("mcp_off")

        self.assertIn("Read", on_tools)
        self.assertIn("Grep", on_tools)
        self.assertIn("Bash", on_tools)
        self.assertIn("ToolSearch", on_tools)
        self.assertIn("mcp__supercontext__find_callers", on_tools)
        self.assertIn("mcp__supercontext__review_context", on_tools)
        self.assertNotIn("mcp__supercontext__find_callers", off_tools)

    def test_mcp_tool_denials_are_counted_and_fail_closed(self) -> None:
        observations = _mcp_tool_observations(
            [
                {
                    "type": "AssistantMessage",
                    "data": {
                        "content": [
                            {
                                "id": "toolu_1",
                                "name": "mcp__supercontext__find_callers",
                                "input": {"symbol": "load_model"},
                            }
                        ]
                    },
                },
                {
                    "type": "UserMessage",
                    "data": {
                        "content": [
                            {
                                "tool_use_id": "toolu_1",
                                "is_error": True,
                                "content": "Claude requested permissions to use mcp__supercontext__find_callers.",
                            }
                        ]
                    },
                },
                {
                    "type": "ResultMessage",
                    "data": {
                        "is_error": False,
                        "permission_denials": [
                            {
                                "tool_use_id": "toolu_1",
                                "tool_name": "mcp__supercontext__find_callers",
                            }
                        ],
                    },
                },
            ]
        )

        self.assertEqual(observations["attempts"], ["mcp__supercontext__find_callers"])
        self.assertEqual(observations["denials"], ["mcp__supercontext__find_callers"])
        with self.assertRaisesRegex(RuntimeError, "denied SuperContext MCP"):
            _raise_for_mcp_tool_failures(observations)

    def test_mcp_tool_errors_are_counted_and_fail_closed(self) -> None:
        observations = _mcp_tool_observations(
            [
                {
                    "type": "AssistantMessage",
                    "data": {
                        "content": [
                            {
                                "id": "toolu_1",
                                "name": "mcp__supercontext__review_context",
                                "input": {"changed_files": ["source/kg/eval/runner.py"]},
                            }
                        ]
                    },
                },
                {
                    "type": "UserMessage",
                    "data": {
                        "content": [
                            {
                                "tool_use_id": "toolu_1",
                                "is_error": True,
                                "content": "server returned invalid JSON",
                            }
                        ]
                    },
                },
            ]
        )

        self.assertEqual(observations["errors"], ["mcp__supercontext__review_context"])
        with self.assertRaisesRegex(RuntimeError, "SuperContext MCP tool error"):
            _raise_for_mcp_tool_failures(observations)

    def test_legacy_bettercontext_tool_prefix_counts_as_supercontext_mcp(self) -> None:
        messages = [
            {
                "type": "AssistantMessage",
                "data": {
                    "content": [
                        {
                            "id": "toolu_1",
                            "name": "mcp__bettercontext__find_callers",
                            "input": {"symbol": "load_model"},
                        },
                        {
                            "id": "toolu_2",
                            "name": "Read",
                            "input": {"file_path": "source/kg/eval/runner.py"},
                        },
                    ]
                },
            },
            {
                "type": "UserMessage",
                "data": {
                    "content": [
                        {"tool_use_id": "toolu_1", "is_error": False, "content": "ok"},
                        {"tool_use_id": "toolu_2", "is_error": False, "content": "ok"},
                    ]
                },
            },
        ]

        mcp_tools, non_mcp_tools = _tool_calls(messages)
        observations = _mcp_tool_observations(messages)

        self.assertEqual(mcp_tools, ["mcp__bettercontext__find_callers"])
        self.assertEqual(non_mcp_tools, ["Read"])
        self.assertEqual(observations["successes"], ["mcp__bettercontext__find_callers"])

    def test_permission_denial_metadata_prevents_error_double_count(self) -> None:
        observations = _mcp_tool_observations(
            [
                {
                    "type": "AssistantMessage",
                    "data": {
                        "content": [
                            {
                                "id": "toolu_1",
                                "name": "mcp__supercontext__find_callers",
                                "input": {"symbol": "load_model"},
                            }
                        ]
                    },
                },
                {
                    "type": "UserMessage",
                    "data": {
                        "content": [
                            {
                                "tool_use_id": "toolu_1",
                                "is_error": True,
                                "content": "tool use was blocked by host policy",
                            }
                        ]
                    },
                },
                {
                    "type": "ResultMessage",
                    "data": {
                        "is_error": False,
                        "permission_denials": [
                            {
                                "tool_use_id": "toolu_1",
                                "tool_name": "mcp__supercontext__find_callers",
                            }
                        ],
                    },
                },
            ]
        )

        self.assertEqual(observations["denials"], ["mcp__supercontext__find_callers"])
        self.assertEqual(observations["errors"], [])

    def test_successful_mcp_tool_result_is_counted(self) -> None:
        observations = _mcp_tool_observations(
            [
                {
                    "type": "AssistantMessage",
                    "data": {
                        "content": [
                            {
                                "id": "toolu_1",
                                "name": "mcp__supercontext__find_callees",
                                "input": {"symbol": "predict_on_session"},
                            }
                        ]
                    },
                },
                {
                    "type": "UserMessage",
                    "data": {
                        "content": [
                            {
                                "tool_use_id": "toolu_1",
                                "is_error": False,
                                "content": [{"text": "{\"status\":\"found\"}"}],
                            }
                        ]
                    },
                },
            ]
        )

        self.assertEqual(observations["successes"], ["mcp__supercontext__find_callees"])
        _raise_for_mcp_tool_failures(observations)

    def test_repeated_mcp_tool_successes_remain_invocation_lists(self) -> None:
        observations = _mcp_tool_observations(
            [
                {
                    "type": "AssistantMessage",
                    "data": {
                        "content": [
                            {
                                "id": "toolu_1",
                                "name": "mcp__supercontext__find_callees",
                                "input": {"symbol": "predict_on_session"},
                            },
                            {
                                "id": "toolu_2",
                                "name": "mcp__supercontext__find_callees",
                                "input": {"symbol": "score_session"},
                            },
                        ]
                    },
                },
                {
                    "type": "UserMessage",
                    "data": {
                        "content": [
                            {"tool_use_id": "toolu_1", "is_error": False, "content": "ok"},
                            {"tool_use_id": "toolu_2", "is_error": False, "content": "ok"},
                        ]
                    },
                },
            ]
        )

        self.assertEqual(
            observations["successes"],
            ["mcp__supercontext__find_callees", "mcp__supercontext__find_callees"],
        )

    def test_mcp_packet_navigation_stats_count_saved_files_and_jq_attempts(self) -> None:
        messages = [
            {
                "type": "UserMessage",
                "data": {
                    "content": [
                        {
                            "tool_use_id": "toolu_1",
                            "content": (
                                "Error: result exceeds maximum allowed tokens. Output has been saved to "
                                "/tmp/session/tool-results/mcp-supercontext-planning_context-123.txt. "
                                "Probe with jq 'keys' /tmp/session/tool-results/mcp-supercontext-planning_context-123.txt"
                            ),
                        }
                    ],
                },
            },
            {
                "type": "AssistantMessage",
                "data": {
                    "content": [
                        {
                            "id": "toolu_2",
                            "name": "Bash",
                            "input": {
                                "command": (
                                    "jq '.summary' "
                                    "/tmp/session/tool-results/mcp-supercontext-planning_context-123.txt"
                                )
                            },
                        },
                        {
                            "id": "toolu_3",
                            "name": "Bash",
                            "input": {"command": "jq '.predicate' data/kg_runs/snapshot/facts.jsonl"},
                        },
                    ]
                },
            },
        ]

        stats = _mcp_packet_navigation_stats(messages)

        self.assertEqual(stats["file_reference_count"], 3)
        self.assertEqual(stats["jq_attempt_count"], 1)
        self.assertEqual(stats["saved_file_count"], 1)
        self.assertEqual(stats["saved_file_bytes_best_effort"], 0)

    def test_mcp_saved_result_path_scanner_handles_host_error_text_without_regex(self) -> None:
        text = (
            "saved to /Users/me/project/tool-results/mcp-supercontext-review_context-123.txt. "
            "Malformed /tmp/session/tool-results/mcp-supercontext-missing-suffix "
            "Then jq /tmp/session/tool-results/mcp-supercontext-planning_context-456.txt) "
            "Also see (/tmp/session/tool-results/mcp-supercontext-find_callers-789.txt) "
            "Legacy /tmp/session/tool-results/mcp-bettercontext-review_context-000.txt"
        )

        self.assertEqual(
            _mcp_saved_result_paths(text),
            [
                "/Users/me/project/tool-results/mcp-supercontext-review_context-123.txt",
                "/tmp/session/tool-results/mcp-supercontext-planning_context-456.txt",
                "/tmp/session/tool-results/mcp-supercontext-find_callers-789.txt",
                "/tmp/session/tool-results/mcp-bettercontext-review_context-000.txt",
            ],
        )

    def test_eval_runner_does_not_force_bare_claude_mode(self) -> None:
        self.assertNotIn("bare", _claude_extra_args())

    def test_task_prompt_includes_manifest_fixture_input(self) -> None:
        task = EvalTask(
            row=CorpusRow(
                task_id="Q037",
                difficulty="Hard",
                tool_surface="blast_radius",
                persona="reviewer",
                fixture="PR input shape",
                user_question="Given this PR, compute blast radius.",
                expected_answer_shape="blast radius",
                capabilities="diff parsing",
            ),
            phase="review",
            fixture_input='PR input:\n{"repo": "backend_api", "changed_files": ["api/auth/routes.py", "api/accounts/views.py"]}',
        )

        prompt = render_task_prompt(task, snapshot_path=Path("snapshot-dir"), arm="mcp_on")

        self.assertIn("Fixture input:", prompt)
        self.assertIn('"repo": "backend_api"', prompt)
        self.assertIn('"changed_files": ["api/auth/routes.py", "api/accounts/views.py"]', prompt)
        self.assertLess(prompt.index("Fixture input:"), prompt.index("User question:"))
        self.assertNotIn("Arm: mcp_on\n\n\n", prompt)

    def test_mcp_on_task_prompt_loads_supercontext_skill_routing_guidance(self) -> None:
        prompt = render_task_prompt(_task(), snapshot_path=Path("snapshot-dir"), arm="mcp_on")

        self.assertIn("SuperContext MCP skill routing guidance for this mcp_on arm:", prompt)
        self.assertIn("Call `planning_context` before broad search", prompt)
        self.assertIn("Before reviewing a diff, call `review_context`", prompt)
        self.assertIn("If the result is `ambiguous`, use `next_actions`", prompt)
        self.assertLess(prompt.index("SuperContext MCP skill routing guidance"), prompt.index("User question:"))
        self.assertNotIn("---\nname: supercontext-mcp", prompt)

    def test_mcp_off_task_prompt_does_not_include_supercontext_skill_routing_guidance(self) -> None:
        prompt = render_task_prompt(_task(), snapshot_path=Path("snapshot-dir"), arm="mcp_off")

        self.assertNotIn("SuperContext MCP skill routing guidance", prompt)
        self.assertNotIn("Call `planning_context` before broad search", prompt)

    def test_mcp_on_task_prompt_fails_loudly_when_skill_template_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eval_runner._claude_supercontext_skill_text.cache_clear()
            try:
                with patch.object(eval_runner, "_CLAUDE_SUPERCONTEXT_SKILL_PATH", Path(tmp) / "missing.md"):
                    with self.assertRaisesRegex(RuntimeError, "SuperContext SKILL.md missing"):
                        render_task_prompt(_task(), snapshot_path=Path("snapshot-dir"), arm="mcp_on")
            finally:
                eval_runner._claude_supercontext_skill_text.cache_clear()

    def test_task_prompt_includes_resolved_fixture_bindings(self) -> None:
        task = EvalTask(
            row=CorpusRow(
                task_id="Q003",
                difficulty="Low",
                tool_surface="find_callers",
                persona="reviewer",
                fixture="$PY_REPO, $CALLER_SYMBOL",
                user_question="Who calls `$CALLER_SYMBOL`?",
                expected_answer_shape="caller list for `$CALLER_SYMBOL`",
                capabilities="call graph",
            ),
            phase="coding",
            fixture_bindings=(("$PY_REPO", "mercury_ml"), ("$CALLER_SYMBOL", "load_model")),
        )

        prompt = render_task_prompt(task, snapshot_path=Path("snapshot-dir"), arm="mcp_on")

        self.assertIn("Fixture: mercury_ml, load_model", prompt)
        self.assertIn("Resolved fixture bindings", prompt)
        self.assertIn("- $PY_REPO = mercury_ml", prompt)
        self.assertIn("- $CALLER_SYMBOL = load_model", prompt)
        self.assertIn("Who calls `load_model`?", prompt)
        self.assertIn("caller list for `load_model`", prompt)
        self.assertNotIn("load_model\n\n\nUser question:", prompt)


def _task(task_id: str = "Q003") -> EvalTask:
    return EvalTask(
        row=CorpusRow(
            task_id=task_id,
            difficulty="Low",
            tool_surface="find_callers",
            persona="reviewer",
            fixture="$PY_REPO, $CALLER_SYMBOL",
            user_question="Who calls load_model?",
            expected_answer_shape="caller list",
            capabilities="call graph",
        ),
        phase="coding",
    )


def _record(
    *,
    task: EvalTask,
    arm: Arm,
    run_group_id: str,
    pre: tuple[str, ...],
    post: tuple[str, ...],
    mcp_tools: list[str] | None = None,
) -> RunRecord:
    return RunRecord(
        run_group_id=run_group_id,
        arm=arm,  # type: ignore[arg-type]
        task_id=task.task_id,
        phase=task.phase,
        host="claude_code",
        repo_fixture=task.fixture,
        difficulty=task.difficulty,
        harness_version=DEFAULT_HARNESS_VERSION,
        task_prompt=render_task_prompt(task, snapshot_path=Path("snapshot-dir"), arm=arm),
        snapshot_path="snapshot-dir",
        mcp_tools_called=mcp_tools or [],
        non_mcp_tools_called=["Read"],
        tokens_in=1,
        tokens_out=1,
        wall_time_seconds=0.1,
        final_answer="answer",
        final_answer_citations=[],
        host_session_log_path="messages.jsonl",
        model="test-model",
        random_seed=7,
        pre_arm_host_config_command=pre,
        post_arm_host_config_command=post,
    )


class _FakeStderr:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def read(self) -> str:
        return self.text


class _FakeProcess:
    def __init__(self, returncode: int | None = None, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = _FakeStderr(stderr)
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


if __name__ == "__main__":
    unittest.main()
