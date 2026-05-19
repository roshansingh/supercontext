from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from source.kg.build.repo_identity import normalize_git_url, resolve_file_path
from source.kg.build import relink as relink_module
from source.kg.build.relink import LinkerInput, PackageProvider, RepoIdentity, link_external_packages
from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.types import ConsumerDependency


class RepoIdentityLinkageTest(unittest.TestCase):
    def test_normalize_git_url_handles_common_forge_forms(self) -> None:
        cases = {
            "https://github.com/acme/shared.git": ("github.com", "acme", "shared"),
            "git@github.com:acme/shared.git": ("github.com", "acme", "shared"),
            "git+ssh://git@gitlab.com/acme/platform/shared.git": ("gitlab.com", "acme/platform", "shared"),
            "github:acme/shared#main": ("github.com", "acme", "shared"),
        }

        for raw_url, expected in cases.items():
            with self.subTest(raw_url=raw_url):
                identity = normalize_git_url(raw_url)
                self.assertIsNotNone(identity)
                assert identity is not None
                self.assertEqual((identity.host, identity.owner, identity.name), expected)

    def test_resolve_file_path_matches_only_scanned_fleet_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "org" / "consumer"
            provider = root / "org" / "provider"
            outside = root / "outside"
            consumer.mkdir(parents=True)
            provider.mkdir(parents=True)
            outside.mkdir()
            manifest = consumer / "package.json"
            manifest.write_text("{}", encoding="utf-8")

            resolved = resolve_file_path("../provider", manifest, (_repo_snapshot(consumer), _repo_snapshot(provider)))
            missed = resolve_file_path("../outside", manifest, (_repo_snapshot(consumer), _repo_snapshot(provider)))

        self.assertEqual(resolved.root, provider)
        self.assertIsNone(missed)

    def test_file_path_dependency_links_to_scanned_repo_without_package_name_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "org" / "consumer"
            provider = root / "org" / "provider"
            consumer.mkdir(parents=True)
            provider.mkdir(parents=True)
            (consumer / "package.json").write_text(
                json.dumps({"dependencies": {"declared-shared": "file:../provider"}}),
                encoding="utf-8",
            )
            (provider / "package.json").write_text(json.dumps({"name": "provider-runtime-name"}), encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(
                        repo=_repo_snapshot(consumer),
                        repo_identity=_repo_identity(consumer),
                        entities=(
                            _repo_entity(consumer),
                            Entity(
                                kind="ExternalPackage",
                                identity={"tenant_id": "default", "repo": "consumer", "name": "declared-shared"},
                                properties={"category": "third_party", "import_root": "declared-shared"},
                            ),
                        ),
                    ),
                    LinkerInput(
                        repo=_repo_snapshot(provider),
                        repo_identity=_repo_identity(provider),
                        entities=(_repo_entity(provider), _service_entity(provider)),
                    ),
                )
            )

        self.assertEqual(
            [(fact.predicate, fact.qualifier["rule"]) for fact in result.facts],
            [("RESOLVES_TO_REPO", "manifest_target_repo_match")],
        )
        self.assertEqual(result.facts[0].object_id, _repo_entity(provider).entity_id)
        self.assertEqual(result.evidence[0].bytes_ref["commit_sha"], "working-tree")
        self.assertEqual(result.evidence[0].bytes_ref["path"], "package.json")
        self.assertEqual(result.package_classifications[0]["bucket"], "candidate_internal")
        self.assertEqual(result.package_classifications[0]["reason"], "consumer manifest dependency target matches exactly one fleet repo")

    def test_git_url_dependency_links_to_scanned_repo_by_owner_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "acme" / "consumer"
            provider = root / "acme" / "provider"
            consumer.mkdir(parents=True)
            provider.mkdir(parents=True)
            (consumer / "package.json").write_text(
                json.dumps({"dependencies": {"declared-shared": "git+https://github.com/acme/provider.git"}}),
                encoding="utf-8",
            )
            (provider / "package.json").write_text(json.dumps({"name": "provider-runtime-name"}), encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(
                        repo=_repo_snapshot(consumer),
                        repo_identity=_repo_identity(consumer),
                        entities=(
                            _repo_entity(consumer),
                            Entity(
                                kind="ExternalPackage",
                                identity={"tenant_id": "default", "repo": "consumer", "name": "declared-shared"},
                                properties={"category": "third_party", "import_root": "declared-shared"},
                            ),
                        ),
                    ),
                    LinkerInput(
                        repo=_repo_snapshot(provider),
                        repo_identity=_repo_identity(provider),
                        entities=(_repo_entity(provider),),
                    ),
                )
            )

        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].qualifier["dependency_target_url"], "git+https://github.com/acme/provider.git")

    def test_manifest_target_match_fails_closed_when_target_repo_has_multiple_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "org" / "consumer"
            provider = root / "org" / "provider"
            consumer.mkdir(parents=True)
            provider.mkdir(parents=True)
            manifest_path = consumer / "package.json"
            manifest_path.write_text("{}", encoding="utf-8")
            target_identity = _repo_identity(provider)
            providers = [
                _package_provider(provider, target_identity, "first"),
                _package_provider(provider, target_identity, "second"),
            ]

            dependency, provider_match = relink_module._manifest_target_provider_match(
                {"shared"},
                (
                    ConsumerDependency(
                        declared_name="shared",
                        declared_version="file:../provider",
                        dependency_kind="dependencies",
                        manifest_path=manifest_path,
                        line_number=None,
                        spec_form="file_path",
                        target_url="../provider",
                    ),
                ),
                _repo_identity(consumer),
                (
                    LinkerInput(_repo_snapshot(consumer), _repo_identity(consumer), (_repo_entity(consumer),)),
                    LinkerInput(_repo_snapshot(provider), target_identity, (_repo_entity(provider),)),
                ),
                relink_module._providers_by_identity(providers),
            )

        self.assertIsNone(dependency)
        self.assertIsNone(provider_match)

    def test_multi_consumer_manifest_target_keeps_manifest_rule_and_consumer_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer_a = root / "owner-a" / "app"
            consumer_b = root / "owner-b" / "app"
            provider = root / "shared-org" / "provider"
            for path in (consumer_a, consumer_b, provider):
                path.mkdir(parents=True)
            for consumer in (consumer_a, consumer_b):
                (consumer / "package.json").write_text(
                    json.dumps({"dependencies": {"shared": f"file:{_relative_path(consumer, provider)}"}}),
                    encoding="utf-8",
                )
            (provider / "package.json").write_text(json.dumps({"name": "provider-runtime-name"}), encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(_repo_snapshot(consumer_a), _repo_identity(consumer_a), (_repo_entity(consumer_a), _external_package("app", "shared"))),
                    LinkerInput(_repo_snapshot(consumer_b), _repo_identity(consumer_b), (_repo_entity(consumer_b), _external_package("app", "shared"))),
                    LinkerInput(_repo_snapshot(provider), _repo_identity(provider), (_repo_entity(provider),)),
                )
            )

        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].qualifier["rule"], "manifest_target_repo_match")
        self.assertEqual(result.facts[0].qualifier["dependency_count"], 2)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual({row.source_ref["consumer_repo_identity"]["owner"] for row in result.evidence}, {"owner-a", "owner-b"})

    def test_partial_manifest_target_multi_consumer_does_not_leak_dependency_qualifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer_a = root / "owner-a" / "app"
            consumer_b = root / "owner-b" / "app"
            provider = root / "shared-org" / "provider"
            for path in (consumer_a, consumer_b, provider):
                path.mkdir(parents=True)
            (consumer_a / "package.json").write_text(
                json.dumps({"dependencies": {"shared": f"file:{_relative_path(consumer_a, provider)}"}}),
                encoding="utf-8",
            )
            (provider / "package.json").write_text(json.dumps({"name": "shared"}), encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(_repo_snapshot(consumer_a), _repo_identity(consumer_a), (_repo_entity(consumer_a), _external_package("app", "shared"))),
                    LinkerInput(_repo_snapshot(consumer_b), _repo_identity(consumer_b), (_repo_entity(consumer_b), _external_package("app", "shared"))),
                    LinkerInput(_repo_snapshot(provider), _repo_identity(provider), (_repo_entity(provider),)),
                )
            )

        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].qualifier["rule"], "unique_normalized_package_name_match")
        self.assertNotIn("dependency_target_url", result.facts[0].qualifier)


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


