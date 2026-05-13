# KG Count Baselines

These baselines are distilled regression gates for KG snapshot shape. They intentionally track aggregate counts and distributions, not identity-level facts.

`latticeai_23.json` is captured from the public `data/kg_runs/latticeai_23` snapshot. The canonical validation report uses `data/kg_runs/private_goldset_eval_2026_05_11`, which keeps the private-goldset artifact path stable but currently uses only public OSS extractors. Apache/WSGI vhost and Zappa event-source extraction are public OSS again. Small count differences between these two artifacts are expected; compare each artifact only against the snapshot it names.

Regenerate a baseline after rebuilding a corpus snapshot:

```bash
python -m source.scripts.capture_snapshot_baseline data/kg_runs/<snapshot_dir> --name <corpus_name> --out tests/baselines/kg_counts/<corpus_name>.json
```

Compare a regenerated snapshot against a committed baseline:

```bash
python -m source.scripts.compare_snapshot_baseline data/kg_runs/<snapshot_dir> --baseline tests/baselines/kg_counts/<corpus_name>.json
```

Use `--allow-additions` only when a feature is expected to add facts without removing existing coverage or counts. Extractor error count changes remain strict even with this flag.

Public multi-repo fixture commands for `llm-app-stack` and `otel-demo` live in `examples/public-orgs/README.md`.

## Drift-Test Snapshot Mapping

`tests/test_baseline_drift.py` compares committed baselines against these local snapshot directories when they are present:

| Baseline | Local snapshot |
|---|---|
| `latticeai_23.json` | `data/kg_runs/latticeai_23` |
| `llm-app-stack.json` | `data/kg_runs/llm-app-stack` |
| `mercury_ml.json` | `data/kg_runs/mercury_ml_eval_2026_05_11` |
| `otel-demo.json` | `data/kg_runs/otel-demo` |
| `true_loop.json` | `data/kg_runs/true_loop_eval_2026_05_11` |

The Mercury ML and True Loop snapshots currently use dated directories because those are the validation snapshots used by the canonical product report. If those snapshots are regenerated under new dated directories, update the mapping in the drift test in the same PR as the baseline update.

## Baseline Change Notes

