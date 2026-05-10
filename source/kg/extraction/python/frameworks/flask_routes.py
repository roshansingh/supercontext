from __future__ import annotations

import ast

from source.kg.extraction.python.frameworks.routes import EndpointRoute


HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
FLASK_FACTORY_NAMES = {"Flask", "Blueprint"}


def extract_flask_routes(tree: ast.AST) -> tuple[list[EndpointRoute], bool]:
    collector = _FlaskRouteCollector()
    collector.visit(tree)
    return collector.routes, collector.recognized_framework


class _FlaskRouteCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.flask_factory_names: set[str] = set()
        self.flask_module_names: set[str] = set()
        self.app_names: set[str] = set()
        self.routes: list[EndpointRoute] = []
        self.recognized_framework = False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "flask":
                self.recognized_framework = True
                self.flask_module_names.add(alias.asname or "flask")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module != "flask":
            return
        for alias in node.names:
            if alias.name in FLASK_FACTORY_NAMES:
                self.recognized_framework = True
                self.flask_factory_names.add(alias.asname or alias.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_flask_factory_call(node.value, self.flask_factory_names, self.flask_module_names):
            self.recognized_framework = True
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.app_names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and _is_flask_factory_call(node.value, self.flask_factory_names, self.flask_module_names):
            self.recognized_framework = True
            if isinstance(node.target, ast.Name):
                self.app_names.add(node.target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._collect_decorated_routes(node.decorator_list)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._collect_decorated_routes(node.decorator_list)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        route = _route_from_add_url_rule(node, self.app_names)
        if route is not None:
            self.routes.append(route)
        self.generic_visit(node)

    def _collect_decorated_routes(self, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            route = _route_from_decorator(decorator, self.app_names)
            if route is not None:
                self.routes.append(route)


def _is_flask_factory_call(node: ast.AST, factory_names: set[str], module_names: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in factory_names
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in module_names and func.attr in FLASK_FACTORY_NAMES
    return False


def _route_from_decorator(node: ast.AST, app_names: set[str]) -> EndpointRoute | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    receiver = node.func.value
    if not isinstance(receiver, ast.Name) or receiver.id not in app_names:
        return None
    method_name = node.func.attr.lower()
    if method_name != "route" and method_name not in HTTP_METHODS:
        return None
    path = _string_arg(node, 0)
    if path is None:
        return None
    method = _method_from_route_call(node) if method_name == "route" else method_name.upper()
    return EndpointRoute(method=method, path=path, line=getattr(node, "lineno", 1), source_kind=f"flask_{method_name}")


def _route_from_add_url_rule(node: ast.Call, app_names: set[str]) -> EndpointRoute | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_url_rule":
        return None
    receiver = node.func.value
    if not isinstance(receiver, ast.Name) or receiver.id not in app_names:
        return None
    path = _string_arg(node, 0)
    if path is None:
        return None
    return EndpointRoute(
        method=_method_from_route_call(node),
        path=path,
        line=getattr(node, "lineno", 1),
        source_kind="flask_add_url_rule",
    )


def _method_from_route_call(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg == "methods":
            methods = _string_sequence(keyword.value)
            return methods[0].upper() if len(methods) == 1 else "ANY"
    return "ANY"


def _string_arg(node: ast.Call, position: int) -> str | None:
    if len(node.args) <= position:
        return None
    value = node.args[position]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _string_sequence(node: ast.AST) -> list[str]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return []
    values = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            values.append(element.value)
    return values
