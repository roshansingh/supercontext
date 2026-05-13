# Source KG Module

Status: first implementation slice.

This is a minimal local knowledge-graph harness for testing the KG shape before Postgres/AGE and MCP are wired in.

## What It Does

- Reads a local Python or TypeScript/JavaScript repository.
- Can combine multiple local repositories into one snapshot.
- Extracts repo, service, module, symbol, import, basic call, domain/env, endpoint, deploy, and event-channel facts with file/line evidence.
- Links imported external packages to another indexed repo/service when a unique manifest package-name match exists.
- Writes `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json`.
- Provides small query scripts for summary, callers, blast radius, and imports.
- Provides a product-validation runner that converts goldset scenario plans into normalized evidence packets.
- Provides a canonical validation runner for low/medium smoke checks plus goldset answer judgement.

## What It Does Not Do Yet

- No Postgres or Apache AGE persistence.
- No MCP server.
- No PR bot.
- No broad language coverage.
- Multi-repo linking is manifest/package-name based only; it does not infer aliases with an LLM.
- TypeScript/JavaScript support is parser-backed but still static; it does not perform full type-aware resolution yet.
- Evidence packets do not fetch source bytes yet; ADR-0005 Mode A verification should consume their `repo`, `commit_sha`, `path`, and line coordinates later.
- No automatic LLM enrichment in the default path.

## Layout

- `source/kg/core/` contains canonical dataclasses, repository discovery, display formatting, and JSONL storage.
- `source/kg/build/` contains single-repo and multi-repo KG build orchestration.
- `source/kg/query/` contains snapshot query surfaces, aggregations, and path search.
- `source/kg/extraction/python/` contains Python AST extraction.
- `source/kg/extraction/typescript/` contains TypeScript/JavaScript compiler-API extraction.
- `source/kg/extraction/config/` contains deterministic config extraction for domains, env vars, endpoints, deploy mappings, and event channels.
- `source/kg/normalization/python/` contains Python import normalization.
- `source/kg/normalization/typescript/` contains TypeScript/JavaScript import normalization.
- `source/kg/product/` contains public product-validation reports, evidence packets, answer synthesis, judgement, and contract reconciliation.
- `source/kg/integrations/` contains optional external service clients.
- `examples/private-goldset/` contains private scenario plans and local runners that consume the public `source/` package.
- `source/kg/product/evidence_packet.py` normalizes query results into synthesis-ready evidence packets.
- `source/kg/product/contract_reconciliation.py` compares two scoped sets of facts using a reusable contract identity key.
- Root-level `source/kg/*.py` files are compatibility wrappers for older imports; new code should import from the grouped packages above.

## Product-Validation Flow

The product path is intentionally split so we can measure KG value before adding agentic fallback:

```text
goldset scenario
-> retrieval plan
-> deterministic KG queries
-> evidence packet
-> source-byte verification later
-> Claude/LLM synthesis later
-> independent ground-truth judgement
-> scored product answer
```

Current validation thesis:

- KG-first retrieval should make many cross-repo answers materially faster and cheaper than asking Claude Code/Codex to rediscover the answer by searching repos from scratch.
- Speed/cost is not enough to validate the product; answer quality is the primary bar.
- Answer quality must be judged against independent ground truth, not by the same synthesis model that generated the answer.
- Failures should be classified as missing KG fact, bad retrieval plan, or bad synthesis before adding new features.

Retrieval plans decide which KG query surfaces to call. Private scenario plans live under `examples/private-goldset/`; public `source/` code consumes already-built EvidencePacket rows.

Evidence packets normalize raw facts into rows with `claim`, `fact_type`, `subject`, `object`, `repo`, `commit_sha`, `path`, `line_start`, `line_end`, `source_system`, `derivation_class`, and `confidence`. They are not final answers; they are the controlled input to source verification and later Claude synthesis.

Answer synthesis is intentionally thin: `source.scripts.run_goldset_answers` sends EvidencePacket rows to Claude Agent SDK with tools disabled and asks for a concise answer, citations, caveats, unknowns, and a `Pass` / `Partial` / `Fail` score. The agent is not allowed to search freely; KG retrieval decides the evidence.

Goldset judgement is separate from synthesis: `source.scripts.run_goldset_judgement` compares the independent ground-truth answer, the EvidencePacket, and the generated answer. Its job is to classify whether failures belong to missing KG facts, retrieval plans, synthesis, or ground-truth issues.

