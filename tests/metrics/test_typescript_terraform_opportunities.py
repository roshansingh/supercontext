from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from source.kg.build.pipeline import build_kg
from source.kg.core.repo_source import discover_repo
from source.kg.core.store import read_jsonl
from source.kg.file_formats.opportunities import TerraformDomainOpportunityDetector
from source.kg.languages.typescript.language import LANGUAGE_SUPPORT as TYPESCRIPT_SUPPORT
from source.kg.languages.typescript.opportunities import TypeScriptHttpClientOpportunityDetector
from source.kg.metrics import compute_all


class TypeScriptTerraformOpportunityTest(unittest.TestCase):
    def test_typescript_language_exposes_http_client_opportunity_detector(self) -> None:
        detectors = TYPESCRIPT_SUPPORT.opportunity_detectors()

        self.assertEqual([type(detector).__name__ for detector in detectors], ["TypeScriptHttpClientOpportunityDetector"])

    def test_typescript_detector_reuses_parser_client_endpoint_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}\n', encoding="utf-8")
            (root / "client.ts").write_text(
                "import axios from 'axios';\n"
                "const api = axios.create({ baseURL: 'https://api.example.com' });\n"
                "fetch('/health');\n"
                "api.post('/orders');\n"
                "axios.request({ url: '/users', method: 'put' });\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = TypeScriptHttpClientOpportunityDetector().detect(repo)

        self.assertEqual([row.predicate for row in opportunities], ["CALLS_ENDPOINT"] * 3)
        self.assertEqual([row.source_kind for row in opportunities], ["fetch_call", "axios_call", "axios_call"])
        self.assertEqual([row.language_or_format for row in opportunities], ["typescript"] * 3)
        self.assertEqual([row.line for row in opportunities], [3, 4, 5])

    def test_typescript_detector_skips_parser_when_repo_has_no_typescript_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
            repo = discover_repo(root)

            with mock.patch(
                "source.kg.languages.typescript.opportunities.http_client.parse_typescript_repo",
                side_effect=AssertionError("parser should not run"),
            ):
                opportunities = TypeScriptHttpClientOpportunityDetector().detect(repo)

        self.assertEqual(opportunities, ())

    def test_typescript_detector_propagates_parser_failures_for_loud_metrics_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "client.ts").write_text("fetch('/health');\n", encoding="utf-8")
            repo = discover_repo(root)

            with mock.patch(
                "source.kg.languages.typescript.opportunities.http_client.parse_typescript_repo",
                side_effect=RuntimeError("parser failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "parser failed"):
                    TypeScriptHttpClientOpportunityDetector().detect(repo)

    def test_typescript_detector_labels_javascript_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}\n', encoding="utf-8")
            (root / "client.js").write_text("fetch('/health');\n", encoding="utf-8")
            repo = discover_repo(root)

            opportunities = TypeScriptHttpClientOpportunityDetector().detect(repo)

        self.assertEqual([row.language_or_format for row in opportunities], ["javascript"])

    def test_typescript_detector_filters_unresolved_imported_client_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}\n', encoding="utf-8")
            src = root / "src"
            src.mkdir()
            (src / "api.ts").write_text(
                "import axios from 'axios';\n"
                "const client = axios.create({ baseURL: 'http://localhost:3000' });\n"
                "export default client;\n",
                encoding="utf-8",
            )
            (src / "notClient.ts").write_text("export const value = 1;\n", encoding="utf-8")
            (src / "auth.ts").write_text(
                "import api from './api';\n"
                "import missing from './notClient';\n"
                "import externalApi from 'external-api';\n"
                "api.get('/safe');\n"
                "missing.get('/missing');\n"
                "externalApi.get('/external');\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = TypeScriptHttpClientOpportunityDetector().detect(repo)

        self.assertEqual([(row.path, row.line) for row in opportunities], [("src/auth.ts", 4)])

    def test_typescript_external_call_is_explicit_coverage_not_silent_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}\n', encoding="utf-8")
            (repo / "client.ts").write_text(
                "import axios from 'axios';\n"
                "axios.get('https://external.example.com/orders');\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"

            build_kg(repo, snapshot)
            coverage = read_jsonl(snapshot / "coverage.jsonl")
            cell = compute_all(snapshot, expected_repos=1)[0]

        self.assertTrue(
            any(
                row.get("predicate") == "CALLS_ENDPOINT"
                and row.get("scope_ref", {}).get("reason") == "external_endpoint_suppressed"
                and row.get("scope_ref", {}).get("file_path") == "client.ts"
                and row.get("scope_ref", {}).get("line") == 2
                for row in coverage
            )
        )
        self.assertEqual(cell.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(cell.metric_values["M_silent_gap"].value, 0.0)

    def test_typescript_resolved_call_fact_covers_detected_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}\n', encoding="utf-8")
            (repo / "client.ts").write_text(
                "import axios from 'axios';\n"
                "axios.post('/orders');\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"

            build_kg(repo, snapshot)
            cell = compute_all(snapshot, expected_repos=1)[0]

        self.assertEqual(cell.metric_values["M_extractor_opportunity"].value, 1.0)
        self.assertEqual(cell.metric_values["M_silent_gap"].value, 0.0)

    def test_terraform_detector_reports_domain_reference_opportunities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.tf").write_text(
                'resource "aws_route53_record" "api" {\n'
                '  name = "api.example.com"\n'
                "}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = TerraformDomainOpportunityDetector().detect(repo)

        self.assertEqual([row.predicate for row in opportunities], ["REFERENCES_DOMAIN"])
        self.assertEqual([row.source_kind for row in opportunities], ["terraform_literal"])
        self.assertEqual([row.language_or_format for row in opportunities], ["terraform"])
        self.assertEqual([row.path for row in opportunities], ["main.tf"])
        self.assertEqual([row.line for row in opportunities], [2])

    def test_terraform_detector_does_not_read_non_terraform_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config.json").write_text('{"domain":"api.example.com"}\n', encoding="utf-8")
            repo = discover_repo(root)

            with mock.patch(
                "source.kg.file_formats.opportunities.terraform_domain.Path.read_text",
                side_effect=AssertionError("non-Terraform file read"),
            ):
                opportunities = TerraformDomainOpportunityDetector().detect(repo)

        self.assertEqual(opportunities, ())

    def test_terraform_domain_reference_fact_covers_detected_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "main.tf").write_text(
                'resource "aws_route53_record" "api" {\n'
                '  name = "api.example.com"\n'
                "}\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot"

            build_kg(repo, snapshot)
            cell = compute_all(snapshot, expected_repos=1)[0]

        self.assertEqual(cell.metric_values["M_extractor_opportunity"].value, 1.0)
        self.assertEqual(cell.metric_values["M_silent_gap"].value, 0.0)


if __name__ == "__main__":
    unittest.main()
