# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**SuperContext** — Product 1 is a typed cross-service knowledge graph for AI coding agents in microservice organizations. The product wedge is change-safety: when an agent edits service A, SuperContext tells it which services B–Z will break before the diff is written.

Two layers exist concurrently:

- **Architecture (`docs/`, `adr/`, `BACKLOG.md`)** — accepted direction plus explicit implementation status. Eleven accepted ADRs, multiple research notes, an ontology recommendation, and a 55-query acceptance corpus.
- **Implementation (`source/`)** — early local slice. JSONL local KG harness for Python and TypeScript repos. No Postgres/AGE or PR bot yet; a local read-only MCP server exists for development.

The architecture is ahead of the implementation by design. Work on either side, but read `adr/README.md` first for the current local-pilot status before treating a platform-target ADR as an immediate implementation requirement.

## Project context index

Use `INDEX.md` as the canonical annotated map of project docs, ADRs, debate seeds, evaluation artifacts, and external channels. When project documentation is needed, read `INDEX.md` first and then open only the relevant indexed documents. Do not maintain duplicate doc inventories here; update `INDEX.md` instead.

## Commands

`pyproject.toml` defines package metadata, optional dependency groups, and console-script entry points. The default verification path is still direct Python module execution:

```bash
# Verify syntax and tests
python -m compileall -q source tests
python -m unittest discover -s tests

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

## Coverage metrics and reports

Use the deterministic coverage pipeline for repo or fleet coverage questions; do not hand-summarize KG coverage from ad hoc file inspection. Claude should use the project-local coverage-report skill when asked to run, summarize, compare, or interpret coverage metrics, but the CLI outputs remain the source of truth.

Build or refresh the snapshot first:

```bash
python -m source.scripts.build_kg --repo <repo-path> --out <snapshot-dir>
python -m source.scripts.build_multi_kg --repo <repo-1> --repo <repo-2> --out <snapshot-dir>
```

Then compute metrics and render the standard report:

```bash
python -m source.scripts.coverage_metrics --snapshot <snapshot-dir> --expected-repos <N>
python -m source.scripts.coverage_report \
  --snapshot <snapshot-dir> \
  --out docs/evaluation/runs/<run-id> \
  --run-id <run-id> \
  --tenant <tenant-or-org> \
  --expected-repos <N> \
  --metric-config source/kg/metrics/config.yaml
