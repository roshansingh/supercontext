# MCP Tool Output Field Reference

This file documents the public MCP tool response shapes so we can review overlap, missing inspection guidance, and prompt usage without rereading implementation code.

Source of truth: `source/kg/product/mcp_tools.py`, `source/kg/product/output_budget.py`, `source/kg/query/snapshot.py`, and packet modules under `source/kg/product/` and `source/kg/query/`.

## Common Response Fields

MCP responses are wrapped by `call_tool(...)` with these common or optional fields:

| Field | Definition | Prompt / Skill Usage |
|---|---|---|
| `tool` | Tool name that produced the response. | Useful for trace/debug only. |
| `status` | Result state such as `found`, `not_found`, `ambiguous`, `partial`, or `unsupported_by_current_kg`. | Skills say to read this before answering and to inspect source for partial/not-found/unsupported results. |
| `packet_contract` | Common response contract and claim rule for the producing tool. | Read this as the field legend: SuperContext is a source-inspection head start, not a replacement for code inspection. |
| `answerability` | Whether the packet can answer directly, partially, ambiguously, or not at all. | Use this to decide whether to answer from KG-backed context, retry/disambiguate, or inspect source/config. |
| `proven_facts` | Compact index of KG-backed/static fields present in the packet, with counts and claim boundary. | Treat listed fields as the strongest returned evidence, then cite the underlying rows/evidence coordinates rather than the index itself. |
| `candidate_leads` | Compact index of plausible but unproven fields such as import-only, unlinked, ambiguous, or inferred leads. | Use as the bounded source-inspection plan. Do not claim these as proven until source inspection verifies them. |
| `coverage_gaps` | Normalized missing, unsupported, truncated, ambiguous, not-found, or unproven scopes. | Mention relevant gaps and inspect before claiming absence, deploy safety, runtime behavior, authz completeness, or ownership. |
| `inspection_areas` | Normalized follow-up rows with `area`, `reason`, `trigger`, `inspection_refs`, and `search_terms`. | Use these to read/search only the uncovered areas instead of starting broad grep. If the packet is small enough, inspect all relevant refs; if compacted, prioritize rows by task relevance. |
| `coverage_warnings` | Explicit coverage warnings attached to the packet. | Skills tell agents not to treat warnings as proof of absence. |
| `unsupported_scopes` | Capabilities or scopes the KG cannot currently prove. | Skills tell agents to state unsupported scopes and inspect source/config. |
| `next_actions` | Suggested refinements or source checks. | Skills tell agents to follow these before finalizing partial/ambiguous results. |
| `output_budget` | Planning-context budget metadata when a packet had to be compacted. | Treat as truncation guidance, not source evidence. Use `remaining_chars`, `backfilled_counts`, `omitted_counts`, and `inspection_areas` to decide narrow follow-ups. |

Common nested row shapes:

| Row | Fields | Definition |
|---|---|---|
| Symbol row | `symbol_id`, `display_name`, `qualified_name`, `repo`, `module`, `qualname`, `symbol_kind`, `path`, `line`, `end_line`, `evidence` | A code or external symbol identity plus source coordinates. |
| Fact row | `fact_id`, `predicate`, `subject`, `object`, `qualifier`, `evidence`, optional `call_site` | A KG edge with human-readable endpoints, metadata, evidence, and optional call-site coordinates. |
| Service row | `service_id`, `urn`, `name`, `identity`, `repo`, `namespace`, `slug`, `evidence` | A service identity plus source evidence. |
| Answerability | `status`, `missing_fact_families`, `recommended_source_checks` or `recommended_followups`, optional `cannot_prove` | Whether the packet can answer directly, what is missing, and where to inspect next. |
| Proven facts | `status`, `sources`, `claim_boundary` | Compact index of KG-backed/static fields returned by the tool. |
| Candidate leads | `status`, `sources`, `claim_boundary` | Compact index of plausible but unverified fields returned by the tool. |
| Coverage gap | `trigger`, plus `detail` or `fact_family` | Normalized explanation of missing, unsupported, truncated, ambiguous, or not-found coverage. |
| Inspection area | `area`, `reason`, `trigger`, `inspection_refs`, `search_terms`, truncation metadata | Structured source-inspection guidance for bounded or partial packets. `inspection_refs` may be structured `{repo,path,line,symbol,...}` objects; `search_terms` may be scalar or list input but is normalized to strings. Tool-specific aliases such as `source_inspection_areas` may still appear, but the normalized common field is `inspection_areas`. |
| Output budget | `truncated`, `measured_chars`, `max_chars`, `omitted_counts`, `truncated_sections`, `advice`, `fallback`, `minimized`, optional `backfilled_counts`, `remaining_chars`, `exceeded_after_minimization` | Explains what was compacted and how much detail was restored under budget. When rows are omitted, the packet should include inspection guidance rather than only an omitted count. |

