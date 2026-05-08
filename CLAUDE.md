# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**SuperContext** (working name; directory is `bettercontext`) — Product 1 is a typed cross-service knowledge graph for AI coding agents in microservice organizations. The product wedge is change-safety: when an agent edits service A, SuperContext tells it which services B–Z will break before the diff is written.

Two layers exist concurrently:

- **Architecture (`docs/`, `adr/`, `BACKLOG.md`)** — fully specified. Nine accepted ADRs, multiple research notes, an ontology recommendation, and a 55-query acceptance corpus.
- **Implementation (`source/`)** — early v0 slice. JSONL local KG harness for Python and TypeScript repos. No Postgres/AGE, no MCP server, no PR bot yet.

The architecture is ahead of the implementation by design. Work on either side, but treat ADRs as binding spec when implementing.

## Commands

No `pyproject.toml`, `Makefile`, or test runner is configured at root. v0 ships as bare Python scripts.

```bash
# Build a KG snapshot from a Python or TS/JS repo
python -m source.scripts.build_kg --repo <path-to-repo> --out data/kg_runs/<name>

# Query the snapshot
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> summary
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> find-callers <symbol> --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> modules-importing <package> --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> top-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> dependency-info <package>
python -m source.scripts.query_kg --snapshot data/kg_runs/<name> blast-radius <symbol> --depth 2
```

Snapshots write `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json` under the `--out` directory.

LLM enrichment is not part of the default v0 path. If used: `source.kg.llm.LightLlmClient` reads `OPENAI_API_KEY`, defaults to `gpt-4.1-mini`, override with `SUPERCONTEXT_LLM_MODEL`.

## Repository layout

| Path | Purpose |
|---|---|
| `docs/PRD.md`, `docs/PLATFORM-PRD.md` | Product vision (Product 1 wedge + broader platform) |
| `adr/0001..0009` | Accepted architecture decisions; binding spec for implementation |
| `docs/ontology/ONTOLOGY-RECOMMENDATION.md` | The v1 canonical ontology (10 nodes, 15 relations, Entity+Fact+Evidence+Coverage shape, identity tuples, derivation classes, promotion rules) — ADR-0006 binding |
| `docs/evaluation/PRODUCT-QUERY-SET.md` | 55-query acceptance corpus mapped to MCP tools, with goldens for Low tier and contract checks |
| `docs/overall-architecture/TECHNICAL-BUILDING-BLOCKS.md` | Implementation map, ADR coverage, next-ADR priority |
| `docs/graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md` | Registry for high-precision call-site extractors that auto-promote `CALLS` facts |
| `BACKLOG.md` | Single-page index of every deferred item across the project |
| `source/kg/extraction/{python,typescript}/` | Per-language deterministic extractors |
| `source/kg/normalization/{python,typescript}/` | Per-language import normalizers |
| `source/kg/{models,store,queries,pipeline,repo_source,llm}.py` | Core data classes, JSONL store, query layer, pipeline orchestration, optional LLM client |
| `source/scripts/{build_kg,query_kg}.py` | CLI entry points |
| `data/kg_runs/` | Gitignored KG snapshots |
| `debates/` | Gitignored multi-agent debate transcripts (orchestrator at `~/.agent-debate/orchestrate.sh`) |

## Architecture (the load-bearing decisions)

Read ADRs in order; each builds on the prior. Key shape:

- **ADR-0001** — Internal runtime is **Claude Agent SDK** for both ingestion (Layer A) and server-side reasoning (Layer B). Layer C is whatever IDE the customer uses.
- **ADR-0002** — Public protocol is **MCP** with eight tools (`search_services`, `get_service_brief`, `find_callers`, `find_callees`, `get_event_consumers`, `get_event_producers`, `blast_radius`, `deploy_blockers_for`). Streamable HTTP, OAuth 2.1.
- **ADR-0003** — Storage is **PostgreSQL + Apache AGE**. Postgres tables = source of truth; AGE = projection.
- **ADR-0004** — Two-tier graph: **canonical** (high-trust, deterministic / authoritative) + **candidate sidecar** (LLM-inferred, prose-derived, ambiguous).
- **ADR-0005** — Evidence retrieval = **Mode A** (commit-pinned bytes via `go-git`/`pygit2`, always-on for surfaced facts) + **Mode B** (selective ladder: ripgrep → ast-grep → Claude Explorer subagent).
- **ADR-0006** — Ontology is **10 node types + 15 relation types**, all tenant-scoped. Storage shape: `entities` + `facts` (with optional `qualifier` for role-bearing relations) + `evidence` (PROV-O qualified pattern, polymorphic to entity or fact, carries `valid_from`/`valid_to`) + `coverage` sidecar. Five derivation classes form a tier: `authoritative_declared` > `manual_override` > `deterministic_static` > `runtime_observed` > `inferred_llm`. Per-edge promotion rules gate `candidate → canonical`.
- **ADR-0007/0008/0009** — Deterministic-first symbol lookup, import normalization, and reverse-dependency queries with agentic disambiguation/candidate fallback.

