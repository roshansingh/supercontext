# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/private_goldset_eval_2026_05_11`
- Model: `opus`
- Scenario count: 2

## Summary

Scores in this document are synthesis self-scores. Use the judgement report or canonical validation report for independent pass/partial/fail verdicts.

| Scenario | Self-Score | Self-Reported Failure Modes | Notes |
|---|---|---|---|
| Q084 | Pass | none | Answer covers UI screens/actions, all backend Stripe routes with their view handlers, the external webhook endpoint with its producer edge to sqs:la-prod-stripe, and the downstream consumer chain (consume_stripe_queue → process_sqs_message → process_stripe_event) plus the management command, with citations. Event lineage includes both producer and consumer sides of the channel as required. |
| Q092 | Pass | none | Answer enumerates all four expected layers (customer/widget, websocket, backend API, operator/mobile UI) with cited symbols and endpoints, and explicitly calls out the unproved callback edge as required by the expected shape. |

## Q084 - Self-Score Pass

**Question:** If Stripe billing behavior changes, which UI flows, backend handlers, and webhook processors need validation?

### Answer

## Stripe Billing Feature-Slice Impact Map

### 1. UI surfaces (mercury_ui / ShopAgainMobile)
- Billing route registration: `Billing` exported from both navigation modules [mercury_ui/src/components/navigation/adminRoutes.js:L60-L60] and [mercury_ui/src/components/navigation/routes.js:L60-L60].
- Plans/Benefits screen that launches Stripe checkout & portal flows: `PlansAndBenifits` [mercury_ui/src/components/viewComponents/Billing/PlansAndBenifits.tsx:L195-L195].
- Cancel-subscription client action: `cancelStripeSubscription` [mercury_ui/src/services/billing.tsx:L20-L20].
- Mobile billing typing: `Billing` interface [ShopAgainMobile/src/interfaces/User.tsx:L99-L99].

### 2. Backend Stripe routes & handlers (mercury_api)
Routes (all from `billing/urls.py`):
- `ANY /create-charge/<company_id>/` [mercury_api/billing/urls.py:L30-L30]
- `ANY /stripe/create_checkout_session/<company_id>/` [mercury_api/billing/urls.py:L51-L51] → handler `CreateStripeSubscriptionCheckoutSession.get` [mercury_api/billing/views/stripe.py:L149-L455]
- `ANY /stripe/sucess/<company_id>/` and `/<return_url>/` variants [mercury_api/billing/urls.py:L56-L56] [mercury_api/billing/urls.py:L61-L61] → `StripeSubscriptionSucessView.get` [mercury_api/billing/views/stripe.py:L66-L146]
- `ANY /stripe/create_onetime_checkout_session/<company_id>/` [mercury_api/billing/urls.py:L66-L66] → `CreateStripeOneTimeCheckoutSession.get` [mercury_api/billing/views/stripe.py:L458-L507]
- `ANY /stripe/onetime_sucess/<company_id>/` [mercury_api/billing/urls.py:L71-L71] → `StripeOneTimeSucessView.get` [mercury_api/billing/views/stripe.py:L510-L564]
- `ANY /stripe/portal/<company_id>/` [mercury_api/billing/urls.py:L76-L76] → `StripePortal.get` [mercury_api/billing/views/stripe.py:L591-L607]
- `ANY /stripe/cancel_subscription/` [mercury_api/billing/urls.py:L77-L77] → `CancelCustomPlanSubscription.post` [mercury_api/billing/views/stripe.py:L567-L588]
- `ANY /stripe/webhook/` (local dev) [mercury_api/billing/urls.py:L79-L79] → `stripe_local_webhook` [mercury_api/billing/views/stripe.py:L612-L629]

Supporting code paths:
- Model: `billing.models.Billing` [mercury_api/billing/models.py:L173-L199]
- Migration adding provider/customer id: `0009_billing_billing_provider_billing_stripe_customer_id.Migration` [mercury_api/billing/migrations/0009_billing_billing_provider_billing_stripe_customer_id.py:L6-L30]
- Subscription transform helper: `transform_stripe_subscription` [mercury_api/billing/functions.py:L197-L225]
- Usage reporting: `create_stripe_usage_record` [mercury_api/billing/utils.py:L249-L256]

### 3. External webhook ingestion (mercury_webhooks)
- Public endpoint: `POST /v1/stripe` [mercury_webhooks/app.py:L79-L79] handled by `views.Stripe.stripe_webhook` [mercury_webhooks/views/Stripe.py:L13-L36].
- Producer edge: `stripe_webhook` **produces** to `sqs:la-prod-stripe` via `boto3 sqs.Queue.send_message` [mercury_webhooks/views/Stripe.py:L34-L34], with queue address resolved from `config.queueConfig.STRIPE_QUEUE` (values `la-staging-stripe`, `la-prod-stripe`) in `common/configmanager/{dev,prod,staging}.ini:L10`.
- Channel reference: [mercury_webhooks/common/configmanager/prod.ini:L10-L10].

