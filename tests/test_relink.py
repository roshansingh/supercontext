from __future__ import annotations

import json
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
            self.assertEqual(relink_manifest["tenant_id"], "default")
            self.assertEqual(relink_manifest["repo_commit_sha_set"], ["working-tree"])
            self.assertEqual(len(relink_manifest["repo_commit_fingerprints"]), 2)
            evidence = read_jsonl(fleet / "cross_repo_link_evidence.jsonl")
            self.assertEqual({row["target_id"] for row in evidence}, set(relink_facts))
            self.assertEqual({row["source_system"] for row in evidence}, {"package_linker"})

    def test_resolve_snapshot_dirs_expands_fleet_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            fleet = root / "links"
            snapshot.mkdir()
            fleet.mkdir()
            (snapshot / "manifest.json").write_text(
                json.dumps({"repo_path": str(snapshot), "commit_sha": "working-tree"}) + "\n",
                encoding="utf-8",
            )
            (fleet / "manifest.json").write_text(
                json.dumps({"build_type": "fleet_relink"}) + "\n",
                encoding="utf-8",
            )
            (root / "manifest.json").write_text(
                json.dumps({"build_type": "fleet_relink"}) + "\n",
                encoding="utf-8",
            )

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

    def test_relink_rejects_manifest_repo_path_that_is_not_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["repo_path"] = str(repo / "pyproject.toml")
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "repo_path must be a directory"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_output_dir_that_is_input_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)

            with self.assertRaisesRegex(ValueError, "output_dir must not be one of the input snapshot"):
                relink_snapshot_dirs([snapshot], snapshot)

    def test_relink_rejects_non_object_entity_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            with (snapshot / "entities.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("[]\n")

            with self.assertRaisesRegex(ValueError, "row .* must be a JSON object"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_accepts_non_object_package_json_as_repo_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "consumer"}\n', encoding="utf-8")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "package.json").write_text("[]\n", encoding="utf-8")

            manifest = relink_snapshot_dirs([snapshot], root / "_fleet")

            self.assertEqual(manifest["provider_count"], 1)

    def test_relink_accepts_malformed_pyproject_tables_as_repo_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").write_text('[tool]\npoetry = "not-a-table"\n', encoding="utf-8")

            manifest = relink_snapshot_dirs([snapshot], root / "_fleet")

            self.assertEqual(manifest["provider_count"], 1)

    def test_relink_rejects_deleted_pyproject_before_package_json_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            (repo / "package.json").write_text('{"name": "consumer-package"}\n', encoding="utf-8")
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "initial")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").unlink()

            with self.assertRaisesRegex(ValueError, "Package manifest has uncommitted changes"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_build_multi_allows_dirty_package_manifest_for_fresh_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import shared_provider\n")
            provider = _python_repo(root / "owner-b" / "provider", "shared_provider", "")
            _git(provider, "init")
            _git(provider, "config", "user.email", "test@example.com")
            _git(provider, "config", "user.name", "Test User")
            _git(provider, "add", ".")
            _git(provider, "commit", "-m", "initial")
            (provider / "pyproject.toml").write_text(
                '[project]\nname = "shared_provider"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            out = root / "combined"

            manifest = build_multi_kg([consumer, provider], out)

            self.assertGreater(manifest["linker"]["link_count"], 0)


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
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
