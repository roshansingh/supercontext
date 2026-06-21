from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from source.kg.core.models import Coverage, Entity, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import endpoint_entity, env_var_entity, normalize_endpoint_path
from source.kg.languages.python.extractors.dataflow import (
    LiteralIndex,
    LiteralRef,
    ResolvedValue,
    UnresolvedValue,
    ValueResolver,
    ValueScope,
    import_bindings,
    local_literal_assignments_before,
)
from source.kg.languages.python.extractors.source_context import source_excerpt, source_line
from source.kg.languages.python.normalization.imports import NormalizedImport
from source.kg.languages.python.opportunities.http_client import FunctionDefNode, HttpClientCall, collect_http_client_calls


HTTP_VERBS = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"})


class CallerSymbol(Protocol):
    entity: Entity
    module_name: str
    qualname: str
    line: int


class KgBuildLike(Protocol):
    entities: list[Entity]
    coverage: list[Coverage]


@dataclass(frozen=True)
class EndpointTarget:
    kind: str
    path: str | None
    host: str | None
    raw_target: str
    reason: str | None = None
    confidence: str | None = None
    resolution_kind: str | None = None
    host_resolution_kind: str | None = None
    route_params: tuple[str, ...] = ()
    env_names: tuple[str, ...] = ()
    base_url_raw: str | None = None


@dataclass(frozen=True)
class BaseTarget:
    kind: str
    host: str | None
    path_prefix: str
    raw_target: str
    reason: str | None = None
    host_resolution_kind: str | None = None
    env_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolverBase:
    imported_modules: dict[str, str]
    imported_values: dict[str, LiteralRef]
    module_values: dict[str, ast.AST]


def extract_http_client_endpoint_calls(
    repo: RepoSnapshot,
    file_path: Path,
    tree: ast.AST,
    module_name: str,
    imports: list[NormalizedImport],
    literal_index: LiteralIndex,
    service_entity: Entity,
    function_symbols_by_node: Mapping[FunctionDefNode, CallerSymbol],
    build: KgBuildLike,
    source_system: str,
    add_entity_evidence: Callable[..., None],
    add_fact: Callable[..., None],
    source_text: str,
    *,
    tenant_id: str,
) -> None:
    resolver_base = _resolver_base(module_name, literal_index, imports)
    for call in collect_http_client_calls(repo, file_path, tree):
        line = getattr(call.node, "lineno", 1)
        resolver = _resolver(resolver_base, literal_index, call)
        target = _target_for_call(call, resolver, source_text)
        if target.kind in {"unresolved", "external"} or target.path is None:
            # Dynamic or intentionally suppressed calls are explicit coverage rows,
            # not extractor-support gaps; metrics use the row to cover the opportunity.
            _add_endpoint_coverage(build, repo, file_path, line, target, source_system, tenant_id, "uninstrumented")
            if target.env_names:
                _add_env_var_references(
                    repo,
                    file_path,
                    line,
                    service_entity,
                    build,
                    add_entity_evidence,
                    add_fact,
                    tenant_id,
                    target,
                    endpoint_method=_method_for_call(call, resolver),
                )
            continue

        endpoint = endpoint_entity(repo, _method_for_call(call, resolver), target.path, host=target.host, tenant_id=tenant_id)
        add_entity_evidence(build, repo, endpoint, file_path, line, line)
        qualifier = _fact_qualifier(repo, call, target, function_symbols_by_node.get(call.enclosing_function), source_text)
        add_fact(
            build,
            "CALLS_ENDPOINT",
            service_entity,
            endpoint,
            repo,
            file_path,
            line,
            line,
            qualifier=qualifier,
            derivation_class="deterministic_static",
        )
        if target.env_names:
            _add_env_var_references(
                repo,
                file_path,
                line,
                service_entity,
                build,
                add_entity_evidence,
                add_fact,
                tenant_id,
                target,
                endpoint_method=endpoint.identity["method"],
            )
        if target.confidence == "host_unresolved_path_resolved":
            _add_endpoint_coverage(build, repo, file_path, line, target, source_system, tenant_id, "partially_instrumented")


