---
name: bettercontext-mcp
description: Use when planning, implementing, or reviewing code with a Bettercontext MCP server available. Call Bettercontext before broad repo exploration when a task mentions a service, repo, symbol, package, endpoint, event channel, domain, file path, or changed files/ranges.
---

# Bettercontext MCP

Use Bettercontext as compact graph context for planning, coding, and review. MCP tool results still spend context tokens, so prefer one bounded workflow call before narrow follow-ups.

## Setup Check

Use an already registered Bettercontext MCP endpoint if present. If no endpoint is registered and the user wants local setup, build a repo-local snapshot and start the local server:

```bash
bettercontext-init
bettercontext-init --serve
```

Register the printed local HTTP `/mcp` URL in Claude Code. Keep the server loopback-bound unless the user intentionally accepts an unauthenticated public bind.

## Planning

Call `planning_context` before broad search when the user task names or implies a service, repo, symbol, package, endpoint, event channel, domain, or file path.

Use structured anchors when known:

- `service`, `repo`, `symbol`, `path`, `line`
- `package`, `endpoint`, `event_channel`, `domain`

If the result is `ambiguous`, use `next_actions` or returned candidates to refine. If the result is `unsupported_by_current_kg` or `not_found`, state what Bettercontext could not prove and fall back to normal repo search/read tools.

## Coding

Use Bettercontext for exact graph questions while editing:

- `find_callers` before changing a known symbol with downstream users.
- `find_callees` to understand immediate dependencies of a changed symbol.
- `blast_radius` only for static downstream CALLS closure from an exact symbol.
- `get_service_brief` for service-scoped endpoint/event/deploy facts.
- `get_event_consumers` and `get_event_producers` for async channel impact.

Still read the relevant source files before editing. Do not treat Bettercontext as a replacement for code inspection.

## Review

Before reviewing a diff, call `review_context` with:

- `repo`
- `changed_files`
- `changed_ranges` when line ranges are known

Use returned `changed_symbols`, `direct_callers`, `direct_callees`, and `repo_dependencies` to decide what to inspect next. Drill into primitive tools for concrete findings.

## Output Rules

- Cite returned evidence rows or file/line coordinates when making a claim.
- Do not paste raw evidence packets wholesale.
- Do not invent endpoint, event, deploy, or runtime impact when the current KG does not return it.
- If `coverage_warnings` or `unsupported_scopes` are present, mention them in the answer or review.
