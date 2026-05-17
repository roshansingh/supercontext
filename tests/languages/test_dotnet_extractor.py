from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from source.kg.core.repo_source import discover_repo
from source.kg.extraction.framework.adapter import ExtractionContext

try:
    from source.kg.languages.dotnet.extractors.csharp_extractor import CSharpExtractor
    DOTNET_AVAILABLE = True
except RuntimeError:
    DOTNET_AVAILABLE = False


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


if __name__ == "__main__":
    unittest.main()
