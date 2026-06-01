# SuperContext A/B Report - search-read-guard-full18-reuseoff-2026-06-01 - 2026-06-01

Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than `mcp_off`; negative values mean `mcp_on` used more.

This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, and downloaded traces remain under ignored `data/ab_runs/search-read-guard-full18-reuseoff-2026-06-01/`.

## Summary

- Tasks: 18 paired tasks / 36 host runs
- Quality judge: `gpt-5.4-mini`, blinded A/B answer order, seed `119`
- Overall quality winners: `mcp_off=6`, `mcp_on=10`, `tie=2`
- Quality gate: answer quality must be at least tied before token, cost, or latency wins matter.
- Cost availability: `{'available': 18}`

## Rubric Summary

| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 6 | 10 | 2 | 0 |
| evidence | 6 | 12 | 0 | 0 |
| completeness | 8 | 10 | 0 | 0 |
| actionability | 8 | 9 | 1 | 0 |

## Per Task

| Task | Phase | Difficulty | Overall | Correctness | Evidence | Completeness | Actionability | MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Q016 | coding | Medium | mcp_on (0.9) | mcp_on | mcp_on | mcp_on | mcp_on | 2 | 0 | -2 | -1952 | -0.022464 | -21.566 |
| Q037 | review | Hard | mcp_on (0.96) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 42 | 27919 | 0.169269 | 198.815 |
| Q081 | planning | Hard | mcp_on (0.97) | mcp_on | mcp_on | mcp_on | mcp_on | 7 | 0 | 52 | 6042 | 0.081702 | 43.96 |
| Q003 | coding | Low | tie (0.9) | tie | mcp_on | mcp_on | tie | 1 | 0 | 7 | 2021 | 0.028539 | 60.894 |
| Q054 | planning | Medium | mcp_on (0.93) | mcp_on | mcp_on | mcp_on | mcp_on | 0 | 0 | 0 | 217 | 0.003255 | 6.851 |
| Q048 | review | Hard | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 2 | 0 | 2 | 11031 | 0.030705 | 4.465 |
| Q038 | planning | Hard | mcp_off (0.91) | mcp_off | mcp_on | mcp_on | mcp_on | 2 | 0 | 3 | 8164 | 0.021156 | -26.142 |
| Q051 | coding | Medium | tie (0.72) | tie | mcp_off | mcp_off | mcp_off | 1 | 0 | -6 | -848 | -0.00798 | 17.805 |
| Q045 | planning | Hard | mcp_off (0.91) | mcp_off | mcp_off | mcp_off | mcp_off | 4 | 0 | 10 | 17037 | 0.117711 | 136.809 |
| Q011 | planning | Low | mcp_off (0.93) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | -7 | -1491 | -0.020385 | -40.626 |
| Q053 | review | Hard | mcp_on (0.86) | mcp_on | mcp_on | mcp_off | mcp_off | 1 | 0 | 24 | 16407 | 0.075189 | -1.77 |
| Q031 | planning | Medium | mcp_off (0.87) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 13 | 21914 | 0.090366 | 56.501 |
| Q040 | review | Hard | mcp_on (0.93) | mcp_on | mcp_on | mcp_on | mcp_on | 2 | 0 | 5 | 13954 | 0.108498 | 73.499 |
| Q021 | review | Medium | mcp_on (0.9) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | -5 | -5371 | -0.050505 | -39.851 |
| Q110 | review | Hard | mcp_off (0.91) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 11 | 1413 | 0.006255 | -11.537 |
| Q004 | coding | Low | mcp_on (0.98) | mcp_on | mcp_on | mcp_off | mcp_off | 2 | 0 | 3 | 393 | 0.005715 | 12.441 |
| Q015 | planning | Low | mcp_on (0.96) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 19 | 2677 | 0.037287 | 46.253 |
| Q035 | planning | Medium | mcp_off (0.97) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 8 | -3 | -0.001257 | 2.627 |

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | 0.5 | -96.5 | 17.394 |
| planning | 8 | 12.25 | 6819.625 | 28.279 |
| review | 6 | 13.167 | 10892.167 | 37.27 |
