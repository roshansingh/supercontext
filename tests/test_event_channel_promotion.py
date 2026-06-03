from __future__ import annotations

import unittest

from source.kg.build.event_channel_promotion import prune_uncorroborated_event_channels
from source.kg.core.models import Entity, Fact


def _channel(channel_address: str, *, properties: dict | None = None) -> Entity:
    return Entity(
        kind="EventChannel",
        identity={"tenant_id": "default", "broker_kind": "sqs", "channel_address": channel_address},
        properties=properties or {},
    )


def _service(slug: str) -> Entity:
    return Entity(kind="Service", identity={"tenant_id": "default", "namespace": "default", "slug": slug, "repo": slug})


class EventChannelPromotionTest(unittest.TestCase):
    def test_drops_channel_with_only_references_and_records_loud_coverage(self) -> None:
        # `region_name = eu-west-1` becomes a bare-name channel with only REFERENCES.
        region = _channel("eu-west-1")
        svc = _service("campaign")
        ref = Fact("REFERENCES_EVENT_CHANNEL", svc.entity_id, region.entity_id)

        result = prune_uncorroborated_event_channels([region, svc], [ref])

        self.assertNotIn(region.entity_id, {e.entity_id for e in result.entities})
        self.assertIn(svc.entity_id, {e.entity_id for e in result.entities})
        # the dangling reference fact is dropped with the channel
        self.assertEqual(result.facts, [])
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


if __name__ == "__main__":
    unittest.main()
