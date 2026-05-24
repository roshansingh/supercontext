from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from source.kg.core.display import display_entity
from source.kg.core.models import JsonObject
from source.kg.query.snapshot import KgSnapshot


TOOL_NAMES = (
    "planning_context",
    "review_context",
    "search_services",
    "get_service_brief",
    "find_callers",
    "find_callees",
    "get_event_consumers",
    "get_event_producers",
    "blast_radius",
    "deploy_blockers_for",
)


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
    endpoints = [row for row in related if row.get("predicate") in {"EXPOSES_ENDPOINT", "CALLS_ENDPOINT", "DOCUMENTS_ENDPOINT"}]
    events = [row for row in related if row.get("predicate") in {"REFERENCES_EVENT_CHANNEL", "CONSUMES_EVENT", "PRODUCES_EVENT"}]
    deploy_mappings = [row for row in related if row.get("predicate") == "ROUTES_DOMAIN_TO_DEPLOY"]
    return {
        "status": "found",
        "service": _service_row(kg, service),
        "summary": {
            "endpoint_fact_count": len(endpoints),
            "event_fact_count": len(events),
            "deploy_mapping_count": len(deploy_mappings),
        },
        "endpoints": endpoints[:limit],
        "event_channels": events[:limit],
        "deploy_mappings": deploy_mappings[:limit],
    }


