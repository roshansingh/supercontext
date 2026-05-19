from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path

from source.kg.core.store import read_jsonl
from source.kg.metrics.report import REPORT_JSON_FILENAME, REPORT_MARKDOWN_FILENAME, write_coverage_report
from source.scripts.coverage_metrics import METRICS_FILENAME
from source.scripts.coverage_report import main


class CoverageReportTest(unittest.TestCase):
    def test_report_writes_stable_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            out = root / "report"
            _write_snapshot(
                snapshot,
                _record(
                    repo="api",
                    dimension="backend",
                    cell_score=0.7,
                    metrics={
                        "M_evidence_grounding": {"value": 1.0, "state": "usable", "reason": None},
                        "M_silent_gap": {"value": 0.2, "state": "usable", "reason": None},
                    },
                ),
                _record(
                    repo="web",
                    dimension="frontend",
                    cell_score=0.3,
                    metrics={
                        "M_evidence_grounding": {"value": 0.5, "state": "usable", "reason": None},
                        "M_silent_gap": {"value": None, "state": "n_a", "reason": "no detected opportunities"},
                    },
                    flags=["M_silent_gap:n_a:no detected opportunities"],
                ),
            )

            report = write_coverage_report(
                snapshot,
                out,
                run_id="shopagain-latticeai-2026-05-18",
                expected_repos=23,
                tenant="shopagain-latticeai",
                metric_config="source/kg/metrics/config.yaml",
            )

            payload = json.loads((out / REPORT_JSON_FILENAME).read_text(encoding="utf-8"))
            markdown = (out / REPORT_MARKDOWN_FILENAME).read_text(encoding="utf-8")

            self.assertEqual(report.json_path, (out / REPORT_JSON_FILENAME).resolve())
            self.assertEqual(report.markdown_path, (out / REPORT_MARKDOWN_FILENAME).resolve())
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["run_id"], "shopagain-latticeai-2026-05-18")
            self.assertEqual(payload["tenant"], "shopagain-latticeai")
            self.assertEqual(payload["repo_count_expected"], 23)
            self.assertEqual(payload["repo_count_indexed"], 2)
            self.assertEqual(payload["metrics_built_at_set"], ["2026-05-18T00:00:00+00:00"])
            self.assertNotIn("generated_at", payload)
            self.assertEqual(payload["summary"]["fleet_score"], 0.5)
            self.assertEqual(payload["summary"]["repos_with_lowest_coverage"][0]["repo"], "web")
            self.assertEqual(payload["summary"]["worst_dimensions"][0]["dimension"], "frontend")
            self.assertEqual(payload["summary"]["worst_metrics"][0]["metric"], "M_silent_gap")
            self.assertEqual(payload["summary"]["coverage_gap_count"], 0)
            self.assertEqual(payload["coverage_gaps"], [])
            self.assertEqual(len(payload["cells"]), 2)
            self.assertIn("# Coverage Run: shopagain-latticeai-2026-05-18", markdown)
            self.assertIn("| `web` | `frontend` | 0.300 | 1 |", markdown)

    def test_cli_prints_json_payload_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            out = root / "report"
            _write_snapshot(snapshot, _record())
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["--snapshot", str(snapshot), "--out", str(out), "--json"])

            printed = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(printed, json.loads((out / REPORT_JSON_FILENAME).read_text(encoding="utf-8")))

    def test_report_payload_is_stable_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record())

            first = write_coverage_report(snapshot, root / "first").payload
            second = write_coverage_report(snapshot, root / "second").payload

            self.assertEqual(first, second)

    def test_report_rejects_missing_metrics_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Path(tmpdir) / "snapshot"
            snapshot.mkdir()
            (snapshot / "manifest.json").write_text(json.dumps({"repo_name": "repo"}), encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "run coverage_metrics first"):
                write_coverage_report(snapshot, Path(tmpdir) / "report")

    def test_report_rejects_coverage_directory_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record())
            (snapshot / "coverage.jsonl").unlink()
            (snapshot / "coverage.jsonl").mkdir()

            with self.assertRaisesRegex(ValueError, "Coverage file is not a regular file"):
                write_coverage_report(snapshot, root / "report")

    def test_report_counts_scalar_repo_count_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(), manifest={"repo_count": 5})

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(report.payload["repo_count_indexed"], 5)

    def test_report_counts_single_repo_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(), manifest={"repo_name": "solo"})

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(report.payload["repo_count_indexed"], 1)

    def test_report_rejects_malformed_metric_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(metrics={"M_evidence_grounding": {"value": True, "state": "usable", "reason": None}}))

            with self.assertRaisesRegex(ValueError, "must be numeric"):
                write_coverage_report(snapshot, root / "report")

    def test_report_rejects_missing_dimension_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            record = _record()
            record.pop("dimension")
            _write_snapshot(snapshot, record)

            with self.assertRaisesRegex(ValueError, "missing required field: dimension"):
                write_coverage_report(snapshot, root / "report")

    def test_report_rejects_empty_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(dimension=""))

            with self.assertRaisesRegex(ValueError, "dimension must be a non-empty string or null"):
                write_coverage_report(snapshot, root / "report")

    def test_report_rejects_missing_metric_built_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            record = _record()
            record.pop("built_at")
            _write_snapshot(snapshot, record)

            with self.assertRaisesRegex(ValueError, "built_at must be a non-empty string"):
                write_coverage_report(snapshot, root / "report")

    def test_report_rejects_empty_commit_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            record = _record()
            record["commit_sha_set"] = [""]
            _write_snapshot(snapshot, record)

            with self.assertRaisesRegex(ValueError, "commit_sha_set must be a non-empty list of strings"):
                write_coverage_report(snapshot, root / "report")

    def test_report_rejects_duplicate_cell_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(repo="api"), _record(repo="api"))

            with self.assertRaisesRegex(ValueError, "duplicate cell key"):
                write_coverage_report(snapshot, root / "report")

    def test_markdown_escapes_table_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(snapshot, _record(repo="repo|name", dimension="back`end"))

            write_coverage_report(snapshot, root / "report")
            markdown = (root / "report" / REPORT_MARKDOWN_FILENAME).read_text(encoding="utf-8")

            self.assertIn("`repo\\|name`", markdown)
            self.assertIn("`back'end`", markdown)

    def test_cli_rejects_non_positive_expected_repos_without_traceback(self) -> None:
        with redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit):
                main(["--snapshot", "snapshot", "--out", "report", "--expected-repos", "0"])

        self.assertIn("must be a positive integer", stderr.getvalue())

    def test_report_surfaces_unsupported_language_coverage_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(),
                coverage_records=[
                    {
                        "coverage_id": "cov_java",
                        "tenant_id": "default",
                        "predicate": "LANGUAGE_SUPPORT",
                        "state": "uninstrumented",
                        "source_system": "repo_discovery",
                        "checked_at": "2026-05-18T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "orders",
                            "language": "java",
                            "reason": "unsupported_language",
                            "file_count": 2,
                            "sample_paths": ["src/Main.java", "src/Api.java"],
                        },
                    }
                ],
            )

            report = write_coverage_report(snapshot, root / "report")
            markdown = (root / "report" / REPORT_MARKDOWN_FILENAME).read_text(encoding="utf-8")

            self.assertEqual(report.payload["summary"]["coverage_gap_count"], 1)
            self.assertEqual(
                report.payload["coverage_gaps"][0],
                {
                    "repo": "orders",
                    "repo_owner": None,
                    "language": "java",
                    "predicate": "LANGUAGE_SUPPORT",
                    "state": "uninstrumented",
                    "reason": "unsupported_language",
                    "file_count": 2,
                    "sample_paths": ["src/Main.java", "src/Api.java"],
                    "scope_ref": {
                        "repo": "orders",
                        "language": "java",
                        "reason": "unsupported_language",
                        "file_count": 2,
                        "sample_paths": ["src/Main.java", "src/Api.java"],
                    },
                    "source_system": "repo_discovery",
                },
            )
            self.assertIn("## Coverage Gaps", markdown)
            self.assertIn(
                "| `orders` | `-` | `java` | `LANGUAGE_SUPPORT` | `uninstrumented` | `unsupported_language` | 2 | "
                "`samples=src/Main.java,src/Api.java` |",
                markdown,
            )

    def test_markdown_coverage_gaps_include_scope_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(),
                coverage_records=[
                    {
                        "coverage_id": "cov_stack",
                        "tenant_id": "default",
                        "predicate": "EXPOSES_ENDPOINT",
                        "state": "uninstrumented",
                        "source_system": "extraction_framework",
                        "checked_at": "2026-05-18T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "orders",
                            "language": "python",
                            "reason": "no_adapter_for_known_stack",
                            "import_root": "django",
                            "category": "web_framework",
                        },
                    }
                ],
            )

            write_coverage_report(snapshot, root / "report")
            markdown = (root / "report" / REPORT_MARKDOWN_FILENAME).read_text(encoding="utf-8")

            self.assertIn(
                "| `orders` | `-` | `python` | `EXPOSES_ENDPOINT` | `uninstrumented` | "
                "`no_adapter_for_known_stack` | 0 | `category=web_framework; import_root=django` |",
                markdown,
            )

    def test_markdown_coverage_gap_details_do_not_break_table_on_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(),
                coverage_records=[
                    {
                        "coverage_id": "cov_error",
                        "tenant_id": "default",
                        "predicate": "PARSES",
                        "state": "uninstrumented",
                        "source_system": "extraction_framework",
                        "checked_at": "2026-05-18T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "orders",
                            "reason": "adapter_error",
                            "message": "first line\nsecond | line",
                        },
                    }
                ],
            )

            write_coverage_report(snapshot, root / "report")
            markdown = (root / "report" / REPORT_MARKDOWN_FILENAME).read_text(encoding="utf-8")

            self.assertIn("`message=first line second \\| line`", markdown)
            self.assertNotIn("first line\nsecond", markdown)

    def test_multi_repo_report_does_not_duplicate_unsupported_manifest_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(),
                manifest={
                    "build_type": "multi_repo",
                    "repo_count": 2,
                    "repos": [
                        {"repo_path": str(root / "first"), "repo_name": "first", "owner": "org", "commit_sha": "a"},
                        {"repo_path": str(root / "second"), "repo_name": "second", "owner": "org", "commit_sha": "b"},
                    ],
                    "counts": {"files_by_language": {}, "unsupported_files_by_language": {"java": 1}},
                },
                coverage_records=[
                    {
                        "coverage_id": "cov_java",
                        "tenant_id": "default",
                        "predicate": "LANGUAGE_SUPPORT",
                        "state": "uninstrumented",
                        "source_system": "repo_discovery",
                        "checked_at": "2026-05-18T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "first",
                            "language": "java",
                            "reason": "unsupported_language",
                            "file_count": 1,
                            "sample_paths": ["Main.java"],
                        },
                    }
                ],
            )

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(len(report.payload["coverage_gaps"]), 1)
            self.assertEqual(report.payload["coverage_gaps"][0]["repo"], "first")

    def test_single_repo_report_does_not_duplicate_unsupported_manifest_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(repo="orders"),
                manifest={
                    "repo_path": str(root / "orders"),
                    "repo_name": "orders",
                    "owner": "shopagain",
                    "commit_sha": "abc",
                    "counts": {"files_by_language": {}, "unsupported_files_by_language": {"java": 2}},
                },
                coverage_records=[
                    {
                        "coverage_id": "cov_java",
                        "tenant_id": "default",
                        "predicate": "LANGUAGE_SUPPORT",
                        "state": "uninstrumented",
                        "source_system": "repo_discovery",
                        "checked_at": "2026-05-18T00:00:00+00:00",
                        "scope_ref": {
                            "repo": "orders",
                            "language": "java",
                            "reason": "unsupported_language",
                            "file_count": 2,
                            "sample_paths": ["src/Main.java", "src/Api.java"],
                        },
                    }
                ],
            )

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(len(report.payload["coverage_gaps"]), 1)
            self.assertEqual(report.payload["coverage_gaps"][0]["repo"], "orders")

    def test_report_skips_manifest_unsupported_gap_when_single_repo_name_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(),
                manifest={"counts": {"files_by_language": {}, "unsupported_files_by_language": {"java": 2}}},
            )

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(report.payload["coverage_gaps"], [])

    def test_manifest_unsupported_gap_scope_ref_matches_coverage_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            snapshot = root / "snapshot"
            _write_snapshot(
                snapshot,
                _record(repo="orders"),
                manifest={
                    "repo_path": str(root / "orders"),
                    "repo_name": "orders",
                    "owner": "shopagain",
                    "commit_sha": "abc",
                    "counts": {"files_by_language": {}, "unsupported_files_by_language": {"java": 2}},
                },
            )

            report = write_coverage_report(snapshot, root / "report")

            self.assertEqual(
                report.payload["coverage_gaps"][0]["scope_ref"],
                {
                    "repo": "orders",
                    "repo_owner": "shopagain",
                    "language": "java",
                    "path_prefix": ".",
                    "reason": "unsupported_language",
                    "file_count": 2,
                    "sample_paths": [],
                },
            )
            self.assertEqual(report.payload["coverage_gaps"][0]["repo_owner"], "shopagain")


