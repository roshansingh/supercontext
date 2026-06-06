from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo


class RepoSourceTest(unittest.TestCase):
    def test_discover_repo_accepts_explicit_owner_for_managed_caches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "org-cache" / "repos" / "api"
            repo.mkdir(parents=True)

            snapshot = discover_repo(repo, owner="Acme")

        self.assertEqual(snapshot.name, "api")
        self.assertEqual(snapshot.owner, "Acme")


if __name__ == "__main__":
    unittest.main()
