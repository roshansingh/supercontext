from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from source.scripts.capture_snapshot_baseline import capture_snapshot_baseline
from source.scripts.compare_snapshot_baseline import load_baseline, compare_snapshot_baseline, render_differences


class SnapshotBaselineTest(unittest.TestCase):
    def test_capture_snapshot_baseline_counts_distilled_distributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir)
            legacy_language_file_key = "python" + "_files"
            _write_json(
                snapshot / "manifest.json",
                {
                    "counts": {
                        "entities": 2,
                        "facts": 2,
                        "files_by_language": {"python": 1},
                        legacy_language_file_key: 1,
                    },
                    "extractor_errors": ["boom"],
                },
            )
            _write_jsonl(snapshot / "entities.jsonl", [{"kind": "Repo"}, {"kind": "Service"}])
            _write_jsonl(snapshot / "facts.jsonl", [{"predicate": "CALLS"}, {"predicate": "CALLS"}])
            _write_jsonl(snapshot / "evidence.jsonl", [{"id": "ev-1"}])
            _write_jsonl(
                snapshot / "coverage.jsonl",
                [
                    {"scope_ref": {"reason": "parser_deferred"}},
                    {"scope_ref": {"reason": "parser_deferred"}},
                    {"scope_ref": {"reason": "unknown_stack"}},
                ],
            )

            baseline = capture_snapshot_baseline(snapshot, name="fixture")

        self.assertEqual(baseline["name"], "fixture")
        self.assertEqual(baseline["manifest_counts"], {"entities": 2, "facts": 2})
        self.assertEqual(baseline["extractor_errors_count"], 1)
        self.assertEqual(baseline["entity_kind_counts"], {"Repo": 1, "Service": 1})
        self.assertEqual(baseline["fact_predicate_counts"], {"CALLS": 2})
        self.assertEqual(baseline["coverage_reason_counts"], {"parser_deferred": 2, "unknown_stack": 1})

    def test_capture_snapshot_baseline_rejects_missing_required_distribution_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir)
            _write_json(snapshot / "manifest.json", {"counts": {}, "extractor_errors": []})
            _write_jsonl(snapshot / "entities.jsonl", [{"kind": "Repo"}])
            _write_jsonl(snapshot / "facts.jsonl", [{"predicate": ""}])
            _write_jsonl(snapshot / "evidence.jsonl", [])
            _write_jsonl(snapshot / "coverage.jsonl", [])

            with self.assertRaisesRegex(ValueError, "facts.jsonl field 'predicate'"):
                capture_snapshot_baseline(snapshot, name="fixture")

    def test_capture_snapshot_baseline_normalizes_legacy_coverage_reason_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir)
            _write_json(snapshot / "manifest.json", {"counts": {}, "extractor_errors": []})
            _write_jsonl(snapshot / "entities.jsonl", [])
            _write_jsonl(snapshot / "facts.jsonl", [])
            _write_jsonl(snapshot / "evidence.jsonl", [])
            _write_jsonl(
                snapshot / "coverage.jsonl",
                [{"scope_ref": {"reason": "parser_backed_js_ts_route_extraction_partial_express_only"}}],
            )

            baseline = capture_snapshot_baseline(snapshot, name="fixture")

        self.assertEqual(
            baseline["coverage_reason_counts"],
            {"parser_backed_js_ts_route_extraction_partial_express_fastify_koa_only": 1},
        )

    def test_compare_snapshot_baseline_reports_distribution_drift(self) -> None:
        expected = _baseline(fact_counts={"CALLS": 2}, coverage_counts={"old": 1})
        actual = _baseline(fact_counts={"CALLS": 1, "IMPORTS": 1}, coverage_counts={"new": 1})

        differences = compare_snapshot_baseline(actual, expected)

        rendered = render_differences(differences)
        self.assertIn("| fact_predicate_counts | CALLS | 2 | 1 |", rendered)
        self.assertIn("| fact_predicate_counts | IMPORTS | missing | 1 |", rendered)
        self.assertIn("| coverage_reason_counts | old | 1 | missing |", rendered)
        self.assertIn("| coverage_reason_counts | new | missing | 1 |", rendered)

    def test_compare_snapshot_baseline_can_allow_additions_only(self) -> None:
        expected = _baseline(fact_counts={"CALLS": 2}, manifest_counts={"facts": 2})
        actual_addition = _baseline(fact_counts={"CALLS": 3, "IMPORTS": 1}, manifest_counts={"facts": 4})
        actual_decrease = _baseline(fact_counts={"CALLS": 1}, manifest_counts={"facts": 1})

        self.assertEqual(compare_snapshot_baseline(actual_addition, expected, allow_additions=True), [])
        self.assertNotEqual(compare_snapshot_baseline(actual_decrease, expected, allow_additions=True), [])

    def test_compare_snapshot_baseline_never_allows_extractor_error_count_changes(self) -> None:
        expected = _baseline()
        actual_with_error = _baseline()
        actual_with_error["extractor_errors_count"] = 1

        differences = compare_snapshot_baseline(actual_with_error, expected, allow_additions=True)

        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0].section, "extractor_errors_count")

    def test_render_differences_reports_success(self) -> None:
        self.assertEqual(render_differences([]), "Snapshot matches baseline.")

    def test_compare_snapshot_baseline_cli_reports_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshot = tmp_path / "snapshot"
            snapshot.mkdir()
            baseline_path = tmp_path / "baseline.json"
            _write_json(snapshot / "manifest.json", {"counts": {"facts": 1}, "extractor_errors": []})
            _write_jsonl(snapshot / "entities.jsonl", [{"kind": "Repo"}])
            _write_jsonl(snapshot / "facts.jsonl", [{"predicate": "CALLS"}])
            _write_jsonl(snapshot / "evidence.jsonl", [{"id": "ev-1"}])
            _write_jsonl(snapshot / "coverage.jsonl", [])
            _write_json(baseline_path, capture_snapshot_baseline(snapshot, name="fixture"))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "source.scripts.compare_snapshot_baseline",
                    str(snapshot),
                    "--baseline",
                    str(baseline_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "Snapshot matches baseline.")
        self.assertEqual(result.stderr, "")

    def test_capture_snapshot_baseline_requires_evidence_file_for_complete_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir)
            _write_json(snapshot / "manifest.json", {"counts": {}, "extractor_errors": []})
            _write_jsonl(snapshot / "entities.jsonl", [])
            _write_jsonl(snapshot / "facts.jsonl", [])
            _write_jsonl(snapshot / "coverage.jsonl", [])

            with self.assertRaisesRegex(FileNotFoundError, "evidence.jsonl"):
                capture_snapshot_baseline(snapshot, name="fixture")

    def test_capture_snapshot_baseline_rejects_boolean_manifest_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir)
            _write_json(snapshot / "manifest.json", {"counts": {"facts": True}, "extractor_errors": []})
            _write_jsonl(snapshot / "entities.jsonl", [])
            _write_jsonl(snapshot / "facts.jsonl", [])
            _write_jsonl(snapshot / "evidence.jsonl", [])
            _write_jsonl(snapshot / "coverage.jsonl", [])

            with self.assertRaisesRegex(ValueError, "manifest.counts.facts"):
                capture_snapshot_baseline(snapshot, name="fixture")

    def test_load_baseline_rejects_malformed_distribution_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            baseline = _baseline(fact_counts={"CALLS": 2})
            baseline["fact_predicate_counts"] = {"CALLS": "two"}
            _write_json(path, baseline)

            with self.assertRaisesRegex(ValueError, "fact_predicate_counts.CALLS"):
                load_baseline(path)

    def test_load_baseline_rejects_boolean_distribution_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            baseline = _baseline(fact_counts={"CALLS": 2})
            baseline["fact_predicate_counts"] = {"CALLS": True}
            _write_json(path, baseline)

            with self.assertRaisesRegex(ValueError, "fact_predicate_counts.CALLS"):
                load_baseline(path)

    def test_compare_snapshot_baseline_treats_boolean_actual_counts_as_invalid(self) -> None:
        expected = _baseline(fact_counts={"CALLS": 1})
        actual = _baseline(fact_counts={"CALLS": 1})
        actual["fact_predicate_counts"] = {"CALLS": True}

        differences = compare_snapshot_baseline(actual, expected)

        self.assertEqual(len(differences), 1)
        self.assertEqual(differences[0].section, "fact_predicate_counts")
        self.assertEqual(differences[0].key, "CALLS")


def _baseline(
    fact_counts: dict[str, int] | None = None,
    coverage_counts: dict[str, int] | None = None,
    manifest_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "baseline_version": 1,
        "name": "fixture",
        "manifest_counts": manifest_counts or {},
        "extractor_errors_count": 0,
        "entity_kind_counts": {},
        "fact_predicate_counts": fact_counts or {},
        "coverage_reason_counts": coverage_counts or {},
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
