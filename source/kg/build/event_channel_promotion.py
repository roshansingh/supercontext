from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from source.kg.core.models import Coverage, Entity, Fact


_DIRECTIONAL_EVENT_PREDICATES = frozenset({"PRODUCES_EVENT", "CONSUMES_EVENT"})
# Literal forms that self-identify an address as a channel even without a directional call.
_CHANNEL_LITERAL_PROPERTY_KEYS = ("arn", "queue_arn", "topic_arn", "queue_url")
_PROMOTION_SOURCE_SYSTEM = "event_channel_promotion"


@dataclass(frozen=True)
class EventChannelPromotionResult:
    entities: list[Entity]
    facts: list[Fact]
    coverage: list[Coverage]


def prune_uncorroborated_event_channels(
    entities: Sequence[Entity], facts: Sequence[Fact]
) -> EventChannelPromotionResult:
    """Drop EventChannels evidenced only by a config value-shape match.

    The config scanner mints an EventChannel for any ini/config value shaped like an
    SQS queue name (alphanumeric + dash). That shape also matches unrelated tokens,
    so a line such as ``region_name = eu-west-1`` under an ``[aws]`` section becomes a
    spurious "channel" carrying only REFERENCES_EVENT_CHANNEL edges. A channel is
    trustworthy only when corroborated by structured evidence:

      * an incoming PRODUCES_EVENT / CONSUMES_EVENT fact -- a real publish/subscribe
        call site or event-source mapping resolved to this address; or
      * a full ARN / queue-URL literal, which is self-identifying.

    Channels with neither are dropped together with their dangling
    REFERENCES_EVENT_CHANNEL facts, and a loud ``coverage`` row records the refusal so
    it is auditable rather than silent. This runs on the fully assembled graph, so a
    config-only reference in one repo is still corroborated by a directional fact in
    another.
    """
    corroborated_ids = {
        fact.object_id for fact in facts if fact.predicate in _DIRECTIONAL_EVENT_PREDICATES
    }
    dropped_ids: set[str] = set()
    kept_entities: list[Entity] = []
    coverage: list[Coverage] = []
    for entity in entities:
        if (
            entity.kind == "EventChannel"
            and entity.canonical_status == "canonical"
            and entity.entity_id not in corroborated_ids
            and not _has_channel_literal(entity)
        ):
            dropped_ids.add(entity.entity_id)
            coverage.append(_uncorroborated_channel_coverage(entity))
            continue
        kept_entities.append(entity)
    if not dropped_ids:
        return EventChannelPromotionResult(list(entities), list(facts), [])
    kept_facts = [fact for fact in facts if fact.object_id not in dropped_ids]
    return EventChannelPromotionResult(kept_entities, kept_facts, coverage)


def _has_channel_literal(entity: Entity) -> bool:
    properties = entity.properties or {}
    return any(properties.get(key) for key in _CHANNEL_LITERAL_PROPERTY_KEYS)


def _uncorroborated_channel_coverage(entity: Entity) -> Coverage:
    identity = entity.identity or {}
    return Coverage(
        tenant_id=str(identity.get("tenant_id", "")),
        predicate="EVENT_CHANNEL_PROMOTION",
        scope_ref={
            "broker_kind": identity.get("broker_kind"),
            "channel_address": identity.get("channel_address"),
            "reason": "uncorroborated_config_value_shape",
        },
        state="uninstrumented",
        source_system=_PROMOTION_SOURCE_SYSTEM,
    )
