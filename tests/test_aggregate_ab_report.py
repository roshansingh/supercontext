from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.scripts.aggregate_ab_report import render_report


class AggregateAbReportTest(unittest.TestCase):
    def test_report_contains_phase_aggregates_and_cost_unavailable(self) -> None:
        rows = [
            _delta("Q003", "coding", tool_delta=1, token_delta=20, cost_status="available", dollars_delta=0.01),
            _delta("Q011", "planning", tool_delta=-1, token_delta=-10, cost_status="unavailable", dollars_delta=None),
            _delta("Q021", "review", tool_delta=0, token_delta=5, cost_status="unavailable", dollars_delta=None),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = render_report(rows, Path(tmp))
            markdown = (Path(tmp) / "ab-report.md").read_text(encoding="utf-8")
            report_json = (Path(tmp) / "ab-report.json").read_text(encoding="utf-8")

        self.assertIn("## Phase Aggregates", markdown)
        self.assertIn("## Rubric Aggregates", markdown)
        self.assertIn("| coding | 1 |", markdown)
        self.assertIn("## Potential Resource Regressions", markdown)
        self.assertIn("- Q011", markdown)
        self.assertIn("unavailable", markdown)
        self.assertIn('"phase_aggregates"', report_json)
        self.assertIn('"rubric_aggregates"', report_json)
        self.assertEqual(report["phase_aggregates"]["planning"]["avg_tool_calls_delta"], -1.0)

    def test_missing_phase_groups_as_unknown_and_partial_tokens_are_na(self) -> None:
        rows = [
            {
                "task_id": "Q999",
                "run_group_id": "group-1",
                "phase": None,
                "quality_verdict": "ungraded",
                "cost_status": "unavailable",
                "dollars_delta": None,
                "deltas": {"tool_calls": 1, "tokens_in": 5, "tokens_out": None, "wall_time_seconds": None},
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            report = render_report(rows, Path(tmp))
            markdown = (Path(tmp) / "ab-report.md").read_text(encoding="utf-8")

        self.assertIn("unknown", report["phase_aggregates"])
        self.assertIn(
            "| Q999 | None | ungraded | unknown | unknown | unknown | unknown | n/a | n/a | 1 | n/a | unavailable | unavailable |",
            markdown,
        )

    def test_resource_regressions_are_listed(self) -> None:
        rows = [
            {
                "task_id": "Q777",
                "run_group_id": "group-1",
                "phase": "review",
                "quality_verdict": "ungraded",
                "cost_status": "unavailable",
                "dollars_delta": None,
                "deltas": {
                    "tool_calls": -1,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "citations_count": 1,
                    "wall_time_seconds": 0,
                },
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            render_report(rows, Path(tmp))
            markdown = (Path(tmp) / "ab-report.md").read_text(encoding="utf-8")

        self.assertIn("- Q777", markdown)


def _delta(
    task_id: str,
    phase: str,
    *,
    tool_delta: int,
    token_delta: int,
    cost_status: str,
    dollars_delta: float | None,
) -> dict:
    return {
        "task_id": task_id,
        "run_group_id": "group-1",
        "phase": phase,
        "quality_verdict": "ungraded",
        "cost_status": cost_status,
        "dollars_delta": dollars_delta,
        "deltas": {
            "tool_calls": tool_delta,
            "tokens_in": token_delta,
            "tokens_out": 0,
            "wall_time_seconds": 0.1,
        },
    }


if __name__ == "__main__":
    unittest.main()
