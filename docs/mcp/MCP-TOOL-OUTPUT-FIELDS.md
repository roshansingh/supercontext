# MCP Tool Output Field Reference

This file documents the public MCP tool response shapes so we can review overlap, missing inspection guidance, and prompt usage without rereading implementation code.

Source of truth: `source/kg/product/mcp_tools.py`, `source/kg/product/output_budget.py`, `source/kg/query/snapshot.py`, and packet modules under `source/kg/product/` and `source/kg/query/`.

## Agent-Facing MCP Transport Fields

Semantic tool packets are produced by `call_tool(...)`. The MCP server now renders those structured packets into a grep-shaped transport response before returning them to host agents. This is deliberate: the agent should treat SuperContext as source-inspection head start rows, not as a nested document to study or copy.

Default MCP `tools/call` responses contain exactly these fields:

| Field | Definition | Prompt / Skill Usage |
|---|---|---|
| `tool` | Tool name that produced the response. | Debug/routing only. |
| `query` | Compact query/status/anchor summary. | Use as orientation, not evidence. |
| `status` | Compact result state such as `found`, `partial`, `ambiguous`, `not_found`, or `indexed_scope_no_match`. | If not fully found/answerable, inspect source before absence, safety, or impact claims. |
| `answerability` | Compact answerability status string. | Treat `partial`, `not_answerable`, and `unknown` as instructions to inspect source or narrow the anchor. |
| `boundary` | One-line claim boundary for proven versus candidate rows. | Apply this before summarizing: candidate rows are leads, not proof; proven rows are still source pointers. |
| `covered` | Compact category summary such as `deploy_mappings: shown 2/6`. | Avoid rediscovering these first; verify only when the task requires source-level confidence. |
| `must_inspect` | Compact omitted/uncovered inspection guidance with category counts and source refs/search terms when available. | Use this for targeted source inspection before finalizing incomplete, risky, or broad answers. |
| `shown` | Number of row strings returned. | Scan these first. |
| `more` | Count of additional source/fact rows not shown because of row or byte budget. | If nonzero, inspect relevant `must_inspect` categories; do not treat omitted rows as absence. |
| `rows` | Flat strings shaped as `locator  [tag] category  fact`. Tags are `[proven]`, `[candidate]`, or bounded existing subtypes such as `[candidate:unlinked_source_lead]`. | Open cited locators for code/config verification. `[candidate]` rows are inspection leads only. |
| `gaps` | One-line summary of candidate/unproven/missing/unsupported/ambiguous coverage. | Say what remains unknown and spend source inspection here before final absence/safety claims. |
| `next` | One narrower MCP call or source-inspection/search lead. | Use when it would save work versus broad grep; otherwise inspect the source refs in `rows`/`gaps`. |

Agent-facing transport example:

```json
{
  "tool": "find_callers",
  "query": "status=found",
  "status": "found",
  "answerability": "partial",
  "boundary": "[proven] rows are KG/static pointers; [candidate] rows need source verification",
  "covered": ["callers: shown 1/1"],
  "must_inspect": ["terminal_import_consumer_leads: 8 omitted; inspect payments/bulk_0.py:10"],
  "shown": 2,
  "more": 8,
  "rows": [
    "payments/checkout.py:14  [proven] callers  checkout.handle_checkout -CALLS-> gateway.charge_card",
    "payments/bulk_0.py:10  [candidate:import_only_source_lead] terminal_import_consumer_leads  name=bulk_checkout"
  ],
  "gaps": "terminal_import_consumer_leads requires source verification",
  "next": "find_callers(line=5, path='payments/gateway.py', symbol='payments.gateway.charge_card')"
}
```

## Internal Semantic Packet Fields

Internal callers and tests may still use structured `call_tool(...)` packets. These fields are not the default MCP transport shape, but they remain the source of truth for rendering tags, gaps, rows, and next actions:

