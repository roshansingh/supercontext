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
        self.assertFalse(result["review_completed"])
        self.assertFalse(result["actionable_feedback"])
        self.assertEqual(result["events"], [])

    def test_poll_once_counts_current_head_review_as_completed_not_actionable(self) -> None:
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
        self.assertTrue(result["review_completed"])
        self.assertFalse(result["actionable_feedback"])
        self.assertEqual(len(result["reviews"]), 1)

    def test_poll_once_counts_unresolved_thread_as_actionable(self) -> None:
        def gh_json(args: list[str]) -> object:
            endpoint = args[1] if len(args) > 1 else ""
            if endpoint.endswith("/reviews"):
                return []
            if endpoint.endswith("/comments"):
                return []
            if endpoint.endswith("/events"):
                return []
            raise AssertionError(f"unexpected gh api call: {args}")

        with (
            patch.object(poll_copilot_review, "_gh_json", side_effect=gh_json),
            patch.object(
                poll_copilot_review,
                "_unresolved_copilot_threads",
                return_value=[{"id": "thread-1", "path": "source.py", "comments": []}],
            ),
        ):
            result = poll_copilot_review._poll_once(
                "owner/repo",
                20,
                "new-head",
                "2026-05-10T11:00:00Z",
            )

        self.assertTrue(result["activity"])
        self.assertFalse(result["review_completed"])
        self.assertTrue(result["actionable_feedback"])

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

    def test_request_copilot_review_uses_gh_pr_edit(self) -> None:
        completed = poll_copilot_review.subprocess.CompletedProcess(
            ["gh", "pr", "edit"],
            0,
            stdout="",
            stderr="",
        )

        with patch.object(poll_copilot_review.subprocess, "run", return_value=completed) as run:
            result = poll_copilot_review._request_copilot_review(
                "owner/repo",
                42,
                "abcdef123456",
                comment_fallback=True,
            )

        self.assertTrue(result["requested"])
        self.assertIn("gh pr edit", result["message"])
        self.assertEqual(
            run.call_args.args[0],
            ["gh", "pr", "edit", "42", "--add-reviewer", "@copilot"],
        )

    def test_request_copilot_review_posts_comment_fallback_when_reviewer_request_fails(self) -> None:
        failed_reviewer_request = poll_copilot_review.subprocess.CompletedProcess(
            ["gh", "pr", "edit"],
            1,
            stdout="",
            stderr="Reviews may only be requested from collaborators.",
        )
        posted_comment = poll_copilot_review.subprocess.CompletedProcess(
            ["gh", "api"],
            0,
            stdout='{"id":1}',
            stderr="",
        )

        with patch.object(
            poll_copilot_review.subprocess,
            "run",
            side_effect=[failed_reviewer_request, posted_comment],
        ) as run:
            result = poll_copilot_review._request_copilot_review(
                "owner/repo",
                42,
                "abcdef123456",
                comment_fallback=True,
            )

        self.assertTrue(result["requested"])
        self.assertIn("comment fallback", result["message"])
        self.assertEqual(run.call_count, 2)
        fallback_command = run.call_args.args[0]
        self.assertEqual(fallback_command[:5], ["gh", "api", "-X", "POST", "repos/owner/repo/issues/42/comments"])
        self.assertIn("@copilot please review the latest changes", fallback_command[-1])

    def test_request_copilot_review_can_disable_comment_fallback(self) -> None:
        failed_reviewer_request = poll_copilot_review.subprocess.CompletedProcess(
            ["gh", "pr", "edit"],
            1,
            stdout="",
            stderr="Reviews may only be requested from collaborators.",
        )

        with patch.object(poll_copilot_review.subprocess, "run", return_value=failed_reviewer_request) as run:
            result = poll_copilot_review._request_copilot_review(
                "owner/repo",
                42,
                "abcdef123456",
                comment_fallback=False,
            )

        self.assertFalse(result["requested"])
        self.assertIn("Could not request", result["message"])
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