def _find_callers(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return kg.find_callers(
        _required_string(arguments, "symbol"),
        limit=_limit(arguments),
        path=_optional_string(arguments, "path"),
        line=_optional_int(arguments, "line"),
        include_all=_optional_bool(arguments, "include_all", default=False),
    )


def _find_callees(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return kg.find_callees(
        _required_string(arguments, "symbol"),
        limit=_limit(arguments),
        path=_optional_string(arguments, "path"),
        line=_optional_int(arguments, "line"),
        include_all=_optional_bool(arguments, "include_all", default=False),
    )


def _blast_radius(kg: KgSnapshot, arguments: JsonObject) -> JsonObject:
    return kg.blast_radius(
        _required_string(arguments, "symbol"),
        depth=_bounded_int(arguments.get("depth", 1), field="depth", minimum=1, maximum=6),
        limit=_limit(arguments),
        path=_optional_string(arguments, "path"),
        line=_optional_int(arguments, "line"),
        include_all=_optional_bool(arguments, "include_all", default=False),
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
    return {
        "status": "found" if rows else "not_found",
        "channel": channel,
        "event_fact_count": len(rows),
        "returned_count": len(returned),
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


def _unsupported_by_current_kg(tool: str, reason: str) -> JsonObject:
    return {
        "status": "unsupported_by_current_kg",
        "reason": reason,
        "missing_contract": tool,
        "coverage_warnings": [],
        "unsupported_scopes": [],
        "next_actions": [],
    }


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
        "symbol": _string_schema("Symbol name or qualified name."),
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
    event_channels: list[JsonObject] = []
    domains: list[JsonObject] = []
    next_actions: list[str] = []

    if anchors["service"]:
        matches = _matching_services(kg, anchors["service"])
        services = [_service_row(kg, service) for service in matches[:limit]]
        if len(matches) > 1:
            next_actions.extend(_service_refinement_actions(services))
            return _planning_context_output(
                query=query,
                anchors=anchors,
                services=services,
                symbols=symbols,
                dependencies=dependencies,
                endpoints=endpoints,
                event_channels=event_channels,
                domains=domains,
                next_actions=next_actions,
                status="ambiguous",
            )
    if anchors["symbol"]:
        resolution = kg.lookup_symbol(anchors["symbol"], limit=limit, path=anchors["path"], line=line)
        if resolution["status"] == "ambiguous":
            symbols = list(resolution.get("candidates", []))[:limit]
            next_actions.extend(_symbol_refinement_actions(symbols))
            return _planning_context_output(
                query=query,
                anchors=anchors,
                services=services,
                symbols=symbols,
                dependencies=dependencies,
                endpoints=endpoints,
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
        endpoints = _planning_context_collect_rows(_planning_context_endpoint_matches(kg, anchors["endpoint"]), limit=limit)
    if anchors["event_channel"]:
        event_channels = _planning_context_collect_rows(_planning_context_event_matches(kg, anchors["event_channel"]), limit=limit)
    if anchors["domain"]:
        domains = _planning_context_collect_rows(_planning_context_domain_matches(kg, anchors["domain"]), limit=limit)
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
            query=query,
            anchors=anchors,
            services=services,
            symbols=symbols,
            dependencies=dependencies,
            endpoints=endpoints,
            event_channels=event_channels,
            domains=domains,
            next_actions=next_actions,
            status="ambiguous",
        )

    base_category = _planning_context_base_category(anchors)
    if base_category == "services":
        services = _planning_context_filter_rows("services", services, anchors, line=line)[:limit]
        symbols = []
        dependencies = []
        endpoints = []
        event_channels = []
        domains = []
    elif base_category == "symbols":
        symbols = _planning_context_filter_rows("symbols", symbols, anchors, line=line)[:limit]
        services = []
        dependencies = []
        endpoints = []
        event_channels = []
        domains = []
    elif base_category == "dependencies":
        dependencies = _planning_context_filter_rows("dependencies", dependencies, anchors, line=line)[:limit]
        services = []
        symbols = []
        endpoints = []
        event_channels = []
        domains = []
    elif base_category == "endpoints":
        endpoints = _planning_context_filter_rows("endpoints", endpoints, anchors, line=line)[:limit]
        services = []
        symbols = []
        dependencies = []
        event_channels = []
        domains = []
    elif base_category == "event_channels":
        event_channels = _planning_context_filter_rows("event_channels", event_channels, anchors, line=line)[:limit]
        services = []
        symbols = []
        dependencies = []
        endpoints = []
        domains = []
    elif base_category == "domains":
        domains = _planning_context_filter_rows("domains", domains, anchors, line=line)[:limit]
        services = []
        symbols = []
        dependencies = []
        endpoints = []
        event_channels = []

    status = "found" if any((services, symbols, dependencies, endpoints, event_channels, domains)) else "not_found"
    if status == "not_found":
        next_actions.append(
            "No deterministic planning anchor combination overlapped after applying the supplied filters. "
            "Try a broader primary anchor or remove one narrowing field."
        )
    return _planning_context_output(
        query=query,
        anchors=anchors,
        services=services,
        symbols=symbols,
        dependencies=dependencies,
        endpoints=endpoints,
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
    return {
        "status": status,
        "repo": repo,
        "changed_symbols": _planning_context_public_rows(changed_symbols),
        "direct_callers": _planning_context_public_rows(direct_callers),
        "direct_callees": _planning_context_public_rows(direct_callees),
        "repo_dependencies": _planning_context_public_rows(repo_dependencies),
        "coverage_warnings": [],
        "unsupported_scopes": unsupported_scopes,
        "evidence": _planning_context_evidence(changed_symbols, direct_callers, direct_callees, repo_dependencies),
        "next_actions": [],
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
        return _planning_context_output(
            query=query,
            anchors=query_anchors,
            services=service_rows if kind == "service" else [],
            symbols=rows if kind == "symbol" else [],
            dependencies=rows if kind in {"repo", "package"} else [],
            endpoints=rows if kind == "endpoint" else [],
            event_channels=rows if kind == "event_channel" else [],
            domains=rows if kind == "domain" else [],
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
        query=query,
        anchors=query_anchors,
        services=service_rows,
        symbols=symbol_rows[:limit],
        dependencies=dependencies,
        endpoints=endpoint_rows,
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
    if category == "services":
        return [row for row in rows if _planning_context_service_row_matches(row, anchors)]
    if category == "symbols":
        return [row for row in rows if _planning_context_symbol_row_matches(row, anchors, line=line)]
    return [row for row in rows if _planning_context_fact_row_matches(row, anchors, line=line)]


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


def _planning_context_output(
    *,
    query: str | None,
    anchors: dict[str, str | None],
    services: list[JsonObject],
    symbols: list[JsonObject],
    dependencies: list[JsonObject],
    endpoints: list[JsonObject],
    event_channels: list[JsonObject],
    domains: list[JsonObject],
    next_actions: list[str],
    status: str,
) -> JsonObject:
    bounded_services = _planning_context_public_rows(services)
    bounded_symbols = _planning_context_public_rows(symbols)
    bounded_dependencies = _planning_context_public_rows(dependencies)
    bounded_endpoints = _planning_context_public_rows(endpoints)
    bounded_event_channels = _planning_context_public_rows(event_channels)
    bounded_domains = _planning_context_public_rows(domains)
    return {
        "status": status,
        "query": query,
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
        "event_channels": bounded_event_channels,
        "domains": bounded_domains,
        "evidence": _planning_context_evidence(
            bounded_services,
            bounded_symbols,
            bounded_dependencies,
            bounded_endpoints,
            bounded_event_channels,
            bounded_domains,
        ),
        "coverage_warnings": [],
        "unsupported_scopes": [],
        "next_actions": next_actions,
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
    "planning_context": McpTool(
        name="planning_context",
        description=(
            "Primary workflow tool for repo-aware planning and broad context. "
            "Use it first when a task names or implies a service, repo, symbol, package, endpoint, event channel, domain, or path. "
            "Returns anchored KG context with evidence, ambiguity, coverage warnings, unsupported scopes, and next actions before narrower drill-down tools."
        ),
        input_schema=_object_schema(_planning_context_properties()),
        handler=_planning_context,
    ),
    "review_context": McpTool(
        name="review_context",
        description=(
            "Primary workflow tool for PR or code review when the repo and changed files or ranges are known. "
            "Use it first to compose changed symbols, direct callers, direct callees, repo dependencies, evidence, and unsupported scopes. "
            "After it anchors the review, drill into exact symbols or services with narrower tools as needed."
        ),
        input_schema=_object_schema(_review_context_properties(), required=["repo", "changed_files"]),
        handler=_review_context,
    ),
    "search_services": McpTool(
        name="search_services",
        description=(
            "Candidate service lookup only. "
            "Use it after broad planning context when you still need to choose between possible services by name, slug, namespace, repo, or stored properties. "
            "For broad planning or ambiguous service tasks, use planning_context first. "
            "Does not return endpoint topology, caller graphs, deploy blockers, or runtime health."
        ),
        input_schema=_object_schema({"query": _nullable_string_schema("Optional service search text."), "limit": _limit_schema()}),
        handler=_search_services,
    ),
    "get_service_brief": McpTool(
        name="get_service_brief",
        description=(
            "Known-service drill-down tool. "
            "Use it after the target service is known to get a compact service brief plus related endpoint, event-channel, and deploy-mapping facts. "
            "If the task is broad or ambiguous, use planning_context first. "
            "Does not traverse caller graphs, compute downstream blast radius, or infer missing runtime contracts."
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
            "Exact-symbol reverse-call drill-down tool. "
            "Use it when you know the function, method, or symbol and need static CALLS edges whose downstream target matches it. "
            "For PR or code review, use review_context first. "
            "Does not include transitive closure, runtime dispatch, cross-repo execution paths, or endpoint/service-level rollups."
        ),
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callers,
    ),
    "find_callees": McpTool(
        name="find_callees",
        description=(
            "Exact-symbol downstream-call drill-down tool. "
            "Use it when you know the function, method, or symbol and need static CALLS edges whose upstream subject matches it. "
            "For broad dependency understanding, start with planning_context or review_context. "
            "Does not return reverse callers, transitive closure, runtime-only invocations, or service and endpoint boundaries."
        ),
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callees,
    ),
    "get_event_consumers": McpTool(
        name="get_event_consumers",
        description=(
            "Known event-channel consumer drill-down tool. "
            "Use it when you know the queue, topic, ARN, or channel and want indexed static consumers attached to that channel. "
            "For broad event impact, use planning_context first. "
            "Does not infer delivery guarantees, runtime subscribers, message schemas, or cross-environment broker state."
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
            "Known event-channel producer drill-down tool. "
            "Use it when you know the queue, topic, ARN, or channel and need indexed static producers that emit onto it. "
            "For broad event impact, use planning_context first. "
            "Does not prove messages were published at runtime, identify consumers, or recover schema and deployment guarantees."
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
            "Exact-symbol static CALLS closure drill-down tool. "
            "Use only when you know the exact edit-site symbol and want downstream intra-repo callees up to `depth`. "
            "It is not full service, endpoint, deploy, schema, or runtime impact. "
            "Does not include reverse callers, cross-repo edges, service or endpoint boundaries, or runtime calls."
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
            "Explicit deploy-blocker drill-down tool for a known service when the current KG implements that contract. "
            "Use it mainly to surface supported deploy-blocker facts or a clear unsupported-scope refusal until deploy facts exist. "
            "Does not infer blockers from callers, events, config drift, or undeclared operational dependencies."
        ),
        input_schema=_object_schema({"service": _string_schema("Service name or slug."), "limit": _limit_schema()}, required=["service"]),
        handler=_deploy_blockers_for,
    ),
}
