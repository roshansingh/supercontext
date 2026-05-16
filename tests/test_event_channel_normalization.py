from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.extraction.adapters.event_channel_normalizer import EVENT_CHANNEL_NORMALIZER_ADAPTER
from source.kg.extraction.config.channel_normalization import (
    normalize_sns_arn,
    normalize_sqs_arn,
    normalize_sqs_queue_name,
    normalize_sqs_url,
    normalized_channels_in_text,
)
from source.kg.extraction.config.common import ConfigKgBuild, ScannedFile, event_channel_entity
from source.kg.extraction.config.deploy_events import extract_deploy_events
from source.kg.extraction.config.static_extractor import StaticConfigExtractor
from source.kg.extraction.framework.adapter import ExtractionContext
from source.kg.extraction.framework.runner import run_adapters


class EventChannelNormalizationTest(unittest.TestCase):
    def test_sqs_arn_preserves_raw_metadata(self) -> None:
        arn = "arn:aws:sqs:eu-west-1:123456789012:orders-created"

        channel = normalize_sqs_arn(arn)

        self.assertIsNotNone(channel)
        assert channel is not None
        self.assertEqual(channel.broker_kind, "sqs")
        self.assertEqual(channel.channel_address, "orders-created")
        self.assertEqual(channel.properties["raw_literal"], arn)
        self.assertEqual(channel.properties["arn"], arn)
        self.assertEqual(channel.properties["region"], "eu-west-1")
        self.assertEqual(channel.properties["account_id"], "123456789012")
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
        self.assertIsNone(normalize_sqs_url("https://sqs..amazonaws.com/123456789012/orders-created"))
        self.assertIsNone(normalize_sqs_url("https://sqs.us_east_1.amazonaws.com/123456789012/orders-created"))

    def test_sns_arn_rejects_nested_resource_names(self) -> None:
        self.assertIsNotNone(normalize_sns_arn("arn:aws:sns:us-east-1:123456789012:orders-topic"))
        self.assertIsNone(normalize_sns_arn("arn:aws:sns:us-east-1:123456789012:orders:topic"))
        self.assertIsNone(normalize_sns_arn("arn:aws:sns:us-east-1:123456789012:orders.topic"))
        self.assertIsNone(normalize_sns_arn("arn:aws:sns:us_east_1:123456789012:orders-topic"))
        self.assertIsNone(normalize_sns_arn("arn:aws:sns:us-east-1:123456789012:orders-１２３"))

    def test_sqs_arn_rejects_invalid_region(self) -> None:
        self.assertIsNone(normalize_sqs_arn("arn:aws:sqs:us_east_1:123456789012:orders-created"))

    def test_channel_tokens_are_extracted_from_config_text_without_regex(self) -> None:
        channels = normalized_channels_in_text(
            "queue=arn:aws:sqs:us-east-1:123456789012:orders-created, "
            "url='https://sqs.us-east-1.amazonaws.com/123456789012/payments-created'"
        )

        self.assertEqual([channel.channel_address for channel in channels], ["orders-created", "payments-created"])

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
        self.assertIsNone(normalize_sqs_queue_name("orders-１２３"))

    def test_event_channel_identity_matches_ontology_shape(self) -> None:
        repo = _repo_snapshot(Path.cwd())

        channel = event_channel_entity(
            repo,
            "sqs",
            "orders-created",
            tenant_id="default",
            properties={"raw_literal": "orders-created"},
        )

        self.assertEqual(
            channel.identity,
            {"tenant_id": "default", "broker_kind": "sqs", "channel_address": "orders-created"},
        )
        self.assertNotIn("repo", channel.identity)
        self.assertNotIn("name", channel.identity)
        self.assertEqual(channel.properties["raw_literal"], "orders-created")

    def test_deploy_events_no_longer_emits_zappa_gap_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            zappa_path = repo_root / "zappa_settings.json"
            arn = "arn:aws:sqs:eu-west-1:123456789012:orders-created"
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

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=False)

            self.assertFalse([entity for entity in build.entities if entity.kind == "EventChannel"])
            self.assertFalse([fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT"])
            self.assertFalse(
                [
                    row
                    for row in build.coverage
                    if row.predicate == "CONSUMES_EVENT"
                    and row.scope_ref.get("reason") == "no_oss_adapter_for_zappa_event_sources"
                ]
            )

    def test_zappa_settings_without_events_does_not_emit_zappa_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            zappa_path = repo_root / "zappa_settings.json"
            zappa_path.write_text('{"prod": {"aws_region": "us-east-1"}}', encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=zappa_path,
                relative_path="zappa_settings.json",
                text=zappa_path.read_text(encoding="utf-8"),
                lines=tuple(zappa_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=False)

            self.assertFalse(
                [
                    row
                    for row in build.coverage
                    if row.predicate == "CONSUMES_EVENT"
                    and row.scope_ref.get("reason") == "no_oss_adapter_for_zappa_event_sources"
                ]
            )

    def test_zappa_settings_with_empty_events_does_not_emit_zappa_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            zappa_path = repo_root / "zappa_settings.json"
            zappa_path.write_text('{"prod": {"events": []}}', encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=zappa_path,
                relative_path="zappa_settings.json",
                text=zappa_path.read_text(encoding="utf-8"),
                lines=tuple(zappa_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=False)

            self.assertFalse(
                [
                    row
                    for row in build.coverage
                    if row.predicate == "CONSUMES_EVENT"
                    and row.scope_ref.get("reason") == "no_oss_adapter_for_zappa_event_sources"
                ]
            )

    def test_zappa_settings_with_non_sqs_event_source_does_not_emit_zappa_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            zappa_path = repo_root / "zappa_settings.json"
            zappa_path.write_text(
                '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "arn:aws:s3:::bucket"}}]}}',
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

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=False)

            self.assertFalse(
                [
                    row
                    for row in build.coverage
                    if row.predicate == "CONSUMES_EVENT"
                    and row.scope_ref.get("reason") == "no_oss_adapter_for_zappa_event_sources"
                ]
            )

    def test_deploy_events_no_longer_emits_apache_vhost_gap_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            apache_path = repo_root / "site.conf"
            apache_path.write_text(
                "<VirtualHost *:80>\n"
                "  ServerName\tapi.example.com\n"
                "  WSGIScriptAlias   / /srv/app/wsgi.py\n"
                "</VirtualHost>\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=apache_path,
                relative_path="site.conf",
                text=apache_path.read_text(encoding="utf-8"),
                lines=tuple(apache_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build, "default", include_event_channel_references=False)

        self.assertFalse(
            [
                row
                for row in build.coverage
                if row.predicate == "ROUTES_DOMAIN_TO_DEPLOY"
                and row.scope_ref.get("reason") == "no_oss_adapter_for_apache_vhosts"
            ]
        )

    def test_non_apache_conf_does_not_emit_apache_vhost_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            conf_path = repo_root / "app.conf"
            conf_path.write_text("server_name=api.example.com\n", encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=conf_path,
                relative_path="app.conf",
                text=conf_path.read_text(encoding="utf-8"),
                lines=tuple(conf_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build, "default", include_event_channel_references=False)

        self.assertFalse(
            [
                row
                for row in build.coverage
                if row.predicate == "ROUTES_DOMAIN_TO_DEPLOY"
                and row.scope_ref.get("reason") == "no_oss_adapter_for_apache_vhosts"
            ]
        )

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

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=True)

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

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=True)

            channels = [entity for entity in build.entities if entity.kind == "EventChannel"]
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].identity["channel_address"], "orders-created")
            reference_fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL")
            self.assertEqual(reference_fact.qualifier["source_kind"], "ini_queue_config")

    def test_ini_default_queue_value_emits_once_with_default_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / "prod.ini"
            config_path.write_text(
                "[DEFAULT]\nemail_queue = orders-created\n\n[messaging]\nother = ignoredvalue\n",
                encoding="utf-8",
            )
            repo = _repo_snapshot(repo_root)
            build = ConfigKgBuild()
            service = Entity(kind="Service", identity={"tenant_id": "local-dev", "namespace": "default", "slug": "svc"})
            scanned = ScannedFile(
                path=config_path,
                relative_path="prod.ini",
                text=config_path.read_text(encoding="utf-8"),
                lines=tuple(config_path.read_text(encoding="utf-8").splitlines()),
            )

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=True)

            channels = [entity for entity in build.entities if entity.kind == "EventChannel"]
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].identity["channel_address"], "orders-created")
            reference_fact = next(fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL")
            evidence = [row for row in build.evidence if row.target_id == reference_fact.fact_id]
            self.assertEqual(evidence[0].bytes_ref["line_start"], 2)

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

            extract_deploy_events(repo, [scanned], service, build, include_event_channel_references=False)

            self.assertFalse([entity for entity in build.entities if entity.kind == "EventChannel"])
            self.assertFalse([fact for fact in build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL"])

    def test_event_channel_adapter_matches_legacy_deploy_event_reference_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / "prod.ini"
            config_path.write_text("[messaging]\nemail_queue = orders-created\n", encoding="utf-8")
            repo = _repo_snapshot(repo_root)
            scanned = ScannedFile(
                path=config_path,
                relative_path="prod.ini",
                text=config_path.read_text(encoding="utf-8"),
                lines=tuple(config_path.read_text(encoding="utf-8").splitlines()),
            )

            legacy_build = ConfigKgBuild()
            service = StaticConfigExtractor()._service_entity(repo, "default")
            extract_deploy_events(
                repo,
                [scanned],
                service,
                legacy_build,
                "default",
                include_event_channel_references=True,
            )
            _, adapter_facts, _, _, adapter_errors = run_adapters(
                repo,
                [EVENT_CHANNEL_NORMALIZER_ADAPTER],
                ctx=ExtractionContext(tenant_id="default"),
            )

        self.assertEqual(adapter_errors, [])
        legacy_fact_ids = {
            fact.fact_id for fact in legacy_build.facts if fact.predicate == "REFERENCES_EVENT_CHANNEL"
        }
        adapter_fact_ids = {
            fact.fact_id for fact in adapter_facts if fact.predicate == "REFERENCES_EVENT_CHANNEL"
        }
        self.assertEqual(legacy_fact_ids, adapter_fact_ids)


def _repo_snapshot(root: Path) -> RepoSnapshot:
    return RepoSnapshot(
        root=root,
        name=root.name,
        owner=root.parent.name,
        commit_sha="test-sha",
        files_by_language={"python": (), "typescript": ()},
    )


if __name__ == "__main__":
    unittest.main()
