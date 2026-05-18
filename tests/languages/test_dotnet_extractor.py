from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.languages.dotnet.extractors.csharp_extractor import CSharpExtractor


def _dotnet_dependencies_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_c_sharp  # noqa: F401
    except ImportError:
        return False
    return True


DOTNET_AVAILABLE = _dotnet_dependencies_available()


@unittest.skipIf(not DOTNET_AVAILABLE, "tree-sitter and tree-sitter-c-sharp not installed; install with pip install -e '.[dotnet]'")
class CSharpExtractorTest(unittest.TestCase):
    def test_minimal_repo_emits_expected_entity_kinds_and_facts(self) -> None:
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

            build = CSharpExtractor().extract_with_context(repo, ctx)

            entity_counts = Counter(entity.kind for entity in build.entities)
            self.assertEqual(entity_counts["Repo"], 1)
            self.assertEqual(entity_counts["Service"], 1)
            self.assertEqual(entity_counts["CodeModule"], 1)
            self.assertGreaterEqual(entity_counts["CodeSymbol"], 2)
            self.assertGreaterEqual(entity_counts["ExternalPackage"], 1)

            fact_predicates = Counter(fact.predicate for fact in build.facts)
            self.assertGreaterEqual(fact_predicates["DEFINED_IN"], 3)
            self.assertEqual(fact_predicates["IMPLEMENTS"], 1)
            self.assertEqual(fact_predicates["IMPORTS"], 1)

            for evidence in build.evidence:
                if evidence.source_system in {"git"}:
                    continue
                self.assertIsNotNone(evidence.bytes_ref, f"missing bytes_ref on {evidence.source_system} evidence")

            self.assertIn("System", ctx.import_roots_by_language.get("dotnet", set()))

            self.assertTrue(any(
                row.predicate == "PARSES" and row.state == "instrumented"
                for row in build.coverage
            ))

    def test_top_level_statement_can_call_local_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Program.cs").write_text(
                "namespace Demo.Api;\n"
                "new Worker().Run();\n"
                "class Worker { public void Run() {} }\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            build = CSharpExtractor().extract(repo)
            entities = {entity.entity_id: entity for entity in build.entities}
            calls = [
                fact
                for fact in build.facts
                if fact.predicate == "CALLS"
            ]

            self.assertEqual(len(calls), 1)
            caller = entities[calls[0].subject_id]
            callee = entities[calls[0].object_id]
            self.assertEqual(caller.identity["qualname"], "<module>")
            self.assertEqual(callee.identity["qualname"], "Worker.Run")

    def test_reference_type_return_preserves_method_symbol_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Greeter.cs").write_text(
                "class Greeter {\n"
                "    public Result DoWork() { return null; }\n"
                "}\n"
                "class Result {}\n",
                encoding="utf-8",
            )
            repo = discover_repo(root)

            build = CSharpExtractor().extract(repo)
            qualnames = {
                entity.identity["qualname"]
                for entity in build.entities
                if entity.kind == "CodeSymbol"
            }

            self.assertIn("Greeter.DoWork", qualnames)
            self.assertIn("Result", qualnames)
            self.assertNotIn("Greeter.Result", qualnames)

    def test_overloaded_methods_do_not_collapse_symbol_identities(self) -> None:
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

            build = CSharpExtractor().extract(repo)
            entities = {entity.entity_id: entity for entity in build.entities}
            say_symbols = [
                entity
                for entity in build.entities
                if entity.kind == "CodeSymbol" and entity.identity["qualname"] == "Greeter.Say"
            ]
            calls = [
                fact
                for fact in build.facts
                if fact.predicate == "CALLS"
            ]

            self.assertEqual(
                {symbol.identity["signature"] for symbol in say_symbols},
                {"Say/0", "Say/1"},
            )
            self.assertEqual(len({symbol.entity_id for symbol in say_symbols}), 2)
            self.assertEqual(
                {
                    (
                        entities[fact.subject_id].identity["signature"],
                        entities[fact.object_id].identity["signature"],
                    )
                    for fact in calls
                },
                {("Run/0", "Say/0"), ("Run/0", "Say/1")},
            )


if __name__ == "__main__":
    unittest.main()