| Field | Definition | Prompt / Skill Usage |
|---|---|---|
| `tool` | Tool name that produced the response. | Useful for trace/debug only. |
| `status` | Result state such as `found`, `not_found`, `indexed_scope_no_match`, `ambiguous`, `partial`, or `unsupported_by_current_kg`. | Skills say to read this before answering and to inspect source for partial/not-found/unsupported results. |
| `packet_contract` | Terse per-response claim reminder for the producing tool. | Use this as a safety reminder only; the full agent-facing behavior contract lives in MCP server instructions. |
| `answerability` | Whether the packet can answer directly, partially, ambiguously, or not at all. | Use this to decide whether to answer from KG-backed context, retry/disambiguate, or inspect source/config. |
| `proven_facts` | Compact index of KG-backed/static fields present in the packet, with counts and claim boundary. | Treat listed fields as the strongest returned evidence, then cite the underlying rows/evidence coordinates rather than the index itself. |
| `candidate_leads` | Compact index of plausible but unproven fields such as import-only, unlinked, ambiguous, or inferred leads. | Use as the bounded source-inspection plan. Do not claim these as proven until source inspection verifies them. |
| `covered_areas` | Compact inline-map index of areas already returned as KG-backed/static leads after output compaction. | Do not rediscover these first; use their evidence refs/search terms as starting context, then verify only when the task requires source-level confidence. |
| `candidate_areas` | Compact inline-map index of candidate/unlinked areas preserved after output compaction. | Treat these as explicit verification leads. Their presence means “inspect this,” not “KG proved this.” |
| `coverage_gaps` | Normalized missing, unsupported, truncated, ambiguous, not-found, or unproven scopes. | Mention relevant gaps and inspect before claiming absence, deploy safety, runtime behavior, authz completeness, or ownership. |
| `inspection_areas` | Normalized follow-up rows with `area`, `reason`, `trigger`, `inspection_refs`, and `search_terms`. | Use these to read/search only the uncovered areas instead of starting broad grep. If the packet is small enough, inspect all relevant refs; if compacted, prioritize rows by task relevance. |
| `next_mcp_calls` | Compact inline-map list of narrower MCP calls with concrete arguments. | Use only when a narrower KG anchor would save work; otherwise inspect source using `inspection_areas`. |
| `head_start` | Compact inline-map section with the highest-signal tool-specific rows, such as runtime, review, authz, service, symbol, ownership, or related-fact leads. | Treat as the first-read summary. It is not a full dump; omitted categories must be followed through `inspection_areas` or `next_mcp_calls`. |
| `coverage_warnings` | Explicit coverage warnings attached to the packet. | Skills tell agents not to treat warnings as proof of absence. |
| `unsupported_scopes` | Capabilities or scopes the KG cannot currently prove. | Skills tell agents to state unsupported scopes and inspect source/config. |
| `next_actions` | Suggested refinements or source checks. | Skills tell agents to follow these before finalizing partial/ambiguous results. |
| `output_budget` | Legacy budget metadata when a structured packet is compacted by direct helper calls. The default MCP transport does not expose this field. | Treat as truncation guidance in internal tests only, not as an agent-facing contract. |

Common nested row shapes:

