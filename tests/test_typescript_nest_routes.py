from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.endpoints import extract_typescript_express_routes
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.languages.typescript.extractors.parser_bridge import parse_typescript_repo


NODE_AVAILABLE = shutil.which("node") is not None


def _endpoints(tmp: str, files: dict[str, str]) -> set[tuple[str, str]]:
    root = Path(tmp)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    repo = discover_repo(root)
    build = ConfigKgBuild()
    service = StaticConfigExtractor()._service_entity(repo, "default")
    extract_typescript_express_routes(repo, parse_typescript_repo(repo), service, build, "default")
    return {(e.identity.get("method"), e.identity.get("path")) for e in build.entities if e.kind == "Endpoint"}


_CONTROLLER = """import { Controller, Get, Post, Put, Delete } from '@nestjs/common';

@Controller('articles')
export class ArticlesController {
  @Get()
  findAll() {}

  @Get(':slug')
  findOne() {}

  @Post()
  create() {}

  @Delete(':slug')
  remove() {}
}
"""


@unittest.skipIf(not NODE_AVAILABLE, "node executable not available for the TypeScript parser bridge")
class TypescriptNestRoutesTest(unittest.TestCase):
    def test_controller_routes_combine_prefix_and_method_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"articles.controller.ts": _CONTROLLER})
        self.assertEqual(
            endpoints,
            {
                ("GET", "/articles"),
                ("GET", "/articles/:slug"),
                ("POST", "/articles"),
                ("DELETE", "/articles/:slug"),
            },
        )

    def test_no_routes_without_nest_common_import(self) -> None:
        source = _CONTROLLER.replace(
            "import { Controller, Get, Post, Put, Delete } from '@nestjs/common';\n", ""
        )
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"articles.controller.ts": source})
        self.assertEqual(endpoints, set())

    def test_non_literal_controller_prefix_skips_all_routes(self) -> None:
        # If the controller prefix isn't a literal, we can't build correct paths -> skip the whole
        # controller rather than emit prefix-less routes.
        source = """import { Controller, Get } from '@nestjs/common';
const PREFIX = 'articles';
@Controller(PREFIX)
export class ArticlesController {
  @Get('feed')
  feed() {}
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"articles.controller.ts": source})
        self.assertEqual(endpoints, set())

    def test_non_literal_route_template_is_skipped(self) -> None:
        source = """import { Controller, Get } from '@nestjs/common';
const PATH = ':id';
@Controller('items')
export class ItemsController {
  @Get(PATH)
  one() {}

  @Get('all')
  all() {}
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"items.controller.ts": source})
        self.assertEqual(endpoints, {("GET", "/items/all")})


if __name__ == "__main__":
    unittest.main()