Common packet example:

```json
{
  "tool": "reverse_impact",
  "status": "partial",
  "proven_facts": {"status": "found", "sources": [{"field": "roots", "count": 1}]},
  "candidate_leads": {"status": "found", "sources": [{"field": "terminal_import_consumer_leads", "count": 2, "lead_kind": "import_only_source_lead"}]},
  "coverage_gaps": [{"trigger": "missing_fact_family", "fact_family": "reverse_callers"}],
  "inspection_areas": [{"area": "candidate_leads", "reason": "Candidate leads require source verification before final claims.", "trigger": "candidate_leads_present", "inspection_refs": [], "search_terms": []}]
}
```

## Budgeted / Compact Packet Contract

Budgeting is currently enforced for `planning_context`, with reusable compaction helpers in `source/kg/product/output_budget.py`.

When a packet is too large:

- Return the best head-start rows that fit within the budget.
- Preserve concrete inspection guidance for omitted rows through `inspection_areas`, using `inspection_refs` and `search_terms` whenever available.
- Use remaining budget to backfill additional compact rows instead of stopping after the first coarse truncation.
- Never rely on an omitted-row count alone; counts without refs or search terms are not useful to an agent.

Budgeted `related_facts` sections are allowlisted so unknown sections do not pass through raw oversized payloads. Current sections are `service_brief`, `symbol_impact`, `dependency_importers`, `inventory`, `service_operational_surfaces`, `runtime_architecture`, `authz_surface`, `dependencies`, `endpoints`, `endpoint_consumers`, `event_channels`, `candidate_or_unlinked_event_channels`, `deploy_mappings`, and `domains`.

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
| `event_channels` | Known linked `CONSUMES_EVENT` / `PRODUCES_EVENT` rows touching the service. |
| `candidate_or_unlinked_event_channels` | Candidate or reference event-channel rows touching the service; use as inspection leads, not known event flow. |
| `deploy_mappings` | `ROUTES_DOMAIN_TO_DEPLOY` and `DEPLOYS_VIA_CONFIG` rows touching the service. |
| `endpoint_consumers` | Static path/method-matched inbound endpoint consumer packet. |
| `operational_surfaces` | Service deploy/domain/runtime surfaces split into known linked, unlinked evidence, and missing contracts. |
| `authz_surface` | Endpoint-to-handler authz packet for the service repo when available. |
| `answerability` | Whether linked service facts are enough and which fact families are missing. |

Example:

