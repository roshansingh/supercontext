from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from source.kg.build.pipeline import build_kg
from source.kg.core.models import Coverage, Entity, Evidence, Fact
from source.kg.core.repo_source import discover_repo
from source.kg.core.store import JsonlKgStore
from source.kg.languages.python.language import LANGUAGE_SUPPORT as PYTHON_SUPPORT
from source.kg.languages.python.opportunities import HttpClientOpportunityDetector
from source.kg.metrics import compute_all


class PythonHttpClientOpportunityTest(unittest.TestCase):
    def test_detector_finds_common_http_client_shapes_without_shadowed_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text(
                "import requests as rq\n"
                "from httpx import get as http_get, Client\n"
                "import aiohttp\n\n"
                "def shadowed(requests):\n"
                "    requests.get('https://shadowed.example')\n\n"
                "def call():\n"
                "    rq.post('https://example.com/orders')\n"
                "    http_get('/health')\n"
                "    client = Client()\n"
                "    client.get('/users')\n"
                "    with aiohttp.ClientSession() as session:\n"
                "        session.put('/events')\n"
                "    rq = object()\n"
                "    rq.get('/not-http-client')\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = HttpClientOpportunityDetector().detect(repo)

        self.assertEqual([row.predicate for row in opportunities], ["CALLS_ENDPOINT"] * 4)
        self.assertEqual([row.line for row in opportunities], [9, 10, 12, 14])
        self.assertEqual(
            [row.source_kind for row in opportunities],
            ["requests.post", "httpx.get", "httpx.client.get", "aiohttp.client.put"],
        )

    def test_python_language_exposes_http_client_opportunity_detector(self) -> None:
        detectors = PYTHON_SUPPORT.opportunity_detectors()

        self.assertEqual([type(detector).__name__ for detector in detectors], ["HttpClientOpportunityDetector"])

    def test_detector_finds_calls_inside_functions_nested_in_compound_statements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text(
                "import requests\n"
                "if True:\n"
                "    def fetch_if():\n"
                "        requests.get('/if')\n"
                "try:\n"
                "    def fetch_try():\n"
                "        requests.post('/try')\n"
                "except Exception:\n"
                "    pass\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = HttpClientOpportunityDetector().detect(repo)

        self.assertEqual([row.source_kind for row in opportunities], ["requests.get", "requests.post"])
        self.assertEqual([row.line for row in opportunities], [4, 7])

    def test_detector_respects_lambda_and_comprehension_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "app.py"
            app.write_text(
                "import requests\n"
                "def call(clients):\n"
                "    lambda_call = lambda requests: requests.get('/lambda')\n"
                "    [requests.get('/comprehension') for requests in clients]\n"
                "    requests.get('/real')\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            opportunities = HttpClientOpportunityDetector().detect(repo)

        self.assertEqual([row.source_kind for row in opportunities], ["requests.get"])
        self.assertEqual([row.line for row in opportunities], [5])

    def test_metrics_report_uncovered_http_client_opportunity_as_silent_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('https://example.com')\n", encoding="utf-8")
            snapshot = root / "snapshot"

            build_kg(repo, snapshot)
            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].state, "usable")
        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].state, "usable")
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 1.0)

    def test_metrics_count_fact_backed_http_client_opportunity_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            service = Entity("Service", {"tenant_id": "default", "namespace": "default", "repo": "repo", "slug": "repo"})
            endpoint = Entity(
                "Endpoint",
                {
                    "tenant_id": "default",
                    "repo": "repo",
                    "protocol": "http",
                    "method": "GET",
                    "path": "/health",
                    "host": None,
                },
            )
            fact = Fact("CALLS_ENDPOINT", service.entity_id, endpoint.entity_id)
            JsonlKgStore(snapshot).write(
                entities=[service, endpoint],
                facts=[fact],
                evidence=[
                    Evidence(
                        target_type="fact",
                        target_id=fact.fact_id,
                        derivation_class="deterministic_static",
                        source_system="test",
                        source_ref={"predicate": "CALLS_ENDPOINT"},
                        bytes_ref={
                            "repo": "repo",
                            "commit_sha": "working-tree",
                            "path": "app.py",
                            "line_start": 2,
                            "line_end": 2,
                        },
                    )
                ],
                coverage=[],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "owner": "acme",
                    "tenant_id": "default",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 1.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 0.0)

    def test_metrics_do_not_scan_opportunities_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text("[project]\nname = 'repo'\n", encoding="utf-8")
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            config = root / "metrics.yaml"
            config.write_text(
                "enabled_metrics:\n"
                "  - M_inventory\n"
                "freshness:\n"
                "  default_days: 365\n"
                "trust_weights: {}\n",
                encoding="utf-8",
            )
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
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

            with mock.patch.object(
                HttpClientOpportunityDetector,
                "detect",
                side_effect=AssertionError("opportunity detector should not run"),
            ):
                cells = compute_all(snapshot, expected_repos=1, config_path=config)

        self.assertEqual(tuple(cells[0].metric_values), ("M_inventory",))
        self.assertEqual(cells[0].metric_values["M_inventory"].state, "usable")

    def test_coverage_rows_from_other_repos_do_not_cover_http_client_opportunities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    Coverage(
                        tenant_id="default",
                        predicate="CALLS_ENDPOINT",
                        scope_ref={"repo": "other", "commit_sha": "working-tree", "path": "app.py", "line": 2},
                        state="uninstrumented",
                        source_system="test",
                    )
                ],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 1.0)

    def test_boolean_coverage_line_does_not_cover_http_client_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests; requests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    Coverage(
                        tenant_id="default",
                        predicate="CALLS_ENDPOINT",
                        scope_ref={"repo": "repo", "commit_sha": "working-tree", "path": "app.py", "line": True},
                        state="uninstrumented",
                        source_system="test",
                    )
                ],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 1.0)

    def test_repo_level_coverage_covers_http_client_opportunity_as_non_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    Coverage(
                        tenant_id="default",
                        predicate="CALLS_ENDPOINT",
                        scope_ref={"repo": "repo", "language": "python", "reason": "explicit_repo_level_coverage"},
                        state="uninstrumented",
                        source_system="test",
                    )
                ],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 0.0)

    def test_repo_level_coverage_from_other_language_does_not_cover_python_opportunity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    Coverage(
                        tenant_id="default",
                        predicate="CALLS_ENDPOINT",
                        scope_ref={
                            "repo": "repo",
                            "language": "javascript/typescript",
                            "reason": "explicit_repo_level_coverage",
                        },
                        state="partially_instrumented",
                        source_system="test",
                    )
                ],
                manifest={
                    "repo_path": str(repo),
                    "repo_name": "repo",
                    "commit_sha": "working-tree",
                    "built_at": "2026-05-17T00:00:00+00:00",
                    "counts": {"files_by_language": {"python": 1}},
                },
            )

            backend = _backend_cell(compute_all(snapshot, expected_repos=1))

        self.assertEqual(backend.metric_values["M_extractor_opportunity"].value, 0.0)
        self.assertEqual(backend.metric_values["M_silent_gap"].value, 1.0)

    def test_metrics_discover_repo_once_for_dimensions_and_opportunities(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'repo'\ndependencies = ['fastapi', 'requests']\n",
                encoding="utf-8",
            )
            (repo / "app.py").write_text("import requests\nrequests.get('/health')\n", encoding="utf-8")
            snapshot = root / "snapshot"
            JsonlKgStore(snapshot).write(
                entities=[],
                facts=[],
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

            with mock.patch("source.kg.metrics.compute.discover_repo", wraps=discover_repo) as mocked_discover:
                compute_all(snapshot, expected_repos=1)

        self.assertEqual(mocked_discover.call_count, 1)


def _backend_cell(cells):
    for cell in cells:
        if cell.dimension == "backend":
            return cell
    raise AssertionError(f"missing backend cell: {cells}")


if __name__ == "__main__":
    unittest.main()
