from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.models import Entity, Evidence, Fact, JsonObject
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import endpoint_entity


FRAMEWORK_IMPORT_ROOTS = ("django", "rest_framework", "flask", "flask_jwt_extended", "flask_login")

DRF_PERMISSION_BASES = {"rest_framework.permissions.BasePermission"}
DRF_VIEW_BASE_NAMES = {
    "APIView",
    "GenericAPIView",
    "ViewSet",
    "ViewSetMixin",
    "GenericViewSet",
    "ModelViewSet",
    "ReadOnlyModelViewSet",
}
DRF_PERMISSION_CLASS_ACCESS = {
    "AllowAny": "public",
    "IsAuthenticated": "authenticated",
    "IsAdminUser": "privileged",
    "DjangoModelPermissions": "model_permissions",
    "DjangoObjectPermissions": "object_permissions",
}
AUTHZ_DECORATOR_ACCESS = {
    "django.contrib.auth.decorators.login_required": "authenticated",
    "django.contrib.auth.decorators.permission_required": "permission_required",
    "flask_login.login_required": "authenticated",
    "flask_jwt_extended.jwt_required": "authenticated",
}
AUTHZ_METHOD_CALL_ACCESS = {
    "self.check_permissions": "permission_check",
    "self.check_object_permissions": "object_permission_check",
    "request.user.has_perm": "permission_check",
}
AUTHZ_EXCEPTION_ACCESS = {
    "django.core.exceptions.PermissionDenied": "permission_denied",
    "rest_framework.exceptions.NotAuthenticated": "not_authenticated",
    "rest_framework.exceptions.AuthenticationFailed": "authentication_failed",
    "rest_framework.exceptions.PermissionDenied": "permission_denied",
}
AUTHZ_FAILURE_STATUS_CODES_BY_SYMBOL = {
    "rest_framework.status.HTTP_401_UNAUTHORIZED": 401,
    "rest_framework.status.HTTP_403_FORBIDDEN": 403,
    "http.HTTPStatus.UNAUTHORIZED": 401,
    "http.HTTPStatus.FORBIDDEN": 403,
}
AUTHZ_FAILURE_RESPONSE_CALLS = {
    "django.http.HttpResponseForbidden",
    "django.http.response.HttpResponseForbidden",
}
AUTHZ_ABORT_CALLS = {
    "flask.abort",
    "werkzeug.exceptions.abort",
}
RESPONSE_LIKE_CALLS = {
    "rest_framework.response.Response",
    "django.http.HttpResponse",
    "django.http.JsonResponse",
    "django.http.response.HttpResponse",
    "django.http.response.JsonResponse",
}
AUTHZ_ATTRIBUTE_CHECKS = {
    "request.user.is_authenticated": "authenticated",
    "request.user.is_staff": "privileged",
    "request.user.is_superuser": "privileged",
    "current_user.is_authenticated": "authenticated",
}
AUTHZ_FAILURE_STATUS_CODES = set(AUTHZ_FAILURE_STATUS_CODES_BY_SYMBOL.values())


@dataclass(frozen=True)
class AuthzSurfaceExtraction:
    entities: list[Entity]
    facts: list[Fact]
    evidence: list[Evidence]
    recognized_framework: bool
    recognized_import_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ParsedFile:
    path: Path
    module_name: str
    tree: ast.AST


@dataclass(frozen=True)
class _SymbolRef:
    entity: Entity
    module_name: str
    qualname: str
    short_name: str
    node: ast.AST


