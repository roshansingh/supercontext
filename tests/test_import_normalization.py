from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.repo_source import RepoSnapshot
from source.kg.languages.python.normalization import imports as python_imports
from source.kg.languages.python.normalization.imports import ImportRef, PythonImportNormalizer
from source.kg.languages.typescript.module_resolution import (
    _is_path_like_extends_value,
    load_typescript_config_object,
    load_typescript_path_aliases,
)
from source.kg.languages.typescript.normalization import imports as typescript_imports
from source.kg.languages.typescript.normalization.imports import JsImportNormalizer, JsImportRef


class PythonImportNormalizationTest(unittest.TestCase):
    def test_package_init_relative_import_does_not_emit_empty_external_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "k8s_cloud_system"
            package.mkdir()
            init_py = package / "__init__.py"
            cli_py = package / "cli.py"
            init_py.write_text("from . import cli\n", encoding="utf-8")
            cli_py.write_text("def main():\n    pass\n", encoding="utf-8")
            repo = _repo_snapshot(root, python_paths=(init_py, cli_py))

            normalizer = PythonImportNormalizer(repo)
            [normalized] = normalizer.collect(ast.parse(init_py.read_text(encoding="utf-8")), "k8s_cloud_system")

            self.assertEqual(normalized.category, "relative_internal_module")
            self.assertEqual(normalized.target_name, "k8s_cloud_system")
            self.assertEqual(normalized.import_root, "k8s_cloud_system")
            self.assertEqual(normalized.imported_names, ("cli",))

    def test_distribution_metadata_maps_import_roots_to_declared_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\n"
                "dependencies = [\n"
                '  "beautifulsoup4>=4",\n'
                '  "python-dateutil",\n'
                '  "attrs",\n'
                '  "setuptools",\n'
                '  "protobuf",\n'
                "]\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={
                    "bs4": ["beautifulsoup4"],
                    "dateutil": ["python-dateutil"],
                    "attr": ["attrs"],
                    "pkg_resources": ["setuptools"],
                    "google": ["google-api-core", "protobuf"],
                },
            ):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            cases = {
                "bs4": "beautifulsoup4",
                "dateutil": "python-dateutil",
                "attr": "attrs",
                "pkg_resources": "setuptools",
                "google.protobuf": "protobuf",
            }
            for raw_import, expected_distribution in cases.items():
                with self.subTest(raw_import=raw_import):
                    normalized = normalizer.normalize(
                        ImportRef(
                            raw_target=raw_import,
                            line=1,
                            import_root=raw_import.split(".", 1)[0],
                            imported_names=(),
                            alias=None,
                        ),
                        current_module="app",
                    )

                    self.assertEqual(normalized.category, "third_party")
                    self.assertEqual(normalized.distribution_name, expected_distribution)
                    self.assertEqual(normalized.target_name, expected_distribution)

    def test_single_distribution_metadata_match_does_not_require_declared_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={"bs4": ["beautifulsoup4"]},
            ):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            normalized = normalizer.normalize(
                ImportRef(raw_target="bs4", line=1, import_root="bs4", imported_names=(), alias=None),
                current_module="app",
            )

            self.assertEqual(normalized.category, "third_party")
            self.assertEqual(normalized.distribution_name, "beautifulsoup4")

    def test_known_import_root_fallback_maps_declared_dependency_when_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"scikit-learn\", \"Pillow\", \"PyYAML\"]\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={},
            ):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            cases = {
                "sklearn": "scikit-learn",
                "PIL": "Pillow",
                "yaml": "PyYAML",
            }
            for raw_import, expected_distribution in cases.items():
                with self.subTest(raw_import=raw_import):
                    normalized = normalizer.normalize(
                        ImportRef(
                            raw_target=raw_import,
                            line=1,
                            import_root=raw_import.split(".", 1)[0],
                            imported_names=(),
                            alias=None,
                        ),
                        current_module="app",
                    )

                    self.assertEqual(normalized.category, "third_party")
                    self.assertEqual(normalized.distribution_name, expected_distribution)
                    self.assertEqual(normalized.target_name, expected_distribution)

    def test_known_import_root_fallback_prefers_declared_distribution_for_ambiguous_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"opencv-python-headless\"]\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={},
            ):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            normalized = normalizer.normalize(
                ImportRef(raw_target="cv2", line=1, import_root="cv2", imported_names=(), alias=None),
                current_module="app",
            )

            self.assertEqual(normalized.category, "third_party")
            self.assertEqual(normalized.distribution_name, "opencv-python-headless")

    def test_known_import_root_fallback_maps_all_single_candidate_aliases_without_metadata_or_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={},
            ):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            cases = {
                "attr": "attrs",
                "bs4": "beautifulsoup4",
                "dateutil": "python-dateutil",
                "PIL": "Pillow",
                "pkg_resources": "setuptools",
                "sklearn": "scikit-learn",
                "yaml": "PyYAML",
            }
            for raw_import, expected_distribution in cases.items():
                with self.subTest(raw_import=raw_import):
                    normalized = normalizer.normalize(
                        ImportRef(
                            raw_target=raw_import,
                            line=1,
                            import_root=raw_import.split(".", 1)[0],
                            imported_names=(),
                            alias=None,
                        ),
                        current_module="app",
                    )

                    self.assertEqual(normalized.category, "third_party")
                    self.assertEqual(normalized.distribution_name, expected_distribution)

    def test_ambiguous_known_import_root_without_declared_dependency_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={},
            ), patch("source.kg.languages.python.normalization.imports.util.find_spec", return_value=object()):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            normalized = normalizer.normalize(
                ImportRef(raw_target="cv2", line=1, import_root="cv2", imported_names=(), alias=None),
                current_module="app",
            )

            self.assertEqual(normalized.category, "unknown")
            self.assertIsNone(normalized.distribution_name)

    def test_ambiguous_known_import_root_with_multiple_declared_variants_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"opencv-python\", \"opencv-python-headless\"]\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={},
            ), patch("source.kg.languages.python.normalization.imports.util.find_spec", return_value=object()):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            normalized = normalizer.normalize(
                ImportRef(raw_target="cv2", line=1, import_root="cv2", imported_names=(), alias=None),
                current_module="app",
            )

            self.assertEqual(normalized.category, "unknown")
            self.assertIsNone(normalized.distribution_name)

    def test_namespace_package_with_multiple_declared_matches_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"google-api-core\", \"protobuf\"]\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, python_paths=(root / "app.py",))

            with patch(
                "source.kg.languages.python.normalization.imports.metadata.packages_distributions",
                return_value={"google": ["google-api-core", "protobuf"]},
            ), patch("source.kg.languages.python.normalization.imports.util.find_spec", return_value=object()):
                python_imports._distributions_by_import_root.cache_clear()
                normalizer = PythonImportNormalizer(repo)
            python_imports._distributions_by_import_root.cache_clear()

            dotted = normalizer.normalize(
                ImportRef(raw_target="google.protobuf", line=1, import_root="google", imported_names=(), alias=None),
                current_module="app",
            )
            root_import = normalizer.normalize(
                ImportRef(raw_target="google", line=1, import_root="google", imported_names=(), alias=None),
                current_module="app",
            )

            self.assertEqual(dotted.category, "unknown")
            self.assertEqual(root_import.category, "unknown")


