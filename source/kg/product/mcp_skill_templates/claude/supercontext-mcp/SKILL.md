---
name: supercontext-mcp
description: Use when planning, implementing, reviewing code, or analyzing SuperContext A/B trace reports with a SuperContext MCP server available. Call SuperContext before broad repo exploration when a task mentions a service, repo, symbol, package, endpoint, event channel, domain, file path, or changed files/ranges. Use the trace-evaluation guidance for ab-report.md, ab-report.json, deltas.jsonl, or LangSmith run analysis.
---

# SuperContext MCP

Use SuperContext as compact graph context for planning, coding, and review. MCP tool results still spend context tokens, so prefer one bounded workflow call before narrow follow-ups.

## Tool Selection

| Task shape | First SuperContext tool |
|---|---|
| Broad repo-aware planning | `planning_context` |
| Feature or bug task mentioning a service, repo, symbol, package, endpoint, event channel, domain, or path | `planning_context` |
| PR or code review with changed files | `review_context` |
| Exact reverse impact for a known symbol | `find_callers` |
| Exact downstream calls for a known symbol | `find_callees` |
| Static downstream call closure from an exact symbol | `blast_radius` |
| Known service summary | `get_service_brief` |
| Candidate service lookup | `search_services` |
| Known event channel impact | `get_event_consumers` or `get_event_producers` |

Treat `planning_context` and `review_context` as first-level workflow tools. Treat `find_callers`, `find_callees`, `blast_radius`, `search_services`, `get_service_brief`, and event tools as drill-down tools once the anchor is known.

## Setup Check

Use an already registered SuperContext MCP endpoint if present. If no endpoint is registered and the user wants local setup, choose one command:

```bash
# Build or refresh the repo-local KG snapshot.
supercontext-init

# Build or refresh the snapshot and start the local MCP server.
supercontext-init --serve
```

Register the printed local HTTP `/mcp` URL in Claude Code. Keep the server loopback-bound unless the user intentionally accepts an unauthenticated public bind.

## Planning

Call `planning_context` before broad search when the user task names or implies a service, repo, symbol, package, endpoint, event channel, domain, or file path.

Use structured anchors when known:

- `service`, `repo`, `symbol`, `path`, `line`
- `package`, `endpoint`, `event_channel`, `domain`

If the result is `ambiguous`, use `next_actions` or returned candidates to refine. If the result is `unsupported_by_current_kg` or `not_found`, state what SuperContext could not prove and fall back to normal repo search/read tools.

## Coding

Use SuperContext for exact graph questions while editing:

- `find_callers` before changing a known symbol with downstream users.
- `find_callees` to understand immediate dependencies of a changed symbol.
- `blast_radius` only for static downstream CALLS closure from an exact symbol.
- `get_service_brief` for service-scoped endpoint/event/deploy facts.
- `get_event_consumers` and `get_event_producers` for async channel impact.

Still read the relevant source files before editing. Do not treat SuperContext as a replacement for code inspection.

## Review

Before reviewing a diff, call `review_context` with:

- `repo`
- `changed_files`
- `changed_ranges` when line ranges are known

Use returned `changed_symbols`, `direct_callers`, `direct_callees`, and `repo_dependencies` to decide what to inspect next. Drill into primitive tools for concrete findings.

## Anti-Patterns

- Do not start broad planning with repeated primitive calls.
- Do not repeatedly call `get_service_brief` to discover the right service when `planning_context` can anchor first.
- Do not use `find_callers` or `find_callees` on fuzzy or candidate-only symbol names as proof.
- Do not treat `deploy_blockers_for` as productive deploy analysis until deploy-blocker facts exist.
- Do not ignore `coverage_warnings`, `unsupported_scopes`, or `next_actions`.
- Do not replace source inspection before editing code; use SuperContext to reduce blind search and decide what to inspect.

## Trace Evaluation

When analyzing SuperContext A/B traces, `ab-report.md`, `ab-report.json`, `deltas.jsonl`, or LangSmith runs, evaluate in this order:

1. Correctness or quality verdict first.
2. Evidence and citation quality.
3. MCP tool timing and `mcp_tools_called`.
4. Non-MCP tool-call count and repeated source-search behavior.
5. Token, dollar, and wall-time deltas.
6. "Where MCP Hurts" rows.
7. Skill-compliance signal: whether SuperContext was used early for planning, coding, or review tasks.

Do not claim value from lower tokens, fewer tool calls, lower cost, or faster wall time when `quality_verdict` is `ungraded`, when `mcp_on` quality is worse, or when `cost_status` is `unavailable`.

## Output Rules

- Cite returned evidence rows or file/line coordinates when making a claim.
- Do not paste raw evidence packets wholesale.
- Do not invent endpoint, event, deploy, or runtime impact when the current KG does not return it.
- If `coverage_warnings` or `unsupported_scopes` are present, mention them in the answer or review.
