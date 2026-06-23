from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import urlparse

from source.kg.core.models import Coverage, Entity
from source.kg.file_formats._shared.common import (
    CONFIG_SOURCE_SYSTEM,
    ConfigKgBuild,
    ScannedFile,
    add_entity_evidence,
    add_fact,
    endpoint_entity,
    env_var_entity,
    normalize_endpoint_path,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats.openapi_yaml import extract_openapi_endpoints
from source.kg.languages.python.extractors.frameworks import (
    extract_django_routes,
    extract_fastapi_routes,
    extract_flask_routes,
)
from source.kg.languages.python.extractors.frameworks.routes import EndpointRoute
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.files import TYPESCRIPT_EXTENSIONS
from source.kg.languages.typescript.module_resolution import (
    load_typescript_path_aliases as _load_typescript_path_aliases,
    resolve_typescript_import_path,
)


JAVASCRIPT_TYPESCRIPT_SUFFIXES = TYPESCRIPT_EXTENSIONS
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
                    "reason": "parser_backed_js_ts_route_extraction_partial_express_fastify_koa_only",
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
    fastapi_routes, fastapi_recognized = extract_fastapi_routes(tree)
    routes.extend(flask_routes)
    routes.extend(django_routes)
    routes.extend(fastapi_routes)
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
    return flask_recognized or django_recognized or fastapi_recognized


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
        for row in parsed_file.get("server_routes", parsed_file.get("express_routes", [])):
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
    module_clients = _build_module_clients_index(parsed_files)
    literal_exports = _build_literal_exports_index(parsed_files)
    literal_aliases = _build_literal_aliases_index(parsed_files)
    path_aliases = _load_typescript_path_aliases(repo.root)
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(parsed_file, dict):
            continue
        file_path = repo.root / str(relative_path)
        scanned = ScannedFile(path=file_path, relative_path=str(relative_path), text="", lines=())
        imports_by_local = _build_imports_by_local(parsed_file)
        for row in parsed_file.get("client_endpoint_calls", []):
            if not isinstance(row, dict):
                continue
            row = _resolve_typescript_endpoint_imported_base_literals(
                scanned.relative_path,
                row,
                imports_by_local,
                literal_exports,
                literal_aliases.get(scanned.relative_path, {}),
                path_aliases,
            )
            line_number = int(row.get("line") or 1)
            raw_target = _raw_target(row)
            if row.get("source_kind") == "imported_axios_call":
                _add_imported_client_endpoint_call(
                    repo,
                    scanned,
                    line_number,
                    row,
                    imports_by_local,
                    module_clients,
                    path_aliases,
                    service_entity,
                    build,
                    tenant_id,
                )
                continue
            if row.get("external") is True:
                _add_endpoint_coverage(
                    build,
                    repo,
                    tenant_id,
                    "external_endpoint_suppressed",
                    scanned.relative_path,
                    line_number,
                    raw_target,
                    "uninstrumented",
                )
                continue
            if row.get("unresolved") is True:
                reason = row.get("reason")
                _add_endpoint_coverage(
                    build,
                    repo,
                    tenant_id,
                    reason if isinstance(reason, str) else "unresolved_target",
                    scanned.relative_path,
                    line_number,
                    raw_target,
                    "uninstrumented",
                )
                continue
            path = row.get("path")
            if not isinstance(path, str):
                _add_endpoint_coverage(
                    build,
                    repo,
                    tenant_id,
                    "unresolved_target",
                    scanned.relative_path,
                    line_number,
                    raw_target,
                    "uninstrumented",
                )
                continue
            method = str(row.get("method") or "ANY").upper()
            source_kind = str(row.get("source_kind") or "client_call")
            host = row.get("host")
            confidence = row.get("confidence")
            resolution_kind = row.get("resolution_kind")
            host_resolution_kind = row.get("host_resolution_kind")
            route_params = row.get("route_params")
            env_names = row.get("env_names")
            qualifier_extra = _endpoint_row_metadata(row)
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
                confidence=confidence if isinstance(confidence, str) else None,
                resolution_kind=resolution_kind if isinstance(resolution_kind, str) else None,
                host_resolution_kind=host_resolution_kind if isinstance(host_resolution_kind, str) else None,
                route_params=route_params if _is_string_list(route_params) else None,
                extra_qualifier=qualifier_extra,
                validate_path=False,
            )
            if _is_string_list(env_names):
                _add_endpoint_env_var_references(
                    repo,
                    scanned,
                    line_number,
                    service_entity,
                    build,
                    tenant_id,
                    env_names,
                    endpoint_method=method,
                    endpoint_path=path,
                    raw_target=raw_target,
                    host_resolution_kind=host_resolution_kind if isinstance(host_resolution_kind, str) else None,
                )
            if confidence == "host_unresolved_path_resolved":
                reason = row.get("reason")
                _add_endpoint_coverage(
                    build,
                    repo,
                    tenant_id,
                    reason if isinstance(reason, str) else "host_env_backed",
                    scanned.relative_path,
                    line_number,
                    raw_target,
                    "partially_instrumented",
                )


