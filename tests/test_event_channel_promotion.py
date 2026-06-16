from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from source.kg.build.event_channel_promotion import prune_uncorroborated_event_channels
from source.kg.core.models import Entity, Fact
from source.kg.core.store import JsonlKgStore
from source.kg.query.snapshot import KgSnapshot


def _channel(channel_address: str, *, properties: dict | None = None) -> Entity:
    return Entity(
        kind="EventChannel",
        identity={"tenant_id": "default", "broker_kind": "sqs", "channel_address": channel_address},
        properties=properties or {},
    )


def _service(slug: str) -> Entity:
    return Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": slug, "repo": slug})


class EventChannelPromotionTest(unittest.TestCase):
    def test_demotes_channel_with_only_references_and_records_loud_coverage(self) -> None:
        # `region_name = eu-west-1` becomes a bare-name channel with only REFERENCES.
        region = _channel("eu-west-1")
        svc = _service("campaign")
        ref = Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, region.entity_id)

        result = prune_uncorroborated_event_channels([region, svc], [ref])

        demoted = next(e for e in result.entities if e.entity_id == region.entity_id)
        self.assertEqual(demoted.canonical_status, "candidate")
        self.assertIn(svc.entity_id, {e.entity_id for e in result.entities})
        # The config reference remains available as candidate evidence.
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.facts[0].predicate, "REFERENCES_EVENT_CHANNEL")
        self.assertEqual(result.facts[0].canonical_status, "candidate")
        # refusal is loud, not silent
        self.assertEqual(len(result.coverage), 1)
        cov = result.coverage[0]
        self.assertEqual(cov.predicate, "EVENT_CHANNEL_PROMOTION")
        self.assertEqual(cov.state, "uninstrumented")
        self.assertEqual(cov.scope_ref["channel_address"], "eu-west-1")
        self.assertEqual(cov.scope_ref["reason"], "uncorroborated_config_value_shape")

    def test_keeps_channel_corroborated_by_producer(self) -> None:
        channel = _channel("la-prod-email")
        svc = _service("campaign")
        ref = Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, channel.entity_id)
        produce = Fact("PRODUCES_EVENT", svc.entity_id, channel.entity_id)

        result = prune_uncorroborated_event_channels([channel, svc], [ref, produce])

        self.assertIn(channel.entity_id, {e.entity_id for e in result.entities})
        self.assertEqual(len(result.facts), 2)  # reference preserved alongside the directional fact
        self.assertEqual(result.coverage, [])

    def test_keeps_channel_corroborated_by_consumer_only(self) -> None:
        channel = _channel("la-prod-shopify")
        svc = _service("api")
        consume = Fact("CONSUMES_EVENT", svc.entity_id, channel.entity_id)

        result = prune_uncorroborated_event_channels([channel, svc], [consume])

        self.assertIn(channel.entity_id, {e.entity_id for e in result.entities})
        self.assertEqual(result.coverage, [])

    def test_keeps_channel_with_arn_literal_even_without_directional_fact(self) -> None:
        # A full ARN is self-identifying as a channel, so a reference-only ARN survives.
        channel = _channel(
            "orders-created",
            properties={"arn": "arn:aws:sqs:eu-west-1:123456789012:orders-created"},
        )
        svc = _service("orders")
        ref = Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, channel.entity_id)

        result = prune_uncorroborated_event_channels([channel, svc], [ref])

        self.assertIn(channel.entity_id, {e.entity_id for e in result.entities})
        self.assertEqual(result.coverage, [])

    def test_no_op_when_all_channels_corroborated(self) -> None:
        channel = _channel("la-prod-email")
        svc = _service("campaign")
        produce = Fact("PRODUCES_EVENT", svc.entity_id, channel.entity_id)

        result = prune_uncorroborated_event_channels([channel, svc], [produce])

        self.assertEqual({e.entity_id for e in result.entities}, {channel.entity_id, svc.entity_id})
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(result.coverage, [])

    def test_does_not_demote_already_candidate_channels(self) -> None:
        channel = Entity(
            kind="EventChannel",
            identity={"tenant_id": "default", "broker_kind": "sqs", "channel_address": "eu-west-1"},
            canonical_status="candidate",
        )

        result = prune_uncorroborated_event_channels([channel], [])

        # only canonical channels are subject to the promotion gate
        self.assertIn(channel.entity_id, {e.entity_id for e in result.entities})
        self.assertEqual(result.coverage, [])

    def test_event_channel_query_partitions_candidate_references_from_known_rows(self) -> None:
        svc = _service("campaign")
        candidate_channel = _channel("orders-created", properties={})
        canonical_channel = _channel("billing-created", properties={})
        candidate_ref = Fact(
            "REFERENCES_EVENT_CHANNEL",
            svc.entity_id,
            candidate_channel.entity_id,
            canonical_status="candidate",
        )
        canonical_consume = Fact("CONSUMES_EVENT", svc.entity_id, canonical_channel.entity_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            JsonlKgStore(root).write(
                entities=[
                    svc,
                    Entity(
                        kind=candidate_channel.kind,
                        identity=candidate_channel.identity,
                        properties=candidate_channel.properties,
                        canonical_status="candidate",
                    ),
                    canonical_channel,
                ],
                facts=[candidate_ref, canonical_consume],
                evidence=[],
                coverage=[],
                manifest={"version": 1},
            )
            candidate = KgSnapshot(root).event_channels("orders-created", limit=10)
            known = KgSnapshot(root).event_channels("billing-created", limit=10)

        self.assertEqual(candidate["status"], "found")
        self.assertEqual(candidate["event_fact_count"], 1)
        self.assertEqual(candidate["known_linked_count"], 0)
        self.assertEqual(candidate["candidate_or_unlinked_count"], 1)
        self.assertEqual(candidate["event_channels"], [])
        self.assertEqual(candidate["candidate_or_unlinked"][0]["predicate"], "REFERENCES_EVENT_CHANNEL")
        self.assertEqual(candidate["candidate_or_unlinked"][0]["linkage_status"], "candidate_or_unlinked")

        self.assertEqual(known["known_linked_count"], 1)
        self.assertEqual(known["candidate_or_unlinked_count"], 0)
        self.assertEqual(known["event_channels"][0]["predicate"], "CONSUMES_EVENT")
        self.assertEqual(known["event_channels"][0]["linkage_status"], "known_linked")

    def test_event_channel_query_applies_limit_across_buckets(self) -> None:
        svc = _service("campaign")
        known_a = _channel("billing-created")
        known_b = _channel("invoice-created")
        candidate_a = Entity(
            kind="EventChannel",
            identity={"tenant_id": "default", "broker_kind": "sqs", "channel_address": "orders-created"},
            canonical_status="candidate",
        )
        candidate_b = Entity(
            kind="EventChannel",
            identity={"tenant_id": "default", "broker_kind": "sqs", "channel_address": "returns-created"},
            canonical_status="candidate",
        )
        facts = [
            Fact("CONSUMES_EVENT", svc.entity_id, known_a.entity_id),
            Fact("PRODUCES_EVENT", svc.entity_id, known_b.entity_id),
            Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, candidate_a.entity_id, canonical_status="candidate"),
            Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, candidate_b.entity_id, canonical_status="candidate"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            JsonlKgStore(root).write(
                entities=[svc, known_a, known_b, candidate_a, candidate_b],
                facts=facts,
                evidence=[],
                coverage=[],
                manifest={"version": 1},
            )
            result = KgSnapshot(root).event_channels(limit=3)

        self.assertEqual(result["event_fact_count"], 4)
        self.assertEqual(result["known_linked_count"], 2)
        self.assertEqual(result["candidate_or_unlinked_count"], 2)
        self.assertEqual(result["returned_count"], 3)
        self.assertEqual(result["candidate_returned_count"], 1)
        self.assertEqual(len(result["event_channels"]), 2)
        self.assertEqual(len(result["candidate_or_unlinked"]), 1)

    def test_event_channel_query_normalizes_emitted_status_fields(self) -> None:
        svc = _service("campaign")
        channel = _channel("orders-created")
        consume = Fact("CONSUMES_EVENT", svc.entity_id, channel.entity_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            JsonlKgStore(root).write(
                entities=[svc, channel],
                facts=[consume],
                evidence=[],
                coverage=[],
                manifest={"version": 1},
            )
            entity_rows = [json.loads(line) for line in (root / "entities.jsonl").read_text(encoding="utf-8").splitlines()]
            fact_rows = [json.loads(line) for line in (root / "facts.jsonl").read_text(encoding="utf-8").splitlines()]
            for row in entity_rows:
                if row["entity_id"] == channel.entity_id:
                    row["canonical_status"] = None
            fact_rows[0]["canonical_status"] = None
            (root / "entities.jsonl").write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in entity_rows) + "\n",
                encoding="utf-8",
            )
            (root / "facts.jsonl").write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in fact_rows) + "\n",
                encoding="utf-8",
            )
            result = KgSnapshot(root).event_channels("orders-created", limit=10)

        row = result["event_channels"][0]
        self.assertEqual(row["canonical_status"], "canonical")
        self.assertEqual(row["channel_canonical_status"], "canonical")
        self.assertEqual(row["linkage_status"], "known_linked")


if __name__ == "__main__":
    unittest.main()