### 4. Queue consumer (downstream of `sqs:la-prod-stripe`) — mercury_api
- SQS polling loop: `consume_stripe_queue` [mercury_api/stores/event_processor/stripe_event_processor.py:L54-L65]
- Per-message handler: `process_sqs_message` [mercury_api/stores/event_processor/stripe_event_processor.py:L36-L51]
- Business processor: `process_stripe_event` [mercury_api/stores/event_processor/stripe_event_processor.py:L16-L33]
- Management entrypoint that runs the consumer: `process_stripe_queue.Command.handle` [mercury_api/stores/management/commands/process_stripe_queue.py:L6-L10]

### Event lineage summary
`mercury_ui` Billing screen / cancel action → mercury_api `/stripe/*` views (checkout, success, portal, cancel) → Stripe → `POST /v1/stripe` on mercury_webhooks → `views.Stripe.stripe_webhook` produces **sqs:la-prod-stripe** → mercury_api `consume_stripe_queue` → `process_sqs_message` → `process_stripe_event` (which can mutate `billing.models.Billing` and may invoke `transform_stripe_subscription` / `create_stripe_usage_record`).

### Validation checklist for any Stripe behavior change
1. UI: `PlansAndBenifits` checkout launch and `cancelStripeSubscription` service call.
2. Backend HTTP: all 8 routes under `billing/urls.py` (subscription + one-time checkout/success, portal, cancel, create-charge, local webhook).
3. Webhook ingestion: `POST /v1/stripe` signature handling and SQS enqueue to `la-prod-stripe`.
4. Queue consumer: management command `process_stripe_queue` and the three processor functions.
5. Data layer: `billing.models.Billing` plus migration `0009_*` columns (`billing_provider`, `billing_stripe_customer_id`).

### Caveats

- Explicit call edges between UI components and specific backend endpoints, and between webhook payloads and `process_stripe_event` branches, are not in the packet — inferred by naming/role only.
- `/stripe/webhook/` in mercury_api appears to be a local-dev webhook (`stripe_local_webhook`); production webhook ingress is `POST /v1/stripe` in mercury_webhooks.
- The `Billing` symbols in `routes.js` / `adminRoutes.js` are exported values; their mounted React route component is not proven in the packet.

### Unknown Because Missing Evidence

- Which specific UI service calls hit which backend Stripe endpoints (no CALLS_ENDPOINT edges in packet).
- Whether `transform_stripe_subscription` and `create_stripe_usage_record` are invoked from `process_stripe_event` or from the HTTP success views (no call edges provided).
- Stripe event types handled by `process_stripe_event` (only symbol definition, no body-level facts).

### Self-Score Notes

Answer covers UI screens/actions, all backend Stripe routes with their view handlers, the external webhook endpoint with its producer edge to sqs:la-prod-stripe, and the downstream consumer chain (consume_stripe_queue → process_sqs_message → process_stripe_event) plus the management command, with citations. Event lineage includes both producer and consumer sides of the channel as required.

## Q092 - Self-Score Pass

**Question:** What repos participate in live chat, from customer widget to websocket to backend API and operator UI?

### Answer

## Live‑chat topology (4 repos)

### 1. Customer storefront widget — `mercury_ui`
The storefront/Shopify script bundles ship as obfuscated JS functions under:
- `mercury_ui/public/shopagain_script.min.js` (e.g., `shopagain_0x130ccd`, `shopagain_0x14d293`, `shopagain_0x24d9fe`, `shopagain_0x2fdad3`, `shopagain_0x31ab17`, `shopagain_0x32279d`, `shopagain_0x53387c`) [mercury_ui/public/shopagain_script.min.js:L1-1]
- `mercury_ui/public/shopify/shopagain_script.min.js` (same symbol set) [mercury_ui/public/shopify/shopagain_script.min.js:L1-1]

Widget configuration is modeled backend‑side by `campaigns.models.widgets.Widget` [mercury_api/campaigns/models/widgets.py:L110-133], with config schema migrations `0071_config_live_chat_widget_config` [mercury_api/companies/migrations/0071_config_live_chat_widget_config.py:L6-17] and rename to customer‑support config `0075_rename_live_chat_widget_config_config_customer_support_config` [mercury_api/companies/migrations/0075_rename_live_chat_widget_config_config_customer_support_config.py:L6-17].

