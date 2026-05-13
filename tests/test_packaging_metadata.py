from __future__ import annotations

import importlib
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTest(unittest.TestCase):
    def test_pyproject_declares_installable_project_metadata(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]

        self.assertEqual(project["name"], "bettercontext")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["readme"], "README.md")
        self.assertIn("classifiers", project)
        self.assertIn("Repository", project["urls"])
        self.assertIn("yaml", project["optional-dependencies"])
        self.assertIn("agent", project["optional-dependencies"])

    def test_console_script_targets_import(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        for target in data["project"]["scripts"].values():
            module_name, function_name = target.split(":", maxsplit=1)
            module = importlib.import_module(module_name)
            self.assertTrue(callable(getattr(module, function_name)))

    def test_script_modules_render_help(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        for target in data["project"]["scripts"].values():
            module_name = target.split(":", maxsplit=1)[0]
            with self.subTest(module=module_name):
                result = subprocess.run(
                    [sys.executable, "-m", module_name, "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)

    def test_typescript_parser_bridge_is_packaged(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package_data = data["tool"]["setuptools"]["package-data"]

        self.assertIn("ts_parser.mjs", package_data["source.kg.extraction.typescript"])
        self.assertTrue((ROOT / "source/kg/extraction/typescript/ts_parser.mjs").exists())


if __name__ == "__main__":
    unittest.main()
