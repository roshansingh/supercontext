# SuperContext Backlog

Status: living index of deferred work and open follow-ups across the project.
Last updated: 2026-05-01.

This file is the single place to scan "what's deferred and why." Per-ADR open-follow-up sections are the authoritative source; this is the index. Refresh when ADRs change.

Format: `Item | Source | Trigger to revisit`.

---

## Next ADRs (priority order per TECHNICAL-BUILDING-BLOCKS.md)

| Item | Source | Trigger to revisit |
|---|---|---|
| Tool Query Contract ADR — semantics for the 8 MCP tools, partial coverage rules, pagination, refusal metadata | TECHNICAL-BUILDING-BLOCKS.md "Next ADR Candidates" | Before Source Connector ADR; needed to drive what facts the engine must serve |
| Source Connector + Extractor ADR — exact v1 inputs, parser stack, typed-client allowlist ownership | TECHNICAL-BUILDING-BLOCKS.md | After Tool Query Contract ADR locks the fact requirements |
| Deployment / Auth / Tenancy ADR — SaaS vs self-hosted boundary, tenant isolation, SSO/SCIM, secrets, audit | TECHNICAL-BUILDING-BLOCKS.md | Parallel to Source Connector ADR |
| Testing / Evaluation ADR — golden graphs, evidence replay, graph/evidence merge tests, p95 benchmarks | TECHNICAL-BUILDING-BLOCKS.md | After Tool Query Contract ADR locks the semantics to test against |
| AGE Projection / Materialization Runtime ADR — projection cadence, incremental vs full rebuild, bulk-write strategy | TECHNICAL-BUILDING-BLOCKS.md | Before scale benchmarks force the choice |

## Implementation discipline (cross-cutting)

| Item | Source | Trigger to revisit |
|---|---|---|
| Loud refusal at ingestion — when Layer A encounters a source scope with no allowlisted extractor, emit `coverage` row with `state='uninstrumented'` for the extractor's declared scope, such as repo, service, language/framework, or path prefix. Never silent-skip | This document, design discussion 2026-05-01 | Land as a hard rule in Source Connector + Extractor ADR |
| `.supercontext/config.json` per-repo customer steering (identity overrides, manual relations, coverage hints, deferred-extractor opt-out) | claude-deepwiki-analysis.md §3 | Source Connector + Extractor ADR |
| Typed-client allowlist seeding — pick first design partner's stack, allowlist their typed clients (TS/JS, Go, Java/Kotlin per PRD) | TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md "Initial Entries" | When first design partner signed |
| MCP install one-liner pattern documented (mirror `claude mcp add -s user -t http supercontext https://...`) | claude-deepwiki-analysis.md §2 | Tool Query Contract ADR or MCP install docs |
| Mermaid in PR-bot blast-radius comments | claude-deepwiki-analysis.md §7 | Future PR-bot ADR |
| Move private validation fixtures out of product source — `source/kg/product/validation_report.py` and `scenario_plans.py` currently include private corpus strings such as `api.shopagain.io`, `/api/token`, `la-prod-email`, `la-prod-campaign-messages`, `prod_shopagain_wsgi.py`, `mercury_api`, and `mercury_campaign_messages`; replace in-tree defaults with a public reference corpus and keep private checks under `examples/private-goldset/` | SOURCE-OSS-READINESS-PLAN.md PR-A; PR-18/PR-19 reviews | Before OSS publication or before adding more private smoke checks |
| Classify KG coverage rows currently captured as `unknown` in count baselines by adding `scope_ref.reason` at emission sites and regenerating `tests/baselines/kg_counts/*.json` | Debate 8 PR-0 baseline review | Before treating T2 count-baseline drift as a strict OSS-readiness gate |
| Per-repo import-root metadata resolution — Python import normalization currently reads `importlib.metadata.packages_distributions()` from the runner environment, not the target repo's venv/lockfile; Node builtin normalization reads the runner `node` on `PATH` plus fallback inventory | Debate 8 PR-C review | Before hosted analysis claims target-repo environment fidelity |
| Namespace-package subpath ownership for Python imports — `google.*` style namespace packages fail closed when multiple declared distributions share one import root; resolve with package file metadata or target-env module ownership | Debate 8 PR-C review | When namespace package imports become product-critical |
| Physical Python / TypeScript extractor moves into `source/kg/languages/<language>/` — wrappers now make language ownership clear, but existing modules still live under `source/kg/extraction/{python,typescript}/`; only move after import/path adjacency checks, especially TypeScript parser bridge assets | Debate 15 Post-P5 | When language-package adjacency simplification justifies a moved-files PR; gate on parser-bridge sibling lookup, legacy adapter import, packaging-data, and wrapper-compatibility checks |
| File-format extractor split — config adapters such as OpenAPI, Serverless, Terraform, dotenv, Apache vhost, and package manifests are still under extraction/config or central adapters rather than an explicit file-format layer | Debate 15 Post-P5 | When adding another non-language config/IaC extractor would otherwise blur language vs file-format ownership |
| Delete language compatibility shims — `RepoSnapshot.python_files` / `typescript_files` and `ExtractionContext.python_*` / `js_ts_*` properties remain for legacy callers such as `source/kg/extraction/python/ast_extractor.py`, `source/kg/extraction/typescript/parser_bridge.py`, and compatibility tests | Debate 15 Post-P5 | After `rg` shows no production or test callers of legacy fields/functions and a dedicated removal PR updates baselines/docs |

