# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a documentation-heavy architecture repo plus a minimal KG prototype.

- `adr/` contains accepted architecture decision records. Keep decisions here once finalized.
- `docs/` contains PRDs, research notes, ontology, graph storage/building, evidence retrieval, and evaluation artifacts.
- `debates/` contains multi-agent debate transcripts and state files.
- `source/` contains the executable KG prototype.
- `source/kg/extraction/python/` and `source/kg/extraction/typescript/` contain language-specific extractors.
- `source/kg/normalization/python/` and `source/kg/normalization/typescript/` contain deterministic normalization logic.
- `source/scripts/` contains CLI entry points for building and querying KG snapshots.
- `data/kg_runs/` stores generated local KG snapshots; treat these as test artifacts.

## Build, Test, and Development Commands

Use Python module commands from the repository root.

```bash
python -m compileall -q source
```

Checks Python syntax/import validity for the prototype.

```bash
python -m source.scripts.build_kg --repo ~/work/mercury_ml --out data/kg_runs/mercury_ml
python -m source.scripts.build_kg --repo ~/work/true_loop --out data/kg_runs/true_loop
```

Builds KG snapshots for Python and TS/JS fixture repos.

```bash
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop summary
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop find-callers generateResponseStream --limit 5
```

Runs smoke queries against a generated snapshot.

## Coding Style & Naming Conventions

Prefer small, language-scoped modules over large generic scripts. Keep deterministic extraction and normalization separate. Use descriptive names such as `PythonAstExtractor`, `TypeScriptCompilerApiExtractor`, and `normalize_import`. Python code should follow standard 4-space indentation and type hints where useful. Avoid LLM calls in default extraction paths; if enrichment is added, route it through `source.kg.llm.LightLlmClient`.

## Testing Guidelines

There is no full test suite yet. For now, verify changes with `compileall`, at least one KG build, and one or more query smoke checks. For behavior changes, add or update a concise note under `docs/evaluation/` with before/after results. Do not claim language support without fixture evidence.

## Commit & Pull Request Guidelines

Use short imperative commit messages, matching the current history, for example `Add deterministic import normalization` or `Add parser-backed TypeScript extraction`. PR descriptions should include summary, scope, verification commands, and evaluation delta when behavior changes. Link relevant ADRs or docs when the PR implements an architectural decision.

## Agent-Specific Instructions

Keep changes surgical. Do not rewrite ADRs, research docs, or generated data unless the task requires it. When implementation uncovers a product or architecture decision, document the finding instead of silently expanding scope.
