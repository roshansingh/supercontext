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


def call_tool(kg: KgSnapshot, name: str, arguments: JsonObject | None = None) -> JsonObject:
    if name not in _TOOLS:
        raise ValueError(f"Unsupported MCP tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    tool = _TOOLS[name]
    _validate_declared_arguments(tool, arguments)
    result = tool.handler(kg, arguments)
    return {
        "tool": name,
        **result,
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
    related = _facts_touching_entity(kg, service_id, limit=limit)
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
    result = kg.event_channels(channel_query=channel, limit=100)
    rows = [row for row in result.get("event_channels", []) if row.get("predicate") == predicate]
    returned = rows[:limit]
    return {
        "status": "found" if rows else "not_found",
        "channel": channel,
        "event_fact_count": len(rows),
        "returned_count": len(returned),
        result_key: returned,
    }


def _unsupported_by_current_kg(tool: str, reason: str) -> JsonObject:
    return {
        "status": "unsupported_by_current_kg",
        "reason": reason,
        "missing_contract": tool,
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


def _facts_touching_entity(kg: KgSnapshot, entity_id: str, *, limit: int) -> list[JsonObject]:
    rows = []
    for fact in kg.facts:
        if fact.get("subject_id") != entity_id and fact.get("object_id") != entity_id:
            continue
        subject = kg.entities_by_id.get(fact["subject_id"])
        object_ = kg.entities_by_id.get(fact["object_id"])
        if not subject or not object_:
            continue
        rows.append(_fact_result(kg, fact, subject, object_))
        if len(rows) >= limit:
            break
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


def _limit(arguments: JsonObject) -> int:
    return _bounded_int(arguments.get("limit", 25), field="limit", minimum=1, maximum=100)


def _bounded_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"MCP tool argument {field!r} must be an integer")
    if isinstance(value, int):
        raw = value
    else:
        raise ValueError(f"MCP tool argument {field!r} must be an integer")
    return min(max(minimum, raw), maximum)


def _object_schema(properties: JsonObject, required: list[str] | None = None) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _string_schema(description: str) -> JsonObject:
    return {"type": "string", "description": description}


def _limit_schema() -> JsonObject:
    return {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}


def _symbol_properties() -> JsonObject:
    return {
        "symbol": _string_schema("Symbol name or qualified name."),
        "path": _string_schema("Optional source-file path for disambiguation."),
        "line": {"type": "integer", "minimum": 1, "description": "Optional source line for disambiguation."},
        "include_all": {"type": "boolean", "default": False},
        "limit": _limit_schema(),
    }


_TOOLS: dict[str, McpTool] = {
    "search_services": McpTool(
        name="search_services",
        description="Search indexed Service entities by name, slug, namespace, repo, or properties.",
        input_schema=_object_schema({"query": _string_schema("Optional service search text."), "limit": _limit_schema()}),
        handler=_search_services,
    ),
    "get_service_brief": McpTool(
        name="get_service_brief",
        description="Return a compact Service brief with related endpoint, event, and deploy facts.",
        input_schema=_object_schema(
            {"service": _string_schema("Service name, slug, namespace, or repo."), "limit": _limit_schema()},
            required=["service"],
        ),
        handler=_get_service_brief,
    ),
    "find_callers": McpTool(
        name="find_callers",
        description="Find symbols that call the requested symbol.",
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callers,
    ),
    "find_callees": McpTool(
        name="find_callees",
        description="Find symbols called by the requested symbol.",
        input_schema=_object_schema(_symbol_properties(), required=["symbol"]),
        handler=_find_callees,
    ),
    "get_event_consumers": McpTool(
        name="get_event_consumers",
        description="Find services/modules that consume an event channel.",
        input_schema=_object_schema(
            {"channel": _string_schema("Event channel name, queue, topic, or ARN substring."), "limit": _limit_schema()},
            required=["channel"],
        ),
        handler=_get_event_consumers,
    ),
    "get_event_producers": McpTool(
        name="get_event_producers",
        description="Find services/modules that produce an event channel.",
        input_schema=_object_schema(
            {"channel": _string_schema("Event channel name, queue, topic, or ARN substring."), "limit": _limit_schema()},
            required=["channel"],
        ),
        handler=_get_event_producers,
    ),
    "blast_radius": McpTool(
        name="blast_radius",
        description="Traverse static CALLS edges downstream from a symbol.",
        input_schema=_object_schema(
            {**_symbol_properties(), "depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 1}},
            required=["symbol"],
        ),
        handler=_blast_radius,
    ),
    "deploy_blockers_for": McpTool(
        name="deploy_blockers_for",
        description="Return deploy blockers for a service when deploy-blocker facts exist.",
        input_schema=_object_schema({"service": _string_schema("Service name or slug."), "limit": _limit_schema()}, required=["service"]),
        handler=_deploy_blockers_for,
    ),
}
