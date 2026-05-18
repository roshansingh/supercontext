from __future__ import annotations

import builtins
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.build.pipeline import extract_repo
from source.kg.core.models import Coverage, Entity, Fact
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.files import TYPESCRIPT_EXTENSIONS
from source.kg.core.store import JsonlKgStore
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
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
        self.assertEqual(_source_kinds_by_path(routes)["/health"], {"flask_get"})

    def test_legacy_javascript_regexes_do_not_run_on_py_source_files(self) -> None:
        build = _extract_config(
            {
                "app.py": (
                    "from flask import Flask\n\n"
                    "app = Flask(__name__)\n\n"
                    "@app.get('/health')\n"
                    "def health():\n"
                    "    return 'ok'\n"
                )
            }
        )

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(_source_kinds_by_path(routes)["/health"], {"flask_get"})

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

    def test_serverless_yaml_is_parsed_with_safe_load(self) -> None:
        build = _extract_config(
            {
                "serverless.yml": (
                    "functions:\n"
                    "  websocket:\n"
                    "    handler: app.ws\n"
                    "    events:\n"
                    "      - websocket:\n"
                    "          route: $connect\n"
                    "  api:\n"
                    "    handler: app.http\n"
                    "    events:\n"
                    "      - http:\n"
                    "          path: /orders\n"
                    "          method: post\n"
                    "      - httpApi:\n"
                    "          path: /reply\n"
                    "          method: post\n"
                    "      - http: GET /short\n"
                )
            }
        )

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")
        events = _endpoint_rows(build, "CONSUMES_EVENT")

        self.assertEqual(
            _methods_by_path(routes),
            {"/$connect": {"ANY"}, "/orders": {"POST"}, "/reply": {"POST"}, "/short": {"GET"}},
        )
        self.assertEqual(_source_kinds_by_path(routes)["/$connect"], {"serverless_route"})
        self.assertEqual(_channel_addresses(events), {"$connect"})
        self.assertEqual(_fact_lines_by_path(build, "EXPOSES_ENDPOINT", "/orders"), [12])
        self.assertEqual(_fact_lines_by_path(build, "EXPOSES_ENDPOINT", "/reply"), [15])
        self.assertEqual(_fact_lines_by_path(build, "EXPOSES_ENDPOINT", "/short"), [16])

    def test_serverless_yaml_variant_filename_is_parsed(self) -> None:
        build = _extract_config(
            {
                "serverless.dev.yml": (
                    "functions:\n"
                    "  api:\n"
                    "    handler: app.http\n"
                    "    events:\n"
                    "      - httpApi:\n"
                    "          path: /dev-orders\n"
                    "          method: get\n"
                )
            }
        )

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(_methods_by_path(routes), {"/dev-orders": {"GET"}})

    def test_serverless_yaml_parse_error_emits_coverage_for_serverless_filename(self) -> None:
        build = _extract_config({"serverless.yml": "functions: [not valid yaml\n"})

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "EXPOSES_ENDPOINT" and row.scope_ref.get("reason") == "serverless_yaml_parse_error"
        ]

        self.assertEqual(len(coverage), 1)

    def test_pyyaml_unavailable_emits_coverage_for_serverless_filename(self) -> None:
        real_import = builtins.__import__

        def import_without_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("blocked by test")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_yaml):
            build = _extract_config({"serverless.yml": "functions:\n  api:\n    events:\n      - http: GET /orders\n"})

        coverage = [
            row
            for row in build.coverage
            if row.predicate == "EXPOSES_ENDPOINT" and row.scope_ref.get("reason") == "pyyaml_unavailable"
        ]

        self.assertEqual(len(coverage), 1)

    def test_non_openapi_file_with_openapi_word_does_not_emit_coverage(self) -> None:
        build = _extract_config({"fixture.json": '{"description": "mentions openapi", "paths": "not an object"}'})

        docs = _endpoint_rows(build, "DOCUMENTS_ENDPOINT")
        coverage = [row for row in build.coverage if row.predicate == "DOCUMENTS_ENDPOINT"]

        self.assertEqual(docs, [])
        self.assertEqual(coverage, [])

    def test_json_with_paths_but_no_openapi_version_is_not_documented_endpoint(self) -> None:
        build = _extract_config({"fixture.json": '{"paths": {"/v1/foo": {"get": {}}}}'})

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
        self.assertEqual(coverage[0].scope_ref["file_path"], "bad_app.py")

    def test_static_config_does_not_use_javascript_endpoint_regexes(self) -> None:
        build = _extract_config({"server.ts": "app.post('/orders', handler)\nfetch('/orders')\n"})

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")
        client_calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        coverage_reasons = {
            (row.predicate, row.scope_ref.get("reason"))
            for row in build.coverage
            if row.scope_ref.get("language") == "javascript/typescript"
        }

        self.assertEqual(routes, [])
        self.assertEqual(client_calls, [])
        self.assertEqual(
            coverage_reasons,
            {
                ("EXPOSES_ENDPOINT", "parser_backed_js_ts_route_extraction_partial_express_fastify_koa_only"),
                ("CALLS_ENDPOINT", "parser_backed_js_ts_client_endpoint_extraction_partial_fetch_axios_only"),
            },
        )

    def test_typescript_express_routes_are_parser_backed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "server.ts"
            source_path.write_text(
                "import express from 'express';\n"
                "import { Router } from 'express';\n"
                "const app = express();\n"
                "const router = Router();\n"
                "app.post('/123', handler);\n"
                "router.get('/orders/:id', handler);\n"
                "app.route('/batch').delete(handler);\n"
                "const cjsApp = require('express')();\n"
                "cjsApp.put('/inline-cjs', handler);\n"
                "app.use('/mounted', router);\n"
                "function handler() { return undefined; }\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="express-api",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(
            _methods_by_path(routes),
            {"/123": {"POST"}, "/orders/:id": {"GET"}, "/batch": {"DELETE"}, "/inline-cjs": {"PUT"}},
        )
        self.assertEqual(_source_kinds_by_path(routes)["/123"], {"express_post"})
        self.assertNotIn("/mounted", _methods_by_path(routes))

    def test_typescript_fastify_and_koa_routes_are_parser_backed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "server.ts"
            source_path.write_text(
                "import { fastify as makeFastify } from 'fastify';\n"
                "import { Router } from '@koa/router';\n"
                "import * as LegacyRouter from 'koa-router';\n"
                "const app = makeFastify();\n"
                "const router = new Router();\n"
                "const legacyRouter = new LegacyRouter();\n"
                "app.get('/health', handler);\n"
                "app.route({ method: 'POST', url: '/orders', handler });\n"
                "app.route({ method: 'PATCH', path: '/orders/:id', handler });\n"
                "app.route({ url: '/all-methods', handler });\n"
                "router.put('/users/:id', handler);\n"
                "router.del('/old-users/:id', handler);\n"
                "legacyRouter.delete('/legacy-users/:id', handler);\n"
                "const computed = '/skip';\n"
                "const method = 'GET';\n"
                "app.post(computed, handler);\n"
                "app.route({ method, url: '/skip-method', handler });\n"
                "app.route({ method: ['GET', 'POST'], url: '/skip-array-method', handler });\n"
                "app.route({ ...{ method: 'GET' }, url: '/skip-spread-method', handler });\n"
                "app.route({ ['method']: method, url: '/skip-computed-method', handler });\n"
                "router.get(`/skip/${id}`, handler);\n"
                "function handler() { return undefined; }\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="node-api",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(
            _methods_by_path(routes),
            {
                "/all-methods": {"ANY"},
                "/health": {"GET"},
                "/legacy-users/:id": {"DELETE"},
                "/old-users/:id": {"DELETE"},
                "/orders": {"POST"},
                "/orders/:id": {"PATCH"},
                "/users/:id": {"PUT"},
            },
        )
        self.assertEqual(_source_kinds_by_path(routes)["/health"], {"fastify_get"})
        self.assertEqual(_source_kinds_by_path(routes)["/orders"], {"fastify_route"})
        self.assertEqual(_source_kinds_by_path(routes)["/old-users/:id"], {"koa_delete"})
        self.assertEqual(_source_kinds_by_path(routes)["/users/:id"], {"koa_put"})
        self.assertNotIn("/skip", _methods_by_path(routes))
        self.assertNotIn("/skip-method", _methods_by_path(routes))
        self.assertNotIn("/skip-array-method", _methods_by_path(routes))
        self.assertNotIn("/skip-spread-method", _methods_by_path(routes))
        self.assertNotIn("/skip-computed-method", _methods_by_path(routes))

    def test_typescript_fastify_and_koa_require_receivers_are_parser_backed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "server.cjs"
            source_path.write_text(
                "const fastify = require('fastify');\n"
                "const Router = require('koa-router');\n"
                "const app = fastify();\n"
                "const router = Router();\n"
                "app.delete('/sessions', handler);\n"
                "router.patch('/profiles/:id', handler);\n"
                "function handler() { return undefined; }\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="node-cjs-api",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        routes = _endpoint_rows(build, "EXPOSES_ENDPOINT")

        self.assertEqual(_methods_by_path(routes), {"/sessions": {"DELETE"}, "/profiles/:id": {"PATCH"}})

    def test_typescript_client_calls_are_parser_backed_for_fetch_and_axios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "client.ts"
            source_path.write_text(
                "import axios from 'axios';\n"
                "const api = axios.create();\n"
                "fetch('/api/orders', { method: 'POST' });\n"
                "fetch(`/api/orders/${orderId}`);\n"
                "axios.get('/api/profile');\n"
                "api.patch('/api/profile');\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="web-client",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/orders": {"POST"},
                "/api/profile": {"GET", "PATCH"},
            },
        )
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"fetch_call"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/profile"], {"axios_call"})
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["target_dynamic_template_segment"],
            1,
        )

    def test_fetch_with_unresolved_method_keeps_any_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "client.ts"
            source_path.write_text(
                "const methodName = 'POST';\n"
                "fetch('/api/orders', { method: methodName });\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="web-client",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"ANY"}})

    def test_typescript_client_calls_resolve_constants_concat_and_axios_config_shapes(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const ORDERS = '/api/orders';\n"
            "const BASE = '/api/v1';\n"
            "const api = axios.create({ baseURL: 'http://localhost:3000' });\n"
            "axios.get(ORDERS);\n"
            "fetch(BASE + '/profiles');\n"
            "fetch(`${BASE}/reports`);\n"
            "axios('/api/shorthand');\n"
            "axios({ method: 'post', url: '/api/direct' });\n"
            "axios.request({ method: 'delete', url: '/api/request' });\n"
            "api('/api/client-shorthand');\n"
            "api.patch('/api/profile');\n"
            "const wrapper = (() => {\n"
            "  const nested = axios.create({ baseURL: 'http://localhost:3000' });\n"
            "  nested.get('/api/nested');\n"
            "  return nested;\n"
            "})();\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/orders": {"GET"},
                "/api/v1/profiles": {"ANY"},
                "/api/v1/reports": {"ANY"},
                "/api/shorthand": {"GET"},
                "/api/direct": {"POST"},
                "/api/request": {"DELETE"},
                "/api/client-shorthand": {"GET"},
                "/api/profile": {"PATCH"},
                "/api/nested": {"GET"},
            },
        )
        self.assertEqual(_hosts_by_path(calls)["/api/profile"], {"localhost"})
        self.assertEqual(_hosts_by_path(calls)["/api/client-shorthand"], {"localhost"})
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")[
                "parser_backed_js_ts_client_endpoint_extraction_partial_fetch_axios_only"
            ],
            1,
        )
        qualifiers_by_path = _qualifiers_by_path(calls)
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["resolution_kind"], "local_var")
        self.assertEqual(qualifiers_by_path["/api/v1/profiles"][0]["resolution_kind"], "concat")
        self.assertEqual(qualifiers_by_path["/api/v1/reports"][0]["resolution_kind"], "template")
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_calls_emit_env_host_confidence_and_coverage(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: process.env.API_HOST });\n"
            "api.get('/api/orders');\n"
            "fetch(`${process.env.API_HOST}/api/users`);\n"
            "fetch(import.meta.env['VITE_API_HOST'] + '/api/config');\n"
            "fetch(process.env['ALT_API_HOST'] + '/api/alt');\n"
            "fetch(process.env.PORTED_API_HOST + ':8080/api/ported');\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {"/api/orders": {"GET"}, "/api/users": {"ANY"}, "/api/config": {"ANY"}, "/api/alt": {"ANY"}},
        )
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"${env:API_HOST}"})
        self.assertEqual(_hosts_by_path(calls)["/api/users"], {"${env:API_HOST}"})
        self.assertEqual(_hosts_by_path(calls)["/api/config"], {"${env:VITE_API_HOST}"})
        self.assertEqual(_hosts_by_path(calls)["/api/alt"], {"${env:ALT_API_HOST}"})
        self.assertEqual(
            {path: rows[0]["confidence"] for path, rows in qualifiers_by_path.items()},
            {
                "/api/orders": "host_unresolved_path_resolved",
                "/api/users": "host_unresolved_path_resolved",
                "/api/config": "host_unresolved_path_resolved",
                "/api/alt": "host_unresolved_path_resolved",
            },
        )
        self.assertEqual(
            {path: rows[0]["host_resolution_kind"] for path, rows in qualifiers_by_path.items()},
            {
                "/api/orders": "env_backed_unresolved",
                "/api/users": "env_backed_unresolved",
                "/api/config": "env_backed_unresolved",
                "/api/alt": "env_backed_unresolved",
            },
        )
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 4)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 1)

    def test_typescript_client_dynamic_template_segment_fails_closed(self) -> None:
        build = _extract_typescript_client(
            "const userId = getUserId();\n"
            "fetch(`/api/users/${userId}`);\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["target_dynamic_template_segment"],
            1,
        )
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("unresolved_target", 0), 0)

    def test_typescript_client_static_template_segment_still_resolves(self) -> None:
        build = _extract_typescript_client(
            "const resource = 'users';\n"
            "fetch(`/api/${resource}`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/users": {"ANY"}})
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_local_url_variable_flow_resolves_source_order(self) -> None:
        build = _extract_typescript_client(
            "function load() {\n"
            "  const url = '/api/local';\n"
            "  fetch(url);\n"
            "  fetch(later);\n"
            "  const later = '/api/later';\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/local": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/local"][0]["resolution_kind"], "local_var")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

    def test_typescript_client_nearest_block_local_overrides_parameter_shadow(self) -> None:
        build = _extract_typescript_client(
            "function load(url) {\n"
            "  {\n"
            "    const url = '/api/local';\n"
            "    fetch(url);\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/local": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/local"][0]["resolution_kind"], "local_var")
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_switch_case_local_url_resolves_source_order(self) -> None:
        build = _extract_typescript_client(
            "function load(kind) {\n"
            "  switch (kind) {\n"
            "    case 'users':\n"
            "      const url = '/api/case';\n"
            "      fetch(url);\n"
            "      break;\n"
            "    default:\n"
            "      const fallback = '/api/default';\n"
            "      fetch(fallback);\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/case": {"ANY"}, "/api/default": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/case"][0]["resolution_kind"], "local_var")
        self.assertEqual(qualifiers_by_path["/api/default"][0]["resolution_kind"], "local_var")
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_local_url_reassignment_is_source_ordered(self) -> None:
        build = _extract_typescript_client(
            "function load() {\n"
            "  let url = '/api/first';\n"
            "  url = '/api/second';\n"
            "  fetch(url);\n"
            "  let beforeMutation = '/api/before';\n"
            "  fetch(beforeMutation);\n"
            "  beforeMutation = '/api/after';\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/before": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/before"][0]["resolution_kind"], "local_var")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_reassigned_binding"], 1)

    def test_typescript_client_prior_control_flow_mutation_fails_closed(self) -> None:
        build = _extract_typescript_client(
            "function load(flag) {\n"
            "  let url = '/api/first';\n"
            "  if (flag) url = '/api/second';\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_reassigned_binding"], 1)

    def test_typescript_client_destructuring_and_update_mutations_fail_closed(self) -> None:
        build = _extract_typescript_client(
            "function load(config) {\n"
            "  let destructured = '/api/destructured';\n"
            "  ({ destructured } = config);\n"
            "  fetch(destructured);\n"
            "  let updated = '/api/updated';\n"
            "  updated++;\n"
            "  fetch(updated);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_reassigned_binding"], 2)

    def test_typescript_client_same_statement_later_declarator_mutation_fails_closed(self) -> None:
        build = _extract_typescript_client(
            "function load() {\n"
            "  let url = '/api/first', other = (url = '/api/second');\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_reassigned_binding"], 1)

    def test_typescript_client_local_helper_initializer_preserves_deferred_reason(self) -> None:
        build = _extract_typescript_client(
            "function load() {\n"
            "  const url = getUrl('/api/helper');\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"],
            1,
        )
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("unresolved_target", 0), 0)

    def test_typescript_client_function_body_does_not_use_mutated_module_binding(self) -> None:
        build = _extract_typescript_client(
            "let url = '/api/before';\n"
            "function load() {\n"
            "  fetch(url);\n"
            "}\n"
            "url = '/api/after';\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 1)

    def test_typescript_client_function_body_does_not_use_module_binding_mutated_in_declarator(self) -> None:
        build = _extract_typescript_client(
            "let url = '/api/before';\n"
            "const other = (url = '/api/after');\n"
            "function load() {\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 1)

    def test_typescript_client_function_body_resolves_stable_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "function load() {\n"
            "  fetch(url);\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/module": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/module"][0]["resolution_kind"], "module_var")
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_for_loop_variable_shadows_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/outer';\n"
            "for (const url of urls) {\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

    def test_typescript_client_outer_function_parameter_does_not_shadow_inner_reference(self) -> None:
        build = _extract_typescript_client(
            "function outer(url) {\n"
            "  function inner() {\n"
            "    fetch(url);\n"
            "  }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("target_shadowed_binding", 0), 0)

    def test_typescript_client_constructor_parameter_shadows_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "class Api {\n"
            "  constructor(url) {\n"
            "    fetch(url);\n"
            "  }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

    def test_typescript_client_accessor_parameter_shadows_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "class Api {\n"
            "  set endpoint(url) {\n"
            "    fetch(url);\n"
            "  }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

    def test_typescript_client_catch_binding_shadows_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "try {\n"
            "  risky();\n"
            "} catch (url) {\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

    def test_typescript_client_function_and_class_declarations_shadow_module_binding(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "function withFunctionShadow() {\n"
            "  function url() {}\n"
            "  fetch(url);\n"
            "}\n"
            "function withClassShadow() {\n"
            "  class url {}\n"
            "  fetch(url);\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 2)

    def test_typescript_client_helper_call_target_is_classified_as_deferred(self) -> None:
        build = _extract_typescript_client(
            "function getUrl(path) { return path; }\n"
            "fetch(getUrl('/api/helper'));\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"],
            1,
        )

    def test_typescript_client_with_block_fails_closed(self) -> None:
        build = _extract_typescript_client("with (obj) { fetch(path); }\n")

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["with_block_present"], 1)

    def test_typescript_client_calls_emit_coverage_for_unresolved_external_and_shadowed_targets(self) -> None:
        build = _extract_typescript_client(
            "const P = '/api/orders';\n"
            "function shadowed(P) { fetch(P); }\n"
            "let R = '/api/first';\n"
            "R = '/api/second';\n"
            "fetch(R);\n"
            "let S = '/api/base';\n"
            "S += '/suffix';\n"
            "fetch(S);\n"
            "fetch(process.env.API_HOST + process.env.STAGE + '/api/orders');\n"
            "fetch(process.env.API_HOST + 'tenant/api/orders');\n"
            "fetch(makeTarget());\n"
            "fetch('https://thirdparty.example.com/api/x');\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_reassigned_binding"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["external_endpoint_suppressed"], 1)

    def test_typescript_imported_default_axios_client_calls_are_resolved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api/axiosConfig.tsx": (
                    "import axios from 'axios';\n"
                    "const shopagainAxios = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "export default shopagainAxios;\n"
                ),
                "src/api/login.api.tsx": (
                    "import shopagainAxios from './axiosConfig';\n"
                    "export function login() {\n"
                    "  return shopagainAxios.post('/api/token/', {});\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/token/": {"POST"}})
        self.assertEqual(_source_kinds_by_path(calls)["/api/token/"], {"imported_axios_call"})
        self.assertEqual(_hosts_by_path(calls)["/api/token/"], {"${env:VITE_API_ROOT}"})
        self.assertEqual(qualifiers_by_path["/api/token/"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/api/token/"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)
        self.assertEqual(_fact_lines_by_path(build, "CALLS_ENDPOINT", "/api/token/"), [3])

    def test_typescript_imported_default_axios_client_setter_parameter_shadows_receiver(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api/axiosConfig.tsx": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: '/api' });\n"
                ),
                "src/users.ts": (
                    "import api from './api/axiosConfig';\n"
                    "class Users {\n"
                    "  set endpoint(api) {\n"
                    "    api.get('/users');\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_imported_axios_client_dynamic_template_reason_is_preserved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api/axiosConfig.tsx": (
                    "import axios from 'axios';\n"
                    "const shopagainAxios = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "export default shopagainAxios;\n"
                ),
                "src/api/login.api.tsx": (
                    "import shopagainAxios from './axiosConfig';\n"
                    "const userId = getUserId();\n"
                    "shopagainAxios.get(`/api/users/${userId}`);\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["target_dynamic_template_segment"],
            1,
        )
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("unresolved_target", 0), 0)

    def test_typescript_imported_named_axios_client_uses_export_alias_and_base_path(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/http.ts": (
                    "import axios from 'axios';\n"
                    "const baseClient = axios.create({ baseURL: 'http://localhost:3000/api' });\n"
                    "export { baseClient as http };\n"
                ),
                "src/orders.ts": (
                    "import { http } from './http';\n"
                    "export function loadOrders() {\n"
                    "  return http.get('orders/');\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders/"], {"localhost"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders/"], {"imported_axios_call"})
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_imported_env_base_url_composes_relative_path_without_leading_slash(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/services/api.js": (
                    "import axios from 'axios';\n"
                    "const httpClient = axios.create({ baseURL: process.env.REACT_APP_API_ROOT });\n"
                    "export default httpClient;\n"
                ),
                "src/services/auth.js": (
                    "import api from './api';\n"
                    "export function logout() {\n"
                    "  return api.post('auth/logout/', {});\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/auth/logout/": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/auth/logout/"], {"${env:REACT_APP_API_ROOT}"})
        self.assertEqual(qualifiers_by_path["/auth/logout/"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/auth/logout/"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)

    def test_typescript_imported_direct_config_call_without_literal_method_uses_any(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.js": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000' });\n"
                    "export default client;\n"
                ),
                "src/orders.js": (
                    "import api from './api';\n"
                    "api({ url: '/orders/', method: methodName });\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/orders/": {"ANY"}})
        self.assertEqual(_hosts_by_path(calls)["/orders/"], {"localhost"})

    def test_typescript_imported_config_call_uses_per_call_base_url_override(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.js": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000/api' });\n"
                    "export default client;\n"
                ),
                "src/orders.js": (
                    "import api from './api';\n"
                    "api.request({ baseURL: process.env.ALT_API_ROOT, url: 'orders/', method: 'post' });\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/orders/": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/orders/"], {"${env:ALT_API_ROOT}"})
        self.assertEqual(qualifiers_by_path["/orders/"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/orders/"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)

    def test_typescript_imported_default_axios_client_resolves_index_module(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api/index.js": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000' });\n"
                    "export default client;\n"
                ),
                "src/profile.js": (
                    "import api from './api';\n"
                    "api.patch('/profile/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/profile/": {"PATCH"}})
        self.assertEqual(_hosts_by_path(calls)["/profile/"], {"localhost"})

    def test_typescript_imported_default_axios_client_resolves_mjs_module(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.mjs": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000' });\n"
                    "export default client;\n"
                ),
                "src/orders.js": (
                    "import api from './api';\n"
                    "api.get('/orders/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/orders/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/orders/"], {"localhost"})

    def test_typescript_imported_default_axios_client_resolves_anonymous_default_create(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/users.js": (
                    "import api from './api';\n"
                    "api.get('/users/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/users/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/users/"], {"localhost"})

    def test_typescript_imported_default_axios_client_resolves_tsconfig_path_alias(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": (
                    "{\n"
                    "  // jsonc comments are valid in tsconfig files\n"
                    '  "compilerOptions": {\n'
                    '    "baseUrl": ".",\n'
                    '    "paths": {\n'
                    '      "@/*": ["src/*"],\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                "src/api.js": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000/api' });\n"
                    "export default client;\n"
                ),
                "src/users.js": (
                    "import api from '@/api';\n"
                    "api.get('users/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/users/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/users/"], {"localhost"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/users/"], {"imported_axios_call"})

    def test_typescript_path_alias_prefers_more_specific_pattern(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": (
                    "{\n"
                    '  "compilerOptions": {\n'
                    '    "paths": {\n'
                    '      "@/*": ["src/*"],\n'
                    '      "@/api/*": ["lib/api/*"]\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                "src/api/users.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000/wrong' });\n"
                ),
                "lib/api/users.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000/right' });\n"
                ),
                "src/consumer.js": (
                    "import api from '@/api/users';\n"
                    "api.get('profile/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/right/profile/": {"GET"}})
        self.assertNotIn("/wrong/profile/", _methods_by_path(calls))

    def test_typescript_path_alias_uses_jsconfig_base_url_and_fallback_targets(self) -> None:
        build = _extract_typescript_client_files(
            {
                "jsconfig.json": (
                    "\ufeff{\n"
                    '  "compilerOptions": {\n'
                    '    "baseUrl": "app",\n'
                    '    "paths": {\n'
                    '      "~/*": ["missing/*", "clients/*",],\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                "app/clients/http.mts": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000/app' });\n"
                ),
                "app/consumer.js": (
                    "import api from '~/http';\n"
                    "api.get('status/');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/app/status/": {"GET"}})

    def test_typescript_exact_path_alias_does_not_apply_wildcard_target(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": (
                    "{\n"
                    '  "compilerOptions": {\n'
                    '    "paths": {\n'
                    '      "api": ["src/*"]\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                "src/index.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/users.js": (
                    "import api from 'api';\n"
                    "api.get('/users/');\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])

    def test_typescript_path_alias_target_with_multiple_wildcards_fails_closed(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": (
                    "{\n"
                    '  "compilerOptions": {\n'
                    '    "paths": {\n'
                    '      "@/*": ["src/*/*"]\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
                "src/api/api.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/users.js": (
                    "import api from '@/api';\n"
                    "api.get('/users/');\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])

    def test_typescript_malformed_path_alias_config_fails_closed(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": "{ invalid json",
                "src/api.js": (
                    "import axios from 'axios';\n"
                    "export default axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/users.js": (
                    "import api from '@/api';\n"
                    "api.get('/users/');\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_imported_client_calls_fail_closed_for_bare_packages_missing_exports_and_shadowing(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.ts": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: 'http://localhost:3000' });\n"
                    "export default client;\n"
                ),
                "src/notClient.ts": "export const value = 1;\n",
                "src/auth.ts": (
                    "import api from './api';\n"
                    "import missing from './notClient';\n"
                    "import externalApi from 'external-api';\n"
                    "function shadowed(api) { return api.get('/shadowed'); }\n"
                    "api.get('/safe');\n"
                    "api.get(makeTarget());\n"
                    "missing.get('/missing');\n"
                    "externalApi.get('/external');\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/safe": {"GET"}})
        self.assertNotIn("/shadowed", _methods_by_path(calls))
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_non_express_javascript_routes_are_not_extracted_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "server.ts"
            source_path.write_text(
                "const app = createApp();\n"
                "app.post('/orders', handler);\n"
                "function handler() { return undefined; }\n",
                encoding="utf-8",
            )
            repo = RepoSnapshot(
                root=root,
                name="not-express",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = extract_repo(repo)

        self.assertEqual(_endpoint_rows(build, "EXPOSES_ENDPOINT"), [])
        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])

    def test_domain_references_include_env_var_consumer_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env.production").write_text("VITE_API_ROOT=https://api.example.com\n", encoding="utf-8")
            source_path = root / "src" / "api.ts"
            source_path.parent.mkdir()
            source_path.write_text("export const apiRoot = import.meta.env.VITE_API_ROOT;\n", encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="web",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (source_path,)},
            )
            build = StaticConfigExtractor().extract(repo)
            snapshot_dir = root / "kg"
            JsonlKgStore(snapshot_dir).write(
                entities=build.entities,
                facts=build.facts,
                evidence=build.evidence,
                coverage=build.coverage,
                manifest={},
            )

            result = KgSnapshot(snapshot_dir).domain_references("api.example.com", limit=20)

        env_usage = [
            row
            for row in result["references"]
            if row["predicate"] == "REFERENCES_ENV_VAR"
            and isinstance(row.get("qualifier"), dict)
            and row["qualifier"].get("reference_kind") == "code_access"
        ]
        self.assertEqual(len(env_usage), 1)
        self.assertEqual(env_usage[0]["evidence"][0]["bytes_ref"]["path"], "src/api.ts")

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

    def test_reconcile_endpoint_warning_coverage_is_not_filtered_by_endpoint_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[],
                facts=[],
                evidence=[],
                coverage=[
                    _coverage_row(
                        "EXPOSES_ENDPOINT",
                        "orders-api",
                        {"file_path": "bad_app.py", "reason": "python_syntax_error"},
                    )
                ],
                manifest={},
            )

            result = KgSnapshot(tmpdir).reconcile_endpoints(backend_scope=("orders-api",), path_prefix="/v1")

        self.assertEqual(result["coverage_warnings"][0]["coverage"][0]["scope_ref"]["file_path"], "bad_app.py")

    def test_reconcile_endpoint_warning_prefix_keeps_trailing_slash_boundary(self) -> None:
        backend_service = _service_entity("orders-api")
        backend_endpoint = _endpoint_entity("orders-api", "POST", "/v1beta/orders")

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[backend_service, backend_endpoint],
                facts=[Fact("EXPOSES_ENDPOINT", backend_service.entity_id, backend_endpoint.entity_id)],
                evidence=[],
                coverage=[],
                manifest={},
            )

            result = KgSnapshot(tmpdir).reconcile_endpoints(backend_scope=("orders-api",), path_prefix="/v1/")

        self.assertEqual(result["coverage_warnings"][0]["scope"], "backend")


