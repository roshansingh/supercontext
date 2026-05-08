# Medium Query Run: Mercury ML and True Loop

Status: evaluation run
Date: 2026-05-08
Snapshots: `data/kg_runs/mercury_ml`, `data/kg_runs/true_loop`
Baseline: after PR4 / `a51513b`

## Summary

Medium-tier readiness is much lower than low-tier readiness. The current KG can answer direct symbol, import, and evidence lookups, but most medium queries require aggregation, reverse transitive traversal, PR diff input, service/catalog fixtures, API/schema fixtures, or refusal policy surfaces.

| Repo | Pass | Partial | Fail / not implemented | Blocked by missing fixture |
|---|---:|---:|---:|---:|
| `mercury_ml` | 1 | 6 | 7 | 10 |
| `true_loop` | 1 | 5 | 7 | 11 |

## Commands Run

| Area | Mercury command | True Loop command | Observation |
|---|---|---|---|
| Reverse callers / impact | `find-callers build_features --include-all --limit 10` | `find-callers generateResponseStream --limit 10` | Direct callers work with evidence; reverse transitive impact is not implemented. |
| Internal module importers | `modules-importing mercury_ml.chatbot.apis.openai_instructor --limit 10` | `modules-importing src.lib.debug-logger --limit 10` | Direct internal importers work with citations. |
| Ambiguity | `lookup-symbol build_features --limit 10` | `lookup-symbol generateResponseStream --limit 10` | Ambiguity/unique resolution works. |
| Dependency impact | `modules-importing pandas --limit 10` | `modules-importing '@prisma/client' --limit 10` | Direct importers work; likely call sites / breakage ranking not implemented. |
| Coverage | `summary` | `summary` | Coverage rows are visible; grouped coverage dashboard is not implemented. |

## Medium Query Status

| ID | Query area | Mercury | True Loop | Finding |
|---|---|---|---|---|
| Q016 | Impact of symbol / reverse transitive callers | Partial | Partial | Direct callers exist; bounded reverse transitive paths are missing. |
| Q017 | Who imports internal module | Partial | Partial | Direct importers work; grouped/package-area output is missing. |
| Q018 | Indirect OpenAI through wrappers | Partial | Blocked | Mercury can show wrapper importers; no merged wrapper-to-external path command. True Loop has no OpenAI wrapper fixture. |
| Q019 | Files to inspect before refactor | Partial | Partial | Lookup and callers exist; no combined “inspection plan” or nearby-test retrieval. |
| Q020 | Ambiguity response | Pass | Pass | Resolver returns explicit ambiguous or resolved status with candidates/evidence. |
| Q021 | PR changed file to touched symbols/callers | Blocked | Blocked | No PR diff input contract or changed-line-to-symbol command. |
| Q022 | PR changed module to importers | Blocked | Blocked | No PR diff input contract. |
| Q023 | Modules combining two dependencies | Fail | Fail | No import-intersection query surface. |
| Q024 | External API calls ranked by caller | Fail | Fail | No aggregation of call edges by external dependency usage. |
| Q025 | Most depended-on internal modules | Fail | Fail | No internal-import fan-in ranking. |
| Q026 | Path from symbol to dependency | Fail | Fail | No mixed call/import path search. |
| Q027 | Remove dependency impact | Partial | Partial | Direct importers work; “break first” ranking and call-site usage are missing. |
| Q028 | Tests mentioning/calling symbol | Fail | Fail | No lexical test retrieval or test-symbol query. |
| Q029 | Stale/uninstrumented areas | Partial | Partial | Coverage rows are visible; grouped/freshness dashboard is missing. |
| Q030 | Top risky functions by fan-in | Fail | Fail | No caller-count aggregation. |
| Q031 | Service owner from catalog | Blocked | Blocked | No catalog/owner fixture. |
| Q032 | Endpoints exposed by service | Blocked | Blocked | No API/OpenAPI/gRPC/GraphQL fixture extraction. |
| Q033 | Services calling endpoint | Blocked | Blocked | No endpoint identity or cross-service fixture. |
| Q034 | PR schema response consumers | Blocked | Blocked | No PR/schema fixture. |
| Q035 | K8s deployable for service | Blocked | Blocked | No manifest fixture/extractor. |
| Q051 | Candidate promotion | Blocked | Blocked | No candidate/promotion fixture. |
| Q052 | PII fields | Blocked | Blocked | No schema/API/PII extraction fixture. |
| Q054 | Broad security refusal | Fail | Fail | No product-level natural-language refusal surface. |
| Q055 | Service alias merge | Blocked | Blocked | No alias/catalog/k8s/OTel fixture. |

## Decision

The next feature should not be deeper language extraction. The evidence points to a **medium-query aggregation layer over existing facts**.

Recommended next PR:

1. `who-imports` / internal dependency fan-in aggregation.
2. `top-internal-dependencies` for Q025.
3. `top-fan-in-symbols` for Q030.
4. `modules-importing-both` for Q023.

This is a focused next slice because all four are deterministic aggregations over existing `IMPORTS`, `CALLS`, `Entity`, and `Evidence` JSONL data. It should convert several medium failures without adding new extractors or fixtures.
