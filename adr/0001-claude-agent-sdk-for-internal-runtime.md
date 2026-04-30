# ADR-0001: Use Claude Agent SDK for Internal Agent Runtime (Layers A and B)

- **Status:** Accepted
- **Date:** 2026-04-28
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

SuperContext Product 1 has three distinct agentic layers:

- **Layer A — Ingestion worker.** Per-repo agent that walks the filesystem, orchestrates the bounded v1 extractors selected by the graph ontology / graph-building work, and writes canonical or candidate graph upserts with provenance according to promotion rules.
- **Layer B — Server-side reasoning agent.** PR-bot blast-radius synthesizer plus the budgeted Explorer used for uninstrumented graph coverage, evidence-led queries, conceptual / cross-repo ambiguity, and safety-critical grounding.
- **Layer C — Customer-facing agentic surface.** The IDE host (Claude Code, Cursor, Continue, Cody, Zed, Windsurf, JetBrains AI Assistant, Copilot in VS Code) — see `PRD.md` §6.2.

Layers A and B run server-side under our control. Layer C is whatever the customer uses; we expose MCP (see ADR-0002).

The decision: which agent SDK powers layers A and B? Two production-grade options exist as of 2026: **Claude Agent SDK** (Anthropic) and **OpenAI Agents SDK** (OpenAI).

This decision is needed now because the ingestion worker is the first piece of buildable scope after the graph schema, and it sets the toolchain, hook model, permission model, and audit-log shape that Layer B will inherit.

## Decision

**Use the Claude Agent SDK as the runtime for layers A and B.**

