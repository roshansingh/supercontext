from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.repo_source import discover_repo
from source.kg.languages.types import ConsumerDependency, ConsumerManifestResult
from source.kg.metrics.dimension import classify_repo


class DimensionClassifierTest(unittest.TestCase):
    def test_detects_python_backend_from_ast_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertIn("backend", {row.dimension for row in assignments})

    def test_detects_typescript_frontend_from_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text('{"dependencies": {"react": "latest"}}\n', encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "index.tsx").write_text("export const App = () => null;\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertIn("frontend", {row.dimension for row in assignments})

    def test_detects_typescript_frontend_from_nested_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "apps" / "web"
            (app / "src").mkdir(parents=True)
            (app / "package.json").write_text('{"dependencies": {"react": "latest"}}\n', encoding="utf-8")
            (app / "src" / "index.tsx").write_text("export const App = () => null;\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertIn("frontend", {row.dimension for row in assignments})

    def test_detects_python_data_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dag.py").write_text("from airflow import DAG\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertIn("data-pipeline", {row.dimension for row in assignments})

    def test_detects_mixed_repo_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "api.py").write_text("import fastapi\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies": {"react": "latest"}}\n', encoding="utf-8")
            (root / "ui.tsx").write_text("export const App = () => null;\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertGreaterEqual({row.dimension for row in assignments}, {"backend", "frontend"})

    def test_ignores_package_manifests_under_ignored_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "index.tsx").write_text("export const App = () => null;\n", encoding="utf-8")
            package_dir = root / "node_modules" / "react"
            package_dir.mkdir(parents=True)
            (package_dir / "package.json").write_text('{"name": "react"}\n', encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertNotIn("frontend", {row.dimension for row in assignments})

    def test_ignores_non_object_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text("[]\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "index.tsx").write_text("export const App = () => null;\n", encoding="utf-8")

            assignments = classify_repo(discover_repo(root))

            self.assertNotIn("frontend", {row.dimension for row in assignments})

    def test_package_rules_use_language_consumer_manifest_hook(self) -> None:
        language = _ExampleLanguageSupport()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "app.example").write_text("example source\n", encoding="utf-8")
            (root / "example.lock").write_text("Example_Web 1.0.0\n", encoding="utf-8")

            repo = discover_repo(root, language_files=(language,))
            assignments = classify_repo(repo, registered_languages=(language,))

        self.assertIn("backend", {row.dimension for row in assignments})


class _ExampleManifestExtractor:
    def extract(self, repo: RepoSnapshot) -> ConsumerManifestResult:
        return ConsumerManifestResult(
            dependencies=(
                ConsumerDependency(
                    declared_name="Example_Web",
                    declared_version="1.0.0",
                    dependency_kind="example.lock",
                    manifest_path=repo.root / "example.lock",
                    line_number=1,
                    spec_form="registry",
                    target_url=None,
                ),
            )
        )


class _ExampleLanguageSupport:
    name = "example"
    aliases: tuple[str, ...] = ()
    file_extensions = frozenset({".example"})
    manifest_files = frozenset({"example.lock"})

    def matches_file(self, path: Path) -> bool:
        return path.suffix == ".example"

    def consumer_manifest_extractor(self) -> _ExampleManifestExtractor:
        return _ExampleManifestExtractor()

    def dimension_rules(self) -> dict:
        return {
            "version": 1,
            "rules": [
                {
                    "id": "example-backend-package",
                    "dimension": "backend",
                    "packages": ["example-web"],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