| Row | Fields | Definition |
|---|---|---|
| Symbol row | `symbol_id`, `display_name`, `qualified_name`, `repo`, `module`, `qualname`, `symbol_kind`, `path`, `line`, `end_line`, `evidence` | A code or external symbol identity plus source coordinates. |
| Fact row | `fact_id`, `predicate`, `subject`, `object`, `qualifier`, `evidence`, optional `call_site` | A KG edge with human-readable endpoints, metadata, evidence, and optional call-site coordinates. |
| Service row | `service_id`, `urn`, `name`, `identity`, `repo`, `namespace`, `slug`, `evidence` | A service identity plus source evidence. |
| Answerability | `status`, `missing_fact_families`, `recommended_source_checks` or `recommended_followups`, optional `cannot_prove` | Whether the packet can answer directly, what is missing, and where to inspect next. |
| Proven facts | `status`, `sources`, `claim_boundary` | Compact index of KG-backed/static fields returned by the tool. |
| Candidate leads | `status`, `sources`, `claim_boundary` | Compact index of plausible but unverified fields returned by the tool. |
| Candidate area | `area`, `count`, `lead_kind`, `evidence_refs`, `search_terms`, `claim_boundary` | Compact record of candidate/unlinked leads that survived compaction and still require verification. |
| Coverage gap | `trigger`, plus `detail` or `fact_family` | Normalized explanation of missing, unsupported, truncated, ambiguous, or not-found coverage. |
| Inspection area | `area`, `reason`, `trigger`, `inspection_refs`, `search_terms`, truncation metadata | Structured source-inspection guidance for bounded or partial packets. `inspection_refs` may be structured `{repo,path,line,symbol,...}` objects; `search_terms` may be scalar or list input but is normalized to strings. Tool-specific aliases such as `source_inspection_areas` may still appear, but the normalized common field is `inspection_areas`. |
| Covered area | `area`, `count`, `evidence_refs`, `search_terms`, `claim_boundary` | Compact record of what the packet already surfaced. |
| Next MCP call | `tool`, `arguments`, `reason` | Concrete narrower KG follow-up when source inspection would otherwise need broad search. |
| Output budget | `truncated`, `strategy`, `measured_chars`, `target_chars`, `max_chars`, `omitted_sections`, `omitted_counts`, `advice`, `row_limit`, `minimized`, optional `remaining_chars`, `backfilled_counts`, `exceeded_after_minimization`; legacy planning-only paths may also emit `fallback` | Explains what was compacted and how much detail was restored under budget. When rows are omitted, the packet should include inspection guidance rather than only an omitted count. |

Internal packet example:

```json
{
  "tool": "reverse_impact",
  "status": "partial",
  "proven_facts": {"status": "found", "sources": [{"field": "roots", "count": 1}]},
  "covered_areas": [{"area": "roots", "count": 1, "evidence_refs": [{"repo": "api", "path": "views.py", "line_start": 12}]}],
  "candidate_leads": {"status": "found", "sources": [{"field": "terminal_import_consumer_leads", "count": 2, "lead_kind": "import_only_source_lead"}]},
  "candidate_areas": [{"area": "terminal_import_consumer_leads", "count": 2, "lead_kind": "import_only_source_lead", "claim_boundary": "Candidate leads are inspection leads only."}],
  "coverage_gaps": [{"trigger": "missing_fact_family", "fact_family": "reverse_callers"}],
  "inspection_areas": [{"area": "candidate_leads", "reason": "Candidate leads require source verification before final claims.", "trigger": "candidate_leads_present", "inspection_refs": [], "search_terms": []}],
  "next_mcp_calls": [{"tool": "planning_context", "arguments": {"repo": "api", "path": "views.py", "limit": 25}, "reason": "Retrieve omitted detail around this source ref."}]
}
```

## Budgeted Transport Contract

Default MCP output is kept inline by rendering flat row strings with a target of roughly 8K serialized characters and a hard cap of 12K for one canonical JSON copy. The lower cap is intentional because the MCP transport currently carries the packet in both `content[].text` and `structuredContent`.

When a packet is too large, `render_grep_response(...)` selects rows by fact family instead of first-N order, keeps a compact `covered` / `must_inspect` header, drops rows from the end only after balanced selection, increments `more`, and preserves `gaps` plus `next`. It exposes only compact string/list transport fields, not nested `packet_contract`, `covered_areas`, `candidate_areas`, `inspection_areas`, `next_mcp_calls`, or `output_budget`.

Legacy structured compaction helpers still exist for direct regression coverage and internal use. They should not be treated as the default MCP host contract.

Budgeted `related_facts` sections are allowlisted so unknown sections do not pass through raw oversized payloads. Current sections are `service_brief`, `symbol_impact`, `dependency_importers`, `inventory`, `service_operational_surfaces`, `runtime_architecture`, `authz_surface`, `dependencies`, `endpoints`, `endpoint_consumers`, `event_channels`, `deploy_mappings`, and `domains`.

## Tool Fields

### `search_services`

Purpose: find indexed services by name, slug, repo, namespace, or other service identity text.

