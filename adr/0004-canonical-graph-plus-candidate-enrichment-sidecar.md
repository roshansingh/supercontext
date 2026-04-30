# ADR-0004: Build a Canonical Typed Graph with a Separate Candidate / Enrichment Sidecar

- **Status:** Accepted
- **Date:** 2026-04-29
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

`PRD.md` defines Product 1 around high-trust graph queries such as `find_callers`, `find_callees`, `get_event_consumers`, `get_event_producers`, `blast_radius`, and `deploy_blockers_for`. These are not generic summarization workflows. They are operational dependency queries where a wrong-but-plausible answer creates real production risk.

`PLATFORM-PRD.md` extends the same system into a broader enterprise context graph covering docs, tickets, files, incidents, ownership, and operational knowledge. That broader direction increases the temptation to build a loose GraphRAG-style knowledge graph early.

The graph-building research converged against that temptation:

- `graph-building/codex-graph-building-research.md` recommends a **strict canonical operational graph** with a **candidate / enrichment layer** for uncertain facts.
- `graph-building/claude-graph-building-research.md` recommends a **precise, typed knowledge graph** built from deterministic extractors first, with Claude Agent SDK used only as a gap-filler and candidate producer.

This ADR closes the architectural posture for graph building.

## Decision

**Build Product 1 and the early platform around two logical graph layers:**

1. **Canonical typed graph**
2. **Candidate / enrichment sidecar**

For Product 1, the binding implementation scope is:

- the canonical typed graph required by the accepted v1 ontology
- a minimal candidate-fact state model for uncertain facts that must not enter canonical answers yet
- provenance, confidence / derivation class, and promotion metadata sufficient to keep those layers separated

Product 1 does **not** require a broad enrichment subsystem, prose-heavy GraphRAG layer, clustering pipeline, or general-purpose discovery graph.

### Canonical typed graph

The canonical graph is the default graph queried by MCP, PR bot, CLI, and REST surfaces for operational workflows.

It must have:

- explicit node and edge types
- deterministic or authoritative ingestion wherever possible
- stable identities
- explicit provenance
- freshness metadata
- confidence / derivation class
- refusal behavior when coverage is missing

### Candidate / enrichment sidecar

The sidecar is the logical home for uncertain, inferred, ambiguous, or prose-derived relationships.

In v1, it should be implemented as the smallest storage / state boundary needed to preserve trust: candidate facts, confidence / derivation class, provenance, and promotion status. It is not a mandate to build a broad enrichment product.

Over time, it may contain:

- LLM-assisted extraction output
- alias hypotheses
- dynamic call-site hypotheses
- entity-mention relationships from prose
- exploratory or low-confidence links
- future GraphRAG-style enrichments

The sidecar must **not** silently contaminate the canonical graph.

## Relationship to ADR-0006

This ADR did not originally finalize the full canonical entity and relation vocabulary. That was intentional: the ontology needed focused prior-art research before implementation.

ADR-0006 now closes that follow-up. It defines the Product 1 v1 canonical ontology, Entity + Fact + Evidence metadata envelope, coverage sidecar, derivation classes, and promotion / demotion rules.

So the architectural posture is now closed:

- **strict canonical graph**
- **separate candidate / enrichment sidecar**
- **v1 ontology and fact metadata envelope defined by ADR-0006**

Any future ontology expansion must be additive and must preserve this canonical-versus-candidate separation.

## Why this decision

### Positive

- **Matches the Product 1 trust requirement.** The core queries need exact identity, exact edge semantics, provenance, and the ability to say "uninstrumented" rather than hallucinate.
- **Preserves deterministic workflows.** Contracts, manifests, traces, schema registries, and service catalogs are operational fact sources, not prose corpora.
- **Makes refusal possible.** A strict canonical layer can distinguish "missing" from "observed absent" more cleanly than a noisy GraphRAG-style graph.
- **Keeps future platform expansion open.** The sidecar allows later prose-heavy and discovery-heavy use cases without weakening the canonical service graph.
- **Aligns cleanly with the storage decision.** `ADR-0003` chose PostgreSQL + Apache AGE as the initial storage layer with a backend-agnostic fact model. Canonical facts plus sidecar enrichments fit that shape well.

### Negative

