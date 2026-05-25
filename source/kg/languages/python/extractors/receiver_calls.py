from __future__ import annotations

import ast
from dataclasses import dataclass
from collections.abc import Iterable

from source.kg.core.models import Entity
from source.kg.languages.python.normalization.imports import NormalizedImport


@dataclass(frozen=True)
class IndexedSymbol:
    entity: Entity
    module_name: str
    qualname: str
    symbol_kind: str


@dataclass(frozen=True)
class ResolvedReceiverCall:
    caller: Entity
    callee: Entity
    line: int
    column: int
    raw_call: str
    receiver_name: str
    receiver_class: str


class PythonReceiverCallIndex:
    def __init__(self, symbols: Iterable[IndexedSymbol]) -> None:
        self._classes_by_qualified_name: dict[str, IndexedSymbol] = {}
        self._classes_by_module_and_name: dict[tuple[str, str], IndexedSymbol] = {}
        self._classes_by_module: dict[str, list[IndexedSymbol]] = {}
        self._methods_by_class_and_name: dict[tuple[str, str, str], IndexedSymbol] = {}
        self._modules: set[str] = set()
        for symbol in symbols:
            self._modules.add(symbol.module_name)
            if symbol.symbol_kind == "class":
                qualified_name = self._qualified_name(symbol)
                self._classes_by_qualified_name[qualified_name] = symbol
                self._classes_by_module_and_name[(symbol.module_name, symbol.qualname.rsplit(".", 1)[-1])] = symbol
                self._classes_by_module.setdefault(symbol.module_name, []).append(symbol)
                continue
            if symbol.symbol_kind != "method" or "." not in symbol.qualname:
                continue
            class_qualname, method_name = symbol.qualname.rsplit(".", 1)
            self._methods_by_class_and_name[(symbol.module_name, class_qualname, method_name)] = symbol

    def class_by_qualified_name(self, qualified_name: str) -> IndexedSymbol | None:
        return self._classes_by_qualified_name.get(qualified_name)

    def module_exists(self, module_name: str) -> bool:
        return module_name in self._modules

    def classes_in_module(self, module_name: str) -> list[IndexedSymbol]:
        return self._classes_by_module.get(module_name, [])

    def method_for_class(self, class_symbol: IndexedSymbol, method_name: str) -> IndexedSymbol | None:
        return self._methods_by_class_and_name.get((class_symbol.module_name, class_symbol.qualname, method_name))

    def _qualified_name(self, symbol: IndexedSymbol) -> str:
        return f"{symbol.module_name}.{symbol.qualname}"


class PythonReceiverCallResolver:
    def __init__(
        self,
        *,
        index: PythonReceiverCallIndex,
        current_module: str,
        imports: list[NormalizedImport],
    ) -> None:
        self.index = index
        self.current_module = current_module
        self.class_bindings = self._class_bindings(imports)
        self.module_bindings = self._module_bindings(imports)

    def receiver_calls_in_body(
        self,
        body: list[ast.stmt],
        *,
        caller: Entity,
    ) -> list[ResolvedReceiverCall]:
        collector = _ReceiverCallCollector(self, caller)
        collector.process_statements(body)
        return collector.calls

    def class_from_constructor(self, node: ast.AST) -> IndexedSymbol | None:
        if isinstance(node, ast.Name):
            return self.class_bindings.get(node.id)
        if isinstance(node, ast.Attribute):
            parts = _attribute_parts(node)
            if len(parts) < 2:
                return None
            direct_class = self.index.class_by_qualified_name(".".join(parts))
            if direct_class is not None:
                return direct_class
            module_name = self.module_bindings.get(parts[0])
            if module_name is None:
                return None
            return self.index.class_by_qualified_name(".".join([module_name, *parts[1:]]))
        return None

    def _class_bindings(self, imports: list[NormalizedImport]) -> dict[str, IndexedSymbol]:
        bindings: dict[str, IndexedSymbol] = {}
        for symbol in self._same_module_classes():
            bindings.setdefault(symbol.qualname.rsplit(".", 1)[-1], symbol)
        for import_ref in imports:
            module_name = import_ref.module_name
            if module_name is None:
                continue
            for imported_name in import_ref.imported_names:
                imported_class = self.index.class_by_qualified_name(f"{module_name}.{imported_name}")
                if imported_class is not None:
                    bindings[imported_name] = imported_class
        return bindings

    def _module_bindings(self, imports: list[NormalizedImport]) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for import_ref in imports:
            module_name = import_ref.module_name
            if module_name is None:
                continue
            if import_ref.imported_names:
                for imported_name in import_ref.imported_names:
                    imported_module = f"{module_name}.{imported_name}"
                    if self.index.module_exists(imported_module):
                        bindings[imported_name] = imported_module
                continue
            if import_ref.alias:
                bindings[import_ref.alias] = module_name
        return bindings

    def _same_module_classes(self) -> list[IndexedSymbol]:
        return self.index.classes_in_module(self.current_module)