| Field | Definition |
|---|---|
| `query` | User-supplied service search string, or `null` for all services. |
| `returned_count` | Number of service rows returned after `limit`. |
| `services` | Service rows. |

Example:

```json
{"tool": "search_services", "status": "found", "returned_count": 1, "services": [{"name": "mercury-api", "repo": "mercury_api"}]}
```

Prompt usage: exact service discovery can start here, but broad planning/runtime questions should use `planning_context` first.

### `get_service_brief`

Purpose: compact service fact sheet for one unambiguous service.

| Field | Definition |
|---|---|
| `query` | Service query when status is `not_found` or `ambiguous`. |
| `service` | The matched service row. |
| `candidates`, `candidate_count` | Candidate service rows when the query is ambiguous. |
| `summary` | Counts for endpoint, event, deploy, endpoint-consumer, domain/deploy target, and authz rows. |
| `endpoints` | `EXPOSES_ENDPOINT`, `CALLS_ENDPOINT`, or `DOCUMENTS_ENDPOINT` rows touching the service. |
| `event_channels` | Event-channel rows touching the service. |
| `deploy_mappings` | `ROUTES_DOMAIN_TO_DEPLOY` and `DEPLOYS_VIA_CONFIG` rows touching the service. |
| `endpoint_consumers` | Static path/method-matched inbound endpoint consumer packet. |
| `operational_surfaces` | Service deploy/domain/runtime surfaces split into known linked, unlinked evidence, and missing contracts. |
| `authz_surface` | Endpoint-to-handler authz packet for the service repo when available. |
| `answerability` | Whether linked service facts are enough and which fact families are missing. This includes operational deploy/runtime missing contracts and static endpoint-consumer uncertainty even when service identity is `found`. |

Example:

```json
{"service": {"name": "api", "repo": "backend"}, "summary": {"endpoint_fact_count": 8, "deploy_mapping_count": 1}, "answerability": {"status": "partial", "missing_fact_families": ["canonical_service_deploy_blocker", "runtime_host_resolution"]}}
```

Prompt usage: skills say to keep `operational_surfaces.evidence_partition` buckets separate and not promote unlinked evidence into deploy proof.

### `find_callers`

Purpose: immediate static reverse `CALLS` edges for a known symbol.

| Field | Definition |
|---|---|
| `target` | Symbol-resolution packet for the requested downstream target. |
| `caller_count` | Number of returned direct callers. |
| `callers` | Direct caller fact rows. |
| `import_consumer_leads` | Source-inspection leads when no direct `CALLS` facts were found but importers may exist. |
| `disambiguation` | Retry guidance for ambiguous symbol matches. |

Example:

```json
{"status": "found", "caller_count": 2, "callers": [{"predicate": "CALLS", "subject": "api.View.post", "object": "lib.score"}]}
```

Prompt usage: tool description says ambiguous empty `callers` is not absence; default transport should surface a `next` path/line retry or candidate import-consumer rows to inspect.

### `reverse_impact`

Purpose: bounded reverse dependency head-start from one symbol anchor.

