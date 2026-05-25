from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


TOOL_NAMES = (
    "search_services",
    "get_service_brief",
    "find_callers",
    "find_callees",
    "get_event_consumers",
    "get_event_producers",
    "blast_radius",
    "deploy_blockers_for",
)

PLANNING_CONTEXT_SECTION_LIMIT = 5
PLANNING_CONTEXT_NO_OVERLAP_ACTION = (
    "No deterministic planning anchor combination overlapped after applying the supplied filters. "
    "Try a broader primary anchor or remove one narrowing field."
)
OPERATIONAL_KNOWN_LINKED = "known_linked"
OPERATIONAL_UNLINKED_EVIDENCE = "unlinked_evidence"
OPERATIONAL_MISSING_CONTRACTS = "missing_contracts"
OPERATIONAL_EVIDENCE_BUCKETS = (
    OPERATIONAL_KNOWN_LINKED,
    OPERATIONAL_UNLINKED_EVIDENCE,
    OPERATIONAL_MISSING_CONTRACTS,
)
OPERATIONAL_BUCKET_DESCRIPTIONS = {
    OPERATIONAL_KNOWN_LINKED: (
        "Operational rows connected to the service by exact KG identity or exact repo identity. "
        "These are evidence candidates, not deploy-blocker proof."
    ),
    OPERATIONAL_UNLINKED_EVIDENCE: (
        "Fleet operational config rows not linked to this service by the current KG. "
        "Use only as source leads; do not attribute them to the service without separate verification."
    ),
    OPERATIONAL_MISSING_CONTRACTS: (
        "Deploy/runtime contracts the current KG cannot prove. These gaps must stay explicit in answers."
    ),
}


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: JsonObject
    handler: Callable[[KgSnapshot, JsonObject], JsonObject]


def tool_definitions() -> list[JsonObject]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in _TOOLS.values()
    ]


def _with_default_tool_metadata(payload: JsonObject) -> JsonObject:
    return {
        **payload,
        "coverage_warnings": payload.get("coverage_warnings", []),
        "unsupported_scopes": payload.get("unsupported_scopes", []),
        "next_actions": payload.get("next_actions", []),
    }