def _repo_identity(path: Path) -> RepoIdentity:
    return RepoIdentity("default", "local", path.parent.name, path.name)


def _repo_entity(path: Path) -> Entity:
    return Entity(
        kind="Repo",
        identity={"tenant_id": "default", "host": "local", "owner": path.parent.name, "name": path.name},
    )


def _service_entity(path: Path) -> Entity:
    return Entity(
        kind="Service",
        identity={"tenant_id": "default", "namespace": path.parent.name, "repo": path.name, "slug": path.name},
    )


def _external_package(repo: str, name: str) -> Entity:
    return Entity(
        kind="ExternalPackage",
        identity={"tenant_id": "default", "repo": repo, "name": name},
        properties={"category": "third_party", "import_root": name},
    )


def _package_provider(path: Path, identity: RepoIdentity, package_name: str) -> PackageProvider:
    return PackageProvider(
        repo=_repo_snapshot(path),
        repo_identity=identity,
        package_name=package_name,
        aliases=(package_name,),
        manifest_path=path / "package.json",
        resolver_language="typescript",
        repo_entity_id=_repo_entity(path).entity_id,
        service_entity_id=None,
    )


def _relative_path(source: Path, target: Path) -> str:
    return str(Path("..") / ".." / target.parent.name / target.name)


if __name__ == "__main__":
    unittest.main()
