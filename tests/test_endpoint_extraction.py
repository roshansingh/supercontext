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
from source.kg.file_formats._shared.common import endpoint_path_shape_matches_prefix, normalize_endpoint_path_shape
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.product.contract_reconciliation import ContractReconciliationSpec, ContractSide, reconcile_contract
from source.kg.query.snapshot import KgSnapshot


class EndpointExtractionTest(unittest.TestCase):
    def test_endpoint_path_shape_normalizes_framework_route_params(self) -> None:
        self.assertEqual(normalize_endpoint_path_shape("/orders/:orderId"), "/orders/{param}")
        self.assertEqual(normalize_endpoint_path_shape("/orders/{orderId}"), "/orders/{param}")
        self.assertEqual(normalize_endpoint_path_shape("/orders/<int:order_id>/"), "/orders/{param}")
        self.assertEqual(normalize_endpoint_path_shape("/orders/{orderId:int}"), "/orders/{param}")
        self.assertEqual(normalize_endpoint_path_shape("/files/{*path}"), "/files/{param}")

    def test_endpoint_path_shape_keeps_composite_and_regex_segments(self) -> None:
        self.assertEqual(normalize_endpoint_path_shape("/files/:name.json"), "/files/:name.json")
        self.assertEqual(normalize_endpoint_path_shape("/^legacy/(?P<slug>[-a-z]+)/$"), "/^legacy/(?P<slug>[-a-z]+)/$")

    def test_endpoint_path_shape_prefix_matches_segment_boundaries(self) -> None:
        self.assertTrue(endpoint_path_shape_matches_prefix("/tenants/:tenantId/orders", "/tenants/{id}"))
        self.assertTrue(endpoint_path_shape_matches_prefix("/v1/orders", "/v1/"))
        self.assertFalse(endpoint_path_shape_matches_prefix("/v1beta/orders", "/v1/"))

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

    def test_serverless_yaml_event_sources_emit_consumers(self) -> None:
        build = _extract_config(
            {
                "serverless.yml": (
                    "functions:\n"
                    "  worker:\n"
                    "    handler: app.worker\n"
                    "    events:\n"
                    "      - sqs: arn:aws:sqs:us-east-1:123456789012:orders-created\n"
                    "      - sns:\n"
                    "          topicName: orders-topic\n"
                    "      - stream:\n"
                    "          arn: arn:aws:kinesis:us-east-1:123456789012:stream/orders-stream\n"
                    "      - stream:\n"
                    "          arn: arn:aws:dynamodb:us-east-1:123456789012:"
                    "table/orders-table/stream/2026-06-16T00:00:00.000\n"
                    "      - eventBridge:\n"
                    "          eventBus: arn:aws:events:us-east-1:123456789012:event-bus/orders-bus\n"
                    "      - sqs: ${self:custom.queueArn}\n"
                )
            }
        )

        events = _endpoint_rows(build, "CONSUMES_EVENT")
        source_kinds_by_channel = {
            entity.identity["channel_address"]: fact.qualifier["source_kind"]
            for fact, entity in events
            if fact.qualifier["source_kind"].startswith("serverless_")
        }

        self.assertEqual(
            source_kinds_by_channel,
            {
                "orders-created": "serverless_sqs_event",
                "orders-topic": "serverless_sns_event",
                "orders-stream": "serverless_stream_event",
                "orders-table": "serverless_stream_event",
                "orders-bus": "serverless_eventbridge_event",
            },
        )
        stream_properties = {
            entity.identity["channel_address"]: entity.properties
            for _, entity in events
            if entity.identity["broker_kind"] == "dynamodb_stream"
        }
        self.assertEqual(
            stream_properties["orders-table"]["stream_resource"],
            "table/orders-table/stream/2026-06-16T00:00:00.000",
        )

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

    def test_python_http_client_calls_are_ast_backed(self) -> None:
        build = _extract_python_client(
            "import os\n"
            "import requests as rq\n"
            "from httpx import Client, get as http_get\n"
            "import aiohttp\n\n"
            "API_PATH = '/api/orders'\n\n"
            "def call(user_id):\n"
            "    rq.post(API_PATH)\n"
            "    http_get(f'/api/users/{user_id}')\n"
            "    client = Client(base_url='https://user:token@service.example.com:8443/base')\n"
            "    client.patch('profiles')\n"
            "    with aiohttp.ClientSession(base_url=os.getenv('API_HOST')) as session:\n"
            "        session.put('/events')\n"
            "    rq.request('DELETE', '/api/old')\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/orders": {"POST"},
                "/api/users/{user_id}": {"GET"},
                "/base/profiles": {"PATCH"},
                "/events": {"PUT"},
                "/api/old": {"DELETE"},
            },
        )
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"requests.post"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/users/{user_id}"], {"httpx.get"})
        self.assertEqual(_source_kinds_by_path(calls)["/base/profiles"], {"httpx.client.patch"})
        self.assertEqual(_source_kinds_by_path(calls)["/events"], {"aiohttp.client.put"})
        self.assertEqual(_hosts_by_path(calls)["/base/profiles"], {"service.example.com:8443"})
        self.assertEqual(_hosts_by_path(calls)["/events"], {"${env:API_HOST}"})
        self.assertEqual(qualifiers_by_path["/api/users/{user_id}"][0]["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifiers_by_path["/api/users/{user_id}"][0]["route_params"], ["user_id"])
        self.assertEqual(qualifiers_by_path["/events"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["API_HOST"])
        self.assertEqual(_env_reference_qualifiers(build, "endpoint_env_host")[0]["raw_target"], "os.getenv('API_HOST')")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)

    def test_python_http_client_calls_fail_closed_for_dynamic_targets_and_methods(self) -> None:
        build = _extract_python_client(
            "import requests\n"
            "url = '/module-url'\n\n"
            "def call(url, method):\n"
            "    requests.get(url)\n"
            "    requests.request(method, '/api/orders')\n"
            "    requests.post(build_url())\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"ANY"}})
        self.assertNotIn("/module-url", _methods_by_path(calls))
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_python_http_client_external_urls_are_suppressed_not_promoted(self) -> None:
        build = _extract_python_client("import requests\nrequests.get('https://user:token@api.example.com/v1/charges')\n")

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["external_endpoint_suppressed"], 1)

    def test_python_http_client_env_url_without_path_keeps_env_reference(self) -> None:
        build = _extract_python_client("import os\nimport requests\nrequests.get(os.getenv('SERVICE_URL'))\n")

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["SERVICE_URL"])

    def test_python_http_client_env_detection_respects_imports_and_shadowing(self) -> None:
        alias_build = _extract_python_client(
            "import os as operating_system\n"
            "import requests\n"
            "requests.get(operating_system.getenv('SERVICE_URL'))\n"
        )
        shadowed_build = _extract_python_client(
            "import requests\n\n"
            "def call(os):\n"
            "    requests.get(os.getenv('SERVICE_URL'))\n"
        )
        unimported_build = _extract_python_client("import requests\nrequests.get(os.getenv('SERVICE_URL'))\n")

        self.assertEqual(_env_reference_names(alias_build, "endpoint_env_host"), ["SERVICE_URL"])
        self.assertEqual(_env_reference_names(shadowed_build, "endpoint_env_host"), [])
        self.assertEqual(_env_reference_names(unimported_build, "endpoint_env_host"), [])

    def test_python_http_client_env_only_template_is_not_marked_literal(self) -> None:
        build = _extract_python_client("import os\nimport requests\nrequests.get(f'{os.getenv(\"API_HOST\")}/api/health')\n")

        qualifiers_by_path = _qualifiers_by_path(_endpoint_rows(build, "CALLS_ENDPOINT"))

        self.assertEqual(qualifiers_by_path["/api/health"][0]["resolution_kind"], "template_parameterized")

    def test_python_http_client_env_only_template_base_url_keeps_env_reference(self) -> None:
        build = _extract_python_client(
            "import os\n"
            "from httpx import Client\n"
            "client = Client(base_url=f\"{os.getenv('API_HOST')}\")\n"
            "client.get('/events')\n"
        )

        rows = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_hosts_by_path(rows)["/events"], {"${env:API_HOST}"})
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["API_HOST"])
        self.assertEqual(
            _env_reference_qualifiers(build, "endpoint_env_host")[0]["raw_target"],
            "f\"{os.getenv('API_HOST')}\"",
        )

    def test_python_http_client_path_env_placeholder_does_not_emit_host_env_reference(self) -> None:
        build = _extract_python_client("import os\nimport requests\nrequests.get(f'/api/{os.getenv(\"USER_ID\")}')\n")

        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), [])

    def test_python_http_client_raw_qualifier_values_are_capped(self) -> None:
        long_segment = "a" * 120
        build = _extract_python_client(
            "import os\n"
            "import requests\n"
            "from httpx import Client\n"
            f"requests.get('/api/{long_segment}')\n"
            f"client = Client(base_url='https://service.example.com/{long_segment}')\n"
            "client.get('/orders')\n"
            f"requests.get(os.getenv('SERVICE_URL', 'https://example.com/{long_segment}'))\n"
        )

        call_qualifiers = [fact.qualifier for fact, _ in _endpoint_rows(build, "CALLS_ENDPOINT")]
        env_qualifiers = [
            fact.qualifier
            for fact in build.facts
            if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("reference_kind") == "endpoint_env_host"
        ]

        self.assertTrue(call_qualifiers)
        self.assertTrue(env_qualifiers)
        self.assertTrue(any("base_url_raw" in qualifier for qualifier in call_qualifiers))
        self.assertTrue(all(len(str(qualifier.get("raw_target", ""))) <= 80 for qualifier in call_qualifiers))
        self.assertTrue(all(len(str(qualifier.get("base_url_raw", ""))) <= 80 for qualifier in call_qualifiers))
        self.assertTrue(all(len(str(qualifier.get("raw_target", ""))) <= 80 for qualifier in env_qualifiers))

    def test_python_http_client_template_host_emits_path_candidate(self) -> None:
        build = _extract_python_client(
            "import requests\n\n"
            "def call(service_url, base_uri, email):\n"
            "    requests.get(f'{service_url}/api/health')\n"
            "    requests.post(f'{base_uri}/api/users/{email}')\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/health": {"GET"}, "/api/users/{email}": {"POST"}})
        self.assertEqual(qualifiers_by_path["/api/health"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/api/users/{email}"][0]["route_params"], ["email"])
        self.assertEqual(
            _coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"],
            2,
        )

    def test_python_http_client_calls_resolve_sessions_and_direct_chains_source_order(self) -> None:
        build = _extract_python_client(
            "import requests\n"
            "import httpx\n\n"
            "def call():\n"
            "    session = requests.Session()\n"
            "    session.delete('/session')\n"
            "    requests.Session().get('/direct')\n"
            "    client = httpx.Client(base_url='/api')\n"
            "    client.post('orders')\n"
            "    client = object()\n"
            "    client.get('/not-http-client')\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(
            _methods_by_path(calls),
            {"/session": {"DELETE"}, "/direct": {"GET"}, "/api/orders": {"POST"}},
        )
        self.assertEqual(_source_kinds_by_path(calls)["/direct"], {"requests.client.get"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"httpx.client.post"})

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
                "/api/orders/{orderId}": {"ANY"},
                "/api/profile": {"GET", "PATCH"},
            },
        )
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"fetch_call"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders/{orderId}"], {"fetch_call"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/profile"], {"axios_call"})
        qualifiers_by_path = _qualifiers_by_path(calls)
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["route_params"], ["orderId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("target_dynamic_template_segment", 0), 0)

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

    def test_typescript_fetch_object_config_resolves_url_and_nested_init_method(self) -> None:
        build = _extract_typescript_client(
            "function load(fetch, userId) {\n"
            "  fetch({\n"
            "    url: `/api/users/${userId}`,\n"
            "    init: { method: 'POST' },\n"
            "    apiVersion: '2026-01-01',\n"
            "  });\n"
            "  fetch({\n"
            "    host: process.env.API_HOST,\n"
            "    path: 'api/orders',\n"
            "    init: { method: 'patch' },\n"
            "  });\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {"/api/users/{userId}": {"POST"}, "/api/orders": {"PATCH"}},
        )
        self.assertEqual(_source_kinds_by_path(calls)["/api/users/{userId}"], {"fetch_call"})
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["api_version"], "2026-01-01")
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["route_params"], ["userId"])
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"${env:API_HOST}"})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["API_HOST"])

    def test_typescript_fetch_object_config_keeps_dynamic_top_level_method_unresolved(self) -> None:
        build = _extract_typescript_client(
            "function load(fetch, methodName) {\n"
            "  fetch({\n"
            "    url: '/api/orders',\n"
            "    method: methodName,\n"
            "    init: { method: 'POST' },\n"
            "  });\n"
            "  fetch({\n"
            "    url: '/api/profiles',\n"
            "    init: { method: methodName },\n"
            "  });\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"ANY"}, "/api/profiles": {"ANY"}})

    def test_typescript_fetch_object_config_requires_url_or_path(self) -> None:
        build = _extract_typescript_client(
            "function load(fetch) {\n"
            "  fetch({ init: { method: 'POST' }, body: JSON.stringify(data) });\n"
            "  fetch({ url: computeUrl(), init: { method: 'POST' } });\n"
            "  fetch({ url: '/api/spread', ...override });\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["unresolved_target"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

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

    def test_typescript_imported_http_wrapper_object_calls_are_resolved(self) -> None:
        build = _extract_typescript_client(
            "import { get, post as create, del } from '@example/http-client';\n"
            "import * as http from '@example/http-client';\n"
            "const SERVICE = 'orders-service';\n"
            "const API_VERSION = '2025-01-01';\n"
            "get({ service: SERVICE, path: `/api/orders/${orderId}`, clientAppId: 'web', apiVersion: API_VERSION });\n"
            "create({ host: process.env.API_HOST, url: 'api/orders', clientAppId: 'web' });\n"
            "del({ baseUrl: 'http://localhost:3000/api', path: 'orders/' });\n"
            "http.put({ service: SERVICE, path: '/api/order-status' });\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/orders/{orderId}": {"GET"},
                "/api/orders": {"POST"},
                "/api/orders/": {"DELETE"},
                "/api/order-status": {"PUT"},
            },
        )
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders/{orderId}"], {"http_wrapper_call"})
        self.assertEqual(_hosts_by_path(calls)["/api/orders/{orderId}"], {"orders-service"})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"${env:API_HOST}"})
        self.assertEqual(_hosts_by_path(calls)["/api/orders/"], {"localhost"})
        self.assertEqual(_hosts_by_path(calls)["/api/order-status"], {"orders-service"})
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["service"], "orders-service")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["api_version"], "2025-01-01")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["route_params"], ["orderId"])
        self.assertEqual(qualifiers_by_path["/api/order-status"][0]["wrapper_method"], "put")
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["API_HOST"])

    def test_typescript_generic_request_wrapper_uses_base_url_and_method(self) -> None:
        build = _extract_typescript_client(
            "import { request } from 'generic-http-client';\n"
            "request({ baseUrl: 'http://localhost:3000/api', path: 'search', method: 'patch' });\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/search": {"PATCH"}})
        self.assertEqual(_source_kinds_by_path(calls)["/api/search"], {"http_wrapper_call"})
        self.assertEqual(_hosts_by_path(calls)["/api/search"], {"localhost"})
        self.assertEqual(qualifiers_by_path["/api/search"][0]["wrapper_import_source"], "generic-http-client")
        self.assertEqual(qualifiers_by_path["/api/search"][0]["wrapper_imported_name"], "request")

    def test_typescript_http_wrapper_object_calls_resolve_shorthand_properties(self) -> None:
        build = _extract_typescript_client(
            "import { get } from '@example/http-client';\n"
            "const service = 'orders-service';\n"
            "const path = '/api/orders';\n"
            "get({ service, path });\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"http_wrapper_call"})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service"], "orders-service")

    def test_typescript_wrapper_metadata_omits_unresolved_raw_expressions(self) -> None:
        build = _extract_typescript_client(
            "import { get } from '@example/http-client';\n"
            "get({ service: 'orders-service', path: '/api/orders', apiVersion: runtimeVersion });\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifier = _qualifiers_by_path(calls)["/api/orders"][0]

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(qualifier["service"], "orders-service")
        self.assertNotIn("api_version_raw", qualifier)
        self.assertNotIn("service_raw", qualifier)
        self.assertNotIn("client_app_id_raw", qualifier)

    def test_typescript_imported_wrapper_overlaps_local_axios_client_only_once(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.ts": (
                    "import axios from 'axios';\n"
                    "export const request = axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/orders.ts": (
                    "import { request } from './api';\n"
                    "request({ service: 'orders-service', url: '/api/orders', method: 'post' });\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(len(calls), 1)
        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"http_wrapper_call"})
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_imported_axios_base_url_config_is_not_wrapper_call(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api.ts": (
                    "import axios from 'axios';\n"
                    "export const request = axios.create({ baseURL: 'http://localhost:3000' });\n"
                ),
                "src/orders.ts": (
                    "import { request } from './api';\n"
                    "request({ url: '/api/orders', baseURL: 'http://localhost:4000', method: 'post' });\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"localhost"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"imported_axios_call"})

    def test_typescript_controller_wrapper_methods_use_super_endpoint_defaults(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "const API_VERSION = '2025-01-01';\n"
            "export class OrdersService extends Controller {\n"
            "  constructor() {\n"
            "    super({ service: 'orders-service', clientAppId: 'web', apiVersion: API_VERSION });\n"
            "  }\n"
            "  async getOrder(orderId) {\n"
            "    return this.get({ path: `/api/orders/${orderId}` });\n"
            "  }\n"
            "  async createOrder(data) {\n"
            "    return this.post({ path: '/api/orders', data });\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders/{orderId}": {"GET"}, "/api/orders": {"POST"}})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders/{orderId}"], {"http_controller_wrapper_call"})
        self.assertEqual(_hosts_by_path(calls)["/api/orders/{orderId}"], {"orders-service"})
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["service"], "orders-service")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["api_version"], "2025-01-01")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["wrapper_receiver"], "this")
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["route_params"], ["orderId"])

    def test_typescript_controller_wrapper_methods_use_super_base_url_default(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "export class OrdersService extends Controller {\n"
            "  constructor() {\n"
            "    super({ baseUrl: 'http://localhost:3000/api', clientAppId: 'web' });\n"
            "  }\n"
            "  async search() {\n"
            "    return this.get({ path: 'orders' });\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"localhost"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"http_controller_wrapper_call"})

    def test_typescript_controller_wrapper_methods_preserve_super_service_env_reference(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "export class OrdersService extends Controller {\n"
            "  constructor() {\n"
            "    super({ service: process.env.SERVICE_NAME, clientAppId: 'web' });\n"
            "  }\n"
            "  async search() {\n"
            "    return this.get({ path: '/api/orders' });\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"${env:SERVICE_NAME}"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"http_controller_wrapper_call"})
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["SERVICE_NAME"])

    def test_typescript_controller_wrapper_methods_normalize_super_host_default(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "const OrdersService = class extends Controller {\n"
            "  constructor() {\n"
            "    super({ host: 'http://localhost:8080/api', clientAppId: 'web' });\n"
            "  }\n"
            "  async search() {\n"
            "    return this.get({ path: 'orders' });\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"localhost"})
        self.assertEqual(_source_kinds_by_path(calls)["/api/orders"], {"http_controller_wrapper_call"})

    def test_typescript_controller_wrapper_methods_emit_candidate_for_unresolved_super_default(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "export class OrdersService extends Controller {\n"
            "  constructor() {\n"
            "    super({ service: serviceName, clientAppId: 'web' });\n"
            "  }\n"
            "  async search() {\n"
            "    return this.get({ path: '/api/orders' });\n"
            "  }\n"
            "}\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["host_resolution_kind"], "expression_unresolved")
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "serviceName")
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["client_app_id"], "web")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_resolve_imported_super_service_literal(self) -> None:
        build = _extract_typescript_client_files(
            {
                "tsconfig.json": (
                    "{\n"
                    '  "compilerOptions": {\n'
                    '    "baseUrl": ".",\n'
                    '    "paths": { "@/*": ["src/*"] }\n'
                    "  }\n"
                    "}\n"
                ),
                "src/constants/services.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService as importedService } from '@/constants/services';\n"
                    "const service = importedService;\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async getOrder(orderId) {\n"
                    "    return this.get({ path: `/api/orders/${orderId}` });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders/{orderId}": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders/{orderId}"], {"orders-service"})
        self.assertEqual(qualifiers_by_path["/api/orders/{orderId}"][0]["service"], "orders-service")
        self.assertNotIn("service_raw", qualifiers_by_path["/api/orders/{orderId}"][0])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_resolve_imported_proto_named_literal(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const __proto__ = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { __proto__ as importedService } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service: importedService, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_resolve_proto_named_alias(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "const __proto__ = ordersService;\n"
                    "const service = __proto__;\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_do_not_resolve_mutable_import_alias(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "let service = ordersService;\n"
                    "function reset() { service = 'local-service'; }\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "service")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_keep_mutable_imported_exports_unresolved(self) -> None:
        cases = {
            "export_let": "export let ordersService = 'orders-service';\nfunction reset() { ordersService = 'local-service'; }\n",
            "reexport_var": "var ORDERS_SERVICE = 'orders-service';\nfunction reset() { ORDERS_SERVICE = 'local-service'; }\nexport { ORDERS_SERVICE as ordersService };\n",
        }
        for case_name, constants_source in cases.items():
            with self.subTest(case_name=case_name):
                build = _extract_typescript_client_files(
                    {
                        "src/constants.ts": constants_source,
                        "src/orders.ts": (
                            "import { Controller } from '@example/http-client';\n"
                            "import { ordersService } from './constants';\n"
                            "export class OrdersService extends Controller {\n"
                            "  constructor() {\n"
                            "    super({ service: ordersService, clientAppId: 'web' });\n"
                            "  }\n"
                            "  async search() {\n"
                            "    return this.get({ path: '/api/orders' });\n"
                            "  }\n"
                            "}\n"
                        ),
                    }
                )

                calls = _endpoint_rows(build, "CALLS_ENDPOINT")
                qualifiers_by_path = _qualifiers_by_path(calls)

                self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
                self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
                self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "ordersService")
                self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_resolve_imported_super_base_url_literal(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "const API_ROOT = 'http://localhost:3000/api';\nexport { API_ROOT as apiRoot };\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiRoot } from './constants';\n"
                    "const baseUrl = apiRoot;\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ baseUrl, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: 'orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"localhost"})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["base_url"], "http://localhost:3000/api")
        self.assertNotIn("base_url_raw", qualifiers_by_path["/api/orders"][0])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_resolve_imported_super_host_literal(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const apiHost = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiHost } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ host: apiHost, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertNotIn("host_raw", qualifiers_by_path["/api/orders"][0])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_suppress_imported_external_base_url_literal(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const apiRoot = 'https://api.example.com/v1';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiRoot } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ baseUrl: apiRoot, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: 'orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["external_endpoint_suppressed"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("host_or_service_unresolved", 0), 0)

    def test_typescript_controller_wrapper_methods_keep_malformed_imported_base_url_unresolved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const apiRoot = 'http://:3000/api';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiRoot } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ baseUrl: apiRoot, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: 'orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/orders"], {None})
        self.assertEqual(qualifiers_by_path["/orders"][0]["base_url_raw"], "apiRoot")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_keep_imported_path_prefix_base_url_unresolved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const apiRoot = '/api/v1';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiRoot } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ baseUrl: apiRoot, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: 'orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/orders"], {None})
        self.assertEqual(qualifiers_by_path["/orders"][0]["base_url_raw"], "apiRoot")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_keep_non_url_imported_base_url_unresolved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const apiRoot = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { apiRoot } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ baseUrl: apiRoot, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: 'orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/orders"], {None})
        self.assertEqual(qualifiers_by_path["/orders"][0]["base_url_raw"], "apiRoot")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_keep_dynamic_imported_super_default_unresolved(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = makeService();\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service: ordersService, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "ordersService")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_do_not_use_imported_literal_for_shadowed_super_default(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor(ordersService) {\n"
                    "    super({ service: ordersService, clientAppId: 'web' });\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "ordersService")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_do_not_use_imported_literal_for_hoisted_var_shadow(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service: ordersService, clientAppId: 'web' });\n"
                    "    var ordersService;\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "ordersService")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_do_not_use_imported_literal_for_later_block_shadow(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/constants.ts": "export const ordersService = 'orders-service';\n",
                "src/orders.ts": (
                    "import { Controller } from '@example/http-client';\n"
                    "import { ordersService } from './constants';\n"
                    "export class OrdersService extends Controller {\n"
                    "  constructor() {\n"
                    "    super({ service: ordersService, clientAppId: 'web' });\n"
                    "    let ordersService = 'local-service';\n"
                    "  }\n"
                    "  async search() {\n"
                    "    return this.get({ path: '/api/orders' });\n"
                    "  }\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {None})
        self.assertEqual(qualifiers_by_path["/api/orders"][0]["service_raw"], "ordersService")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

    def test_typescript_controller_wrapper_methods_require_super_base_context(self) -> None:
        build = _extract_typescript_client(
            "import { Controller } from '@example/http-client';\n"
            "export class OrdersService extends Controller {\n"
            "  constructor() {\n"
            "    super({ apiVersion: '2025-01-01', clientAppId: 'web' });\n"
            "  }\n"
            "  async search() {\n"
            "    return this.get({ path: '/api/orders' });\n"
            "  }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])

    def test_typescript_http_wrapper_object_calls_require_wrapper_context(self) -> None:
        build = _extract_typescript_client(
            "import { get, post } from '@example/http-client';\n"
            "import { run } from '@example/tasks';\n"
            "function localGet(options) { return options.path; }\n"
            "localGet({ service: 'orders-service', path: '/api/local' });\n"
            "get({ path: '/api/missing-context' });\n"
            "post({ service: 'orders-service', label: '/api/missing-path' });\n"
            "run({ service: 'orders-service', path: '/api/not-http', method: 'get' });\n"
            "class Plain {\n"
            "  read() { return this.get({ path: '/api/not-controller' }); }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])

    def test_typescript_http_wrapper_object_calls_emit_candidates_for_unresolved_host_context(self) -> None:
        build = _extract_typescript_client(
            "import { get, post } from '@example/http-client';\n"
            "const SERVICE = 'orders-service';\n"
            "get({ service: SERVICE, path: '/api/orders' });\n"
            "post({ service: serviceName, path: '/api/users' });\n"
            "get({ host: makeHost(), path: '/api/profiles' });\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {"/api/orders": {"GET"}, "/api/users": {"POST"}, "/api/profiles": {"GET"}},
        )
        self.assertEqual(_hosts_by_path(calls)["/api/orders"], {"orders-service"})
        self.assertEqual(_hosts_by_path(calls)["/api/users"], {None})
        self.assertEqual(_hosts_by_path(calls)["/api/profiles"], {None})
        self.assertEqual(qualifiers_by_path["/api/users"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/api/users"][0]["host_resolution_kind"], "expression_unresolved")
        self.assertEqual(qualifiers_by_path["/api/users"][0]["service_raw"], "serviceName")
        self.assertEqual(qualifiers_by_path["/api/profiles"][0]["host_raw"], "makeHost()")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 2)

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

    def test_typescript_client_dynamic_template_segments_parameterize_safe_path_segments(self) -> None:
        build = _extract_typescript_client(
            "fetch(`/campaigns/${campaignId}/analytics/`);\n"
            "fetch(`/items/${this.userId}`);\n"
            "fetch(`/rows/${row['id']}`);\n"
            "fetch(`/api/${'v1'}/items/${campaignId}`);\n"
            "fetch(`/repeat/${id}/again/${id}`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/campaigns/{campaignId}/analytics/": {"ANY"},
                "/items/{userId}": {"ANY"},
                "/rows/{id}": {"ANY"},
                "/api/v1/items/{campaignId}": {"ANY"},
                "/repeat/{id}/again/{id}": {"ANY"},
            },
        )
        self.assertEqual(qualifiers_by_path["/campaigns/{campaignId}/analytics/"][0]["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifiers_by_path["/campaigns/{campaignId}/analytics/"][0]["route_params"], ["campaignId"])
        self.assertEqual(qualifiers_by_path["/items/{userId}"][0]["route_params"], ["userId"])
        self.assertEqual(qualifiers_by_path["/rows/{id}"][0]["route_params"], ["id"])
        self.assertEqual(qualifiers_by_path["/api/v1/items/{campaignId}"][0]["route_params"], ["campaignId"])
        self.assertEqual(qualifiers_by_path["/repeat/{id}/again/{id}"][0]["route_params"], ["id"])
        self.assertFalse(_call_site_coverage(build))

    def test_typescript_client_unsafe_dynamic_template_segments_fail_closed(self) -> None:
        build = _extract_typescript_client(
            "fetch(`/items/${getId()}`);\n"
            "fetch(`/items/${a}-${b}`);\n"
            "fetch(`/items/${a + b}`);\n"
            "fetch(`${baseUrl}${path}`);\n"
            "fetch(`/${tenant}${suffix}/items`);\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_expression_unsafe"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_composite_segment"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("target_dynamic_template_segment", 0), 0)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("unresolved_target", 0), 0)

    def test_typescript_client_unresolved_template_host_emits_path_candidate(self) -> None:
        build = _extract_typescript_client(
            "fetch(`${apiHost}/api/projects/${projectId}/activities/search`, { method: 'POST' });\n"
            "fetch(`${getHost()}/api/unsafe`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/projects/{projectId}/activities/search": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/api/projects/{projectId}/activities/search"], {None})
        qualifier = qualifiers_by_path["/api/projects/{projectId}/activities/search"][0]
        self.assertEqual(qualifier["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifier["reason"], "template_dynamic_host_position")
        self.assertEqual(qualifier["host_resolution_kind"], "expression_unresolved")
        self.assertEqual(qualifier["host_raw"], "apiHost")
        self.assertEqual(qualifier["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifier["route_params"], ["projectId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_expression_unsafe"], 1)

    def test_typescript_client_env_host_template_parameterizes_safe_path_segment(self) -> None:
        build = _extract_typescript_client("fetch(`${process.env.API_HOST}/api/users/${userId}`);\n")

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/users/{userId}": {"ANY"}})
        self.assertEqual(_hosts_by_path(calls)["/api/users/{userId}"], {"${env:API_HOST}"})
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["route_params"], ["userId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("template_dynamic_host_position", 0), 0)

    def test_typescript_configured_axios_relative_template_path_parameterizes_under_base(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: process.env.API_HOST });\n"
            "api.get(`users/${userId}/orders/`);\n"
            "fetch(`users/${id}`);\n"
            "axios.get(`users/${id}`);\n"
            "api.get(`items/${getId()}`);\n"
            "api.get(`items/${a}-${b}`);\n"
            "const stripe = axios.create({ baseURL: 'https://api.stripe.com' });\n"
            "stripe.get('v1/customers');\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/users/{userId}/orders/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/users/{userId}/orders/"], {"${env:API_HOST}"})
        self.assertEqual(qualifiers_by_path["/users/{userId}/orders/"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(
            qualifiers_by_path["/users/{userId}/orders/"][0]["host_resolution_kind"],
            "env_backed_unresolved",
        )
        self.assertEqual(
            qualifiers_by_path["/users/{userId}/orders/"][0]["resolution_kind"],
            "template_parameterized",
        )
        self.assertEqual(qualifiers_by_path["/users/{userId}/orders/"][0]["route_params"], ["userId"])
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["API_HOST"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"], 2)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_expression_unsafe"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_composite_segment"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["external_endpoint_suppressed"], 1)

    def test_typescript_configured_axios_unresolved_base_emits_path_candidate(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: apiRoot });\n"
            "api.post(`/api/projects/${projectId}/orders`);\n"
            "api.get(`${pathRoot}${suffix}`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/projects/{projectId}/orders": {"POST"}})
        self.assertEqual(_hosts_by_path(calls)["/api/projects/{projectId}/orders"], {None})
        qualifier = qualifiers_by_path["/api/projects/{projectId}/orders"][0]
        self.assertEqual(qualifier["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifier["host_resolution_kind"], "expression_unresolved")
        self.assertEqual(qualifier["base_url_raw"], "apiRoot")
        self.assertEqual(qualifier["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifier["route_params"], ["projectId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"], 1)

    def test_typescript_configured_axios_url_constructor_relative_template_uses_base(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: process.env.API_HOST });\n"
            "api.get(new URL(`users/${userId}/orders/`, 'https://placeholder.invalid').toString());\n"
            "fetch(new URL(`users/${id}`, 'https://placeholder.invalid').toString());\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/users/{userId}/orders/": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/users/{userId}/orders/"], {"${env:API_HOST}"})
        self.assertEqual(qualifiers_by_path["/users/{userId}/orders/"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/users/{userId}/orders/"][0]["route_params"], ["userId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_typescript_configured_axios_module_path_root_chains_resolve_source_order(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: process.env.API_HOST });\n"
            "const root = 'audience/';\n"
            "const listRoot = root + 'list/';\n"
            "const detailRoot = `${listRoot}detail/`;\n"
            "const parenRoot = (`${listRoot}paren/`);\n"
            "api.get(`${root}${id}/`);\n"
            "api.get(`${listRoot}${id}/`);\n"
            "api.get(`${detailRoot}${id}/`);\n"
            "api.get(`${parenRoot}${id}/`);\n"
            "let reassigned = 'safe/';\n"
            "reassigned = 'changed/';\n"
            "const reassignedChild = reassigned + 'child/';\n"
            "api.get(`${reassigned}${id}/`);\n"
            "api.get(`${reassignedChild}${id}/`);\n"
            "const conditional = isAdmin ? 'admin/' : 'user/';\n"
            "api.get(`${conditional}${id}/`);\n"
            "const earlyRef = lateRoot + 'x/';\n"
            "const lateRoot = 'late/';\n"
            "api.get(`${earlyRef}${id}/`);\n"
            "const duplicate = makeRoot();\n"
            "const duplicate = 'duplicate/';\n"
            "api.get(`${duplicate}${id}/`);\n"
            "declare const declaredRoot: string;\n"
            "const declaredRoot = 'declared/';\n"
            "api.get(`${declaredRoot}${id}/`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/audience/{id}/": {"GET"},
                "/audience/list/{id}/": {"GET"},
                "/audience/list/detail/{id}/": {"GET"},
                "/audience/list/paren/{id}/": {"GET"},
                "/declared/{id}/": {"GET"},
            },
        )
        self.assertEqual(qualifiers_by_path["/audience/{id}/"][0]["route_params"], ["id"])
        self.assertEqual(qualifiers_by_path["/audience/list/{id}/"][0]["route_params"], ["id"])
        self.assertEqual(qualifiers_by_path["/audience/list/detail/{id}/"][0]["route_params"], ["id"])
        self.assertEqual(qualifiers_by_path["/audience/list/paren/{id}/"][0]["route_params"], ["id"])
        self.assertEqual(qualifiers_by_path["/declared/{id}/"][0]["route_params"], ["id"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 5)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["template_dynamic_host_position"], 5)

    def test_typescript_client_env_host_emits_endpoint_env_var_references(self) -> None:
        build = _extract_typescript_client(
            "import axios from 'axios';\n"
            "const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
            "api.get('/api/token/');\n"
            "const bracket = axios.create({ baseURL: process.env['API_ROOT'] + '/v1' });\n"
            "bracket.post('/orders');\n"
            "fetch(`${import.meta.env['VITE_OTHER_ROOT']}/api/other`);\n"
            "fetch(`/api/${process.env.USER_ID}`);\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/token/": {"GET"},
                "/v1/orders": {"POST"},
                "/api/other": {"ANY"},
                "/api/${env:USER_ID}": {"ANY"},
            },
        )
        self.assertEqual(
            _env_reference_names(build, "endpoint_env_host"),
            ["API_ROOT", "VITE_API_ROOT", "VITE_OTHER_ROOT"],
        )
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 3)

    def test_typescript_client_env_host_reference_reuses_dotenv_env_var_identity(self) -> None:
        build = _extract_typescript_client_files(
            {
                ".env": "VITE_API_ROOT=https://api.example.com\n",
                "client.ts": (
                    "import axios from 'axios';\n"
                    "const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "api.get('/api/token/');\n"
                ),
            }
        )

        endpoint_refs = _env_reference_object_ids(build, "endpoint_env_host")
        config_refs = _env_reference_object_ids(build, "config_assignment")

        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["VITE_API_ROOT"])
        self.assertEqual(_env_reference_names(build, "config_assignment"), ["VITE_API_ROOT"])
        self.assertEqual(endpoint_refs, config_refs)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)

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

    def test_typescript_client_switch_sibling_clause_declaration_blocks_module_fallback(self) -> None:
        build = _extract_typescript_client(
            "const url = '/api/module';\n"
            "function load(kind) {\n"
            "  switch (kind) {\n"
            "    case 'declared':\n"
            "      const url = '/api/case';\n"
            "      break;\n"
            "    case 'used':\n"
            "      fetch(url);\n"
            "  }\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

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

    def test_typescript_client_same_statement_later_declarator_is_not_in_scope(self) -> None:
        build = _extract_typescript_client(
            "function load() {\n"
            "  const other = fetch(url), url = '/api/later';\n"
            "}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_shadowed_binding"], 1)

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

    def test_typescript_client_direct_return_helper_call_resolves(self) -> None:
        build = _extract_typescript_client(
            "function getUrl(path) { return '/api/' + path; }\n"
            "fetch(getUrl('helper'));\n"
            "const BASE = '/v1';\n"
            "function withBase(path) { return BASE + path; }\n"
            "fetch(withBase('/items'));\n"
            "function overloaded(path: string): string;\n"
            "function overloaded(path) { return '/overloaded/' + path; }\n"
            "fetch(overloaded('item'));\n"
            "function scoped(p) { return '/scoped/' + p; }\n"
            "function unrelated() { var scoped = () => '/changed'; }\n"
            "fetch(scoped('helper'));\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/helper": {"ANY"},
                "/v1/items": {"ANY"},
                "/overloaded/item": {"ANY"},
                "/scoped/helper": {"ANY"},
            },
        )
        self.assertEqual(qualifiers_by_path["/api/helper"][0]["resolution_kind"], "helper_inline")
        self.assertEqual(qualifiers_by_path["/v1/items"][0]["resolution_kind"], "helper_inline")
        self.assertEqual(qualifiers_by_path["/overloaded/item"][0]["resolution_kind"], "helper_inline")
        self.assertEqual(qualifiers_by_path["/scoped/helper"][0]["resolution_kind"], "helper_inline")

    def test_typescript_client_helper_call_fail_closed_shapes(self) -> None:
        build = _extract_typescript_client(
            "function branch(p) { if (p) return '/a'; return '/b'; }\n"
            "fetch(branch('x'));\n"
            "function multi(p) { let x = '/a' + p; return x; }\n"
            "fetch(multi('y'));\n"
            "function reassigned(p) { return '/a/' + p; }\n"
            "reassigned = () => '/changed';\n"
            "fetch(reassigned('z'));\n"
            "function unresolved(p) { return '/api/' + p; }\n"
            "fetch(unresolved(getId()));\n"
            "function selfCall(p) { return selfCall(p); }\n"
            "fetch(selfCall('loop'));\n"
            "function rest(...parts) { return '/api/' + parts; }\n"
            "fetch(rest('a', 'b'));\n"
            "function nestedVar(p) { return '/api/' + p; }\n"
            "if (cond) { var nestedVar = () => '/changed'; }\n"
            "fetch(nestedVar('shadowed'));\n"
            "function getUrl(p) { return '/api/' + p; }\n"
            "function load(getUrl) { fetch(getUrl('shadowed')); }\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 6)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_reassigned"], 2)

    def test_typescript_client_helper_inline_preserves_env_host_metadata(self) -> None:
        build = _extract_typescript_client(
            "function makeUrl(path) { return import.meta.env.VITE_API_ROOT + path; }\n"
            "fetch(makeUrl('/api/helper-env'));\n"
            "function userPath() { return `/users/${userId}`; }\n"
            "fetch(userPath());\n"
            "function campaignPath(path) { return '/api' + path; }\n"
            "fetch(campaignPath(`/campaigns/${campaignId}`));\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {"/api/helper-env": {"ANY"}, "/users/{userId}": {"ANY"}, "/api/campaigns/{campaignId}": {"ANY"}},
        )
        self.assertEqual(qualifiers_by_path["/api/helper-env"][0]["resolution_kind"], "helper_inline")
        self.assertEqual(qualifiers_by_path["/api/helper-env"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(qualifiers_by_path["/users/{userId}"][0]["resolution_kind"], "helper_inline")
        self.assertEqual(qualifiers_by_path["/users/{userId}"][0]["route_params"], ["userId"])
        self.assertEqual(qualifiers_by_path["/api/campaigns/{campaignId}"][0]["route_params"], ["campaignId"])
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["VITE_API_ROOT"])

    def test_typescript_client_url_constructor_to_string_resolves_narrow_shape(self) -> None:
        build = _extract_typescript_client(
            "const apiBase = 'https://example.com';\n"
            "const versionBase = 'https://example.com/v1/';\n"
            "const rootedBase = 'https://example.com/v1';\n"
            "fetch(new URL('/api/items', apiBase).toString());\n"
            "fetch(new URL('relative-items', versionBase).toString());\n"
            "fetch(new URL('/api/rooted', rootedBase).toString());\n"
            "fetch(new URL(`/api/campaigns/${campaignId}`, apiBase).toString());\n"
            "fetch(new URL('/api/env-items', import.meta.env.VITE_API_ROOT).toString());\n"
            "fetch(new URL('HTTPS://other.example/api/external', apiBase).toString());\n"
            "fetch(new URL('//other.example/api/scheme-relative', apiBase).toString());\n"
            "fetch(new URL('ftp://other.example/api/ftp', apiBase).toString());\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(
            _methods_by_path(calls),
            {
                "/api/items": {"ANY"},
                "/v1/relative-items": {"ANY"},
                "/api/rooted": {"ANY"},
                "/api/campaigns/{campaignId}": {"ANY"},
                "/api/env-items": {"ANY"},
            },
        )
        self.assertEqual(qualifiers_by_path["/api/items"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/v1/relative-items"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/api/rooted"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/api/campaigns/{campaignId}"][0]["route_params"], ["campaignId"])
        self.assertEqual(qualifiers_by_path["/api/env-items"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/api/env-items"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["VITE_API_ROOT"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 3)

    def test_typescript_client_url_constructor_env_base_path_uses_absolute_path(self) -> None:
        build = _extract_typescript_client(
            "const apiBase = import.meta.env.VITE_API_ROOT + '/v1';\n"
            "fetch(new URL('/api/env-rooted', apiBase).toString());\n"
            "const schemeBase = import.meta.env.SCHEME + '://example.com';\n"
            "fetch(new URL('/api/scheme-env', schemeBase).toString());\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/env-rooted": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/env-rooted"][0]["resolution_kind"], "url_constructor")
        self.assertEqual(qualifiers_by_path["/api/env-rooted"][0]["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(_env_reference_names(build, "endpoint_env_host"), ["VITE_API_ROOT"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_typescript_client_url_constructor_fails_when_url_is_module_shadowed(self) -> None:
        build = _extract_typescript_client(
            "const apiBase = 'https://example.com';\n"
            "fetch(new URL('/api/shadowed', apiBase).toString());\n"
            "enum URL {}\n"
        )

        self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_typescript_client_url_constructor_fails_when_url_is_later_block_shadowed(self) -> None:
        for declaration in ("const URL = makeUrl;", "var URL = makeUrl;", "class URL {}"):
            with self.subTest(declaration=declaration):
                build = _extract_typescript_client(
                    "const apiBase = 'https://example.com';\n"
                    "function load() {\n"
                    "  fetch(new URL('/api/block-shadowed', apiBase).toString());\n"
                    f"  {declaration}\n"
                    "}\n"
                )

                self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
                self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_typescript_client_url_constructor_fails_when_url_is_control_flow_shadowed(self) -> None:
        cases = {
            "catch_binding": (
                "const apiBase = 'https://example.com';\n"
                "try { throw makeUrl; } catch (URL) {\n"
                "  fetch(new URL('/api/catch-shadowed', apiBase).toString());\n"
                "}\n"
            ),
            "for_initializer": (
                "const apiBase = 'https://example.com';\n"
                "for (let URL = makeUrl; ready; ready = false) {\n"
                "  fetch(new URL('/api/for-shadowed', apiBase).toString());\n"
                "}\n"
            ),
            "for_of_initializer": (
                "const apiBase = 'https://example.com';\n"
                "for (const URL of urls) {\n"
                "  fetch(new URL('/api/for-of-shadowed', apiBase).toString());\n"
                "}\n"
            ),
            "for_in_initializer": (
                "const apiBase = 'https://example.com';\n"
                "for (let URL in urls) {\n"
                "  fetch(new URL('/api/for-in-shadowed', apiBase).toString());\n"
                "}\n"
            ),
            "module_nested_var": (
                "const apiBase = 'https://example.com';\n"
                "fetch(new URL('/api/module-var-shadowed', apiBase).toString());\n"
                "if (cond) { var URL = makeUrl; }\n"
            ),
            "function_nested_var": (
                "const apiBase = 'https://example.com';\n"
                "function load() {\n"
                "  fetch(new URL('/api/function-var-shadowed', apiBase).toString());\n"
                "  if (cond) { var URL = makeUrl; }\n"
                "}\n"
            ),
            "namespace_nested_var_inside_namespace": (
                "namespace Local {\n"
                "  const apiBase = 'https://example.com';\n"
                "  fetch(new URL('/api/namespace-shadowed', apiBase).toString());\n"
                "  if (cond) { var URL = makeUrl; }\n"
                "}\n"
            ),
        }
        for case_name, source in cases.items():
            with self.subTest(case_name=case_name):
                build = _extract_typescript_client(source)

                self.assertEqual(_endpoint_rows(build, "CALLS_ENDPOINT"), [])
                self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["target_helper_call_deferred"], 1)

    def test_typescript_client_url_constructor_ignores_type_only_url_import(self) -> None:
        build = _extract_typescript_client(
            "import type { URL } from './types';\n"
            "const apiBase = 'https://example.com';\n"
            "fetch(new URL('/api/type-only', apiBase).toString());\n"
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/type-only": {"ANY"}})
        self.assertEqual(qualifiers_by_path["/api/type-only"][0]["resolution_kind"], "url_constructor")

    def test_typescript_client_url_constructor_ignores_non_runtime_url_declarations(self) -> None:
        cases = {
            "import_type_equals": (
                "import type URL = require('./types');\n"
                "const apiBase = 'https://example.com';\n"
                "fetch(new URL('/api/import-type-equals', apiBase).toString());\n",
                "/api/import-type-equals",
            ),
            "declare_var": (
                "declare var URL: unknown;\n"
                "const apiBase = 'https://example.com';\n"
                "fetch(new URL('/api/declare-var', apiBase).toString());\n",
                "/api/declare-var",
            ),
            "declare_const": (
                "declare const URL: unknown;\n"
                "const apiBase = 'https://example.com';\n"
                "fetch(new URL('/api/declare-const', apiBase).toString());\n",
                "/api/declare-const",
            ),
            "namespace_local_var": (
                "namespace Local { var URL = makeUrl; }\n"
                "const apiBase = 'https://example.com';\n"
                "fetch(new URL('/api/namespace-local', apiBase).toString());\n",
                "/api/namespace-local",
            ),
            "block_declare_const": (
                "if (cond) {\n"
                "  declare const URL: unknown;\n"
                "  const apiBase = 'https://example.com';\n"
                "  fetch(new URL('/api/block-declare-const', apiBase).toString());\n"
                "}\n",
                "/api/block-declare-const",
            ),
        }
        for case_name, (source, expected_path) in cases.items():
            with self.subTest(case_name=case_name):
                build = _extract_typescript_client(source)
                calls = _endpoint_rows(build, "CALLS_ENDPOINT")
                qualifiers_by_path = _qualifiers_by_path(calls)

                self.assertEqual(_methods_by_path(calls), {expected_path: {"ANY"}})
                self.assertEqual(qualifiers_by_path[expected_path][0]["resolution_kind"], "url_constructor")

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

    def test_typescript_imported_axios_client_unresolved_base_emits_path_candidate(self) -> None:
        build = _extract_typescript_client_files(
            {
                "src/api/axiosConfig.ts": (
                    "import axios from 'axios';\n"
                    "const api = axios.create({ baseURL: apiRoot });\n"
                    "export default api;\n"
                ),
                "src/orders.ts": (
                    "import api from './api/axiosConfig';\n"
                    "export function load(projectId: string) {\n"
                    "  return api.get(`/api/projects/${projectId}/orders`);\n"
                    "}\n"
                ),
            }
        )

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/projects/{projectId}/orders": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/projects/{projectId}/orders"], {None})
        qualifier = qualifiers_by_path["/api/projects/{projectId}/orders"][0]
        self.assertEqual(qualifier["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(qualifier["host_resolution_kind"], "expression_unresolved")
        self.assertEqual(qualifier["base_url_raw"], "apiRoot")
        self.assertEqual(qualifier["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifier["route_params"], ["projectId"])
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_or_service_unresolved"], 1)

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

    def test_typescript_imported_axios_client_dynamic_template_segment_is_parameterized(self) -> None:
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

        calls = _endpoint_rows(build, "CALLS_ENDPOINT")
        qualifiers_by_path = _qualifiers_by_path(calls)

        self.assertEqual(_methods_by_path(calls), {"/api/users/{userId}": {"GET"}})
        self.assertEqual(_hosts_by_path(calls)["/api/users/{userId}"], {"${env:VITE_API_ROOT}"})
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["resolution_kind"], "template_parameterized")
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["route_params"], ["userId"])
        self.assertEqual(qualifiers_by_path["/api/users/{userId}"][0]["confidence"], "host_unresolved_path_resolved")
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT")["host_env_backed"], 1)
        self.assertEqual(_coverage_reason_counts(build, "CALLS_ENDPOINT").get("target_dynamic_template_segment", 0), 0)
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

    def test_domain_references_include_endpoint_env_host_citations(self) -> None:
        build = _extract_typescript_client_files(
            {
                ".env": "VITE_API_ROOT=https://api.example.com\n",
                "client.ts": (
                    "import axios from 'axios';\n"
                    "const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "api.get('/api/token/');\n"
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=build.entities,
                facts=build.facts,
                evidence=build.evidence,
                coverage=build.coverage,
                manifest={},
            )

            result = KgSnapshot(tmpdir).domain_references("api.example.com", limit=20)

        endpoint_env_usage = [
            row
            for row in result["references"]
            if row["predicate"] == "REFERENCES_ENV_VAR"
            and isinstance(row.get("qualifier"), dict)
            and row["qualifier"].get("reference_kind") == "endpoint_env_host"
        ]
        self.assertEqual(len(endpoint_env_usage), 1)
        qualifier = endpoint_env_usage[0]["qualifier"]
        self.assertEqual(qualifier["endpoint_method"], "GET")
        self.assertEqual(qualifier["endpoint_path"], "/api/token/")
        self.assertEqual(qualifier["raw_target"], "${env:VITE_API_ROOT}/api/token/")
        self.assertEqual(qualifier["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(endpoint_env_usage[0]["evidence"][0]["bytes_ref"]["path"], "client.ts")
        self.assertNotIn("ROUTES_DOMAIN_TO_DEPLOY", {row["predicate"] for row in result["references"]})
        self.assertNotIn("CALLS_ENDPOINT", {row["predicate"] for row in result["references"]})

    def test_domain_references_include_imported_endpoint_env_host_citations(self) -> None:
        build = _extract_typescript_client_files(
            {
                ".env": "VITE_API_ROOT=https://api.example.com\n",
                "src/api/axiosConfig.tsx": (
                    "import axios from 'axios';\n"
                    "const client = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "export default client;\n"
                ),
                "src/api/login.api.tsx": (
                    "import client from './axiosConfig';\n"
                    "export function login() {\n"
                    "  return client.post('/api/token/', {});\n"
                    "}\n"
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=build.entities,
                facts=build.facts,
                evidence=build.evidence,
                coverage=build.coverage,
                manifest={},
            )

            result = KgSnapshot(tmpdir).domain_references("api.example.com", limit=20)

        endpoint_env_usage = [
            row
            for row in result["references"]
            if row["predicate"] == "REFERENCES_ENV_VAR"
            and isinstance(row.get("qualifier"), dict)
            and row["qualifier"].get("reference_kind") == "endpoint_env_host"
        ]
        self.assertEqual(len(endpoint_env_usage), 1)
        qualifier = endpoint_env_usage[0]["qualifier"]
        self.assertEqual(qualifier["endpoint_method"], "POST")
        self.assertEqual(qualifier["endpoint_path"], "/api/token/")
        self.assertEqual(qualifier["raw_target"], "/api/token/")
        self.assertEqual(qualifier["host_resolution_kind"], "env_backed_unresolved")
        self.assertEqual(endpoint_env_usage[0]["evidence"][0]["bytes_ref"]["path"], "src/api/login.api.tsx")

    def test_domain_references_exclude_endpoint_env_host_without_domain_link(self) -> None:
        build = _extract_typescript_client_files(
            {
                "client.ts": (
                    "import axios from 'axios';\n"
                    "const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "api.get('/api/token/');\n"
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=build.entities,
                facts=build.facts,
                evidence=build.evidence,
                coverage=build.coverage,
                manifest={},
            )

            result = KgSnapshot(tmpdir).domain_references("api.example.com", limit=20)

        endpoint_env_usage = [
            row
            for row in result["references"]
            if row["predicate"] == "REFERENCES_ENV_VAR"
            and isinstance(row.get("qualifier"), dict)
            and row["qualifier"].get("reference_kind") == "endpoint_env_host"
        ]
        self.assertEqual(result["reference_count"], 0)
        self.assertEqual(endpoint_env_usage, [])

    def test_domain_references_scope_endpoint_env_host_to_matching_env_domain(self) -> None:
        build = _extract_typescript_client_files(
            {
                ".env": (
                    "VITE_API_ROOT=https://api.example.com\n"
                    "VITE_OTHER_ROOT=https://other.example.com\n"
                ),
                "client.ts": (
                    "import axios from 'axios';\n"
                    "const api = axios.create({ baseURL: import.meta.env.VITE_API_ROOT });\n"
                    "api.get('/api/token/');\n"
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=build.entities,
                facts=build.facts,
                evidence=build.evidence,
                coverage=build.coverage,
                manifest={},
            )

            result = KgSnapshot(tmpdir).domain_references("other.example.com", limit=20)

        endpoint_env_usage = [
            row
            for row in result["references"]
            if row["predicate"] == "REFERENCES_ENV_VAR"
            and isinstance(row.get("qualifier"), dict)
            and row["qualifier"].get("reference_kind") == "endpoint_env_host"
        ]
        self.assertEqual(endpoint_env_usage, [])

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

    def test_reconcile_endpoints_matches_route_parameter_shapes(self) -> None:
        docs_service = _service_entity("api-docs")
        backend_service = _service_entity("orders-api")
        client_service = _service_entity("web-app")
        docs_endpoint = _endpoint_entity("api-docs", "ANY", "/v1/orders/{orderId}")
        backend_endpoint = _endpoint_entity("orders-api", "GET", "/v1/orders/:id")
        client_endpoint = _endpoint_entity("web-app", "GET", "/v1/orders/<int:order_id>")
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

            snapshot = KgSnapshot(tmpdir)
            result = snapshot.reconcile_endpoints(
                docs_scope=("api-docs",),
                backend_scope=("orders-api",),
                client_scope=("web-app",),
            )
            endpoint_query = snapshot.endpoints(path_query="/v1/orders/{id}", limit=10)

        self.assertEqual([row["key"] for row in result["documented_AND_implemented"]], ["/v1/orders/{param}"])
        self.assertEqual([row["key"] for row in result["documented_AND_called"]], ["/v1/orders/{param}"])
        self.assertEqual(endpoint_query["endpoint_fact_count"], 3)
        self.assertEqual(
            {row["object"] for row in endpoint_query["endpoints"]},
            {"ANY /v1/orders/{orderId}", "GET /v1/orders/:id", "GET /v1/orders/<int:order_id>"},
        )

    def test_reconcile_endpoint_path_prefix_requires_segment_boundary(self) -> None:
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
                path_prefix="/v1/ord",
            )

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["documented_AND_implemented"], [])
        self.assertEqual(result["documented_AND_called"], [])
        self.assertEqual([warning["scope"] for warning in result["coverage_warnings"]], ["docs", "backend", "client"])

    def test_reconcile_contract_non_endpoint_prefix_uses_plain_string_prefix(self) -> None:
        producer = _service_entity("orders-api")
        consumer = _service_entity("worker")
        channel = Entity(
            kind="EventChannel",
            identity={
                "tenant_id": "default",
                "repo": "orders-api",
                "broker_kind": "sqs",
                "channel_address": "orders-created",
                "name": "orders-created",
            },
        )
        facts = [
            Fact("PRODUCES_EVENT", producer.entity_id, channel.entity_id),
            Fact("CONSUMES_EVENT", consumer.entity_id, channel.entity_id),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            JsonlKgStore(tmpdir).write(
                entities=[producer, consumer, channel],
                facts=facts,
                evidence=[],
                coverage=[],
                manifest={},
            )

            result = reconcile_contract(
                KgSnapshot(tmpdir),
                ContractReconciliationSpec(
                    name="events",
                    identity_key="event_channel",
                    left=ContractSide(
                        name="produced",
                        predicates=("PRODUCES_EVENT",),
                        path_prefix="sqs:ord",
                    ),
                    right=ContractSide(
                        name="consumed",
                        predicates=("CONSUMES_EVENT",),
                        path_prefix="sqs:ord",
                    ),
                ),
            )

        self.assertEqual([row["key"] for row in result["matched"]], ["sqs:orders-created"])

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


def _extract_python_client(source: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_path = root / "client.py"
        source_path.write_text(source, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name="python-client",
            owner="test",
            commit_sha="test-sha",
            files_by_language={"python": (source_path,), "typescript": ()},
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


def _env_reference_names(build, reference_kind: str) -> list[str]:
    names = [
        fact.qualifier.get("name")
        for fact in build.facts
        if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("reference_kind") == reference_kind
    ]
    return sorted(name for name in names if isinstance(name, str))


def _env_reference_qualifiers(build, reference_kind: str) -> list[dict[str, object]]:
    return [
        fact.qualifier
        for fact in build.facts
        if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("reference_kind") == reference_kind
    ]


def _env_reference_object_ids(build, reference_kind: str) -> set[str]:
    return {
        fact.object_id
        for fact in build.facts
        if fact.predicate == "REFERENCES_ENV_VAR" and fact.qualifier.get("reference_kind") == reference_kind
    }


def _call_site_coverage(build) -> list[Coverage]:
    call_site_reasons = {
        "external_endpoint_suppressed",
        "host_env_backed",
        "target_helper_call_deferred",
        "target_dynamic_template_segment",
        "target_reassigned_binding",
        "target_shadowed_binding",
        "template_dynamic_composite_segment",
        "template_dynamic_expression_unsafe",
        "template_dynamic_host_position",
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
