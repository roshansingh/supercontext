# ADR-0007: Use Deterministic Symbol Lookup with Agentic Disambiguation Fallback

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Maruti Agarwal
- **Supersedes:** —
- **Superseded by:** —

---

## Context

The first KG implementation slice in `source/` builds a local code-symbol graph from `/Users/maruti/work/mercury_ml` and records the smoke-test results in `source/KG-QUERY-SMOKE-TESTS.md`.

That test showed useful evidence-backed answers for imports, local callers, and outgoing call expansion, but it also exposed a required query-resolution layer:

- names such as `predict`, `load_model`, or `FeatureBuilder` can match many symbols
- substring lookup is too noisy for product behavior
- PR-bot and safety-critical tools cannot guess which symbol a user meant
- evidence retrieval needs exact coordinates: `repo + commit_sha + path + line_start + line_end`
- Agent SDK search is strong for conceptual discovery, but too variable and expensive to be the primary resolver

Symbol lookup is the layer that maps a user/tool input such as a name, qualified name, file/line coordinate, or changed PR span to an exact code entity or a structured ambiguity response.

## Decision

**Use deterministic symbol lookup as the primary resolver. Use the Claude Agent SDK Explorer only as a bounded fallback for ambiguous, missing, or conceptual queries.**

The v1 resolver order is:

1. Coordinate lookup: `repo + commit_sha + path + line`
2. Fully-qualified symbol lookup
3. Exact symbol-name lookup
4. Ranked fuzzy / substring lookup
5. Bounded Agent SDK Explorer fallback when deterministic lookup is ambiguous, missing, or the query is conceptual

Agentic fallback must not silently promote a guessed symbol to an accepted fact. It may return candidate symbols with evidence and confidence, or ask for clarification through the tool contract.

## Required Resolver Outcomes

| Case | Required behavior |
|---|---|
| Exact unique match | Resolve automatically and return the resolved symbol ID plus evidence coordinates. |
| Exact multiple matches | Return structured ambiguity with ranked candidates; do not guess for safety-critical tools. |
| Fuzzy / substring unique-ish match | Resolve only with `resolved_from` metadata and confidence label. |
| Fuzzy / substring multiple matches | Return ranked candidates and require clarification unless `include_all=true` is explicitly allowed. |
| No deterministic match | Return `not_found` with nearby suggestions, then optionally run bounded Agent SDK Explorer if the query class permits. |
| PR-bot changed file/line | Resolve from coordinates, not from names. If coordinates cannot resolve, return explicit coverage/refusal metadata. |

## Query Contract Shape

Symbol-resolution responses must be structured. The exact MCP schema will be finalized in the Tool Query Contract ADR, but the semantics are binding:

```json
{
  "status": "resolved | ambiguous | not_found | uninstrumented",
  "query": "load_model",
  "resolved_symbol": null,
  "confidence": "exact_unique | exact_multiple | fuzzy_unique | fuzzy_multiple | agent_candidate",
  "candidates": [
    {
      "symbol_id": "sym_...",
      "display_name": "FrustrationPredictor.load_model",
      "qualified_name": "mercury_ml.chatbot.frustration_classification.prediction.FrustrationPredictor.load_model",
      "repo": "mercury_ml",
      "path": "mercury_ml/chatbot/frustration_classification/prediction.py",
      "line_start": 28,
      "line_end": 31,
      "evidence": {
        "commit_sha": "c83cacf...",
        "derivation_class": "deterministic_static"
      }
    }
  ],
  "message": "Multiple symbols match load_model. Choose one or set include_all=true."
}
```

## Agent SDK Fallback Rules

Agent SDK Explorer is allowed only after deterministic lookup has failed to produce a safe answer, or when the query is conceptual from the start.

Allowed fallback cases:

- same name exists in many classes/modules and surrounding context is needed to rank likely targets
- the user asks for a conceptual target such as "the prediction flow"
- static extraction coverage is partial or stale
- dynamic language behavior makes deterministic resolution incomplete
- lexical / structural evidence exists, but no deterministic symbol has been indexed

