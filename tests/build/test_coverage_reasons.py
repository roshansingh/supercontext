from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from source.kg.build import relink as relink_module
from source.kg.build.relink import LinkerInput, RepoIdentity, link_external_packages
from source.kg.core.models import Coverage, Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.types import ConsumerManifestIssue
from source.kg.metrics.report import write_coverage_report


class PackageLinkageCoverageReasonTest(unittest.TestCase):
    def test_linker_emits_only_actionable_package_linkage_coverage_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "org" / "consumer"
            provider_a = root / "org" / "provider-a"
            provider_b = root / "org" / "provider-b"
            for path in (consumer, provider_a, provider_b):
                path.mkdir(parents=True)
            (consumer / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {
                            "ambiguous": "^1.0.0",
                            "local-missing": "file:../missing",
                            "react": "^18.2.0",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (provider_a / "package.json").write_text(json.dumps({"name": "ambiguous"}), encoding="utf-8")
            (provider_b / "package.json").write_text(json.dumps({"name": "ambiguous"}), encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(
                        repo=_repo_snapshot(consumer),
                        repo_identity=_repo_identity(consumer),
                        entities=(
                            _repo_entity(consumer),
                            _external_package("consumer", "ambiguous"),
                            _external_package("consumer", "local-missing"),
                            _external_package("consumer", "react"),
                            _external_package("consumer", "code-only"),
                            Entity(
                                kind="ExternalPackage",
                                identity={"tenant_id": "default", "repo": "consumer", "name": "requests"},
                                properties={
                                    "category": "third_party",
                                    "import_root": "requests",
                                    "distribution_name": "requests",
                                },
                            ),
                            Entity(
                                kind="ExternalPackage",
                                identity={"tenant_id": "default", "repo": "consumer", "name": "fs"},
                                properties={"category": "node_builtin", "import_root": "fs"},
                            ),
                        ),
                    ),
                    LinkerInput(
                        repo=_repo_snapshot(provider_a),
                        repo_identity=_repo_identity(provider_a),
                        entities=(_repo_entity(provider_a),),
                    ),
                    LinkerInput(
                        repo=_repo_snapshot(provider_b),
                        repo_identity=_repo_identity(provider_b),
                        entities=(_repo_entity(provider_b),),
                    ),
                )
            )

        reasons = {row.scope_ref["package_name"]: row.scope_ref["reason"] for row in result.coverage}
        self.assertEqual(reasons["ambiguous"], "cross_repo_dependency_ambiguous_provider")
        self.assertEqual(reasons["local-missing"], "cross_repo_dependency_no_provider")
        self.assertEqual(reasons["code-only"], "cross_repo_dependency_unknown_category")
        self.assertNotIn("react", reasons)
        self.assertNotIn("requests", reasons)
        self.assertNotIn("fs", reasons)
        local_missing = next(row for row in result.package_classifications if row["package_name"] == "local-missing")
        self.assertEqual(local_missing["spec_form"], "file_path")

    def test_linker_emits_manifest_unreadable_coverage_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            consumer = root / "org" / "consumer"
            consumer.mkdir(parents=True)
            (consumer / "package.json").write_text("{not-json}\n", encoding="utf-8")

            result = link_external_packages(
                (
                    LinkerInput(
                        repo=_repo_snapshot(consumer),
                        repo_identity=_repo_identity(consumer),
                        entities=(_repo_entity(consumer),),
                    ),
                )
            )

        self.assertEqual(len(result.coverage), 1)
        self.assertEqual(result.coverage[0].scope_ref["reason"], "cross_repo_dependency_manifest_unreadable")
        self.assertEqual(result.coverage[0].scope_ref["language"], "typescript")

    def test_manifest_unreadable_coverage_is_visible_when_issue_path_has_no_repo_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "org" / "consumer"
            repo.mkdir(parents=True)

            coverage = relink_module._package_linkage_coverage(
                (LinkerInput(_repo_snapshot(repo), _repo_identity(repo), (_repo_entity(repo),)),),
                (),
                (
                    ConsumerManifestIssue(
                        reason="cross_repo_dependency_manifest_unreadable",
                        manifest_path=root / "outside" / "package.json",
                        message="cannot read",
                        language="typescript",
                    ),
                ),
            )

        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0].scope_ref["repo"], "-")
        self.assertEqual(coverage[0].scope_ref["reason"], "cross_repo_dependency_manifest_unreadable")

    def test_coverage_dedupe_ignores_generated_checked_at(self) -> None:
        first = Coverage(
            tenant_id="default",
            predicate="RESOLVES_TO_REPO",
            scope_ref={"repo": "consumer", "reason": "cross_repo_dependency_unknown_category"},
            state="partially_instrumented",
            source_system="package_linker",
            checked_at="2026-05-19T00:00:00+00:00",
        )
        second = Coverage(
            tenant_id="default",
            predicate="RESOLVES_TO_REPO",
            scope_ref={"repo": "consumer", "reason": "cross_repo_dependency_unknown_category"},
            state="partially_instrumented",
            source_system="package_linker",
            checked_at="2026-05-19T00:00:01+00:00",
        )

        deduped = relink_module._dedupe_coverage([first, second])

        self.assertEqual(deduped, (second,))

    def test_report_includes_actionable_reasons_and_aggregate_non_actionable_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "manifest.json").write_text(
                json.dumps({"build_type": "multi_repo", "repo_count": 1, "tenant_id": "default"}),
                encoding="utf-8",
            )
            (snapshot / "metrics.jsonl").write_text(
                json.dumps(
                    {
                        "repo": "__fleet__",
                        "dimension": "backend",
                        "metric_values": {"M_cross_repo_linkage": {"value": 1.0, "state": "usable", "reason": None}},
                        "cell_score": 1.0,
                        "contract_flags": [],
                        "commit_sha_set": ["working-tree"],
                        "built_at": "2026-05-19T00:00:00+00:00",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (snapshot / "cross_repo_package_coverage.jsonl").write_text(
                json.dumps(
                    {
                        "coverage_id": "cov_pkg",
                        "tenant_id": "default",
                        "predicate": "RESOLVES_TO_REPO",
                        "state": "partially_instrumented",
                        "source_system": "package_linker",
                        "checked_at": "2026-05-19T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "consumer",
                            "repo_owner": "org",
                            "language": "typescript",
                            "reason": "cross_repo_dependency_no_provider",
                            "package_name": "local-missing",
                            "classifier_bucket": "consumer_manifest_external",
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (snapshot / "package_classifications.jsonl").write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True)
                    for row in (
                        {"classification_id": "a", "entity_id": "ent_a", "package_name": "fs", "bucket": "builtin_or_stdlib"},
                        {"classification_id": "b", "entity_id": "ent_b", "package_name": "react", "bucket": "consumer_manifest_external", "reason": "registry dependency has no matching fleet provider"},
                        {"classification_id": "c", "entity_id": "ent_c", "package_name": "local-missing", "bucket": "consumer_manifest_external", "reason": "human wording can change", "spec_form": "file_path"},
                        {"classification_id": "d", "entity_id": "ent_d", "package_name": "malformed", "bucket": "consumer_manifest_external", "spec_form": ["file_path"]},
                        {"classification_id": "e", "entity_id": "ent_e", "package_name": "bad-bucket", "bucket": ["consumer_manifest_external"]},
                        {"classification_id": "f", "entity_id": "ent_f", "package_name": "requests", "bucket": "code_inferred_external"},
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            report = write_coverage_report(snapshot, root / "report")
            markdown = (root / "report" / "coverage-run.md").read_text(encoding="utf-8")

        self.assertEqual(report.payload["coverage_gaps"][0]["reason"], "cross_repo_dependency_no_provider")
        self.assertEqual(
            report.payload["package_classification_summary"]["non_actionable_bucket_counts"],
            {"builtin_or_stdlib": 1, "code_inferred_external": 1, "consumer_manifest_external": 2},
        )
        self.assertEqual(
            report.payload["package_classification_summary"]["actionable_reason_counts"],
            {"cross_repo_dependency_no_provider": 1},
        )
        self.assertIn("| `builtin_or_stdlib` | 1 |", markdown)
        self.assertIn("| `cross_repo_dependency_no_provider` | 1 |", markdown)


def _repo_snapshot(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


def _repo_identity(path: Path) -> RepoIdentity:
    return RepoIdentity("default", "local", path.parent.name, path.name)


def _repo_entity(path: Path) -> Entity:
    return Entity(
        kind="Repo",
        identity={"tenant_id": "default", "host": "local", "owner": path.parent.name, "name": path.name},
    )


def _external_package(repo: str, name: str) -> Entity:
    return Entity(
        kind="ExternalPackage",
        identity={"tenant_id": "default", "repo": repo, "name": name},
        properties={"category": "third_party", "import_root": name},
    )


if __name__ == "__main__":
    unittest.main()
