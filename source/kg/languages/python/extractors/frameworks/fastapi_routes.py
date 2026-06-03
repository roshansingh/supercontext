from __future__ import annotations

import ast

from source.kg.languages.python.extractors.frameworks.routes import EndpointRoute


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "trace"}


def extract_fastapi_routes(tree: ast.AST) -> tuple[list[EndpointRoute], bool]:
    collector = _FastAPIRouteCollector()
    collector.visit(tree)
    return collector.routes, collector.recognized_framework


class _FastAPIRouteCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.fastapi_module_names: set[str] = set()
        self.fastapi_locals: set[str] = set()  # names imported as FastAPI
        self.apirouter_locals: set[str] = set()  # names imported as APIRouter
        self.app_names: set[str] = set()  # x = FastAPI()
        self.router_prefixes: dict[str, str | None] = {}  # x = APIRouter(prefix="/p") -> prefix; None = non-literal
        self.routes: list[EndpointRoute] = []
        self.recognized_framework = False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "fastapi":
                self.recognized_framework = True
                self.fastapi_module_names.add(alias.asname or "fastapi")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module != "fastapi":
            return
        for alias in node.names:
            if alias.name == "FastAPI":
                self.recognized_framework = True
                self.fastapi_locals.add(alias.asname or "FastAPI")
            elif alias.name == "APIRouter":
                self.recognized_framework = True
                self.apirouter_locals.add(alias.asname or "APIRouter")

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_factory(node.value, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_factory(node.value, [node.target])
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._collect_decorated_routes(node.decorator_list)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._collect_decorated_routes(node.decorator_list)
        self.generic_visit(node)

    def _record_factory(self, value: ast.expr, targets: list[ast.expr]) -> None:
        kind = self._factory_kind(value)
        if kind is None:
            return
        self.recognized_framework = True
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if kind == "FastAPI":
                self.app_names.add(target.id)
            else:
                self.router_prefixes[target.id] = self._router_prefix(value)

    def _factory_kind(self, value: ast.AST) -> str | None:
        if not isinstance(value, ast.Call):
            return None
        func = value.func
        if isinstance(func, ast.Name):
            if func.id in self.fastapi_locals:
                return "FastAPI"
            if func.id in self.apirouter_locals:
                return "APIRouter"
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in self.fastapi_module_names:
            if func.attr == "FastAPI":
                return "FastAPI"
            if func.attr == "APIRouter":
                return "APIRouter"
        return None

    def _router_prefix(self, call: ast.AST) -> str | None:
        # "" = no prefix kwarg (routes use their own paths); None = non-literal prefix we can't
        # resolve, so the router's routes are skipped rather than emitted prefix-less.
        if not isinstance(call, ast.Call):
            return ""
        for keyword in call.keywords:
            if keyword.arg == "prefix":
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    return keyword.value.value
                return None
        return ""

    def _collect_decorated_routes(self, decorators: list[ast.expr]) -> None:
        for decorator in decorators:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            receiver = decorator.func.value
            if not isinstance(receiver, ast.Name):
                continue
            verb = decorator.func.attr.lower()
            if verb not in HTTP_METHODS:
                continue
            if receiver.id in self.app_names:
                prefix = ""
            elif receiver.id in self.router_prefixes:
                prefix = self.router_prefixes[receiver.id]
                if prefix is None:  # non-literal APIRouter prefix -> can't build a correct path
                    continue
            else:
                continue
            path = _string_arg(decorator, 0)
            if path is None:
                continue
            self.routes.append(
                EndpointRoute(
                    method=verb.upper(),
                    path=_join_route(prefix, path),
                    line=getattr(decorator, "lineno", 1),
                    source_kind=f"fastapi_{verb}",
                )
            )


def _join_route(prefix: str, path: str) -> str:
    if not prefix:
        return path
    return prefix.rstrip("/") + "/" + path.lstrip("/")


def _string_arg(node: ast.Call, position: int) -> str | None:
    if len(node.args) <= position:
        return None
    value = node.args[position]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None
