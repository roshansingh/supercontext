from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.org.git import GitClient
from source.kg.org.workspace import DiscoveredRepo


class OrgGitClientTest(unittest.TestCase):
    def test_sync_repo_replaces_incomplete_managed_cache_clone(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "org"
            home.mkdir()
            (home / "config.json").write_text("{}", encoding="utf-8")
            destination = home / "repos" / "api"
            (destination / ".git").mkdir(parents=True)
            (destination / "partial.pack").write_text("partial", encoding="utf-8")
            commands: list[tuple[list[str], int]] = []

            def run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
                commands.append((command, timeout_seconds))
                if command[1] == "clone":
                    destination.mkdir(parents=True, exist_ok=True)
                return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")

            repo = DiscoveredRepo(
                name="api",
                full_name="Acme/api",
                clone_url="https://github.com/Acme/api",
                default_branch="main",
            )

            with patch("source.kg.org.git._run", side_effect=run):
                commit_sha = GitClient(timeout_seconds=12).sync_repo(repo, destination)

            self.assertEqual(commit_sha, "abc123")
            self.assertEqual(commands[0][0][1], "clone")
            self.assertEqual(commands[0][1], 12)
            self.assertTrue((destination / ".supercontext-managed-repo").exists())

    def test_sync_repo_refuses_existing_unmanaged_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "repos" / "api"
            destination.mkdir(parents=True)
            repo = DiscoveredRepo(
                name="api",
                full_name="Acme/api",
                clone_url="https://github.com/Acme/api",
                default_branch="main",
            )

            with self.assertRaisesRegex(ValueError, "unmanaged"):
                GitClient(timeout_seconds=12).sync_repo(repo, destination)

    def test_sync_repo_refuses_marker_for_different_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "repos" / "api"
            destination.mkdir(parents=True)
            (destination / ".supercontext-managed-repo").write_text("Acme/other", encoding="utf-8")
            repo = DiscoveredRepo(
                name="api",
                full_name="Acme/api",
                clone_url="https://github.com/Acme/api",
                default_branch="main",
            )

            with self.assertRaisesRegex(ValueError, "marked for"):
                GitClient(timeout_seconds=12).sync_repo(repo, destination)


if __name__ == "__main__":
    unittest.main()
