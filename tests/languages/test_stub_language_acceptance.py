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
            (language_dir / "files.py").write_text(_files_py(), encoding="utf-8")
            (language_dir / "language.py").write_text(_language_py(), encoding="utf-8")

            repo_root = root / "repo"
            repo_root.mkdir()
            source_file = repo_root / "main.example"
            source_file.write_text("service example\n", encoding="utf-8")

            sys.path.insert(0, str(root))
            try:
                matchers = discover_language_file_matchers(package_root, "stub_languages")
                languages = discover_languages(package_root, "stub_languages")
            finally:
                sys.path.remove(str(root))

            repo = discover_repo(repo_root, language_files=matchers)

        self.assertEqual([matcher.name for matcher in matchers], ["example_lang"])
        self.assertEqual([language.name for language in languages], ["example_lang"])
        self.assertEqual(repo.files_by_language["example_lang"], (source_file.resolve(),))


def _files_py() -> str:
    return textwrap.dedent(
        """
        from dataclasses import dataclass
        from pathlib import Path

        @dataclass(frozen=True)
        class ExampleLanguageFiles:
            name: str = "example_lang"
            aliases: tuple[str, ...] = ()
            file_extensions: frozenset[str] = frozenset({".example"})
            manifest_files: frozenset[str] = frozenset()

            def matches_file(self, path: Path) -> bool:
                return path.suffix == ".example"

        LANGUAGE_FILES = ExampleLanguageFiles()
        """
    )


def _language_py() -> str:
    return textwrap.dedent(
        """
        from dataclasses import dataclass
        from pathlib import Path
        from typing import Any

        from stub_languages.example_lang.files import LANGUAGE_FILES, ExampleLanguageFiles

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
                return {}

            def adapters(self):
                return ()

            def known_stacks(self):
                return {}

        LANGUAGE_SUPPORT = ExampleLanguageSupport()
        """
    )


if __name__ == "__main__":
    unittest.main()
