from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from source.kg.core.models import Coverage, Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.metrics import compute_all
from source.kg.metrics.compute import _looks_like_hash_urn


class CoverageMetricsComputeTest(unittest.TestCase):
    def test_compute_all_emits_all_default_metrics_with_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir))

            cells = compute_all(snapshot, expected_repos=1)

            backend = _cell(cells, "backend")
            self.assertEqual(set(backend.metric_values), {
                "M_inventory",
                "M_dimension_classification",
                "M_freshness",
                "M_extractor_opportunity",
                "M_evidence_grounding",
                "M_meta_coverage",
                "M_silent_gap",
                "M_trust_mix",
                "M_useful_edge",
                "M_cross_repo_linkage",
                "M_identity_health",
            })
            self.assertEqual(backend.metric_values["M_inventory"].value, 1.0)
            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 1.0)
            self.assertEqual(backend.metric_values["M_extractor_opportunity"].state, "n_a")
            self.assertEqual(backend.metric_values["M_silent_gap"].state, "n_a")
            self.assertEqual(backend.metric_values["M_useful_edge"].state, "usable")
            self.assertEqual(backend.metric_values["M_useful_edge"].value, 1.0)
            self.assertEqual(backend.metric_values["M_identity_health"].state, "usable")
            self.assertEqual(backend.metric_values["M_identity_health"].value, 1.0)

    def test_evidence_grounding_counts_scoped_facts_without_evidence_as_ungrounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir), include_ungrounded_fact=True)

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 0.5)

    def test_evidence_grounding_ignores_fact_evidence_outside_dimension_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            (repo / "notes.md").write_text("outside scope\n", encoding="utf-8")
            snapshot = root / "snapshot"
            module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[module, service],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "module"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "outside-scope"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "notes.md", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 0.0)
            self.assertEqual(backend.metric_values["M_trust_mix"].value, 0.0)

    def test_meta_coverage_ignores_uninstrumented_coverage_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    Coverage(
                        tenant_id="default",
                        predicate="CALLS",
                        scope_ref={"repo": "repo", "reason": "not_supported"},
                        state="uninstrumented",
                        source_system="test",
                    )
                ],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_meta_coverage"].value, 0.0)

    def test_multi_repo_manifest_paths_feed_dimension_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            api_repo = root / "api"
            ui_repo = root / "ui"
            api_repo.mkdir()
            ui_repo.mkdir()
            (api_repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            (ui_repo / "package.json").write_text('{"dependencies": {"react": "latest"}}\n', encoding="utf-8")
            (ui_repo / "index.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_count": 2,
                    "repos": [
                        {"repo_path": str(api_repo), "repo_name": "api", "owner": root.name, "commit_sha": "working-tree"},
                        {"repo_path": str(ui_repo), "repo_name": "ui", "owner": root.name, "commit_sha": "working-tree"},
                    ],
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1, "typescript": 1}},
                },
            )

            cells = compute_all(snapshot, expected_repos=2)

            self.assertGreaterEqual({cell.dimension for cell in cells}, {"backend", "frontend"})

    def test_cross_repo_linkage_is_usable_when_snapshot_languages_have_resolvers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            package = Entity(
                "ExternalPackage",
                {"tenant_id": "default", "repo": "repo", "name": "shared_pkg"},
                properties={"category": "third_party", "import_root": "shared_pkg", "distribution_name": "shared-pkg"},
            )
            provider = Entity(
                "Repo",
                {"tenant_id": "default", "host": "local", "owner": "owner", "name": "shared"},
            )
            link = Fact("RESOLVES_TO_REPO", package.entity_id, provider.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[package, provider],
                facts=[link],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            metric = compute_all(snapshot, expected_repos=1)[0].metric_values["M_cross_repo_linkage"]

            self.assertEqual(metric.state, "usable")
            self.assertEqual(metric.value, 1.0)

    def test_cross_repo_linkage_stays_partial_when_snapshot_language_resolver_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "index.ts").write_text("import sharedPkg from 'shared-pkg';\n", encoding="utf-8")
            snapshot = root / "snapshot"
            package = Entity(
                "ExternalPackage",
                {"tenant_id": "default", "repo": "repo", "name": "shared-pkg"},
                properties={"category": "third_party", "import_root": "shared-pkg", "distribution_name": "shared-pkg"},
            )
            provider = Entity(
                "Repo",
                {"tenant_id": "default", "host": "local", "owner": "owner", "name": "shared"},
            )
            link = Fact("RESOLVES_TO_REPO", package.entity_id, provider.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[package, provider],
                facts=[link],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"typescript": 1}},
                },
            )

            metric = compute_all(snapshot, expected_repos=1)[0].metric_values["M_cross_repo_linkage"]

            self.assertEqual(metric.state, "partial")
            self.assertEqual(metric.reason, "package_resolver hooks are not implemented for: typescript")

    def test_cross_repo_linkage_treats_boolean_language_counts_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            package = Entity(
                "ExternalPackage",
                {"tenant_id": "default", "repo": "repo", "name": "shared_pkg"},
                properties={"category": "third_party", "import_root": "shared_pkg", "distribution_name": "shared-pkg"},
            )
            provider = Entity(
                "Repo",
                {"tenant_id": "default", "host": "local", "owner": "owner", "name": "shared"},
            )
            link = Fact("RESOLVES_TO_REPO", package.entity_id, provider.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[package, provider],
                facts=[link],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": True}},
                },
            )

            metric = compute_all(snapshot, expected_repos=1)[0].metric_values["M_cross_repo_linkage"]

            self.assertEqual(metric.state, "partial")
            self.assertEqual(metric.reason, "package_resolver language coverage is unknown")

    def test_inventory_fails_closed_on_malformed_repo_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_count": 1,
                    "repos": [{}],
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_inventory"].state, "n_a")
            self.assertEqual(cell.metric_values["M_inventory"].reason, "missing actual repo count in manifest")

    def test_inventory_rejects_boolean_repo_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_count": True,
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_inventory"].state, "n_a")

    def test_useful_edge_counts_object_anchor_without_object_entity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
            fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[service, module],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "module"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "implements"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

        self.assertEqual(backend.metric_values["M_useful_edge"].value, 1.0)

    def test_useful_edge_reports_zero_when_anchor_has_no_useful_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            JsonlKgStore(snapshot).write(
                entities=[service],
                facts=[],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=service.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "service"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

        self.assertEqual(backend.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(backend.metric_values["M_useful_edge"].value, 0.0)

    def test_useful_edge_counts_fact_endpoints_without_entity_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            endpoint = Entity(
                "Endpoint",
                {"tenant_id": "default", "repo": "repo", "protocol": "http", "method": "GET", "path": "/health"},
            )
            fact = Fact("EXPOSES_ENDPOINT", service.entity_id, endpoint.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[service, endpoint],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "endpoint"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

        self.assertEqual(backend.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(backend.metric_values["M_useful_edge"].value, 1.0)

    def test_iac_useful_edge_counts_domain_object_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "main.tf").write_text('resource "aws_route53_record" "www" {}\n', encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            domain = Entity("Domain", {"tenant_id": "default", "repo": "repo", "name": "example.com"})
            fact = Fact("REFERENCES_DOMAIN", service.entity_id, domain.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[service, domain],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=domain.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "domain"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "main.tf", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "domain"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "main.tf", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"terraform": 1}},
                },
            )

            iac = _cell(compute_all(snapshot, expected_repos=1), "iac")

        self.assertEqual(iac.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(iac.metric_values["M_useful_edge"].value, 1.0)

    def test_useful_edge_counts_event_channel_object_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "worker.py").write_text("from fastapi import FastAPI\nimport boto3\n", encoding="utf-8")
            snapshot = root / "snapshot"
            caller = Entity(
                "CodeSymbol",
                {"tenant_id": "default", "repo": "repo", "module": "worker", "qualname": "publish", "symbol_kind": "function"},
            )
            channel = Entity(
                "EventChannel",
                {"tenant_id": "default", "broker_kind": "sqs", "channel_address": "orders"},
            )
            fact = Fact("PRODUCES_EVENT", caller.entity_id, channel.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[caller, channel],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "event"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "worker.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

        self.assertEqual(backend.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(backend.metric_values["M_useful_edge"].value, 1.0)

    def test_useful_edge_counts_references_event_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            channel = Entity(
                "EventChannel",
                {"tenant_id": "default", "broker_kind": "sqs", "channel_address": "orders"},
            )
            fact = Fact("REFERENCES_EVENT_CHANNEL", service.entity_id, channel.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[service, channel],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "event-reference"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

        self.assertEqual(backend.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(backend.metric_values["M_useful_edge"].value, 1.0)

    def test_shared_lib_useful_edge_counts_incoming_call_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text("[project]\nname = \"repo\"\n", encoding="utf-8")
            (repo / "lib.py").write_text("def caller():\n    return callee()\n\ndef callee():\n    return 1\n", encoding="utf-8")
            snapshot = root / "snapshot"
            caller = Entity(
                "CodeSymbol",
                {"tenant_id": "default", "repo": "repo", "module": "lib", "qualname": "caller", "symbol_kind": "function"},
            )
            callee = Entity(
                "CodeSymbol",
                {"tenant_id": "default", "repo": "repo", "module": "lib", "qualname": "callee", "symbol_kind": "function"},
            )
            fact = Fact("CALLS", caller.entity_id, callee.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[caller, callee],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=callee.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "callee"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "lib.py", "line_start": 4, "line_end": 5},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "call"},
                        bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "lib.py", "line_start": 2, "line_end": 2},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            shared_lib = _cell(compute_all(snapshot, expected_repos=1), "shared-lib")

        self.assertEqual(shared_lib.metric_values["M_useful_edge"].state, "usable")
        self.assertEqual(shared_lib.metric_values["M_useful_edge"].value, 1.0)

    def test_custom_config_can_disable_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = _write_backend_snapshot(root)
            config = root / "metrics.yaml"
            config.write_text(
                "enabled_metrics:\n"
                "  - M_inventory\n"
                "freshness:\n"
                "  default_days: 365\n"
                "trust_weights: {}\n",
                encoding="utf-8",
            )

            cell = compute_all(snapshot, expected_repos=1, config_path=config)[0]

            self.assertEqual(tuple(cell.metric_values), ("M_inventory",))
            self.assertIsNone(cell.cell_score)

    def test_missing_dimension_reports_zero_dimension_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "plain.py").write_text("print('plain')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertIsNone(cell.dimension)
            self.assertEqual(cell.metric_values["M_dimension_classification"].value, 0.0)

    def test_missing_dimension_still_requires_file_count_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "plain.py").write_text("print('plain')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertIsNone(cell.dimension)
            self.assertEqual(cell.metric_values["M_dimension_classification"].state, "n_a")
            self.assertEqual(
                cell.metric_values["M_dimension_classification"].reason,
                "missing manifest counts.files_by_language denominator",
            )

    def test_missing_file_count_denominator_is_na(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_dimension_classification"].state, "n_a")
            self.assertEqual(
                cell.metric_values["M_dimension_classification"].reason,
                "missing manifest counts.files_by_language denominator",
            )

    def test_malformed_counts_denominator_is_na(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": "malformed",
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_dimension_classification"].state, "n_a")

    def test_partially_malformed_file_count_denominator_is_na(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "abc",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1, "typescript": "100"}},
                },
            )

            cell = compute_all(snapshot, expected_repos=1)[0]

            self.assertEqual(cell.metric_values["M_dimension_classification"].state, "n_a")
            self.assertEqual(
                cell.metric_values["M_dimension_classification"].reason,
                "malformed manifest counts.files_by_language denominator",
            )

    def test_dimension_scoping_uses_snapshot_repo_commit_and_path_for_multi_repo_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            api_repo = root / "api"
            ml_repo = root / "ml"
            api_repo.mkdir()
            ml_repo.mkdir()
            (api_repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            (ml_repo / "app.py").write_text("import torch\n", encoding="utf-8")
            snapshot = root / "snapshot"
            api_identity = f"default/local/{root.name}/api"
            ml_identity = f"default/local/{root.name}/ml"

            api_module = Entity("CodeModule", {"tenant_id": "default", "repo": "api", "module": "app"})
            api_service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "api", "slug": "api"})
            api_fact = Fact("IMPLEMENTS", api_module.entity_id, api_service.entity_id)
            ml_module = Entity("CodeModule", {"tenant_id": "default", "repo": "ml", "module": "app"})
            ml_service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "ml", "slug": "ml"})
            ml_fact = Fact("IMPLEMENTS", ml_module.entity_id, ml_service.entity_id)

            JsonlKgStore(snapshot).write(
                entities=[api_module, api_service, ml_module, ml_service],
                facts=[api_fact, ml_fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=api_module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "api-module"},
                        bytes_ref={"repo": api_identity, "commit_sha": "api-snapshot", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=api_fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "api-implements"},
                        bytes_ref={"repo": api_identity, "commit_sha": "api-snapshot", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="entity",
                        target_id=ml_module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "ml-module"},
                        bytes_ref={"repo": ml_identity, "commit_sha": "ml-snapshot", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_count": 2,
                    "repos": [
                        {"repo_path": str(api_repo), "repo_name": "api", "owner": root.name, "commit_sha": "api-snapshot"},
                        {"repo_path": str(ml_repo), "repo_name": "ml", "owner": root.name, "commit_sha": "ml-snapshot"},
                    ],
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 2}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=2), "backend")

            self.assertEqual(backend.metric_values["M_dimension_classification"].value, 0.5)
            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 1.0)

    def test_dimension_scoping_uses_owner_identity_for_same_name_working_tree_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend_repo = root / "owner-a" / "svc"
            data_repo = root / "owner-b" / "svc"
            backend_repo.mkdir(parents=True)
            data_repo.mkdir(parents=True)
            (backend_repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            (data_repo / "app.py").write_text("import torch\n", encoding="utf-8")
            snapshot = root / "snapshot"
            backend_identity = "default/local/owner-a/svc"
            data_identity = "default/local/owner-b/svc"

            backend_module = Entity("CodeModule", {"tenant_id": "default", "repo": backend_identity, "module": "app"})
            backend_service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": backend_identity, "slug": "svc"})
            backend_fact = Fact("IMPLEMENTS", backend_module.entity_id, backend_service.entity_id)
            data_module = Entity("CodeModule", {"tenant_id": "default", "repo": data_identity, "module": "app"})
            data_service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": data_identity, "slug": "svc"})
            data_fact = Fact("IMPLEMENTS", data_module.entity_id, data_service.entity_id)

            JsonlKgStore(snapshot).write(
                entities=[backend_module, backend_service, data_module, data_service],
                facts=[backend_fact, data_fact],
                evidence=[
                    Evidence(
                        target_type="entity",
                        target_id=backend_module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "backend-module"},
                        bytes_ref={"repo": backend_identity, "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=backend_fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "backend-implements"},
                        bytes_ref={"repo": backend_identity, "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="entity",
                        target_id=data_module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "data-module"},
                        bytes_ref={"repo": data_identity, "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "tenant_id": "default",
                    "repo_count": 2,
                    "repos": [
                        {"repo_path": str(backend_repo), "repo_name": "svc", "owner": "owner-a", "commit_sha": "working-tree"},
                        {"repo_path": str(data_repo), "repo_name": "svc", "owner": "owner-b", "commit_sha": "working-tree"},
                    ],
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 2}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=2), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 1.0)

    def test_dimension_rule_loader_errors_are_not_hidden(self) -> None:
        class BadLanguage:
            name = "python"
            aliases = ()

            def dimension_rules(self):
                raise ValueError("bad dimension rules")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "snapshot-commit",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            with mock.patch("source.kg.metrics.dimension._registered_languages", return_value=(BadLanguage(),)):
                with self.assertRaisesRegex(ValueError, "bad dimension rules"):
                    compute_all(snapshot, expected_repos=1)

    def test_evidence_grounding_rejects_boolean_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir), fact_line_start=True)

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 0.0)

    def test_per_kind_urn_shape_no_longer_counts_as_hash_urn(self) -> None:
        entity = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})

        self.assertFalse(_looks_like_hash_urn(entity.urn))


