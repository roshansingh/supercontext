from __future__ import annotations

from copy import deepcopy

from source.kg.core.models import JsonObject, canonical_json


# Default MCP responses must stay inline in host agents. Once Claude Code saves
# a large tool result to a sidecar file, agents tend to spend turns doing jq
# archaeology instead of source inspection. MCP responses currently include the
# same packet in `content[].text` and `structuredContent`, so keep the one-copy
# hard cap near 12K to leave room for the doubled wire payload.
MCP_INLINE_TARGET_CHARS = 8_000
MCP_INLINE_HARD_MAX_CHARS = 12_000
PLANNING_CONTEXT_MAX_CHARS = MCP_INLINE_HARD_MAX_CHARS
PLANNING_CONTEXT_ANCHORED_MAX_CHARS = MCP_INLINE_HARD_MAX_CHARS
INLINE_HEADSTART_ROW_LIMIT = 3
INLINE_INSPECTION_AREA_LIMIT = 8
INLINE_NEXT_MCP_CALL_LIMIT = 6
INLINE_COVERED_AREA_LIMIT = 8
INLINE_INSPECTION_REF_LIMIT = 3
GREP_RESPONSE_KEYS = (
    "tool",
    "query",
    "status",
    "answerability",
    "boundary",
    "covered",
    "must_inspect",
    "shown",
    "more",
    "rows",
    "gaps",
    "next",
)
GREP_ROW_CANDIDATE_KINDS = frozenset(
    {
        "import_only_source_lead",
        "unlinked_source_lead",
        "inference_or_guidance",
        "truncated_source_inspection_lead",
        "coverage_gap_lead",
    }
)
GREP_RENDER_SOURCE_ROW_LIMIT = 200
GREP_RENDER_SOURCE_GROUP_ROW_LIMIT = 80
GREP_COVERED_SUMMARY_LIMIT = 8
GREP_MUST_INSPECT_LIMIT = 8
GREP_MUST_INSPECT_REF_LIMIT = 2
GREP_FALLBACK_FIELD_TAGS = {
    "surface_status": "candidate",
}
INLINE_PRESERVED_TOP_LEVEL_KEYS = frozenset(
    {
        "tool",
        "status",
        "query",
        "repo",
        "anchors",
        "summary",
        "answerability",
        "packet_contract",
        "proven_facts",
        "candidate_leads",
        "coverage_gaps",
        "inspection_areas",
        "next_actions",
        "output_budget",
    }
)
COMPACT_RUNTIME_COMPONENT_LIMIT = 4
COMPACT_RUNTIME_ROUTE_LIMIT = 15
COMPACT_RUNTIME_HEADSTART_LIMIT = 8
COMPACT_RUNTIME_LEAD_LIMIT = 8
COMPACT_RUNTIME_DEPLOY_UNIT_LIMIT = 2
COMPACT_RUNTIME_SOURCE_CHECK_LIMIT = 15
COMPACT_AUTHZ_INSPECTION_REF_LIMIT = INLINE_INSPECTION_REF_LIMIT
AUTHZ_COMPACT_LIST_KEYS = (
    "review_leads",
    "inspection_areas",
    "inspection_index",
    "endpoint_authorization",
    "applied_policies",
    "in_method_checks",
    "declared_policies",
    "missing_or_unknown",
    "unsupported_scopes",
)
RELATED_FACT_SECTION_KEYS = frozenset(
    {
        "service_brief",
        "symbol_impact",
        "dependency_importers",
        "inventory",
        "service_operational_surfaces",
        "runtime_architecture",
        "authz_surface",
        "dependencies",
        "endpoints",
        "endpoint_consumers",
        "event_channels",
        "deploy_mappings",
        "domains",
    }
)
INLINE_CORE_ROW_KEYS = (
    "services",
    "symbols",
    "dependencies",
    "endpoints",
    "endpoint_consumers",
    "event_channels",
    "consumers",
    "producers",
    "callers",
    "callees",
    "edges",
    "affected_symbols",
    "deploy_mappings",
    "domains",
    "entry_points",
    "changed_symbols",
    "changed_file_symbols",
    "direct_callers",
    "direct_callees",
    "direct_callers_of_changed_symbols",
    "direct_callees_from_changed_symbols",
    "transitive_callers",
    "repo_dependencies",
    "source_coordinates",
    "evidence",
    "surface_status",
)

_RUNTIME_COMPONENTS_PATH = "runtime_architecture.answer_packet.runtime_building_blocks"
_RUNTIME_ROUTES_PATH = "runtime_architecture.answer_packet.domain_routing_map"
_RUNTIME_DEPLOY_UNITS_PATH = "runtime_architecture.answer_packet.deploy_runtime_map"
_RUNTIME_CONSUMERS_PATH = "runtime_architecture.answer_packet.endpoint_consumer_map"
_RUNTIME_DEPLOY_GUIDANCE_PATH = "runtime_architecture.answer_packet.deploy_order_guidance"
_RUNTIME_INVESTIGATION_BRIEF_PATH = "runtime_architecture.answer_packet.investigation_brief"
_BUDGET_BACKFILL_LIST_PATHS: tuple[tuple[str, ...], ...] = (
    ("runtime_architecture", "answer_packet", "investigation_brief", "runtime_anchors"),
    ("runtime_architecture", "answer_packet", "investigation_brief", "known_routes"),
    ("runtime_architecture", "answer_packet", "investigation_brief", "unlinked_runtime_leads"),
    ("runtime_architecture", "answer_packet", "investigation_brief", "deploy_units"),
    ("runtime_architecture", "answer_packet", "investigation_brief", "consumer_links"),
    ("runtime_architecture", "answer_packet", "investigation_brief", "recommended_source_checks"),
    *(("authz_surface", key) for key in AUTHZ_COMPACT_LIST_KEYS),
    *(("related_facts", "authz_surface", key) for key in AUTHZ_COMPACT_LIST_KEYS),
    ("runtime_architecture", "answer_packet", "runtime_building_blocks"),
    ("runtime_architecture", "answer_packet", "domain_routing_map"),
    ("runtime_architecture", "answer_packet", "deploy_runtime_map"),
    ("runtime_architecture", "answer_packet", "endpoint_consumer_map"),
    ("runtime_architecture", "answer_packet", "deploy_order_guidance"),
    ("ownership_context", "proven_owners"),
    ("ownership_context", "candidate_maintainers"),
    ("ownership_context", "answer_packet", "unsupported_promotions"),
    ("ownership_context", "recommended_source_checks"),
    ("related_facts", "service_brief", "services"),
    ("related_facts", "service_brief", "endpoints"),
    ("related_facts", "service_brief", "endpoint_consumers"),
    ("related_facts", "service_brief", "event_channels"),
    ("related_facts", "service_brief", "deploy_mappings"),
    ("related_facts", "dependencies"),
    ("related_facts", "endpoints"),
    ("related_facts", "endpoint_consumers"),
    ("related_facts", "event_channels"),
    ("related_facts", "deploy_mappings"),
    ("related_facts", "domains"),
    ("related_facts", "symbol_impact", "direct_callers"),
    ("related_facts", "symbol_impact", "direct_callees"),
    ("related_facts", "symbol_impact", "reverse_impact", "tiers"),
    ("related_facts", "symbol_impact", "reverse_impact", "edges"),
    ("related_facts", "symbol_impact", "reverse_impact", "terminal_import_consumer_leads"),
    ("related_facts", "symbol_impact", "reverse_impact", "truncated_terminal_symbols"),
    ("related_facts", "symbol_impact", "reverse_impact", "source_inspection_areas"),
)
GREP_BACKFILL_PATH_TAGS: dict[tuple[str, ...], str] = {
    **{("authz_surface", key): "candidate" for key in AUTHZ_COMPACT_LIST_KEYS},
    **{("related_facts", "authz_surface", key): "candidate" for key in AUTHZ_COMPACT_LIST_KEYS},
    (
        "runtime_architecture",
        "answer_packet",
        "investigation_brief",
        "unlinked_runtime_leads",
    ): "candidate:unlinked_source_lead",
    (
        "runtime_architecture",
        "answer_packet",
        "investigation_brief",
        "recommended_source_checks",
    ): "candidate",
    ("runtime_architecture", "answer_packet", "deploy_order_guidance"): "candidate:inference_or_guidance",
    ("ownership_context", "candidate_maintainers"): "candidate",
    ("ownership_context", "answer_packet", "unsupported_promotions"): "candidate:inference_or_guidance",
    ("ownership_context", "recommended_source_checks"): "candidate",
    (
        "related_facts",
        "symbol_impact",
        "reverse_impact",
        "terminal_import_consumer_leads",
    ): "candidate:import_only_source_lead",
    (
        "related_facts",
        "symbol_impact",
        "reverse_impact",
        "truncated_terminal_symbols",
    ): "candidate:truncated_source_inspection_lead",
    (
        "related_facts",
        "symbol_impact",
        "reverse_impact",
        "source_inspection_areas",
    ): "candidate",
}
_PLANNING_BUDGET_ADVICE = (
    "Use runtime_architecture.answer_packet.investigation_brief as the source-inspection head start, then use narrower "
    "planning_context anchors such as repo+service, domain+repo, endpoint, path, or line to retrieve omitted runtime detail."
)


def render_grep_response(
    result: JsonObject,
    *,
    max_chars: int = MCP_INLINE_HARD_MAX_CHARS,
    target_chars: int = MCP_INLINE_TARGET_CHARS,
) -> JsonObject:
    """Render a tool packet as flat source-pointer rows for MCP transport.

    Internal callers still receive the structured `call_tool` packet. The MCP
    transport default is intentionally grep-shaped so host agents read the
    result as pointers to source, not as a nested document to navigate.
    """

    rows, more, covered, must_inspect = _grep_rows(result)
    packet: JsonObject = {
        "tool": _short_text(result.get("tool"), limit=80),
        "query": _grep_query(result),
        "status": _grep_status(result),
        "answerability": _grep_answerability_status(result),
        "boundary": _grep_boundary(result),
        "covered": covered,
        "must_inspect": must_inspect,
        "shown": len(rows),
        "more": more,
        "rows": rows,
        "gaps": _grep_gaps(result),
        "next": _grep_next(result),
    }
    budget_chars = target_chars if 0 < target_chars < max_chars else max_chars
    for _ in range(8):
        previous_more = _non_bool_int(packet.get("more"))
        _refresh_grep_omission_gap(packet)
        _shrink_grep_response_to_budget(packet, max_chars=budget_chars, target_chars=target_chars)
        if _non_bool_int(packet.get("more")) == previous_more and _current_chars(packet) <= budget_chars:
            break
    if _current_chars(packet) > max_chars:
        for _ in range(4):
            previous_more = _non_bool_int(packet.get("more"))
            _shrink_grep_response_to_budget(packet, max_chars=max_chars, target_chars=target_chars)
            _refresh_grep_omission_gap(packet)
            if _non_bool_int(packet.get("more")) == previous_more and _current_chars(packet) <= max_chars:
                break
    _refresh_grep_covered_from_rows(packet)
    if _current_chars(packet) > max_chars:
        _shrink_grep_response_to_budget(packet, max_chars=max_chars, target_chars=target_chars)
    return packet


