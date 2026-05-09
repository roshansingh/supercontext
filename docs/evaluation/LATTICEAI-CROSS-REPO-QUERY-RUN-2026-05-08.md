# LatticeAI Cross-Repo Query Run - 2026-05-08

## Snapshot

Fixture: `/Users/maruti/work/orgs/latticeai`

Snapshot: `data/kg_runs/latticeai_23`

Build summary:

| Metric | Value |
|---|---:|
| Repos indexed | 23 |
| Entities | 17,570 |
| Facts | 47,117 |
| Evidence rows | 95,791 |
| Coverage rows | 61 |
| Extractor errors | 0 |
| Cross-repo link facts | 4 |

Current KG scope: Python AST extraction, TS/JS compiler extraction, static config extraction, import normalization, symbol lookup, local call lookup, package-to-repo/service linking, contract reconciliation, and product evidence packets.

Current KG now models deterministic domains/env vars, HTTP endpoint strings, Django/Flask/OpenAPI endpoint declarations, basic frontend API calls, Zappa/serverless event sources, SQS queue names, and Apache/WSGI deploy mappings.

Current KG does not yet model: deep Terraform/Ansible resource semantics, PHP/WooCommerce semantics, PR diffs, runtime traces, full endpoint-to-handler resolution, feature aggregation, or source-byte Mode A retrieval as a first-class command for this fixture.

## Commands Run

| Purpose | Command |
|---|---|
| Snapshot summary | `python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_23 summary` |
| Cross-repo links | `python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_23 cross-repo-links --limit 30` |
| ML repo dependency | `python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_23 repo-dependencies mercury_ml_api --limit 20` |
| Error package dependency | `python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_23 repo-dependencies mercury_api --limit 20` |
| Vendor/import probes | `modules-importing stripe/shopify/woocommerce/sentry_sdk/@sentry/react/boto3/requests` |
| Symbol probes | `lookup-symbol campaign/postChatMessage/prod_shopagain_wsgi/auth/process` |
| Local call probes | `find-callers postChatMessage`, `find-callees postChatMessage` |
| Domain/deploy probes | `domain-references api.shopagain.io`, `deploy-mappings --target prod_shopagain_wsgi.py` |
| Endpoint probes | `endpoints --path /api/token`, `endpoints --path /v1/stripe`, `endpoints --path /v1/company` |
| Event probes | `event-channels --channel la-prod-campaign-messages` |
| Contract reconciliation | `reconcile-contract --identity-key endpoint_path ... DOCUMENTS_ENDPOINT ... EXPOSES_ENDPOINT` |
| Goldset evidence packets | `python -m source.scripts.run_goldset_scenario --snapshot data/kg_runs/latticeai_23 --out docs/evaluation/LATTICEAI-GOLDSET-EVIDENCE-PACKETS-2026-05-08.json` |

## Key Observations

| Finding | Evidence |
|---|---|
| Multi-repo package linking works for the current deterministic cases. | `mercury_ml_api -> mercury_ml` and `mercury_api -> hipo-drf-exceptions`, each linked to repo and service. |
| Feature/vendor import discovery is useful but not sufficient for end-to-end answers. | Stripe, Shopify, WooCommerce, Sentry, boto3, and requests imports are found with file/line evidence. |
| Symbol lookup works on exact symbols. | `postChatMessage` resolves to `mercury_websocket/handler.py:189`; `Campaign` resolves to `mercury_api/campaigns/models/campaign.py:127`. |
| Reverse local calls remain limited by indexed static calls. | `postChatMessage` has no indexed callers, but its callees include `json.loads` and `requests.post`. |
| Deploy/config names are now visible as config facts. | `deploy-mappings --target prod_shopagain_wsgi.py` returns `api.shopagain.io -> /home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py`. |
| Static config extraction directly improved product-validation coverage. | Smoke checks found `api.shopagain.io` domain refs, `/api/token` callers/routes, `/v1/stripe`, `/v1/company`, `la-prod-campaign-messages`, and Apache WSGI mappings. |
| Generic contract reconciliation now catches endpoint contract drift without query-specific logic. | Q100 docs-vs-backend returns 6 matched paths, 1 documented-only path, 5 backend-only paths, and a possible rename `/v1/collections` -> `/v1/product_collections`. |
| Ambiguous broad terms need a higher-level product/query layer. | `auth` returns 78 candidates; `process` returns multiple exact candidates. |

