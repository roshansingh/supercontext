# pr119-full-2026-05-23 Non-Win Classification

Generated from the sanitized pr119-full-2026-05-23 A/B report plus available local raw records.

## Sources

- Report JSON: `docs/evaluation/ab-runs/pr119-full-2026-05-23/ab-report.json`
- Report JSON sha256: `19e1611f2475e9ff850cfb67e8fcfac88c9bb1c2190600386ed58f42599a5e02`
- Report Markdown: `docs/evaluation/ab-runs/pr119-full-2026-05-23/ab-report.md`
- Raw root: `data/ab_runs/pr119-full-2026-05-23`

## Baseline

| Winner | Count |
|---|---:|
| `mcp_off` | 4 |
| `mcp_on` | 11 |
| `tie` | 3 |

## Non-Win Rows

| Task | Phase | Winner | Confidence | Raw | MCP Tools | Non-MCP Tools | Bucket | Post-pr119 |
|---|---|---|---:|---|---:|---:|---|---|
| Q048 | review | `tie` | 0.9 | missing | 5 | n/a | Acceptable tie |  |
| Q035 | planning | `mcp_off` | 0.95 | available | 3 | 24 | Real MCP quality loss: missing KG fact / retrieval gap |  |
| Q003 | coding | `mcp_off` | 0.9 | available | 2 | 8 | Real MCP quality loss: symbol-resolution gap | fixed_win |
| Q015 | planning | `mcp_off` | 0.9 | available | 1 | 18 | Synthesis / report consistency issue |  |
| Q037 | review | `mcp_off` | 0.95 | available | 0 | 29 | Eval task-input problem / inconclusive MCP loss | fixed_tie |
| Q051 | coding | `tie` | 0.9 | available | 2 | 41 | Acceptable tie, resource-heavy |  |
| Q081 | planning | `tie` | 0.85 | missing | 6 | n/a | Mostly positive tie |  |

## Non-Win Evidence

### Q048

- Result: `tie` with confidence 0.9.
- Report classification: Acceptable tie.
- Report summary: `mcp_on` used 5 MCP calls. Both arms handled partial evidence and explicit refusal for uninstrumented scope.
- Raw evidence status: `missing`.
- MCP tools called: none.
- Non-MCP tools called: none.

### Q035

- Result: `mcp_off` with confidence 0.95.
- Report classification: Real MCP quality loss: missing KG fact / retrieval gap.
- Report summary: `mcp_on` used SuperContext but concluded the KG could not prove Kubernetes deployables. `mcp_off` found manifest-level deployment mappings through ordinary source search. The immediate issue is that the KG/tool path did not expose the deployable facts needed for this question, and the agent used service-oriented MCP calls instead of a deploy-specific path.
- Raw evidence status: `available`.
- Raw record: `data/ab_runs/pr119-full-2026-05-23/20f1df23-8220-46b8-ba58-4367f156b369/mcp_on/record.json`.
- Raw messages: `data/ab_runs/pr119-full-2026-05-23/20f1df23-8220-46b8-ba58-4367f156b369/mcp_on/messages.jsonl`.
- MCP tools called: `mcp__supercontext__get_service_brief`, `mcp__supercontext__search_services`.
- Non-MCP tools called: `Bash`, `Grep`, `Read`, `ToolSearch`.

### Q003

- Result: `mcp_off` with confidence 0.9.
- Report classification: Real MCP quality loss: symbol-resolution gap.
- Report summary: `mcp_on` returned ambiguous or fuzzy `load_model` candidates and included unrelated matches. `mcp_off` found the concrete `pycaret.load_model` call sites by source inspection. This points to retrieval/symbol resolution behavior, not MCP availability.
- Raw evidence status: `available`.
- Raw record: `data/ab_runs/pr119-full-2026-05-23/213f622c-00fb-4e85-a07a-53ef10f1f251/mcp_on/record.json`.
- Raw messages: `data/ab_runs/pr119-full-2026-05-23/213f622c-00fb-4e85-a07a-53ef10f1f251/mcp_on/messages.jsonl`.
- MCP tools called: `mcp__supercontext__find_callers`.
- Non-MCP tools called: `Grep`, `Read`, `ToolSearch`.
- Post-pr119 evidence: data/ab_runs/q003-exact-symbol-2026-05-23/judged-deltas.jsonl: judge_winner=mcp_on; judge_confidence=0.95; on.mcp_tools_called=['mcp__supercontext__find_callers']; on.mcp_tool_attempt_count=1.

