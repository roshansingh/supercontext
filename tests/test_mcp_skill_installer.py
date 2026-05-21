from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.scripts import install_mcp_skills


class McpSkillInstallerTest(unittest.TestCase):
    def test_project_install_copies_only_bettercontext_mcp_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            existing_codex = project / ".codex" / "skills" / "coverage-report"
            existing_claude = project / ".claude" / "skills" / "coverage-report"
            existing_codex.mkdir(parents=True)
            existing_claude.mkdir(parents=True)
            (existing_codex / "SKILL.md").write_text("existing codex skill", encoding="utf-8")
            (existing_claude / "SKILL.md").write_text("existing claude skill", encoding="utf-8")

            self._run_installer("--scope", "project", "--project", str(project), "--agent", "both")

            self.assertEqual(
                sorted(path.name for path in (project / ".codex" / "skills").iterdir()),
                ["bettercontext-mcp", "coverage-report"],
            )
            self.assertEqual(
                sorted(path.name for path in (project / ".claude" / "skills").iterdir()),
                ["bettercontext-mcp", "coverage-report"],
            )
            self.assertIn(
                "name: bettercontext-mcp",
                (project / ".codex" / "skills" / "bettercontext-mcp" / "SKILL.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "name: bettercontext-mcp",
                (project / ".claude" / "skills" / "bettercontext-mcp" / "SKILL.md").read_text(encoding="utf-8"),
            )

    def test_install_replaces_stale_files_inside_target_skill_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = project / ".codex" / "skills" / "bettercontext-mcp"
            sibling = project / ".codex" / "skills" / "coverage-report"
            target.mkdir(parents=True)
            sibling.mkdir()
            (target / "old.md").write_text("stale", encoding="utf-8")
            (sibling / "SKILL.md").write_text("existing", encoding="utf-8")

            self._run_installer("--scope", "project", "--project", str(project), "--agent", "codex")

            self.assertFalse((target / "old.md").exists())
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((sibling / "SKILL.md").is_file())

    def test_global_install_uses_agent_homes(self) -> None:
        with tempfile.TemporaryDirectory() as codex_tmp, tempfile.TemporaryDirectory() as claude_tmp:
            self._run_installer(
                "--scope",
                "global",
                "--agent",
                "both",
                "--codex-home",
                codex_tmp,
                "--claude-home",
                claude_tmp,
            )

            self.assertTrue((Path(codex_tmp) / "skills" / "bettercontext-mcp" / "SKILL.md").is_file())
            self.assertTrue((Path(claude_tmp) / "skills" / "bettercontext-mcp" / "SKILL.md").is_file())

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            output = self._run_installer("--scope", "project", "--project", str(project), "--dry-run")

            self.assertIn("would install codex skill", output)
            self.assertIn("would install claude skill", output)
            self.assertFalse((project / ".codex").exists())
            self.assertFalse((project / ".claude").exists())

    def _run_installer(self, *args: str) -> str:
        stdout = io.StringIO()
        with patch("sys.argv", ["install_mcp_skills", *args]), contextlib.redirect_stdout(stdout):
            install_mcp_skills.main()
        return stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
