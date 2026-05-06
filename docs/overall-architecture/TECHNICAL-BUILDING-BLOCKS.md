# SuperContext Product 1 — Technical Building Blocks

Status: working implementation map  
Last updated: 2026-05-01

Legend:

- `[ADR]` = covered by an accepted ADR
- `[Needs ADR]` = required for implementation, not yet technically finalized
- `[PRD]` = described in `PRD.md`, but not yet converted into a technical decision

## Block Diagram

```text
Customer engineering systems
  |
  |  Git repos, API specs, service catalogs, k8s/Helm, traces, schema/event metadata
  v
+----------------------------------------------------------------------------------+
| Layer A Ingestion Runtime                                             [ADR-0001]  |
| Orchestrates bounded connectors/extractors and writes evidence/fact candidates    |
| Stack: Claude Agent SDK, role allowlists, hooks, SessionStore adapter             |
|                                                                                  |
|   Sub-blocks: Source Connectors + Extractors                         [Needs ADR] |
|   Git/API/spec/manifest/runtime/catalog readers invoked by Layer A               |
|   Stack: GitHub/GitLab APIs, go-git/pygit2, OpenAPI/proto/GraphQL/AsyncAPI        |
|          parsers, k8s/Helm parsers, OTel-compatible client binding TBD           |
+----------------------------------------------------------------------------------+
  |
  v
+----------------------------------------------------------------------------------+
| Graph Building + Reconciliation + Coverage Pipeline              [ADR-0004/0006]  |
| Promotes evidence into canonical/candidate facts; updates aliases and coverage    |
| Stack: deterministic extractors, targeted tree-sitter/ast-grep, typed-client      |
|        allowlist, custom promotion/demotion rules, alias reconciler, freshness    |
|        watchers                                                                  |
+----------------------------------------------------------------------------------+
  |
  v
+----------------------------------------------------------------------------------+
| Canonical Store                                                      [ADR-0003/6] |
| Postgres tables are source of truth: entities, facts, evidence, coverage, aliases |
| Stack: PostgreSQL, SQL migrations, tenant-scoped identity tuples, derivation data |
+----------------------------------------------------------------------------------+
  |
  v
+----------------------------------------------------------------------------------+
| AGE Projection / Materialization Runtime                            [Needs ADR]   |
| Projects canonical facts/evidence into Apache AGE nodes and edges for traversal   |
| Stack: Apache AGE, incremental/full projection jobs, bulk-write strategy TBD      |
+----------------------------------------------------------------------------------+
  |
  v
+----------------------------------------------------------------------------------+
| Query + Tool Execution Engine                                      [Needs ADR]    |
| Plans graph queries, invokes evidence retrieval, merges results, applies refusal  |
| Stack: SQL, AGE/openCypher, custom planner/router, JSON schema contracts          |
+----------------------------------------------------------------------------------+
  |
  v
+----------------------------------------------------------------------------------+
| Product Surfaces                                                                  |
| MCP server [ADR-0002], PR bot [PRD], CLI/REST [PRD]                               |
| Stack: MCP streamable HTTP, OAuth 2.1/static bearer, GitHub/GitLab apps, REST API,|
|        CLI wrapper                                                                |
+----------------------------------------------------------------------------------+
  |
  v
Humans and agents
Claude Code, Cursor, Continue, Cody, Zed, Windsurf, JetBrains AI, Copilot, CI, SRE

Side dependency invoked by Query + Tool Execution Engine:
+----------------------------------------------------------------------------------+
| Evidence Retrieval Layer                                             [ADR-0005]   |
| Proves graph claims with coordinate fetch and selective lexical/structural search |
| Stack: go-git/pygit2, ripgrep, targeted ast-grep/tree-sitter, Claude Explorer,    |
|        later Zoekt adapter                                                       |
+----------------------------------------------------------------------------------+

Specs / contracts used across runtime blocks:
- ADR-0006 ontology and Entity + Fact + Evidence + Coverage envelope.
- ADR-0005 evidence contract and coordinate-fetch shape.
- ADR-0002 MCP tool/resource contract.
```

## Building Blocks

