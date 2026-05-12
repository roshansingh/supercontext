# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/private_goldset_eval_2026_05_11/q084_q092_packets_for_answers_eval_2026_05_12.json`
- Answers: `data/kg_runs/private_goldset_eval_2026_05_11/q084_q092_answers_eval_2026_05_12.json`
- Model: `opus`
- Scenario count: 2
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q084 | complete | Pass | none | The EvidencePacket contains all key ground-truth facts: UI cancel subscription service at src/services/billing.tsx:20, PlansAndBenifits screen, mercury_api billing/urls.py Stripe routes (52-79 range), billing/views/stripe.py handlers, mercury_webhooks /v1/stripe route, views/Stripe.py with producer edge to la-prod-stripe queue from prod.ini:10, and backend consumer (process_stripe_queue.Command and stripe_event_processor). The generated answer covers all these elements with accurate citations and adds a sensible validation checklist. |
| Q092 | partial | Partial | missing KG fact, bad retrieval plan | The packet covers four of the five repo roles (storefront script in mercury_ui, mercury_websocket routes/handlers, mercury_api LiveChatViewset, mercury_ui operator routes, and ShopAgainMobile mobile UI), and the generated answer faithfully enumerates them. However, several ground-truth specifics are missing: the non-minified `shopagain_script.js`, the `shopagain-chat-widget` config repo, the websocket `$connect` route, the `mercury_websocket/handler.py` forwarding of connect/message/history events to `/campaigns/live_chat/`, the `campaigns/urls.py:77` registration, and the `WhatsApp/Conversations.js` operator UI path. The answer reflects these gaps as caveats/unknowns but cannot cover ground-truth details. |

## Q084 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all key ground-truth facts: UI cancel subscription service at src/services/billing.tsx:20, PlansAndBenifits screen, mercury_api billing/urls.py Stripe routes (52-79 range), billing/views/stripe.py handlers, mercury_webhooks /v1/stripe route, views/Stripe.py with producer edge to la-prod-stripe queue from prod.ini:10, and backend consumer (process_stripe_queue.Command and stripe_event_processor). The generated answer covers all these elements with accurate citations and adds a sensible validation checklist.

### Ground Truth Coverage

- UI cancel subscription via src/services/billing.tsx:20 - covered
- PlansAndBenifits.tsx Stripe portal screen - covered
- Backend routes in billing/urls.py:52-79 - covered (all stripe routes listed)
- Handlers in billing/views/stripe.py - covered (all classes listed)
- External webhook /v1/stripe in mercury_webhooks/app.py:79 - covered
- views/Stripe.py implementation - covered
- la-prod-stripe queue from prod.ini:10 - covered
- Backend consumer process_stripe_queue.py and stripe_event_processor.py - covered

### Missing Or Weak Evidence

- Ground truth mentions PlansAndBenifits.tsx:333 specifically, but evidence shows line 195 for the function symbol; the specific Stripe portal call site at line 333 is not directly in the packet (function definition is provided instead).
- Test gaps mentioned in expected_answer_shape are not directly evidenced as a category, though the answer provides a validation checklist.

### Answer Issues

- Minor: line numbers for PlansAndBenifits cite the function definition (line 195), not the specific Stripe portal invocation line (333) in ground truth, but this is an evidence limitation, not a synthesis fault.

### Recommended Next Action

Accept as Pass. Optionally enhance retrieval to fetch specific call-site lines (e.g., Stripe portal usage at PlansAndBenifits.tsx:333) and CALLS_ENDPOINT edges to strengthen UI-to-backend traceability.

## Q092 - Partial

**Evidence completeness:** partial

**Failure owner:** missing KG fact, bad retrieval plan

### Summary

The packet covers four of the five repo roles (storefront script in mercury_ui, mercury_websocket routes/handlers, mercury_api LiveChatViewset, mercury_ui operator routes, and ShopAgainMobile mobile UI), and the generated answer faithfully enumerates them. However, several ground-truth specifics are missing: the non-minified `shopagain_script.js`, the `shopagain-chat-widget` config repo, the websocket `$connect` route, the `mercury_websocket/handler.py` forwarding of connect/message/history events to `/campaigns/live_chat/`, the `campaigns/urls.py:77` registration, and the `WhatsApp/Conversations.js` operator UI path. The answer reflects these gaps as caveats/unknowns but cannot cover ground-truth details.

### Ground Truth Coverage

- Storefront script in mercury_ui: covered via shopagain_script.min.js (minified variant only; .js source not in packet).
- Websocket routes postChatMessage and getChatHistory: covered; $connect route not in packet.
- mercury_websocket handler.py forwarding: only handler.postChatMessage symbol present; no evidence of HTTP forwarding to /campaigns/live_chat/.
- Backend live-chat API mercury_api/campaigns/views/live_chat.py: covered (LiveChatViewset and methods).
- campaigns/urls.py:77 registration: not in packet.
- Operator UI in mercury_ui WhatsApp/Conversations.js: not directly in packet (only navigation routes and messaging service calls).
- shopagain-chat-widget repo: not represented in packet.

### Missing Or Weak Evidence

- No `mercury_ui/public/shopify/shopagain_script.js` (only minified variants).
- No shopagain-chat-widget repo evidence.
- Missing $connect websocket route.
- Missing handler.py forwarding edges to mercury_api /campaigns/live_chat/ endpoints.
- Missing campaigns/urls.py registration of LiveChatViewset (line 77).
- Missing mercury_ui/src/views/main/WhatsApp/Conversations.js operator UI file.

### Answer Issues

- Does not mention `shopagain-chat-widget` repo at all (a participant per ground truth).
- Does not surface the `$connect` websocket route.
- Does not identify the WhatsApp/Conversations.js operator screen specifically; lists navigation symbols and messaging services instead.
- Does not cite campaigns/urls.py:77 registration of live-chat viewset.
- Cites only obfuscated minified script symbols; doesn't establish the iframe/websocket bootstrap mechanism in shopagain_script.js.

### Recommended Next Action

Re-run retrieval to fetch the non-minified `shopagain_script.js`, the `shopagain-chat-widget` repo's chat widget config, the `$connect` websocket route, handler.py CALLS_ENDPOINT edges to /campaigns/live_chat/, the campaigns/urls.py registration line for LiveChatViewset, and the WhatsApp Conversations.js operator UI file.