Implementation guardrails:
- Internal runtime only — the public Layer C contract is MCP per ADR-0002 and must remain SDK-agnostic.
- Self-hosted execution — SDK tools run in-process inside the customer's environment.
- Production agents must use narrow tool allowlists by role. Ingestion and evidence paths are read-mostly by default (`Glob`, `Grep`, `Read`); `Edit`, broad `Bash`, and network-capable tools such as `WebFetch` are not part of the default v1 ingestion path.
- Permission mode defaults to `default`; `bypassPermissions` is forbidden in production paths.
- Hooks (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`) are the canonical hook for `last_indexed_at` checks, audit logging, and refusal-on-uninstrumented logic.
- A `SessionStore` adapter is required for the multi-tenant SaaS plane; default JSONL-on-disk persistence is acceptable only for the self-hosted plane.

## V1 scope boundary

This ADR decides the internal agent runtime, not the full extractor catalog.

For Product 1, Layer A may orchestrate only the bounded extractors needed for the accepted v1 graph ontology in ADR-0006 and first design-partner workflows. Examples such as OpenAPI, proto, GraphQL, AsyncAPI, Helm / Kubernetes manifests, Kafka topic normalization, tree-sitter, ast-grep, and Opengrep are eligible extractor families, not commitments that all must ship in v1.

Broad cross-language structural indexing, broad Opengrep flow analysis, and every enterprise integration implied by the platform PRD remain outside this ADR's v1 implementation scope unless a later graph-building ADR explicitly pulls them in.

## Consequences

### Positive
- Built-in `Glob`, `Grep` (ripgrep-backed), `Read`, `Bash`, `Monitor`, and optional tools such as `Edit` / `WebFetch` give us the runtime surface needed across Layers A and B, while production allowlists keep each path narrow. A code-walking agent compiles in ~30 lines vs. writing 4–6 ripgrep wrappers around `subprocess.run` with OpenAI Agents SDK.
- Local-first execution. No customer code uploaded to a hosted vector store or sandbox. Required for `PRD.md` §8's "no code leaves the customer environment in self-hosted mode" promise and for fintech/health ICP qualification.
- Five-mode permission system (`default` / `dontAsk` / `acceptEdits` / `bypassPermissions` / `plan`) plus per-tool allow/deny rules plus a `canUseTool` callback. Maps directly to `PRD.md` §7's "refuse when unsafe" requirement.
- First-class hooks. Native home for the audit and refusal logic the product's trust posture depends on.
- Filesystem-driven config (`.claude/skills/`, `CLAUDE.md`, `.mcp.json`). Customers can ship per-org skill packs without our code changes.
- Subagents with isolated context windows and per-agent MCP scope. Supports per-service exploration in parallel without polluting the main agent's context.
- Same SDK for layers A and B = single toolchain, single auth model, single hook system, single audit-log shape, single ops surface.

### Negative
- Anthropic-model-only on the inference path (Bedrock / Vertex / Foundry are supported, but the model is Claude). If a customer mandates non-Claude models for internal reasoning, the swap cost to OpenAI Agents SDK is approximately one week (functional parity on MCP consumption + custom-tool wrap, minus the built-in code-search primitives, which we'd reimplement as `@function_tool` ripgrep wrappers).
- Tracing UI is not first-class; observability is built via hooks. OpenAI Agents SDK ships a more polished tracing UI out of the box.
- Default session backend is JSONL on disk. The multi-tenant SaaS plane needs a custom `SessionStore` adapter; OpenAI Agents SDK ships SQLite/Redis/Mongo/SQLAlchemy/Dapr/Encrypted variants.

### Neutral
- MCP consumption depth (stdio + streamable HTTP + SSE, runtime schema fetch, multi-server, lazy-load) is at parity with OpenAI Agents SDK. The MCP layer — the actual moat per ADR-0002 — works identically either way.

## Alternatives considered

**OpenAI Agents SDK** — rejected. Strongest hosted tools (`FileSearchTool`, `CodeInterpreterTool`, `HostedMCPTool`, `WebSearchTool`) are server-side and bill per call; using them in Layer A would ship customer code to OpenAI Vector Stores, violating `PRD.md` §8's no-egress posture and disqualifying us from regulated-buyer ICPs. For Layer B, functional parity exists but no positive differentiator over Claude Agent SDK, and operational simplicity (one SDK across A+B) tilts the call toward Claude.

**Pure agent-over-local-files (no SDK)** — rejected. Per `overall-architecture/codex-code-research.md` §7 Recommendation 3: weak moat, harder permissioning, harder central audit, doesn't scale across multiple repos and tenants without rebuilding orchestration we'd otherwise get for free.

**Build custom orchestration on raw Anthropic / OpenAI model APIs** — rejected. Loses MCP integration, hooks, permission modes, and session resume/fork. Months of plumbing work to recreate what either SDK gives us in days.

**Embeddings-first retrieval with no agentic SDK** — rejected as architecture-level direction; see `overall-architecture/claude-code-research.md` §5 (industry has moved away — Cody deprecated embeddings, Anthropic dropped RAG, Bloop archived), `overall-architecture/codex-code-research.md` §7 Recommendation 2, ADR-0004 (canonical graph plus candidate / enrichment sidecar), and ADR-0005 (modular evidence retrieval with coordinate fetch and selective ladder).

## References

- `PRD.md` §3 (vision), §6.2 (MCP server surface), §6.3 (PR bot), §7 (UX principles — refusal, provenance), §8 (architecture, no-egress posture), §13 (risks: MCP fork mitigation)
- `overall-architecture/claude-code-research.md` §3 (OSS code-search landscape), §4 (Claude Agent SDK detail — hooks, subagents, MCP, permissions), §7 (Product 1 architecture diagram showing layers A/B/C), §8 (open questions)
- `overall-architecture/codex-code-research.md` §4 (Claude Agent SDK assessment — strong orchestration, weak as sole retrieval substrate), §7 Recommendation 3 (do not ship pure agent-over-local-files), §8 Layer 4 (agentic interface), §11 (final architectural posture)
- `agentic-layer/AGENTIC-LAYER-RECOMMENDATION-V2.md` §3 (Claude vs OpenAI SDK side-by-side comparison), §4 (why V2 differs from v0.1), §5 (skills resolution), §6 (operational implications), §7 (swap clause)
- `agentic-layer/AGENTIC-LAYER-RECOMMENDATION.md` v0.1 (Codex, 2026-04-27, superseded — preserved for attribution; alternatives weighing that V2 rebalances)
- `agentic-layer/AGENTIC-SKILLS-NOTE.md` v0.1 (2026-04-27, deferred question now resolved in V2 §5)
- `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
