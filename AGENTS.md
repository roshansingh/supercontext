# Repository Guidelines

## Project Context Index

Use `INDEX.md` as the canonical annotated map of project docs, ADRs, debate seeds, evaluation artifacts, and external channels. When project documentation is needed, read `INDEX.md` first and then open only the relevant indexed documents. Do not maintain duplicate doc inventories here; update `INDEX.md` instead.

## Project Structure & Module Organization

This repository is currently a documentation-heavy architecture repo plus a minimal KG prototype.

- `adr/` contains accepted architecture decision records. Keep decisions here once finalized.
- `docs/` contains PRDs, research notes, ontology, graph storage/building, evidence retrieval, and evaluation artifacts.
- `debates/` contains multi-agent debate transcripts and state files.
- `source/` contains the executable KG prototype.
- `source/kg/languages/python/extractors/` and `source/kg/languages/typescript/extractors/` contain language-specific extractors.
- `source/kg/languages/python/normalization/` and `source/kg/languages/typescript/normalization/` contain deterministic normalization logic.
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

## Coverage Metrics & Reports

Use the deterministic coverage pipeline for repo or fleet coverage questions; do not hand-summarize KG coverage from ad hoc file inspection. Codex should use the project-local `.codex/skills/coverage-report` skill when asked to run, summarize, compare, or interpret coverage metrics.

Build or refresh the snapshot first:

```bash
python -m source.scripts.build_kg --repo <repo-path> --out <snapshot-dir>
python -m source.scripts.build_multi_kg --repo <repo-1> --repo <repo-2> --out <snapshot-dir>
```

Then compute metrics and render the standard report:

```bash
python -m source.scripts.coverage_metrics --snapshot <snapshot-dir> --expected-repos <N>
python -m source.scripts.coverage_report \
  --snapshot <snapshot-dir> \
  --out docs/evaluation/runs/<run-id> \
  --run-id <run-id> \
  --tenant <tenant-or-org> \
  --expected-repos <N> \
  --metric-config source/kg/metrics/config.yaml
```

`coverage_metrics` writes `<snapshot-dir>/metrics.jsonl`. `coverage_report` writes `coverage-run.json` and `coverage-run.md` under `docs/evaluation/runs/<run-id>/`. Treat all three as generated artifacts: never hand-edit metric values, reasons, scores, or contract flags. For fleet reports, pass a stable `--run-id`, the tenant/org label, and `--expected-repos` whenever the expected repo count is known.

## Coding Style & Naming Conventions

Prefer small, language-scoped modules over large generic scripts. Keep deterministic extraction and normalization separate. Use descriptive names such as `PythonAstExtractor`, `TypeScriptCompilerApiExtractor`, and `normalize_import`. Python code should follow standard 4-space indentation and type hints where useful. Avoid LLM calls in default extraction paths; if enrichment is added, route it through `source.kg.integrations.llm.LightLlmClient`.

## Testing Guidelines

There is no full test suite yet. For now, verify changes with `compileall`, at least one KG build, and one or more query smoke checks. For behavior changes, add or update a concise note under `docs/evaluation/` with before/after results. Do not claim language support without fixture evidence.

## Commit & Pull Request Guidelines

Use short imperative commit messages, matching the current history, for example `Add deterministic import normalization` or `Add parser-backed TypeScript extraction`. PR descriptions should include summary, scope, verification commands, and evaluation delta when behavior changes. Link relevant ADRs or docs when the PR implements an architectural decision.

## PR Review Loop

Before creating a PR for the first time, after coding is finished, tests pass, and self-review is complete:

