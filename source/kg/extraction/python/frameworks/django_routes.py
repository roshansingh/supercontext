from __future__ import annotations

import ast
from pathlib import Path

from source.kg.extraction.python.frameworks.routes import EndpointRoute


def extract_django_routes(tree: ast.AST, file_path: Path) -> tuple[list[EndpointRoute], bool]:
    collector = _DjangoRouteCollector(file_path)
    collector.visit(tree)
    return collector.routes, collector.recognized_framework


class _DjangoRouteCollector(ast.NodeVisitor):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.path_names: set[str] = set()
        self.re_path_names: set[str] = set()
        self.recognized_framework = False
        self.routes: list[EndpointRoute] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module != "django.urls":
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            if alias.name == "path":
                self.recognized_framework = True
                self.path_names.add(local_name)
            elif alias.name == "re_path":
                self.recognized_framework = True
                self.re_path_names.add(local_name)

    def visit_Call(self, node: ast.Call) -> None:
        route = self._route_from_call(node)
        if route is not None:
            self.routes.append(route)
        self.generic_visit(node)

    def _route_from_call(self, node: ast.Call) -> EndpointRoute | None:
        if not isinstance(node.func, ast.Name):
            return None
        name = node.func.id
        file_role_allows = self.file_path.name == "urls.py" and name in {"path", "re_path"}
        if name in self.path_names:
            source_kind = "django_path"
        elif name in self.re_path_names:
            source_kind = "django_re_path"
        elif file_role_allows:
            source_kind = f"django_{name}"
        else:
            return None
        path = _string_arg(node, 0)
        if path is None:
            return None
        return EndpointRoute(method="ANY", path=path, line=getattr(node, "lineno", 1), source_kind=source_kind)


def _string_arg(node: ast.Call, position: int) -> str | None:
    if len(node.args) <= position:
        return None
    value = node.args[position]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None