```json
{"service": {"name": "api", "repo": "backend"}, "summary": {"endpoint_fact_count": 8, "deploy_mapping_count": 1}, "answerability": {"status": "answerable"}}
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

Prompt usage: tool description says ambiguous empty `callers` is not absence; retry with `disambiguation.retry_arguments` or inspect `import_consumer_leads`.

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
| `candidate_impact_previews` | Ambiguous-candidate previews ranked by direct caller count and stable tie-breakers. `selection_basis` explains whether constructor targets were included, so preview counts may differ from exact `find_callers`. |
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

Prompt usage: skills and MCP instructions tell agents to use this instead of chaining `find_callers`, use `candidate_impact_previews` on ambiguity, and verify `source_inspection_areas`.

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
| `answerability` | Static-event scope, missing fact families, and runtime claims it cannot prove. |
| `consumers` | `CONSUMES_EVENT` fact rows. |

Example:

```json
{"status": "found", "channel": "queue-name", "event_fact_count": 2, "consumers": [{"predicate": "CONSUMES_EVENT"}]}
```

Prompt usage: skills say static event facts cannot prove time-window usage or zero runtime consumers.

### `get_event_producers`

Purpose: static producers of an event channel.

| Field | Definition |
|---|---|
| `channel` | Event channel query string. |
| `event_fact_count` | Number of matching static event facts. |
| `returned_count` | Number returned after `limit`. |
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
| `services`, `symbols`, `dependencies`, `endpoints`, `endpoint_consumers`, `event_channels`, `candidate_or_unlinked_event_channels`, `domains` | Bounded grouped rows matching the anchors. `event_channels` is known linked; `candidate_or_unlinked_event_channels` is inspection-only. |
| `entry_points` | Compact service/symbol/endpoint/event/domain entry rows for scanning. |
| `related_facts` | Anchor-specific packets such as `dependency_importers`, `symbol_impact`, `authz_surface`, runtime references, dependencies, endpoints, endpoint consumers, event channels, deploy mappings, and domains. In compacted packets it may contain its own `inspection_areas` for omitted related rows. |
| `source_coordinates` | Bounded coordinates extracted from grouped rows. |
| `answerability` | Missing fact families and follow-up checks for the supplied anchors. |
| `evidence` | Evidence rows from grouped context. |
| `output_budget` | Added by budget enforcement when output was compacted/truncated; includes omitted sections/counts, budget advice, backfill counts, and remaining character budget when available. |

Example:

```json
{
  "tool": "planning_context",
  "status": "found",
  "anchors": {"repo": "backend", "symbol": null},
  "runtime_architecture": {"answer_packet": {"investigation_brief": {"recommended_source_checks": []}}}
}
```

Prompt usage: skills say call this first for broad planning/runtime/domain/dependency questions, then inspect `answerability`, `runtime_architecture.answer_packet.investigation_brief`, `service_operational_surfaces`, `authz_surface`, and `related_facts.symbol_impact.reverse_impact` as applicable.

Important compact-packet usage: if `output_budget.truncated` is true, use returned rows as the head start and then follow `inspection_areas` or `runtime_architecture.answer_packet.investigation_brief.recommended_source_checks` for omitted detail. Do not treat missing rows in a compacted section as absence.

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
| `runtime_surfaces` | Bounded endpoints, endpoint consumers, known linked event channels, candidate/unlinked event-channel leads, and deploy mappings. |
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

Prompt usage: skills say read `review_answer_packet` first, keep `changed_symbols` distinct from `changed_file_symbols`, and pass `requested_surfaces` when the user names impact categories.

## Known Duplication / Normalization Notes

- `inspection_areas` is now the normalized common follow-up field. It is assembled from tool-specific inspection rows, `source_inspection_areas`, answerability follow-ups, next actions, runtime investigation briefs, and nested authz/review inspection rows when present.
- Tool-specific fields such as `reverse_impact.source_inspection_areas`, `authz_surface.inspection_areas`, and `runtime_architecture.answer_packet.investigation_brief` remain for compatibility and richer domain detail, but prompt and skill text should prefer the common `inspection_areas` field when choosing what source to inspect next.
- `proven_facts`, `candidate_leads`, and `coverage_gaps` are normalized indexes, not replacements for the detailed tool fields. Cite detailed rows/evidence coordinates in final answers.
- Counted normalized indexes fail closed when possible: if a field says `caller_count: 10` but the corresponding row list is empty, the common index should not count it as ten returned facts.
- `candidate_leads` includes top-level lead fields and selected nested lead fields, including operational unlinked evidence, application cross-repo name leads, and runtime unlinked leads.
- `direct_callers` and `direct_callers_of_changed_symbols` are aliases in `review_context`; same for `direct_callees` and `direct_callees_from_changed_symbols`.
- `unsupported_scopes` and `unsupported_review_scopes` duplicate review gaps for compatibility.
- `output_budget` appears only after planning-context budget enforcement and should be treated as metadata about omitted/compacted sections, not source evidence. The preferred behavior is "best rows plus inspection guidance for omitted rows," not "top rows plus an opaque omitted count."