### 2. Realtime transport — `mercury_websocket`
Serverless WebSocket routes:
- `ANY /postChatMessage` → `handler.postChatMessage` [mercury_websocket/serverless.yml:L36]
- `ANY /getChatHistory` → `handler.getChatHistory` [mercury_websocket/serverless.yml:L42]

Handler implementation: `handler.postChatMessage` [mercury_websocket/handler.py:L189-215].

### 3. Backend live‑chat API — `mercury_api`
`campaigns.views.live_chat.LiveChatViewset` [mercury_api/campaigns/views/live_chat.py:L59-293] with methods:
- `receive_message` [L65-164]
- `on_connect` [L167-191], `on_disconnect` [L194-207]
- `get_chat_history` [L210-268]
- `post_user_status` [L271-277], `mark_as_seen` [L280-293]

Helpers: `set_popup_user_status` [L36-37], `delete_popup_user_status` [L40-41], `get_popup_user_status` [L44-45], `is_chatbot_disabled` [L48-56].

Exposed Django routes seen in the packet:
- `ANY /chatty_stats/` [mercury_api/dashboard/urls.py:L54]
- `ANY /v1/chatbot` [mercury_api/mercury_api/urls.py:L58]

### 4. Operator UI — `mercury_ui`
Conversations navigation entries:
- `src.components.navigation.routes.Conversations` [mercury_ui/src/components/navigation/routes.js:L103]
- `src.components.navigation.adminRoutes.Conversations` [mercury_ui/src/components/navigation/adminRoutes.js:L105]

Chat/messaging service callers (all rooted at `REACT_APP_API_ROOT`):
- Chatflow CRUD: `GET/POST /campaigns/chatflow/` [mercury_ui/src/services/campaigns.ts:L343], [mercury_ui/src/services/campaigns.ts:L349]; `GET/PUT/PATCH/DELETE /campaigns/chatflow/{id}/` [mercury_ui/src/services/campaigns.ts:L346], [mercury_ui/src/services/campaigns.ts:L352], [mercury_ui/src/services/campaigns.ts:L355], [mercury_ui/src/services/campaigns.ts:L358]
- Stats: `GET /dashboard/chatty_stats/` [mercury_ui/src/services/dashboard.js:L86]
- Messaging: `POST /{smsChatRoot}{user}/send_sms_chat_message/` [mercury_ui/src/services/messaging.tsx:L26]; `POST /{whatsAppRoot}chat/{user}/send_whatsapp_chat_message/` [mercury_ui/src/services/messaging.tsx:L37]; onboarding checks [mercury_ui/src/services/messaging.tsx:L40], [mercury_ui/src/services/messaging.tsx:L43]; chat list/refresh [mercury_ui/src/services/messaging.tsx:L46], [mercury_ui/src/services/messaging.tsx:L49]; templates [mercury_ui/src/services/messaging.tsx:L103]

### 5. Mobile operator UI — `ShopAgainMobile`
- `src.pages.Conversations.Conversations` page [ShopAgainMobile/src/pages/Conversations.tsx:L30]
- Calls `GET /messaging/whats_app/template/chat_templates/` via `VITE_API_ROOT` [ShopAgainMobile/src/api/conversation.api.tsx:L82]

### Topology summary
`mercury_ui` storefront script (and `Widget` config in `mercury_api`) → `mercury_websocket` (`/postChatMessage`, `/getChatHistory`) → `mercury_api` `LiveChatViewset` (receive/connect/history/seen) ↔ operator surfaces in `mercury_ui` (Conversations + messaging/chatflow services) and `ShopAgainMobile` (Conversations page + chat templates API).

### Caveats

- Storefront script symbols are obfuscated; the packet proves their existence but not their exact widget→websocket call edge.
- All UI endpoint hosts are `host_unresolved_path_resolved` (env-rooted), so cross-repo binding to `mercury_api`/`mercury_websocket` is by path convention, not a resolved host.

### Unknown Because Missing Evidence

- Exact backend live-chat callback endpoint paths (e.g., for `LiveChatViewset.receive_message`) — `backend_live_chat_endpoint` retrieval returned no facts, so the URL routing that ties `LiveChatViewset` methods to specific HTTP routes is not provable from this packet.
- Whether `mercury_websocket.handler.postChatMessage`/`getChatHistory` calls back into `mercury_api`'s `LiveChatViewset` (no CALLS_ENDPOINT edge in the packet).

### Self-Score Notes

Answer enumerates all four expected layers (customer/widget, websocket, backend API, operator/mobile UI) with cited symbols and endpoints, and explicitly calls out the unproved callback edge as required by the expected shape.
