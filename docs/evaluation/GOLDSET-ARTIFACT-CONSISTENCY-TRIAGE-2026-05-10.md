# Goldset Artifact Consistency Triage

Date: 2026-05-10

## Question

Are the remaining LatticeAI goldset partials current product failures, or are they stale evaluation artifacts?

## Finding

They are currently stale artifact failures. The canonical EvidencePacket files contain newer evidence than the synthesized answer/judgement files used by the canonical validation report.

## Evidence

| Scenario | Current packet | Current answer metadata | Triage |
|---|---:|---:|---|
| Q082 | 50 evidence items, 2 retrieval steps | 30 evidence items, 2 retrieval steps | Stale answer after config/env citation improvements. |
| Q088 | 11 evidence items, 3 retrieval steps | 1 evidence item, 2 retrieval steps | Stale answer; current packet includes campaign scheduling, delivery, and email-status event facts. |
| Q106 | 9 evidence items, 2 retrieval steps | 2 evidence items, 2 retrieval steps | Stale answer; current packet includes producer, consumer, and downstream email-status evidence. |

Q088 and Q106 also pass in the event-focused judgement artifacts, which confirms the KG/evidence layer already improved for the event-channel path. The canonical validation report should therefore stop treating the stale judgement rows as direct evidence of `missing KG fact` or `bad retrieval plan`.

## Decision

Add a generic artifact-consistency guard to the canonical validation report:

- Compare each current EvidencePacket row to the synthesized answer row metadata.
- Mark rows as `current`, `stale`, `unverified`, `missing_packet`, or `missing_answer`.
- Exclude stale/unverified rows from product-gap failure-owner aggregation.
- Tell the reader to regenerate answers and judgement from current packets before selecting the next product feature.

## Next Step

Regenerate goldset answers and judgement from the current packets. If Q088/Q106 still fail after regeneration, debug the answer synthesis or retrieval plan. If they pass, the next product-effectiveness gap should come from the remaining current failures only.
