from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.build.multi_repo import build_multi_kg
from source.kg.build.pipeline import RepoKgBuild
from source.kg.core.store import read_jsonl


class MultiRepoIdentityTest(unittest.TestCase):
    def test_same_named_repos_under_different_owners_link_by_full_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "svc", "consumer-package", "import shared_provider\n")
            provider = _python_repo(root / "owner-b" / "svc", "shared_provider", "")
            out = root / "kg"

            manifest = build_multi_kg([consumer, provider], out)

            self.assertEqual(manifest["repo_count"], 2)
            self.assertEqual(manifest["counts"]["files_by_language"]["python"], 3)
            repo_entities = [row for row in read_jsonl(out / "entities.jsonl") if row["kind"] == "Repo"]
            svc_repos = [row for row in repo_entities if row["identity"]["name"] == "svc"]
            self.assertEqual({row["identity"]["owner"] for row in svc_repos}, {"owner-a", "owner-b"})

            entities_by_id = {row["entity_id"]: row for row in read_jsonl(out / "entities.jsonl")}
            resolve_facts = [
                row for row in read_jsonl(out / "facts.jsonl") if row["predicate"] == "RESOLVES_TO_REPO"
            ]
            self.assertEqual(len(resolve_facts), 1)
            target = entities_by_id[resolve_facts[0]["object_id"]]
            self.assertEqual(target["identity"]["owner"], "owner-b")
            self.assertEqual(resolve_facts[0]["qualifier"]["consumer_repo_identity"]["tenant_id"], "default")
            self.assertEqual(resolve_facts[0]["qualifier"]["consumer_repo_identity"]["owner"], "owner-a")
            self.assertEqual(resolve_facts[0]["qualifier"]["provider_repo_identity"]["tenant_id"], "default")
            self.assertEqual(resolve_facts[0]["qualifier"]["provider_repo_identity"]["owner"], "owner-b")
            evidence_rows = [
                row
                for row in read_jsonl(out / "evidence.jsonl")
                if row["target_id"] == resolve_facts[0]["fact_id"]
            ]
            self.assertEqual(len(evidence_rows), 1)
            self.assertEqual(evidence_rows[0]["bytes_ref"]["repo"], "default/local/owner-b/svc")
            self.assertEqual(evidence_rows[0]["bytes_ref"]["repo_name"], "svc")
            self.assertEqual(evidence_rows[0]["bytes_ref"]["repo_identity"]["owner"], "owner-b")
            extractor_evidence = [
                row
                for row in read_jsonl(out / "evidence.jsonl")
                if row["source_system"] == "python_ast_v0" and row["bytes_ref"] is not None
            ]
            self.assertTrue(extractor_evidence)
            self.assertEqual(
                {row["bytes_ref"]["repo"] for row in extractor_evidence},
                {"default/local/owner-a/svc", "default/local/owner-b/svc"},
            )

    def test_collapsed_external_package_records_plural_consumer_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer_a = _python_repo(root / "owner-a" / "svc", "consumer-a", "import common_lib\n")
            consumer_b = _python_repo(root / "owner-b" / "svc", "consumer-b", "import common_lib\n")
            provider = _python_repo(root / "owner-c" / "common_lib", "common_lib", "")
            out = root / "kg"

            build_multi_kg([consumer_a, consumer_b, provider], out)

            resolve_facts = [
                row for row in read_jsonl(out / "facts.jsonl") if row["predicate"] == "RESOLVES_TO_REPO"
            ]
            self.assertEqual(len(resolve_facts), 2)
            identities = [row["qualifier"]["consumer_repo_identity"] for row in resolve_facts]
            self.assertEqual(
                {(row["tenant_id"], row["host"], row["owner"], row["name"]) for row in identities},
                {("default", "local", "owner-a", "svc"), ("default", "local", "owner-b", "svc")},
            )

    def test_ambiguous_package_providers_do_not_emit_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = _python_repo(root / "owner-a" / "consumer", "consumer", "import shared_provider\n")
            provider_a = _python_repo(root / "owner-b" / "provider-a", "shared_provider", "")
            provider_b = _python_repo(root / "owner-c" / "provider-b", "shared_provider", "")
            out = root / "kg"

            manifest = build_multi_kg([consumer, provider_a, provider_b], out)

            self.assertEqual(manifest["linker"]["ambiguous_package_count"], 1)
            resolve_facts = [
                row for row in read_jsonl(out / "facts.jsonl") if row["predicate"] == "RESOLVES_TO_REPO"
            ]
            self.assertEqual(resolve_facts, [])

    def test_duplicate_full_repo_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _python_repo(root / "owner-a" / "svc", "consumer-package", "")

            with self.assertRaisesRegex(ValueError, "unique repo identities"):
                build_multi_kg([repo, repo], root / "kg")

    def test_strict_extractor_errors_use_unique_repo_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_a = _python_repo(root / "owner-a" / "svc", "consumer-a", "")
            repo_b = _python_repo(root / "owner-b" / "svc", "consumer-b", "")

            def fail_build(*args, **kwargs) -> RepoKgBuild:
                return RepoKgBuild(
                    entities=[],
                    facts=[],
                    evidence=[],
                    coverage=[],
                    extractor_names=["broken_extractor"],
                    extractor_errors=[
                        {
                            "source_system": "broken_extractor",
                            "error": "RuntimeError",
                            "message": "boom",
                        }
                    ],
                )

            with patch("source.kg.build.multi_repo.extract_repo", side_effect=fail_build):
                with self.assertRaises(RuntimeError) as raised:
                    build_multi_kg([repo_a, repo_b], root / "kg", strict_extractors=True)

            message = str(raised.exception)
            self.assertIn("default/local/owner-a/svc:broken_extractor", message)
            self.assertIn("default/local/owner-b/svc:broken_extractor", message)


def _python_repo(path: Path, package_name: str, source: str) -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{package_name}"\n', encoding="utf-8")
    if source:
        (path / "module.py").write_text(source, encoding="utf-8")
    package_dir = path / package_name.replace("-", "_")
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