def _grep_rows(result: JsonObject) -> tuple[list[str], int, list[str], list[str]]:
    groups = _grep_row_groups(result)
    if not groups:
        groups = _grep_fallback_groups(result)
    rows, more, group_summaries = _select_balanced_grep_rows(groups, limit=GREP_RENDER_SOURCE_ROW_LIMIT)
    covered = _grep_covered_summary(group_summaries)
    must_inspect = _grep_must_inspect_summary(result, group_summaries)
    return rows, more, covered, must_inspect


def _grep_row_groups(result: JsonObject) -> list[JsonObject]:
    groups: list[JsonObject] = []
    status_group = _grep_status_group(result)
    if status_group:
        groups.append(status_group)
        if result.get("status") == "indexed_scope_no_match":
            return groups

    proven_facts = result.get("proven_facts")
    if isinstance(proven_facts, dict):
        for source in _list_value(proven_facts.get("sources")):
            if not isinstance(source, dict):
                continue
            field = source.get("field")
            if not isinstance(field, str) or not field:
                continue
            group = _grep_source_group(
                result,
                field=field,
                tag="proven",
                source_count=_non_bool_int(source.get("count")),
            )
            if group:
                groups.append(group)

    candidate_leads = result.get("candidate_leads")
    if isinstance(candidate_leads, dict):
        for source in _list_value(candidate_leads.get("sources")):
            if not isinstance(source, dict):
                continue
            field = source.get("field")
            if not isinstance(field, str) or not field:
                continue
            tag = _grep_candidate_tag(source.get("lead_kind"))
            group = _grep_source_group(
                result,
                field=field,
                tag=tag,
                source_count=_non_bool_int(source.get("count")),
            )
            if group:
                groups.append(group)

    emitted_fields = {group["field"] for group in groups if isinstance(group.get("field"), str)}
    groups.extend(_grep_supplemental_path_groups(result, emitted_fields=emitted_fields))
    return groups


def _grep_status_group(result: JsonObject) -> JsonObject:
    status = result.get("status")
    if status not in {"ambiguous", "not_found", "unsupported_by_current_kg", "indexed_scope_no_match"}:
        return {}
    answerability = _grep_answerability_status(result)
    row = (
        f"{_grep_fallback_locator(result)}  [candidate] status  "
        f"status={status} answerability={answerability} boundary=inspect_before_claiming"
    )
    return _grep_group(
        field="status",
        tag="candidate",
        rows=[row],
        total=1,
        priority=0,
        raw_rows=[{"status": status, "answerability": answerability}],
    )


def _grep_source_group(result: JsonObject, *, field: str, tag: str, source_count: int = 0) -> JsonObject:
    value = _grep_field_value(result, field)
    raw_rows = _grep_field_rows(value)
    rows: list[str] = []
    for raw_row in raw_rows[:GREP_RENDER_SOURCE_GROUP_ROW_LIMIT]:
        row = _grep_row_from_value(raw_row, tag=tag, category=field, fallback_locator=_grep_fallback_locator(result))
        if row:
            rows.append(row)
    total = source_count or len(raw_rows)
    return _grep_group(
        field=field,
        tag=tag,
        rows=rows,
        total=max(total, len(raw_rows)),
        priority=_grep_field_priority(result, field, tag),
        raw_rows=raw_rows,
    )


def _grep_field_value(result: JsonObject, field: str) -> object:
    if "." in field:
        return _nested_value(result, tuple(part for part in field.split(".") if part))
    return result.get(field)


