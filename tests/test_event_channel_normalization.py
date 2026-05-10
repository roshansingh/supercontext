from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.config.channel_normalization import normalize_sqs_arn, normalize_sqs_queue_name, normalize_sqs_url
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile, event_channel_entity
from source.kg.extraction.config.deploy_events import extract_deploy_events


class EventChannelNormalizationTest(unittest.TestCase):
    def test_sqs_arn_preserves_raw_metadata(self) -> None:
        arn = "arn:aws:sqs:eu-west-1:015424956416:orders-created"

        channel = normalize_sqs_arn(arn)

        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual(channel.broker_kind, "sqs")
        self.assertEqual(channel.channel_address, "orders-created")
        self.assertEqual(channel.properties["raw_literal"], arn)
        self.assertEqual(channel.properties["arn"], arn)
        self.assertEqual(channel.properties["region"], "eu-west-1")
        self.assertEqual(channel.properties["account_id"], "015424956416")
        self.assertEqual(channel.properties["queue_name"], "orders-created")

    def test_sqs_url_normalizes_to_queue_name(self) -> None:
        url = "https://sqs.us-east-1.amazonaws.com/123456789012/orders-created"

        channel = normalize_sqs_url(url)

        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual(channel.broker_kind, "sqs")
        self.assertEqual(channel.channel_address, "orders-created")
        self.assertEqual(channel.properties["queue_url"], url)
        self.assertIsNone(normalize_sqs_url("https://sqs.us-east-1.amazonaws.com/123456789012/orders.created"))

    def test_sqs_queue_name_normalizes_only_valid_queue_names(self) -> None:
        channel = normalize_sqs_queue_name("orders-created")

        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual(channel.broker_kind, "sqs")
        self.assertEqual(channel.channel_address, "orders-created")
        self.assertIsNotNone(normalize_sqs_queue_name("orders-created.fifo"))
        self.assertIsNone(normalize_sqs_queue_name("not a queue name"))
        self.assertIsNone(normalize_sqs_queue_name("orders.created"))
        self.assertIsNone(normalize_sqs_queue_name("orders-created.fifo.fifo"))
        self.assertIsNone(normalize_sqs_queue_name("a" * 76 + ".fifo"))
        self.assertIsNone(normalize_sqs_queue_name("a" * 81))

    def test_event_channel_identity_matches_ontology_shape(self) -> None:
        repo = _repo_snapshot(Path.cwd())

        channel = event_channel_entity(repo, "sqs", "orders-created", properties={"raw_literal": "orders-created"})

        self.assertEqual(
            channel.identity,
            {"tenant_id": "local-dev", "broker_kind": "sqs", "channel_address": "orders-created"},
        )
        self.assertNotIn("repo", channel.identity)
        self.assertNotIn("name", channel.identity)
        self.assertEqual(channel.properties["raw_literal"], "orders-created")

    def test_zappa_sqs_event_source_uses_channel_address_and_authoritative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            zappa_path = repo_root / "zappa_settings.json"
            arn = "arn:aws:sqs:eu-west-1:015424956416:orders-created"
            zappa_path.write_text(
                '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "'
                + arn
                + '"}}]}}',
                encoding="utf-8",
            )
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=zappa_path,
                relative_path="zappa_settings.json",
                text=zappa_path.read_text(encoding="utf-8"),
                lines=tuple(zappa_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build)

            channels = [entity for entity in build.entities if entity.kind == "EventChannel"]
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].identity["broker_kind"], "sqs")
            self.assertEqual(channels[0].identity["channel_address"], "orders-created")
            self.assertNotIn("repo", channels[0].identity)
            self.assertEqual(channels[0].properties["arn"], arn)
            consume_fact = next(fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT")
            fact_evidence = [row for row in build.evidence if row.target_id == consume_fact.fact_id]
            self.assertEqual(fact_evidence[0].derivation_class, "authoritative_static")
            self.assertEqual(consume_fact.qualifier["raw_literal"], arn)

    def test_keyword_only_queue_like_config_does_not_emit_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / ".env"
            config_path.write_text("APP_MESSAGE_QUEUE=orders-created\n", encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=config_path,
                relative_path=".env",
                text=config_path.read_text(encoding="utf-8"),
                lines=tuple(config_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build)

            self.assertFalse([entity for entity in build.entities if entity.kind == "EventChannel"])
            self.assertFalse([fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL"])

    def test_ini_sqs_shaped_value_emits_event_reference_from_any_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / "prod.ini"
            config_path.write_text("[messaging]\nemail_queue = orders-created\n", encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=config_path,
                relative_path="prod.ini",
                text=config_path.read_text(encoding="utf-8"),
                lines=tuple(config_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build)

            channels = [entity for entity in build.entities if entity.kind == "EventChannel"]
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].identity["channel_address"], "orders-created")
            reference_fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL")
            self.assertEqual(reference_fact.qualifier["source_kind"], "ini_queue_config")

    def test_ini_non_queue_tooling_values_do_not_emit_event_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / "setup.ini"
            config_path.write_text("[flake8]\nmax-line-length = 88\nasyncio_mode = auto\n", encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=config_path,
                relative_path="setup.ini",
                text=config_path.read_text(encoding="utf-8"),
                lines=tuple(config_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build)

            self.assertFalse([entity for entity in build.entities if entity.kind == "EventChannel"])
            self.assertFalse([fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL"])


def _repo_snapshot(root: Path) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        python_files=(),
        typescript_files=(),
    )


if __name__ == "__main__":
    unittest.main()
