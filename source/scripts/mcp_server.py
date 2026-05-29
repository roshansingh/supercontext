from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from source.kg.core.models import JsonObject, canonical_json
from source.kg.product.mcp_tools import call_tool, tool_definitions
from source.kg.product.output_budget import render_grep_response
from source.kg.query.snapshot import KgSnapshot
from source.scripts.mcp_host import format_host_for_url, is_loopback_host


MCP_PROTOCOL_VERSION = "2025-03-26"
REQUEST_READ_TIMEOUT_SECONDS = 5.0
# This initialize.instructions block is the load-bearing agent contract for
# SuperContext MCP behavior; keep anti-overclaim rules here, not per tool.
SUPERCONTEXT_MCP_INSTRUCTIONS = """# SuperContext KG

Use SuperContext as a source-inspection head start. Default tool results are compact grep-style packets with grep-style rows. Read `status`, `answerability`, `boundary`, `covered`, and `must_inspect` first, then scan `rows` shaped as `locator [tag] category fact`. Open cited source or follow `next` for a narrower anchor; verify partial, candidate, risky, or code-detail claims with ordinary source tools.

## Tool Routing

- Broad planning/arch/deps/ownership/runtime/domain/inventory/impact -> planning_context first.
- PR/review with changed files/ranges -> review_context first.
- Reverse callers -> find_callers; transitive reverse impact -> reverse_impact.
- Callees -> find_callees; downstream static CALLS closure -> blast_radius.
- Service facts -> get_service_brief.
- Event producers/consumers -> get_event_producers/get_event_consumers.

## Result Contract

Default results contain `tool`, `query`, `status`, `answerability`, `boundary`, `covered`, `must_inspect`, `shown`, `more`, `rows`, `gaps`, and `next`. `[proven]` rows are KG-backed/static source pointers, not a substitute for reading code when editing or making risky claims. `[candidate]` and `[candidate:*]` rows are inspection leads only. `covered` says which fact families are already represented. `must_inspect` points to omitted or unproven areas with coordinates/search terms when available. `gaps` names what SuperContext could not prove. `next` is one narrower MCP call or source-inspection lead.

## Behavior Rules

- Graph miss is not absence: partial/not_found/unsupported_by_current_kg/indexed_scope_no_match need source inspection; indexed_scope_no_match only proves scoped inventory.
- Runtime windows, event/deploy safety, and dynamic dispatch need source/config/ops evidence.
- Ambiguous symbol results are not empty impact/caller proof. Use `next` or path/line anchors; candidate preview rows are scan-order/risk hints, not intent proof.
- Do not use a first source-search hit as a symbol anchor unless user/disambiguation supplied it.
- For not_found event/symbol rows, use near matches, indexed counts, candidate rows, `gaps`, and `next` as inspection leads before absence claims.
- Keep known_linked, unlinked_evidence, and missing_contracts separate. Only linked deploy facts / DEPLOYS_VIA_CONFIG prove service-to-deploy evidence; unlinked routes are inspection leads.
- Package authors/maintainers are candidates only; service owners require CODEOWNERS/catalog/explicit metadata.
- Missing declared authz policy is an inspection lead, not public-access proof.
- client_endpoint_call_count is path-scoped; inspect method/host/env before runtime dependency claims.
- deploy_order_guidance is inference, not a canonical deploy-blocker fact.

## Anti-Patterns

- Do not finalize partial results without checking relevant `gaps` / `next` leads or saying what remains unknown.
- Do not copy raw packets; summarize with citations.
- Do not trust partial multi-repo evidence without verification.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local read-only SuperContext MCP server.")
    parser.add_argument("--snapshot", required=True, help="Directory containing JSONL KG snapshot files")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=3845, help="Port to bind. Defaults to 3845.")
    parser.add_argument("--allow-public", action="store_true", help="Allow binding to non-loopback hosts. Unsafe without auth.")
    args = parser.parse_args()
    if not args.allow_public and not is_loopback_host(args.host):
        parser.error("local MCP server has no authentication; bind to loopback or pass --allow-public explicitly")

    kg = KgSnapshot(args.snapshot)
    server = _server_class_for_host(args.host)(_server_address_for_host(args.host, args.port), _handler_class(kg))
    print(f"SuperContext MCP server listening on http://{format_host_for_url(args.host)}:{args.port}/mcp", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler_class(kg: KgSnapshot) -> type[BaseHTTPRequestHandler]:
    class McpHandler(BaseHTTPRequestHandler):
        server_version = "supercontext-local/0.1.0"
        sys_version = ""

        def version_string(self) -> str:
            return self.server_version

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write_json(200, {"status": "ok"})
                return
            self._write_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/mcp":
                self._write_json(404, {"error": "not_found"})
                return
            try:
                body = _read_request_body(self, _content_length(self))
            except _RequestBodyTimeout as exc:
                self._write_json(408, {"error": "request_timeout", "message": str(exc)})
                return
            except ValueError as exc:
                self._write_json(400, {"error": "invalid_request", "message": str(exc)})
                return
            try:
                payload = _decode_json_payload(body)
            except _JsonPayloadError as exc:
                response = _json_rpc_error(None, -32700, f"Invalid JSON-RPC request: {exc}")
                self._write_json(200, response)
                return
            response = _handle_json_rpc_payload(kg, payload)
            if response is None:
                self.send_response(204)
                self.end_headers()
                return
            self._write_json(200, response)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _write_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    # The captured KgSnapshot is shared across request threads. Server handlers
    # must treat it as read-only; mutation belongs in snapshot rebuild commands.
    return McpHandler


def _content_length(handler: BaseHTTPRequestHandler) -> int:
    raw_value = handler.headers.get("Content-Length")
    if raw_value is None:
        raise ValueError("Missing Content-Length header")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("Content-Length must be an integer") from exc
    if value < 0 or value > 1_000_000:
        raise ValueError("Content-Length is outside the accepted range")
    return value


class _RequestBodyTimeout(TimeoutError):
    pass


def _read_request_body(handler: BaseHTTPRequestHandler, content_length: int) -> bytes:
    handler.connection.settimeout(REQUEST_READ_TIMEOUT_SECONDS)
    try:
        body = handler.rfile.read(content_length)
    except TimeoutError as exc:
        raise _RequestBodyTimeout("Timed out reading request body") from exc
    if len(body) != content_length:
        raise ValueError("Request body ended before Content-Length bytes were received")
    return body


_is_loopback_host = is_loopback_host
_format_host_for_url = format_host_for_url


def _server_class_for_host(host: str) -> type[ThreadingHTTPServer]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return ThreadingHTTPServer
    if address.version != 6:
        return ThreadingHTTPServer

    class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    return IPv6ThreadingHTTPServer


def _server_address_for_host(host: str, port: int) -> tuple[str, int] | tuple[str, int, int, int]:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return (host, port)
    if address.version == 6:
        return (host, port, 0, 0)
    return (host, port)


class _JsonPayloadError(ValueError):
    pass


def _decode_json_payload(body: bytes) -> object:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _JsonPayloadError(f"invalid UTF-8: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise _JsonPayloadError(str(exc)) from exc


def _handle_json_rpc_payload(kg: KgSnapshot, payload: object) -> object | None:
    if isinstance(payload, list):
        if not payload:
            return _json_rpc_error(None, -32600, "JSON-RPC batch must not be empty")
        responses = [row for row in (_handle_json_rpc(kg, item) for item in payload) if row is not None]
        return responses or None
    return _handle_json_rpc(kg, payload)


def _handle_json_rpc(kg: KgSnapshot, request: object) -> JsonObject | None:
    if not isinstance(request, dict):
        return _json_rpc_error(None, -32600, "JSON-RPC request must be an object")
    has_id = "id" in request
    request_id = request.get("id") if has_id else None
    if has_id and not _valid_request_id(request_id):
        return _json_rpc_error(None, -32600, "JSON-RPC id must be a string, number, or null")
    if request.get("jsonrpc") != "2.0":
        return _json_rpc_error(request_id, -32600, "JSON-RPC version must be 2.0")
    method = request.get("method")
    if not isinstance(method, str) or not method:
        return _json_rpc_error(request_id, -32600, "JSON-RPC method must be a non-empty string")
    params = request.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _json_rpc_error(request_id, -32602, "JSON-RPC params must be an object")

    is_notification = not has_id
    try:
        if method == "initialize":
            return None if is_notification else _json_rpc_result(request_id, _initialize_result(params))
        if method == "tools/list":
            return None if is_notification else _json_rpc_result(request_id, {"tools": tool_definitions()})
        if method == "tools/call":
            return None if is_notification else _json_rpc_result(request_id, _tools_call_result(kg, params))
        if method == "ping":
            return None if is_notification else _json_rpc_result(request_id, {})
    except ValueError as exc:
        return None if is_notification else _json_rpc_error(request_id, -32602, str(exc))
    except Exception:
        print("Unhandled MCP JSON-RPC error", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None if is_notification else _json_rpc_error(request_id, -32000, "Internal MCP server error")
    return None if is_notification else _json_rpc_error(request_id, -32601, f"Unsupported MCP method: {method}")


def _valid_request_id(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    return isinstance(value, (str, int, float))


def _initialize_result(params: JsonObject) -> JsonObject:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "supercontext-local", "version": "0.1.0"},
        "instructions": SUPERCONTEXT_MCP_INSTRUCTIONS,
    }


def _tools_call_result(kg: KgSnapshot, params: JsonObject) -> JsonObject:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name.strip():
        raise ValueError("tools/call requires a non-empty string name")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("tools/call arguments must be an object")
    result = _render_tool_result_for_transport(call_tool(kg, name.strip(), arguments))
    return {
        "content": [{"type": "text", "text": canonical_json(result)}],
        "structuredContent": result,
        "isError": False,
    }


def _render_tool_result_for_transport(result: JsonObject) -> JsonObject:
    try:
        return render_grep_response(result)
    except Exception as exc:
        tool = result.get("tool") if isinstance(result.get("tool"), str) else "unknown"
        print(
            f"SuperContext MCP renderer failed for tool={tool}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        query = result.get("query") or result.get("symbol") or result.get("service") or ""
        return {
            "tool": tool,
            "query": str(query),
            "status": "partial",
            "answerability": "partial: MCP renderer failed; use this as an inspection-only result.",
            "boundary": "render_error: do not treat missing rows as absence; inspect source or retry with a narrower anchor.",
            "covered": [],
            "must_inspect": ["render_error: inspect source and retry the MCP tool with narrower arguments if useful"],
            "shown": 0,
            "more": 0,
            "rows": [],
            "gaps": f"render_error:{type(exc).__name__}",
            "next": "inspect source; retry the same MCP tool with narrower arguments if useful",
        }


def _json_rpc_result(request_id: object, result: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(request_id: object, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
