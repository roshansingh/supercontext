# Graph Building Recommendation — Product 1

- **Status:** Accepted
- **Date:** 2026-04-29
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** `codex-graph-building-research.md` and `claude-graph-building-research.md` as decision inputs
- **Binding ADR:** [`../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md`](../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md)

---

## Final recommendation

**Build a strict canonical typed graph for Product 1, with a separate candidate / enrichment sidecar.**

This closes the graph-building posture for the current phase.

## What this means

- Operational workflows query the canonical graph by default.
- Deterministic and authoritative extraction comes first.
- LLM-assisted or ambiguous output goes to the sidecar unless explicitly promoted.
- GraphRAG-style enrichment is allowed later, but not as the substrate for Product 1's core dependency queries.

## Why this won

- Product 1 needs deterministic, provenance-backed answers for change-safety workflows.
- The platform still needs room for fuzzier, prose-driven, and exploratory layers later.
- A two-layer model preserves both without mixing trust levels.

## Important open work

This decision **does not** finalize the exact canonical entity and relation set.

That research is still required and should explicitly look for prior art worth borrowing so the team avoids avoidable ontology mistakes. The architecture is closed; the exact ontology inventory is not.

## Historical inputs

- [`claude-graph-building-research.md`](./claude-graph-building-research.md)
- [`codex-graph-building-research.md`](./codex-graph-building-research.md)

Read those as research history, not as open decisions.