def _target_for_call(call: HttpClientCall, resolver: ValueResolver, source_text: str) -> EndpointTarget:
    raw_target = _raw_node(call.url_arg, source_text)
    if call.url_arg is None:
        return EndpointTarget("unresolved", None, None, raw_target, reason="unresolved_target")
    target = _target_from_node(call.url_arg, resolver, source_text, allow_relative=call.client_factory_call is not None)
    if target.kind in {"unresolved", "external"}:
        return target
    base = _base_from_factory(call.client_factory_call, resolver, source_text)
    if base is None:
        return target
    if base.kind == "external":
        # An explicit client base_url is endpoint dependency context. Bare absolute
        # URLs remain suppressed as generic third-party calls in _target_from_string.
        return EndpointTarget(
            "resolved",
            _join_paths(base.path_prefix, target.path or "/"),
            base.host,
            target.raw_target,
            resolution_kind=target.resolution_kind,
            route_params=target.route_params,
            base_url_raw=base.raw_target,
        )
    if base.kind == "host_unresolved":
        return EndpointTarget(
            "host_unresolved",
            _join_paths(base.path_prefix, target.path or "/"),
            base.host,
            target.raw_target,
            reason=base.reason,
            confidence="host_unresolved_path_resolved",
            resolution_kind=target.resolution_kind,
            host_resolution_kind=base.host_resolution_kind,
            route_params=target.route_params,
            env_names=base.env_names,
            base_url_raw=base.raw_target,
        )
    if base.kind == "unresolved":
        return EndpointTarget(
            "host_unresolved",
            target.path,
            None,
            target.raw_target,
            reason=base.reason or "host_or_service_unresolved",
            confidence="host_unresolved_path_resolved",
            resolution_kind=target.resolution_kind,
            host_resolution_kind="expression_unresolved",
            route_params=target.route_params,
            base_url_raw=base.raw_target,
        )
    return target


def _base_from_factory(factory_call: ast.Call | None, resolver: ValueResolver, source_text: str) -> BaseTarget | None:
    if factory_call is None:
        return None
    base_node = _keyword_arg(factory_call, "base_url")
    if base_node is None:
        return None
    raw = _raw_node(base_node, source_text)
    env_name = _env_name_from_node(base_node, resolver)
    if env_name is not None:
        return BaseTarget(
            "host_unresolved",
            f"${{env:{env_name}}}",
            "",
            raw,
            reason="host_env_backed",
            host_resolution_kind="env_backed_unresolved",
            env_names=(env_name,),
        )
    resolved = resolver.resolve_value(base_node)
    if isinstance(resolved, ResolvedValue) and isinstance(resolved.value, str):
        return _base_from_string(resolved.value, raw)
    if isinstance(base_node, ast.JoinedStr):
        target = _target_from_joined_str(base_node, resolver, source_text, allow_relative=False)
        if target.kind == "host_unresolved" or target.env_names:
            return BaseTarget(
                "host_unresolved",
                target.host,
                target.path or "",
                raw,
                reason=target.reason,
                host_resolution_kind=target.host_resolution_kind,
                env_names=target.env_names,
            )
        if target.kind == "unresolved":
            return BaseTarget(
                "unresolved",
                target.host,
                target.path or "",
                raw,
                reason=target.reason,
                host_resolution_kind=target.host_resolution_kind,
                env_names=target.env_names,
            )
    return BaseTarget("unresolved", None, "", raw, reason=_coverage_reason(resolved))


