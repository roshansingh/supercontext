from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import discover_repo
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


if __name__ == "__main__":
    unittest.main()
