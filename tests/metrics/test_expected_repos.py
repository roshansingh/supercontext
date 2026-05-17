from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.metrics import compute_all


class ExpectedReposMetricTest(unittest.TestCase):
    def test_inventory_is_na_without_expected_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_minimal_snapshot(Path(tmpdir))

            cell = compute_all(snapshot)[0]

            self.assertEqual(cell.metric_values["M_inventory"].state, "n_a")
            self.assertEqual(cell.metric_values["M_inventory"].reason, "missing expected repo denominator")

    def test_inventory_uses_expected_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_minimal_snapshot(Path(tmpdir))

            cell = compute_all(snapshot, expected_repos=2)[0]

            self.assertEqual(cell.metric_values["M_inventory"].state, "usable")
            self.assertEqual(cell.metric_values["M_inventory"].value, 0.5)


def _write_minimal_snapshot(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("import fastapi\n", encoding="utf-8")
    snapshot = root / "snapshot"
    service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
    module = Entity("CodeModule", {"tenant_id": "default", "repo": "repo", "module": "app"})
    fact = Fact("IMPLEMENTS", module.entity_id, service.entity_id)
    evidence = Evidence(
        target_type="fact",
        target_id=fact.fact_id,
        derivation_class="deterministic_static",
        source_system="test",
        source_ref={"test": "minimal"},
        bytes_ref={"repo": "repo", "commit_sha": "abc", "path": "app.py", "line_start": 1, "line_end": 1},
    )
    JsonlKgStore(snapshot).write(
        entities=[service, module],
        facts=[fact],
        evidence=[evidence],
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


if __name__ == "__main__":
    unittest.main()
