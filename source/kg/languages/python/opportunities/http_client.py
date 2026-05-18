from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.metrics.opportunity import Opportunity


HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "request"})
MODULES = frozenset({"requests", "httpx", "aiohttp"})
CLIENT_FACTORIES = {
    ("requests", "Session"),
    ("httpx", "Client"),
    ("httpx", "AsyncClient"),
    ("aiohttp", "ClientSession"),
}


@dataclass(frozen=True)
class HttpClientOpportunityDetector:
    def detect(self, repo: RepoSnapshot, dimension: str | None = None) -> tuple[Opportunity, ...]:
        opportunities: list[Opportunity] = []
        for path in repo.files_by_language.get("python", ()):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
            except (OSError, SyntaxError, ValueError):
                continue
            scanner = _ScopeScanner(repo, path, dimension)
            opportunities.extend(scanner.scan_module(tree))
        return tuple(opportunities)


@dataclass
class _Scope:
    parent: "_Scope | None" = None
    module_aliases: dict[str, str] = field(default_factory=dict)
    function_aliases: dict[str, tuple[str, str]] = field(default_factory=dict)
    client_aliases: dict[str, str] = field(default_factory=dict)
    shadowed_names: set[str] = field(default_factory=set)

    def child(self, shadowed_names: Iterable[str]) -> "_Scope":
        return _Scope(parent=self, shadowed_names=set(shadowed_names))

    def resolve_module(self, name: str) -> str | None:
        if name in self.module_aliases:
            return self.module_aliases[name]
        if name in self.shadowed_names:
            return None
        return self.parent.resolve_module(name) if self.parent is not None else None

    def resolve_function(self, name: str) -> tuple[str, str] | None:
        if name in self.function_aliases:
            return self.function_aliases[name]
        if name in self.shadowed_names:
            return None
        return self.parent.resolve_function(name) if self.parent is not None else None

    def resolve_client(self, name: str) -> str | None:
        if name in self.client_aliases:
            return self.client_aliases[name]
        if name in self.shadowed_names:
            return None
        return self.parent.resolve_client(name) if self.parent is not None else None

    def bind_module(self, name: str, module: str) -> None:
        self.module_aliases[name] = module
        self.function_aliases.pop(name, None)
        self.client_aliases.pop(name, None)
        self.shadowed_names.discard(name)

    def bind_function(self, name: str, module: str, method: str) -> None:
        self.function_aliases[name] = (module, method)
        self.module_aliases.pop(name, None)
        self.client_aliases.pop(name, None)
        self.shadowed_names.discard(name)

    def bind_client(self, name: str, module: str) -> None:
        self.client_aliases[name] = module
        self.module_aliases.pop(name, None)
        self.function_aliases.pop(name, None)
        self.shadowed_names.discard(name)

    def shadow(self, name: str) -> None:
        self.module_aliases.pop(name, None)
        self.function_aliases.pop(name, None)
        self.client_aliases.pop(name, None)
        self.shadowed_names.add(name)