| Field | Definition |
|---|---|
| `source` | Symbol-resolution packet for the anchor. |
| `mode` | `exact_symbol`, `ambiguous`, or `all_matching_symbols`. |
| `depth` | Maximum reverse traversal depth used. |
| `summary` | Root, affected-symbol, edge, constructor-bridge, terminal-lead, truncation, limit, and multiplicity counts. Also includes `terminal_import_lead_returned_count`, `terminal_import_lead_total_in_returned_rows`, `truncated_terminal_symbol_returned_count`, `roots_unexpanded_count`, `edge_multiplicity`, `affected_symbol_multiplicity`, `tier_symbol_multiplicity`, and `affected_root_projection`. |
| `roots` | Resolved root symbol rows. |
| `tiers` | Affected symbols grouped by reverse depth. |
| `edges` | Reverse `CALLS` traversal fact rows. |
| `constructor_bridges` | Python `__init__` to class bridge rows so class instantiation callers are visible. |
| `terminal_import_consumer_leads` | Import-consumer source leads for terminal graph nodes; not runtime-call proof. |
| `truncated_terminal_symbols` | Symbols where reverse traversal stopped because the global section limit was reached; inspect these before claiming the returned impact is complete. `truncated_before_expansion` means queued incoming callers for that symbol were not explored. |
| `source_inspection_areas` | Source-inspection plan for tests, scripts, notebooks, entry points, and import-only modules outside the returned `CALLS` graph. |
| `affected_symbols` | Flat list of affected symbol rows with depth/root metadata. |
| `candidate_impact_previews` | Ambiguous-candidate previews ranked by direct caller count and stable tie-breakers. `selection_basis` explains whether constructor targets were included, so preview counts may differ from exact `find_callers`. Preview rank is a scan-order/risk hint, not proof of user intent. |
| `ambiguity_guidance` | Instructions for choosing one candidate instead of aggregating. |
| `answerability` | Missing anchor/caller facts and recommended source checks. |
| `contract` | Evidence boundary: static head start, not runtime proof. |
| `disambiguation` | Retry arguments for ambiguous symbol matches. |

Example:

```json
{
  "status": "found",
  "summary": {"affected_symbol_count": 11, "constructor_bridge_count": 1},
  "source_inspection_areas": [{"area": "same_repo_tests_scripts_notebooks", "search_terms": ["build_features("]}]
}
```

Prompt usage: default MCP transport renders these as source-pointer rows. Agents should use `reverse_impact` instead of manually chaining `find_callers`, treat candidate preview rows as ambiguity hints only, and verify source-inspection leads before final impact claims.

### `find_callees`

Purpose: immediate static downstream `CALLS` edges from a known symbol.

| Field | Definition |
|---|---|
| `source` | Symbol-resolution packet for the requested caller/source. |
| `callee_count` | Number of returned direct callees. |
| `callees` | Direct callee fact rows. |
| `disambiguation` | Retry guidance for ambiguous symbol matches. |

Example:

```json
{"status": "found", "callee_count": 1, "callees": [{"predicate": "CALLS", "subject": "A.run", "object": "B.load"}]}
```

Prompt usage: exact primitive for immediate dependencies; not a reverse-impact or service-boundary tool.

### `get_event_consumers`

Purpose: static consumers of an event channel.

| Field | Definition |
|---|---|
| `channel` | Event channel query string. |
| `event_fact_count` | Number of matching static event facts. |
| `returned_count` | Number returned after `limit`. |
| `indexed_channel_count` | Number of indexed event-channel entities in the snapshot when `status=not_found`; `null` on hits because the inventory scan is only needed for miss triage. |
| `near_matches` | Bounded nearby channel identities when an exact query has no static fact match. |
| `answerability` | Static-event scope, missing fact families, and runtime claims it cannot prove. |
| `consumers` | `CONSUMES_EVENT` fact rows. |

Example:

```json
{"status": "found", "channel": "queue-name", "event_fact_count": 2, "consumers": [{"predicate": "CONSUMES_EVENT"}]}
```

Prompt usage: skills say static event facts cannot prove time-window usage or zero runtime consumers. On `not_found`, inspect `gaps` / `next` transport leads and internal `near_matches` before claiming the channel is unused or unindexed.

### `get_event_producers`

Purpose: static producers of an event channel.

| Field | Definition |
|---|---|
| `channel` | Event channel query string. |
| `event_fact_count` | Number of matching static event facts. |
| `returned_count` | Number returned after `limit`. |
| `indexed_channel_count` | Number of indexed event-channel entities in the snapshot when `status=not_found`; `null` on hits because the inventory scan is only needed for miss triage. |
| `near_matches` | Bounded nearby channel identities when an exact query has no static fact match. |
| `answerability` | Static-event scope, missing fact families, and runtime claims it cannot prove. |
| `producers` | `PRODUCES_EVENT` fact rows. |

Example:

```json
{"status": "found", "channel": "topic-name", "event_fact_count": 1, "producers": [{"predicate": "PRODUCES_EVENT"}]}
```

