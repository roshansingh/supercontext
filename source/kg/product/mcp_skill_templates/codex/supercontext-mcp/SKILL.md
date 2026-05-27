---
name: supercontext-mcp
description: Use when planning, implementing, reviewing code, or analyzing SuperContext A/B trace reports with a SuperContext MCP server available. For broad planning, architecture, dependency, or impact questions, call planning_context before broad repo exploration when the task mentions a service, repo, symbol, package, endpoint, event channel, domain, file path, or changed files/ranges. Use exact primitive tools for exact caller, callee, service brief, or event producer/consumer questions. Use the trace-evaluation guidance for ab-report.md, ab-report.json, deltas.jsonl, or LangSmith run analysis.
---

# SuperContext MCP

Use SuperContext as the starting point for planning, coding, and review. MCP tool results should give the agent a source-inspection head start: first read the graph packet to choose the best files, repos, services, domains, and symbols to inspect, then verify and complete the answer with ordinary source reads. MCP tool results still spend context tokens, so prefer one bounded workflow call before narrow follow-ups, and prefer exact primitive tools when the user asks an exact graph question.

## Setup Check

Use an already registered SuperContext MCP endpoint if present. If no endpoint is registered and the user wants local setup, choose one command:

```bash
# Build or refresh the repo-local KG snapshot.
supercontext-init

# Build or refresh the snapshot and start the local MCP server.
supercontext-init --serve
```

Register the printed local HTTP `/mcp` URL in Codex. Keep the server loopback-bound unless the user intentionally accepts an unauthenticated public bind.

## Planning

Call `planning_context` before broad search for broad planning, architecture, dependency, or impact questions when the user task names or implies a service, repo, symbol, package, endpoint, event channel, domain, or file path.

Use structured anchors when known:

- `service`, `repo`, `symbol`, `path`, `line`
- `package`, `endpoint`, `event_channel`, `domain`

Read `summary`, `inventory`, `entry_points`, `related_facts`, `source_coordinates`, `answerability`, and any `runtime_architecture.answer_packet.investigation_brief` before deciding what to inspect next. For dependency questions, check `related_facts.dependency_importers`; for service planning, check `service_operational_surfaces.evidence_partition`, `deploy_runtime_units`, and `deploy_order_guidance`, and keep buckets separate: `known_linked` is exact KG/repo-linked evidence, `unlinked_evidence` is source leads only, and `missing_contracts` are claims SuperContext cannot prove. Treat `service_operational_surfaces.deploy_link_facts` / `DEPLOYS_VIA_CONFIG` and `deploy_runtime_units` as service-to-deploy-target evidence; treat `deploy_order_guidance` as practical consumer-compatibility inference, not a canonical deploy-blocker fact. Do not promote unlinked domain routes into deploy proof. Use `investigation_brief.recommended_source_checks` and `source_coordinates` for targeted source reads instead of starting with broad grep.

The primary `limit` controls top-level result rows. Nested packets such as `entry_points`, `related_facts`, and `source_coordinates` are intentionally capped by the returned `summary.section_limit` to keep planning context compact. Fleet planning packets use a compact output cap; anchored planning packets allow more detail but are still bounded. For runtime architecture questions, read `runtime_architecture.answer_packet.investigation_brief` first. Use `runtime_anchors`, `known_routes`, `unlinked_runtime_leads`, `deploy_units`, `consumer_links`, and `recommended_source_checks` as the investigation plan, then inspect files or call `planning_context` again with narrower `repo`, `service`, `domain`, or `endpoint` anchors for omitted detail. In the final answer, include verified `unlinked_runtime_leads` such as API Gateway hostnames, private IPs, and static-site CNAME domains as referenced runtime targets with a caveat that they are source leads rather than proven route mappings. Before finalizing, compare the answer against every category named by the user and every category named in the expected answer shape. If any requested category is missing, partially covered, or only present as a missing fact family, do a targeted follow-up source read/search or a narrower SuperContext call for that category, then explicitly mark it found or unknown. `runtime_architecture.summary.client_endpoint_call_count` is path-scoped candidate fact count, so inspect `endpoint_consumer_missing_method_drop_count` before treating it as usable consumer evidence.

If `answerability.status` is `answerable`, answer from returned graph context with minimal targeted verification as needed. If it is `partial`, state the missing fact families and use returned follow-ups or targeted source reads. If the result is `ambiguous`, use `next_actions` or returned candidates to refine. If the result is `unsupported_by_current_kg`, `not_found`, or `not_answerable`, state what SuperContext could not prove and fall back to normal repo search/read tools.

## Coding

Use SuperContext for exact graph questions while editing:

- `find_callers` before changing a known symbol with downstream users.
- `find_callees` to understand immediate dependencies of a changed symbol.
- `blast_radius` only for static downstream CALLS closure from an exact symbol.
- `get_service_brief` for a concise service fact sheet when no broader planning or impact context is needed; read `operational_surfaces.evidence_partition` and `operational_surfaces.deploy_link_facts`, and do not promote `unlinked_evidence` into deploy/runtime proof.
- `get_event_consumers` and `get_event_producers` for exact known async channel impact.

Still read the relevant source files before editing. Do not treat SuperContext as a replacement for code inspection.

## Review

Before reviewing a diff, call `review_context` with:

- `repo`
- `changed_files`
- `changed_ranges` when line ranges are known

Read `changed_surface`, `impact`, `runtime_surfaces`, `framework_impact`, `application_impact`, `source_coordinates`, `answerability`, and `unsupported_review_scopes` before deciding what to inspect next. Use `application_impact.same_repo_surfaces` for app-level API/model/serializer/worker/scheduled-job context, `application_impact.runtime_facts` for app-scoped typed runtime facts, and `application_impact.cross_repo_name_leads` only as unlinked source-inspection leads, not as proven impact. Use `source_coordinates` for targeted diff/source reads. Drill into primitive tools only for concrete follow-up findings or missing details.

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
