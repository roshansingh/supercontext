---
name: pre-pr-semantic-review
description: "Run before pushing PR updates in this repository, especially after changing extractors, normalization, query/evaluation logic, metrics, loaders, relink/snapshot code, endpoint/path reconciliation, config/YAML contracts, manifest producers/consumers, output-contract/packet-shape/budget code, or GitHub review fixes. Focuses on Copilot-style semantic bugs (Python/AST binding semantics, fail-closed behavior, source-order resolution, multiplicity, validation, path/filter semantics, metric scope correctness, trust-boundary drift) AND change-completeness failures (a new rule applied to only some sites, an inconsistent serialization/measurement unit, partial enum coverage, built-but-unwired code, docs drifting from changed behavior), plus regression tests."
---

# Pre-PR Semantic Review

Use this skill before pushing PR changes in this repository.

## Required Workflow

1. Inspect the diff and list changed behavior.

```bash
git diff --stat
git diff --check
```

2. Review changed code against the checklist below. For every applicable item, either add a regression test or state why it is not applicable. If touching metrics, manifests, config, YAML, evidence scoping, or evaluation output, always run the Metrics, Config, And Data-Contract Checklist. If touching snapshot loaders, relink, package manifests, JSONL stores, or multi-repo linking, always run the Snapshot/Relink Checklist.

3. Run focused tests for touched modules, then the full test suite.

```bash
python -m compileall -q source
python -m unittest discover tests
```

4. Before pushing, verify unrelated files are not staged or included.

```bash
git status --short --branch
```

5. Stop-the-line rule: if a reviewer raises **2 or more findings of the same family** (or 3+ across families) on one PR, do not keep patching individual comments — that is the signature of a change-completeness miss and it will not stop one comment at a time. Pause, name the family, then **enumerate every site/value/doc the family touches across the whole codebase (grep), fix them all in one change, and add a coverage test that fails if a new instance is missed** before the next push. Patching N comments one-by-one across N review rounds means this rule was skipped.

## Change-Completeness And Consistency Checklist

Run this FIRST whenever the change introduces or modifies an output-contract field, a rule
applied across many call sites, a serialization/measurement unit, a classification map or
enum, a packet/budget shape, or any guidance describing them. This is the failure family that
produces long one-comment-at-a-time review threads (each fix correct but narrow).

- Enumerate every site, apply uniformly. When you add a rule ("record this in
  `truncated_sections`", "sync `*_returned_count`", "classify in `_CANDIDATE_LEAD_KIND`",
  "signal-rank this section", "bound this list"), grep for EVERY place the rule applies and
  apply it in the same change — not only the sites you happened to touch. If you fixed 3 sites,
  search for 5; if 5, look for 8. Recipe: `grep -n '\[:limit\]\|\[:COMPACT\|_compact_'` (or the
  relevant slice/compactor) and confirm each obeys the new rule.
- Cover the full input domain. A tier/priority/classification map must include every value the
  codebase actually emits, not a subset — unknown values silently take the default/lowest rank.
  Grep the literal set (e.g. `grep -rhoE '"(authoritative_declared|deterministic_static|...)"'`),
  map them all, and add a test asserting every registered field/enum value is mapped explicitly
  (not via the generic fallback).
- Keep one unit/contract consistent across the whole path: produced -> measured -> emitted on
  the wire -> consumed -> asserted in tests. A budget that measures `canonical_json` must be the
  exact serialization the server emits and the tests assert. Grep the unit (`canonical_json`,
  `json.dumps`, `indent=`) across producer/server/tests and reconcile before pushing.
- Wire what you build; delete what you don't. Every new helper, parameter, or signal must be
  used on its intended path (e.g. actually pass the anchor you added `match_rank` for). No dead
  public API. Recipe: `grep -rn "<new_symbol>" source/ | grep -v "def <new_symbol>"` and confirm
  a real (non-test) caller; if none, wire it or remove it.
- Update docs/comments/guidance in lockstep with behavior. When an output contract or behavior
  changes, grep the OLD term/shape across docstrings, advice strings, tool descriptions, SKILL
  templates, and server instructions, and update every occurrence (e.g. "omitted counts" ->
  "truncated_sections", "guarantees it fits" -> note the exceeded edge case). Stale guidance that
  names fields the tool no longer emits is review bait.
- Mirror parallel code paths. If two functions compute the "same" thing (e.g. `fact_count` vs
  evidence scoping, or fleet vs anchored budgeting), a rule added to one almost always belongs in
  the other. Diff the pair and reconcile.

## Extractor And AST Checklist