def _grep_field_rows(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    if value not in (None, "", []):
        return [value]
    return []


def _grep_row_count(value: object) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1
    if value not in (None, "", []):
        return 1
    return 0


def _grep_fallback_groups(result: JsonObject) -> list[JsonObject]:
    groups: list[JsonObject] = []
    for field in INLINE_CORE_ROW_KEYS:
        value = result.get(field)
        raw_rows = _grep_field_rows(value)
        if not raw_rows:
            continue
        tag = GREP_FALLBACK_FIELD_TAGS.get(field, "proven")
        rows = [
            row
            for row in (
                _grep_row_from_value(
                    raw_row,
                    tag=tag,
                    category=field,
                    fallback_locator=_grep_fallback_locator(result),
                )
                for raw_row in raw_rows[:GREP_RENDER_SOURCE_GROUP_ROW_LIMIT]
            )
            if row
        ]
        groups.append(
            _grep_group(
                field=field,
                tag=tag,
                rows=rows,
                total=len(raw_rows),
                priority=_grep_field_priority(result, field, tag),
                raw_rows=raw_rows,
            )
        )
    status = _short_text(result.get("status"), limit=120)
    if status and not groups:
        groups.append(_grep_status_group(result) or _grep_group(
            field="status",
            tag="candidate",
            rows=[f"{_grep_fallback_locator(result)}  [candidate] status  {status}"],
            total=1,
            priority=0,
            raw_rows=[{"status": status}],
        ))
    return [group for group in groups if group.get("rows")]


def _grep_supplemental_path_groups(
    result: JsonObject,
    *,
    emitted_fields: set[str],
) -> list[JsonObject]:
    if result.get("status") == "indexed_scope_no_match":
        return []
    groups: list[JsonObject] = []
    for path in _BUDGET_BACKFILL_LIST_PATHS:
        field = _path_label(path)
        if field in emitted_fields:
            continue
        if "authz_surface" in field and not _should_include_authz_transport_group(result):
            continue
        if field.startswith("related_facts.authz_surface") and _nested_list(result, ("authz_surface", path[-1])):
            continue
        values = _nested_list(result, path)
        if not values:
            continue
        rows: list[str] = []
        for value in values[:GREP_RENDER_SOURCE_GROUP_ROW_LIMIT]:
            tag = _grep_tag_for_backfill_row(path, value)
            if isinstance(value, dict):
                value = _compact_backfill_row(path, value)
            row = _grep_row_from_value(value, tag=tag, category=field, fallback_locator=_grep_fallback_locator(result))
            if row:
                rows.append(row)
        groups.append(
            _grep_group(
                field=field,
                tag=_grep_tag_for_path(path),
                rows=rows,
                total=len(values),
                priority=_grep_field_priority(result, field, _grep_tag_for_path(path)),
                raw_rows=values,
            )
        )
    return [group for group in groups if group.get("rows")]


def _should_include_authz_transport_group(result: JsonObject) -> bool:
    if result.get("tool") == "review_context":
        return True
    for prefix in (("authz_surface",), ("related_facts", "authz_surface")):
        for key in AUTHZ_COMPACT_LIST_KEYS:
            if _nested_list(result, (*prefix, key)):
                return True
    return False


def _grep_group(
    *,
    field: str,
    tag: str,
    rows: list[str],
    total: int,
    priority: int,
    raw_rows: list[object],
) -> JsonObject:
    return {
        "field": field,
        "tag": tag,
        "rows": _dedupe_strings([row for row in rows if row]),
        "total": max(0, total),
        "priority": priority,
        "raw_rows": raw_rows,
    }


def _grep_field_priority(result: JsonObject, field: str, tag: str) -> int:
    lowered = field.lower()
    status = result.get("status")
    if field == "status":
        return 0
    if _grep_has_intent_token(result, {"auth", "authz", "authorization", "permission", "policy", "security"}) and any(
        token in lowered for token in ("authz", "authorization", "policy", "permission")
    ):
        if "review_leads" in lowered:
            return 5
        if "inspection_index" in lowered or "inspection_areas" in lowered:
            return 6
        if "endpoint_authorization" in lowered:
            return 7
        if "missing_or_unknown" in lowered or "in_method_checks" in lowered:
            return 8
        if "declared_policies" in lowered or "applied_policies" in lowered:
            return 9
        if "unsupported_scopes" in lowered:
            return 30
        return 8
    if any(token in lowered for token in ("dependency", "dependencies", "importer", "repo_dependencies")):
        return 9
    if any(token in lowered for token in ("deploy", "kubernetes")):
        return 10
    if "ownership_context" in lowered:
        if "proven_owners" in lowered:
            return 18
        if "candidate_maintainers" in lowered or "unsupported_promotions" in lowered:
            return 19
        return 20
    if any(token in lowered for token in ("authz", "authorization", "policy", "permission")):
        tool = result.get("tool")
        return 14 if tool in {"planning_context", "review_context"} else 75
    if lowered in {"service", "services"} or lowered.endswith(".services"):
        return 16
    if "runtime_building_blocks" in lowered or "runtime_anchors" in lowered:
        return 18
    if any(token in lowered for token in ("caller", "callee", "edges", "affected_symbols", "symbol_impact")):
        return 20
    if "changed_symbols" in lowered:
        return 22
    if any(token in lowered for token in ("domain_routing_map", "known_routes", "runtime_anchors")):
        return 24
    if "endpoint_consumer" in lowered or "consumer_links" in lowered:
        return 28
    if "event" in lowered:
        return 34
    if lowered == "endpoints" or lowered.endswith(".endpoints"):
        return 45
    if "domains" in lowered:
        return 50
    if "symbols" in lowered:
        return 55
    return 40


def _grep_intent_text(result: JsonObject) -> str:
    values: list[str] = []
    for value in (
        result.get("query"),
        result.get("service"),
        result.get("repo"),
        result.get("symbol"),
        result.get("domain"),
        result.get("endpoint"),
    ):
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            values.append(str(value))
        elif isinstance(value, dict):
            values.append(canonical_json(value))
    anchors = result.get("anchors")
    if isinstance(anchors, dict):
        for value in anchors.values():
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                values.append(str(value))
    return " ".join(values).lower()


def _grep_has_intent_token(result: JsonObject, tokens: set[str]) -> bool:
    return any(token in tokens for token in _word_tokens(_grep_intent_text(result)))


def _word_tokens(value: str) -> set[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in value.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return set(tokens)


def _select_balanced_grep_rows(groups: list[JsonObject], *, limit: int) -> tuple[list[str], int, list[JsonObject]]:
    sorted_groups = sorted(
        [group for group in groups if isinstance(group.get("rows"), list)],
        key=lambda group: (group.get("priority", 100), str(group.get("field", ""))),
    )
    selected: list[str] = []
    shown_by_group: dict[int, int] = {index: 0 for index, _ in enumerate(sorted_groups)}
    max_depth = max((len(group.get("rows", [])) for group in sorted_groups), default=0)
    for depth in range(max_depth):
        for index, group in enumerate(sorted_groups):
            if len(selected) >= limit:
                break
            rows = group.get("rows")
            if not isinstance(rows, list) or depth >= len(rows):
                continue
            row = rows[depth]
            if isinstance(row, str) and row and row not in selected:
                selected.append(row)
                shown_by_group[index] += 1
        if len(selected) >= limit:
            break
    summaries: list[JsonObject] = []
    more = 0
    for index, group in enumerate(sorted_groups):
        rows = group.get("rows")
        total = _non_bool_int(group.get("total"))
        shown = shown_by_group.get(index, 0)
        available = len(rows) if isinstance(rows, list) else 0
        group_more = max(0, total - shown)
        if total == 0:
            group_more = max(0, available - shown)
        more += group_more
        summaries.append(
            {
                "field": group.get("field"),
                "tag": group.get("tag"),
                "shown": shown,
                "available": available,
                "total": total or available,
                "omitted": group_more,
                "priority": group.get("priority", 100),
                "raw_rows": group.get("raw_rows", []),
            }
        )
    return _dedupe_strings(selected), more, summaries


def _grep_tag_for_path(path: tuple[str, ...]) -> str:
    return GREP_BACKFILL_PATH_TAGS.get(path, "proven")


def _grep_tag_for_backfill_row(path: tuple[str, ...], row: object) -> str:
    if path == ("runtime_architecture", "answer_packet", "domain_routing_map") and isinstance(row, dict):
        if row.get("status") == "unlinked_domain_reference":
            return "candidate:unlinked_source_lead"
    return _grep_tag_for_path(path)


def _grep_row_from_value(value: object, *, tag: str, category: str, fallback_locator: str) -> str:
    if isinstance(value, dict):
        locator = _grep_locator(value) or fallback_locator
        fact = _grep_fact_text(value, category=category)
    else:
        locator = fallback_locator
        scalar_text = "" if value is None else str(value).strip()
        fact = _short_text(scalar_text, limit=220)
    if not fact:
        return ""
    return _short_text(f"{locator}  [{tag}] {category}  {fact}", limit=360)


def _grep_locator(row: JsonObject) -> str:
    refs = _first_inspection_refs(row, limit=1)
    ref = refs[0] if refs else _compact_coordinate(row)
    if not ref:
        return ""
    repo = ref.get("repo")
    path = ref.get("path")
    line = ref.get("line_start") or ref.get("line")
    if isinstance(repo, str) and repo and isinstance(path, str) and path:
        locator = f"{repo}/{path}"
    elif isinstance(path, str) and path:
        locator = path
    elif isinstance(repo, str) and repo:
        locator = repo
    else:
        for key in ("domain", "endpoint", "event_channel", "module", "qualname", "qualified_name", "name", "kind"):
            value = ref.get(key)
            if isinstance(value, str) and value:
                locator = value
                break
        else:
            return ""
    if isinstance(line, int) and not isinstance(line, bool):
        return f"{locator}:{line}"
    return locator


def _grep_fallback_locator(result: JsonObject) -> str:
    repo = result.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    anchors = result.get("anchors")
    if isinstance(anchors, dict):
        for key in ("repo", "path", "service", "domain", "endpoint", "event_channel", "symbol"):
            value = anchors.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    tool = result.get("tool")
    return f"<{tool}>" if isinstance(tool, str) and tool else "<supercontext>"


def _grep_status(result: JsonObject) -> str:
    status = result.get("status")
    return status if isinstance(status, str) and status else "unknown"


def _grep_answerability_status(result: JsonObject) -> str:
    answerability = result.get("answerability")
    if isinstance(answerability, dict):
        status = answerability.get("status")
        if isinstance(status, str) and status:
            return status
    status = result.get("status")
    if status in {"ambiguous", "not_found", "unsupported_by_current_kg", "indexed_scope_no_match"}:
        return "not_answerable"
    if status in {"partial"}:
        return "partial"
    if status in {"found"}:
        return "answerable_or_partial"
    return "unknown"


def _grep_boundary(result: JsonObject) -> str:
    status = _grep_status(result)
    if status in {"ambiguous", "not_found", "unsupported_by_current_kg", "indexed_scope_no_match"}:
        return "[candidate] rows are leads only; inspect before absence/impact claims"
    candidate_leads = result.get("candidate_leads")
    if isinstance(candidate_leads, dict) and candidate_leads.get("status") == "found":
        return "[proven] rows are KG/static pointers; [candidate] rows need source verification"
    return "[proven] rows are KG/static pointers; verify risky code/runtime claims in source"


def _grep_covered_summary(group_summaries: list[JsonObject]) -> list[str]:
    rows: list[str] = []
    for group in sorted(group_summaries, key=lambda item: (item.get("priority", 100), str(item.get("field", "")))):
        shown = _non_bool_int(group.get("shown"))
        if shown <= 0:
            continue
        total = _non_bool_int(group.get("total")) or shown
        rows.append(f"{group.get('field')}: shown {shown}/{total}")
        if len(rows) >= GREP_COVERED_SUMMARY_LIMIT:
            break
    return rows


def _grep_must_inspect_summary(result: JsonObject, group_summaries: list[JsonObject]) -> list[str]:
    if result.get("status") == "indexed_scope_no_match":
        return [
            "no first-class rows matched the supplied filters: inspect source/config or retry with a broader primary anchor"
        ]
    rows: list[str] = []
    for group in sorted(group_summaries, key=lambda item: (-_non_bool_int(item.get("omitted")), item.get("priority", 100))):
        omitted = _non_bool_int(group.get("omitted"))
        if omitted <= 0:
            continue
        refs = _grep_omitted_refs(group, limit=GREP_MUST_INSPECT_REF_LIMIT)
        if refs:
            rows.append(f"{group.get('field')}: {omitted} omitted; inspect {', '.join(refs)}")
        else:
            rows.append(f"{group.get('field')}: {omitted} omitted; narrow with repo/path/service or source search")
        if len(rows) >= GREP_MUST_INSPECT_LIMIT:
            break
    for area in _list_value(result.get("inspection_areas")):
        if len(rows) >= GREP_MUST_INSPECT_LIMIT:
            break
        if not isinstance(area, dict):
            continue
        area_name = _short_text(area.get("area") or area.get("reason") or "inspection_area", limit=80)
        refs = [_grep_locator(ref) for ref in _first_inspection_refs(area, limit=GREP_MUST_INSPECT_REF_LIMIT)]
        refs = [ref for ref in refs if ref]
        if refs:
            rows.append(f"{area_name}: inspect {', '.join(refs)}")
            continue
        terms = _first_search_terms(area, limit=2)
        if terms:
            rows.append(f"{area_name}: search {' '.join(terms)}")
    if not rows and _grep_answerability_status(result) in {"partial", "not_answerable"}:
        rows.append("user-requested categories not covered by rows: inspect source/config before final claims")
    return _dedupe_strings(rows)[:GREP_MUST_INSPECT_LIMIT]


def _grep_omitted_refs(group: JsonObject, *, limit: int) -> list[str]:
    raw_rows = group.get("raw_rows")
    shown = _non_bool_int(group.get("shown"))
    if not isinstance(raw_rows, list):
        return []
    refs: list[str] = []
    for row in raw_rows[shown:]:
        if isinstance(row, dict):
            locator = _grep_locator(row)
            if locator:
                refs.append(locator)
        if len(refs) >= limit:
            break
    return _dedupe_strings(refs)


def _grep_fact_text(row: JsonObject, *, category: str) -> str:
    deploy_text = _grep_deploy_fact_text(row, category=category)
    if deploy_text:
        return deploy_text
    dependency_text = _grep_dependency_fact_text(row, category=category)
    if dependency_text:
        return dependency_text
    authz_text = _grep_authz_fact_text(row, category=category)
    if authz_text:
        return authz_text
    ownership_text = _grep_ownership_fact_text(row, category=category)
    if ownership_text:
        return ownership_text
    compact = _inline_row(row)
    predicate = compact.get("predicate") or row.get("predicate")
    subject = _grep_entity_label(compact.get("subject") if isinstance(compact.get("subject"), dict) else row.get("subject"))
    obj = _grep_entity_label(compact.get("object") if isinstance(compact.get("object"), dict) else row.get("object"))
    if subject and obj:
        arrow = f" -{predicate}-> " if isinstance(predicate, str) and predicate else " -> "
        return _short_text(f"{subject}{arrow}{obj}", limit=220)
    for first, second in (
        ("caller_symbol", "callee_symbol"),
        ("caller", "callee"),
        ("provider", "consumer"),
        ("provider_endpoint", "matched_provider_endpoint"),
        ("service", "endpoint"),
        ("domain", "target"),
        ("deploy_target", "service"),
    ):
        left = _grep_entity_label(compact.get(first) if first in compact else row.get(first))
        right = _grep_entity_label(compact.get(second) if second in compact else row.get(second))
        if left and right:
            return _short_text(f"{left} -> {right}", limit=220)
    pieces: list[str] = []
    for key in (
        "name",
        "display_name",
        "slug",
        "status",
        "kind",
        "repo",
        "module",
        "qualname",
        "qualified_name",
        "symbol_kind",
        "method",
        "path",
        "predicate",
        "state",
        "expression",
        "domain",
        "target",
        "deploy_kind",
        "authz_status",
        "reason",
        "recommendation",
    ):
        value = compact.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            pieces.append(f"{key}={value}")
        elif isinstance(value, dict):
            label = _grep_entity_label(value)
            if label:
                pieces.append(f"{key}={label}")
    if not pieces:
        for key, value in compact.items():
            if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                pieces.append(f"{key}={value}")
            if len(pieces) >= 6:
                break
    if not pieces:
        return _short_text(canonical_json(compact or row), limit=220)
    return _short_text(" ".join(pieces[:8]), limit=220)


def _grep_ownership_fact_text(row: JsonObject, *, category: str) -> str:
    if "ownership_context" not in category.lower():
        return ""
    pieces: list[str] = []
    owners = row.get("owners")
    if isinstance(owners, list):
        owner_text = ",".join(str(owner).strip() for owner in owners if str(owner).strip())
        if owner_text:
            pieces.append(f"owners={owner_text}")
    candidate = _first_text(row.get("candidate"))
    if candidate:
        pieces.append(f"candidate={candidate}")
    candidate_kind = _first_text(row.get("candidate_kind"))
    if candidate_kind:
        pieces.append(f"candidate_kind={candidate_kind}")
    candidate_kinds = row.get("candidate_kinds")
    if isinstance(candidate_kinds, list):
        kind_text = ",".join(str(kind).strip() for kind in candidate_kinds if str(kind).strip())
        if kind_text:
            pieces.append(f"candidate_kinds={kind_text}")
    owner_kind = _first_text(row.get("owner_kind"))
    if owner_kind:
        pieces.append(f"owner_kind={owner_kind}")
    owner_scope = _first_text(row.get("owner_scope"))
    if owner_scope:
        pieces.append(f"owner_scope={owner_scope}")
    source_kind = _first_text(row.get("source_kind"))
    if source_kind:
        pieces.append(f"source_kind={source_kind}")
    promotion_allowed = row.get("promotion_allowed")
    if isinstance(promotion_allowed, bool):
        pieces.append(f"promotion_allowed={str(promotion_allowed).lower()}")
    blocked_reason = _first_text(row.get("promotion_blocked_reason"), row.get("reason"))
    if blocked_reason:
        pieces.append(f"reason={blocked_reason}")
    guidance = _first_text(row.get("final_answer_guidance"))
    if guidance:
        pieces.append(f"guidance={guidance}")
    return _short_text(" ".join(pieces), limit=220)


def _grep_deploy_fact_text(row: JsonObject, *, category: str) -> str:
    lowered = category.lower()
    predicate = row.get("predicate")
    qualifier = row.get("qualifier") if isinstance(row.get("qualifier"), dict) else {}
    has_deploy_qualifier = bool(
        qualifier
        and (
            qualifier.get("kubernetes_kind")
            or qualifier.get("target_type") in {"kubernetes_deployment", "wsgi", "zappa_lambda", "cloudfront_distribution"}
            or qualifier.get("source_kind") in {"kubernetes_manifest", "runtime_linker", "zappa_settings", "apache_vhost"}
            or qualifier.get("workload")
        )
    )
    if "deploy" not in lowered and predicate != "DEPLOYS_VIA_CONFIG" and not has_deploy_qualifier:
        return ""
    subject = _grep_entity_label(row.get("subject")) or _grep_entity_label(row.get("service"))
    target = _grep_entity_label(row.get("object")) or _grep_entity_label(row.get("deploy_target"))
    kind = _first_text(
        qualifier.get("kubernetes_kind"),
        qualifier.get("target_type"),
        row.get("deploy_kind"),
        row.get("kind"),
    )
    workload = _first_text(qualifier.get("workload"), row.get("name"), target)
    namespace = _first_text(qualifier.get("namespace"))
    source_kind = _first_text(qualifier.get("source_kind"), row.get("route_source_kind"))
    path = _first_text(qualifier.get("path"), row.get("path"))
    images = qualifier.get("images")
    image = ""
    if isinstance(images, list) and images:
        image = _short_text(images[0], limit=80)
    pieces = []
    if subject:
        pieces.append(f"service={subject}")
    if kind:
        pieces.append(f"kind={kind}")
    if workload:
        pieces.append(f"workload={workload}")
    if namespace:
        pieces.append(f"namespace={namespace}")
    if source_kind:
        pieces.append(f"source_kind={source_kind}")
    if path:
        pieces.append(f"path={path}")
    if image:
        pieces.append(f"image={image}")
    if not pieces and target:
        pieces.append(f"target={target}")
    return _short_text(" ".join(pieces), limit=220)


def _grep_dependency_fact_text(row: JsonObject, *, category: str) -> str:
    lowered = category.lower()
    predicate = row.get("predicate")
    if not any(token in lowered for token in ("dependency", "dependencies", "importer", "imports", "resolves")) and predicate not in {
        "RESOLVES_TO_SERVICE",
        "RESOLVES_TO_REPO",
        "IMPORTS",
    }:
        return ""
    source_ref = _first_evidence_source_ref(row)
    consumer_repo = _first_text(source_ref.get("consumer_repo") if source_ref else None, row.get("consumer_repo"))
    provider_repo = _first_text(source_ref.get("provider_repo") if source_ref else None, row.get("provider_repo"))
    provider_package = _first_text(source_ref.get("provider_package_name") if source_ref else None, row.get("package"))
    subject = _grep_entity_label(row.get("subject"))
    obj = _grep_entity_label(row.get("object"))
    predicate_text = _first_text(predicate)
    pieces = []
    if consumer_repo:
        pieces.append(f"consumer_repo={consumer_repo}")
    elif subject:
        pieces.append(f"consumer={subject}")
    if obj:
        pieces.append(f"target={obj}")
    if provider_package:
        pieces.append(f"package={provider_package}")
    if provider_repo:
        pieces.append(f"provider_repo={provider_repo}")
    if predicate_text:
        pieces.append(f"edge={predicate_text}")
    if not pieces and subject and obj:
        pieces.append(f"{subject} -> {obj}")
    return _short_text(" ".join(pieces), limit=220)


def _grep_authz_fact_text(row: JsonObject, *, category: str) -> str:
    lowered = category.lower()
    if not any(token in lowered for token in ("authz", "authorization", "policy", "permission")):
        return ""
    endpoint = row.get("endpoint")
    handler = row.get("handler")
    policies = row.get("policies")
    checks = row.get("checks")
    pieces = []
    endpoint_text = _endpoint_label(endpoint)
    if endpoint_text:
        pieces.append(f"endpoint={endpoint_text}")
    handler_text = _grep_entity_label(handler)
    if handler_text:
        pieces.append(f"handler={handler_text}")
    for key in ("authz_status", "access_level", "policy", "reason", "lead_type"):
        value = row.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            pieces.append(f"{key}={value}")
    if isinstance(policies, list) and policies:
        policy_labels = [_grep_entity_label(item) for item in policies[:2]]
        policy_labels = [label for label in policy_labels if label]
        if policy_labels:
            pieces.append(f"policies={','.join(policy_labels)}")
    if isinstance(checks, list) and checks:
        check_labels = []
        for check in checks[:2]:
            if isinstance(check, dict):
                check_labels.append(_grep_entity_label(check.get("object")) or _first_text((check.get("qualifier") or {}).get("check")))
        check_labels = [label for label in check_labels if label]
        if check_labels:
            pieces.append(f"checks={','.join(check_labels)}")
    return _short_text(" ".join(pieces), limit=220)


def _first_evidence_source_ref(row: JsonObject) -> JsonObject:
    evidence = row.get("evidence")
    if not isinstance(evidence, list):
        return {}
    for item in evidence:
        if isinstance(item, dict):
            source_ref = item.get("source_ref")
            if isinstance(source_ref, dict):
                return source_ref
    return {}


def _endpoint_label(value: object) -> str:
    if isinstance(value, dict):
        method = _first_text(value.get("method"))
        path = _first_text(value.get("path"), value.get("name"))
        if method and path:
            return f"{method} {path}"
        return path or method or _grep_entity_label(value)
    return _grep_entity_label(value)


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, bool)) and value not in ("", None):
            return str(value)
    return ""


