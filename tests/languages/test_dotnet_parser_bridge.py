from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.languages.dotnet.extractors.parser_bridge import _parse_dotnet_repo_uncached
from source.kg.languages.dotnet.extractors.parser_bridge import parse_dotnet_repo


def _dotnet_dependencies_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c_sharp  # noqa: F401
    except ImportError:
        return False
    return True


DOTNET_AVAILABLE = _dotnet_dependencies_available()


class DotnetParserBridgeDependencyTest(unittest.TestCase):
    def test_missing_dependency_error_mentions_dotnet_extra(self) -> None:
        repo = RepoSnapshot(
            root=Path("/tmp/supercontext-dotnet-missing-deps"),
            name="repo",
            owner="test",
            commit_sha="sha",
            files_by_language={"dotnet": ()},
        )

        original_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "tree_sitter":
                raise ImportError("missing tree_sitter")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError) as raised:
                _parse_dotnet_repo_uncached(repo)
        message = str(raised.exception)
        self.assertIn("pip install -e", message)
        self.assertIn("supercontext[dotnet]", message)


@unittest.skipIf(not DOTNET_AVAILABLE, "tree-sitter and tree-sitter-c-sharp not installed; install with pip install -e '.[dotnet]'")
class DotnetParserBridgeTest(unittest.TestCase):
    def test_parses_minimal_file_into_per_file_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Foo.cs").write_text(
                "using System;\n"
                "namespace Demo {\n"
                "    public class Foo {\n"
                "        public void Bar() { Console.WriteLine(\"hi\"); }\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)
            ctx = ExtractionContext()

            parsed = parse_dotnet_repo(repo, ctx)

            self.assertIn("Foo.cs", parsed)
            entry = parsed["Foo.cs"]
            self.assertIn("imports", entry)
            self.assertIn("symbols", entry)
            self.assertIn("calls", entry)
            self.assertIn("parse_diagnostics", entry)

            import_targets = [imp["raw_target"] for imp in entry["imports"]]
            self.assertIn("System", import_targets)

            symbol_names = {sym["name"] for sym in entry["symbols"]}
            self.assertIn("Demo.Foo", symbol_names)
            self.assertTrue(any(name.endswith("Bar") for name in symbol_names))

    def test_cache_returns_same_object_for_same_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "A.cs").write_text("class A {}\n", encoding="utf-8")
            repo = discover_repo(root)
            ctx = ExtractionContext()

            first = parse_dotnet_repo(repo, ctx)
            second = parse_dotnet_repo(repo, ctx)

            self.assertIs(first, second)

    def test_alias_using_records_target_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Alias.cs").write_text(
                "using Json = System.Text.Json;\n"
                "class A {}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            parsed = parse_dotnet_repo(repo)

            self.assertEqual(
                [imp["raw_target"] for imp in parsed["Alias.cs"]["imports"]],
                ["System.Text.Json"],
            )

    def test_top_level_statement_calls_have_module_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Program.cs").write_text(
                "namespace Demo.Api;\n"
                "new Worker().Run();\n"
                "class Worker { public void Run() {} }\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            parsed = parse_dotnet_repo(repo)
            entry = parsed["Program.cs"]

            self.assertIn("Demo.Api.<module>", {sym["name"] for sym in entry["symbols"]})
            self.assertTrue(
                any(
                    call["caller"] == "Demo.Api.<module>"
                    and call["caller_key"] == "Demo.Api.<module>"
                    and call["name"] == "new Worker().Run"
                    and call["arity"] == 0
                    and call["line"] == 2
                    for call in entry["calls"]
                ),
                entry["calls"],
            )

    def test_reference_type_return_does_not_replace_method_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Greeter.cs").write_text(
                "class Greeter {\n"
                "    public Result DoWork() { return null; }\n"
                "    public Result Value { get; }\n"
                "}\n"
                "class Result {}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            parsed = parse_dotnet_repo(repo)
            symbol_names = {sym["name"] for sym in parsed["Greeter.cs"]["symbols"]}

            self.assertIn("Greeter.DoWork", symbol_names)
            self.assertIn("Greeter.Value", symbol_names)
            self.assertIn("Result", symbol_names)
            self.assertNotIn("Greeter.Result", symbol_names)

    def test_namespaces_qualify_duplicate_symbol_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Workers.cs").write_text(
                "namespace Alpha { class Worker { public void Run() {} } }\n"
                "namespace Beta { class Worker { public void Run() {} } }\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            parsed = parse_dotnet_repo(repo)
            symbols = parsed["Workers.cs"]["symbols"]

            self.assertIn("Alpha.Worker", {sym["name"] for sym in symbols})
            self.assertIn("Beta.Worker", {sym["name"] for sym in symbols})
            self.assertIn("Alpha.Worker.Run", {sym["name"] for sym in symbols})
            self.assertIn("Beta.Worker.Run", {sym["name"] for sym in symbols})
            self.assertIn("Alpha.Worker.Run/0", {sym["key"] for sym in symbols})
            self.assertIn("Beta.Worker.Run/0", {sym["key"] for sym in symbols})

    def test_overloaded_methods_have_distinct_symbol_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Greeter.cs").write_text(
                "class Greeter {\n"
                "    public void Say() {}\n"
                "    public void Say(string name) {}\n"
                "    public void Run() { Say(); Say(\"Ada\"); }\n"
                "}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            parsed = parse_dotnet_repo(repo)
            entry = parsed["Greeter.cs"]
            say_symbols = [
                sym
                for sym in entry["symbols"]
                if sym["name"] == "Greeter.Say"
            ]

            self.assertEqual({sym["key"] for sym in say_symbols}, {"Greeter.Say/0", "Greeter.Say/1"})
            self.assertEqual({sym["signature"] for sym in say_symbols}, {"Say/0", "Say/1"})
            self.assertEqual({sym["arity"] for sym in say_symbols}, {0, 1})
            self.assertEqual(
                [
                    (call["caller_key"], call["name"], call["arity"])
                    for call in entry["calls"]
                    if call["name"] == "Say"
                ],
                [("Greeter.Run/0", "Say", 0), ("Greeter.Run/0", "Say", 1)],
            )


if __name__ == "__main__":
    unittest.main()
