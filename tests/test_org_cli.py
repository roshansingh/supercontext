from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.org.workspace import init_org
from source.scripts import supercontext, supercontext_org


class OrgCliTest(unittest.TestCase):
    def test_org_init_prints_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with (
                patch("sys.argv", ["supercontext-org", "init", "--provider", "github", "--org", "Acme", "--home", tmpdir]),
                contextlib.redirect_stdout(stdout),
            ):
                supercontext_org.main()

        output = stdout.getvalue()
        self.assertIn("SuperContext org workspace initialized", output)
        self.assertIn("supercontext org sync", output)
        self.assertIn("supercontext org build", output)

    def test_top_level_cli_dispatches_org_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            with (
                patch("sys.argv", ["supercontext", "org", "init", "--provider", "github", "--org", "Acme", "--home", tmpdir]),
                contextlib.redirect_stdout(stdout),
            ):
                supercontext.main()

            self.assertTrue((Path(tmpdir) / "config.json").exists())
            self.assertIn("SuperContext org workspace initialized", stdout.getvalue())

    def test_org_review_calls_review_context_with_git_changed_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            worktree = Path(tmpdir) / "api"
            worktree.mkdir()
            init_org(provider="github", org="Acme", home=home)
            calls: list[tuple[object, str, dict[str, object]]] = []

            def fake_call_tool(kg, name, arguments):
                calls.append((kg, name, arguments))
                return {"status": "found", "repo": arguments["repo"], "changed_files": arguments["changed_files"]}

            def fake_check_output(command, **kwargs):
                self.assertEqual(kwargs["cwd"], str(worktree.resolve()))
                if command[:3] == ["git", "diff", "--name-only"]:
                    return "src/app.py\n"
                if command[:3] == ["git", "diff", "--unified=0"]:
                    return "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n@@ -10,0 +11,2 @@\n+one\n+two\n"
                raise AssertionError(f"unexpected command: {command}")

            stdout = io.StringIO()
            with (
                patch(
                    "sys.argv",
                    [
                        "supercontext-org",
                        "review",
                        "--home",
                        str(home),
                        "--repo",
                        "Acme/api",
                        "--worktree",
                        str(worktree),
                        "--base",
                        "main",
                        "--head",
                        "feature",
                        "--requested-surface",
                        "schemas",
                        "--include-deploy-blockers",
                    ],
                ),
                patch(
                    "source.scripts.supercontext_org.KgSnapshot",
                    side_effect=lambda snapshot: {"snapshot": snapshot},
                    create=True,
                ),
                patch("source.scripts.supercontext_org.call_tool", side_effect=fake_call_tool, create=True),
                patch("source.scripts.supercontext_org.subprocess.check_output", side_effect=fake_check_output),
                contextlib.redirect_stdout(stdout),
            ):
                supercontext_org.main()

            self.assertEqual(len(calls), 1)
            kg, name, arguments = calls[0]
            self.assertEqual(kg, {"snapshot": home.resolve() / "kg"})
            self.assertEqual(name, "review_context")
            self.assertEqual(arguments["repo"], "Acme/api")
            self.assertEqual(arguments["changed_files"], ["src/app.py"])
            self.assertEqual(
                arguments["changed_ranges"],
                [{"path": "src/app.py", "start_line": 11, "end_line": 12}],
            )
            self.assertEqual(arguments["requested_surfaces"], ["schemas"])
            self.assertTrue(arguments["include_deploy_blockers"])
            self.assertEqual(json.loads(stdout.getvalue())["status"], "found")


if __name__ == "__main__":
    unittest.main()