def _grep_entity_label(value: object) -> str:
    if isinstance(value, dict):
        for key in ("qualified_name", "qualname", "display_name", "name", "slug", "path", "domain", "target", "repo", "kind"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        identity = value.get("identity")
        if isinstance(identity, dict):
            return _grep_entity_label(identity)
    elif isinstance(value, (str, int, float, bool)) and value not in ("", None):
        return str(value)
    return ""


def _grep_candidate_tag(lead_kind: object) -> str:
    if isinstance(lead_kind, str) and lead_kind in GREP_ROW_CANDIDATE_KINDS:
        return f"candidate:{lead_kind}"
    return "candidate"


def _grep_gaps(result: JsonObject) -> str:
    clauses: list[str] = []
    candidate_leads = result.get("candidate_leads")
    if (
        result.get("status") != "indexed_scope_no_match"
        and isinstance(candidate_leads, dict)
        and candidate_leads.get("status") == "found"
    ):
        for source in _list_value(candidate_leads.get("sources")):
            if not isinstance(source, dict):
                continue
            field = source.get("field")
            if isinstance(field, str) and field:
                clauses.append(f"{field} requires source verification")
    for gap in _list_value(result.get("coverage_gaps")):
        if isinstance(gap, dict):
            clauses.append(_grep_gap_clause(gap))
        else:
            clauses.append(_short_text(gap, limit=160))
    answerability = result.get("answerability")
    if isinstance(answerability, dict):
        for family in _list_value(answerability.get("missing_fact_families")):
            clauses.append(f"missing {family}")
        for item in _list_value(answerability.get("cannot_prove")):
            clauses.append(f"cannot prove {_short_text(item, limit=120)}")
    if result.get("status") in {"not_found", "unsupported_by_current_kg", "ambiguous"}:
        clauses.append(f"status={result.get('status')}")
    clauses = _dedupe_strings([clause for clause in clauses if clause])
    if not clauses:
        return "none"
    suffix = f"; +{len(clauses) - 3} more" if len(clauses) > 3 else ""
    return _short_text("; ".join(clauses[:3]) + suffix, limit=420)


def _grep_gap_clause(gap: JsonObject) -> str:
    trigger = gap.get("trigger")
    if isinstance(trigger, str) and trigger:
        prefix = trigger
    else:
        prefix = "gap"
    for key in ("fact_family", "detail", "reason", "area"):
        value = gap.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            return _short_text(f"{prefix}: {value}", limit=160)
        if isinstance(value, dict) and value:
            return _short_text(f"{prefix}: {canonical_json(value)}", limit=160)
    return _short_text(prefix, limit=160)


def _grep_next(result: JsonObject) -> str:
    calls = _inline_next_mcp_calls(result, limit=1)
    if calls and _grep_next_call_is_safe(result, calls[0]):
        return _grep_call_text(calls[0])
    current_tool = result.get("tool")
    symbol_anchor = _symbol_anchor_from_result(result)
    if current_tool in {"find_callers", "find_callees", "blast_radius", "reverse_impact"} and symbol_anchor:
        refs = _first_inspection_refs(result, limit=1)
        if refs:
            path = refs[0].get("path")
            line = refs[0].get("line_start") or refs[0].get("line")
            if isinstance(path, str) and path:
                arguments: JsonObject = {"symbol": symbol_anchor, "path": path, "limit": 25}
                if isinstance(line, int) and not isinstance(line, bool):
                    arguments["line"] = line
                return _grep_call_text({"tool": current_tool, "arguments": arguments})
    if (
        current_tool == "planning_context"
        and result.get("status") == "ambiguous"
        and not _grep_has_intent_token(result, {"auth", "authz", "authorization", "permission", "policy", "security"})
    ):
        return "inspect must_inspect rows; rerun with explicit repo/service/domain/path after source confirms anchor"
    if current_tool == "planning_context" and result.get("status") == "indexed_scope_no_match":
        for action in _string_list(result.get("next_actions"), limit=2):
            return action
        return "inspect source/config or retry planning_context with a broader primary anchor"
    for area in _list_value(result.get("inspection_areas")):
        if not isinstance(area, dict):
            continue
        refs = _first_inspection_refs(area, limit=1)
        if refs:
            return f"inspect {_grep_locator(refs[0]) or canonical_json(refs[0])}"
        terms = _first_search_terms(area, limit=2)
        if terms:
            return f"source search: {' '.join(terms)}"
    terms = _first_search_terms(result, limit=2)
    if terms:
        return f"source search: {' '.join(terms)}"
    for action in _string_list(result.get("next_actions"), limit=1):
        return action
    if result.get("status") in {"ambiguous", "not_found", "unsupported_by_current_kg", "indexed_scope_no_match"}:
        return "inspect must_inspect rows or rerun with explicit repo/path/line/domain/endpoint anchor"
    return "inspect source for user-requested categories not covered by rows"


def _grep_next_call_is_safe(result: JsonObject, call: JsonObject) -> bool:
    status = result.get("status")
    if status not in {"ambiguous", "not_found", "unsupported_by_current_kg", "indexed_scope_no_match"}:
        return True
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return False
    tool = call.get("tool")
    if tool in {"find_callers", "find_callees", "reverse_impact", "blast_radius"}:
        return any(key in arguments for key in ("path", "line"))
    # For broad planning ambiguity, a service-only retry often over-anchors on the
    # first candidate. Require a stronger coordinate or let source inspection lead.
    return any(key in arguments for key in ("repo", "path", "line", "domain", "endpoint", "event_channel"))


def _grep_call_text(call: JsonObject) -> str:
    tool = call.get("tool")
    arguments = call.get("arguments")
    if not isinstance(tool, str) or not tool:
        return _short_text(call, limit=240)
    if not isinstance(arguments, dict):
        return tool
    parts = []
    for key in sorted(arguments):
        value = arguments[key]
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            parts.append(f"{key}={value!r}")
    return _short_text(f"{tool}({', '.join(parts)})", limit=260)


def _grep_query(result: JsonObject) -> str:
    parts: list[str] = []
    for key in ("query", "symbol", "repo", "service", "domain", "channel", "event_channel", "endpoint", "path"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}={value.strip()}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{key}={value}")
    anchors = result.get("anchors")
    if isinstance(anchors, dict):
        for key in ("repo", "service", "symbol", "domain", "endpoint", "event_channel", "path"):
            value = anchors.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(f"{key}={value.strip()}")
    status = result.get("status")
    if isinstance(status, str) and status:
        parts.append(f"status={status}")
    return _short_text(" ".join(_dedupe_strings(parts)), limit=260)


def _shrink_grep_response_to_budget(result: JsonObject, *, max_chars: int, target_chars: int) -> None:
    rows = result.get("rows")
    if not isinstance(rows, list):
        result["rows"] = []
        rows = result["rows"]
    while rows and _current_chars(result) > max_chars:
        _add_dropped_row_inspection_hint(result, rows.pop())
        result["more"] = _non_bool_int(result.get("more")) + 1
        result["shown"] = len(rows)
    if _current_chars(result) <= max_chars:
        return
    result["rows"] = [_short_text(row, limit=180) for row in rows if isinstance(row, str)]
    result["shown"] = len(result["rows"])
    while result["rows"] and _current_chars(result) > max_chars:
        _add_dropped_row_inspection_hint(result, result["rows"].pop())
        result["more"] = _non_bool_int(result.get("more")) + 1
        result["shown"] = len(result["rows"])
    if _current_chars(result) <= max_chars:
        return
    must_inspect = result.get("must_inspect")
    if isinstance(must_inspect, list):
        while must_inspect and _current_chars(result) > max_chars:
            must_inspect.pop()
    if _current_chars(result) <= max_chars:
        return
    covered = result.get("covered")
    if isinstance(covered, list):
        while covered and _current_chars(result) > max_chars:
            covered.pop()
    if _current_chars(result) <= max_chars:
        return
    result["boundary"] = _short_text(result.get("boundary"), limit=120)
    if _current_chars(result) <= max_chars:
        return
    result["gaps"] = _short_text(result.get("gaps"), limit=160)
    if _current_chars(result) <= max_chars:
        return
    result["query"] = _short_text(result.get("query"), limit=120)
    result["next"] = _short_text(result.get("next"), limit=160)
    if _current_chars(result) > max_chars:
        result["more"] = _non_bool_int(result.get("more")) + len(result["rows"])
        for row in list(result["rows"]):
            _add_dropped_row_inspection_hint(result, row)
        result["rows"] = []
        result["shown"] = 0
        result["gaps"] = _short_text(result.get("gaps"), limit=80)
        result["next"] = _short_text(result.get("next"), limit=120) or "inspect source for uncovered areas"


def _refresh_grep_covered_from_rows(result: JsonObject) -> None:
    rows = result.get("rows")
    if not isinstance(rows, list):
        result["covered"] = []
        return
    shown_by_category: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, str):
            continue
        _locator, category = _parse_grep_row_locator_category(row)
        if category:
            shown_by_category[category] = shown_by_category.get(category, 0) + 1

    total_by_category = _covered_total_by_category(result.get("covered"))
    covered = []
    for category, shown in sorted(shown_by_category.items()):
        total = max(total_by_category.get(category, shown), shown)
        covered.append(f"{category}: shown {shown}/{total}")
    result["covered"] = covered[:GREP_COVERED_SUMMARY_LIMIT]