The canonical validation report is generated by `source.scripts.run_product_validation`. It runs deterministic low/medium smoke checks against the current Mercury ML, True Loop, and private goldset snapshots, summarizes the latest goldset packets/answers/judgements, and marks older dated evaluation artifacts as superseded.

Contract reconciliation is the generic primitive behind docs-vs-code, client-vs-backend, producer-vs-consumer, and deploy-vs-service checks. It takes two scoped fact sets, an identity key such as `endpoint_path`, and returns `matched`, `left_only`, `right_only`, and `possible_matches`. Scenario plans provide the domain-specific scope; the reconciler itself does not know about a specific product or API drift.

## Interactive UI

The optional Streamlit app gives evaluators a local UI for existing JSONL snapshots. It does not build snapshots or persist state.

```bash
pip install streamlit
SUPERCONTEXT_ORGS_ROOT=~/work/orgs streamlit run source/scripts/streamlit_app.py
```

The app discovers org directories from `SUPERCONTEXT_ORGS_ROOT` and complete snapshots under `data/kg_runs/`. It has two modes:

- Natural language: `source.kg.agent` uses Claude Agent SDK with tools disabled to plan anchors and synthesize from KG evidence. Retrieval still runs through deterministic `RetrievalStep` and `EvidencePacket` code.
- Direct query: six direct `KgSnapshot` query surfaces remain available for debugging: `summary`, `find_callers`, `modules_importing`, `top_dependencies`, `blast_radius`, and `lookup_symbol`.

Optional ground-truth JSON can be loaded from the sidebar for local evaluation. The OSS UI never imports private-goldset modules directly.

## Run

Install the local TypeScript parser dependency before indexing TypeScript/JavaScript repos:

```bash
npm install
```

```bash
python -m source.scripts.build_kg --repo ~/work/mercury_ml --out data/kg_runs/mercury_ml
python -m source.scripts.build_kg --repo ~/work/true_loop --out data/kg_runs/true_loop
python -m source.scripts.build_multi_kg --repo ~/work/orgs/example/ml_service --repo ~/work/orgs/example/backend_api --out data/kg_runs/multi_repo_fixture
python -m source.scripts.build_multi_kg --repo ~/work/orgs/example/ml_service --repo ~/work/orgs/example/backend_api --out data/kg_runs/multi_repo_fixture --strict-extractors
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml summary
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture cross-repo-links --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture repo-dependencies backend_api --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture domain-references api.example.com --limit 20
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture endpoints --path /api/token --limit 20
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture event-channels --channel orders-events --limit 20
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture deploy-mappings --target app_wsgi.py --limit 20
python -m source.scripts.query_kg --snapshot data/kg_runs/multi_repo_fixture reconcile-contract --name docs_vs_backend --identity-key endpoint_path --left-name documented --left-predicate DOCUMENTS_ENDPOINT --left-repo api_docs --left-path-prefix /v1/ --right-name implemented --right-predicate EXPOSES_ENDPOINT --right-repo backend_api --right-path-prefix /v1/
python examples/private-goldset/run_scenario.py --snapshot data/kg_runs/private_goldset --scenario Q082
python examples/private-goldset/run_scenario.py --snapshot data/kg_runs/private_goldset --scenario Q082 --scenario Q083 --out data/kg_runs/private_goldset/product_packets.json
python -m source.scripts.run_goldset_answers --snapshot private_goldset --packets-in data/kg_runs/private_goldset/product_packets.json --packets-out data/kg_runs/private_goldset/goldset_packets_for_answers.json --md-out docs/evaluation/GOLDSET-ANSWERS.md --json-out data/kg_runs/private_goldset/goldset_answers.json
python -m source.scripts.run_goldset_judgement --packets data/kg_runs/private_goldset/goldset_packets_for_answers.json --answers data/kg_runs/private_goldset/goldset_answers.json --md-out docs/evaluation/GOLDSET-JUDGEMENT.md --json-out data/kg_runs/private_goldset/goldset_judgement.json
python -m source.scripts.run_product_validation
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

If later enrichment needs an LLM, use `source.kg.integrations.llm.LightLlmClient`. It reads `OPENAI_API_KEY` from the environment and defaults to `gpt-4.1-mini`, overrideable via `SUPERCONTEXT_LLM_MODEL`.
