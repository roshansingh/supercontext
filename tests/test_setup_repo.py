from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.scripts import setup_repo


class SetupRepoTest(unittest.TestCase):
    def test_default_init_builds_repo_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            stdout, build_mock, _ = self._run_setup("--repo", str(repo))

        self.assertEqual(build_mock.call_count, 1)
        _, out = build_mock.call_args.args[:2]
        self.assertEqual(out, repo.resolve() / ".supercontext" / "kg")
        self.assertIn("SuperContext KG built:", stdout)
        self.assertIn("-m source.scripts.mcp_server --snapshot", stdout)
        self.assertIn("supercontext-install-mcp-skills --scope global", stdout)

    def test_custom_out_and_strict_options_are_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            out = Path(tmp) / "snapshot"
            repo.mkdir()
            _, build_mock, _ = self._run_setup(
                "--repo",
                str(repo),
                "--out",
                str(out),
                "--tenant",
                "tenant-a",
                "--strict-extractors",
            )

        self.assertEqual(build_mock.call_args.args[:2], (repo.resolve(), out.resolve()))
        self.assertEqual(build_mock.call_args.kwargs["tenant_id"], "tenant-a")
        self.assertTrue(build_mock.call_args.kwargs["strict_extractors"])

    def test_serve_starts_mcp_after_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            stdout, _, run_mock = self._run_setup("--repo", str(repo), "--serve", "--host", "::1", "--port", "9999")

        self.assertEqual(run_mock.call_count, 1)
        command = run_mock.call_args.args[0]
        self.assertIn("source.scripts.mcp_server", command)
        self.assertIn("-P", command)
        self.assertIn("--port", command)
        self.assertIn("9999", command)
        self.assertIn("http://[::1]:9999/mcp", stdout)

    def test_serve_rejects_non_loopback_host_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            stderr = io.StringIO()

            with (
                patch("sys.argv", ["setup_repo", "--repo", str(repo), "--serve", "--host", "0.0.0.0"]),
                patch.object(setup_repo, "build_kg") as build_mock,
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit),
            ):
                setup_repo.main()

        build_mock.assert_not_called()
        self.assertIn("only supports loopback", stderr.getvalue())

    def _run_setup(self, *args: str) -> tuple[str, object, object]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        repo_arg = args[args.index("--repo") + 1] if "--repo" in args else "."
        with (
            patch("sys.argv", ["setup_repo", *args]),
            patch.object(
                setup_repo,
                "build_kg",
                return_value={"repo_path": str(Path(repo_arg).resolve())},
            ) as build_mock,
            patch.object(setup_repo.subprocess, "run") as run_mock,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            setup_repo.main()
        return stdout.getvalue(), build_mock, run_mock


if __name__ == "__main__":
    unittest.main()