@dataclass
class _ScopeScanner:
    repo: RepoSnapshot
    path: Path
    dimension: str | None

    def scan_module(self, tree: ast.AST) -> tuple[Opportunity, ...]:
        if not isinstance(tree, ast.Module):
            return ()
        return tuple(self._scan_statements(tree.body, _Scope()))

    def _scan_statements(
        self,
        statements: list[ast.stmt],
        scope: _Scope,
        function_parent_scope: _Scope | None = None,
    ) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._bind_import(statement, scope)
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                opportunities.extend(self._scan_function(statement, function_parent_scope or scope))
                scope.shadow(statement.name)
                continue
            if isinstance(statement, ast.ClassDef):
                opportunities.extend(self._scan_class(statement, scope, function_parent_scope or scope))
                scope.shadow(statement.name)
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    opportunities.extend(self._opportunities_in_node(item.context_expr, scope))
                    if item.optional_vars is not None:
                        self._bind_target(item.optional_vars, scope, _client_factory_module(item.context_expr, scope))
                opportunities.extend(self._scan_statements(statement.body, scope, function_parent_scope))
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                opportunities.extend(self._opportunities_in_node(statement.iter, scope))
                self._bind_target(statement.target, scope, None)
                opportunities.extend(self._scan_statements(statement.body, scope, function_parent_scope))
                opportunities.extend(self._scan_statements(statement.orelse, scope, function_parent_scope))
                continue
            if isinstance(statement, ast.If):
                opportunities.extend(self._opportunities_in_node(statement.test, scope))
                opportunities.extend(self._scan_statements(statement.body, scope, function_parent_scope))
                opportunities.extend(self._scan_statements(statement.orelse, scope, function_parent_scope))
                continue
            if isinstance(statement, ast.While):
                opportunities.extend(self._opportunities_in_node(statement.test, scope))
                opportunities.extend(self._scan_statements(statement.body, scope, function_parent_scope))
                opportunities.extend(self._scan_statements(statement.orelse, scope, function_parent_scope))
                continue
            if isinstance(statement, ast.Try):
                opportunities.extend(self._scan_statements(statement.body, scope, function_parent_scope))
                for handler in statement.handlers:
                    if handler.type is not None:
                        opportunities.extend(self._opportunities_in_node(handler.type, scope))
                    handler_scope = scope.child({handler.name} if handler.name else ())
                    opportunities.extend(self._scan_statements(handler.body, handler_scope, function_parent_scope))
                opportunities.extend(self._scan_statements(statement.orelse, scope, function_parent_scope))
                opportunities.extend(self._scan_statements(statement.finalbody, scope, function_parent_scope))
                continue
            if isinstance(statement, ast.Match):
                opportunities.extend(self._opportunities_in_node(statement.subject, scope))
                for case in statement.cases:
                    case_scope = scope.child(_pattern_names(case.pattern))
                    if case.guard is not None:
                        opportunities.extend(self._opportunities_in_node(case.guard, case_scope))
                    opportunities.extend(self._scan_statements(case.body, case_scope, function_parent_scope))
                continue
            opportunities.extend(self._opportunities_in_node(statement, scope))
            self._bind_statement_targets(statement, scope)
        return opportunities

    def _scan_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, parent_scope: _Scope) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for decorator in node.decorator_list:
            opportunities.extend(self._opportunities_in_node(decorator, parent_scope))
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                opportunities.extend(self._opportunities_in_node(default, parent_scope))
        child_scope = parent_scope.child(_function_binding_names(node))
        opportunities.extend(self._scan_statements(node.body, child_scope))
        return opportunities

    def _scan_class(self, node: ast.ClassDef, eval_scope: _Scope, function_parent_scope: _Scope) -> list[Opportunity]:
        opportunities: list[Opportunity] = []
        for expr in (*node.decorator_list, *node.bases, *node.keywords):
            opportunities.extend(self._opportunities_in_node(expr, eval_scope))
        child_scope = eval_scope.child(())
        opportunities.extend(self._scan_statements(node.body, child_scope, function_parent_scope))
        return opportunities

    def _bind_import(self, node: ast.Import | ast.ImportFrom, scope: _Scope) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in MODULES:
                    scope.bind_module(alias.asname or root, root)
            return
        module = (node.module or "").split(".", 1)[0]
        if module not in MODULES:
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            if alias.name in HTTP_METHODS:
                scope.bind_function(local_name, module, alias.name)
            elif (module, alias.name) in CLIENT_FACTORIES:
                scope.bind_function(local_name, module, alias.name)

    def _bind_statement_targets(self, statement: ast.stmt, scope: _Scope) -> None:
        if isinstance(statement, ast.Assign):
            client_module = _client_factory_module(statement.value, scope)
            for target in statement.targets:
                self._bind_target(target, scope, client_module)
        elif isinstance(statement, ast.AnnAssign):
            client_module = _client_factory_module(statement.value, scope) if statement.value is not None else None
            self._bind_target(statement.target, scope, client_module)
        elif isinstance(statement, ast.AugAssign):
            self._bind_target(statement.target, scope, None)

    def _bind_target(self, target: ast.AST, scope: _Scope, client_module: str | None) -> None:
        for name in _target_names(target):
            if client_module is None:
                scope.shadow(name)
            else:
                scope.bind_client(name, client_module)

    def _opportunities_in_node(self, node: ast.AST, scope: _Scope) -> list[Opportunity]:
        visitor = _CallVisitor(self, scope)
        visitor.visit(node)
        return visitor.opportunities

    def opportunity_for_call(self, node: ast.Call, source_kind: str) -> Opportunity:
        return Opportunity(
            predicate="CALLS_ENDPOINT",
            source_kind=source_kind,
            language_or_format="python",
            dimension=self.dimension,
            path=str(self.path.relative_to(self.repo.root)),
            line=getattr(node, "lineno", 1),
        )


