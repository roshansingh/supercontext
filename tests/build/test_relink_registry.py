from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from source.kg.build import relink as relink_module
from source.kg.build.relink import LinkerInput, RepoIdentity, link_external_packages
from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot


class RelinkRegistryTest(unittest.TestCase):
    def test_package_metadata_preserves_existing_language_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "mixed"
            repo.mkdir(parents=True)
            (repo / "pyproject.toml").write_text('[project]\nname = "python-package"\n', encoding="utf-8")
            (repo / "package.json").write_text(json.dumps({"name": "typescript-package"}), encoding="utf-8")
            (repo / "Mixed.csproj").write_text(
                "<Project><PropertyGroup><PackageId>Dotnet.Package</PackageId></PropertyGroup></Project>\n",
                encoding="utf-8",
            )

            package_name, aliases, manifest_path = relink_module._package_metadata(
                _repo_snapshot(repo),
                validate_snapshot_manifest=False,
            )

        self.assertEqual(package_name, "python-package")
        self.assertIs(type(aliases), set)
        self.assertIn("python-package", aliases)
        self.assertEqual(manifest_path, repo / "pyproject.toml")

    def test_registered_extra_resolver_is_used_by_linker_without_relink_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer_repo = root / "owner-a" / "consumer"
            provider_repo = root / "owner-b" / "provider"
            consumer_repo.mkdir(parents=True)
            provider_repo.mkdir(parents=True)
            (provider_repo / "custom.pkg").write_text("shared-distribution\n", encoding="utf-8")

            with patch.object(relink_module, "REGISTERED_LANGUAGES", (_StubLanguageSupport(),)):
                result = link_external_packages(
                    [
                        LinkerInput(
                            repo=_repo_snapshot(consumer_repo),
                            repo_identity=_repo_identity(consumer_repo),
                            entities=(
                                _repo_entity(consumer_repo),
                                Entity(
                                    kind="ExternalPackage",
                                    identity={"tenant_id": "default", "repo": "consumer", "name": "shared_import"},
                                    properties={"category": "third_party", "import_root": "shared_import"},
                                ),
                            ),
                        ),
                        LinkerInput(
                            repo=_repo_snapshot(provider_repo),
                            repo_identity=_repo_identity(provider_repo),
                            entities=(_repo_entity(provider_repo),),
                        ),
                    ]
                )

        self.assertEqual({fact.predicate for fact in result.facts}, {"RESOLVES_TO_REPO"})

    def test_relink_collects_consumer_manifest_results_from_registered_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "owner" / "consumer"
            repo.mkdir(parents=True)
            (repo / "package.json").write_text(
                json.dumps({"dependencies": {"@acme/shared": "workspace:*"}}),
                encoding="utf-8",
            )

            result = link_external_packages(
                (
                    LinkerInput(
                        repo=_repo_snapshot(repo),
                        repo_identity=_repo_identity(repo),
                        entities=(_repo_entity(repo),),
                    ),
                )
            )

        self.assertEqual(result.consumer_manifest_issues, ())
        self.assertEqual(
            [(dependency.declared_name, dependency.spec_form) for dependency in result.consumer_dependencies],
            [("@acme/shared", "workspace")],
        )


@dataclass(frozen=True)
class _StubPackageMetadata:
    package_name: str
    aliases: frozenset[str]
    manifest_path: Path | None


class _StubPackageResolver:
    def manifest_paths(self, repo: RepoSnapshot) -> tuple[Path, ...]:
        path = repo.root / "custom.pkg"
        return (path,) if path.exists() else ()

    def package_metadata(self, repo: RepoSnapshot) -> _StubPackageMetadata:
        manifest_path = repo.root / "custom.pkg"
        return _StubPackageMetadata(
            package_name=manifest_path.read_text(encoding="utf-8").strip(),
            aliases=frozenset({"provider-only-alias"}),
            manifest_path=manifest_path,
        )

    def resolve(self, import_root: str, target_repos) -> str | None:
        matches = [
            self.package_metadata(repo).package_name
            for repo in target_repos
            if import_root == "shared_import" and (repo.root / "custom.pkg").exists()
        ]
        return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class _StubLanguageSupport:
    name: str = "custom"
    aliases: tuple[str, ...] = ()
    file_extensions: frozenset[str] = frozenset()
    manifest_files: frozenset[str] = frozenset({"custom.pkg"})

    def matches_file(self, path: Path) -> bool:
        return path.name == "custom.pkg"

    def source_roots(self, repo, ctx) -> dict[str, set[str]]:
        return {}

    def parse_repo(self, repo, ctx):
        return {}

    def opportunity_detectors(self) -> tuple:
        return ()

    def package_resolver(self) -> _StubPackageResolver:
        return _StubPackageResolver()

    def consumer_manifest_extractor(self):
        return None

    def dimension_rules(self):
        return {}

    def useful_edges(self):
        return {}

    def adapters(self) -> tuple:
        return ()

    def known_stacks(self) -> dict[str, dict[str, str]]:
        return {}


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


def _repo_identity(path: Path) -> RepoIdentity:
    return RepoIdentity("default", "local", path.parent.name, path.name)


def _repo_entity(path: Path) -> Entity:
    return Entity(
        kind="Repo",
        identity={"tenant_id": "default", "host": "local", "owner": path.parent.name, "name": path.name},
    )


if __name__ == "__main__":
    unittest.main()