| Block | Coverage | What it does | Tech stack / candidates |
|---|---|---|---|
| Public MCP surface | `[ADR-0002]` | Exposes the eight Product 1 tools and service brief resource to IDE agents. | MCP streamable HTTP, OAuth 2.1, static bearer for self-hosted |
| Internal agent runtime | `[ADR-0001]` | Runs ingestion and server-side reasoning agents with narrow permissions. | Claude Agent SDK, hooks, role allowlists, custom SessionStore |
| Canonical graph posture | `[ADR-0004]` | Keeps high-trust canonical graph separate from candidate/enrichment facts. | Custom graph-building pipeline, canonical/candidate state model |
| Ontology and fact envelope | `[ADR-0006]` | Defines Product 1 entities, relations, evidence, coverage, derivation, promotion. | Spec/contract, Entity + Fact + Evidence + Coverage tables, tenant-scoped identity tuples; URNs scoped by connection context |
| Canonical store | `[ADR-0003/0006]` | Stores entities, facts, evidence, coverage, aliases, and app metadata. | PostgreSQL, SQL migrations, tenant-scoped schema design |
| AGE projection runtime | `[Needs ADR]` | Materializes canonical facts/evidence into AGE nodes and edges for traversal. | Apache AGE, projection jobs, incremental/full rebuild policy, bulk-write strategy |
| Evidence retrieval | `[ADR-0005]` | Fetches commit-pinned bytes and runs selective lexical/structural/agentic search. | go-git or pygit2, ripgrep, targeted ast-grep/tree-sitter, Claude Explorer, later Zoekt |
| Source connectors | `[Needs ADR]` | Layer A-invoked readers for repos, specs, manifests, catalogs, traces, and schema systems. | GitHub/GitLab APIs, OpenAPI/proto/GraphQL/AsyncAPI parsers, k8s/Helm parsers, OTel-compatible client binding TBD |
| Extractor catalog | `[Needs ADR]` | Decides which v1 extractors actually ship and how their outputs map to facts. | Typed-client allowlist, contract parsers, CODEOWNERS, k8s/Helm, trace mappers |
| Alias/entity reconciliation | `[Needs ADR]` | Maps source-native IDs and duplicate observations to canonical tenant-scoped entities. | Alias table, deterministic identity rules, manual override path, reconciliation jobs |
| Coverage-update pipeline | `[Needs ADR]` | Maintains known-empty/unknown/stale/partial coverage and source freshness. | Extractor heartbeats, source liveness checks, trace ingestion freshness watchers |
| Query/tool engine | `[Needs ADR]` | Implements the eight tool semantics, coverage behavior, pagination, and refusal rules. | SQL, AGE/openCypher, graph/evidence merge layer, JSON schema contracts |
| PR bot | `[PRD]` | Posts blast-radius comments on PRs touching public contracts. | GitHub App, GitLab App, diff parser, `blast_radius` tool path |
| CLI + REST | `[PRD]` | Gives humans, CI, and shell agents direct access outside MCP. | REST API, OpenAPI spec, CLI wrapper |
| Auth, tenancy, deployment | `[Needs ADR]` | Defines SaaS/self-hosted authz, tenant isolation, deployment shape, secrets, audit. | OAuth 2.1, SSO/SCIM, Postgres tenancy/RLS decision, Docker/Helm, KMS/secrets |
| Evaluation + contract tests | `[Needs ADR]` | Prevents graph/evidence regressions and validates query correctness. | Golden fixtures, graph query contract tests, evidence replay tests, benchmark harness |
| Observability + operations | `[Needs ADR]` | Tracks ingestion lag, freshness, query latency, refusals, and extractor health. | OpenTelemetry, structured logs, metrics, alerts, audit log storage |

## ADR Coverage Summary

- Covered: internal agent runtime, external MCP protocol, initial graph storage, canonical/candidate graph posture, evidence retrieval, docs/ontology/fact metadata.
- Partially covered: graph-building implementation, source evidence model, query/refusal behavior, storage modularity.
- Not yet covered: source connector architecture, concrete v1 extractor list, tool execution engine, PR bot design, CLI/REST design, auth/tenancy/deployment, observability, testing/evaluation.

## Next ADR Candidates

1. **Tool Query Contract ADR** — semantics for the eight tools, partial coverage rules, pagination, refusal metadata.
2. **Source Connector + Extractor ADR** — exact v1 inputs, parser stack, and typed-client allowlist ownership, driven by the tool contract.
3. **Deployment/Auth/Tenancy ADR** — SaaS/self-hosted boundary, tenant isolation, SSO/SCIM, secrets and audit posture.
4. **Testing/Evaluation ADR** — golden graphs, evidence replay, graph/evidence merge tests, p95 benchmarks.
