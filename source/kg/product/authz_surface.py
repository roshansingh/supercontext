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
AUTHZ_SUPPORTED_LANGUAGES = {"python"}
AUTHZ_NON_SECURITY_SURFACE_LANGUAGES = {
    "css",
    "csv",
    "dockerfile",
    "hcl",
    "html",
    "ini",
    "json",
    "jsonnet",
    "markdown",
    "md",
    "scss",
    "shell",
    "terraform",
    "text",
    "toml",
    "txt",
    "xml",
    "yaml",
    "yml",
}
AUTHZ_INSPECTION_REF_MAX = 40


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
    review_leads = _authz_review_leads(endpoint_authorization)
    unsupported_scopes = _authz_unsupported_scopes(kg)
    inspection_areas = _authz_inspection_areas(
        endpoint_authorization,
        applied_policies=applied_policies,
        checks=checks,
        declared_policies=declared_policies,
        missing_authz=missing_authz,
        review_leads=review_leads,
        unsupported_scopes=unsupported_scopes,
        limit=limit,
    )
    inspection_index = _authz_inspection_index(inspection_areas, limit=limit)
    missing_fact_families = []
    if missing_authz:
        missing_fact_families.append("endpoint_authz_policy")
    if unsupported_scopes:
        missing_fact_families.append("unsupported_authz_languages")
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
            "review_lead_count": len(review_leads),
            "inspection_area_count": len(inspection_areas),
            "inspection_index_count": len(inspection_index),
            "inspection_row_count": sum(_int_area_count(area.get("inspection_row_count")) for area in inspection_areas),
            "inspection_ref_count": sum(_int_area_count(area.get("inspection_ref_count")) for area in inspection_areas),
            "unsupported_scope_count": len(unsupported_scopes),
            "section_limit": limit,
        },
        "review_leads": review_leads[:limit],
        "inspection_areas": inspection_areas,
        "inspection_index": inspection_index,
        "endpoint_authorization": endpoint_authorization[:limit],
        "applied_policies": applied_policies[:limit],
        "in_method_checks": checks[:limit],
        "declared_policies": declared_policies[:limit],
        "missing_or_unknown": missing_authz[:limit],
        "unsupported_scopes": unsupported_scopes[:limit],
        "answerability": {
            "status": "partial" if missing_fact_families else ("answerable" if rows else "empty"),
            "missing_fact_families": missing_fact_families if rows else ["authz_surface"],
            "recommended_source_checks": [
                "Start endpoint-level security reviews from authz_surface.review_leads, then use inspection_areas for omitted or dynamic authz checks.",
                "Verify framework defaults and custom middleware in source before concluding an endpoint is public.",
                "For endpoint-level security answers, treat missing_declared_policy as a source-inspection lead, not proof of unauthenticated access.",
                "Explicitly refuse to prove authz behavior for unsupported languages or frameworks listed in authz_surface.unsupported_scopes.",
            ],
        },
        "assembly_contract": (
            "authz_surface is assembled from parser-backed support facts: route handler bindings, DRF/flask auth decorators, "
            "DRF permission_classes, custom permission classes, and recognized framework auth checks. "
            "It separates missing/unknown policy from proven public access and does not infer dynamic middleware or settings defaults."
            " review_leads is prioritized from the full authz set before section row limits are applied."
            " When rows are pruned by section_limit, inspection_areas and inspection_index preserve compact coordinates "
            "for omitted rows so the agent can inspect source without rediscovering the row."
            " Inspection areas may also include source-check guidance for partial or dynamic authz cases even when those rows are not omitted."
            " Section rows and per-endpoint policies/checks are bounded by section_limit."
            " unsupported_scopes lists languages/files outside the current authz extractor coverage and must be treated as unknown."
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
            "review_lead_count": 0,
            "inspection_area_count": len(recommended_source_checks),
            "inspection_index_count": 0,
            "inspection_row_count": 0,
            "inspection_ref_count": 0,
            "unsupported_scope_count": 0,
            "section_limit": limit,
        },
        "review_leads": [],
        "inspection_areas": [
            {
                "area": "authz_surface_unavailable",
                "reason": reason,
                "recommended_source_checks": [reason],
            }
            for reason in recommended_source_checks
        ],
        "inspection_index": [],
        "endpoint_authorization": [],
        "applied_policies": [],
        "in_method_checks": [],
        "declared_policies": [],
        "missing_or_unknown": [],
        "unsupported_scopes": [],
        "answerability": {
            "status": "empty",
            "missing_fact_families": missing_fact_families,
            "recommended_source_checks": recommended_source_checks,
        },
        "assembly_contract": (
            "authz_surface is assembled from parser-backed support facts: route handler bindings, DRF/flask auth decorators, "
            "DRF permission_classes, custom permission classes, and recognized framework auth checks. "
            "It separates missing/unknown policy from proven public access and does not infer dynamic middleware or settings defaults."
            " review_leads is prioritized from the full authz set before section row limits are applied."
            " When rows are pruned by section_limit, inspection_areas and inspection_index preserve compact coordinates "
            "for omitted rows so the agent can inspect source without rediscovering the row."
            " Inspection areas may also include source-check guidance for partial or dynamic authz cases even when those rows are not omitted."
            " Section rows and per-endpoint policies/checks are bounded by section_limit."
            " unsupported_scopes lists languages/files outside the current authz extractor coverage and must be treated as unknown."
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


def _authz_review_leads(endpoint_authorization: list[JsonObject]) -> list[JsonObject]:
    leads = []
    for row in endpoint_authorization:
        leads.extend(_authz_review_leads_for_row(row))
    return sorted(_dedupe_review_leads(leads), key=_review_lead_sort_key)


def _authz_review_leads_for_row(row: JsonObject) -> list[JsonObject]:
    checks = _list_of_dicts(row.get("checks"))
    policies = _list_of_dicts(row.get("policies"))
    access_levels = _access_levels([*checks, *policies])
    leads: list[JsonObject] = []
    if row.get("authz_status") == "declared_public":
        leads.append(
            _lead(
                row,
                lead_type="declared_public",
                priority=100,
                reason="Endpoint is explicitly public through an AllowAny-style policy; inspect whether it can perform privileged writes or account/data changes.",
                recommended_source_checks=[
                    "Read the handler body and called service methods for writes, external calls, or account/data changes.",
                    "Check whether public access is intentional for this endpoint.",
                ],
            )
        )
    elif row.get("public_policy_present"):
        leads.append(
            _lead(
                row,
                lead_type="public_policy_present",
                priority=75,
                reason="Endpoint includes an explicit public policy alongside other authz evidence; inspect both the public surface and the additional guard or policy.",
                recommended_source_checks=[
                    "Read the public policy declaration and the additional guard or permission checks.",
                    "Verify whether public access is intentional and whether later checks protect the privileged action.",
                ],
            )
        )
    if _has_source_kind(checks, "custom_guard_call"):
        leads.append(
            _lead(
                row,
                lead_type="custom_guard",
                priority=90,
                reason="Endpoint has a parser-backed custom security guard call with an auth failure outcome; inspect the guard implementation to confirm authz semantics and the protected action.",
                recommended_source_checks=[
                    "Read the handler body around the custom guard call and 401/403 branch.",
                    "Read the guard function implementation to confirm header/token/request validation semantics.",
                    "Inspect the handler's side effects after the guard succeeds.",
                ],
            )
        )
    if row.get("authz_status") == "missing_declared_policy":
        leads.append(
            _lead(
                row,
                lead_type="missing_policy",
                priority=80,
                reason="Endpoint has a route-handler binding but no KG-proven policy or guard; inspect framework defaults, middleware, decorators, and handler body before classifying access.",
                recommended_source_checks=[
                    "Read the handler class/function for permission_classes, decorators, get_permissions overrides, and in-method guards.",
                    "Read framework settings or middleware if the handler does not declare authz locally.",
                ],
            )
        )
    if access_levels & {"privileged", "permission_required", "model_permissions", "object_permissions", "custom_policy"}:
        leads.append(
            _lead(
                row,
                lead_type="privileged_policy",
                priority=70,
                reason="Endpoint has privileged or custom policy evidence; inspect the policy implementation and protected action.",
                recommended_source_checks=[
                    "Read the policy class/decorator implementation.",
                    "Read the handler body for the privileged action being protected.",
                ],
            )
        )
    if access_levels & {"permission_check", "object_permission_check", "permission_denied"}:
        leads.append(
            _lead(
                row,
                lead_type="in_method_check",
                priority=60,
                reason="Endpoint has in-method authorization check evidence; inspect the branch and protected operation.",
                recommended_source_checks=[
                    "Read the in-method check and failure branch.",
                    "Read the code after the check to identify the protected action.",
                ],
            )
        )
    return leads


def _lead(
    row: JsonObject,
    *,
    lead_type: str,
    priority: int,
    reason: str,
    recommended_source_checks: list[str],
) -> JsonObject:
    return {
        "lead_type": lead_type,
        "priority": priority,
        "reason": reason,
        "endpoint": row.get("endpoint", {}),
        "handler": row.get("handler", {}),
        "route": row.get("route", {}),
        "authz_status": row.get("authz_status"),
        "public_policy_present": row.get("public_policy_present", False),
        "policies": _lead_fact_summaries(row.get("policies")),
        "checks": _lead_fact_summaries(row.get("checks")),
        "evidence": row.get("evidence", []),
        "recommended_source_checks": recommended_source_checks,
    }


def _authz_inspection_areas(
    endpoint_authorization: list[JsonObject],
    *,
    applied_policies: list[JsonObject],
    checks: list[JsonObject],
    declared_policies: list[JsonObject],
    missing_authz: list[JsonObject],
    review_leads: list[JsonObject],
    unsupported_scopes: list[JsonObject],
    limit: int,
) -> list[JsonObject]:
    areas: list[JsonObject] = []
    omitted_endpoints = endpoint_authorization[limit:]
    if omitted_endpoints:
        areas.append(
            _inspection_area(
                area="omitted_endpoint_rows",
                rows=omitted_endpoints,
                ref_builder=lambda row: _endpoint_inspection_ref(row, category="omitted_endpoint"),
                limit=limit,
                reason="endpoint_authorization is bounded by section_limit; review_leads is prioritized from the full set, but lower-priority rows are omitted from the compact packet.",
                recommended_source_checks=[
                    "Call get_service_brief or planning_context again with a higher limit or narrower repo/service/endpoint anchor if omitted endpoints matter.",
                ],
            )
        )
    if missing_authz:
        areas.append(
            _inspection_area(
                area="missing_or_unknown_endpoint_authz",
                rows=missing_authz,
                ref_builder=lambda row: _endpoint_inspection_ref(row, category="missing_or_unknown_authz"),
                limit=limit,
                reason="Some endpoints have handler bindings but no KG-proven policy or guard.",
                recommended_source_checks=[
                    "Inspect handler-local permission declarations, decorators, get_permissions overrides, middleware, and framework defaults.",
                    "Do not treat missing_declared_policy as proof of public access.",
                ],
            )
        )
    custom_guard_leads = [
        lead for lead in review_leads if _has_source_kind(_list_of_dicts(lead.get("checks")), "custom_guard_call")
    ]
    if custom_guard_leads:
        areas.append(
            _inspection_area(
                area="custom_guard_implementations",
                rows=custom_guard_leads,
                ref_builder=lambda row: _lead_inspection_ref(row, category="custom_guard"),
                limit=limit,
                reason="Custom security guard calls prove a local auth failure path, but the guard implementation still determines whether the check is authn, authz, signature validation, tenant membership, or another security gate.",
                recommended_source_checks=[
                    "Read each custom guard implementation referenced by review_leads.",
                    "Check whether the guard validates headers, API keys, tokens, signatures, session users, or tenant/company membership.",
                ],
            )
        )
    public_leads = [
        lead for lead in review_leads if lead.get("lead_type") in {"declared_public", "public_policy_present"}
    ]
    if public_leads:
        areas.append(
            _inspection_area(
                area="public_endpoint_effects",
                rows=public_leads,
                ref_builder=lambda row: _lead_inspection_ref(row, category="public_endpoint"),
                limit=limit,
                reason="Explicitly public endpoints need source inspection to determine whether they reach privileged actions.",
                recommended_source_checks=[
                    "Read public handlers and immediate callees for writes, account changes, billing changes, deletes, message sends, or external side effects.",
                ],
            )
        )
    omitted_policies = applied_policies[limit:]
    if omitted_policies:
        areas.append(
            _inspection_area(
                area="omitted_applied_policy_rows",
                rows=omitted_policies,
                ref_builder=lambda row: _fact_inspection_ref(row, category="omitted_applied_policy"),
                limit=limit,
                reason="applied_policies is bounded by section_limit; remaining policy rows are source-inspection leads for broader endpoint security coverage.",
                recommended_source_checks=[
                    "Inspect these policy coordinates when the answer needs broad endpoint security coverage beyond the detailed lead rows.",
                ],
            )
        )
    omitted_checks = checks[limit:]
    if omitted_checks:
        areas.append(
            _inspection_area(
                area="omitted_in_method_check_rows",
                rows=omitted_checks,
                ref_builder=lambda row: _fact_inspection_ref(row, category="omitted_in_method_check"),
                limit=limit,
                reason="in_method_checks is bounded by section_limit; remaining checks are source-inspection leads for custom or branch-local authorization logic.",
                recommended_source_checks=[
                    "Inspect these check coordinates before concluding only the displayed in-method checks exist.",
                ],
            )
        )
    omitted_declared = declared_policies[limit:]
    if omitted_declared:
        areas.append(
            _inspection_area(
                area="omitted_declared_policy_rows",
                rows=omitted_declared,
                ref_builder=lambda row: _fact_inspection_ref(row, category="omitted_declared_policy"),
                limit=limit,
                reason="declared_policies is bounded by section_limit; remaining policy definitions can explain custom permission semantics.",
                recommended_source_checks=[
                    "Inspect policy definitions when an applied custom policy appears in an omitted or compact row.",
                ],
            )
        )
    if unsupported_scopes:
        areas.append(
            _inspection_area(
                area="unsupported_authz_scopes",
                rows=unsupported_scopes,
                ref_builder=lambda row: _unsupported_scope_inspection_ref(row),
                limit=limit,
                reason="Some indexed files are in languages or formats outside the current parser-backed authz surface.",
                recommended_source_checks=[
                    "Do not prove or disprove endpoint authorization for unsupported language files from the KG packet.",
                    "Inspect unsupported files manually when the question asks for complete authz coverage.",
                ],
            )
        )
    return areas


def _authz_unsupported_scopes(kg: KgSnapshot) -> list[JsonObject]:
    manifest_counts = kg.manifest.get("counts", {})
    if not isinstance(manifest_counts, dict):
        return []
    rows = []
    files_by_language = manifest_counts.get("files_by_language")
    if isinstance(files_by_language, dict):
        for language, count in sorted(files_by_language.items()):
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                continue
            language_key = str(language).lower()
            if language_key in AUTHZ_SUPPORTED_LANGUAGES:
                continue
            if language_key in AUTHZ_NON_SECURITY_SURFACE_LANGUAGES:
                continue
            rows.append(
                {
                    "language": str(language),
                    "file_count": count,
                    "reason": "language_has_no_authz_extractor",
                }
            )
    unsupported_counts = manifest_counts.get("unsupported_files_by_language")
    if not isinstance(unsupported_counts, dict):
        return rows
    existing = {str(row.get("language")).lower() for row in rows}
    for language, count in sorted(unsupported_counts.items()):
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            continue
        language_key = str(language).lower()
        if language_key in AUTHZ_NON_SECURITY_SURFACE_LANGUAGES:
            continue
        if language_key in existing:
            continue
        rows.append(
            {
                "language": str(language),
                "file_count": count,
                "reason": "unsupported_language",
            }
        )
    return rows


def _authz_inspection_index(inspection_areas: list[JsonObject], *, limit: int) -> list[JsonObject]:
    refs = []
    for area in inspection_areas:
        area_name = area.get("area")
        for ref in _list_of_dicts(area.get("inspection_refs")):
            item = dict(ref)
            item.setdefault("area", area_name)
            refs.append(item)
    return refs[: _inspection_ref_limit(limit)]


def _inspection_area(
    *,
    area: str,
    rows: list[JsonObject],
    ref_builder,
    limit: int,
    reason: str,
    recommended_source_checks: list[str],
) -> JsonObject:
    ref_limit = _inspection_ref_limit(limit)
    refs = []
    for row in rows[:ref_limit]:
        ref = ref_builder(row)
        if ref:
            refs.append(ref)
    result: JsonObject = {
        "area": area,
        "count": len(rows),
        "inspection_row_count": len(rows),
        "inspection_ref_count": len(refs),
        "inspection_refs": refs,
        "reason": reason,
        "recommended_source_checks": recommended_source_checks,
    }
    omitted = max(0, len(rows) - len(refs))
    if omitted:
        result["omitted_inspection_ref_count"] = omitted
        result["continuation"] = (
            "Narrow by repo/service/endpoint/path or rerun with a higher limit to retrieve additional compact inspection references."
        )
    return result


def _inspection_ref_limit(limit: int) -> int:
    if limit <= 0:
        return 1
    return min(AUTHZ_INSPECTION_REF_MAX, max(3, limit * 4))


def _endpoint_inspection_ref(row: JsonObject, *, category: str) -> JsonObject:
    checks = _list_of_dicts(row.get("checks"))
    policies = _list_of_dicts(row.get("policies"))
    return _drop_empty(
        {
            "category": category,
            "endpoint": _endpoint_ref(row.get("endpoint"), row.get("route")),
            "handler": _code_ref(row.get("handler")),
            "authz_status": row.get("authz_status"),
            "public_policy_present": row.get("public_policy_present"),
            "policy_count": len(policies),
            "check_count": len(checks),
            "policy_names": _policy_names(policies),
            "check_names": _check_names(checks),
            "evidence": _evidence_refs(row.get("evidence")),
        }
    )


def _lead_inspection_ref(row: JsonObject, *, category: str) -> JsonObject:
    checks = _list_of_dicts(row.get("checks"))
    policies = _list_of_dicts(row.get("policies"))
    return _drop_empty(
        {
            "category": category,
            "lead_type": row.get("lead_type"),
            "endpoint": _endpoint_ref(row.get("endpoint"), row.get("route")),
            "handler": _code_ref(row.get("handler")),
            "authz_status": row.get("authz_status"),
            "public_policy_present": row.get("public_policy_present"),
            "policy_names": _policy_names(policies),
            "check_names": _check_names(checks),
            "guard_implementations": [
                _code_ref(check.get("object"))
                for check in checks
                if isinstance(check, dict) and _row_source_kind(check) == "custom_guard_call"
            ],
            "evidence": _evidence_refs(row.get("evidence")),
        }
    )


def _fact_inspection_ref(row: JsonObject, *, category: str) -> JsonObject:
    return _drop_empty(
        {
            "category": category,
            "predicate": row.get("predicate"),
            "subject": _code_ref(row.get("subject")),
            "object": _code_ref(row.get("object")),
            "qualifier": _compact_qualifier(row.get("qualifier")),
            "evidence": _evidence_refs(row.get("evidence")),
        }
    )


def _unsupported_scope_inspection_ref(row: JsonObject) -> JsonObject:
    return _drop_empty(
        {
            "category": "unsupported_authz_scope",
            "language": row.get("language"),
            "file_count": row.get("file_count"),
            "reason": row.get("reason"),
        }
    )


def _endpoint_ref(endpoint: object, route: object) -> JsonObject:
    endpoint_row = endpoint if isinstance(endpoint, dict) else {}
    route_row = route if isinstance(route, dict) else {}
    return _drop_empty(
        {
            "repo": endpoint_row.get("repo"),
            "method": route_row.get("method") or endpoint_row.get("method"),
            "path": _endpoint_path(endpoint_row, route_row),
            "framework": route_row.get("framework"),
            "source_kind": route_row.get("source_kind"),
        }
    )


def _endpoint_path(endpoint: JsonObject, route: JsonObject) -> object:
    route_path = route.get("path")
    endpoint_path = endpoint.get("path")
    if isinstance(route_path, str) and route_path.startswith("/"):
        return route_path
    if isinstance(endpoint_path, str) and endpoint_path:
        return endpoint_path
    return route_path


def _code_ref(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    properties = value.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    return _drop_empty(
        {
            "repo": value.get("repo"),
            "path": value.get("path") or properties.get("path"),
            "line": value.get("line") or properties.get("line") or properties.get("start_line"),
            "module": value.get("module"),
            "qualname": value.get("qualname"),
            "symbol_kind": value.get("symbol_kind"),
            "name": value.get("name"),
            "kind": value.get("kind"),
        }
    )


def _compact_qualifier(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    allowed = (
        "access_level",
        "framework",
        "policy",
        "check",
        "source_kind",
        "guard_intent",
        "method",
        "path",
    )
    return {key: value[key] for key in allowed if key in value}


def _evidence_refs(value: object, *, limit: int = 2) -> list[JsonObject]:
    refs = []
    for row in _list_of_dicts(value)[:limit]:
        bytes_ref = row.get("bytes_ref")
        if not isinstance(bytes_ref, dict):
            continue
        refs.append(
            _drop_empty(
                {
                    "repo": bytes_ref.get("repo"),
                    "path": bytes_ref.get("path"),
                    "line": bytes_ref.get("line_start"),
                    "line_end": bytes_ref.get("line_end"),
                    "extractor": _source_ref_value(row.get("source_ref"), "extractor"),
                    "predicate": _source_ref_value(row.get("source_ref"), "predicate"),
                }
            )
        )
    return refs


def _source_ref_value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _policy_names(rows: list[JsonObject]) -> list[str]:
    names = []
    for row in rows:
        qualifier = row.get("qualifier", {})
        if isinstance(qualifier, dict) and isinstance(qualifier.get("policy"), str):
            names.append(qualifier["policy"])
    return sorted(set(names))


def _check_names(rows: list[JsonObject]) -> list[str]:
    names = []
    for row in rows:
        qualifier = row.get("qualifier", {})
        if not isinstance(qualifier, dict):
            continue
        for key in ("check", "guard", "policy"):
            if isinstance(qualifier.get(key), str):
                names.append(qualifier[key])
    return sorted(set(names))


def _row_source_kind(row: JsonObject) -> object:
    qualifier = row.get("qualifier")
    if isinstance(qualifier, dict):
        return qualifier.get("source_kind")
    return None


def _drop_empty(value: JsonObject) -> JsonObject:
    return {key: item for key, item in value.items() if item not in (None, [], {})}


def _int_area_count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _access_levels(rows: list[JsonObject]) -> set[str]:
    levels = set()
    for row in rows:
        qualifier = row.get("qualifier", {})
        if isinstance(qualifier, dict) and isinstance(qualifier.get("access_level"), str):
            levels.add(qualifier["access_level"])
    return levels


def _has_source_kind(rows: list[JsonObject], source_kind: str) -> bool:
    for row in rows:
        qualifier = row.get("qualifier", {})
        if isinstance(qualifier, dict) and qualifier.get("source_kind") == source_kind:
            return True
    return False


def _list_of_dicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _lead_fact_summaries(value: object) -> list[JsonObject]:
    summaries = []
    for row in _list_of_dicts(value):
        summaries.append(
            {
                "predicate": row.get("predicate"),
                "object": row.get("object", {}),
                "qualifier": row.get("qualifier", {}),
                "evidence": row.get("evidence", []),
            }
        )
    return summaries


def _dedupe_review_leads(rows: list[JsonObject]) -> list[JsonObject]:
    seen: set[tuple[object, object]] = set()
    deduped = []
    for row in rows:
        endpoint = row.get("endpoint", {})
        handler = row.get("handler", {})
        key = (
            row.get("lead_type"),
            endpoint.get("entity_id") if isinstance(endpoint, dict) else None,
            handler.get("entity_id") if isinstance(handler, dict) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _review_lead_sort_key(row: JsonObject) -> tuple[int, str, str]:
    endpoint = row.get("endpoint", {})
    route = row.get("route", {})
    path = ""
    if isinstance(endpoint, dict):
        path = str(endpoint.get("path") or "")
    if isinstance(route, dict):
        path = str(route.get("path") or path)
    return (-int(row.get("priority") or 0), str(row.get("lead_type") or ""), path)


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
