# ADR-0002: Use MCP as the Public Protocol for the Customer-Facing Surface (Layer C)

- **Status:** Accepted
- **Date:** 2026-04-28
- **Deciders:** Roshan Singh, Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

`PRD.md` §3 frames the product vision as making the service graph a first-class input to every AI coding interaction. `PRD.md` §6.2 names eight target IDE hosts the product must reach: **Claude Code, Cursor, Continue, Cody, Zed, Windsurf, JetBrains AI Assistant, and Copilot in VS Code**.

The product cannot afford a bespoke client per host. `PRD.md` §6.4 explicitly defers a SuperContext IDE extension as redundant: "MCP coverage in every major IDE (early 2026) makes this redundant for the MVP." The customer-facing surface (Layer C) therefore needs a single contract that all named hosts already speak.

Internally, layers A and B run on Claude Agent SDK per ADR-0001. The risk to manage here is that internal runtime choices must not leak into the public contract — a customer using Cursor or Copilot must get identical behavior to a customer using Claude Code.

## Decision

**Expose Layer C as a Model Context Protocol (MCP) server.**

Concretely:
- **Transport:** streamable HTTP, with OAuth 2.1 for the SaaS plane and static bearer tokens for self-hosted.
- **Tool surface:** the eight tools defined in `PRD.md` §6.2 — `search_services`, `get_service_brief`, `find_callers`, `find_callees`, `get_event_consumers`, `get_event_producers`, `blast_radius`, `deploy_blockers_for`.
- **Resource:** `supercontext://service/{name}/brief` per `PRD.md` §6.2 — a small (~2 KB) push-attachable brief for prompt-cache-friendly auto-attachment when the user opens a file in that service.
- **Schema discipline:** structured JSON with stable IDs, depth limits (default `depth=1`), cursor pagination, summary-then-drill-down for any neighborhood >10 nodes (per `PRD.md` §6.2).
- **Provenance / evidence contract:** every fact returned carries `commit_sha + file:line` (code), `topic + schema_version + last_seen_at` (events), or `trace_id + observed_at` (runtime), per `PRD.md` §6.1 and §7. Surfaced and safety-critical code facts also return evidence / refusal metadata consistent with ADR-0005's coordinate-fetch contract.
- **Implementation-agnostic on the consumer side:** tool schemas, JSON shapes, freshness fields, evidence fields, and refusal semantics must behave identically under any MCP-compliant host. The public MCP contract must not expose assumptions from the internal SDK, storage engine, retrieval backend, or query language.

## Consequences

### Positive
- One server reaches all eight named hosts in `PRD.md` §6.2 with zero per-host adapter work. Distribution scales at the cost of a single integration.
- MCP is the de facto standard for agent-tool integration as of 2026. Betting on the protocol matches the industry's direction and the eight named hosts' announced commitments.
- Decouples public contract from internal runtime. The Claude Agent SDK choice in ADR-0001 can be swapped without breaking any customer integration, preserving the swap clause in ADR-0001.
- Multiple OSS precedents confirm the pattern works for code-context tooling — Sourcebot's MCP server, ast-grep's MCP server, Multiplayer's MCP server (per `docs/overall-architecture/claude-code-research.md` §3 and §6). These are references and precedents, not runtime dependencies.
- The CLI and REST surfaces (`PRD.md` §6.4) can be layered on top of the same engine without forking the protocol — the engine answers questions; MCP, CLI, and REST are three projections.
- Forces healthy discipline on tool schemas: small surface (~8 tools), structured JSON, depth limits, cursor pagination. This is desirable for prompt-cache friendliness regardless of protocol.

### Negative
- The MCP spec is still maturing; transport, auth, and resource semantics may shift. Mitigated per `PRD.md` §13: "Adapter layer behind the engine; CLI + REST surface independent of MCP; OpenCtx as a fallback."
- A proprietary protocol fork by a major IDE (e.g., Cursor or GitHub forking MCP) would force adapter work. Tracked as an explicit risk in `PRD.md` §13. The CLI + REST surface in `PRD.md` §6.4 is the primary mitigation — those surfaces remain valuable even if the protocol fragments.
- MCP authn/authz is still being standardized; SSO/SCIM (`PRD.md` §8) sits above MCP and must be enforced at our server, not the protocol layer.

### Neutral
- Schema discipline imposed by MCP (small tool count, structured JSON) constrains the engine's expressiveness, which is desirable rather than limiting for the wedge use case.
- Streamable HTTP transport requires customer egress rules to permit our endpoint; not unique to MCP.

## Implementation Status (as of 2026-05-16)

This ADR has a local-development MCP server skeleton.

