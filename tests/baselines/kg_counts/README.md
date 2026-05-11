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
