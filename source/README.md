# Source KG Module

Status: first implementation slice.

This is a minimal local knowledge-graph harness for testing the KG shape before Postgres/AGE and MCP are wired in.

## What It Does

- Reads a local Python or TypeScript/JavaScript repository.
- Can combine multiple local repositories into one snapshot.
- Extracts repo, service, module, symbol, import, and basic call facts with file/line evidence.
- Links imported external packages to another indexed repo/service when a unique manifest package-name match exists.
- Writes `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json`.
- Provides small query scripts for summary, callers, blast radius, and imports.

## What It Does Not Do Yet

- No Postgres or Apache AGE persistence.
- No MCP server.
- No PR bot.
- No broad language coverage.
- Multi-repo linking is manifest/package-name based only; it does not infer aliases with an LLM.
- TypeScript/JavaScript support is parser-backed but still static; it does not perform full type-aware resolution yet.
- No automatic LLM enrichment in the default path.

## Layout

- `source/kg/extraction/python/` contains Python AST extraction.
- `source/kg/extraction/typescript/` contains TypeScript/JavaScript compiler-API extraction.
- `source/kg/normalization/python/` contains Python import normalization.
- `source/kg/normalization/typescript/` contains TypeScript/JavaScript import normalization.
- `source/kg/aggregations.py` contains language-independent ranked/grouped query helpers over normalized facts.

## Run

Install the local TypeScript parser dependency before indexing TypeScript/JavaScript repos:

```bash
npm install
```

```bash
python -m source.scripts.build_kg --repo ~/work/mercury_ml --out data/kg_runs/mercury_ml
python -m source.scripts.build_kg --repo ~/work/true_loop --out data/kg_runs/true_loop
python -m source.scripts.build_multi_kg --repo ~/work/orgs/latticeai/mercury_ml --repo ~/work/orgs/latticeai/mercury_ml_api --out data/kg_runs/latticeai_ml_pair
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml summary
python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_ml_pair cross-repo-links --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/latticeai_ml_pair repo-dependencies mercury_ml_api --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing pandas --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-info os
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml who-imports mercury_ml.chatbot.apis.openai_instructor --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-internal-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-fan-in-symbols --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing-both pandas sklearn --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-path predict_on_session sklearn --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml find-callers predict --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml find-callers load_model --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml find-callees predict_on_session --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop lookup-symbol generateResponseStream
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop lookup-symbol generateResponse --path src/lib/response-generator.ts --line 635
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop symbols-in-file src/lib/response-generator.ts
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop evidence-for-call generateResponse generateResponseStream --path src/lib/response-generator.ts --line 635
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop blast-radius generateResponseStream --depth 1 --limit 5
```

## LLM Policy

The v0 extractor is deterministic and does not call an LLM.

If later enrichment needs an LLM, use `source.kg.llm.LightLlmClient`. It reads `OPENAI_API_KEY` from the environment and defaults to `gpt-4.1-mini`, overrideable via `SUPERCONTEXT_LLM_MODEL`.
