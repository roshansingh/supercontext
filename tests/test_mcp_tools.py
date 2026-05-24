from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.product.mcp_tools import TOOL_NAMES, call_tool, tool_definitions
from source.kg.query.snapshot import KgSnapshot
from source.scripts.mcp_server import (
    _JsonPayloadError,
    MCP_PROTOCOL_VERSION,
    REQUEST_READ_TIMEOUT_SECONDS,
    _content_length,
    _decode_json_payload,
    _format_host_for_url,
    _handler_class,
    _handle_json_rpc,
    _handle_json_rpc_payload,
    _is_loopback_host,
    _read_request_body,
    _RequestBodyTimeout,
    _server_address_for_host,
    _server_class_for_host,
)


def _assert_additive_fields(testcase: unittest.TestCase, payload: dict[str, object]) -> None:
    testcase.assertIn("coverage_warnings", payload)
    testcase.assertIn("unsupported_scopes", payload)
    testcase.assertIn("next_actions", payload)
    testcase.assertIsInstance(payload["coverage_warnings"], list)
    testcase.assertIsInstance(payload["unsupported_scopes"], list)
    testcase.assertIsInstance(payload["next_actions"], list)


class McpToolsTest(unittest.TestCase):
    def test_tool_definitions_include_adr_names_and_workflow_extensions(self) -> None:
        definitions = tool_definitions()
        self.assertEqual([row["name"] for row in definitions], list(TOOL_NAMES))
        schemas = {row["name"]: row["inputSchema"] for row in definitions}
        self.assertEqual(schemas["search_services"]["properties"]["query"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["path"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["line"]["type"], ["integer", "null"])
        self.assertEqual(schemas["planning_context"]["properties"]["symbol"]["type"], ["string", "null"])
        self.assertEqual(schemas["review_context"]["properties"]["changed_files"]["type"], "array")
        self.assertNotIn("depth", schemas["review_context"]["properties"])
        descriptions = {row["name"]: row["description"] for row in definitions}
        self.assertIn("Primary workflow tool", descriptions["planning_context"])
        self.assertIn("Primary workflow tool", descriptions["review_context"])
        self.assertIn("planning_context first", descriptions["search_services"])
        self.assertIn("planning_context first", descriptions["get_service_brief"])
        self.assertIn("review_context first", descriptions["find_callers"])
        self.assertIn("planning_context or review_context", descriptions["find_callees"])
        self.assertIn("planning_context first", descriptions["get_event_consumers"])
        self.assertIn("planning_context first", descriptions["get_event_producers"])

    def test_planning_context_resolves_structured_and_query_inputs(self) -> None:
        with _fixture_snapshot() as kg:
            symbol = call_tool(kg, "planning_context", {"symbol": "charge_card"})
            query = call_tool(kg, "planning_context", {"query": "shared-lib"})

        self.assertEqual(symbol["status"], "found")
        self.assertIn("anchors", symbol)
        self.assertEqual(query["status"], "found")
        self.assertEqual(query["anchors"]["package"], "shared-lib")
        self.assertEqual(query["dependencies"][0]["predicate"], "IMPORTS")

    def test_planning_context_ambiguous_and_empty_inputs_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            ambiguous = call_tool(kg, "planning_context", {"query": "payments"})
            self.assertEqual(ambiguous["status"], "ambiguous")
            self.assertTrue(ambiguous["next_actions"])
            self.assertTrue(any(row["predicate"] == "RESOLVES_TO_REPO" for row in ambiguous["dependencies"]))
            with self.assertRaisesRegex(ValueError, "planning_context requires at least one of"):
                call_tool(kg, "planning_context", {})

    def test_planning_context_package_query_does_not_treat_limited_rows_as_unique(self) -> None:
        with _fixture_snapshot(extra_package_importers=1) as kg:
            ambiguous = call_tool(kg, "planning_context", {"query": "shared-lib", "limit": 1})

        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertTrue(ambiguous["next_actions"])
        self.assertEqual(len(ambiguous["dependencies"]), 1)
        self.assertEqual(ambiguous["dependencies"][0]["predicate"], "IMPORTS")

    def test_planning_context_raw_query_substring_matches_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            endpoint = call_tool(kg, "planning_context", {"query": "/check"})
            event_channel = call_tool(kg, "planning_context", {"query": "orders"})
            domain = call_tool(kg, "planning_context", {"query": "internal"})

        self.assertEqual(endpoint["status"], "ambiguous")
        self.assertTrue(endpoint["next_actions"])
        self.assertEqual(event_channel["status"], "ambiguous")
        self.assertTrue(event_channel["next_actions"])
        self.assertEqual(domain["status"], "ambiguous")
        self.assertTrue(domain["next_actions"])

    def test_planning_context_raw_query_zero_hits_is_ambiguous(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"query": "definitely-missing-anchor"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertTrue(result["next_actions"])

    def test_planning_context_symbol_ambiguity_returns_candidates(self) -> None:
        with _fixture_snapshot(extra_charge_card_symbol=True) as kg:
            result = call_tool(kg, "planning_context", {"symbol": "charge_card"})

        self.assertEqual(result["status"], "ambiguous")
        self.assertGreaterEqual(len(result["symbols"]), 2)
        self.assertTrue(result["next_actions"])

    def test_planning_context_multiple_primary_anchors_intersect(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"repo": "payments", "package": "shared-lib"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["anchors"]["repo"], "payments")
        self.assertEqual(result["anchors"]["package"], "shared-lib")
        self.assertEqual({row["predicate"] for row in result["dependencies"]}, {"IMPORTS", "RESOLVES_TO_REPO"})

    def test_planning_context_service_and_repo_narrow_without_scope_rejection(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "repo": "payments"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")

    def test_planning_context_single_substring_service_anchor_stays_found(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "pay"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")

    def test_planning_context_symbol_path_and_line_narrow_deterministically(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"symbol": "charge_card", "path": "payments/gateway.py", "line": 5})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "charge_card")

    def test_planning_context_path_and_line_filter_before_limit(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"path": "payments/checkout.py", "line": 10, "limit": 1})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "handle_checkout")

    def test_planning_context_fact_line_filter_uses_attached_evidence(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "planning_context",
                {"package": "shared-lib", "line": 2},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual({row["predicate"] for row in result["dependencies"]}, {"IMPORTS"})

    def test_planning_context_symbol_path_and_line_disambiguate_symbol_anchor(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "planning_context",
                {"symbol": "charge_card", "path": "payments/gateway.py", "line": 5},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["symbols"]), 1)
        self.assertEqual(result["symbols"][0]["qualname"], "charge_card")
        self.assertEqual(result["symbols"][0]["path"], "payments/gateway.py")

    def test_planning_context_repo_filters_service_anchor_without_failing_closed(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "planning_context", {"service": "payments", "repo": "payments"})

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["services"]), 1)
        self.assertEqual(result["services"][0]["slug"], "payments")
        self.assertEqual(result["dependencies"], [])

    def test_planning_context_structured_endpoint_event_and_domain_anchors(self) -> None:
        with _fixture_snapshot() as kg:
            endpoint = call_tool(kg, "planning_context", {"repo": "payments", "endpoint": "/checkout"})
            event = call_tool(kg, "planning_context", {"repo": "payments", "event_channel": "orders-created"})
            domain = call_tool(kg, "planning_context", {"repo": "payments", "domain": "api.internal.example"})

        self.assertEqual(endpoint["status"], "found")
        self.assertEqual({row["predicate"] for row in endpoint["endpoints"]}, {"EXPOSES_ENDPOINT"})
        self.assertEqual(event["status"], "found")
        self.assertEqual({row["predicate"] for row in event["event_channels"]}, {"CONSUMES_EVENT", "PRODUCES_EVENT"})
        self.assertEqual(domain["status"], "found")
        self.assertEqual({row["predicate"] for row in domain["domains"]}, {"REFERENCES_DOMAIN"})

    def test_review_context_aggregates_symbols_and_call_edges(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {"repo": "payments", "changed_files": ["payments/checkout.py"], "limit": 10},
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["repo"], "payments")
        self.assertIn("changed_symbols", result)
        self.assertIn("direct_callers", result)
        self.assertIn("direct_callees", result)
        self.assertIn("repo_dependencies", result)
        self.assertTrue(any(row["qualname"] == "handle_checkout" for row in result["changed_symbols"]))
        self.assertEqual({row["predicate"] for row in result["direct_callees"]}, {"CALLS"})
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})
        _assert_additive_fields(self, result)

    def test_review_context_repo_filter_is_case_insensitive(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {"repo": "Payments", "changed_files": ["payments/checkout.py"], "limit": 10},
            )

        self.assertEqual(result["status"], "found")
        self.assertTrue(any(row["qualname"] == "handle_checkout" for row in result["changed_symbols"]))
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_review_context_changed_ranges_filter_symbols(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 10, "end_line": 10}],
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual([row["qualname"] for row in result["changed_symbols"]], ["handle_checkout"])

    def test_review_context_changed_ranges_only_narrow_matching_files(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py", "payments/gateway.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 10, "end_line": 10}],
                    "limit": 10,
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(
            {row["qualname"] for row in result["changed_symbols"]},
            {"handle_checkout", "charge_card"},
        )

    def test_review_context_missing_changed_file_still_returns_repo_dependencies(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/missing.py"]})

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["changed_symbols"], [])
        self.assertEqual(result["direct_callers"], [])
        self.assertEqual(result["direct_callees"], [])
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_review_context_changed_ranges_fail_closed_for_non_overlapping_file(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(
                kg,
                "review_context",
                {
                    "repo": "payments",
                    "changed_files": ["payments/checkout.py"],
                    "changed_ranges": [{"path": "payments/checkout.py", "start_line": 30, "end_line": 30}],
                },
            )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["changed_symbols"], [])
        self.assertEqual(result["direct_callers"], [])
        self.assertEqual(result["direct_callees"], [])
        self.assertEqual({row["predicate"] for row in result["repo_dependencies"]}, {"RESOLVES_TO_REPO"})

    def test_review_context_rejects_unknown_arguments(self) -> None:
        with _fixture_snapshot() as kg:
            with self.assertRaisesRegex(ValueError, "does not accept argument\\(s\\): depth"):
                call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/checkout.py"], "depth": 2})
            with self.assertRaisesRegex(ValueError, "changed_ranges"):
                call_tool(
                    kg,
                    "review_context",
                    {
                        "repo": "payments",
                        "changed_files": ["payments/checkout.py"],
                        "changed_ranges": [
                            {"path": "payments/checkout.py", "start_line": 10, "end_line": 10, "extra": "bad"}
                        ],
                    },
                )
            with self.assertRaisesRegex(ValueError, "changed_ranges"):
                call_tool(
                    kg,
                    "review_context",
                    {"repo": "payments", "changed_files": ["payments/checkout.py"], "changed_ranges": None},
                )

    def test_review_context_deploy_blocker_row_is_opt_in(self) -> None:
        with _fixture_snapshot() as kg:
            default = call_tool(kg, "review_context", {"repo": "payments", "changed_files": ["payments/checkout.py"]})
            opted_in = call_tool(
                kg,
                "review_context",
                {"repo": "payments", "changed_files": ["payments/checkout.py"], "include_deploy_blockers": True},
            )

        self.assertEqual(default["unsupported_scopes"], [])
        self.assertEqual(
            opted_in["unsupported_scopes"],
            [
                {
                    "kind": "deploy_blockers",
                    "scope": "payments",
                    "reason": "No canonical deploy-blocker relation is implemented yet",
                }
            ],
        )

    def test_search_services_and_service_brief_return_json_shapes(self) -> None:
        with _fixture_snapshot() as kg:
            all_services = call_tool(kg, "search_services", {})
            search = call_tool(kg, "search_services", {"query": "payments"})
            brief = call_tool(kg, "get_service_brief", {"service": "payments"})
            limited_brief = call_tool(kg, "get_service_brief", {"service": "payments", "limit": 1})
            missing = call_tool(kg, "get_service_brief", {"service": "missing"})

        self.assertEqual(all_services["status"], "found")
        self.assertEqual(search["status"], "found")
        self.assertEqual(search["services"][0]["slug"], "payments")
        self.assertEqual(brief["status"], "found")
        self.assertEqual(brief["service"]["slug"], "payments")
        self.assertEqual(brief["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(limited_brief["summary"]["endpoint_fact_count"], 1)
        self.assertEqual(limited_brief["summary"]["event_fact_count"], 1)
        self.assertEqual(len(limited_brief["endpoints"]), 1)
        self.assertEqual(len(limited_brief["event_channels"]), 1)
        self.assertFalse(any(key.startswith("_") for key in brief["endpoints"][0]))
        self.assertEqual(missing["status"], "not_found")
        _assert_additive_fields(self, all_services)
        _assert_additive_fields(self, search)
        _assert_additive_fields(self, brief)
        _assert_additive_fields(self, limited_brief)
        _assert_additive_fields(self, missing)

    def test_symbol_tools_wrap_snapshot_query_methods(self) -> None:
        with _fixture_snapshot() as kg:
            callers = call_tool(kg, "find_callers", {"symbol": "charge_card"})
            callees = call_tool(kg, "find_callees", {"symbol": "handle_checkout"})
            radius = call_tool(kg, "blast_radius", {"symbol": "handle_checkout", "depth": 1})

        self.assertEqual(callers["status"], "found")
        self.assertEqual(callers["caller_count"], 1)
        self.assertEqual(callees["status"], "found")
        self.assertEqual(callees["callee_count"], 1)
        self.assertEqual(radius["status"], "found")
        self.assertEqual(radius["edge_count"], 1)
        _assert_additive_fields(self, callers)
        _assert_additive_fields(self, callees)
        _assert_additive_fields(self, radius)

    def test_discovery_keeps_fuzzy_but_graph_tools_require_exact_symbols(self) -> None:
        with _fixture_snapshot() as kg:
            lookup = kg.lookup_symbol("card")
            planning = call_tool(kg, "planning_context", {"query": "card"})
            callers = call_tool(kg, "find_callers", {"symbol": "card"})
            callees = call_tool(kg, "find_callees", {"symbol": "handle"})
            radius = call_tool(kg, "blast_radius", {"symbol": "handle", "depth": 1})
            dependency = kg.dependency_path("handle", "shared-lib")
            evidence = kg.evidence_for_call("handle_checkout", "card")

        self.assertEqual(lookup["status"], "resolved")
        self.assertEqual(lookup["confidence"], "fuzzy_unique")
        self.assertEqual(lookup["resolved_symbol"]["qualname"], "charge_card")
        self.assertTrue(any(row["qualname"] == "charge_card" for row in planning["symbols"]))
        self.assertEqual(callers["status"], "not_found")
        self.assertEqual(callers["target"]["confidence"], "not_found")
        self.assertEqual(callees["status"], "not_found")
        self.assertEqual(callees["source"]["confidence"], "not_found")
        self.assertEqual(radius["status"], "not_found")
        self.assertEqual(radius["source"]["confidence"], "not_found")
        self.assertEqual(dependency["status"], "not_found")
        self.assertEqual(dependency["source"]["confidence"], "not_found")
        self.assertEqual(evidence["status"], "not_found")
        self.assertEqual(evidence["callee"]["confidence"], "not_found")

    def test_event_tools_filter_consumers_and_producers(self) -> None:
        with _fixture_snapshot() as kg:
            consumers = call_tool(kg, "get_event_consumers", {"channel": "orders"})
            producers = call_tool(kg, "get_event_producers", {"channel": "orders"})
            limited_producers = call_tool(kg, "get_event_producers", {"channel": "orders", "limit": 1})

        self.assertEqual(consumers["status"], "found")
        self.assertEqual(consumers["returned_count"], 1)
        self.assertEqual(consumers["consumers"][0]["predicate"], "CONSUMES_EVENT")
        self.assertEqual(producers["status"], "found")
        self.assertEqual(producers["returned_count"], 1)
        self.assertEqual(producers["producers"][0]["predicate"], "PRODUCES_EVENT")
        self.assertEqual(limited_producers["status"], "found")
        _assert_additive_fields(self, consumers)
        _assert_additive_fields(self, producers)
        _assert_additive_fields(self, limited_producers)

    def test_event_tools_scan_all_matching_facts_before_limiting(self) -> None:
        with _fixture_snapshot(extra_consumers=125) as kg:
            consumers = call_tool(kg, "get_event_consumers", {"channel": "orders", "limit": 1})
            producers = call_tool(kg, "get_event_producers", {"channel": "orders", "limit": 1})

        self.assertEqual(consumers["event_fact_count"], 126)
        self.assertEqual(consumers["returned_count"], 1)
        self.assertEqual(producers["event_fact_count"], 1)
        self.assertEqual(producers["returned_count"], 1)

    def test_deploy_blockers_refuses_when_current_kg_has_no_contract(self) -> None:
        with _fixture_snapshot() as kg:
            result = call_tool(kg, "deploy_blockers_for", {"service": "payments"})

        self.assertEqual(result["status"], "unsupported_by_current_kg")
        self.assertEqual(result["missing_contract"], "deploy_blockers_for")
        _assert_additive_fields(self, result)

    def test_tool_arguments_fail_closed(self) -> None:
        with _fixture_snapshot() as kg:
            with self.assertRaisesRegex(ValueError, "symbol"):
                call_tool(kg, "find_callers", {"limit": 10})
            with self.assertRaisesRegex(ValueError, "limit"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": True})
            with self.assertRaisesRegex(ValueError, "limit"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": "10"})
            with self.assertRaisesRegex(ValueError, "between 1 and 100"):
                call_tool(kg, "find_callers", {"symbol": "x", "limit": 0})
            with self.assertRaisesRegex(ValueError, "between 1 and 6"):
                call_tool(kg, "blast_radius", {"symbol": "x", "depth": 999})
            with self.assertRaisesRegex(ValueError, "does not accept"):
                call_tool(kg, "find_callers", {"symbol": "x", "extra": "ignored"})
            with self.assertRaisesRegex(ValueError, "Unsupported MCP tool"):
                call_tool(kg, "unknown_tool", {})

    def test_json_rpc_lists_and_calls_tools(self) -> None:
        with _fixture_snapshot() as kg:
            initialized = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
            initialized_with_client_version = _handle_json_rpc(
                kg,
                {"jsonrpc": "2.0", "id": 8, "method": "initialize", "params": {"protocolVersion": "2099-01-01"}},
            )
            ping = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 9, "method": "ping"})
            listed = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            batch = _handle_json_rpc_payload(
                kg,
                [
                    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
                    {"jsonrpc": "2.0", "method": "ping"},
                ],
            )
            called = _handle_json_rpc(
                kg,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "search_services", "arguments": {"query": "payments"}},
                },
            )
            unsupported = _handle_json_rpc(
                kg,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "deploy_blockers_for", "arguments": {"service": "payments"}},
                },
            )

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "supercontext-local")
        self.assertEqual(initialized["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(initialized_with_client_version["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(ping["result"], {})
        self.assertEqual(batch[0]["id"], 3)
        self.assertEqual(listed["result"]["tools"][0]["name"], "planning_context")
        listed_tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
        self.assertIn("Exact-symbol static CALLS closure", listed_tools["blast_radius"]["description"])
        self.assertEqual(called["result"]["structuredContent"]["status"], "found")
        _assert_additive_fields(self, called["result"]["structuredContent"])
        self.assertFalse(called["result"]["isError"])
        self.assertEqual(unsupported["result"]["structuredContent"]["status"], "unsupported_by_current_kg")
        self.assertFalse(unsupported["result"]["isError"])

    def test_json_rpc_reports_protocol_errors(self) -> None:
        with _fixture_snapshot() as kg:
            result = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}})
            wrong_version = _handle_json_rpc(kg, {"jsonrpc": "1.0", "id": 2, "method": "ping"})
            notification = _handle_json_rpc(kg, {"jsonrpc": "2.0", "method": "ping"})
            invalid_notification_version = _handle_json_rpc(kg, {"jsonrpc": "1.0", "method": "ping"})
            invalid_notification_method = _handle_json_rpc(kg, {"jsonrpc": "2.0"})
            invalid_notification_params = _handle_json_rpc(kg, {"jsonrpc": "2.0", "method": "ping", "params": []})
            empty_batch = _handle_json_rpc_payload(kg, [])
            notification_batch = _handle_json_rpc_payload(kg, [{"jsonrpc": "2.0", "method": "ping"}])
            invalid_id = _handle_json_rpc(kg, {"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "ping"})

        self.assertEqual(result["error"]["code"], -32602)
        self.assertIn("name", result["error"]["message"])
        self.assertEqual(wrong_version["error"]["code"], -32600)
        self.assertIsNone(notification)
        self.assertEqual(invalid_notification_version["error"]["code"], -32600)
        self.assertEqual(invalid_notification_method["error"]["code"], -32600)
        self.assertEqual(invalid_notification_params["error"]["code"], -32602)
        self.assertEqual(empty_batch["error"]["code"], -32600)
        self.assertIsNone(notification_batch)
        self.assertEqual(invalid_id["error"]["code"], -32600)

    def test_json_rpc_internal_errors_do_not_leak_exception_details(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = _handle_json_rpc(
                object(),
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "search_services", "arguments": {}},
                },
            )

        self.assertEqual(result["error"]["code"], -32000)
        self.assertEqual(result["error"]["message"], "Internal MCP server error")
        self.assertIn("Unhandled MCP JSON-RPC error", stderr.getvalue())
        self.assertIn("AttributeError", stderr.getvalue())

    def test_content_length_validation_rejects_transport_level_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "Missing Content-Length"):
            _content_length(_FakeHttpHandler({}))
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            _content_length(_FakeHttpHandler({"Content-Length": "abc"}))
        with self.assertRaisesRegex(ValueError, "outside the accepted range"):
            _content_length(_FakeHttpHandler({"Content-Length": "1000001"}))

        self.assertEqual(_content_length(_FakeHttpHandler({"Content-Length": "2"})), 2)

    def test_request_body_read_sets_timeout_and_rejects_incomplete_body(self) -> None:
        complete = _FakeHttpHandler({"Content-Length": "2"}, body=b"{}")
        short = _FakeHttpHandler({"Content-Length": "4"}, body=b"{}")
        stalled = _FakeHttpHandler({"Content-Length": "2"}, rfile=_TimeoutReader())

        self.assertEqual(_read_request_body(complete, 2), b"{}")
        self.assertEqual(complete.connection.timeout, REQUEST_READ_TIMEOUT_SECONDS)
        with self.assertRaisesRegex(ValueError, "before Content-Length"):
            _read_request_body(short, 4)
        with self.assertRaisesRegex(_RequestBodyTimeout, "Timed out"):
            _read_request_body(stalled, 2)

    def test_json_body_decoding_reports_invalid_utf8_as_parse_error(self) -> None:
        with self.assertRaisesRegex(_JsonPayloadError, "invalid UTF-8"):
            _decode_json_payload(b"\xff")
        with self.assertRaisesRegex(_JsonPayloadError, "Expecting value"):
            _decode_json_payload(b"not-json")

        self.assertEqual(_decode_json_payload(b'{"ok": true}'), {"ok": True})

    def test_loopback_host_detection_accepts_loopback_network(self) -> None:
        self.assertTrue(_is_loopback_host("localhost"))
        self.assertTrue(_is_loopback_host("127.0.0.1"))
        self.assertTrue(_is_loopback_host("127.0.1.1"))
        self.assertTrue(_is_loopback_host("::1"))
        self.assertFalse(_is_loopback_host("0.0.0.0"))
        self.assertFalse(_is_loopback_host("example.com"))
        self.assertEqual(_format_host_for_url("127.0.0.1"), "127.0.0.1")
        self.assertEqual(_format_host_for_url("::1"), "[::1]")
        self.assertEqual(_format_host_for_url("localhost"), "localhost")
        self.assertEqual(_server_address_for_host("127.0.0.1", 3845), ("127.0.0.1", 3845))
        self.assertEqual(_server_address_for_host("::1", 3845), ("::1", 3845, 0, 0))
        self.assertNotEqual(_server_class_for_host("::1").address_family, _server_class_for_host("127.0.0.1").address_family)

    def test_http_server_header_does_not_expose_python_version(self) -> None:
        handler = _handler_class(object())
        fake_handler = type("FakeHandler", (), {"server_version": handler.server_version})()

        self.assertEqual(handler.sys_version, "")
        self.assertEqual(handler.version_string(fake_handler), "supercontext-local/0.1.0")


