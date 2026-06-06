from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from source.kg.org.github import GitHubCliRepoProvider


class GitHubCliRepoProviderTest(unittest.TestCase):
    def test_list_repos_parses_github_cli_json(self) -> None:
        payload = [
            {
                "name": "api",
                "nameWithOwner": "Acme/api",
                "sshUrl": "git@github.com:Acme/api.git",
                "url": "https://github.com/Acme/api",
                "isArchived": False,
                "defaultBranchRef": {"name": "main"},
            },
            {
                "name": "old",
                "nameWithOwner": "Acme/old",
                "sshUrl": "git@github.com:Acme/old.git",
                "url": "https://github.com/Acme/old",
                "isArchived": True,
                "defaultBranchRef": {"name": "main"},
            },
        ]

        with patch("source.kg.org.github.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                ("gh",),
                0,
                stdout=json.dumps(payload),
                stderr="",
            )
            repos = GitHubCliRepoProvider(org="Acme", include_archived=False, clone_protocol="ssh").list_repos()

        self.assertEqual([repo.full_name for repo in repos], ["Acme/api"])
        self.assertEqual(repos[0].clone_url, "git@github.com:Acme/api.git")
        self.assertEqual(repos[0].default_branch, "main")
        run_mock.assert_called_once()
        self.assertIn("--json", run_mock.call_args.args[0])

    def test_list_repos_rejects_malformed_rows(self) -> None:
        with patch("source.kg.org.github.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(
                ("gh",),
                0,
                stdout=json.dumps([{"name": "api"}]),
                stderr="",
            )

            with self.assertRaisesRegex(ValueError, "nameWithOwner"):
                GitHubCliRepoProvider(org="Acme").list_repos()

    def test_list_repos_skips_repos_without_default_branch(self) -> None:
        payload = [
            {
                "name": "empty",
                "nameWithOwner": "Acme/empty",
                "sshUrl": "git@github.com:Acme/empty.git",
                "url": "https://github.com/Acme/empty",
                "isArchived": False,
                "defaultBranchRef": None,
            },
            {
                "name": "api",
                "nameWithOwner": "Acme/api",
                "sshUrl": "git@github.com:Acme/api.git",
                "url": "https://github.com/Acme/api",
                "isArchived": False,
                "defaultBranchRef": {"name": "main"},
            },
        ]

        with patch("source.kg.org.github.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess(("gh",), 0, stdout=json.dumps(payload), stderr="")
            repos = GitHubCliRepoProvider(org="Acme").list_repos()

        self.assertEqual([repo.full_name for repo in repos], ["Acme/api"])


if __name__ == "__main__":
    unittest.main()
