# KG Count Baselines

These baselines are distilled regression gates for KG snapshot shape. They intentionally track aggregate counts and distributions, not identity-level facts.

Regenerate a baseline after rebuilding a corpus snapshot:

```bash
python -m source.scripts.capture_snapshot_baseline data/kg_runs/<snapshot_dir> --name <corpus_name> --out tests/baselines/kg_counts/<corpus_name>.json
```

Compare a regenerated snapshot against a committed baseline:

```bash
python -m source.scripts.compare_snapshot_baseline data/kg_runs/<snapshot_dir> --baseline tests/baselines/kg_counts/<corpus_name>.json
```

Use `--allow-additions` only when a feature is expected to add facts without removing existing coverage or counts. Extractor error count changes remain strict even with this flag.

## Baseline Change Notes

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
