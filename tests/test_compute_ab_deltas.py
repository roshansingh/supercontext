from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.scripts.compute_ab_deltas import compute_deltas, load_jsonl


class ComputeAbDeltasTest(unittest.TestCase):
    def test_pairs_traces_and_computes_off_minus_on_deltas(self) -> None:
        rows = compute_deltas(
            [
                _trace(
                    "mcp_on",
                    mcp_tools=["mcp__supercontext__find_callers"],
                    mcp_success_count=1,
                    non_mcp_tools=["Read"],
                    cost=0.03,
                ),
                _trace("mcp_off", mcp_tools=[], non_mcp_tools=["Read", "Grep", "Read"], cost=0.05),
            ]
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["quality_verdict"], "ungraded")
        self.assertEqual(row["quality_grading_mode"], "auto_eligible")
        self.assertEqual(row["cost_status"], "available")
        self.assertAlmostEqual(row["dollars_delta"], 0.02, places=9)
        self.assertEqual(row["deltas"]["tool_calls"], 1)
        self.assertEqual(row["deltas"]["mcp_calls"], -1)
        self.assertEqual(row["deltas"]["mcp_tool_attempts"], -1)
        self.assertEqual(row["deltas"]["mcp_tool_successes"], -1)
        self.assertEqual(row["on"]["mcp_tool_success_count"], 1)
        self.assertEqual(row["deltas"]["non_mcp_calls"], 2)
        self.assertEqual(row["deltas"]["non_mcp_tool_attempts"], 2)
        self.assertEqual(row["deltas"]["tokens_in"], 20)
        self.assertEqual(row["deltas"]["tokens_out"], 5)

    def test_missing_cost_stays_unavailable_without_zero_default(self) -> None:
        rows = compute_deltas(
            [
                _trace("mcp_on", mcp_tools=["mcp__supercontext__find_callers"], non_mcp_tools=[], cost=None),
                _trace("mcp_off", mcp_tools=[], non_mcp_tools=["Read"], cost=0.05),
            ]
        )

        self.assertEqual(rows[0]["cost_status"], "unavailable")
        self.assertIsNone(rows[0]["dollars_delta"])

    def test_medium_rows_remain_ungraded(self) -> None:
        rows = compute_deltas(
            [
                _trace("mcp_on", difficulty="Medium"),
                _trace("mcp_off", difficulty="Medium"),
            ]
        )

        self.assertEqual(rows[0]["quality_verdict"], "ungraded")
        self.assertEqual(rows[0]["quality_grading_mode"], "manual_required")

    def test_unpaired_traces_fail_loudly_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "unpaired traces"):
            compute_deltas([_trace("mcp_on")])

    def test_unpaired_traces_can_be_explicitly_skipped(self) -> None:
        self.assertEqual(compute_deltas([_trace("mcp_on")], allow_unpaired=True), [])

    def test_mcp_on_permission_denials_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "SuperContext MCP denials=1"):
            compute_deltas(
                [
                    _trace(
                        "mcp_on",
                        mcp_tools=["mcp__supercontext__find_callers"],
                        mcp_denial_count=1,
                    ),
                    _trace("mcp_off"),
                ]
            )

    def test_mcp_on_tool_failures_can_be_explicitly_allowed_for_forensics(self) -> None:
        rows = compute_deltas(
            [
                _trace(
                    "mcp_on",
                    mcp_tools=["mcp__supercontext__find_callers"],
                    mcp_denial_count=1,
                ),
                _trace("mcp_off"),
            ],
            allow_mcp_tool_failures=True,
        )

        self.assertEqual(rows[0]["on"]["mcp_tool_denial_count"], 1)

    def test_mcp_on_tool_errors_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "SuperContext MCP denials=0 errors=1"):
            compute_deltas(
                [
                    _trace(
                        "mcp_on",
                        mcp_tools=["mcp__supercontext__review_context"],
                        mcp_error_count=1,
                    ),
                    _trace("mcp_off"),
                ]
            )

    def test_incomplete_background_tasks_fail_closed_before_scoring(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete background tasks=bg-1"):
            compute_deltas(
                [
                    _trace("mcp_on", incomplete_background_task_ids=["bg-1"]),
                    _trace("mcp_off"),
                ]
            )

    def test_incomplete_background_tasks_can_be_explicitly_allowed_for_forensics(self) -> None:
        rows = compute_deltas(
            [
                _trace("mcp_on", incomplete_background_task_ids=["bg-1"]),
                _trace("mcp_off"),
            ],
            allow_incomplete_background_tasks=True,
        )

        self.assertEqual(rows[0]["on"]["incomplete_background_task_ids"], ["bg-1"])

    def test_load_jsonl_reports_file_and_line_for_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traces.jsonl"
            path.write_text("{\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"traces\.jsonl:1: invalid JSON"):
                load_jsonl(path)


def _trace(
    arm: str,
    *,
    difficulty: str = "Low",
    mcp_tools: list[str] | None = None,
    mcp_success_count: int = 0,
    mcp_denial_count: int = 0,
    mcp_error_count: int = 0,
    non_mcp_tools: list[str] | None = None,
    cost: float | None = 0.01,
    incomplete_background_task_ids: list[str] | None = None,
) -> dict:
    return {
        "run_group_id": "group-1",
        "task_id": "Q003",
        "arm": arm,
        "phase": "coding",
        "difficulty": difficulty,
        "mcp_tools_called": mcp_tools or [],
        "mcp_tool_attempt_count": len(mcp_tools or []),
        "mcp_tool_success_count": mcp_success_count,
        "mcp_tool_denial_count": mcp_denial_count,
        "mcp_tool_error_count": mcp_error_count,
        "mcp_tool_successes": (mcp_tools or []) if mcp_success_count else [],
        "mcp_tool_denials": (mcp_tools or []) if mcp_denial_count else [],
        "mcp_tool_errors": (mcp_tools or []) if mcp_error_count else [],
        "non_mcp_tools_called": ["Read"] if non_mcp_tools is None else non_mcp_tools,
        "non_mcp_tool_attempt_count": len(["Read"] if non_mcp_tools is None else non_mcp_tools),
        "non_mcp_tool_attempts": ["Read"] if non_mcp_tools is None else non_mcp_tools,
        "tokens_in": 100 if arm == "mcp_on" else 120,
        "tokens_out": 10 if arm == "mcp_on" else 15,
        "wall_time_seconds": 1.0 if arm == "mcp_on" else 2.5,
        "final_answer_citations": ["a.py"] if arm == "mcp_on" else [],
        "final_answer": f"{arm} answer",
        "total_cost": cost,
        "cost_status": "available" if cost is not None else "unavailable",
        "incomplete_background_task_ids": incomplete_background_task_ids or [],
    }


if __name__ == "__main__":
    unittest.main()
