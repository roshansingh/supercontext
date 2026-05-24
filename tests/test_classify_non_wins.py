from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.kg.eval.classify_non_wins import classify_non_wins, render_markdown


class ClassifyNonWinsTest(unittest.TestCase):
    def test_current_pr119_report_has_expected_baseline_and_win_inventory(self) -> None:
        result = classify_non_wins(Path("docs/evaluation/ab-runs/pr119-full-2026-05-23/ab-report.json"))

        self.assertEqual(result.source_winner_counts, {"mcp_off": 4, "mcp_on": 11, "tie": 3})
        self.assertEqual(len(result.non_wins), 7)
        self.assertEqual(len(result.wins), 11)
        self.assertEqual(
            [row.task_id for row in result.non_wins],
            ["Q048", "Q035", "Q003", "Q015", "Q037", "Q051", "Q081"],
        )

    def test_non_wins_use_raw_records_or_missing_status_with_report_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            report_md = root / "ab-report.md"
            raw_root = root / "raw"
            _write_report(report_json, [_row("Q001", "mcp_off"), _row("Q002", "tie"), _row("Q003", "mcp_on")])
            _write_caveats(report_md)
            _write_raw_record(raw_root, "group-1", "mcp_on", "Q001", mcp_tools=["mcp__supercontext__find_callers"])
            _write_raw_record(raw_root, "group-1", "mcp_off", "Q001", mcp_tools=[])

            result = classify_non_wins(report_json, raw_root, report_md_path=report_md)

        by_task = {row.task_id: row for row in result.non_wins}
        self.assertEqual(by_task["Q001"].raw_evidence_status, "available")
        self.assertEqual(by_task["Q001"].mcp_tools_called, ("mcp__supercontext__find_callers",))
        self.assertEqual(by_task["Q001"].report_classification, "Real MCP quality loss")
        self.assertEqual(by_task["Q002"].raw_evidence_status, "missing")
        self.assertEqual(by_task["Q002"].mcp_tools_called, ())
        self.assertEqual(by_task["Q002"].report_summary, "Report fallback only.")

    def test_zero_mcp_call_raw_record_is_valid_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            raw_root = root / "raw"
            _write_report(report_json, [_row("Q037", "mcp_off", attempts=0, successes=0)])
            _write_raw_record(raw_root, "group-37", "mcp_on", "Q037", mcp_tools=[], non_mcp_tools=["Read"])
            _write_raw_record(raw_root, "group-37", "mcp_off", "Q037", mcp_tools=[], non_mcp_tools=["Bash"])

            result = classify_non_wins(report_json, raw_root)

        row = result.non_wins[0]
        self.assertEqual(row.task_id, "Q037")
        self.assertEqual(row.raw_evidence_status, "available")
        self.assertEqual(row.mcp_tool_count_on, 0)
        self.assertEqual(row.mcp_tools_called, ())
        self.assertEqual(row.non_mcp_tools_called, ("Read",))

    def test_mismatched_raw_task_ids_in_run_group_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            raw_root = root / "raw"
            _write_report(report_json, [_row("Q001", "mcp_off")])
            _write_raw_record(raw_root, "group-1", "mcp_on", "Q001")
            _write_raw_record(raw_root, "group-1", "mcp_off", "Q999")

            with self.assertRaisesRegex(ValueError, "Mismatched task_id"):
                classify_non_wins(report_json, raw_root)

    def test_duplicate_report_task_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_json = Path(tmp) / "ab-report.json"
            _write_report(report_json, [_row("Q001", "mcp_off"), _row("Q001", "tie")])

            with self.assertRaisesRegex(ValueError, "Duplicate report task_id"):
                classify_non_wins(report_json)

    def test_malformed_raw_tool_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            raw_root = root / "raw"
            _write_report(report_json, [_row("Q001", "mcp_off")])
            _write_raw_record(raw_root, "group-1", "mcp_on", "Q001", mcp_tools=["mcp__supercontext__find_callers"])
            record_path = raw_root / "group-1" / "mcp_on" / "record.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["mcp_tools_called"] = "mcp__supercontext__find_callers"
            record_path.write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "mcp_tools_called must be a list"):
                classify_non_wins(report_json, raw_root)

    def test_post_pr119_overlay_is_rendered_without_removing_historical_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            post_path = root / "post.jsonl"
            _write_report(report_json, [_row("Q003", "mcp_off")])
            post_path.write_text(
                json.dumps(
                    {
                        "task_id": "Q003",
                        "judge_winner": "mcp_on",
                        "judge_confidence": 0.95,
                        "on": {
                            "mcp_tools_called": ["mcp__supercontext__find_callers"],
                            "mcp_tool_attempt_count": 1,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = classify_non_wins(report_json, post_pr119_paths=[post_path])
            markdown = render_markdown(result)

        self.assertEqual(len(result.non_wins), 1)
        self.assertEqual(result.non_wins[0].post_pr119_status, "fixed_win")
        self.assertIn("fixed_win", markdown)
        self.assertIn("mcp__supercontext__find_callers", markdown)

    def test_post_pr119_status_is_derived_from_historical_and_focused_winners(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            post_path = root / "post.jsonl"
            _write_report(report_json, [_row("Q777", "mcp_off")])
            post_path.write_text(
                json.dumps({"task_id": "Q777", "judge_winner": "tie", "judge_confidence": 0.9}) + "\n",
                encoding="utf-8",
            )

            result = classify_non_wins(report_json, post_pr119_paths=[post_path])

        self.assertEqual(result.non_wins[0].post_pr119_status, "fixed_tie")

    def test_duplicate_post_pr119_task_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            post_path = root / "post.jsonl"
            _write_report(report_json, [_row("Q003", "mcp_off")])
            post_path.write_text(
                "\n".join(
                    [
                        json.dumps({"task_id": "Q003", "judge_winner": "mcp_on", "judge_confidence": 0.95}),
                        json.dumps({"task_id": "Q003", "judge_winner": "tie", "judge_confidence": 0.9}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate post-pr119 task_id"):
                classify_non_wins(report_json, post_pr119_paths=[post_path])

    def test_report_markdown_without_caveat_rows_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "ab-report.json"
            report_md = root / "ab-report.md"
            _write_report(report_json, [_row("Q001", "mcp_off")])
            report_md.write_text("# report\n\nNo caveats here.\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "No caveat table rows"):
                classify_non_wins(report_json, report_md_path=report_md)


def _write_report(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")


def _row(task_id: str, winner: str, *, attempts: int = 1, successes: int = 1) -> dict:
    return {
        "task_id": task_id,
        "phase": "planning",
        "difficulty": "Low",
        "judge_winner": winner,
        "judge_confidence": 0.9,
        "judge_aspect_winners": {
            "correctness": winner,
            "evidence": winner,
            "completeness": winner,
            "actionability": winner,
        },
        "mcp_on_tool_health": {
            "attempts": attempts,
            "denials": 0,
            "errors": 0,
            "successes": successes,
        },
    }


def _write_caveats(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "## Caveat Analysis",
                "",
                "| Task | Result | Classification | What happened |",
                "|---|---|---|---|",
                "| Q001 | `mcp_off` won | Real MCP quality loss | Raw plus report evidence. |",
                "| Q002 | tie | Acceptable tie | Report fallback only. |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_raw_record(
    raw_root: Path,
    run_group_id: str,
    arm: str,
    task_id: str,
    *,
    mcp_tools: list[str] | None = None,
    non_mcp_tools: list[str] | None = None,
) -> None:
    record_dir = raw_root / run_group_id / arm
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / "messages.jsonl").write_text("", encoding="utf-8")
    record = {
        "task_id": task_id,
        "run_group_id": run_group_id,
        "arm": arm,
        "mcp_tools_called": mcp_tools if mcp_tools is not None else [],
        "non_mcp_tools_called": non_mcp_tools if non_mcp_tools is not None else [],
        "mcp_tool_attempt_count": len(mcp_tools or []),
        "non_mcp_tool_attempt_count": len(non_mcp_tools or []),
    }
    (record_dir / "record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
