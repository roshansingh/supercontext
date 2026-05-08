# Multi-Repo Linking Smoke

Status: implementation evaluation
Date: 2026-05-08
Feature: multi-repo snapshot builder plus deterministic package-to-repo/service linker

## Summary

The new multi-repo builder can combine many local repositories into one JSONL snapshot while preserving per-repo commit SHA, evidence, and coverage. The deterministic linker adds implementation-side `RESOLVES_TO_REPO` and `RESOLVES_TO_SERVICE` facts when an imported `ExternalPackage` uniquely matches another indexed repo's manifest package name or package-root alias.

This is intentionally not a canonical ontology expansion. The link facts are a local KG bridge for multi-repo evaluation until ADR/tool contracts define the final relation.

## Commands Run

| Area | Command | Result |
|---|---|---|
| Compile | `python -m compileall -q source` | Pass. |
| ML pair build | `build_multi_kg --repo mercury_ml --repo mercury_ml_api --out data/kg_runs/latticeai_ml_pair` | Pass: 2 repos, 653 entities, 1910 facts, 2 link facts. |
| ML pair query | `repo-dependencies mercury_ml_api` | Pass: `mercury_ml_api` resolves to provider repo `mercury_ml` via `pyproject.toml` evidence. |
| API pair build | `build_multi_kg --repo mercury_api --repo hipo-drf-exceptions --out data/kg_runs/latticeai_api_exceptions_pair` | Pass: 2 repos, 6066 entities, 17326 facts, 2 link facts. |
| API pair query | `repo-dependencies mercury_api` | Pass: `mercury_api` resolves to provider repo `hipo-drf-exceptions` via `pyproject.toml` evidence. |
| 23-repo LatticeAI build | `build_multi_kg` over all 23 repos in `/Users/maruti/work/orgs/latticeai` | Pass after adding root `typescript` dependency: 23 repos, 11698 entities, 33657 facts, 4 link facts, 0 ambiguous package matches, 0 extractor errors. |
| 23-repo link query | `cross-repo-links --limit 20` | Pass: returns repo/service links for `mercury_ml_api -> mercury_ml` and `mercury_api -> hipo-drf-exceptions`. |

## Findings

| Finding | Evidence | Comment |
|---|---|---|
| Multi-repo snapshot build works. | 23-repo run completed with `repo_count=23`, `entities=11698`, `facts=33657`, `coverage=38`. | This is enough to start running cross-repo product queries against one snapshot. |
| Deterministic package linking works for known Python package dependencies. | `mercury_ml_api -> mercury_ml`; `mercury_api -> hipo-drf-exceptions`. | Matching is by normalized unique package/alias only; no LLM inference. |
| Link evidence is source-backed. | Link evidence cites provider `pyproject.toml` with provider repo commit SHA. | Consumer-side import evidence is already present on the underlying `IMPORTS` facts. |
| TS parser dependency gap is resolved. | Root `package.json` adds `typescript`; 23-repo run now records `extractor_errors=[]`. | The previous failures were missing parser dependency, not repo syntax failures. |

## Remaining Gaps

| Gap | Impact |
|---|---|
| No package-to-repo linking for aliases that are not present in manifests or package roots. | Some real repo dependencies will remain external until explicit aliases or stronger metadata are added. |
| No domain/API/event/deploy linking yet. | Many valuable LatticeAI queries still require env/config/deploy extractors, not just package links. |
| JS/TS extraction remains shallow. | Parser-backed extraction now runs, but it is still static and not type-aware. |
| Query surfaces are local CLI only. | MCP/PR-bot contracts still need separate implementation. |

## Decision

This slice is successful as the first multi-repo substrate: it prevents false failures caused by disconnected package identity and gives us a single snapshot for product-query evaluation. The next highest-value work should be running the LatticeAI cross-repo query section against `data/kg_runs/latticeai_23` and using failures to choose the next extractor/linker.
