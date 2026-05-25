from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from source.kg.core.models import Entity
from source.kg.core.repo_source import RepoSnapshot
from source.kg.file_formats._shared.common import ConfigKgBuild, ScannedFile
from source.kg.file_formats.zappa import extract_zappa_event_sources


class ZappaExtractionTest(unittest.TestCase):
    def test_single_stage_sqs_event_source_emits_consumer(self) -> None:
        build = _extract(
            '{"prod": {"events": [{"function": "handlers.consume", "event_source": {"arn": "'
            'arn:aws:sqs:eu-west-1:123456789012:orders-created"}}]}}'
        )

        self.assertEqual(_entity_count(build, "EventChannel"), 1)
        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 1)
        fact = next(fact for fact in build.facts if fact.predicate == "CONSUMES_EVENT")
        fact_evidence = next(row for row in build.evidence if row.target_type == "fact" and row.target_id == fact.fact_id)
        self.assertEqual(fact_evidence.derivation_class, "authoritative_static")
        self.assertEqual(fact.qualifier["source_kind"], "zappa_event_source")
        self.assertEqual(fact.qualifier["stage"], "prod")
        self.assertEqual(fact.qualifier["function"], "handlers.consume")
        self.assertEqual(fact.qualifier["normalized_channel"], "orders-created")

    def test_multiple_stages_preserve_stage_per_event(self) -> None:
        build = _extract(
            '{'
            '"prod": {"events": [{"function": "handlers.prod", "event_source": {"arn": "'
            'arn:aws:sqs:eu-west-1:123456789012:orders-created"}}]},'
            '"dev": {"events": [{"function": "handlers.dev", "event_source": {"arn": "'
            'arn:aws:sqs:us-east-1:123456789012:orders-dev"}}]}'
            '}'
        )

        self.assertEqual(_fact_count(build, "CONSUMES_EVENT"), 2)
        self.assertEqual(
            sorted(fact.qualifier["stage"] for fact in build.facts if fact.predicate == "CONSUMES_EVENT"),
            ["dev", "prod"],
        )

    def test_non_sqs_arn_is_skipped(self) -> None:
        build = _extract('{"prod": {"events": [{"function": "h.consume", "event_source": {"arn": "arn:aws:s3:::bucket"}}]}}')

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_malformed_json_is_skipped_silently(self) -> None:
        build = _extract('{"prod": {"events": [}')

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_missing_event_source_is_skipped(self) -> None:
        build = _extract('{"prod": {"events": [{"function": "h.consume"}]}}')

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_missing_arn_is_skipped(self) -> None:
        build = _extract('{"prod": {"events": [{"function": "h.consume", "event_source": {}}]}}')

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_non_list_events_is_skipped(self) -> None:
        build = _extract('{"prod": {"events": {"function": "h.consume"}}}')

        self.assertEqual(build.entities, [])
        self.assertEqual(build.facts, [])
        self.assertEqual(build.evidence, [])

    def test_stage_domain_and_app_function_emit_deploy_and_route(self) -> None:
        build = _extract('{"prod": {"app_function": "app.app", "domain": "api.example.com"}}')

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_entity_count(build, "Domain"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 1)
        deploy = next(fact for fact in build.facts if fact.predicate == "DEPLOYS_VIA_CONFIG")
        route = next(fact for fact in build.facts if fact.predicate == "ROUTES_DOMAIN_TO_DEPLOY")
        self.assertEqual(deploy.object_id, route.object_id)
        self.assertEqual(deploy.qualifier["target_type"], "zappa_lambda")
        self.assertEqual(route.qualifier["stage"], "prod")

    def test_disabled_apigateway_emits_deploy_only(self) -> None:
        build = _extract(
            '{"prod": {"app_function": "app.app", "domain": "api.example.com", "apigateway_enabled": false}}'
        )

        self.assertEqual(_entity_count(build, "DeployTarget"), 1)
        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)

    def test_non_string_domain_fails_closed_for_route(self) -> None:
        build = _extract('{"prod": {"app_function": "app.app", "domain": ["api.example.com"]}}')

        self.assertEqual(_fact_count(build, "DEPLOYS_VIA_CONFIG"), 1)
        self.assertEqual(_fact_count(build, "REFERENCES_DOMAIN"), 0)
        self.assertEqual(_fact_count(build, "ROUTES_DOMAIN_TO_DEPLOY"), 0)


def _extract(text: str) -> ConfigKgBuild:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        settings = root / "zappa_settings.json"
        settings.write_text(text, encoding="utf-8")
        repo = RepoSnapshot(
            root=root,
            name="zappa-service",
            owner="test",
            commit_sha="sha",
            files_by_language={"python": (), "typescript": ()},
        )
        scanned = ScannedFile(
            path=settings,
            relative_path="zappa_settings.json",
            text=text,
            lines=tuple(text.splitlines()),
        )
        service = Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": "svc"})
        build = ConfigKgBuild()
        extract_zappa_event_sources(repo, scanned, service, build, "default")
        return build


def _entity_count(build: ConfigKgBuild, kind: str) -> int:
    return len([entity for entity in build.entities if entity.kind == kind])


def _fact_count(build: ConfigKgBuild, predicate: str) -> int:
    return len([fact for fact in build.facts if fact.predicate == predicate])


if __name__ == "__main__":
    unittest.main()
