# MCP Workflow Integration Debate Seed

Use this as a seed for a debate about making SuperContext useful through MCP inside Claude Code, Codex, and similar coding agents.

## Question

How should the MCP surface and agent-side usage hooks change so SuperContext is used naturally during planning, code writing, and code review, without adding a separate UI or interrupting users?

The goal is not "more tools because tools are easy to add." The goal is a small, high-signal MCP contract that makes agents spend fewer tokens rediscovering known repo structure and gives them better evidence before they plan, edit, or review code.

## Product Direction

The primary user surface should be MCP inside existing coding agents.

Assumptions:

- Users will not regularly open a separate Streamlit or web UI while coding.
- Claude Code, Codex, Cursor-like agents, and PR-review bots are the actual UX.
- SuperContext should provide structured graph context, citations, and refusal metadata.
- Agents should still use normal repo search/read tools when the KG cannot answer safely.
- Feedback capture should not be a near-term priority because it interrupts users and will likely be ignored.

Important correction: MCP usage does not spend zero tokens. Tool results still enter the agent context. The product win is that a compact structured MCP result should spend far fewer tokens than repeated grep/read loops over many repos.

## Current Evidence

Current MCP implementation:

- Server: `source/scripts/mcp_server.py`
- Tool definitions and handlers: `source/kg/product/mcp_tools.py`
- Tests: `tests/test_mcp_tools.py`
- ADR contract: `adr/0002-mcp-protocol-for-external-surface.md`
- Product query mapping: `docs/evaluation/PRODUCT-QUERY-SET.md`

Observed current behavior:

- The server exposes JSON-RPC methods: `initialize`, `tools/list`, `tools/call`, and `ping`.
- Tool calls return both textual JSON and `structuredContent`, which is good for agent consumption.
- The server is local and read-only by default, loopback-bound unless `--allow-public` is explicitly passed.
- Argument validation is fail-closed for unknown fields, missing required args, bad limits, and unsupported tool names.
- The current implementation has no passive answer trace, feedback capture, or host-agent skill hook.

Current MCP tools:

| Tool | Current status | Recommendation |
|---|---|---|
| `search_services` | Works over indexed `Service` entities by name, slug, namespace, repo, and properties. | Keep. Improve descriptions so agents call it before planning service-scoped work. Add richer identity/owner/coverage data when available. |
| `get_service_brief` | Works as a compact service summary with endpoint, event, and deploy facts. | Keep. This should become one of the main planning tools. It needs upstream/downstream dependency summaries, package deps, coverage warnings, and owner/deploy fields when available. |
| `find_callers` | Works for symbol reverse calls with disambiguation fields. | Keep. Useful for coding and review. Needs stronger guidance that agents should use `path` and `line` when they know the edit location. |
| `find_callees` | Works for direct outgoing calls. | Keep. Useful while reading/changing a symbol. Should include endpoint/package/service edges where those are known, or point to follow-up tools. |
| `get_event_consumers` | Works for event-channel consumers. | Keep. Useful for async-flow planning and review. Needs coverage/refusal metadata when event extraction is incomplete. |
| `get_event_producers` | Works for event-channel producers. | Keep. Same as `get_event_consumers`; valuable for event lineage and contract review. |
| `blast_radius` | Works only from a symbol anchor over static `CALLS` edges. | Keep, but change the contract. The name implies broader impact than it currently covers. Either narrow description to `symbol_blast_radius` behavior or expand inputs to support changed files/lines, endpoints, packages, and repos. |
| `deploy_blockers_for` | Exists but returns `unsupported_by_current_kg`. | Keep as a contract/refusal surface, but do not position it as ready. It should remain honest until deploy/dependency facts can support it. |

Recommendation on removal: do not remove any of the eight ADR-0002 tools now. They are the public shape already documented in ADR-0002 and the PRD. Instead, fix descriptions, add coverage/refusal fields, and add workflow-level tools that make the existing tools useful in real agent loops.

## Main Gap

The current MCP surface is a v0 query surface, not yet a daily-driver agent workflow surface.

It can answer some exact questions, but it does not yet help enough with:

