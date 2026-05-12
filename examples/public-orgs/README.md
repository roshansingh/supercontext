# Public Org Fixtures

These fixtures are public multi-repo corpora used by the product query set
section Q056-Q080. They are intentionally separate from private goldset
fixtures and should be reproducible from local checkouts under one org root.

Set the org root before running commands:

```bash
export SUPERCONTEXT_ORGS_ROOT="${SUPERCONTEXT_ORGS_ROOT:-$HOME/work/orgs}"
```

## Expected Local Checkouts

- `llm-app-stack`: `$SUPERCONTEXT_ORGS_ROOT/llm-app-stack`
- `otel-demo`: `$SUPERCONTEXT_ORGS_ROOT/otel-demo`

If a checkout is missing locally, do not synthesize placeholder baselines.
Record the missing path in the PR notes and regenerate once the repos exist.

## Build Snapshots

Build the LLM app stack snapshot:

```bash
python -m source.scripts.build_multi_kg \
  --repo "$SUPERCONTEXT_ORGS_ROOT/llm-app-stack/langfuse" \
  --repo "$SUPERCONTEXT_ORGS_ROOT/llm-app-stack/langfuse-python" \
  --repo "$SUPERCONTEXT_ORGS_ROOT/llm-app-stack/litellm" \
  --repo "$SUPERCONTEXT_ORGS_ROOT/llm-app-stack/open-webui" \
  --repo "$SUPERCONTEXT_ORGS_ROOT/llm-app-stack/open-webui-pipelines" \
  --out data/kg_runs/llm-app-stack
```

Build the OpenTelemetry demo snapshot:

```bash
python -m source.scripts.build_multi_kg \
  --repo "$SUPERCONTEXT_ORGS_ROOT/otel-demo/opentelemetry-demo" \
  --out data/kg_runs/otel-demo
```

Builds are idempotent for these snapshot directories: the store opens each
JSONL output file in write mode and rewrites `manifest.json`.

## Capture Baselines

```bash
python -m source.scripts.capture_snapshot_baseline \
  data/kg_runs/llm-app-stack \
  --name llm-app-stack \
  --out tests/baselines/kg_counts/llm-app-stack.json

python -m source.scripts.capture_snapshot_baseline \
  data/kg_runs/otel-demo \
  --name otel-demo \
  --out tests/baselines/kg_counts/otel-demo.json
```

## Verify Baselines

```bash
python -m source.scripts.compare_snapshot_baseline \
  data/kg_runs/llm-app-stack \
  --baseline tests/baselines/kg_counts/llm-app-stack.json

python -m source.scripts.compare_snapshot_baseline \
  data/kg_runs/otel-demo \
  --baseline tests/baselines/kg_counts/otel-demo.json
```

Both compares should print `Snapshot matches baseline.`.

## Current Baseline Notes

- `llm-app-stack`: 5 repos, 6 Service entities, 0 extractor errors, 523 package-linker edges.
- `otel-demo`: 1 repo, 0 extractor errors, 0 package-linker edges.
- `data/kg_runs/` is ignored; commit only distilled baseline JSON and docs.

`llm-app-stack` has 6 Service entities for 5 repos because `langfuse-python`
emits both `langfuse` and `langfuse-python` service identities.
