from __future__ import annotations

from dataclasses import dataclass, field
import tempfile
import unittest
from pathlib import Path

from source.kg.build.multi_repo import build_multi_kg
from source.kg.build.pipeline import build_kg
from source.kg.core.repo_source import discover_repo
from source.kg.core.store import read_jsonl


class UnsupportedLanguageCoverageTest(unittest.TestCase):
    def test_discover_repo_records_common_unsupported_source_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "service"
            repo.mkdir()
            (repo / "Main.java").write_text("class Main {}\n", encoding="utf-8")
            (repo / "module.py").write_text("print('ok')\n", encoding="utf-8")
            ignored = repo / "node_modules" / "legacy"
            ignored.mkdir(parents=True)
            (ignored / "Ignored.java").write_text("class Ignored {}\n", encoding="utf-8")

            snapshot = discover_repo(repo)

            self.assertEqual(len(snapshot.files_by_language["python"]), 1)
            self.assertEqual(
                [
                    path.relative_to(snapshot.root).as_posix()
                    for path in snapshot.unsupported_files_by_language["java"]
                ],
                ["Main.java"],
            )

    def test_build_kg_emits_unsupported_language_coverage_and_manifest_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "service"
            repo.mkdir()
            (repo / "Main.java").write_text("class Main {}\n", encoding="utf-8")
            out = root / "kg"

            manifest = build_kg(repo, out)

            self.assertEqual(manifest["counts"]["unsupported_files_by_language"], {"java": 1})
            coverage = read_jsonl(out / "coverage.jsonl")
            language_rows = [
                row
                for row in coverage
                if row["predicate"] == "LANGUAGE_SUPPORT"
                and row["scope_ref"].get("reason") == "unsupported_language"
            ]
            self.assertEqual(len(language_rows), 1)
            self.assertEqual(language_rows[0]["state"], "uninstrumented")
            self.assertEqual(language_rows[0]["scope_ref"]["language"], "java")
            self.assertEqual(language_rows[0]["scope_ref"]["repo_owner"], root.name)
            self.assertEqual(language_rows[0]["scope_ref"]["path_prefix"], ".")
            self.assertEqual(language_rows[0]["scope_ref"]["file_count"], 1)
            self.assertEqual(language_rows[0]["scope_ref"]["sample_paths"], ["Main.java"])

    def test_multi_repo_manifest_aggregates_unsupported_language_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "Main.java").write_text("class Main {}\n", encoding="utf-8")
            (second / "worker.go").write_text("package main\n", encoding="utf-8")

            manifest = build_multi_kg([first, second], root / "kg")

            self.assertEqual(manifest["counts"]["unsupported_files_by_language"], {"go": 1, "java": 1})

    def test_multi_repo_same_name_unsupported_language_rows_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "owner-a" / "svc"
            second = root / "owner-b" / "svc"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "Main.java").write_text("class Main {}\n", encoding="utf-8")
            (second / "Main.java").write_text("class Main {}\n", encoding="utf-8")

            build_multi_kg([first, second], root / "kg")

            coverage = [
                row
                for row in read_jsonl(root / "kg" / "coverage.jsonl")
                if row["predicate"] == "LANGUAGE_SUPPORT"
                and row["scope_ref"].get("reason") == "unsupported_language"
            ]
            self.assertEqual(len(coverage), 2)
            self.assertEqual({row["scope_ref"]["repo"] for row in coverage}, {"svc"})
            self.assertEqual({row["scope_ref"]["repo_owner"] for row in coverage}, {"owner-a", "owner-b"})

    def test_unsupported_detection_does_not_call_unrelated_language_matchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Main.java").write_text("class Main {}\n", encoding="utf-8")
            matcher = _CountingMatcher()

            repo = discover_repo(root, language_files=(matcher,))

            self.assertEqual(repo.unsupported_files_by_language["java"], ((root / "Main.java").resolve(),))
            self.assertEqual(matcher.calls, [])

    def test_supported_matcher_extensions_do_not_become_unsupported_when_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = root / "obj" / "Debug" / "Generated.cs"
            generated.parent.mkdir(parents=True)
            generated.write_text("class Generated {}\n", encoding="utf-8")

            repo = discover_repo(root)

            self.assertEqual(repo.files_by_language["dotnet"], ())
            self.assertNotIn("dotnet", repo.unsupported_files_by_language)

    def test_unsupported_detection_normalizes_uppercase_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Main.JAVA").write_text("class Main {}\n", encoding="utf-8")

            repo = discover_repo(root)

            self.assertEqual(repo.unsupported_files_by_language["java"], ((root / "Main.JAVA").resolve(),))

    def test_uppercase_supported_extension_is_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "Program.CS").write_text("class Program {}\n", encoding="utf-8")

            repo = discover_repo(root)

            self.assertEqual(repo.files_by_language["dotnet"], ())
            self.assertEqual(repo.unsupported_files_by_language["dotnet"], ((root / "Program.CS").resolve(),))

    def test_unsupported_detection_skips_common_build_output_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = root / "target" / "generated-sources" / "Main.java"
            generated.parent.mkdir(parents=True)
            generated.write_text("class Main {}\n", encoding="utf-8")

            repo = discover_repo(root)

            self.assertNotIn("java", repo.unsupported_files_by_language)


@dataclass(frozen=True)
class _CountingMatcher:
    name: str = "example"
    aliases: tuple[str, ...] = ()
    file_extensions: frozenset[str] = frozenset({".example"})
    manifest_files: frozenset[str] = frozenset()
    calls: list[Path] = field(default_factory=list, compare=False)

    def matches_file(self, path: Path) -> bool:
        self.calls.append(path)
        return path.suffix == ".example"


if __name__ == "__main__":
    unittest.main()
