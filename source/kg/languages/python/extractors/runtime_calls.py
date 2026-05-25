from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

from source.kg.languages.python.extractors.source_context import source_excerpt, source_line


PYTHON_BUILTIN_CALLABLES: frozenset[str] = frozenset(
    name for name in dir(builtins) if not name.startswith("_") and callable(getattr(builtins, name))
)


@dataclass(frozen=True)
class RuntimeCall:
    name: str
    line: int
    column: int
    raw_call: str
    source_line: str | None = None
    source_excerpt: str | None = None


def collect_builtin_runtime_calls(
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module_bound_names: set[str] | None = None,
    source_text: str | None = None,
) -> list[RuntimeCall]:
    shadowed_names = _function_bound_names(function_node)
    # Python decides local names statically for the whole function body, so a
    # later assignment still shadows earlier reads of that name.
    shadowed_names.update(_local_bound_names(function_node.body))
    shadowed_names.update(module_bound_names or set())
    collector = _BuiltinCallCollector(shadowed_names=shadowed_names, source_text=source_text)
    for statement in function_node.body:
        collector.visit(statement)
    return collector.calls


def module_bound_builtin_names(tree: ast.AST) -> set[str]:
    if not isinstance(tree, ast.Module):
        return set()
    bound: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(statement.name)
            continue
        bound.update(_bound_names_in_statement(statement))
    return bound & PYTHON_BUILTIN_CALLABLES


class _BuiltinCallCollector(ast.NodeVisitor):
    def __init__(self, *, shadowed_names: set[str], source_text: str | None = None) -> None:
        self.shadowed_names = shadowed_names
        self.source_text = source_text
        self.calls: list[RuntimeCall] = []

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in PYTHON_BUILTIN_CALLABLES
            and node.func.id not in self.shadowed_names
        ):
            self.calls.append(
                RuntimeCall(
                    name=node.func.id,
                    line=getattr(node, "lineno", 1),
                    column=getattr(node, "col_offset", -1),
                    raw_call=_expression(node.func),
                    source_line=source_line(self.source_text, getattr(node, "lineno", 1)),
                    source_excerpt=source_excerpt(self.source_text, node),
                )
            )
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_header(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_header(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arg_defaults(node.args)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, value_nodes=(node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, value_nodes=(node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, value_nodes=(node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, value_nodes=(node.key, node.value))

    def _visit_function_header(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arg_defaults(node.args)
        if node.returns is not None:
            self.visit(node.returns)

    def _visit_arg_defaults(self, args: ast.arguments) -> None:
        defaults = [*args.defaults, *[default for default in args.kw_defaults if default is not None]]
        for default in defaults:
            self.visit(default)

    def _visit_comprehension(self, generators: list[ast.comprehension], *, value_nodes: tuple[ast.AST, ...]) -> None:
        branch = _BuiltinCallCollector(shadowed_names=set(self.shadowed_names), source_text=self.source_text)
        for generator in generators:
            branch.visit(generator.iter)
            branch.shadowed_names.update(_target_names(generator.target))
            for condition in generator.ifs:
                branch.visit(condition)
        for value_node in value_nodes:
            branch.visit(value_node)
        self.calls.extend(branch.calls)


def _function_bound_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
    if node.args.vararg is not None:
        names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        names.add(node.args.kwarg.arg)
    return names & PYTHON_BUILTIN_CALLABLES


def _local_bound_names(statements: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(statement.name)
            continue
        names.update(_bound_names_in_statement(statement))
    return names & PYTHON_BUILTIN_CALLABLES


def _bound_names_in_statement(statement: ast.stmt) -> set[str]:
    collector = _BindingCollector()
    collector.visit(statement)
    return collector.names


class _BindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        for generator in node.generators:
            self.visit(generator.iter)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        for generator in node.generators:
            self.visit(generator.iter)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        for generator in node.generators:
            self.visit(generator.iter)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        for generator in node.generators:
            self.visit(generator.iter)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.names.update(_target_names(node.target))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        for pattern in node.patterns:
            self.visit(pattern)


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return set()


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
