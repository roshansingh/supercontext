from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile


def _load_zappa_module():
    module_path = Path(__file__).resolve().parents[1] / "examples" / "private-goldset" / "extractors" / "zappa.py"
    spec = importlib.util.spec_from_file_location("private_goldset_zappa", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateGoldsetZappaTest(unittest.TestCase):
    def test_private_zappa_extension_emits_authoritative_sqs_consumer(self) -> None:
        module = _load_zappa_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zappa_path = root / "zappa_settings.json"
            arn = "arn:aws:sqs:eu-west-1:015424956416:orders-created"
            zappa_path.write_text(
                '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "'
                + arn
                + '"}}]}}',
                encoding="utf-8",
            )
            text = zappa_path.read_text(encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="worker",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )
            scanned = ScannedFile(
                path=zappa_path,
                relative_path="zappa_settings.json",
                text=text,
                lines=tuple(text.splitlines()),
            )
            service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
            build = ConfigKgBuild()

            module.extract_zappa_event_sources(repo, scanned, service, build, "default")

        channels = [entity for entity in build.entities if entity.kind == "EventChannel"]
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].identity["broker_kind"], "sqs")
        self.assertEqual(channels[0].identity["channel_address"], "orders-created")
        self.assertEqual(channels[0].properties["arn"], arn)
        consume_fact = next(fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT")
        self.assertEqual(consume_fact.qualifier["source_kind"], "zappa_event_source")
        self.assertEqual(consume_fact.qualifier["function"], "handlers.consume")
        fact_evidence = [row for row in build.evidence if row.target_id == consume_fact.fact_id]
        self.assertEqual(fact_evidence[0].derivation_class, "authoritative_static")

    def test_private_zappa_extension_ignores_malformed_or_non_sqs_sources(self) -> None:
        cases = [
            "{",
            "[]",
            '{"prod": {"events": "not-a-list"}}',
            '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "arn:aws:s3:::bucket"}}]}}',
            '{"prod": {"events": [{"function": "handlers.consume"}]}}',
        ]
        module = _load_zappa_module()
        for text in cases:
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    zappa_path = root / "zappa_settings.json"
                    zappa_path.write_text(text, encoding="utf-8")
                    repo = RepoSnapshot(
                        root=root,
                        name="worker",
                        owner="test",
                        commit_sha="sha",
                        python_files=(),
                        typescript_files=(),
                    )
                    scanned = ScannedFile(
                        path=zappa_path,
                        relative_path="zappa_settings.json",
                        text=text,
                        lines=tuple(text.splitlines()),
                    )
                    service = Entity(
                        kind="Service",
                        identity={"tenant_id": "default", "namespace": "default", "slug": "svc"},
                    )
                    build = ConfigKgBuild()

                    module.extract_zappa_event_sources(repo, scanned, service, build, "default")

                self.assertFalse(build.entities)
                self.assertFalse(build.facts)
                self.assertFalse(build.evidence)

    def test_private_zappa_extension_preserves_stage_per_event(self) -> None:
        module = _load_zappa_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            zappa_path = root / "zappa_settings.json"
            zappa_path.write_text(
                '{"prod": {"events": [{"function": "handlers.prod", "event_source": {"arn": "'
                'arn:aws:sqs:eu-west-1:015424956416:prod-orders"}}]},'
                '"staging": {"events": [{"function": "handlers.staging", "event_source": {"arn": "'
                'arn:aws:sqs:eu-west-1:015424956416:staging-orders"}}]}}',
                encoding="utf-8",
            )
            text = zappa_path.read_text(encoding="utf-8")
            repo = RepoSnapshot(
                root=root,
                name="worker",
                owner="test",
                commit_sha="sha",
                python_files=(),
                typescript_files=(),
            )
            scanned = ScannedFile(
                path=zappa_path,
                relative_path="zappa_settings.json",
                text=text,
                lines=tuple(text.splitlines()),
            )
            service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
            build = ConfigKgBuild()

            module.extract_zappa_event_sources(repo, scanned, service, build, "default")

        stages = sorted(fact.qualifier["stage"] for fact in build.facts if fact.predicate == "CONSUMES_EVENT")
        self.assertEqual(stages, ["prod", "staging"])


if __name__ == "__main__":
    unittest.main()
