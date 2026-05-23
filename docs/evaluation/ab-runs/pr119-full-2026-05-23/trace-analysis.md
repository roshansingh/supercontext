# Trace Analysis - pr119-full-2026-05-23 - 2026-05-23

## Current Validation Status

This run completed the `pr119-full-2026-05-23` A/B measurement: 18 paired tasks, 36 Claude Code host runs, local SuperContext MCP server, LangSmith upload, pulled traces, paired deltas, and blinded quality judging.

The product signal is rubric-based, not a single scoreboard. Quality comes first: the judge preferred `mcp_off` overall on 4 tasks, `mcp_on` on 11 tasks, and marked 3 ties. A cost, token, or latency win matters only after answer quality is at least tied.

| Phase | mcp_off wins | mcp_on wins | Ties |
|---|---:|---:|---:|
| coding | 1 | 2 | 1 |
| planning | 2 | 5 | 1 |
| review | 1 | 4 | 1 |

| Quality Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 4 | 11 | 3 | 0 |
| evidence | 3 | 13 | 2 | 0 |
| completeness | 4 | 9 | 5 | 0 |
| actionability | 4 | 11 | 3 | 0 |

## Strongest Product-Value Signal

Cost data was available for 18 of 18 rows. Token data was available for 18 of 18 rows. Aggregate deltas use `off_minus_on`, so positive values mean SuperContext used less of that resource than the non-MCP arm.

- Total dollar delta: `0.383766` in favor of `mcp_on` overall. This is `n/a` unless every paired row has cost data.
- Total token delta: `83298` in favor of `mcp_on` overall. This is `n/a` unless every paired row has token data.
- Positive dollar deltas appeared on 12 of 18 cost-available rows.

This says MCP improved judged answer quality on more tasks and can reduce spend or tokens in many cases. That is a positive product signal, but the task-level losses still gate any broad rollout claim.

## Weakest Blocking Gap

The blocking gap is consistency, not trace capture. The installed skill and MCP server were available, but `mcp_on` did not win 7 of 18 judged tasks, and 2 `mcp_on` rows made zero MCP calls. The next work should classify the loss/tie rows before optimizing cost or latency.

The report also shows aggregate tool-use behavior: total tool-call delta was `69`, so `mcp_on` used fewer tool calls overall.

## Where MCP Helped

`mcp_on` won on Q053, Q016, Q031, Q004, Q038, Q054, Q045, Q040, Q011, Q110, Q021. These should be inspected first because they are the success cases that show when the MCP surface is adding value.

## Where MCP Hurt

`mcp_off` won on Q035, Q003, Q015, Q037. These are the priority failure cases. Do not optimize tokens or costs until these quality losses are understood.

## Next Recommended PR

Add a trace-inspection report that classifies each `mcp_on` loss into one of these buckets without using repo-specific keyword rules:

- MCP not used early enough
- MCP returned insufficient/ambiguous context
- MCP result was ignored or contradicted by later source search
- agent over-trusted partial KG context
- ordinary source search found evidence missing from KG

Expected movement: after classification, choose one repeated failure family and fix either host skill guidance, MCP response shape, or KG retrieval. Verification should rerun `pr119-full-2026-05-23` and require quality movement first, with token/cost deltas reported only after quality is not worse.

## Verification Commands

```bash
.venv/bin/python -m source.scripts.pull_ab_traces --project supercontext-ab-eval --run-group-ids <18-run-group-ids> --limit 100 --out data/ab_runs/pr119-full-2026-05-23/traces.jsonl
.venv/bin/python -m source.scripts.compute_ab_deltas --traces data/ab_runs/pr119-full-2026-05-23/traces.jsonl --out data/ab_runs/pr119-full-2026-05-23/deltas.jsonl
.venv/bin/python -m source.scripts.judge_ab_quality --judge-model gpt-4.1-mini --deltas data/ab_runs/pr119-full-2026-05-23/deltas.jsonl --out data/ab_runs/pr119-full-2026-05-23/judged-deltas.jsonl --seed 119
.venv/bin/python -m source.scripts.aggregate_ab_report --deltas data/ab_runs/pr119-full-2026-05-23/judged-deltas.jsonl --out data/ab_runs/pr119-full-2026-05-23/report
.venv/bin/python -m source.scripts.sanitize_ab_report --judged-deltas data/ab_runs/pr119-full-2026-05-23/judged-deltas.jsonl --raw-report data/ab_runs/pr119-full-2026-05-23/report/ab-report.json --out docs/evaluation/ab-runs/pr119-full-2026-05-23 --run-id pr119-full-2026-05-23 --date 2026-05-23 --judge-model gpt-4.1-mini --seed 119
```
