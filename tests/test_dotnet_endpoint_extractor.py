from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.file_formats._shared.common import ConfigKgBuild
from source.kg.file_formats._shared.endpoints import extract_dotnet_endpoints
from source.kg.file_formats._shared.static_config import StaticConfigExtractor
from source.kg.languages.dotnet.extractors.parser_bridge import parse_dotnet_repo


def _dotnet_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c_sharp  # noqa: F401
    except ImportError:
        return False
    return True


DOTNET_AVAILABLE = _dotnet_available()


def _endpoints(tmp: str, files: dict[str, str]) -> set[tuple[str, str]]:
    root = Path(tmp)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    repo = discover_repo(root)
    build = ConfigKgBuild()
    service = StaticConfigExtractor()._service_entity(repo, "default")
    extract_dotnet_endpoints(repo, parse_dotnet_repo(repo), service, build, "default")
    return {
        (e.identity.get("method"), e.identity.get("path"))
        for e in build.entities
        if e.kind == "Endpoint"
    }


@unittest.skipIf(not DOTNET_AVAILABLE, "tree-sitter and tree-sitter-c-sharp not installed; install with pip install -e '.[dotnet]'")
class DotnetEndpointExtractorTest(unittest.TestCase):
    def test_controller_routes_combine_class_prefix_and_method_path(self) -> None:
        source = """using Microsoft.AspNetCore.Mvc;
namespace App;
[Route("articles")]
public class ArticlesController
{
    [HttpGet("{slug}")]
    public object Get(string slug) => null;

    [HttpPost]
    public object Create() => null;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"ArticlesController.cs": source})
        self.assertEqual(endpoints, {("GET", "/articles/{slug}"), ("POST", "/articles")})

    def test_controller_route_token_resolves_controller_name(self) -> None:
        source = """using Microsoft.AspNetCore.Mvc;
namespace App;
[Route("[controller]")]
public class ProductsController
{
    [HttpGet]
    public object All() => null;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"ProductsController.cs": source})
        self.assertEqual(endpoints, {("GET", "/products")})

    def test_minimal_api_direct_route(self) -> None:
        source = """using Microsoft.AspNetCore.Builder;
public class Endpoints
{
    public void Map(WebApplication app)
    {
        app.MapGet("/basket/{userName}", () => "ok");
        app.MapPost("/basket", () => "ok");
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"Endpoints.cs": source})
        self.assertEqual(endpoints, {("GET", "/basket/{userName}"), ("POST", "/basket")})

    def test_minimal_api_mapgroup_prefix_is_applied(self) -> None:
        source = """using Microsoft.AspNetCore.Builder;
public class Endpoints
{
    public void Map(WebApplication app)
    {
        var api = app.MapGroup("api/orders").HasApiVersion(1.0);
        api.MapGet("/cardtypes", () => "ok");
        api.MapPost("/draft", () => "ok");
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"Endpoints.cs": source})
        self.assertEqual(endpoints, {("GET", "/api/orders/cardtypes"), ("POST", "/api/orders/draft")})

    def test_named_attribute_argument_is_not_treated_as_route(self) -> None:
        # `[HttpGet(Name = "List")]` has no positional route; Name is metadata, not a path.
        source = """using Microsoft.AspNetCore.Mvc;
namespace App;
[Route("items")]
public class ItemsController
{
    [HttpGet(Name = "ListItems")]
    public object List() => null;

    [HttpGet("{id}", Name = "GetItem")]
    public object Get(int id) => null;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"ItemsController.cs": source})
        self.assertEqual(endpoints, {("GET", "/items"), ("GET", "/items/{id}")})

    def test_method_without_any_route_template_is_skipped(self) -> None:
        # `[HttpGet]` with no class `[Route]` => no resolvable template; must not emit "/".
        source = """using Microsoft.AspNetCore.Mvc;
namespace App;
public class ThingsController
{
    [HttpGet]
    public object All() => null;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"ThingsController.cs": source})
        self.assertEqual(endpoints, set())

    def test_non_literal_route_is_not_emitted(self) -> None:
        source = """using Microsoft.AspNetCore.Builder;
public class Endpoints
{
    public void Map(WebApplication app)
    {
        var path = Configure();
        app.MapGet(path, () => "ok");
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            endpoints = _endpoints(tmp, {"Endpoints.cs": source})
        self.assertEqual(endpoints, set())


if __name__ == "__main__":
    unittest.main()
