# Medium Query Aggregation Run

Status: implementation evaluation
Date: 2026-05-08
Snapshots: `data/kg_runs/mercury_ml`, `data/kg_runs/true_loop`
Implemented plan: `debates/3-2026-05-07-finalize-the-implementation-plan-for-the.md`

## Summary

The aggregation layer converts the intended medium-query gaps into passes without changing extraction or normalization. Low-tier results remain stable.

| Repo | Low pass | Low partial | Low fail | Low blocked | Medium pass | Medium partial | Medium fail | Medium blocked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `mercury_ml` | 13 | 1 | 0 | 1 | 5 | 5 | 4 | 10 |
| `true_loop` | 13 | 1 | 0 | 1 | 5 | 4 | 4 | 11 |

Medium baseline before this slice was:

| Repo | Pass | Partial | Fail | Blocked |
|---|---:|---:|---:|---:|
| `mercury_ml` | 1 | 6 | 7 | 10 |
| `true_loop` | 1 | 5 | 7 | 11 |

## Commands Run

| Area | Mercury command | True Loop command | Result |
|---|---|---|---|
| Compile | `python -m compileall -q source` | same | Pass. |
| Q017 `who-imports` | `who-imports mercury_ml.chatbot.apis.openai_instructor --limit 10` | `who-imports src.lib.debug-logger --limit 10` | Pass. Mercury returns 6 importers grouped under `mercury_ml.chatbot` and `mercury_ml.content_creation`; True Loop returns 5 importers grouped under `src.app` and `src.lib`. |
| Q023 dependency intersection | `modules-importing-both pandas sklearn --limit 10` | `modules-importing-both react next --limit 10` | Pass. Mercury returns 13 modules; True Loop returns 7 modules. |
| Q025 internal dependency fan-in | `top-internal-dependencies --limit 10` | same | Pass. Mercury top result is `mercury_ml.chatbot` with 53 importers; True Loop top result is `src.lib.db` with 24 importers. |
| Q030 symbol fan-in | `top-fan-in-symbols --limit 10` | same | Pass. Mercury top internal symbol has 4 callers; True Loop top internal symbol has 8 callers. |
| External fan-in guardrail | `top-fan-in-symbols --include-external --limit 10` | not needed | Validates default: external packages dominate when included, so internal-only default is correct for risky-functions query. |
| No-regression smoke | `modules-importing pandas`, `find-callers load_model`, `evidence-for-call predict_on_session build_features` | `lookup-symbol generateResponseStream` | Existing low-query surfaces still pass. |

## Medium Query Movement

| ID | Area | Mercury | True Loop | Finding |
|---|---|---|---|---|
| Q017 | Internal module importers | Pass | Pass | New grouped `who-imports` surface resolves internal `CodeModule.identity.module` targets and returns citations. |
| Q020 | Ambiguity response | Pass | Pass | Already passed before this slice. |
| Q023 | Modules importing both dependencies | Pass | Pass | New `modules-importing-both` surface returns concrete intersecting modules and both-side citations. |
| Q025 | Most depended-on internal modules | Pass | Pass | New internal import fan-in ranking works over normalized categories. |
| Q030 | Top risky functions by fan-in | Pass | Pass | New caller-count aggregation works and excludes external callees by default. |

## Remaining Medium Gaps

| Category | Query IDs | Reason |
|---|---|---|
| Reverse transitive/path search | Q016, Q026 | Direct callers/callees exist, but mixed or transitive path search is not implemented. |
| Wrapper/API usage aggregation | Q018, Q024 | Needs call/import merge and external API call grouping. |
| Inspection/test retrieval | Q019, Q028 | Needs a combined inspection-plan surface and lexical/test retrieval. |
| Coverage dashboard/refusal | Q029, Q054 | Coverage rows exist, but product-level refusal and grouped coverage surfaces are missing. |
| Fixture-blocked platform queries | Q021, Q022, Q031-Q035, Q051, Q052, Q055 | Need PR, catalog/owner, endpoint/schema, deploy, candidate/promotion, PII, and alias fixtures. |

## Decision

This slice is successful: it improves medium readiness by four queries on both repos and keeps low readiness unchanged. The next evidence-backed implementation choice should come from the remaining non-fixture medium failures, especially Q024 external API call aggregation or Q026 mixed call/import path search.
