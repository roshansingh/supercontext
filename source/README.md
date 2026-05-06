# Source KG Module

Status: first implementation slice.

This is a minimal local knowledge-graph harness for testing the KG shape before Postgres/AGE and MCP are wired in.

## What It Does

- Reads a local Python repository.
- Extracts repo, service, module, symbol, import, and call facts with file/line evidence.
- Writes `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json`.
- Provides small query scripts for summary, callers, blast radius, and imports.

## What It Does Not Do Yet

- No Postgres or Apache AGE persistence.
- No MCP server.
- No PR bot.
- No broad language coverage.
- No automatic LLM enrichment in the default path.

## Run

```bash
python -m source.scripts.build_kg --repo ~/work/mercury_ml --out data/kg_runs/mercury_ml
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml summary
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing pandas --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-info os
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml find-callers predict --limit 5
```

## LLM Policy

The v0 extractor is deterministic and does not call an LLM.

If later enrichment needs an LLM, use `source.kg.llm.LightLlmClient`. It reads `OPENAI_API_KEY` from the environment and defaults to `gpt-4.1-mini`, overrideable via `SUPERCONTEXT_LLM_MODEL`.