def _extract_config(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for relative_path, text in files.items():
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name=root.name,
            owner=root.parent.name,
            commit_sha="test-sha",
            files_by_language={"python": (), "typescript": ()},
        )
        return StaticConfigExtractor().extract(repo)


def _extract_typescript_client(source: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_path = root / "client.ts"
        source_path.write_text(source, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name="web-client",
            owner="test",
            commit_sha="test-sha",
            files_by_language={"python": (), "typescript": (source_path,)},
        )
        return extract_repo(repo)


def _extract_typescript_client_files(files: dict[str, str]):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_paths = []
        for relative_path, source in files.items():
            source_path = root / relative_path
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text(source, encoding="utf-8")
            if source_path.suffix in TYPESCRIPT_EXTENSIONS:
                source_paths.append(source_path)
        repo = RepoSnapshot(
            root=root,
            name="web-client",
            owner="test",
            commit_sha="test-sha",
            files_by_language={"python": (), "typescript": tuple(source_paths)},
        )
        return extract_repo(repo)


def _service_entity(repo: str) -> Entity:
    return Entity(kind="Service", identity={"tenant_id": "local-dev", "repo": repo, "namespace": "default", "slug": repo})


def _endpoint_entity(repo: str, method: str, path: str) -> Entity:
    return Entity(
        kind="Endpoint",
        identity={"tenant_id": "local-dev", "repo": repo, "protocol": "http", "method": method, "path": path, "host": None},
    )


def _coverage_row(predicate: str, repo: str, scope_ref: dict[str, object]) -> Coverage:
    return Coverage(
        tenant_id="local-dev",
        predicate=predicate,
        scope_ref={"repo": repo, **scope_ref},
        state="uninstrumented",
        source_system="test",
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


def _hosts_by_path(rows: list[tuple[object, object]]) -> dict[str, set[str | None]]:
    grouped: dict[str, set[str | None]] = {}
    for _, endpoint in rows:
        grouped.setdefault(endpoint.identity["path"], set()).add(endpoint.identity["host"])
    return grouped


def _qualifiers_by_path(rows: list[tuple[object, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for fact, endpoint in rows:
        grouped.setdefault(endpoint.identity["path"], []).append(fact.qualifier)
    return grouped


def _coverage_reason_counts(build, predicate: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in build.coverage:
        if row.predicate != predicate:
            continue
        reason = row.scope_ref.get("reason")
        if isinstance(reason, str):
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _call_site_coverage(build) -> list[Coverage]:
    call_site_reasons = {
        "external_endpoint_suppressed",
        "host_env_backed",
        "target_helper_call_deferred",
        "target_dynamic_template_segment",
        "target_reassigned_binding",
        "target_shadowed_binding",
        "unresolved_target",
        "with_block_present",
    }
    return [
        row
        for row in build.coverage
        if row.predicate == "CALLS_ENDPOINT" and row.scope_ref.get("reason") in call_site_reasons
    ]


def _channel_addresses(rows: list[tuple[object, object]]) -> set[str]:
    return {entity.identity["channel_address"] for _, entity in rows}


def _fact_lines_by_path(build, predicate: str, endpoint_path: str) -> list[int]:
    entities_by_id = {entity.entity_id: entity for entity in build.entities}
    fact_ids = [
        fact.fact_id
        for fact in build.facts
        if fact.predicate == predicate and entities_by_id[fact.object_id].identity["path"] == endpoint_path
    ]
    return sorted(
        evidence.bytes_ref["line_start"]
        for evidence in build.evidence
        if evidence.target_type == "fact" and evidence.target_id in fact_ids
    )


if __name__ == "__main__":
    unittest.main()
