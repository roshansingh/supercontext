# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/latticeai_23_pr16`
- Model: `opus`
- Scenario count: 1

## Summary

| Scenario | Score | Failure Modes | Notes |
|---|---|---|---|
| Q100 | Pass | none | Answer enumerates documented endpoints lacking exact backend matches and lacking matched client calls, cited to specific repo/path/line coordinates, matching the expected inventory-with-drift-caveats shape. |

## Q100 - Pass

**Question:** Which documented ShopAgain API endpoints are not obviously implemented or called by any client?

### Answer

## Documented ShopAgain v1 endpoints with implementation/client gaps

Based on the two reconciliations in the packet (`docs_vs_backend_v1_endpoints`, `clients_vs_docs_v1_endpoints`).

### Not obviously implemented in backend (no exact match)
- **`/v1/collections`** — only a fuzzy/`possible_match` (similarity 0.789) to mercury-api's `/v1/product_collections`, not an exact match. Documented in [shopagain_api_docs/dist.json:L403-404], [shopagain_api_docs/openapi/openapi.yaml:L76]; backend route is `ANY /v1/product_collections` at [mercury_api/mercury_api/urls.py:L53].

All other documented endpoints (`/v1/company`, `/v1/contacts`, `/v1/products`, `/v1/carts`, `/v1/checkouts`, `/v1/orders`, `/v1/store_data`) reconcile cleanly to backend routes in mercury-api or mercury-webhooks.

### Not obviously called by any in-scope client
In the `clients_vs_docs_v1_endpoints` reconciliation (mercury_ui, ShopAgainMobile, shopagain-chat-widget vs. shopagain_api_docs), **every** documented v1 endpoint appears as `right_only` — i.e., no in-scope client call matches any of them:
- `ANY /v1/company` [shopagain_api_docs/dist.json:L90], [shopagain_api_docs/docs/dist.json:L27], [shopagain_api_docs/openapi/openapi.yaml:L67]
- `POST /v1/company` [shopagain_api_docs/dist.json:L91], [shopagain_api_docs/docs/dist.json:L28]
- `ANY /v1/contacts` [shopagain_api_docs/dist.json:L181], [shopagain_api_docs/openapi/openapi.yaml:L70]
- `POST /v1/contacts` [shopagain_api_docs/dist.json:L182]
- `ANY /v1/products` [shopagain_api_docs/dist.json:L275], [shopagain_api_docs/openapi/openapi.yaml:L73]
- `POST /v1/products` [shopagain_api_docs/dist.json:L276]
- `ANY /v1/collections` [shopagain_api_docs/dist.json:L403], [shopagain_api_docs/openapi/openapi.yaml:L76]
- `POST /v1/collections` [shopagain_api_docs/dist.json:L404]
- `ANY /v1/carts` [shopagain_api_docs/dist.json:L489], [shopagain_api_docs/openapi/openapi.yaml:L79]
- `POST /v1/carts` [shopagain_api_docs/dist.json:L490]
- `ANY /v1/checkouts` [shopagain_api_docs/dist.json:L581], [shopagain_api_docs/openapi/openapi.yaml:L82]
- `POST /v1/checkouts` [shopagain_api_docs/dist.json:L582]
- `ANY /v1/orders` [shopagain_api_docs/dist.json:L713], [shopagain_api_docs/openapi/openapi.yaml:L85]
- `POST /v1/orders` [shopagain_api_docs/dist.json:L714]
- `ANY /v1/store_data` [shopagain_api_docs/dist.json:L845], [shopagain_api_docs/openapi/openapi.yaml:L88]
- `POST /v1/store_data` [shopagain_api_docs/dist.json:L846]

### Net result
- **Documented but only a possible (renamed) backend match:** `/v1/collections` ↔ `/v1/product_collections`.
- **Documented but no matched client caller in scope:** every documented v1 endpoint above.

### Caveats

- The `clients_vs_docs` step shows zero `matched` rows for any documented endpoint — every documented endpoint is `right_only`. This is striking and may indicate the client extractors did not produce normalized `/v1/...` keys for the in-scope clients, rather than a true absence of usage.
- `/v1/collections` vs `/v1/product_collections` is flagged at 0.789 similarity; treat as a likely naming drift, not a true missing implementation.
- Reconciliation is `deterministic_static` based on Django/Flask/OpenAPI parsing; it does not validate dynamic routing or proxy rewrites.

### Unknown Because Missing Evidence

- Whether mercury_ui / ShopAgainMobile / shopagain-chat-widget actually call any of these endpoints — the packet contains no `CALLS_ENDPOINT` evidence, only the reconciliation outputs.
- Whether `/v1/collections` is intentionally renamed to `/v1/product_collections` in the backend or is a doc/code drift bug.

### Score Notes

Answer enumerates documented endpoints lacking exact backend matches and lacking matched client calls, cited to specific repo/path/line coordinates, matching the expected inventory-with-drift-caveats shape.
