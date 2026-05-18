# JS/TS Endpoint Resolution Validation

Validation for Debate 1 after PR-1 and PR-2.

## Inputs

- Before snapshot: `data/kg_runs/shopagain_latticeai_23_dotnet_resolver_compare_2026-05-18`
- Before report: `docs/evaluation/runs/shopagain-latticeai-dotnet-resolver-compare-2026-05-18/coverage-run.md`
- After snapshot: `data/kg_runs/shopagain_latticeai_23_debate1_pr2_2026-05-18`
- After report: `docs/evaluation/runs/shopagain-latticeai-debate1-pr2-2026-05-18/coverage-run.md`
- Fleet size: 23 LatticeAI repos

## Result

| Measure | Before | After | Readout |
|---|---:|---:|---|
| Fleet score | 0.450 | 0.417 | Lower, because false-positive endpoint facts now fail closed. |
| `CALLS_ENDPOINT` facts | 454 | 215 | Lower by design; dynamic template paths are no longer fabricated. |
| `CALLS_ENDPOINT` coverage rows | 521 | 521 | Same opportunity surface, better reason taxonomy. |
| `unresolved_target` | 53 | 13 | Improved: helper/reassignment cases now get specific reasons. |
| `unresolved_host` / `host_env_backed` | 456 | 211 | Renamed and reduced; env-host partials are now explicit. |
| `target_dynamic_template_segment` | 0 | 245 | New honest gap for dynamic template segments that were previously false-open. |
| `target_helper_call_deferred` | 0 | 39 | New honest gap for helper-call targets. |
| `target_reassigned_binding` | 0 | 1 | New honest gap for unsafe mutable local flow. |

## Metric Movement

| Metric | Before | After | Readout |
|---|---:|---:|---|
| Fleet score | 0.450 | 0.417 | Lower because false-positive facts became explicit gaps. |
| Avg `M_extractor_opportunity` | 0.522 | 0.356 | Lower because fewer endpoint opportunities become facts. |
| Frontend `M_extractor_opportunity` | 0.929 | 0.449 | Lower from fail-closed JS/TS endpoint handling. |
| Shared-lib `M_extractor_opportunity` | 0.683 | 0.330 | Lower from fail-closed JS/TS endpoint handling. |
| Avg `M_evidence_grounding` | 0.977 | 0.977 | Stable. |
| Avg `M_silent_gap` | 0.453 | 0.453 | Stable. |

## Interpretation

This debate improved response quality more than raw coverage. The old extractor counted many unsafe JS/TS calls as endpoint facts; the new extractor refuses those cases and explains why. That drops `M_extractor_opportunity` because the metric currently rewards emitted facts, even when the old facts were less trustworthy.

Non-`mercury_ui` validation did move: `ShopAgainMobile`, `highagencyui`, and `mercury_api` now show specific dynamic-template/helper/reassignment reasons instead of generic unresolved rows or unsafe facts.

## Cross-File Decision

Do not implement cross-file imported-constant endpoint resolution yet.

The remaining largest gaps are not primarily imported constants:

- `target_dynamic_template_segment`: 245
- `host_env_backed`: 211
- `target_helper_call_deferred`: 39
- `unresolved_target`: 13

The next useful debate should focus on general, non-repo-specific handling for dynamic route/template parameters and env-host/base-client provenance, not cross-file constants.
