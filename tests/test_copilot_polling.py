from __future__ import annotations

import unittest
from importlib import util
from pathlib import Path
from unittest.mock import patch


def _load_poll_script() -> object:
    script_path = Path(__file__).resolve().parents[1] / ".codex" / "scripts" / "poll_copilot_review.py"
    spec = util.spec_from_file_location("poll_copilot_review", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


poll_copilot_review = _load_poll_script()


class CopilotPollingTest(unittest.TestCase):
    def test_poll_once_ignores_stale_copilot_events(self) -> None:
        def gh_json(args: list[str]) -> object:
            endpoint = args[1] if len(args) > 1 else ""
            if endpoint.endswith("/reviews"):
                return []
            if endpoint.endswith("/comments"):
                return []
            if endpoint.endswith("/events"):
                return [
                    {
                        "event": "copilot_work_started",
                        "created_at": "2026-05-10T10:00:00Z",
                    }
                ]
            raise AssertionError(f"unexpected gh api call: {args}")

        with (
            patch.object(poll_copilot_review, "_gh_json", side_effect=gh_json),
            patch.object(poll_copilot_review, "_unresolved_copilot_threads", return_value=[]),
        ):
            result = poll_copilot_review._poll_once(
                "owner/repo",
                20,
                "new-head",
                "2026-05-10T11:00:00Z",
            )

        self.assertFalse(result["activity"])
        self.assertFalse(result["feedback"])
        self.assertEqual(result["events"], [])

    def test_poll_once_counts_current_head_review_as_feedback(self) -> None:
        def gh_json(args: list[str]) -> object:
            endpoint = args[1] if len(args) > 1 else ""
            if endpoint.endswith("/reviews"):
                return [
                    {
                        "user": {"login": "Copilot"},
                        "commit_id": "new-head",
                        "state": "COMMENTED",
                    }
                ]
            if endpoint.endswith("/comments"):
                return []
            if endpoint.endswith("/events"):
                return []
            raise AssertionError(f"unexpected gh api call: {args}")

        with (
            patch.object(poll_copilot_review, "_gh_json", side_effect=gh_json),
            patch.object(poll_copilot_review, "_unresolved_copilot_threads", return_value=[]),
        ):
            result = poll_copilot_review._poll_once(
                "owner/repo",
                20,
                "new-head",
                "2026-05-10T11:00:00Z",
            )

        self.assertTrue(result["activity"])
        self.assertTrue(result["feedback"])
        self.assertEqual(len(result["reviews"]), 1)

    def test_head_commit_timestamp_uses_pushed_date(self) -> None:
        with patch.object(
            poll_copilot_review,
            "_gh_json",
            return_value={
                "data": {
                    "repository": {
                        "object": {
                            "pushedDate": "2026-05-10T12:00:00Z",
                            "committedDate": "2026-05-01T12:00:00Z",
                        }
                    }
                }
            },
        ) as gh_json:
            timestamp = poll_copilot_review._head_commit_pushed_at("owner/repo", "abc123")

        self.assertEqual(timestamp, "2026-05-10T12:00:00Z")
        self.assertIn("graphql", gh_json.call_args.args[0])

    def test_default_poll_delays_use_six_minute_schedule(self) -> None:
        self.assertEqual(poll_copilot_review._poll_delays(None, 360), [120, 120, 60, 60])

    def test_fixed_poll_interval_respects_timeout(self) -> None:
        self.assertEqual(poll_copilot_review._poll_delays(120, 300), [120, 120, 60])


if __name__ == "__main__":
    unittest.main()