def _add_imported_client_endpoint_call(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    row: dict,
    imports_by_local: dict[str, dict[str, str]],
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    raw_target = _raw_target(row)
    client_info = _resolve_imported_client(scanned.relative_path, row, imports_by_local, module_clients, path_aliases)
    if client_info is None:
        return

    target = row.get("target")
    if not isinstance(target, dict):
        _add_endpoint_coverage(
            build,
            repo,
            tenant_id,
            "unresolved_target",
            scanned.relative_path,
            line_number,
            raw_target,
            "uninstrumented",
        )
        return

    base_url = row.get("base_url")
    resolved = _compose_imported_client_target(target, base_url if isinstance(base_url, dict) else client_info.get("base_url"))
    if resolved["kind"] == "external":
        _add_endpoint_coverage(
            build,
            repo,
            tenant_id,
            "external_endpoint_suppressed",
            scanned.relative_path,
            line_number,
            raw_target,
            "uninstrumented",
        )
        return
    if resolved["kind"] == "unresolved" or not isinstance(resolved.get("path"), str):
        reason = resolved.get("reason") or row.get("reason")
        _add_endpoint_coverage(
            build,
            repo,
            tenant_id,
            reason if isinstance(reason, str) else "unresolved_target",
            scanned.relative_path,
            line_number,
            raw_target,
            "uninstrumented",
        )
        return

    confidence = "host_unresolved_path_resolved" if resolved["kind"] == "host_unresolved" else None
    resolution_kind = resolved.get("resolution_kind")
    host_resolution_kind = resolved.get("host_resolution_kind")
    route_params = resolved.get("route_params")
    env_names = resolved.get("env_names")
    method = str(row.get("method") or "ANY").upper()
    path = str(resolved["path"])
    _add_endpoint_fact(
        repo,
        scanned,
        line_number,
        service_entity,
        build,
        "CALLS_ENDPOINT",
        method,
        path,
        "imported_axios_call",
        tenant_id,
        host=resolved.get("host") if isinstance(resolved.get("host"), str) else None,
        raw_target=raw_target,
        confidence=confidence,
        resolution_kind=resolution_kind if isinstance(resolution_kind, str) else None,
        host_resolution_kind=host_resolution_kind if isinstance(host_resolution_kind, str) else None,
        route_params=route_params if _is_string_list(route_params) else None,
        extra_qualifier=_endpoint_row_metadata(resolved),
        validate_path=False,
    )
    if _is_string_list(env_names):
        _add_endpoint_env_var_references(
            repo,
            scanned,
            line_number,
            service_entity,
            build,
            tenant_id,
            env_names,
            endpoint_method=method,
            endpoint_path=path,
            raw_target=raw_target,
            host_resolution_kind=host_resolution_kind if isinstance(host_resolution_kind, str) else None,
        )
    if confidence == "host_unresolved_path_resolved":
        reason = resolved.get("reason") or row.get("reason")
        _add_endpoint_coverage(
            build,
            repo,
            tenant_id,
            reason if isinstance(reason, str) else "host_env_backed",
            scanned.relative_path,
            line_number,
            raw_target,
            "partially_instrumented",
        )


def _endpoint_row_metadata(row: dict) -> dict[str, object] | None:
    metadata: dict[str, object] = {}
    for key in (
        "service",
        "service_raw",
        "service_resolution_kind",
        "api_version",
        "api_version_resolution_kind",
        "client_app_id",
        "client_app_id_resolution_kind",
        "base_url",
        "host_raw",
        "base_url_raw",
        "reason",
        "wrapper_receiver",
        "wrapper_method",
        "wrapper_import_source",
        "wrapper_imported_name",
    ):
        value = row.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata or None


def _build_module_clients_index(parsed_files: dict[str, object]) -> dict[str, dict[str, object]]:
    index: dict[str, dict[str, object]] = {}
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(relative_path, str) or not isinstance(parsed_file, dict):
            continue
        module_clients = parsed_file.get("module_clients")
        if not isinstance(module_clients, dict):
            continue
        default_client = module_clients.get("default")
        named_clients = module_clients.get("named")
        clients: dict[str, object] = {}
        if isinstance(default_client, dict):
            clients["default"] = default_client
        if isinstance(named_clients, dict):
            for export_name, client_info in named_clients.items():
                if isinstance(export_name, str) and isinstance(client_info, dict):
                    clients[export_name] = client_info
        if clients:
            index[relative_path] = clients
    return index


def build_typescript_module_clients_index(parsed_files: dict[str, object]) -> dict[str, dict[str, object]]:
    return _build_module_clients_index(parsed_files)


def _build_literal_exports_index(parsed_files: dict[str, object]) -> dict[str, dict[str, str]]:
    return _build_string_map_index(parsed_files, "literal_exports")


def _build_literal_aliases_index(parsed_files: dict[str, object]) -> dict[str, dict[str, str]]:
    return _build_string_map_index(parsed_files, "literal_aliases")


def _build_string_map_index(parsed_files: dict[str, object], key: str) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(relative_path, str) or not isinstance(parsed_file, dict):
            continue
        value = parsed_file.get(key)
        if not isinstance(value, dict):
            continue
        strings = {str(name): item for name, item in value.items() if isinstance(name, str) and isinstance(item, str)}
        if strings:
            index[relative_path] = strings
    return index


def _resolve_typescript_endpoint_imported_base_literals(
    importer_path: str,
    row: dict,
    imports_by_local: dict[str, dict[str, str]],
    literal_exports: dict[str, dict[str, str]],
    literal_aliases: dict[str, str],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict:
    if row.get("confidence") != "host_unresolved_path_resolved" or row.get("reason") != "host_or_service_unresolved":
        return row
    for raw_key in ("service_raw", "host_raw", "base_url_raw"):
        if row.get(f"{raw_key}_imported_literal_candidate") is not True:
            continue
        raw = row.get(raw_key)
        local_name = _identifier_from_typescript_raw(raw)
        if local_name is None:
            continue
        literal = _resolve_typescript_imported_literal(
            importer_path,
            local_name,
            imports_by_local,
            literal_exports,
            literal_aliases,
            path_aliases,
            seen=frozenset(),
        )
        if literal is None:
            continue
        resolved = _endpoint_row_with_resolved_base_literal(row, raw_key, literal)
        if resolved is not None:
            return resolved
    return row


def _resolve_typescript_imported_literal(
    importer_path: str,
    local_name: str,
    imports_by_local: dict[str, dict[str, str]],
    literal_exports: dict[str, dict[str, str]],
    literal_aliases: dict[str, str],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    seen: frozenset[str],
) -> str | None:
    if local_name in seen:
        return None
    next_seen = seen | frozenset((local_name,))
    import_binding = imports_by_local.get(local_name)
    if import_binding is not None:
        module_path = resolve_typescript_import_path(
            importer_path,
            import_binding["import_source"],
            literal_exports,
            path_aliases,
        )
        if module_path is None:
            return None
        value = literal_exports.get(module_path, {}).get(import_binding["imported_name"])
        return value if isinstance(value, str) else None
    alias = literal_aliases.get(local_name)
    if alias is None:
        return None
    return _resolve_typescript_imported_literal(
        importer_path,
        alias,
        imports_by_local,
        literal_exports,
        literal_aliases,
        path_aliases,
        seen=next_seen,
    )


def _endpoint_row_with_resolved_base_literal(row: dict, raw_key: str, literal: str) -> dict | None:
    path = row.get("path")
    if not isinstance(path, str):
        return None
    trimmed = literal.strip()
    if not trimmed or trimmed.startswith("${env:") or trimmed.startswith("/"):
        return None
    resolved = dict(row)
    is_absolute_url = trimmed.startswith(("http://", "https://"))
    if raw_key == "base_url_raw" and not is_absolute_url:
        return None
    if is_absolute_url:
        split = _split_resolved_endpoint_target(f"{trimmed.rstrip('/')}/{path.lstrip('/')}")
        if split.get("kind") not in {"external", "resolved"}:
            return None
        split_path = split.get("path")
        split_host = split.get("host")
        if not isinstance(split_path, str) or not isinstance(split_host, str):
            return None
        resolved["path"] = split_path
        resolved["host"] = split_host
        if split.get("kind") == "external":
            resolved["external"] = True
    else:
        resolved["host"] = trimmed
    if raw_key == "service_raw":
        resolved["service"] = trimmed
    elif raw_key == "base_url_raw":
        resolved["base_url"] = trimmed
    for key in (
        raw_key,
        f"{raw_key}_imported_literal_candidate",
        "confidence",
        "reason",
        "host_resolution_kind",
    ):
        resolved.pop(key, None)
    return resolved


def _identifier_from_typescript_raw(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    first = raw[0]
    if not (first.isalpha() or first in {"_", "$"}):
        return None
    if all(char.isalnum() or char in {"_", "$"} for char in raw[1:]):
        return raw
    return None


def _build_imports_by_local(parsed_file: dict) -> dict[str, dict[str, str]]:
    imports_by_local: dict[str, dict[str, str]] = {}
    duplicate_locals: set[str] = set()
    imports = parsed_file.get("imports")
    if not isinstance(imports, list):
        return imports_by_local
    for row in imports:
        if not isinstance(row, dict) or row.get("is_type_only") is True:
            continue
        raw_target = row.get("raw_target")
        imported_names = row.get("imported_names")
        local_names = row.get("local_names")
        if not isinstance(raw_target, str) or not isinstance(imported_names, list) or not isinstance(local_names, list):
            continue
        if len(imported_names) != len(local_names):
            continue
        for imported_name, local_name in zip(imported_names, local_names, strict=True):
            if not isinstance(imported_name, str) or not isinstance(local_name, str):
                continue
            if local_name in imports_by_local:
                duplicate_locals.add(local_name)
            imports_by_local[local_name] = {"import_source": raw_target, "imported_name": imported_name}
    for local_name in duplicate_locals:
        imports_by_local.pop(local_name, None)
    return imports_by_local


def build_typescript_imports_by_local(parsed_file: dict) -> dict[str, dict[str, str]]:
    return _build_imports_by_local(parsed_file)


def _resolve_imported_client(
    importer_path: str,
    row: dict,
    imports_by_local: dict[str, dict[str, str]],
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, object] | None:
    receiver = row.get("receiver_local")
    if not isinstance(receiver, str):
        return None
    import_binding = imports_by_local.get(receiver)
    if import_binding is None:
        return None
    module_path = _resolve_import(importer_path, import_binding["import_source"], module_clients, path_aliases)
    if module_path is None:
        return None
    imported_name = row.get("imported_name")
    if not isinstance(imported_name, str) or imported_name != import_binding["imported_name"]:
        return None
    client_info = module_clients.get(module_path, {}).get(imported_name)
    return client_info if isinstance(client_info, dict) else None


def resolve_typescript_imported_client(
    importer_path: str,
    row: dict,
    imports_by_local: dict[str, dict[str, str]],
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, object] | None:
    return _resolve_imported_client(importer_path, row, imports_by_local, module_clients, path_aliases)


def _resolve_import(
    importer_path: str,
    import_source: str,
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> str | None:
    return resolve_typescript_import_path(importer_path, import_source, module_clients, path_aliases)


def load_typescript_path_aliases(repo_root: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _load_typescript_path_aliases(repo_root)


def _compose_imported_client_target(target: dict, base_url: object) -> dict[str, object]:
    target_kind = target.get("kind")
    target_value = target.get("value")
    target_raw = target.get("raw")
    raw_target = target_raw if isinstance(target_raw, str) else ""
    if target_kind == "unresolved" or not isinstance(target_value, str):
        reason = target.get("reason")
        resolved: dict[str, object] = {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
        if isinstance(reason, str):
            resolved["reason"] = reason
        return resolved
    target_value = target_value.strip()
    resolution_kind = target.get("resolution_kind")
    route_params = target.get("route_params")
    target_env_names = target.get("env_names")
    if target_value.startswith("http://") or target_value.startswith("https://") or target_value.startswith("${env:"):
        resolved = _split_resolved_endpoint_target(target_value)
        if isinstance(resolution_kind, str):
            resolved["resolution_kind"] = resolution_kind
        if _is_string_list(route_params):
            resolved["route_params"] = route_params
        if resolved["kind"] == "host_unresolved" and _is_string_list(target_env_names):
            resolved["env_names"] = target_env_names
        return resolved if resolved["kind"] != "unresolved" else {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
    if not isinstance(base_url, dict):
        resolved = _split_resolved_endpoint_target(target_value)
        if isinstance(resolution_kind, str):
            resolved["resolution_kind"] = resolution_kind
        if _is_string_list(route_params):
            resolved["route_params"] = route_params
        if resolved["kind"] == "host_unresolved" and _is_string_list(target_env_names):
            resolved["env_names"] = target_env_names
        return resolved
    base_kind = base_url.get("kind")
    base_value = base_url.get("value")
    if base_kind not in {"resolved", "env"} or not isinstance(base_value, str):
        unresolved_base_target = _compose_imported_client_unresolved_base_target(target, base_url)
        if unresolved_base_target is not None:
            return unresolved_base_target
        return {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
    combined = f"{base_value.strip().rstrip('/')}/{target_value.lstrip('/')}"
    resolved = _split_resolved_endpoint_target(combined)
    if isinstance(resolution_kind, str):
        resolved["resolution_kind"] = resolution_kind
    if _is_string_list(route_params):
        resolved["route_params"] = route_params
    env_names = _merge_string_lists(base_url.get("env_names"), target_env_names)
    # Env-name provenance only applies while the host is still env-backed;
    # path-position env placeholders must not become endpoint_env_host facts.
    if resolved["kind"] == "host_unresolved" and env_names:
        resolved["env_names"] = env_names
    return resolved if resolved["kind"] != "unresolved" else {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}


def _compose_imported_client_unresolved_base_target(target: dict, base_url: object) -> dict[str, object] | None:
    target_value = target.get("value")
    if not isinstance(target_value, str):
        return None
    target_value = target_value.strip()
    if not target_value or target_value.startswith(("http://", "https://", "${env:")):
        return None
    raw_target = target.get("raw")
    resolved: dict[str, object] = {
        "kind": "host_unresolved",
        "path": normalize_endpoint_path(target_value),
        "host": None,
        "raw_target": raw_target if isinstance(raw_target, str) else target_value,
        "reason": "host_or_service_unresolved",
        "host_resolution_kind": "expression_unresolved",
    }
    if isinstance(base_url, dict):
        base_raw = base_url.get("raw")
        if isinstance(base_raw, str) and base_raw:
            resolved["base_url_raw"] = base_raw
    resolution_kind = target.get("resolution_kind")
    route_params = target.get("route_params")
    if isinstance(resolution_kind, str):
        resolved["resolution_kind"] = resolution_kind
    if _is_string_list(route_params):
        resolved["route_params"] = route_params
    return resolved


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(isinstance(item, str) for item in value)


def _merge_string_lists(*values: object) -> list[str]:
    merged: list[str] = []
    for value in values:
        if not _is_string_list(value):
            continue
        for item in value:
            if item not in merged:
                merged.append(item)
    return merged


def _add_endpoint_env_var_references(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    line_number: int,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
    env_names: object,
    *,
    endpoint_method: str | None = None,
    endpoint_path: str | None = None,
    raw_target: str | None = None,
    host_resolution_kind: str | None = None,
) -> None:
    if not _is_string_list(env_names):
        return
    # Evidence is anchored to the endpoint call site. For imported clients, the
    # env-backed base URL may be declared in another file and is not cited here.
    for name in _merge_string_lists(env_names):
        env_entity = env_var_entity(repo, name, tenant_id)
        add_entity_evidence(build, repo, env_entity, scanned.path, line_number)
        qualifier = {"name": name, "reference_kind": "endpoint_env_host"}
        if endpoint_method is not None:
            qualifier["endpoint_method"] = endpoint_method
        if endpoint_path is not None:
            qualifier["endpoint_path"] = normalize_endpoint_path(endpoint_path)
        if raw_target is not None:
            qualifier["raw_target"] = raw_target
        if host_resolution_kind is not None:
            qualifier["host_resolution_kind"] = host_resolution_kind
        add_fact(
            build,
            "REFERENCES_ENV_VAR",
            service_entity,
            env_entity,
            repo,
            scanned.path,
            line_number,
            qualifier=qualifier,
        )


def _split_resolved_endpoint_target(value: str) -> dict[str, object]:
    trimmed = value.strip()
    if trimmed.startswith("http://") or trimmed.startswith("https://"):
        parsed = urlparse(trimmed)
        if not parsed.scheme or not parsed.netloc:
            return {"kind": "unresolved", "path": None, "host": None, "raw_target": trimmed}
        host = parsed.hostname
        if not isinstance(host, str) or not host:
            return {"kind": "unresolved", "path": None, "host": None, "raw_target": trimmed}
        external = host is not None and host not in {"localhost", "127.0.0.1"}
        return {
            "kind": "external" if external else "resolved",
            "path": parsed.path or "/",
            "host": host,
            "raw_target": trimmed,
        }
    if trimmed.startswith("${env:"):
        host_end = trimmed.find("}")
        if host_end >= 0:
            path_start = trimmed.find("/", host_end + 1)
            if path_start == host_end + 1 and "${env:" not in trimmed[path_start:]:
                return {
                    "kind": "host_unresolved",
                    "path": trimmed[path_start:] or "/",
                    "host": trimmed[: host_end + 1],
                    "raw_target": trimmed,
                    "reason": "host_env_backed",
                    "host_resolution_kind": "env_backed_unresolved",
                }
        return {"kind": "unresolved", "path": None, "host": None, "raw_target": trimmed}
    if not trimmed.startswith("/"):
        return {"kind": "unresolved", "path": None, "host": None, "raw_target": trimmed}
    return {"kind": "resolved", "path": trimmed, "host": None, "raw_target": trimmed}


def _raw_target(row: dict) -> str:
    raw_target = row.get("raw_target")
    if isinstance(raw_target, str):
        return raw_target[:80]
    return ""


def _add_endpoint_coverage(
    build: ConfigKgBuild,
    repo: RepoSnapshot,
    tenant_id: str,
    reason: str,
    file_path: str,
    line_number: int,
    raw_target: str,
    state: str,
) -> None:
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="CALLS_ENDPOINT",
            scope_ref={
                "repo": repo.name,
                "file_path": file_path,
                "line": line_number,
                "reason": reason,
                "raw_target": raw_target,
            },
            state=state,
            source_system=CONFIG_SOURCE_SYSTEM,
        )
    )


_DOTNET_HTTP_ATTR_VERBS = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpDelete": "DELETE",
    "HttpPatch": "PATCH",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
}
_DOTNET_MAP_METHOD_VERBS = {
    "MapGet": "GET",
    "MapPost": "POST",
    "MapPut": "PUT",
    "MapDelete": "DELETE",
    "MapPatch": "PATCH",
}


def extract_dotnet_endpoints(
    repo: RepoSnapshot,
    parsed_files: dict[str, object],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    """ASP.NET Core EXPOSES_ENDPOINT extraction from the .NET parser output.

    Covers controllers (``[HttpGet("path")]`` methods under a ``[Route("prefix")]`` class) and
    minimal APIs (``app.MapGet("/path", ...)``, including ``MapGroup`` prefixes). Paths come from
    attribute / call string literals — non-literal routes are simply not emitted.
    """
    for relative_path, parsed_file in parsed_files.items():
        if not isinstance(parsed_file, dict):
            continue
        scanned = ScannedFile(path=repo.root / str(relative_path), relative_path=str(relative_path), text="", lines=())
        symbols = [s for s in parsed_file.get("symbols", []) if isinstance(s, dict)]
        _dotnet_controller_endpoints(repo, scanned, symbols, service_entity, build, tenant_id)
        _dotnet_minimal_api_endpoints(repo, scanned, parsed_file, service_entity, build, tenant_id)


def _nearest_at_or_before(declarations: list[tuple[int, str]] | None, line: int) -> str:
    if not declarations:
        return ""
    preceding = [(decl_line, value) for decl_line, value in declarations if decl_line <= line]
    return max(preceding)[1] if preceding else ""


def _normalize_attribute_name(name: str) -> str:
    # C# attributes may be namespace-qualified and the `Attribute` suffix is optional, so
    # `[Microsoft.AspNetCore.Mvc.HttpGetAttribute]` and `[HttpGet]` must match the same key.
    simple = name.rsplit(".", 1)[-1].strip()
    suffix = "Attribute"
    if simple.endswith(suffix) and len(simple) > len(suffix):
        simple = simple[: -len(suffix)]
    return simple


def _dotnet_controller_endpoints(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    symbols: list[dict],
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    class_prefixes = {
        str(sym.get("name")): _dotnet_class_route_prefix(sym)
        for sym in symbols
        if sym.get("kind") in {"class", "record"}
    }
    for sym in symbols:
        if sym.get("kind") != "method":
            continue
        qualname = str(sym.get("name", ""))
        for attribute in sym.get("attributes", []):
            verb = _DOTNET_HTTP_ATTR_VERBS.get(_normalize_attribute_name(str(attribute.get("name"))))
            if verb is None:
                continue
            args = attribute.get("args") or []
            method_path = str(args[0]) if args else ""
            prefix = _dotnet_owning_class_prefix(qualname, class_prefixes)
            if not prefix and not method_path:
                # No literal route template anywhere (convention-based routing we can't resolve);
                # don't emit a bogus "/" endpoint.
                continue
            path = _join_route(prefix, method_path)
            _add_endpoint_fact(
                repo, scanned, int(sym.get("line") or 1), service_entity, build,
                "EXPOSES_ENDPOINT", verb, path, "dotnet_controller_route", tenant_id, validate_path=False,
            )


def _dotnet_minimal_api_endpoints(
    repo: RepoSnapshot,
    scanned: ScannedFile,
    parsed_file: dict,
    service_entity: Entity,
    build: ConfigKgBuild,
    tenant_id: str,
) -> None:
    # MapGroup prefixes keyed by (method symbol key, local name) -> [(line, prefix)] so a local
    # `api` cannot prefix routes in another scope, and a later reassignment only affects calls
    # after it (nearest declaration at/before the call site wins).
    group_prefixes: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for assignment in parsed_file.get("local_assignments", []):
        if isinstance(assignment, dict) and assignment.get("map_group_prefix"):
            key = (str(assignment.get("scope", "")), str(assignment.get("name", "")))
            group_prefixes.setdefault(key, []).append(
                (int(assignment.get("line") or 0), str(assignment.get("map_group_prefix")))
            )
    for call in parsed_file.get("calls", []):
        if not isinstance(call, dict):
            continue
        verb = _DOTNET_MAP_METHOD_VERBS.get(str(call.get("method", "")))
        if verb is None:
            continue
        first_arg = call.get("first_arg") or {}
        if first_arg.get("kind") != "string":
            continue
        line = int(call.get("line") or 1)
        prefix = (
            _nearest_at_or_before(group_prefixes.get((str(call.get("caller_key", "")), str(call.get("receiver", "")))), line)
            or str(call.get("inline_group_prefix") or "")  # chained app.MapGroup("p").MapGet(...)
        )
        path = _join_route(prefix, str(first_arg.get("value", "")))
        _add_endpoint_fact(
            repo, scanned, int(call.get("line") or 1), service_entity, build,
            "EXPOSES_ENDPOINT", verb, path, "dotnet_minimal_api_route", tenant_id, validate_path=False,
        )


def _dotnet_class_route_prefix(class_symbol: dict) -> str:
    for attribute in class_symbol.get("attributes", []):
        if _normalize_attribute_name(str(attribute.get("name"))) == "Route":
            args = attribute.get("args") or []
            if args:
                return _resolve_route_token(str(args[0]), class_symbol)
    return ""


def _resolve_route_token(prefix: str, class_symbol: dict) -> str:
    if "[controller]" in prefix:
        name = str(class_symbol.get("name", "")).rsplit(".", 1)[-1]
        controller = name[: -len("Controller")] if name.endswith("Controller") else name
        return prefix.replace("[controller]", controller.lower())
    return prefix


def _dotnet_owning_class_prefix(method_qualname: str, class_prefixes: dict[str, str]) -> str:
    best = ""
    best_len = -1
    for class_qualname, prefix in class_prefixes.items():
        if method_qualname.startswith(class_qualname + ".") and len(class_qualname) > best_len:
            best = prefix
            best_len = len(class_qualname)
    return best


def _join_route(prefix: str, path: str) -> str:
    parts = [segment.strip("/") for segment in (prefix, path) if segment and segment.strip("/")]
    return "/" + "/".join(parts) if parts else "/"


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
    confidence: str | None = None,
    resolution_kind: str | None = None,
    host_resolution_kind: str | None = None,
    route_params: list[str] | None = None,
    extra_qualifier: dict[str, object] | None = None,
    validate_path: bool = True,
) -> None:
    normalized_path = normalize_endpoint_path(path)
    if validate_path and not _looks_like_endpoint(normalized_path):
        return
    endpoint = endpoint_entity(repo, method, normalized_path, host=host, tenant_id=tenant_id)
    add_entity_evidence(build, repo, endpoint, scanned.path, line_number)
    qualifier = {"source_kind": source_kind, "raw_target": raw_target or path, "path": scanned.relative_path}
    if confidence is not None:
        qualifier["confidence"] = confidence
    if resolution_kind is not None:
        qualifier["resolution_kind"] = resolution_kind
    if host_resolution_kind is not None:
        qualifier["host_resolution_kind"] = host_resolution_kind
    if route_params:
        qualifier["route_params"] = route_params
    if extra_qualifier:
        for key, value in extra_qualifier.items():
            qualifier.setdefault(key, value)
    add_fact(
        build,
        predicate,
        service_entity,
        endpoint,
        repo,
        scanned.path,
        line_number,
        qualifier=qualifier,
    )


def _looks_like_endpoint(path: str) -> bool:
    if not path.startswith("/"):
        return False
    if path in {"/", "/*"}:
        return True
    return any(char.isalpha() for char in path)