- Gate language-specific legacy extractors by file type before scanning lines. A JS/TS regex extractor must not run on Python, YAML, JSON, Markdown, or config files.
- Parser-backed extractors must not be followed by broad legacy regex extraction over the same file type unless the legacy facts are explicitly isolated and tested for no duplicate/conflicting facts.
- Do not use whole-function facts when call-site-scoped facts are required. Resolution maps for locals, clients, resources, aliases, or wrappers must only use bindings visible at that call site unless Python semantics require fail-closed handling.
- If a name is locally bound but not statically resolvable, do not fall back to a same-named module/global constant. Emit unresolved coverage or skip promotion.
- Match Python call semantics before wrapper promotion: positional-only, keyword-only, missing required args, duplicate bindings, `*args`, and `**kwargs` must fail closed when ambiguous.
- Account for local shadowing by params, assignment, annotated/aug assignment, imports, loops, `with`, `except`, walrus, nested defs/classes, lambdas, and `match/case` captures. Also account for `global`/`nonlocal` symbol-table effects.
- Keep nested-scope traversal policies aligned across collectors. If call collection visits evaluated decorators/defaults/class bases, binding collection must treat the same expressions consistently.
- Do not traverse nested function/class/lambda bodies as if they execute in the outer body. Do visit evaluated expressions: decorators, defaults, kw-defaults, class bases, and class keyword values.
- Fail closed on ambiguous multiplicity. If one input maps to multiple candidate facts and the output contract is not list-shaped, emit no promoted fact.
- Avoid repeated full-body scans inside per-call loops. Cache binding/name/alias analysis per function when used for many calls, and stop ordered prefix scans with `break` once the target call site is reached.

## Validation Checklist

- Validate external JSON/input shapes before `.get`, iteration, or rendering.
- Validate file path shape before reading: a required file must exist and be a regular file, not a directory or special path.
- Reject Python `bool` anywhere JSON/YAML expects an `int` or `float`; `bool` is a subclass of `int`.
- Validate enum-like runtime values explicitly. `Literal[...]` type hints are not runtime validation.
- Validate numeric ratios, weights, confidences, and scores stay within their allowed range, usually `[0, 1]`.
- Validate config documents by structural schema markers, not by broad content keywords. For OpenAPI, require a `paths` object plus an `openapi` or `swagger` version marker before emitting endpoint documentation facts.
- Reject malformed rows, duplicate IDs, padded IDs, non-list list fields, and non-string list members with field-specific errors.
- Treat sentinel values as contracts; pass/fail fields must be mutually consistent.
- Keep allowlists as the single source of truth for supported languages, transports, methods, statuses, and derivation classes.
- Resolve executable/SDK dependencies early with actionable errors.

## Snapshot, Relink, And Loader Checklist

Use this checklist for any change that reads existing snapshots, writes JSONL artifacts, relinks packages, merges multi-repo data, or trusts manifest metadata.