class _fixture_snapshot:
    def __init__(
        self,
        extra_consumers: int = 0,
        extra_package_importers: int = 0,
        extra_charge_card_symbol: bool = False,
    ) -> None:
        self.extra_consumers = extra_consumers
        self.extra_package_importers = extra_package_importers
        self.extra_charge_card_symbol = extra_charge_card_symbol

    def __enter__(self) -> KgSnapshot:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        service = Entity(
            kind="Service",
            identity={"tenant_id": "default", "namespace": "default", "slug": "payments", "repo": "payments"},
        )
        caller = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.checkout",
                "qualname": "handle_checkout",
                "symbol_kind": "function",
            },
            properties={"path": "payments/checkout.py", "line": 10, "end_line": 20},
        )
        earlier_symbol = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.checkout",
                "qualname": "bootstrap_checkout",
                "symbol_kind": "function",
            },
            properties={"path": "payments/checkout.py", "line": 1, "end_line": 3},
        )
        module = Entity(
            kind="CodeModule",
            identity={"tenant_id": "default", "repo": "payments", "module": "payments.checkout"},
            properties={"path": "payments/checkout.py"},
        )
        callee = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.gateway",
                "qualname": "charge_card",
                "symbol_kind": "function",
            },
            properties={"path": "payments/gateway.py", "line": 5, "end_line": 12},
        )
        endpoint = Entity(
            kind="Endpoint",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "protocol": "http",
                "method": "POST",
                "path": "/checkout",
                "host": None,
            },
        )
        channel = Entity(
            kind="EventChannel",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "broker_kind": "sqs",
                "channel_address": "orders-created",
                "name": "orders-created",
            },
        )
        domain = Entity(
            kind="Domain",
            identity={"tenant_id": "default", "repo": "payments", "name": "api.internal.example"},
        )
        env_var = Entity(
            kind="EnvVar",
            identity={"tenant_id": "default", "repo": "payments", "name": "PAYMENTS_API_BASE_URL"},
        )
        package = Entity(
            kind="ExternalPackage",
            identity={"tenant_id": "default", "repo": "payments", "name": "shared-lib"},
            properties={"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
        )
        provider_repo = Entity(
            kind="Repo",
            identity={"tenant_id": "default", "host": "local", "owner": "default", "name": "shared-platform"},
        )
        duplicate_callee = Entity(
            kind="CodeSymbol",
            identity={
                "tenant_id": "default",
                "repo": "payments",
                "module": "payments.alt_gateway",
                "qualname": "charge_card",
                "symbol_kind": "function",
            },
            properties={"path": "payments/alt_gateway.py", "line": 7, "end_line": 9},
        )
        call_fact = Fact("CALLS", caller.entity_id, callee.entity_id)
        import_fact = Fact(
            "IMPORTS",
            module.entity_id,
            package.entity_id,
            {"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
        )
        repo_link_fact = Fact(
            "RESOLVES_TO_REPO",
            package.entity_id,
            provider_repo.entity_id,
            {"consumer_repo": "payments", "package_name": "shared-lib"},
        )
        endpoint_fact = Fact("EXPOSES_ENDPOINT", service.entity_id, endpoint.entity_id, {"method": "POST", "path": "/checkout"})
        consume_fact = Fact("CONSUMES_EVENT", service.entity_id, channel.entity_id)
        produce_fact = Fact("PRODUCES_EVENT", caller.entity_id, channel.entity_id)
        domain_fact = Fact("REFERENCES_DOMAIN", env_var.entity_id, domain.entity_id)
        extra_services = [
            Entity(
                kind="Service",
                identity={
                    "tenant_id": "default",
                    "namespace": "default",
                    "slug": f"consumer-{index}",
                    "repo": f"consumer-{index}",
                },
            )
            for index in range(self.extra_consumers)
        ]
        extra_modules = [
            Entity(
                kind="CodeModule",
                identity={"tenant_id": "default", "repo": "payments", "module": f"payments.importer_{index}"},
                properties={"path": f"payments/importer_{index}.py"},
            )
            for index in range(self.extra_package_importers)
        ]
        extra_consume_facts = [Fact("CONSUMES_EVENT", extra_service.entity_id, channel.entity_id) for extra_service in extra_services]
        extra_import_facts = [
            Fact(
                "IMPORTS",
                extra_module.entity_id,
                package.entity_id,
                {"category": "third_party", "import_root": "shared_lib", "distribution_name": "shared-lib"},
            )
            for extra_module in extra_modules
        ]
        evidence = [
            Evidence(
                target_type="entity",
                target_id=service.entity_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                confidence=1.0,
            ),
            Evidence(
                target_type="fact",
                target_id=call_fact.fact_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                bytes_ref={"repo": "payments", "path": "payments/checkout.py", "line_start": 14, "line_end": 14},
                confidence=1.0,
            ),
            Evidence(
                target_type="fact",
                target_id=import_fact.fact_id,
                derivation_class="deterministic_static",
                source_system="test",
                source_ref={"repo": "payments"},
                bytes_ref={"repo": "payments", "path": "payments/checkout.py", "line_start": 2, "line_end": 2},
                confidence=1.0,
            ),
        ]
        entities = [
            service,
            caller,
            earlier_symbol,
            module,
            callee,
            endpoint,
            channel,
            domain,
            env_var,
            package,
            provider_repo,
            *([duplicate_callee] if self.extra_charge_card_symbol else []),
            *extra_services,
            *extra_modules,
        ]
        facts = [
            call_fact,
            import_fact,
            repo_link_fact,
            endpoint_fact,
            consume_fact,
            produce_fact,
            domain_fact,
            *extra_consume_facts,
            *extra_import_facts,
        ]
        JsonlKgStore(root).write(
            entities=entities,
            facts=facts,
            evidence=evidence,
            coverage=[],
            manifest={"counts": {"entities": len(entities), "facts": len(facts)}},
        )
        self._kg = KgSnapshot(root)
        return self._kg

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._tmpdir.cleanup()


class _FakeHttpHandler:
    def __init__(self, headers: dict[str, str], *, body: bytes = b"", rfile: object | None = None) -> None:
        self.headers = headers
        self.connection = _FakeConnection()
        self.rfile = rfile or io.BytesIO(body)


class _FakeConnection:
    def __init__(self) -> None:
        self.timeout: float | None = None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class _TimeoutReader:
    def read(self, size: int) -> bytes:
        raise TimeoutError("stalled")


if __name__ == "__main__":
    unittest.main()
