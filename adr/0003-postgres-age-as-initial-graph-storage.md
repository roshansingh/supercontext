# ADR-0003: Use PostgreSQL + Apache AGE as the Initial Graph Storage Layer

- **Status:** Accepted
- **Date:** 2026-04-29
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

`PRD.md` defines Product 1 as a typed, provenance-first service graph powering eight MCP tools, a PR bot, and CLI / REST surfaces. `PLATFORM-PRD.md` extends that direction into a broader enterprise context graph spanning code, runtime systems, docs, tickets, files, incidents, and ownership.

The storage decision therefore has to satisfy two constraints at once:

1. **Product 1 fit now.** The store must handle typed nodes and edges, provenance-heavy properties, bounded multi-hop traversals, blast-radius expansion, and deploy-dependency queries.
2. **Platform flexibility later.** The store must not lock SuperContext into one storage engine forever. The platform will add more source connectors and may later support additional storage backends if query shape, scale, tenancy, or customer requirements change.

The storage research produced two serious final candidates, synthesized in `docs/graph-storage/GRAPH-STORAGE-RECOMMENDATION.md`:

- **PostgreSQL + Apache AGE**
- **Neo4j**

Both notes agree on the graph model shape: a typed operational graph with rich edge metadata, provenance, and freshness. The disagreement is primarily about implementation tradeoffs: graph-native ergonomics versus operational simplicity, license posture, and modularity for a self-hosted / multi-tenant platform.

This ADR closes that decision.

## Decision

**Use PostgreSQL + Apache AGE as the initial graph storage layer for Product 1 and the early platform.**

More specifically:

- **Canonical source of truth:** PostgreSQL tables for normalized facts, evidence metadata / records, graph metadata, and surrounding application state. Raw source bytes are fetched from source control through the evidence layer defined in ADR-0005.
- **Graph traversal layer:** Apache AGE over PostgreSQL for graph-shaped queries
- **Initial deployment target:** one Postgres instance per environment / region, with one AGE graph per tenant (or one graph per self-hosted customer)

ADR-0006 later refines the canonical table shape as Entity + Fact + Evidence + Coverage rows. In particular, `valid_from` / `valid_to` live on evidence rows, and AGE nodes / edges are projections whose validity is derived at projection time.

This is an **initial storage choice, not a permanent storage lock-in**.

SuperContext will keep the storage layer modular so that additional graph/storage adapters can be supported later if justified by customer needs or platform evolution.

## Storage modularity requirements

The modularity clause is part of the decision, not an implementation detail.

Implementation guardrails:

- The **canonical fact model** must remain backend-agnostic.
- MCP, PR bot, CLI, and REST surfaces must expose **product queries and stable JSON contracts**, not raw AGE/Cypher semantics.
- Ingestion workers must write **normalized facts, provenance, and freshness metadata**, not backend-specific graph tricks.
- Graph edges should be treated as a **queryable projection / materialization over facts**, so a future backend can be introduced without changing connector semantics.
- Candidate / enrichment facts may live in separate tables, schemas, or stores, but they must stay explicitly separated from canonical graph projections unless promoted by validated promotion rules.
- The core Product 1 query semantics must be covered by **contract tests** for at least:
  - `search_services`
  - `get_service_brief`
  - `find_callers`
  - `find_callees`
  - `get_event_consumers`
  - `get_event_producers`
  - `blast_radius`
  - `deploy_blockers_for`
- Future storage adapters are allowed and expected if needed. AGE is the **first supported graph storage adapter**, not the only storage backend the platform may ever support.

## Why this decision

### Positive

- **Best operational fit for the current company stage.** Postgres is already a standard operational substrate with well-understood backup, migration, observability, tenancy, and self-hosting patterns.
- **Aligned with the platform direction.** `PLATFORM-PRD.md` calls for a generic entity-edge-metadata graph, not a vendor-specific graph product. Postgres + AGE supports that without overcommitting to a graph-database-only future.
- **Clean license posture.** PostgreSQL and Apache AGE are clean fits for SaaS and self-hosted deployment, which matters for the target enterprise / regulated ICP.
- **Good enough graph expressiveness for Product 1.** AGE gives openCypher-style traversal over the same Postgres substrate that stores facts, provenance, and app metadata.
- **Supports incremental platform expansion.** Adding entity types such as `Document`, `Ticket`, `Decision`, `Runbook`, and `Incident` is additive rather than a storage rewrite.
- **Easier future backend replacement than a graph-vendor-shaped design.** If query contracts and fact storage stay stable, the AGE layer can later be replaced or supplemented without redefining the product.

