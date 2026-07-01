# SuperContext Project Index

Annotated index for agents and contributors. Read this before opening many docs blindly. Each entry names the owner, URL, what is inside, and when to read it.

## Start Here

| URL | Owner | Annotation |
|---|---|---|
| [README.md](README.md) | Project | Top-level repository overview, setup commands, coverage-report commands, MCP server command, extraction scope, and repository layout. Read first when orienting to the repo or checking standard commands. |
| [source/README.md](source/README.md) | KG implementation | Lower-level source-module overview, local query examples, Streamlit harness notes, and MCP server details. Read when working on `source/kg`, scripts, query surfaces, or MCP behavior. |
| [docs/PRD.md](docs/PRD.md) | Product | Product 1 rationale, target users, eight MCP tools, UX principles, surfaces, and risks. Read before changing product scope, MCP contracts, or user-facing claims. |
| [docs/PLATFORM-PRD.md](docs/PLATFORM-PRD.md) | Product | Broader platform direction beyond the local KG prototype. Read when a change might affect enterprise context graph, hosted surfaces, or long-term platform positioning. |
| [docs/mcp/HOST_SKILL_EVALUATION.md](docs/mcp/HOST_SKILL_EVALUATION.md) | MCP/product | Checklist for testing whether Codex and Claude Code actually use the installed SuperContext MCP skill during planning, coding, and review. Read when evaluating host-agent behavior after installing MCP skills. |
| [docs/mcp/MCP-TOOL-OUTPUT-FIELDS.md](docs/mcp/MCP-TOOL-OUTPUT-FIELDS.md) | MCP/product | Field reference for every exposed MCP tool response, common row shapes, prompt usage notes, and known duplicate follow-up/inspection fields. Read before changing tool outputs, packet fields, or prompt routing. |

## Architecture Decisions

| URL | Owner | Annotation |
|---|---|---|
| [adr/README.md](adr/README.md) | Architecture | ADR index plus current local-pilot implementation status for each accepted decision. Read before proposing new architecture or deciding whether an ADR is active, deferred, or superseded. |
| [adr/0001-claude-agent-sdk-for-internal-runtime.md](adr/0001-claude-agent-sdk-for-internal-runtime.md) | Agent runtime | Accepted direction for Claude Agent SDK in internal Layer A/B runtime, with default local KG builds still deterministic and SDK-free. Read before changing internal agent runtime, bounded answer synthesis, evaluation helpers, or no-egress assumptions. |
| [adr/0002-mcp-protocol-for-external-surface.md](adr/0002-mcp-protocol-for-external-surface.md) | MCP surface | Public MCP protocol decision, the eight tool names, current implementation status, and rationale for small structured tools. Read before changing MCP tools, schemas, transport, or host-agent integration. |
| [adr/0003-postgres-age-as-initial-graph-storage.md](adr/0003-postgres-age-as-initial-graph-storage.md) | Storage | Accepted platform storage direction for Postgres plus Apache AGE, while the current local pilot uses JSONL snapshots. Read before changing storage substrate, snapshot/query abstractions, or graph projection assumptions. |
| [adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md](adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md) | Graph trust | Canonical graph vs candidate enrichment rules. Read before exposing inferred facts in operational tools or changing default query visibility. |
| [adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md](adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md) | Evidence retrieval | Evidence-packet and coordinate-fetch strategy. Read before changing evidence retrieval, answer packets, or source citation behavior. |
| [adr/0006-canonical-ontology-and-fact-metadata-envelope.md](adr/0006-canonical-ontology-and-fact-metadata-envelope.md) | Ontology | Entity/fact metadata envelope, confidence, coverage policy, partial/refusal behavior, and known local implementation deviations. Read before adding fact types, relation types, or coverage semantics. |
| [adr/0007-deterministic-symbol-lookup-with-agentic-disambiguation.md](adr/0007-deterministic-symbol-lookup-with-agentic-disambiguation.md) | Symbol lookup | Symbol identity and disambiguation policy. Read before changing `lookup_symbol`, callers/callees, or symbol matching behavior. |
| [adr/0008-deterministic-import-normalization-with-agentic-candidate-fallback.md](adr/0008-deterministic-import-normalization-with-agentic-candidate-fallback.md) | Dependency extraction | Import/package normalization and candidate fallback policy. Read before changing package classification, import facts, or dependency queries. |
| [adr/0009-deterministic-reverse-dependency-queries-with-agentic-candidate-enrichment.md](adr/0009-deterministic-reverse-dependency-queries-with-agentic-candidate-enrichment.md) | Dependency queries | Reverse dependency query design. Read before changing `who_imports`, package impact, or dependency path behavior. |
| [adr/0010-deploy-target-without-domain.md](adr/0010-deploy-target-without-domain.md) | Deploy modeling | Deploy target modeling when no domain exists. Read before changing deploy/config extraction or deploy mapping semantics. |
| [adr/0011-python-import-distribution-aliases.md](adr/0011-python-import-distribution-aliases.md) | Python packages | Python import-to-distribution alias policy. Read before changing Python dependency classification. |

