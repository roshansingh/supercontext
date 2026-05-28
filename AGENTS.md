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

## Prompt and Tool Wording Discipline

Tool descriptions, MCP instructions, and skill text are routing contracts. Do not phrase them around a goldset question, fixture wording, repo name, service name, or one benchmark scenario. Describe the semantic operation, required anchors, evidence contract, and when to inspect source next.

SuperContext's product position is to give the agent the best head start possible, not to return everything or replace source inspection. If a packet must omit detail for budget reasons, keep the highest-signal evidence rows and add explicit inspection leads for omitted important rows with file/path/location hints where available; count-only omissions are not useful.

When fixing an eval miss, ask whether the wording and implementation would still make sense for unrelated OSS repositories and adjacent questions. Ask Claude Code specifically whether the change is overfit or makes the general OSS product stronger before finalizing.

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

## MCP Head-Start Product Positioning

SuperContext MCP tools should give the agent the best possible head start. When the relevant packet fits comfortably inside the output budget, return the complete relevant evidence. When the full packet would exceed size or section limits, bound it without erasing the agent's inspection path.

- Prefer complete relevant sections for small packets and compact, prioritized lead sections for large packets. A good bounded packet surfaces the highest-value review/planning leads first, with evidence coordinates and why each lead matters.
- Count-only omissions are not a head start. If limits prune rows, do not merely say "N rows omitted." Provide a compact inspection index for omitted rows whenever possible. If no rows were pruned, do not invent omitted sections.
- Use a two-tier bounded packet shape only when full detail does not fit: detailed leads for the most important rows, plus compact inspection references for the rest. Detailed leads should include the relevant fact/evidence summary; compact references should still include enough coordinates for the agent to inspect without rediscovering the row from scratch.
- After compaction, spend remaining output budget deliberately. If the full packet is over budget and the compact packet lands under budget, backfill the highest-value omitted rows or details until the packet is near the budget ceiling without crossing it. Do not stop at an unnecessarily tiny compact packet when safe headroom remains.
- Every omitted inspection reference should preserve the strongest available coordinates: `repo`, `path`, `line`, `symbol`/`qualname`, `endpoint`/`domain`/`event_channel` when applicable, category/status, and a short reason it matters. Evidence blobs may be capped; coordinates and inspection targets should survive.
- If even the compact omitted index must be truncated, expose an explicit continuation/narrowing contract such as omitted count by category plus the exact narrower anchor to call next. Never let truncation silently erase a category.
- Separate `known_linked`, `candidate_or_unlinked`, and `missing_or_unknown` evidence. Do not let compact packets imply absence just because a row was omitted by a limit.
- For review/security/runtime questions, include investigation leads and inspection areas together: proven KG facts, high-signal source leads, and the specific dynamic/framework/config areas the KG cannot prove.
- When one row has multiple important classifications, preserve the classifications instead of allowing one lead type to suppress another. For example, an explicitly public endpoint with an in-method signature/API-key guard should remain visible as both public surface and guarded surface.
- Raise limits only when the packet genuinely needs more rows. The default fix for oversized packets should be better prioritization and clearer follow-up guidance; the default for small packets is to return the relevant evidence directly.
- Evaluate MCP improvements by whether they improve final answer quality and reduce unnecessary agent investigation. If MCP gives a partial head start, the expected behavior is targeted source inspection, not stopping at the packet.

## Anti-Overfitting Discipline

When fixing an evaluated question or a previous MCP-off win, treat that question as evidence of a product gap, not as the objective itself. The objective is to make SuperContext stronger as a generic OSS tool.

- Before coding, re-read the current `AGENTS.md` on the active branch and verify these MCP head-start and A/B regression instructions are present. If they are stale, update them before implementing feature work.
- Prefer generic parser/AST/compiler/config/source-of-truth semantics over fixture-specific matching. Do not add repo names, service names, endpoint names, function names, product-domain terms, or fixture-specific ranking just to move one question.
- For packet design, return all relevant rows when they fit. When size or section limits require pruning, capture the most important generic facts as prioritized leads, backfill omitted detail with any remaining budget, and put the rest into explicit inspection areas with coordinates. A count without omitted-row coordinates is not an acceptable inspection area for pruned rows. Do not churn limits, row ordering, or packet fields only to make one answer look better.
- When fixing a loss caused by budget/packet truncation, first ask whether the omitted evidence had a compact inspection index. If not, fix the packet contract before increasing budgets or adding more prose.
- If a proposed change only helps the target question and does not plausibly help similar repositories or workflows, stop and either narrow it to private fixture configuration or reject it.
- Before running validation for an eval-driven fix, ask Claude Code specifically: "Are these changes overfitting to the target question, or do they make the overall OSS product stronger?" Include the target question, changed files, and the generic rule being added.
- Treat Claude Code's answer as a hypothesis to verify against code. For each concern, decide `accept`, `deny`, or `act` with evidence before running focused or previous-loss-set evals.
- Do not proceed to merge or claim an improvement while unresolved overfitting concerns remain.

## A/B Evaluation Regression Discipline

For iterative MCP quality work, use tiered validation. Do not treat a single-question MCP-on win as sufficient evidence, but also do not rerun the full 18-question suite after every edit.

- During development, run the target question only, usually MCP-on only or MCP-on against a reused compatible MCP-off record, to check whether the local change works.
- After the target question wins, rerun MCP-on for the full current MCP-off loss set from the latest relevant full report, reusing compatible MCP-off records with `run_ab_eval --reuse-mcp-off-from <run-dir>`, then regenerate deltas/judgement/report.
- Before merge or before claiming a direction-level improvement, run the full 18-question A/B, or full 18 with reused MCP-off records if the harness, prompts, fixtures, and task text are unchanged and only MCP/KG behavior changed.
- Recompute MCP-off only for fresh merge-gating runs, new baselines, harness changes that invalidate cached records, or when the task prompt/fixture changed.
- Report the previous-loss-set outcome after focused wins, not only the target question. If a target win creates or preserves other MCP-off wins, classify those regressions before further coding.
- Use `gpt-5.4-mini` for A/B judge passes unless the user explicitly changes the judge model. This is a local evaluation alias supplied to the A/B judge runner in this workspace, not a public OpenAI model SKU or checked-in portability contract; do not auto-substitute another model. If the judge provider rejects it, stop and ask. Raw answer inspection is acceptable for diagnosis but not for claiming an eval win.

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