What exists now:

- `source/scripts/query_kg.py` provides a local CLI prototype over the same KG facts that future MCP tools will query.
- Implemented local query surfaces include `find-callers`, `find-callees`, `blast-radius`, `lookup-symbol`, `symbols-in-file`, `evidence-for-call`, `who-imports`, and `dependency-path`.
- `source/kg/product/mcp_tools.py` defines the eight ADR-0002 tool names with local JSON schemas and read-only handlers.
- `source/scripts/mcp_server.py` exposes a dependency-free local JSON-RPC HTTP endpoint at `/mcp` with `initialize`, `tools/list`, `tools/call`, and `ping`.
- The local server is single-request/single-response over plain HTTP. The ADR's streamable transport target remains a follow-up for real host compatibility work.
- `search_services`, `get_service_brief`, `find_callers`, `find_callees`, `get_event_consumers`, `get_event_producers`, and `blast_radius` return current KG-backed results.
- `deploy_blockers_for` returns `unsupported_by_current_kg` until canonical deploy-blocker facts exist.
- The local-development MCP server also exposes experimental composition tools, `planning_context` and `review_context`, to validate host-agent planning and review workflows. These are not yet ratified as ADR-0002 public primitive tools; the Tool Query Contract ADR must decide whether they remain MCP-visible workflow tools, move behind client skills, or become a separate surface.

What is still pending:

- OAuth/static-token auth modes.
- Host compatibility testing against real MCP clients.
- Streamable HTTP transport beyond the current request/response endpoint.
- Cursor pagination and summary-then-drill-down behavior beyond current local limits.
- `supercontext://service/{name}/brief` resource.
- Resource auto-attach behavior.
- Public contract decision for workflow composition tools such as `planning_context` and `review_context`.

### Post-merge review notes (as of 2026-05-21)

PR #108 moved the local MCP implementation from a primitive query surface toward an agent workflow surface:

- `source/scripts/mcp_server.py` is still local-development infrastructure, but it now has a usable read-only JSON-RPC tool path for host agents: `initialize`, `tools/list`, `tools/call`, `ping`, text JSON output, and `structuredContent` for tool consumers.
- `source/kg/product/mcp_tools.py` still exposes the eight ADR-0002 primitive tools, and also exposes the experimental workflow composition tools `planning_context` and `review_context`.
- `planning_context` is the intended first call for planning when a task mentions a service, repo, symbol, package, endpoint, event channel, domain, or file path. It normalizes the anchor, returns bounded matching rows, evidence, ambiguity/refinement actions, and then lets the agent choose narrower primitive tools.
- `review_context` is the intended first call for code review when the agent knows the changed repo plus changed files or changed line ranges. It currently composes changed symbols, direct callers, direct callees, and repo dependency links.
- `source/kg/product/mcp_skill_templates/{codex,claude}/bettercontext-mcp/SKILL.md` are the installable Codex and Claude Code skill templates for planning, coding, and review flows.
- `source/scripts/install_mcp_skills.py` installs only those explicit `bettercontext-mcp` host skill templates into project-local or global Codex/Claude Code skill directories. It intentionally does not copy this repository's project-maintenance skills.
- `source/scripts/register_mcp.py` registers the default local MCP endpoint (`http://127.0.0.1:3845/mcp`) with Codex and Claude Code using their host CLIs when available.
- `install.sh` is the one-line machine installer. It installs the Bettercontext package, global host-agent MCP skills, and default host MCP registration.
- `bettercontext-init` is the per-repo setup command. It builds the repo-local KG snapshot at `.bettercontext/kg` by default, and `bettercontext-init --serve` builds that snapshot and starts the local MCP server in the foreground.
- `AGENTS.md` and `CLAUDE.md` now direct agents to use `INDEX.md` as the canonical annotated project map before opening broad documentation sets.

Recommended development install model:

- Install host-agent skills and MCP registration globally once per user machine because the instructions and default local endpoint are reusable across projects.
- Build KG snapshots locally per repository because facts, paths, commit evidence, coverage, and freshness are repo-specific. The default project artifact is `.bettercontext/kg`.
- Do not make a global KG the default. A global graph is only appropriate later behind an explicit multi-repo workspace/fleet registry with freshness and identity controls.
- Keep project-local skill installation available for teams that want repo-pinned skill behavior, but do not require it for normal use.

Current usability assessment:

