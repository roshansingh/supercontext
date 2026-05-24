---
name: supercontext-mcp
description: Use when planning, implementing, reviewing code, or analyzing SuperContext A/B trace reports with a SuperContext MCP server available. Call SuperContext before broad repo exploration when a task mentions a service, repo, symbol, package, endpoint, event channel, domain, file path, or changed files/ranges. Use the trace-evaluation guidance for ab-report.md, ab-report.json, deltas.jsonl, or LangSmith run analysis.
---

# SuperContext MCP

Use SuperContext as compact graph context for planning, coding, and review. MCP tool results still spend context tokens, so prefer one bounded workflow call before narrow follow-ups.

## Tool Selection

| Task shape | First SuperContext tool |
|---|---|
| Whole KG or snapshot summary | Ordinary snapshot files/metrics first |
| Broad repo-aware planning | `planning_context` |
| Feature or bug task with multiple possible anchors, broad service/repo context, endpoint, event channel, domain, package, or path | `planning_context` |
| PR or code review with changed files | `review_context` |
| Exact reverse impact for a known symbol | `find_callers` |
| Exact downstream calls for a known symbol | `find_callees` |
| Static downstream call closure from an exact symbol | `blast_radius` |
| Known service summary | `get_service_brief` |
| Candidate service lookup | `search_services` |
| Known event channel impact | `get_event_consumers` or `get_event_producers` |

Treat `planning_context` and `review_context` as first-level workflow tools. Treat `find_callers`, `find_callees`, `blast_radius`, `search_services`, `get_service_brief`, and event tools as drill-down tools once the anchor is known.

Exception: when the user asks an exact symbol question such as "who calls X?", "what does X call?", or "what symbols may be affected by X?", start with the exact-symbol tool. Do not force these through `planning_context`.

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

Call `planning_context` before broad search when the user task names or implies broad service/repo context, package, endpoint, event channel, domain, path, or multiple possible anchors. `planning_context` requires at least one anchor. For whole-KG or snapshot summaries, inspect snapshot manifest, metrics, and JSONL files directly instead of calling anchored MCP tools without an anchor.

Use structured anchors when known:

- `service`, `repo`, `symbol`, `path`, `line`
- `package`, `endpoint`, `event_channel`, `domain`

If the result is `ambiguous`, use `next_actions` or returned candidates to refine. If the result is `unsupported_by_current_kg` or `not_found`, state what SuperContext could not prove and fall back to normal repo search/read tools before giving the final answer.

## Coding

Use SuperContext for exact graph questions while editing:

- `find_callers` before changing a known symbol with downstream users.
- `find_callees` to understand immediate dependencies of a changed symbol.
- `blast_radius` only for static downstream CALLS closure from an exact symbol.
- `get_service_brief` for service-scoped endpoint/event/deploy facts.
- `get_event_consumers` and `get_event_producers` for async channel impact.

Still read the relevant source files before editing. Do not treat SuperContext as a replacement for code inspection.

If an exact-symbol tool returns `not_found`, do not conclude the symbol has no callers or callees until you inspect imports and source text. The symbol may be external, dynamically referenced, unindexed, or represented under a different qualname.

For exact caller/callee questions, report concrete source call sites found by fallback inspection before describing the KG miss. Do not answer only "not found in KG" when source references exist.

## Review

Before reviewing a diff, call `review_context` with:

- `repo`
- `changed_files`
- `changed_ranges` when line ranges are known

Use returned `changed_symbols`, `direct_callers`, `direct_callees`, and `repo_dependencies` to decide what to inspect next. Drill into primitive tools for concrete findings.

`review_context` does not replace the PR diff. If changed lines are not available from SuperContext, inspect the diff or changed file manually before saying what changed.

## Coverage Fallback

SuperContext is an index, not an authority over missing data. Treat `not_found`, empty rows, `unsupported_scopes`, and coverage warnings as routing signals.

Before answering from absence, inspect source when the task asks about:

- Kubernetes, Terraform, Docker, domains, ingress, or runtime routing
- PR diffs or changed lines
- external package calls or imported symbols
- event schemas, queue names, producers, or consumers when the returned channel does not match the prompt
- deployability or runtime blockers when the current KG says the scope is unsupported

Good answer shape: "SuperContext could prove X. It could not prove Y because of coverage Z. I inspected source A:B and therefore can/cannot conclude C."

## Anti-Patterns

- Do not start broad planning with repeated primitive calls.
- Do not repeatedly call `get_service_brief` to discover the right service when `planning_context` can anchor first.
- Do not use `find_callers` or `find_callees` on fuzzy or candidate-only symbol names as proof.
- Do not treat `deploy_blockers_for` as productive deploy analysis until deploy-blocker facts exist.
- Do not ignore `coverage_warnings`, `unsupported_scopes`, or `next_actions`.
- Do not turn `not_found`, empty results, or unsupported scope into the final answer without source fallback.
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
- When source fallback changes the conclusion, cite both the SuperContext limit and the source file/line evidence.
