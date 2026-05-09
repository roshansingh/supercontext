from __future__ import annotations

import re
from urllib.parse import urlparse

from source.kg.extraction.config.common import (
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    normalize_endpoint_path,
)
from source.kg.models import Entity
from source.kg.repo_source import RepoSnapshot


PY_ROUTE_RE = re.compile(r"\b(?:path|re_path)\(\s*r?['\"]([^'\"]+)['\"]")
PY_DECORATOR_RE = re.compile(r"@\w+(?:\.\w+)*\.(get|post|put|delete|patch|route)\(\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
PY_ADD_URL_RULE_RE = re.compile(r"\bapp\.add_url_rule\(\s*['\"]([^'\"]+)['\"](?P<rest>.*)", re.IGNORECASE)
JS_ROUTE_RE = re.compile(r"\b(?:app|router|server)\.(get|post|put|delete|patch|all|use)\(\s*['\"`]([^'\"`]+)['\"`]", re.IGNORECASE)
OPENAPI_PATH_RE = re.compile(r"^\s{0,6}['\"]?(/[^:'\"\s]+)['\"]?\s*:\s*$")
OPENAPI_METHOD_RE = re.compile(r"^\s{2,10}(get|post|put|delete|patch|options|head)\s*:\s*$", re.IGNORECASE)
CLIENT_CALL_RE = re.compile(
    r"\b(?:fetch|axios\.(?:get|post|put|delete|patch)|[A-Za-z_][A-Za-z0-9_]*\.(?:get|post|put|delete|patch))\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)
HTTP_METHOD_BY_VERB = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
    "all": "ANY",
    "use": "ANY",
    "route": "ANY",
}


def extract_endpoints(repo: RepoSnapshot, files: list[ScannedFile], service_entity: Entity, build: ConfigKgBuild) -> None:
    for scanned in files:
        current_openapi_path: str | None = None
        for line_number, line in enumerate(scanned.lines, start=1):
            current_openapi_path = _extract_openapi_path(repo, scanned, line_number, line, service_entity, build, current_openapi_path)
            _extract_backend_routes(repo, scanned, line_number, line, service_entity, build)
            _extract_client_calls(repo, scanned, line_number, line, service_entity, build)


def _extract_backend_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
) -> None:
    for route in PY_ROUTE_RE.findall(line):
        _add_endpoint_fact(repo, scanned, line_number, service_entity, build, "EXPOSES_ENDPOINT", "ANY", route, "python_route")
    for verb, route in PY_DECORATOR_RE.findall(line):
        _add_endpoint_fact(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            "EXPOSES_ENDPOINT",
            HTTP_METHOD_BY_VERB.get(verb.lower(), "ANY"),
            route,
            "python_decorator",
        )
    add_url_rule_match = PY_ADD_URL_RULE_RE.search(line)
    if add_url_rule_match:
        _add_endpoint_fact(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            "EXPOSES_ENDPOINT",
            _method_from_methods_arg(add_url_rule_match.group("rest")),
            add_url_rule_match.group(1),
            "python_add_url_rule",
        )
    for verb, route in JS_ROUTE_RE.findall(line):
        _add_endpoint_fact(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            "EXPOSES_ENDPOINT",
            HTTP_METHOD_BY_VERB.get(verb.lower(), "ANY"),
            route,
            "javascript_route",
        )


def _extract_client_calls(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
) -> None:
    for raw_target in CLIENT_CALL_RE.findall(line):
        method = _method_from_client_call(line)
        path, host = _split_endpoint_target(raw_target)
        if not path:
            continue
        _add_endpoint_fact(repo, scanned, line_number, service_entity, build, "CALLS_ENDPOINT", method, path, "client_call", host=host)


def _extract_openapi_path(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
    current_path: str | None,
) -> str | None:
    path_match = OPENAPI_PATH_RE.match(line)
    if path_match:
        path = path_match.group(1)
        _add_endpoint_fact(repo, scanned, line_number, service_entity, build, "DOCUMENTS_ENDPOINT", "ANY", path, "openapi_path")
        return path
    method_match = OPENAPI_METHOD_RE.match(line)
    if method_match and current_path:
        _add_endpoint_fact(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            "DOCUMENTS_ENDPOINT",
            method_match.group(1).upper(),
            current_path,
            "openapi_method",
        )
    return current_path


def _add_endpoint_fact(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    service_entity: Entity,
    build: ConfigKgBuild,
    predicate: str,
    method: str,
    path: str,
    source_kind: str,
    host: str | None = None,
) -> None:
    normalized_path = normalize_endpoint_path(path)
    if not _looks_like_endpoint(normalized_path):
        return
    endpoint = endpoint_entity(repo, method, normalized_path, host=host)
    add_entity_evidence(build, repo, endpoint, scanned.path, line_number)
    add_fact(
        build,
        predicate,
        service_entity,
        endpoint,
        repo,
        scanned.path,
        line_number,
        qualifier={"source_kind": source_kind, "raw_target": path, "path": scanned.relative_path},
    )


def _method_from_client_call(line: str) -> str:
    lower = line.lower()
    for verb, method in HTTP_METHOD_BY_VERB.items():
        if f".{verb}(" in lower:
            return method
    return "ANY"


def _method_from_methods_arg(value: str) -> str:
    methods_match = re.search(r"methods\s*=\s*\[([^\]]+)\]", value)
    if not methods_match:
        return "ANY"
    methods = re.findall(r"['\"]([A-Za-z]+)['\"]", methods_match.group(1))
    return methods[0].upper() if len(methods) == 1 else "ANY"


def _split_endpoint_target(raw_target: str) -> tuple[str, str | None]:
    target = raw_target.strip()
    if target.startswith("http://") or target.startswith("https://"):
        try:
            parsed = urlparse(target)
        except ValueError:
            return "", None
        try:
            host = parsed.hostname
        except ValueError:
            host = None
        return parsed.path or "/", host
    if "}" in target:
        target = target[target.rfind("}") + 1 :]
    if "/" not in target:
        return "", None
    return target, None


def _looks_like_endpoint(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path in {"/", "/*"}:
        return True
    return any(char.isalpha() for char in path)
