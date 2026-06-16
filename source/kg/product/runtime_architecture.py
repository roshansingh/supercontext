from __future__ import annotations

from collections.abc import Callable
import ipaddress

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


RUNTIME_DOMAIN_PREDICATES = {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"}
RUNTIME_ENDPOINT_PREDICATES = {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}
RUNTIME_EVENT_PREDICATES = {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}
RUNTIME_DEPLOY_PREDICATES = {"DEPLOYS_VIA_CONFIG"}
RUNTIME_UNLINKED_DEPLOY_REASONS = {"ambiguous_wsgi_module_suffix", "no_target_bytes_ref_evidence"}
RUNTIME_COMPONENT_LIMIT = 12
RUNTIME_COMPONENT_HARD_CAP = 25
RUNTIME_COMPONENT_DETAIL_LIMIT = 1
RUNTIME_ROUTE_LIMIT = 20
RUNTIME_ROUTE_HARD_CAP = 50
RUNTIME_INVESTIGATION_BRIEF_LIMIT = 8
RUNTIME_INVESTIGATION_SOURCE_CHECK_LIMIT = 15
RUNTIME_LEADS_PER_KIND_CAP = 2


def runtime_architecture_packet(
    kg: KgSnapshot,
    *,
    repo: str | None,
    limit: int,
    include_legacy_sections: bool = True,
) -> JsonObject:
    repo_key = _normalize_repo(repo)
    domain_routes: list[JsonObject] = []
    deploy_links: list[JsonObject] = []
    deploy_candidate_rows: list[JsonObject] = []
    endpoint_rows: list[JsonObject] = []
    client_rows: list[JsonObject] = []
    event_rows: list[JsonObject] = []
    domain_references: list[JsonObject] = []

    scoped_endpoint_keys = _scoped_endpoint_keys(kg, repo_key)
    scoped_endpoint_paths = {path for _, path in scoped_endpoint_keys if path is not None}

    for fact in kg.facts:
        predicate = str(fact.get("predicate") or "")
        if predicate not in RUNTIME_DOMAIN_PREDICATES | RUNTIME_ENDPOINT_PREDICATES | RUNTIME_EVENT_PREDICATES | RUNTIME_DEPLOY_PREDICATES:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if repo_key is not None and not _fact_touches_repo(subject, object_, fact, repo_key):
            if predicate != "CALLS_ENDPOINT" or _endpoint_key(object_)[1] not in scoped_endpoint_paths:
                continue
        row = _fact_row(kg, fact, subject, object_)
        if predicate == "ROUTES_DOMAIN_TO_DEPLOY":
            domain_routes.append(row)
        elif predicate == "DEPLOYS_VIA_CONFIG":
            if _canonical_status(fact) == "canonical":
                deploy_links.append(row)
            else:
                deploy_candidate_rows.append(row)
        elif predicate == "CALLS_ENDPOINT":
            client_rows.append(row)
        elif predicate in {"EXPOSES_ENDPOINT", "DOCUMENTS_ENDPOINT"}:
            endpoint_rows.append(row)
        elif predicate in RUNTIME_EVENT_PREDICATES:
            event_rows.append(row)
        elif predicate == "REFERENCES_DOMAIN":
            domain_references.append(row)

    domain_routes = _dedupe_rows(domain_routes)
    deploy_links = _dedupe_rows(deploy_links)
    deploy_candidate_rows = _dedupe_rows(deploy_candidate_rows)
    endpoint_rows = _dedupe_rows(endpoint_rows)
    client_rows = _dedupe_rows(client_rows)
    event_rows = _dedupe_rows(event_rows)
    domain_references = _dedupe_rows(domain_references)
    component_limit = min(max(limit, RUNTIME_COMPONENT_LIMIT), RUNTIME_COMPONENT_HARD_CAP)
    # Keep each component compact; summary counts and truncated_sections carry the full local shape.
    component_detail_limit = RUNTIME_COMPONENT_DETAIL_LIMIT
    route_limit = min(max(limit, RUNTIME_ROUTE_LIMIT), RUNTIME_ROUTE_HARD_CAP)
    runtime_building_blocks = _runtime_building_blocks(
        kg,
        repo_key=repo_key,
        domain_routes=domain_routes,
        deploy_links=deploy_links,
        endpoint_rows=endpoint_rows,
        client_rows=client_rows,
        event_rows=event_rows,
        domain_references=domain_references,
        component_limit=component_limit,
        detail_limit=component_detail_limit,
    )
    domain_routing_map = _domain_routing_map(
        kg,
        domain_routes=domain_routes,
        deploy_links=deploy_links,
        domain_references=domain_references,
        limit=route_limit,
    )
    investigation_domain_routing_map = _domain_routing_map(
        kg,
        domain_routes=domain_routes,
        deploy_links=deploy_links,
        domain_references=domain_references,
        limit=RUNTIME_ROUTE_HARD_CAP,
    )
    deploy_runtime_map = _deploy_runtime_map(deploy_links=deploy_links, domain_routes=domain_routes, limit=route_limit)
    unlinked_deploy_leads = _unlinked_deploy_leads(
        kg,
        deploy_candidate_rows=deploy_candidate_rows,
        repo_key=repo_key,
    )
    endpoint_consumer_map, endpoint_consumer_missing_method_drop_count = _endpoint_consumer_map(
        endpoint_rows=endpoint_rows,
        client_rows=client_rows,
        limit=route_limit,
    )
    deploy_order_guidance = _runtime_deploy_order_guidance(endpoint_consumer_map, limit=route_limit)
    deploy_kind_counts = _deploy_kind_counts(runtime_building_blocks, domain_routing_map)
    missing_fact_families = _runtime_missing_fact_families(
        deploy_order_guidance=deploy_order_guidance,
        endpoint_consumer_map=endpoint_consumer_map,
    )
    investigation_brief = _runtime_investigation_brief(
        runtime_building_blocks=runtime_building_blocks,
        domain_routing_map=investigation_domain_routing_map,
        deploy_runtime_map=deploy_runtime_map,
        unlinked_deploy_leads=unlinked_deploy_leads,
        endpoint_consumer_map=endpoint_consumer_map,
        missing_fact_families=missing_fact_families,
        limit=min(max(limit, RUNTIME_INVESTIGATION_BRIEF_LIMIT), RUNTIME_COMPONENT_HARD_CAP),
    )

    packet = {
        "scope": {"kind": "repo", "repo": repo} if repo_key else {"kind": "fleet"},
        "summary": {
            "domain_route_count": len(domain_routes),
            "deploy_link_count": len(deploy_links),
            "candidate_or_unlinked_deploy_lead_count": len(unlinked_deploy_leads),
            "endpoint_surface_count": len(endpoint_rows),
            "client_endpoint_call_count": len(client_rows),
            "event_surface_count": len(event_rows),
            "domain_reference_count": len(domain_references),
            "runtime_building_block_count": len(runtime_building_blocks),
            "domain_routing_map_count": len(domain_routing_map),
            "deploy_runtime_unit_count": len(deploy_runtime_map),
            "endpoint_consumer_map_count": len(endpoint_consumer_map),
            "endpoint_consumer_missing_method_drop_count": endpoint_consumer_missing_method_drop_count,
            "deploy_order_guidance_count": len(deploy_order_guidance),
            "investigation_brief_anchor_count": len(investigation_brief["runtime_anchors"]),
            "investigation_brief_source_check_count": len(investigation_brief["recommended_source_checks"]),
            "section_limit": limit,
            "component_limit": component_limit,
            "component_detail_limit": component_detail_limit,
            "route_limit": route_limit,
        },
        "answer_packet": {
            "investigation_brief": investigation_brief,
            "runtime_building_blocks": runtime_building_blocks,
            "domain_routing_map": domain_routing_map,
            "deploy_runtime_map": deploy_runtime_map,
            "unlinked_deploy_leads": unlinked_deploy_leads[:route_limit],
            "endpoint_consumer_map": endpoint_consumer_map,
            "deploy_order_guidance": deploy_order_guidance,
            "deploy_kind_counts": deploy_kind_counts,
            "missing_fact_families": missing_fact_families,
            "evidence_contract": (
                "known_route rows come from ROUTES_DOMAIN_TO_DEPLOY and can be treated as domain-to-deploy evidence. "
                "deploy_link rows come from DEPLOYS_VIA_CONFIG and link services to deploy targets. "
                "unlinked_deploy_leads are candidate or unresolved service-to-deploy evidence and must not be treated as known deploy links. "
                "endpoint_consumer_map rows are proven static CALLS_ENDPOINT consumers matched to provider endpoints. "
                "deploy_order_guidance rows are practical compatibility inferences from those consumers, not canonical deploy-blocker facts. "
                "unlinked_domain_reference rows are source leads only and must not be promoted to proven routes. "
                "investigation_brief is a compact head start for agent source inspection, not a complete final answer."
            ),
        },
        "assembly_contract": (
            "Runtime architecture is assembled only from typed KG facts. Domain references without ROUTES_DOMAIN_TO_DEPLOY or DEPLOYS_VIA_CONFIG remain evidence leads, not proven routes."
        ),
    }
    if include_legacy_sections:
        packet.update(
            {
                "runtime_building_blocks": runtime_building_blocks,
                "domain_routing_map": domain_routing_map,
                "deploy_runtime_map": deploy_runtime_map,
                "endpoint_consumer_map": endpoint_consumer_map,
                "deploy_order_guidance": deploy_order_guidance,
                "deploy_kind_counts": deploy_kind_counts,
                "domain_routes": domain_routes[:limit],
                "deploy_links": deploy_links[:limit],
                "unlinked_deploy_leads": unlinked_deploy_leads[:limit],
                "backend_services": endpoint_rows[:limit],
                "clients": client_rows[:limit],
                "events_and_workers": event_rows[:limit],
                "domain_references": domain_references[:limit],
                "missing_or_unlinked": _missing_or_unlinked(domain_routes, deploy_links, domain_references, limit=limit),
                "truncated": any(
                    len(rows) > limit
                    for rows in (
                        domain_routes,
                        deploy_links,
                        unlinked_deploy_leads,
                        endpoint_rows,
                        client_rows,
                        event_rows,
                        domain_references,
                    )
                ),
            }
        )
    return packet


def _runtime_building_blocks(
    kg: KgSnapshot,
    *,
    repo_key: str | None,
    domain_routes: list[JsonObject],
    deploy_links: list[JsonObject],
    endpoint_rows: list[JsonObject],
    client_rows: list[JsonObject],
    event_rows: list[JsonObject],
    domain_references: list[JsonObject],
    component_limit: int,
    detail_limit: int,
) -> list[JsonObject]:
    service_ids_by_repo = _service_ids_by_repo(kg)
    deploy_target_to_service_rows = _deploy_target_to_service_rows(deploy_links)
    components: dict[str, JsonObject] = {}

    def component_for_entity(entity: JsonObject, *, fallback_name: str | None = None) -> JsonObject:
        service = _component_service_entity(kg, entity, service_ids_by_repo)
        if service is not None:
            return component_for_service(service)
        repo = _entity_repo(entity)
        component_id = f"repo:{repo or fallback_name or display_entity(entity)}"
        return components.setdefault(
            component_id,
            _empty_component(
                component_id=component_id,
                name=fallback_name or display_entity(entity),
                repo=repo,
                service=None,
            ),
        )

    def component_for_service(service: JsonObject) -> JsonObject:
        service_id = str(service.get("entity_id") or display_entity(service))
        component_id = f"service:{service_id}"
        return components.setdefault(
            component_id,
            _empty_component(
                component_id=component_id,
                name=display_entity(service),
                repo=_entity_repo(service),
                service=_entity_row(service),
            ),
        )

    for row in deploy_links:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        if not subject:
            continue
        component = component_for_entity(subject)
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        _component_add(component, "deployable")
        deploy_kind = _deploy_kind_for_route_or_target(row)
        if deploy_kind:
            component.setdefault("_deploy_kinds", set()).add(deploy_kind)
        component["deploy_targets"].append(
            {
                "deploy_kind": deploy_kind,
                "target": _compact_entity(target),
                "qualifier": _compact_qualifier(row.get("qualifier")),
                "evidence_coordinates": _evidence_coordinates(row),
            }
        )

    for row in domain_routes:
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        service_rows = deploy_target_to_service_rows.get(str(target.get("entity_id") or ""), [])
        if service_rows:
            for service_row in service_rows:
                service_id = service_row.get("subject", {}).get("entity_id")
                service = kg.entities_by_id.get(service_id) if isinstance(service_id, str) else None
                component = component_for_service(service) if service else component_for_entity(target)
                _component_add(component, "domain_routed")
                component["domains"].append(_domain_route_component_row(row))
        else:
            component = component_for_entity(target)
            _component_add(component, "domain_routed")
            component["domains"].append(_domain_route_component_row(row))

    for row in endpoint_rows:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        if not subject:
            continue
        component = component_for_entity(subject)
        _component_add(component, "documented_api" if row.get("predicate") == "DOCUMENTS_ENDPOINT" else "http_api")
        component["endpoints"].append(_compact_fact_row(row))

    for row in client_rows:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        if not subject:
            continue
        component = component_for_entity(subject)
        _component_add(component, "api_client")
        component["client_endpoint_calls"].append(_compact_fact_row(row))

    for row in event_rows:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        if not subject:
            continue
        component = component_for_entity(subject)
        predicate = row.get("predicate")
        if predicate == "CONSUMES_EVENT":
            _component_add(component, "event_consumer")
        elif predicate == "PRODUCES_EVENT":
            _component_add(component, "event_producer")
        else:
            _component_add(component, "event_reference")
        component["events"].append(_compact_fact_row(row))

    routed_domain_ids = _routed_domain_ids(domain_routes)
    for row in _unlinked_domain_reference_rows(domain_references, routed_domain_ids=routed_domain_ids):
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        if not subject:
            continue
        component = component_for_entity(subject)
        _component_add(component, _domain_reference_category(row))
        component["domain_reference_leads"].append(_domain_reference_component_row(row))

    finalized = [_finalize_component(component, limit=detail_limit) for component in components.values()]
    scoped = [
        component
        for component in finalized
        if repo_key is None or _normalize_repo(component.get("repo")) == repo_key
    ]
    return sorted(scoped, key=_component_sort_key)[:component_limit]


def _domain_routing_map(
    kg: KgSnapshot,
    *,
    domain_routes: list[JsonObject],
    deploy_links: list[JsonObject],
    domain_references: list[JsonObject],
    limit: int,
) -> list[JsonObject]:
    deploy_target_to_service_rows = _deploy_target_to_service_rows(deploy_links)
    routed_domain_ids = _routed_domain_ids(domain_routes)
    routes: list[JsonObject] = []
    for row in domain_routes:
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        service_rows = deploy_target_to_service_rows.get(str(target.get("entity_id") or ""), [])
        route = {
            "status": "known_route",
            "domain": _compact_entity(row.get("subject")),
            "target": _compact_entity(target),
            "deploy_kind": _deploy_kind_for_route_or_target(row),
            "route_source_kind": _qualifier_value(row, "source_kind"),
            "qualifier": _compact_qualifier(row.get("qualifier")),
            "evidence_coordinates": _evidence_coordinates(row),
        }
        if service_rows:
            route["services"] = [
                _compact_entity(service_row.get("subject"))
                for service_row in service_rows
                if isinstance(service_row.get("subject"), dict)
            ]
        routes.append(route)
    for row in _unlinked_domain_reference_rows(domain_references, routed_domain_ids=routed_domain_ids):
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        domain = row.get("object") if isinstance(row.get("object"), dict) else {}
        deploy_kind = _domain_reference_deploy_kind(row)
        routes.append(
            {
                "status": "unlinked_domain_reference",
                "domain": _compact_entity(domain),
                "source": _compact_entity(subject),
                "deploy_kind": deploy_kind,
                "route_source_kind": _qualifier_value(row, "source_kind"),
                "qualifier": _compact_qualifier(row.get("qualifier")),
                "evidence_coordinates": _evidence_coordinates(row),
                "interpretation": (
                    "Source-level runtime/domain evidence only. The current KG has no typed route or deploy-link fact for this domain."
                ),
            }
        )
    return sorted(_dedupe_route_rows(routes), key=_route_sort_key)[:limit]


def _deploy_runtime_map(
    *,
    deploy_links: list[JsonObject],
    domain_routes: list[JsonObject],
    limit: int,
) -> list[JsonObject]:
    routes_by_target: dict[str, list[JsonObject]] = {}
    for route in domain_routes:
        target = route.get("object") if isinstance(route.get("object"), dict) else {}
        target_id = target.get("entity_id")
        if isinstance(target_id, str):
            routes_by_target.setdefault(target_id, []).append(route)

    units = []
    for row in deploy_links:
        service = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        target_id = target.get("entity_id")
        if not isinstance(target_id, str):
            continue
        qualifier = _compact_qualifier(row.get("qualifier"))
        routes = routes_by_target.get(target_id, [])
        units.append(
            {
                "status": "known_linked_deploy_unit",
                "service": _compact_entity(service),
                "deploy_target": _compact_entity(target),
                "deploy_kind": _deploy_kind_for_route_or_target(row),
                "deploy_details": _deploy_details(qualifier),
                "ingress_or_domain_routes": [
                    _deploy_runtime_route(route)
                    for route in sorted(routes, key=_route_sort_key)
                ][:limit],
                "evidence_coordinates": _evidence_coordinates(row),
            }
        )
    return sorted(_dedupe_deploy_runtime_units(units), key=_deploy_runtime_sort_key)[:limit]


def _endpoint_consumer_map(
    *,
    endpoint_rows: list[JsonObject],
    client_rows: list[JsonObject],
    limit: int,
) -> tuple[list[JsonObject], int]:
    rows = []
    missing_method_drop_keys: set[tuple[object, object, object]] = set()
    clients_by_path: dict[str, list[tuple[tuple[str | None, str | None], JsonObject]]] = {}
    for client_row in client_rows:
        client_key = _endpoint_key_from_row(client_row)
        if client_key is None or client_key[1] is None:
            continue
        clients_by_path.setdefault(client_key[1], []).append((client_key, client_row))
    for provider_row in endpoint_rows:
        provider_endpoint = provider_row.get("object") if isinstance(provider_row.get("object"), dict) else {}
        endpoint_key = _endpoint_key_from_row(provider_row)
        if endpoint_key is None or endpoint_key[1] is None:
            continue
        provider_method, provider_path = endpoint_key
        consumers = []
        provider = provider_row.get("subject") if isinstance(provider_row.get("subject"), dict) else {}
        provider_id = provider.get("entity_id")
        provider_repo = _entity_repo(provider)
        for client_key, client_row in clients_by_path.get(provider_path, []):
            consumer = client_row.get("subject") if isinstance(client_row.get("subject"), dict) else {}
            if provider_id is not None and consumer.get("entity_id") == provider_id:
                continue
            if _same_repo_internal_endpoint_call(provider_repo=provider_repo, consumer=consumer):
                continue
            consumer_method, _ = client_key
            if provider_method is None or consumer_method is None:
                client_endpoint = client_row.get("object") if isinstance(client_row.get("object"), dict) else {}
                missing_method_drop_keys.add(
                    (
                        client_row.get("fact_id"),
                        consumer.get("entity_id"),
                        client_endpoint.get("entity_id") or provider_path,
                    )
                )
                continue
            if not _endpoint_keys_are_compatible(client_key, endpoint_key):
                continue
            consumers.append(
                {
                    "consumer": _compact_entity(consumer),
                    "called_endpoint": _compact_entity(client_row.get("object")),
                    "qualifier": _compact_qualifier(client_row.get("qualifier")),
                    "match_basis": "literal_normalized_endpoint_path_and_compatible_method",
                    "evidence_coordinates": _evidence_coordinates(client_row),
                }
            )
        if not consumers:
            continue
        rows.append(
            {
                "provider": _compact_entity(provider),
                "provider_endpoint": _compact_entity(provider_endpoint),
                "consumers": sorted(consumers, key=_consumer_sort_key)[:limit],
                "consumer_count": len(consumers),
                "match_basis": "literal_normalized_endpoint_path_and_compatible_method",
                "evidence_coordinates": _evidence_coordinates(provider_row),
            }
        )
    return sorted(_dedupe_endpoint_consumer_map(rows), key=_endpoint_consumer_sort_key)[:limit], len(missing_method_drop_keys)


def _same_repo_internal_endpoint_call(*, provider_repo: str | None, consumer: JsonObject) -> bool:
    if provider_repo is None or consumer.get("kind") not in {"CodeModule", "CodeSymbol"}:
        return False
    return _entity_repo(consumer) == provider_repo


def _runtime_deploy_order_guidance(endpoint_consumer_map: list[JsonObject], *, limit: int) -> list[JsonObject]:
    guidance = []
    for row in endpoint_consumer_map:
        provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
        endpoint = row.get("provider_endpoint") if isinstance(row.get("provider_endpoint"), dict) else {}
        consumers = row.get("consumers")
        if not isinstance(consumers, list):
            continue
        for consumer_row in consumers:
            if not isinstance(consumer_row, dict):
                continue
            consumer = consumer_row.get("consumer") if isinstance(consumer_row.get("consumer"), dict) else {}
            guidance.append(
                {
                    "status": "practical_inference",
                    "provider": provider,
                    "endpoint": endpoint,
                    "consumer": consumer,
                    "recommendation": (
                        "If this provider endpoint changes incompatibly, make the consumer compatible before or alongside the provider deploy."
                    ),
                    "basis": "static CALLS_ENDPOINT consumer matched to provider endpoint; not a canonical deploy-blocker fact",
                    "missing_fact_families": [
                        "canonical_service_deploy_blocker",
                        "runtime_host_resolution",
                        "endpoint_contract_change_classification",
                    ],
                    "evidence_coordinates": consumer_row.get("evidence_coordinates", []),
                }
            )
    return sorted(_dedupe_guidance_rows(guidance), key=_guidance_sort_key)[:limit]


def _runtime_missing_fact_families(
    *,
    deploy_order_guidance: list[JsonObject],
    endpoint_consumer_map: list[JsonObject],
) -> list[str]:
    missing: list[str] = []
    if deploy_order_guidance:
        missing.append("canonical_service_deploy_blocker")
    if endpoint_consumer_map:
        missing.extend(["endpoint_contract_change_classification", "runtime_host_resolution"])
    return sorted(set(missing))


def _runtime_investigation_brief(
    *,
    runtime_building_blocks: list[JsonObject],
    domain_routing_map: list[JsonObject],
    deploy_runtime_map: list[JsonObject],
    unlinked_deploy_leads: list[JsonObject],
    endpoint_consumer_map: list[JsonObject],
    missing_fact_families: list[str],
    limit: int,
) -> JsonObject:
    component_anchors = [
        _runtime_component_headstart(component)
        for component in runtime_building_blocks[:limit]
        if isinstance(component, dict)
    ]
    known_routes = _select_diverse_headstart_rows(sorted([
        _runtime_route_headstart(route)
        for route in domain_routing_map
        if isinstance(route, dict) and route.get("status") == "known_route"
    ], key=_route_headstart_sort_key), limit=limit, key_fn=_route_headstart_diversity_key)
    unlinked_leads = _select_diverse_runtime_leads(sorted([
        _runtime_route_headstart(route)
        for route in domain_routing_map
        if isinstance(route, dict) and route.get("status") == "unlinked_domain_reference"
    ], key=_route_headstart_sort_key), limit=limit)
    deploy_units = _select_diverse_headstart_rows(sorted([
        _runtime_deploy_unit_headstart(unit)
        for unit in deploy_runtime_map
        if isinstance(unit, dict)
    ], key=_deploy_unit_headstart_sort_key), limit=limit, key_fn=_deploy_unit_headstart_diversity_key)
    deploy_leads = _select_diverse_headstart_rows(sorted([
        _runtime_deploy_lead_headstart(lead)
        for lead in unlinked_deploy_leads
        if isinstance(lead, dict)
    ], key=_deploy_lead_sort_key), limit=limit, key_fn=_deploy_lead_diversity_key)
    consumer_links = _select_diverse_headstart_rows(sorted([
        _runtime_consumer_headstart(row)
        for row in endpoint_consumer_map
        if isinstance(row, dict)
    ], key=_consumer_headstart_diversity_key), limit=limit, key_fn=_consumer_headstart_diversity_key)
    source_checks = _runtime_recommended_source_checks(
        component_anchors=component_anchors,
        known_routes=known_routes,
        unlinked_leads=unlinked_leads,
        deploy_units=deploy_units,
        deploy_leads=deploy_leads,
        consumer_links=consumer_links,
        limit=max(limit, RUNTIME_INVESTIGATION_SOURCE_CHECK_LIMIT),
    )
    repos_referenced = _runtime_repos_referenced(
        [*component_anchors, *known_routes, *unlinked_leads, *deploy_units, *deploy_leads, *consumer_links, *source_checks]
    )
    return {
        "purpose": "head_start_for_agent_source_investigation",
        "usage": (
            "Use these anchors to inspect current source files first. Treat known routes and deploy units as typed KG evidence; "
            "treat unlinked leads and missing_fact_families as prompts for source verification, not final conclusions."
        ),
        "repos_referenced": repos_referenced,
        "kg_only_inspection_contract": _kg_only_inspection_contract(),
        "runtime_anchors": component_anchors,
        "known_routes": known_routes,
        "unlinked_runtime_leads": unlinked_leads,
        "deploy_units": deploy_units,
        "unlinked_deploy_leads": deploy_leads,
        "consumer_links": consumer_links,
        "recommended_source_checks": source_checks,
        "missing_fact_families": missing_fact_families,
    }


def _select_diverse_headstart_rows(
    rows: list[JsonObject],
    *,
    limit: int,
    key_fn: Callable[[JsonObject], tuple[object, ...]],
) -> list[JsonObject]:
    selected: list[JsonObject] = []
    selected_ids: set[int] = set()
    seen = set()
    for row in rows:
        key = key_fn(row)
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
        selected_ids.add(id(row))
        if len(selected) >= limit:
            return selected
    return selected


def _select_diverse_runtime_leads(rows: list[JsonObject], *, limit: int) -> list[JsonObject]:
    selected: list[JsonObject] = []
    seen_keys = set()
    per_kind_counts: dict[object, int] = {}
    for row in rows:
        kind = row.get("deploy_kind")
        if per_kind_counts.get(kind, 0) >= RUNTIME_LEADS_PER_KIND_CAP:
            continue
        key = _route_headstart_diversity_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        per_kind_counts[kind] = per_kind_counts.get(kind, 0) + 1
        selected.append(row)
        if len(selected) >= limit:
            return selected
    for row in rows:
        key = _route_headstart_diversity_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def _route_headstart_diversity_key(row: JsonObject) -> tuple[object, ...]:
    service_names = tuple(
        service.get("name") or service.get("slug")
        for service in _dict_list(row.get("services"))
        if service.get("name") or service.get("slug")
    )
    domain = row.get("domain") if isinstance(row.get("domain"), dict) else {}
    target = row.get("target") if isinstance(row.get("target"), dict) else {}
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    return (
        row.get("status"),
        row.get("deploy_kind"),
        service_names,
        _domain_suffix(domain.get("name")) if service_names else domain.get("name"),
        target.get("repo") if service_names else None,
    )


def _route_headstart_sort_key(row: JsonObject) -> tuple[int, int, int, str, str]:
    domain = row.get("domain") if isinstance(row.get("domain"), dict) else {}
    services = _dict_list(row.get("services"))
    return (
        0 if services else 1,
        _domain_environment_rank(domain.get("name")),
        _evidence_environment_rank(row.get("evidence_coordinates")),
        _route_kind_rank(row.get("deploy_kind")),
        str(_domain_suffix(domain.get("name")) or ""),
        str(domain.get("name") or ""),
    )


def _deploy_unit_headstart_diversity_key(row: JsonObject) -> tuple[object, ...]:
    service = row.get("service") if isinstance(row.get("service"), dict) else {}
    target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
    return (
        row.get("deploy_kind"),
        service.get("name") or service.get("slug"),
        service.get("repo"),
        target.get("repo"),
    )


def _deploy_unit_headstart_sort_key(row: JsonObject) -> tuple[int, str, str, str]:
    service = row.get("service") if isinstance(row.get("service"), dict) else {}
    target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
    return (
        _route_kind_rank(row.get("deploy_kind")),
        str(service.get("name") or service.get("slug") or ""),
        str(service.get("repo") or ""),
        str(target.get("name") or target.get("target") or ""),
    )


def _deploy_lead_diversity_key(row: JsonObject) -> tuple[object, ...]:
    service = row.get("service") if isinstance(row.get("service"), dict) else {}
    target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
    candidate_services = tuple(
        candidate_service.get("entity_id")
        or candidate_service.get("name")
        or candidate_service.get("slug")
        for candidate_service in _dict_list(row.get("candidate_services"))
    )
    return (
        row.get("status"),
        row.get("reason"),
        row.get("deploy_kind"),
        service.get("entity_id") or service.get("name") or service.get("slug"),
        candidate_services,
        target.get("entity_id") or target.get("target"),
    )


def _deploy_lead_sort_key(row: JsonObject) -> tuple[int, str, str, str]:
    service = row.get("service") if isinstance(row.get("service"), dict) else {}
    target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
    return (
        0 if row.get("status") == "candidate_deploy_link" else 1,
        str(row.get("reason") or ""),
        str(service.get("name") or service.get("slug") or ""),
        str(target.get("target") or target.get("name") or ""),
    )


def _consumer_headstart_diversity_key(row: JsonObject) -> tuple[str, str]:
    provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
    endpoint = row.get("provider_endpoint") if isinstance(row.get("provider_endpoint"), dict) else {}
    return (
        str(provider.get("name") or provider.get("repo") or ""),
        str(endpoint.get("path") or endpoint.get("name") or ""),
    )


def _domain_environment_rank(value: object) -> int:
    if not isinstance(value, str):
        return 4
    first_label = value.lower().split(".", 1)[0]
    parts = [part for part in first_label.replace("_", "-").split("-") if part]
    if any(part in {"prod", "production"} for part in parts):
        return 0
    if any(part in {"staging", "stage", "qa"} for part in parts):
        return 2
    if any(part in {"dev", "test", "sandbox", "local"} for part in parts):
        return 3
    return 1


def _evidence_environment_rank(value: object) -> int:
    ranks = [
        _path_environment_rank(coordinate.get("path"))
        for coordinate in _dict_list(value)
        if isinstance(coordinate.get("path"), str)
    ]
    if not ranks:
        return 4
    return min(ranks)


def _path_environment_rank(value: object) -> int:
    if not isinstance(value, str):
        return 4
    normalized = value.lower().replace("_", "-")
    parts = [part for part in normalized.replace(".", "/").split("/") if part]
    if any(part in {"prod", "production"} or part.endswith("-prod") for part in parts):
        return 0
    if any(part in {"staging", "stage", "qa"} or part.endswith("-staging") for part in parts):
        return 2
    if any(part in {"dev", "test", "sandbox", "local"} or part.endswith("-dev") for part in parts):
        return 3
    return 1


def _domain_suffix(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parts = [part for part in value.lower().split(".") if part]
    if len(parts) < 2:
        return value.lower()
    return ".".join(parts[-2:])


def _runtime_component_headstart(component: JsonObject) -> JsonObject:
    summary = component.get("summary") if isinstance(component.get("summary"), dict) else {}
    row = {
        "anchor_kind": "runtime_component",
        "name": component.get("name"),
        "repo": component.get("repo"),
        "service": _brief_entity(component.get("service")),
        "runtime_categories": _string_list(component.get("runtime_categories")),
        "deploy_kinds": _string_list(component.get("deploy_kinds")),
        "counts": {
            key: summary.get(key)
            for key in (
                "domain_count",
                "deploy_target_count",
                "endpoint_count",
                "client_endpoint_call_count",
                "event_count",
                "domain_reference_lead_count",
            )
            if key in summary
        },
        "known_domains": [
            _runtime_domain_headstart(domain)
            for domain in _dict_list(component.get("domains"))[:2]
        ],
        "unlinked_domain_leads": [
            _runtime_domain_headstart(lead)
            for lead in _dict_list(component.get("domain_reference_leads"))[:2]
        ],
        "deploy_targets": [
            _runtime_deploy_target_headstart(target)
            for target in _dict_list(component.get("deploy_targets"))[:2]
        ],
        "source_coordinates": _dedupe_coordinates(_coordinates_from_rows(_component_detail_rows(component)))[:3],
    }
    return {key: value for key, value in row.items() if value not in (None, {}, [])}


def _runtime_route_headstart(route: JsonObject) -> JsonObject:
    row = {
        "status": route.get("status"),
        "anchor_kind": "domain_route",
        "domain": _brief_entity(route.get("domain")),
        "deploy_kind": route.get("deploy_kind"),
        "target": _brief_entity(route.get("target")),
        "source": _brief_entity(route.get("source")),
        "services": [_brief_entity(service) for service in _dict_list(route.get("services"))],
        "route_source_kind": route.get("route_source_kind"),
        "evidence_coordinates": _dedupe_coordinates(_dict_list(route.get("evidence_coordinates")))[:2],
        "interpretation": route.get("interpretation"),
    }
    return {key: value for key, value in row.items() if value not in (None, {}, [])}


def _runtime_deploy_unit_headstart(unit: JsonObject) -> JsonObject:
    row = {
        "status": unit.get("status"),
        "anchor_kind": "deploy_unit",
        "service": _brief_entity(unit.get("service")),
        "deploy_target": _brief_entity(unit.get("deploy_target")),
        "deploy_kind": unit.get("deploy_kind"),
        "deploy_details": unit.get("deploy_details") if isinstance(unit.get("deploy_details"), dict) else {},
        "domains": [
            _brief_entity(route.get("domain"))
            for route in _dict_list(unit.get("ingress_or_domain_routes"))[:3]
        ],
        "evidence_coordinates": _dedupe_coordinates(_dict_list(unit.get("evidence_coordinates")))[:2],
    }
    return {key: value for key, value in row.items() if value not in (None, {}, [])}


def _runtime_deploy_lead_headstart(lead: JsonObject) -> JsonObject:
    row = {
        "status": lead.get("status"),
        "anchor_kind": "deploy_lead",
        "reason": lead.get("reason"),
        "service": _brief_entity(lead.get("service")),
        "candidate_services": [
            _brief_entity(service)
            for service in _dict_list(lead.get("candidate_services"))
        ],
        "deploy_target": _brief_entity(lead.get("deploy_target")),
        "deploy_kind": lead.get("deploy_kind"),
        "match_basis": lead.get("match_basis"),
        "evidence_coordinates": _dedupe_coordinates(_dict_list(lead.get("evidence_coordinates")))[:2],
        "interpretation": lead.get("interpretation"),
    }
    return {key: value for key, value in row.items() if value not in (None, {}, [])}


def _runtime_consumer_headstart(row: JsonObject) -> JsonObject:
    consumers = [
        _brief_entity(consumer.get("consumer"))
        for consumer in _dict_list(row.get("consumers"))[:3]
    ]
    result = {
        "anchor_kind": "endpoint_consumer_link",
        "provider": _brief_entity(row.get("provider")),
        "provider_endpoint": _brief_entity(row.get("provider_endpoint")),
        "consumers": consumers,
        "consumer_count": row.get("consumer_count"),
        "match_basis": row.get("match_basis"),
        "evidence_coordinates": _dedupe_coordinates(_dict_list(row.get("evidence_coordinates")))[:2],
    }
    return {key: value for key, value in result.items() if value not in (None, {}, [])}


def _runtime_domain_headstart(row: JsonObject) -> JsonObject:
    result = {
        "domain": _brief_entity(row.get("domain")),
        "target": _brief_entity(row.get("target")),
        "deploy_kind": row.get("deploy_kind"),
        "evidence_coordinates": _dedupe_coordinates(_dict_list(row.get("evidence_coordinates")))[:1],
        "interpretation": row.get("interpretation"),
    }
    return {key: value for key, value in result.items() if value not in (None, {}, [])}


def _runtime_deploy_target_headstart(row: JsonObject) -> JsonObject:
    result = {
        "deploy_kind": row.get("deploy_kind"),
        "target": _brief_entity(row.get("target")),
        "evidence_coordinates": _dedupe_coordinates(_dict_list(row.get("evidence_coordinates")))[:1],
    }
    return {key: value for key, value in result.items() if value not in (None, {}, [])}


def _runtime_recommended_source_checks(
    *,
    component_anchors: list[JsonObject],
    known_routes: list[JsonObject],
    unlinked_leads: list[JsonObject],
    deploy_units: list[JsonObject],
    deploy_leads: list[JsonObject],
    consumer_links: list[JsonObject],
    limit: int,
) -> list[JsonObject]:
    buckets = [
        [
            check
            for route in known_routes
            for check in _source_checks_from_row(route, reason="verify known domain route and backend mapping")
        ],
        [
            check
            for lead in unlinked_leads
            for check in _source_checks_from_row(lead, reason="verify unlinked runtime/domain lead before claiming routing")
        ],
        [
            check
            for unit in deploy_units
            for check in _source_checks_from_row(unit, reason="verify deploy unit and runtime target")
        ],
        [
            check
            for lead in deploy_leads
            for check in _source_checks_from_row(
                lead,
                reason="verify candidate or unresolved deploy lead before claiming service deployment",
            )
        ],
        [
            check
            for link in consumer_links
            for check in _source_checks_from_row(link, reason="verify static endpoint consumer evidence")
        ],
        [
            check
            for component in component_anchors
            for check in _source_checks_from_row(component, reason="inspect runtime component evidence")
        ],
    ]
    checks: list[JsonObject] = []
    for index in range(max((len(bucket) for bucket in buckets), default=0)):
        for bucket in buckets:
            if index < len(bucket):
                checks.append(bucket[index])
    return _dedupe_source_checks(checks)[:limit]


def _runtime_repos_referenced(rows: list[JsonObject]) -> list[JsonObject]:
    repo_commits: dict[str, set[str]] = {}

    def add_coordinate(value: JsonObject) -> None:
        repo = value.get("repo")
        path = value.get("path")
        line_start = value.get("line_start")
        if (
            not isinstance(repo, str)
            or not repo.strip()
            or not isinstance(path, str)
            or not path.strip()
            or isinstance(line_start, bool)
            or not isinstance(line_start, int)
        ):
            return
        commits = repo_commits.setdefault(repo.strip(), set())
        commit_sha = value.get("commit_sha")
        if isinstance(commit_sha, str) and commit_sha.strip():
            commits.add(commit_sha.strip())

    def visit(value: object) -> None:
        if isinstance(value, dict):
            add_coordinate(value)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for row in rows:
        visit(row)
    return [
        {"repo": repo, "commit_shas": sorted(commits)}
        for repo, commits in sorted(repo_commits.items())
    ]


def _kg_only_inspection_contract() -> JsonObject:
    return {
        "status": "source_availability_unresolved_by_supercontext",
        "host_agent_action": (
            "Compare repos_referenced with the local workspace or remote source access. "
            "When a repo is unavailable locally, treat returned coordinates as KG-only inspection leads."
        ),
        "coordinate_fields": ["repo", "commit_sha", "path", "line_start", "line_end"],
        "boundary": (
            "SuperContext reports KG evidence coordinates and does not infer whether a host agent can read the referenced repo."
        ),
    }


def _source_checks_from_row(row: JsonObject, *, reason: str) -> list[JsonObject]:
    checks = []
    anchor = _source_check_anchor(row)
    for coordinate in _dict_list(row.get("evidence_coordinates")) + _dict_list(row.get("source_coordinates")):
        check = {
            "reason": reason,
            "anchor": anchor,
            "repo": coordinate.get("repo"),
            "commit_sha": coordinate.get("commit_sha"),
            "path": coordinate.get("path"),
            "line_start": coordinate.get("line_start"),
            "line_end": coordinate.get("line_end"),
            "confidence": coordinate.get("confidence"),
            "source_system": coordinate.get("source_system"),
        }
        checks.append({key: value for key, value in check.items() if value is not None})
    return checks


def _source_check_anchor(row: JsonObject) -> str | None:
    for key in ("domain", "service", "provider", "name", "deploy_target"):
        value = row.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("slug") or value.get("target")
            if isinstance(name, str) and name:
                return name
        if isinstance(value, str) and value:
            return value
    return None


def _dedupe_source_checks(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        key = (
            row.get("repo"),
            row.get("commit_sha"),
            row.get("path"),
            row.get("line_start"),
            row.get("anchor"),
            row.get("reason"),
        )
        if key in seen or row.get("path") is None:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _component_detail_rows(component: JsonObject) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for key in ("domains", "deploy_targets", "endpoints", "client_endpoint_calls", "events", "domain_reference_leads"):
        rows.extend(_dict_list(component.get(key)))
    return rows


def _coordinates_from_rows(rows: list[JsonObject]) -> list[JsonObject]:
    coordinates: list[JsonObject] = []
    for row in rows:
        coordinates.extend(_dict_list(row.get("evidence_coordinates")))
    return coordinates


def _dedupe_coordinates(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        key = (
            row.get("repo"),
            row.get("commit_sha"),
            row.get("path"),
            row.get("line_start"),
            row.get("line_end"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _brief_entity(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    if not value:
        return {}
    identity = value.get("identity")
    properties = value.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    result = {
        "kind": value.get("kind"),
        "name": value.get("name") or display_entity(value),
        "repo": value.get("repo") or identity.get("repo") or properties.get("repo"),
        "slug": value.get("slug") or identity.get("slug"),
        "type": value.get("type") or identity.get("type"),
        "target": value.get("target") or identity.get("target"),
        "path": value.get("path") or identity.get("path") or properties.get("path"),
    }
    return {key: item for key, item in result.items() if item is not None}


def _dict_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _deploy_runtime_route(row: JsonObject) -> JsonObject:
    qualifier = _compact_qualifier(row.get("qualifier"))
    return {
        "domain": _compact_entity(row.get("subject")),
        "deploy_target": _compact_entity(row.get("object")),
        "deploy_kind": _deploy_kind_for_route_or_target(row),
        "route_source_kind": qualifier.get("source_kind"),
        "backend_service": qualifier.get("backend_service"),
        "backend_service_ports": qualifier.get("backend_service_ports", []),
        "ingress_path": qualifier.get("ingress_path"),
        "namespace": qualifier.get("namespace"),
        "workload": qualifier.get("workload"),
        "match_basis": qualifier.get("match_basis"),
        "qualifier": qualifier,
        "evidence_coordinates": _evidence_coordinates(row),
    }


def _deploy_details(qualifier: JsonObject) -> JsonObject:
    keys = (
        "source_kind",
        "target_type",
        "kubernetes_kind",
        "namespace",
        "workload",
        "containers",
        "images",
        "ownership_basis",
        "path",
    )
    return {key: qualifier[key] for key in keys if key in qualifier}


def _fact_row(kg: KgSnapshot, fact: JsonObject, subject: JsonObject, object_: JsonObject) -> JsonObject:
    return {
        "fact_id": fact.get("fact_id"),
        "predicate": fact.get("predicate"),
        "canonical_status": _canonical_status(fact),
        "subject": _entity_row(subject),
        "object": _entity_row(object_),
        "qualifier": fact.get("qualifier", {}),
        "evidence": kg.evidence_by_target.get(fact.get("fact_id"), []),
    }


def _canonical_status(row: JsonObject) -> str:
    value = row.get("canonical_status", "canonical")
    return value if isinstance(value, str) and value else "canonical"


def _entity_row(entity: JsonObject) -> JsonObject:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return {
        "entity_id": entity.get("entity_id"),
        "kind": entity.get("kind"),
        "name": display_entity(entity),
        "repo": identity.get("repo") or properties.get("repo"),
        "identity": identity,
        "properties": properties,
    }


def _empty_component(*, component_id: str, name: str, repo: str | None, service: JsonObject | None) -> JsonObject:
    return {
        "component_id": component_id,
        "name": name,
        "repo": repo,
        "service": service,
        "_runtime_categories": set(),
        "_deploy_kinds": set(),
        "domains": [],
        "deploy_targets": [],
        "endpoints": [],
        "client_endpoint_calls": [],
        "events": [],
        "domain_reference_leads": [],
    }


def _component_add(component: JsonObject, category: str) -> None:
    component["_runtime_categories"].add(category)


def _finalize_component(component: JsonObject, *, limit: int) -> JsonObject:
    categories = component.pop("_runtime_categories", set())
    deploy_kinds = component.pop("_deploy_kinds", set())
    domains = _dedupe_component_rows(component["domains"])
    deploy_targets = _dedupe_component_rows(component["deploy_targets"])
    endpoints = _dedupe_component_rows(component["endpoints"])
    client_endpoint_calls = _dedupe_component_rows(component["client_endpoint_calls"])
    events = _dedupe_component_rows(component["events"])
    domain_reference_leads = _dedupe_component_rows(component["domain_reference_leads"])
    summary = {
        "domain_count": len(domains),
        "deploy_target_count": len(deploy_targets),
        "endpoint_count": len(endpoints),
        "client_endpoint_call_count": len(client_endpoint_calls),
        "event_count": len(events),
        "domain_reference_lead_count": len(domain_reference_leads),
    }
    truncated_sections = {key.removesuffix("_count"): value > limit for key, value in summary.items()}
    return {
        **component,
        "runtime_categories": sorted(categories),
        "deploy_kinds": sorted(kind for kind in deploy_kinds if kind),
        "summary": summary,
        "truncated_sections": truncated_sections,
        "domains": domains[:limit],
        "deploy_targets": deploy_targets[:limit],
        "endpoints": endpoints[:limit],
        "client_endpoint_calls": client_endpoint_calls[:limit],
        "events": events[:limit],
        "domain_reference_leads": domain_reference_leads[:limit],
        "truncated": any(truncated_sections.values()),
    }


def _component_sort_key(component: JsonObject) -> tuple[int, str, str]:
    summary = component.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    score = (
        8 * int(summary.get("domain_count") or 0)
        + 6 * int(summary.get("deploy_target_count") or 0)
        + 4 * int(summary.get("endpoint_count") or 0)
        + 3 * int(summary.get("event_count") or 0)
        + 2 * int(summary.get("client_endpoint_call_count") or 0)
        + int(summary.get("domain_reference_lead_count") or 0)
    )
    return (-score, str(component.get("repo") or ""), str(component.get("name") or ""))


def _service_ids_by_repo(kg: KgSnapshot) -> dict[str, list[str]]:
    service_ids: dict[str, list[str]] = {}
    for entity in kg.entities:
        if entity.get("kind") != "Service":
            continue
        repo = _entity_repo(entity)
        entity_id = entity.get("entity_id")
        if repo is None or not isinstance(entity_id, str):
            continue
        service_ids.setdefault(repo, []).append(entity_id)
    return service_ids


def _component_service_entity(
    kg: KgSnapshot,
    entity: JsonObject,
    service_ids_by_repo: dict[str, list[str]],
) -> JsonObject | None:
    if entity.get("kind") == "Service":
        return entity
    repo = _entity_repo(entity)
    if repo is None:
        return None
    service_ids = service_ids_by_repo.get(repo, [])
    if len(service_ids) != 1:
        return None
    return kg.entities_by_id.get(service_ids[0])


def _deploy_target_to_service_rows(deploy_links: list[JsonObject]) -> dict[str, list[JsonObject]]:
    by_target: dict[str, list[JsonObject]] = {}
    for row in deploy_links:
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        target_id = target.get("entity_id")
        if not isinstance(target_id, str):
            continue
        by_target.setdefault(target_id, []).append(row)
    return by_target


def _unlinked_deploy_leads(
    kg: KgSnapshot,
    *,
    deploy_candidate_rows: list[JsonObject],
    repo_key: str | None,
) -> list[JsonObject]:
    rows: list[JsonObject] = []
    candidate_target_ids: set[str] = set()
    for row in deploy_candidate_rows:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        target = row.get("object") if isinstance(row.get("object"), dict) else {}
        target_id = target.get("entity_id")
        if isinstance(target_id, str):
            candidate_target_ids.add(target_id)
        qualifier = _compact_qualifier(row.get("qualifier"))
        rows.append(
            {
                "status": "candidate_deploy_link",
                "reason": qualifier.get("resolved_by") or "candidate_deploy_link",
                "service": _compact_entity(subject),
                "candidate_services": _candidate_service_rows(kg, qualifier.get("candidate_service_ids")),
                "deploy_target": _compact_entity(target),
                "deploy_kind": _deploy_kind_for_route_or_target(row),
                "match_basis": qualifier.get("resolved_by"),
                "qualifier": qualifier,
                "evidence_coordinates": _evidence_coordinates(row),
                "interpretation": (
                    "Candidate service-to-deploy link from runtime config. Verify source before treating it as a known deploy link."
                ),
            }
        )

    for coverage in kg.coverage:
        if coverage.get("predicate") != "DEPLOYS_VIA_CONFIG" or coverage.get("source_system") != "runtime_linker":
            continue
        scope_ref = coverage.get("scope_ref") if isinstance(coverage.get("scope_ref"), dict) else {}
        reason = scope_ref.get("reason")
        if reason not in RUNTIME_UNLINKED_DEPLOY_REASONS:
            continue
        target_id = scope_ref.get("deploy_target_id")
        if reason == "ambiguous_wsgi_module_suffix" and isinstance(target_id, str) and target_id in candidate_target_ids:
            continue
        target_identity = scope_ref.get("deploy_target_identity")
        if not isinstance(target_identity, dict):
            continue
        if repo_key is not None and _normalize_repo(target_identity.get("repo")) != repo_key:
            continue
        target = kg.entities_by_id.get(target_id) if isinstance(target_id, str) else None
        target_row = _compact_entity(target) if isinstance(target, dict) else _deploy_target_from_identity(target_id, target_identity)
        rows.append(
            {
                "status": "unresolved_deploy_link",
                "reason": reason,
                "candidate_services": _candidate_service_rows(kg, scope_ref.get("candidate_service_ids")),
                "deploy_target": target_row,
                "deploy_kind": _deploy_kind_from_target_identity(target_identity),
                "match_basis": reason,
                "qualifier": {
                    "source_kind": "runtime_linker",
                    "reason": reason,
                    "rule_version": scope_ref.get("rule_version"),
                },
                "evidence_coordinates": _entity_evidence_coordinates(kg, target_id),
                "interpretation": (
                    "Runtime linker could not emit a known deploy link for this target. Use the target identity and any coordinates as an inspection lead."
                ),
            }
        )
    return sorted(_dedupe_deploy_leads(rows), key=_deploy_lead_sort_key)


def _candidate_service_rows(kg: KgSnapshot, value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, str):
            continue
        entity = kg.entities_by_id.get(item)
        if isinstance(entity, dict) and entity.get("kind") == "Service":
            rows.append(_compact_entity(entity))
    return rows


def _deploy_target_from_identity(target_id: object, identity: JsonObject) -> JsonObject:
    return _compact_entity(
        {
            "entity_id": target_id if isinstance(target_id, str) else None,
            "kind": "DeployTarget",
            "identity": identity,
            "properties": {},
        }
    )


def _entity_evidence_coordinates(kg: KgSnapshot, entity_id: object) -> list[JsonObject]:
    if not isinstance(entity_id, str):
        return []
    return _evidence_coordinates({"evidence": kg.evidence_by_target.get(entity_id, [])})


def _deploy_kind_from_target_identity(identity: JsonObject) -> str | None:
    deploy_type = identity.get("type")
    if not isinstance(deploy_type, str) or not deploy_type:
        return None
    if deploy_type == "wsgi":
        return "apache_wsgi"
    return deploy_type


def _dedupe_deploy_leads(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
        service = row.get("service") if isinstance(row.get("service"), dict) else {}
        candidate_services = tuple(
            candidate_service.get("entity_id")
            or candidate_service.get("name")
            or candidate_service.get("slug")
            for candidate_service in _dict_list(row.get("candidate_services"))
        )
        key = (
            row.get("status"),
            row.get("reason"),
            service.get("entity_id"),
            candidate_services,
            target.get("entity_id") or target.get("target"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _deploy_kind_counts(runtime_building_blocks: list[JsonObject], domain_routing_map: list[JsonObject]) -> JsonObject:
    component_counts: dict[str, int] = {}
    for component in runtime_building_blocks:
        deploy_kinds = component.get("deploy_kinds")
        if isinstance(deploy_kinds, list):
            for kind in deploy_kinds:
                if isinstance(kind, str) and kind:
                    component_counts[kind] = component_counts.get(kind, 0) + 1
    unlinked_route_counts: dict[str, int] = {}
    for route in domain_routing_map:
        deploy_kind = route.get("deploy_kind")
        if isinstance(deploy_kind, str) and deploy_kind and route.get("status") == "unlinked_domain_reference":
            unlinked_route_counts[deploy_kind] = unlinked_route_counts.get(deploy_kind, 0) + 1
    return {
        "component_deploy_kind_counts": dict(
            sorted(component_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "unlinked_route_deploy_kind_counts": dict(
            sorted(unlinked_route_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
    }


def _domain_route_component_row(row: JsonObject) -> JsonObject:
    return {
        "domain": _compact_entity(row.get("subject")),
        "target": _compact_entity(row.get("object")),
        "deploy_kind": _deploy_kind_for_route_or_target(row),
        "qualifier": _compact_qualifier(row.get("qualifier")),
        "evidence_coordinates": _evidence_coordinates(row),
    }


def _domain_reference_component_row(row: JsonObject) -> JsonObject:
    return {
        "domain": _compact_entity(row.get("object")),
        "deploy_kind": _domain_reference_deploy_kind(row),
        "qualifier": _compact_qualifier(row.get("qualifier")),
        "evidence_coordinates": _evidence_coordinates(row),
        "interpretation": "Unlinked source lead; not proof of runtime routing.",
    }


def _compact_fact_row(row: JsonObject) -> JsonObject:
    return {
        "predicate": row.get("predicate"),
        "subject": _compact_entity(row.get("subject")),
        "object": _compact_entity(row.get("object")),
        "qualifier": _compact_qualifier(row.get("qualifier")),
        "evidence_coordinates": _evidence_coordinates(row),
    }


def _compact_entity(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    identity = value.get("identity")
    properties = value.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return {
        "entity_id": value.get("entity_id"),
        "kind": value.get("kind"),
        "name": value.get("name") or display_entity(value),
        "repo": identity.get("repo") or properties.get("repo") or value.get("repo"),
        "slug": identity.get("slug"),
        "type": identity.get("type"),
        "target": identity.get("target"),
        "path": identity.get("path") or properties.get("path"),
    }


def _compact_qualifier(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _evidence_coordinates(row: JsonObject, *, limit: int = 2) -> list[JsonObject]:
    coordinates = []
    evidence_rows = row.get("evidence", [])
    if not isinstance(evidence_rows, list):
        return coordinates
    for evidence in evidence_rows:
        if not isinstance(evidence, dict):
            continue
        bytes_ref = evidence.get("bytes_ref")
        if not isinstance(bytes_ref, dict):
            continue
        coordinate = {
            "repo": bytes_ref.get("repo_name") or bytes_ref.get("repo"),
            "commit_sha": bytes_ref.get("commit_sha"),
            "path": bytes_ref.get("path"),
            "line_start": bytes_ref.get("line_start"),
            "line_end": bytes_ref.get("line_end"),
            "confidence": evidence.get("confidence"),
            "source_system": evidence.get("source_system"),
        }
        coordinates.append({key: value for key, value in coordinate.items() if value is not None})
        if len(coordinates) >= limit:
            break
    return coordinates


def _deploy_kind_for_route_or_target(row: JsonObject) -> str | None:
    qualifier = row.get("qualifier")
    if not isinstance(qualifier, dict):
        qualifier = {}
    target_type = str(qualifier.get("target_type") or "")
    source_kind = str(qualifier.get("source_kind") or "")
    object_ = row.get("object") if isinstance(row.get("object"), dict) else {}
    identity = object_.get("identity") if isinstance(object_.get("identity"), dict) else {}
    deploy_type = str(identity.get("type") or target_type)
    if deploy_type == "wsgi" or source_kind == "apache_vhost":
        return "apache_wsgi"
    if deploy_type == "zappa_lambda" or source_kind in {"zappa_settings", "zappa_domain"}:
        return "zappa_lambda"
    if deploy_type.startswith("kubernetes_") or target_type.startswith("kubernetes_"):
        return deploy_type or target_type
    return deploy_type or target_type or None


def _unlinked_domain_reference_rows(
    domain_references: list[JsonObject],
    *,
    routed_domain_ids: set[str],
) -> list[JsonObject]:
    rows = []
    for row in domain_references:
        domain = row.get("object") if isinstance(row.get("object"), dict) else {}
        domain_id = domain.get("entity_id")
        if isinstance(domain_id, str) and domain_id in routed_domain_ids:
            continue
        if _domain_reference_deploy_kind(row) is not None:
            rows.append(row)
    return rows


def _domain_reference_deploy_kind(row: JsonObject) -> str | None:
    qualifier = row.get("qualifier") if isinstance(row.get("qualifier"), dict) else {}
    source_kind = str(qualifier.get("source_kind") or "").lower()
    if source_kind in {"apache_server_name", "zappa_domain"}:
        return f"{source_kind}_reference"
    if source_kind in {"terraform_literal", "terraform_module_source"}:
        return "terraform_domain_reference"
    if source_kind == "static_site_cname":
        return "static_site_cname_reference"
    if source_kind in {"dotenv_assignment", "domain_env"}:
        return "env_domain_reference"
    if source_kind == "source_domain_literal":
        return None
    if source_kind == "kubernetes_ingress":
        return "kubernetes_ingress_domain_reference"
    domain = row.get("object") if isinstance(row.get("object"), dict) else {}
    identity = domain.get("identity") if isinstance(domain.get("identity"), dict) else {}
    domain_name = str(identity.get("name") or domain.get("name") or "")
    if _is_aws_api_gateway_domain(domain_name):
        return "api_gateway_domain_reference"
    if _is_ip_address(domain_name):
        return "internal_address_reference"
    return None


def _is_aws_api_gateway_domain(value: str) -> bool:
    normalized = value.lower()
    return ".execute-api." in normalized and normalized.endswith(".amazonaws.com")


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _domain_reference_category(row: JsonObject) -> str:
    deploy_kind = _domain_reference_deploy_kind(row)
    if deploy_kind is None:
        return "domain_reference"
    if deploy_kind == "env_domain_reference":
        return "client_runtime_target"
    return "domain_reference"


def _dedupe_route_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        domain = row.get("domain") if isinstance(row.get("domain"), dict) else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        key = (
            row.get("status"),
            domain.get("entity_id") or domain.get("name"),
            target.get("entity_id") or source.get("entity_id"),
            row.get("deploy_kind"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_component_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        key = _component_row_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _component_row_key(row: JsonObject) -> tuple[object, ...]:
    qualifier = row.get("qualifier") if isinstance(row.get("qualifier"), dict) else {}
    evidence = row.get("evidence_coordinates") if isinstance(row.get("evidence_coordinates"), list) else []
    return (
        row.get("predicate"),
        row.get("deploy_kind"),
        _compact_row_entity_key(row.get("domain")),
        _compact_row_entity_key(row.get("target")),
        _compact_row_entity_key(row.get("source")),
        _compact_row_entity_key(row.get("subject")),
        _compact_row_entity_key(row.get("object")),
        tuple(sorted((str(key), str(value)) for key, value in qualifier.items())),
        tuple(
            (
                coordinate.get("repo"),
                coordinate.get("path"),
                coordinate.get("line_start"),
                coordinate.get("line_end"),
            )
            for coordinate in evidence
            if isinstance(coordinate, dict)
        ),
    )


def _compact_row_entity_key(value: object) -> tuple[object, object, object]:
    if not isinstance(value, dict):
        return (None, None, None)
    return (value.get("entity_id"), value.get("kind"), value.get("name"))


def _dedupe_deploy_runtime_units(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        service = row.get("service") if isinstance(row.get("service"), dict) else {}
        target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
        key = (service.get("entity_id"), target.get("entity_id"), row.get("deploy_kind"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_endpoint_consumer_map(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
        endpoint = row.get("provider_endpoint") if isinstance(row.get("provider_endpoint"), dict) else {}
        key = (provider.get("entity_id"), endpoint.get("entity_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_guidance_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    deduped = []
    for row in rows:
        provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
        endpoint = row.get("endpoint") if isinstance(row.get("endpoint"), dict) else {}
        consumer = row.get("consumer") if isinstance(row.get("consumer"), dict) else {}
        key = (provider.get("entity_id"), endpoint.get("entity_id"), consumer.get("entity_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _deploy_runtime_sort_key(row: JsonObject) -> tuple[str, str, str]:
    service = row.get("service") if isinstance(row.get("service"), dict) else {}
    target = row.get("deploy_target") if isinstance(row.get("deploy_target"), dict) else {}
    return (str(service.get("repo") or ""), str(service.get("name") or ""), str(target.get("name") or ""))


def _endpoint_consumer_sort_key(row: JsonObject) -> tuple[str, str]:
    provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
    endpoint = row.get("provider_endpoint") if isinstance(row.get("provider_endpoint"), dict) else {}
    return (str(provider.get("name") or ""), str(endpoint.get("path") or endpoint.get("name") or ""))


def _consumer_sort_key(row: JsonObject) -> tuple[str, str]:
    consumer = row.get("consumer") if isinstance(row.get("consumer"), dict) else {}
    return (str(consumer.get("repo") or ""), str(consumer.get("name") or ""))


def _guidance_sort_key(row: JsonObject) -> tuple[str, str]:
    consumer = row.get("consumer") if isinstance(row.get("consumer"), dict) else {}
    provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
    return (str(provider.get("name") or ""), str(consumer.get("name") or ""))


def _route_sort_key(row: JsonObject) -> tuple[int, str, str]:
    status_rank = 0 if row.get("status") == "known_route" else 1
    domain = row.get("domain") if isinstance(row.get("domain"), dict) else {}
    return (status_rank, _route_kind_rank(row.get("deploy_kind")), str(domain.get("name") or ""))


def _route_kind_rank(value: object) -> int:
    if not isinstance(value, str):
        return 99
    priority = {
        "apache_wsgi": 0,
        "zappa_lambda": 1,
        "cloudfront_distribution": 2,
        "kubernetes_deployment": 3,
        "api_gateway_domain_reference": 4,
        "internal_address_reference": 5,
        "static_site_cname_reference": 6,
        "apache_server_name_reference": 7,
        "zappa_domain_reference": 8,
        "env_domain_reference": 9,
        "kubernetes_ingress_domain_reference": 10,
        "terraform_domain_reference": 11,
    }
    return priority.get(value, 50)


def _qualifier_value(row: JsonObject, key: str) -> object:
    qualifier = row.get("qualifier")
    if not isinstance(qualifier, dict):
        return None
    return qualifier.get(key)


def _routed_domain_ids(domain_routes: list[JsonObject]) -> set[str]:
    return {
        domain_id
        for row in domain_routes
        if isinstance(row.get("subject"), dict)
        for domain_id in [row["subject"].get("entity_id")]
        if isinstance(domain_id, str)
    }


def _missing_or_unlinked(
    domain_routes: list[JsonObject],
    deploy_links: list[JsonObject],
    domain_references: list[JsonObject],
    *,
    limit: int,
) -> JsonObject:
    routed_domain_ids = {
        row.get("subject", {}).get("entity_id")
        for row in domain_routes
        if isinstance(row.get("subject"), dict)
    }
    unlinked = [
        row
        for row in domain_references
        if isinstance(row.get("object"), dict) and row["object"].get("entity_id") not in routed_domain_ids
    ]
    return {
        "domain_references_without_route_count": len(unlinked),
        "service_deploy_link_count": len(deploy_links),
        "domain_reference_samples": unlinked[:limit],
    }


def _fact_touches_repo(subject: JsonObject, object_: JsonObject, fact: JsonObject, repo_key: str) -> bool:
    if _entity_repo(subject) == repo_key or _entity_repo(object_) == repo_key:
        return True
    qualifier = fact.get("qualifier", {})
    # CALLS_ENDPOINT producers attach consumer_repo when client code calls a provider endpoint in another repo.
    return isinstance(qualifier, dict) and _normalize_repo(qualifier.get("consumer_repo")) == repo_key


def _scoped_endpoint_keys(kg: KgSnapshot, repo_key: str | None) -> set[tuple[str | None, str | None]]:
    if repo_key is None:
        return set()
    keys = set()
    for fact in kg.facts:
        if fact.get("predicate") != "EXPOSES_ENDPOINT":
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        endpoint = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not endpoint:
            continue
        if _entity_repo(subject) != repo_key and _entity_repo(endpoint) != repo_key:
            continue
        keys.add(_endpoint_key(endpoint))
    return keys


def _endpoint_key(entity: JsonObject) -> tuple[str | None, str | None]:
    identity = entity.get("identity")
    if not isinstance(identity, dict):
        identity = {}
    method = identity.get("method")
    path = identity.get("path")
    # Method-aware endpoint joins intentionally fail closed when one side lacks
    # a method; otherwise any path-only endpoint could absorb method-specific calls.
    return (str(method).upper() if method is not None else None, str(path) if path is not None else None)


def _endpoint_key_from_row(row: JsonObject) -> tuple[str | None, str | None] | None:
    endpoint = row.get("object")
    if not isinstance(endpoint, dict):
        return None
    key = _endpoint_key(endpoint)
    if key[1] is None:
        return None
    qualifier = row.get("qualifier")
    if key[0] is None and isinstance(qualifier, dict):
        method = qualifier.get("method")
        if isinstance(method, str) and method.strip():
            key = (method.strip().upper(), key[1])
    return key


def _endpoint_keys_are_compatible(
    consumer_key: tuple[str | None, str | None] | None,
    provider_key: tuple[str | None, str | None] | None,
) -> bool:
    if consumer_key is None or provider_key is None:
        return False
    consumer_method, consumer_path = consumer_key
    provider_method, provider_path = provider_key
    if consumer_path != provider_path or consumer_method is None or provider_method is None:
        return False
    return provider_method == "ANY" or consumer_method == provider_method


def _entity_repo(entity: JsonObject) -> str | None:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    return _normalize_repo(identity.get("repo") or properties.get("repo"))


def _normalize_repo(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", "-")
    return text or None


def _dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen = set()
    result = []
    for row in rows:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        object_ = row.get("object") if isinstance(row.get("object"), dict) else {}
        key = row.get("fact_id") or (
            row.get("predicate"),
            subject.get("entity_id"),
            object_.get("entity_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
