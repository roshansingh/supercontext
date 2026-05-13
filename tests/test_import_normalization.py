from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.repo_source import RepoSnapshot
from source.kg.normalization.python import imports as python_imports
from source.kg.normalization.python.imports import ImportRef, PythonImportNormalizer
from source.kg.normalization.typescript import imports as typescript_imports
from source.kg.normalization.typescript.imports import JsImportNormalizer, JsImportRef


class PythonImportNormalizationTest(unittest.TestCase):
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
                return_value={},
            ), patch("source.kg.normalization.python.imports.util.find_spec", return_value=object()):
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
                return_value={},
            ), patch("source.kg.normalization.python.imports.util.find_spec", return_value=object()):
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
            repo = _repo_snapshot(root, python_files=(root / "app.py",))

            with patch(
                "source.kg.normalization.python.imports.metadata.packages_distributions",
                return_value={"google": ["google-api-core", "protobuf"]},
            ), patch("source.kg.normalization.python.imports.util.find_spec", return_value=object()):
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
            repo = _repo_snapshot(root, typescript_files=(root / "src" / "index.ts",))

            with patch("source.kg.normalization.typescript.imports._node_builtin_modules", return_value=builtin_modules):
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
            "source.kg.normalization.typescript.imports.subprocess.run",
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
        with patch("source.kg.normalization.typescript.imports.subprocess.run", return_value=completed):
            builtins = typescript_imports._node_builtin_modules()
        typescript_imports._node_builtin_modules.cache_clear()

        self.assertIn("fictional_builtin", builtins)


def _repo_snapshot(
    root: Path,
    python_files: tuple[Path, ...] = (),
    typescript_files: tuple[Path, ...] = (),
) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        python_files=python_files,
        typescript_files=typescript_files,
    )


if __name__ == "__main__":
    unittest.main()
