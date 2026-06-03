from __future__ import annotations

import ast
import unittest

from source.kg.languages.python.extractors.frameworks.fastapi_routes import extract_fastapi_routes


def _routes(source: str) -> tuple[set[tuple[str, str]], bool]:
    routes, recognized = extract_fastapi_routes(ast.parse(source))
    return {(r.method, r.path) for r in routes}, recognized


class FastApiRoutesTest(unittest.TestCase):
    def test_app_decorator_routes(self) -> None:
        routes, recognized = _routes(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "@app.get('/api/labels')\n"
            "def labels(): ...\n"
            "@app.post('/api/doc/{sha}/comments')\n"
            "async def comments(): ...\n"
        )
        self.assertTrue(recognized)
        self.assertEqual(routes, {("GET", "/api/labels"), ("POST", "/api/doc/{sha}/comments")})

    def test_apirouter_prefix_is_applied(self) -> None:
        routes, _ = _routes(
            "from fastapi import APIRouter\n"
            "router = APIRouter(prefix='/users')\n"
            "@router.get('/{id}')\n"
            "def get_user(): ...\n"
            "@router.delete('/{id}')\n"
            "def del_user(): ...\n"
        )
        self.assertEqual(routes, {("GET", "/users/{id}"), ("DELETE", "/users/{id}")})

    def test_module_qualified_factory(self) -> None:
        routes, _ = _routes(
            "import fastapi\n"
            "app = fastapi.FastAPI()\n"
            "@app.put('/items/{id}')\n"
            "def put_item(): ...\n"
        )
        self.assertEqual(routes, {("PUT", "/items/{id}")})

    def test_not_recognized_without_fastapi_import(self) -> None:
        routes, recognized = _routes(
            "app = something()\n"
            "@app.get('/x')\n"
            "def x(): ...\n"
        )
        self.assertFalse(recognized)
        self.assertEqual(routes, set())

    def test_non_literal_router_prefix_skips_its_routes(self) -> None:
        routes, _ = _routes(
            "from fastapi import APIRouter\n"
            "PREFIX = '/v1'\n"
            "router = APIRouter(prefix=PREFIX)\n"
            "@router.get('/items')\n"
            "def items(): ...\n"
        )
        self.assertEqual(routes, set())

    def test_non_literal_path_is_skipped(self) -> None:
        routes, _ = _routes(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "PATH = '/dynamic'\n"
            "@app.get(PATH)\n"
            "def dyn(): ...\n"
            "@app.get('/static')\n"
            "def stat(): ...\n"
        )
        self.assertEqual(routes, {("GET", "/static")})


if __name__ == "__main__":
    unittest.main()
