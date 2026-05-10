from __future__ import annotations

import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.models import Entity, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import JsonlKgStore
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.query.snapshot import KgSnapshot


class EndpointExtractionTest(unittest.TestCase):
    def test_flask_ast_routes_emit_without_path_value_filtering(self) -> None:
        build = _extract_config(
            {
                "app.py": (
                    "from flask import Flask\n\n"
                    "app = Flask(__name__)\n\n"
                    "@app.route('/123', methods=['POST'])\n"
                    "def numeric_route():\n"
                    "    return 'ok'\n\n"
                    "@app.get('/health')\n"
                    "def health():\n"
                    "    return 'ok'\n\n"
                    "app.add_url_rule('/internal', 'internal', health, methods=['DELETE'])\n"
                )
            }
        )

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(_methods_by_path(routes), {"/123": {"POST"}, "/health": {"GET"}, "/internal": {"DELETE"}})
        self.assertEqual(_source_kinds_by_path(routes)["/123"], {"flask_route"})

    def test_django_ast_routes_emit_from_import_identity(self) -> None:
        build = _extract_config(
            {
                "urls.py": (
                    "from django.urls import path as url_path, re_path\n\n"
                    "urlpatterns = [\n"
                    "    url_path('orders/<int:order_id>/', view, name='orders'),\n"
                    "    re_path(r'^legacy/(?P<slug>[-a-z]+)/$', view),\n"
                    "]\n"
                )
            }
        )

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(_methods_by_path(routes), {"/orders/<int:order_id>/": {"ANY"}, "/^legacy/(?P<slug>[-a-z]+)/$": {"ANY"}})
        self.assertEqual(_source_kinds_by_path(routes)["/orders/<int:order_id>/"], {"django_path"})
        self.assertEqual(_source_kinds_by_path(routes)["/^legacy/(?P<slug>[-a-z]+)/$"], {"django_re_path"})

    def test_openapi_json_is_parsed_without_line_regexes(self) -> None:
        build = _extract_config(
            {
                "openapi.json": (
                    '{"openapi":"3.0.0","paths":{'
                    '"/v1/store_data":{"post":{"operationId":"storeData"}},'
                    '"/v1/orders":{"get":{"operationId":"listOrders"}}'
                    "}}"
                )
            }
        )

        docs = _endpoint_rows(build, "DOCUMENTS_ENDPOINT")

        self.assertEqual(_methods_by_path(docs), {"/v1/store_data": {"ANY", "POST"}, "/v1/orders": {"ANY", "GET"}})
        self.assertEqual(_source_kinds_by_path(docs)["/v1/store_data"], {"openapi_path", "openapi_method"})

    def test_openapi_yaml_is_parsed_with_safe_load(self) -> None:
        build = _extract_config(
            {
                "openapi.yaml": (
                    "openapi: 3.0.0\n"
                    "paths:\n"
                    "  /v1/foo:\n"
                    "    get:\n"
                    "      operationId: getFoo\n"
                )
            }
        )

        docs = _endpoint_rows(build, "DOCUMENTS_ENDPOINT")

        self.assertEqual(_methods_by_path(docs), {"/v1/foo": {"ANY", "GET"}})

    def test_openapi_yaml_parse_error_emits_coverage_for_openapi_filename(self) -> None:
        build = _extract_config({"openapi.yaml": "openapi: 3.0.0\npaths: [not valid yaml\n"})

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "DOCUMENTS_ENDPOINT" and row.scope_ref.get("reason") == "openapi_yaml_parse_error"
        ]

        self.assertEqual(len(coverage), 1)

    def test_pyyaml_unavailable_emits_coverage_for_openapi_filename(self) -> None:
        real_import = builtins.__import__

        def import_without_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("blocked by test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_yaml):
            build = _extract_config(
                {
                    "openapi.yaml": (
                        "openapi: 3.0.0\n"
                        "paths:\n"
                        "  /v1/foo:\n"
                        "    get:\n"
                        "      operationId: getFoo\n"
                    )
                }
            )

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "DOCUMENTS_ENDPOINT" and row.scope_ref.get("reason") == "pyyaml_unavailable"
        ]

        self.assertEqual(len(coverage), 1)

    def test_non_openapi_file_with_openapi_word_does_not_emit_coverage(self) -> None:
        build = _extract_config({"fixture.json": '{"description": "mentions openapi", "paths": "not an object"}'})

        docs = _endpoint_rows(build, "DOCUMENTS_ENDPOINT")
        coverage = [row for row in build.coverage if row.predicate == "DOCUMENTS_ENDPOINT"]

        self.assertEqual(docs, [])
        self.assertEqual(coverage, [])

    def test_python_repo_without_recognized_framework_emits_coverage(self) -> None:
        build = _extract_config({"worker.py": "def run():\n    return 1\n"})

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "EXPOSES_ENDPOINT" and row.scope_ref.get("reason") == "no_recognized_web_framework"
        ]

        self.assertEqual(len(coverage), 1)

    def test_python_syntax_error_emits_explicit_coverage(self) -> None:
        build = _extract_config({"bad_app.py": "def broken(:\n    return 1\n"})

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "EXPOSES_ENDPOINT" and row.scope_ref.get("reason") == "python_syntax_error"
        ]

        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0].scope_ref["path"], "bad_app.py")

    def test_javascript_endpoint_parser_gap_is_explicit_coverage(self) -> None:
        build = _extract_config({"server.ts": "app.post('/orders', handler)\nfetch('/orders')\n"})

        coverage_reasons = {
            (row.predicate, row.scope_ref.get("reason"))
            for row in build.coverage
            if row.scope_ref.get("language") == "javascript/typescript"
        }

        self.assertEqual(
            coverage_reasons,
            {
                ("EXPOSES_ENDPOINT", "parser_backed_js_ts_endpoint_extraction_deferred"),
                ("CALLS_ENDPOINT", "parser_backed_js_ts_endpoint_extraction_deferred"),
            },
        )

    def test_reconcile_endpoints_matches_docs_backend_and_client_by_path(self) -> None:
        docs_service = _service_entity("api-docs")
        backend_service = _service_entity("orders-api")
        client_service = _service_entity("web-app")
        docs_endpoint = _endpoint_entity("api-docs", "ANY", "/v1/orders")
        backend_endpoint = _endpoint_entity("orders-api", "POST", "/v1/orders")
        client_endpoint = _endpoint_entity("web-app", "POST", "/v1/orders")
        facts = [
            Fact("DOCUMENTS_ENDPOINT", docs_service.entity_id, docs_endpoint.entity_id),
            Fact("EXPOSES_ENDPOINT", backend_service.entity_id, backend_endpoint.entity_id),
            Fact("CALLS_ENDPOINT", client_service.entity_id, client_endpoint.entity_id),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[docs_service, backend_service, client_service, docs_endpoint, backend_endpoint, client_endpoint],
                facts=facts,
                evidence=[],
                coverage=[],
                manifest={},
            )

            result = KgSnapshot(tmpdir).reconcile_endpoints(
                docs_scope=("api-docs",),
                backend_scope=("orders-api",),
                client_scope=("web-app",),
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual([row["key"] for row in result["documented_AND_implemented"]], ["/v1/orders"])
        self.assertEqual([row["key"] for row in result["documented_AND_called"]], ["/v1/orders"])
        self.assertEqual(result["coverage_warnings"], [])

    def test_reconcile_endpoints_warns_when_docs_scope_has_no_documented_endpoints(self) -> None:
        backend_service = _service_entity("orders-api")
        backend_endpoint = _endpoint_entity("orders-api", "POST", "/v1/orders")

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[backend_service, backend_endpoint],
                facts=[Fact("EXPOSES_ENDPOINT", backend_service.entity_id, backend_endpoint.entity_id)],
                evidence=[],
                coverage=[],
                manifest={},
            )

            result = KgSnapshot(tmpdir).reconcile_endpoints(docs_scope=("api-docs",), backend_scope=("orders-api",))

        self.assertEqual(result["coverage_warnings"][0]["scope"], "docs")
        self.assertEqual(result["coverage_warnings"][0]["warning"], "no_endpoint_documentation_evidence")

    def test_reconcile_endpoint_warnings_honor_path_prefix(self) -> None:
        backend_service = _service_entity("orders-api")
        backend_endpoint = _endpoint_entity("orders-api", "POST", "/internal/health")

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[backend_service, backend_endpoint],
                facts=[Fact("EXPOSES_ENDPOINT", backend_service.entity_id, backend_endpoint.entity_id)],
                evidence=[],
                coverage=[],
                manifest={},
            )

            result = KgSnapshot(tmpdir).reconcile_endpoints(backend_scope=("orders-api",), path_prefix="/v1")

        self.assertEqual(result["coverage_warnings"][0]["scope"], "backend")
        self.assertEqual(result["coverage_warnings"][0]["warning"], "no_endpoint_extractor_matched")