@dataclass
class _CallVisitor(ast.NodeVisitor):
    scanner: _ScopeScanner
    scope: _Scope
    opportunities: list[Opportunity] = field(default_factory=list)

    def visit_Call(self, node: ast.Call) -> None:
        source_kind = _http_call_source_kind(node.func, self.scope)
        if source_kind is not None:
            self.opportunities.append(self.scanner.opportunity_for_call(node, source_kind))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._visit_with_scope(node.body, self.scope.child(_argument_names(node.args)))

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.elt, node.generators)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.key, node.generators, node.value)

    def _visit_comprehension(
        self,
        result: ast.AST,
        generators: list[ast.comprehension],
        extra_result: ast.AST | None = None,
    ) -> None:
        comp_scope = self.scope.child(())
        for index, generator in enumerate(generators):
            if index == 0:
                self.visit(generator.iter)
            else:
                self._visit_with_scope(generator.iter, comp_scope)
            for name in _target_names(generator.target):
                comp_scope.shadow(name)
            for condition in generator.ifs:
                self._visit_with_scope(condition, comp_scope)
        self._visit_with_scope(result, comp_scope)
        if extra_result is not None:
            self._visit_with_scope(extra_result, comp_scope)

    def _visit_with_scope(self, node: ast.AST, scope: _Scope) -> None:
        visitor = _CallVisitor(self.scanner, scope)
        visitor.visit(node)
        self.opportunities.extend(visitor.opportunities)


def _http_call_source_kind(func: ast.AST, scope: _Scope) -> str | None:
    if isinstance(func, ast.Name):
        resolved = scope.resolve_function(func.id)
        if resolved is None:
            return None
        module, method = resolved
        if method in HTTP_METHODS:
            return f"{module}.{method}"
        return None
    if not isinstance(func, ast.Attribute) or func.attr not in HTTP_METHODS:
        return None
    root = _attribute_root(func.value)
    if root is None:
        return None
    module = scope.resolve_module(root)
    if module in {"requests", "httpx"}:
        return f"{module}.{func.attr}"
    client_module = scope.resolve_client(root)
    if client_module in MODULES:
        return f"{client_module}.client.{func.attr}"
    return None


def _client_factory_module(node: ast.AST | None, scope: _Scope) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        resolved = scope.resolve_function(func.id)
        if resolved is not None and resolved in CLIENT_FACTORIES:
            return resolved[0]
        return None
    if isinstance(func, ast.Attribute):
        root = _attribute_root(func.value)
        if root is None:
            return None
        module = scope.resolve_module(root)
        if module is not None and (module, func.attr) in CLIENT_FACTORIES:
            return module
    return None


def _attribute_root(node: ast.AST) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return None


def _argument_names(args: ast.arguments) -> set[str]:
    names = {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    if args.vararg is not None:
        names.add(args.vararg.arg)
    if args.kwarg is not None:
        names.add(args.kwarg.arg)
    return names


def _function_binding_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = _argument_names(node.args)
    collector = _BindingCollector()
    for statement in node.body:
        collector.visit(statement)
    names.update(collector.names)
    names.difference_update(collector.global_names)
    names.update(collector.nonlocal_names)
    return names


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    return set()


class _BindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocal_names.update(node.names)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.names.update(_target_names(target))
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.names.update(_target_names(node.target))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.iter)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.iter)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.names.update(_target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.names.update(_target_names(item.optional_vars))
        for statement in node.body:
            self.visit(statement)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.names.update(_target_names(node.target))
        self.visit(node.value)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            self.names.update(_pattern_names(case.pattern))
            if case.guard is not None:
                self.visit(case.guard)
            for statement in case.body:
                self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arg_defaults(node.args)

    def _visit_arg_defaults(self, args: ast.arguments) -> None:
        for default in (*args.defaults, *args.kw_defaults):
            if default is not None:
                self.visit(default)


def _pattern_names(pattern: ast.AST) -> set[str]:
    if isinstance(pattern, ast.MatchAs):
        names = set()
        if pattern.name is not None:
            names.add(pattern.name)
        if pattern.pattern is not None:
            names.update(_pattern_names(pattern.pattern))
        return names
    if isinstance(pattern, ast.MatchStar):
        return {pattern.name} if pattern.name is not None else set()
    if isinstance(pattern, ast.MatchMapping):
        names = set()
        for nested_pattern in pattern.patterns:
            names.update(_pattern_names(nested_pattern))
        if pattern.rest is not None:
            names.add(pattern.rest)
        return names
    if isinstance(pattern, ast.MatchSequence):
        return {name for nested_pattern in pattern.patterns for name in _pattern_names(nested_pattern)}
    if isinstance(pattern, ast.MatchClass):
        names = set()
        for nested_pattern in (*pattern.patterns, *pattern.kwd_patterns):
            names.update(_pattern_names(nested_pattern))
        return names
    if isinstance(pattern, ast.MatchOr):
        return {name for nested_pattern in pattern.patterns for name in _pattern_names(nested_pattern)}
    return set()
