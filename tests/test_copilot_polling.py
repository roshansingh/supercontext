from __future__ import annotations

import unittest
from unittest.mock import patch

from source.scripts import poll_copilot_review


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
            patch("source.scripts.poll_copilot_review._gh_json", side_effect=gh_json),
            patch("source.scripts.poll_copilot_review._unresolved_copilot_threads", return_value=[]),
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
            patch("source.scripts.poll_copilot_review._gh_json", side_effect=gh_json),
            patch("source.scripts.poll_copilot_review._unresolved_copilot_threads", return_value=[]),
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


if __name__ == "__main__":
    unittest.main()
