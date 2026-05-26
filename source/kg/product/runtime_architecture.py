from __future__ import annotations

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


RUNTIME_DOMAIN_PREDICATES = {"REFERENCES_DOMAIN", "ROUTES_DOMAIN_TO_DEPLOY"}
RUNTIME_ENDPOINT_PREDICATES = {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}
RUNTIME_EVENT_PREDICATES = {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}
RUNTIME_DEPLOY_PREDICATES = {"DEPLOYS_VIA_CONFIG"}


def runtime_architecture_packet(
    kg: KgSnapshot,
    *,
    repo: str | None,
    limit: int,
) -> JsonObject:
    repo_key = _normalize_repo(repo)
    domain_routes: list[JsonObject] = []
    deploy_links: list[JsonObject] = []
    endpoint_rows: list[JsonObject] = []
    client_rows: list[JsonObject] = []
    event_rows: list[JsonObject] = []
    domain_references: list[JsonObject] = []

    scoped_endpoint_keys = _scoped_endpoint_keys(kg, repo_key)

    for fact in kg.facts:
        predicate = str(fact.get("predicate") or "")
        if predicate not in RUNTIME_DOMAIN_PREDICATES | RUNTIME_ENDPOINT_PREDICATES | RUNTIME_EVENT_PREDICATES | RUNTIME_DEPLOY_PREDICATES:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if repo_key is not None and not _fact_touches_repo(subject, object_, fact, repo_key):
            if predicate != "CALLS_ENDPOINT" or _endpoint_key(object_) not in scoped_endpoint_keys:
                continue
        row = _fact_row(kg, fact, subject, object_)
        if predicate == "ROUTES_DOMAIN_TO_DEPLOY":
            domain_routes.append(row)
        elif predicate == "DEPLOYS_VIA_CONFIG":
            deploy_links.append(row)
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
    endpoint_rows = _dedupe_rows(endpoint_rows)
    client_rows = _dedupe_rows(client_rows)
    event_rows = _dedupe_rows(event_rows)
    domain_references = _dedupe_rows(domain_references)

    return {
        "scope": {"kind": "repo", "repo": repo} if repo_key else {"kind": "fleet"},
        "summary": {
            "domain_route_count": len(domain_routes),
            "deploy_link_count": len(deploy_links),
            "endpoint_surface_count": len(endpoint_rows),
            "client_endpoint_call_count": len(client_rows),
            "event_surface_count": len(event_rows),
            "domain_reference_count": len(domain_references),
            "section_limit": limit,
        },
        "domain_routes": domain_routes[:limit],
        "deploy_links": deploy_links[:limit],
        "backend_services": endpoint_rows[:limit],
        "clients": client_rows[:limit],
        "events_and_workers": event_rows[:limit],
        "domain_references": domain_references[:limit],
        "missing_or_unlinked": _missing_or_unlinked(domain_routes, deploy_links, domain_references, limit=limit),
        "truncated": any(
            len(rows) > limit
            for rows in (domain_routes, deploy_links, endpoint_rows, client_rows, event_rows, domain_references)
        ),
        "assembly_contract": (
            "Runtime architecture is assembled only from typed KG facts. Domain references without ROUTES_DOMAIN_TO_DEPLOY or DEPLOYS_VIA_CONFIG remain evidence leads, not proven routes."
        ),
    }


def _fact_row(kg: KgSnapshot, fact: JsonObject, subject: JsonObject, object_: JsonObject) -> JsonObject:
    return {
        "fact_id": fact.get("fact_id"),
        "predicate": fact.get("predicate"),
        "subject": _entity_row(subject),
        "object": _entity_row(object_),
        "qualifier": fact.get("qualifier", {}),
        "evidence": kg.evidence_by_target.get(fact.get("fact_id"), []),
    }


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