def _write_snapshot(
    snapshot: Path,
    *records: dict,
    manifest: dict | None = None,
    coverage_records: list[dict] | None = None,
) -> None:
    repo = snapshot.parent / "repo"
    repo.mkdir(exist_ok=True)
    snapshot.mkdir()
    manifest_payload = manifest or {
        "build_type": "multi_repo",
        "built_at": "2026-05-18T00:00:00+00:00",
        "tenant_id": "default",
        "repo_count": 2,
        "repos": [
            {"repo_path": str(repo), "repo_name": "api", "owner": "shopagain", "commit_sha": "a"},
            {"repo_path": str(repo), "repo_name": "web", "owner": "shopagain", "commit_sha": "b"},
        ],
        "counts": {"files_by_language": {"python": 1}},
    }
    (snapshot / "manifest.json").write_text(
        json.dumps(manifest_payload, sort_keys=True),
        encoding="utf-8",
    )
    with (snapshot / METRICS_FILENAME).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    with (snapshot / "coverage.jsonl").open("w", encoding="utf-8") as handle:
        for record in coverage_records or []:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    self_check = read_jsonl(snapshot / METRICS_FILENAME)
    if len(self_check) != len(records):
        raise AssertionError("test fixture metrics did not round-trip")


def _record(
    *,
    repo: str = "repo",
    dimension: str | None = "backend",
    cell_score: float | None = 0.5,
    metrics: dict | None = None,
    flags: list[str] | None = None,
) -> dict:
    return {
        "repo": repo,
        "dimension": dimension,
        "metric_values": metrics
        or {
            "M_evidence_grounding": {"value": 1.0, "state": "usable", "reason": None},
            "M_silent_gap": {"value": 0.0, "state": "usable", "reason": None},
        },
        "cell_score": cell_score,
        "contract_flags": flags or [],
        "commit_sha_set": ["abc"],
        "built_at": "2026-05-18T00:00:00+00:00",
    }


if __name__ == "__main__":
    unittest.main()
