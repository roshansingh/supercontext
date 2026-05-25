from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.repo_source import RepoSnapshot
from source.kg.core.store import JsonlKgStore
from source.kg.languages.python.extractors.ast_extractor import PythonAstExtractor
from source.kg.query.snapshot import KgSnapshot


class PythonReceiverCallResolutionTest(unittest.TestCase):
    def test_imported_class_instance_method_emits_cross_file_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "model.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            runner.write_text(
                "from app.model import Predictor\n\n"
                "def run():\n"
                "    predictor = Predictor()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, runner))

        result = kg.find_callers("predict_on_session", path="app/model.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.runner.run")
        self.assertEqual(result["callers"][0]["qualifier"]["receiver_class"], "app.model.Predictor")
        self.assertEqual(result["callers"][0]["qualifier"]["resolution_kind"], "python_local_instance_receiver")
        self.assertEqual(result["callers"][0]["call_site"]["source_line"], "return predictor.predict_on_session()")
        self.assertEqual(result["callers"][0]["call_site"]["source_excerpt"], "predictor.predict_on_session()")

    def test_dotted_module_import_constructor_resolves_by_full_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "model.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            runner.write_text(
                "import app.model\n\n"
                "def run():\n"
                "    predictor = app.model.Predictor()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, runner))

        result = kg.find_callers("predict_on_session", path="app/model.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.runner.run")

    def test_dotted_module_alias_constructor_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "model.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            runner.write_text(
                "import app.model as model\n\n"
                "def run():\n"
                "    predictor = model.Predictor()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, runner))

        result = kg.find_callers("predict_on_session", path="app/model.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.runner.run")

    def test_self_and_cls_attribute_calls_still_bind_by_short_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "local.py"
            module.parent.mkdir()
            module.write_text(
                "class Worker:\n"
                "    def helper(self):\n"
                "        return 1\n\n"
                "    def run(self):\n"
                "        return self.helper()\n\n"
                "    @classmethod\n"
                "    def cls_helper(cls):\n"
                "        return 2\n\n"
                "    @classmethod\n"
                "    def cls_run(cls):\n"
                "        return cls.cls_helper()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        self_result = kg.find_callers("helper", path="app/local.py", line=2)
        cls_result = kg.find_callers("cls_helper", path="app/local.py", line=9)

        self.assertEqual(self_result["status"], "found")
        self.assertEqual(self_result["caller_count"], 1)
        self.assertEqual(self_result["callers"][0]["subject"], "app.local.Worker.run")
        self.assertEqual(cls_result["status"], "found")
        self.assertEqual(cls_result["caller_count"], 1)
        self.assertEqual(cls_result["callers"][0]["subject"], "app.local.Worker.cls_run")

    def test_module_level_instance_method_call_uses_module_as_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "model.py"
            script = root / "app" / "script.py"
            model.parent.mkdir()
            model.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            script.write_text(
                "from app.model import Predictor\n\n"
                "predictor = Predictor()\n"
                "score = predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, script))

        result = kg.find_callers("predict_on_session", path="app/model.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.script")
        self.assertEqual(result["callers"][0]["qualifier"]["call"], "predictor.predict_on_session")

    def test_instance_method_resolution_fails_closed_after_unknown_reassignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "model.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n",
                encoding="utf-8",
            )
            runner.write_text(
                "from app.model import Predictor\n\n"
                "def run(factory):\n"
                "    predictor = Predictor()\n"
                "    predictor = factory()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, runner))

        result = kg.find_callers("predict_on_session", path="app/model.py", line=2)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)

    def test_non_self_attribute_call_does_not_match_by_method_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "local.py"
            module.parent.mkdir()
            module.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n\n"
                "def run(other):\n"
                "    return other.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("predict_on_session", path="app/local.py", line=2)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)

    def test_same_file_instance_method_call_uses_receiver_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "local.py"
            module.parent.mkdir()
            module.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n\n"
                "def run():\n"
                "    predictor = Predictor()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("predict_on_session", path="app/local.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["qualifier"]["receiver_class"], "app.local.Predictor")
        self.assertEqual(result["callers"][0]["qualifier"]["resolution_kind"], "python_local_instance_receiver")

    def test_class_reference_alias_resolves_constructor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "local.py"
            module.parent.mkdir()
            module.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n\n"
                "def run():\n"
                "    Alias = Predictor\n"
                "    predictor = Alias()\n"
                "    return predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("predict_on_session", path="app/local.py", line=2)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.local.run")

    def test_same_line_duplicate_calls_are_not_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "local.py"
            module.parent.mkdir()
            module.write_text(
                "class Predictor:\n"
                "    def predict_on_session(self):\n"
                "        return 1\n\n"
                "def run():\n"
                "    predictor = Predictor()\n"
                "    return predictor.predict_on_session() + predictor.predict_on_session()\n",
                encoding="utf-8",
            )

            build = PythonAstExtractor(include_transport=False).extract(
                RepoSnapshot(
                    root=root,
                    name="app",
                    owner="test",
                    commit_sha="sha",
                    files_by_language={"python": (module,), "typescript": ()},
                )
            )

        method_id = next(
            entity.entity_id
            for entity in build.entities
            if entity.kind == "CodeSymbol" and entity.identity.get("qualname") == "Predictor.predict_on_session"
        )
        run_id = next(
            entity.entity_id
            for entity in build.entities
            if entity.kind == "CodeSymbol" and entity.identity.get("qualname") == "run"
        )
        call_facts = [
            fact
            for fact in build.facts
            if fact.predicate == "CALLS" and fact.subject_id == run_id and fact.object_id == method_id
        ]

        self.assertEqual(len(call_facts), 2)

    def test_same_file_constructor_call_emits_class_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "features.py"
            module.parent.mkdir()
            module.write_text(
                "class build_features:\n"
                "    pass\n\n"
                "def run():\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.features.run")
        self.assertEqual(result["callers"][0]["qualifier"]["constructor_class"], "app.features.build_features")
        self.assertEqual(result["callers"][0]["qualifier"]["resolution_kind"], "python_constructor_call")
        self.assertEqual(result["callers"][0]["call_site"]["source_line"], "return build_features()")
        self.assertEqual(result["callers"][0]["call_site"]["source_excerpt"], "build_features()")

    def test_imported_constructor_call_emits_cross_file_class_caller(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "features.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class build_features:\n"
                "    pass\n",
                encoding="utf-8",
            )
            runner.write_text(
                "from app.features import build_features\n\n"
                "def run():\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (model, runner))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["caller_count"], 1)
        self.assertEqual(result["callers"][0]["subject"], "app.runner.run")

    def test_dotted_module_constructor_call_emits_class_caller_without_package_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "app" / "features.py"
            runner = root / "app" / "runner.py"
            model.parent.mkdir()
            model.write_text(
                "class build_features:\n"
                "    pass\n",
                encoding="utf-8",
            )
            runner.write_text(
                "import app.features\n\n"
                "def run():\n"
                "    return app.features.build_features()\n",
                encoding="utf-8",
            )

            build = PythonAstExtractor(include_transport=False).extract(
                RepoSnapshot(
                    root=root,
                    name="app",
                    owner="test",
                    commit_sha="sha",
                    files_by_language={"python": (model, runner), "typescript": ()},
                )
            )

        class_id = next(
            entity.entity_id
            for entity in build.entities
            if entity.kind == "CodeSymbol" and entity.identity.get("qualname") == "build_features"
        )
        run_id = next(
            entity.entity_id
            for entity in build.entities
            if entity.kind == "CodeSymbol" and entity.identity.get("qualname") == "run"
        )
        constructor_facts = [
            fact
            for fact in build.facts
            if fact.predicate == "CALLS" and fact.subject_id == run_id and fact.object_id == class_id
        ]
        package_facts = [
            fact
            for fact in build.facts
            if fact.predicate == "CALLS"
            and fact.subject_id == run_id
            and fact.qualifier.get("call") == "app.features.build_features"
            and fact.object_id != class_id
        ]

        self.assertEqual(len(constructor_facts), 1)
        self.assertEqual(constructor_facts[0].qualifier["call"], "app.features.build_features")
        self.assertEqual(package_facts, [])

    def test_constructor_call_fails_closed_when_parameter_shadows_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "features.py"
            module.parent.mkdir()
            module.write_text(
                "class build_features:\n"
                "    pass\n\n"
                "def run(build_features):\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)

    def test_constructor_call_fails_closed_after_unknown_reassignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "features.py"
            module.parent.mkdir()
            module.write_text(
                "class build_features:\n"
                "    pass\n\n"
                "def run(factory):\n"
                "    build_features = factory()\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)

    def test_constructor_call_fails_closed_when_local_import_shadows_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "features.py"
            module.parent.mkdir()
            module.write_text(
                "class build_features:\n"
                "    pass\n\n"
                "def run():\n"
                "    import external.factory as build_features\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)

    def test_constructor_call_fails_closed_when_nested_class_shadows_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            module = root / "app" / "features.py"
            module.parent.mkdir()
            module.write_text(
                "class build_features:\n"
                "    pass\n\n"
                "def run():\n"
                "    class build_features:\n"
                "        pass\n"
                "    return build_features()\n",
                encoding="utf-8",
            )

            kg = _snapshot(root, (module,))

        result = kg.find_callers("build_features", path="app/features.py", line=1)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["caller_count"], 0)


def _snapshot(root: Path, files: tuple[Path, ...]) -> KgSnapshot:
    repo = RepoSnapshot(
        root=root,
        name="app",
        owner="test",
        commit_sha="sha",
        files_by_language={"python": files, "typescript": ()},
    )
    build = PythonAstExtractor(include_transport=False).extract(repo)
    snapshot_dir = root / "snapshot"
    JsonlKgStore(snapshot_dir).write(
        entities=build.entities,
        facts=build.facts,
        evidence=build.evidence,
        coverage=build.coverage,
        manifest={"counts": {"entities": len(build.entities), "facts": len(build.facts)}},
    )
    return KgSnapshot(snapshot_dir)
