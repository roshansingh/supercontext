from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.build import relink as relink_module
from source.kg.build.pipeline import build_kg
from source.kg.build.multi_repo import build_multi_kg
from source.kg.build.relink import default_output_dir, relink_snapshot_dirs, resolve_snapshot_dirs
from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import read_jsonl
from source.scripts import relink as relink_cli


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

            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")
            relink_manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)
            build_multi_kg([consumer, provider], combined, tenant_id="default")

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

    def test_relink_removes_stale_full_snapshot_artifacts_from_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            fleet = root / "snapshots" / "_fleet"
            build_kg(repo, snapshot, tenant_id="default")
            fleet.mkdir(parents=True)
            for filename in ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl", "metrics.jsonl"):
                (fleet / filename).write_text('{"stale": true}\n', encoding="utf-8")

            relink_snapshot_dirs([snapshot], fleet)

            self.assertTrue((fleet / "cross_repo_links.jsonl").exists())
            self.assertTrue((fleet / "cross_repo_link_evidence.jsonl").exists())
            for filename in ("entities.jsonl", "facts.jsonl", "evidence.jsonl", "coverage.jsonl", "metrics.jsonl"):
                self.assertFalse((fleet / filename).exists())

    def test_relink_keeps_stale_snapshot_artifacts_when_new_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            fleet = root / "snapshots" / "_fleet"
            build_kg(repo, snapshot)
            fleet.mkdir(parents=True)
            stale_entities = fleet / "entities.jsonl"
            stale_entities.write_text('{"stale": true}\n', encoding="utf-8")

            with patch("source.kg.build.relink._write_jsonl", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    relink_snapshot_dirs([snapshot], fleet)

            self.assertTrue(stale_entities.exists())

    def test_resolve_snapshot_dirs_expands_fleet_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            fleet = root / "links"
            snapshot.mkdir()
            fleet.mkdir()
            combined = root / "combined"
            combined.mkdir()
            private_combined = root / "private-combined"
            private_combined.mkdir()
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
            (combined / "manifest.json").write_text(
                json.dumps({"build_type": "multi_repo"}) + "\n",
                encoding="utf-8",
            )
            (private_combined / "manifest.json").write_text(
                json.dumps({"build_type": "private_goldset_multi_repo"}) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(resolve_snapshot_dirs((root,)), (snapshot.resolve(),))
            self.assertEqual(default_output_dir((root,)), root.resolve() / "_fleet")

    def test_resolve_snapshot_dirs_excludes_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            fleet = root / "_fleet"
            snapshot.mkdir()
            fleet.mkdir()
            (snapshot / "manifest.json").write_text(
                json.dumps({"repo_path": str(snapshot), "commit_sha": "working-tree"}) + "\n",
                encoding="utf-8",
            )
            (fleet / "manifest.json").write_text("{not-json}\n", encoding="utf-8")

            self.assertEqual(resolve_snapshot_dirs((root,), exclude_dirs=(fleet,)), (snapshot.resolve(),))

    def test_resolve_snapshot_dirs_rejects_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot_arg = root / "not-a-dir"
            snapshot_arg.write_text("not a snapshot directory\n", encoding="utf-8")

            with self.assertRaisesRegex(NotADirectoryError, "Snapshot path must be a directory"):
                resolve_snapshot_dirs((snapshot_arg,))

    def test_resolve_snapshot_dirs_rejects_malformed_child_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            snapshot.mkdir()
            (snapshot / "manifest.json").write_text("{not-json}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                resolve_snapshot_dirs((root,))

    def test_resolve_snapshot_dirs_rejects_non_string_build_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            snapshot.mkdir()
            (snapshot / "manifest.json").write_text(
                json.dumps({"build_type": ["multi_repo"], "repo_path": str(snapshot), "commit_sha": "working-tree"})
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "manifest is not a valid repo snapshot"):
                resolve_snapshot_dirs((snapshot,))

    def test_resolve_snapshot_dirs_rejects_malformed_direct_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            snapshot.mkdir()
            (snapshot / "manifest.json").write_text("{not-json}\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                resolve_snapshot_dirs((snapshot,))

    def test_resolve_snapshot_dirs_rejects_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "repo-a"
            (snapshot / "manifest.json").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "must be a JSON file"):
                resolve_snapshot_dirs((snapshot,))

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
            build_kg(repo, snapshot, tenant_id="default")

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

    def test_relink_rejects_non_string_manifest_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tenant_id"] = 123
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "tenant_id must be a non-empty string"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_non_string_manifest_repo_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["owner"] = ["owner-a"]
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "owner must be a non-empty string"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_entity_tenant_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import requests\n")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot, tenant_id="default")
            rows = read_jsonl(snapshot / "entities.jsonl")
            for index, row in enumerate(rows):
                if row.get("kind") == "ExternalPackage":
                    identity = dict(row["identity"])
                    identity["tenant_id"] = "other-tenant"
                    rows[index] = Entity(
                        kind="ExternalPackage",
                        identity=identity,
                        properties=row["properties"],
                    ).to_record()
                    break
            _write_jsonl_records(snapshot / "entities.jsonl", rows)

            with self.assertRaisesRegex(ValueError, "entity tenant_id values do not match"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_padded_entity_tenant_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import requests\n")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot, tenant_id="default")
            rows = read_jsonl(snapshot / "entities.jsonl")
            for index, row in enumerate(rows):
                if row.get("kind") == "ExternalPackage":
                    identity = dict(row["identity"])
                    identity["tenant_id"] = " default "
                    rows[index] = Entity(
                        kind="ExternalPackage",
                        identity=identity,
                        properties=row["properties"],
                    ).to_record()
                    break
            _write_jsonl_records(snapshot / "entities.jsonl", rows)

            with self.assertRaisesRegex(ValueError, "entity tenant_id values do not match"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_infers_missing_manifest_tenant_from_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot, tenant_id="snapshot-tenant")
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("tenant_id", None)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with patch.dict(os.environ, {"SUPERCONTEXT_TENANT_ID": "ambient-tenant"}):
                relink_manifest = relink_snapshot_dirs([snapshot], root / "_fleet")

            self.assertEqual(relink_manifest["tenant_id"], "snapshot-tenant")

    def test_relink_rejects_manifest_repo_identity_without_matching_entity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["owner"] = "wrong-owner"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not match a Repo entity"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_does_not_link_stdlib_imports_to_same_named_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import json\n")
            provider = _python_repo(root / "owner-b" / "json", "json", "")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")

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
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(fleet / "cross_repo_links.jsonl"), [])

    def test_relink_uses_setup_cfg_python_package_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import shared_pkg\n")
            provider = root / "owner-b" / "provider"
            provider.mkdir(parents=True)
            (provider / "setup.cfg").write_text("[metadata]\nname = shared-pkg\n", encoding="utf-8")
            (provider / "module.py").write_text("", encoding="utf-8")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            facts = read_jsonl(fleet / "cross_repo_links.jsonl")
            self.assertEqual(manifest["link_count"], 2)
            self.assertEqual({row["predicate"] for row in facts}, {"RESOLVES_TO_REPO", "RESOLVES_TO_SERVICE"})

    def test_relink_uses_setup_cfg_when_pyproject_has_no_package_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import shared_pkg\n")
            provider = root / "owner-b" / "provider"
            provider.mkdir(parents=True)
            (provider / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
            (provider / "setup.cfg").write_text("[metadata]\nname = shared-pkg\n", encoding="utf-8")
            (provider / "module.py").write_text("", encoding="utf-8")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            self.assertEqual(manifest["link_count"], 2)

    def test_relink_uses_python_resolver_alias_when_distribution_name_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import sklearn\n")
            provider = _python_repo(root / "owner-b" / "provider", "scikit-learn", "")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            fleet = root / "snapshots" / "_fleet"
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")
            rows = read_jsonl(consumer_snapshot / "entities.jsonl")
            for index, row in enumerate(rows):
                if row.get("kind") == "ExternalPackage":
                    identity = dict(row["identity"])
                    identity["name"] = "sklearn"
                    properties = dict(row["properties"])
                    properties["import_root"] = "sklearn"
                    properties["distribution_name"] = None
                    rows[index] = Entity("ExternalPackage", identity, properties).to_record()
                    break
            _write_jsonl_records(consumer_snapshot / "entities.jsonl", rows)

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], fleet)

            self.assertGreaterEqual(manifest["link_count"], 1)
            facts = read_jsonl(fleet / "cross_repo_links.jsonl")
            self.assertIn("RESOLVES_TO_REPO", {row["predicate"] for row in facts})

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

    def test_git_commit_sha_reports_missing_git(self) -> None:
        with patch("source.kg.build.relink.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "git is required"):
                relink_module._git_commit_sha(Path("/tmp/repo"))

    def test_git_commit_sha_reports_non_git_working_copy(self) -> None:
        error = subprocess.CalledProcessError(128, ["git", "rev-parse", "HEAD"])
        with patch("source.kg.build.relink.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(ValueError, "not a git working copy"):
                relink_module._git_commit_sha(Path("/tmp/repo"))

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

    def test_relink_rejects_existing_relink_artifact_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            fleet = root / "_fleet"
            build_kg(repo, snapshot)
            (fleet / "manifest.json").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "not a file"):
                relink_snapshot_dirs([snapshot], fleet)

    def test_relink_cli_reports_missing_out_as_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            stderr = io.StringIO()

            with patch.object(sys, "argv", ["bettercontext-relink", "--snapshot-dir", str(snapshot)]):
                with patch("sys.stderr", stderr):
                    with self.assertRaises(SystemExit) as raised:
                        relink_cli.main()

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--out is required", stderr.getvalue())

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

    def test_relink_rejects_entity_rows_missing_entity_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            rows = read_jsonl(snapshot / "entities.jsonl")
            rows[0].pop("entity_id")
            with (snapshot / "entities.jsonl").open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")

            with self.assertRaisesRegex(ValueError, "entity_id must be a non-empty string"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_non_string_entity_canonical_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            rows = read_jsonl(snapshot / "entities.jsonl")
            rows[0]["canonical_status"] = []
            _write_jsonl_records(snapshot / "entities.jsonl", rows)

            with self.assertRaisesRegex(ValueError, "canonical_status is unsupported"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_non_string_external_package_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import requests\n")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            rows = read_jsonl(snapshot / "entities.jsonl")
            for row in rows:
                if row.get("kind") == "ExternalPackage":
                    row["properties"]["category"] = []
                    break
            _write_jsonl_records(snapshot / "entities.jsonl", rows)

            with self.assertRaisesRegex(ValueError, "ExternalPackage category must be a string"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_duplicate_entity_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            rows = read_jsonl(snapshot / "entities.jsonl")
            rows.append(dict(rows[0]))
            _write_jsonl_records(snapshot / "entities.jsonl", rows)

            with self.assertRaisesRegex(ValueError, "duplicate entity_id"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_entities_jsonl_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (snapshot / "entities.jsonl").unlink()
            (snapshot / "entities.jsonl").mkdir()

            with self.assertRaisesRegex(ValueError, "entities.jsonl must be a JSONL file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_skips_collapsed_packages_when_any_source_is_builtin(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stdlib_consumer = _python_repo(root / "owner-a" / "app", "stdlib-consumer", "import json\n")
            third_party_consumer = _python_repo(
                root / "owner-b" / "app",
                "third-party-consumer",
                "import json\n",
            )
            provider = _python_repo(root / "owner-c" / "json", "json", "")
            stdlib_snapshot = root / "snapshots" / "stdlib"
            third_party_snapshot = root / "snapshots" / "third-party"
            provider_snapshot = root / "snapshots" / "provider"
            build_kg(stdlib_consumer, stdlib_snapshot)
            build_kg(third_party_consumer, third_party_snapshot)
            build_kg(provider, provider_snapshot)
            rows = read_jsonl(third_party_snapshot / "entities.jsonl")
            for row in rows:
                if row.get("kind") == "ExternalPackage" and row.get("identity", {}).get("name") == "json":
                    row["properties"]["category"] = "third_party"
                    row["properties"]["distribution_name"] = "json"
            _write_jsonl_records(third_party_snapshot / "entities.jsonl", rows)

            manifest = relink_snapshot_dirs([stdlib_snapshot, third_party_snapshot, provider_snapshot], root / "_fleet")

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(root / "_fleet" / "cross_repo_links.jsonl"), [])

    def test_relink_fails_closed_when_collapsed_package_has_partial_self_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider = _python_repo(root / "owner-a" / "app", "shared", "")
            consumer = _python_repo(root / "owner-b" / "app", "consumer-package", "import shared\n")
            provider_snapshot = root / "snapshots" / "provider"
            consumer_snapshot = root / "snapshots" / "consumer"
            build_kg(provider, provider_snapshot)
            build_kg(consumer, consumer_snapshot)
            consumer_rows = read_jsonl(consumer_snapshot / "entities.jsonl")
            provider_rows = read_jsonl(provider_snapshot / "entities.jsonl")
            shared_package = next(
                row
                for row in consumer_rows
                if row.get("kind") == "ExternalPackage" and row.get("identity", {}).get("name") == "shared"
            )
            provider_rows.append(dict(shared_package))
            _write_jsonl_records(provider_snapshot / "entities.jsonl", provider_rows)

            manifest = relink_snapshot_dirs([provider_snapshot, consumer_snapshot], root / "_fleet")

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(root / "_fleet" / "cross_repo_links.jsonl"), [])

    def test_relink_fails_closed_on_divergent_collapsed_package_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            provider_a = _python_repo(root / "owner-a" / "app", "shared", "")
            provider_b = _python_repo(root / "owner-b" / "app", "shared", "")
            snapshot_a = root / "snapshots" / "a"
            snapshot_b = root / "snapshots" / "b"
            build_kg(provider_a, snapshot_a, tenant_id="default")
            build_kg(provider_b, snapshot_b, tenant_id="default")
            shared_external = Entity(
                kind="ExternalPackage",
                identity={"tenant_id": "default", "repo": "app", "name": "shared"},
                properties={"category": "third_party", "import_root": "shared", "distribution_name": "shared"},
            ).to_record()
            for snapshot in (snapshot_a, snapshot_b):
                rows = read_jsonl(snapshot / "entities.jsonl")
                rows.append(dict(shared_external))
                _write_jsonl_records(snapshot / "entities.jsonl", rows)

            manifest = relink_snapshot_dirs([snapshot_a, snapshot_b], root / "_fleet")

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(manifest["ambiguous_package_count"], 1)
            self.assertEqual(read_jsonl(root / "_fleet" / "cross_repo_links.jsonl"), [])

    def test_relink_accepts_non_object_package_json_as_repo_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text("[]\n", encoding="utf-8")

            package_name, aliases, manifest_path = relink_module._package_metadata(
                _repo_snapshot(repo),
                validate_snapshot_manifest=False,
            )

            self.assertEqual(package_name, "consumer")
            self.assertEqual(aliases, {"consumer"})
            self.assertEqual(manifest_path, repo / "package.json")

    def test_relink_accepts_non_string_package_json_name_as_repo_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": ["consumer"]}\n', encoding="utf-8")

            package_name, aliases, manifest_path = relink_module._package_metadata(
                _repo_snapshot(repo),
                validate_snapshot_manifest=False,
            )

            self.assertEqual(package_name, "consumer")
            self.assertEqual(aliases, {"consumer"})
            self.assertEqual(manifest_path, repo / "package.json")

    def test_relink_accepts_malformed_pyproject_tables_as_repo_name_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            (repo / "pyproject.toml").write_text('[tool]\npoetry = "not-a-table"\n', encoding="utf-8")

            package_name, aliases, manifest_path = relink_module._package_metadata(
                _repo_snapshot(repo),
                validate_snapshot_manifest=False,
            )

            self.assertEqual(package_name, "consumer")
            self.assertEqual(aliases, {"consumer"})
            self.assertEqual(manifest_path, repo / "pyproject.toml")

    def test_relink_rejects_pyproject_directory_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").unlink()
            (repo / "pyproject.toml").mkdir()

            with self.assertRaisesRegex(ValueError, "not a file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_package_json_directory_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "package.json").mkdir()

            with self.assertRaisesRegex(ValueError, "not a file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_ignores_non_string_poetry_include_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            provider = _python_repo(root / "owner-b" / "provider", "provider-package", "")
            # Intentional malformed Poetry config: include must be a string package root.
            (provider / "pyproject.toml").write_text(
                '[project]\nname = "provider-package"\n[tool.poetry]\npackages = [{ include = true }]\n',
                encoding="utf-8",
            )
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            build_kg(consumer, consumer_snapshot, tenant_id="default")
            build_kg(provider, provider_snapshot, tenant_id="default")
            consumer_rows = read_jsonl(consumer_snapshot / "entities.jsonl")
            consumer_rows.append(
                Entity(
                    kind="ExternalPackage",
                    # Keep literal "true": prior buggy alias logic coerced include=true to "True"
                    # and could incorrectly resolve this package name. Non-string include
                    # values are now ignored, so this package should remain unresolved.
                    identity={"tenant_id": "default", "repo": "consumer-package", "name": "true"},
                    properties={"category": "third_party", "import_root": "true", "distribution_name": "true"},
                ).to_record()
            )
            _write_jsonl_records(consumer_snapshot / "entities.jsonl", consumer_rows)

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], root / "_fleet")

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(root / "_fleet" / "cross_repo_links.jsonl"), [])

    def test_relink_does_not_treat_scoped_npm_name_as_unscoped_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer-package", "import shared\n")
            provider = root / "owner-b" / "provider"
            provider.mkdir(parents=True)
            (provider / "package.json").write_text('{"name": "@scope/shared"}\n', encoding="utf-8")
            consumer_snapshot = root / "snapshots" / "consumer"
            provider_snapshot = root / "snapshots" / "provider"
            build_kg(consumer, consumer_snapshot)
            build_kg(provider, provider_snapshot)

            manifest = relink_snapshot_dirs([consumer_snapshot, provider_snapshot], root / "_fleet")

            self.assertEqual(manifest["link_count"], 0)
            self.assertEqual(read_jsonl(root / "_fleet" / "cross_repo_links.jsonl"), [])

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

            with self.assertRaisesRegex(ValueError, "Package manifest recorded in snapshot is not a file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_package_manifest_restored_after_dirty_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "consumer", "consumer-package", "")
            clean_pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "initial")
            (repo / "pyproject.toml").write_text('[project]\nname = "dirty-package"\n', encoding="utf-8")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").write_text(clean_pyproject, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Package manifest content differs"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_ignored_package_manifest_added_after_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / ".gitignore").write_text("pyproject.toml\n", encoding="utf-8")
            (repo / "module.py").write_text("", encoding="utf-8")
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "initial")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").write_text('[project]\nname = "ignored-provider"\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Package manifest has uncommitted changes"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_package_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "module.py").write_text("", encoding="utf-8")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "pyproject.toml").mkdir()

            with self.assertRaisesRegex(ValueError, "Package manifest path is not a file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_setup_cfg_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "module.py").write_text("", encoding="utf-8")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "setup.cfg").mkdir()

            with self.assertRaisesRegex(ValueError, "Package manifest path is not a file"):
                relink_snapshot_dirs([snapshot], root / "_fleet")

    def test_relink_rejects_deleted_setup_cfg_before_package_json_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "owner-a" / "consumer"
            repo.mkdir(parents=True)
            (repo / "setup.cfg").write_text("[metadata]\nname = setup-provider\n", encoding="utf-8")
            (repo / "module.py").write_text("", encoding="utf-8")
            _git(repo, "init")
            _git(repo, "config", "user.email", "test@example.com")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "initial")
            snapshot = root / "snapshots" / "consumer"
            build_kg(repo, snapshot)
            (repo / "setup.cfg").unlink()

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


def _write_jsonl_records(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _python_repo(path: Path, package_name: str, source: str) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{package_name}"\n', encoding="utf-8")
    if source:
        (path / "module.py").write_text(source, encoding="utf-8")
    package_dir = path / package_name.replace("-", "_")
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    return path


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