def _target_from_node(
    node: ast.AST,
    resolver: ValueResolver,
    source_text: str,
    *,
    allow_relative: bool,
) -> EndpointTarget:
    raw = _raw_node(node, source_text)
    env_name = _env_name_from_node(node, resolver)
    if env_name is not None:
        return EndpointTarget(
            "unresolved",
            None,
            None,
            raw,
            reason="host_or_service_unresolved",
            host_resolution_kind="env_backed_unresolved",
            env_names=(env_name,),
        )
    if isinstance(node, ast.JoinedStr):
        return _target_from_joined_str(node, resolver, source_text, allow_relative=allow_relative)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        rendered = _render_string_expression(node, resolver, source_text)
        if isinstance(rendered, UnresolvedValue):
            return EndpointTarget("unresolved", None, None, raw, reason=_coverage_reason(rendered))
        return _target_from_string(
            rendered.value,
            raw,
            allow_relative=allow_relative,
            resolution_kind=rendered.resolution_kind,
            route_params=tuple(rendered.route_params),
        )
    resolved = resolver.resolve_value(node)
    if isinstance(resolved, ResolvedValue) and isinstance(resolved.value, str):
        return _target_from_string(resolved.value, raw, allow_relative=allow_relative, resolution_kind=resolved.source)
    return EndpointTarget("unresolved", None, None, raw, reason=_coverage_reason(resolved))


def _target_from_joined_str(
    node: ast.JoinedStr,
    resolver: ValueResolver,
    source_text: str,
    *,
    allow_relative: bool,
) -> EndpointTarget:
    raw = _raw_node(node, source_text)
    rendered = _render_joined_str(node, resolver, source_text)
    if isinstance(rendered, UnresolvedValue):
        return EndpointTarget("unresolved", None, None, raw, reason=_coverage_reason(rendered))
    return _target_from_string(
        rendered.value,
        raw,
        allow_relative=allow_relative,
        resolution_kind=rendered.resolution_kind,
        route_params=tuple(rendered.route_params),
    )


def _target_from_string(
    value: str,
    raw: str,
    *,
    allow_relative: bool,
    resolution_kind: str | None = None,
    route_params: tuple[str, ...] = (),
) -> EndpointTarget:
    trimmed = value.strip()
    if not trimmed:
        return EndpointTarget("unresolved", None, None, raw, reason="unresolved_target")
    env_host = _env_placeholder_host(trimmed)
    if env_host is not None:
        host, env_name, path = env_host
        if not path:
            return EndpointTarget("unresolved", None, host, raw, reason="host_or_service_unresolved", env_names=(env_name,))
        return EndpointTarget(
            "host_unresolved",
            path,
            host,
            raw,
            reason="host_env_backed",
            confidence="host_unresolved_path_resolved",
            resolution_kind=resolution_kind,
            host_resolution_kind="env_backed_unresolved",
            route_params=route_params,
            env_names=(env_name,),
        )
    template_host = _template_host_placeholder(trimmed, route_params)
    if template_host is not None:
        path, path_params = template_host
        return EndpointTarget(
            "host_unresolved",
            path,
            None,
            raw,
            reason="template_dynamic_host_position",
            confidence="host_unresolved_path_resolved",
            resolution_kind=resolution_kind,
            host_resolution_kind="expression_unresolved",
            route_params=path_params,
        )
    parsed = urlparse(trimmed)
    host = _parsed_host(parsed)
    if parsed.scheme in {"http", "https"} and host:
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return EndpointTarget(
            "external",
            path,
            host,
            raw,
            reason="external_endpoint_suppressed",
            resolution_kind=resolution_kind,
            route_params=route_params,
        )
    if trimmed.startswith("/") or allow_relative:
        return EndpointTarget(
            "resolved",
            normalize_endpoint_path(trimmed),
            None,
            raw,
            resolution_kind=resolution_kind,
            route_params=route_params,
        )
    return EndpointTarget("unresolved", None, None, raw, reason="unresolved_target")