- `llm-app-stack` public-corpus baseline: initial capture from five local public repos (`langfuse`, `langfuse-python`, `litellm`, `open-webui`, `open-webui-pipelines`) with 0 extractor errors, 523 package-linker edges, 112443 entities, 299505 facts, 685030 evidence rows, and 966 coverage rows.
- `otel-demo` public-corpus baseline: initial capture from local `opentelemetry-demo` checkout with 0 extractor errors, 2138 entities, 3296 facts, 6721 evidence rows, and 9 coverage rows.
- `true_loop` PR-C import-normalizer introspection: `ExternalPackage` 91 -> 92 and total entities 1814 -> 1815 because `fs/promises` is now preserved as its own Node builtin submodule instead of collapsing to `fs`. Mercury ML and LatticeAI 23 stayed unchanged.
- `mercury_ml` PR-E config scan observability: coverage 5 -> 6 because `mercury_ml/chatbot/frustration_classification/frustration-data/embeddings_cache.json` is 4.18 MB and now emits `exceeds_max_scan_bytes` coverage instead of silently skipping.
- `latticeai_23` PR-E config scan observability: coverage 93 -> 100 because seven oversized JSON config/template files in `mercury_api` now emit `exceeds_max_scan_bytes` coverage instead of silently skipping: `campaigns/management/commands/popup_library_02_06_23.json`, `engagement/static_email_templates/email_library_templates.json`, `engagement/static_email_templates/new_templates.json`, `engagement/static_email_templates/templates_01_06_23.json`, `engagement/static_email_templates/templates_16_02_23.json`, `engagement/static_email_templates/templates_json.json`, and `engagement/static_email_templates/themed.json`.
- `true_loop` PR-F'.1 dotenv parser: entities 1815 -> 1816, facts 3648 -> 3668, evidence 7677 -> 7764, `EnvVar` 100 -> 101, `REFERENCES_DOMAIN` 597 -> 586, and `REFERENCES_ENV_VAR` 137 -> 168 because `.env*` files now use the deterministic dotenv parser. This removes duplicated URL+hostname domain facts while capturing all valid `.env.example` assignments.
- `latticeai_23` PR-F'.1 dotenv parser: entities 16834 -> 16864, facts 45585 -> 45589, evidence 91688 -> 91780, `Domain` 3998 stayed unchanged, `EnvVar` 528 -> 558, `REFERENCES_DOMAIN` 10412 -> 10376, and `REFERENCES_ENV_VAR` 764 -> 804 for the same parser-backed `.env*` ownership change. Mercury ML stayed unchanged.
- `true_loop` PR-F'.3 TypeScript endpoint parser: `Endpoint` 24 -> 19 and `CALLS_ENDPOINT` 34 -> 26 because broad JS/TS endpoint regexes were replaced with parser-backed Express route extraction plus parser-backed `fetch`/`axios` client calls. Arbitrary `.get()`/`.post()` patterns and mock-handler-style calls are no longer treated as endpoint calls.
- `latticeai_23` PR-F'.3 TypeScript endpoint parser: `Endpoint` 523 -> 233 and `CALLS_ENDPOINT` 320 -> 4 for the same reason. The `parser_backed_js_ts_endpoint_extraction_deferred` coverage rows were replaced by explicit partial coverage rows for Express-only route extraction and fetch/axios-only client-call extraction.
- `latticeai_23` PR-F'.4 Apache vhost move: `DeployTarget` 6 -> 0, `Domain` 3998 -> 3996, `REFERENCES_DOMAIN` 10376 -> 10370, `ROUTES_DOMAIN_TO_DEPLOY` 6 -> 0, and coverage 100 -> 109 because Apache vhost/WSGI extraction moved out of OSS `source/` into the private goldset example extension while public extraction now emits `no_oss_adapter_for_apache_vhosts` coverage. Mercury ML and True Loop stayed unchanged.
- `latticeai_23` PR-F'.5 Zappa move: `CONSUMES_EVENT` 63 -> 54, facts 45261 -> 45252, evidence 90999 -> 90981, and coverage 109 -> 111 because Zappa SQS event-source extraction moved out of OSS `source/` into the private goldset example extension while public extraction now emits `no_oss_adapter_for_zappa_event_sources` coverage. Mercury ML and True Loop stayed unchanged.
- `latticeai_23` PR-F'.6 serverless.yml parser: `Endpoint` 233 -> 234, `EXPOSES_ENDPOINT` 220 -> 221, facts 45252 -> 45253, and evidence 90981 -> 90983 because `mercury_websocket/serverless.yml` now parser-extracts the `httpApi` `POST /reply` route in addition to the existing websocket routes. Mercury ML and True Loop stayed unchanged.
- `true_loop` JS/TS endpoint caller resolution v1: `Endpoint` 19 -> 18, `CALLS_ENDPOINT` 26 -> 25, and coverage 6 -> 13 because parser-backed client-call extraction now suppresses external full-URL calls (`https://api.vapi.ai/call/{}` and `https://texttospeech.googleapis.com/v1/text:synthesize?key={}`) instead of treating them as internal endpoints, and emits per-call-site coverage for two `external_endpoint_suppressed` and five `unresolved_target` fetch/axios targets.
- `latticeai_23` JS/TS endpoint caller resolution v1: `Endpoint` 234 -> 235, `CALLS_ENDPOINT` 4 -> 5, facts 45253 -> 45254, evidence 90983 -> 90985, and coverage 111 -> 143 because `ShopAgainMobile/src/api/axiosConfig.tsx` now resolves the env-host axios refresh call to `/api/token/refresh/` with `confidence=host_unresolved_path_resolved`, while parser-recognized but unresolved/external client targets emit explicit call-site coverage (`unresolved_target`: 30, `unresolved_host`: 1, `external_endpoint_suppressed`: 1). Mercury ML stayed unchanged because it has no JS/TS files.
- `latticeai_23` JS/TS imported axios provenance v1: `Endpoint` 235 -> 642, `CALLS_ENDPOINT` 5 -> 454, facts 45254 -> 45703, evidence 90985 -> 91895, and coverage 143 -> 621 because single-hop relative imports of proven exported `axios.create(...)` clients now emit `CALLS_ENDPOINT` facts. The coverage growth is expected from `unresolved_host` rows attached to env-host resolved calls (`1 -> 456`) plus unresolved targets on proven imported clients (`30 -> 53`). True Loop stayed unchanged after non-client relative imports were made fail-closed without coverage.
- `latticeai_23` Apache/WSGI OSS promotion: `DeployTarget` 0 -> 6, `Domain` 3996 -> 3998, `REFERENCES_DOMAIN` 10370 -> 10376, `ROUTES_DOMAIN_TO_DEPLOY` 0 -> 6, entities 16975 -> 16983, facts 45703 -> 45715, evidence 91895 -> 91916, and coverage 621 -> 612 because public extraction now emits parser-backed Apache vhost facts and removes the nine `no_oss_adapter_for_apache_vhosts` rows.
- `latticeai_23` Zappa event-source OSS promotion: `CONSUMES_EVENT` 54 -> 63, facts 45715 -> 45724, evidence 91916 -> 91934, and coverage 612 -> 610 because public extraction now emits parser-backed Zappa SQS event-source consumer facts and removes the two `no_oss_adapter_for_zappa_event_sources` rows.
- `latticeai_23` Terraform literal-domain extraction: `Domain` 3998 -> 4015, `REFERENCES_DOMAIN` 10376 -> 10397, entities 16983 -> 17000, facts 45724 -> 45745, evidence 91934 -> 91987, and coverage stayed 610 because simple Terraform `variable`/`resource` string literals now emit domain references while interpolation, lists, objects, and module blocks remain fail-closed.
- `latticeai_23` Terraform module/list widening: `Domain` 4015 -> 4016, `REFERENCES_DOMAIN` 10397 -> 10399, entities 17000 -> 17001, facts 45745 -> 45747, evidence 91987 -> 91991, and coverage stayed 610 because Terraform now reads quoted list literals and `module.source` git hosts while remaining fail-closed for interpolation, objects, heredocs, and multi-line lists.
- `llm-app-stack` and `otel-demo` JS/TS route parser widening: no `EXPOSES_ENDPOINT` count change in the current public snapshots; coverage reason changed from `parser_backed_js_ts_route_extraction_partial_express_only` to `parser_backed_js_ts_route_extraction_partial_express_fastify_koa_only` because the parser now supports literal Express, Fastify, and Koa route receivers. Current public corpora do not add new Fastify/Koa route facts under the v1 literal-path patterns.
