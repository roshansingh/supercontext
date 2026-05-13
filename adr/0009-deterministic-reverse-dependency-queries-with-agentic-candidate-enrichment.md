# ADR-0009: Use Deterministic Reverse Dependency Queries with Agentic Candidate Enrichment

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

The first KG implementation slice can already answer outgoing call expansion, for example:

`predict_on_session -> get_data, impute_data, build_features, compute_prediction, write_result`

That is useful, but Product 1's main value is mostly reverse impact:

- a PR changes a function; what callers may break?
- a module moves; who imports it?
- a core prediction/helper function changes; which flows depend on it?
- a package abstraction changes; which modules are affected?

Reverse queries flip dependency direction:

- `who-calls(symbol)` answers direct callers of a function/method/class constructor
- `who-imports(module_or_package)` answers modules importing an internal module or external package
- `impact-of-symbol(symbol)` expands reverse dependencies from a changed symbol

These queries are the bridge from "we built a KG" to "the PR bot can explain blast radius."

## Decision

**Implement reverse dependency queries as deterministic graph traversals in v1. Use Agent SDK only as later v2 candidate enrichment for dynamic, framework-driven, or conceptual impact.**

The v1 query flow is:

1. Resolve the target symbol via ADR-0007.
2. Normalize the target import/module/package via ADR-0008 when the query is import-related.
3. Traverse reverse `CALLS` or `IMPORTS` edges.
4. Return direct evidence for each edge.
5. If the target is ambiguous, return candidates; do not guess.
6. If graph coverage is missing, stale, or uninstrumented, return explicit refusal/warning metadata.

## V1 Query Semantics

| Query | Input | Deterministic behavior |
|---|---|---|
| `who-calls(symbol)` | resolved symbol ID or symbol query | Find `CALLS` facts where `object_id = target_symbol_id`. |
| `who-imports(module)` | normalized internal module target | Find `IMPORTS` facts where `object_id = target_module_id`. |
| `who-imports(package)` | normalized third-party package target | Find `IMPORTS` facts whose normalized package root / distribution matches target. |
| `impact-of-symbol(symbol)` | resolved changed symbol | Reverse-expand `CALLS` up to bounded depth, returning direct and transitive callers with evidence. |
| `impact-of-module(module)` | normalized module target | Reverse-expand `IMPORTS`, then optionally map importer modules to containing symbols. |

All outputs must include source evidence compatible with ADR-0005 Mode A:

`repo + commit_sha + path + line_start + line_end`

## Examples

### `who-calls("load_model")`

If symbol lookup finds multiple `load_model` methods, return ambiguity first:

```json
{
  "status": "ambiguous",
  "query": "load_model",
  "candidates": [
    "HumanHandoverAgentDspy.load_model",
    "FrustrationPredictor.load_model"
  ],
  "message": "Multiple symbols match load_model. Choose one or set include_all=true."
}
```

If resolved or `include_all=true`, deterministic output can include:

| Caller | Callee | Evidence |
|---|---|---|
| `HumanHandoverAgentDspy.__init__` | `HumanHandoverAgentDspy.load_model` | `handover_dspy_agent.py:33` |
| `FrustrationPredictor.__init__` | `FrustrationPredictor.load_model` | `prediction.py:26` |

### `who-imports("mercury_ml.chatbot.apis.openai_instructor")`

After ADR-0008 import normalization, return modules importing that internal module, with line evidence.

This answers: "if we change this internal OpenAI abstraction, which agents depend on it?"

### `impact-of-symbol("build_features")`

V1 deterministic output should include direct and bounded transitive callers from the reverse `CALLS` graph.

Agentic conceptual output is not part of v1. A later v2 may add candidate commentary such as "intent prediction batch pipeline may be affected" only if grounded in evidence.

## Deterministic V1 Algorithm

For `who-calls`:

1. Resolve target using ADR-0007.
2. If ambiguous and `include_all=false`, return ambiguity response.
3. For each resolved target, scan/query `CALLS` facts where `object_id = target`.
4. Join caller/callee entities and evidence rows.
5. Return sorted callers with evidence and optional depth.

For `who-imports`:

1. Normalize target using ADR-0008.
2. If target is ambiguous or unknown, return ambiguity/unknown response.
3. Query `IMPORTS` facts matching normalized internal module or package root/distribution.
4. Join importer modules and evidence rows.
5. Return sorted importers with category metadata.

For `impact-of-symbol`:

1. Resolve target using ADR-0007.
2. Traverse reverse `CALLS` edges up to bounded `depth`.
3. Deduplicate by symbol/module.
4. Preserve path information: `target <- caller <- transitive_caller`.
5. Return evidence for every traversed edge.
6. Stop traversal when coverage is uninstrumented/stale and report refusal/warning metadata.

## Query Contract Requirements

The exact MCP schema remains owned by the Tool Query Contract ADR, but the semantics are binding:

- no silent guessing on ambiguous targets
- every returned impact edge carries evidence
- safety-critical query paths default to deterministic facts only
- `include_all=true` must be explicit when querying ambiguous names
- `depth` must be bounded
- outputs must distinguish direct vs transitive impact
- outputs must distinguish deterministic facts from candidate/agentic enrichment
- missing or stale coverage must be visible to the caller