Prompt usage: same event-boundary guidance as `get_event_consumers`.

### `blast_radius`

Purpose: bounded downstream static `CALLS` closure from one exact symbol.

| Field | Definition |
|---|---|
| `source` | Symbol-resolution packet for the root caller/source. |
| `depth` | Maximum downstream traversal depth. |
| `edge_count` | Number of returned downstream call edges. |
| `edges` | Downstream `CALLS` fact rows with depth metadata. |
| `disambiguation` | Retry guidance for ambiguous symbol matches. |

Example:

```json
{"status": "found", "depth": 2, "edge_count": 3, "edges": [{"predicate": "CALLS", "depth": 1}]}
```

Prompt usage: exact primitive for downstream intra-graph calls only; use `reverse_impact` for upstream callers.

### `deploy_blockers_for`

Purpose: explicit deploy-blocker contract when implemented.

| Field | Definition |
|---|---|
| `reason` | Why the current KG cannot answer. |
| `missing_contract` | Tool/contract name that is unsupported. |
| `unsupported_scopes` | Coverage gap row for deploy blockers. |

Example:

```json
{"status": "unsupported_by_current_kg", "missing_contract": "deploy_blockers_for"}
```

Prompt usage: tool description and next actions say unsupported means inspect manifests/source; absence of blocker facts is not proof of safety.

### `planning_context`

Purpose: composed planning packet for fleet or anchored repo/service/symbol/package/endpoint/event/domain context.

| Field | Definition |
|---|---|
| `query` | Free-form query only used for broad matching when no structured anchor is supplied. |
| `summary` | Counts for grouped rows and source coordinates; includes section limits. |
| `snapshot_summary` | Fleet-wide KG counts and count contract. |
| `snapshot_scope` | Indexed scope for supplied anchors, especially repo-scoped inventory. |
| `inventory` | Snapshot inventory, top dependencies, and coverage gap samples. |
| `service_operational_surfaces` | Service-level runtime/deploy/domain packet with evidence partitions. |
| `runtime_architecture` | Runtime architecture packet with building blocks, routing/deploy maps, and investigation brief. |
| `ownership_context` | Owner/maintainer candidate packet that separates explicit ownership from weak package metadata. |
| `authz_surface` | Authz review-lead packet for endpoint/handler/policy checks. |
| `anchors` | Structured anchors used: `repo`, `path`, `symbol`, `service`, `package`, `endpoint`, `event_channel`, `domain`. |
| `services`, `symbols`, `dependencies`, `endpoints`, `endpoint_consumers`, `event_channels`, `domains` | Bounded grouped rows matching the anchors. |
| `entry_points` | Compact service/symbol/endpoint/event/domain entry rows for scanning. |
| `related_facts` | Anchor-specific packets such as `dependency_importers`, `symbol_impact`, `authz_surface`, runtime references, dependencies, endpoints, endpoint consumers, event channels, deploy mappings, and domains. Internal structured packets may contain their own `inspection_areas` for omitted related rows. |
| `source_coordinates` | Bounded coordinates extracted from grouped rows. |
| `answerability` | Missing fact families and follow-up checks for the supplied anchors. `indexed_scope_no_match` means the scoped repo has indexed KG inventory but no matching first-class rows for the supplied filters; it is partial inventory evidence, not proof of absence. |
| `evidence` | Evidence rows from grouped context. |
| `output_budget` | Legacy internal helper metadata when structured output is compacted/truncated; not exposed by default MCP transport. |

Example:

```json
{
  "tool": "planning_context",
  "status": "found",
  "anchors": {"repo": "backend", "symbol": null},
  "runtime_architecture": {"answer_packet": {"investigation_brief": {"recommended_source_checks": []}}}
}
```

Prompt usage: skills say call this first for broad planning/runtime/domain/dependency questions, then use default transport `rows`, `gaps`, and `next` to decide source inspection. Internal structured consumers can still inspect `answerability`, `runtime_architecture.answer_packet.investigation_brief`, `service_operational_surfaces`, `authz_surface`, and `related_facts.symbol_impact.reverse_impact` as applicable.

