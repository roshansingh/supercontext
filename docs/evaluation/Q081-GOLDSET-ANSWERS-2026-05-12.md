# Goldset Answer Synthesis

- Snapshot: `data/kg_runs/private_goldset_eval_2026_05_11`
- Model: `opus`
- Scenario count: 1

## Summary

Scores in this document are synthesis self-scores. Use the judgement report or canonical validation report for independent pass/partial/fail verdicts.

| Scenario | Self-Score | Self-Reported Failure Modes | Notes |
|---|---|---|---|
| Q081 | Pass | none | Answer covers all expected building blocks (web/mobile clients, API backend with Apache→WSGI route, webhooks, tracking, campaign producer+consumer lineage on sqs:la-prod-campaign-messages, websocket service, ML API library dependency) with inline citations, and explicitly flags missing deploy evidence for the ML API and absent downstream event edges as required. |

## Q081 - Self-Score Pass

**Question:** What are the runtime building blocks of ShopAgain across these repos, and which domains route to each backend?

### Answer

## ShopAgain runtime topology

### Clients
- **Web app (mercury_ui)** — React SPA points to the backend via `REACT_APP_API_ROOT=https://api.shopagain.io/` [mercury_ui/.env.production:L1-L1] and is consumed across services (e.g., [mercury_ui/src/services/api.js:L10-L10], [mercury_ui/src/components/viewComponents/EmailBuilder/EmailEditor.js:L37-L37], [mercury_ui/src/views/main/Settings.js:L159-L159]). Embedded storefront scripts also call `api.shopagain.io` directly [mercury_ui/public/shopify/widgets.js:L31-L31], [mercury_ui/public/shopify/shopagain_script.js:L32-L32]. Web-app surface also referenced from UI at `app.shopagain.io` [mercury_ui/src/components/viewComponents/Campaign/Create/Steps/Compose/SmsTemplateCreator/SmsEditorForm/TextEditor/TestMessageModal.tsx:L182-L182].
- **Mobile app (ShopAgainMobile)** — `VITE_API_ROOT=https://api.shopagain.io` in both dev and prod env files [ShopAgainMobile/.env.development:L1-L1], [ShopAgainMobile/.env.production:L1-L1], wired through axios config [ShopAgainMobile/src/api/axiosConfig.tsx:L8-L8], [ShopAgainMobile/src/api/axiosConfig.tsx:L37-L37].

### API backend
- **mercury_api** — Django/WSGI service. Apache vhost for `api.shopagain.io` routes to `wsgi:/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-L7]. Backend settings declare `API_URL=https://api.shopagain.io/` [mercury_api/mercury_api/settings/shopagain_prod.py:L2-L2], `SMS_WEBHOOK_URL` on the same domain [mercury_api/mercury_api/settings/shopagain_prod.py:L4-L4], and cookie-domain scoping [mercury_api/mercury_api/settings/shopagain_prod.py:L48-L49]. The web-app URL `https://app.shopagain.io/` is set as `APP_URL` and `POPUP_JS_BASE_URL` in shopagain_prod/prod/azure_prod settings [mercury_api/mercury_api/settings/shopagain_prod.py:L1-L1], [mercury_api/mercury_api/settings/prod.py:L1-L1], [mercury_api/mercury_api/settings/prod.py:L7-L7], [mercury_api/mercury_api/settings/azure_prod.py:L1-L1], [mercury_api/mercury_api/settings/azure_prod.py:L7-L7]. Customer-support flows and Shopify theme extension also use the app URL [mercury_api/campaigns/customer_support_utils.py:L811-L811], [mercury_api/shopify_app/theme-app-extension/assets/script.js:L1-L1].
- **latticeai-terraform** declares the web-app hostname `app.shopagain.io` [latticeai-terraform/prod/variables.tf:L75-L75].

### Webhooks
- **mercury_webhooks** — Zappa-deployed with custom domains `webhooks.shopagain.io` [mercury_webhooks/zappa_settings.json:L137-L137] and `staging-webhooks.shopagain.io` [mercury_webhooks/zappa_settings.json:L109-L109]; calls back into `https://api.shopagain.io` [mercury_webhooks/common/configmanager/prod.ini:L28-L28].
- Public docs confirm the dual surface `api.shopagain.io` + `webhooks.shopagain.io` [shopagain_api_docs/openapi/openapi.yaml:L45-L47], [shopagain_api_docs/openapi/paths/webhook.yaml:L10-L10], [shopagain_api_docs/dist.json:L14-L14].