def _covered_total_by_category(value: object) -> dict[str, int]:
    totals: dict[str, int] = {}
    if not isinstance(value, list):
        return totals
    for row in value:
        if not isinstance(row, str):
            continue
        category, separator, remainder = row.partition(": shown ")
        if not separator:
            continue
        _shown, separator, total = remainder.partition("/")
        if not separator:
            continue
        try:
            parsed_total = int(total.strip())
        except ValueError:
            continue
        if parsed_total >= 0:
            totals[category.strip()] = parsed_total
    return totals


def _add_dropped_row_inspection_hint(result: JsonObject, row: object) -> None:
    if not isinstance(row, str) or not row.strip():
        return
    locator, category = _parse_grep_row_locator_category(row)
    if not category:
        return
    if locator:
        hint = f"{category}: omitted by byte budget; inspect {locator}"
    else:
        hint = f"{category}: omitted by byte budget; inspect narrowed source/category"
    must_inspect = result.get("must_inspect")
    if not isinstance(must_inspect, list):
        must_inspect = []
        result["must_inspect"] = must_inspect
    if hint not in must_inspect:
        must_inspect.insert(0, hint)
    del must_inspect[GREP_MUST_INSPECT_LIMIT:]


def _parse_grep_row_locator_category(row: str) -> tuple[str, str]:
    marker = "  ["
    before, separator, after = row.partition(marker)
    if not separator:
        return "", ""
    _tag, separator, remainder = after.partition("] ")
    if not separator:
        return before.strip(), ""
    category = remainder.split("  ", 1)[0].strip()
    return before.strip(), category


def _refresh_grep_omission_gap(result: JsonObject) -> None:
    more = _non_bool_int(result.get("more"))
    if more <= 0:
        return
    clause = f"{more} additional rows omitted; use must_inspect refs/categories"
    gaps = result.get("gaps")
    if not isinstance(gaps, str) or not gaps.strip() or gaps == "none":
        result["gaps"] = clause
        return
    clauses = [
        part.strip()
        for part in gaps.split(";")
        if part.strip()
        and "additional rows omitted" not in part
        and "must_inspect refs/categories" not in part
    ]
    clauses.append(clause)
    result["gaps"] = _short_text("; ".join(clauses), limit=420)


def _non_bool_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def enforce_planning_context_budget(
    result: JsonObject,
    *,
    max_chars: int = PLANNING_CONTEXT_MAX_CHARS,
    preserve_planning_sections: bool = False,
) -> JsonObject:
    """Legacy planning-only compactor retained for direct regression coverage.

    The MCP server uses `render_grep_response` at the transport boundary. Keep
    this helper isolated so old planning-budget tests can guard the previous
    backfill behavior without reintroducing a second MCP production budget path.
    """

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
            return _backfill_planning_context(
                result,
                original_result,
                measured_chars=measured_chars,
                max_chars=max_chars,
                original_counts=original_counts,
            )

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
            return _backfill_planning_context(
                fallback,
                original_result,
                measured_chars=measured_chars,
                max_chars=max_chars,
                original_counts=original_counts,
                fallback=True,
            )

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


def _backfill_planning_context(
    result: JsonObject,
    original_result: JsonObject,
    *,
    measured_chars: int,
    max_chars: int,
    original_counts: dict[str, int],
    fallback: bool = False,
) -> JsonObject:
    candidate = deepcopy(result)
    backfilled_counts: dict[str, int] = {}
    for path in _BUDGET_BACKFILL_LIST_PATHS:
        candidate, added = _backfill_list_path(
            candidate,
            original_result,
            path,
            measured_chars=measured_chars,
            max_chars=max_chars,
            original_counts=original_counts,
            backfilled_counts=backfilled_counts,
            fallback=fallback,
        )
        if added:
            backfilled_counts[_path_label(path)] = backfilled_counts.get(_path_label(path), 0) + added
    return _with_budget_metadata(
        candidate,
        measured_chars=measured_chars,
        max_chars=max_chars,
        original_counts=original_counts,
        backfilled_counts=backfilled_counts,
        fallback=fallback,
    )


def _backfill_list_path(
    candidate: JsonObject,
    original_result: JsonObject,
    path: tuple[str, ...],
    *,
    measured_chars: int,
    max_chars: int,
    original_counts: dict[str, int],
    backfilled_counts: dict[str, int],
    fallback: bool,
) -> tuple[JsonObject, int]:
    source = _nested_list(original_result, path)
    target = _nested_list(candidate, path)
    if source is None or target is None or len(target) >= len(source):
        return candidate, 0
    added = 0
    for row in source[len(target) :]:
        trial_base = deepcopy(candidate)
        trial_target = _nested_list(trial_base, path)
        if trial_target is None:
            break
        trial_target.append(_compact_backfill_row(path, row))
        proposed_counts = dict(backfilled_counts)
        proposed_counts[_path_label(path)] = proposed_counts.get(_path_label(path), 0) + added + 1
        trial = _with_budget_metadata(
            trial_base,
            measured_chars=measured_chars,
            max_chars=max_chars,
            original_counts=original_counts,
            backfilled_counts=proposed_counts,
            fallback=fallback,
        )
        if _current_chars(trial) > max_chars:
            break
        candidate = trial
        added += 1
    return candidate, added


def _with_budget_metadata(
    result: JsonObject,
    *,
    measured_chars: int,
    max_chars: int,
    original_counts: dict[str, int],
    backfilled_counts: dict[str, int],
    fallback: bool,
) -> JsonObject:
    payload = deepcopy(result)
    _attach_budget_metadata(
        payload,
        measured_chars=measured_chars,
        max_chars=max_chars,
        original_counts=original_counts,
        fallback=fallback,
    )
    if backfilled_counts:
        payload["output_budget"]["backfilled_counts"] = {
            key: value for key, value in sorted(backfilled_counts.items()) if value > 0
        }
    payload["output_budget"]["remaining_chars"] = max(0, max_chars - _current_chars(payload))
    return payload


def _nested_list(payload: JsonObject, path: tuple[str, ...]) -> list[object] | None:
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, list) else None


def _path_label(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _compact_backfill_row(path: tuple[str, ...], row: object) -> object:
    if not isinstance(row, dict):
        return deepcopy(row)
    if path[:3] == ("runtime_architecture", "answer_packet", "investigation_brief"):
        if path[-1] == "recommended_source_checks":
            return _compact_source_check(row)
        return _compact_headstart_row(row)
    if path[:2] == ("runtime_architecture", "answer_packet"):
        return _minimal_runtime_row(row)
    if path[:2] == ("authz_surface", "inspection_areas") or path[:3] == (
        "related_facts",
        "authz_surface",
        "inspection_areas",
    ):
        compacted = _compact_authz_inspection_areas([row])
        return compacted[0] if compacted else {}
    if path[:1] == ("authz_surface",) or path[:2] == ("related_facts", "authz_surface"):
        return deepcopy(row)
    if path[:2] == ("related_facts", "symbol_impact"):
        if path[-1] == "tiers":
            compacted_tiers = _compact_reverse_impact_tiers([row])
            return compacted_tiers[0] if compacted_tiers else {}
        if path[-1] == "terminal_import_consumer_leads":
            compacted_leads = _compact_terminal_import_leads([row])
            return compacted_leads[0] if compacted_leads else {}
        if path[-1] == "truncated_terminal_symbols":
            compacted_symbols = _compact_truncated_terminal_symbols([row])
            return compacted_symbols[0] if compacted_symbols else {}
        if path[-1] == "source_inspection_areas":
            return deepcopy(row)
        return _compact_headstart_or_relation_row(row)
    if path[:1] == ("related_facts",):
        return _compact_headstart_or_relation_row(row)
    return deepcopy(row)


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
        "authz_surface": _compact_authz_surface(result.get("authz_surface", {})),
        "related_facts": _compact_related_facts(result.get("related_facts", {})),
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
                "related_facts": _compact_related_facts(result.get("related_facts", {})),
                "source_coordinates": result.get("source_coordinates", []),
            }
        )
    return {key: value for key, value in fallback.items() if value is not None}


