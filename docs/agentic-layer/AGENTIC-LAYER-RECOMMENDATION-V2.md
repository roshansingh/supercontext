# Agentic Layer Recommendation for Product 1 (V2)

- **Status:** Accepted
- **Date:** 2026-04-28
- **Authors:** Roshan Singh, Maruti Agarwal
- **Supersedes:** earlier v0.1 Codex recommendation (2026-04-27) for OpenAI Agents SDK and a 2026-04-27 skills-question note, both removed after this V2 became the binding record.
- **Anchors:** `adr/0001-claude-agent-sdk-for-internal-runtime.md`

---

## 1. Three layers, not one decision

Product 1 has three distinct agentic surfaces. Conflating them caused the v0.1 recommendation to land in the wrong place; this V2 separates them and decides each on its own merits.

- **Layer A — Ingestion worker.** Per-repo agent that walks the filesystem, parses contracts (OpenAPI / proto / GraphQL / AsyncAPI), runs structural pattern matchers (tree-sitter + Opengrep) for typed-client call sites, parses Helm/k8s manifests, normalizes Kafka topic names, and writes typed graph upserts with provenance.
- **Layer B — Server-side reasoning agent.** PR-bot blast-radius synthesizer plus the agentic-fallback explorer that runs when the graph returns "uninstrumented" for a queried edge.
- **Layer C — Customer-facing agentic surface.** The IDE host (Claude Code, Cursor, Continue, Cody, Zed, Windsurf, JetBrains AI Assistant, Copilot in VS Code), per `PRD.md` §6.2.

Layers A and B run server-side under our control. Layer C is whatever the customer uses; we expose MCP per ADR-0002.

## 2. Decision

| Layer | Runtime | Rationale |
|---|---|---|
| **A — Ingestion worker** | Claude Agent SDK | Built-in code-search primitives + local-first execution + filesystem skill packs |
| **B — Server-side reasoning** | Claude Agent SDK | Operational simplicity (one SDK across A+B) + hooks for refusal-on-uninstrumented + same audit-log shape |
| **C — Customer-facing surface** | MCP protocol, SDK-agnostic on the consumer side | One server reaches all eight host IDEs in `PRD.md` §6.2; do not couple the public contract to any SDK |

Captured formally in `adr/0001-claude-agent-sdk-for-internal-runtime.md` (layers A+B) and `adr/0002-mcp-protocol-for-external-surface.md` (layer C).

## 3. SDK comparison — Claude Agent SDK vs OpenAI Agents SDK

The comparison driving the layers A+B decision. `✓` = ships built-in. `H` = ships, but **hosted** (server-side, billed per call). `⚠` = available via integration / requires user-supplied implementation. `✗` = not provided.

| Capability | Claude Agent SDK | OpenAI Agents SDK |
|---|---|---|
| Read file | `✓ Read` (local) | `⚠` via `@function_tool` or `ApplyPatchTool` |
| Write / Edit file | `✓ Write` / `✓ Edit` (local) | `⚠` via `ApplyPatchTool` (user supplies editor) |
| Shell / Bash | `✓ Bash` (local) | `✓ ShellTool` (local) **or** `H` hosted container |
| Glob (filename pattern) | `✓ Glob` (local) | `✗` |
| Grep (content regex) | `✓ Grep` (local, ripgrep-backed) | `✗` |
| Streaming script output | `✓ Monitor` | `⚠` user-built |
| Web search | `✓ WebSearch` | `H WebSearchTool` (per-call) |
| Web fetch | `✓ WebFetch` | `✗` (do via function tool) |
| Code interpreter / Python sandbox | `✗` (use Bash) | `H CodeInterpreterTool` (hosted) |
| File search / vector store | `✗` | `H FileSearchTool` (OpenAI Vector Stores) |
| Computer use / browser | `⚠` via Playwright MCP | `⚠ ComputerTool` |
| Image generation | `✗` | `H ImageGenerationTool` |
| Subagents / handoffs | `✓ Agent` tool, isolated context windows | `✓` agents-as-tools / handoffs |
| Hooks (PreToolUse, PostToolUse, SessionStart, Stop) | `✓` first-class | `⚠` lifecycle/guardrails callbacks (narrower) |
| Permission gating | `✓` 5 modes + per-tool allow/deny + `canUseTool` callback | `⚠` `needs_approval` per-tool |
| Sessions | `✓` JSONL on disk + `resume` / `fork_session` / `continue` | `✓` SQLite/AsyncSQLite/Redis/Mongo/SQLAlchemy/Dapr/OpenAI-managed/Encrypted |
| Context compaction | `✓` Claude Code-style auto-compaction | `✓ OpenAIResponsesCompactionSession` |
| MCP — stdio / streamable HTTP / SSE | `✓` all three | `✓` all three (SSE legacy) |
| MCP — hosted, server-side | `✗` | `✓ HostedMCPTool` |
| MCP server manager / multi-server | `✓` | `✓` |
| MCP runtime tool-list fetch | `✓` | `✓` (`cache_tools_list` flag) |
| Tool search (lazy load) | `✓` enabled by default | `✓ ToolSearchTool` + `defer_loading=True` |
| Tracing / observability | `⚠` via hooks (no first-party UI) | `✓` first-class built-in tracing |
| Filesystem-config skills/commands | `✓` `.claude/skills/`, `.claude/commands/`, CLAUDE.md | `✗` (skills exist but tied to sandbox/shell — see §5) |
| Function-tool decorator | `⚠` via in-process MCP server | `✓ @function_tool` (Pydantic, strict mode default) |
| Multimodal | `✓` | `✓` |
| Streaming | `✓` async iterator | `✓` |