## v0 Implementation Status (read before editing `source/`)

`source/` ships ahead of full ADR-0006 conformance. Known divergences (full list in `adr/0006-canonical-ontology-and-fact-metadata-envelope.md` §"Implementation Status" and `BACKLOG.md`):

- Storage = JSONL, not Postgres + AGE.
- Single hardcoded `tenant_id="local-dev"`.
- v0 introduces extra-canonical entity types (`CodeModule`, `CodeSymbol`, `ExternalPackage`) and the `IMPORTS` relation. Not yet in the canonical 10/15. Status pending.
- `CALLS` grain in v0 is `CodeSymbol → CodeSymbol` (function-level, intra-repo), not `Service → Endpoint` (the binding spec).
- URN scheme uses opaque hash for all kinds; ADR-0006 §3 specifies per-kind human-readable URNs for most kinds.
- Evidence rows omit `valid_from`/`valid_to`.
- Promotion rules not enforced (everything defaults `canonical_status='canonical'`).
- Coverage row shape simplified.
- Polyglot ingestion limited to Python + TS/JS; loud-refusal-at-ingestion not wired.

When extending v0, prefer closing one of these gaps over adding new capability.

## Repo conventions

- **Research notes pattern.** Each major topic gets two parallel notes (`claude-<topic>-research.md` + `codex-<topic>-research.md`) under its own folder in `docs/`. They feed a debate (under `debates/`, gitignored), which converges into a single `<TOPIC>-RECOMMENDATION.md` and a binding ADR. Don't write a single research note when prior topics had two.
- **ADRs are numbered monotonically** and marked `Status: Accepted` on land. Cross-reference earlier ADRs when superseding details.
- **`BACKLOG.md` is the single tracked-deferrals index.** Every ADR has its own "Open follow-ups" section as the audit trail; BACKLOG.md is the searchable view across all of them. Add a row when deferring; remove a row when closing. Drift is the failure mode.
- **`docs/evaluation/PRODUCT-QUERY-SET.md` is the acceptance corpus.** Every query has a difficulty, a tool/surface mapping, a fixture variable (so Mercury-ML specifics don't leak), an expected answer shape, and a grading rubric. Run queries, record `pass`/`partial`/`fail`/`refused correctly`, use gaps to choose the next implementation slice.
- **Loud refusal at ingestion.** When extraction encounters a language/framework with no allowlisted extractor, emit a `coverage` row with `state='uninstrumented'` and the scope (`{repo, language, path_prefix}`) — never silent-skip. Preserves the refusal-on-uninstrumented contract from PRD §7. Tracked in BACKLOG.md.
- **Code-backed evidence MUST carry `bytes_ref = {repo, commit_sha, path, line_start, line_end}`** so ADR-0005 Mode A can verify the cited bytes.

## Personal guidance for assistant edits

- Don't auto-create ADRs after a debate converges. Prior pattern: write `<TOPIC>-RECOMMENDATION.md` only when explicitly asked; user opens the ADR.
- Multi-agent debates run via `~/.agent-debate/orchestrate.sh`. Host (Claude) writes its R1 turn directly in the debate file; orchestrator handles Codex rounds. See `~/.claude/agent-debate/agent-guardrails.md` for the editing conventions.
- Edits to `source/` should match v0 minimalism — small Python modules, `from __future__ import annotations`, frozen dataclasses for the Entity/Fact/Evidence/Coverage models, JSONL via the existing `JsonlKgStore`. No new frameworks or test runners without explicit ask.
