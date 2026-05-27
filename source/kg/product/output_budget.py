from __future__ import annotations

from copy import deepcopy

from source.kg.core.models import JsonObject, canonical_json


# Fleet runtime architecture questions need a compact head-start packet that
# still carries known routes plus high-value unlinked leads. Keep this below the
# server-side MCP spill threshold while avoiding 20k packet starvation.
PLANNING_CONTEXT_MAX_CHARS = 40_000
# Anchored packets serve detailed follow-up questions, so they preserve more
# evidence while still staying below typical MCP message-size limits.
PLANNING_CONTEXT_ANCHORED_MAX_CHARS = 150_000
COMPACT_RUNTIME_COMPONENT_LIMIT = 4
COMPACT_RUNTIME_ROUTE_LIMIT = 15
COMPACT_RUNTIME_HEADSTART_LIMIT = 8
COMPACT_RUNTIME_LEAD_LIMIT = 8
COMPACT_RUNTIME_DEPLOY_UNIT_LIMIT = 2
COMPACT_RUNTIME_SOURCE_CHECK_LIMIT = 15

_RUNTIME_COMPONENTS_PATH = "runtime_architecture.answer_packet.runtime_building_blocks"
_RUNTIME_ROUTES_PATH = "runtime_architecture.answer_packet.domain_routing_map"
_RUNTIME_DEPLOY_UNITS_PATH = "runtime_architecture.answer_packet.deploy_runtime_map"
_RUNTIME_CONSUMERS_PATH = "runtime_architecture.answer_packet.endpoint_consumer_map"
_RUNTIME_DEPLOY_GUIDANCE_PATH = "runtime_architecture.answer_packet.deploy_order_guidance"
_RUNTIME_INVESTIGATION_BRIEF_PATH = "runtime_architecture.answer_packet.investigation_brief"
_PLANNING_BUDGET_ADVICE = (
    "Use runtime_architecture.answer_packet.investigation_brief as the source-inspection head start, then use narrower "
    "planning_context anchors such as repo+service, domain+repo, endpoint, path, or line to retrieve omitted runtime detail."
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
        "investigation_brief": _int_count(
            summary.get("investigation_brief_anchor_count"),
            fallback=_investigation_brief_anchor_count(answer_packet.get("investigation_brief")),
        ),
        "runtime_building_blocks": _int_count(
            summary.get("runtime_building_block_count"),
            fallback=len(components) if isinstance(components, list) else 0,
        ),
        "domain_routing_map": _int_count(
            summary.get("domain_routing_map_count"),
            fallback=len(routes) if isinstance(routes, list) else 0,
        ),
        "deploy_runtime_map": _int_count(
            summary.get("deploy_runtime_unit_count"),
            fallback=_answer_list_len(answer_packet, "deploy_runtime_map"),
        ),
        "endpoint_consumer_map": _int_count(
            summary.get("endpoint_consumer_map_count"),
            fallback=_answer_list_len(answer_packet, "endpoint_consumer_map"),
        ),
        "deploy_order_guidance": _int_count(
            summary.get("deploy_order_guidance_count"),
            fallback=_answer_list_len(answer_packet, "deploy_order_guidance"),
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
    for key in ("deploy_runtime_map", "endpoint_consumer_map", "deploy_order_guidance"):
        rows = answer_packet.get(key)
        if isinstance(rows, list):
            answer_packet[key] = rows[:route_limit]


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
        for key in (
            "investigation_brief",
            "runtime_building_blocks",
            "domain_routing_map",
            "deploy_runtime_map",
            "endpoint_consumer_map",
            "deploy_order_guidance",
        )
    }
    truncated_sections = []
    if omitted_counts["investigation_brief"] > 0:
        truncated_sections.append(_RUNTIME_INVESTIGATION_BRIEF_PATH)
    if omitted_counts["runtime_building_blocks"] > 0:
        truncated_sections.append(_RUNTIME_COMPONENTS_PATH)
    if omitted_counts["domain_routing_map"] > 0:
        truncated_sections.append(_RUNTIME_ROUTES_PATH)
    if omitted_counts["deploy_runtime_map"] > 0:
        truncated_sections.append(_RUNTIME_DEPLOY_UNITS_PATH)
    if omitted_counts["endpoint_consumer_map"] > 0:
        truncated_sections.append(_RUNTIME_CONSUMERS_PATH)
    if omitted_counts["deploy_order_guidance"] > 0:
        truncated_sections.append(_RUNTIME_DEPLOY_GUIDANCE_PATH)
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
        "investigation_brief": _investigation_brief_anchor_count(answer_packet.get("investigation_brief")),
        "runtime_building_blocks": len(components) if isinstance(components, list) else 0,
        "domain_routing_map": len(routes) if isinstance(routes, list) else 0,
        "deploy_runtime_map": _answer_list_len(answer_packet, "deploy_runtime_map"),
        "endpoint_consumer_map": _answer_list_len(answer_packet, "endpoint_consumer_map"),
        "deploy_order_guidance": _answer_list_len(answer_packet, "deploy_order_guidance"),
    }


