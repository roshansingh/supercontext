# Trace Analysis - search-read-guard-full18-reuseoff-2026-06-01 - 2026-06-01

## Current Validation Status

This run completed the `search-read-guard-full18-reuseoff-2026-06-01` A/B measurement: 18 paired tasks, 36 Claude Code host runs, local SuperContext MCP server, LangSmith upload, pulled traces, paired deltas, and blinded quality judging.

The product signal is rubric-based, not a single scoreboard. Quality comes first: the judge preferred `mcp_off` overall on 6 tasks, `mcp_on` on 10 tasks, and marked 2 ties. A cost, token, or latency win matters only after answer quality is at least tied.

| Phase | mcp_off wins | mcp_on wins | Ties |
|---|---:|---:|---:|
| coding | 0 | 2 | 2 |
| planning | 5 | 3 | 0 |
| review | 1 | 5 | 0 |

| Quality Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 6 | 10 | 2 | 0 |
| evidence | 6 | 12 | 0 | 0 |
| completeness | 8 | 10 | 0 | 0 |
| actionability | 8 | 9 | 1 | 0 |

## Strongest Product-Value Signal

Cost data was available for 18 of 18 rows. Token data was available for 18 of 18 rows. Aggregate deltas use `off_minus_on`, so positive values mean SuperContext used less of that resource than the non-MCP arm.

- Total dollar delta: `0.673056` in favor of `mcp_on` overall. This is `n/a` unless every paired row has cost data.
- Total token delta: `119524` in favor of `mcp_on` overall. This is `n/a` unless every paired row has token data.
- Positive dollar deltas appeared on 13 of 18 cost-available rows.

This says MCP improved judged answer quality on more tasks and can reduce spend or tokens in many cases. That is a positive product signal, but the task-level losses still gate any broad rollout claim.

## Weakest Blocking Gap

The blocking gap is consistency, not trace capture. The installed skill and MCP server were available, but `mcp_on` did not win 8 of 18 judged tasks, and 1 `mcp_on` rows made zero MCP calls. The next work should classify the loss/tie rows before optimizing cost or latency.

The report also shows aggregate tool-use behavior: total tool-call delta was `179`, so `mcp_on` used fewer tool calls overall.

## Where MCP Helped

`mcp_on` won on Q016, Q037, Q081, Q054, Q048, Q053, Q040, Q021, Q004, Q015. These should be inspected first because they are the success cases that show when the MCP surface is adding value.

## Where MCP Hurt

`mcp_off` won on Q038, Q045, Q011, Q031, Q110, Q035. These are the priority failure cases. Do not optimize tokens or costs until these quality losses are understood.

## Next Recommended PR

Add a trace-inspection report that classifies each `mcp_on` loss into one of these buckets without using repo-specific keyword rules:

- MCP not used early enough
- MCP returned insufficient/ambiguous context
- MCP result was ignored or contradicted by later source search
- agent over-trusted partial KG context
- ordinary source search found evidence missing from KG

Expected movement: after classification, choose one repeated failure family and fix either host skill guidance, MCP response shape, or KG retrieval. Verification should rerun `search-read-guard-full18-reuseoff-2026-06-01` and require quality movement first, with token/cost deltas reported only after quality is not worse.

## Verification Commands

```bash
.venv/bin/python -m source.scripts.pull_ab_traces --project supercontext-ab-eval --run-group-ids <18-run-group-ids> --limit 100 --out data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/traces.jsonl
.venv/bin/python -m source.scripts.compute_ab_deltas --traces data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/traces.jsonl --out data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/deltas.jsonl
.venv/bin/python -m source.scripts.judge_ab_quality --judge-model gpt-5.4-mini --deltas data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/deltas.jsonl --out data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/judged-deltas.jsonl --seed 119
.venv/bin/python -m source.scripts.aggregate_ab_report --deltas data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/judged-deltas.jsonl --out data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/report
.venv/bin/python -m source.scripts.sanitize_ab_report --judged-deltas data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/judged-deltas.jsonl --raw-report data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/report/ab-report.json --out docs/evaluation/ab-runs/search-read-guard-full18-reuseoff-2026-06-01 --run-id search-read-guard-full18-reuseoff-2026-06-01 --date 2026-06-01 --judge-model gpt-5.4-mini --seed 119
```