## Evaluation And Coverage

| URL | Owner | Annotation |
|---|---|---|
| [docs/evaluation/README.md](docs/evaluation/README.md) | Evaluation | Evaluation directory guide. Read when looking for canonical reports, validation inputs, or product-evaluation docs. |
| [docs/evaluation/PRODUCT-QUERY-SET.md](docs/evaluation/PRODUCT-QUERY-SET.md) | Product evaluation | Product query matrix, MCP tool mapping, goldens, expected answer shapes, and validation scenarios. Read before claiming a feature improves product usefulness or choosing the next evaluated gap. |
| [docs/evaluation/default-v1-fixture-overrides.yaml](docs/evaluation/default-v1-fixture-overrides.yaml) | Product evaluation | Private fixture bindings and extra prompt inputs for the default-v1 A/B eval task slice. Pass via `run_ab_eval --fixture-overrides` when running local private-corpus comparisons. |
| [docs/evaluation/PRODUCT-QUERY-SET-RUN-EXPECTED.json](docs/evaluation/PRODUCT-QUERY-SET-RUN-EXPECTED.json) | Product evaluation | Machine-readable expected outputs for product query runs. Read when updating product-query regression behavior. |
| [docs/evaluation/CANONICAL-VALIDATION-REPORT.md](docs/evaluation/CANONICAL-VALIDATION-REPORT.md) | Product evaluation | Canonical validation report format and interpretation. Read before changing validation-report output or interpreting answer-quality results. |
| [docs/evaluation/ab-runs/main-full-18-post-q016-2026-05-28/ab-report.md](docs/evaluation/ab-runs/main-full-18-post-q016-2026-05-28/ab-report.md) | Product evaluation | Current default-v1 A/B baseline promoted on 2026-05-28: `mcp_on=9`, `mcp_off=7`, `tie=2`, zero MCP denials/errors, and MCP-on resource wins. Read before comparing new A/B runs. |
| [docs/evaluation/review-context-repo-scope-resolution.md](docs/evaluation/review-context-repo-scope-resolution.md) | Product evaluation | Focused PR-review packet audit for owner-qualified repo arguments against single-repo checkout snapshots, with before/after anchor counts for repo-scope resolution. Read before changing `review_context` repo identity handling or deciding PR-review fallback parser scope. |
| [docs/evaluation/review-context-lead-gate.md](docs/evaluation/review-context-lead-gate.md) | Product evaluation | Focused PR-review packet audit for the compact `review_lead_status` / `review_leads` gate, with before/after packet size and low-coverage fallback evidence. Read before changing PR-review packet routing, compact low-coverage behavior, or static packet evaluation. |
| [docs/COVERAGE-METRICS.md](docs/COVERAGE-METRICS.md) | Coverage | User-facing coverage metric definitions and report interpretation. Read before changing coverage report semantics or explaining score movement. |
| [docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md](docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md) | Coverage | Implementation plan for coverage metrics. Read before changing metric computation, dimensions, or generated report contracts. |
| [docs/evaluation/COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md](docs/evaluation/COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md) | Coverage | Notes on incremental coverage and linking gaps. Read when diagnosing why coverage rows/gaps changed. |

## Design Recommendations

