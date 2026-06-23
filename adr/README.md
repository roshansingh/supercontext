# Architecture Decision Records

This directory contains accepted architecture decisions for SuperContext. ADRs are append-only unless a later ADR explicitly supersedes an earlier decision. Do not delete an accepted ADR just because implementation has moved in smaller local-pilot steps; mark the current implementation status here or add a superseding ADR.

## Current Local Pilot Status

| ADR | Decision status | Local pilot status |
|---|---|---|
| [0001](0001-claude-agent-sdk-for-internal-runtime.md) | Accepted | Partially implemented. The default KG build path uses deterministic in-process extractors; Claude Agent SDK is currently used only for bounded natural-language KG sessions, answer synthesis, and evaluation helpers. Full Layer A/B SDK orchestration is deferred. |
| [0002](0002-mcp-protocol-for-external-surface.md) | Accepted | Active and partially implemented. A local read-only MCP server and query tools exist; hosted transport, auth, service resources, pagination, and final workflow-tool contracts remain pending. |
| [0003](0003-postgres-age-as-initial-graph-storage.md) | Accepted | Deferred platform-storage direction. The current runnable product uses backend-agnostic JSONL snapshots through `KgSnapshot`; Postgres + Apache AGE are not required for local pilots. |
| [0004](0004-canonical-graph-plus-candidate-enrichment-sidecar.md) | Accepted | Active constraint. Canonical facts and candidate/unlinked enrichment must stay visibly separated in graph storage and packets. |
| [0005](0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md) | Accepted | Active constraint, partially implemented. Evidence packets carry source coordinates; the full coordinate-fetch backend and selective retrieval ladder are still incomplete. |
| [0006](0006-canonical-ontology-and-fact-metadata-envelope.md) | Accepted | Active ontology direction with local deviations. The local KG uses extra code-level entities, support predicates, simplified coverage rows, and JSONL storage while unresolved ontology choices remain tracked. |
| [0007](0007-deterministic-symbol-lookup-with-agentic-disambiguation.md) | Accepted | Active deterministic path. Symbol lookup and disambiguation support exist; agentic fallback remains future candidate enrichment. |
| [0008](0008-deterministic-import-normalization-with-agentic-candidate-fallback.md) | Accepted | Active deterministic path. Import normalization/package classification are implemented and continue to evolve; agentic fallback remains future candidate enrichment. |
| [0009](0009-deterministic-reverse-dependency-queries-with-agentic-candidate-enrichment.md) | Accepted | Active deterministic path. Reverse dependency/package impact queries exist; agentic candidate enrichment remains future work. |
| [0010](0010-deploy-target-without-domain.md) | Accepted | Implemented in the local deploy evidence model. Domainless deploy configs should emit deploy-only evidence, not domain-route evidence. |
| [0011](0011-python-import-distribution-aliases.md) | Accepted | Implemented for Python dependency normalization through declared and metadata-backed import-to-distribution aliases. |