class _ReceiverCallCollector(ast.NodeVisitor):
    def __init__(self, resolver: PythonReceiverCallResolver, caller: Entity) -> None:
        self.resolver = resolver
        self.caller = caller
        self.calls: list[ResolvedReceiverCall] = []
        self.local_classes: dict[str, IndexedSymbol | None] = {}

    def process_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self._process_statement(statement)

    def _process_statement(self, statement: ast.stmt) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(statement, ast.Assign):
            self.visit(statement.value)
            resolved_class = self._resolved_class_from_assigned_value(statement.value)
            for target in statement.targets:
                self._bind_target(target, resolved_class)
            return
        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                self.visit(statement.value)
            self._bind_target(
                statement.target,
                self._resolved_class_from_assigned_value(statement.value) if statement.value is not None else None,
            )
            return
        if isinstance(statement, ast.AugAssign):
            self.visit(statement.value)
            self._bind_target(statement.target, None)
            return
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self.visit(statement.iter)
            self._process_branch(statement.body, unknown_target=statement.target)
            self._process_branch(statement.orelse)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self.visit(item.context_expr)
            branch = self._copy_for_branch()
            for item in statement.items:
                if item.optional_vars is not None:
                    branch._bind_target(item.optional_vars, None)
            branch.process_statements(statement.body)
            self.calls.extend(branch.calls)
            return
        if isinstance(statement, ast.If):
            self.visit(statement.test)
            self._process_branch(statement.body)
            self._process_branch(statement.orelse)
            return
        if isinstance(statement, ast.Try):
            self._process_branch(statement.body)
            for handler in statement.handlers:
                self._process_branch(handler.body)
            self._process_branch(statement.orelse)
            self._process_branch(statement.finalbody)
            return
        self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._receiver_call(node)
        if resolved is not None:
            self.calls.append(resolved)
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def _receiver_call(self, node: ast.Call) -> ResolvedReceiverCall | None:
        if not isinstance(node.func, ast.Attribute):
            return None
        receiver = node.func.value
        if not isinstance(receiver, ast.Name):
            return None
        class_symbol = self.local_classes.get(receiver.id)
        if class_symbol is None:
            return None
        method = self.resolver.index.method_for_class(class_symbol, node.func.attr)
        if method is None:
            return None
        return ResolvedReceiverCall(
            caller=self.caller,
            callee=method.entity,
            line=getattr(node, "lineno", 1),
            column=getattr(node, "col_offset", -1),
            raw_call=_expression(node.func),
            receiver_name=receiver.id,
            receiver_class=f"{class_symbol.module_name}.{class_symbol.qualname}",
        )

    def _resolved_class_from_assigned_value(self, value: ast.AST) -> IndexedSymbol | None:
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name):
                local_class = self.local_classes.get(value.func.id)
                if local_class is not None:
                    return local_class
            return self.resolver.class_from_constructor(value.func)
        if isinstance(value, ast.Name):
            return self.local_classes.get(value.id) or self.resolver.class_bindings.get(value.id)
        return None

    def _bind_target(self, target: ast.AST, resolved_class: IndexedSymbol | None) -> None:
        for name in _target_names(target):
            self.local_classes[name] = resolved_class

    def _process_branch(self, statements: list[ast.stmt], unknown_target: ast.AST | None = None) -> None:
        branch = self._copy_for_branch()
        if unknown_target is not None:
            branch._bind_target(unknown_target, None)
        branch.process_statements(statements)
        self.calls.extend(branch.calls)

    def _copy_for_branch(self) -> _ReceiverCallCollector:
        branch = _ReceiverCallCollector(self.resolver, self.caller)
        branch.local_classes = dict(self.local_classes)
        return branch


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    return set()


def _attribute_parts(node: ast.Attribute) -> list[str]:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return parts


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__