### Tracking / email link domains
- **mercury_tracking** — Zappa custom domains `shopagainmail.net` (prod) [mercury_tracking/zappa_settings.json:L53-L53] and `staging.shopagainmail.net` (staging) [mercury_tracking/zappa_settings.json:L26-L26]; calls `https://api.shopagain.io` from worker config [mercury_tracking/common/configmanager/prod.ini:L8-L8].
- API backend's `TRACKING_BASE_URL` resolves to `https://shopagainmail.net` in prod/shopagain_prod [mercury_api/mercury_api/settings/prod.py:L72-L72], [mercury_api/mercury_api/settings/shopagain_prod.py:L71-L71] and `https://staging.shopagainmail.net` in staging/dev [mercury_api/mercury_api/settings/staging.py:L76-L76], [mercury_api/mercury_api/settings/dev.py:L76-L76].

### Campaign delivery pipeline (event lineage)
- **Producer** — `mercury_api` enqueues to SQS `la-prod-campaign-messages` from `campaigns.processor.user_messaging.send_email_to_queue` via `boto3.resource('sqs').Queue(...).send_message`, resolved from `settings.CAMPAIGN_MESSAGE_SQS` [mercury_api/campaigns/processor/user_messaging.py:L469-L469].
- **Consumer** — `mercury_campaign_messages` binds the SQS ARN `arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages` to `mercury_campaign_messages.email_sender.process_campaign_message_delivery` via Zappa event_source (stage=prod) [mercury_campaign_messages/zappa_settings.json:L73-L73]. The worker calls back into `https://api.shopagain.io` [mercury_campaign_messages/mercury_campaign_messages/configmanager/prod.ini:L8-L8].
- Channel: `sqs:la-prod-campaign-messages` (with staging/dev variants `la-staging-campaign-messages`, `la-dev-campaign-messages` per resolver). No downstream event channels are reported in the packet for this consumer.

### Realtime / chat
- **mercury_websocket** — Serverless WebSocket route `ANY /postChatMessage` → handler `handler.postChatMessage` [mercury_websocket/serverless.yml:L36-L36]. No domain mapping in packet.

### ML
- **mercury_ml_api** depends on packaged library `mercury_ml` (provider package `la_mercury_ml`) [mercury_ml/pyproject.toml:L1-L1]. **No deploy/domain mapping for the ML API was found** (deploy_prod_ml_api retrieval returned nothing).

### Domain → backend summary
| Domain | Backend |
|---|---|
| api.shopagain.io | mercury_api via Apache → `prod_shopagain_wsgi.py` [ansible-playbooks/apache/prod_shopagain.conf:L2-L7] |
| app.shopagain.io | Web app (mercury_ui); declared in Terraform [latticeai-terraform/prod/variables.tf:L75-L75]; no Apache/WSGI route in packet |
| webhooks.shopagain.io / staging-webhooks.shopagain.io | mercury_webhooks (Zappa) [mercury_webhooks/zappa_settings.json:L137-L137], [mercury_webhooks/zappa_settings.json:L109-L109] |
| shopagainmail.net / staging.shopagainmail.net | mercury_tracking (Zappa) [mercury_tracking/zappa_settings.json:L53-L53], [mercury_tracking/zappa_settings.json:L26-L26] |
| (no domain in packet) | mercury_websocket, mercury_campaign_messages, mercury_ml_api |

### Caveats

- Only api.shopagain.io has an explicit Apache→WSGI route in the packet; app.shopagain.io appears only as Terraform/config literals, not as a routed deploy target.
- Campaign-message consumer (mercury_campaign_messages) is not shown producing any downstream event channel in this packet.
- Websocket service has a route but no domain binding in the packet.

### Unknown Because Missing Evidence

- Deploy target for mercury_ml_api (deploy_prod_ml_api returned no facts).
- Whether app.shopagain.io is served by a specific WSGI/static backend (no Apache vhost evidence in packet).
- Any downstream event channel produced by mercury_campaign_messages after consuming la-prod-campaign-messages.

### Self-Score Notes

Answer covers all expected building blocks (web/mobile clients, API backend with Apache→WSGI route, webhooks, tracking, campaign producer+consumer lineage on sqs:la-prod-campaign-messages, websocket service, ML API library dependency) with inline citations, and explicitly flags missing deploy evidence for the ML API and absent downstream event edges as required.
