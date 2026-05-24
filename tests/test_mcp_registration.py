from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import call, patch

from source.scripts import register_mcp


class McpRegistrationTest(unittest.TestCase):
    def test_registers_codex_and_claude_with_default_local_url(self) -> None:
        output = self._run_register(
            "--agent",
            "both",
            which_side_effect=lambda executable: f"/bin/{executable}",
        )

        self.assertIn("registered codex MCP server", output)
        self.assertIn("registered claude MCP server", output)
        self.run_mock.assert_has_calls(
            [
                call(
                    ("codex", "mcp", "remove", "supercontext"),
                    check=False,
                    stdout=register_mcp.subprocess.DEVNULL,
                    stderr=register_mcp.subprocess.DEVNULL,
                ),
                call(
                    ("codex", "mcp", "remove", "bettercontext"),
                    check=False,
                    stdout=register_mcp.subprocess.DEVNULL,
                    stderr=register_mcp.subprocess.DEVNULL,
                ),
                call(
                    (
                        "codex",
                        "mcp",
                        "add",
                        "supercontext",
                        "--url",
                        "http://127.0.0.1:3845/mcp",
                    ),
                    check=True,
                ),
                call(
                    ("claude", "mcp", "remove", "--scope", "user", "supercontext"),
                    check=False,
                    stdout=register_mcp.subprocess.DEVNULL,
                    stderr=register_mcp.subprocess.DEVNULL,
                ),
                call(
                    ("claude", "mcp", "remove", "--scope", "user", "bettercontext"),
                    check=False,
                    stdout=register_mcp.subprocess.DEVNULL,
                    stderr=register_mcp.subprocess.DEVNULL,
                ),
                call(
                    (
                        "claude",
                        "mcp",
                        "add",
                        "--scope",
                        "user",
                        "--transport",
                        "http",
                        "supercontext",
                        "http://127.0.0.1:3845/mcp",
                    ),
                    check=True,
                ),
            ]
        )

    def test_custom_name_and_url_are_forwarded(self) -> None:
        self._run_register(
            "--agent",
            "codex",
            "--name",
            "bc-local",
            "--url",
            "http://localhost:9999/mcp",
            which_side_effect=lambda executable: f"/bin/{executable}",
        )

        self.run_mock.assert_has_calls(
            [
                call(
                    ("codex", "mcp", "remove", "bc-local"),
                    check=False,
                    stdout=register_mcp.subprocess.DEVNULL,
                    stderr=register_mcp.subprocess.DEVNULL,
                ),
                call(
                    (
                        "codex",
                        "mcp",
                        "add",
                        "bc-local",
                        "--url",
                        "http://localhost:9999/mcp",
                    ),
                    check=True,
                ),
            ]
        )

    def test_dry_run_prints_commands_without_running_them(self) -> None:
        output = self._run_register(
            "--agent",
            "claude",
            "--dry-run",
            which_side_effect=lambda executable: f"/bin/{executable}",
        )

        self.assertIn("would remove existing claude MCP registration", output)
        self.assertIn("would remove legacy claude MCP registration", output)
        self.assertIn("would add claude MCP registration", output)
        self.run_mock.assert_not_called()

    def test_remove_dry_run_prints_remove_without_add(self) -> None:
        output = self._run_register(
            "--agent",
            "claude",
            "--remove",
            "--dry-run",
            which_side_effect=lambda executable: f"/bin/{executable}",
        )

        self.assertIn("would remove existing claude MCP registration", output)
        self.assertNotIn("would add claude MCP registration", output)
        self.run_mock.assert_not_called()

    def test_remove_runs_remove_without_add(self) -> None:
        output = self._run_register(
            "--agent",
            "codex",
            "--remove",
            which_side_effect=lambda executable: f"/bin/{executable}",
        )

        self.assertIn("ran remove command for codex MCP server", output)
        self.run_mock.assert_called_once_with(
            ("codex", "mcp", "remove", "supercontext"),
            check=False,
            stdout=register_mcp.subprocess.DEVNULL,
            stderr=register_mcp.subprocess.DEVNULL,
        )

    def test_remove_failure_warns_by_default_without_claiming_success(self) -> None:
        output = self._run_register(
            "--agent",
            "codex",
            "--remove",
            which_side_effect=lambda executable: f"/bin/{executable}",
            run_side_effect=[
                register_mcp.subprocess.CompletedProcess(
                    ("codex", "mcp", "remove", "supercontext"),
                    1,
                ),
            ],
        )

        self.assertIn("warning: codex MCP registration failed (exit code 1)", output)
        self.assertNotIn("ran remove command for codex MCP server", output)

    def test_remove_failure_errors_in_strict_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register(
                "--agent",
                "codex",
                "--remove",
                "--on-error",
                "error",
                which_side_effect=lambda executable: f"/bin/{executable}",
                run_side_effect=[
                    register_mcp.subprocess.CompletedProcess(
                        ("codex", "mcp", "remove", "supercontext"),
                        1,
                    ),
                ],
            )

    def test_missing_cli_warns_by_default(self) -> None:
        output = self._run_register(
            "--agent",
            "codex",
            which_side_effect=lambda executable: None,
        )

        self.assertIn("warning: 'codex' CLI not found", output)
        self.run_mock.assert_not_called()

    def test_missing_cli_errors_in_strict_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register(
                "--agent",
                "codex",
                "--on-error",
                "error",
                which_side_effect=lambda executable: None,
            )

        self.run_mock.assert_not_called()

    def test_hidden_missing_alias_maps_to_strict_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register(
                "--agent",
                "codex",
                "--missing",
                "error",
                which_side_effect=lambda executable: None,
            )

        self.run_mock.assert_not_called()

    def test_add_failure_warns_by_default(self) -> None:
        output = self._run_register(
            "--agent",
            "codex",
            which_side_effect=lambda executable: f"/bin/{executable}",
            run_side_effect=[
                register_mcp.subprocess.CompletedProcess(
                    ("codex", "mcp", "remove", "supercontext"),
                    1,
                ),
                register_mcp.subprocess.CompletedProcess(
                    ("codex", "mcp", "remove", "bettercontext"),
                    1,
                ),
                register_mcp.subprocess.CalledProcessError(
                    2,
                    (
                        "codex",
                        "mcp",
                        "add",
                        "supercontext",
                        "--url",
                        "http://127.0.0.1:3845/mcp",
                    ),
                ),
            ],
        )

        self.assertIn("warning: codex MCP registration failed (exit code 2)", output)

    def test_add_failure_errors_in_strict_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register(
                "--agent",
                "codex",
                "--on-error",
                "error",
                which_side_effect=lambda executable: f"/bin/{executable}",
                run_side_effect=[
                    register_mcp.subprocess.CompletedProcess(
                        ("codex", "mcp", "remove", "supercontext"),
                        1,
                    ),
                    register_mcp.subprocess.CompletedProcess(
                        ("codex", "mcp", "remove", "bettercontext"),
                        1,
                    ),
                    register_mcp.subprocess.CalledProcessError(
                        2,
                        (
                            "codex",
                            "mcp",
                            "add",
                            "supercontext",
                            "--url",
                            "http://127.0.0.1:3845/mcp",
                        ),
                    ),
                ],
            )

    def test_both_agents_continue_after_warn_mode_failure(self) -> None:
        output = self._run_register(
            "--agent",
            "both",
            which_side_effect=lambda executable: f"/bin/{executable}",
            run_side_effect=[
                register_mcp.subprocess.CompletedProcess(
                    ("codex", "mcp", "remove", "supercontext"),
                    1,
                ),
                register_mcp.subprocess.CompletedProcess(
                    ("codex", "mcp", "remove", "bettercontext"),
                    0,
                ),
                register_mcp.subprocess.CompletedProcess(
                    (
                        "codex",
                        "mcp",
                        "add",
                        "supercontext",
                        "--url",
                        "http://127.0.0.1:3845/mcp",
                    ),
                    0,
                ),
                register_mcp.subprocess.CompletedProcess(
                    ("claude", "mcp", "remove", "--scope", "user", "supercontext"),
                    1,
                ),
                register_mcp.subprocess.CompletedProcess(
                    ("claude", "mcp", "remove", "--scope", "user", "bettercontext"),
                    1,
                ),
                register_mcp.subprocess.CalledProcessError(
                    2,
                    (
                        "claude",
                        "mcp",
                        "add",
                        "--scope",
                        "user",
                        "--transport",
                        "http",
                        "supercontext",
                        "http://127.0.0.1:3845/mcp",
                    ),
                ),
            ],
        )

        self.assertIn("registered codex MCP server", output)
        self.assertIn("warning: claude MCP registration failed", output)

    def test_os_error_warns_by_default(self) -> None:
        output = self._run_register(
            "--agent",
            "codex",
            which_side_effect=lambda executable: f"/bin/{executable}",
            run_side_effect=PermissionError("cannot execute codex"),
        )

        self.assertIn(
            "warning: codex MCP registration failed (cannot execute codex)",
            output,
        )

    def test_os_error_errors_in_strict_mode(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register(
                "--agent",
                "codex",
                "--on-error",
                "error",
                which_side_effect=lambda executable: f"/bin/{executable}",
                run_side_effect=PermissionError("cannot execute codex"),
            )

    def test_empty_or_non_http_values_are_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self._run_register("--name", "")
        with self.assertRaises(SystemExit):
            self._run_register("--url", "")
        with self.assertRaises(SystemExit):
            self._run_register("--url", "file:///tmp/mcp")
        with self.assertRaises(SystemExit):
            self._run_register("--url", "http://")

    def _run_register(
        self,
        *args: str,
        which_side_effect=None,
        run_side_effect=None,
    ) -> str:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.argv", ["register_mcp", *args]),
            patch.object(
                register_mcp.shutil,
                "which",
                side_effect=which_side_effect or (lambda executable: None),
            ),
            patch.object(
                register_mcp.subprocess,
                "run",
                side_effect=run_side_effect,
            ) as run_mock,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.run_mock = run_mock
            register_mcp.main()
        return stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