- For planning, the shape is directionally right: agents can call `planning_context` before broad repo search and then drill into `get_service_brief`, `find_callers`, `find_callees`, event tools, or `blast_radius`.
- For writing code, Bettercontext should not replace reading source files. It should reduce blind search by answering exact graph questions such as who calls a symbol, what a symbol calls, which event channel has producers or consumers, and which service or dependency anchor is relevant.
- For code review, `review_context` is useful but not yet the full product promise. It does not yet summarize endpoint, event, package, deploy, or runtime impact for a changed file set. It should be treated as static review context, not as a complete blast-radius reviewer.

Remaining gaps from the review:

- Skill support now has an installer for explicit global or project-local `bettercontext-mcp` skill files, and `bettercontext-register-mcp` can register the default local MCP endpoint with Codex and Claude Code. Host behavior still needs real-world evaluation: we need to measure whether installed skills and registered MCP tools reliably cause agents to call Bettercontext at planning, coding, and review time.
- The local server is not production/host-compat ready. Auth, streamable HTTP, resource auto-attach, real-host compatibility testing, and hosted/self-hosted deployment behavior remain open.
- `coverage_warnings` and `unsupported_scopes` are structurally present in tool outputs, but most successful paths return empty coverage metadata. Agents still cannot reliably distinguish "the graph found no risk" from "the graph lacks coverage for this risk family."
- `deploy_blockers_for` remains an honest refusal surface until canonical deploy-blocker facts exist.
- `planning_context` and `review_context` need a Tool Query Contract decision: keep them as MCP-visible workflow tools, move composition into host skills, or expose both with clear stability labels.

The recommendation after this review is to keep the eight ADR-0002 primitive tools and keep the workflow tools for local validation. The next highest-leverage work is not adding many more top-level tools; it is evaluating the installed host-agent hooks, making coverage/refusal metadata meaningful, and expanding `review_context` toward endpoint/event/package/deploy impact without inventing unsupported facts.

## Alternatives considered

**Per-IDE bespoke extensions** — rejected per `PRD.md` §6.4. Cost and maintenance burden across eight IDEs is prohibitive for an MVP, and MCP coverage already reaches all of them.

**OpenAI Agents SDK `HostedMCPTool` only** — rejected. Locks customers into OpenAI's hosted MCP runner; non-OpenAI hosts (Cursor, Continue, Cody, Zed, JetBrains AI, Claude Code) cannot reach it. Same self-hosted no-egress objection as ADR-0001.

**Custom REST or GraphQL API as primary surface** — rejected as primary. Each IDE host would then need its own integration to consume our API; defeats `PRD.md` §6.2's "one integration reaches every IDE" thesis. Retained as a *secondary* surface per `PRD.md` §6.4 for shell agents (Claude Code subagents, custom scripts), oncall humans, and CI gates.

**OpenCtx (Sourcegraph's earlier protocol)** — rejected as primary. Smaller host adoption than MCP and momentum has stalled since Sourcegraph's 2024 license change and pivot to Cody/Amp (per `docs/overall-architecture/claude-code-research.md` §3). Retained as a fallback option per `PRD.md` §13's "MCP loses to a proprietary spec" mitigation.

**Push-only context (auto-attach without tool calls)** — rejected as the only mechanism. Pull-by-default with one push-style brief is the chosen model per `PRD.md` §7 ("Pull by default, push for orientation"). The `supercontext://service/{name}/brief` resource captures the push case; everything else is pull.

## References

- `PRD.md` §3 (vision), §6.1 (engine — typed graph + provenance), §6.2 (MCP server, eight tools, resource shape, list of host IDEs), §6.3 (PR bot — separate surface, same engine), §6.4 (CLI + REST as secondary surfaces; rationale for deferring bespoke IDE extension), §7 (UX principles — provenance, pull-by-default, refuse when unsafe), §8 (architecture diagram showing MCP, PR bot, CLI as parallel surfaces over one engine), §12 (competitive positioning — MCP as the API, "Hosts" row), §13 (risks — MCP fork mitigation; OpenCtx fallback)
- `PLATFORM-PRD.md` §9 (surfaces — MCP / agent tools as one of four interfaces over the unified context graph)
- `docs/overall-architecture/claude-code-research.md` §3 (Sourcebot, ast-grep MCP precedents), §4 (MCP-as-first-class consumer in Claude Agent SDK), §6 (Multiplayer's MCP, Sourcebot's MCP), §7 (Product 1 architecture diagram — MCP, PR bot, CLI as parallel surfaces)
- `docs/overall-architecture/codex-code-research.md` §4 (Sourcebot MCP — pragmatic stack reference), §8 Layer 4 (agentic interface — MCP tools, PR bot, CLI), §11 (final architectural posture endorses MCP as substrate)
- ADR-0001 (Claude Agent SDK as internal runtime — internal/external split this ADR enforces)
