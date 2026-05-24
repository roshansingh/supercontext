from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from source.scripts.pull_ab_traces import trace_from_langsmith_run


class PullAbTracesTest(unittest.TestCase):
    def test_trace_from_langsmith_run_extracts_metadata_and_cost_status(self) -> None:
        run = SimpleNamespace(
            id="run-1",
            name="supercontext.ab_eval.Q003.mcp_on",
            run_type="chain",
            tags=("arm:mcp_on", "task_id:Q003"),
            extra={
                "metadata": {
                    "run_group_id": "group-1",
                    "arm": "mcp_on",
                    "task_id": "Q003",
                    "phase": "coding",
                    "host": "claude_code",
                    "repo_fixture": "$PY_REPO",
                    "difficulty": "Low",
                    "harness_version": "ab-eval-v1",
                    "mcp_tools_called": ["mcp__supercontext__find_callers"],
                    "mcp_tool_attempt_count": 1,
                    "mcp_tool_success_count": 1,
                    "mcp_tool_denial_count": 0,
                    "mcp_tool_error_count": 0,
                    "mcp_tool_successes": ["mcp__supercontext__find_callers"],
                    "mcp_tool_denials": [],
                    "mcp_tool_errors": [],
                    "non_mcp_tools_called": ["Read"],
                    "non_mcp_tool_attempt_count": 2,
                    "non_mcp_tool_attempts": ["Read", "Read"],
                    "tokens_in": 10,
                    "tokens_out": 5,
                    "wall_time_seconds": 1.2,
                    "final_answer": "answer",
                    "final_answer_citations": ["a.py"],
                    "model": "claude-sonnet-4-5-20250929",
                    "random_seed": 7,
                    "cost_status": "not_uploaded",
                }
            },
            inputs={"task_id": "Q003"},
            outputs={"final_answer": "answer"},
            total_cost=Decimal("0.01"),
            prompt_cost=Decimal("0.004"),
            completion_cost=Decimal("0.006"),
            total_tokens=15,
            prompt_tokens=10,
            completion_tokens=5,
        )

        trace = trace_from_langsmith_run(run)

        self.assertEqual(trace["id"], "run-1")
        self.assertEqual(trace["tags"], ["arm:mcp_on", "task_id:Q003"])
        self.assertEqual(trace["run_group_id"], "group-1")
        self.assertEqual(trace["mcp_tools_called"], ["mcp__supercontext__find_callers"])
        self.assertEqual(trace["mcp_tool_attempt_count"], 1)
        self.assertEqual(trace["mcp_tool_success_count"], 1)
        self.assertEqual(trace["mcp_tool_denial_count"], 0)
        self.assertEqual(trace["mcp_tool_successes"], ["mcp__supercontext__find_callers"])
        self.assertEqual(trace["non_mcp_tool_attempt_count"], 2)
        self.assertEqual(trace["non_mcp_tool_attempts"], ["Read", "Read"])
        self.assertEqual(trace["cost_status"], "available")
        self.assertEqual(trace["record_cost_status"], "not_uploaded")
        self.assertNotIn("cost_status", trace["metadata"])
        self.assertEqual(trace["total_cost"], 0.01)
        self.assertEqual(trace["prompt_cost"], 0.004)
        self.assertEqual(trace["completion_cost"], 0.006)

    def test_trace_from_langsmith_run_marks_missing_cost_unavailable(self) -> None:
        run = SimpleNamespace(extra={"metadata": {"arm": "mcp_off"}}, tags=[], total_cost=None)

        trace = trace_from_langsmith_run(run)

        self.assertEqual(trace["arm"], "mcp_off")
        self.assertEqual(trace["cost_status"], "unavailable")
        self.assertIsNone(trace["total_cost"])


if __name__ == "__main__":
    unittest.main()