### Where Claude Agent SDK wins (load-bearing for Layer A)

- **Code-search primitives ship in the box.** `Glob`, `Grep` (ripgrep-backed), `Read`, `Edit`, `Bash`, `Monitor`. The literal Claude Code toolset, tuned for ripping through codebases. With OpenAI Agents SDK we'd write 4–6 `function_tool` wrappers around `subprocess.run("rg", ...)`. Not hard, but not free, and we lose the permission/audit machinery that comes attached.
- **Local-by-default execution.** No hosted container fees, no upload-to-vector-store step, no leaving customer infra. Required for `PRD.md` §8's "no code leaves the customer environment in self-hosted mode" promise and for fintech/health ICP qualification.
- **Five-mode permission system** (`default` / `dontAsk` / `acceptEdits` / `bypassPermissions` / `plan`) plus per-tool allow/deny plus a `canUseTool` callback, evaluated in a documented order. Maps directly to `PRD.md` §7's "refuse when unsafe."
- **Hooks are first-class.** `PreToolUse`, `PostToolUse`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop` — natural home for `last_indexed_at` checks, audit logs, refusal-on-uninstrumented.
- **Filesystem-driven config.** `.claude/skills/`, `.claude/commands/`, `CLAUDE.md`, `.mcp.json` load automatically. Lets a customer ship a SuperContext skill pack without a code change. This resolved the earlier skills question.
- **Subagents inherit ergonomically.** Per-agent `tools`, `model`, `permissionMode`, `mcpServers`, `effort`, `background`. Useful for spawning per-service exploration in parallel with isolated context.

### Where OpenAI Agents SDK wins

- **Hosted tools we'd otherwise build.** `FileSearchTool`, `CodeInterpreterTool`, `ImageGenerationTool`, `WebSearchTool` — but these are **server-side and ship customer code to OpenAI**. Disqualifying for our self-hosted no-egress posture in regulated ICPs.
- **`HostedMCPTool`.** Removes a network hop for publicly reachable MCP servers; irrelevant when the SuperContext MCP server is inside the customer VPC.
- **Session backends are far more diverse** out of the box (SQLite, AsyncSQLite, Redis, MongoDB, SQLAlchemy, Dapr, OpenAI-managed, Encrypted). For a multi-tenant SaaS plane this is a real advantage — Claude SDK requires a custom `SessionStore` adapter.
- **`@function_tool` decorator** with Pydantic schema generation and `strict_json_schema=True` by default. Cleaner ergonomics than registering an in-process MCP server.
- **First-class tracing UI.** Claude's audit story is hooks-you-build.
- **Provider-agnostic.** 100+ models per the repo README. Claude Agent SDK supports Bedrock / Vertex / Azure-Foundry routing but the model is Claude.

### Where they tie

- **MCP consumption depth.** Both consume external MCP servers via stdio, streamable HTTP, and SSE; both pull tool schemas at runtime; both let you mix MCP tools and native tools in one tool list. Both support multi-server and tool-search/lazy-load. **The MCP layer — the actual moat — works identically either way.**
- **Streaming, parallel tool calls, multimodal, handoffs/subagents, compaction.** Parity.

## 4. Why this V2 differs from v0.1

The earlier v0.1 recommendation picked OpenAI Agents SDK. The reasoning weighed *generic platform-orchestration primitives* (sessions, tracing, guardrails, handoffs) and read Claude Agent SDK as too workspace-centric for a "graph-backed engineering context platform."

That weighting was reasonable but missed two product-shaped concerns:

1. **Layer A is not a generic orchestrator. It is a code-walking ingestion worker.** Glob/Grep/Read/Bash/Edit are not optional tools — they are the substance of the job. The v0.1 recommendation evaluated SDKs as if Layer A and Layer B were the same kind of agent. They aren't.
2. **`PRD.md` §8 mandates self-hosted Helm with no code egress.** OpenAI Agents SDK's strongest features (`FileSearchTool`, `CodeInterpreterTool`, `HostedMCPTool`) are server-side and require shipping code to OpenAI. For our regulated-buyer ICP this disqualifies the OpenAI SDK on its strongest axis.

Both v0.1 docs are honest research notes. The shift here is not a contradiction of the prior analysis but a reframing: separate A from B from C, and weigh code-search primitives + no-egress posture more heavily than generic platform primitives.

The skills question tilts the same direction — Claude's first-class skills load is the right native fit. The earlier open question is now resolved: skills are central enough to matter, and Claude wins on this axis today.

## 5. Skills resolution

The earlier open question was: *"Is the Product 1 agent layer primarily a graph-backed platform orchestrator, or is skills-based progressive disclosure important enough that we should optimize for it as a first-class runtime feature?"*

**Answer:** skills-based progressive disclosure is important enough. Compact base prompt + lazy instruction bundles per workflow (PR-bot synthesis, blast-radius explanation, deprecation campaign, oncall diff) keeps the coordinator prompt clean and lets customer admins ship per-org skill packs as `.claude/skills/`. OpenAI's skills support is currently shell-and-sandbox-tied (per the GitHub issue tracked in the v0.1 skills note); not aligned with our coordinator-agent shape.

This convergence — code-search tools + no-egress + skills — is what makes the Claude SDK choice load-bearing rather than marginal.

## 6. Operational implications and known gaps

Adopting Claude Agent SDK for layers A+B carries three operational tasks the v0.1 OpenAI choice would not have:

1. **Custom `SessionStore` adapter for the multi-tenant SaaS plane.** Default JSONL-on-disk persistence is acceptable for the self-hosted plane only. Estimated 1–2 weeks.
2. **Tracing/observability built via hooks.** Pipe `PostToolUse` events into our own observability stack (Datadog / OpenTelemetry / structured logs). No first-party tracing UI to lean on.
3. **Pricing page diligence on OpenAI hosted-tool fallback.** If we later support OpenAI Agents SDK as an alt for OpenAI-mandated customers, exact $/call numbers for `WebSearchTool`/`CodeInterpreterTool`/`FileSearchTool` need to be in the TCO model. The pricing page returned 403 during the comparison research — verify before any TCO commitment.

None of these are blockers. All are tracked work.

## 7. Swap clause

If a customer mandates a non-Claude model on the inference path for layers A or B, the swap cost to OpenAI Agents SDK is approximately one week:

- Functional parity on MCP consumption (no work)
- Custom `function_tool` wrappers around ripgrep / fd / yaml-parsing for what Glob/Grep/Read/Bash give us today
- Hook semantics re-implemented as guardrails / lifecycle callbacks
- Session store adapter (we already need a custom one — neutral)

The MCP contract for Layer C (per ADR-0002) is unaffected by any future swap. That decoupling is the load-bearing architectural choice.

## 8. References

- `PRD.md` §3 (vision), §6.1 (engine — typed graph + provenance), §6.2 (MCP server, eight tools, host IDEs), §6.3 (PR bot), §6.4 (CLI + REST, deferred IDE extension), §7 (UX principles), §8 (architecture, no-egress posture), §13 (risks)
- `PLATFORM-PRD.md` §9 (surfaces — MCP / agent tools)
- `docs/overall-architecture/claude-code-research.md` §3 (OSS landscape), §4 (Claude Agent SDK detail), §5 (embeddings — industry away), §7 (architecture)
- `docs/overall-architecture/codex-code-research.md` §4 (Claude Agent SDK assessment), §7 (recommendations), §8 (5-layer architecture), §11 (final posture)
- `adr/0001-claude-agent-sdk-for-internal-runtime.md`
- `adr/0002-mcp-protocol-for-external-surface.md`

### External sources consulted

- [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK MCP](https://code.claude.com/docs/en/agent-sdk/mcp)
- [Claude Agent SDK permissions](https://code.claude.com/docs/en/agent-sdk/permissions)
- [Claude Agent SDK subagents](https://code.claude.com/docs/en/agent-sdk/subagents)
- [Claude Agent SDK sessions](https://code.claude.com/docs/en/agent-sdk/sessions)
- [Claude Agent SDK skills](https://docs.claude.com/en/docs/agent-sdk/skills)
- [OpenAI Agents SDK tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI Agents SDK MCP](https://openai.github.io/openai-agents-python/mcp/)
- [OpenAI Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/)
- [OpenAI Agents SDK function_tool](https://openai.github.io/openai-agents-python/ref/tool/)
- [OpenAI Skills guide](https://developers.openai.com/api/docs/guides/tools-skills)
- [OpenAI Sandbox Agents skills](https://openai.github.io/openai-agents-python/ref/sandbox/capabilities/skills/)
- [openai/skills repo](https://github.com/openai/skills)
- [openai-agents-python repo](https://github.com/openai/openai-agents-python)
- [Lazy-loaded instruction skills request (issue #2906)](https://github.com/openai/openai-agents-python/issues/2906)
