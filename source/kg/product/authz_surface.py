from __future__ import annotations

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


AUTHZ_PREDICATES = {
    "DEFINES_AUTHZ_POLICY",
    "APPLIES_AUTHZ_POLICY",
    "USES_AUTHZ_CHECK",
    "HANDLES_ENDPOINT",
}


def authz_surface_packet(
    kg: KgSnapshot,
    *,
    repo: str | None,
    limit: int,
    allow_fleet: bool = True,
) -> JsonObject:
    repo_key = _normalize_repo(repo)
    repo_scope = _scope_repo(repo)
    if repo_key is None and not allow_fleet:
        return _empty_authz_surface_packet(
            scope={"repo": None, "mode": "unscoped"},
            limit=limit,
            missing_fact_families=["service_repo"],
            recommended_source_checks=[
                "Resolve the service to a repo before using authz_surface; service-scoped packets do not fall back to fleet-wide authz rows."
            ],
        )
    rows = _authz_rows(kg, repo=repo)
    endpoint_bindings = [row for row in rows if row["predicate"] == "HANDLES_ENDPOINT"]
    applied_policies = [row for row in rows if row["predicate"] == "APPLIES_AUTHZ_POLICY"]
    declared_policies = [row for row in rows if row["predicate"] == "DEFINES_AUTHZ_POLICY"]
    checks = [row for row in rows if row["predicate"] == "USES_AUTHZ_CHECK"]
    endpoint_authorization = _endpoint_authorization(endpoint_bindings, applied_policies, checks, limit=limit)
    missing_authz = [row for row in endpoint_authorization if row.get("authz_status") == "missing_declared_policy"]
    return {
        "status": "found" if rows else "empty",
        "scope": {"repo": repo_scope, "mode": "repo" if repo_key else "fleet"},
        "summary": {
            "endpoint_handler_count": len(endpoint_authorization),
            "endpoint_handler_fact_count": len(endpoint_bindings),
            "declared_policy_count": len(declared_policies),
            "applied_policy_count": len(applied_policies),
            "in_method_check_count": len(checks),
            "endpoint_authorization_count": len(endpoint_authorization),
            "missing_or_unknown_authz_count": len(missing_authz),
            "section_limit": limit,
        },
        "endpoint_authorization": endpoint_authorization[:limit],
        "applied_policies": applied_policies[:limit],
        "in_method_checks": checks[:limit],
        "declared_policies": declared_policies[:limit],
        "missing_or_unknown": missing_authz[:limit],
        "answerability": {
            "status": "partial" if missing_authz else ("answerable" if rows else "empty"),
            "missing_fact_families": (
                ["endpoint_authz_policy"] if missing_authz else ([] if rows else ["authz_surface"])
            ),
            "recommended_source_checks": [
                "Verify framework defaults and custom middleware in source before concluding an endpoint is public.",
                "For endpoint-level security answers, treat missing_declared_policy as a source-inspection lead, not proof of unauthenticated access.",
            ],
        },
        "assembly_contract": (
            "authz_surface is assembled from parser-backed support facts: route handler bindings, DRF/flask auth decorators, "
            "DRF permission_classes, custom permission classes, and recognized framework auth checks. "
            "It separates missing/unknown policy from proven public access and does not infer dynamic middleware or settings defaults."
            " Section rows and per-endpoint policies/checks are bounded by section_limit."
        ),
    }


def _empty_authz_surface_packet(
    *,
    scope: JsonObject,
    limit: int,
    missing_fact_families: list[str],
    recommended_source_checks: list[str],
) -> JsonObject:
    return {
        "status": "empty",
        "scope": scope,
        "summary": {
            "endpoint_handler_count": 0,
            "endpoint_handler_fact_count": 0,
            "declared_policy_count": 0,
            "applied_policy_count": 0,
            "in_method_check_count": 0,
            "endpoint_authorization_count": 0,
            "missing_or_unknown_authz_count": 0,
            "section_limit": limit,
        },
        "endpoint_authorization": [],
        "applied_policies": [],
        "in_method_checks": [],
        "declared_policies": [],
        "missing_or_unknown": [],
        "answerability": {
            "status": "empty",
            "missing_fact_families": missing_fact_families,
            "recommended_source_checks": recommended_source_checks,
        },
        "assembly_contract": (
            "authz_surface is assembled from parser-backed support facts: route handler bindings, DRF/flask auth decorators, "
            "DRF permission_classes, custom permission classes, and recognized framework auth checks. "
            "It separates missing/unknown policy from proven public access and does not infer dynamic middleware or settings defaults."
            " Section rows and per-endpoint policies/checks are bounded by section_limit."
        ),
    }


def _authz_rows(kg: KgSnapshot, *, repo: str | None) -> list[JsonObject]:
    repo_key = _normalize_repo(repo)
    rows = []
    for fact in kg.support_facts:
        if fact.get("predicate") not in AUTHZ_PREDICATES:
            continue
        subject = kg.entities_by_id.get(fact.get("subject_id"))
        object_ = kg.entities_by_id.get(fact.get("object_id"))
        if not subject or not object_:
            continue
        if repo_key and _entity_repo(subject) != repo_key:
            continue
        rows.append(
            {
                "fact_id": fact.get("fact_id"),
                "predicate": fact.get("predicate"),
                "subject": _entity_row(subject),
                "object": _entity_row(object_),
                "qualifier": fact.get("qualifier", {}),
                "evidence": kg.evidence_by_target.get(fact.get("fact_id"), []),
            }
        )
    return rows


