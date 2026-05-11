from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from source.kg.core.store import read_jsonl


def _load_builder_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "private-goldset" / "build_enriched_snapshot.py"
    spec = importlib.util.spec_from_file_location("private_goldset_build_enriched_snapshot", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrivateGoldsetEnrichedSnapshotTest(unittest.TestCase):
    def test_private_builder_adds_extension_facts_and_clears_oss_gap_coverage(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo(root / "service")
            _write_apache_vhost(repo)
            _write_zappa_settings(repo)
            out = root / "kg"

            manifest = module.build_private_goldset_kg([repo], out, tenant_id="default")

            facts = read_jsonl(out / "facts.jsonl")
            evidence = read_jsonl(out / "evidence.jsonl")
            coverage = read_jsonl(out / "coverage.jsonl")

        self.assertEqual(manifest["build_type"], "private_goldset_multi_repo")
        self.assertEqual(manifest["private_extensions"]["source_system"], "private_goldset_extensions_v0")
        self.assertEqual(manifest["private_extensions"]["extractors"], ["apache_vhost", "zappa"])
        self.assertGreaterEqual(manifest["private_extensions"]["facts"], 2)
        self.assertGreaterEqual(manifest["private_extensions"]["entities"], 2)
        self.assertGreaterEqual(manifest["private_extensions"]["evidence"], 4)
        self.assertEqual(manifest["private_extensions"]["cleared_coverage"], 2)
        self.assertIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in facts})
        self.assertIn("CONSUMES_EVENT", {fact["predicate"] for fact in facts})
        self.assertTrue([row for row in evidence if row["bytes_ref"] and row["bytes_ref"]["path"] == "site.conf"])
        self.assertTrue(
            [row for row in evidence if row["bytes_ref"] and row["bytes_ref"]["path"] == "zappa_settings.json"]
        )
        coverage_reasons = {row["scope_ref"].get("reason") for row in coverage}
        self.assertNotIn("no_oss_adapter_for_apache_vhosts", coverage_reasons)
        self.assertNotIn("no_oss_adapter_for_zappa_event_sources", coverage_reasons)

    def test_private_builder_does_not_emit_or_clear_when_private_patterns_are_absent(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = _repo(root / "service")
            (repo / "settings.json").write_text('{"debug": false}', encoding="utf-8")
            (repo / "events.json").write_text(
                '{"events": [{"function": "handlers.consume", "event_source": {"arn": "'
                'arn:aws:sqs:eu-west-1:015424956416:orders-created"}}]}',
                encoding="utf-8",
            )
            out = root / "kg"

            manifest = module.build_private_goldset_kg([repo], out, tenant_id="tenant-a")
            facts = read_jsonl(out / "facts.jsonl")

        self.assertEqual(manifest["tenant_id"], "tenant-a")
        self.assertEqual(manifest["private_extensions"]["facts"], 0)
        self.assertEqual(manifest["private_extensions"]["cleared_coverage"], 0)
        self.assertNotIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in facts})
        self.assertNotIn("CONSUMES_EVENT", {fact["predicate"] for fact in facts})

    def test_private_builder_clears_only_the_matching_asymmetric_gap(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            apache_repo = _repo(root / "apache-service")
            zappa_repo = _repo(root / "zappa-service")
            _write_apache_vhost(apache_repo)
            _write_zappa_settings(zappa_repo)

            apache_manifest = module.build_private_goldset_kg([apache_repo], root / "apache-kg", tenant_id="default")
            zappa_manifest = module.build_private_goldset_kg([zappa_repo], root / "zappa-kg", tenant_id="default")

            apache_facts = read_jsonl(root / "apache-kg" / "facts.jsonl")
            zappa_facts = read_jsonl(root / "zappa-kg" / "facts.jsonl")

        self.assertEqual(apache_manifest["private_extensions"]["cleared_coverage"], 1)
        self.assertIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in apache_facts})
        self.assertNotIn("CONSUMES_EVENT", {fact["predicate"] for fact in apache_facts})
        self.assertEqual(zappa_manifest["private_extensions"]["cleared_coverage"], 1)
        self.assertIn("CONSUMES_EVENT", {fact["predicate"] for fact in zappa_facts})
        self.assertNotIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in zappa_facts})

    def test_private_builder_enriches_multiple_repos_in_one_snapshot(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            apache_repo = _repo(root / "owner-a" / "apache-service")
            zappa_repo = _repo(root / "owner-b" / "zappa-service")
            _write_apache_vhost(apache_repo)
            _write_zappa_settings(zappa_repo)
            out = root / "kg"

            manifest = module.build_private_goldset_kg([apache_repo, zappa_repo], out, tenant_id="default")
            facts = read_jsonl(out / "facts.jsonl")

        self.assertEqual(manifest["repo_count"], 2)
        self.assertEqual(manifest["private_extensions"]["cleared_coverage"], 2)
        self.assertIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in facts})
        self.assertIn("CONSUMES_EVENT", {fact["predicate"] for fact in facts})

    def test_private_builder_uses_full_repo_identity_for_same_named_repos(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            apache_repo = _repo(root / "owner-a" / "svc", package_name="apache-service")
            zappa_repo = _repo(root / "owner-b" / "svc", package_name="zappa-service")
            _write_apache_vhost(apache_repo)
            _write_zappa_settings(zappa_repo)
            out = root / "kg"

            manifest = module.build_private_goldset_kg([apache_repo, zappa_repo], out, tenant_id="default")
            facts = read_jsonl(out / "facts.jsonl")

        self.assertEqual(manifest["repo_count"], 2)
        self.assertEqual(manifest["private_extensions"]["cleared_coverage"], 2)
        self.assertIn("ROUTES_DOMAIN_TO_DEPLOY", {fact["predicate"] for fact in facts})
        self.assertIn("CONSUMES_EVENT", {fact["predicate"] for fact in facts})


def _repo(path: Path, package_name: str = "service") -> Path:
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{package_name}"\n', encoding="utf-8")
    package_dir = path / package_name.replace("-", "_")
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    return path


def _write_apache_vhost(repo: Path) -> None:
    (repo / "site.conf").write_text(
        "<VirtualHost *:80>\n"
        "  ServerName api.example.com\n"
        "  WSGIScriptAlias / /home/ubuntu/service/service/wsgi.py\n"
        "</VirtualHost>\n",
        encoding="utf-8",
    )


def _write_zappa_settings(repo: Path) -> None:
    (repo / "zappa_settings.json").write_text(
        '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "'
        'arn:aws:sqs:eu-west-1:015424956416:orders-created"}}]}}',
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
