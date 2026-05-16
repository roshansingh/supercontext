from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.languages.known_stacks import load_known_stacks
from source.kg.languages.python.language import LANGUAGE_SUPPORT as PYTHON_SUPPORT
from source.kg.languages.typescript.language import LANGUAGE_SUPPORT as TYPESCRIPT_SUPPORT


class KnownStacksLoaderTest(unittest.TestCase):
    def test_language_known_stacks_load_from_owned_yaml(self) -> None:
        self.assertEqual(
            PYTHON_SUPPORT.known_stacks()["python"],
            {
                "boto3": "transport",
                "django": "web_framework",
                "fastapi": "web_framework",
                "flask": "web_framework",
            },
        )
        self.assertEqual(
            TYPESCRIPT_SUPPORT.known_stacks()["javascript"],
            {
                "@koa/router": "web_framework",
                "express": "web_framework",
                "fastify": "web_framework",
                "koa-router": "web_framework",
            },
        )

    def test_loader_rejects_non_object_root(self) -> None:
        path = self._yaml("[not, an, object]\n")

        with self.assertRaisesRegex(ValueError, "must contain a YAML object"):
            load_known_stacks(path)

    def test_loader_rejects_empty_yaml(self) -> None:
        path = self._yaml("# intentionally empty\n")

        with self.assertRaisesRegex(ValueError, "is empty; expected a YAML object"):
            load_known_stacks(path)

    def test_loader_wraps_yaml_parse_errors_with_path_context(self) -> None:
        path = self._yaml("web_framework: [not valid yaml\n")

        with self.assertRaisesRegex(ValueError, "known_stacks.yaml could not be parsed as YAML"):
            load_known_stacks(path)

    def test_loader_rejects_non_list_category_value(self) -> None:
        path = self._yaml("web_framework: flask\n")

        with self.assertRaisesRegex(ValueError, "web_framework must be a list"):
            load_known_stacks(path)

    def test_loader_rejects_unknown_category(self) -> None:
        path = self._yaml("web_framewrok:\n  - flask\n")

        with self.assertRaisesRegex(ValueError, "category 'web_framewrok' is not supported"):
            load_known_stacks(path)

    def test_loader_rejects_non_string_import_root(self) -> None:
        path = self._yaml("web_framework:\n  - flask\n  - 123\n")

        with self.assertRaisesRegex(ValueError, r"web_framework\[1\] must be a non-empty string"):
            load_known_stacks(path)

    def test_loader_rejects_duplicate_import_root_in_category(self) -> None:
        path = self._yaml("web_framework:\n  - flask\n  - flask\n")

        with self.assertRaisesRegex(ValueError, "contains duplicate import root 'flask'"):
            load_known_stacks(path)

    def test_loader_rejects_duplicate_import_root_across_categories(self) -> None:
        path = self._yaml("web_framework:\n  - flask\ntransport:\n  - flask\n")

        with self.assertRaisesRegex(ValueError, "appears in multiple categories"):
            load_known_stacks(path)

    def _yaml(self, text: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "known_stacks.yaml"
        path.write_text(text, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
