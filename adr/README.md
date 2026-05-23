# Architecture Decision Records

This directory contains accepted architecture decisions for SuperContext. ADRs are append-only unless a later ADR explicitly supersedes an earlier decision.

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-claude-agent-sdk-for-internal-runtime.md) | Accepted | Use Claude Agent SDK for the internal runtime layer. |
| [0002](0002-mcp-protocol-for-external-surface.md) | Accepted | Expose the external tool surface through MCP. |
| [0003](0003-postgres-age-as-initial-graph-storage.md) | Accepted | Use Postgres plus Apache AGE as the initial graph storage. |
| [0004](0004-canonical-graph-plus-candidate-enrichment-sidecar.md) | Accepted | Keep canonical typed graph facts separate from candidate/enrichment facts. |
| [0005](0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md) | Accepted | Use modular evidence retrieval with coordinate fetch and selective laddering. |
| [0006](0006-canonical-ontology-and-fact-metadata-envelope.md) | Accepted | Define canonical ontology and fact metadata envelope. |
| [0007](0007-deterministic-symbol-lookup-with-agentic-disambiguation.md) | Accepted | Start symbol lookup deterministically, with agentic disambiguation as candidate enrichment. |
| [0008](0008-deterministic-import-normalization-with-agentic-candidate-fallback.md) | Accepted | Start import normalization deterministically, with agentic candidate fallback later. |
| [0009](0009-deterministic-reverse-dependency-queries-with-agentic-candidate-enrichment.md) | Accepted | Use deterministic reverse dependency queries with agentic candidate enrichment later. |
| [0010](0010-deploy-target-without-domain.md) | Accepted | Represent deploy targets without domains as deploy-only facts. |
| [0011](0011-python-import-distribution-aliases.md) | Accepted | Use declared- and metadata-backed Python import distribution aliases. |
