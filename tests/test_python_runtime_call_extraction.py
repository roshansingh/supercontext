from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import JsonlKgStore
from source.kg.languages.python.extractors.ast_extractor import KgBuild, PythonAstExtractor
from source.kg.product.mcp_tools import call_tool
from source.kg.query.snapshot import KgSnapshot


class PythonRuntimeCallExtractionTest(unittest.TestCase):
    def test_builtin_calls_emit_external_symbol_callees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session(items):\n"
                "    print('loading')\n"
                "    return len(items)\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))
            kg = _snapshot(root, build)

        result = kg.find_callees("predict_on_session", path="app/predict.py", line=1, limit=10)
        callees = {row["object"]: row for row in result["callees"]}
        builtin_entities = {
            entity.identity["name"]: entity
            for entity in build.entities
            if entity.kind == "ExternalSymbol" and entity.identity.get("module") == "builtins"
        }

        self.assertEqual(result["status"], "found")
        self.assertIn("builtins.print", callees)
        self.assertIn("builtins.len", callees)
        self.assertEqual(callees["builtins.print"]["qualifier"]["resolution_kind"], "python_builtin_call")
        self.assertEqual(
            callees["builtins.print"]["call_site"],
            {"source_line": "print('loading')", "source_excerpt": "print('loading')"},
        )
        self.assertEqual(builtin_entities["print"].identity["language"], "python")
        self.assertEqual(builtin_entities["print"].identity["symbol_kind"], "builtin")
        builtin_evidence = [
            row
            for row in build.evidence
            if row.target_type == "entity" and row.target_id == builtin_entities["print"].entity_id
        ]
        self.assertEqual(len(builtin_evidence), 1)
        self.assertEqual(builtin_evidence[0].source_system, "python_runtime")
        self.assertIsNone(builtin_evidence[0].bytes_ref)

    def test_direct_local_calls_include_call_site_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "pipeline.py"
            module.parent.mkdir()
            module.write_text(
                "def normalize(value):\n"
                "    return value\n\n"
                "def run(value):\n"
                "    return normalize(value)\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, _build(root, (module,)))

        result = call_tool(kg, "find_callees", {"symbol": "run", "path": "app/pipeline.py", "line": 4})
        callees = {row["object"]: row for row in result["callees"]}

        self.assertEqual(result["status"], "found")
        self.assertEqual(callees["app.pipeline.normalize"]["call_site"]["source_line"], "return normalize(value)")
        self.assertEqual(callees["app.pipeline.normalize"]["call_site"]["source_excerpt"], "normalize(value)")

    def test_builtin_calls_are_queryable_in_reverse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session():\n"
                "    print('loading')\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, _build(root, (module,)))

        result = kg.find_callers("builtins.print")

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.predict.predict_on_session")
        self.assertEqual(result["callers"][0]["object"], "builtins.print")

    def test_builtin_call_fails_closed_when_parameter_shadows_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session(print):\n"
                "    return print('loading')\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))

        self.assertFalse(_has_builtin_call(build, "print"))

    def test_builtin_call_fails_closed_when_function_assigns_name_anywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session(logger):\n"
                "    print('loading')\n"
                "    print = logger\n"
                "    return print\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))

        self.assertFalse(_has_builtin_call(build, "print"))

    def test_builtin_call_fails_closed_when_module_global_shadows_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "print = lambda value: value\n\n"
                "def predict_on_session():\n"
                "    return print('loading')\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))

        self.assertFalse(_has_builtin_call(build, "print"))

    def test_builtin_calls_in_nested_function_defaults_belong_to_outer_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session():\n"
                "    def inner(value=print('default')):\n"
                "        return value\n"
                "    return inner()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, _build(root, (module,)))

        result = kg.find_callees("predict_on_session", path="app/predict.py", line=1, limit=10)

        self.assertIn("builtins.print", {row["object"] for row in result["callees"]})

    def test_comprehension_target_shadows_builtin_inside_comprehension_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session(functions):\n"
                "    return [print('value') for print in functions]\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))

        self.assertFalse(_has_builtin_call(build, "print"))

    def test_match_capture_shadows_builtin_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "predict.py"
            module.parent.mkdir()
            module.write_text(
                "def predict_on_session(value):\n"
                "    match value:\n"
                "        case print:\n"
                "            return print('loading')\n",
                encoding="utf-8",
            )

            build = _build(root, (module,))

        self.assertFalse(_has_builtin_call(build, "print"))


def _build(root: Path, files: tuple[Path, ...]) -> KgBuild:
    return PythonAstExtractor(include_transport=False).extract(
        RepoSnapshot(
            root=root,
            name="app",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": files, "typescript": ()},
        )
    )


def _snapshot(root: Path, build: KgBuild) -> KgSnapshot:
    snapshot_dir = root / "snapshot"
    JsonlKgStore(snapshot_dir).write(
        entities=build.entities,
        facts=build.facts,
        evidence=build.evidence,
        coverage=build.coverage,
        manifest={"counts": {"entities": len(build.entities), "facts": len(build.facts)}},
    )
    return KgSnapshot(snapshot_dir)


def _has_builtin_call(build: KgBuild, name: str) -> bool:
    builtin_ids = {
        entity.entity_id
        for entity in build.entities
        if entity.kind == "ExternalSymbol"
        and entity.identity.get("module") == "builtins"
        and entity.identity.get("name") == name
    }
    return any(fact.predicate == "CALLS" and fact.object_id in builtin_ids for fact in build.facts)
