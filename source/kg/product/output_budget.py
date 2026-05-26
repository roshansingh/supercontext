from __future__ import annotations

from copy import deepcopy

from source.kg.core.models import JsonObject, canonical_json


PLANNING_CONTEXT_MAX_CHARS = 20_000
# Anchored packets serve detailed follow-up questions, so they preserve more
# evidence while still staying below typical MCP message-size limits.
PLANNING_CONTEXT_ANCHORED_MAX_CHARS = 150_000
COMPACT_RUNTIME_COMPONENT_LIMIT = 4
COMPACT_RUNTIME_ROUTE_LIMIT = 15

_RUNTIME_COMPONENTS_PATH = "runtime_architecture.answer_packet.runtime_building_blocks"
_RUNTIME_ROUTES_PATH = "runtime_architecture.answer_packet.domain_routing_map"
_PLANNING_BUDGET_ADVICE = (
    "Use narrower or additional planning_context anchors such as repo+service, domain+repo, endpoint, path, or line "
    "to retrieve omitted runtime detail."
)


def enforce_planning_context_budget(
    result: JsonObject,
    *,
    max_chars: int = PLANNING_CONTEXT_MAX_CHARS,
    preserve_planning_sections: bool = False,
) -> JsonObject:
    measured_chars = len(canonical_json(result))
    if measured_chars <= max_chars:
        return result

    original_counts = _runtime_answer_counts(result)
    original_result = deepcopy(result)
    result = deepcopy(original_result)
    for component_limit, route_limit in (
        (COMPACT_RUNTIME_COMPONENT_LIMIT, COMPACT_RUNTIME_ROUTE_LIMIT),
        (1, COMPACT_RUNTIME_ROUTE_LIMIT),
        (0, COMPACT_RUNTIME_ROUTE_LIMIT),
        (0, max(1, COMPACT_RUNTIME_ROUTE_LIMIT // 2)),
    ):
        _truncate_runtime_answer(result, component_limit=component_limit, route_limit=route_limit)
        _attach_budget_metadata(
            result,
            measured_chars=measured_chars,
            max_chars=max_chars,
            original_counts=original_counts,
        )
        post_chars = _current_chars(result)
        if post_chars <= max_chars:
            return result

    for component_limit, route_limit in (
        (COMPACT_RUNTIME_COMPONENT_LIMIT, COMPACT_RUNTIME_ROUTE_LIMIT),
        (1, COMPACT_RUNTIME_ROUTE_LIMIT),
        (0, COMPACT_RUNTIME_ROUTE_LIMIT),
        (0, max(1, COMPACT_RUNTIME_ROUTE_LIMIT // 2)),
        (1, 1),
    ):
        fallback_source = deepcopy(original_result)
        _truncate_runtime_answer(fallback_source, component_limit=component_limit, route_limit=route_limit)
        fallback = _planning_context_fallback(fallback_source, preserve_planning_sections=preserve_planning_sections)
        _attach_budget_metadata(
            fallback,
            measured_chars=measured_chars,
            max_chars=max_chars,
            original_counts=original_counts,
            fallback=True,
        )
        fallback_post_chars = _current_chars(fallback)
        if fallback_post_chars <= max_chars:
            return fallback

    minimal_source = deepcopy(original_result)
    _truncate_runtime_answer(minimal_source, component_limit=0, route_limit=max(1, COMPACT_RUNTIME_ROUTE_LIMIT))
    minimal = _planning_context_fallback(minimal_source, preserve_planning_sections=preserve_planning_sections)
    _minimize_runtime_answer_rows(minimal)
    _attach_budget_metadata(
        minimal,
        measured_chars=measured_chars,
        max_chars=max_chars,
        original_counts=original_counts,
        fallback=True,
        minimized=True,
    )
    if _current_chars(minimal) <= max_chars:
        return minimal

    final = _minimal_valid_packet(original_result)
    _attach_budget_metadata(
        final,
        measured_chars=measured_chars,
        max_chars=max_chars,
        original_counts=original_counts,
        fallback=True,
        minimized=True,
    )
    if _current_chars(final) > max_chars:
        final["output_budget"]["exceeded_after_minimization"] = True
    return final


def _runtime_answer_counts(result: JsonObject) -> dict[str, int]:
    runtime = result.get("runtime_architecture")
    if not isinstance(runtime, dict):
        return {"runtime_building_blocks": 0, "domain_routing_map": 0}
    summary = runtime.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    answer_packet = runtime.get("answer_packet")
    if not isinstance(answer_packet, dict):
        answer_packet = {}
    components = answer_packet.get("runtime_building_blocks")
    routes = answer_packet.get("domain_routing_map")
    return {
        "runtime_building_blocks": _int_count(
            summary.get("runtime_building_block_count"),
            fallback=len(components) if isinstance(components, list) else 0,
        ),
        "domain_routing_map": _int_count(
            summary.get("domain_routing_map_count"),
            fallback=len(routes) if isinstance(routes, list) else 0,
        ),
    }


def _int_count(value: object, *, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int) and value >= 0:
        return value
    return fallback


def _truncate_runtime_answer(result: JsonObject, *, component_limit: int, route_limit: int) -> None:
    runtime = result.get("runtime_architecture")
    if not isinstance(runtime, dict):
        return
    answer_packet = runtime.get("answer_packet")
    if not isinstance(answer_packet, dict):
        return
    components = answer_packet.get("runtime_building_blocks")
    if isinstance(components, list):
        answer_packet["runtime_building_blocks"] = components[:component_limit]
    routes = answer_packet.get("domain_routing_map")
    if isinstance(routes, list):
        answer_packet["domain_routing_map"] = routes[:route_limit]


def _attach_budget_metadata(
    result: JsonObject,
    *,
    measured_chars: int,
    max_chars: int,
    original_counts: dict[str, int],
    fallback: bool = False,
    minimized: bool = False,
) -> None:
    shown_counts = _runtime_answer_shown_counts(result)
    omitted_counts = {
        key: max(0, original_counts.get(key, 0) - shown_counts.get(key, 0))
        for key in ("runtime_building_blocks", "domain_routing_map")
    }
    truncated_sections = []
    if omitted_counts["runtime_building_blocks"] > 0:
        truncated_sections.append(_RUNTIME_COMPONENTS_PATH)
    if omitted_counts["domain_routing_map"] > 0:
        truncated_sections.append(_RUNTIME_ROUTES_PATH)
    advice = _PLANNING_BUDGET_ADVICE
    if fallback:
        advice += " The response also dropped non-essential planning sections to preserve a valid JSON packet."
    if minimized:
        advice += " Oversized row payloads were minimized to status, identity, and evidence coordinates."
    result["output_budget"] = {
        "truncated": True,
        "measured_chars": measured_chars,
        "max_chars": max_chars,
        "omitted_counts": omitted_counts,
        "truncated_sections": truncated_sections,
        "advice": advice,
        "fallback": fallback,
        "minimized": minimized,
    }


def _current_chars(result: JsonObject) -> int:
    return len(canonical_json(result))


def _runtime_answer_shown_counts(result: JsonObject) -> dict[str, int]:
    runtime = result.get("runtime_architecture")
    if not isinstance(runtime, dict):
        return {"runtime_building_blocks": 0, "domain_routing_map": 0}
    answer_packet = runtime.get("answer_packet")
    if not isinstance(answer_packet, dict):
        return {"runtime_building_blocks": 0, "domain_routing_map": 0}
    components = answer_packet.get("runtime_building_blocks")
    routes = answer_packet.get("domain_routing_map")
    return {
        "runtime_building_blocks": len(components) if isinstance(components, list) else 0,
        "domain_routing_map": len(routes) if isinstance(routes, list) else 0,
    }


def _planning_context_fallback(result: JsonObject, *, preserve_planning_sections: bool) -> JsonObject:
    runtime = result.get("runtime_architecture")
    compact_runtime: JsonObject = {}
    if isinstance(runtime, dict):
        answer_packet = runtime.get("answer_packet")
        compact_answer: JsonObject = {}
        if isinstance(answer_packet, dict):
            compact_answer = {
                "runtime_building_blocks": _list_value(answer_packet.get("runtime_building_blocks")),
                "domain_routing_map": _list_value(answer_packet.get("domain_routing_map")),
                "deploy_kind_counts": answer_packet.get("deploy_kind_counts", {}),
                "evidence_contract": answer_packet.get("evidence_contract"),
            }
        compact_runtime = {
            "scope": runtime.get("scope", {}),
            "summary": runtime.get("summary", {}),
            "answer_packet": compact_answer,
            "assembly_contract": runtime.get("assembly_contract"),
        }
    fallback = {
        "tool": result.get("tool"),
        "status": result.get("status"),
        "query": result.get("query"),
        "summary": result.get("summary", {}),
        "snapshot_summary": result.get("snapshot_summary", {}),
        "snapshot_scope": result.get("snapshot_scope", {}),
        "runtime_architecture": compact_runtime,
        "anchors": result.get("anchors", {}),
        "answerability": result.get("answerability", {}),
        "coverage_warnings": result.get("coverage_warnings", []),
        "unsupported_scopes": result.get("unsupported_scopes", []),
        "next_actions": result.get("next_actions", []),
    }
    if preserve_planning_sections:
        fallback.update(
            {
                "inventory": result.get("inventory", {}),
                "service_operational_surfaces": result.get("service_operational_surfaces", {}),
                "services": result.get("services", []),
                "symbols": result.get("symbols", []),
                "dependencies": result.get("dependencies", []),
                "endpoints": result.get("endpoints", []),
                "endpoint_consumers": result.get("endpoint_consumers", []),
                "event_channels": result.get("event_channels", []),
                "domains": result.get("domains", []),
                "entry_points": result.get("entry_points", {}),
                "related_facts": result.get("related_facts", {}),
                "source_coordinates": result.get("source_coordinates", []),
            }
        )
    return {key: value for key, value in fallback.items() if value is not None}


def _minimize_runtime_answer_rows(result: JsonObject) -> None:
    answer_packet = _runtime_answer_packet(result)
    if answer_packet is None:
        return
    for key in ("runtime_building_blocks", "domain_routing_map"):
        rows = answer_packet.get(key)
        if not isinstance(rows, list):
            continue
        answer_packet[key] = [_minimal_runtime_row(row) for row in rows if isinstance(row, dict)]


def _runtime_answer_packet(result: JsonObject) -> JsonObject | None:
    runtime = result.get("runtime_architecture")
    if not isinstance(runtime, dict):
        return None
    answer_packet = runtime.get("answer_packet")
    if not isinstance(answer_packet, dict):
        return None
    return answer_packet


def _minimal_runtime_row(row: JsonObject) -> JsonObject:
    keys = (
        "status",
        "component_id",
        "name",
        "repo",
        "runtime_categories",
        "deploy_kinds",
        "domain",
        "target",
        "services",
        "source",
        "deploy_kind",
        "route_source_kind",
        "evidence_coordinates",
        "interpretation",
    )
    return {key: row[key] for key in keys if key in row}


def _minimal_valid_packet(result: JsonObject) -> JsonObject:
    runtime = result.get("runtime_architecture")
    compact_runtime: JsonObject = {}
    if isinstance(runtime, dict):
        answer_packet = runtime.get("answer_packet")
        compact_answer = {}
        if isinstance(answer_packet, dict):
            compact_answer = {
                "deploy_kind_counts": answer_packet.get("deploy_kind_counts", {}),
                "evidence_contract": answer_packet.get("evidence_contract"),
            }
        compact_runtime = {
            "scope": runtime.get("scope", {}),
            "summary": runtime.get("summary", {}),
            "answer_packet": compact_answer,
            "assembly_contract": runtime.get("assembly_contract"),
        }
    return {
        "tool": result.get("tool"),
        "status": result.get("status"),
        "query": result.get("query"),
        "summary": result.get("summary", {}),
        "snapshot_summary": result.get("snapshot_summary", {}),
        "snapshot_scope": result.get("snapshot_scope", {}),
        "runtime_architecture": compact_runtime,
        "anchors": result.get("anchors", {}),
        "answerability": result.get("answerability", {}),
        "coverage_warnings": [],
        "unsupported_scopes": [],
        "next_actions": result.get("next_actions", []),
    }


def _list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return value
