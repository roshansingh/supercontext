# ADR-0006: Define the Product 1 Canonical Ontology and Fact Metadata Envelope

- **Status:** Accepted
- **Date:** 2026-04-30
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** ADR-0004 follow-up item "Research and finalize the exact canonical entities and relations for v1"
- **Superseded by:** —

---

## Context

ADR-0004 closed the graph-building posture: Product 1 uses a strict canonical typed graph with a separate candidate / enrichment sidecar.

That ADR intentionally left the exact ontology open. We have now completed the ontology prior-art research and debate:

- `ontology/claude-ontology-prior-art-research.md`
- `ontology/codex-ontology-prior-art-research.md`
- `debates/2-2026-04-30-define-the-final-v1-canonical-ontology-f.md`
- `ontology/ONTOLOGY-RECOMMENDATION.md`

This ADR closes the Product 1 v1 ontology and the shared Entity + Fact + Evidence metadata envelope.

## Decision

**Use the ontology defined in `ontology/ONTOLOGY-RECOMMENDATION.md` as the binding Product 1 v1 canonical ontology.**

The binding shape is:

- **10 canonical node types:** `Service`, `Repo`, `Endpoint`, `Schema`, `EventChannel`, `EventMessage`, `Deployable`, `Deployment`, `Environment`, `Owner`
- **15 canonical relation types:** `OWNS`, `DEFINED_IN`, `IMPLEMENTS`, `PROVIDES_API`, `CONSUMES_API`, `CALLS`, `PRODUCES`, `CONSUMES`, `USES_SCHEMA`, `CARRIES`, `RUNS_SERVICE`, `RUNS_IN`, `INSTANCE_OF`, `DEPENDS_ON`, `EVOLVES_TO`
- **Per-node identity tuples**, all tenant-scoped
- **Per-kind URNs**, tenant-scoped by connection/session context
- **Entity + Fact + Evidence rows** as the source of truth
- **AGE nodes and edges as projections**, not the source of truth
- **Evidence-level `valid_from` / `valid_to`**
- **Qualified facts** via `facts.qualifier` for role-bearing relations such as `USES_SCHEMA`
- **Five derivation classes:** `authoritative_declared`, `manual_override`, `deterministic_static`, `runtime_observed`, `inferred_llm`
- **Coverage sidecar table** for known-empty / unknown / stale / partial coverage behavior
- **Per-edge promotion rules** and entity promotion rules
- **Explicit v1 deferrals** for non-MVP platform families such as docs, tickets, incidents, databases, feature flags, code symbols, and broad enterprise knowledge

## Relationship to Prior ADRs

### ADR-0003

ADR-0003 remains the storage decision: PostgreSQL + Apache AGE is the initial graph storage layer.

This ADR refines ADR-0003's schema sketch:

- normalized `entities`, `facts`, `evidence`, and `coverage` tables are the canonical source of truth
- AGE nodes and edges are materialized projections
- edge validity is derived from active evidence rows at projection time
- `valid_from` / `valid_to` live on `evidence`, not as independently managed edge-level source-of-truth columns

If ADR-0003 is read as implying edge-level `valid_from` / `valid_to` are primary storage fields, this ADR supersedes that detail.

### ADR-0004

ADR-0004 remains the graph-building posture: canonical typed graph plus candidate / enrichment sidecar.

This ADR closes ADR-0004's open ontology follow-up. Candidate entities and facts use the same Entity + Fact + Evidence shape with `canonical_status='candidate'`.

### ADR-0005

ADR-0005 remains the evidence retrieval decision.

Source-code-backed entity or fact evidence must carry `bytes_ref` compatible with ADR-0005 Mode A:

`repo + commit_sha + path + line_start + line_end`

## Implementation Guardrails

- Product surfaces query canonical entities/facts by default.
- Candidate entities/facts are visible only through explicit candidate / enrichment paths.
- No entity or fact becomes canonical from `inferred_llm` evidence alone.
- `DEPENDS_ON` is always derived from lower-level facts and must carry derivation evidence with source fact IDs and rule version.
- `USES_SCHEMA` must use `facts.qualifier.role`, not an overloaded evidence field.
- Hash-backed URNs are stable machine IDs; UI surfaces must render human-readable identity tuples as the primary display text.
- URNs are tenant-scoped, not globally unique across tenants.
- Partial coverage policy is owned by tool contracts. Safety-critical / completeness-sensitive tools must refuse unless missing scope is irrelevant to the requested answer.
- High-precision static `CALLS` promotion depends on the typed-client extractor allowlist in `graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md`.

## Consequences

### Positive

- Product 1 has a concrete ontology ready for implementation.
- The graph can answer the eight Product 1 MCP tools without pulling in deferred platform scope.
- Provenance, freshness, confidence, promotion, and coverage are modeled consistently for both nodes and edges.
- Later platform entities can be added without replacing the Entity + Fact + Evidence substrate.

### Negative

- The model is more explicit than a simple property graph. Implementation must manage canonical storage and AGE projection separately.
- Tool contracts still need to define partial-coverage behavior per tool.
- The typed-client extractor allowlist must be maintained as implementation evolves.

### Neutral

- This ADR does not choose every source connector implementation.
- This ADR does not define the MCP tool schemas in full.
- This ADR does not make broad language indexing, SCIP, GraphRAG, docs, tickets, incidents, databases, or feature flags part of Product 1 v1.

## References

- `ontology/ONTOLOGY-RECOMMENDATION.md`
- `ontology/claude-ontology-prior-art-research.md`
- `ontology/codex-ontology-prior-art-research.md`
- `debates/2-2026-04-30-define-the-final-v1-canonical-ontology-f.md`
- `graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md`
- ADR-0003: `adr/0003-postgres-age-as-initial-graph-storage.md`
- ADR-0004: `adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md`
- ADR-0005: `adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`
- `PRD.md` §6.1, §6.2, §7, §9
- `PLATFORM-PRD.md` §8, §10, §11

