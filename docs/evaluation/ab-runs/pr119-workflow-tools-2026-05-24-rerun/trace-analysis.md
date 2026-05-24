# Trace Analysis - pr119-workflow-tools-2026-05-24-rerun - 2026-05-24

## Current Validation Status

This run completed the `pr119-workflow-tools-2026-05-24-rerun` A/B measurement: 18 paired tasks, 36 Claude Code host runs, local SuperContext MCP server, LangSmith upload, pulled traces, paired deltas, and blinded quality judging.

The product signal is rubric-based, not a single scoreboard. Quality comes first: the judge preferred `mcp_off` overall on 9 tasks, `mcp_on` on 4 tasks, and marked 5 ties. A cost, token, or latency win matters only after answer quality is at least tied.

| Phase | mcp_off wins | mcp_on wins | Ties |
|---|---:|---:|---:|
| coding | 2 | 0 | 2 |
| planning | 4 | 1 | 3 |
| review | 3 | 3 | 0 |

| Quality Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 9 | 4 | 5 | 0 |
| evidence | 10 | 2 | 6 | 0 |
| completeness | 7 | 4 | 7 | 0 |
| actionability | 9 | 4 | 5 | 0 |

## Strongest Product-Value Signal

Cost data was available for 18 of 18 rows. Token data was available for 18 of 18 rows. Aggregate deltas use `off_minus_on`, so positive values mean SuperContext used less of that resource than the non-MCP arm.

- Total dollar delta: `0.694008` in favor of `mcp_on` overall. This is `n/a` unless every paired row has cost data.
- Total token delta: `122916` in favor of `mcp_on` overall. This is `n/a` unless every paired row has token data.
- Positive dollar deltas appeared on 13 of 18 cost-available rows.

This says MCP can reduce spend or tokens in some cases, but that signal is secondary because `mcp_off` won judged answer quality on more tasks.

## Weakest Blocking Gap

The blocking gap is skill/tool adoption quality, not trace capture. The installed skill and MCP server were available, but `mcp_on` only won 4 of 18 judged tasks, and 1 `mcp_on` row made zero MCP calls. The likely failure pattern is that the host either used MCP too late, accepted partial KG context, or found better evidence through ordinary source inspection.

The report also shows aggregate tool-use behavior: total tool-call delta was `159`, so `mcp_on` used fewer tool calls overall.

## PR1.5 Gate Check

The workflow-tool priority experiment failed the neutral-eval promotion gate. It should not replace `main` as-is.

| Gate | Required | Observed | Status |
|---|---:|---:|---|
| Overall quality losses | `mcp_off <= 2` | `mcp_off=9`, `mcp_on=4`, `tie=5` | FAIL |
| Workflow-tool successful calls | `planning_context + review_context >= 9` | `10` (`planning_context=7`, `review_context=3`) | PASS |
| Workflow tool used first | `workflow_first_rows >= 9` | `4` | FAIL |
| Zero-MCP rows | `0` | `1` (`Q054`) | FAIL |

Tool-mix diagnostics from raw `record.json` files:

- Successful MCP calls: `get_service_brief=24`, `find_callers=21`, `search_services=9`, `planning_context=7`, `get_event_consumers=6`, `review_context=3`, `get_event_producers=2`, `deploy_blockers_for=2`, `find_callees=1`, `blast_radius=1`.
- First successful MCP tool by row: `search_services=6`, `find_callers=4`, `planning_context=3`, `get_event_consumers=2`, `find_callees=1`, `review_context=1`.
- Zero-MCP row: `Q054`.

This means the combined ordering/description/skill-template change did move workflow tools above the threshold for total successful calls, but it did not make workflow tools the first-class entry point and answer quality regressed versus the adjusted baseline.

## Where MCP Helped

`mcp_on` won on Q040, Q011, Q037, Q110. These should be inspected first because they are the success cases that show when the MCP surface is adding value.

## Where MCP Hurt

`mcp_off` won on Q015, Q053, Q045, Q048, Q081, Q016, Q035, Q003, Q021. These are the priority failure cases. Do not optimize tokens or costs until these quality losses are understood.

## Next Recommended PR

Because the combined PR1.5 branch failed and usage movement is not clean, do not promote the neutral eval branch to `main`. The next narrow step is to split or roll back the surface experiment before more capability work:

- Revert PR1.5 from the neutral eval branch, then continue with the next already-planned non-surface slot; or
- Create a focused follow-up that isolates registry order from description/template wording and reruns the same gate before any main replacement decision.

For whichever path is chosen, add a trace-inspection report that classifies each `mcp_on` loss into one of these buckets without using repo-specific keyword rules:

- MCP not used early enough
- MCP returned insufficient/ambiguous context
- MCP result was ignored or contradicted by later source search
- agent over-trusted partial KG context
- ordinary source search found evidence missing from KG

Expected movement: after classification, choose one repeated failure family and fix either host skill guidance, MCP response shape, or KG retrieval. Verification should rerun `pr119-workflow-tools-2026-05-24-rerun` and require quality movement first, with token/cost deltas reported only after quality is not worse.

## Verification Commands

```bash
.venv/bin/python -m source.scripts.pull_ab_traces --project supercontext-ab-eval --run-group-ids <18-run-group-ids> --limit 100 --out data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/traces.jsonl
.venv/bin/python -m source.scripts.compute_ab_deltas --traces data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/traces.jsonl --out data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/deltas.jsonl
.venv/bin/python -m source.scripts.judge_ab_quality --judge-model gpt-4.1-mini --deltas data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/deltas.jsonl --out data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/judged-deltas.jsonl --seed 119
.venv/bin/python -m source.scripts.aggregate_ab_report --deltas data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/judged-deltas.jsonl --out data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/report
.venv/bin/python -m source.scripts.sanitize_ab_report --judged-deltas data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/judged-deltas.jsonl --raw-report data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/report/ab-report.json --out docs/evaluation/ab-runs/pr119-workflow-tools-2026-05-24-rerun --run-id pr119-workflow-tools-2026-05-24-rerun --date 2026-05-24 --judge-model gpt-4.1-mini --seed 119
```
