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

        self.assertEqual(project["name"], "supercontext")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["readme"], "README.md")
        self.assertIn("PyYAML>=6.0", project["dependencies"])
        self.assertIn("classifiers", project)
        self.assertIn("Repository", project["urls"])
        self.assertIn("agent", project["optional-dependencies"])
        self.assertIn("eval", project["optional-dependencies"])
        self.assertIn("langsmith>=0.4.43", project["optional-dependencies"]["eval"])

    def test_console_script_targets_import(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        for target in data["project"]["scripts"].values():
            module_name, function_name = target.split(":", maxsplit=1)
            module = importlib.import_module(module_name)
            self.assertTrue(callable(getattr(module, function_name)))

    def test_console_script_targets_are_in_discovered_packages(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        for target in data["project"]["scripts"].values():
            module_name = target.split(":", maxsplit=1)[0]
            package_name = module_name.rsplit(".", maxsplit=1)[0]
            package_path = ROOT.joinpath(*package_name.split("."))
            with self.subTest(package=package_name):
                self.assertTrue((package_path / "__init__.py").exists())

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

        self.assertIn("ts_parser.mjs", package_data["source.kg.languages.typescript.extractors"])
        self.assertTrue((ROOT / "source/kg/languages/typescript/extractors/ts_parser.mjs").exists())
        for package in (
            "source.kg.languages.python",
            "source.kg.languages.typescript",
            "source.kg.languages.dotnet",
        ):
            self.assertIn("known_stacks.yaml", package_data[package])
            self.assertTrue((ROOT / Path(*package.split(".")) / "known_stacks.yaml").exists())
            self.assertIn("dimension_rules.yaml", package_data[package])
            self.assertTrue((ROOT / Path(*package.split(".")) / "dimension_rules.yaml").exists())

    def test_mcp_skill_templates_are_packaged(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package_data = data["tool"]["setuptools"]["package-data"]

        self.assertIn("mcp_skill_templates/*/supercontext-mcp/*", package_data["source.kg.product"])
        self.assertTrue(
            (
                ROOT
                / "source/kg/product/mcp_skill_templates/codex/supercontext-mcp/SKILL.md"
            ).exists()
        )
        self.assertTrue(
            (
                ROOT
                / "source/kg/product/mcp_skill_templates/claude/supercontext-mcp/SKILL.md"
            ).exists()
        )
        codex_skill = (ROOT / "source/kg/product/mcp_skill_templates/codex/supercontext-mcp/SKILL.md").read_text(
            encoding="utf-8"
        )
        claude_skill = (ROOT / "source/kg/product/mcp_skill_templates/claude/supercontext-mcp/SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Trace Evaluation", codex_skill)
        self.assertIn("Trace Evaluation", claude_skill)
        self.assertIn("answerability.status", codex_skill)
        self.assertIn("changed_surface", codex_skill)
        self.assertIn("runtime_surfaces", codex_skill)
        self.assertIn("source_coordinates", codex_skill)
        self.assertIn("summary.section_limit", codex_skill)
        self.assertIn("exact primitive tools", codex_skill)
        self.assertIn("answerability.status", claude_skill)
        self.assertIn("changed_surface", claude_skill)
        self.assertIn("runtime_surfaces", claude_skill)
        self.assertIn("source_coordinates", claude_skill)
        self.assertIn("summary.section_limit", claude_skill)
        self.assertIn("exact primitive tools", claude_skill)

    def test_eval_yaml_is_packaged(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package_data = data["tool"]["setuptools"]["package-data"]

        self.assertIn("*.yaml", package_data["source.kg.eval"])
        self.assertTrue((ROOT / "source/kg/eval/default_v1_tasks.yaml").exists())


if __name__ == "__main__":
    unittest.main()