- planning a change before editing,
- finding the relevant symbols/files/services from a vague task,
- converting changed files or changed line ranges into impact context,
- reviewing a diff for hidden callers, consumers, deployables, packages, and coverage gaps,
- teaching Claude Code/Codex when to call SuperContext instead of immediately searching the repo.

## Desired Agent Workflows

### Project Context Index

Maintain a root `INDEX.md` per project as the first agent-readable map of durable context.

Each entry should include:

- URL or repo-relative path,
- owner,
- short annotation explaining what is inside,
- when an agent should read it.

Reason:

A bare list of links forces Claude Code/Codex to open many files just to decide what matters. An annotated index lets the project pay that context-selection cost once. MCP workflow docs and host-agent skills should instruct agents to read `INDEX.md` before opening broad documentation sets, then open only the documents relevant to the current planning, coding, or review task.

### Planning

When the user asks for a change, the host agent should call SuperContext before broad repo exploration if the task mentions a service, repo, package, symbol, endpoint, event, domain, deploy target, or changed file.

Expected planning output:

- likely services/repos involved,
- relevant symbols and files,
- direct and reverse dependencies,
- related endpoints/events/domains/deploy mappings,
- cross-repo package links,
- evidence citations,
- explicit coverage warnings and unsupported areas,
- suggested next graph queries if the anchor is ambiguous.

### Code Writing

While implementing, the agent should use SuperContext for exact graph questions:

- "Who calls this symbol?"
- "What does this symbol call?"
- "Which modules import this package?"
- "Which repo depends on this internal package?"
- "Which endpoints/domains/deploy mappings touch this service?"
- "Show evidence for this edge."

The agent should then use normal file reads/grep for local code details. SuperContext should not replace code reading. It should reduce the number of blind searches.

### Code Review

Before reviewing a PR or local diff, the agent should call SuperContext with changed files and line ranges.

Expected review output:

- changed symbols inferred from coordinates,
- callers/callees of those symbols,
- endpoint/event/package/deploy impacts,
- cross-repo consumers,
- areas where KG coverage is partial or unsupported,
- recommended review checklist items grounded in evidence.

This is more useful than asking a reviewer to manually query `find_callers` one symbol at a time.

## Proposed MCP Surface

The debate should decide whether to expose many precise tools or keep a smaller agent-facing surface with workflow tools that internally compose precise queries.

### Option A: Add Many Top-Level Query Tools

Expose current CLI capabilities directly through MCP:

- `lookup_symbol`
- `symbols_in_file`
- `modules_importing`
- `dependency_info`
- `who_imports`
- `top_dependencies`
- `repo_dependencies`
- `cross_repo_links`
- `domain_references`
- `endpoints`
- `deploy_mappings`
- `evidence_for_call`

Pros:

- Simple mapping to existing `KgSnapshot` methods.
- Easy to test with current CLI fixtures.
- Gives power users and agents explicit exact tools.

Cons:

- Tool list becomes large.
- Agents may choose the wrong narrow tool.
- More tool descriptions means more prompt/schema tokens.
- This drifts from the PRD principle of a small high-signal surface.

### Option B: Add Workflow Tools And Keep Primitives Limited

Add two high-level MCP tools:

#### `planning_context`

Inputs:

- `query`: natural-language user task or short planning question.
- optional `repo`
- optional `path`
- optional `line`
- optional `symbol`
- optional `service`
- optional `package`
- optional `endpoint`
- optional `event_channel`
- optional `domain`
- `limit`

Output:

- normalized anchors,
- matching services/repos/symbols,
- relevant dependencies,
- endpoints/events/domains/deploy mappings,
- evidence rows,
- coverage warnings,
- ambiguity/refusal state,
- recommended follow-up tool calls.

Important: this should not synthesize a final prose answer. It should return compact structured context for the host agent.

#### `review_context`

Inputs:

- `repo`
- `changed_files`: list of paths
- optional `changed_ranges`: list of `{path, start_line, end_line}`
- optional `diff_summary`
- `depth`
- `limit`

Output:

