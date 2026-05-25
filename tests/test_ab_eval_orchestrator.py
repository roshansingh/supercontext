from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.eval.corpus import CorpusRow, EvalTask
from source.kg.eval.runner import (
    RunRecord,
    RunnerConfig,
    _allowed_tools,
    _claude_extra_args,
    _mcp_tool_observations,
    _raise_for_host_error_messages,
    _raise_for_mcp_tool_failures,
    _task_prompt,
    _tool_calls,
)
from source.scripts.run_ab_eval import (
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

        prompt = _task_prompt(task, snapshot_path=Path("snapshot-dir"), arm="mcp_on")

        self.assertIn("Fixture input:", prompt)
        self.assertIn('"repo": "backend_api"', prompt)
        self.assertIn('"changed_files": ["api/auth/routes.py", "api/accounts/views.py"]', prompt)
        self.assertLess(prompt.index("Fixture input:"), prompt.index("User question:"))
        self.assertNotIn("Arm: mcp_on\n\n\n", prompt)

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

        prompt = _task_prompt(task, snapshot_path=Path("snapshot-dir"), arm="mcp_on")

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
    arm: str,
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
        harness_version="ab-eval-v1",
        task_prompt=task.prompt,
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


if __name__ == "__main__":
    unittest.main()