## Per-ADR open follow-ups

### ADR-0003 (Postgres + AGE storage)

| Item | Trigger to revisit |
|---|---|
| AGE bulk-edge-insert performance benchmark on 500-service / 100k-edge fixture | Before first design-partner load test |
| AGE 4-hop blast_radius p95 < 500 ms validation | Before first design-partner load test |
| openCypher coverage gap audit (AGE vs Neo4j) for our 8 tools | Before locking Tool Query Contract ADR |
| AGE upgrade story (1.5 → 1.7), PG 18 + AGE 1.7 production fitness | Before any version upgrade |
| Dgraph ownership stability post-Istari acquisition | Q3 2026 review |
| Bitemporal modeling depth — `valid_from`/`valid_to` columns vs XTDB swap | When `oncall_context_for(since=1h)`-style tools become hot |

### ADR-0005 (Evidence retrieval)

| Item | Trigger to revisit |
|---|---|
| ripgrep p95 benchmark across multi-repo enterprise fixtures | Before deciding Zoekt adapter timing |
| First Zoekt adapter boundary definition | When ripgrep p95 fails at target scale |
| Targeted ast-grep / tree-sitter framework patterns for first design partner | When first design partner signed |
| Default agentic exploration budgets from measured latency / token data (DeepWiki uses a 5-iteration ceiling as one data point) | After first instrumented design-partner runs; DeepWiki's 5-iteration ceiling is input data, not a binding default |
| Semble future fuzzy-search research | Phase 2+ if alias / discovery gap forces it |

### ADR-0006 (Ontology)