class TypeScriptImportNormalizationTest(unittest.TestCase):
    def test_tsconfig_path_alias_resolves_internal_module_with_jsonc_and_fallback_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "tsconfig.json",
                "{\n"
                "  // jsonc comments are valid in tsconfig files\n"
                '  "compilerOptions": {\n'
                '    "baseUrl": ".",\n'
                '    "paths": {\n'
                '      "~/*": ["missing/*", "src/*",],\n'
                '      "@app/*": ["app/*"]\n'
                "    }\n"
                "  }\n"
                "}\n",
            )
            app = _write(root / "src" / "app.ts", "import { api } from '~/lib/api';\n")
            api = _write(root / "src" / "lib" / "api.ts", "export const api = 1;\n")
            view = _write(root / "app" / "view.ts", "export const view = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, api, view))
            normalizer = JsImportNormalizer(repo)

            alias = normalizer.normalize(_js_ref("~/lib/api"), "src.app", "src/app.ts")
            scoped_alias = normalizer.normalize(_js_ref("@app/view"), "src.app", "src/app.ts")

            self.assertEqual(alias.category, "internal_module")
            self.assertEqual(alias.target_name, "src.lib.api")
            self.assertEqual(alias.module_name, "src.lib.api")
            self.assertEqual(alias.import_root, "~")
            self.assertEqual(scoped_alias.category, "internal_module")
            self.assertEqual(scoped_alias.target_name, "app.view")
            self.assertEqual(scoped_alias.import_root, "@app")

    def test_exact_path_alias_import_root_uses_root_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"compilerOptions":{"paths":{"foo/bar":["src/lib"]}}}\n')
            app = _write(root / "src" / "app.ts", "import lib from 'foo/bar';\n")
            lib = _write(root / "src" / "lib.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, lib))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("foo/bar"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.lib")
            self.assertEqual(normalized.import_root, "foo")

    def test_alias_import_root_comes_from_resolving_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "tsconfig.json",
                '{"compilerOptions":{"paths":{"@scope/*":["missing/*"],"@scope/pkg/*":["src/*"]}}}\n',
            )
            app = _write(root / "src" / "app.ts", "import api from '@scope/pkg/api';\n")
            api = _write(root / "src" / "api.ts", "export default {};\n")
            repo = _repo_snapshot(root, typescript_paths=(app, api))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@scope/pkg/api"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.api")
            self.assertEqual(normalized.import_root, "@scope/pkg")

    def test_root_tsconfig_and_jsconfig_aliases_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"compilerOptions":{"paths":{"@ts/*":["ts/*"]}}}\n')
            _write(root / "jsconfig.json", '{"compilerOptions":{"paths":{"@js/*":["js/*"]}}}\n')
            app = _write(root / "src" / "app.ts", "import tsValue from '@ts/value';\nimport jsValue from '@js/value';\n")
            ts_value = _write(root / "ts" / "value.ts", "export default 1;\n")
            js_value = _write(root / "js" / "value.ts", "export default 2;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, ts_value, js_value))
            normalizer = JsImportNormalizer(repo)

            ts_import = normalizer.normalize(_js_ref("@ts/value"), "src.app", "src/app.ts")
            js_import = normalizer.normalize(_js_ref("@js/value"), "src.app", "src/app.ts")

            self.assertEqual(ts_import.category, "internal_module")
            self.assertEqual(ts_import.target_name, "ts.value")
            self.assertEqual(js_import.category, "internal_module")
            self.assertEqual(js_import.target_name, "js.value")

    def test_unresolved_alias_collision_still_uses_declared_dependency_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "package.json", '{"dependencies":{"react":"18.0.0"}}\n')
            _write(root / "tsconfig.json", '{"compilerOptions":{"paths":{"react/*":["missing/*"]}}}\n')
            app = _write(root / "src" / "app.ts", "import jsxRuntime from 'react/jsx-runtime';\n")
            repo = _repo_snapshot(root, typescript_paths=(app,))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("react/jsx-runtime"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "third_party")
            self.assertEqual(normalized.import_root, "react")
            self.assertEqual(normalized.distribution_name, "react")

    def test_unconfigured_at_slash_import_resolves_from_src(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = _write(root / "src" / "app.ts", "import api from '@/api';\n")
            api = _write(root / "src" / "api.ts", "export default {};\n")
            repo = _repo_snapshot(root, typescript_paths=(app, api))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@/api"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.api")
            self.assertEqual(normalized.import_root, "@")

    def test_configured_at_slash_alias_wins_over_src_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"compilerOptions":{"paths":{"@/*":["app/*"]}}}\n')
            app = _write(root / "src" / "app.ts", "import api from '@/api';\n")
            src_api = _write(root / "src" / "api.ts", "export default 'src';\n")
            app_api = _write(root / "app" / "api.ts", "export default 'app';\n")
            repo = _repo_snapshot(root, typescript_paths=(app, src_api, app_api))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@/api"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "app.api")
            self.assertEqual(normalized.import_root, "@")

    def test_relative_imports_resolve_directory_index_and_index_file_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = _write(root / "src" / "app.ts", "import feature from './feature';\n")
            index = _write(root / "src" / "feature" / "index.ts", "import { child } from './child';\n")
            child = _write(root / "src" / "feature" / "child.ts", "export const child = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, index, child))
            normalizer = JsImportNormalizer(repo)

            directory_import = normalizer.normalize(_js_ref("./feature"), "src.app", "src/app.ts")
            index_sibling_import = normalizer.normalize(
                _js_ref("./child"),
                "src.feature",
                "src/feature/index.ts",
            )

            self.assertEqual(directory_import.category, "relative_internal_module")
            self.assertEqual(directory_import.target_name, "src.feature")
            self.assertEqual(index_sibling_import.category, "relative_internal_module")
            self.assertEqual(index_sibling_import.target_name, "src.feature.child")

    def test_relative_imports_normalize_windows_style_importer_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = _write(root / "src" / "feature" / "app.ts", "import { child } from './child';\n")
            child = _write(root / "src" / "feature" / "child.ts", "export const child = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, child))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(
                _js_ref("./child"),
                "src.feature.app",
                "src\\feature\\app.ts",
            )

            self.assertEqual(normalized.category, "relative_internal_module")
            self.assertEqual(normalized.target_name, "src.feature.child")

            windows_import = normalizer.normalize(
                _js_ref(".\\child"),
                "src.feature.app",
                "src\\feature\\app.ts",
            )

            self.assertEqual(windows_import.category, "relative_internal_module")
            self.assertEqual(windows_import.target_name, "src.feature.child")

    def test_relative_imports_resolve_dotted_module_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            spec = _write(root / "src" / "app.component.spec.ts", "import { AppComponent } from './app.component';\n")
            component = _write(root / "src" / "app.component.ts", "export class AppComponent {}\n")
            repo = _repo_snapshot(root, typescript_paths=(spec, component))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("./app.component"), "src.app.component.spec", "src/app.component.spec.ts")

            self.assertEqual(normalized.category, "relative_internal_module")
            self.assertEqual(normalized.target_name, "src.app.component")
            self.assertEqual(normalized.module_name, "src.app.component")

    def test_nested_tsconfig_path_alias_is_scoped_to_importing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"compilerOptions":{"paths":{"~/*":["root/*"]}}}\n')
            _write(
                root / "packages" / "widget" / "tsconfig.json",
                '{"compilerOptions":{"baseUrl":".","paths":{"~/*":["./src/*"]}}}\n',
            )
            app = _write(root / "packages" / "widget" / "src" / "app.ts", "import timeout from '~/constants/apiTimeout';\n")
            config = _write(
                root / "packages" / "widget" / "src" / "constants" / "apiTimeout.ts",
                "export default 5000;\n",
            )
            root_config = _write(root / "root" / "constants" / "apiTimeout.ts", "export default 1000;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, config, root_config))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(
                _js_ref("~/constants/apiTimeout"),
                "packages.widget.src.app",
                "packages/widget/src/app.ts",
            )

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "packages.widget.src.constants.apiTimeout")

    def test_nested_tsconfig_and_jsconfig_aliases_are_merged_per_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "packages" / "widget" / "tsconfig.json",
                '{"compilerOptions":{"paths":{"@ts/*":["src/ts/*"]}}}\n',
            )
            _write(
                root / "packages" / "widget" / "jsconfig.json",
                '{"compilerOptions":{"paths":{"@js/*":["src/js/*"]}}}\n',
            )
            app = _write(
                root / "packages" / "widget" / "src" / "app.ts",
                "import tsValue from '@ts/value';\nimport jsValue from '@js/value';\n",
            )
            ts_value = _write(root / "packages" / "widget" / "src" / "ts" / "value.ts", "export default 1;\n")
            js_value = _write(root / "packages" / "widget" / "src" / "js" / "value.ts", "export default 2;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, ts_value, js_value))
            normalizer = JsImportNormalizer(repo)

            ts_import = normalizer.normalize(_js_ref("@ts/value"), "packages.widget.src.app", "packages/widget/src/app.ts")
            js_import = normalizer.normalize(_js_ref("@js/value"), "packages.widget.src.app", "packages/widget/src/app.ts")

            self.assertEqual(ts_import.category, "internal_module")
            self.assertEqual(ts_import.target_name, "packages.widget.src.ts.value")
            self.assertEqual(js_import.category, "internal_module")
            self.assertEqual(js_import.target_name, "packages.widget.src.js.value")

    def test_nested_tsconfig_takes_precedence_when_same_alias_exists_in_jsconfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "packages" / "widget" / "tsconfig.json",
                '{"compilerOptions":{"paths":{"@same/*":["src/ts/*"]}}}\n',
            )
            _write(
                root / "packages" / "widget" / "jsconfig.json",
                '{"compilerOptions":{"paths":{"@same/*":["src/js/*"]}}}\n',
            )
            app = _write(root / "packages" / "widget" / "src" / "app.ts", "import value from '@same/value';\n")
            ts_value = _write(root / "packages" / "widget" / "src" / "ts" / "value.ts", "export default 1;\n")
            js_value = _write(root / "packages" / "widget" / "src" / "js" / "value.ts", "export default 2;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, ts_value, js_value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@same/value"), "packages.widget.src.app", "packages/widget/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "packages.widget.src.ts.value")

    def test_nested_tsconfig_inherits_path_aliases_from_extended_base_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "tsconfig.base.json",
                '{"compilerOptions":{"baseUrl":".","paths":{"@acme/widgets":["libs/widgets/src/index.ts"]}}}\n',
            )
            _write(root / "apps" / "web" / "tsconfig.json", '{"extends":"../../tsconfig.base.json"}\n')
            app = _write(root / "apps" / "web" / "src" / "app.ts", "import { Widget } from '@acme/widgets';\n")
            widgets = _write(root / "libs" / "widgets" / "src" / "index.ts", "export const Widget = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, widgets))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@acme/widgets"), "apps.web.src.app", "apps/web/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "libs.widgets.src")
            self.assertEqual(normalized.import_root, "@acme/widgets")

    def test_root_tsconfig_extends_base_config_dedupes_inherited_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.base.json", '{"compilerOptions":{"baseUrl":".","paths":{"@acme/*":["libs/*"]}}}\n')
            _write(root / "tsconfig.json", '{"extends":"./tsconfig.base.json"}\n')

            aliases = load_typescript_path_aliases(root)

            self.assertEqual(aliases, (("@acme/*", ("libs/*",)),))

    def test_tsconfig_list_extends_uses_local_extended_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.base.json", '{"compilerOptions":{"baseUrl":".","paths":{"@base/*":["src/base/*"]}}}\n')
            _write(root / "packages" / "widget" / "tsconfig.json", '{"extends":["../../missing.json","../../tsconfig.base.json"]}\n')
            app = _write(root / "packages" / "widget" / "src" / "app.ts", "import value from '@base/value';\n")
            value = _write(root / "src" / "base" / "value.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@base/value"), "packages.widget.src.app", "packages/widget/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.base.value")

    def test_backslash_relative_tsconfig_extends_resolves_across_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.base.json", '{"compilerOptions":{"baseUrl":".","paths":{"@win/*":["src/win/*"]}}}\n')
            _write(
                root / "packages" / "widget" / "tsconfig.json",
                json.dumps({"extends": r"..\..\tsconfig.base.json"}) + "\n",
            )
            app = _write(root / "packages" / "widget" / "src" / "app.ts", "import value from '@win/value';\n")
            value = _write(root / "src" / "win" / "value.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@win/value"), "packages.widget.src.app", "packages/widget/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.win.value")

    def test_tsconfig_directory_extends_resolves_nested_tsconfig_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "configs" / "shared" / "tsconfig.json",
                '{"compilerOptions":{"baseUrl":"../..","paths":{"@dir/*":["src/dir/*"]}}}\n',
            )
            _write(root / "packages" / "widget" / "tsconfig.json", '{"extends":"../../configs/shared"}\n')
            app = _write(root / "packages" / "widget" / "src" / "app.ts", "import value from '@dir/value';\n")
            value = _write(root / "src" / "dir" / "value.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@dir/value"), "packages.widget.src.app", "packages/widget/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.dir.value")

    def test_absolute_tsconfig_extends_resolves_when_under_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            shared_config = _write(
                root / "configs" / "shared.json",
                '{"compilerOptions":{"baseUrl":"..","paths":{"@inside/*":["src/inside/*"]}}}\n',
            )
            _write(root / "tsconfig.json", json.dumps({"extends": shared_config.as_posix()}) + "\n")
            app = _write(root / "src" / "app.ts", "import value from '@inside/value';\n")
            value = _write(root / "src" / "inside" / "value.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@inside/value"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.inside.value")

    def test_tsconfig_extends_outside_repo_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            root = workspace / "repo"
            root.mkdir()
            outside_config = _write(
                workspace / "shared.json",
                '{"compilerOptions":{"baseUrl":".","paths":{"@outside/*":["src/outside/*"]}}}\n',
            )
            _write(root / "tsconfig.json", json.dumps({"extends": outside_config.as_posix()}) + "\n")
            app = _write(root / "src" / "app.ts", "import value from '@outside/value';\n")
            value = _write(root / "src" / "outside" / "value.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, value))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@outside/value"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "unknown")
            self.assertEqual(normalized.target_name, "@outside/value")

    def test_tsconfig_extends_path_classifier_accepts_windows_absolute_paths(self) -> None:
        self.assertTrue(_is_path_like_extends_value("C:/repo/tsconfig.base.json"))
        self.assertTrue(_is_path_like_extends_value(r"C:\repo\tsconfig.base.json"))
        self.assertFalse(_is_path_like_extends_value("@tsconfig/node18/tsconfig.json"))

    def test_tsconfig_extends_cycle_does_not_block_parent_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"extends":"./tsconfig.base.json"}\n')
            _write(
                root / "tsconfig.base.json",
                '{"extends":"./tsconfig.json","compilerOptions":{"baseUrl":".","paths":{"@cycle":["src/cycle.ts"]}}}\n',
            )
            app = _write(root / "src" / "app.ts", "import cycle from '@cycle';\n")
            cycle = _write(root / "src" / "cycle.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, cycle))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@cycle"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.cycle")

    def test_extended_base_url_applies_to_child_config_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.base.json", '{"compilerOptions":{"baseUrl":"."}}\n')
            _write(
                root / "apps" / "web" / "tsconfig.json",
                '{"extends":"../../tsconfig.base.json","compilerOptions":{"paths":{"@pkg/*":["libs/*"]}}}\n',
            )
            app = _write(root / "apps" / "web" / "src" / "app.ts", "import core from '@pkg/core';\n")
            core = _write(root / "libs" / "core.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, core))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@pkg/core"), "apps.web.src.app", "apps/web/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "libs.core")

    def test_child_base_url_override_applies_to_inherited_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.base.json", '{"compilerOptions":{"baseUrl":".","paths":{"@shared/*":["shared/*"]}}}\n')
            _write(
                root / "apps" / "web" / "tsconfig.json",
                '{"extends":"../../tsconfig.base.json","compilerOptions":{"baseUrl":"."}}\n',
            )
            app = _write(root / "apps" / "web" / "src" / "app.ts", "import util from '@shared/util';\n")
            util = _write(root / "apps" / "web" / "shared" / "util.ts", "export default 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, util))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@shared/util"), "apps.web.src.app", "apps/web/src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "apps.web.shared.util")

    def test_typescript_config_loader_fails_closed_on_decode_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tsconfig.json"
            path.write_bytes(b"\xff\xfe\x00")

            self.assertEqual(load_typescript_config_object(path), {})

    def test_local_package_imports_resolve_before_declared_dependency_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(
                root / "package.json",
                '{"dependencies":{"@acme/ui":"workspace:*"},"workspaces":["packages/*"]}\n',
            )
            _write(root / "packages" / "ui" / "package.json", '{"name":"@acme/ui","main":"src/index.ts"}\n')
            app = _write(root / "src" / "app.ts", "import Button from '@acme/ui/Button';\n")
            ui_index = _write(root / "packages" / "ui" / "src" / "index.ts", "export { Button } from './Button';\n")
            button = _write(root / "packages" / "ui" / "src" / "Button.ts", "export const Button = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, ui_index, button))
            normalizer = JsImportNormalizer(repo)

            subpath_import = normalizer.normalize(_js_ref("@acme/ui/Button"), "src.app", "src/app.ts")
            root_import = normalizer.normalize(_js_ref("@acme/ui"), "src.app", "src/app.ts")

            self.assertEqual(subpath_import.category, "internal_module")
            self.assertEqual(subpath_import.target_name, "packages.ui.src.Button")
            self.assertIsNone(subpath_import.distribution_name)
            self.assertEqual(root_import.category, "internal_module")
            self.assertEqual(root_import.target_name, "packages.ui.src")

    def test_local_package_subpath_uses_import_root_when_manifest_name_case_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "packages" / "ui" / "package.json", '{"name":"@Acme/UI"}\n')
            app = _write(root / "src" / "app.ts", "import Button from '@acme/ui/Button';\n")
            button = _write(root / "packages" / "ui" / "src" / "Button.ts", "export const Button = 1;\n")
            repo = _repo_snapshot(root, typescript_paths=(app, button))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("@acme/ui/Button"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "packages.ui.src.Button")

    def test_base_url_imports_resolve_after_declared_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "package.json", '{"dependencies":{"react":"18.0.0"}}\n')
            _write(root / "tsconfig.json", '{"compilerOptions":{"baseUrl":"src"}}\n')
            app = _write(root / "src" / "app.ts", "import config from 'shared/config';\nimport React from 'react';\n")
            config = _write(root / "src" / "shared" / "config.ts", "export default {};\n")
            react_shadow = _write(root / "src" / "react.ts", "export default {};\n")
            repo = _repo_snapshot(root, typescript_paths=(app, config, react_shadow))
            normalizer = JsImportNormalizer(repo)

            internal_import = normalizer.normalize(_js_ref("shared/config"), "src.app", "src/app.ts")
            dependency_import = normalizer.normalize(_js_ref("react"), "src.app", "src/app.ts")

            self.assertEqual(internal_import.category, "internal_module")
            self.assertEqual(internal_import.target_name, "src.shared.config")
            self.assertEqual(dependency_import.category, "third_party")
            self.assertEqual(dependency_import.distribution_name, "react")

    def test_base_url_imports_resolve_dotted_module_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "tsconfig.json", '{"compilerOptions":{"baseUrl":"."}}\n')
            app = _write(root / "src" / "app.ts", "import { UserDto } from 'src/models/user.dto';\n")
            model = _write(root / "src" / "models" / "user.dto.ts", "export interface UserDto {}\n")
            repo = _repo_snapshot(root, typescript_paths=(app, model))
            normalizer = JsImportNormalizer(repo)

            normalized = normalizer.normalize(_js_ref("src/models/user.dto"), "src.app", "src/app.ts")

            self.assertEqual(normalized.category, "internal_module")
            self.assertEqual(normalized.target_name, "src.models.user.dto")

    def test_node_builtin_modules_are_sourced_from_runtime_inventory(self) -> None:
        builtin_modules = {
            "async_hooks",
            "cluster",
            "dns",
            "fs/promises",
            "inspector",
            "module",
            "perf_hooks",
            "test",
            "tls",
            "vm",
            "worker_threads",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo_snapshot(root, typescript_paths=(root / "src" / "index.ts",))

            with patch("source.kg.languages.typescript.normalization.imports._node_builtin_modules", return_value=builtin_modules):
                normalizer = JsImportNormalizer(repo)

            for raw_import in (
                "worker_threads",
                "cluster",
                "dns",
                "fs/promises",
                "vm",
                "module",
                "tls",
                "perf_hooks",
                "inspector",
                "node:test",
                "async_hooks",
            ):
                with self.subTest(raw_import=raw_import):
                    normalized = normalizer.normalize(
                        JsImportRef(
                            raw_target=raw_import,
                            line=1,
                            imported_names=(),
                            local_names=(),
                        ),
                        current_module="src.index",
                    )

                    self.assertEqual(normalized.category, "node_builtin")
                    self.assertIsNone(normalized.distribution_name)

            promises_import = normalizer.normalize(
                JsImportRef(
                    raw_target="fs/promises",
                    line=1,
                    imported_names=(),
                    local_names=(),
                ),
                current_module="src.index",
            )
            node_prefixed_promises_import = normalizer.normalize(
                JsImportRef(
                    raw_target="node:fs/promises",
                    line=1,
                    imported_names=(),
                    local_names=(),
                ),
                current_module="src.index",
            )
            self.assertEqual(promises_import.target_name, "fs/promises")
            self.assertEqual(promises_import.import_root, "fs")
            self.assertEqual(node_prefixed_promises_import.target_name, "fs/promises")
            self.assertEqual(node_prefixed_promises_import.import_root, "fs")

    def test_node_builtin_modules_fall_back_when_node_is_unavailable(self) -> None:
        typescript_imports._node_builtin_modules.cache_clear()
        with patch(
            "source.kg.languages.typescript.normalization.imports.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            builtins = typescript_imports._node_builtin_modules()
        typescript_imports._node_builtin_modules.cache_clear()

        self.assertIn("worker_threads", builtins)
        self.assertIn("fs/promises", builtins)

    def test_node_builtin_modules_include_runtime_discovered_modules(self) -> None:
        typescript_imports._node_builtin_modules.cache_clear()
        completed = subprocess.CompletedProcess(
            args=["node"],
            returncode=0,
            stdout='["node:fictional_builtin"]',
            stderr="",
        )
        with patch("source.kg.languages.typescript.normalization.imports.subprocess.run", return_value=completed):
            builtins = typescript_imports._node_builtin_modules()
        typescript_imports._node_builtin_modules.cache_clear()

        self.assertIn("fictional_builtin", builtins)


def _repo_snapshot(
    root: Path,
    python_paths: tuple[Path, ...] = (),
    typescript_paths: tuple[Path, ...] = (),
) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        files_by_language={"python": python_paths, "typescript": typescript_paths},
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _js_ref(raw_target: str) -> JsImportRef:
    return JsImportRef(raw_target=raw_target, line=1, imported_names=(), local_names=())


if __name__ == "__main__":
    unittest.main()