def extract_python_authz_surface(
    repo: RepoSnapshot,
    parsed_files: dict[Path, ast.AST],
    *,
    tenant_id: str,
    source_system: str,
) -> AuthzSurfaceExtraction:
    files = [
        _ParsedFile(path=file_path, module_name=_module_name(repo, file_path), tree=tree)
        for file_path, tree in parsed_files.items()
    ]
    recognized_import_roots = tuple(sorted({root for file in files for root in _framework_import_roots(file.tree)}))
    candidate_files = [
        file
        for file in files
        if _has_framework_import(file.tree) or file.path.name == "urls.py" or _has_route_decorator(file.tree)
    ]
    if not candidate_files:
        return AuthzSurfaceExtraction(
            entities=[],
            facts=[],
            evidence=[],
            recognized_framework=bool(recognized_import_roots),
            recognized_import_roots=recognized_import_roots,
        )

    symbols = _collect_class_and_function_symbols(repo, files, tenant_id=tenant_id)
    symbols_by_full_name = {f"{symbol.module_name}.{symbol.qualname}": symbol for symbol in symbols}
    symbols_by_node_id = {id(symbol.node): symbol for symbol in symbols}
    candidate_module_names = {file.module_name for file in candidate_files}
    symbols_by_short_name = _unique_by_short_name(
        [symbol for symbol in symbols if symbol.module_name in candidate_module_names]
    )
    file_by_module = {file.module_name: file.path for file in files}

    entities: list[Entity] = []
    facts: list[Fact] = []
    evidence: list[Evidence] = []
    seen_entities: set[str] = set()
    seen_facts: set[str] = set()

    def add_entity(entity: Entity, file_path: Path, line_start: int, line_end: int) -> None:
        if entity.entity_id in seen_entities:
            return
        seen_entities.add(entity.entity_id)
        entities.append(entity)
        evidence.append(
            Evidence(
                target_type="entity",
                target_id=entity.entity_id,
                derivation_class="deterministic_static",
                source_system=source_system,
                source_ref={"extractor": source_system, "entity_kind": entity.kind, "surface": "authz"},
                bytes_ref=_bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    def add_fact(
        predicate: str,
        subject: Entity,
        object_: Entity,
        qualifier: JsonObject,
        file_path: Path,
        line_start: int,
        line_end: int,
    ) -> None:
        fact = Fact(predicate, subject.entity_id, object_.entity_id, qualifier)
        if fact.fact_id in seen_facts:
            return
        seen_facts.add(fact.fact_id)
        facts.append(fact)
        evidence.append(
            Evidence(
                target_type="fact",
                target_id=fact.fact_id,
                derivation_class="deterministic_static",
                source_system=source_system,
                source_ref={"extractor": source_system, "predicate": predicate, "surface": "authz"},
                bytes_ref=_bytes_ref(repo, file_path, line_start, line_end),
                confidence=1.0,
            )
        )

    def add_symbol_entity(symbol: _SymbolRef) -> None:
        file_path = file_by_module.get(symbol.module_name)
        if file_path is None:
            return
        add_entity(
            symbol.entity,
            file_path,
            int(symbol.entity.properties.get("line") or 1),
            int(symbol.entity.properties.get("end_line") or symbol.entity.properties.get("line") or 1),
        )

    for file in candidate_files:
        imports = _ImportResolver.from_module(file.module_name, file.tree)
        drf_view_method_node_ids = _drf_view_method_node_ids(file.tree, imports)
        drf_permission_class_names = _drf_permission_class_names(file.tree, imports)
        for node in ast.walk(file.tree):
            if isinstance(node, ast.ClassDef):
                class_symbol = symbols_by_full_name.get(f"{file.module_name}.{node.name}")
                if class_symbol is None:
                    continue
                if node.name in drf_permission_class_names:
                    add_symbol_entity(class_symbol)
                    base_policy = _external_symbol(repo, "rest_framework.permissions", "BasePermission", tenant_id)
                    add_entity(base_policy, file.path, getattr(node, "lineno", 1), getattr(node, "lineno", 1))
                    add_fact(
                        "DEFINES_AUTHZ_POLICY",
                        class_symbol.entity,
                        base_policy,
                        {
                            "framework": "django",
                            "source_kind": "drf_permission_class",
                            "policy": class_symbol.short_name,
                            "methods": _permission_methods(node),
                        },
                        file.path,
                        getattr(node, "lineno", 1),
                        getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                    )
                for policy_expr, policy_line in _permission_class_values(node):
                    policy = _policy_entity(
                        repo,
                        policy_expr,
                        imports,
                        symbols_by_full_name,
                        symbols_by_short_name,
                        tenant_id,
                    )
                    if policy is None:
                        continue
                    add_symbol_entity(class_symbol)
                    local_policy_symbol = symbols_by_short_name.get(policy.name)
                    if local_policy_symbol is not None and policy.entity.entity_id == local_policy_symbol.entity.entity_id:
                        add_symbol_entity(local_policy_symbol)
                    else:
                        add_entity(policy.entity, file.path, policy_line, policy_line)
                    add_fact(
                        "APPLIES_AUTHZ_POLICY",
                        class_symbol.entity,
                        policy.entity,
                        {
                            "framework": "django",
                            "source_kind": "drf_permission_classes",
                            "policy": policy.name,
                            "access_level": policy.access_level,
                        },
                        file.path,
                        policy_line,
                        policy_line,
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = symbols_by_node_id.get(id(node))
                if symbol is None:
                    continue
                endpoints = _flask_route_endpoints(repo, node, tenant_id)
                if endpoints:
                    add_symbol_entity(symbol)
                for endpoint in endpoints:
                    add_entity(endpoint.entity, file.path, endpoint.line, endpoint.line)
                    add_fact(
                        "HANDLES_ENDPOINT",
                        symbol.entity,
                        endpoint.entity,
                        {
                            "framework": "flask",
                            "source_kind": endpoint.source_kind,
                            "method": endpoint.method,
                            "path": endpoint.path,
                            "link_confidence": "decorator_declared",
                        },
                        file.path,
                        endpoint.line,
                        endpoint.line,
                    )
                policies = _decorator_policies(repo, node.decorator_list, imports, tenant_id)
                if policies:
                    add_symbol_entity(symbol)
                for policy in policies:
                    add_entity(policy.entity, file.path, policy.line, policy.line)
                    add_fact(
                        "APPLIES_AUTHZ_POLICY",
                        symbol.entity,
                        policy.entity,
                        {
                            "framework": policy.framework,
                            "source_kind": "authz_decorator",
                            "policy": policy.name,
                            "access_level": policy.access_level,
                        },
                        file.path,
                        policy.line,
                        policy.line,
                    )
                checks = _body_authz_checks(
                    repo,
                    node,
                    imports,
                    file.module_name,
                    symbols_by_full_name,
                    file_by_module,
                    tenant_id,
                    allow_drf_self_checks=id(node) in drf_view_method_node_ids,
                    allow_request_user_checks=bool(endpoints or policies) or id(node) in drf_view_method_node_ids,
                )
                if checks:
                    add_symbol_entity(symbol)
                for check in checks:
                    check_entity_file = check.entity_file_path or file.path
                    check_entity_line = check.entity_line or check.line
                    add_entity(check.entity, check_entity_file, check_entity_line, check_entity_line)
                    qualifier = {
                        "framework": check.framework,
                        "source_kind": check.source_kind,
                        "check": check.name,
                        "access_level": check.access_level,
                    }
                    if check.guard_intent is not None:
                        qualifier["guard_intent"] = check.guard_intent
                    add_fact(
                        "USES_AUTHZ_CHECK",
                        symbol.entity,
                        check.entity,
                        qualifier,
                        file.path,
                        check.line,
                        check.line,
                    )

        for route in _django_route_handlers(repo, file, symbols_by_full_name, symbols_by_short_name, tenant_id):
            add_symbol_entity(route.handler)
            add_entity(route.endpoint, file.path, route.line, route.line)
            add_fact(
                "HANDLES_ENDPOINT",
                route.handler.entity,
                route.endpoint,
                {
                    "framework": "django",
                    "source_kind": route.source_kind,
                    "method": "ANY",
                    "path": route.path,
                    "handler": route.handler.short_name,
                    "link_confidence": "handler_expression",
                },
                file.path,
                route.line,
                route.line,
            )

    return AuthzSurfaceExtraction(
        entities=entities,
        facts=facts,
        evidence=evidence,
        recognized_framework=bool(recognized_import_roots),
        recognized_import_roots=recognized_import_roots,
    )


@dataclass(frozen=True)
class _Policy:
    entity: Entity
    name: str
    access_level: str
    framework: str = "django"
    line: int = 1


@dataclass(frozen=True)
class _EndpointBinding:
    entity: Entity
    method: str
    path: str
    line: int
    source_kind: str


@dataclass(frozen=True)
class _AuthzCheck:
    entity: Entity
    name: str
    source_kind: str
    access_level: str
    framework: str
    line: int
    entity_file_path: Path | None = None
    entity_line: int | None = None
    guard_intent: str | None = None


@dataclass(frozen=True)
class _DjangoRouteBinding:
    handler: _SymbolRef
    endpoint: Entity
    path: str
    line: int
    source_kind: str


def _collect_class_and_function_symbols(repo: RepoSnapshot, files: list[_ParsedFile], *, tenant_id: str) -> list[_SymbolRef]:
    symbols: list[_SymbolRef] = []
    for file in files:
        if not isinstance(file.tree, ast.Module):
            continue

        def add_symbol(node: ast.AST, qualname: str, symbol_kind: str) -> None:
            entity = Entity(
                kind="CodeSymbol",
                identity={
                    "tenant_id": tenant_id,
                    "repo": repo.name,
                    "module": file.module_name,
                    "qualname": qualname,
                    "symbol_kind": symbol_kind,
                },
                properties={
                    "path": str(file.path.relative_to(repo.root)),
                    "line": getattr(node, "lineno", 1),
                    "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                },
            )
            symbols.append(_SymbolRef(entity, file.module_name, qualname, qualname.rsplit(".", 1)[-1], node))

        def visit(body: list[ast.stmt], prefix: str = "") -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    add_symbol(node, qualname, "class")
                    visit(node.body, qualname)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualname = f"{prefix}.{node.name}" if prefix else node.name
                    symbol_kind = (
                        "method" if prefix else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
                    )
                    add_symbol(node, qualname, symbol_kind)

        visit(file.tree.body)
    return symbols


def _unique_by_short_name(symbols: list[_SymbolRef]) -> dict[str, _SymbolRef]:
    counts: dict[str, int] = {}
    for symbol in symbols:
        counts[symbol.short_name] = counts.get(symbol.short_name, 0) + 1
    # Short-name policy linking is allowed only when globally unique to avoid cross-file misattribution.
    return {symbol.short_name: symbol for symbol in symbols if counts[symbol.short_name] == 1}


def _drf_permission_class_names(tree: ast.AST, imports: "_ImportResolver") -> set[str]:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    permission_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in permission_names:
                continue
            if _is_drf_permission_class(node, imports, permission_names):
                permission_names.add(node.name)
                changed = True
    return permission_names


def _is_drf_permission_class(
    node: ast.ClassDef,
    imports: "_ImportResolver",
    local_permission_class_names: set[str],
) -> bool:
    for base in node.bases:
        dotted = _dotted_name(base)
        if dotted is None:
            continue
        if dotted in local_permission_class_names:
            return True
        resolved = imports.resolve_alias(dotted) or dotted
        if resolved in DRF_PERMISSION_BASES:
            return True
    return False


def _permission_methods(node: ast.ClassDef) -> list[str]:
    methods = [
        statement.name
        for statement in node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in {"has_permission", "has_object_permission"}
    ]
    return sorted(methods)


def _permission_class_values(node: ast.ClassDef) -> list[tuple[ast.AST, int]]:
    values: list[tuple[ast.AST, int]] = []
    for statement in node.body:
        if _assignment_target_name(statement) != "permission_classes":
            continue
        value = _assignment_value(statement)
        line = getattr(statement, "lineno", getattr(value, "lineno", getattr(node, "lineno", 1)))
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            values.extend((element, line) for element in value.elts)
        elif value is not None:
            values.append((value, line))
    return values


def _policy_entity(
    repo: RepoSnapshot,
    expr: ast.AST,
    imports: "_ImportResolver",
    symbols_by_full_name: dict[str, _SymbolRef],
    symbols_by_short_name: dict[str, _SymbolRef],
    tenant_id: str,
) -> _Policy | None:
    dotted = _dotted_name(expr)
    if dotted is None and isinstance(expr, ast.Call):
        dotted = _dotted_name(expr.func)
    if dotted is None:
        return None
    resolved = imports.resolve_alias(dotted) or dotted
    name = resolved.rsplit(".", 1)[-1]
    local_full_symbol = symbols_by_full_name.get(resolved)
    if local_full_symbol is not None and local_full_symbol.entity.identity.get("symbol_kind") == "class":
        return _Policy(
            entity=local_full_symbol.entity,
            name=name,
            access_level="custom_policy",
            framework="custom",
            line=getattr(expr, "lineno", 1),
        )
    local_symbol = symbols_by_short_name.get(name)
    if local_symbol is not None and local_symbol.entity.identity.get("symbol_kind") == "class":
        return _Policy(
            entity=local_symbol.entity,
            name=name,
            access_level="custom_policy",
            framework="custom",
            line=getattr(expr, "lineno", 1),
        )
    if "." not in resolved:
        return None
    framework = "django" if resolved.startswith(("django.", "rest_framework.")) else "custom"
    return _Policy(
        entity=_external_symbol(repo, resolved.rsplit(".", 1)[0], name, tenant_id),
        name=name,
        access_level=DRF_PERMISSION_CLASS_ACCESS.get(name, "custom_policy") if framework == "django" else "custom_policy",
        framework=framework,
        line=getattr(expr, "lineno", 1),
    )


def _decorator_policies(
    repo: RepoSnapshot,
    decorators: list[ast.expr],
    imports: "_ImportResolver",
    tenant_id: str,
) -> list[_Policy]:
    policies: list[_Policy] = []
    for decorator in decorators:
        dotted = _decorator_name(decorator)
        if dotted is None:
            continue
        resolved = imports.resolve_alias(dotted)
        if resolved is None:
            continue
        access_level = AUTHZ_DECORATOR_ACCESS.get(resolved)
        if access_level is None:
            continue
        name = resolved.rsplit(".", 1)[-1]
        module = resolved.rsplit(".", 1)[0]
        policies.append(
            _Policy(
                entity=_external_symbol(repo, module, name, tenant_id),
                name=name,
                access_level=access_level,
                framework="django" if resolved.startswith("django.") else "flask",
                line=getattr(decorator, "lineno", 1),
            )
        )
    return policies


def _drf_view_method_node_ids(tree: ast.AST, imports: "_ImportResolver") -> set[int]:
    method_ids: set[int] = set()
    drf_class_names = _drf_view_class_names(tree, imports)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name not in drf_class_names:
            continue
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_ids.add(id(statement))
    return method_ids


def _drf_view_class_names(tree: ast.AST, imports: "_ImportResolver") -> set[str]:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    drf_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in drf_names:
                continue
            if _is_drf_view_class(node, imports, drf_names):
                drf_names.add(node.name)
                changed = True
    return drf_names


def _is_drf_view_class(node: ast.ClassDef, imports: "_ImportResolver", local_drf_class_names: set[str]) -> bool:
    for base in node.bases:
        dotted = _dotted_name(base)
        if dotted is None:
            continue
        if dotted in local_drf_class_names:
            return True
        resolved = imports.resolve_alias(dotted)
        if resolved is None:
            continue
        base_name = resolved.rsplit(".", 1)[-1]
        if resolved.startswith(("rest_framework.views.", "rest_framework.generics.", "rest_framework.viewsets.")):
            return True
        if resolved.startswith("rest_framework.") and base_name in DRF_VIEW_BASE_NAMES:
            return True
    return False


def _body_authz_checks(
    repo: RepoSnapshot,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
    file_by_module: dict[str, Path],
    tenant_id: str,
    *,
    allow_drf_self_checks: bool,
    allow_request_user_checks: bool,
) -> list[_AuthzCheck]:
    checks: list[_AuthzCheck] = []
    seen: set[tuple[str, int, str]] = set()
    for child in ast.walk(node):
        check: _AuthzCheck | None = None
        if isinstance(child, ast.Call):
            dotted = _dotted_name(child.func)
            if dotted is not None:
                resolved = imports.resolve_alias(dotted)
                access_level = AUTHZ_METHOD_CALL_ACCESS.get(dotted)
                if access_level is not None and _authz_method_call_allowed(
                    dotted,
                    allow_drf_self_checks=allow_drf_self_checks,
                    allow_request_user_checks=allow_request_user_checks,
                ):
                    check = _authz_check(repo, dotted, "authz_call", access_level, child, tenant_id)
                elif resolved in AUTHZ_EXCEPTION_ACCESS:
                    check = _authz_check(repo, resolved, "authz_exception", AUTHZ_EXCEPTION_ACCESS[resolved], child, tenant_id)
        elif isinstance(child, ast.Raise):
            dotted = _raise_exception_name(child)
            if dotted is not None:
                resolved = imports.resolve_alias(dotted)
                if resolved in AUTHZ_EXCEPTION_ACCESS:
                    check = _authz_check(repo, resolved, "authz_exception", AUTHZ_EXCEPTION_ACCESS[resolved], child, tenant_id)
        elif isinstance(child, ast.Attribute):
            dotted = _dotted_name(child)
            if dotted is not None and dotted in AUTHZ_ATTRIBUTE_CHECKS:
                check = _authz_check(repo, dotted, "authz_attribute_check", AUTHZ_ATTRIBUTE_CHECKS[dotted], child, tenant_id)
        if check is None:
            continue
        key = (check.name, check.line, check.source_kind)
        if key in seen:
            continue
        seen.add(key)
        checks.append(check)
    for check in _custom_guard_checks(repo, node, imports, module_name, symbols_by_full_name, file_by_module, tenant_id):
        key = (check.name, check.line, check.source_kind)
        if key in seen:
            continue
        seen.add(key)
        checks.append(check)
    return checks


@dataclass(frozen=True)
class _CallRef:
    dotted: str
    line: int


def _custom_guard_checks(
    repo: RepoSnapshot,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
    file_by_module: dict[str, Path],
    tenant_id: str,
) -> list[_AuthzCheck]:
    checks: list[_AuthzCheck] = []
    assignments: dict[str, _CallRef] = {}

    def visit_statements(statements: list[ast.stmt], inherited_assignments: dict[str, _CallRef]) -> None:
        local_assignments = dict(inherited_assignments)
        for statement in statements:
            assignment = _guard_call_assignment(statement, imports, module_name, symbols_by_full_name)
            if assignment is not None:
                name, call_ref = assignment
                local_assignments[name] = call_ref
            if isinstance(statement, ast.If):
                guarded_calls = _guarded_calls_from_test(
                    statement.test,
                    local_assignments,
                    imports,
                    module_name,
                    symbols_by_full_name,
                )
                if guarded_calls and _contains_auth_failure_outcome(statement.body, imports):
                    for call_ref in guarded_calls:
                        checks.append(_custom_guard_check(repo, call_ref, symbols_by_full_name, file_by_module, tenant_id))
                visit_statements(statement.body, local_assignments)
                visit_statements(statement.orelse, local_assignments)
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)):
                for nested in _nested_statement_blocks(statement):
                    visit_statements(nested, local_assignments)

    visit_statements(node.body, assignments)
    return checks


def _guard_call_assignment(
    statement: ast.stmt,
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
) -> tuple[str, _CallRef] | None:
    target_name = _assignment_target_name(statement)
    value = _assignment_value(statement)
    if target_name is None or not isinstance(value, ast.Call):
        return None
    call_ref = _authz_guard_call_ref(value, imports, module_name, symbols_by_full_name)
    if call_ref is None:
        return None
    return target_name, call_ref


def _guarded_calls_from_test(
    test: ast.AST,
    assignments: dict[str, _CallRef],
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
) -> list[_CallRef]:
    calls: list[_CallRef] = []
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        calls.extend(_guarded_calls_from_operand(test.operand, assignments, imports, module_name, symbols_by_full_name))
    elif isinstance(test, ast.Compare) and _is_none_check(test):
        calls.extend(_guarded_calls_from_operand(test.left, assignments, imports, module_name, symbols_by_full_name))
        for comparator in test.comparators:
            calls.extend(_guarded_calls_from_operand(comparator, assignments, imports, module_name, symbols_by_full_name))
    return calls


def _guarded_calls_from_operand(
    operand: ast.AST,
    assignments: dict[str, _CallRef],
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
) -> list[_CallRef]:
    if isinstance(operand, ast.Name):
        call_ref = assignments.get(operand.id)
        return [call_ref] if call_ref is not None else []
    if isinstance(operand, ast.Call):
        call_ref = _authz_guard_call_ref(operand, imports, module_name, symbols_by_full_name)
        return [call_ref] if call_ref is not None else []
    return []


def _authz_guard_call_ref(
    call: ast.Call,
    imports: "_ImportResolver",
    module_name: str,
    symbols_by_full_name: dict[str, _SymbolRef],
) -> _CallRef | None:
    dotted = _dotted_name(call.func)
    if dotted is None:
        return None
    resolved = imports.resolve_alias(dotted)
    if resolved is None:
        if "." in dotted:
            return None
        same_module = f"{module_name}.{dotted}"
        if same_module in symbols_by_full_name:
            resolved = same_module
        else:
            return None
    return _CallRef(dotted=resolved, line=getattr(call, "lineno", 1))


def _custom_guard_check(
    repo: RepoSnapshot,
    call_ref: _CallRef,
    symbols_by_full_name: dict[str, _SymbolRef],
    file_by_module: dict[str, Path],
    tenant_id: str,
) -> _AuthzCheck:
    local_symbol = symbols_by_full_name.get(call_ref.dotted)
    if local_symbol is not None:
        entity_line = int(local_symbol.entity.properties.get("line") or 1)
        return _AuthzCheck(
            entity=local_symbol.entity,
            name=local_symbol.short_name,
            source_kind="custom_guard_call",
            access_level="custom_security_guard",
            framework="custom",
            line=call_ref.line,
            entity_file_path=file_by_module.get(local_symbol.module_name),
            entity_line=entity_line,
            guard_intent="unknown",
        )
    module = call_ref.dotted.rsplit(".", 1)[0] if "." in call_ref.dotted else "python.authz"
    name = call_ref.dotted.rsplit(".", 1)[-1]
    return _AuthzCheck(
        entity=_external_symbol(repo, module, name, tenant_id),
        name=name,
        source_kind="custom_guard_call",
        access_level="custom_security_guard",
        framework="custom",
        line=call_ref.line,
        guard_intent="unknown",
    )


def _is_none_check(node: ast.Compare) -> bool:
    operators = node.ops
    comparators = node.comparators
    if len(operators) != 1 or len(comparators) != 1:
        return False
    if not isinstance(operators[0], (ast.Is, ast.IsNot, ast.Eq, ast.NotEq)):
        return False
    return _is_none_literal(node.left) or _is_none_literal(comparators[0])


def _is_none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _contains_auth_failure_outcome(statements: list[ast.stmt], imports: "_ImportResolver") -> bool:
    for statement in statements:
        if isinstance(statement, ast.Return) and _return_has_auth_failure_outcome(statement.value, imports):
            return True
        if isinstance(statement, ast.Raise):
            dotted = _raise_exception_name(statement)
            resolved = imports.resolve_alias(dotted) if dotted is not None else None
            if resolved in AUTHZ_EXCEPTION_ACCESS:
                return True
    return False


def _return_has_auth_failure_outcome(value: ast.AST | None, imports: "_ImportResolver") -> bool:
    if value is None:
        return False
    if isinstance(value, ast.Tuple):
        return any(_status_code(element, imports) in AUTHZ_FAILURE_STATUS_CODES for element in value.elts)
    if isinstance(value, ast.Call):
        call_name = _resolved_call_name(value, imports)
        if call_name in AUTHZ_FAILURE_RESPONSE_CALLS:
            return True
        if call_name in AUTHZ_ABORT_CALLS and value.args:
            return _status_code(value.args[0], imports) in AUTHZ_FAILURE_STATUS_CODES
        if _is_response_like_call(value, imports):
            for keyword in value.keywords:
                if keyword.arg == "status" and _status_code(keyword.value, imports) in AUTHZ_FAILURE_STATUS_CODES:
                    return True
            if len(value.args) >= 2:
                return _status_code(value.args[1], imports) in AUTHZ_FAILURE_STATUS_CODES
    return _status_code(value, imports) in AUTHZ_FAILURE_STATUS_CODES


def _status_code(node: ast.AST, imports: "_ImportResolver") -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    dotted = _dotted_name(node)
    if dotted is None:
        return None
    resolved = imports.resolve_alias(dotted)
    if resolved is None:
        return None
    return AUTHZ_FAILURE_STATUS_CODES_BY_SYMBOL.get(resolved)


def _is_response_like_call(node: ast.Call, imports: "_ImportResolver") -> bool:
    return _resolved_call_name(node, imports) in RESPONSE_LIKE_CALLS


def _resolved_call_name(node: ast.Call, imports: "_ImportResolver") -> str | None:
    dotted = _dotted_name(node.func)
    if dotted is None:
        return None
    return imports.resolve_alias(dotted) or dotted


def _nested_statement_blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    blocks: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        value = getattr(statement, attr, None)
        if isinstance(value, list):
            blocks.append([item for item in value if isinstance(item, ast.stmt)])
    handlers = getattr(statement, "handlers", None)
    if isinstance(handlers, list):
        for handler in handlers:
            body = getattr(handler, "body", None)
            if isinstance(body, list):
                blocks.append([item for item in body if isinstance(item, ast.stmt)])
    cases = getattr(statement, "cases", None)
    if isinstance(cases, list):
        for case in cases:
            body = getattr(case, "body", None)
            if isinstance(body, list):
                blocks.append([item for item in body if isinstance(item, ast.stmt)])
    return blocks


def _authz_method_call_allowed(
    dotted: str,
    *,
    allow_drf_self_checks: bool,
    allow_request_user_checks: bool,
) -> bool:
    if dotted.startswith("self."):
        return allow_drf_self_checks
    if dotted == "request.user.has_perm":
        return allow_request_user_checks
    return True


def _authz_check(
    repo: RepoSnapshot,
    dotted: str,
    source_kind: str,
    access_level: str,
    node: ast.AST,
    tenant_id: str,
) -> _AuthzCheck:
    module = dotted.rsplit(".", 1)[0] if "." in dotted else "python.authz"
    name = dotted.rsplit(".", 1)[-1]
    return _AuthzCheck(
        entity=_external_symbol(repo, module, name, tenant_id),
        name=name,
        source_kind=source_kind,
        access_level=access_level,
        framework="django" if module.startswith(("django", "rest_framework")) else "python",
        line=getattr(node, "lineno", 1),
    )


def _flask_route_endpoints(
    repo: RepoSnapshot,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    tenant_id: str,
) -> list[_EndpointBinding]:
    endpoints: list[_EndpointBinding] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            continue
        method_name = func.attr.lower()
        if method_name != "route" and method_name not in {"get", "post", "put", "delete", "patch"}:
            continue
        path = _string_arg(decorator, 0)
        if path is None:
            continue
        method = _http_method_from_route_call(decorator) if method_name == "route" else method_name.upper()
        endpoints.append(
            _EndpointBinding(
                entity=endpoint_entity(repo, method, path, tenant_id=tenant_id),
                method=method,
                path=path,
                line=getattr(decorator, "lineno", 1),
                source_kind=f"flask_{method_name}",
            )
        )
    return endpoints


def _django_route_handlers(
    repo: RepoSnapshot,
    file: _ParsedFile,
    symbols_by_full_name: dict[str, _SymbolRef],
    symbols_by_short_name: dict[str, _SymbolRef],
    tenant_id: str,
) -> list[_DjangoRouteBinding]:
    bindings: list[_DjangoRouteBinding] = []
    if not isinstance(file.tree, ast.Module):
        return bindings
    names = _DjangoUrlNames.from_module(file.tree, file.path)
    imports = _ImportResolver.from_module(file.module_name, file.tree)
    for node in ast.walk(file.tree):
        if not isinstance(node, ast.Call):
            continue
        source_kind = names.source_kind(node)
        if source_kind is None:
            continue
        path = _string_arg(node, 0)
        handler_name = _django_handler_name(node)
        if path is None or handler_name is None:
            continue
        handler = _django_handler_symbol(node, imports, symbols_by_full_name, symbols_by_short_name)
        if handler is None:
            continue
        bindings.append(
            _DjangoRouteBinding(
                handler=handler,
                endpoint=endpoint_entity(repo, "ANY", path, tenant_id=tenant_id),
                path=path,
                line=getattr(node, "lineno", 1),
                source_kind=source_kind,
            )
        )
    return bindings


def _django_handler_symbol(
    node: ast.Call,
    imports: "_ImportResolver",
    symbols_by_full_name: dict[str, _SymbolRef],
    symbols_by_short_name: dict[str, _SymbolRef],
) -> _SymbolRef | None:
    if len(node.args) <= 1:
        return None
    expr = node.args[1]
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "include":
        return None
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "as_view":
        expr = expr.func.value
    dotted = _dotted_name(expr)
    if dotted is None:
        return None
    resolved = imports.resolve_alias(dotted)
    if resolved is not None:
        resolved_symbol = symbols_by_full_name.get(resolved)
        if resolved_symbol is not None:
            return resolved_symbol
        return None
    return symbols_by_short_name.get(dotted.rsplit(".", 1)[-1])


def _django_handler_name(node: ast.Call) -> str | None:
    if len(node.args) <= 1:
        return None
    expr = node.args[1]
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "include":
        return None
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "as_view":
        return _tail_name(expr.func.value)
    return _tail_name(expr)


class _DjangoUrlNames:
    def __init__(self, path_names: set[str], re_path_names: set[str], file_path: Path) -> None:
        self.path_names = path_names
        self.re_path_names = re_path_names
        self.file_path = file_path

    @classmethod
    def from_module(cls, tree: ast.Module, file_path: Path) -> "_DjangoUrlNames":
        path_names: set[str] = set()
        re_path_names: set[str] = set()
        for statement in tree.body:
            if not isinstance(statement, ast.ImportFrom) or statement.module != "django.urls":
                continue
            for alias in statement.names:
                local = alias.asname or alias.name
                if alias.name == "path":
                    path_names.add(local)
                elif alias.name == "re_path":
                    re_path_names.add(local)
        return cls(path_names, re_path_names, file_path)

    def source_kind(self, node: ast.Call) -> str | None:
        if not isinstance(node.func, ast.Name):
            return None
        name = node.func.id
        if name in self.path_names:
            return "django_path"
        if name in self.re_path_names:
            return "django_re_path"
        return None


class _ImportResolver:
    def __init__(self, module_name: str, aliases: dict[str, str]) -> None:
        self.module_name = module_name
        self.aliases = aliases

    @classmethod
    def from_module(cls, module_name: str, tree: ast.AST) -> "_ImportResolver":
        aliases: dict[str, str] = {}
        if not isinstance(tree, ast.Module):
            return cls(module_name, aliases)
        for statement in tree.body:
            if isinstance(statement, ast.ImportFrom):
                source_module = _resolve_import_from_module(module_name, statement)
                for alias in statement.names:
                    local = alias.asname or alias.name
                    aliases[local] = f"{source_module}.{alias.name}" if source_module else alias.name
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    local = alias.asname or alias.name.split(".", 1)[0]
                    aliases[local] = alias.name
        return cls(module_name, aliases)

    def resolve_alias(self, name: str) -> str | None:
        return _resolve_alias_with_map(self.aliases, name)


def _framework_import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    if not isinstance(tree, ast.Module):
        return roots
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom):
            root = (statement.module or "").split(".", 1)[0]
            if root in FRAMEWORK_IMPORT_ROOTS:
                roots.add(root)
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                root = alias.name.split(".", 1)[0]
                if root in FRAMEWORK_IMPORT_ROOTS:
                    roots.add(root)
    return roots


def _has_framework_import(tree: ast.AST) -> bool:
    return bool(_framework_import_roots(tree))


def _has_route_decorator(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr.lower() in {"route", "get", "post", "put", "delete", "patch"}:
                    return True
    return False


def _external_symbol(repo: RepoSnapshot, module: str, name: str, tenant_id: str) -> Entity:
    return Entity(
        kind="ExternalSymbol",
        identity={
            "tenant_id": tenant_id,
            "repo": repo.name,
            "language": "python",
            "module": module,
            "name": name,
            "symbol_kind": "authz",
        },
        properties={},
    )


def _module_name(repo: RepoSnapshot, file_path: Path) -> str:
    relative = file_path.relative_to(repo.root).with_suffix("")
    parts = [part for part in relative.parts if part != "__init__"]
    return ".".join(parts) if parts else file_path.stem


def _resolve_import_from_module(current_module: str, statement: ast.ImportFrom) -> str:
    module = statement.module or ""
    if statement.level <= 0:
        return module
    parts = current_module.split(".")
    package_parts = parts[: max(0, len(parts) - statement.level)]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(part for part in package_parts if part)


def _resolve_alias_with_map(aliases: dict[str, str], name: str) -> str | None:
    if name in aliases:
        return aliases[name]
    parts = name.split(".")
    if not parts:
        return None
    root = aliases.get(parts[0])
    if root is None:
        return None
    return ".".join([root, *parts[1:]])


def _dotted_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _tail_name(node: ast.AST) -> str | None:
    dotted = _dotted_name(node)
    if dotted is None:
        return None
    return dotted.rsplit(".", 1)[-1]


def _decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return _dotted_name(node)


def _raise_exception_name(node: ast.Raise) -> str | None:
    exc = node.exc
    if isinstance(exc, ast.Call):
        return _dotted_name(exc.func)
    return _dotted_name(exc)


def _assignment_target_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            if isinstance(target, ast.Name):
                return target.id
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id
    return None


def _assignment_value(statement: ast.stmt) -> ast.AST | None:
    if isinstance(statement, ast.Assign):
        return statement.value
    if isinstance(statement, ast.AnnAssign):
        return statement.value
    return None


def _string_arg(node: ast.Call, position: int) -> str | None:
    if len(node.args) <= position:
        return None
    value = node.args[position]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _http_method_from_route_call(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg != "methods":
            continue
        methods = _string_sequence(keyword.value)
        return methods[0].upper() if len(methods) == 1 else "ANY"
    return "ANY"


def _string_sequence(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return []
    values: list[str] = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            values.append(element.value)
    return values


def _bytes_ref(repo: RepoSnapshot, file_path: Path, line_start: int, line_end: int) -> JsonObject:
    return {
        "repo": repo.name,
        "path": str(file_path.relative_to(repo.root)),
        "line_start": line_start,
        "line_end": line_end,
    }
