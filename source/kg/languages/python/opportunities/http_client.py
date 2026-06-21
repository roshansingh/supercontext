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
FunctionDefNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class HttpClientBinding:
    module: str
    factory: str | None = None
    factory_call: ast.Call | None = field(default=None, compare=False)


@dataclass(frozen=True)
class HttpClientCall:
    path: Path
    node: ast.Call = field(compare=False)
    source_kind: str
    module: str
    method_name: str
    url_arg: ast.AST | None = field(default=None, compare=False)
    method_arg: ast.AST | None = field(default=None, compare=False)
    client_factory_call: ast.Call | None = field(default=None, compare=False)
    enclosing_function: FunctionDefNode | None = field(default=None, compare=False)
    local_binding_names: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class _HttpCallMatch:
    source_kind: str
    module: str
    method_name: str
    url_arg: ast.AST | None
    method_arg: ast.AST | None = None
    client_factory_call: ast.Call | None = None


def collect_http_client_calls(repo: RepoSnapshot, path: Path, tree: ast.AST) -> tuple[HttpClientCall, ...]:
    scanner = _ScopeScanner(repo, path, None)
    return scanner.scan_module_calls(tree)


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
    client_aliases: dict[str, HttpClientBinding] = field(default_factory=dict)
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

    def resolve_client(self, name: str) -> HttpClientBinding | None:
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

    def bind_client(self, name: str, binding: HttpClientBinding) -> None:
        self.client_aliases[name] = binding
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
        return tuple(self.opportunity_for_call(call) for call in self.scan_module_calls(tree))

    def scan_module_calls(self, tree: ast.AST) -> tuple[HttpClientCall, ...]:
        if not isinstance(tree, ast.Module):
            return ()
        return tuple(self._scan_statements(tree.body, _Scope()))

    def _scan_statements(
        self,
        statements: list[ast.stmt],
        scope: _Scope,
        function_parent_scope: _Scope | None = None,
        function_node: FunctionDefNode | None = None,
        function_binding_names: frozenset[str] = frozenset(),
    ) -> list[HttpClientCall]:
        calls: list[HttpClientCall] = []
        for statement in statements:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                self._bind_import(statement, scope)
                continue
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls.extend(self._scan_function(statement, function_parent_scope or scope))
                scope.shadow(statement.name)
                continue
            if isinstance(statement, ast.ClassDef):
                calls.extend(self._scan_class(statement, scope, function_parent_scope or scope))
                scope.shadow(statement.name)
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    calls.extend(self._calls_in_node(item.context_expr, scope, function_node, function_binding_names))
                    if item.optional_vars is not None:
                        self._bind_target(item.optional_vars, scope, _client_factory_binding(item.context_expr, scope))
                calls.extend(
                    self._scan_statements(
                        statement.body,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                calls.extend(self._calls_in_node(statement.iter, scope, function_node, function_binding_names))
                self._bind_target(statement.target, scope, None)
                calls.extend(
                    self._scan_statements(
                        statement.body,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                calls.extend(
                    self._scan_statements(
                        statement.orelse,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                continue
            if isinstance(statement, ast.If):
                calls.extend(self._calls_in_node(statement.test, scope, function_node, function_binding_names))
                calls.extend(
                    self._scan_statements(
                        statement.body,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                calls.extend(
                    self._scan_statements(
                        statement.orelse,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                continue
            if isinstance(statement, ast.While):
                calls.extend(self._calls_in_node(statement.test, scope, function_node, function_binding_names))
                calls.extend(
                    self._scan_statements(
                        statement.body,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                calls.extend(
                    self._scan_statements(
                        statement.orelse,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                continue
            if isinstance(statement, ast.Try):
                calls.extend(
                    self._scan_statements(
                        statement.body,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                for handler in statement.handlers:
                    if handler.type is not None:
                        calls.extend(self._calls_in_node(handler.type, scope, function_node, function_binding_names))
                    handler_scope = scope.child({handler.name} if handler.name else ())
                    calls.extend(
                        self._scan_statements(
                            handler.body,
                            handler_scope,
                            function_parent_scope,
                            function_node,
                            function_binding_names,
                        )
                    )
                calls.extend(
                    self._scan_statements(
                        statement.orelse,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                calls.extend(
                    self._scan_statements(
                        statement.finalbody,
                        scope,
                        function_parent_scope,
                        function_node,
                        function_binding_names,
                    )
                )
                continue
            if isinstance(statement, ast.Match):
                calls.extend(self._calls_in_node(statement.subject, scope, function_node, function_binding_names))
                for case in statement.cases:
                    case_scope = scope.child(_pattern_names(case.pattern))
                    if case.guard is not None:
                        calls.extend(self._calls_in_node(case.guard, case_scope, function_node, function_binding_names))
                    calls.extend(
                        self._scan_statements(
                            case.body,
                            case_scope,
                            function_parent_scope,
                            function_node,
                            function_binding_names,
                        )
                    )
                continue
            calls.extend(self._calls_in_node(statement, scope, function_node, function_binding_names))
            self._bind_statement_targets(statement, scope)
        return calls

    def _scan_function(self, node: FunctionDefNode, parent_scope: _Scope) -> list[HttpClientCall]:
        calls: list[HttpClientCall] = []
        for decorator in node.decorator_list:
            calls.extend(self._calls_in_node(decorator, parent_scope, None, frozenset()))
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                calls.extend(self._calls_in_node(default, parent_scope, None, frozenset()))
        binding_names = frozenset(_function_binding_names(node))
        child_scope = parent_scope.child(binding_names)
        calls.extend(self._scan_statements(node.body, child_scope, function_node=node, function_binding_names=binding_names))
        return calls

    def _scan_class(self, node: ast.ClassDef, eval_scope: _Scope, function_parent_scope: _Scope) -> list[HttpClientCall]:
        calls: list[HttpClientCall] = []
        for expr in (*node.decorator_list, *node.bases, *node.keywords):
            calls.extend(self._calls_in_node(expr, eval_scope, None, frozenset()))
        child_scope = eval_scope.child(())
        calls.extend(self._scan_statements(node.body, child_scope, function_parent_scope))
        return calls

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
            client_binding = _client_factory_binding(statement.value, scope)
            for target in statement.targets:
                self._bind_target(target, scope, client_binding)
        elif isinstance(statement, ast.AnnAssign):
            client_binding = _client_factory_binding(statement.value, scope) if statement.value is not None else None
            self._bind_target(statement.target, scope, client_binding)
        elif isinstance(statement, ast.AugAssign):
            self._bind_target(statement.target, scope, None)

    def _bind_target(self, target: ast.AST, scope: _Scope, client_binding: HttpClientBinding | None) -> None:
        for name in _target_names(target):
            if client_binding is None:
                scope.shadow(name)
            else:
                scope.bind_client(name, client_binding)

    def _calls_in_node(
        self,
        node: ast.AST,
        scope: _Scope,
        function_node: FunctionDefNode | None,
        function_binding_names: frozenset[str],
    ) -> list[HttpClientCall]:
        visitor = _CallVisitor(self, scope, function_node, function_binding_names)
        visitor.visit(node)
        return visitor.calls

    def call_for_match(
        self,
        node: ast.Call,
        match: _HttpCallMatch,
        function_node: FunctionDefNode | None,
        function_binding_names: frozenset[str],
    ) -> HttpClientCall:
        return HttpClientCall(
            path=self.path,
            node=node,
            source_kind=match.source_kind,
            module=match.module,
            method_name=match.method_name,
            url_arg=match.url_arg,
            method_arg=match.method_arg,
            client_factory_call=match.client_factory_call,
            enclosing_function=function_node,
            local_binding_names=function_binding_names,
        )

    def opportunity_for_call(self, call: HttpClientCall) -> Opportunity:
        return Opportunity(
            predicate="CALLS_ENDPOINT",
            source_kind=call.source_kind,
            language_or_format="python",
            dimension=self.dimension,
            path=str(self.path.relative_to(self.repo.root)),
            line=getattr(call.node, "lineno", 1),
        )


@dataclass
class _CallVisitor(ast.NodeVisitor):
    scanner: _ScopeScanner
    scope: _Scope
    function_node: FunctionDefNode | None
    function_binding_names: frozenset[str]
    calls: list[HttpClientCall] = field(default_factory=list)

    def visit_Call(self, node: ast.Call) -> None:
        match = _http_call_match(node, self.scope)
        if match is not None:
            self.calls.append(
                self.scanner.call_for_match(node, match, self.function_node, self.function_binding_names)
            )
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
        visitor = _CallVisitor(self.scanner, scope, self.function_node, self.function_binding_names)
        visitor.visit(node)
        self.calls.extend(visitor.calls)


def _http_call_match(node: ast.Call, scope: _Scope) -> _HttpCallMatch | None:
    func = node.func
    if isinstance(func, ast.Name):
        resolved = scope.resolve_function(func.id)
        if resolved is None:
            return None
        module, method = resolved
        if method in HTTP_METHODS:
            return _call_match(node, module, method, f"{module}.{method}", None)
        return None
    if not isinstance(func, ast.Attribute) or func.attr not in HTTP_METHODS:
        return None
    root = _attribute_root(func.value)
    if root is not None:
        module = scope.resolve_module(root)
        if module in {"requests", "httpx"}:
            return _call_match(node, module, func.attr, f"{module}.{func.attr}", None)
        client_binding = scope.resolve_client(root)
        if client_binding is not None and client_binding.module in MODULES:
            return _call_match(
                node,
                client_binding.module,
                func.attr,
                f"{client_binding.module}.client.{func.attr}",
                client_binding.factory_call,
            )
    direct_client = _client_factory_binding(func.value, scope)
    if direct_client is not None:
        return _call_match(
            node,
            direct_client.module,
            func.attr,
            f"{direct_client.module}.client.{func.attr}",
            direct_client.factory_call,
        )
    return None


def _call_match(
    node: ast.Call,
    module: str,
    method: str,
    source_kind: str,
    client_factory_call: ast.Call | None,
) -> _HttpCallMatch:
    method_name = method.lower()
    if method_name == "request":
        method_arg = _call_arg(node, 0, "method")
        url_arg = _call_arg(node, 1, "url")
    else:
        method_arg = None
        url_arg = _call_arg(node, 0, "url")
    return _HttpCallMatch(
        source_kind=source_kind,
        module=module,
        method_name=method_name,
        url_arg=url_arg,
        method_arg=method_arg,
        client_factory_call=client_factory_call,
    )


def _call_arg(node: ast.Call, positional_index: int, keyword_name: str) -> ast.AST | None:
    if len(node.args) > positional_index:
        return node.args[positional_index]
    for keyword in node.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _client_factory_binding(node: ast.AST | None, scope: _Scope) -> HttpClientBinding | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        resolved = scope.resolve_function(func.id)
        if resolved is not None and resolved in CLIENT_FACTORIES:
            return HttpClientBinding(resolved[0], resolved[1], node)
        return None
    if isinstance(func, ast.Attribute):
        root = _attribute_root(func.value)
        if root is None:
            return None
        module = scope.resolve_module(root)
        if module is not None and (module, func.attr) in CLIENT_FACTORIES:
            return HttpClientBinding(module, func.attr, node)
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