def _base_from_string(value: str, raw: str) -> BaseTarget:
    trimmed = value.strip()
    env_host = _env_placeholder_host(trimmed)
    if env_host is not None:
        host, env_name, path = env_host
        return BaseTarget(
            "host_unresolved",
            host,
            path,
            raw,
            reason="host_env_backed",
            host_resolution_kind="env_backed_unresolved",
            env_names=(env_name,),
        )
    parsed = urlparse(trimmed)
    host = _parsed_host(parsed)
    if parsed.scheme in {"http", "https"} and host:
        return BaseTarget("external", host, parsed.path or "", raw)
    if trimmed:
        return BaseTarget("external", None, trimmed, raw)
    return BaseTarget("unresolved", None, "", raw, reason="unresolved_target")


@dataclass(frozen=True)
class RenderedString:
    value: str
    resolution_kind: str | None = None
    route_params: tuple[str, ...] = ()


def _render_string_expression(node: ast.AST, resolver: ValueResolver, source_text: str) -> RenderedString | UnresolvedValue:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return RenderedString(node.value, "literal")
    if isinstance(node, ast.JoinedStr):
        return _render_joined_str(node, resolver, source_text)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _render_string_expression(node.left, resolver, source_text)
        if isinstance(left, UnresolvedValue):
            return left
        right = _render_string_expression(node.right, resolver, source_text)
        if isinstance(right, UnresolvedValue):
            return right
        return RenderedString(
            left.value + right.value,
            "concat",
            _merge_tuple(left.route_params, right.route_params),
        )
    env_name = _env_name_from_node(node, resolver)
    if env_name is not None:
        return RenderedString(f"${{env:{env_name}}}", "env_reference")
    resolved = resolver.resolve_value(node)
    if isinstance(resolved, ResolvedValue) and isinstance(resolved.value, str):
        return RenderedString(resolved.value, resolved.source)
    return UnresolvedValue(_coverage_reason(resolved), _raw_node(node, source_text))


def _render_joined_str(node: ast.JoinedStr, resolver: ValueResolver, source_text: str) -> RenderedString | UnresolvedValue:
    parts: list[str] = []
    route_params: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
            continue
        if not isinstance(value, ast.FormattedValue):
            return UnresolvedValue("template_dynamic_expression_unsafe", _raw_node(value, source_text))
        env_name = _env_name_from_node(value.value, resolver)
        if env_name is not None:
            parts.append(f"${{env:{env_name}}}")
            continue
        param_name = _route_param_name(value.value)
        if param_name is None:
            return UnresolvedValue("template_dynamic_expression_unsafe", _raw_node(value.value, source_text))
        parts.append("{" + param_name + "}")
        if param_name not in route_params:
            route_params.append(param_name)
    return RenderedString("".join(parts), "template_parameterized", tuple(route_params))


def _method_for_call(call: HttpClientCall, resolver: ValueResolver) -> str:
    if call.method_name != "request":
        return call.method_name.upper()
    if call.method_arg is None:
        return "ANY"
    resolved = resolver.resolve_value(call.method_arg)
    if not isinstance(resolved, ResolvedValue) or not isinstance(resolved.value, str):
        return "ANY"
    method = resolved.value.upper()
    return method if method in HTTP_VERBS else "ANY"


def _fact_qualifier(
    repo: RepoSnapshot,
    call: HttpClientCall,
    target: EndpointTarget,
    caller: CallerSymbol | None,
    source_text: str,
) -> JsonObject:
    line = getattr(call.node, "lineno", 1)
    qualifier: JsonObject = {
        "source_kind": call.source_kind,
        "raw_target": _cap_raw_text(target.raw_target),
        "path": str(call.path.relative_to(repo.root)),
    }
    if caller is not None:
        qualifier["caller_module"] = caller.module_name
        qualifier["caller_qualname"] = caller.qualname
    if target.confidence is not None:
        qualifier["confidence"] = target.confidence
    if target.resolution_kind is not None:
        qualifier["resolution_kind"] = target.resolution_kind
    if target.host_resolution_kind is not None:
        qualifier["host_resolution_kind"] = target.host_resolution_kind
    if target.route_params:
        qualifier["route_params"] = list(target.route_params)
    if target.base_url_raw is not None:
        qualifier["base_url_raw"] = _cap_raw_text(target.base_url_raw)
    line_text = source_line(source_text, line)
    excerpt = source_excerpt(source_text, call.node)
    if line_text is not None:
        qualifier["source_line"] = line_text
    if excerpt is not None:
        qualifier["source_excerpt"] = excerpt
    return qualifier


