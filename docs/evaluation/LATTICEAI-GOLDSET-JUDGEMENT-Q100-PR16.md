# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/latticeai_23_pr16/goldset_packets_q100_pr16.json`
- Answers: `data/kg_runs/latticeai_23_pr16/goldset_answers_q100_pr16.json`
- Model: `opus`
- Scenario count: 1
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q100 | complete | Pass | none | The evidence packet contains all documented ShopAgain endpoints, their backend matches, the /v1/collections vs /v1/product_collections drift, and the right-only client reconciliation. The generated answer correctly identifies /v1/collections as the only documented endpoint without an exact backend match, notes the right-only status of all docs vs clients, and adds appropriate false-positive caveats. |

## Q100 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The evidence packet contains all documented ShopAgain endpoints, their backend matches, the /v1/collections vs /v1/product_collections drift, and the right-only client reconciliation. The generated answer correctly identifies /v1/collections as the only documented endpoint without an exact backend match, notes the right-only status of all docs vs clients, and adds appropriate false-positive caveats.

### Ground Truth Coverage

- Identified documented public paths from openapi.yaml (covers /v1/company, /v1/contacts, /v1/products, /v1/collections, /v1/carts, /v1/checkouts, /v1/orders, /v1/store_data with line citations).
- Identified backend routes in mercury_api/urls.py including /v1/elementor and /v1/chatbot as code-only (not in docs), and /v1/product_collections as the renamed match.
- Captured the docs/code drift: /v1/collections fuzzy-matches /v1/product_collections.
- Noted /v1/store_data is implemented in mercury_webhooks app.py (line 101) rather than mercury_api.

### Missing Or Weak Evidence

- No CALLS_ENDPOINT evidence is included in the packet for clients (mercury_ui, ShopAgainMobile, shopagain-chat-widget); the right_only status alone is what the answer leans on, which the answer correctly flags as a caveat.

### Answer Issues

- Answer does not explicitly call out that /v1/store_data is implemented in mercury_webhooks rather than the main mercury_api backend in the body, though it cites the route correctly via the reconciliation, and notes /v1/elementor/chatbot are code-only is implicitly handled (not strictly required by the user's question, which asks about documented-but-not-implemented/called).

### Recommended Next Action

Accept; optionally augment the packet with explicit CALLS_ENDPOINT facts from the in-scope clients to verify whether the all-right_only client reconciliation reflects true absence or an extractor gap.