Important transport usage: if `more` is greater than zero or `gaps` is not `none`, follow `next` or inspect the row locators before claiming completeness or absence.

### `review_context`

Purpose: composed review packet for a repo and changed files/ranges.

| Field | Definition |
|---|---|
| `repo` | Review repo anchor. |
| `summary` | Counts for changed symbols, callers/callees, transitive callers, dependencies, runtime facts, framework/app facts, and section/detail limits. |
| `review_answer_packet` | Compact first-read review packet with top changed symbols, callers/callees, framework, application, runtime, and surface status. |
| `changed_symbols` | Exact symbols overlapping changed ranges or changed files. |
| `changed_file_symbols` | File symbol inventory; context only, not proof every symbol changed. |
| `direct_callers`, `direct_callers_of_changed_symbols` | Direct callers of changed symbols. |
| `direct_callees`, `direct_callees_from_changed_symbols` | Direct callees from changed symbols. |
| `transitive_callers` | Bounded upstream caller closure for changed symbols. |
| `repo_dependencies` | Cross-repo dependency rows for the repo. |
| `changed_surface` | Changed-file/range scope explanation. |
| `scope_contract` | Contract separating changed symbols from file inventory. |
| `impact` | Compact grouping of callers, callees, transitive callers, and dependencies. |
| `runtime_surfaces` | Bounded endpoints, endpoint consumers, event channels, and deploy mappings. |
| `framework_impact` | Parser-backed framework facts such as Django/Celery model fields, relations, serializers, views, and tasks. |
| `application_impact` | App/package namespace surfaces, runtime facts, and cross-repo name leads. |
| `surface_status` | Requested review surface status: known, unlinked, missing, or unsupported. |
| `source_coordinates` | Coordinates from changed and related rows. |
| `answerability` | Missing review fact families and follow-up checks. |
| `unsupported_review_scopes` | Alias of unsupported scopes for review-specific consumers. |
| `evidence` | Evidence rows from changed symbols and related impact facts. |

Example:

```json
{
  "tool": "review_context",
  "status": "found",
  "summary": {"changed_symbol_count": 2, "transitive_caller_count": 5},
  "review_answer_packet": {"surface_status": [{"surface": "api_surfaces", "status": "known"}]}
}
```

Prompt usage: internal structured consumers can read `review_answer_packet` first, keep `changed_symbols` distinct from `changed_file_symbols`, and pass `requested_surfaces` when the user names impact categories. Default MCP host agents see these as flat `rows` with `gaps` and `next`.

## Known Duplication / Normalization Notes

- `inspection_areas` is the normalized internal common follow-up field. It is assembled from tool-specific inspection rows, `source_inspection_areas`, answerability follow-ups, next actions, runtime investigation briefs, and nested authz/review inspection rows when present. Default MCP transport renders this guidance into `gaps` and `next`.
- Tool-specific fields such as `reverse_impact.source_inspection_areas`, `authz_surface.inspection_areas`, and `runtime_architecture.answer_packet.investigation_brief` remain for compatibility and richer domain detail, but prompt and skill text should prefer default transport `rows`, `gaps`, and `next` when choosing what source to inspect next.
- `proven_facts`, `candidate_leads`, and `coverage_gaps` are normalized internal indexes, not replacements for the detailed tool fields. Default transport converts them into row tags and the `gaps` line.
- Counted normalized indexes fail closed when possible: if a field says `caller_count: 10` but the corresponding row list is empty, the common index should not count it as ten returned facts.
- `candidate_leads` includes top-level lead fields and selected nested lead fields, including operational unlinked evidence, application cross-repo name leads, and runtime unlinked leads.
- `direct_callers` and `direct_callers_of_changed_symbols` are aliases in `review_context`; same for `direct_callees` and `direct_callees_from_changed_symbols`.
- `unsupported_scopes` and `unsupported_review_scopes` duplicate review gaps for compatibility.
- `output_budget` is no longer part of the default MCP host response. It remains in legacy structured budget helpers for direct tests and internal compatibility.
