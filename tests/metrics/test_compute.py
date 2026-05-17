from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
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

    def test_hash_urn_shape_matches_current_entity_urn(self) -> None:
        entity = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})

        self.assertTrue(_looks_like_hash_urn(entity.urn))


def _write_backend_snapshot(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    snapshot = root / "snapshot"
    service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
    module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
    symbol = Entity("CodeSymbol", {"tenant_id": "default", "repo": "repo", "module": "app", "qualname": "run"})
    fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
    evidence = [
        Evidence(
            target_type="entity",
            target_id=module.entity_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"entity": "module"},
            bytes_ref={"repo": "repo", "commit_sha": "abc", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
        Evidence(
            target_type="entity",
            target_id=symbol.entity_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"entity": "symbol"},
            bytes_ref={"repo": "repo", "commit_sha": "abc", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
        Evidence(
            target_type="fact",
            target_id=fact.fact_id,
            derivation_class="deterministic_static",
            source_system="test",
            source_ref={"fact": "implements"},
            bytes_ref={"repo": "repo", "commit_sha": "abc", "path": "app.py", "line_start": 1, "line_end": 1},
        ),
    ]
    JsonlKgStore(snapshot).write(
        entities=[service, module, symbol],
        facts=[fact],
        evidence=evidence,
        coverage=[],
        manifest={
            "repo_path": str(repo),
            "repo_name": "repo",
            "commit_sha": "abc",
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
