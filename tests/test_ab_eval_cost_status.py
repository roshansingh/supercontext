from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.eval.runner import RunRecord, RunnerConfig, _mcp_servers, _prepare_arm_output_dir, _usage_tokens


class AbEvalCostStatusTest(unittest.TestCase):
    def test_local_run_record_has_no_silent_dollar_default(self) -> None:
        record = RunRecord(
            run_group_id="group-1",
            arm="mcp_on",
            task_id="Q003",
            phase="coding",
            host="claude_code",
            repo_fixture="$PY_REPO",
            difficulty="Low",
            harness_version="ab-eval-v1",
            task_prompt="Who calls load_model?",
            snapshot_path="data/kg_runs/example",
            mcp_tools_called=[],
            non_mcp_tools_called=[],
            tokens_in=None,
            tokens_out=None,
            wall_time_seconds=0.0,
            final_answer="",
            final_answer_citations=[],
            host_session_log_path="data/ab_runs/smoke/mcp_on/messages.jsonl",
            model="claude-sonnet-4-5-20250929",
            random_seed=0,
        )

        payload = record.to_json()
        self.assertEqual(payload["cost_status"], "not_uploaded")
        self.assertNotIn("dollars_spent", payload)
        self.assertNotIn("pricing_version", payload)

    def test_mcp_servers_only_attached_for_on_arm(self) -> None:
        config = RunnerConfig(mcp_url="http://127.0.0.1:9999/mcp")

        self.assertEqual(_mcp_servers("mcp_off", config), {})
        self.assertEqual(
            _mcp_servers("mcp_on", config),
            {"bettercontext": {"type": "http", "url": "http://127.0.0.1:9999/mcp"}},
        )

    def test_usage_tokens_sum_across_messages(self) -> None:
        messages = [
            {"data": {"usage": {"input_tokens": 3, "output_tokens": 5}}},
            {"data": {"usage": {"input_tokens": 7, "completion_tokens": 11}}},
            {"data": {"usage": {"input_tokens": True, "output_tokens": 13}}},
        ]

        self.assertEqual(_usage_tokens(messages), (10, 29))

    def test_usage_tokens_skip_nested_duplicate_keys_and_preserve_zero(self) -> None:
        messages = [
            {"data": {"usage": {"input_tokens": 0, "details": {"input_tokens": 3}}}},
            {"data": {"usage": {"output_tokens": 0}}},
        ]

        self.assertEqual(_usage_tokens(messages), (0, 0))

    def test_arm_output_dir_uses_run_group_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arm_dir = _prepare_arm_output_dir(root, group_id="group-1", arm="mcp_on")

            self.assertEqual(arm_dir, root / "group-1" / "mcp_on")
            with self.assertRaisesRegex(ValueError, "already exists"):
                _prepare_arm_output_dir(root, group_id="group-1", arm="mcp_on")


if __name__ == "__main__":
    unittest.main()
