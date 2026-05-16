from __future__ import annotations

from pathlib import Path
import unittest

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.languages import REGISTERED_LANGUAGES
from source.kg.languages._template.files import LANGUAGE_FILES
from source.kg.languages._template.language import LANGUAGE_SUPPORT


class LanguageTemplateTest(unittest.TestCase):
    def test_registered_languages_include_python_and_typescript(self) -> None:
        self.assertGreaterEqual({language.name for language in REGISTERED_LANGUAGES}, {"python", "typescript"})

    def test_template_is_noop_and_not_registered(self) -> None:
        root = Path("/tmp/bettercontext-template-language")
        repo = RepoSnapshot(root=root, name="template", owner="test", commit_sha="sha")
        ctx = ExtractionContext()

        self.assertFalse(LANGUAGE_FILES.matches_file(root / "example.template"))
        self.assertEqual(LANGUAGE_SUPPORT.source_roots(repo, ctx), {})
        self.assertEqual(LANGUAGE_SUPPORT.adapters(), ())
        self.assertEqual(LANGUAGE_SUPPORT.known_stacks(), {})


if __name__ == "__main__":
    unittest.main()
