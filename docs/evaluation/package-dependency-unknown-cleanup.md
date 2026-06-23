# Package Dependency Unknown Cleanup

## Scope

This note records the focused evidence for the generic package dependency classification cleanup.

The validation reused the latest private 720-repo fleet extraction and reran package classification against current source manifests. It did not rerun full source extraction, because this change only affects consumer manifest extraction, relink package classification, and coverage/report bucketing.

## Before And After

| metric | before | after | delta |
|---|---:|---:|---:|
| `unknown` package classifications | 1,849 | 1,651 | -198 |
| `consumer_manifest_external` package classifications | 4,857 | 5,011 | +154 |
| `code_inferred_external` package classifications | 0 | 42 | +42 |
| `cross_repo_dependency_unknown_category` reasons | 1,849 | 1,651 | -198 |
| `cross_repo_dependency_no_provider` reasons | 4 | 4 | 0 |

Top package-name reductions in the unknown bucket:

| package | before | after | delta |
|---|---:|---:|---:|
| `pytest` | 92 | 16 | -76 |
| `PyYAML` | 27 | 0 | -27 |
| `behave` | 11 | 0 | -11 |
| `nox` | 50 | 43 | -7 |
| `python-dateutil` | 5 | 0 | -5 |
| `mongomock` | 5 | 0 | -5 |
| `beautifulsoup4` | 5 | 0 | -5 |

## Interpretation

The change reduces actionable dependency unknowns by moving manifest-proven and normalizer-proven third-party imports out of the unknown bucket. Unresolved aliases without a concrete `distribution_name` remain unknown.

This is a useful cleanup, but not a large fleet-score mover by itself. Remaining dependency unknowns are still 1,651 rows, so the next pass should inspect the residual bucket before adding more dependency classification rules.
