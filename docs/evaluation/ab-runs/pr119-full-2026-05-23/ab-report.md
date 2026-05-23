# BetterContext A/B Report - pr119-full-2026-05-23 - 2026-05-23

Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than `mcp_off`; negative values mean `mcp_on` used more.

This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, and downloaded traces remain under ignored `data/ab_runs/pr119-full-2026-05-23/`.

## Summary

- Tasks: 18 paired tasks / 36 host runs
- Quality judge: `gpt-4.1-mini`, blinded A/B answer order, seed `119`
- Overall quality winners: `mcp_off=4`, `mcp_on=11`, `tie=3`
- Quality gate: answer quality must be at least tied before token, cost, or latency wins matter.
- Cost availability: `{'available': 18}`

## Rubric Summary

| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 4 | 11 | 3 | 0 |
| evidence | 3 | 13 | 2 | 0 |
| completeness | 4 | 9 | 5 | 0 |
| actionability | 4 | 11 | 3 | 0 |

## Per Task

| Task | Phase | Difficulty | Overall | Correctness | Evidence | Completeness | Actionability | MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Q053 | review | Hard | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 7 | 0 | 3 | 12763 | 0.059793 | 21.245 |
| Q016 | coding | Medium | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 5 | 0 | 19 | 3304 | 0.045432 | 74.474 |
| Q048 | review | Hard | tie (0.9) | tie | tie | tie | tie | 5 | 0 | -9 | 8100 | 0.02358 | 19.139 |
| Q035 | planning | Medium | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 3 | 0 | -14 | -2580 | -0.034452 | -69.58 |
| Q003 | coding | Low | mcp_off (0.9) | mcp_off | mcp_on | mcp_on | mcp_off | 2 | 0 | 11 | 984 | 0.012756 | 28.029 |
| Q031 | planning | Medium | mcp_on (0.9) | mcp_on | mcp_on | tie | mcp_on | 2 | 0 | 2 | -50 | -0.00051 | 8.267 |
| Q004 | coding | Low | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 3 | 723 | 0.009933 | 27.269 |
| Q038 | planning | Hard | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 2 | 0 | -2 | -1306 | -0.017922 | -40.097 |
| Q015 | planning | Low | mcp_off (0.9) | mcp_off | mcp_off | tie | mcp_off | 1 | 0 | 2 | 13266 | 0.067494 | 7.499 |
| Q054 | planning | Medium | mcp_on (0.9) | mcp_on | mcp_on | mcp_on | mcp_on | 0 | 0 | 0 | -447 | -0.006705 | -8.394 |
| Q045 | planning | Hard | mcp_on (0.9) | mcp_on | tie | mcp_on | mcp_on | 3 | 0 | 5 | 9398 | 0.04101 | 240.691 |
| Q040 | review | Hard | mcp_on (0.9) | mcp_on | mcp_on | mcp_off | mcp_on | 4 | 0 | 3 | 5688 | 0.013848 | 0.025 |
| Q011 | planning | Low | mcp_on (0.9) | mcp_on | mcp_on | mcp_off | mcp_on | 3 | 0 | 5 | 920 | 0.012972 | 21.415 |
| Q037 | review | Hard | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 0 | 0 | 9 | 18233 | 0.080559 | 17.038 |
| Q110 | review | Hard | mcp_on (0.9) | mcp_on | mcp_on | tie | mcp_on | 6 | 0 | 6 | -221 | -0.004023 | -7.691 |
| Q051 | coding | Medium | tie (0.9) | tie | mcp_on | tie | tie | 2 | 0 | -10 | -13089 | -0.062163 | -328.292 |
| Q081 | planning | Hard | tie (0.85) | tie | mcp_on | mcp_on | mcp_on | 6 | 0 | 12 | 15690 | 0.067806 | 39.893 |
| Q021 | review | Medium | mcp_on (0.9) | mcp_on | mcp_on | mcp_on | tie | 3 | 0 | 24 | 11922 | 0.074358 | 105.714 |

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | 5.75 | -2019.5 | -49.63 |
| planning | 8 | 1.25 | 4361.375 | 24.962 |
| review | 6 | 6 | 9414.167 | 25.912 |
