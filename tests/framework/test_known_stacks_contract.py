from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.kg.build.pipeline import extract_repo
from source.kg.core.repo_source import discover_repo
from source.kg.extraction.adapters import REGISTERED_ADAPTERS
from source.kg.extraction.framework.known_stacks import KNOWN_STACK_IMPORTS


FIXTURE_ROOT = Path(__file__).resolve().parent / "known_stacks"


class KnownStacksContractTest(unittest.TestCase):
    def test_known_stack_entries_have_adapter_tag_or_fixture(self) -> None:
        supported_tags = {tag for adapter in REGISTERED_ADAPTERS for tag in adapter.capability.framework_tags}

        missing = []
        for language, imports in KNOWN_STACK_IMPORTS.items():
            for import_root in imports:
                fixture_dir = FIXTURE_ROOT / language / import_root
                if import_root not in supported_tags and not fixture_dir.is_dir():
                    missing.append(f"{language}/{import_root}")

        self.assertEqual(missing, [])

    def test_unsupported_known_stack_fixtures_emit_expected_coverage(self) -> None:
        for fixture_dir in sorted(FIXTURE_ROOT.glob("*/*")):
            if not fixture_dir.is_dir():
                continue
            with self.subTest(fixture=str(fixture_dir.relative_to(FIXTURE_ROOT))):
                result = _run_fixture(fixture_dir)
                actual_rows = [
                    {
                        "predicate": row.predicate,
                        "state": row.state,
                        "source_system": row.source_system,
                        "scope_ref": row.scope_ref,
                    }
                    for row in result.coverage
                ]
                for expected in _load_expected_rows(fixture_dir / "expected_coverage.json"):
                    self.assertTrue(
                        any(_coverage_matches(actual, expected) for actual in actual_rows),
                        f"missing expected coverage row: {expected}",
                    )


def _run_fixture(fixture_dir: Path):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for source in fixture_dir.rglob("*"):
            if not source.is_file() or source.name == "expected_coverage.json":
                continue
            target = root / source.relative_to(fixture_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        repo = discover_repo(root)
        return extract_repo(repo)


def _load_expected_rows(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise AssertionError(f"{path} must contain a JSON array")
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise AssertionError(f"{path}[{index}] must be a JSON object")
        for field in ("predicate", "state", "source_system"):
            if not isinstance(row.get(field), str):
                raise AssertionError(f"{path}[{index}].{field} must be a string")
        scope_ref = row.get("scope_ref")
        if not isinstance(scope_ref, dict):
            raise AssertionError(f"{path}[{index}].scope_ref must be a JSON object")
    return data


def _coverage_matches(actual: dict[str, object], expected: dict[str, object]) -> bool:
    expected_scope = expected.get("scope_ref", {})
    actual_scope = actual.get("scope_ref", {})
    if not isinstance(expected_scope, dict) or not isinstance(actual_scope, dict):
        return False
    for key in ("predicate", "state", "source_system"):
        if expected.get(key) != actual.get(key):
            return False
    return all(actual_scope.get(key) == value for key, value in expected_scope.items())


if __name__ == "__main__":
    unittest.main()