## Agent SDK Candidate Enrichment

Agent SDK is not part of v1 primary reverse dependency computation.

Allowed future candidate cases:

- dynamic calls that static extraction cannot resolve
- framework magic such as decorators, routes, CLIs, scheduled jobs, plugin registries, or config-driven entrypoints
- conceptual targets such as "the prediction flow"
- partial or stale index coverage
- ranking or explanation of which deterministic impacts are likely most important
- test suggestion based on impacted code

Agent SDK fallback requirements:

- run only after deterministic reverse traversal has completed or refused
- use read-only tools and explicit budgets per ADR-0001 and ADR-0005
- cite file/line evidence for every candidate impact
- mark outputs as candidate / inferred
- never hide deterministic coverage gaps
- never promote candidate impacts into canonical answers without deterministic corroboration

## V2 Agentic Expansion Criteria

A later v2 may use Agent SDK more actively only if measured evidence shows it improves reverse impact quality.

Evidence required:

- measured recall improvement on dynamic/framework/conceptual impact fixtures
- no measurable increase in false impact edges
- p95 latency and token cost within query budget
- every agent-proposed impact cites concrete files/lines
- deterministic corroboration or explicit candidate labeling before safety-critical use

Until then, the binding v1 posture is deterministic reverse traversal first, Agent SDK candidate enrichment later.

## V1 Scope

Initial scope:

- `who-calls`
- `who-imports`
- `impact-of-symbol`
- direct and bounded transitive reverse `CALLS`
- reverse `IMPORTS` over normalized import facts
- ambiguity handling through ADR-0007
- import target resolution through ADR-0008
- compact human-readable output mode for CLI/local testing

Explicitly out of v1:

- framework-specific dynamic call inference as canonical fact
- runtime trace integration
- test selection as a committed product behavior
- ownership/team impact expansion
- cross-repo impact beyond available indexed facts
- Agent SDK as the default impact engine
- promoting Agent SDK candidate impacts without deterministic corroboration

## Implementation Status (v0, 2026-05-08)

This ADR is partially implemented in the local KG harness.

What exists now:

- `find-callers` performs direct reverse `CALLS` lookup after ADR-0007 symbol resolution.
- `who-imports` performs reverse `IMPORTS` lookup for normalized internal modules and external packages.
- `top-fan-in-symbols` ranks symbols by direct caller count.
- `top-internal-dependencies` ranks internal modules by importer count.
- `modules-importing-both` finds modules that import two normalized targets.
- `dependency-path` finds bounded mixed paths across `CALLS`, `DEFINED_IN`, and `IMPORTS` facts.
- Outputs include evidence samples from indexed source coordinates.

What is still pending:

- Generalized reverse transitive `impact-of-symbol` traversal.
- Product-grade `impact-of-module` that maps importers back to owning symbols/services.
- Break-first ranking for changed symbols or changed packages.
- Runtime trace integration and framework-specific dynamic call inference.
- Agent SDK candidate enrichment.
- MCP/PR-bot schemas and refusal semantics.

Evaluation evidence is summarized in `docs/evaluation/CANONICAL-VALIDATION-REPORT.md`.

## Relationship to Existing ADRs

### ADR-0005

Reverse queries are graph/evidence queries. Every surfaced edge must be groundable through ADR-0005 Mode A coordinate fetch.

Agent SDK enrichment, when used later, is ADR-0005 Mode B and remains candidate unless deterministically corroborated.

### ADR-0006

This ADR does not alter the Product 1 canonical ontology. Reverse call/import queries operate over implementation-side KG facts needed for source-level query resolution and PR-bot impact analysis.

Canonical product answers must still respect ADR-0006 and the Tool Query Contract.

### ADR-0007

Reverse call queries depend on deterministic symbol lookup. Ambiguous symbol names must return candidate choices or require `include_all=true`.

### ADR-0008

Reverse import queries depend on deterministic import normalization so that stdlib, third-party packages, internal modules, and unknowns are not mixed together.

## Consequences

### Positive

- Directly supports PR-bot blast-radius behavior.
- Enables refactoring and impact questions with evidence.
- Keeps v1 cheap, deterministic, and testable.
- Reuses existing `CALLS` and `IMPORTS` facts instead of adding a new inference system.
- Provides a clear place for later agentic candidate enrichment without weakening trust.

### Negative

- V1 recall is limited by extractor coverage.
- Static Python call resolution will miss dynamic dispatch and framework entrypoints.
- Good `impact-of-symbol` output depends on ADR-0007 symbol lookup quality and ADR-0008 import normalization quality.

### Neutral

- This ADR does not require Postgres / AGE before local testing.
- This ADR does not define final MCP schemas.
- This ADR does not commit to runtime trace ingestion for impact expansion.

## References

- `docs/evaluation/CANONICAL-VALIDATION-REPORT.md`
- ADR-0001: `adr/0001-claude-agent-sdk-for-internal-runtime.md`
- ADR-0005: `adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`
- ADR-0006: `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- ADR-0007: `adr/0007-deterministic-symbol-lookup-with-agentic-disambiguation.md`
- ADR-0008: `adr/0008-deterministic-import-normalization-with-agentic-candidate-fallback.md`
