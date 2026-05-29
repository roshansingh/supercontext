from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from source.kg.eval.runner import RunRecord
from source.scripts.compute_ab_deltas import compute_deltas, load_jsonl
from source.scripts.mcp_quality_floor_gate import (
    DEFAULT_JUDGE_MODEL,
    _filter_rows_by_task_ids,
    _parse_winner_set,
    _selected_task_ids,
    _validate_baseline_judge_contract,
    _validate_baseline_winners,
    _write_local_records_as_traces,
    _winner,
    main,
    quality_floor_failures,
)


class McpQualityFloorGateTest(unittest.TestCase):
    def test_default_judge_model_is_workspace_alias(self) -> None:
        self.assertEqual(DEFAULT_JUDGE_MODEL, "gpt-5.4-mini")

    def test_quality_floor_fails_when_protected_row_becomes_mcp_off(self) -> None:
        baseline = [
            {"task_id": "Q001", "judge_winner": "mcp_on"},
            {"task_id": "Q002", "judge_winner": "tie"},
            {"task_id": "Q003", "judge_winner": "mcp_off"},
        ]
        current = [
            {"task_id": "Q001", "judge_winner": "mcp_off", "judge_reasoning": "less complete"},
            {"task_id": "Q002", "judge_winner": "tie"},
            {"task_id": "Q003", "judge_winner": "mcp_off"},
        ]

        failures = quality_floor_failures(baseline, current, protected_winners={"mcp_on", "tie"})

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["task_id"], "Q001")
        self.assertEqual(failures[0]["reason"], "protected_baseline_row_became_mcp_off_win")

    def test_quality_floor_fails_missing_current_protected_row(self) -> None:
        failures = quality_floor_failures(
            [{"task_id": "Q001", "judge_winner": "tie"}],
            [],
            protected_winners={"mcp_on", "tie"},
        )

        self.assertEqual(failures[0]["reason"], "missing_current_row")

    def test_quality_floor_records_current_judge_error_as_failure(self) -> None:
        failures = quality_floor_failures(
            [{"task_id": "Q001", "judge_winner": "mcp_on"}],
            [{"task_id": "Q001", "quality_verdict": "judge_error", "judge_error": "invalid JSON"}],
            protected_winners={"mcp_on", "tie"},
        )

        self.assertEqual(failures[0]["reason"], "current_row_not_judged")
        self.assertEqual(failures[0]["current_quality_verdict"], "judge_error")
        self.assertEqual(failures[0]["current_judge_error"], "invalid JSON")

    def test_task_selection_defaults_to_deduped_baseline_order(self) -> None:
        rows = [
            {"task_id": "Q002", "judge_winner": "tie"},
            {"task_id": "Q001", "judge_winner": "mcp_on"},
            {"task_id": "Q002", "judge_winner": "tie"},
        ]

        self.assertEqual(_selected_task_ids(rows, tasks_arg=None), ["Q002", "Q001"])
        self.assertEqual(_selected_task_ids(rows, tasks_arg="Q003,Q001"), ["Q003", "Q001"])

    def test_baseline_filter_limits_quality_floor_to_selected_tasks(self) -> None:
        rows = [
            {"task_id": "Q001", "judge_winner": "mcp_on"},
            {"task_id": "Q002", "judge_winner": "tie"},
        ]

        self.assertEqual(_filter_rows_by_task_ids(rows, task_ids=["Q002"]), [rows[1]])
        with self.assertRaisesRegex(ValueError, "missing selected task"):
            _filter_rows_by_task_ids(rows, task_ids=["Q003"])

    def test_winner_set_validation(self) -> None:
        self.assertEqual(_parse_winner_set("mcp_on,tie"), {"mcp_on", "tie"})
        with self.assertRaisesRegex(ValueError, "unsupported winner"):
            _parse_winner_set("mcp_on,unknown")
        with self.assertRaisesRegex(ValueError, "unsupported winner"):
            _parse_winner_set("mcp_off")

    def test_invalid_baseline_winner_explains_fully_judged_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "fully judged baseline"):
            _winner({"task_id": "Q001", "quality_verdict": "ungraded"})

    def test_baseline_winner_validation_fails_before_expensive_run(self) -> None:
        with self.assertRaisesRegex(ValueError, "fully judged baseline"):
            _validate_baseline_winners([{"task_id": "Q001", "quality_verdict": "ungraded"}])

    def test_baseline_judge_contract_must_match_current_gate(self) -> None:
        rows = [{"task_id": "Q001", "judge_model": "gpt-5.4-mini", "judge_prompt_seed": 119}]

        _validate_baseline_judge_contract(rows, judge_model="gpt-5.4-mini", seed=119)
        with self.assertRaisesRegex(ValueError, "same judge model and seed"):
            _validate_baseline_judge_contract(rows, judge_model="other-model", seed=119)
        with self.assertRaisesRegex(ValueError, "same judge model and seed"):
            _validate_baseline_judge_contract(rows, judge_model="gpt-5.4-mini", seed=120)

    def test_local_records_are_materialized_from_run_ab_eval_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for arm in ("mcp_on", "mcp_off"):
                arm_dir = root / "group-1" / arm
                arm_dir.mkdir(parents=True)
                (arm_dir / "record.json").write_text(
                    json.dumps({"run_group_id": "group-1", "task_id": "Q001", "arm": arm}),
                    encoding="utf-8",
                )
            out = root / "traces.jsonl"

            _write_local_records_as_traces(root, out)

            rows = load_jsonl(out)
            self.assertEqual({row["arm"] for row in rows}, {"mcp_on", "mcp_off"})
            self.assertEqual({row["run_group_id"] for row in rows}, {"group-1"})

    def test_materialized_local_records_feed_real_delta_computation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for arm in ("mcp_on", "mcp_off"):
                record = RunRecord(
                    run_group_id="group-1",
                    arm=arm,
                    task_id="Q001",
                    phase="default-v1",
                    host="claude_code",
                    repo_fixture="fleet",
                    difficulty="medium",
                    harness_version="test",
                    task_prompt="answer the question",
                    snapshot_path="snapshot",
                    mcp_tools_called=["planning_context"] if arm == "mcp_on" else [],
                    non_mcp_tools_called=["Grep"],
                    tokens_in=10,
                    tokens_out=5,
                    wall_time_seconds=1.0,
                    final_answer=f"{arm} answer",
                    final_answer_citations=[],
                    host_session_log_path="session.jsonl",
                    model="claude-opus-4",
                    random_seed=119,
                    mcp_tool_attempt_count=1 if arm == "mcp_on" else 0,
                    mcp_tool_success_count=1 if arm == "mcp_on" else 0,
                )
                arm_dir = root / "group-1" / arm
                arm_dir.mkdir(parents=True)
                (arm_dir / "record.json").write_text(json.dumps(record.to_json()), encoding="utf-8")
            traces_path = root / "traces.jsonl"

            _write_local_records_as_traces(root, traces_path)
            deltas = compute_deltas(load_jsonl(traces_path))

            self.assertEqual(len(deltas), 1)
            self.assertEqual(deltas[0]["task_id"], "Q001")
            self.assertEqual(deltas[0]["on"]["answer"], "mcp_on answer")
            self.assertEqual(deltas[0]["off"]["answer"], "mcp_off answer")

    def test_main_forwards_seed_model_and_paths_to_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "judged-deltas.jsonl"
            baseline.write_text(
                json.dumps(
                    {
                        "task_id": "Q001",
                        "judge_winner": "mcp_on",
                        "judge_model": DEFAULT_JUDGE_MODEL,
                        "judge_prompt_seed": 119,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"
            query_set = root / "queries.md"
            fixture_overrides = root / "overrides.yaml"
            reuse_dir = root / "baseline-run"
            out_dir = root / "out"

            def fake_run_ab_eval(**kwargs: object) -> None:
                self.assertEqual(kwargs["snapshot"], snapshot)
                self.assertEqual(kwargs["out_dir"], out_dir)
                self.assertEqual(kwargs["reuse_mcp_off_from"], reuse_dir)
                self.assertEqual(kwargs["task_ids"], ["Q001"])
                self.assertEqual(kwargs["query_set"], query_set)
                self.assertEqual(kwargs["fixture_overrides"], fixture_overrides)
                self.assertEqual(kwargs["model"], "claude-opus-4")
                self.assertEqual(kwargs["seed"], 119)
                self.assertEqual(kwargs["parallelism"], 3)
                for arm in ("mcp_on", "mcp_off"):
                    arm_dir = out_dir / "group-1" / arm
                    arm_dir.mkdir(parents=True)
                    (arm_dir / "record.json").write_text(
                        json.dumps({"run_group_id": "group-1", "task_id": "Q001", "arm": arm}),
                        encoding="utf-8",
                    )

            argv = [
                "mcp_quality_floor_gate",
                "--snapshot",
                str(snapshot),
                "--baseline-judged-deltas",
                str(baseline),
                "--reuse-mcp-off-from",
                str(reuse_dir),
                "--out",
                str(out_dir),
                "--query-set",
                str(query_set),
                "--fixture-overrides",
                str(fixture_overrides),
                "--tasks",
                "Q001",
                "--model",
                "claude-opus-4",
                "--seed",
                "119",
                "--parallelism",
                "3",
                "--judge-model",
                DEFAULT_JUDGE_MODEL,
            ]

            with (
                mock.patch("sys.argv", argv),
                mock.patch("source.scripts.mcp_quality_floor_gate._run_ab_eval", side_effect=fake_run_ab_eval),
                mock.patch("source.scripts.mcp_quality_floor_gate.compute_deltas", return_value=[{"task_id": "Q001"}]),
                mock.patch(
                    "source.scripts.mcp_quality_floor_gate.judge_rows",
                    return_value=[
                        {
                            "task_id": "Q001",
                            "judge_winner": "mcp_on",
                            "judge_model": DEFAULT_JUDGE_MODEL,
                            "judge_prompt_seed": 119,
                        }
                    ],
                ) as judge,
                mock.patch("source.scripts.mcp_quality_floor_gate.render_report") as render,
            ):
                main()

            judge.assert_called_once_with([{"task_id": "Q001"}], judge_model=DEFAULT_JUDGE_MODEL, seed=119)
            render.assert_called_once()

    def test_main_writes_quality_floor_failures_and_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "judged-deltas.jsonl"
            baseline.write_text(
                json.dumps(
                    {
                        "task_id": "Q001",
                        "judge_winner": "mcp_on",
                        "judge_model": DEFAULT_JUDGE_MODEL,
                        "judge_prompt_seed": 119,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"
            out_dir = root / "out"

            def fake_run_ab_eval(**_: object) -> None:
                for arm in ("mcp_on", "mcp_off"):
                    arm_dir = out_dir / "group-1" / arm
                    arm_dir.mkdir(parents=True)
                    (arm_dir / "record.json").write_text(
                        json.dumps({"run_group_id": "group-1", "task_id": "Q001", "arm": arm}),
                        encoding="utf-8",
                    )

            argv = [
                "mcp_quality_floor_gate",
                "--snapshot",
                str(snapshot),
                "--baseline-judged-deltas",
                str(baseline),
                "--out",
                str(out_dir),
                "--tasks",
                "Q001",
                "--seed",
                "119",
                "--judge-model",
                DEFAULT_JUDGE_MODEL,
            ]

            with (
                mock.patch("sys.argv", argv),
                mock.patch("source.scripts.mcp_quality_floor_gate._run_ab_eval", side_effect=fake_run_ab_eval),
                mock.patch("source.scripts.mcp_quality_floor_gate.compute_deltas", return_value=[{"task_id": "Q001"}]),
                mock.patch(
                    "source.scripts.mcp_quality_floor_gate.judge_rows",
                    return_value=[
                        {
                            "task_id": "Q001",
                            "judge_winner": "mcp_off",
                            "judge_model": DEFAULT_JUDGE_MODEL,
                            "judge_prompt_seed": 119,
                            "judge_reasoning": "current answer lost evidence",
                        }
                    ],
                ),
                mock.patch("source.scripts.mcp_quality_floor_gate.render_report"),
            ):
                with self.assertRaisesRegex(SystemExit, "Quality floor failed"):
                    main()

            failure_path = out_dir / "quality-floor-failures.json"
            self.assertTrue(failure_path.is_file())
            failures = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(failures[0]["task_id"], "Q001")
            self.assertEqual(failures[0]["reason"], "protected_baseline_row_became_mcp_off_win")
            self.assertEqual(failures[0]["current_reasoning"], "current answer lost evidence")

    def test_main_rejects_unjudged_baseline_before_running_ab_eval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "judged-deltas.jsonl"
            baseline.write_text(
                json.dumps(
                    {
                        "task_id": "Q001",
                        "judge_model": DEFAULT_JUDGE_MODEL,
                        "judge_prompt_seed": 119,
                        "quality_verdict": "ungraded",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            argv = [
                "mcp_quality_floor_gate",
                "--snapshot",
                str(root / "snapshot"),
                "--baseline-judged-deltas",
                str(baseline),
                "--out",
                str(root / "out"),
                "--tasks",
                "Q001",
                "--seed",
                "119",
                "--judge-model",
                DEFAULT_JUDGE_MODEL,
            ]

            with (
                mock.patch("sys.argv", argv),
                mock.patch("source.scripts.mcp_quality_floor_gate._run_ab_eval") as run_ab_eval,
            ):
                with self.assertRaisesRegex(ValueError, "fully judged baseline"):
                    main()

            run_ab_eval.assert_not_called()


if __name__ == "__main__":
    unittest.main()
