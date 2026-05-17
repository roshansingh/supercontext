from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(backend.metric_values["M_extractor_opportunity"].state, "partial")
            self.assertEqual(backend.metric_values["M_useful_edge"].state, "partial")
            self.assertEqual(backend.metric_values["M_identity_health"].state, "partial")

    def test_evidence_grounding_counts_scoped_facts_without_evidence_as_ungrounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir), include_ungrounded_fact=True)

            backend = _cell(compute_all(snapshot, expected_repos=1), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 0.5)

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

    def test_dimension_scoping_uses_repo_and_path_for_multi_repo_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            api_repo = root / "api"
            ml_repo = root / "ml"
            api_repo.mkdir()
            ml_repo.mkdir()
            (api_repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
            (ml_repo / "app.py").write_text("import torch\n", encoding="utf-8")
            snapshot = root / "snapshot"

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
                        bytes_ref={"repo": "api", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="fact",
                        target_id=api_fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"fact": "api-implements"},
                        bytes_ref={"repo": "api", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                    Evidence(
                        target_type="entity",
                        target_id=ml_module.entity_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"entity": "ml-module"},
                        bytes_ref={"repo": "ml", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
                    ),
                ],
                coverage=[],
                manifest={
                    "repo_count": 2,
                    "repos": [
                        {"repo_path": str(api_repo), "repo_name": "api", "owner": root.name, "commit_sha": "working-tree"},
                        {"repo_path": str(ml_repo), "repo_name": "ml", "owner": root.name, "commit_sha": "working-tree"},
                    ],
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 2}},
                },
            )

            backend = _cell(compute_all(snapshot, expected_repos=2), "backend")

            self.assertEqual(backend.metric_values["M_evidence_grounding"].value, 1.0)

    def test_hash_urn_shape_matches_current_entity_urn(self) -> None:
        entity = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})

        self.assertTrue(_looks_like_hash_urn(entity.urn))


def _write_backend_snapshot(root: Path, *, include_ungrounded_fact: bool = False) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    snapshot = root / "snapshot"
    service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
    module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
    symbol = Entity("CodeSymbol", {"tenant_id": "default", "repo": "repo", "module": "app", "qualname": "run"})
    fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
    ungrounded_fact = Fact("DEFINED_IN", symbol.entity_id, module.entity_id)
    evidence = [
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
            bytes_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line_start": 1, "line_end": 1},
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
