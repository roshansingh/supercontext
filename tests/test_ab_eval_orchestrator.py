from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.eval.corpus import CorpusRow, EvalTask
from source.kg.eval.runner import (
    RunRecord,
    RunnerConfig,
    _claude_extra_args,
    _raise_for_host_error_messages,
)
from source.scripts.run_ab_eval import (
    _parse_arms,
    _post_arm_host_config_command,
    _pre_arm_host_config_command,
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

    def test_mcp_off_rejects_bettercontext_tool_calls_and_restores_registration(self) -> None:
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
                mcp_tools=["mcp__bettercontext__planning_context"],
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

    def test_eval_runner_does_not_force_bare_claude_mode(self) -> None:
        self.assertNotIn("bare", _claude_extra_args())


def _task() -> EvalTask:
    return EvalTask(
        row=CorpusRow(
            task_id="Q003",
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
