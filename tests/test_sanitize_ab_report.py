from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.scripts.sanitize_ab_report import render_sanitized_report


class SanitizeAbReportTest(unittest.TestCase):
    def test_render_sanitized_report_excludes_raw_answers_and_reproduces_docs(self) -> None:
        rows = [
            {
                "task_id": "Q001",
                "phase": "planning",
                "difficulty": "Low",
                "quality_verdict": "judged",
                "judge_winner": "mcp_on",
                "judge_aspect_winners": {
                    "correctness": "mcp_on",
                    "evidence": "mcp_off",
                    "completeness": "tie",
                    "actionability": "mcp_on",
                },
                "judge_confidence": 0.9,
                "judge_reasoning": "private reasoning",
                "langsmith_run_url": "https://smith.langchain.com/private",
                "cost_status": "available",
                "dollars_delta": 0.123456789,
                "deltas": {
                    "tool_calls": 1,
                    "mcp_calls": -1,
                    "non_mcp_calls": 2,
                    "tokens_in": 10,
                    "tokens_out": 20,
                    "wall_time_seconds": 1.234567,
                    "citations_count": 0,
                },
                "on": {"answer": "private on answer"},
                "off": {"answer": "private off answer"},
            },
            {
                "task_id": "Q002",
                "phase": "review",
                "difficulty": "Medium",
                "quality_verdict": "judged",
                "judge_winner": "tie",
                "judge_aspect_winners": {
                    "correctness": "tie",
                    "evidence": "tie",
                    "completeness": "tie",
                    "actionability": "tie",
                },
                "judge_confidence": 0.5,
                "cost_status": "available",
                "dollars_delta": -0.10000000000000002,
                "deltas": {
                    "tool_calls": -1,
                    "mcp_calls": -1,
                    "non_mcp_calls": 0,
                    "tokens_in": -5,
                    "tokens_out": 5,
                    "wall_time_seconds": -0.0000001,
                    "citations_count": 0,
                },
            },
            {
                "task_id": "Q003",
                "phase": None,
                "difficulty": None,
                "quality_verdict": "judge_error",
                "cost_status": "unavailable",
                "dollars_delta": None,
                "deltas": {
                    "tool_calls": 0,
                    "mcp_calls": 0,
                    "non_mcp_calls": 0,
                    "tokens_in": 12,
                    "tokens_out": None,
                    "wall_time_seconds": None,
                    "citations_count": 0,
                },
            }
        ]
        raw_report = {
            "phase_aggregates": {
                "planning": {
                    "tasks": 1,
                    "avg_tool_calls_delta": 1.0,
                    "avg_token_delta": 30.0,
                    "avg_wall_time_delta": 1.235,
                }
            },
            "rows": rows,
        }

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            render_sanitized_report(
                rows=rows,
                raw_report=raw_report,
                out_dir=out_dir,
                run_id="run-1",
                run_date="2026-05-23",
                judge_model="judge-test",
                seed=6,
            )

            report_json = json.loads((out_dir / "ab-report.json").read_text(encoding="utf-8"))
            combined_text = "\n".join(path.read_text(encoding="utf-8") for path in out_dir.iterdir())

        self.assertEqual(report_json["judge_winners"], {"mcp_on": 1, "tie": 1, "unknown": 1})
        self.assertEqual(report_json["judge_aspect_winners"]["correctness"], {"mcp_on": 1, "tie": 1, "unknown": 1})
        self.assertEqual(report_json["judge_aspect_winners"]["evidence"], {"mcp_off": 1, "tie": 1, "unknown": 1})
        self.assertEqual(sum(report_json["judge_winners"].values()), report_json["task_count"])
        self.assertEqual(report_json["rows"][0]["deltas"]["tokens_total"], 30)
        self.assertIsNone(report_json["rows"][2]["deltas"]["tokens_total"])
        self.assertEqual(report_json["rows"][2]["phase"], "unknown")
        self.assertEqual(report_json["rows"][2]["difficulty"], "unknown")
        self.assertEqual(report_json["rows"][2]["quality_verdict"], "judge_error")
        self.assertEqual(report_json["rows"][2]["judge_winner"], "unknown")
        self.assertIsNone(report_json["rows"][2]["judge_confidence"])
        self.assertIsNone(report_json["rows"][0]["mcp_on_tool_health"]["successes"])
        self.assertEqual(report_json["rows"][0]["dollars_delta"], 0.123457)
        self.assertEqual(report_json["rows"][1]["dollars_delta"], -0.1)
        self.assertEqual(report_json["rows"][1]["deltas"]["wall_time_seconds"], 0)
        self.assertIn("n/a", combined_text)
        self.assertIn("Cost data was available for 2 of 3 rows.", combined_text)
        self.assertIn("Token data was available for 2 of 3 rows.", combined_text)
        self.assertIn("Quality gate: answer quality must be at least tied", combined_text)
        self.assertIn("| correctness | 0 | 1 | 1 | 1 |", combined_text)
        self.assertIn("| Q001 | planning | Low | mcp_on (0.9) | mcp_on | mcp_off | tie | mcp_on | n/a | n/a |", combined_text)
        self.assertIn("Total dollar delta: `n/a`", combined_text)
        self.assertIn("Total token delta: `n/a`", combined_text)
        self.assertIn("MCP improved judged answer quality on more tasks", combined_text)
        self.assertIn("did not win 1 of 2 judged tasks", combined_text)
        self.assertNotIn("answer quality was worse on most judged tasks", combined_text)
        self.assertNotIn("lost quality on most planning and coding tasks", combined_text)
        self.assertIn("`mcp_off` won on none.", combined_text)
        self.assertNotIn("| -0 |", combined_text)
        self.assertNotIn("None", combined_text)
        self.assertIn("# SuperContext A/B Report - run-1 - 2026-05-23", combined_text)
        self.assertIn("# Trace Analysis - run-1 - 2026-05-23", combined_text)
        self.assertIn("Verification should rerun `run-1`", combined_text)
        self.assertIn("source.scripts.sanitize_ab_report", combined_text)
        self.assertIn("| Phase | mcp_off wins | mcp_on wins | Ties |", combined_text)
        self.assertNotIn("default-v1", combined_text)
        self.assertNotIn("private on answer", combined_text)
        self.assertNotIn("private off answer", combined_text)
        self.assertNotIn("private reasoning", combined_text)
        self.assertNotIn("smith.langchain.com", combined_text)


if __name__ == "__main__":
    unittest.main()
