from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import textwrap
import unittest

from source.kg.core.repo_source import discover_repo
from source.kg.languages import discover_languages
from source.kg.languages.file_matchers import discover_language_file_matchers


class StubLanguageAcceptanceTest(unittest.TestCase):
    def test_stub_language_is_discovered_without_central_registry_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_root = root / "stub_languages"
            language_dir = package_root / "example_lang"
            language_dir.mkdir(parents=True)
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (language_dir / "__init__.py").write_text("", encoding="utf-8")
            (language_dir / "files.py").write_text(_files_py("example_lang"), encoding="utf-8")
            (language_dir / "language.py").write_text(
                _language_py("stub_languages.example_lang.files"),
                encoding="utf-8",
            )

            repo_root = root / "repo"
            repo_root.mkdir()
            source_file = repo_root / "main.example"
            source_file.write_text("service example\n", encoding="utf-8")

            _clear_stub_modules()
            sys.path.insert(0, str(root))
            try:
                matchers = discover_language_file_matchers(package_root, "stub_languages")
                languages = discover_languages(package_root, "stub_languages")
            finally:
                sys.path.remove(str(root))
                _clear_stub_modules()

            repo = discover_repo(repo_root, language_files=matchers)

        self.assertEqual([matcher.name for matcher in matchers], ["example_lang"])
        self.assertEqual([language.name for language in languages], ["example_lang"])
        self.assertEqual(repo.files_by_language["example_lang"], (source_file.resolve(),))

    def test_discovery_rejects_duplicate_language_file_matcher_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "stub_languages"
            _write_stub_language(package_root, "one", "duplicate")
            _write_stub_language(package_root, "two", "duplicate")
            _clear_stub_modules()
            sys.path.insert(0, str(package_root.parent))
            try:
                with self.assertRaisesRegex(ValueError, "Duplicate language file matcher name: duplicate"):
                    discover_language_file_matchers(package_root, "stub_languages")
            finally:
                sys.path.remove(str(package_root.parent))
                _clear_stub_modules()

    def test_discovery_rejects_duplicate_language_support_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "stub_languages"
            _write_stub_language(package_root, "one", "duplicate")
            _write_stub_language(package_root, "two", "duplicate")
            _clear_stub_modules()
            sys.path.insert(0, str(package_root.parent))
            try:
                with self.assertRaisesRegex(ValueError, "Duplicate language support name: duplicate"):
                    discover_languages(package_root, "stub_languages")
            finally:
                sys.path.remove(str(package_root.parent))
                _clear_stub_modules()

    def test_discovery_rejects_missing_language_plugpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_root = Path(tmpdir) / "stub_languages"
            language_dir = package_root / "example_lang"
            language_dir.mkdir(parents=True)
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (language_dir / "__init__.py").write_text("", encoding="utf-8")
            (language_dir / "files.py").write_text(_files_py("example_lang"), encoding="utf-8")
            (language_dir / "language.py").write_text(
                _language_py("stub_languages.example_lang.files").replace(
                    "    def useful_edges(self):\n        return {}\n\n",
                    "",
                ),
                encoding="utf-8",
            )

            _clear_stub_modules()
            sys.path.insert(0, str(package_root.parent))
            try:
                with self.assertRaisesRegex(ValueError, "example_lang must implement useful_edges"):
                    discover_languages(package_root, "stub_languages")
            finally:
                sys.path.remove(str(package_root.parent))
                _clear_stub_modules()


def _write_stub_language(package_root: Path, directory_name: str, language_name: str) -> None:
    language_dir = package_root / directory_name
    language_dir.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (language_dir / "__init__.py").write_text("", encoding="utf-8")
    (language_dir / "files.py").write_text(_files_py(language_name), encoding="utf-8")
    (language_dir / "language.py").write_text(
        _language_py(f"stub_languages.{directory_name}.files"),
        encoding="utf-8",
    )


def _clear_stub_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "stub_languages" or module_name.startswith("stub_languages."):
            del sys.modules[module_name]


def _files_py(language_name: str) -> str:
    return textwrap.dedent(
        f"""
        from dataclasses import dataclass
        from pathlib import Path

        @dataclass(frozen=True)
        class ExampleLanguageFiles:
            name: str = "{language_name}"
            aliases: tuple[str, ...] = ()
            file_extensions: frozenset[str] = frozenset({{".example"}})
            manifest_files: frozenset[str] = frozenset()

            def matches_file(self, path: Path) -> bool:
                return path.suffix == ".example"

        LANGUAGE_FILES = ExampleLanguageFiles()
        """
    )


def _language_py(files_module: str) -> str:
    return textwrap.dedent(
        f"""
        from dataclasses import dataclass
        from pathlib import Path

        from {files_module} import LANGUAGE_FILES, ExampleLanguageFiles

        @dataclass(frozen=True)
        class ExampleLanguageSupport:
            files: ExampleLanguageFiles = LANGUAGE_FILES

            @property
            def name(self) -> str:
                return self.files.name

            @property
            def aliases(self) -> tuple[str, ...]:
                return self.files.aliases

            @property
            def file_extensions(self) -> frozenset[str]:
                return self.files.file_extensions

            @property
            def manifest_files(self) -> frozenset[str]:
                return self.files.manifest_files

            def matches_file(self, path: Path) -> bool:
                return self.files.matches_file(path)

            def source_roots(self, repo, ctx):
                return {{}}

            def parse_repo(self, repo, ctx):
                return {{}}

            def opportunity_detectors(self):
                return ()

            def package_resolver(self):
                return None

            def dimension_rules(self):
                return {{}}

            def useful_edges(self):
                return {{}}

            def adapters(self):
                return ()

            def known_stacks(self):
                return {{}}

        LANGUAGE_SUPPORT = ExampleLanguageSupport()
        """
    )


if __name__ == "__main__":
    unittest.main()