def _endpoint_authorization(
    endpoint_bindings: list[JsonObject],
    applied_policies: list[JsonObject],
    checks: list[JsonObject],
    *,
    limit: int,
) -> list[JsonObject]:
    policies_by_subject: dict[str, list[JsonObject]] = {}
    checks_by_subject: dict[str, list[JsonObject]] = {}
    for row in applied_policies:
        subject_id = row["subject"].get("entity_id")
        if isinstance(subject_id, str):
            policies_by_subject.setdefault(subject_id, []).append(row)
    for row in checks:
        subject_id = row["subject"].get("entity_id")
        if isinstance(subject_id, str):
            checks_by_subject.setdefault(subject_id, []).append(row)

    rows: list[JsonObject] = []
    for binding in endpoint_bindings:
        handler = binding["subject"]
        handler_id = handler.get("entity_id")
        handler_policies = list(policies_by_subject.get(handler_id, [])) if isinstance(handler_id, str) else []
        handler_checks = list(checks_by_subject.get(handler_id, [])) if isinstance(handler_id, str) else []
        handler_policies.extend(_method_rows_for_handler(handler, applied_policies))
        handler_checks.extend(_method_rows_for_handler(handler, checks))
        access_levels = {
            str(row.get("qualifier", {}).get("access_level"))
            for row in [*handler_policies, *handler_checks]
            if row.get("qualifier", {}).get("access_level")
        }
        public_policy_present = "public" in access_levels
        if access_levels and access_levels <= {"public"}:
            authz_status = "declared_public"
        elif handler_policies or handler_checks:
            authz_status = "authz_evidence_found"
        else:
            authz_status = "missing_declared_policy"
        rows.append(
            {
                "endpoint": binding["object"],
                "handler": handler,
                "route": binding.get("qualifier", {}),
                "authz_status": authz_status,
                "public_policy_present": public_policy_present,
                "policies": _dedupe_rows(handler_policies)[:limit],
                "checks": _dedupe_rows(handler_checks)[:limit],
                "evidence": binding.get("evidence", []),
            }
        )
    return sorted(_dedupe_endpoint_rows(rows), key=_endpoint_sort_key)


def _method_rows_for_handler(handler: JsonObject, rows: list[JsonObject]) -> list[JsonObject]:
    module = handler.get("module")
    qualname = handler.get("qualname")
    if not isinstance(module, str) or not isinstance(qualname, str):
        return []
    prefix = f"{qualname}."
    expected_depth = qualname.count(".") + 1
    matches = []
    for row in rows:
        subject = row.get("subject", {})
        if not isinstance(subject, dict):
            continue
        if subject.get("module") == module and isinstance(subject.get("qualname"), str):
            subject_qualname = str(subject["qualname"])
            if subject_qualname.startswith(prefix) and subject_qualname.count(".") == expected_depth:
                matches.append(row)
    return matches


def _dedupe_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[object, object]] = set()
    deduped = []
    for row in rows:
        key = (row.get("fact_id"), row.get("predicate"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_endpoint_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[object, object]] = set()
    deduped = []
    for row in rows:
        endpoint = row.get("endpoint", {})
        handler = row.get("handler", {})
        key = (
            endpoint.get("entity_id") if isinstance(endpoint, dict) else None,
            handler.get("entity_id") if isinstance(handler, dict) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _endpoint_sort_key(row: JsonObject) -> tuple[str, str]:
    endpoint = row.get("endpoint", {})
    route = row.get("route", {})
    path = ""
    method = ""
    if isinstance(endpoint, dict):
        properties = endpoint.get("properties", {})
        path = str(endpoint.get("path") or "")
        method = str(endpoint.get("method") or "")
        if isinstance(properties, dict):
            path = str(properties.get("path") or path)
    if isinstance(route, dict):
        path = str(route.get("path") or path)
        method = str(route.get("method") or method)
    return (path, method)


def _entity_row(entity: JsonObject) -> JsonObject:
    identity = entity.get("identity")
    properties = entity.get("properties")
    if not isinstance(identity, dict):
        identity = {}
    if not isinstance(properties, dict):
        properties = {}
    row = {
        "entity_id": entity.get("entity_id"),
        "kind": entity.get("kind"),
        "name": display_entity(entity),
        "repo": identity.get("repo") or properties.get("repo"),
        "module": identity.get("module"),
        "qualname": identity.get("qualname"),
        "symbol_kind": identity.get("symbol_kind"),
        "properties": properties,
    }
    if entity.get("kind") == "Endpoint":
        row["method"] = identity.get("method")
        row["path"] = identity.get("path")
    if entity.get("kind") == "ExternalSymbol":
        row["module"] = identity.get("module")
    return row


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
    text = str(value).strip().lower()
    return text or None


def _scope_repo(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