def call_tool(kg: KgSnapshot, name: str, arguments: JsonObject | None = None) -> JsonObject:
    if name not in _TOOLS:
        raise ValueError(f"Unsupported MCP tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    tool = _TOOLS[name]
    _validate_declared_arguments(tool, arguments)
    result = _with_default_tool_metadata(tool.handler(kg, arguments))
    return {
        **result,
        "tool": name,
    }


def _search_services(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    query = _optional_string(arguments, "query")
    limit = _limit(arguments)
    services = _matching_services(kg, query)[:limit]
    return {
        "status": "found" if services else "not_found",
        "query": query,
        "returned_count": len(services),
        "services": [_service_row(kg, service) for service in services],
    }


def _get_service_brief(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    service_query = _required_string(arguments, "service")
    limit = _limit(arguments)
    matches = _matching_services(kg, service_query)
    if not matches:
        return {"status": "not_found", "query": service_query, "service": None}
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "query": service_query,
            "candidates": [_service_row(kg, service) for service in matches[:limit]],
            "candidate_count": len(matches),
        }

    service = matches[0]
    service_id = service["entity_id"]
    related = _facts_touching_entity(kg, service_id)
    endpoints = _planning_context_dedupe_rows(
        [row for row in related if row.get("predicate") in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}]
    )
    events = _planning_context_dedupe_rows(
        [row for row in related if row.get("predicate") in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}]
    )
    deploy_mappings = _planning_context_dedupe_rows(
        [row for row in related if row.get("predicate") in {"ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}]
    )
    endpoint_consumer_packet = _endpoint_consumer_packet_for_service(kg, service, limit=limit)
    operational_surfaces = _service_operational_surfaces(kg, service, limit=limit)
    missing_fact_families = []
    next_actions = []
    if not deploy_mappings:
        missing_fact_families.append("deploy_mapping")
        next_actions.append(
            "No deploy-mapping facts are linked to this service; inspect deployment manifests or CI/CD config before making production/staging deployment claims."
        )
    if endpoint_consumer_packet["summary"]["consumer_fact_count"] > 0:
        next_actions.append(
            "endpoint_consumers are static path-matched CALLS_ENDPOINT facts; verify host/env resolution before treating them as runtime dependencies."
        )
    return {
        "status": "found",
        "service": _service_row(kg, service),
        "summary": {
            "endpoint_fact_count": len(endpoints),
            "event_fact_count": len(events),
            "deploy_mapping_count": len(deploy_mappings),
            "endpoint_consumer_fact_count": endpoint_consumer_packet["summary"]["consumer_fact_count"],
            "endpoint_consumer_service_count": endpoint_consumer_packet["summary"]["consumer_service_count"],
            "domain_route_candidate_count": operational_surfaces["summary"]["domain_route_candidate_count"],
            "deploy_target_candidate_count": operational_surfaces["summary"]["deploy_target_candidate_count"],
        },
        "endpoints": endpoints[:limit],
        "event_channels": events[:limit],
        "deploy_mappings": deploy_mappings[:limit],
        "endpoint_consumers": endpoint_consumer_packet,
        "operational_surfaces": operational_surfaces,
        "answerability": {
            "status": "partial" if missing_fact_families else "answerable",
            "missing_fact_families": missing_fact_families,
            "recommended_followups": next_actions,
        },
        "next_actions": next_actions,
    }


def _find_callers(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return _with_symbol_miss_next_actions(
        kg.find_callers(
            _required_string(arguments, "symbol"),
            limit=_limit(arguments),
            path=_optional_string(arguments, "path"),
            line=_optional_int(arguments, "line"),
            include_all=_optional_bool(arguments, "include_all", default=False),
        ),
        direction="callers",
    )


def _with_symbol_miss_next_actions(payload: JsonObject, *, direction: str) -> JsonObject:
    if payload.get("status") != "not_found":
        return payload
    next_actions = list(payload.get("next_actions", []))
    next_actions.extend(
        [
            f"Use source inspection to verify {direction}; this graph miss is not proof of absence.",
            "If the symbol is imported from an external package, search workspace source files for call sites such as `symbol(`.",
            "If the symbol is locally defined under a different qualified name, retry with `path` or `line` disambiguation.",
        ]
    )
    return {
        **payload,
        "next_actions": next_actions,
    }


def _find_callees(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return _with_symbol_miss_next_actions(
        kg.find_callees(
            _required_string(arguments, "symbol"),
            limit=_limit(arguments),
            path=_optional_string(arguments, "path"),
            line=_optional_int(arguments, "line"),
            include_all=_optional_bool(arguments, "include_all", default=False),
        ),
        direction="callees",
    )


def _blast_radius(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return _with_symbol_miss_next_actions(
        kg.blast_radius(
            _required_string(arguments, "symbol"),
            depth=_bounded_int(arguments.get("depth", 1), field="depth", minimum=1, maximum=6),
            limit=_limit(arguments),
            path=_optional_string(arguments, "path"),
            line=_optional_int(arguments, "line"),
            include_all=_optional_bool(arguments, "include_all", default=False),
        ),
        direction="static downstream impact",
    )


def _get_event_consumers(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    channel = _required_string(arguments, "channel")
    return _event_facts(kg, channel=channel, predicate="CONSUMES_EVENT", limit=_limit(arguments), result_key="consumers")


def _get_event_producers(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    channel = _required_string(arguments, "channel")
    return _event_facts(kg, channel=channel, predicate="PRODUCES_EVENT", limit=_limit(arguments), result_key="producers")


def _deploy_blockers_for(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    service = _required_string(arguments, "service")
    return _unsupported_by_current_kg(
        "deploy_blockers_for",
        f"No canonical deploy-blocker relation is implemented yet for service {service!r}.",
    )


def _event_facts(kg: KgSnapshot, *, channel: str, predicate: str, limit: int, result_key: str) -> JsonObject:
    rows = []
    for fact in kg.facts:
        if fact.get("predicate") != predicate:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        object_ = kg.entities_by_id.get(fact["object_id"])
        if not subject or not object_ or object_.get("kind") != "EventChannel":
            continue
        if channel.lower() not in _event_channel_search_text(object_).lower():
            continue
        rows.append(_fact_result(kg, fact, subject, object_))
    returned = rows[:limit]
    missing_fact_families = [] if rows else ["static_event_facts"]
    return {
        "status": "found" if rows else "not_found",
        "channel": channel,
        "event_fact_count": len(rows),
        "returned_count": len(returned),
        "answerability": {
            "status": "answerable" if rows else "partial",
            "scope": "indexed static event-channel facts only",
            "missing_fact_families": missing_fact_families,
            "cannot_prove": [
                "whether messages were published or consumed in a time window",
                "whether there are runtime-only subscribers outside indexed source/config",
                "whether a zero-consumer result means the event channel is unused",
            ],
        },
        "next_actions": _event_next_actions(found=bool(rows), channel=channel),
        result_key: returned,
    }


def _event_channel_search_text(channel: JsonObject) -> str:
    identity = channel.get("identity", {})
    return " ".join(
        str(value)
        for value in [
            display_entity(channel),
            identity.get("channel_address"),
            identity.get("name"),
            identity.get("broker_kind"),
        ]
        if value is not None
    )


def _event_next_actions(*, found: bool, channel: str) -> list[str]:
    actions = [
        "For runtime claims such as `no consumers in the last 30 days`, inspect broker metrics, traces, logs, or deployment config; static KG event facts cannot prove time-window usage.",
        "Inspect source/config around returned event evidence before finalizing schema, handler, retry, or delivery-semantics claims.",
    ]
    if not found:
        actions.insert(
            0,
            f"Search source and deployment config for event channel {channel!r}; no indexed static event facts matched this query.",
        )
    return actions


def _unsupported_by_current_kg(tool: str, reason: str) -> JsonObject:
    return {
        "status": "unsupported_by_current_kg",
        "reason": reason,
        "missing_contract": tool,
        "coverage_warnings": [],
        "unsupported_scopes": [
            {
                "kind": tool,
                "reason": reason,
            }
        ],
        "next_actions": _unsupported_contract_next_actions(tool),
    }


def _unsupported_contract_next_actions(tool: str) -> list[str]:
    if tool == "deploy_blockers_for":
        return [
            "Inspect deployment manifests, CI/CD config, service ownership docs, and source-level runtime dependencies before making deploy-blocker claims.",
            "Use `get_service_brief` or `planning_context` only as static context; absence of explicit deploy-blocker facts is not proof that deployment is safe.",
        ]
    return [
        "Fall back to source, config, or operational evidence for this unsupported contract.",
        "Treat this unsupported result as a coverage gap, not as evidence that the risk is absent.",
    ]


def _validate_declared_arguments(tool: McpTool, arguments: JsonObject) -> None:
    properties = tool.input_schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError(f"MCP tool {tool.name} has an invalid input schema")
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ValueError(f"MCP tool {tool.name} does not accept argument(s): {', '.join(unknown)}")
    required = tool.input_schema.get("required", [])
    if not isinstance(required, list):
        raise ValueError(f"MCP tool {tool.name} has an invalid required-arguments schema")
    for field in required:
        if field not in arguments:
            raise ValueError(f"MCP tool {tool.name} requires argument: {field}")


def _matching_services(kg: KgSnapshot, query: str | None) -> list[JsonObject]:
    services = [entity for entity in kg.entities if entity.get("kind") == "Service"]
    if not query:
        return sorted(services, key=_service_sort_key)
    needle = query.lower()
    return sorted(
        [
            service
            for service in services
            if needle in _service_search_text(service).lower()
        ],
        key=_service_sort_key,
    )


def _service_row(kg: KgSnapshot, service: JsonObject) -> JsonObject:
    identity = service.get("identity", {})
    properties = service.get("properties", {})
    return {
        "service_id": service.get("entity_id"),
        "urn": service.get("urn"),
        "name": display_entity(service),
        "identity": identity,
        "repo": identity.get("repo") or properties.get("repo"),
        "namespace": identity.get("namespace"),
        "slug": identity.get("slug"),
        "evidence": kg.evidence_by_target.get(service.get("entity_id"), []),
    }


def _facts_touching_entity(kg: KgSnapshot, entity_id: str) -> list[JsonObject]:
    rows = []
    for fact in kg.facts:
        if fact.get("subject_id") != entity_id and fact.get("object_id") != entity_id:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        object_ = kg.entities_by_id.get(fact["object_id"])
        if not subject or not object_:
            continue
        rows.append(_fact_result(kg, fact, subject, object_))
    return rows


def _service_search_text(service: JsonObject) -> str:
    identity = service.get("identity", {})
    properties = service.get("properties", {})
    return " ".join(str(value) for value in [display_entity(service), *identity.values(), *properties.values()])


def _fact_result(kg: KgSnapshot, fact: JsonObject, subject: JsonObject, object_: JsonObject) -> JsonObject:
    return {
        "fact_id": fact["fact_id"],
        "predicate": fact["predicate"],
        "subject": display_entity(subject),
        "object": display_entity(object_),
        "qualifier": fact.get("qualifier", {}),
        "evidence": kg.evidence_by_target.get(fact["fact_id"], []),
    }


def _endpoint_consumer_packet_for_service(kg: KgSnapshot, service: JsonObject, *, limit: int) -> JsonObject:
    return _endpoint_consumer_packet(
        kg,
        _exposed_endpoint_rows_for_service_id(kg, str(service["entity_id"])),
        limit=limit,
    )


def _endpoint_consumer_packet(kg: KgSnapshot, exposed_endpoint_rows: list[JsonObject], *, limit: int) -> JsonObject:
    matched_rows = _endpoint_consumer_rows_for_exposed_endpoints(kg, exposed_endpoint_rows)
    public_rows = _planning_context_public_rows(matched_rows)
    confidence_counts = _count_row_qualifier_values(public_rows, "confidence")
    host_resolution_counts = _count_row_qualifier_values(public_rows, "host_resolution_kind")
    consumer_keys = {
        str(row.get("consumer", {}).get("service_id") or row.get("consumer", {}).get("name"))
        for row in public_rows
        if isinstance(row.get("consumer"), dict)
    }
    return {
        "summary": {
            "consumer_fact_count": len(public_rows),
            "consumer_service_count": len(consumer_keys),
            "confidence_counts": confidence_counts,
            "host_resolution_kind_counts": host_resolution_counts,
            "match_basis": "literal_normalized_endpoint_path_and_compatible_method",
            "section_limit": limit,
        },
        "consumers": public_rows[:limit],
        "truncated": len(public_rows) > limit,
        "coverage_note": (
            "These rows are candidate inbound endpoint consumers from static CALLS_ENDPOINT facts. "
            "Unresolved hosts require source or environment verification before runtime/deploy conclusions."
        ),
    }


def _endpoint_consumer_rows_for_exposed_endpoints(
    kg: KgSnapshot,
    exposed_endpoint_rows: list[JsonObject],
) -> list[JsonObject]:
    provider_index = _provider_endpoint_index(exposed_endpoint_rows)
    if not provider_index:
        return []
    provider_service_ids = {
        str(row.get("_subject", {}).get("entity_id"))
        for row in exposed_endpoint_rows
        if isinstance(row.get("_subject"), dict) and row.get("_subject", {}).get("entity_id")
    }
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") != "CALLS_ENDPOINT":
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        endpoint = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not endpoint or endpoint.get("kind") != "Endpoint":
            continue
        if str(subject.get("entity_id")) in provider_service_ids:
            continue
        endpoint_path = _endpoint_path(endpoint)
        if endpoint_path is None or endpoint_path not in provider_index:
            continue
        endpoint_method = _endpoint_method(endpoint, fact)
        provider_methods = provider_index[endpoint_path]
        if not _endpoint_methods_are_compatible(endpoint_method, provider_methods):
            continue
        rows.append(
            {
                **_planning_context_fact_result(kg, fact, subject, endpoint),
                "consumer": _endpoint_consumer_identity(subject),
                "matched_provider_endpoint": {
                    "path": endpoint_path,
                    "methods": sorted(provider_methods),
                },
                "match_basis": "literal_normalized_endpoint_path_and_compatible_method",
            }
        )
    return _planning_context_dedupe_rows(rows)


def _exposed_endpoint_rows_for_service_id(kg: KgSnapshot, service_id: str) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") != "EXPOSES_ENDPOINT" or fact.get("subject_id") != service_id:
            continue
        service = kg.entities_by_id.get(fact.get("subject_id"))
        endpoint = kg.entities_by_id.get(fact.get("object_id"))
        if not service or not endpoint or endpoint.get("kind") != "Endpoint":
            continue
        rows.append(_planning_context_fact_result(kg, fact, service, endpoint))
    return rows


def _provider_endpoint_index(exposed_endpoint_rows: list[JsonObject]) -> dict[str, set[str]]:
    paths: dict[str, set[str]] = {}
    for row in exposed_endpoint_rows:
        endpoint = row.get("_object")
        fact = row.get("_fact")
        if not isinstance(endpoint, dict) or not isinstance(fact, dict):
            continue
        path = _endpoint_path(endpoint)
        if path is None:
            continue
        methods = paths.setdefault(path, set())
        method = _endpoint_method(endpoint, fact)
        if method is not None:
            methods.add(method)
    return paths


def _endpoint_path(endpoint: JsonObject) -> str | None:
    identity = endpoint.get("identity", {})
    if not isinstance(identity, dict):
        return None
    path = identity.get("path")
    if not isinstance(path, str) or not path.strip():
        return None
    return _normalize_endpoint_query(path)


def _endpoint_method(endpoint: JsonObject, fact: JsonObject | None = None) -> str | None:
    identity = endpoint.get("identity", {})
    method = identity.get("method") if isinstance(identity, dict) else None
    if method is None and fact is not None:
        qualifier = fact.get("qualifier", {})
        method = qualifier.get("method") if isinstance(qualifier, dict) else None
    if not isinstance(method, str) or not method.strip():
        return None
    return method.strip().upper()


def _endpoint_methods_are_compatible(consumer_method: str | None, provider_methods: set[str]) -> bool:
    if consumer_method is None or not provider_methods:
        return False
    return "ANY" in provider_methods or consumer_method in provider_methods


def _endpoint_consumer_identity(subject: JsonObject) -> JsonObject:
    identity = subject.get("identity", {})
    properties = subject.get("properties", {})
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return {
        "service_id": subject.get("entity_id"),
        "kind": subject.get("kind"),
        "name": display_entity(subject),
        "repo": identity.get("repo") or properties.get("repo"),
        "namespace": identity.get("namespace"),
        "slug": identity.get("slug"),
    }


def _count_row_qualifier_values(rows: list[JsonObject], key: str) -> JsonObject:
    counts: dict[str, int] = {}
    for row in rows:
        qualifier = row.get("qualifier", {})
        if not isinstance(qualifier, dict):
            continue
        value = qualifier.get(key)
        if value is None:
            continue
        value_key = str(value)
        counts[value_key] = counts.get(value_key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _service_operational_surfaces(kg: KgSnapshot, service: JsonObject, *, limit: int) -> JsonObject:
    repo = _planning_context_entity_repo(service)
    service_id = service.get("entity_id")
    direct_domain_rows: list[JsonObject] = []
    deploy_target_rows: list[JsonObject] = []
    deploy_link_rows: list[JsonObject] = []
    domain_route_rows: list[JsonObject] = []
    unlinked_domain_route_rows: list[JsonObject] = []
    service_deploy_targets = {
        fact.get("object_id")
        for fact in kg.facts
        if fact.get("predicate") == "DEPLOYS_VIA_CONFIG"
        and fact.get("subject_id") == service_id
        and isinstance(fact.get("object_id"), str)
    }

    for entity in kg.entities:
        if entity.get("kind") != "DeployTarget":
            continue
        if _planning_context_entity_repo(entity) != repo:
            continue
        deploy_target_rows.append(
            _operational_entity_row(kg, entity, match_basis="deploy_target_repo_equals_service_repo")
        )

    for fact in kg.facts:
        predicate = fact.get("predicate")
        if predicate not in {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        row = _fact_result(kg, fact, subject, object_)
        if predicate == "DEPLOYS_VIA_CONFIG" and subject.get("entity_id") == service_id:
            deploy_link_rows.append(
                {
                    **row,
                    "match_basis": "service_deploys_via_config",
                }
            )
            continue
        if _planning_context_entity_repo(subject) == repo or _planning_context_entity_repo(object_) == repo:
            direct_domain_rows.append(row)
            if predicate == "ROUTES_DOMAIN_TO_DEPLOY":
                domain_route_rows.append(
                    {
                        **row,
                        "match_basis": "domain_or_deploy_target_repo_equals_service_repo",
                    }
                )
            continue
        if predicate == "ROUTES_DOMAIN_TO_DEPLOY" and fact.get("object_id") in service_deploy_targets:
            domain_route_rows.append(
                {
                    **row,
                    "match_basis": "route_deploy_target_linked_to_service",
                }
            )
        elif predicate == "ROUTES_DOMAIN_TO_DEPLOY":
            unlinked_domain_route_rows.append(
                {
                    **row,
                    "relationship_to_service": "unlinked_fleet_route",
                }
            )

    direct_domain_rows = _planning_context_dedupe_rows(direct_domain_rows)
    domain_route_rows = _planning_context_dedupe_rows(domain_route_rows)
    deploy_target_rows = _planning_context_dedupe_rows(deploy_target_rows)
    deploy_link_rows = _planning_context_dedupe_rows(deploy_link_rows)
    unlinked_domain_route_rows = _planning_context_dedupe_rows(unlinked_domain_route_rows)
    deploy_evidence_count = len(deploy_target_rows) + len(deploy_link_rows)
    return {
        "summary": {
            "direct_domain_reference_count": len(direct_domain_rows),
            "domain_route_candidate_count": len(domain_route_rows),
            "deploy_target_candidate_count": deploy_evidence_count,
            "deploy_target_entity_count": len(deploy_target_rows),
            "deploy_link_fact_count": len(deploy_link_rows),
            "unlinked_domain_route_count": len(unlinked_domain_route_rows),
            "match_basis": "structured_repo_identity_only",
            "section_limit": limit,
        },
        "evidence_buckets": list(OPERATIONAL_EVIDENCE_BUCKETS),
        "bucket_descriptions": OPERATIONAL_BUCKET_DESCRIPTIONS,
        "evidence_partition": _operational_evidence_partition(
            direct_domain_rows=direct_domain_rows,
            domain_route_rows=domain_route_rows,
            deploy_target_rows=deploy_target_rows,
            deploy_link_rows=deploy_link_rows,
            unlinked_domain_route_rows=unlinked_domain_route_rows,
            limit=limit,
        ),
        "direct_domain_references": direct_domain_rows[:limit],
        "domain_route_candidates": domain_route_rows[:limit],
        "deploy_target_candidates": deploy_target_rows[:limit],
        "deploy_link_facts": deploy_link_rows[:limit],
        "unlinked_domain_route_samples": unlinked_domain_route_rows[:limit],
        "truncated": any(
            len(rows) > limit
            for rows in (
                direct_domain_rows,
                domain_route_rows,
                deploy_target_rows,
                deploy_link_rows,
                unlinked_domain_route_rows,
            )
        ),
        "coverage_note": (
            "domain_route_candidates and deploy_target_candidates require exact repo-identity evidence; deploy_link_facts require service-to-target evidence; unlinked_domain_route_samples are fleet config evidence and are not service deploy-blocker facts."
        ),
    }


def _operational_evidence_partition(
    *,
    direct_domain_rows: list[JsonObject],
    domain_route_rows: list[JsonObject],
    deploy_target_rows: list[JsonObject],
    deploy_link_rows: list[JsonObject],
    unlinked_domain_route_rows: list[JsonObject],
    limit: int,
) -> JsonObject:
    known_count = len(direct_domain_rows) + len(domain_route_rows) + len(deploy_target_rows) + len(deploy_link_rows)
    return {
        OPERATIONAL_KNOWN_LINKED: {
            "status": "found" if known_count else "empty",
            "interpretation": OPERATIONAL_BUCKET_DESCRIPTIONS[OPERATIONAL_KNOWN_LINKED],
            "direct_domain_references": direct_domain_rows[:limit],
            "domain_routes": domain_route_rows[:limit],
            "deploy_targets": deploy_target_rows[:limit],
            "deploy_links": deploy_link_rows[:limit],
            "counts": {
                "direct_domain_reference_count": len(direct_domain_rows),
                "domain_route_count": len(domain_route_rows),
                "deploy_target_count": len(deploy_target_rows) + len(deploy_link_rows),
                "deploy_target_entity_count": len(deploy_target_rows),
                "deploy_link_fact_count": len(deploy_link_rows),
            },
        },
        OPERATIONAL_UNLINKED_EVIDENCE: {
            "status": "found" if unlinked_domain_route_rows else "empty",
            "interpretation": OPERATIONAL_BUCKET_DESCRIPTIONS[OPERATIONAL_UNLINKED_EVIDENCE],
            "domain_route_samples": unlinked_domain_route_rows[:limit],
            "counts": {
                "domain_route_sample_count": len(unlinked_domain_route_rows),
            },
        },
        OPERATIONAL_MISSING_CONTRACTS: {
            "status": "present",
            "interpretation": OPERATIONAL_BUCKET_DESCRIPTIONS[OPERATIONAL_MISSING_CONTRACTS],
            "items": _operational_missing_contracts(
                domain_route_rows=domain_route_rows,
                deploy_target_rows=deploy_target_rows,
                deploy_link_rows=deploy_link_rows,
                unlinked_domain_route_rows=unlinked_domain_route_rows,
            ),
        },
    }


def _operational_missing_contracts(
    *,
    domain_route_rows: list[JsonObject],
    deploy_target_rows: list[JsonObject],
    deploy_link_rows: list[JsonObject],
    unlinked_domain_route_rows: list[JsonObject],
) -> list[JsonObject]:
    missing = [
        {
            "contract": "canonical_service_deploy_blocker",
            "status": "unsupported_by_current_kg",
            "meaning": (
                "The current KG has no canonical relation proving another service must deploy before this service."
            ),
        },
        {
            "contract": "runtime_host_resolution",
            "status": "not_proven",
            "meaning": (
                "Static endpoint/domain/config evidence does not prove which runtime host or environment a client uses."
            ),
        },
    ]
    if not domain_route_rows and not deploy_target_rows and not deploy_link_rows:
        missing.append(
            {
                "contract": "service_to_deploy_target",
                "status": "missing",
                "meaning": (
                    "No exact repo-linked DeployTarget or ROUTES_DOMAIN_TO_DEPLOY row is connected to this service."
                ),
            }
        )
    if unlinked_domain_route_rows:
        missing.append(
            {
                "contract": "unlinked_route_to_service",
                "status": "not_proven",
                "meaning": (
                    "Fleet domain-route evidence exists, but the current KG does not connect it to this service."
                ),
            }
        )
    return missing


def _operational_entity_row(kg: KgSnapshot, entity: JsonObject, *, match_basis: str) -> JsonObject:
    return {
        "entity_id": entity.get("entity_id"),
        "kind": entity.get("kind"),
        "name": display_entity(entity),
        "urn": entity.get("urn"),
        "identity": entity.get("identity", {}),
        "properties": entity.get("properties", {}),
        "match_basis": match_basis,
        "evidence": kg.evidence_by_target.get(entity.get("entity_id"), []),
    }


def _service_sort_key(service: JsonObject) -> tuple[str, str]:
    identity = service.get("identity", {})
    return (str(identity.get("namespace") or ""), str(identity.get("slug") or display_entity(service)))


def _required_string(arguments: JsonObject, field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MCP tool argument {field!r} must be a non-empty string")
    return value.strip()


def _optional_string(arguments: JsonObject, field: str) -> str | None:
    value = arguments.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"MCP tool argument {field!r} must be a string")
    stripped = value.strip()
    return stripped or None


def _optional_int(arguments: JsonObject, field: str) -> int | None:
    value = arguments.get(field)
    if value is None:
        return None
    return _bounded_int(value, field=field, minimum=1, maximum=10_000_000)


def _optional_bool(arguments: JsonObject, field: str, *, default: bool) -> bool:
    value = arguments.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"MCP tool argument {field!r} must be a boolean")
    return value


def _required_string_list(arguments: JsonObject, field: str) -> list[str]:
    value = arguments.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"MCP tool argument {field!r} must be a non-empty list of strings")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"MCP tool argument {field!r} must be a non-empty list of strings")
        normalized.append(item.strip())
    return normalized


def _optional_changed_ranges(arguments: JsonObject, field: str) -> list[JsonObject]:
    if field not in arguments:
        return []
    value = arguments[field]
    if not isinstance(value, list):
        raise ValueError(f"MCP tool argument {field!r} must be a list of changed-range objects")
    ranges: list[JsonObject] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"MCP tool argument {field!r} must be a list of changed-range objects")
        unknown = sorted(set(item) - {"path", "start_line", "end_line"})
        if unknown:
            raise ValueError(f"MCP tool argument {field!r} range does not accept field(s): {', '.join(unknown)}")
        path = item.get("path")
        start_line = item.get("start_line")
        end_line = item.get("end_line")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"MCP tool argument {field!r} requires non-empty range paths")
        if isinstance(start_line, bool) or not isinstance(start_line, int) or start_line < 1:
            raise ValueError(f"MCP tool argument {field!r} requires integer start_line >= 1")
        if isinstance(end_line, bool) or not isinstance(end_line, int) or end_line < start_line:
            raise ValueError(f"MCP tool argument {field!r} requires integer end_line >= start_line")
        ranges.append({"path": path.strip(), "start_line": start_line, "end_line": end_line})
    return ranges


def _limit(arguments: JsonObject) -> int:
    return _bounded_int(arguments.get("limit", 25), field="limit", minimum=1, maximum=100)


def _bounded_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"MCP tool argument {field!r} must be an integer")
    if isinstance(value, int):
        raw = value
    else:
        raise ValueError(f"MCP tool argument {field!r} must be an integer")
    if raw < minimum or raw > maximum:
        raise ValueError(f"MCP tool argument {field!r} must be between {minimum} and {maximum}")
    return raw


def _object_schema(properties: JsonObject, required: list[str] | None = None) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string_schema(description: str) -> JsonObject:
    return {"type": "string", "description": description}


def _nullable_string_schema(description: str) -> JsonObject:
    return {"type": ["string", "null"], "description": description}


def _nullable_line_schema() -> JsonObject:
    return {"type": ["integer", "null"], "minimum": 1, "description": "Optional source line for disambiguation."}


def _limit_schema() -> JsonObject:
    return {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}


def _symbol_properties() -> JsonObject:
    return {
        "symbol": _string_schema(
            "Symbol name or exact qualified name. If a prior result was ambiguous, retry with a candidate `qualified_name`."
        ),
        "path": _nullable_string_schema("Optional source-file path for disambiguation."),
        "line": _nullable_line_schema(),
        "include_all": {"type": "boolean", "default": False},
        "limit": _limit_schema(),
    }


def _planning_context_properties() -> JsonObject:
    return {
        "query": _nullable_string_schema("Optional exact identifier query when no structured anchor is known."),
        "repo": _nullable_string_schema("Repository identifier anchor."),
        "path": _nullable_string_schema("File path anchor."),
        "line": _nullable_line_schema(),
        "symbol": _nullable_string_schema("Symbol anchor."),
        "service": _nullable_string_schema("Service anchor."),
        "package": _nullable_string_schema("Package/module anchor."),
        "endpoint": _nullable_string_schema("Endpoint path anchor."),
        "event_channel": _nullable_string_schema("Event channel anchor."),
        "domain": _nullable_string_schema("Domain anchor."),
        "limit": _limit_schema(),
    }


def _changed_range_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {
            "path": _string_schema("Changed file path."),
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path", "start_line", "end_line"],
        "additionalProperties": False,
    }


def _review_context_properties() -> JsonObject:
    return {
        "repo": _string_schema("Repository identifier for the review target."),
        "changed_files": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Changed file paths to review.",
        },
        "changed_ranges": {
            "type": "array",
            "items": _changed_range_schema(),
            "description": "Optional changed line ranges for narrowing file symbols.",
        },
        "limit": _limit_schema(),
        "include_deploy_blockers": {"type": "boolean", "default": False},
    }


def _planning_context(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    limit = _limit(arguments)
    query = _optional_string(arguments, "query")
    anchors = {
        "repo": _optional_string(arguments, "repo"),
        "path": _optional_string(arguments, "path"),
        "symbol": _optional_string(arguments, "symbol"),
        "service": _optional_string(arguments, "service"),
        "package": _optional_string(arguments, "package"),
        "endpoint": _optional_string(arguments, "endpoint"),
        "event_channel": _optional_string(arguments, "event_channel"),
        "domain": _optional_string(arguments, "domain"),
    }
    line = _optional_int(arguments, "line")
    if query is None and line is None and not any(anchors.values()):
        raise ValueError(
            "planning_context requires at least one of: query, repo, path, line, symbol, service, "
            "package, endpoint, event_channel, domain"
        )

    if query is not None and not any(anchors.values()) and line is None:
        return _planning_context_from_query(kg, query=query, limit=limit)

    services: list[JsonObject] = []
    symbols: list[JsonObject] = []
    dependencies: list[JsonObject] = []
    endpoints: list[JsonObject] = []
    endpoint_consumers: list[JsonObject] = []
    event_channels: list[JsonObject] = []
    domains: list[JsonObject] = []
    next_actions: list[str] = []

    if anchors["service"]:
        matches = _matching_services(kg, anchors["service"])
        services = [_service_row(kg, service) for service in matches[:limit]]
        if len(matches) > 1:
            next_actions.extend(_service_refinement_actions(services))
            return _planning_context_output(
                kg=kg,
                query=query,
                anchors=anchors,
                services=services,
                symbols=symbols,
                dependencies=dependencies,
                endpoints=endpoints,
                endpoint_consumers=endpoint_consumers,
                event_channels=event_channels,
                domains=domains,
                next_actions=next_actions,
                status="ambiguous",
            )
        if len(matches) == 1:
            related = _planning_context_service_related_rows(kg, matches[0], limit=limit)
            dependencies = _planning_context_dedupe_rows(dependencies + related["dependencies"])
            endpoints = _planning_context_dedupe_rows(endpoints + related["endpoints"])
            endpoint_consumers = _planning_context_dedupe_rows(endpoint_consumers + related["endpoint_consumers"])
            event_channels = _planning_context_dedupe_rows(event_channels + related["event_channels"])
            domains = _planning_context_dedupe_rows(domains + related["domains"])
    if anchors["symbol"]:
        resolution = kg.lookup_symbol(anchors["symbol"], limit=limit, path=anchors["path"], line=line)
        if resolution["status"] == "ambiguous":
            symbols = list(resolution.get("candidates", []))[:limit]
            next_actions.extend(_symbol_refinement_actions(symbols))
            return _planning_context_output(
                kg=kg,
                query=query,
                anchors=anchors,
                services=services,
                symbols=symbols,
                dependencies=dependencies,
                endpoints=endpoints,
                endpoint_consumers=endpoint_consumers,
                event_channels=event_channels,
                domains=domains,
                next_actions=next_actions,
                status="ambiguous",
            )
        if resolution["status"] == "resolved" and resolution.get("resolved_symbol") is not None:
            symbols = [resolution["resolved_symbol"]]

    if anchors["repo"]:
        dependencies = _planning_context_dedupe_rows(
            dependencies + _planning_context_collect_rows(_planning_context_repo_matches(kg, anchors["repo"]), limit=limit)
        )
    if anchors["package"]:
        dependencies = _planning_context_dedupe_rows(
            dependencies + _planning_context_collect_rows(_planning_context_package_matches(kg, anchors["package"]), limit=limit)
        )
    if anchors["endpoint"]:
        endpoints = _planning_context_dedupe_rows(
            endpoints + _planning_context_collect_rows(_planning_context_endpoint_matches(kg, anchors["endpoint"]), limit=limit)
        )
    if anchors["event_channel"]:
        event_channels = _planning_context_dedupe_rows(
            event_channels
            + _planning_context_collect_rows(_planning_context_event_matches(kg, anchors["event_channel"]), limit=limit)
        )
    if anchors["domain"]:
        domains = _planning_context_dedupe_rows(
            domains + _planning_context_collect_rows(_planning_context_domain_matches(kg, anchors["domain"]), limit=limit)
        )
    if anchors["path"] and not anchors["symbol"]:
        path_symbols = kg.symbols_in_file(anchors["path"], limit=10_000)
        rows = list(path_symbols.get("symbols", []))
        if line is not None:
            rows = [row for row in rows if _line_matches_symbol(line, row)]
        symbols = rows[:limit]
    if line is not None and anchors["path"] is None and anchors["symbol"] is None and not any(
        anchors[key] for key in ("repo", "service", "package", "endpoint", "event_channel", "domain")
    ):
        next_actions.append("Add `path` or `symbol` with `line` to target a concrete source location.")
        return _planning_context_output(
            kg=kg,
            query=query,
            anchors=anchors,
            services=services,
            symbols=symbols,
            dependencies=dependencies,
            endpoints=endpoints,
            endpoint_consumers=endpoint_consumers,
            event_channels=event_channels,
            domains=domains,
            next_actions=next_actions,
            status="ambiguous",
        )

    base_category = _planning_context_base_category(anchors)
    if base_category == "services":
        services = _planning_context_filter_rows("services", services, anchors, line=line)[:limit]
    elif base_category == "symbols":
        symbols = _planning_context_filter_rows("symbols", symbols, anchors, line=line)[:limit]
    elif base_category == "dependencies":
        dependencies = _planning_context_filter_rows("dependencies", dependencies, anchors, line=line)[:limit]
    elif base_category == "endpoints":
        endpoints = _planning_context_filter_rows("endpoints", endpoints, anchors, line=line)[:limit]
    elif base_category == "event_channels":
        event_channels = _planning_context_filter_rows("event_channels", event_channels, anchors, line=line)[:limit]
    elif base_category == "domains":
        domains = _planning_context_filter_rows("domains", domains, anchors, line=line)[:limit]

    status = "found" if any((services, symbols, dependencies, endpoints, event_channels, domains)) else "not_found"
    if status == "not_found":
        next_actions.append(PLANNING_CONTEXT_NO_OVERLAP_ACTION)
    return _planning_context_output(
        kg=kg,
        query=query,
        anchors=anchors,
        services=services,
        symbols=symbols,
        dependencies=dependencies,
        endpoints=endpoints,
        endpoint_consumers=endpoint_consumers,
        event_channels=event_channels,
        domains=domains,
        next_actions=next_actions,
        status=status,
    )


def _review_context(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    repo = _required_string(arguments, "repo")
    changed_files = _required_string_list(arguments, "changed_files")
    changed_ranges = _optional_changed_ranges(arguments, "changed_ranges")
    limit = _limit(arguments)
    include_deploy_blockers = _optional_bool(arguments, "include_deploy_blockers", default=False)

    changed_symbols: list[JsonObject] = []
    range_filters = _changed_ranges_by_path(changed_ranges)
    changed_symbols_by_path: dict[str, list[JsonObject]] = {}

    for changed_file in changed_files:
        symbol_rows = list(kg.symbols_in_file(changed_file, limit=10_000).get("symbols", []))
        symbol_rows = [row for row in symbol_rows if _normalize_repo_text(row.get("repo")) == _normalize_repo_text(repo)]
        normalized_changed_file = _planning_context_normalize_path(changed_file)
        if changed_ranges:
            file_ranges = range_filters.get(normalized_changed_file, [])
            if file_ranges:
                symbol_rows = [row for row in symbol_rows if _review_context_symbol_overlaps_ranges(row, file_ranges)]
        for row in symbol_rows:
            changed_symbols.append(row)
        changed_symbols_by_path[normalized_changed_file] = symbol_rows

    changed_symbols = _review_context_dedupe_rows(changed_symbols)[:limit]
    direct_callers: list[JsonObject] = []
    direct_callees: list[JsonObject] = []
    for row in changed_symbols:
        symbol_name = str(row.get("qualified_name") or row.get("qualname") or "")
        if not symbol_name:
            continue
        callers = kg.find_callers(
            symbol_name,
            limit=limit,
            path=_optional_symbol_path(row),
            line=_optional_symbol_line(row),
            include_all=False,
        )
        callees = kg.find_callees(
            symbol_name,
            limit=limit,
            path=_optional_symbol_path(row),
            line=_optional_symbol_line(row),
            include_all=False,
        )
        direct_callers.extend(callers.get("callers", []))
        direct_callees.extend(callees.get("callees", []))
    repo_dependency_result = kg.repo_dependencies(repo, limit=limit)
    repo_dependencies = list(repo_dependency_result.get("dependencies", []))
    direct_callers = _review_context_dedupe_rows(direct_callers)[:limit]
    direct_callees = _review_context_dedupe_rows(direct_callees)[:limit]
    repo_dependencies = _review_context_dedupe_rows(repo_dependencies)[:limit]
    runtime_surfaces = _review_context_runtime_surfaces(kg, repo=repo, changed_symbols=changed_symbols, limit=limit)
    endpoint_rows = runtime_surfaces["endpoints"]
    endpoint_consumer_rows = runtime_surfaces["endpoint_consumers"]
    event_channel_rows = runtime_surfaces["event_channels"]
    deploy_mapping_rows = runtime_surfaces["deploy_mappings"]

    unsupported_scopes: list[JsonObject] = []
    if include_deploy_blockers:
        unsupported_scopes.append(
            {
                "kind": "deploy_blockers",
                "scope": repo,
                "reason": "No canonical deploy-blocker relation is implemented yet",
            }
        )

    status = "found" if any((changed_symbols, direct_callers, direct_callees, repo_dependencies)) else "not_found"
    changed_surface = _review_context_changed_surface(
        changed_files=changed_files,
        range_filters=range_filters,
        symbols_by_path=changed_symbols_by_path,
        changed_symbols=changed_symbols,
    )
    source_coordinates = _planning_context_source_coordinates(
        changed_symbols,
        direct_callers,
        direct_callees,
        repo_dependencies,
        endpoint_rows,
        endpoint_consumer_rows,
        event_channel_rows,
        deploy_mapping_rows,
        limit=PLANNING_CONTEXT_SECTION_LIMIT,
    )
    answerability = _review_context_answerability(
        status=status,
        changed_symbols=changed_symbols,
        include_deploy_blockers=include_deploy_blockers,
    )
    next_actions = _review_context_next_actions(answerability, unsupported_scopes=unsupported_scopes)
    public_changed_symbols = _planning_context_public_rows(changed_symbols)
    public_direct_callers = _planning_context_public_rows(direct_callers)
    public_direct_callees = _planning_context_public_rows(direct_callees)
    public_repo_dependencies = _planning_context_public_rows(repo_dependencies)
    public_endpoints = _planning_context_public_rows(endpoint_rows)
    public_endpoint_consumers = _planning_context_public_rows(endpoint_consumer_rows)
    public_event_channels = _planning_context_public_rows(event_channel_rows)
    public_deploy_mappings = _planning_context_public_rows(deploy_mapping_rows)
    return {
        "status": status,
        "repo": repo,
        "summary": _review_context_summary(
            changed_files=changed_files,
            changed_symbols=public_changed_symbols,
            direct_callers=public_direct_callers,
            direct_callees=public_direct_callees,
            repo_dependencies=public_repo_dependencies,
            endpoints=public_endpoints,
            endpoint_consumers=public_endpoint_consumers,
            event_channels=public_event_channels,
            deploy_mappings=public_deploy_mappings,
            source_coordinates=source_coordinates,
        ),
        "changed_symbols": public_changed_symbols,
        "direct_callers": public_direct_callers,
        "direct_callees": public_direct_callees,
        "repo_dependencies": public_repo_dependencies,
        "changed_surface": changed_surface,
        "impact": {
            "direct_callers": public_direct_callers[:PLANNING_CONTEXT_SECTION_LIMIT],
            "direct_callees": public_direct_callees[:PLANNING_CONTEXT_SECTION_LIMIT],
            "repo_dependencies": public_repo_dependencies[:PLANNING_CONTEXT_SECTION_LIMIT],
        },
        "runtime_surfaces": {
            "endpoints": public_endpoints[:PLANNING_CONTEXT_SECTION_LIMIT],
            "endpoint_consumers": public_endpoint_consumers[:PLANNING_CONTEXT_SECTION_LIMIT],
            "event_channels": public_event_channels[:PLANNING_CONTEXT_SECTION_LIMIT],
            "deploy_mappings": public_deploy_mappings[:PLANNING_CONTEXT_SECTION_LIMIT],
        },
        "source_coordinates": source_coordinates,
        "answerability": answerability,
        "coverage_warnings": [],
        "unsupported_scopes": unsupported_scopes,
        "unsupported_review_scopes": unsupported_scopes,
        "evidence": _planning_context_evidence(
            changed_symbols,
            direct_callers,
            direct_callees,
            repo_dependencies,
            endpoint_rows,
            endpoint_consumer_rows,
            event_channel_rows,
            deploy_mapping_rows,
        ),
        "next_actions": next_actions,
    }


def _planning_context_from_query(kg: KgSnapshot, *, query: str, limit: int) -> JsonObject:
    service_matches = _matching_services(kg, query)
    service_rows = [_service_row(kg, service) for service in service_matches[:limit]]
    symbol_result = kg.lookup_symbol(query, limit=limit)
    repo_result = kg.repo_dependencies(query, limit=limit)
    package_rows = list(kg.modules_importing(query, limit=limit))
    package_uniqueness_probe = list(kg.modules_importing(query, limit=2))
    endpoint_result = kg.endpoints(path_query=query, limit=limit)
    event_result = kg.event_channels(channel_query=query, limit=limit)
    domain_result = kg.domain_references(query, limit=limit)

    resolved_symbol = symbol_result.get("resolved_symbol")
    symbol_rows = (
        [resolved_symbol]
        if symbol_result["status"] == "resolved" and isinstance(resolved_symbol, dict)
        else list(symbol_result.get("candidates", []))[:limit]
    )
    repo_rows = list(repo_result.get("dependencies", []))[:limit]
    endpoint_rows = list(endpoint_result.get("endpoints", []))[:limit]
    event_rows = list(event_result.get("event_channels", []))[:limit]
    domain_rows = list(domain_result.get("references", []))[:limit]
    exact_endpoint_rows = _planning_context_exact_endpoint_rows(kg, query, limit)
    exact_event_rows = _planning_context_exact_event_rows(kg, query, limit)
    exact_domain_rows = _planning_context_exact_domain_rows(kg, query, limit)

    resolver_hits = {
        "service": bool(service_matches),
        "symbol": symbol_result["status"] in {"resolved", "ambiguous"},
        "repo": int(repo_result.get("dependency_count", 0)) > 0,
        "package": bool(package_rows),
        "endpoint": int(endpoint_result.get("endpoint_fact_count", 0)) > 0,
        "event_channel": int(event_result.get("event_fact_count", 0)) > 0,
        "domain": int(domain_result.get("reference_count", 0)) > 0,
    }
    unique_matches: dict[str, list[JsonObject]] = {}
    if len(service_matches) == 1 and _service_exact_match(query, service_matches[0]):
        unique_matches["service"] = service_rows
    if symbol_result["status"] == "resolved" and str(symbol_result.get("confidence", "")).startswith("exact_") and symbol_rows:
        unique_matches["symbol"] = symbol_rows[:1]
    if int(repo_result.get("dependency_count", 0)) == 1 and len(repo_rows) == 1:
        unique_matches["repo"] = repo_rows
    if len(package_uniqueness_probe) == 1 and len(package_rows) == 1:
        unique_matches["package"] = package_rows
    if len(exact_endpoint_rows) == 1 and int(endpoint_result.get("endpoint_fact_count", 0)) == 1:
        unique_matches["endpoint"] = exact_endpoint_rows
    if len(exact_event_rows) == 1 and int(event_result.get("event_fact_count", 0)) == 1:
        unique_matches["event_channel"] = exact_event_rows
    if len(exact_domain_rows) == 1 and int(domain_result.get("reference_count", 0)) == 1:
        unique_matches["domain"] = exact_domain_rows

    query_anchors = {
        "repo": None,
        "path": None,
        "symbol": None,
        "service": None,
        "package": None,
        "endpoint": None,
        "event_channel": None,
        "domain": None,
    }
    hit_resolvers = [kind for kind, hit in resolver_hits.items() if hit]
    if len(hit_resolvers) == 1 and len(unique_matches) == 1:
        kind, rows = next(iter(unique_matches.items()))
        query_anchors[kind] = query
        dependencies: list[JsonObject] = rows if kind in {"repo", "package"} else []
        endpoints: list[JsonObject] = rows if kind == "endpoint" else []
        event_channels: list[JsonObject] = rows if kind == "event_channel" else []
        domains: list[JsonObject] = rows if kind == "domain" else []
        endpoint_consumers: list[JsonObject] = []
        if kind == "service" and len(service_matches) == 1:
            related = _planning_context_service_related_rows(kg, service_matches[0], limit=limit)
            dependencies = _planning_context_dedupe_rows(dependencies + related["dependencies"])
            endpoints = _planning_context_dedupe_rows(endpoints + related["endpoints"])
            endpoint_consumers = _planning_context_dedupe_rows(endpoint_consumers + related["endpoint_consumers"])
            event_channels = _planning_context_dedupe_rows(event_channels + related["event_channels"])
            domains = _planning_context_dedupe_rows(domains + related["domains"])
        return _planning_context_output(
            kg=kg,
            query=query,
            anchors=query_anchors,
            services=service_rows if kind == "service" else [],
            symbols=rows if kind == "symbol" else [],
            dependencies=dependencies,
            endpoints=endpoints,
            endpoint_consumers=endpoint_consumers,
            event_channels=event_channels,
            domains=domains,
            next_actions=[],
            status="found",
        )

    dependencies = (repo_rows + package_rows)[:limit]
    next_actions = [
        "Use a structured anchor instead of `query`: `symbol`, `service`, `repo`, `package`, `endpoint`, `event_channel`, or `domain`.",
    ]
    if resolver_hits["symbol"]:
        next_actions.extend(_symbol_refinement_actions(symbol_rows[:limit]))
    if resolver_hits["service"]:
        next_actions.extend(_service_refinement_actions(service_rows))
    if resolver_hits["repo"]:
        next_actions.append(f"Use `repo={query}` to inspect cross-repo dependency links for that consumer repo.")
    if resolver_hits["package"]:
        next_actions.append(f"Use `package={query}` to inspect importer modules for that package.")
    if resolver_hits["endpoint"]:
        next_actions.append(f"Use `endpoint={query}` to inspect matching endpoint facts.")
    if resolver_hits["event_channel"]:
        next_actions.append(f"Use `event_channel={query}` to inspect matching event-channel facts.")
    if resolver_hits["domain"]:
        next_actions.append(f"Use `domain={query}` to inspect matching domain references.")

    return _planning_context_output(
        kg=kg,
        query=query,
        anchors=query_anchors,
        services=service_rows,
        symbols=symbol_rows[:limit],
        dependencies=dependencies,
        endpoints=endpoint_rows,
        endpoint_consumers=[],
        event_channels=event_rows,
        domains=domain_rows,
        next_actions=next_actions,
        status="ambiguous",
    )


def _planning_context_base_category(anchors: dict[str, str | None]) -> str | None:
    if anchors.get("service"):
        return "services"
    if anchors.get("symbol") or anchors.get("path"):
        return "symbols"
    if anchors.get("endpoint"):
        return "endpoints"
    if anchors.get("event_channel"):
        return "event_channels"
    if anchors.get("domain"):
        return "domains"
    if anchors.get("package") or anchors.get("repo"):
        return "dependencies"
    return None


def _planning_context_filter_rows(
    category: str,
    rows: list[JsonObject],
    anchors: dict[str, str | None],
    *,
    line: int | None,
) -> list[JsonObject]:
    category_anchors = _planning_context_category_anchors(category, anchors)
    if category == "services":
        return [row for row in rows if _planning_context_service_row_matches(row, category_anchors)]
    if category == "symbols":
        return [row for row in rows if _planning_context_symbol_row_matches(row, category_anchors, line=line)]
    return [row for row in rows if _planning_context_fact_row_matches(row, category_anchors, line=line)]


def _planning_context_category_anchors(category: str, anchors: dict[str, str | None]) -> dict[str, str | None]:
    relevant = {
        "services": {"service", "repo"},
        "symbols": {"symbol", "path", "repo"},
        "dependencies": {"repo", "package", "service", "path"},
        "endpoints": {"repo", "service", "endpoint", "path"},
        "event_channels": {"repo", "service", "event_channel", "path"},
        "domains": {"repo", "service", "domain", "path"},
    }.get(category, set())
    return {key: value if key in relevant else None for key, value in anchors.items()}


def _planning_context_service_row_matches(row: JsonObject, anchors: dict[str, str | None]) -> bool:
    service = anchors.get("service")
    if service and service.strip().lower() not in _planning_context_service_row_search_text(row).lower():
        return False
    repo = anchors.get("repo")
    if repo and _normalize_repo_text(row.get("repo")) != _normalize_repo_text(repo):
        return False
    return True


def _planning_context_symbol_row_matches(
    row: JsonObject,
    anchors: dict[str, str | None],
    *,
    line: int | None,
) -> bool:
    symbol = anchors.get("symbol")
    if symbol and not _planning_context_value_matches(
        symbol,
        row.get("qualified_name"),
        row.get("qualname"),
        row.get("display_name"),
    ):
        return False
    repo = anchors.get("repo")
    if repo and _normalize_repo_text(row.get("repo")) != _normalize_repo_text(repo):
        return False
    path = anchors.get("path")
    if path and not _planning_context_path_matches(str(row.get("path") or ""), path):
        return False
    if line is not None and not _line_matches_symbol(line, row):
        return False
    return True


def _planning_context_fact_row_matches(
    row: JsonObject,
    anchors: dict[str, str | None],
    *,
    line: int | None,
) -> bool:
    fact = row.get("_fact")
    subject = row.get("_subject")
    object_ = row.get("_object")
    if not isinstance(fact, dict) or not isinstance(subject, dict) or not isinstance(object_, dict):
        return False
    if anchors.get("repo") and not _planning_context_fact_matches_repo(fact, subject, object_, anchors["repo"]):
        return False
    if anchors.get("package") and not _planning_context_fact_matches_package(fact, subject, object_, anchors["package"]):
        return False
    if anchors.get("endpoint") and not _planning_context_fact_matches_endpoint(subject, object_, anchors["endpoint"]):
        return False
    if anchors.get("event_channel") and not _planning_context_fact_matches_event_channel(subject, object_, anchors["event_channel"]):
        return False
    if anchors.get("domain") and not _planning_context_fact_matches_domain(subject, object_, anchors["domain"]):
        return False
    if anchors.get("service") and not _planning_context_fact_matches_service(subject, object_, anchors["service"]):
        return False
    path = anchors.get("path")
    evidence_rows = row.get("evidence", [])
    if path and not _planning_context_fact_matches_path_or_line(
        subject, object_, evidence_rows, path=path, line=line
    ):
        return False
    if path is None and line is not None and not _planning_context_fact_matches_path_or_line(
        subject, object_, evidence_rows, path=None, line=line
    ):
        return False
    return True


def _planning_context_fact_matches_repo(fact: JsonObject, subject: JsonObject, object_: JsonObject, repo: str) -> bool:
    needle = repo.strip().lower()
    qualifier = fact.get("qualifier", {})
    if str(qualifier.get("consumer_repo") or "").strip().lower() == needle:
        return True
    return any(_planning_context_entity_repo(entity) == needle for entity in (subject, object_))


def _planning_context_fact_matches_package(fact: JsonObject, subject: JsonObject, object_: JsonObject, package: str) -> bool:
    needle = package.strip().lower()
    qualifier = fact.get("qualifier", {})
    candidates = (
        str(qualifier.get("package_name") or ""),
        str(qualifier.get("distribution_name") or ""),
        str(qualifier.get("import_root") or ""),
        _planning_context_entity_name(subject),
        _planning_context_entity_name(object_),
    )
    return any(value.strip().lower() == needle for value in candidates if value)


def _normalize_repo_text(value: object) -> str:
    return str(value or "").strip().lower()


def _planning_context_service_row_search_text(row: JsonObject) -> str:
    values = [
        row.get("slug"),
        row.get("repo"),
        row.get("namespace"),
        row.get("name"),
    ]
    return " ".join(str(value) for value in values if value is not None)


def _planning_context_fact_matches_endpoint(subject: JsonObject, object_: JsonObject, endpoint: str) -> bool:
    return any(_planning_context_endpoint_entity_matches(entity, endpoint) for entity in (subject, object_))


def _planning_context_fact_matches_event_channel(subject: JsonObject, object_: JsonObject, event_channel: str) -> bool:
    return any(_planning_context_event_channel_entity_matches(entity, event_channel) for entity in (subject, object_))


def _planning_context_fact_matches_domain(subject: JsonObject, object_: JsonObject, domain: str) -> bool:
    return any(_planning_context_domain_entity_matches(entity, domain) for entity in (subject, object_))


def _planning_context_fact_matches_service(subject: JsonObject, object_: JsonObject, service: str) -> bool:
    return any(entity.get("kind") == "Service" and _service_exact_match(service, entity) for entity in (subject, object_))


def _planning_context_fact_matches_path_or_line(
    subject: JsonObject,
    object_: JsonObject,
    evidence_rows: object,
    *,
    path: str | None,
    line: int | None,
) -> bool:
    if any(_planning_context_entity_matches_coordinate(entity, path=path, line=line) for entity in (subject, object_)):
        return True
    if not isinstance(evidence_rows, list):
        return False
    for evidence in evidence_rows:
        if not isinstance(evidence, dict):
            continue
        bytes_ref = evidence.get("bytes_ref") or {}
        evidence_path = str(bytes_ref.get("path") or "")
        if path is not None and not _planning_context_path_matches(evidence_path, path):
            continue
        if line is None:
            return True
        line_start = int(bytes_ref.get("line_start") or 0)
        line_end = int(bytes_ref.get("line_end") or line_start)
        if line_start <= line <= line_end:
            return True
    return False


def _planning_context_entity_matches_coordinate(entity: JsonObject, *, path: str | None, line: int | None) -> bool:
    properties = entity.get("properties", {})
    entity_path = str(properties.get("path") or "")
    if path is not None and not _planning_context_path_matches(entity_path, path):
        return False
    if line is None:
        return bool(entity_path) if path is not None else True
    start = properties.get("line")
    if not isinstance(start, int):
        return False
    end = properties.get("end_line")
    line_end = end if isinstance(end, int) else start
    return start <= line <= line_end


def _planning_context_path_matches(candidate: str, target: str) -> bool:
    return candidate.replace("\\", "/").lstrip("./") == target.replace("\\", "/").lstrip("./")


def _planning_context_entity_repo(entity: JsonObject) -> str | None:
    identity = entity.get("identity", {})
    properties = entity.get("properties", {})
    repo = identity.get("repo") or properties.get("repo")
    if not isinstance(repo, str):
        return None
    return repo.strip().lower() or None


def _planning_context_entity_name(entity: JsonObject) -> str:
    identity = entity.get("identity", {})
    return str(
        identity.get("name")
        or identity.get("qualname")
        or identity.get("slug")
        or identity.get("path")
        or display_entity(entity)
    )


def _planning_context_endpoint_entity_matches(entity: JsonObject, endpoint: str) -> bool:
    if entity.get("kind") != "Endpoint":
        return False
    return endpoint.strip().lower() in str(entity.get("identity", {}).get("path") or "").lower()


def _planning_context_event_channel_entity_matches(entity: JsonObject, event_channel: str) -> bool:
    if entity.get("kind") != "EventChannel":
        return False
    identity = entity.get("identity", {})
    return _planning_context_value_matches(event_channel, identity.get("channel_address"), identity.get("name"))


def _planning_context_domain_entity_matches(entity: JsonObject, domain: str) -> bool:
    if entity.get("kind") != "Domain":
        return False
    return str(entity.get("identity", {}).get("name") or "").strip().lower() == domain.strip().lower()


def _planning_context_value_matches(anchor: str, *candidates: object) -> bool:
    needle = anchor.strip().lower()
    normalized = {
        str(candidate).strip().lower()
        for candidate in candidates
        if candidate is not None and str(candidate).strip()
    }
    return needle in normalized


def _planning_context_normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _changed_ranges_by_path(changed_ranges: list[JsonObject]) -> dict[str, list[tuple[int, int]]]:
    by_path: dict[str, list[tuple[int, int]]] = {}
    for row in changed_ranges:
        by_path.setdefault(_planning_context_normalize_path(str(row["path"])), []).append(
            (int(row["start_line"]), int(row["end_line"]))
        )
    return by_path


def _review_context_symbol_overlaps_ranges(symbol: JsonObject, ranges: list[tuple[int, int]]) -> bool:
    start = symbol.get("line")
    if not isinstance(start, int):
        return False
    end = symbol.get("end_line")
    line_end = end if isinstance(end, int) else start
    for range_start, range_end in ranges:
        if start <= range_end and range_start <= line_end:
            return True
    return False


def _optional_symbol_path(symbol: JsonObject) -> str | None:
    path = symbol.get("path")
    return path if isinstance(path, str) and path else None


def _optional_symbol_line(symbol: JsonObject) -> int | None:
    line = symbol.get("line")
    return line if isinstance(line, int) else None


def _review_context_dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    deduped: list[JsonObject] = []
    seen: set[str] = set()
    for row in rows:
        key = str(
            row.get("fact_id")
            or row.get("symbol_id")
            or row.get("service_id")
            or row.get("qualified_name")
            or row
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _review_context_changed_surface(
    *,
    changed_files: list[str],
    range_filters: dict[str, list[tuple[int, int]]],
    symbols_by_path: dict[str, list[JsonObject]],
    changed_symbols: list[JsonObject],
) -> JsonObject:
    files = []
    for changed_file in changed_files:
        normalized_path = _planning_context_normalize_path(changed_file)
        ranges = [
            {"start_line": start_line, "end_line": end_line}
            for start_line, end_line in range_filters.get(normalized_path, [])
        ]
        files.append(
            {
                "path": changed_file,
                "normalized_path": normalized_path,
                "ranges": ranges,
                "symbol_count": len(symbols_by_path.get(normalized_path, [])),
            }
        )
    return {
        "files": files,
        "symbols": _planning_context_public_rows(changed_symbols)[:PLANNING_CONTEXT_SECTION_LIMIT],
    }


def _review_context_runtime_surfaces(
    kg: KgSnapshot,
    *,
    repo: str,
    changed_symbols: list[JsonObject],
    limit: int,
) -> dict[str, list[JsonObject]]:
    changed_symbol_ids = {
        str(row["symbol_id"]) for row in changed_symbols if isinstance(row.get("symbol_id"), str) and row["symbol_id"]
    }
    endpoints: list[JsonObject] = []
    exposed_endpoints: list[JsonObject] = []
    event_channels: list[JsonObject] = []
    deploy_mappings: list[JsonObject] = []
    for fact in kg.facts:
        predicate = fact.get("predicate")
        if predicate not in {
            "EXPOSES_ENDPOINT",
            "CALLS_ENDPOINT",
            "DOCUMENTS_ENDPOINT",
            "REFERENCES_EVENT_CHANNEL",
            "CONSUMES_EVENT",
            "PRODUCES_EVENT",
            "ROUTES_DOMAIN_TO_DEPLOY",
            "DEPLOYS_VIA_CONFIG",
        }:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if not _review_context_fact_is_in_review_scope(
            subject,
            object_,
            repo=repo,
            changed_symbol_ids=changed_symbol_ids,
        ):
            continue
        row = _fact_result(kg, fact, subject, object_)
        if predicate in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}:
            endpoints.append(row)
            if predicate == "EXPOSES_ENDPOINT":
                exposed_endpoints.append(_planning_context_fact_result(kg, fact, subject, object_))
        elif predicate in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}:
            event_channels.append(row)
        elif predicate in {"ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}:
            deploy_mappings.append(row)
    endpoint_consumers = _endpoint_consumer_rows_for_exposed_endpoints(kg, exposed_endpoints)
    return {
        "endpoints": _planning_context_dedupe_rows(endpoints)[:limit],
        "endpoint_consumers": endpoint_consumers[:limit],
        "event_channels": _planning_context_dedupe_rows(event_channels)[:limit],
        "deploy_mappings": _planning_context_dedupe_rows(deploy_mappings)[:limit],
    }


def _review_context_fact_is_in_review_scope(
    subject: JsonObject,
    object_: JsonObject,
    *,
    repo: str,
    changed_symbol_ids: set[str],
) -> bool:
    if subject.get("entity_id") in changed_symbol_ids or object_.get("entity_id") in changed_symbol_ids:
        return True
    repo_key = _normalize_repo_text(repo)
    return any(_normalize_repo_text(_review_context_entity_repo(entity)) == repo_key for entity in (subject, object_))


def _review_context_entity_repo(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    repo = identity.get("repo") or properties.get("repo")
    return str(repo) if repo is not None else None


def _review_context_summary(
    *,
    changed_files: list[str],
    changed_symbols: list[JsonObject],
    direct_callers: list[JsonObject],
    direct_callees: list[JsonObject],
    repo_dependencies: list[JsonObject],
    endpoints: list[JsonObject],
    endpoint_consumers: list[JsonObject],
    event_channels: list[JsonObject],
    deploy_mappings: list[JsonObject],
    source_coordinates: list[JsonObject],
) -> JsonObject:
    return {
        "changed_file_count": len(changed_files),
        "changed_symbol_count": len(changed_symbols),
        "direct_caller_count": len(direct_callers),
        "direct_callee_count": len(direct_callees),
        "repo_dependency_count": len(repo_dependencies),
        "endpoint_fact_count": len(endpoints),
        "endpoint_consumer_fact_count": len(endpoint_consumers),
        "event_fact_count": len(event_channels),
        "deploy_mapping_count": len(deploy_mappings),
        "source_coordinate_count": len(source_coordinates),
        "section_limit": PLANNING_CONTEXT_SECTION_LIMIT,
    }


def _review_context_answerability(
    *,
    status: str,
    changed_symbols: list[JsonObject],
    include_deploy_blockers: bool,
) -> JsonObject:
    if status == "not_found":
        return {
            "status": "not_answerable",
            "missing_fact_families": ["review_anchor"],
            "recommended_followups": ["Read the changed files directly or pass narrower changed_ranges."],
        }
    missing = []
    if not changed_symbols:
        missing.append("changed_symbols")
    if include_deploy_blockers:
        missing.append("deploy_blockers")
    return {
        "status": "partial" if missing else "answerable",
        "missing_fact_families": missing,
        "recommended_followups": _review_context_answerability_followups(missing),
    }


def _review_context_answerability_followups(missing: list[str]) -> list[str]:
    actions = []
    if "changed_symbols" in missing:
        actions.append("Read the changed files directly; no indexed symbols overlapped the review scope.")
    if "deploy_blockers" in missing:
        actions.append("Use deployment manifests or source inspection; deploy-blocker facts are unsupported by the current KG.")
    return actions


def _review_context_next_actions(
    answerability: JsonObject,
    *,
    unsupported_scopes: list[JsonObject],
) -> list[str]:
    actions = list(answerability.get("recommended_followups", []))
    if unsupported_scopes:
        actions.append("Treat unsupported_review_scopes as explicit coverage gaps, not as findings.")
    return actions


def _dependency_importer_packet(kg: KgSnapshot, dependencies: list[JsonObject], *, limit: int) -> JsonObject:
    package_ids = _dependency_package_ids(kg, dependencies)
    if not package_ids:
        return {
            "summary": {
                "package_count": 0,
                "importer_fact_count": 0,
                "importer_repo_count": 0,
                "section_limit": limit,
            },
            "packages": [],
            "importers": [],
            "repo_counts": {},
            "truncated": False,
        }
    packages = [
        kg.entities_by_id[package_id]
        for package_id in sorted(package_ids)
        if package_id in kg.entities_by_id
    ]
    importers: list[JsonObject] = []
    repo_counts: dict[str, int] = {}
    for fact in kg.facts:
        if fact.get("predicate") != "IMPORTS" or fact.get("object_id") not in package_ids:
            continue
        module = kg.entities_by_id.get(fact.get("subject_id"))
        package = kg.entities_by_id.get(fact.get("object_id"))
        if not module or not package:
            continue
        repo = _planning_context_entity_repo(module) or "unknown"
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
        importers.append(_fact_result(kg, fact, module, package))
    importers = _planning_context_dedupe_rows(importers)
    return {
        "summary": {
            "package_count": len(packages),
            "importer_fact_count": len(importers),
            "importer_repo_count": len(repo_counts),
            "section_limit": limit,
        },
        "packages": [
            {
                "package_id": package.get("entity_id"),
                "name": display_entity(package),
                "identity": package.get("identity", {}),
                "properties": package.get("properties", {}),
            }
            for package in packages[:limit]
        ],
        "importers": importers[:limit],
        "repo_counts": dict(sorted(repo_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]),
        "truncated": len(packages) > limit or len(importers) > limit or len(repo_counts) > limit,
    }


def _dependency_package_ids(kg: KgSnapshot, dependencies: list[JsonObject]) -> set[str]:
    facts_by_id = {str(fact.get("fact_id")): fact for fact in kg.facts if fact.get("fact_id")}
    package_ids: set[str] = set()
    for row in dependencies:
        fact_id = row.get("fact_id")
        if not isinstance(fact_id, str):
            continue
        fact = facts_by_id.get(fact_id)
        if not fact:
            continue
        predicate = fact.get("predicate")
        if predicate == "IMPORTS":
            package_ids.add(str(fact.get("object_id")))
        elif predicate in {"RESOLVES_TO_REPO", "RESOLVES_TO_SERVICE"}:
            package_ids.add(str(fact.get("subject_id")))
    return package_ids


def _planning_context_service_operational_surfaces(
    kg: KgSnapshot,
    services: list[JsonObject],
    *,
    limit: int,
) -> JsonObject:
    if len(services) != 1:
        return {
            "status": "not_computed",
            "reason": "service operational surfaces require one resolved service",
        }
    service_id = services[0].get("service_id") or services[0].get("entity_id")
    if not isinstance(service_id, str):
        return {
            "status": "not_computed",
            "reason": "resolved service missing service_id",
        }
    service = kg.entities_by_id.get(service_id)
    if not service:
        return {
            "status": "not_computed",
            "reason": "resolved service not found in snapshot",
        }
    return {
        "status": "found",
        **_service_operational_surfaces(kg, service, limit=limit),
    }


def _planning_context_service_related_rows(kg: KgSnapshot, service: JsonObject, *, limit: int) -> dict[str, list[JsonObject]]:
    related = _facts_touching_entity(kg, str(service["entity_id"]))
    exposed_endpoint_rows = _exposed_endpoint_rows_for_service_id(kg, str(service["entity_id"]))
    return {
        "dependencies": [
            row
            for row in related
            if row.get("predicate") in {"IMPORTS", "RESOLVES_TO_REPO", "RESOLVES_TO_SERVICE"}
        ][:limit],
        "endpoints": [
            row
            for row in related
            if row.get("predicate") in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}
        ][:limit],
        "endpoint_consumers": _endpoint_consumer_rows_for_exposed_endpoints(kg, exposed_endpoint_rows)[:limit],
        "event_channels": [
            row
            for row in related
            if row.get("predicate") in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}
        ][:limit],
        "domains": [
            row
            for row in related
            if row.get("predicate") in {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}
        ][:limit],
    }


def _planning_context_output(
    *,
    kg: KgSnapshot,
    query: str | None,
    anchors: dict[str, str | None],
    services: list[JsonObject],
    symbols: list[JsonObject],
    dependencies: list[JsonObject],
    endpoints: list[JsonObject],
    endpoint_consumers: list[JsonObject],
    event_channels: list[JsonObject],
    domains: list[JsonObject],
    next_actions: list[str],
    status: str,
) -> JsonObject:
    dependency_importers = _dependency_importer_packet(kg, dependencies, limit=PLANNING_CONTEXT_SECTION_LIMIT)
    bounded_services = _planning_context_public_rows(services)
    bounded_symbols = _planning_context_public_rows(symbols)
    bounded_dependencies = _planning_context_public_rows(dependencies)
    bounded_endpoints = _planning_context_public_rows(endpoints)
    bounded_endpoint_consumers = _planning_context_public_rows(endpoint_consumers)
    bounded_event_channels = _planning_context_public_rows(event_channels)
    bounded_domains = _planning_context_public_rows(domains)
    groups = {
        "services": bounded_services,
        "symbols": bounded_symbols,
        "dependencies": bounded_dependencies,
        "endpoints": bounded_endpoints,
        "endpoint_consumers": bounded_endpoint_consumers,
        "event_channels": bounded_event_channels,
        "domains": bounded_domains,
    }
    inventory = _snapshot_inventory_packet(kg, anchors=anchors, limit=PLANNING_CONTEXT_SECTION_LIMIT)
    service_operational_surfaces = _planning_context_service_operational_surfaces(
        kg,
        bounded_services,
        limit=PLANNING_CONTEXT_SECTION_LIMIT,
    )
    related_facts = _planning_context_related_facts(
        kg=kg,
        services=bounded_services,
        symbols=bounded_symbols,
        dependencies=bounded_dependencies,
        endpoints=bounded_endpoints,
        endpoint_consumers=bounded_endpoint_consumers,
        event_channels=bounded_event_channels,
        domains=bounded_domains,
        anchors=anchors,
        status=status,
        dependency_importers=dependency_importers,
        inventory=inventory,
        service_operational_surfaces=service_operational_surfaces,
    )
    source_coordinates = _planning_context_source_coordinates(
        bounded_services,
        bounded_symbols,
        bounded_dependencies,
        bounded_endpoints,
        bounded_endpoint_consumers,
        bounded_event_channels,
        bounded_domains,
        limit=PLANNING_CONTEXT_SECTION_LIMIT,
    )
    snapshot_scope = _planning_context_snapshot_scope(kg, anchors)
    if status == "not_found" and _planning_context_has_indexed_scope(snapshot_scope):
        next_actions = [action for action in next_actions if action != PLANNING_CONTEXT_NO_OVERLAP_ACTION]
        next_actions.append(
            "The repo anchor has indexed snapshot scope but no matching first-class dependency, endpoint, event, domain, service, or symbol rows for the supplied filters."
        )
        next_actions.append(
            "Use `snapshot_summary` and `snapshot_scope` for KG inventory counts, then inspect source or narrower anchors for behavioral claims."
        )
    answerability = _planning_context_answerability(status=status, anchors=anchors, groups=groups)
    return {
        "status": status,
        "query": query,
        "summary": _planning_context_summary(groups, source_coordinates=source_coordinates),
        "snapshot_summary": _planning_context_snapshot_summary(kg),
        "snapshot_scope": snapshot_scope,
        "inventory": inventory,
        "service_operational_surfaces": service_operational_surfaces,
        "anchors": {
            "repo": anchors.get("repo"),
            "path": anchors.get("path"),
            "symbol": anchors.get("symbol"),
            "service": anchors.get("service"),
            "package": anchors.get("package"),
            "endpoint": anchors.get("endpoint"),
            "event_channel": anchors.get("event_channel"),
            "domain": anchors.get("domain"),
        },
        "services": bounded_services,
        "symbols": bounded_symbols,
        "dependencies": bounded_dependencies,
        "endpoints": bounded_endpoints,
        "endpoint_consumers": bounded_endpoint_consumers,
        "event_channels": bounded_event_channels,
        "domains": bounded_domains,
        "entry_points": _planning_context_entry_points(groups),
        "related_facts": related_facts,
        "source_coordinates": source_coordinates,
        "answerability": answerability,
        "evidence": _planning_context_evidence(
            bounded_services,
            bounded_symbols,
            bounded_dependencies,
            bounded_endpoints,
            bounded_endpoint_consumers,
            bounded_event_channels,
            bounded_domains,
        ),
        "coverage_warnings": [],
        "unsupported_scopes": [],
        "next_actions": next_actions,
    }


def _planning_context_summary(groups: dict[str, list[JsonObject]], *, source_coordinates: list[JsonObject]) -> JsonObject:
    return {
        "service_count": len(groups["services"]),
        "symbol_count": len(groups["symbols"]),
        "dependency_count": len(groups["dependencies"]),
        "endpoint_fact_count": len(groups["endpoints"]),
        "endpoint_consumer_fact_count": len(groups["endpoint_consumers"]),
        "event_fact_count": len(groups["event_channels"]),
        "domain_fact_count": len(groups["domains"]),
        "source_coordinate_count": len(source_coordinates),
        "section_limit": PLANNING_CONTEXT_SECTION_LIMIT,
    }


def _planning_context_snapshot_summary(kg: KgSnapshot) -> JsonObject:
    summary = kg.summary()
    entity_kinds = _top_count_map(summary.get("entity_kinds", {}), limit=10)
    predicates = _top_count_map(summary.get("predicates", {}), limit=10)
    coverage = summary.get("coverage", [])
    coverage_states: dict[str, int] = {}
    if isinstance(coverage, list):
        for row in coverage:
            if not isinstance(row, dict):
                continue
            state = str(row.get("state") or "unknown")
            coverage_states[state] = coverage_states.get(state, 0) + 1
    return {
        "entity_count": len(kg.entities),
        "fact_count": len(kg.facts),
        "evidence_count": len(kg.evidence),
        "coverage_count": len(kg.coverage),
        "top_entity_kinds": entity_kinds,
        "top_predicates": predicates,
        "coverage_states": dict(sorted(coverage_states.items())),
    }


def _snapshot_inventory_packet(
    kg: KgSnapshot,
    *,
    anchors: dict[str, str | None],
    limit: int,
) -> JsonObject:
    repo = anchors.get("repo")
    repo_key = _normalize_repo_text(repo)
    scoped = bool(repo_key)
    coverage_rows = [
        row
        for row in kg.coverage
        if isinstance(row, dict) and (not scoped or _planning_context_coverage_row_matches_repo(row, repo_key))
    ]
    top_dependencies = _top_dependency_rows(kg, repo_key=repo_key if scoped else None, limit=limit)
    coverage_state_counts = _coverage_counts(coverage_rows, "state", limit=10)
    coverage_predicate_counts = _coverage_counts(coverage_rows, "predicate", limit=10)
    coverage_reason_counts = _coverage_counts(coverage_rows, "reason", limit=10)
    runtime_counts = _runtime_inventory_counts(kg, repo_key=repo_key if scoped else None)
    gap_samples = _coverage_gap_samples(coverage_rows, limit=limit)
    return {
        "scope": {"kind": "repo", "repo": repo} if scoped else {"kind": "fleet"},
        "summary": {
            "entity_count": _inventory_entity_count(kg, repo_key=repo_key if scoped else None),
            "fact_count": _inventory_fact_count(kg, repo_key=repo_key if scoped else None),
            "coverage_count": len(coverage_rows),
            "top_dependency_count": len(top_dependencies),
            "coverage_gap_sample_count": len(gap_samples),
            "section_limit": limit,
        },
        "top_dependencies": top_dependencies,
        "coverage": {
            "state_counts": coverage_state_counts,
            "predicate_counts": coverage_predicate_counts,
            "reason_counts": coverage_reason_counts,
            "gap_samples": gap_samples,
        },
        "runtime_counts": runtime_counts,
    }


def _top_dependency_rows(kg: KgSnapshot, *, repo_key: str | None, limit: int) -> list[JsonObject]:
    counts: dict[str, JsonObject] = {}
    for fact in kg.facts:
        if fact.get("predicate") != "IMPORTS":
            continue
        module = kg.entities_by_id.get(fact.get("subject_id"))
        package = kg.entities_by_id.get(fact.get("object_id"))
        if not module or not package or package.get("kind") != "ExternalPackage":
            continue
        if repo_key is not None and _planning_context_entity_repo(module) != repo_key:
            continue
        qualifier = fact.get("qualifier", {})
        if not isinstance(qualifier, dict):
            qualifier = {}
        category = qualifier.get("category")
        if category in {"stdlib", "node_builtin", "unknown"}:
            continue
        name = str(package.get("identity", {}).get("name") or display_entity(package))
        row = counts.setdefault(
            name,
            {
                "name": name,
                "category": category,
                "import_root": qualifier.get("import_root"),
                "distribution_name": qualifier.get("distribution_name"),
                "importer_count": 0,
                "sample_evidence": [],
            },
        )
        row["importer_count"] += 1
        if len(row["sample_evidence"]) < 2:
            row["sample_evidence"].extend(kg.evidence_by_target.get(fact["fact_id"], [])[:1])
    return sorted(counts.values(), key=lambda row: (-int(row["importer_count"]), str(row["name"])))[:limit]


def _coverage_counts(rows: list[JsonObject], field: str, *, limit: int) -> JsonObject:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _coverage_gap_samples(rows: list[JsonObject], *, limit: int) -> list[JsonObject]:
    samples = []
    for row in rows:
        state = str(row.get("state") or "")
        if state not in {"partially_instrumented", "uninstrumented"}:
            continue
        samples.append(
            {
                "state": row.get("state"),
                "predicate": row.get("predicate"),
                "reason": row.get("reason"),
                "scope_ref": row.get("scope_ref"),
            }
        )
        if len(samples) >= limit:
            break
    return samples


def _runtime_inventory_counts(kg: KgSnapshot, *, repo_key: str | None) -> JsonObject:
    entity_kinds = {"Service", "Endpoint", "EventChannel", "Domain", "DeployTarget"}
    predicate_kinds = {
        "EXPOSES_ENDPOINT",
        "CALLS_ENDPOINT",
        "PRODUCES_EVENT",
        "CONSUMES_EVENT",
        "REFERENCES_DOMAIN",
        "ROUTES_DOMAIN_TO_DEPLOY",
        "DEPLOYS_VIA_CONFIG",
    }
    entities: dict[str, int] = {}
    facts: dict[str, int] = {}
    for entity in kg.entities:
        kind = str(entity.get("kind"))
        if kind not in entity_kinds:
            continue
        if repo_key is not None and _planning_context_entity_repo(entity) != repo_key:
            continue
        entities[kind] = entities.get(kind, 0) + 1
    for fact in kg.facts:
        predicate = str(fact.get("predicate"))
        if predicate not in predicate_kinds:
            continue
        if repo_key is not None and not _fact_touches_repo(kg, fact, repo_key):
            continue
        facts[predicate] = facts.get(predicate, 0) + 1
    return {
        "entity_counts": dict(sorted(entities.items())),
        "fact_counts": dict(sorted(facts.items())),
    }


def _inventory_entity_count(kg: KgSnapshot, *, repo_key: str | None) -> int:
    if repo_key is None:
        return len(kg.entities)
    return sum(1 for entity in kg.entities if _planning_context_entity_repo(entity) == repo_key)


def _inventory_fact_count(kg: KgSnapshot, *, repo_key: str | None) -> int:
    if repo_key is None:
        return len(kg.facts)
    return sum(1 for fact in kg.facts if _fact_touches_repo(kg, fact, repo_key))


def _fact_touches_repo(kg: KgSnapshot, fact: JsonObject, repo_key: str) -> bool:
    subject = kg.entities_by_id.get(fact.get("subject_id"))
    object_ = kg.entities_by_id.get(fact.get("object_id"))
    if subject and _planning_context_entity_repo(subject) == repo_key:
        return True
    if object_ and _planning_context_entity_repo(object_) == repo_key:
        return True
    qualifier = fact.get("qualifier", {})
    return isinstance(qualifier, dict) and _normalize_repo_text(qualifier.get("consumer_repo")) == repo_key


def _planning_context_snapshot_scope(kg: KgSnapshot, anchors: dict[str, str | None]) -> JsonObject:
    repo = anchors.get("repo")
    if not repo:
        return {}
    repo_key = _normalize_repo_text(repo)
    entity_count = sum(1 for entity in kg.entities if _planning_context_entity_repo(entity) == repo_key)
    fact_count = 0
    for fact in kg.facts:
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if subject and _planning_context_entity_repo(subject) == repo_key:
            fact_count += 1
            continue
        if object_ and _planning_context_entity_repo(object_) == repo_key:
            fact_count += 1
            continue
        qualifier = fact.get("qualifier", {})
        if isinstance(qualifier, dict) and _normalize_repo_text(qualifier.get("consumer_repo")) == repo_key:
            fact_count += 1
    coverage_rows = [
        row
        for row in kg.coverage
        if isinstance(row, dict) and _planning_context_coverage_row_matches_repo(row, repo_key)
    ]
    coverage_states: dict[str, int] = {}
    coverage_predicates: dict[str, int] = {}
    for row in coverage_rows:
        state = str(row.get("state") or "unknown")
        predicate = str(row.get("predicate") or "unknown")
        coverage_states[state] = coverage_states.get(state, 0) + 1
        coverage_predicates[predicate] = coverage_predicates.get(predicate, 0) + 1
    return {
        "repo": repo,
        "entity_count": entity_count,
        "fact_count": fact_count,
        "coverage_count": len(coverage_rows),
        "coverage_states": dict(sorted(coverage_states.items())),
        "coverage_predicates": _top_count_map(coverage_predicates, limit=10),
    }


def _planning_context_has_indexed_scope(snapshot_scope: JsonObject) -> bool:
    return any(
        isinstance(snapshot_scope.get(field), int) and int(snapshot_scope[field]) > 0
        for field in ("entity_count", "fact_count", "coverage_count")
    )


def _planning_context_coverage_row_matches_repo(row: JsonObject, repo_key: str) -> bool:
    scope_ref = row.get("scope_ref")
    if not isinstance(scope_ref, dict):
        return False
    return _normalize_repo_text(scope_ref.get("repo")) == repo_key


def _top_count_map(raw_counts: object, *, limit: int) -> JsonObject:
    if not isinstance(raw_counts, dict):
        return {}
    rows = []
    for key, value in raw_counts.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        rows.append((str(key), value))
    return dict(sorted(rows, key=lambda item: (-item[1], item[0]))[:limit])


def _planning_context_entry_points(groups: dict[str, list[JsonObject]]) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for kind in ("services", "symbols", "endpoints", "endpoint_consumers", "event_channels", "dependencies", "domains"):
        for row in groups[kind]:
            entry = {key: value for key, value in row.items() if key != "evidence"}
            entry["section"] = kind
            rows.append(entry)
            if len(rows) >= PLANNING_CONTEXT_SECTION_LIMIT:
                return rows
    return rows


def _planning_context_related_facts(
    *,
    kg: KgSnapshot,
    services: list[JsonObject],
    symbols: list[JsonObject],
    dependencies: list[JsonObject],
    endpoints: list[JsonObject],
    endpoint_consumers: list[JsonObject],
    event_channels: list[JsonObject],
    domains: list[JsonObject],
    anchors: dict[str, str | None],
    status: str,
    dependency_importers: JsonObject,
    inventory: JsonObject,
    service_operational_surfaces: JsonObject,
) -> JsonObject:
    return {
        "service_brief": _planning_context_service_brief(services, endpoints, endpoint_consumers, event_channels, domains),
        "symbol_impact": _planning_context_symbol_impact(kg, symbols, anchors=anchors, status=status),
        "dependency_importers": dependency_importers,
        "inventory": inventory,
        "service_operational_surfaces": service_operational_surfaces,
        "dependencies": dependencies[:PLANNING_CONTEXT_SECTION_LIMIT],
        "endpoints": endpoints[:PLANNING_CONTEXT_SECTION_LIMIT],
        "endpoint_consumers": endpoint_consumers[:PLANNING_CONTEXT_SECTION_LIMIT],
        "event_channels": event_channels[:PLANNING_CONTEXT_SECTION_LIMIT],
        "deploy_mappings": [
            row for row in domains if row.get("predicate") in {"ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}
        ][:PLANNING_CONTEXT_SECTION_LIMIT],
        "domains": domains[:PLANNING_CONTEXT_SECTION_LIMIT],
    }


def _planning_context_service_brief(
    services: list[JsonObject],
    endpoints: list[JsonObject],
    endpoint_consumers: list[JsonObject],
    event_channels: list[JsonObject],
    domains: list[JsonObject],
) -> JsonObject:
    deploy_mappings = [row for row in domains if row.get("predicate") in {"ROUTES_DOMAIN_TO_DEPLOY", "DEPLOYS_VIA_CONFIG"}]
    return {
        "services": services[:PLANNING_CONTEXT_SECTION_LIMIT],
        "summary": {
            "service_count": len(services),
            "endpoint_fact_count": len(endpoints),
            "endpoint_consumer_fact_count": len(endpoint_consumers),
            "event_fact_count": len(event_channels),
            "deploy_mapping_count": len(deploy_mappings),
        },
        "endpoints": endpoints[:PLANNING_CONTEXT_SECTION_LIMIT],
        "endpoint_consumers": endpoint_consumers[:PLANNING_CONTEXT_SECTION_LIMIT],
        "event_channels": event_channels[:PLANNING_CONTEXT_SECTION_LIMIT],
        "deploy_mappings": deploy_mappings[:PLANNING_CONTEXT_SECTION_LIMIT],
    }


def _planning_context_symbol_impact(
    kg: KgSnapshot,
    symbols: list[JsonObject],
    *,
    anchors: dict[str, str | None],
    status: str,
) -> JsonObject:
    if status != "found" or not anchors.get("symbol") or len(symbols) != 1:
        return {"status": "not_computed", "reason": "symbol impact requires one resolved symbol anchor"}
    symbol_name = symbols[0].get("qualified_name") or symbols[0].get("qualname")
    if not isinstance(symbol_name, str) or not symbol_name:
        return {"status": "not_computed", "reason": "resolved symbol missing qualified name"}
    return {
        "status": "found",
        "symbol": symbols[0],
        "direct_callers": list(
            kg.find_callers(
                symbol_name,
                path=_optional_symbol_path(symbols[0]),
                line=_optional_symbol_line(symbols[0]),
                limit=PLANNING_CONTEXT_SECTION_LIMIT,
            ).get("callers", [])
        ),
        "direct_callees": list(
            kg.find_callees(
                symbol_name,
                path=_optional_symbol_path(symbols[0]),
                line=_optional_symbol_line(symbols[0]),
                limit=PLANNING_CONTEXT_SECTION_LIMIT,
            ).get("callees", [])
        ),
    }


def _planning_context_answerability(
    *,
    status: str,
    anchors: dict[str, str | None],
    groups: dict[str, list[JsonObject]],
) -> JsonObject:
    if status == "ambiguous":
        return {
            "status": "not_answerable",
            "missing_fact_families": ["unambiguous_primary_anchor"],
            "recommended_followups": ["Refine the query with a structured anchor or source coordinate."],
        }
    if status == "not_found":
        return {
            "status": "not_answerable",
            "missing_fact_families": ["primary_anchor"],
            "recommended_followups": ["Broaden or correct the supplied planning anchor."],
        }
    missing = _planning_context_missing_fact_families(anchors, groups)
    return {
        "status": "partial" if missing else "answerable",
        "missing_fact_families": missing,
        "recommended_followups": _planning_context_answerability_followups(missing),
    }


def _planning_context_missing_fact_families(
    anchors: dict[str, str | None],
    groups: dict[str, list[JsonObject]],
) -> list[str]:
    missing = []
    if anchors.get("service") and not groups["services"]:
        missing.append("service_identity")
    if (anchors.get("symbol") or anchors.get("path")) and not groups["symbols"]:
        missing.append("symbol_identity")
    if (anchors.get("repo") or anchors.get("package")) and not groups["dependencies"]:
        missing.append("dependency_edges")
    if anchors.get("endpoint") and not groups["endpoints"]:
        missing.append("endpoint_facts")
    if anchors.get("event_channel") and not groups["event_channels"]:
        missing.append("event_facts")
    if anchors.get("domain") and not groups["domains"]:
        missing.append("domain_facts")
    return missing


def _planning_context_answerability_followups(missing: list[str]) -> list[str]:
    actions = []
    if "service_identity" in missing:
        actions.append("Use `search_services` to find candidate service slugs or retry with the exact service repo/name.")
    if "symbol_identity" in missing:
        actions.append("Retry with an exact qualified symbol name, or add `path` and `line` to disambiguate the source anchor.")
    if "dependency_edges" in missing:
        actions.append("Use `repo` or `package` alone to inspect dependency edges, or fall back to source inspection.")
    if "endpoint_facts" in missing:
        actions.append("Use endpoint-specific tools or source inspection to verify route ownership.")
    if "event_facts" in missing:
        actions.append("Use event producer/consumer tools or source inspection to verify event flow.")
    if "domain_facts" in missing:
        actions.append("Use domain lookup or source inspection to verify runtime host references.")
    return actions


def _planning_context_source_coordinates(*groups: list[JsonObject], limit: int) -> list[JsonObject]:
    coordinates: list[JsonObject] = []
    seen: set[tuple[object, object, object, object, object]] = set()
    for group in groups:
        for row in group:
            for coordinate in _planning_context_row_source_coordinates(row):
                key = (
                    coordinate.get("repo"),
                    coordinate.get("commit_sha"),
                    coordinate.get("path"),
                    coordinate.get("line_start"),
                    coordinate.get("line_end"),
                )
                if key in seen:
                    continue
                seen.add(key)
                coordinates.append(coordinate)
                if len(coordinates) >= limit:
                    return coordinates
    return coordinates


def _planning_context_row_source_coordinates(row: JsonObject) -> list[JsonObject]:
    coordinates: list[JsonObject] = []
    for evidence in row.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        bytes_ref = evidence.get("bytes_ref")
        if not isinstance(bytes_ref, dict):
            continue
        coordinate = _planning_context_coordinate_from_bytes_ref(bytes_ref, evidence=evidence)
        if coordinate is not None:
            coordinates.append(coordinate)
    coordinate = _planning_context_coordinate_from_row(row)
    if coordinate is not None:
        geometry_key = _coordinate_location_key(coordinate)
        if any(_coordinate_location_key(existing) == geometry_key for existing in coordinates):
            return coordinates
        coordinates.append(coordinate)
    return coordinates


def _coordinate_location_key(coordinate: JsonObject) -> tuple[object, object, object, object]:
    return (
        coordinate.get("repo"),
        coordinate.get("path"),
        coordinate.get("line_start"),
        coordinate.get("line_end"),
    )


def _planning_context_coordinate_from_bytes_ref(bytes_ref: JsonObject, *, evidence: JsonObject) -> JsonObject | None:
    path = bytes_ref.get("path")
    line_start = bytes_ref.get("line_start")
    if not isinstance(path, str) or not path.strip():
        return None
    if isinstance(line_start, bool) or not isinstance(line_start, int) or line_start < 1:
        return None
    line_end = bytes_ref.get("line_end")
    if isinstance(line_end, bool) or not isinstance(line_end, int) or line_end < line_start:
        line_end = line_start
    source_ref = evidence.get("source_ref") if isinstance(evidence.get("source_ref"), dict) else {}
    return {
        "repo": bytes_ref.get("repo") or source_ref.get("repo"),
        "commit_sha": bytes_ref.get("commit_sha") or source_ref.get("commit_sha"),
        "provenance": "bytes_ref",
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
    }


def _planning_context_coordinate_from_row(row: JsonObject) -> JsonObject | None:
    path = row.get("path")
    line = row.get("line")
    if not isinstance(path, str) or not path.strip():
        return None
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return None
    end_line = row.get("end_line")
    if isinstance(end_line, bool) or not isinstance(end_line, int) or end_line < line:
        end_line = line
    return {
        "repo": row.get("repo"),
        "commit_sha": row.get("commit_sha"),
        "provenance": "row_geometry",
        "path": path,
        "line_start": line,
        "line_end": end_line,
    }


def _planning_context_evidence(*groups: list[JsonObject]) -> list[JsonObject]:
    evidence: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for row in group:
            for item in row.get("evidence", []):
                if not isinstance(item, dict):
                    continue
                key = (str(item.get("target_type", "")), str(item.get("target_id", "")))
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(item)
                if len(evidence) >= 5:
                    return evidence
    return evidence


def _line_matches_symbol(line: int, symbol: JsonObject) -> bool:
    start = symbol.get("line")
    end = symbol.get("end_line")
    if not isinstance(start, int):
        return False
    line_end = end if isinstance(end, int) else start
    return start <= line <= line_end


def _planning_context_public_rows(rows: list[JsonObject]) -> list[JsonObject]:
    public_rows: list[JsonObject] = []
    for row in rows:
        public_rows.append({key: value for key, value in row.items() if not key.startswith("_")})
    return public_rows


def _planning_context_fact_result(kg: KgSnapshot, fact: JsonObject, subject: JsonObject, object_: JsonObject) -> JsonObject:
    return {
        **_fact_result(kg, fact, subject, object_),
        "_fact": fact,
        "_subject": subject,
        "_object": object_,
    }


def _planning_context_repo_matches(kg: KgSnapshot, repo: str) -> dict[str, list[JsonObject]]:
    matches: dict[str, list[JsonObject]] = {}
    repo_key = _normalize_repo_text(repo)
    for fact in kg.facts:
        if fact.get("predicate") != "RESOLVES_TO_REPO":
            continue
        qualifier = fact.get("qualifier", {})
        if _normalize_repo_text(qualifier.get("consumer_repo")) != repo_key:
            continue
        package = kg.entities_by_id.get(fact["subject_id"])
        target_repo = kg.entities_by_id.get(fact["object_id"])
        if not package or not target_repo:
            continue
        matches.setdefault(fact["subject_id"], []).append(
            {
                **_planning_context_fact_result(kg, fact, package, target_repo),
            }
        )
    return matches


def _planning_context_package_matches(kg: KgSnapshot, package_name: str) -> dict[str, list[JsonObject]]:
    matches: dict[str, list[JsonObject]] = {}
    for fact in kg.facts:
        if fact.get("predicate") != "IMPORTS":
            continue
        package = kg.entities_by_id.get(fact["object_id"])
        module = kg.entities_by_id.get(fact["subject_id"])
        if not package or not module:
            continue
        if not kg.import_matches(fact, package, package_name):
            continue
        matches.setdefault(fact["object_id"], []).append(
            {
                **_planning_context_fact_result(kg, fact, module, package),
            }
        )
    return matches


def _planning_context_endpoint_matches(kg: KgSnapshot, path_query: str) -> dict[str, list[JsonObject]]:
    matches: dict[str, list[JsonObject]] = {}
    needle = path_query.lower()
    for fact in kg.facts:
        if fact.get("predicate") not in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        endpoint = kg.entities_by_id.get(fact["object_id"])
        if not subject or not endpoint or endpoint.get("kind") != "Endpoint":
            continue
        path = str(endpoint.get("identity", {}).get("path", ""))
        if needle not in path.lower():
            continue
        matches.setdefault(fact["object_id"], []).append(
            {
                **_planning_context_fact_result(kg, fact, subject, endpoint),
            }
        )
    return matches


def _planning_context_event_matches(kg: KgSnapshot, query: str) -> dict[str, list[JsonObject]]:
    matches: dict[str, list[JsonObject]] = {}
    needle = query.lower()
    for fact in kg.facts:
        if fact.get("predicate") not in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        channel = kg.entities_by_id.get(fact["object_id"])
        if not subject or not channel or channel.get("kind") != "EventChannel":
            continue
        identity = channel.get("identity", {})
        name = str(identity.get("channel_address") or identity.get("name") or "")
        if needle not in name.lower():
            continue
        matches.setdefault(fact["object_id"], []).append(
            {
                **_planning_context_fact_result(kg, fact, subject, channel),
            }
        )
    return matches


def _planning_context_domain_matches(kg: KgSnapshot, query: str) -> dict[str, list[JsonObject]]:
    matches: dict[str, list[JsonObject]] = {}
    needle = query.lower()
    for fact in kg.facts:
        if fact.get("predicate") not in {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        domain = kg.entities_by_id.get(fact["object_id"])
        if not subject or not domain or domain.get("kind") != "Domain":
            continue
        domain_name = str(domain.get("identity", {}).get("name", ""))
        if needle not in domain_name.lower():
            continue
        matches.setdefault(fact["object_id"], []).append(
            {
                **_planning_context_fact_result(kg, fact, subject, domain),
            }
        )
    return matches


def _planning_context_collect_rows(rows_by_id: dict[str, list[JsonObject]], *, limit: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for match_id in sorted(rows_by_id):
        rows.extend(rows_by_id[match_id])
    return rows[:limit]


def _planning_context_dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    deduped: list[JsonObject] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("fact_id") or row.get("service_id") or row.get("symbol_id") or row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _planning_context_exact_endpoint_rows(kg: KgSnapshot, query: str, limit: int) -> list[JsonObject]:
    needle = _normalize_endpoint_query(query)
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") not in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        endpoint = kg.entities_by_id.get(fact["object_id"])
        if not subject or not endpoint or endpoint.get("kind") != "Endpoint":
            continue
        if _normalize_endpoint_query(str(endpoint.get("identity", {}).get("path", ""))) != needle:
            continue
        rows.append(_fact_result(kg, fact, subject, endpoint))
        if len(rows) >= limit:
            break
    return rows


def _planning_context_exact_event_rows(kg: KgSnapshot, query: str, limit: int) -> list[JsonObject]:
    needle = query.strip().lower()
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") not in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        channel = kg.entities_by_id.get(fact["object_id"])
        if not subject or not channel or channel.get("kind") != "EventChannel":
            continue
        identity = channel.get("identity", {})
        candidates = {
            str(identity.get("channel_address") or "").lower(),
            str(identity.get("name") or "").lower(),
            _event_channel_search_text(channel).lower(),
        }
        if needle not in candidates:
            continue
        rows.append(_fact_result(kg, fact, subject, channel))
        if len(rows) >= limit:
            break
    return rows


def _planning_context_exact_domain_rows(kg: KgSnapshot, query: str, limit: int) -> list[JsonObject]:
    needle = query.strip().lower()
    rows: list[JsonObject] = []
    for fact in kg.facts:
        if fact.get("predicate") not in {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"}:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        domain = kg.entities_by_id.get(fact["object_id"])
        if not subject or not domain or domain.get("kind") != "Domain":
            continue
        if str(domain.get("identity", {}).get("name", "")).strip().lower() != needle:
            continue
        rows.append(_fact_result(kg, fact, subject, domain))
        if len(rows) >= limit:
            break
    return rows


def _normalize_endpoint_query(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized.rstrip("/") or "/"


def _symbol_refinement_actions(symbols: list[JsonObject]) -> list[str]:
    actions = [
        "Provide `symbol` with an exact qualified name, or add `path` and `line` to disambiguate the code anchor.",
    ]
    if symbols:
        actions.append(f"Candidate symbol: {symbols[0].get('qualified_name') or symbols[0].get('display_name')}.")
    return actions


def _service_refinement_actions(services: list[JsonObject]) -> list[str]:
    actions = ["Provide `service` with an exact slug or repo name."]
    if services:
        actions.append(f"Candidate service: {services[0].get('slug') or services[0].get('name')}.")
    return actions


def _service_exact_match(query: str, service: JsonObject) -> bool:
    needle = query.strip().lower()
    identity = service.get("identity", {})
    return needle in {
        str(display_entity(service)).lower(),
        str(identity.get("slug") or "").lower(),
        str(identity.get("repo") or "").lower(),
        str(identity.get("namespace") or "").lower(),
    }


_TOOLS: dict[str, McpTool] = {
    "search_services": McpTool(
        name="search_services",
        description=(
            "Searches indexed Service entities by name, slug, namespace, repo, or stored properties. "
            "Use it when you need candidate services before drilling into a specific service brief or dependency path. "
            "Does not return endpoint topology, caller graphs, deploy blockers, or runtime health."
        ),
        input_schema=_object_schema({"query": _nullable_string_schema("Optional service search text."), "limit": _limit_schema()}),
        handler=_search_services,
    ),
    "get_service_brief": McpTool(
        name="get_service_brief",
        description=(
            "Returns a compact service brief plus related endpoint, path-matched endpoint-consumer, event-channel, deploy-mapping, and operational domain/deploy-target candidate facts for one matched service. "
            "Use it after you know the target service and want a bounded operational summary of what the KG has linked to it. "
            "endpoint_consumers are static CALLS_ENDPOINT candidates matched by literal normalized endpoint path and compatible method; verify unresolved hosts/env before runtime or deploy claims. "
            "Read operational_surfaces.evidence_partition: known_linked uses exact repo-identity joins, unlinked_evidence is source leads only, and missing_contracts lists deploy/runtime claims the KG cannot prove. "
            "Treat operational_surfaces.deploy_link_facts / DEPLOYS_VIA_CONFIG as service-to-deploy-target evidence; do not promote unlinked domain routes into deploy proof. "
            "Does not traverse caller graphs, compute downstream blast radius, or infer missing runtime/deploy contracts; if deploy mappings are absent, inspect manifests before making environment claims."
        ),
        input_schema=_object_schema(
            {"service": _string_schema("Service name, slug, namespace, or repo."), "limit": _limit_schema()},
            required=["service"],
        ),
        handler=_get_service_brief,
    ),
    "find_callers": McpTool(
        name="find_callers",
        description=(
            "Returns static CALLS edges whose downstream target matches the requested symbol, with optional path and line disambiguation. "
            "Use it when you need reverse call impact for a known function, method, or symbol in the indexed codebase. "
            "If status is ambiguous, do not treat the empty callers list as no callers; retry with disambiguation.retry_arguments or a candidate qualified_name. "
            "Does not include transitive closure, runtime dispatch, cross-repo execution paths, endpoint/service-level rollups, or unresolved external-package call sites. "
            "A not_found result is not proof of absence; inspect source before finalizing."
        ),
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callers,
    ),
    "find_callees": McpTool(
        name="find_callees",
        description=(
            "Returns static CALLS edges whose upstream subject matches the requested symbol, with optional path and line disambiguation. "
            "Use it when you want the immediate downstream call surface of a known symbol before expanding to blast radius. "
            "If status is ambiguous, do not treat the empty callees list as no callees; retry with disambiguation.retry_arguments or a candidate qualified_name. "
            "Does not return reverse callers, transitive closure, runtime-only invocations, service and endpoint boundaries, or unresolved external-package calls. "
            "A not_found result is not proof of absence; inspect source before finalizing."
        ),
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callees,
    ),
    "get_event_consumers": McpTool(
        name="get_event_consumers",
        description=(
            "Returns facts whose subject consumes an event channel matching the provided queue, topic, ARN, or channel substring. "
            "Use it when you know the event channel and want the indexed static consumers attached to that channel. "
            "Does not infer delivery guarantees, runtime subscribers, message schemas, time-window usage, or cross-environment broker state."
        ),
        input_schema=_object_schema(
            {"channel": _string_schema("Event channel name, queue, topic, or ARN substring."), "limit": _limit_schema()},
            required=["channel"],
        ),
        handler=_get_event_consumers,
    ),
    "get_event_producers": McpTool(
        name="get_event_producers",
        description=(
            "Returns facts whose subject produces an event channel matching the provided queue, topic, ARN, or channel substring. "
            "Use it when you know the event channel and need the indexed static producers that emit onto it. "
            "Does not prove messages were published at runtime or in a time window, identify consumers, or recover schema and deployment guarantees."
        ),
        input_schema=_object_schema(
            {"channel": _string_schema("Event channel name, queue, topic, or ARN substring."), "limit": _limit_schema()},
            required=["channel"],
        ),
        handler=_get_event_producers,
    ),
    "blast_radius": McpTool(
        name="blast_radius",
        description=(
            "Returns downstream static CALLS closure from an anchor symbol up to `depth`. "
            "Use only when you know the exact edit-site symbol and want to enumerate intra-repo callees. "
            "If status is ambiguous, do not treat the empty edge list as no impact; retry with disambiguation.retry_arguments or a candidate qualified_name. "
            "Does not include reverse callers, cross-repo edges, service or endpoint boundaries, runtime calls, or unresolved external-package calls. "
            "A not_found result is not proof of absence; inspect source before finalizing."
        ),
        input_schema=_object_schema(
            {**_symbol_properties(), "depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 1}},
            required=["symbol"],
        ),
        handler=_blast_radius,
    ),
    "deploy_blockers_for": McpTool(
        name="deploy_blockers_for",
        description=(
            "Returns deploy-blocker information for a named service when the current KG implements that contract. "
            "Use it only when you need explicit deploy-blocker facts for a known service and can tolerate refusal when the graph lacks that relation. "
            "Does not infer blockers from callers, events, config drift, or undeclared operational dependencies; unsupported results require manifest/source inspection."
        ),
        input_schema=_object_schema({"service": _string_schema("Service name or slug."), "limit": _limit_schema()}, required=["service"]),
        handler=_deploy_blockers_for,
    ),
    "planning_context": McpTool(
        name="planning_context",
        description=(
            "Returns bounded planning context for one structured anchor such as a symbol, service, repo, package, endpoint, event channel, or domain. "
            "Includes additive grouped context: summary, snapshot_summary, snapshot_scope, inventory, entry_points, related_facts, source_coordinates with provenance, and answerability metadata. "
            "For service anchors, includes bounded endpoint_consumers from structured endpoint path/method matches when available. "
            "For service operational evidence, read service_operational_surfaces.evidence_partition and keep known_linked, unlinked_evidence, and missing_contracts separate. "
            "Treat service_operational_surfaces.deploy_link_facts / DEPLOYS_VIA_CONFIG as service-to-deploy-target evidence; do not promote unlinked domain routes into deploy proof. "
            "For dependency anchors, includes grouped importer evidence; for inventory questions, includes top dependencies and coverage gap samples. "
            "Top-level result rows honor limit; nested planning packets are capped by summary.section_limit to stay compact. "
            "Use it first for broad planning, architecture, dependency, or impact questions on deterministic anchors before selecting narrower MCP tools. "
            "For exact caller, callee, service-brief, or event producer/consumer questions, prefer the exact primitive tool. "
            "Does not expand free-form natural language, call an LLM, or fan one query across multiple ambiguous resolver paths."
        ),
        input_schema=_object_schema(_planning_context_properties()),
        handler=_planning_context,
    ),
    "review_context": McpTool(
        name="review_context",
        description=(
            "Returns bounded review context for one repo plus a changed-file set by composing changed_surface, impact, runtime_surfaces, source_coordinates, and answerability metadata. "
            "Existing top-level changed_symbols, direct_callers, direct_callees, and repo_dependencies remain available for compatibility. "
            "runtime_surfaces includes bounded path-matched endpoint_consumers for endpoints exposed by the review repo when static CALLS_ENDPOINT facts exist. "
            "Use it when you know the changed files and need deterministic static review context before drilling into narrower MCP tools. "
            "Does not infer deploy blockers unless explicitly requested, summarize diffs with an LLM, or invent cross-repo and runtime-only impact."
        ),
        input_schema=_object_schema(_review_context_properties(), required=["repo", "changed_files"]),
        handler=_review_context,
    ),
}
