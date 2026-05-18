from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore, read_jsonl
from source.scripts.coverage_metrics import METRICS_FILENAME, main


class CoverageMetricsPersistenceTest(unittest.TestCase):
    def test_cli_writes_metrics_jsonl_and_json_stdout_matches_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir))
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--snapshot", str(snapshot), "--expected-repos", "1", "--json"])

            metrics_path = snapshot / METRICS_FILENAME
            persisted = read_jsonl(metrics_path)
            printed = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]

            self.assertEqual(exit_code, 0)
            self.assertTrue(metrics_path.exists())
            self.assertEqual(printed, persisted)
            self.assertEqual(len(persisted), 1)
            record = persisted[0]
            self.assertEqual(record["repo"], "repo")
            self.assertEqual(record["dimension"], "backend")
            self.assertEqual(record["commit_sha_set"], ["working-tree"])
            self.assertIsInstance(record["built_at"], str)
            self.assertIn("M_inventory", record["metric_values"])

    def test_cli_no_persist_keeps_snapshot_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = _write_backend_snapshot(Path(tmpdir))
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--snapshot", str(snapshot), "--expected-repos", "1", "--json", "--no-persist"])

            printed = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
            self.assertEqual(exit_code, 0)
            self.assertFalse((snapshot / METRICS_FILENAME).exists())
            self.assertEqual(len(printed), 1)
            self.assertIsInstance(printed[0]["built_at"], str)


def _write_backend_snapshot(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
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
    return snapshot


if __name__ == "__main__":
    unittest.main()
