from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path

from source.kg.build.pipeline import build_kg
from source.kg.build.multi_repo import build_multi_kg
from source.kg.build.relink import relink_snapshot_dirs, resolve_snapshot_dirs
from source.kg.core.store import read_jsonl


class RelinkOnlyTest(unittest.TestCase):
    def test_relink_snapshot_dirs_matches_batch_linker_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import shared_provider\n")
            provider = _python_repo(root / "owner-b" / "shared-provider", "shared_provider", "")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            combined = root / "combined"

            build_kg(consumer, consumer_snapshot)
            build_kg(provider, provider_snapshot)
            relink_manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)
            build_multi_kg([consumer, provider], combined)

            relink_facts = _records_by_id(read_jsonl(fleet / "cross_repo_links.jsonl"), "fact_id")
            batch_facts = _records_by_id(
                [
                    row
                    for row in read_jsonl(combined / "facts.jsonl")
                    if row["predicate"] in {"RESOLVES_TO_REPO", "RESOLVES_TO_SERVICE"}
                ],
                "fact_id",
            )
            self.assertEqual(relink_facts, batch_facts)
            self.assertEqual(relink_manifest["link_count"], len(batch_facts))
            self.assertEqual(relink_manifest["repo_commit_sha_set"], ["working-tree"])
            evidence = read_jsonl(fleet / "cross_repo_link_evidence.jsonl")
            self.assertEqual({row["target_id"] for row in evidence}, set(relink_facts))
            self.assertEqual({row["source_system"] for row in evidence}, {"package_linker"})

    def test_resolve_snapshot_dirs_expands_fleet_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            fleet = root / "_fleet"
            snapshot.mkdir()
            fleet.mkdir()
            (snapshot / "manifest.json").write_text("{}\n", encoding="utf-8")
            (fleet / "manifest.json").write_text("{}\n", encoding="utf-8")

            self.assertEqual(resolve_snapshot_dirs((root,)), (snapshot.resolve(),))

    def test_relink_rejects_duplicate_repo_identity_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot_a = root / "snapshots" / "a"
            snapshot_b = root / "snapshots" / "b"
            build_kg(repo, snapshot_a)
            build_kg(repo, snapshot_b)

            with self.assertRaisesRegex(ValueError, "unique repo identities"):
                relink_snapshot_dirs([snapshot_a, snapshot_b], root / "_fleet")

    def test_relink_rejects_tenant_override_that_does_not_match_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)

            with self.assertRaisesRegex(ValueError, "tenant override must match snapshot tenant_id"):
                relink_snapshot_dirs([snapshot], root / "_fleet", tenant_id="other-tenant")

    def test_relink_rejects_mixed_tenant_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = _python_repo(root / "owner-a" / "consumer-a", "consumer-a", "")
            repo_b = _python_repo(root / "owner-b" / "consumer-b", "consumer-b", "")
            snapshot_a = root / "snapshots" / "a"
            snapshot_b = root / "snapshots" / "b"
            build_kg(repo_a, snapshot_a, tenant_id="tenant-a")
            build_kg(repo_b, snapshot_b, tenant_id="tenant-b")

            with self.assertRaisesRegex(ValueError, "one tenant"):
                relink_snapshot_dirs([snapshot_a, snapshot_b], root / "_fleet")

    def test_relink_does_not_link_stdlib_imports_to_same_named_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import json\n")
            provider = _python_repo(root / "owner-b" / "json", "json", "")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot)
            build_kg(provider, provider_snapshot)

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(fleet / "cross_repo_links.jsonl"), [])

    def test_relink_skips_missing_distribution_candidate_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import unknown_package\n")
            provider = _python_repo(root / "owner-b" / "none", "none", "")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot)
            build_kg(provider, provider_snapshot)

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(fleet / "cross_repo_links.jsonl"), [])

    def test_relink_rejects_repo_commit_that_moved_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "initial")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").write_text('[project]\nname = "changed-package"\n', encoding="utf-8")
            _git(repo, "add", "pyproject.toml")
            _git(repo, "commit", "-m", "change package")

            with self.assertRaisesRegex(ValueError, "does not match current repo commit"):
                relink_snapshot_dirs([snapshot], root / "_fleet")


def _records_by_id(rows: list[dict], key: str) -> dict[str, dict]:
    return {str(row[key]): row for row in rows}


def _python_repo(path: Path, package_name: str, source: str) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{package_name}"\n', encoding="utf-8")
    if source:
        (path / "module.py").write_text(source, encoding="utf-8")
    package_dir = path / package_name.replace("-", "_")
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
