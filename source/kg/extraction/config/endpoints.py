from __future__ import annotations

import ast
import re
from urllib.parse import urlparse

from source.kg.core.models import Coverage, Entity
from source.kg.extraction.config.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    TENANT_ID,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    normalize_endpoint_path,
)
from source.kg.extraction.config.openapi_yaml import extract_openapi_endpoints
from source.kg.extraction.python.frameworks import extract_django_routes, extract_flask_routes
from source.kg.extraction.python.frameworks.routes import EndpointRoute
from source.kg.core.repo_source import RepoSnapshot


JS_ROUTE_RE = re.compile(r"\b(?:app|router|server)\.(get|post|put|delete|patch|all|use)\(\s*['\"`]([^'\"`]+)['\"`]", re.IGNORECASE)
CLIENT_CALL_RE = re.compile(
    r"\b(?:fetch|axios\.(?:get|post|put|delete|patch)|[A-Za-z_][A-Za-z0-9_]*\.(?:get|post|put|delete|patch))\(\s*['\"`]([^'\"`]+)['\"`]",
    re.IGNORECASE,
)
JAVASCRIPT_TYPESCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
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
    saw_python = False
    saw_javascript_or_typescript = False
    saw_recognized_python_web_framework = False
    for scanned in files:
        if scanned.path.suffix == ".py":
            saw_python = True
            saw_recognized_python_web_framework = (
                _extract_python_backend_routes(repo, scanned, service_entity, build) or saw_recognized_python_web_framework
            )
        if scanned.path.suffix in JAVASCRIPT_TYPESCRIPT_SUFFIXES:
            saw_javascript_or_typescript = True
        _extract_openapi_document(repo, scanned, service_entity, build)
        if scanned.path.suffix in JAVASCRIPT_TYPESCRIPT_SUFFIXES:
            for line_number, line in enumerate(scanned.lines, start=1):
                _extract_legacy_javascript_routes(repo, scanned, line_number, line, service_entity, build)
                _extract_client_calls(repo, scanned, line_number, line, service_entity, build)
    if saw_python and not saw_recognized_python_web_framework:
        build.coverage.append(
            Coverage(
                tenant_id=TENANT_ID,
                predicate="EXPOSES_ENDPOINT",
                scope_ref={"repo": repo.name, "language": "python", "reason": "no_recognized_web_framework"},
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
    if saw_javascript_or_typescript:
        for predicate in ("EXPOSES_ENDPOINT", "CALLS_ENDPOINT"):
            build.coverage.append(
                Coverage(
                    tenant_id=TENANT_ID,
                    predicate=predicate,
                    scope_ref={
                        "repo": repo.name,
                        "language": "javascript/typescript",
                        "reason": "parser_backed_js_ts_endpoint_extraction_deferred",
                    },
                    state="partially_instrumented",
                    source_system=CONFIG_SOURCE_SYSTEM,
                )
            )


def _extract_python_backend_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
) -> bool:
    try:
        tree = ast.parse(scanned.text, filename=str(scanned.path))
    except SyntaxError as exc:
        build.coverage.append(
            Coverage(
                tenant_id=TENANT_ID,
                predicate="EXPOSES_ENDPOINT",
                scope_ref={
                    "repo": repo.name,
                    "file_path": scanned.relative_path,
                    "language": "python",
                    "reason": "python_syntax_error",
                    "message": str(exc),
                },
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
        return False
    routes: list[EndpointRoute] = []
    flask_routes, flask_recognized = extract_flask_routes(tree)
    django_routes, django_recognized = extract_django_routes(tree, scanned.path)
    routes.extend(flask_routes)
    routes.extend(django_routes)
    for route in routes:
        _add_endpoint_fact(
            repo,
            scanned,
            route.line,
            service_entity,
            build,
            "EXPOSES_ENDPOINT",
            route.method,
            route.path,
            route.source_kind,
            validate_path=False,
        )
    return flask_recognized or django_recognized


def _extract_openapi_document(repo: RepoSnapshot, scanned: ScannedFile, service_entity: Entity, build: ConfigKgBuild) -> None:
    result = extract_openapi_endpoints(scanned)
    if result.coverage_reason:
        build.coverage.append(
            Coverage(
                tenant_id=TENANT_ID,
                predicate="DOCUMENTS_ENDPOINT",
                scope_ref={"repo": repo.name, "file_path": scanned.relative_path, "reason": result.coverage_reason},
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
        return
    for endpoint in result.endpoints:
        _add_endpoint_fact(
            repo,
            scanned,
            endpoint.line,
            service_entity,
            build,
            "DOCUMENTS_ENDPOINT",
            endpoint.method,
            endpoint.path,
            endpoint.source_kind,
            validate_path=False,
        )


def _extract_legacy_javascript_routes(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    line: str,
    service_entity: Entity,
    build: ConfigKgBuild,
) -> None:
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
            "legacy_javascript_route_regex",
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
    validate_path: bool = True,
) -> None:
    normalized_path = normalize_endpoint_path(path)
    if validate_path and not _looks_like_endpoint(normalized_path):
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
