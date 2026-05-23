# SuperContext A/B Report - default-v1-2026-05-23 - 2026-05-23

Delta orientation: `off_minus_on`. Positive tool/token/cost values mean `mcp_on` used less than `mcp_off`; negative values mean `mcp_on` used more.

This checked-in report is sanitized. Raw answers, judge reasoning, SDK messages, LangSmith URLs, and downloaded traces remain under ignored `data/ab_runs/default-v1-2026-05-23/`.

## Summary

- Tasks: 18 paired tasks / 36 host runs
- Quality judge: `gpt-4.1-mini`, blinded A/B answer order, seed `6`
- Judge winners: `mcp_off=11`, `mcp_on=3`, `tie=4`
- Cost availability: `{'available': 18}`

## Per Task

| Task | Phase | Difficulty | Winner | Confidence | Tool Delta | Token Delta | Dollar Delta | Wall-Time Delta |
|---|---|---|---|---:|---:|---:|---:|---:|
| Q045 | planning | Hard | mcp_off | 0.95 | 1 | 16350 | 0.232998 | 334.991 |
| Q004 | coding | Low | mcp_off | 0.9 | -1 | 5744 | 0.082392 | 113.536 |
| Q054 | planning | Medium | mcp_on | 0.9 | -1 | -306 | -0.004158 | -5.13 |
| Q035 | planning | Medium | mcp_off | 0.9 | -3 | 731 | 0.011037 | 16.799 |
| Q037 | review | Hard | tie | 0.9 | -2 | 15017 | 0.089187 | 74.994 |
| Q031 | planning | Medium | mcp_off | 0.95 | 2 | 10419 | 0.113589 | 156.294 |
| Q038 | planning | Hard | mcp_off | 0.9 | -2 | 2195 | 0.030609 | 48.124 |
| Q003 | coding | Low | mcp_off | 0.9 | -1 | 5216 | 0.073932 | 117.404 |
| Q048 | review | Hard | mcp_on | 0.9 | -2 | -16950 | -0.026382 | 26.359 |
| Q011 | planning | Low | mcp_off | 0.9 | 0 | 3237 | 0.045627 | 64.164 |
| Q110 | review | Hard | mcp_off | 0.95 | 0 | 5282 | 0.076422 | 124.247 |
| Q051 | coding | Medium | tie | 0.9 | -3 | 1346 | 0.017562 | 29.449 |
| Q021 | review | Medium | tie | 0.9 | -2 | -3525 | -0.049503 | -49.299 |
| Q016 | coding | Medium | mcp_off | 0.95 | 1 | 9309 | 0.131979 | 180.802 |
| Q053 | review | Hard | tie | 0.9 | -2 | -9104 | -0.128004 | -156.302 |
| Q015 | planning | Low | mcp_on | 0.9 | -2 | 7151 | 0.009405 | -23.624 |
| Q040 | review | Hard | mcp_off | 0.9 | -3 | 11830 | 0.013314 | -12.228 |
| Q081 | planning | Hard | mcp_off | 0.95 | 1 | 11504 | 0.164172 | 231.213 |

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | -1 | 5403.75 | 110.298 |
| planning | 8 | -0.5 | 6410.125 | 102.854 |
| review | 6 | -1.833 | 425 | 1.295 |
