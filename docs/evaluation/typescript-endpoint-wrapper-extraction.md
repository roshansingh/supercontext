# TypeScript Endpoint Wrapper Extraction Evidence

Date: 2026-06-18

## Change

Parser-backed TypeScript endpoint extraction now recognizes endpoint-shaped object wrapper calls in [ts_parser.mjs](../../source/kg/languages/typescript/extractors/ts_parser.mjs). It covers imported HTTP helpers such as `get({ service, path })`, generic request helpers such as `request({ baseUrl, path, method })`, and controller-style inherited methods such as `this.post({ path })` when a constructor forwards endpoint defaults through `super({ service, apiVersion, ... })`.

The shared endpoint adapter preserves allowlisted wrapper metadata (`service`, `api_version`, client app id, and wrapper import/method hints) on `CALLS_ENDPOINT` qualifiers in [endpoints.py](../../source/kg/file_formats/_shared/endpoints.py).

## Evidence

Baseline on the same local TypeScript monorepo checkout before the change:

- TypeScript/JavaScript files discovered: 1,489
- `CALLS_ENDPOINT` facts: 5
- `source_kind` counts: `{"fetch_call": 5}`

After the change on the same checkout, with the review hardening that fails closed when a wrapper
declares `host`/`service` but that expression is unresolved:

- TypeScript/JavaScript files discovered: 1,489
- `CALLS_ENDPOINT` facts: 134
- `source_kind` counts: `{"http_wrapper_call": 108, "http_controller_wrapper_call": 21, "fetch_call": 5}`
- Wrapper-derived facts: 129
- Wrapper calls withheld as explicit coverage rows because `host`/`service` was unresolved: 76

Representative new wrapper evidence preserved service names, API versions, safe template route parameters, and env-backed host confidence without adding generated snapshots to the repository.

Regression fixtures include repo-neutral positive and negative cases under [test_endpoint_extraction.py](../../tests/test_endpoint_extraction.py), including a generic `request({ baseUrl, path, method })` helper shape that does not depend on tenant-specific method names, shorthand wrapper config properties such as `{ service, path }`, and fail-closed unresolved `service`/`host` wrapper cases.

## Verification

- `uv run --extra dotnet python -m unittest tests.test_endpoint_extraction`
- `uv run --extra dotnet python -m unittest tests.metrics.test_typescript_terraform_opportunities`
- `uv run --extra dotnet python -m compileall -q source`
- `uv run --extra dotnet python -m unittest discover -s tests`

Result: full suite passed with 1,291 tests run and 2 skipped.