def _planning_context_fallback(result: JsonObject, *, preserve_planning_sections: bool) -> JsonObject:
    runtime = result.get("runtime_architecture")
    compact_runtime: JsonObject = {}
    if isinstance(runtime, dict):
        answer_packet = runtime.get("answer_packet")
        compact_answer: JsonObject = {}
        if isinstance(answer_packet, dict):
            compact_answer = {
                "investigation_brief": _compact_investigation_brief(answer_packet.get("investigation_brief")),
                "runtime_building_blocks": _list_value(answer_packet.get("runtime_building_blocks")),
                "domain_routing_map": _list_value(answer_packet.get("domain_routing_map")),
                "deploy_runtime_map": _list_value(answer_packet.get("deploy_runtime_map")),
                "endpoint_consumer_map": _list_value(answer_packet.get("endpoint_consumer_map")),
                "deploy_order_guidance": _list_value(answer_packet.get("deploy_order_guidance")),
                "deploy_kind_counts": answer_packet.get("deploy_kind_counts", {}),
                "missing_fact_families": answer_packet.get("missing_fact_families", []),
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
        "ownership_context": _compact_ownership_context(result.get("ownership_context", {})),
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
                "service_operational_surfaces": _compact_service_operational_surfaces(
                    result.get("service_operational_surfaces", {})
                ),
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
    for key in (
        "investigation_brief",
        "runtime_building_blocks",
        "domain_routing_map",
        "deploy_runtime_map",
        "endpoint_consumer_map",
        "deploy_order_guidance",
    ):
        rows = answer_packet.get(key)
        if not isinstance(rows, list):
            continue
        answer_packet[key] = [_minimal_runtime_row(row) for row in rows if isinstance(row, dict)]
    brief = answer_packet.get("investigation_brief")
    if isinstance(brief, dict):
        answer_packet["investigation_brief"] = _compact_investigation_brief(brief)


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
        "service",
        "subject",
        "object",
        "predicate",
        "qualifier",
        "match_basis",
        "provider",
        "provider_endpoint",
        "matched_provider_endpoint",
        "endpoint",
        "consumer",
        "consumers",
        "consumer_count",
        "deploy_target",
        "deploy_kind",
        "deploy_details",
        "ingress_or_domain_routes",
        "route_source_kind",
        "backend_service",
        "backend_service_ports",
        "ingress_path",
        "recommendation",
        "basis",
        "missing_fact_families",
        "evidence_coordinates",
        "interpretation",
    )
    minimal = {key: row[key] for key in keys if key in row}
    for nested_key in ("consumers", "ingress_or_domain_routes"):
        nested = minimal.get(nested_key)
        if isinstance(nested, list):
            minimal[nested_key] = [_minimal_runtime_row(item) for item in nested if isinstance(item, dict)]
    return minimal


