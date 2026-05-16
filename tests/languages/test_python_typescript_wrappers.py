from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from source.kg.core.repo_source import RepoSnapshot, discover_repo
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.languages.python.language import LANGUAGE_SUPPORT as PYTHON_SUPPORT
from source.kg.languages.typescript.language import LANGUAGE_SUPPORT as TYPESCRIPT_SUPPORT


class PythonTypeScriptWrapperTest(unittest.TestCase):
    def test_python_wrapper_exposes_existing_adapter_names_and_roots(self) -> None:
        ctx = ExtractionContext()
        ctx.python_import_roots.update({"flask"})

        self.assertEqual(
            [adapter.capability.name for adapter in PYTHON_SUPPORT.adapters()],
            ["legacy-python-ast", "python-boto3-transport"],
        )
        self.assertEqual(PYTHON_SUPPORT.source_roots(_repo_snapshot(), ctx), {"python": {"flask"}})

    def test_typescript_wrapper_exposes_existing_adapter_names_and_javascript_roots(self) -> None:
        ctx = ExtractionContext()
        ctx.js_ts_import_roots.update({"express"})

        self.assertEqual(
            [adapter.capability.name for adapter in TYPESCRIPT_SUPPORT.adapters()],
            ["typescript-express-routes", "legacy-typescript-compiler-api"],
        )
        self.assertEqual(TYPESCRIPT_SUPPORT.source_roots(_repo_snapshot(), ctx), {"javascript": {"express"}})

    def test_typescript_matcher_preserves_declaration_file_exclusion(self) -> None:
        self.assertFalse(TYPESCRIPT_SUPPORT.matches_file(Path("types/foo.d.ts")))
        self.assertTrue(TYPESCRIPT_SUPPORT.matches_file(Path("src/index.ts")))
        self.assertTrue(TYPESCRIPT_SUPPORT.matches_file(Path("src/index.jsx")))

    def test_repo_discovery_populates_generic_language_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python_file = root / "app.py"
            ts_file = root / "src" / "index.ts"
            declaration_file = root / "src" / "types.d.ts"
            ts_file.parent.mkdir()
            python_file.write_text("print('ok')\n", encoding="utf-8")
            ts_file.write_text("export const ok = true;\n", encoding="utf-8")
            declaration_file.write_text("declare const value: string;\n", encoding="utf-8")

            repo = discover_repo(root)

        self.assertEqual(repo.python_files, (python_file.resolve(),))
        self.assertEqual(repo.typescript_files, (ts_file.resolve(),))
        self.assertEqual(repo.files_by_language["python"], (python_file.resolve(),))
        self.assertEqual(repo.files_by_language["typescript"], (ts_file.resolve(),))


def _repo_snapshot() -> RepoSnapshot:
    return RepoSnapshot(root=Path("/tmp/bettercontext-language-test"), name="repo", owner="test", commit_sha="sha")


if __name__ == "__main__":
    unittest.main()