## Q081-Q110 Results

Status meanings:

| Status | Meaning |
|---|---|
| Pass | Current KG can answer the core query mechanically. |
| Partial | Current KG returns useful evidence, but misses required parts of the expected answer. |
| Blocked | Missing fact types/extractors/query surface, not just missing data. |

| ID | Status | Current Result | Main Gap |
|---|---|---|---|
| Q081 | Partial | KG can list repos/services and map `api.shopagain.io` to the WSGI backend via Apache deploy facts. | Needs service-topology aggregation to combine repos, deploy mappings, clients, and runtime/service identity into one answer. |
| Q082 | Partial | `domain-references api.shopagain.io` finds 47 refs and `deploy-mappings --target prod_shopagain_wsgi.py` maps the domain to the WSGI backend. | Needs product-layer grouping to combine web/mobile env-var refs with deployed backend in one answer. |
| Q083 | Pass | `endpoints --path /api/token` finds backend token routes plus mobile callers; `endpoints --path auth` finds web auth callers and backend auth routes. | Add endpoint equivalence/grouping later. |
| Q084 | Partial | Stripe imports found in `mercury_api` billing modules and `mercury_webhooks/views/Stripe.py`. | UI flow mapping, webhook route semantics, billing feature aggregation. |
| Q085 | Partial | WooCommerce imports found in `mercury_api` modules; plugin repo is indexed only as generic TS/JS/PHP-adjacent files. | PHP/plugin semantics, payload/entity extraction, docs-code linking. |
| Q086 | Pass | `mercury_ml_api` deterministically resolves package dependency to `mercury_ml`. | Add deploy/test recommendations in product layer later. |
| Q087 | Partial | Library-to-service dependency is present: `mercury_ml_api -> mercury_ml`. | Deploy playbook/config extraction and ML feature-symbol grouping. |
| Q088 | Partial | `event-channels --channel la-prod-campaign-messages` finds queue config in `mercury_api` and Zappa consumer in `mercury_campaign_messages`. | Needs producer send-site classification beyond config references. |
| Q089 | Blocked | `Campaign` model is indexed, but no async workflow path is modeled. | Event/queue edges and feature-level aggregation. |
| Q090 | Blocked | Some Mailgun/request imports are visible, but event handling taxonomy is not. | Event taxonomy and tracking-domain extraction. |
| Q091 | Blocked | Webhook repo code is indexed, but source systems and normalization flows are not modeled. | Webhook route/source extraction plus downstream edges. |
| Q092 | Partial | Chat repos are indexed and `postChatMessage` is found. | Widget/client route callers, websocket route config, backend callback mapping. |
| Q093 | Partial | `postChatMessage` resolves to `mercury_websocket/handler.py:189`; serverless websocket route config is indexed as endpoint/event facts. | Needs client websocket sender/listener extraction and callback concatenation resolution. |
| Q094 | Blocked | `mercury_api` code indexed, but deployables/domains/workers are not. | Apache, WSGI, Celery, Terraform, Ansible extraction. |
| Q095 | Pass | `deploy-mappings --target prod_shopagain_wsgi.py` maps `api.shopagain.io` to `/home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py`. | Product answer should join this with domain refs from clients. |
| Q096 | Blocked | Scheduled jobs are not represented as facts. | Zappa scheduled event extraction and callable-handler linking. |
| Q097 | Partial | Sentry imports found in `mercury_api/settings/__init__.py`, `mercury_ui/src/store/AuthState.ts`, and `shopagain-chat-widget/helpers/analytics.ts`. | Initialization-call recognition and broader observability package aliases. |
| Q098 | Blocked | Vendor imports can be listed, but PII data flow is not modeled. | PII field/entity detection and data-flow/vendor edges. |
| Q099 | Pass | `mercury_api -> hipo-drf-exceptions` link exists; 9 importing modules found, including billing, campaigns, companies, Shopify, WooCommerce. | Add frontend error-consumer detection later. |
| Q100 | Pass | Contract reconciliation compares docs-vs-backend and clients-vs-docs by endpoint path. It returns matched, documented-only, backend-only, and possible rename groups with file/line evidence. | Later synthesis should explain caveats in natural language. |
| Q101 | Partial | Frontend/mobile API calls are indexed as `CALLS_ENDPOINT`. | Needs docs-minus-client reconciliation query. |
| Q102 | Partial | Domain and env config facts exist through `Domain`, `EnvVar`, `REFERENCES_DOMAIN`, and `REFERENCES_ENV_VAR`. | Needs environment classification and mismatch detection across prod/staging/local configs. |
| Q103 | Partial | Shopify imports found across backend billing, campaigns, messaging, and shopify_app modules. | OAuth/store-install route grouping, UI step mapping, docs links. |
| Q104 | Blocked | WooCommerce backend imports are visible, but plugin-to-backend payload flow is not. | PHP/plugin extraction, webhook payload modeling, docs contract links. |
| Q105 | Blocked | boto3 imports are visible, but infra-to-service dependencies are not. | Terraform/Ansible/Zappa network/IAM extraction. |
| Q106 | Partial | `event-channels --channel la-prod-campaign-messages` finds `CAMPAIGN_MESSAGE_SQS` refs and Zappa consumer handler. | Needs send-site producer classification. |
| Q107 | Blocked | PR input and rollout planning are outside current KG query surfaces. | PR diff ingestion plus compatibility/planning layer. |
| Q108 | Partial | Snapshot exposes coverage rows and uninstrumented parse failures. | Per-repo/language coverage report grouped by blocked query IDs. |
| Q109 | Partial | Tracking domains are indexed as `Domain` refs. | Needs domain-to-feature grouping and route-handler linkage. |
| Q110 | Blocked | `Campaign` model resolves, but downstream UI/jobs/queues/tracking paths are not connected. | Feature aggregation, endpoint/event/deploy edges, multi-hop traversal. |

