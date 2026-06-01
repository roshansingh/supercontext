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

Register the printed local HTTP `/mcp` URL in Claude Code. Keep the server loopback-bound unless the user intentionally accepts an unauthenticated public bind.

## Common Packet Contract

For every MCP result, read `answerability`, `proven_facts`, `candidate_leads`, `coverage_gaps`, and `inspection_areas` before deciding what to inspect next. Read `packet_contract` when present; extreme budget fallback packets may omit static legends to preserve evidence. `proven_facts` points to KG-backed/static fields and their counts; cite the underlying detailed rows or file/line evidence, not just the index. `candidate_leads` contains plausible but unverified leads such as import-only consumers, unlinked runtime evidence, ambiguous candidates, or inferred guidance. `coverage_gaps` lists what the KG could not prove. If `output_budget` is present, treat it as truncation guidance and use `inspection_areas`, `output_budget.omitted_counts`, `output_budget.backfilled_counts`, and narrower anchors to recover omitted detail when the task needs it.

Use SuperContext as a head start for source inspection: do not reread every proven row when the packet already covers it, but do inspect uncovered `inspection_areas` when task quality depends on completeness. If the packet is compacted or too large, prioritize the most task-relevant `inspection_areas`; still name the other concrete refs/search terms as follow-up areas when they matter. Count-only omissions are not enough for final claims; follow any provided refs/search terms or call a narrower anchor when omitted categories are relevant. Do not claim candidate leads, missing gaps, or unsupported scopes as facts until source inspection verifies them.

## Evidence Gates

Before finalizing, split the user request into named answer categories and mark each category as KG-proven, source-verified, candidate, contradicted, unknown, or out-of-scope. If an MCP result is ambiguous, retry one exact `disambiguation.retry_arguments` candidate or returned path/qualified name before interpreting empty rows. If a result is partial, not_found, not_answerable, or unsupported_by_current_kg, treat it as an anchor or coverage gap, not a final refusal; use your normal search/read tools once before refusing or saying unknown. If a packet spills to a saved file, use a narrower MCP anchor or returned source refs/search terms instead of making jq/file archaeology the main workflow. For count/list/impact answers, verify that the final count matches the detailed evidence or inspected source rows. Final answers must separate KG-proven facts, source-verified facts, candidates, contradictions, and unknowns.

## Planning

Call `planning_context` before broad search for broad planning, architecture, dependency, or impact questions when the user task names or implies a service, repo, symbol, package, endpoint, event channel, domain, or file path.

Use structured anchors when known:

- `service`, `repo`, `symbol`, `path`, `line`
- `package`, `endpoint`, `event_channel`, `domain`

Read `summary`, `inventory`, `entry_points`, `related_facts`, `source_coordinates`, and the common packet fields before deciding what to inspect next.

- Dependency questions: check `related_facts.dependency_importers`.
- Ownership questions: check `ownership_context.answer_packet`; package authors and maintainers are not service owners unless explicit CODEOWNERS/catalog/owner metadata proves ownership.
- Endpoint authorization/security questions: check top-level `authz_surface`, `related_facts.authz_surface`, or `get_service_brief.authz_surface`. Read `review_leads`, `applied_policies`, `in_method_checks`, `inspection_areas`, `inspection_index`, and `unsupported_scopes`; do not treat a missing policy as proven public access.
- Service planning: check `service_operational_surfaces.evidence_partition`, `service_operational_surfaces.deploy_link_facts` / `DEPLOYS_VIA_CONFIG`, `deploy_runtime_units`, and `deploy_order_guidance`. Keep `known_linked`, `unlinked_evidence`, and `missing_contracts` separate. Do not promote unlinked domain routes into deploy proof.
- Source inspection: use `inspection_areas`, `runtime_architecture.answer_packet.investigation_brief.recommended_source_checks`, and `source_coordinates` for targeted reads instead of starting with broad grep.

