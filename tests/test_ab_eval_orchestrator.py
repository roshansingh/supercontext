from __future__ import annotations

import unittest
from pathlib import Path

from source.kg.eval.corpus import CorpusRow, EvalTask
from source.kg.eval.runner import RunRecord, RunnerConfig
from source.scripts.run_ab_eval import (
    _parse_arms,
    _post_arm_host_config_command,
    _pre_arm_host_config_command,
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
        on_command = _pre_arm_host_config_command(arm="mcp_on", host="claude_code")
        off_command = _pre_arm_host_config_command(arm="mcp_off", host="claude_code")
        restore_command = _post_arm_host_config_command(arm="mcp_off", host="claude_code")

        self.assertEqual(on_command[-4:], ("-m", "source.scripts.register_mcp", "--agent", "claude"))
        self.assertEqual(off_command[-5:], ("-m", "source.scripts.register_mcp", "--agent", "claude", "--remove"))
        self.assertEqual(restore_command[-4:], ("-m", "source.scripts.register_mcp", "--agent", "claude"))


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