| URL | Owner | Annotation |
|---|---|---|
| [docs/ontology/ONTOLOGY-RECOMMENDATION.md](docs/ontology/ONTOLOGY-RECOMMENDATION.md) | Ontology | Recommended graph ontology, coverage sidecar behavior, and deferred families. Read before adding entity kinds, predicates, or coverage policies. |
| [docs/evidence-retrieval/EVIDENCE-RETRIEVAL-RECOMMENDATION.md](docs/evidence-retrieval/EVIDENCE-RETRIEVAL-RECOMMENDATION.md) | Evidence retrieval | Recommended evidence retrieval architecture. Read before changing packets, source snippets, or retrieval ladder behavior. |
| [docs/graph-building/GRAPH-BUILDING-RECOMMENDATION.md](docs/graph-building/GRAPH-BUILDING-RECOMMENDATION.md) | Graph building | Recommended graph build pipeline. Read before changing snapshot build flow, extractors, or relinking architecture. |
| [docs/graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md](docs/graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md) | Extractors | Allowlist for typed client extraction. Read before adding API/client extractor support or changing transport/client recognition. |
| [docs/graph-storage/GRAPH-STORAGE-RECOMMENDATION.md](docs/graph-storage/GRAPH-STORAGE-RECOMMENDATION.md) | Graph storage | Storage recommendation and separation between product APIs and raw graph semantics. Read before changing storage backend assumptions. |
| [docs/agentic-layer/AGENTIC-LAYER-RECOMMENDATION-V2.md](docs/agentic-layer/AGENTIC-LAYER-RECOMMENDATION-V2.md) | Agent runtime | Agentic layer recommendation and MCP as Layer C. Read before changing host-agent, SDK, or no-egress architecture. |
| [docs/overall-architecture/claude-code-research.md](docs/overall-architecture/claude-code-research.md) | Research | Claude Code research notes and MCP consumption assumptions. Read when optimizing for Claude Code as a host. |
| [docs/overall-architecture/codex-code-research.md](docs/overall-architecture/codex-code-research.md) | Research | Codex/code-agent research notes and agentic codebase context strategy. Read when optimizing for Codex-like hosts. |

## Implementation Guides

| URL | Owner | Annotation |
|---|---|---|
| [.codex/skills/implement-debate/SKILL.md](.codex/skills/implement-debate/SKILL.md) | Workflow | Required workflow for implementing converged debates, including PR sequencing, Claude review, Copilot review, merge, and measurement. Read before implementing any debate plan. |
| [.codex/skills/safe-git-pr-workflow/SKILL.md](.codex/skills/safe-git-pr-workflow/SKILL.md) | Workflow | Git and PR workflow for this repo. Read before staging, committing, pushing, opening PRs, or handling GitHub review loops. |
| [.codex/skills/pre-pr-semantic-review/SKILL.md](.codex/skills/pre-pr-semantic-review/SKILL.md) | Review | Semantic self-review checklist focused on extractor, query, loader, coverage, and validation bugs. Read before pushing code changes. |
| [.codex/skills/product-evaluation/SKILL.md](.codex/skills/product-evaluation/SKILL.md) | Evaluation | Product-evaluation workflow and failure buckets. Read before interpreting product-validation results or recommending the next product gap. |
| [.codex/skills/coverage-report/SKILL.md](.codex/skills/coverage-report/SKILL.md) | Coverage | Standard coverage-report workflow. Read before running, comparing, or summarizing KG coverage metrics. |
| [docs/contributing/ADDING-A-NEW-LANGUAGE.md](docs/contributing/ADDING-A-NEW-LANGUAGE.md) | Extractors | Guide for adding a new language. Read before creating language-specific extractors or normalization modules. |

## Channels And External Links

| URL | Owner | Annotation |
|---|---|---|
| Not indexed yet | Project | No Slack, Discord, issue tracker, roadmap board, or external design-doc channels are currently recorded here. Add them with owner and annotation when they become part of normal project context. |

## Maintenance Rule

Update this file when adding a durable document, ADR, debate seed, evaluation artifact, or external project channel that future agents should know about. Do not index generated one-off review files or local run outputs unless they become canonical references.
