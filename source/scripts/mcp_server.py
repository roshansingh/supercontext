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
from source.kg.query.snapshot import KgSnapshot
from source.scripts.mcp_host import format_host_for_url, is_loopback_host


MCP_PROTOCOL_VERSION = "2025-03-26"
REQUEST_READ_TIMEOUT_SECONDS = 5.0
SUPERCONTEXT_MCP_INSTRUCTIONS = """# SuperContext - repository knowledge graph

SuperContext provides deterministic, source-cited context from the indexed repository graph. Use it as a source-inspection head start, not a complete or final answer: it routes you to evidence to verify, then you finish with ordinary source inspection when the graph is partial, compacted, or when code details matter. SuperContext is an evidence router, not an answer oracle. SuperContext is never a replacement for source inspection, semantic search, runtime/config review, or the agent's own judgement.

## Tool selection by intent

- Broad planning, architecture, dependency, or impact question with a repo, service, symbol, package, endpoint, event channel, domain, or path anchor -> planning_context first.
- PR or code review question with changed files or line ranges -> review_context first, then targeted primitive tools or source reads.
- Exact reverse callers for a known symbol -> find_callers.
- Reverse dependency or caller-impact analysis from a resolved symbol anchor -> reverse_impact.
- Exact downstream callees for a known symbol -> find_callees.
- Static downstream call closure from an exact edit-site symbol -> blast_radius.
- Service endpoint/event/deploy fact sheet -> get_service_brief.
- Exact event channel producers or consumers -> get_event_producers or get_event_consumers.
- KG inventory or repo coverage summary -> planning_context and read snapshot_summary/snapshot_scope.
- Runtime architecture or domain-routing map -> planning_context first and read runtime_architecture.answer_packet.investigation_brief before source inspection. If runtime_architecture.summary.answer_packet_mode is investigation_brief_only, retry with narrower anchors before treating runtime maps or counts as answer facts; otherwise read runtime_building_blocks, domain_routing_map, unlinked_deploy_leads, and deploy_kind_counts while keeping component deploy counts separate from unlinked route/deploy leads.
- Service/repo ownership question -> planning_context first and read ownership_context.answer_packet; package authors and package maintainers are candidates only, not service owners, unless explicit CODEOWNERS/catalog/owner metadata proves ownership.
- Endpoint authorization/security question -> planning_context first and read top-level authz_surface.review_leads, applied_policies, in_method_checks, inspection_areas, inspection_index, and unsupported_scopes when present, related_facts.authz_surface as a compact reference, or get_service_brief.authz_surface for a known service; treat missing_declared_policy as a source-inspection lead, not proof of public access.

If this endpoint is backed by an org snapshot served with `supercontext org serve`, use the same planning_context and review_context tools; the snapshot scope is wider, but the MCP tool surface is unchanged. For org snapshots, pass `repo` anchors explicitly, using either `repo` or `owner/repo` when the review target is known.

## Common packet contract

Every tool result includes common evidence fields: `answerability`, `proven_facts`, `candidate_leads`, `coverage_gaps`, and `inspection_areas`. Normal packets also include `packet_contract`; extreme budget fallback packets may omit static legends to preserve evidence. Large planning, review, impact, and service-brief packets may include `output_budget`. Treat the evidence fields as the normalized first-read fields across all tools. Use `proven_facts` to find the strongest KG-backed fields, then cite the underlying evidence rows or file/line coordinates. Use `candidate_leads` and `inspection_areas` as the bounded source-inspection plan for uncovered tests, scripts, notebooks, entry points, import-only consumers, config, manifests, runtime routes, or other areas outside the proven packet. If `output_budget.truncated` is true, treat it as truncation metadata, not absence proof: `output_budget.truncated_sections` lists the sampled arrays (planning packets also carry `omitted_counts`/`backfilled_counts`); follow returned inspection refs/search terms or call narrower anchors for the sampled categories that matter. Use `coverage_gaps` to state what the graph could not prove. Do not claim candidate leads, missing gaps, or unsupported scopes as facts until source inspection verifies them. Never assert that SuperContext alone fully resolved the user's question; `answerability.status: answerable` means relevant KG evidence exists inside the current graph scope, not that the whole repository/runtime/deploy/security question is globally answered. For non-trivial planning, review, impact, runtime, deploy, ownership, or safety questions, final answers should separate MCP head start, source-verified claims, candidate or unlinked leads, coverage gaps or unknowns, and next source/config/runtime inspection. Answer the user's question first; keep extra MCP rows as inspection leads unless the user asks for exploratory coverage.

## Evidence gates

Before finalizing, split the user request into named answer categories and mark each category as KG-backed, source-verified, candidate, contradicted, unknown, or out-of-scope. Treat requested answer categories as coverage obligations to answer or mark unknown, not permission to expand into every packet row. If an MCP result is ambiguous, retry one exact `disambiguation.retry_arguments` candidate or returned path/qualified name before interpreting empty rows. If a result is partial, not_found, not_answerable, or unsupported_by_current_kg, treat it as an anchor or coverage gap, not a final refusal; use your normal search/read tools at least once before refusing or saying unknown. If a packet spills to a saved file, use a narrower MCP anchor or returned source refs/search terms instead of making jq/file archaeology the main workflow. For count/list/impact answers, verify that the final count matches the detailed evidence or inspected source rows. Final answers must separate KG-backed facts, source-verified facts, candidates, contradictions, and unknowns. Keep final answers focused on scoped findings, evidence, and unknowns; do not include internal progress commentary.

## Answerability

Read answerability, proven_facts, candidate_leads, coverage_gaps, inspection_areas, coverage_warnings, unsupported_scopes, and next_actions before finalizing. If a SuperContext result is partial, ambiguous, unsupported_by_current_kg, not_found, or not_answerable, say what the graph could not prove and use your normal search/read tools at least once before finalizing. For runtime event time windows and deploy-safety claims, static graph facts are context only; inspect operational/config/source evidence. Do not treat a graph miss as proof of absence.

For planning_context runtime architecture, unresolved or ambiguous anchors expose runtime_architecture.answer_packet as investigation_brief_only. Treat that as source-inspection context, not a resolved architecture or domain-routing answer, and retry with narrower repo/service/domain/endpoint anchors when runtime detail matters.

For symbol callers, reverse impact, callees, and blast-radius tools, an ambiguous result means no exact result was computed. Do not interpret an empty callers/edges/callees list as absence; use disambiguation.retry_arguments, candidate_impact_previews, a candidate qualified_name, or candidate path+line to retry the exact symbol. If a not_found result carries a top-level `coordinate_mismatch` with answerability missing `correct_coordinate`, the symbol exists at a different path/line; retry one `coordinate_mismatch.retry_arguments` entry before treating it as a missing symbol or an empty result. For reverse dependency or caller-impact analysis, prefer reverse_impact over manually chaining repeated find_callers calls, then verify the returned source coordinates and `inspection_areas`; `source_inspection_areas` is a compatibility alias with tool-specific detail.

When the user gives only an unqualified symbol name, call the symbol tool with that name first so SuperContext can return candidate ambiguity. Do not add path or line from a first source-search hit unless the user supplied that location or a prior SuperContext disambiguation candidate did.

For ambiguous symbol-impact results, do not aggregate all candidates unless the user asks for all matches or exploratory impact. Use candidate_impact_previews as ranking hints, then retry one exact candidate when the intended edit site is clear; otherwise report the ambiguity and ask for path/line.

For service operational evidence, read operational_surfaces.evidence_partition or service_operational_surfaces.evidence_partition. Keep known_linked, unlinked_evidence, and missing_contracts separate: known_linked is exact KG/repo-linked evidence, unlinked_evidence is source leads only, and missing_contracts are claims the KG cannot prove. Treat deploy_link_facts / known DEPLOYS_VIA_CONFIG as service-to-deploy-target evidence; do not promote candidate_or_unlinked_deploy_links or unlinked domain routes into deploy proof.

For PR review impact, read review_context.review_answer_packet first, then review_context.application_impact alongside framework_impact and runtime_surfaces. When the prompt names expected impact categories such as UI screens, scheduled jobs, SQS consumers, delivery workers, tracking paths, schemas, or contracts, pass requested_surfaces so surface_status can separate inventory_context, unlinked_lead, and missing evidence; broad answer categories such as services and deployables are covered by other review packet sections rather than dedicated surface filters. surface_status inventory_context rows are source-inspection leads, not proof that the named surface is affected by the change. If changed_ranges were not supplied, review_context.review_answer_packet.top_changed_symbols is empty and review_context.review_answer_packet.changed_file_symbol_inventory contains changed-file symbol inventory; top-level changed_symbols is a compatibility changed-file symbol inventory field, not proof that every listed function changed. Say "symbols in changed files" or inspect the diff before saying a function was touched. Owner/maintainer requests in review_context are explicit ownership_context coverage gaps; use planning_context with the repo or service and read ownership_context.answer_packet before claiming owners. application_impact groups same-repo app/package namespace surfaces such as API, models, serializers, workers, and scheduled jobs as context, and separates app-scoped runtime facts from unlinked cross-repo name leads. Use cross_repo_name_leads only as source-inspection leads, not as proven impact. For reverse_impact, keep static CALLS rows, terminal_import_consumer_leads, and omitted inspection refs in separate counts; terminal import leads are not runtime-call proof. Known event, endpoint, or contract rows do not prove deploy or safety readiness when unresolved consumers, missing fact families, unsupported scopes, or coverage gaps remain; separate known rows from the safety refusal.
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
    result = call_tool(kg, name.strip(), arguments)
    return {
        # Serialize the text block with canonical_json — the exact form the output budgeter
        # measures against — so the on-the-wire size matches the enforced cap (and drops the
        # ~2.5x pretty-print bloat). structuredContent carries the same parsed object.
        "content": [{"type": "text", "text": canonical_json(result)}],
        "structuredContent": result,
        "isError": False,
    }


def _json_rpc_result(request_id: object, result: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _json_rpc_error(request_id: object, code: int, message: str) -> JsonObject:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
