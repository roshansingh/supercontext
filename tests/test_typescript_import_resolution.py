from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.typescript.extractors.compiler_api_extractor import TypeScriptCompilerApiExtractor


class TypeScriptImportResolutionExtractorTest(unittest.TestCase):
    def test_resolved_imports_emit_code_module_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "tsconfig.base.json",
                '{"compilerOptions":{"baseUrl":".","paths":{"@acme/widgets":["libs/widgets/src/index.ts"]}}}\n',
            )
            _write(root / "apps" / "web" / "tsconfig.json", '{"extends":"../../tsconfig.base.json"}\n')
            app_spec = _write(
                root / "apps" / "web" / "src" / "app.component.spec.ts",
                "import { AppComponent } from './app.component';\n"
                "import { Widget } from '@acme/widgets';\n"
                "export const testDeps = [AppComponent, Widget];\n",
            )
            app_component = _write(
                root / "apps" / "web" / "src" / "app.component.ts",
                "export class AppComponent {}\n",
            )
            widgets = _write(root / "libs" / "widgets" / "src" / "index.ts", "export const Widget = 1;\n")
            repo = RepoSnapshot(
                root=root,
                name="web-client",
                owner="test",
                commit_sha="test-sha",
                files_by_language={"python": (), "typescript": (app_spec, app_component, widgets)},
            )

            build = TypeScriptCompilerApiExtractor().extract(repo)

            entities_by_id = {entity.entity_id: entity for entity in build.entities}
            imports = [fact for fact in build.facts if fact.predicate == "IMPORTS"]
            imports_by_raw = {fact.qualifier.get("raw_import"): fact for fact in imports}

            relative_import = imports_by_raw["./app.component"]
            alias_import = imports_by_raw["@acme/widgets"]

            self.assertEqual(relative_import.qualifier["category"], "relative_internal_module")
            self.assertEqual(entities_by_id[relative_import.object_id].kind, "CodeModule")
            self.assertEqual(
                entities_by_id[relative_import.object_id].identity["module"],
                "apps.web.src.app.component",
            )
            self.assertEqual(alias_import.qualifier["category"], "internal_module")
            self.assertEqual(entities_by_id[alias_import.object_id].kind, "CodeModule")
            self.assertEqual(entities_by_id[alias_import.object_id].identity["module"], "libs.widgets.src")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
