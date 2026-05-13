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
    _content_length,
    _decode_json_payload,
    _format_host_for_url,
    _handler_class,
    _handle_json_rpc,
    _handle_json_rpc_payload,
    _is_loopback_host,
    _server_address_for_host,
    _server_class_for_host,
)


class McpToolsTest(unittest.TestCase):
    def test_tool_definitions_match_adr_0002_names(self) -> None:
        definitions = tool_definitions()
        self.assertEqual([row["name"] for row in definitions], list(TOOL_NAMES))
        schemas = {row["name"]: row["inputSchema"] for row in definitions}
        self.assertEqual(schemas["search_services"]["properties"]["query"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["path"]["type"], ["string", "null"])
        self.assertEqual(schemas["find_callers"]["properties"]["line"]["type"], ["integer", "null"])

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
        self.assertEqual(missing["status"], "not_found")

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

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "supercontext-local")
        self.assertEqual(initialized["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(initialized_with_client_version["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(ping["result"], {})
        self.assertEqual(batch[0]["id"], 3)
        self.assertEqual(listed["result"]["tools"][0]["name"], "search_services")
        self.assertEqual(called["result"]["structuredContent"]["status"], "found")
        self.assertFalse(called["result"]["isError"])

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
    def __init__(self, extra_consumers: int = 0) -> None:
        self.extra_consumers = extra_consumers

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
        call_fact = Fact("CALLS", caller.entity_id, callee.entity_id)
        endpoint_fact = Fact("EXPOSES_ENDPOINT", service.entity_id, endpoint.entity_id, {"method": "POST", "path": "/checkout"})
        consume_fact = Fact("CONSUMES_EVENT", service.entity_id, channel.entity_id)
        produce_fact = Fact("PRODUCES_EVENT", caller.entity_id, channel.entity_id)
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
        extra_consume_facts = [Fact("CONSUMES_EVENT", extra_service.entity_id, channel.entity_id) for extra_service in extra_services]
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
        ]
        entities = [service, caller, callee, endpoint, channel, *extra_services]
        facts = [call_fact, endpoint_fact, consume_fact, produce_fact, *extra_consume_facts]
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
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


if __name__ == "__main__":
    unittest.main()
