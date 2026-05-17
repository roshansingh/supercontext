from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.extraction.framework.adapter import AdapterCapability, AdapterResult, ExtractionContext
from source.kg.extraction.framework.runner import run_adapters


class RunnerDimensionTaggingTest(unittest.TestCase):
    def test_unsupported_known_stack_coverage_gets_dimension_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"express": "^4.18.0"}}),
                encoding="utf-8",
            )
            app = root / "apps" / "api" / "server.ts"
            app.parent.mkdir(parents=True)
            app.write_text("import express from 'express';\n", encoding="utf-8")
            repo = discover_repo(root)

            _, _, _, coverage, errors = run_adapters(
                repo,
                (_ImportRootAdapter(javascript_roots=("express",)),),
                ctx=ExtractionContext(),
            )

        self.assertEqual(errors, [])
        rows = _known_stack_rows(coverage)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].scope_ref["dimension"], "backend")
        self.assertEqual(rows[0].scope_ref["path_prefix"], "apps/api")

    def test_adapter_error_coverage_remains_untagged_without_dimension_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"express": "^4.18.0"}}),
                encoding="utf-8",
            )
            (root / "app.js").write_text("import express from 'express';\n", encoding="utf-8")
            repo = discover_repo(root)

            _, _, _, coverage, errors = run_adapters(
                repo,
                (_FailingAdapter(),),
                ctx=ExtractionContext(),
            )

        self.assertEqual(errors[0]["error"], "RuntimeError")
        adapter_error = [row for row in coverage if row.scope_ref.get("reason") == "adapter_error"][0]
        self.assertNotIn("dimension", adapter_error.scope_ref)
        self.assertNotIn("path_prefix", adapter_error.scope_ref)


@dataclass(frozen=True)
class _ImportRootAdapter:
    javascript_roots: tuple[str, ...]

    @property
    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            name="test-import-roots",
            languages=("typescript",),
            source_system="test_import_roots_v0",
        )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        ctx.import_roots_by_language.setdefault("javascript", set()).update(self.javascript_roots)
        return AdapterResult()


@dataclass(frozen=True)
class _FailingAdapter:
    @property
    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            name="test-failing",
            languages=("typescript",),
            source_system="test_failing_v0",
        )

    def applies_to(self, repo: RepoSnapshot, ctx: ExtractionContext) -> bool:
        return True

    def extract(self, repo: RepoSnapshot, ctx: ExtractionContext) -> AdapterResult:
        raise RuntimeError("boom")


def _known_stack_rows(coverage: list) -> list:
    return [row for row in coverage if row.scope_ref.get("reason") == "no_adapter_for_known_stack"]


if __name__ == "__main__":
    unittest.main()
