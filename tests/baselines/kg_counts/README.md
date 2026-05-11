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
