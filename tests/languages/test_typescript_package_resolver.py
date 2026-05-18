from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.package_resolver import TypeScriptPackageResolver


class TypeScriptPackageResolverTest(unittest.TestCase):
    def test_package_json_metadata_uses_declared_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "shared-pkg"}\n', encoding="utf-8")

            metadata = TypeScriptPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "shared-pkg")
            self.assertEqual(metadata.manifest_path, repo / "package.json")
            self.assertEqual(metadata.aliases, frozenset({"shared-pkg", "repo"}))

    def test_package_json_malformed_name_falls_back_to_repo_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": ["shared-pkg"]}\n', encoding="utf-8")

            metadata = TypeScriptPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "repo")

    def test_package_json_invalid_json_falls_back_to_repo_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text("{not-json}\n", encoding="utf-8")

            metadata = TypeScriptPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "repo")

    def test_package_json_blank_name_falls_back_to_repo_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "   "}\n', encoding="utf-8")

            metadata = TypeScriptPackageResolver().package_metadata(_repo_snapshot(repo))

            self.assertEqual(metadata.package_name, "repo")

    def test_package_metadata_rejects_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").mkdir()

            with self.assertRaisesRegex(ValueError, "Package manifest path is not a file"):
                TypeScriptPackageResolver().package_metadata(_repo_snapshot(repo))

    def test_resolve_matches_scoped_package_name_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "@scope/shared"}\n', encoding="utf-8")

            resolved = TypeScriptPackageResolver().resolve("@scope/shared", [_repo_snapshot(repo)])

            self.assertEqual(resolved, "@scope/shared")

    def test_resolve_does_not_treat_scoped_name_as_unscoped_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "provider"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "@scope/shared"}\n', encoding="utf-8")

            resolved = TypeScriptPackageResolver().resolve("shared", [_repo_snapshot(repo)])

            self.assertIsNone(resolved)

    def test_resolve_fails_closed_on_ambiguous_provider_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "owner-a" / "provider-a"
            second = Path(tmpdir) / "owner-b" / "provider-b"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "package.json").write_text('{"name": "shared-pkg"}\n', encoding="utf-8")
            (second / "package.json").write_text('{"name": "shared-pkg"}\n', encoding="utf-8")

            resolved = TypeScriptPackageResolver().resolve("shared-pkg", [_repo_snapshot(first), _repo_snapshot(second)])

            self.assertIsNone(resolved)

    def test_repo_snapshot_is_usable_as_resolver_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "repo"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text('{"name": "shared-pkg"}\n', encoding="utf-8")
            snapshot = _repo_snapshot(repo)
            resolver = TypeScriptPackageResolver()

            first = resolver.package_metadata(snapshot)
            second = resolver.package_metadata(snapshot)

            self.assertIs(first, second)


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


if __name__ == "__main__":
    unittest.main()
