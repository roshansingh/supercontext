---
name: supercontext-mcp
description: Use when planning, coding, reviewing code, or analyzing SuperContext A/B traces with a SuperContext MCP server available. Prefer planning_context for broad repo/service/symbol/package/endpoint/event/domain/path questions, review_context for changed-file review tasks, and primitive tools for exact caller, callee, service brief, or event producer/consumer questions.
---

# SuperContext MCP

Use SuperContext as a source-inspection head start. Default MCP results include compact `status`, `answerability`, `boundary`, `covered`, and `must_inspect` fields, plus grep-style rows: `locator [tag] category fact`, `gaps`, and `next`. Read the header and rows first to choose the right repos, files, symbols, services, domains, or follow-up searches, then verify and complete the answer with ordinary source inspection when rows are partial, candidate-tagged, ambiguous, risky, or missing a requested category. Treat `[candidate]` rows, `must_inspect`, and `gaps` as inspection leads, not proof. Use `next` only when a narrower KG anchor would save work. The MCP server instructions are the single behavior contract for packet fields and anti-overclaim rules.

## Setup

Use an already registered SuperContext MCP endpoint if present. If no endpoint is registered and the user wants local setup, choose one command:

```bash
supercontext-init
supercontext-init --serve
```

Register the printed local HTTP `/mcp` URL in Codex. Keep the server loopback-bound unless the user intentionally accepts an unauthenticated public bind.

## Routing

- Broad planning, architecture, dependency, ownership, runtime, domain, inventory, or impact map: call `planning_context` first.
- Diff/review with changed files or line ranges: call `review_context` first.
- Known symbol reverse callers: use `find_callers`.
- Transitive reverse impact from a resolved symbol: use `reverse_impact`.
- Known symbol callees or downstream call closure: use `find_callees` or `blast_radius`.
- Known service fact sheet: use `get_service_brief`.
- Known event channel producer/consumer facts: use `get_event_producers` or `get_event_consumers`.

Prefer one bounded workflow tool before narrow follow-ups. Prefer exact primitive tools when the user asks an exact graph question. Still inspect source before editing or before making claims that depend on partial, candidate, missing, dynamic, runtime, deploy, authz, or ownership evidence.

## Trace Evaluation

When analyzing SuperContext A/B traces, `ab-report.md`, `ab-report.json`, `deltas.jsonl`, or LangSmith runs, evaluate in this order:

1. Correctness or quality verdict.
2. Evidence and citation quality.
3. MCP tool timing and `mcp_tools_called`.
4. Non-MCP tool-call count and repeated source-search behavior.
5. Token, dollar, and wall-time deltas.
6. Where MCP hurts.
7. Skill-compliance signal: whether SuperContext was used early for planning, coding, or review tasks.

Do not claim value from lower tokens, fewer tool calls, lower cost, or faster wall time when `quality_verdict` is `ungraded`, when `mcp_on` quality is worse, or when `cost_status` is `unavailable`.