| Item | Trigger to revisit |
|---|---|
| Per-relation runtime freshness window defaults — currently 10/14/30 days, expect adjustment | After first design partner trace-data cadence known |
| Probabilistic entity resolution (Splink) for alias reconciliation | Phase 2+ when deterministic Alias table conflicts grow |
| Conflict-resolution policy when two evidence rows assert mutually exclusive mappings (beyond `manual_override` + candidate status) | When such conflicts surface in production |
| Schema compatibility policy (BACKWARD/FORWARD/FULL/transitive) for `EVOLVES_TO` lineage | When schema-evolution campaigns become a Product 1 feature, likely Phase 2 |
| Code-level entity types (`CodeModule`, `CodeSymbol`, `ExternalPackage`) status — promote to canonical (10 → 13 nodes), keep candidate-only enrichment, or model as a sub-layer below the canonical 10 | When multi-language extraction beyond Python AST forces a consistent decision |
| `IMPORTS` relation status — add to canonical 15, keep code-layer-only, or treat as candidate enrichment | Same trigger as code-level entity types |
| `CALLS` grain roll-up rule — function-level (`CodeSymbol → CodeSymbol`) vs operation-level (`Service → Endpoint`); how to aggregate for multi-service blast_radius | When ingestion crosses repo boundaries and cross-service `find_callers` is needed |
| URN human-readable scheme (ADR-0006 §3) not yet honored — v0 uses `supercontext://{kind}/{stable_hash}` for all kinds | Before MCP / UI surfaces ship |
| Evidence-level `valid_from` / `valid_to` columns missing in v0 | When bitemporal or freshness-window queries land |
| Promotion rules not enforced in v0 (all entities/facts default canonical) | When multi-source or `inferred_llm` evidence enters the pipeline |
| Coverage row shape simplified in v0 (missing `subject_id`, `last_seen_at`, `window_start`, `window_end`) | When Tool Query Contract ADR locks coverage semantics |
| v0 storage is JSONL, not Postgres + AGE (ADR-0003) | When multi-tenant or query-volume requirements force the migration |
| v0 ingestion is Python-only; loud-refusal-at-ingestion not wired | When second language enters the extractor catalog |

## Phase 2 / 3 candidates

| Item | Phase | Source |
|---|---|---|
| Cross-tenant federation for cross-org service graphs (post-merger transitional + permanently federated subsidiaries) | Phase 3 | PLATFORM-PRD.md §11; ONTOLOGY-RECOMMENDATION.md §11 |
| `get_service_wiki(service_id)` MCP tool generating DeepWiki-style narrative from typed graph + evidence | Phase 2/3 | claude-deepwiki-analysis.md §6 |
| Free hosted MCP for OSS repos as viral acquisition channel (mirror DeepWiki's `mcp.deepwiki.com` model) | GTM strategy, not technical | claude-deepwiki-analysis.md §5 |
| GraphRAG-style enrichment in candidate / sidecar layer (prose / docs / runbooks / incidents) | Phase 2+ | ADR-0004 candidate / enrichment sidecar |
| SCIP / language-indexer integration for symbol-level evidence | Phase 2+ | ADR-0005 §"Explicitly out of v1" |
| Database / FeatureFlag node types | Phase 2+ | ONTOLOGY-RECOMMENDATION.md §8 deferred families |
| Document / Ticket / Decision / Runbook / Incident / File node types | Phase 3 | ONTOLOGY-RECOMMENDATION.md §8 |
| GATES / MIGRATES_WITH / SHARES_DB_WITH / IMPACTED_BY relations | Phase 2+ | ONTOLOGY-RECOMMENDATION.md §8 |

## Open product / strategy questions

| Item | Source | Owner |
|---|---|---|
| Naming finalization — `SuperContext` vs `BetterContext` vs other | PRD.md §14 #1 | Roshan |
| First-language priority — TS/JS, Go, or Java/Kotlin (drives extractor allowlist seeding) | PRD.md §14 #2 | First design partner |
| Tracing source for MVP — Datadog vs Tempo vs Jaeger (or all three) | PRD.md §14 #3 | First design partner |
| Pricing model — per-seat vs per-service vs platform-team flat fee | PRD.md §14 #4 | After 2 design partners |
| Self-host vs SaaS-first | PRD.md §14 #5 | Strategic call |
| Buyer entry point — platform team vs single feature team | PRD.md §14 #6 | GTM motion |
| Training-data policy — pre-commit "no model training on customer code" or stay flexible | PRD.md §14 #7 | Legal + GTM |

---

## How to use this file

- **Adding an item:** include source ADR/doc + the trigger condition that should bring it back into scope.
- **Closing an item:** delete the row. The originating ADR's open-follow-up section is the audit trail.
- **Refreshing:** every time an ADR is updated or a new debate converges, sync this file. Drift is the failure mode.
- **Not in scope:** day-to-day implementation tasks, bugs, sprint planning. This is for decisions and capabilities deferred at the architectural level.
