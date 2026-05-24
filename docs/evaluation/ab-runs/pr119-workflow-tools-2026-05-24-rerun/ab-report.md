# SuperContext A/B Report - pr119-workflow-tools-2026-05-24-rerun - 2026-05-24

Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than `mcp_off`; negative values mean `mcp_on` used more.

This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, and downloaded traces remain under ignored `data/ab_runs/pr119-workflow-tools-2026-05-24-rerun/`.

## Summary

- Tasks: 18 paired tasks / 36 host runs
- Quality judge: `gpt-4.1-mini`, blinded A/B answer order, seed `119`
- Overall quality winners: `mcp_off=9`, `mcp_on=4`, `tie=5`
- Quality gate: answer quality must be at least tied before token, cost, or latency wins matter.
- Cost availability: `{'available': 18}`

## Rubric Summary

| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 9 | 4 | 5 | 0 |
| evidence | 10 | 2 | 6 | 0 |
| completeness | 7 | 4 | 7 | 0 |
| actionability | 9 | 4 | 5 | 0 |

## Per Task

| Task | Phase | Difficulty | Overall | Correctness | Evidence | Completeness | Actionability | MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Q004 | coding | Low | tie (0.9) | tie | mcp_on | tie | mcp_off | 1 | 0 | -1 | -518 | -0.00771 | -19.798 |
| Q015 | planning | Low | mcp_off (0.9) | mcp_off | mcp_off | tie | tie | 2 | 0 | 7 | 689 | 0.010155 | -28.995 |
| Q053 | review | Hard | mcp_off (0.95) | mcp_off | mcp_off | tie | mcp_off | 7 | 0 | 13 | 10035 | 0.023085 | -48.746 |
| Q045 | planning | Hard | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 2 | 0 | 0 | 3410 | 0.050994 | -5.665 |
| Q040 | review | Hard | mcp_on (0.95) | mcp_on | mcp_off | mcp_on | mcp_on | 4 | 0 | 20 | 21989 | 0.229107 | 255.676 |
| Q054 | planning | Medium | tie (0.9) | tie | tie | tie | tie | 0 | 0 | 0 | -494 | -0.00741 | -10.752 |
| Q048 | review | Hard | mcp_off (0.9) | mcp_off | mcp_off | mcp_on | mcp_off | 4 | 0 | 3 | 10227 | 0.024801 | -21.784 |
| Q011 | planning | Low | mcp_on (0.9) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 4 | -70 | -0.00165 | -0.973 |
| Q037 | review | Hard | mcp_on (0.95) | mcp_on | mcp_off | mcp_off | mcp_on | 3 | 0 | 22 | 3162 | 0.046098 | 85.798 |
| Q051 | coding | Medium | tie (0.9) | tie | tie | tie | tie | 1 | 0 | 11 | 12015 | 0.050565 | 17.165 |
| Q081 | planning | Hard | mcp_off (0.95) | mcp_off | tie | mcp_off | mcp_off | 14 | 0 | 26 | 15836 | 0.075324 | 24.475 |
| Q016 | coding | Medium | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 7 | 0 | 8 | 565 | 0.006783 | 43.913 |
| Q035 | planning | Medium | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 4 | 0 | 13 | 15757 | 0.075063 | 58.11 |
| Q003 | coding | Low | mcp_off (0.95) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 14 | 3540 | 0.049524 | 61.088 |
| Q110 | review | Hard | mcp_on (0.9) | mcp_on | tie | tie | tie | 13 | 0 | -23 | -5995 | -0.086121 | -108.24 |
| Q031 | planning | Medium | tie (0.9) | tie | mcp_off | mcp_off | mcp_on | 2 | 0 | 19 | 16241 | 0.081651 | 70.119 |
| Q021 | review | Medium | mcp_off (0.9) | mcp_off | tie | mcp_on | mcp_off | 8 | 0 | -3 | -787 | -0.012297 | 13.747 |
| Q038 | planning | Hard | tie (0.9) | tie | tie | tie | tie | 2 | 0 | 26 | 17314 | 0.086046 | 27.214 |

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | 8 | 3900.5 | 25.592 |
| planning | 8 | 11.875 | 8585.375 | 16.692 |
| review | 6 | 5.333 | 6438.5 | 29.408 |
