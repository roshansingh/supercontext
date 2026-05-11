from __future__ import annotations

import ast

from source.kg.core.models import Coverage, Entity
from source.kg.extraction.config.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    normalize_endpoint_path,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.extraction.config.openapi_yaml import extract_openapi_endpoints
from source.kg.extraction.python.frameworks import extract_django_routes, extract_flask_routes
from source.kg.extraction.python.frameworks.routes import EndpointRoute
from source.kg.core.repo_source import RepoSnapshot


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


def extract_endpoints(
    repo: RepoSnapshot,
    files: list[ScannedFile],
    service_entity: Entity,
    build: ConfigKgBuild,
    *,
    tenant_id: str | None = None,
    include_openapi: bool = True,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    saw_python = False
    saw_javascript_or_typescript = False
    saw_recognized_python_web_framework = False
    for scanned in files:
        if scanned.path.suffix == ".py":
            saw_python = True
            saw_recognized_python_web_framework = (
                _extract_python_backend_routes(repo, scanned, service_entity, build, resolved_tenant_id)
                or saw_recognized_python_web_framework
            )
        if scanned.path.suffix in JAVASCRIPT_TYPESCRIPT_SUFFIXES:
            saw_javascript_or_typescript = True
        if include_openapi:
            extract_openapi_document(repo, scanned, service_entity, build, resolved_tenant_id)
    if saw_python and not saw_recognized_python_web_framework:
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="EXPOSES_ENDPOINT",
                scope_ref={"repo": repo.name, "language": "python", "reason": "no_recognized_web_framework"},
                state="uninstrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
    if saw_javascript_or_typescript:
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="EXPOSES_ENDPOINT",
                scope_ref={
                    "repo": repo.name,
                    "language": "javascript/typescript",
                    "reason": "parser_backed_js_ts_route_extraction_partial_express_only",
                },
                state="partially_instrumented",
                source_system=CONFIG_SOURCE_SYSTEM,
            )
        )
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
                predicate="CALLS_ENDPOINT",
                scope_ref={
                    "repo": repo.name,
                    "language": "javascript/typescript",
                    "reason": "parser_backed_js_ts_client_endpoint_extraction_partial_fetch_axios_only",
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
    tenant_id: str,
) -> bool:
    try:
        tree = ast.parse(scanned.text, filename=str(scanned.path))
    except SyntaxError as exc:
        build.coverage.append(
            Coverage(
                tenant_id=tenant_id,
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
            tenant_id,
            validate_path=False,
        )
    return flask_recognized or django_recognized


def extract_openapi_document(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str | None = None,
) -> None:
    resolved_tenant_id = resolve_tenant_id(tenant_id)
    result = extract_openapi_endpoints(scanned)
    if result.coverage_reason:
        build.coverage.append(
            Coverage(
                tenant_id=resolved_tenant_id,
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
            resolved_tenant_id,
            validate_path=False,
        )


def extract_typescript_express_routes(
    repo: RepoSnapshot,
    parsed_files: dict[str, object],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(parsed_file, dict):
            continue
        file_path = repo.root / str(relative_path)
        scanned = ScannedFile(path=file_path, relative_path=str(relative_path), text="", lines=())
        for row in parsed_file.get("express_routes", []):
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            if not isinstance(path, str):
                continue
            method = HTTP_METHOD_BY_VERB.get(str(row.get("method", "")).lower(), "ANY")
            line_number = int(row.get("line") or 1)
            source_kind = str(row.get("source_kind") or "express_route")
            _add_endpoint_fact(
                repo,
                scanned,
                line_number,
                service_entity,
                build,
                "EXPOSES_ENDPOINT",
                method,
                path,
                source_kind,
                tenant_id,
                validate_path=False,
            )


def extract_typescript_client_endpoint_calls(
    repo: RepoSnapshot,
    parsed_files: dict[str, object],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(parsed_file, dict):
            continue
        file_path = repo.root / str(relative_path)
        scanned = ScannedFile(path=file_path, relative_path=str(relative_path), text="", lines=())
        for row in parsed_file.get("client_endpoint_calls", []):
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            if not isinstance(path, str):
                continue
            method = str(row.get("method") or "ANY").upper()
            line_number = int(row.get("line") or 1)
            source_kind = str(row.get("source_kind") or "client_call")
            raw_target = str(row.get("raw_target") or path)
            host = row.get("host")
            _add_endpoint_fact(
                repo,
                scanned,
                line_number,
                service_entity,
                build,
                "CALLS_ENDPOINT",
                method,
                path,
                source_kind,
                tenant_id,
                host=host if isinstance(host, str) else None,
                raw_target=raw_target,
                validate_path=False,
            )


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
    tenant_id: str,
    host: str | None = None,
    raw_target: str | None = None,
    validate_path: bool = True,
) -> None:
    normalized_path = normalize_endpoint_path(path)
    if validate_path and not _looks_like_endpoint(normalized_path):
        return
    endpoint = endpoint_entity(repo, method, normalized_path, host=host, tenant_id=tenant_id)
    add_entity_evidence(build, repo, endpoint, scanned.path, line_number)
    add_fact(
        build,
        predicate,
        service_entity,
        endpoint,
        repo,
        scanned.path,
        line_number,
        qualifier={"source_kind": source_kind, "raw_target": raw_target or path, "path": scanned.relative_path},
    )


def _looks_like_endpoint(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path in {"/", "/*"}:
        return True
    return any(char.isalpha() for char in path)
