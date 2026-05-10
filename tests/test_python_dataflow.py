from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.python.dataflow import (
    ResolvedValue,
    UnresolvedValue,
    ValueResolver,
    ValueScope,
    _unique_values,
    build_repo_literal_index,
    config_object_value_assignments,
    import_bindings,
    local_literal_assignments,
    resolved_to_json,
    unresolved_coverage,
)
from source.kg.normalization.python.imports import PythonImportNormalizer


class PythonDataflowTest(unittest.TestCase):
    def test_resolves_same_repo_imported_constant_through_local_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = root / "app" / "settings.py"
            producer = root / "app" / "producer.py"
            settings.parent.mkdir()
            settings.write_text('QUEUE_URL = "https://example.test/queue"\n', encoding="utf-8")
            producer.write_text(
                "from app.settings import QUEUE_URL\n\n"
                "def send():\n"
                "    target = QUEUE_URL\n"
                "    return target\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (settings, producer))
            literal_index = build_repo_literal_index(repo)
            tree = ast.parse(producer.read_text(encoding="utf-8"))
            imports = PythonImportNormalizer(repo).collect(tree, "app.producer")
            imported_modules, imported_values = import_bindings(imports)
            function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
            resolver = ValueResolver(
                ValueScope(
                    local_values=local_literal_assignments(function),
                    imported_modules=imported_modules,
                    imported_values=imported_values,
                ),
                literal_index,
            )

            resolved = resolver.resolve_value(ast.Name(id="target", ctx=ast.Load()))

            self.assertIsInstance(resolved, ResolvedValue)
            assert isinstance(resolved, ResolvedValue)
            self.assertEqual(resolved.value, "https://example.test/queue")

    def test_resolves_imported_module_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = root / "app" / "settings.py"
            producer = root / "app" / "producer.py"
            settings.parent.mkdir()
            settings.write_text('CHANNEL_NAME = "orders-created"\n', encoding="utf-8")
            producer.write_text(
                "import app.settings as settings\n\n"
                "def send():\n"
                "    return settings.CHANNEL_NAME\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (settings, producer))
            tree = ast.parse(producer.read_text(encoding="utf-8"))
            imports = PythonImportNormalizer(repo).collect(tree, "app.producer")
            imported_modules, imported_values = import_bindings(imports)
            return_node = next(node for node in ast.walk(tree) if isinstance(node, ast.Return))
            resolver = ValueResolver(ValueScope(imported_modules=imported_modules, imported_values=imported_values), build_repo_literal_index(repo))

            resolved = resolver.resolve_value(return_node.value or ast.Constant(None))

            self.assertIsInstance(resolved, ResolvedValue)
            assert isinstance(resolved, ResolvedValue)
            self.assertEqual(resolved.value, "orders-created")

    def test_resolves_dotted_import_without_alias_from_root_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = root / "app" / "settings.py"
            producer = root / "app" / "producer.py"
            settings.parent.mkdir()
            settings.write_text('CHANNEL_NAME = "orders-created"\n', encoding="utf-8")
            producer.write_text(
                "import app.settings\n\n"
                "def send():\n"
                "    return app.settings.CHANNEL_NAME\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (settings, producer))
            tree = ast.parse(producer.read_text(encoding="utf-8"))
            imports = PythonImportNormalizer(repo).collect(tree, "app.producer")
            imported_modules, imported_values = import_bindings(imports)
            return_node = next(node for node in ast.walk(tree) if isinstance(node, ast.Return))
            resolver = ValueResolver(ValueScope(imported_modules=imported_modules, imported_values=imported_values), build_repo_literal_index(repo))

            resolved = resolver.resolve_value(return_node.value or ast.Constant(None))

            self.assertIsInstance(resolved, ResolvedValue)
            assert isinstance(resolved, ResolvedValue)
            self.assertEqual(resolved.value, "orders-created")

    def test_resolves_env_lookup_when_env_value_is_supplied(self) -> None:
        node = ast.parse('value = os.getenv("CHANNEL_URL")').body[0]
        assert isinstance(node, ast.Assign)
        resolver = ValueResolver(ValueScope(env_values={"CHANNEL_URL": "resolved-value"}))

        resolved = resolver.resolve_value(node.value)

        self.assertIsInstance(resolved, ResolvedValue)
        assert isinstance(resolved, ResolvedValue)
        self.assertEqual(resolved.value, "resolved-value")
        self.assertEqual(resolved.source, "env:CHANNEL_URL")

    def test_bare_getenv_is_not_treated_as_env_lookup(self) -> None:
        node = ast.parse('value = getenv("CHANNEL_URL")').body[0]
        assert isinstance(node, ast.Assign)
        resolver = ValueResolver(ValueScope(env_values={"CHANNEL_URL": "resolved-value"}))

        resolved = resolver.resolve_value(node.value)

        self.assertIsInstance(resolved, UnresolvedValue)
        assert isinstance(resolved, UnresolvedValue)
        self.assertEqual(resolved.reason, "unsupported_call")

    def test_unresolved_value_can_be_converted_to_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "module.py"
            source.write_text("value = make_value()\n", encoding="utf-8")
            repo = _repo_snapshot(root, (source,))
            assign = ast.parse(source.read_text(encoding="utf-8")).body[0]
            assert isinstance(assign, ast.Assign)
            resolver = ValueResolver()

            unresolved = resolver.resolve_value(assign.value)

            self.assertIsInstance(unresolved, UnresolvedValue)
            assert isinstance(unresolved, UnresolvedValue)
            coverage = unresolved_coverage(repo, source, unresolved, "python_ast_v0", predicate="VALUE_RESOLUTION", line=1)
            self.assertEqual(coverage.state, "uninstrumented")
            self.assertEqual(coverage.scope_ref["reason"], "unsupported_call")
            self.assertEqual(coverage.scope_ref["expression"], "make_value()")

    def test_resolves_simple_dict_subscript(self) -> None:
        tree = ast.parse('value = {"primary": "orders-created"}["primary"]')
        assign = tree.body[0]
        assert isinstance(assign, ast.Assign)

        resolved = ValueResolver().resolve_value(assign.value)

        self.assertIsInstance(resolved, ResolvedValue)
        assert isinstance(resolved, ResolvedValue)
        self.assertEqual(resolved.value, "orders-created")

    def test_resolved_to_json_normalizes_non_json_values(self) -> None:
        resolved = ResolvedValue({"tuple": ("a", "b"), "set": {"b", "a"}, 1: "numeric-key"}, "literal", "value")

        payload = resolved_to_json(resolved)

        json.dumps(payload)
        self.assertEqual(payload["value"]["tuple"], ["a", "b"])
        self.assertEqual(payload["value"]["set"], ["a", "b"])
        self.assertEqual(payload["value"]["1"], "numeric-key")

    def test_unique_values_deduplicates_unordered_sets_deterministically(self) -> None:
        values = [{"b", "a"}, {"a", "b"}, {"c"}]

        unique = _unique_values(values)

        self.assertEqual(unique, [{"b", "a"}, {"c"}])

    def test_config_object_value_assignments_reuses_preparsed_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            config_module = config_dir / "__init__.py"
            (config_dir / "prod.ini").write_text("[queue]\nemail_queue = prod-email\n", encoding="utf-8")
            config_module.write_text(
                "import configparser\n\n"
                "class QueueConfig:\n"
                "    def __init__(self):\n"
                "        parser = configparser.ConfigParser()\n"
                "        parser.read('prod.ini')\n"
                "        self.EMAIL_QUEUE = parser['queue']['email_queue']\n"
                "\n"
                "settings = QueueConfig()\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_module,))
            parsed_tree = ast.parse(config_module.read_text(encoding="utf-8"))

            with patch(
                "source.kg.extraction.python.dataflow.ast.parse",
                side_effect=AssertionError("unexpected parse"),
            ):
                assignments, source_assignments = config_object_value_assignments(repo, {config_module: parsed_tree})

        resolved_values = [node.value for values in assignments.values() for node in values]
        self.assertEqual(resolved_values, ["prod-email"])
        source_refs = [source for sources in source_assignments.values() for source in sources]
        self.assertEqual(
            [(source.path, source.line, source.section, source.option) for source in source_refs],
            [("app/configmanager/prod.ini", 2, "queue", "email_queue")],
        )

    def test_config_object_value_assignments_preserves_percent_literals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "app" / "configmanager"
            config_dir.mkdir(parents=True)
            config_module = config_dir / "__init__.py"
            (config_dir / "prod.ini").write_text("[format]\ntime_format = %H:%M:%S\n", encoding="utf-8")
            config_module.write_text(
                "import configparser\n\n"
                "class FormatConfig:\n"
                "    def __init__(self):\n"
                "        parser = configparser.ConfigParser()\n"
                "        parser.read('prod.ini')\n"
                "        self.TIME_FORMAT = parser['format']['time_format']\n"
                "\n"
                "settings = FormatConfig()\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(root, (config_module,))

            assignments, _ = config_object_value_assignments(repo)

        resolved_values = [node.value for values in assignments.values() for node in values]
        self.assertEqual(resolved_values, ["%H:%M:%S"])


def _repo_snapshot(root: Path, python_files: tuple[Path, ...]) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        python_files=python_files,
        typescript_files=(),
    )


if __name__ == "__main__":
    unittest.main()
