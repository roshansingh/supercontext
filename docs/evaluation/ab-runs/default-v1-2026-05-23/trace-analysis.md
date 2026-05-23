# Trace Analysis - default-v1-2026-05-23 - 2026-05-23

## Current Validation Status

This run completed the `default-v1-2026-05-23` A/B measurement: 18 paired tasks, 36 Claude Code host runs, local BetterContext MCP server, LangSmith upload, pulled traces, paired deltas, and blinded quality judging.

The product signal is not ready to claim BetterContext improves agent outcomes by default. Quality comes first: the judge preferred `mcp_off` on 11 tasks, `mcp_on` on 3 tasks, and marked 4 ties.

| Phase | mcp_off wins | mcp_on wins | Ties |
|---|---:|---:|---:|
| coding | 3 | 0 | 1 |
| planning | 6 | 2 | 0 |
| review | 2 | 1 | 3 |

## Strongest Product-Value Signal

Cost data was available for 18 of 18 rows. Token data was available for 18 of 18 rows. Aggregate deltas use `off_minus_on`, so positive values mean BetterContext used less of that resource than the non-MCP arm.

- Total dollar delta: `0.884178` in favor of `mcp_on` overall. This is `n/a` unless every paired row has cost data.
- Total token delta: `75446` in favor of `mcp_on` overall. This is `n/a` unless every paired row has token data.
- Positive dollar deltas appeared on 14 of 18 cost-available rows.

This says MCP can reduce spend or tokens in many cases, but that signal is secondary because answer quality was worse on most judged tasks.

## Weakest Blocking Gap

The blocking gap is skill/tool adoption quality, not trace capture. The installed skill and MCP server were available, but `mcp_on` still lost quality on most planning and coding tasks. The likely failure pattern is that the host either overused the MCP packet, used it too late, or accepted partial KG context where ordinary source inspection produced a better answer.

The report also shows `mcp_on` often used more total tool calls despite MCP availability: total tool-call delta was `-19`, where negative means `mcp_on` used more tools.

## Where MCP Helped

`mcp_on` won on Q054, Q048, Q015. These should be inspected first because they are the success cases that show when the MCP surface is adding value.

## Where MCP Hurt

`mcp_off` won on Q045, Q004, Q035, Q031, Q038, Q003, Q011, Q110, Q016, Q040, Q081. These are the priority failure cases. Do not optimize tokens or costs until these quality losses are understood.

## Next Recommended PR

Add a trace-inspection report that classifies each `mcp_on` loss into one of these buckets without using repo-specific keyword rules:

- MCP not used early enough
- MCP returned insufficient/ambiguous context
- MCP result was ignored or contradicted by later source search
- agent over-trusted partial KG context
- ordinary source search found evidence missing from KG

Expected movement: after classification, choose one repeated failure family and fix either host skill guidance, MCP response shape, or KG retrieval. Verification should rerun `default-v1-2026-05-23` and require quality movement first, with token/cost deltas reported only after quality is not worse.

## Verification Commands

```bash
.venv/bin/python -m source.scripts.pull_ab_traces --project bettercontext-ab-eval --run-group-ids <18-run-group-ids> --limit 100 --out data/ab_runs/default-v1-2026-05-23/traces.jsonl
.venv/bin/python -m source.scripts.compute_ab_deltas --traces data/ab_runs/default-v1-2026-05-23/traces.jsonl --out data/ab_runs/default-v1-2026-05-23/deltas.jsonl
.venv/bin/python -m source.scripts.judge_ab_quality --judge-model gpt-4.1-mini --deltas data/ab_runs/default-v1-2026-05-23/deltas.jsonl --out data/ab_runs/default-v1-2026-05-23/judged-deltas.jsonl --seed 6
.venv/bin/python -m source.scripts.aggregate_ab_report --deltas data/ab_runs/default-v1-2026-05-23/judged-deltas.jsonl --out data/ab_runs/default-v1-2026-05-23/report
.venv/bin/python -m source.scripts.sanitize_ab_report --judged-deltas data/ab_runs/default-v1-2026-05-23/judged-deltas.jsonl --raw-report data/ab_runs/default-v1-2026-05-23/report/ab-report.json --out docs/evaluation/ab-runs/default-v1-2026-05-23 --run-id default-v1-2026-05-23 --date 2026-05-23 --judge-model gpt-4.1-mini --seed 6
```