Agent fallback requirements:

- use a narrow read-only tool allowlist, consistent with ADR-0001 and ADR-0005
- run under explicit budget limits
- return candidate symbols with file/line evidence
- mark outputs as `agent_candidate` / `inferred_llm` until deterministic evidence confirms them
- never bypass refusal-on-uninstrumented for safety-critical tools

## V1 Implementation Scope

V1 symbol lookup requires a deterministic symbol index for the languages supported by the first implementation slice.

Initial scope:

- Python symbol extraction from AST for the local KG harness
- symbol identity: `(tenant_id, repo, module, qualname, symbol_kind)`
- source coordinates for every indexed symbol
- lookup by coordinate, fully-qualified name, exact name, and ranked substring
- ambiguity responses instead of silent guesses

Near-term next scope:

- reverse call lookup: "who calls this symbol?"
- reverse import lookup: "who imports this module/package?"
- exact symbol lookup in the CLI / query script
- compact human-readable output mode
- import normalization into external package root, internal module, and relative import

Explicitly out of v1:

- broad cross-language code intelligence
- SCIP / language-server-grade symbol graph
- whole-program Python type inference
- agent-only symbol resolution as the default
- promoting Agent SDK guesses to canonical facts without deterministic corroboration

## V2 Agentic Expansion Criteria

The v1 resolver is deterministic-first. A later v2 may expand Agent SDK involvement only if implementation evidence shows that it improves resolution quality without weakening trust, cost, or latency.

Evidence required before expanding Agent SDK usage:

- measured precision / recall improvement on ambiguous or missing-symbol fixtures
- p95 latency and token cost within the Tool Query Contract budget
- no increase in wrong-symbol resolutions for safety-critical queries
- every agent-proposed symbol carries file/line evidence
- deterministic corroboration path exists before candidate symbols influence canonical product answers

Until those conditions are met, Agent SDK remains a fallback/disambiguation layer, not the primary symbol resolver.

## Relationship to Existing ADRs

### ADR-0001

This ADR uses the Claude Agent SDK Explorer as the fallback/disambiguation runtime for symbol lookup, but keeps production usage narrow, read-only, permissioned, and budgeted.

### ADR-0005

Symbol lookup is part of the query/evidence retrieval path:

- deterministic symbol index lookup is the primary resolver
- Agent SDK fallback is ADR-0005 Mode B, not the primary path
- any surfaced code claim must still be groundable by ADR-0005 Mode A coordinate fetch

### ADR-0006

ADR-0006 keeps code symbols out of the Product 1 canonical service ontology. This ADR does not reopen that decision.

Symbols are implementation-side evidence/query-resolution artifacts. They may be stored in the same Entity + Fact + Evidence substrate for the KG module, but product canonical answers must still project through the accepted v1 ontology and tool contracts.

## Consequences

### Positive

- Faster, cheaper, and more repeatable than agent-first lookup.
- Enables PR-bot coordinate-to-symbol resolution.
- Prevents wrong blast-radius answers from ambiguous names.
- Gives users and MCP clients explicit ambiguity responses instead of hidden guesses.
- Keeps Agent SDK where it is strongest: conceptual discovery, missing coverage, and disambiguation.

### Negative

- Requires maintaining a symbol index per supported language.
- V1 precision depends on the language extractor quality.
- Dynamic language behavior will remain imperfect without targeted rules or fallback exploration.

### Neutral

- This ADR does not require Postgres / AGE before the resolver is useful.
- This ADR does not define the full Tool Query Contract schema.
- This ADR does not make code symbols part of the final Product 1 canonical ontology.

## References

- `source/KG-QUERY-SMOKE-TESTS.md`
- `source/kg/python_ast_extractor.py`
- ADR-0001: `adr/0001-claude-agent-sdk-for-internal-runtime.md`
- ADR-0005: `adr/0005-modular-evidence-retrieval-with-coordinate-fetch-and-selective-ladder.md`
- ADR-0006: `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- `graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md`