- symbols touched by changed ranges,
- direct callers and callees,
- import/package consumers,
- endpoint/event/domain/deploy impacts,
- cross-repo dependencies,
- coverage warnings,
- evidence rows,
- review checklist grouped by risk area.

Recommendation: prefer Option B as the product surface. Add a small number of precise tools only when workflow tools cannot express a frequent agent need.

### Minimal Additional Precise Tools

Even with workflow tools, these precise tools are worth exposing because agents naturally ask exact questions:

- `lookup_symbol`: resolve ambiguous symbols before calling impact tools.
- `symbols_in_file`: map changed files/lines to symbols.
- `modules_importing`: answer package usage questions cheaply.
- `repo_dependencies`: answer cross-repo dependency questions cheaply.
- `evidence_for_call`: retrieve exact citations for a specific edge.

Potentially keep the rest as CLI-only or internal helper APIs until usage proves they need to be MCP-visible.

## Existing Tool Changes Needed

### `search_services`

Change:

- Add stronger description: "Call before planning service-scoped changes."
- Return coverage/refusal metadata for missing owner/deploy/runtime dimensions.
- Include top evidence with path/line, not unbounded evidence arrays.

Reason:

Agents need quick service orientation without pulling many files.

### `get_service_brief`

Change:

- Include upstream/downstream summaries when available.
- Include package dependencies and cross-repo links when available.
- Include endpoints/events/domains/deploy mappings with bounded examples.
- Include `coverage_warnings`.

Reason:

This should become the main service planning primitive.

### `find_callers` and `find_callees`

Change:

- Keep strict symbol/path/line disambiguation.
- Return ambiguity state with candidate symbols when a bare symbol is unsafe.
- Add review-oriented fields such as `risk_notes` only if grounded in facts.
- Keep candidate/LLM-inferred facts hidden by default per ADR-0004/ADR-0006.

Reason:

These are core coding tools. They must stay precise and evidence-first.

### `get_event_consumers` and `get_event_producers`

Change:

- Add explicit coverage warnings for unsupported event frameworks/config sources.
- Include producer/consumer service/repo identity where known.
- Avoid implying complete lineage when only partial event extraction exists.

Reason:

Async impact review is high value, but false completeness is dangerous.

### `blast_radius`

Change:

- Debate whether to rename semantics internally or expand contract.
- Current behavior is really `symbol_downstream_calls`.
- Desired product behavior is broader: changed symbols/files/endpoints/packages/deploy targets across services.

Recommended path:

- Keep `blast_radius` public name.
- Add input union in stages:
  - `symbol` with optional `path`/`line` first,
  - `changed_files`/`changed_ranges` next,
  - `package`, `endpoint`, `event_channel`, and `service` anchors after supporting facts are reliable.
- Always return `coverage_warnings` and `unsupported_scopes`.

Reason:

The product promise of blast radius is review/planning impact, not only call graph traversal.

### `deploy_blockers_for`

Change:

- Keep refusal behavior until deploy blocker facts are real.
- Improve unsupported response with what evidence is missing.
- Later compute blockers from service dependencies, event/API/schema consumers, package dependencies, and deploy topology.

Reason:

Removing it weakens the ADR contract. Faking it would be worse.

## Agent Skill Hooks

MCP tools alone are not enough. Claude Code/Codex need explicit instructions to call them.

Add repo-distributed guidance for host agents. Current implementation ships this as installable skill templates:

- `source/kg/product/mcp_skill_templates/claude/supercontext-mcp/SKILL.md`
- `source/kg/product/mcp_skill_templates/codex/supercontext-mcp/SKILL.md`
- installed by `supercontext-install-mcp-skills`

The hook should be short and operational:

1. Before planning a change, call `planning_context` when the task names a service, repo, path, symbol, package, endpoint, event, domain, or deploy target.
2. Before editing a known symbol, call `lookup_symbol` if ambiguous and `find_callers`/`find_callees` if the change may affect behavior.
3. Before reviewing a diff, call `review_context` with changed files and line ranges.
4. Use normal `Read`/`Grep`/repo tools after SuperContext narrows the search.
5. If SuperContext returns `unsupported_by_current_kg`, `ambiguous`, or partial coverage, say what is unknown and fall back to code search.
6. Do not paste large MCP outputs into the final answer. Use the citations and conclusions.

