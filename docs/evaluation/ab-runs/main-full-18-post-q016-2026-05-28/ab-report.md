# SuperContext A/B Report - main-full-18-post-q016-2026-05-28 - 2026-05-28

Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than `mcp_off`; negative values mean `mcp_on` used more.

This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, and downloaded traces remain under ignored `data/ab_runs/main-full-18-post-q016-2026-05-28/`.

## Summary

- Tasks: 18 paired tasks / 36 host runs
- Quality judge: `gpt-5.4-mini`, blinded A/B answer order, seed `119`
- Overall quality winners: `mcp_off=7`, `mcp_on=9`, `tie=2`
- Quality gate: answer quality must be at least tied before token, cost, or latency wins matter.
- Cost availability: `{'available': 18}`

## Rubric Summary

| Aspect | mcp_off wins | mcp_on wins | Ties | Unknown |
|---|---:|---:|---:|---:|
| correctness | 7 | 9 | 2 | 0 |
| evidence | 9 | 9 | 0 | 0 |
| completeness | 10 | 8 | 0 | 0 |
| actionability | 12 | 5 | 1 | 0 |

## Per Task

| Task | Phase | Difficulty | Overall | Correctness | Evidence | Completeness | Actionability | MCP OK | MCP Denied | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |
|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Q031 | planning | Medium | mcp_on (0.95) | mcp_on | mcp_on | mcp_off | mcp_off | 1 | 0 | 14 | 22018 | 0.09279 | 32.22 |
| Q003 | coding | Low | mcp_on (0.89) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 8 | 1880 | 0.026868 | 40.189 |
| Q011 | planning | Low | tie (0.42) | tie | mcp_off | mcp_off | mcp_off | 1 | 0 | 1 | -112 | -0.001632 | -3.808 |
| Q015 | planning | Low | mcp_off (0.98) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 19 | 2715 | 0.037857 | 47.643 |
| Q048 | review | Hard | mcp_on (0.91) | mcp_on | mcp_on | mcp_on | mcp_on | 2 | 0 | -1 | 11039 | 0.031221 | -7.673 |
| Q037 | review | Hard | mcp_on (0.95) | mcp_on | mcp_on | mcp_off | mcp_off | 1 | 0 | 41 | 27981 | 0.170175 | 183.646 |
| Q021 | review | Medium | mcp_on (0.95) | mcp_on | mcp_on | mcp_on | mcp_on | 1 | 0 | 10 | 693 | 0.009099 | 29.825 |
| Q110 | review | Hard | mcp_off (0.93) | mcp_off | mcp_off | mcp_off | mcp_off | 1 | 0 | 3 | -2313 | -0.047619 | -61.861 |
| Q004 | coding | Low | tie (0.78) | tie | mcp_on | mcp_on | tie | 3 | 0 | 3 | 505 | 0.007251 | 14.651 |
| Q053 | review | Hard | mcp_off (0.91) | mcp_off | mcp_off | mcp_on | mcp_off | 1 | 0 | 22 | 15922 | 0.068022 | -13.345 |
| Q016 | coding | Medium | mcp_off (0.86) | mcp_off | mcp_off | mcp_on | mcp_off | 2 | 0 | 11 | 1357 | 0.018591 | 8.581 |
| Q035 | planning | Medium | mcp_on (0.9) | mcp_on | mcp_on | mcp_off | mcp_off | 1 | 0 | 7 | 193 | 0.003375 | 0.963 |
| Q045 | planning | Hard | mcp_on (0.86) | mcp_on | mcp_off | mcp_off | mcp_off | 3 | 0 | 9 | 18395 | 0.138249 | 145.063 |
| Q054 | planning | Medium | mcp_off (0.93) | mcp_off | mcp_off | mcp_off | mcp_off | 0 | 0 | 0 | 257 | 0.003855 | 1.509 |
| Q081 | planning | Hard | mcp_on (0.89) | mcp_on | mcp_on | mcp_off | mcp_off | 5 | 0 | 38 | 3338 | 0.043506 | 37.975 |
| Q051 | coding | Medium | mcp_on (0.93) | mcp_on | mcp_on | mcp_on | mcp_on | 0 | 0 | -2 | 162 | -0.005166 | -1.119 |
| Q040 | review | Hard | mcp_off (0.9) | mcp_off | mcp_off | mcp_on | mcp_on | 2 | 0 | 19 | 15731 | 0.128877 | 5.705 |
| Q038 | planning | Hard | mcp_off (0.9) | mcp_off | mcp_off | mcp_off | mcp_off | 2 | 0 | 0 | 7446 | 0.016794 | -13.024 |

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | 5 | 976 | 15.576 |
| planning | 8 | 11 | 6781.25 | 31.068 |
| review | 6 | 15.667 | 11508.833 | 22.716 |
