---
name: pre-pr-semantic-review
description: Run before pushing PR updates in this repository, especially after changing extractors, normalization, query/evaluation logic, loaders, or GitHub review fixes. Focuses on Copilot-style semantic bugs: Python/AST binding semantics, fail-closed behavior, source-order resolution, multiplicity, validation, and regression tests.
---

# Pre-PR Semantic Review

Use this skill before pushing PR changes in this repository.

## Required Workflow

1. Inspect the diff and list changed behavior.

```bash
git diff --stat
git diff --check
```

2. Review changed code against the checklist below. For every applicable item, either add a regression test or state why it is not applicable.

3. Run focused tests for touched modules, then the full test suite.

```bash
python -m compileall -q source
python -m unittest discover tests
```

4. Before pushing, verify unrelated files are not staged or included.

```bash
git status --short --branch
```

## Extractor And AST Checklist

- Do not use whole-function facts when call-site-scoped facts are required. Resolution maps for locals, clients, resources, aliases, or wrappers must only use bindings visible at that call site unless Python semantics require fail-closed handling.
- If a name is locally bound but not statically resolvable, do not fall back to a same-named module/global constant. Emit unresolved coverage or skip promotion.
- Match Python call semantics before wrapper promotion: positional-only, keyword-only, missing required args, duplicate bindings, `*args`, and `**kwargs` must fail closed when ambiguous.
- Account for local shadowing by params, assignment, annotated/aug assignment, imports, loops, `with`, `except`, walrus, nested defs/classes, lambdas, and `match/case` captures.
- Keep nested-scope traversal policies aligned across collectors. If call collection visits evaluated decorators/defaults/class bases, binding collection must treat the same expressions consistently.
- Do not traverse nested function/class/lambda bodies as if they execute in the outer body. Do visit evaluated expressions: decorators, defaults, kw-defaults, class bases, and class keyword values.
- Fail closed on ambiguous multiplicity. If one input maps to multiple candidate facts and the output contract is not list-shaped, emit no promoted fact.
- Avoid repeated full-body scans inside per-call loops. Cache binding/name/alias analysis per function when used for many calls.

## Validation Checklist

- Validate external JSON/input shapes before `.get`, iteration, or rendering.
- Reject malformed rows, duplicate IDs, padded IDs, non-list list fields, and non-string list members with field-specific errors.
- Treat sentinel values as contracts; pass/fail fields must be mutually consistent.
- Keep allowlists as the single source of truth for supported languages, transports, methods, statuses, and derivation classes.
- Resolve executable/SDK dependencies early with actionable errors.

## Regression Test Rule

Every semantic fix must add a negative test that would have failed before the fix and a positive test when the safe path should still work.