- Identify every trust boundary before coding: persisted snapshot files, live repo files, environment variables, git state, generated fleet artifacts, and CLI arguments.
- Validate snapshot artifact paths before reading: `manifest.json`, `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, `metrics.jsonl`, and relink artifacts must be regular files when present.
- Fail fast on malformed JSONL rows: non-object rows, missing IDs, duplicate IDs, padded IDs, recomputed ID mismatches, unsupported enum values, and non-string tenant or category fields.
- Check producer/consumer drift for every manifest field. If a loader consumes a field, prove the producer writes it, legacy absence is handled intentionally, and malformed presence fails loudly.
- Do not let ambient environment reinterpret persisted snapshots. Tests and loaders must not let `SUPERCONTEXT_TENANT_ID` or similar env vars change the tenant of already-written entity IDs.
- Validate live repo state when old snapshots depend on live files. For package manifests, check commit identity, dirty files, deleted files, ignored files, restored dirty content, missing git, and non-git repos.
- If old snapshots must read live package manifests, persist and compare content fingerprints where commit/dirty checks are insufficient.
- Keep relink outputs transactional. Write to staging/temp files, validate duplicate output IDs before publish, reject non-file stale artifacts, and roll back or preserve old outputs on failure.
- Reject output directories that alias input snapshot directories before creating or writing files.
- For fleet discovery, distinguish repo snapshots from generated artifacts using explicit manifest shape, not broad file existence.
- Add negative fixtures for directory-as-file, malformed manifest shape, duplicate rows, tenant mismatch, moved commit, dirty/deleted/restored package manifest, stale output cleanup failure, and output/input aliasing when those paths are touched.

## Graph Linker Semantics Checklist

Use this checklist for package linking, cross-repo facts, identity normalization, canonicalization, or relation promotion.

- Treat tenant, repo owner, repo name, host, and commit as part of identity. Repo name alone is not enough in multi-repo or fleet contexts.
- Fail closed on ambiguous collapsed subjects. If one entity ID can represent multiple consumer identities or provider choices and downstream graph traversal is qualifier-insensitive, emit no promoted fact unless every consumer resolves to the same target.
- Filter builtin/stdlib/runtime-provided imports before package-to-repo matching.
- Do not invent aliases by string convenience. Scoped npm packages such as `@scope/name` must not match plain `name` unless a separate explicit alias proves that relationship.
- Check self-link filtering per consumer/provider identity, not against a global collapsed set.
- For every new relation, trace definition, construction, serialization, query consumption, metric consumption, and tests. Do not assume qualifiers will be honored unless the consumer is verified.

## Metrics, Config, And Data-Contract Checklist

- Keep numerator, denominator, and evidence scope identical for each metric cell. If the denominator is scoped by dimension/repo/path, the numerator must use the same scoped rows, not whole-snapshot rows.
- Do not return a usable zero before validating the denominator. Missing or malformed denominators should produce `n_a`, not a valid score.
- Distinguish physical file counts from compatibility aliases. Compatibility aliases may help match old evidence, but must not inflate classified-file or coverage numerators.
- For multi-repo snapshots, qualify evidence and file scopes by full repo identity when available. Repo name alone is unsafe; same-name repos and `working-tree` commits can collide.
- Preserve legacy single-repo compatibility only when the legacy key is unambiguous. If `repo_name + commit_sha` is duplicated, fail closed or require full identity.
- Validate producer/consumer manifest contracts end to end. If a metric requires `manifest.counts.files_by_language`, verify every snapshot producer writes it or the consumer derives it safely.
- When adding a manifest/config field, trace definition, construction, serialization, loading, consumption, and test coverage.
- Deep-copy cached YAML/config structures before returning them from public wrapper methods, or make them immutable. Shallow copies can let callers mutate cached nested lists/dicts.
- Make YAML shape tests validate the shape consumed by implementation, including nested object fields such as `predicate` and `subject_kinds`.
- Check module docstrings are the first statement in the module, before `from __future__` imports, when the string is intended for generated docs.
- For every metric/config hardening change, add a negative fixture for the malformed shape and a positive fixture proving the valid shape still works.

## Documentation Contract Checklist

Use this checklist when editing docs in the same PR as code, especially architecture/evaluation docs that contain commands, file paths, manifest fields, or implementation claims.

- Treat docs as executable contracts. Every command shown must match the actual CLI flags and required inputs.
- Verify every referenced file, symbol, manifest field, output artifact, and module owner against the current tree.
- Avoid exact line-number anchors in docs unless they are required and refreshed in the same diff.
- If code changes from proposed to implemented, update every stale "proposed", "not implemented", "future", and backlog row in touched docs.
- If docs describe a consumer flow, verify the consumer actually reads the producer output. If not, mark it blocked or show the current workaround.
- Keep examples from corrupting real artifact layouts: do not write combined snapshots into `_fleet` if `_fleet` is a relink-only artifact directory.

## Test Hermeticity Checklist

- Any test that expects tenant `default` must pass `tenant_id="default"` or derive the value from the produced manifest.
- Tests must not depend on the caller's git config, signing config, current branch, global env vars, or installed optional CLIs unless the test is explicitly about that dependency.
- Use temporary repos with explicit git user config and `commit.gpgsign=false` when commits are required.
- Add negative tests for environment drift when code reads env vars as defaults.

## Path And Scope Semantics

- Do not overload `path` in structured records. Use explicit keys such as `file_path`, `endpoint_path`, `module_path`, or `path_prefix` so filters cannot confuse source-file paths with product/runtime paths.
- Apply endpoint `path_prefix` filters only to endpoint identities or explicitly named `endpoint_path` fields. Do not apply endpoint prefixes to coverage rows whose paths are source files.
- Preserve caller-provided prefix semantics. If another helper uses raw `startswith(path_prefix)`, do not normalize away trailing slashes in an adjacent warning/status path and accidentally make `/v1/` match `/v1beta/...`.
- When a query/reconciliation method has filters, apply the same filters consistently to status, warning suppression, and result rows. Add a negative test where data exists outside the requested filter and must not suppress warnings inside the filter.

## Regression Test Rule

Every semantic fix must add a negative test that would have failed before the fix and a positive test when the safe path should still work.