- **More moving parts than a single mixed graph.** Canonical and candidate layers require explicit promotion rules and query discipline.
- **Some useful fuzzy knowledge is delayed.** Product 1 will not get the broadest possible discovery behavior on day one.
- **Ontology work moved into a separate binding ADR.** Closing the architectural posture required a separate ontology decision, now captured by ADR-0006.

### Neutral

- This decision does not ban LLMs from graph building.
- This decision does not ban GraphRAG from the platform.
- This decision does require that LLM- or GraphRAG-derived facts be labeled, isolated, and promoted intentionally.

## Graph-building rules

Implementation guardrails:

- Deterministic / authoritative extractors run first.
- Candidate generation runs only after deterministic extraction has had its chance.
- Every fact, canonical or candidate, must carry provenance and freshness in the Entity + Fact + Evidence shape defined by ADR-0006. Source-code-backed facts must also carry evidence metadata compatible with ADR-0005's coordinate-fetch contract.
- Canonical facts must have explicit identity and semantics.
- Derived edges must be marked as derived, not confused with direct evidence.
- Candidate facts must be labeled by source and confidence class.
- Promotion from candidate to canonical must require validation, corroboration, or repeated evidence, depending on edge type, and the promotion decision must be recorded as auditable state / metadata.
- Product surfaces must query the canonical graph by default for operational workflows.

## What belongs where

### Canonical graph

Eligible canonical sources, when explicitly selected by the v1 ontology or later module ADRs:

- service ownership from authoritative catalogs or CODEOWNERS
- endpoints and operations from OpenAPI / proto / GraphQL / AsyncAPI
- typed call edges from structural extraction or symbol-aware analysis
- event producer / consumer edges from contracts, manifests, traces, or registries
- deploy topology from manifests and deployment metadata
- runtime call edges from traces

### Candidate / enrichment sidecar

Eligible candidate / enrichment sources, most of which are outside Product 1 unless explicitly pulled into v1:

- LLM-inferred alias mappings
- unresolved or ambiguous topic mappings
- prose-derived document-to-service links
- likely but unconfirmed dependency hints
- exploratory summaries and clustering outputs

## Alternatives considered

**Single GraphRAG-style mixed graph** — rejected. Too weak for Product 1's trust and refusal requirements.

**LLM-first graph construction** — rejected. Useful as gap-fill and enrichment, not as the default constructor of canonical facts.

**Heavyweight semantic-web ontology project** — rejected. Product 1 needs an operational ontology, not an academic ontology program.

**Canonical graph only, no sidecar** — rejected. Too rigid for future platform expansion and for practical handling of ambiguous evidence.

## Follow-up work resolved by ADR-0006

The following items were intentionally left open by this ADR and are now resolved by ADR-0006:

1. **Research and finalize the exact canonical entities and relations for v1.**
2. **Look for prior art worth borrowing** so we avoid avoidable ontology mistakes.
3. **Define promotion rules** from candidate to canonical by edge type.
4. **Define confidence / derivation classes** consistently across graph-building and query layers.
5. **Define the shared graph fact evidence record shape** that both canonical and candidate facts will use, building on ADR-0005's evidence retrieval contract.

ADR-0006 should be treated as the binding follow-up for these items.

## Consequences

### Immediate

- Product 1 can proceed assuming canonical operational queries run on the typed graph, not on a mixed noisy graph.
- LLM-assisted extraction can proceed, but only into candidate / enrichment paths unless explicitly promoted.
- Ontology research and schema definition are closed by ADR-0006; the next design steps are graph-building implementation boundaries, extractor selection, and query/tool contracts.

### Medium-term

- Product 1 keeps high-trust operational behavior.
- Phase 2+ can add prose-heavy context without reopening this core posture.
- Query surfaces can stay disciplined: canonical by default, sidecar only when explicitly needed.

### Long-term

- The broader platform can host multiple graph-shaped knowledge layers without conflating their trust levels.
- SuperContext's durable asset becomes the graph model, provenance contract, and promotion rules, not just ingestion code.

## References

- `PRD.md` §6.1 (engine), §6.2 (8 MCP tools), §7 (provenance, refusal)
- `PLATFORM-PRD.md` §8 (generic graph model), §10 (architecture principles)
- `adr/0003-postgres-age-as-initial-graph-storage.md`
- `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- `graph-building/codex-graph-building-research.md`
- `graph-building/claude-graph-building-research.md`