### Q015

- Result: `mcp_off` with confidence 0.9.
- Report classification: Synthesis / report consistency issue.
- Report summary: Both arms summarized KG inventory. `mcp_on` was more concise but had internal inconsistencies/noisier claims in counts and coverage phrasing. This is weaker answer synthesis around metrics, not a core MCP transport failure.
- Raw evidence status: `available`.
- Raw record: `data/ab_runs/pr119-full-2026-05-23/59f1569f-bfb3-407b-b3b2-d005ddba41eb/mcp_on/record.json`.
- Raw messages: `data/ab_runs/pr119-full-2026-05-23/59f1569f-bfb3-407b-b3b2-d005ddba41eb/mcp_on/messages.jsonl`.
- MCP tools called: `mcp__supercontext__search_services`.
- Non-MCP tools called: `Bash`, `Read`, `ToolSearch`.

### Q037

- Result: `mcp_off` with confidence 0.95.
- Report classification: Eval task-input problem / inconclusive MCP loss.
- Report summary: The prompt said "Given this PR" but did not provide a concrete PR input shape. `mcp_on` made zero MCP calls and refused because changed files, repo, and diff were missing. `mcp_off` inferred a PR from local context and answered. This row should not be treated as a clean MCP quality loss until the task supplies explicit PR input.
- Raw evidence status: `available`.
- Raw record: `data/ab_runs/pr119-full-2026-05-23/a40a6a84-2a85-4e8f-9d1e-5354595979fe/mcp_on/record.json`.
- Raw messages: `data/ab_runs/pr119-full-2026-05-23/a40a6a84-2a85-4e8f-9d1e-5354595979fe/mcp_on/messages.jsonl`.
- MCP tools called: none.
- Non-MCP tools called: `Bash`, `Glob`, `Grep`, `Read`, `ToolSearch`.
- Post-pr119 evidence: data/ab_runs/q037-fixture-paired-2026-05-23/judged-deltas.jsonl: judge_winner=tie; judge_confidence=0.9; on.mcp_tools_called=['mcp__supercontext__find_callers', 'mcp__supercontext__get_service_brief', 'mcp__supercontext__review_context', 'mcp__supercontext__search_services']; on.mcp_tool_attempt_count=6.

### Q051

- Result: `tie` with confidence 0.9.
- Report classification: Acceptable tie, resource-heavy.
- Report summary: Both arms found the gating truth: promotion logic is not implemented and default behavior does not prove the intended transition. `mcp_on` had stronger evidence, but the core answer was tied and used more tokens/time.
- Raw evidence status: `available`.
- Raw record: `data/ab_runs/pr119-full-2026-05-23/bfcd16d0-355e-4076-8758-953c773ff478/mcp_on/record.json`.
- Raw messages: `data/ab_runs/pr119-full-2026-05-23/bfcd16d0-355e-4076-8758-953c773ff478/mcp_on/messages.jsonl`.
- MCP tools called: `mcp__supercontext__find_callers`.
- Non-MCP tools called: `Bash`, `Grep`, `Read`, `ToolSearch`.

### Q081

- Result: `tie` with confidence 0.85.
- Report classification: Mostly positive tie.
- Report summary: Overall correctness tied, but `mcp_on` won evidence, completeness, and actionability. This is a useful MCP signal even though the overall winner was tie.
- Raw evidence status: `missing`.
- MCP tools called: none.
- Non-MCP tools called: none.

## Win Inventory

Rows preserve the source report order.

| Task | Phase | Confidence | MCP Tool Count | Raw |
|---|---|---:|---:|---|
| Q053 | review | 0.95 | 7 | missing |
| Q016 | coding | 0.95 | 5 | available |
| Q031 | planning | 0.9 | 2 | available |
| Q004 | coding | 0.95 | 1 | available |
| Q038 | planning | 0.95 | 2 | available |
| Q054 | planning | 0.9 | 0 | available |
| Q045 | planning | 0.9 | 3 | missing |
| Q040 | review | 0.9 | 4 | missing |
| Q011 | planning | 0.9 | 3 | available |
| Q110 | review | 0.9 | 6 | missing |
| Q021 | review | 0.9 | 3 | available |