### Negative

- **We give up some graph-native ergonomics.** Neo4j remains stronger on pure graph developer experience and graph ecosystem maturity.
- **AGE performance and feature coverage must be validated on real workloads.** In particular, bulk edge ingestion and the exact `blast_radius` / dependency queries need benchmark coverage.
- **Temporal semantics are not first-class.** Historical / bitemporal use cases will need explicit modeling rather than native temporal primitives.
- **Modularity is not free.** If the team leaks AGE-specific assumptions into APIs, prompts, or ingestion paths, future backend support will become expensive.

### Neutral

- This decision does **not** reject future support for other graph stores.
- This decision does **not** require every future connector to use the graph in the same way.
- This decision does **not** imply the enrichment / candidate layer must live inside AGE forever.

## Alternatives considered

**Neo4j** — rejected as the initial default. Strongest pure graph ergonomics and a serious technical option, but less attractive on license posture, self-hosting pragmatics, and “boring” platform operations for the current stage.

**Dgraph** — not chosen as the initial default. Credible fallback if native graph scale becomes the bottleneck, but heavier operationally than Postgres and less attractive as the first platform substrate.

**XTDB** — not chosen. Strong temporal story and an interesting future fit for history-heavy workloads, but too heavyweight / exotic for the current phase.

**Postgres without AGE** — not chosen. Viable, but less ergonomic for graph traversal and would push more graph-query complexity into hand-written SQL / recursive CTEs than is justified up front.

## Consequences

### Immediate

- Product 1 can proceed assuming **Postgres facts + AGE traversal**.
- The next implementation work can define:
  - canonical fact tables
  - evidence/provenance model
  - candidate / enrichment storage and promotion-state model
  - AGE graph projection strategy
  - query contract tests for the 8 Product 1 tools

### Medium-term

- New connectors should target the **canonical fact model first**.
- The platform can add more entity and relation types without reopening the storage decision immediately.
- A future migration to or addition of another graph backend stays viable if the modularity guardrails are respected.

### Long-term

- SuperContext may support multiple storage backends over time.
- The durable product asset is the **graph model, provenance contract, and query semantics**, not Apache AGE itself.

## Implementation Status (as of 2026-05-16)

Storage implementation has not reached PostgreSQL + Apache AGE yet. As of the local pilot, Postgres + AGE is a deferred platform-storage direction, not a setup dependency for building, querying, or evaluating local snapshots.

What exists now:

- The local KG harness writes backend-agnostic JSONL snapshots under `data/kg_runs/`: `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json`.
- The snapshot shape follows the ADR-0006 Entity + Fact + Evidence + Coverage substrate closely enough to validate extraction and query semantics before choosing final table DDL.
- Query code reads the JSONL substrate through `source.kg.queries.KgSnapshot`, keeping current CLI behavior independent of AGE/Cypher.

What is still pending:

- PostgreSQL tables, migrations, and indexes.
- Apache AGE graph creation and projection/materialization from facts.
- Incremental projection strategy, bulk-write path, and storage-level contract tests for the eight Product 1 tools.
- Tenant graph isolation beyond the current local-dev snapshot convention.

## References

- `PRD.md` §6.1 (engine), §6.2 (8 MCP tools), §7 (provenance, refusal), §8 (architecture)
- `PLATFORM-PRD.md` §8 (generic entity-edge-metadata model), §9 (shared surfaces), §10 (architecture principles)
- `docs/graph-building/GRAPH-BUILDING-RECOMMENDATION.md` (strict canonical graph + candidate/enrichment separation)
- `docs/graph-storage/GRAPH-STORAGE-RECOMMENDATION.md` (storage recommendation and tradeoffs)
- `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
