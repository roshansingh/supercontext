from __future__ import annotations

import ast
import json
import posixpath
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
    normalize_endpoint_path,
)
from source.kg.core.tenant import resolve_tenant_id
from source.kg.file_formats.openapi_yaml import extract_openapi_endpoints
from source.kg.languages.python.extractors.frameworks import extract_django_routes, extract_flask_routes
from source.kg.languages.python.extractors.frameworks.routes import EndpointRoute
from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.files import TYPESCRIPT_EXTENSIONS


JAVASCRIPT_TYPESCRIPT_SUFFIXES = TYPESCRIPT_EXTENSIONS
JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
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
                validate_path=False,
            )
            if confidence == "host_unresolved_path_resolved":
                _add_endpoint_coverage(
                    build,
                    repo,
                    tenant_id,
                    "unresolved_host",
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
        return

    confidence = "host_unresolved_path_resolved" if resolved["kind"] == "host_unresolved" else None
    _add_endpoint_fact(
        repo,
        scanned,
        line_number,
        service_entity,
        build,
        "CALLS_ENDPOINT",
        str(row.get("method") or "ANY").upper(),
        str(resolved["path"]),
        "imported_axios_call",
        tenant_id,
        host=resolved.get("host") if isinstance(resolved.get("host"), str) else None,
        raw_target=raw_target,
        confidence=confidence,
        validate_path=False,
    )
    if confidence == "host_unresolved_path_resolved":
        _add_endpoint_coverage(
            build,
            repo,
            tenant_id,
            "unresolved_host",
            scanned.relative_path,
            line_number,
            raw_target,
            "partially_instrumented",
        )


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
    if not import_source.startswith("."):
        return _resolve_path_alias_import(import_source, module_clients, path_aliases)
    importer_dir = posixpath.dirname(importer_path)
    normalized = posixpath.normpath(posixpath.join(importer_dir, import_source))
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        return None
    return _resolve_module_path_candidate(normalized, module_clients)


def _resolve_path_alias_import(
    import_source: str,
    module_clients: dict[str, dict[str, object]],
    path_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> str | None:
    for pattern, targets in path_aliases:
        capture = _match_typescript_path_pattern(pattern, import_source)
        if capture is None:
            continue
        pattern_has_wildcard = "*" in pattern
        for target in targets:
            if pattern_has_wildcard and target.count("*") > 1:
                continue
            candidate = target.replace("*", capture) if pattern_has_wildcard and "*" in target else target
            normalized = posixpath.normpath(candidate)
            if not normalized or normalized == "." or normalized.startswith("/") or normalized.startswith("../") or normalized == "..":
                continue
            resolved = _resolve_module_path_candidate(normalized, module_clients)
            if resolved is not None:
                return resolved
    return None


def _resolve_module_path_candidate(normalized: str, module_clients: dict[str, dict[str, object]]) -> str | None:
    if not normalized or normalized.startswith("/"):
        return None
    candidates = [normalized]
    if posixpath.splitext(normalized)[1] == "":
        candidates.extend(f"{normalized}{suffix}" for suffix in JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES)
        candidates.extend(posixpath.join(normalized, f"index{suffix}") for suffix in JAVASCRIPT_TYPESCRIPT_IMPORT_SUFFIXES)
    for candidate in candidates:
        if candidate in module_clients:
            return candidate
    return None


def _match_typescript_path_pattern(pattern: str, import_source: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == import_source else None
    if pattern.count("*") != 1:
        return None
    prefix, suffix = pattern.split("*", 1)
    if not import_source.startswith(prefix) or not import_source.endswith(suffix):
        return None
    return import_source[len(prefix) : len(import_source) - len(suffix) if suffix else len(import_source)]


def _typescript_path_pattern_sort_key(alias: tuple[str, tuple[str, ...]]) -> tuple[int, int, int]:
    pattern, _targets = alias
    if "*" not in pattern:
        return (1, len(pattern), 0)
    if pattern.count("*") != 1:
        return (-1, 0, 0)
    prefix, suffix = pattern.split("*", 1)
    return (0, len(prefix), len(suffix))


def _load_typescript_path_aliases(repo_root: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    aliases: list[tuple[str, tuple[str, ...]]] = []
    for config_name in ("tsconfig.json", "jsconfig.json"):
        config_path = repo_root / config_name
        if not config_path.exists():
            continue
        config = _load_jsonc_object(config_path)
        compiler_options = config.get("compilerOptions") if isinstance(config, dict) else None
        if not isinstance(compiler_options, dict):
            continue
        paths = compiler_options.get("paths")
        if not isinstance(paths, dict):
            continue
        base_url = compiler_options.get("baseUrl")
        base_prefix = _normalize_repo_relative_path(base_url) if isinstance(base_url, str) else "."
        for pattern, raw_targets in paths.items():
            if not isinstance(pattern, str) or not isinstance(raw_targets, list):
                continue
            targets = tuple(
                _normalize_repo_relative_path(posixpath.join(base_prefix, target))
                for target in raw_targets
                if isinstance(target, str)
            )
            if targets:
                aliases.append((pattern, targets))
    return tuple(sorted(aliases, key=_typescript_path_pattern_sort_key, reverse=True))


def load_typescript_path_aliases(repo_root: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _load_typescript_path_aliases(repo_root)


def _normalize_repo_relative_path(value: str) -> str:
    normalized = posixpath.normpath(value.replace("\\", "/"))
    return "" if normalized == "." else normalized


def _load_jsonc_object(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    try:
        data = json.loads(_strip_trailing_json_commas(_strip_jsonc_comments(text)))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _strip_jsonc_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index = min(index + 2, len(text))
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _strip_trailing_json_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


def _compose_imported_client_target(target: dict, base_url: object) -> dict[str, object]:
    target_kind = target.get("kind")
    target_value = target.get("value")
    target_raw = target.get("raw")
    raw_target = target_raw if isinstance(target_raw, str) else ""
    if target_kind == "unresolved" or not isinstance(target_value, str):
        return {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
    target_value = target_value.strip()
    if target_value.startswith("http://") or target_value.startswith("https://") or target_value.startswith("${env:"):
        resolved = _split_resolved_endpoint_target(target_value)
        return resolved if resolved["kind"] != "unresolved" else {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
    if not isinstance(base_url, dict):
        return _split_resolved_endpoint_target(target_value)
    base_kind = base_url.get("kind")
    base_value = base_url.get("value")
    if base_kind not in {"resolved", "env"} or not isinstance(base_value, str):
        return {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}
    combined = f"{base_value.strip().rstrip('/')}/{target_value.lstrip('/')}"
    resolved = _split_resolved_endpoint_target(combined)
    return resolved if resolved["kind"] != "unresolved" else {"kind": "unresolved", "path": None, "host": None, "raw_target": raw_target}


def _split_resolved_endpoint_target(value: str) -> dict[str, object]:
    trimmed = value.strip()
    if trimmed.startswith("http://") or trimmed.startswith("https://"):
        parsed = urlparse(trimmed)
        if not parsed.scheme or not parsed.netloc:
            return {"kind": "unresolved", "path": None, "host": None, "raw_target": trimmed}
        host = parsed.hostname
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
