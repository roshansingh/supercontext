from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.dotnet.consumer_manifest import DotnetConsumerManifestExtractor
from source.kg.languages.python.consumer_manifest import PythonConsumerManifestExtractor
from source.kg.languages.typescript.consumer_manifest import TypeScriptConsumerManifestExtractor


class ConsumerManifestExtractorTest(unittest.TestCase):
    def test_typescript_package_json_dependency_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {
                            "@acme/shared": "workspace:*",
                            "@acme/client": "git+https://github.com/acme/client.git",
                            "local-lib": "file:../local-lib",
                            "linked-lib": "link:../linked-lib",
                            "react": "^18.2.0",
                        },
                        "devDependencies": {"vite": "^5.0.0"},
                    }
                ),
                encoding="utf-8",
            )

            result = TypeScriptConsumerManifestExtractor().extract(_repo(root))

        by_name = {dependency.declared_name: dependency for dependency in result.dependencies}
        self.assertEqual(by_name["@acme/shared"].spec_form, "workspace")
        self.assertEqual(by_name["@acme/client"].spec_form, "git_url")
        self.assertEqual(by_name["local-lib"].spec_form, "file_path")
        self.assertEqual(by_name["local-lib"].target_url, "../local-lib")
        self.assertEqual(by_name["linked-lib"].spec_form, "file_path")
        self.assertEqual(by_name["react"].spec_form, "registry")
        self.assertEqual(by_name["vite"].dependency_kind, "devDependencies")
        self.assertEqual(result.issues, ())

    def test_typescript_nested_package_json_dependency_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = root / "apps" / "web"
            app.mkdir(parents=True)
            (app / "package.json").write_text(
                json.dumps({"dependencies": {"react": "^18.2.0"}}),
                encoding="utf-8",
            )

            result = TypeScriptConsumerManifestExtractor().extract(_repo(root))

        self.assertEqual([dependency.declared_name for dependency in result.dependencies], ["react"])
        self.assertEqual(result.dependencies[0].manifest_path, app / "package.json")
        self.assertEqual(result.issues, ())

    def test_typescript_ignores_package_json_under_ignored_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ignored = root / "node_modules" / "react"
            ignored.mkdir(parents=True)
            (ignored / "package.json").write_text(
                json.dumps({"dependencies": {"ignored": "^1.0.0"}}),
                encoding="utf-8",
            )

            result = TypeScriptConsumerManifestExtractor().extract(_repo(root))

        self.assertEqual(result.dependencies, ())
        self.assertEqual(result.issues, ())

    def test_typescript_malformed_package_json_reports_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text("{not-json}\n", encoding="utf-8")

            result = TypeScriptConsumerManifestExtractor().extract(_repo(root))

        self.assertEqual(result.dependencies, ())
        self.assertEqual(result.issues[0].reason, "cross_repo_dependency_manifest_unreadable")
        self.assertEqual(result.issues[0].language, "typescript")

    def test_python_pyproject_and_requirements_dependency_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "\n".join(
                    (
                        "[project]",
                        'dependencies = ["requests>=2", "shared @ git+https://github.com/acme/shared.git"]',
                        "[tool.poetry.dependencies]",
                        'python = "^3.12"',
                        'local-lib = { path = "../local-lib" }',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text(
                "git+https://github.com/acme/client.git#egg=client-lib\n"
                "-e ../editable#egg=editable-lib\n"
                "--index-url=https://packages.example/simple\n"
                "-c constraints.txt\n",
                encoding="utf-8",
            )

            result = PythonConsumerManifestExtractor().extract(_repo(root))

        by_name = {dependency.declared_name: dependency for dependency in result.dependencies}
        self.assertEqual(by_name["requests"].spec_form, "registry")
        self.assertEqual(by_name["shared"].spec_form, "git_url")
        self.assertEqual(by_name["local-lib"].spec_form, "file_path")
        self.assertEqual(by_name["client-lib"].spec_form, "git_url")
        self.assertEqual(by_name["editable-lib"].spec_form, "file_path")
        self.assertNotIn("-c", by_name)
        self.assertNotIn("--index-url", by_name)
        self.assertNotIn("python", by_name)
        self.assertEqual(result.issues, ())

    def test_python_extracts_optional_group_setup_cfg_and_named_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            requirements_dir = root / "requirements"
            requirements_dir.mkdir()
            (root / "pyproject.toml").write_text(
                "\n".join(
                    (
                        "[project.optional-dependencies]",
                        'dev = ["pytest>=8", "typing-extensions>=4"]',
                        "[tool.poetry.group.dev.dependencies]",
                        'ruff = "^0.6.0"',
                        'local-tool = { path = "../local-tool" }',
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "setup.cfg").write_text(
                "\n".join(
                    (
                        "[options]",
                        "install_requires =",
                        "    requests>=2",
                        "    PyYAML>=6",
                        "[options.extras_require]",
                        "test =",
                        "    pandas>=2",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "requirements-dev.txt").write_text("numpy>=1\n", encoding="utf-8")
            (requirements_dir / "lint.txt").write_text("mypy>=1\n", encoding="utf-8")

            result = PythonConsumerManifestExtractor().extract(_repo(root))

        by_name = {dependency.declared_name: dependency for dependency in result.dependencies}
        self.assertEqual(by_name["pytest"].dependency_kind, "project.optional-dependencies.dev")
        self.assertEqual(by_name["typing-extensions"].dependency_kind, "project.optional-dependencies.dev")
        self.assertEqual(by_name["ruff"].dependency_kind, "tool.poetry.group.dev.dependencies")
        self.assertEqual(by_name["local-tool"].spec_form, "file_path")
        self.assertEqual(by_name["local-tool"].target_url, "../local-tool")
        self.assertEqual(by_name["requests"].dependency_kind, "setup.cfg:options.install_requires")
        self.assertEqual(by_name["PyYAML"].dependency_kind, "setup.cfg:options.install_requires")
        self.assertEqual(by_name["pandas"].dependency_kind, "setup.cfg:options.extras_require.test")
        self.assertEqual(by_name["numpy"].dependency_kind, "requirements-dev.txt")
        self.assertEqual(by_name["mypy"].dependency_kind, "requirements/lint.txt")
        self.assertEqual(result.issues, ())

    def test_python_malformed_pyproject_reports_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project\n", encoding="utf-8")

            result = PythonConsumerManifestExtractor().extract(_repo(root))

        self.assertEqual(result.dependencies, ())
        self.assertEqual(result.issues[0].reason, "cross_repo_dependency_manifest_unreadable")
        self.assertEqual(result.issues[0].language, "python")

    def test_dotnet_csproj_dependency_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "App.csproj").write_text(
                """
<Project>
  <ItemGroup>
    <ProjectReference Include="..\\Shared\\Shared.csproj" />
    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />
  </ItemGroup>
</Project>
""".strip()
                + "\n",
                encoding="utf-8",
            )

            result = DotnetConsumerManifestExtractor().extract(_repo(root))

        by_name = {dependency.declared_name: dependency for dependency in result.dependencies}
        self.assertEqual(by_name["Shared"].spec_form, "file_path")
        self.assertEqual(by_name["Shared"].target_url, "..\\Shared\\Shared.csproj")
        self.assertEqual(by_name["Newtonsoft.Json"].spec_form, "registry")
        self.assertEqual(by_name["Newtonsoft.Json"].declared_version, "13.0.3")
        self.assertEqual(result.issues, ())

    def test_dotnet_malformed_csproj_reports_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "App.csproj").write_text("<Project>\n", encoding="utf-8")

            result = DotnetConsumerManifestExtractor().extract(_repo(root))

        self.assertEqual(result.dependencies, ())
        self.assertEqual(result.issues[0].reason, "cross_repo_dependency_manifest_unreadable")
        self.assertEqual(result.issues[0].language, "dotnet")


def _repo(path: Path) -> RepoSnapshot:
    return RepoSnapshot(path, path.name, path.parent.name, "working-tree", {})


if __name__ == "__main__":
    unittest.main()