def _compact_service_operational_surfaces(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    deploy_order = value.get("deploy_order_guidance")
    if not isinstance(deploy_order, dict):
        deploy_order = {}
    partition = value.get("evidence_partition")
    if not isinstance(partition, dict):
        partition = {}
    missing_contracts = partition.get("missing_contracts")
    if not isinstance(missing_contracts, dict):
        missing_contracts = {}
    return {
        "status": value.get("status"),
        "summary": value.get("summary", {}),
        "missing_fact_families": value.get("missing_fact_families", []),
        "evidence_buckets": value.get("evidence_buckets", []),
        "evidence_partition": {
            "known_linked": _compact_partition_counts(partition.get("known_linked")),
            "unlinked_evidence": _compact_partition_counts(partition.get("unlinked_evidence")),
            "missing_contracts": {
                "status": missing_contracts.get("status"),
                "items": missing_contracts.get("items", []),
            },
        },
        "deploy_runtime_units": [
            _minimal_runtime_row(row)
            for row in _list_value(value.get("deploy_runtime_units"))
            if isinstance(row, dict)
        ],
        "deploy_order_guidance": {
            "status": deploy_order.get("status"),
            "inference_contract": deploy_order.get("inference_contract"),
            "proven_endpoint_consumers": [
                _minimal_runtime_row(row)
                for row in _list_value(deploy_order.get("proven_endpoint_consumers"))
                if isinstance(row, dict)
            ],
            "practical_deploy_order": [
                _minimal_runtime_row(row)
                for row in _list_value(deploy_order.get("practical_deploy_order"))
                if isinstance(row, dict)
            ],
            "truncated": deploy_order.get("truncated"),
        },
        "direct_domain_references": _minimal_runtime_rows(value.get("direct_domain_references")),
        "domain_route_candidates": _minimal_runtime_rows(value.get("domain_route_candidates")),
        "deploy_target_candidates": _minimal_runtime_rows(value.get("deploy_target_candidates")),
        "deploy_link_facts": _minimal_runtime_rows(value.get("deploy_link_facts")),
        "endpoint_consumers": _minimal_runtime_rows(value.get("endpoint_consumers")),
        "unlinked_domain_route_samples": _minimal_runtime_rows(value.get("unlinked_domain_route_samples")),
        "coverage_note": value.get("coverage_note"),
    }


def _minimal_runtime_rows(value: object, *, limit: int = 2) -> list[JsonObject]:
    return [_minimal_runtime_row(row) for row in _list_value(value)[:limit] if isinstance(row, dict)]


def _compact_ownership_context(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    if not value:
        return {}
    answer_packet = value.get("answer_packet")
    compact_answer = {
        "can_answer_owner": None,
        "service_identity": None,
        "proven_owner": None,
        "owner_candidates": [],
        "final_answer_guidance": None,
        "unsupported_promotions": [],
    }
    if isinstance(answer_packet, dict):
        compact_answer = {
            "can_answer_owner": answer_packet.get("can_answer_owner"),
            "service_identity": answer_packet.get("service_identity"),
            "proven_owner": answer_packet.get("proven_owner"),
            "owner_candidates": _list_value(answer_packet.get("owner_candidates"))[:3],
            "final_answer_guidance": answer_packet.get("final_answer_guidance"),
            "unsupported_promotions": _list_value(answer_packet.get("unsupported_promotions"))[:3],
        }
    return {
        "status": value.get("status"),
        "scope": value.get("scope", {}),
        "evidence_contract": value.get("evidence_contract"),
        "answer_packet": compact_answer,
        "proven_owners": _list_value(value.get("proven_owners"))[:3],
        "candidate_maintainers": _list_value(value.get("candidate_maintainers"))[:3],
        "missing_fact_families": value.get("missing_fact_families", []),
        "recommended_source_checks": _list_value(value.get("recommended_source_checks"))[:3],
    }


def _compact_investigation_brief(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    compact = {
        "purpose": value.get("purpose"),
        "usage": value.get("usage"),
        "runtime_anchors": [
            _compact_headstart_row(row)
            for row in _list_value(value.get("runtime_anchors"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
            if isinstance(row, dict)
        ],
        "known_routes": [
            _compact_headstart_row(row)
            for row in _list_value(value.get("known_routes"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
            if isinstance(row, dict)
        ],
        "unlinked_runtime_leads": [
            _compact_headstart_row(row)
            for row in _list_value(value.get("unlinked_runtime_leads"))[:COMPACT_RUNTIME_LEAD_LIMIT]
            if isinstance(row, dict)
        ],
        "deploy_units": [
            _compact_headstart_row(row)
            for row in _list_value(value.get("deploy_units"))[:COMPACT_RUNTIME_DEPLOY_UNIT_LIMIT]
            if isinstance(row, dict)
        ],
        "consumer_links": [
            _compact_headstart_row(row)
            for row in _list_value(value.get("consumer_links"))[:COMPACT_RUNTIME_DEPLOY_UNIT_LIMIT]
            if isinstance(row, dict)
        ],
        "recommended_source_checks": [
            _compact_source_check(row)
            for row in _list_value(value.get("recommended_source_checks"))[:COMPACT_RUNTIME_SOURCE_CHECK_LIMIT]
            if isinstance(row, dict)
        ],
        "missing_fact_families": value.get("missing_fact_families", []),
    }
    return {key: item for key, item in compact.items() if item not in (None, [], {})}


def _compact_headstart_row(row: JsonObject) -> JsonObject:
    keys = (
        "anchor_kind",
        "status",
        "kind",
        "name",
        "repo",
        "slug",
        "type",
        "path",
        "service",
        "runtime_categories",
        "deploy_kinds",
        "counts",
        "domain",
        "target",
        "source",
        "services",
        "deploy_kind",
        "route_source_kind",
        "deploy_target",
        "deploy_details",
        "domains",
        "provider",
        "provider_endpoint",
        "consumers",
        "consumer_count",
        "match_basis",
        "evidence_coordinates",
        "source_coordinates",
        "interpretation",
    )
    compact = {key: row[key] for key in keys if key in row}
    for nested_key in (
        "services",
        "domains",
        "consumers",
    ):
        nested = compact.get(nested_key)
        if isinstance(nested, list):
            compact[nested_key] = [
                _compact_headstart_row(item) if isinstance(item, dict) else item
                for item in nested
            ]
    for coordinate_key in ("evidence_coordinates", "source_coordinates"):
        coordinates = compact.get(coordinate_key)
        if isinstance(coordinates, list):
            compact[coordinate_key] = [
                _compact_coordinate(row)
                for row in coordinates
                if isinstance(row, dict)
            ]
    return compact


def _compact_source_check(row: JsonObject) -> JsonObject:
    keys = ("reason", "anchor", "repo", "path", "line_start", "line_end")
    return {key: row[key] for key in keys if key in row}


def _compact_coordinate(row: JsonObject) -> JsonObject:
    keys = ("repo", "path", "line_start", "line_end")
    return {key: row[key] for key in keys if key in row}


def _investigation_brief_anchor_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    anchors = value.get("runtime_anchors")
    return len(anchors) if isinstance(anchors, list) else 0


def _compact_partition_counts(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "status": value.get("status"),
        "interpretation": value.get("interpretation"),
        "counts": value.get("counts", {}),
    }


def _minimal_valid_packet(result: JsonObject) -> JsonObject:
    runtime = result.get("runtime_architecture")
    compact_runtime: JsonObject = {}
    if isinstance(runtime, dict):
        answer_packet = runtime.get("answer_packet")
        compact_answer = {}
        if isinstance(answer_packet, dict):
            compact_answer = {
                "investigation_brief": _compact_investigation_brief(answer_packet.get("investigation_brief")),
                "deploy_kind_counts": answer_packet.get("deploy_kind_counts", {}),
                "missing_fact_families": answer_packet.get("missing_fact_families", []),
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
        "ownership_context": _compact_ownership_context(result.get("ownership_context", {})),
        "service_operational_surfaces": _compact_service_operational_surfaces(
            result.get("service_operational_surfaces", {})
        ),
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


def _answer_list_len(answer_packet: JsonObject, key: str) -> int:
    value = answer_packet.get(key)
    return len(value) if isinstance(value, list) else 0