The primary `limit` controls top-level result rows. Nested packets such as `entry_points`, `related_facts`, and `source_coordinates` are intentionally capped by the returned `summary.section_limit` to keep planning context compact. Fleet planning packets use a compact output cap; anchored planning packets allow more detail but are still bounded. For runtime architecture questions, read `runtime_architecture.answer_packet.investigation_brief` first. Use `runtime_anchors`, `known_routes`, `unlinked_runtime_leads`, `deploy_units`, `consumer_links`, and `recommended_source_checks` as the investigation plan, then inspect files or call `planning_context` again with narrower `repo`, `service`, `domain`, or `endpoint` anchors for omitted detail. In the final answer, include verified `unlinked_runtime_leads` such as API Gateway hostnames, private IPs, and static-site CNAME domains as referenced runtime targets with a caveat that they are source leads rather than proven route mappings. Before finalizing, compare the answer against every category named by the user request. If any requested category is missing, partially covered, or only present as a missing fact family, do a targeted follow-up source read/search or a narrower SuperContext call for that category, then explicitly mark it found or unknown. `runtime_architecture.summary.client_endpoint_call_count` is path-scoped candidate fact count, so inspect `endpoint_consumer_missing_method_drop_count` before treating it as usable consumer evidence.

If `answerability.status` is `answerable`, use the returned graph context as the primary head start and do only the targeted verification needed for the task risk. If it is `partial`, state the missing fact families and use returned follow-ups or targeted source reads. If the result is `ambiguous`, use `next_actions` or returned candidates to refine. If the result is `unsupported_by_current_kg`, `not_found`, or `not_answerable`, state what SuperContext could not prove and fall back to normal repo search/read tools.

## Coding

Use SuperContext for exact graph questions while editing:

- `find_callers` before changing a known symbol with downstream users.
- `reverse_impact` for reverse dependency and caller-impact analysis from a resolved symbol anchor; use it when you need transitive upstream callers, entry-point leads, or `inspection_areas` instead of manually chaining repeated `find_callers` calls.
- `find_callees` to understand immediate dependencies of a changed symbol.
- `blast_radius` only for static downstream CALLS closure from an exact symbol.
- `get_service_brief` for a concise service fact sheet when no broader planning or impact context is needed; read `operational_surfaces.evidence_partition` and `operational_surfaces.deploy_link_facts`, and do not promote `unlinked_evidence` into deploy/runtime proof.
- `get_event_consumers` and `get_event_producers` for exact known async channel impact.

Still read the relevant source files before editing. If `reverse_impact` is ambiguous, use `candidate_impact_previews` and `disambiguation.retry_arguments` to choose an exact anchor. Treat `reverse_impact.terminal_import_consumer_leads` as source-inspection leads, not runtime-call proof. Use common `inspection_areas` first, and `reverse_impact.source_inspection_areas` as the tool-specific detail, to inspect tests, scripts, notebooks, entry points, and import-only modules outside the returned CALLS graph. Do not treat SuperContext as a replacement for code inspection.

When the user gives only an unqualified symbol name, call the symbol tool with that name first so SuperContext can surface all candidates. Add `path`/`line` only when the user supplied that location or a prior SuperContext result returned it as a disambiguation candidate; do not use a first source-search hit as the anchor.

For ambiguous symbol-impact results, do not aggregate all candidates unless the user asks for all matches or exploratory impact. Use `candidate_impact_previews` as ranking hints, then retry one exact candidate when the intended edit site is clear; otherwise report the ambiguity and ask for `path`/`line`.

## Review

Before reviewing a diff, call `review_context` with:

- `repo`
- `changed_files`
- `changed_ranges` when line ranges are known

Read `changed_surface`, `impact`, `runtime_surfaces`, `framework_impact`, `application_impact`, `source_coordinates`, `answerability`, `proven_facts`, `candidate_leads`, `coverage_gaps`, `inspection_areas`, and `unsupported_review_scopes` before deciding what to inspect next. Use `application_impact.same_repo_surfaces` for app-level API/model/serializer/worker/scheduled-job context, `application_impact.runtime_facts` for app-scoped typed runtime facts, and `application_impact.cross_repo_name_leads` only as unlinked source-inspection leads, not as proven impact. Use `inspection_areas` and `source_coordinates` for targeted diff/source reads. Drill into primitive tools only for concrete follow-up findings or missing details.

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
