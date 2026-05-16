# Graph Storage Recommendation — Product 1

- **Status:** Accepted
- **Date:** 2026-04-29
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** prior paired graph-storage research notes as decision inputs
- **Binding ADR:** [`adr/0003-postgres-age-as-initial-graph-storage.md`](../adr/0003-postgres-age-as-initial-graph-storage.md)

---

## Final recommendation

**Use PostgreSQL + Apache AGE as the initial graph storage layer for Product 1.**

This closes the storage discussion for the current phase.

## Why this won

- It fits the current Product 1 query shape well enough: typed nodes and edges, provenance-heavy properties, bounded multi-hop traversal, blast-radius expansion, and deploy dependency queries.
- It fits the broader platform direction better than a graph-only posture because the platform also needs ordinary operational storage for facts, evidence, metadata, permissions, and application state.
- It preserves a clean self-hosted and enterprise-friendly deployment story.
- It keeps the company on a modular path: the product model is the moat, not Apache AGE itself.

## Modularity clause

This decision is intentionally **not** a permanent storage lock-in.

SuperContext is expected to add more connectors and may later support additional storage backends. To preserve that option:

- the canonical fact model must stay backend-agnostic
- product APIs and MCP tools must not expose raw AGE/Cypher semantics
- graph traversal should remain a projection over normalized facts
- core query semantics must be covered by storage-independent contract tests

## Why the other candidates did not win

**Neo4j**
- Strongest pure graph ergonomics
- Lost on initial platform pragmatism, license posture, and self-hosted simplicity

**Dgraph**
- Credible future fallback if native graph scale becomes a hard requirement
- Lost on operational weight for the current phase

**XTDB**
- Strong temporal model
- Too heavyweight and specialized for the current stage

## Historical inputs

The paired graph-storage research notes were consolidated into this recommendation. Read this document as the surviving decision history.