def _compact_related_facts(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    compact: JsonObject = {}
    inspection_areas: list[JsonObject] = []
    service_brief, service_brief_areas = _compact_service_brief(value.get("service_brief"))
    if service_brief:
        compact["service_brief"] = service_brief
        inspection_areas.extend(service_brief_areas)
    dependency_importers, dependency_areas = _compact_dependency_importers(value.get("dependency_importers"))
    if dependency_importers:
        compact["dependency_importers"] = dependency_importers
        inspection_areas.extend(dependency_areas)
    inventory, inventory_areas = _compact_inventory(value.get("inventory"))
    if inventory:
        compact["inventory"] = inventory
        inspection_areas.extend(inventory_areas)
    service_surfaces = _compact_service_operational_surfaces(value.get("service_operational_surfaces"))
    if service_surfaces:
        compact["service_operational_surfaces"] = service_surfaces
    runtime_reference = _compact_runtime_architecture_reference(value.get("runtime_architecture"))
    if runtime_reference:
        compact["runtime_architecture"] = runtime_reference
    symbol_impact = value.get("symbol_impact")
    if isinstance(symbol_impact, dict):
        compact["symbol_impact"] = _compact_symbol_impact(symbol_impact)
    authz = value.get("authz_surface")
    if isinstance(authz, dict):
        compact["authz_surface"] = _compact_authz_surface(authz)
    for key in ("dependencies", "endpoints", "endpoint_consumers", "event_channels", "deploy_mappings", "domains"):
        rows, areas = _compact_budgeted_rows(
            value.get(key),
            limit=COMPACT_RUNTIME_HEADSTART_LIMIT,
            row_compactor=_compact_headstart_or_relation_row,
            area=f"related_facts.{key}",
            reason=f"Additional related_facts.{key} rows did not fit in the compact head-start packet.",
        )
        if rows:
            compact[key] = rows
        inspection_areas.extend(areas)
    unknown_keys = sorted(
        key
        for key in value
        if key not in RELATED_FACT_SECTION_KEYS
    )
    if unknown_keys:
        inspection_areas.append(
            {
                "area": "related_facts.omitted_unknown_sections",
                "reason": "Unknown related_facts sections were omitted from budget fallback instead of passing raw payloads through.",
                "trigger": "budget_unknown_section",
                "inspection_refs": [],
                "search_terms": unknown_keys,
                "omitted_section_count": len(unknown_keys),
            }
        )
    if inspection_areas:
        compact["inspection_areas"] = _dedupe_budget_rows(inspection_areas)[:COMPACT_RUNTIME_SOURCE_CHECK_LIMIT]
    return compact


def _compact_service_brief(value: object) -> tuple[JsonObject, list[JsonObject]]:
    if not isinstance(value, dict):
        return {}, []
    compact: JsonObject = {
        "status": value.get("status"),
        "summary": value.get("summary", {}),
    }
    inspection_areas: list[JsonObject] = []
    for key, compactor in (
        ("services", _compact_entity_ref),
        ("endpoints", _compact_headstart_or_relation_row),
        ("endpoint_consumers", _compact_headstart_or_relation_row),
        ("event_channels", _compact_headstart_or_relation_row),
        ("deploy_mappings", _compact_headstart_or_relation_row),
    ):
        rows, areas = _compact_budgeted_rows(
            value.get(key),
            limit=COMPACT_RUNTIME_HEADSTART_LIMIT,
            row_compactor=compactor,
            area=f"related_facts.service_brief.{key}",
            reason=f"Additional service brief {key} rows did not fit in the compact head-start packet.",
        )
        if rows:
            compact[key] = rows
        inspection_areas.extend(areas)
    return {key: item for key, item in compact.items() if item not in (None, [], {})}, inspection_areas


def _compact_dependency_importers(value: object) -> tuple[JsonObject, list[JsonObject]]:
    if not isinstance(value, dict):
        return {}, []
    compact: JsonObject = {
        "status": value.get("status"),
        "summary": value.get("summary", {}),
        "package_count": value.get("package_count"),
        "importer_count": value.get("importer_count"),
        "repo_counts": value.get("repo_counts", {}),
        "truncated": value.get("truncated"),
    }
    inspection_areas: list[JsonObject] = []
    for key in ("packages", "importers"):
        rows, areas = _compact_budgeted_rows(
            value.get(key),
            limit=COMPACT_RUNTIME_HEADSTART_LIMIT,
            row_compactor=_compact_headstart_or_relation_row,
            area=f"related_facts.dependency_importers.{key}",
            reason=f"Additional dependency importer {key} rows did not fit in the compact head-start packet.",
        )
        if rows:
            compact[key] = rows
        inspection_areas.extend(areas)
    return {key: item for key, item in compact.items() if item not in (None, [], {})}, inspection_areas


def _compact_inventory(value: object) -> tuple[JsonObject, list[JsonObject]]:
    if not isinstance(value, dict):
        return {}, []
    compact: JsonObject = {
        "scope": value.get("scope", {}),
        "count_contract": value.get("count_contract"),
        "summary": value.get("summary", {}),
        "runtime_counts": value.get("runtime_counts", {}),
    }
    inspection_areas: list[JsonObject] = []
    rows, areas = _compact_budgeted_rows(
        value.get("top_dependencies"),
        limit=COMPACT_RUNTIME_HEADSTART_LIMIT,
        row_compactor=_compact_headstart_or_relation_row,
        area="related_facts.inventory.top_dependencies",
        reason="Additional inventory top dependency rows did not fit in the compact head-start packet.",
    )
    if rows:
        compact["top_dependencies"] = rows
    inspection_areas.extend(areas)
    coverage = value.get("coverage")
    if isinstance(coverage, dict):
        gap_samples, gap_areas = _compact_budgeted_rows(
            coverage.get("gap_samples"),
            limit=COMPACT_RUNTIME_HEADSTART_LIMIT,
            row_compactor=_compact_headstart_or_relation_row,
            area="related_facts.inventory.coverage.gap_samples",
            reason="Additional coverage gap samples did not fit in the compact head-start packet.",
        )
        compact["coverage"] = {
            "state_counts": coverage.get("state_counts", {}),
            "predicate_counts": coverage.get("predicate_counts", {}),
            "reason_counts": coverage.get("reason_counts", {}),
            "gap_samples": gap_samples,
        }
        inspection_areas.extend(gap_areas)
    return {key: item for key, item in compact.items() if item not in (None, [], {})}, inspection_areas


def _compact_runtime_architecture_reference(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    answer_packet = value.get("answer_packet")
    if not isinstance(answer_packet, dict):
        answer_packet = {}
    compact = {
        "summary": value.get("summary", {}),
        "scope": value.get("scope", {}),
        "deploy_kind_counts": answer_packet.get("deploy_kind_counts", {}),
        "missing_fact_families": answer_packet.get("missing_fact_families", []),
        "evidence_contract": answer_packet.get("evidence_contract"),
        "read_top_level_field": "runtime_architecture.answer_packet",
        "read_for_deploy_runtime": "runtime_architecture.answer_packet.deploy_runtime_map",
        "read_for_endpoint_consumers": "runtime_architecture.answer_packet.endpoint_consumer_map",
        "read_for_deploy_order": "runtime_architecture.answer_packet.deploy_order_guidance",
    }
    return {key: item for key, item in compact.items() if item not in (None, [], {})}


def _compact_budgeted_rows(
    value: object,
    *,
    limit: int,
    row_compactor: object,
    area: str,
    reason: str,
) -> tuple[list[JsonObject], list[JsonObject]]:
    rows = [row for row in _list_value(value) if isinstance(row, dict)]
    compact_rows = [_call_row_compactor(row_compactor, row) for row in rows[:limit]]
    overflow = rows[limit:]
    inspection_area = _overflow_inspection_area(
        overflow,
        area=area,
        reason=reason,
        omitted_count=len(overflow),
    )
    return [row for row in compact_rows if row], ([inspection_area] if inspection_area else [])


def _overflow_inspection_area(
    rows: list[JsonObject],
    *,
    area: str,
    reason: str,
    omitted_count: int,
) -> JsonObject:
    if omitted_count <= 0:
        return {}
    refs: list[JsonObject] = []
    search_terms: list[str] = []
    for row in rows:
        refs.extend(_inspection_refs_from_budget_row(row))
        search_terms.extend(_search_terms_from_budget_row(row))
        if len(refs) >= COMPACT_RUNTIME_SOURCE_CHECK_LIMIT and len(search_terms) >= COMPACT_RUNTIME_SOURCE_CHECK_LIMIT:
            break
    inspection_area: JsonObject = {
        "area": area,
        "reason": reason,
        "trigger": "budget_truncated",
        "inspection_refs": _dedupe_budget_rows(refs)[:COMPACT_RUNTIME_SOURCE_CHECK_LIMIT],
        "search_terms": _dedupe_strings(search_terms)[:COMPACT_RUNTIME_SOURCE_CHECK_LIMIT],
        "omitted_row_count": omitted_count,
    }
    if len(refs) > COMPACT_RUNTIME_SOURCE_CHECK_LIMIT:
        inspection_area["inspection_refs_truncated"] = True
        inspection_area["omitted_inspection_ref_count"] = len(refs) - COMPACT_RUNTIME_SOURCE_CHECK_LIMIT
    return inspection_area


def _inspection_refs_from_budget_row(row: JsonObject) -> list[JsonObject]:
    refs: list[JsonObject] = []
    for key in ("source_coordinates", "evidence_coordinates"):
        value = row.get(key)
        if isinstance(value, list):
            refs.extend(_compact_coordinate(item) for item in value if isinstance(item, dict))
    refs.extend(_source_coordinates(row))
    direct_ref = _compact_coordinate(row)
    if direct_ref:
        refs.append(direct_ref)
    for key in ("subject", "object", "caller_symbol", "callee_symbol", "symbol", "handler", "endpoint", "domain"):
        nested = row.get(key)
        if isinstance(nested, dict):
            nested_ref = _compact_coordinate(nested)
            if nested_ref:
                refs.append(nested_ref)
    return [ref for ref in refs if ref]


def _call_row_compactor(row_compactor: object, row: JsonObject) -> JsonObject:
    if callable(row_compactor):
        compacted = row_compactor(row)
        return compacted if isinstance(compacted, dict) else {}
    return {}


def _compact_headstart_or_relation_row(row: JsonObject) -> JsonObject:
    compact = _minimal_runtime_row(row)
    if compact:
        return compact
    compact = _compact_headstart_row(row)
    if compact:
        return compact
    compact = _compact_entity_ref(row)
    if compact:
        return compact
    keys = (
        "name",
        "package",
        "import_root",
        "distribution_name",
        "importer_count",
        "state",
        "predicate",
        "reason",
        "scope_ref",
    )
    return {key: row[key] for key in keys if key in row and row[key] is not None}


def _search_terms_from_budget_row(row: JsonObject) -> list[str]:
    terms: list[str] = []
    for key in ("name", "display_name", "qualified_name", "qualname", "package", "path", "domain", "target"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            terms.append(value.strip())
        elif isinstance(value, dict):
            terms.extend(_search_terms_from_budget_row(value))
    for key in ("subject", "object", "caller_symbol", "callee_symbol", "symbol", "handler", "endpoint"):
        nested = row.get(key)
        if isinstance(nested, dict):
            terms.extend(_search_terms_from_budget_row(nested))
    return terms


def _dedupe_budget_rows(rows: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    deduped = []
    for row in rows:
        key = canonical_json(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _compact_symbol_impact(value: JsonObject) -> JsonObject:
    compact: JsonObject = {
        "status": value.get("status"),
        "symbol": _compact_symbol(value.get("symbol")),
        "direct_callers": _compact_relation_rows(value.get("direct_callers"), limit=COMPACT_RUNTIME_HEADSTART_LIMIT),
        "reverse_impact": _compact_reverse_impact(value.get("reverse_impact")),
        "import_consumer_leads": _compact_import_consumer_leads(value.get("import_consumer_leads")),
        "direct_callees": _compact_relation_rows(value.get("direct_callees"), limit=COMPACT_RUNTIME_HEADSTART_LIMIT),
    }
    if value.get("reason") is not None:
        compact["reason"] = value.get("reason")
    return {key: item for key, item in compact.items() if item not in (None, [], {})}


def _compact_reverse_impact(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    terminal_import_leads = _compact_terminal_import_leads(value.get("terminal_import_consumer_leads"))
    truncated_terminal_symbols = _compact_truncated_terminal_symbols(value.get("truncated_terminal_symbols"))
    source_inspection_areas = _list_value(value.get("source_inspection_areas"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
    summary = _compact_reverse_impact_summary(value.get("summary"))
    if terminal_import_leads:
        summary["terminal_import_lead_returned_count"] = len(terminal_import_leads)
        summary["terminal_import_lead_total_in_returned_rows"] = sum(
            _non_bool_int(row.get("import_consumer_leads", {}).get("lead_count"))
            for row in terminal_import_leads
        )
    if truncated_terminal_symbols:
        summary["truncated_terminal_symbol_returned_count"] = len(truncated_terminal_symbols)
    compact: JsonObject = {
        "status": value.get("status"),
        "mode": value.get("mode"),
        "depth": value.get("depth"),
        "summary": summary,
        "roots": [_compact_symbol(row) for row in _list_value(value.get("roots"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]],
        "tiers": _compact_reverse_impact_tiers(value.get("tiers")),
        "edges": _compact_relation_rows(value.get("edges"), limit=COMPACT_RUNTIME_HEADSTART_LIMIT),
        "constructor_bridges": _compact_constructor_bridges(value.get("constructor_bridges")),
        "terminal_import_consumer_leads": terminal_import_leads,
        "truncated_terminal_symbols": truncated_terminal_symbols,
        "source_inspection_areas": source_inspection_areas,
        "affected_symbols": _compact_reverse_impact_symbols(value.get("affected_symbols")),
        "candidate_impact_previews": _compact_candidate_impact_previews(value.get("candidate_impact_previews")),
        "ambiguity_guidance": value.get("ambiguity_guidance"),
        "disambiguation": _compact_disambiguation(value.get("disambiguation")),
        "answerability": value.get("answerability", {}),
        "contract": value.get("contract"),
    }
    return {key: item for key, item in compact.items() if item not in (None, [], {})}


def _compact_reverse_impact_summary(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    keys = (
        "root_symbol_count",
        "affected_symbol_count",
        "affected_symbol_returned_count",
        "affected_symbols_truncated",
        "edge_count",
        "constructor_bridge_count",
        "constructor_bridge_returned_count",
        "constructor_bridges_truncated",
        "terminal_import_lead_count",
        "terminal_import_lead_returned_count",
        "terminal_import_lead_total_in_returned_rows",
        "terminal_import_leads_truncated",
        "truncated_terminal_symbol_count",
        "truncated_terminal_symbol_returned_count",
        "max_depth_terminal_count",
        "truncated",
        "walk_truncated",
        "roots_unexpanded_count",
        "section_limit",
        "max_depth",
        "edge_multiplicity",
        "affected_symbol_multiplicity",
        "tier_symbol_multiplicity",
        "affected_root_projection",
    )
    return {key: value[key] for key in keys if key in value}


def _compact_reverse_impact_tiers(value: object) -> list[JsonObject]:
    tiers = []
    for tier in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(tier, dict):
            continue
        symbols = []
        for row in _list_value(tier.get("symbols"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
            if not isinstance(row, dict):
                continue
            symbols.append(
                {
                    "depth": row.get("depth"),
                    "symbol": _compact_symbol(row.get("symbol")),
                    "root_symbol": _compact_symbol(row.get("root_symbol")),
                    "root_symbols": [
                        _compact_symbol(symbol)
                        for symbol in _list_value(row.get("root_symbols"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
                    ],
                }
            )
        tiers.append(
            {
                "depth": tier.get("depth"),
                "symbol_count": tier.get("symbol_count", len(symbols)),
                "symbols": symbols,
            }
        )
    return tiers


def _compact_reverse_impact_symbols(value: object) -> list[JsonObject]:
    symbols = []
    for row in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(row, dict):
            continue
        symbols.append(
            {
                "depth": row.get("depth"),
                "symbol": _compact_symbol(row.get("symbol")),
                "root_symbol": _compact_symbol(row.get("root_symbol")),
                "root_symbols": [
                    _compact_symbol(symbol)
                    for symbol in _list_value(row.get("root_symbols"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
                ],
            }
        )
    return symbols


def _compact_constructor_bridges(value: object) -> list[JsonObject]:
    bridges = []
    for row in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(row, dict):
            continue
        bridges.append(_compact_constructor_bridge(row))
    return bridges


def _compact_constructor_bridge(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "depth": value.get("depth"),
        "bridge_kind": value.get("bridge_kind"),
        "reason": value.get("reason"),
        "from_init": _compact_symbol(value.get("from_init")),
        "to_class": _compact_symbol(value.get("to_class")),
        "root_symbol": _compact_symbol(value.get("root_symbol")),
    }


def _compact_terminal_import_leads(value: object) -> list[JsonObject]:
    rows = []
    for row in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "depth": row.get("depth"),
                "terminal_reason": row.get("terminal_reason"),
                "for_symbol": _compact_symbol(row.get("for_symbol")),
                "root_symbol": _compact_symbol(row.get("root_symbol")),
                "import_consumer_leads": _compact_import_consumer_leads(row.get("import_consumer_leads")),
            }
        )
    return rows


def _compact_truncated_terminal_symbols(value: object) -> list[JsonObject]:
    rows = []
    for row in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "depth": row.get("depth"),
                "terminal_reason": row.get("terminal_reason"),
                "symbol": _compact_symbol(row.get("symbol")),
                "root_symbol": _compact_symbol(row.get("root_symbol")),
                "inspection_hint": row.get("inspection_hint"),
            }
        )
    return rows


def _compact_import_consumer_leads(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "status": value.get("status"),
        "lead_count": value.get("lead_count"),
        "returned_count": value.get("returned_count"),
        "contract": value.get("contract"),
        "leads": [
            _compact_import_consumer_lead(row)
            for row in _list_value(value.get("leads"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
            if isinstance(row, dict)
        ],
    }


def _compact_import_consumer_lead(row: JsonObject) -> JsonObject:
    return {
        "lead_kind": row.get("lead_kind"),
        "repo_relation": row.get("repo_relation"),
        "match": row.get("match", {}),
        "importer": _compact_entity_ref(row.get("importer")),
        "imported_module": _compact_entity_ref(row.get("imported_module")),
        "imported_symbol": _compact_symbol(row.get("imported_symbol")),
        "importer_module_symbols": [
            _compact_symbol(symbol)
            for symbol in _list_value(row.get("importer_module_symbols"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
        ],
        "source_coordinates": _source_coordinates(row.get("fact")),
        "interpretation": row.get("interpretation"),
    }


def _compact_candidate_impact_previews(value: object) -> list[JsonObject]:
    previews = []
    for row in _list_value(value)[:COMPACT_RUNTIME_HEADSTART_LIMIT]:
        if not isinstance(row, dict):
            continue
        previews.append(
            {
                "symbol": _compact_symbol(row.get("symbol")),
                "impact_preview_rank": row.get("impact_preview_rank"),
                "selection_basis": row.get("selection_basis"),
                "direct_caller_count": row.get("direct_caller_count"),
                "caller_samples": _compact_relation_rows(
                    row.get("caller_samples"),
                    limit=COMPACT_AUTHZ_INSPECTION_REF_LIMIT,
                ),
                "retry_arguments": row.get("retry_arguments", {}),
            }
        )
    return previews


def _compact_disambiguation(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    retry_arguments = value.get("retry_arguments")
    if isinstance(retry_arguments, list):
        compact_retry_arguments: object = retry_arguments[:COMPACT_RUNTIME_HEADSTART_LIMIT]
    elif isinstance(retry_arguments, dict):
        compact_retry_arguments = retry_arguments
    else:
        compact_retry_arguments = []
    return {
        "status": value.get("status"),
        "reason": value.get("reason"),
        "message": value.get("message"),
        "candidate_count": value.get("candidate_count"),
        "candidates": [
            _compact_symbol(row)
            for row in _list_value(value.get("candidates"))[:COMPACT_RUNTIME_HEADSTART_LIMIT]
        ],
        "retry_arguments": compact_retry_arguments,
    }


def _compact_relation_rows(value: object, *, limit: int) -> list[JsonObject]:
    rows = []
    for row in _list_value(value)[:limit]:
        if not isinstance(row, dict):
            continue
        compact_row = {
            "predicate": row.get("predicate"),
            "depth": row.get("depth"),
            "traversal": row.get("traversal"),
            "subject": _compact_symbol(row.get("subject")),
            "object": _compact_symbol(row.get("object")),
            "caller_symbol": _compact_symbol(row.get("caller_symbol")),
            "callee_symbol": _compact_symbol(row.get("callee_symbol")),
            "source_coordinates": _source_coordinates(row),
        }
        bridge = _compact_constructor_bridge(row.get("via_constructor_bridge"))
        if bridge:
            compact_row["via_constructor_bridge"] = bridge
        rows.append(compact_row)
    return rows


def _compact_symbol(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    keys = (
        "symbol_id",
        "display_name",
        "qualified_name",
        "repo",
        "module",
        "qualname",
        "symbol_kind",
        "path",
        "line",
        "end_line",
        "kind",
        "name",
    )
    return {key: value[key] for key in keys if key in value and value[key] is not None}


def _compact_entity_ref(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    keys = ("entity_id", "display_name", "kind", "repo", "module", "path", "name")
    return {key: value[key] for key in keys if key in value and value[key] is not None}


def _source_coordinates(value: object) -> list[JsonObject]:
    if not isinstance(value, dict):
        return []
    coordinates = []
    for evidence in _list_value(value.get("evidence")):
        if not isinstance(evidence, dict):
            continue
        bytes_ref = evidence.get("bytes_ref")
        if not isinstance(bytes_ref, dict):
            continue
        coordinates.append(_compact_coordinate(bytes_ref))
        if len(coordinates) >= COMPACT_AUTHZ_INSPECTION_REF_LIMIT:
            break
    return [row for row in coordinates if row]


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


def _compact_authz_surface(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    if not value:
        return {}
    compact = {
        "status": value.get("status"),
        "scope": value.get("scope", {}),
        "summary": value.get("summary", {}),
        "answerability": value.get("answerability", {}),
        "assembly_contract": value.get("assembly_contract"),
    }
    for key in AUTHZ_COMPACT_LIST_KEYS:
        rows = _list_value(value.get(key))
        if key == "inspection_areas":
            compact[key] = _compact_authz_inspection_areas(rows[:COMPACT_RUNTIME_HEADSTART_LIMIT])
        elif key == "inspection_index":
            compact[key] = rows[:COMPACT_RUNTIME_SOURCE_CHECK_LIMIT]
        else:
            compact[key] = rows[:COMPACT_RUNTIME_HEADSTART_LIMIT]
    return compact


def _compact_authz_inspection_areas(rows: list[object]) -> list[JsonObject]:
    compact = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        area = dict(row)
        refs = _list_value(area.get("inspection_refs"))
        if refs:
            area["inspection_refs"] = refs[:COMPACT_AUTHZ_INSPECTION_REF_LIMIT]
            omitted = len(refs) - len(area["inspection_refs"])
            if omitted > 0:
                existing_omitted = area.get("omitted_inspection_ref_count")
                if isinstance(existing_omitted, bool) or not isinstance(existing_omitted, int):
                    existing_omitted = 0
                area["omitted_inspection_ref_count"] = existing_omitted + omitted
                area["inspection_refs_truncated"] = True
        compact.append(area)
    return compact


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
    keys = ("reason", "anchor", "repo", "path", "line", "line_start", "line_end", "module", "qualname", "name")
    compact = {key: row[key] for key in keys if key in row}
    if "line_start" not in compact and isinstance(row.get("line"), int) and not isinstance(row.get("line"), bool):
        compact["line_start"] = row["line"]
    return compact


def _compact_coordinate(row: JsonObject) -> JsonObject:
    keys = (
        "repo",
        "path",
        "line",
        "line_start",
        "line_end",
        "end_line",
        "module",
        "qualname",
        "qualified_name",
        "name",
        "symbol_kind",
        "kind",
        "predicate",
        "endpoint",
        "domain",
        "event_channel",
    )
    compact = {key: row[key] for key in keys if key in row and row[key] is not None}
    if "line_start" not in compact and isinstance(row.get("line"), int) and not isinstance(row.get("line"), bool):
        compact["line_start"] = row["line"]
    if "line_end" not in compact and isinstance(row.get("end_line"), int) and not isinstance(row.get("end_line"), bool):
        compact["line_end"] = row["end_line"]
    return compact


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
        "authz_surface": _compact_authz_surface(result.get("authz_surface", {})),
        "related_facts": _compact_related_facts(result.get("related_facts", {})),
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


def _inline_row(row: JsonObject) -> JsonObject:
    keys = (
        "status",
        "area",
        "trigger",
        "reason",
        "section",
        "surface",
        "kind",
        "name",
        "display_name",
        "repo",
        "module",
        "qualname",
        "qualified_name",
        "symbol_kind",
        "path",
        "line",
        "line_start",
        "line_end",
        "method",
        "predicate",
        "state",
        "expression",
        "depth",
        "authz_status",
        "public_policy_present",
        "methods",
        "domain",
        "target",
        "deploy_details",
        "deploy_kind",
        "deploy_kinds",
        "runtime_categories",
        "counts",
        "route_source_kind",
        "match_basis",
        "recommendation",
        "basis",
        "omitted_row_count",
        "missing_fact_families",
    )
    compact: JsonObject = {key: row[key] for key in keys if key in row and row[key] is not None}
    for key in (
        "service",
        "source",
        "subject",
        "object",
        "caller_symbol",
        "callee_symbol",
        "symbol",
        "handler",
        "endpoint",
        "provider",
        "provider_endpoint",
        "matched_provider_endpoint",
        "consumer",
        "deploy_target",
    ):
        nested = row.get(key)
        if isinstance(nested, dict):
            identity = _inline_entity_identity(nested)
            if identity:
                compact[key] = identity
        elif isinstance(nested, (str, int, float, bool)) and nested is not None:
            compact[key] = nested
    for key in ("services", "domains", "consumers", "policies", "checks"):
        values = row.get(key)
        if isinstance(values, list):
            compact[key] = [
                _inline_entity_identity(item) if isinstance(item, dict) else item
                for item in values[:2]
            ]
    refs = _first_inspection_refs(row, limit=COMPACT_AUTHZ_INSPECTION_REF_LIMIT)
    if refs:
        compact["evidence_refs"] = refs
    terms = _first_search_terms(row, limit=4)
    if terms:
        compact["search_terms"] = terms
    return _drop_empty(compact)


def _inline_entity_identity(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    identity = value.get("identity")
    if isinstance(identity, dict):
        merged = {**identity, **value}
    else:
        merged = value
    keys = (
        "entity_id",
        "kind",
        "name",
        "display_name",
        "slug",
        "repo",
        "module",
        "qualname",
        "qualified_name",
        "symbol_kind",
        "path",
        "line",
        "line_start",
        "line_end",
        "method",
        "methods",
        "protocol",
        "host",
        "target",
        "type",
        "access_level",
        "policy",
    )
    compact = {key: merged[key] for key in keys if key in merged and merged[key] is not None}
    properties = value.get("properties")
    if isinstance(properties, dict):
        for key in ("repo", "path", "line", "end_line"):
            if key in properties and key not in compact and properties[key] is not None:
                compact[key] = properties[key]
    return compact


def _first_inspection_refs(value: object, *, limit: int) -> list[JsonObject]:
    refs: list[JsonObject] = []
    for row in _iter_json_rows(value):
        for ref_key in ("source_coordinates", "evidence_coordinates", "inspection_refs"):
            ref_value = row.get(ref_key)
            if isinstance(ref_value, list):
                refs.extend(_compact_coordinate(item) for item in ref_value if isinstance(item, dict))
        refs.extend(_source_coordinates(row))
        direct = _compact_coordinate(row)
        if direct:
            refs.append(direct)
        if len(refs) >= limit:
            break
    return _dedupe_budget_rows([ref for ref in refs if ref])[:limit]


def _first_search_terms(value: object, *, limit: int) -> list[str]:
    terms: list[str] = []
    for row in _iter_json_rows(value):
        terms.extend(_search_terms_from_budget_row(row))
        if len(terms) >= limit:
            break
    return _dedupe_strings([term for term in terms if term])[:limit]


def _iter_json_rows(value: object) -> list[JsonObject]:
    rows: list[JsonObject] = []
    if isinstance(value, dict):
        rows.append(value)
        for nested in value.values():
            if isinstance(nested, dict):
                rows.extend(_iter_json_rows(nested))
            elif isinstance(nested, list):
                rows.extend(item for item in nested if isinstance(item, dict))
    elif isinstance(value, list):
        rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _inline_next_mcp_calls(result: JsonObject, *, limit: int) -> list[JsonObject]:
    calls: list[JsonObject] = []
    current_tool = result.get("tool")
    symbol_tools = {"find_callers", "find_callees", "blast_radius", "reverse_impact"}
    if current_tool == "planning_context":
        for row in _list_value(result.get("services")):
            if not isinstance(row, dict):
                continue
            service = row.get("slug") or row.get("name") or row.get("display_name")
            if isinstance(service, str) and service:
                calls.append(
                    {
                        "tool": "planning_context",
                        "arguments": {"service": service, "limit": 25},
                        "reason": "Narrow broad planning result to this service.",
                    }
                )
        for row in _list_value(result.get("domains")):
            if not isinstance(row, dict):
                continue
            domain = row.get("name") or row.get("domain")
            if isinstance(domain, str) and domain:
                calls.append(
                    {
                        "tool": "planning_context",
                        "arguments": {"domain": domain, "limit": 25},
                        "reason": "Narrow runtime/domain evidence to this domain.",
                    }
                )
    symbol_anchor = _symbol_anchor_from_result(result)
    for ref in _first_inspection_refs(result.get("inspection_areas"), limit=limit * 2):
        repo = ref.get("repo")
        path = ref.get("path")
        line = ref.get("line_start")
        if current_tool in symbol_tools and symbol_anchor and isinstance(path, str) and path:
            args: JsonObject = {"symbol": symbol_anchor, "path": path, "limit": 25}
            if isinstance(line, int) and not isinstance(line, bool):
                args["line"] = line
            calls.append(
                {
                    "tool": current_tool,
                    "arguments": args,
                    "reason": "Retry this symbol tool with source coordinates to retrieve omitted or disambiguated detail.",
                }
            )
        elif current_tool == "planning_context" and isinstance(path, str) and path:
            args = {"path": path, "limit": 25}
            if isinstance(repo, str) and repo:
                args["repo"] = repo
            if isinstance(line, int) and not isinstance(line, bool):
                args["line"] = line
            calls.append(
                {
                    "tool": "planning_context",
                    "arguments": args,
                    "reason": "Retrieve omitted planning detail around this source ref.",
                }
            )
    return _dedupe_budget_rows(calls)[:limit]


def _symbol_anchor_from_result(result: JsonObject) -> str | None:
    symbol = result.get("symbol")
    if isinstance(symbol, str) and symbol.strip():
        return symbol.strip()
    if isinstance(symbol, dict):
        for key in ("qualified_name", "name", "display_name"):
            value = symbol.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    target = result.get("target")
    if isinstance(target, dict):
        resolved = target.get("resolved_symbol")
        if isinstance(resolved, dict):
            for key in ("qualified_name", "qualname", "name", "display_name"):
                value = resolved.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        value = target.get("query")
        if isinstance(value, str) and value.strip():
            return value.strip()
    query = result.get("query")
    if isinstance(query, str) and query.strip():
        return query.strip()
    return None


def _nested_value(payload: JsonObject, path: tuple[str, ...]) -> object:
    current: object = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _string_list(value: object, *, limit: int) -> list[str]:
    rows = _list_value(value)
    if not rows and isinstance(value, str):
        rows = [value]
    return [_short_text(row) for row in rows[:limit] if _short_text(row)]


def _short_text(value: object, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _drop_empty(value: JsonObject) -> JsonObject:
    return {key: item for key, item in value.items() if item not in (None, [], {})}