## Result Summary

| Bucket | Count |
|---|---:|
| Pass | 5 |
| Partial | 15 |
| Blocked | 10 |

## Recommended Next Feature

The completed implementation was **deterministic config/API/event extraction**, not more graph traversal.

Focused scope:

| Extractor | Why it matters |
|---|---|
| Domain/env extractor | Added `Domain` and `EnvVar` entities plus `REFERENCES_DOMAIN` and `REFERENCES_ENV_VAR` facts. |
| HTTP endpoint/caller extractor | Added `Endpoint` entities plus `EXPOSES_ENDPOINT`, `CALLS_ENDPOINT`, and `DOCUMENTS_ENDPOINT` facts. |
| Deploy/event config extractor for Zappa/serverless/Apache | Added `DeployTarget` and `EventChannel` entities plus deploy, event reference, and consume facts. |

The follow-up implementation added a small product layer over these facts:

| Component | Why it matters |
|---|---|
| Scenario retrieval plans | Turns selected goldset questions into deterministic KG steps. |
| Evidence packet builder | Normalizes retrieved facts into claim/evidence rows for later source-byte verification and answer synthesis. |
| Contract reconciliation | Compares scoped fact sets by identity key and surfaces `matched`, `left_only`, `right_only`, and `possible_matches`. |

Next product-validation feature should be source-byte verification plus answer synthesis over evidence packets, not another broad extractor.