## Response Shape Requirements

Every MCP tool intended for agent use should return:

- `status`: `found | not_found | ambiguous | partial | unsupported_by_current_kg`
- `query` or normalized input
- `returned_count`
- bounded result arrays
- `evidence` with repo, commit, path, and line when available
- `coverage_warnings`
- `unsupported_scopes`
- `next_actions` or suggested follow-up tools when ambiguous

Avoid:

- large unbounded evidence arrays,
- prose-only answers,
- hidden defaults that imply completeness,
- raw graph implementation details,
- keyword-only semantic shortcuts.

## Debate Scope

The debate should produce a staged implementation plan, not a giant MCP rewrite.

Suggested PR sequence:

### PR1: Tool Contract Cleanup

- Improve descriptions for existing eight tools.
- Add common response metadata: coverage warnings, unsupported scopes, bounded evidence shape.
- Keep current behavior otherwise.
- Add tests that tool descriptions and schemas stay stable.

### PR2: Add Minimal Precise MCP Tools

- Add `lookup_symbol`.
- Add `symbols_in_file`.
- Add `modules_importing`.
- Add `repo_dependencies`.
- Add `evidence_for_call`.
- Reuse existing `KgSnapshot` methods.
- Add MCP tests for argument validation and result shapes.

### PR3: Add `planning_context`

- Compose existing query methods.
- Start with deterministic anchor fields, not full natural-language planning.
- If only `query` is provided, do conservative structured matching across service/symbol/package/domain/event names.
- Return ambiguity rather than guessing.

### PR4: Add `review_context`

- Accept changed files and optional changed ranges.
- Map ranges to symbols via existing symbol coordinates.
- Compose callers/callees/imports/repo deps/endpoints/deploy mappings.
- Include coverage warnings and unsupported scopes.

### PR5: Add Host Agent Skill Docs

- Add concise Claude Code/Codex usage snippets.
- Document when to call tools for planning, coding, and review.
- Instruct agents to read root `INDEX.md` first when project docs are needed, then open only relevant indexed docs.
- Include examples that show fallback to grep/read when KG coverage is partial.

## Success Criteria

The implementation should be considered successful only if a host agent can do these workflows without a UI:

1. Planning: user asks "I need to change billing auth behavior"; agent calls MCP first and gets service/symbol/endpoint context before broad repo search.
2. Coding: user asks to edit a known symbol; agent checks callers/callees and cites affected files before changing code.
3. Review: user asks for PR review; agent calls `review_context` on changed files and includes hidden consumers or explicit coverage unknowns in review findings.
4. Token discipline: typical MCP result stays compact and bounded; it should not dump entire evidence packets.
5. Honesty: unsupported deploy blockers or partial coverage produce explicit caveats, not empty "no impact" answers.

## Open Questions For Debate

- Should `planning_context` accept natural language, or only structured anchors in v1?
- Should existing CLI query commands become MCP tools, or remain internal helpers behind workflow tools?
- Should `blast_radius` expand to changed files/ranges, or should `review_context` own PR/diff impact?
- How many tools can Claude Code/Codex reliably choose from before tool-selection quality drops?
- Should workflow tools include snippets/source excerpts, or only coordinates and claims?
- Where should host-agent skill docs live so users can actually install or copy them?
- Should local MCP server support stdio transport in addition to HTTP for easier Claude Code/Codex setup?
- How should snapshots be discovered or refreshed from MCP without making the server mutate code or run expensive builds?

## Recommended Debate Starting Position

Keep the ADR-0002 eight tools, but stop treating them as sufficient for the product goal.

Add two workflow tools, `planning_context` and `review_context`, because planning and review are the actual agent moments where SuperContext can change behavior. Add only a small number of exact query tools that agents frequently need during coding: `lookup_symbol`, `symbols_in_file`, `modules_importing`, `repo_dependencies`, and `evidence_for_call`.

Do not prioritize feedback capture or a UI. The next product risk is not lack of feedback forms; it is that agents will not know when to call SuperContext, or will call it and get too narrow an answer for planning/review work.