def _write_backend_snapshot(
    root: Path,
    *,
    include_ungrounded_fact: bool = False,
    fact_line_start: object = 1,
) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    snapshot = root / "snapshot"
    service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
    module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
    symbol = Entity(
        "CodeSymbol",
        {"tenant_id": "default", "repo": "repo", "module": "app", "qualname": "run", "symbol_kind": "function"},
    )
    fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
    ungrounded_fact = Fact("DEFINED_IN", symbol.entity_id, module.entity_id)
    evidence = [
        Evidence(
            # Service evidence keeps the shared fixture broad enough for
            # scoped entity metrics beyond useful-edge fact endpoints.
            target_type="entity",
            target_id=service.entity_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"entity": "service"},
            bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
        Evidence(
            target_type="entity",
            target_id=module.entity_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"entity": "module"},
            bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
        Evidence(
            target_type="entity",
            target_id=symbol.entity_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"entity": "symbol"},
            bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"fact": "implements"},
            bytes_ref={
                "repo": "repo",
                "commit_sha": "working-tree",
                "path": "app.py",
                "line_start": fact_line_start,
                "line_end": 1,
            },
        ),
    ]
    JsonlKgStore(snapshot).write(
        entities=[service, module, symbol],
        facts=[fact, ungrounded_fact] if include_ungrounded_fact else [fact],
        evidence=evidence,
        coverage=[],
        manifest={
            "repo_path": str(repo),
            "repo_name": "repo",
            "commit_sha": "working-tree",
            "built_at": "2026-05-17T00:00:00+00:00",
            "counts": {"files_by_language": {"python": 1}},
        },
    )
    return snapshot


def _cell(cells, dimension: str):
    for cell in cells:
        if cell.dimension == dimension:
            return cell
    raise AssertionError(f"missing cell for dimension {dimension!r}: {cells}")


if __name__ == "__main__":
    unittest.main()