```

`coverage_metrics` writes `<snapshot-dir>/metrics.jsonl`. `coverage_report` writes `coverage-run.json` and `coverage-run.md` under `docs/evaluation/runs/<run-id>/`. Treat all three as generated artifacts: never hand-edit metric values, reasons, scores, or contract flags. For fleet reports, pass a stable `--run-id`, the tenant/org label, and `--expected-repos` whenever the expected repo count is known.

LLM enrichment is not part of the default KG build path. If used: `source.kg.integrations.llm.LightLlmClient` reads `OPENAI_API_KEY`, defaults to `gpt-4.1-mini`, override with `SUPERCONTEXT_LLM_MODEL`.

## Architecture (the load-bearing decisions)

Read `adr/README.md` first for the local-pilot status of each decision, then open the specific ADRs you need. Key shape:

- **ADR-0001** — Accepted direction: internal Layer A/B runtime uses **Claude Agent SDK**. Current local-pilot reality: the default KG builder is deterministic and in-process; Claude Agent SDK use is limited to bounded natural-language KG sessions, answer synthesis, and evaluation helpers.
- **ADR-0002** — Accepted direction: public protocol is **MCP** with eight tools (`search_services`, `get_service_brief`, `find_callers`, `find_callees`, `get_event_consumers`, `get_event_producers`, `blast_radius`, `deploy_blockers_for`). Current local-pilot reality: local read-only MCP exists; streamable HTTP, OAuth 2.1, and final hosted contracts are pending.
- **ADR-0003** — Accepted platform direction: storage is **PostgreSQL + Apache AGE**. Current local-pilot reality: runnable snapshots are JSONL behind `KgSnapshot`; Postgres/AGE is not required to use or test the pilot.
- **ADR-0004** — Two-tier graph: **canonical** (high-trust, deterministic / authoritative) + **candidate sidecar** (LLM-inferred, prose-derived, ambiguous).
- **ADR-0005** — Evidence retrieval = **Mode A** (commit-pinned bytes via `go-git`/`pygit2`, always-on for surfaced facts) + **Mode B** (selective ladder: ripgrep → ast-grep → Claude Explorer subagent).
- **ADR-0006** — Ontology is **10 node types + 15 relation types**, all tenant-scoped. Storage shape: `entities` + `facts` (with optional `qualifier` for role-bearing relations) + `evidence` (PROV-O qualified pattern, polymorphic to entity or fact, carries `valid_from`/`valid_to`) + `coverage` sidecar. Five derivation classes form a tier: `authoritative_declared` > `manual_override` > `deterministic_static` > `runtime_observed` > `inferred_llm`. Per-edge promotion rules gate `candidate → canonical`.
- **ADR-0007/0008/0009** — Deterministic-first symbol lookup, import normalization, and reverse-dependency queries with agentic disambiguation/candidate fallback.

## Implementation Status (read before editing `source/`)

`source/` ships ahead of full ADR-0006 conformance. Known divergences (full list in `adr/0006-canonical-ontology-and-fact-metadata-envelope.md` §"Implementation Status" and `BACKLOG.md`):

- Storage = JSONL, not Postgres + AGE.
- Tenant IDs resolve from explicit CLI/config input, then `SUPERCONTEXT_TENANT_ID`, then default to `"default"`; full multi-tenant isolation is not implemented.
- Current extractors introduce extra-canonical entity types (`CodeModule`, `CodeSymbol`, `ExternalPackage`) and the `IMPORTS` relation. Not yet in the canonical 10/15. Status pending.
- `CALLS` grain in the current implementation is `CodeSymbol → CodeSymbol` (function-level, intra-repo), not `Service → Endpoint` (the binding spec).
- URN scheme uses opaque hash for all kinds; ADR-0006 §3 specifies per-kind human-readable URNs for most kinds.
- Evidence rows omit `valid_from`/`valid_to`.
- Promotion rules not enforced (everything defaults `canonical_status='canonical'`).
- Coverage row shape simplified.
- Polyglot ingestion limited to Python + TS/JS. Loud-refusal-at-ingestion is wired for inventoried no-extractor source languages and known stacks (the build emits `LANGUAGE_SUPPORT`/`state='uninstrumented'` coverage rows in `source/kg/extraction/framework/runner.py`), and these surface at query time via `planning_context`, `get_service_brief`, and the symbol tools; it is not yet wired for arbitrary unknown extensions. See BACKLOG.md.

When extending `source/`, prefer closing one of these gaps over adding new capability.

## MCP head-start and budgeting

SuperContext MCP tools are a head start for the agent, not a replacement for source inspection and not a mandate to return everything. A good packet should tell the agent what is already covered by KG-backed evidence and where to inspect next.

Use **Head-Start Budgeting** when a composed MCP packet would exceed useful output size:

- Return complete relevant evidence when it fits comfortably.
- When it does not fit, keep the highest-signal evidence rows with concrete coordinates.
- Preserve total and omitted counts, but never rely on counts alone.
- Convert omitted but relevant rows into `inspection_areas` with `repo`, `path`, `line`, `symbol`/`qualname`, endpoint/domain/event-channel context, and search terms when available.
- Use remaining budget to backfill useful rows or details instead of returning an unnecessarily tiny compact packet.
- Keep `known_linked`, `candidate_or_unlinked`, and `missing_or_unknown` evidence separate. Do not let truncation imply absence.

When fixing eval failures, avoid packet churn that only helps one question. Ask whether the change makes SuperContext stronger for similar OSS repositories and adjacent workflows. Prefer extraction/linking or deterministic retrieval fixes over adding more prompt prose.

## Repo conventions

- **Research notes pattern.** Each major topic gets two parallel notes (`claude-<topic>-research.md` + `codex-<topic>-research.md`) under its own folder in `docs/`. They feed a debate (under `debates/`, gitignored), which converges into a single `<TOPIC>-RECOMMENDATION.md` and a binding ADR. Don't write a single research note when prior topics had two.
- **ADRs are numbered monotonically** and marked `Status: Accepted` on land. Cross-reference earlier ADRs when superseding details.
- **`BACKLOG.md` is the single tracked-deferrals index.** Every ADR has its own "Open follow-ups" section as the audit trail; BACKLOG.md is the searchable view across all of them. Add a row when deferring; remove a row when closing. Drift is the failure mode.
- **`docs/evaluation/PRODUCT-QUERY-SET.md` is the acceptance corpus.** Every query has a difficulty, a tool/surface mapping, a fixture variable (so Mercury-ML specifics don't leak), an expected answer shape, and a grading rubric. Run queries, record `pass`/`partial`/`fail`/`refused correctly`, use gaps to choose the next implementation slice.
- **Extractor evidence must be repo-general.** Do not hardcode repo names, service names, package names, product-domain terms, path fragments, or fixture variables to make a query pass. Prefer parser/AST/compiler/config-schema evidence over keyword heuristics for semantic facts, and cover new extractor behavior with positive and negative fixtures that prove the rule is not tuned to one repo.
- **Loud refusal at ingestion.** When extraction encounters a language/framework with no allowlisted extractor, emit a `coverage` row with `state='uninstrumented'` and the scope (`{repo, language, path_prefix}`) — never silent-skip. Preserves the refusal-on-uninstrumented contract from PRD §7. Tracked in BACKLOG.md.
- **Code-backed evidence MUST carry `bytes_ref = {repo, commit_sha, path, line_start, line_end}`** so ADR-0005 Mode A can verify the cited bytes.

## Personal guidance for assistant edits

- Don't auto-create ADRs after a debate converges. Prior pattern: write `<TOPIC>-RECOMMENDATION.md` only when explicitly asked; user opens the ADR.
- Multi-agent debates run via `~/.agent-debate/orchestrate.sh`. Host (Claude) writes its R1 turn directly in the debate file; orchestrator handles Codex rounds. See `~/.claude/agent-debate/agent-guardrails.md` for the editing conventions.
- Edits to `source/` should match the current minimalism — small Python modules, `from __future__ import annotations`, frozen dataclasses for the Entity/Fact/Evidence/Coverage models, JSONL via the existing `JsonlKgStore`. No new frameworks or test runners without explicit ask.
