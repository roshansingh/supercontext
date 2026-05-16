from __future__ import annotations

from dataclasses import dataclass

from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.file_formats.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    event_channel_entity,
)


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "any"}


@dataclass(frozen=True)
class ServerlessRoute:
    route_kind: str
    path: str
    method: str
    handler: str | None
    line: int


def extract_serverless_yaml_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    result = serverless_routes(scanned)
    if result.coverage_reason:
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="EXPOSES_ENDPOINT",
                scope_ref={"repo": repo.name, "file_path": scanned.relative_path, "reason": result.coverage_reason},
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
        return
    for route in result.routes:
        endpoint = endpoint_entity(repo, route.method, route.path, tenant_id=resolved_tenant_id)
        add_entity_evidence(build, repo, endpoint, scanned.path, route.line)
        qualifier: JsonObject = {
            "source_kind": "serverless_route",
            "path": scanned.relative_path,
            "route_kind": route.route_kind,
        }
        if route.handler:
            qualifier["handler"] = route.handler
        add_fact(build, "EXPOSES_ENDPOINT", service_entity, endpoint, repo, scanned.path, route.line, qualifier=qualifier)
        if route.route_kind != "websocket":
            continue
        channel = event_channel_entity(
            repo,
            "websocket",
            route.path,
            tenant_id=resolved_tenant_id,
            properties={"raw_literal": route.path, "source_kind": "serverless_route", "path": scanned.relative_path},
        )
        add_entity_evidence(build, repo, channel, scanned.path, route.line)
        add_fact(build, "CONSUMES_EVENT", service_entity, channel, repo, scanned.path, route.line, qualifier=qualifier)


@dataclass(frozen=True)
class ServerlessRouteExtraction:
    routes: list[ServerlessRoute]
    coverage_reason: str | None = None


def is_serverless_yaml_filename(name: str) -> bool:
    lower_name = name.lower()
    if lower_name in {"serverless.yml", "serverless.yaml"}:
        return True
    if lower_name.startswith("serverless.") and lower_name.endswith((".yml", ".yaml")):
        return True
    if lower_name.startswith("serverless-") and lower_name.endswith((".yml", ".yaml")):
        return True
    if lower_name.endswith((".serverless.yml", ".serverless.yaml")):
        return True
    return False


def serverless_routes(scanned: ScannedFile) -> ServerlessRouteExtraction:
    if not is_serverless_yaml_filename(scanned.path.name):
        return ServerlessRouteExtraction([])
    try:
        import yaml
    except ImportError:
        return ServerlessRouteExtraction([], coverage_reason="pyyaml_unavailable")
    try:
        data = yaml.safe_load(scanned.text)
    except yaml.YAMLError:
        return ServerlessRouteExtraction([], coverage_reason="serverless_yaml_parse_error")
    if not _is_serverless_document(data):
        return ServerlessRouteExtraction([])
    routes: list[ServerlessRoute] = []
    functions = data["functions"]
    for function_config in functions.values():
        if not isinstance(function_config, dict):
            continue
        handler = function_config.get("handler")
        handler_value = handler if isinstance(handler, str) else None
        events = function_config.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            route = _route_from_event(event, handler_value, scanned)
            if route is not None:
                routes.append(route)
    return ServerlessRouteExtraction(routes)


def _is_serverless_document(data: object) -> bool:
    return isinstance(data, dict) and isinstance(data.get("functions"), dict)


def _route_from_event(event: dict[object, object], handler: str | None, scanned: ScannedFile) -> ServerlessRoute | None:
    for route_kind in ("websocket", "http", "httpApi"):
        if route_kind not in event:
            continue
        event_config = event[route_kind]
        if isinstance(event_config, str):
            return _route_from_string(route_kind, event_config, handler, scanned)
        if not isinstance(event_config, dict):
            return None
        path = _route_path(route_kind, event_config)
        if path is None:
            return None
        method = _route_method(route_kind, event_config)
        return ServerlessRoute(
            route_kind=route_kind,
            path=path,
            method=method,
            handler=handler,
            line=_route_line(route_kind, event_config, scanned, path),
        )
    return None


def _route_from_string(route_kind: str, value: str, handler: str | None, scanned: ScannedFile) -> ServerlessRoute | None:
    parts = value.split(maxsplit=1)
    if route_kind in {"http", "httpApi"} and len(parts) == 2 and parts[0].lower() in HTTP_METHODS:
        method = parts[0].upper()
        path = parts[1]
    else:
        method = "ANY"
        path = value
    return ServerlessRoute(route_kind=route_kind, path=path, method=method, handler=handler, line=_line_for_key(scanned, value))


def _route_path(route_kind: str, event_config: dict[object, object]) -> str | None:
    if route_kind == "websocket":
        route = event_config.get("route")
        return route if isinstance(route, str) and route else None
    # Some Serverless plugins use route-like keys for HTTP events; prefer the
    # documented path field and accept route only as a conservative fallback.
    route = event_config.get("path") or event_config.get("route")
    return route if isinstance(route, str) and route else None


def _route_method(route_kind: str, event_config: dict[object, object]) -> str:
    if route_kind == "websocket":
        return "ANY"
    method = event_config.get("method")
    if isinstance(method, str) and method.lower() in HTTP_METHODS:
        return method.upper()
    return "ANY"


def _route_line(route_kind: str, event_config: dict[object, object], scanned: ScannedFile, path: str) -> int:
    path_line = _line_for_key(scanned, path)
    if route_kind == "websocket":
        return path_line
    method = event_config.get("method")
    if isinstance(method, str) and method.lower() in HTTP_METHODS:
        return _line_for_key(scanned, method, start_line=path_line)
    return path_line


def _line_for_key(scanned: ScannedFile, key: str, start_line: int = 1) -> int:
    needle = str(key)
    for line_number, line in enumerate(scanned.lines[start_line - 1 :], start=start_line):
        if needle in line:
            return line_number
    return start_line