def _add_env_var_references(
    repo: RepoSnapshot,
    file_path: Path,
    line: int,
    service_entity: Entity,
    build: KgBuildLike,
    add_entity_evidence: Callable[..., None],
    add_fact: Callable[..., None],
    tenant_id: str,
    target: EndpointTarget,
    *,
    endpoint_method: str,
) -> None:
    for name in target.env_names:
        env_entity = env_var_entity(repo, name, tenant_id)
        add_entity_evidence(build, repo, env_entity, file_path, line, line)
        qualifier: JsonObject = {
            "name": name,
            "reference_kind": "endpoint_env_host",
            "endpoint_method": endpoint_method,
            "raw_target": _cap_raw_text(target.base_url_raw or target.raw_target),
            "host_resolution_kind": target.host_resolution_kind or "env_backed_unresolved",
        }
        if target.path is not None:
            qualifier["endpoint_path"] = normalize_endpoint_path(target.path)
        add_fact(
            build,
            "REFERENCES_ENV_VAR",
            service_entity,
            env_entity,
            repo,
            file_path,
            line,
            line,
            qualifier=qualifier,
            derivation_class="deterministic_static",
        )


def _add_endpoint_coverage(
    build: KgBuildLike,
    repo: RepoSnapshot,
    file_path: Path,
    line: int,
    target: EndpointTarget,
    source_system: str,
    tenant_id: str,
    state: str,
) -> None:
    build.coverage.append(
        Coverage(
            tenant_id=tenant_id,
            predicate="CALLS_ENDPOINT",
            scope_ref={
                "repo": repo.name,
                "language": "python",
                "path": str(file_path.relative_to(repo.root)),
                "line": line,
                "reason": target.reason or "unresolved_target",
                "raw_target": _cap_raw_text(target.raw_target),
            },
            state=state,
            source_system=source_system,
        )
    )


def _resolver_base(
    module_name: str,
    literal_index: LiteralIndex,
    imports: list[NormalizedImport],
) -> ResolverBase:
    imported_modules, imported_values = import_bindings(imports)
    _bind_stdlib_os_imports(imports, imported_modules, imported_values)
    return ResolverBase(imported_modules, imported_values, _module_values(module_name, literal_index))


def _resolver(
    base: ResolverBase,
    literal_index: LiteralIndex,
    call: HttpClientCall,
) -> ValueResolver:
    local_values = dict(base.module_values)
    known_local_names: set[str] = set()
    if call.enclosing_function is not None:
        local_literals = local_literal_assignments_before(call.enclosing_function, call.node)
        local_values.update(local_literals)
        known_local_names.update(local_literals)
    blocked_names = set(call.local_binding_names) - known_local_names
    return ValueResolver(
        ValueScope(
            local_values=local_values,
            imported_modules=base.imported_modules,
            imported_values=base.imported_values,
            blocked_names=blocked_names,
        ),
        literal_index,
    )


def _bind_stdlib_os_imports(
    imports: list[NormalizedImport],
    imported_modules: dict[str, str],
    imported_values: dict[str, LiteralRef],
) -> None:
    for import_ref in imports:
        if import_ref.category != "stdlib" or import_ref.import_root != "os":
            continue
        if import_ref.imported_names:
            for imported_name in import_ref.imported_names:
                imported_values.setdefault(imported_name, LiteralRef("os", imported_name))
            continue
        imported_modules.setdefault(import_ref.alias or import_ref.import_root, "os")