def _extract_config(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for relative_path, text in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(root=root, name=root.name, owner=root.parent.name, commit_sha="test-sha", python_files=(), typescript_files=())
        return StaticConfigExtractor().extract(repo)


def _service_entity(repo: str) -> Entity:
    return Entity(kind="Service", identity={"tenant_id": "local-dev", "repo": repo, "namespace": "default", "slug": repo})


def _endpoint_entity(repo: str, method: str, path: str) -> Entity:
    return Entity(
        kind="Endpoint",
        identity={"tenant_id": "local-dev", "repo": repo, "protocol": "http", "method": method, "path": path, "host": None},
    )


def _endpoint_rows(build, predicate: str) -> list[tuple[object, object]]:
    entities_by_id = {entity.entity_id: entity for entity in build.entities}
    rows = []
    for fact in build.facts:
        if fact.predicate != predicate:
            continue
        endpoint = entities_by_id[fact.object_id]
        rows.append((fact, endpoint))
    return rows


def _methods_by_path(rows: list[tuple[object, object]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for _, endpoint in rows:
        grouped.setdefault(endpoint.identity["path"], set()).add(endpoint.identity["method"])
    return grouped


def _source_kinds_by_path(rows: list[tuple[object, object]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for fact, endpoint in rows:
        grouped.setdefault(endpoint.identity["path"], set()).add(fact.qualifier["source_kind"])
    return grouped


if __name__ == "__main__":
    unittest.main()