- Run `python3 .codex/scripts/request_claude_pre_pr_review.py --base main` yourself.
- The helper must run Claude Code CLI non-interactively, review the current branch against `main`, include any uncommitted working-tree diff, forbid edits, and write the review under `docs/reviews/`.
- When invoking Claude directly with `claude -p`, unset Anthropic API key environment variables in that command so Claude uses the locally authenticated Claude Code session, for example: `env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude -p "<prompt>"`.
- If the helper reports that `claude` is missing or unauthenticated, stop and report that blocker instead of creating the PR.
- The generated review must follow the helper's embedded format: metadata, verdict, summary, what works, real issues, questions or assumptions, pass conditions, and final verdict.
- For each Claude finding, make an explicit decision: `accept`, `deny`, or `act`.
- If accepting/acting, implement the fix with a regression test when behavior changes.
- If denying, document the concrete reason in the PR notes or a reply/comment.
- Only create the PR after accepted/actionable Claude findings are handled.
- Do not run Claude again before the first Copilot review. Each PR gets at most two Claude reviews unless the user explicitly asks otherwise.

After every `git push` to a PR branch, request and verify Copilot review state. Copilot auto-reviews the first PR push, but follow-up pushes usually do not auto-review. Do not just wait after follow-up pushes; explicitly request Copilot review from the CLI.

- Run `python .codex/scripts/poll_copilot_review.py --pr <PR_NUMBER>` after each push. This script requests `@copilot` first, then polls.
- Use `python .codex/scripts/poll_copilot_review.py --pr <PR_NUMBER> --skip-request` only when the user has already manually requested Copilot for the current head and asks you to poll.
- Poll on the default 8-minute schedule: 3 minutes, 2 minutes, then 1 minute, 1 minute, and 1 minute.
- If a current-head Copilot review completes with zero unresolved threads or issue comments, the review step is done.
- If current-head Copilot activity starts but no completed review appears within 8 minutes, stop and report that review activity did not finish in time.
- If no current-head Copilot activity appears within 8 minutes after the CLI request, stop and report that the request produced no review activity.
- Check both top-level Copilot reviews and inline review comments.
- For each Copilot comment, make an explicit decision: `accept`, `deny`, or `act`.
- If accepting/acting, implement the fix with a regression test when behavior changes.
- If denying, reply with concrete evidence for why the feedback is not applicable.
- Reply to each Copilot thread with the decision and either the fix summary or denial rationale, then resolve the thread.
- After implementing changes from the first Copilot review batch, before pushing those changes, run Claude Code exactly one more time with `python3 .codex/scripts/request_claude_pre_pr_review.py --base main`. This is the second and final Claude review for the PR.
- For that second Claude review, decide `accept`, `deny`, or `act` for each finding. Implement accepted/actionable findings with tests when behavior changes, but do not run Claude again unless the user explicitly asks.
- After any code/doc change, run `.codex/skills/pre-pr-semantic-review`, push again, request Copilot again, and repeat this loop until a requested current-head review completes with zero actionable feedback.
- If no actionable Copilot feedback appears after a completed current-head review, state that Copilot reviewed the current head and produced no actionable feedback.

## Agent-Specific Instructions

Keep changes surgical. Do not rewrite ADRs, research docs, or generated data unless the task requires it. When implementation uncovers a product or architecture decision, document the finding instead of silently expanding scope.

Always use the project-local `.codex/skills/product-evaluation` skill before interpreting product-validation results, proposing the next validation-driven feature, or deciding the next highest-value KG/product gap.

## Pre-PR Validation Discipline

Copilot has repeatedly caught boundary-condition mistakes in review. Before opening or updating a PR, explicitly check these patterns:

- Always run the project-local `.codex/skills/pre-pr-semantic-review` checklist before any `git push`, especially for extractor, normalization, query, loader, evaluation, or review-fix changes.
- Extractor and evidence-collection changes must generalize across repositories. Do not hardcode repo names, service names, package names, product-domain terms, path fragments, or fixture variables to make a query pass.
- Prefer parser, AST, compiler, structured config, or source-of-truth schema evidence over keyword or substring heuristics for semantic facts. Keyword matching is only acceptable for genuinely lexical tasks or explicit private fixture configuration.
- Cover new extractor behavior with representative positive and negative fixtures that prove the rule is not tuned to one current repo or goldset case.
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
