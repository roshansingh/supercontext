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
        self.assertIn("| coding | 1 |", markdown)
        self.assertIn("## Where MCP Hurts", markdown)
        self.assertIn("- Q011", markdown)
        self.assertIn("unavailable", markdown)
        self.assertIn('"phase_aggregates"', report_json)
        self.assertEqual(report["phase_aggregates"]["planning"]["avg_tool_calls_delta"], -1.0)


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
