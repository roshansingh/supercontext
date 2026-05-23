# BetterContext A/B Report - pr119-full-2026-05-23 - 2026-05-23

> BetterContext is a semantic context accelerator and evidence provider. It should make Claude Code/Codex do less
> blind grep/read work when the KG has the right facts. It should not stop the agent from falling back to source
> inspection when KG coverage is missing, ambiguous, or out of scope.

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

## Caveat Analysis

`mcp_on` did not win 7 of 18 judged tasks: 4 `mcp_off` wins and 3 ties. These are not all the same failure mode.

| Task | Result | Classification | What happened |
|---|---|---|---|
| Q035 | `mcp_off` won | Real MCP quality loss: missing KG fact / retrieval gap | `mcp_on` used BetterContext but concluded the KG could not prove Kubernetes deployables. `mcp_off` found manifest-level deployment mappings through ordinary source search. The immediate issue is that the KG/tool path did not expose the deployable facts needed for this question, and the agent used service-oriented MCP calls instead of a deploy-specific path. |
| Q003 | `mcp_off` won | Real MCP quality loss: symbol-resolution gap | `mcp_on` returned ambiguous or fuzzy `load_model` candidates and included unrelated matches. `mcp_off` found the concrete `pycaret.load_model` call sites by source inspection. This points to retrieval/symbol resolution behavior, not MCP availability. |
| Q015 | `mcp_off` won | Synthesis / report consistency issue | Both arms summarized KG inventory. `mcp_on` was more concise but had internal inconsistencies/noisier claims in counts and coverage phrasing. This is weaker answer synthesis around metrics, not a core MCP transport failure. |
| Q037 | `mcp_off` won | Eval task-input problem / inconclusive MCP loss | The prompt said "Given this PR" but did not provide a concrete PR input shape. `mcp_on` made zero MCP calls and refused because changed files, repo, and diff were missing. `mcp_off` inferred a PR from local context and answered. This row should not be treated as a clean MCP quality loss until the task supplies explicit PR input. |
| Q048 | tie | Acceptable tie | `mcp_on` used 5 MCP calls. Both arms handled partial evidence and explicit refusal for uninstrumented scope. |
| Q051 | tie | Acceptable tie, resource-heavy | Both arms found the gating truth: promotion logic is not implemented and default behavior does not prove the intended transition. `mcp_on` had stronger evidence, but the core answer was tied and used more tokens/time. |
| Q081 | tie | Mostly positive tie | Overall correctness tied, but `mcp_on` won evidence, completeness, and actionability. This is a useful MCP signal even though the overall winner was tie. |

The 2 zero-MCP-call `mcp_on` rows also have different meanings:

- Q054 is expected: the task asks "Is this code secure?", and the correct behavior is an out-of-scope refusal plus narrower supported security questions. No MCP call is necessary.
- Q037 is problematic: the task expected PR blast-radius analysis but did not provide concrete PR input. This should be fixed in the evaluation harness or task fixture before drawing product conclusions from that row.

Priority follow-up from this run is not generic cost optimization. The serious answer-quality issues are Q035 and Q003. Q015 is a metric-summary/synthesis quality issue, and Q037 is an evaluation-input issue.

## Phase Aggregates

| Phase | Tasks | Avg Tool Delta | Avg Token Delta | Avg Wall-Time Delta |
|---|---:|---:|---:|---:|
| coding | 4 | 5.75 | -2019.5 | -49.63 |
| planning | 8 | 1.25 | 4361.375 | 24.962 |
| review | 6 | 6 | 9414.167 | 25.912 |
