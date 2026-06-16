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
    """Demote EventChannels evidenced only by a config value-shape match.

    The config scanner mints an EventChannel for any ini/config value shaped like an
    SQS queue name (alphanumeric + dash). That shape also matches unrelated tokens,
    so a line such as ``region_name = eu-west-1`` under an ``[aws]`` section becomes a
    spurious "channel" carrying only REFERENCES_EVENT_CHANNEL edges. A channel is
    trustworthy only when corroborated by structured evidence:

      * an incoming PRODUCES_EVENT / CONSUMES_EVENT fact -- a real publish/subscribe
        call site or event-source mapping resolved to this address; or
      * a full ARN / queue-URL literal, which is self-identifying.

    Channels with neither are demoted together with facts that point at them, and a
    loud ``coverage`` row records the refusal so it is auditable rather than silent.
    This keeps the source-inspection lead available while preventing config-only
    references from being presented as known event flow. This runs on the fully
    assembled graph, so a config-only reference in one repo is still corroborated by
    a directional fact in another.
    """
    corroborated_ids = {
        fact.object_id for fact in facts if fact.predicate in _DIRECTIONAL_EVENT_PREDICATES
    }
    demoted_ids: set[str] = set()
    kept_entities: list[Entity] = []
    coverage: list[Coverage] = []
    for entity in entities:
        if (
            entity.kind == "EventChannel"
            and entity.canonical_status == "canonical"
            and entity.entity_id not in corroborated_ids
            and not _has_channel_literal(entity)
        ):
            demoted_ids.add(entity.entity_id)
            kept_entities.append(_candidate_entity(entity))
            coverage.append(_uncorroborated_channel_coverage(entity))
            continue
        kept_entities.append(entity)
    if not demoted_ids:
        return EventChannelPromotionResult(list(entities), list(facts), [])
    kept_facts = [_candidate_fact(fact) if fact.object_id in demoted_ids else fact for fact in facts]
    return EventChannelPromotionResult(kept_entities, kept_facts, coverage)


def _candidate_entity(entity: Entity) -> Entity:
    return Entity(
        kind=entity.kind,
        identity=dict(entity.identity),
        properties=dict(entity.properties),
        canonical_status="candidate",
    )


def _candidate_fact(fact: Fact) -> Fact:
    return Fact(
        predicate=fact.predicate,
        subject_id=fact.subject_id,
        object_id=fact.object_id,
        qualifier=dict(fact.qualifier),
        canonical_status="candidate",
    )


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
