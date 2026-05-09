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
python -m unittest discover -s tests
```

Checks Python syntax/import validity and the focused regression tests for the prototype.

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

Prefer small, language-scoped modules over large generic scripts. Keep deterministic extraction and normalization separate. Use descriptive names such as `PythonAstExtractor`, `TypeScriptCompilerApiExtractor`, and `normalize_import`. Python code should follow standard 4-space indentation and type hints where useful. Avoid LLM calls in default extraction paths; if enrichment is added, route it through `source.kg.integrations.llm.LightLlmClient`.

## Testing Guidelines

There is no full test suite yet. For now, verify changes with `compileall`, at least one KG build, and one or more query smoke checks. For behavior changes, add or update a concise note under `docs/evaluation/` with before/after results. Do not claim language support without fixture evidence.

## Commit & Pull Request Guidelines

Use short imperative commit messages, matching the current history, for example `Add deterministic import normalization` or `Add parser-backed TypeScript extraction`. PR descriptions should include summary, scope, verification commands, and evaluation delta when behavior changes. Link relevant ADRs or docs when the PR implements an architectural decision.

## Agent-Specific Instructions

Keep changes surgical. Do not rewrite ADRs, research docs, or generated data unless the task requires it. When implementation uncovers a product or architecture decision, document the finding instead of silently expanding scope.

## Pre-PR Validation Discipline

Copilot has repeatedly caught boundary-condition mistakes in review. Before opening or updating a PR, explicitly check these patterns:

- Always run the project-local `.codex/skills/pre-pr-semantic-review` checklist before any `git push`, especially for extractor, normalization, query, loader, evaluation, or review-fix changes.
- Validate external JSON/input shapes before use. If a CLI accepts either a list or an object wrapper, branch on `isinstance(data, dict)` before calling `.get(...)`.
- Fail fast on malformed rows. Reject non-object rows, missing IDs, duplicate IDs, and padded IDs; normalize stored IDs after stripping whitespace.
- Validate list-shaped fields before rendering or iterating. Do not assume model outputs or loaded JSON contain `list[str]`; reject missing, non-list, or non-string values with field-specific errors.
- Treat sentinel values as contracts. Values like `"none"` must be mutually exclusive with failure values, and pass/fail scores must be consistent with their failure fields.
- Keep production defaults aligned with ADRs. If eval scripts need unsafe or non-interactive modes such as `dontAsk`, expose them through CLI/env config and keep library defaults policy-safe.
- Resolve executable dependencies early. If code shells out or relies on an SDK CLI, check path/config up front and raise an actionable error.
- Add targeted negative checks for each validation branch. A help/compile check is not enough when changing loaders, parsers, or LLM-output handling.
- For API extractors, test common equivalent call shapes before PR: positional args, keyword args, alias imports, chained calls, assigned clients/resources, and unresolved arguments. Do not stop at the single happy path.
- For AST extractors, test common statement variants too: `Assign`, `AnnAssign`, direct chained calls, and assigned intermediate objects.
- For Python AST semantics, test language rules that affect binding before PR: positional-only parameters, duplicate argument binding, missing required parameters, keyword-only parameters, local assignment/import/loop/with/except shadowing, parameter shadowing, lambda bodies, nested function/class bodies, and evaluated nested-scope expressions such as decorators, default args, class bases, and class keywords.
- Do not use whole-function facts when call-site-scoped facts are required. Local assignments, transport clients/resources, alias maps, and wrapper arguments must respect source order or fail closed.
- If a name is locally bound but not statically resolvable, do not let resolution fall through to a same-named module/global literal.
- Include Python 3.10+ `match/case` capture bindings in shadowing checks when wrapper or symbol resolution depends on local names.
- For inference/promotion features, fail closed on ambiguous multiplicity. If one call-site can map to multiple candidate facts and the output contract is not explicitly list-shaped, emit no promoted fact rather than a partial first result.
- When one AST helper is split into parallel collectors, keep their nested-scope semantics aligned or centralize the traversal policy. A fix in call collection often has an equivalent binding-collection case.
- If code has an unsupported/error branch, add a test that proves the branch is reachable. Do not leave fallback logic so broad that invalid inputs silently become canonical facts.
- When adding caches or indexes, check resource impact explicitly. Avoid retaining full file contents when only AST, line count, or metadata is needed.
- Keep allowlists as the single source of truth. Do not duplicate supported kinds, methods, transports, languages, or statuses in extractor logic.
- Run a self-review for hygiene before pushing: unused imports, dead locals, broad `Any`, duplicated parsing/IO, and helper signatures with unused parameters.
- For every Copilot-style fix, add a regression test that exercises the exact missed shape, especially keyword forms like `service_name=...` or resource factory args like `url=...`.