def _module_values(module_name: str, literal_index: LiteralIndex) -> dict[str, ast.AST]:
    return {
        ref.name: node
        for ref, node in literal_index.values.items()
        if isinstance(ref, LiteralRef) and ref.module_name == module_name
    }


def _keyword_arg(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _env_name_from_node(node: ast.AST, resolver: ValueResolver) -> str | None:
    if isinstance(node, ast.Call):
        os_parts = _resolved_os_parts(_attribute_parts(node.func), resolver)
        if os_parts in {("getenv",), ("environ", "get")}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
    if isinstance(node, ast.Subscript) and _resolved_os_parts(_attribute_parts(node.value), resolver) == ("environ",):
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return node.slice.value
    return None


def _attribute_parts(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (*_attribute_parts(node.value), node.attr)
    return ()


def _resolved_os_parts(parts: tuple[str, ...], resolver: ValueResolver) -> tuple[str, ...] | None:
    if not parts:
        return None
    root = parts[0]
    if (
        root in resolver.scope.blocked_names
        or root in resolver.scope.local_values
        or root in resolver.scope.local_resolved_values
    ):
        return None
    module_name = resolver.scope.imported_modules.get(root)
    if module_name == "os":
        return parts[1:]
    imported_ref = resolver.scope.imported_values.get(root)
    if imported_ref is not None and imported_ref.module_name == "os":
        return (imported_ref.name, *parts[1:])
    return None


def _route_param_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) and _is_identifierish(node.slice.value):
            return node.slice.value
    return None


def _is_identifierish(value: str) -> bool:
    return bool(value) and (value[0].isalpha() or value[0] == "_") and all(char.isalnum() or char == "_" for char in value[1:])


def _env_placeholder_host(value: str) -> tuple[str, str, str] | None:
    prefix = "${env:"
    if not value.startswith(prefix):
        return None
    end = value.find("}")
    if end <= len(prefix):
        return None
    env_name = value[len(prefix) : end]
    remainder = value[end + 1 :]
    if remainder and not remainder.startswith("/"):
        return None
    return (value[: end + 1], env_name, remainder)


def _parsed_host(parsed: object) -> str | None:
    hostname = getattr(parsed, "hostname", None)
    if not isinstance(hostname, str) or not hostname:
        return None
    try:
        port = getattr(parsed, "port", None)
    except ValueError:
        port = None
    if not isinstance(port, int):
        return hostname
    if ":" in hostname and not hostname.startswith("["):
        return f"[{hostname}]:{port}"
    return f"{hostname}:{port}"


def _template_host_placeholder(value: str, route_params: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
    if not value.startswith("{"):
        return None
    end = value.find("}")
    if end <= 1:
        return None
    remainder = value[end + 1 :]
    if not remainder.startswith("/"):
        return None
    host_param = value[1:end]
    path_params = tuple(param for param in route_params if param != host_param)
    return remainder, path_params


def _coverage_reason(value: ResolvedValue | UnresolvedValue) -> str:
    if isinstance(value, ResolvedValue):
        return "unresolved_target"
    reason = value.reason
    if reason == "unknown_local_binding":
        return "target_shadowed_binding"
    if reason == "unsupported_call":
        return "target_helper_call_deferred"
    if reason.startswith("unsupported_"):
        return "unresolved_target"
    return reason or "unresolved_target"


def _raw_node(node: ast.AST | None, source_text: str) -> str:
    if node is None:
        return ""
    excerpt = source_excerpt(source_text, node)
    if excerpt is not None:
        return excerpt
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _cap_raw_text(value: str) -> str:
    return value[:80]


def _join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return normalize_endpoint_path(path)
    if not path:
        return normalize_endpoint_path(prefix)
    return "/" + "/".join(part.strip("/") for part in (prefix, path) if part.strip("/"))


def _merge_tuple(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(first)
    for item in second:
        if item not in merged:
            merged.append(item)
    return tuple(merged)
