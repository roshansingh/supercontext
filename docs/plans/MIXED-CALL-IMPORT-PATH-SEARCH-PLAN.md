# Mixed Call/Import Path Search Plan

Status: proposal for review
Date: 2026-05-08
Input evidence: `docs/evaluation/MEDIUM-QUERY-AGGREGATION-RUN-2026-05-08.md`

## Goal

Add a deterministic path-search query over existing KG facts so users can ask:

```text
What dependency path connects this symbol to this package or internal module?
```

This targets Q026 directly and should improve the usefulness of Q018 and Q027 without adding new extractors, LLM calls, storage changes, or product-level natural-language parsing.

## Why This Is Next

After the aggregation PR, both `mercury_ml` and `true_loop` improved to 5 medium passes. The remaining non-fixture failures are not primarily language extraction gaps:

- Q026 fails because there is no mixed `CALLS` + `IMPORTS` path search.
- Q018 is partial because wrapper usage needs connecting internal call paths to external package/API use.
- Q027 is partial because dependency removal impact currently shows direct importers, not path-based usage from entry symbols.

This is a reusable graph primitive, not a one-off report.

## Proposed Query Surface

Add one focused CLI/query method:

```bash
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-path predict_on_session sklearn --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop dependency-path generateResponseStream openai --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop dependency-path generateResponseStream src.lib.ai-client --max-depth 4 --limit 5
```

Initial name: `dependency-path`.

Inputs:

| Argument | Meaning |
|---|---|
| `source` | Symbol query resolved by existing symbol lookup. |
| `target` | Import/module/package query resolved by the shared import-target matcher from `source/kg/aggregations.py`. |
| `--path`, `--line` | Optional source-symbol disambiguation, same convention as existing symbol commands. |
| `--include-all` | If source symbol is ambiguous, search from all candidates. Default is to return ambiguity. |
| `--max-depth` | Default `4`; hard cap `6` in v1 to avoid noisy traversals. |
| `--limit` | Default `5`; maximum number of shortest paths returned. |

## Graph Traversal Model

Traversal should be language-independent and operate only on normalized facts.

Allowed v1 edges:

| From | Fact | To | Why |
|---|---|---|---|
| `CodeSymbol` | `CALLS` | `CodeSymbol` | Symbol-to-symbol execution path. |
| `CodeSymbol` | `CALLS` | `ExternalPackage` | Direct external API/package call already captured in snapshots. |
| `CodeSymbol` | `CALLS` | `CodeModule` | TS/JS imported module call targets already appear in current facts. |
| `CodeSymbol` | `DEFINED_IN` reverse | `CodeModule` | Connect a symbol to the module that owns its imports. |
| `CodeModule` | `IMPORTS` | `ExternalPackage` | Connect module code to third-party packages. |
| `CodeModule` | `IMPORTS` | `CodeModule` | Connect module code to internal module wrappers. |

Do not infer edges that are not present. If a target is unreachable from current facts, return `empty` with the resolved source/target and traversal settings.

## Output Contract

Return a JSON object:

```json
{
  "status": "resolved",
  "source": {
    "status": "resolved",
    "resolved_symbol": {"display_name": "...", "path": "...", "line": 70}
  },
  "target": {
    "status": "resolved",
    "resolved_target": {"display_name": "scikit-learn", "kind": "ExternalPackage"}
  },
  "max_depth": 4,
  "path_count": 2,
  "returned_count": 2,
  "paths": [
    {
      "depth": 3,
      "nodes": [
        {"entity_id": "...", "kind": "CodeSymbol", "display_name": "..."},
        {"entity_id": "...", "kind": "CodeModule", "display_name": "..."},
        {"entity_id": "...", "kind": "ExternalPackage", "display_name": "scikit-learn"}
      ],
      "edges": [
        {
          "fact_id": "fact_...",
          "predicate": "DEFINED_IN",
          "direction": "reverse",
          "derivation_class": "deterministic_static",
          "sources_count": 1,
          "evidence_samples": [{"path": "...", "line_start": 70}]
        }
      ]
    }
  ]
}
```

Status values:

| Status | Meaning |
|---|---|
| `resolved` | Source and target resolved, at least one path returned. |
| `ambiguous` | Source or target matched multiple candidates and `--include-all` was not set. |
| `not_found` | Source or target could not be resolved. |
| `empty` | Source and target resolved but no path exists within `max_depth`. |

## Code Approach

Keep the implementation surgical and modular.

Planned files:

| File | Change |
|---|---|
| `source/kg/path_search.py` | New pure traversal module. Build an adjacency list from existing facts and return shortest paths with evidence summaries. |
| `source/kg/queries.py` | Add a thin `KgSnapshot.dependency_path(...)` wrapper. Reuse existing `_resolve_symbol`; do not duplicate symbol resolution. |
| `source/kg/aggregations.py` | Reuse or expose target-resolution helpers if needed. Do not duplicate import target matching. |
| `source/scripts/query_kg.py` | Add the `dependency-path` CLI command. |
| `docs/evaluation/` | Add a new run note with Q026 before/after and any Q018/Q027 partial movement. |

Implementation details:

1. Use breadth-first search because v1 needs shortest unweighted paths, not weighted ranking.
2. Build adjacency once per query from canonical facts only.
3. Preserve edge direction in output; reverse `DEFINED_IN` is allowed only to move from symbol to containing module.
4. Deduplicate paths by entity-id sequence.
5. Stop after `limit` paths and never traverse beyond `max_depth`.
6. Include evidence summaries per edge using the same shape as aggregation rows: `derivation_class`, `sources_count`, `evidence_samples`.
7. Keep candidate facts hidden by default through `canonical_status == "canonical"` filters on entities and facts.

## What Not To Build In This Slice

Out of scope:

- weighted/ranked path scoring
- type-aware TS resolution
- dynamic dispatch or runtime import handling
- PR diff parsing
- endpoint/schema/deploy/catalog traversal
- LLM explanation generation
- natural-language query parsing
- multi-repo service-level path search

The first version should expose the raw deterministic path evidence. A later product layer can summarize it.

## Verification Plan

Run:

```bash
python -m compileall -q source

python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-path predict_on_session sklearn --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-path predict_on_session pandas --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml dependency-path chat_completion_request_instructor openai --max-depth 4 --limit 5

python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop dependency-path generateResponseStream src.lib.ai-client --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop dependency-path generateResponseStream react --max-depth 4 --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop dependency-path generateResponseStream openai --max-depth 4 --limit 5
```

Also run no-regression smoke:

```bash
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml find-callees predict_on_session --path mercury_ml/intent_based_predictions/batch_predict.py --line 77 --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing-both pandas sklearn --limit 5
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop top-fan-in-symbols --limit 5
```

## Expected Evaluation Movement

| Query | Current status | Expected after this slice | Notes |
|---|---|---|---|
| Q026 | Fail | Pass if fixture paths exist; otherwise `empty` with correct proof shape | Main target. |
| Q018 | Partial | Better partial | Wrapper-to-external dependency paths become visible, but full wrapper API classification is still out of scope. |
| Q027 | Partial | Better partial | Dependency removal impact can show path-based usage from entry symbols, but break-first ranking remains out of scope. |
| Q016 | Partial | No guaranteed movement | Reverse transitive impact uses related traversal mechanics, but this PR should not expand into general blast-radius. |

## Acceptance Criteria

- `dependency-path` returns JSON with resolved source, resolved target, paths, nodes, edges, and evidence summaries.
- Ambiguous source symbols return `status="ambiguous"` unless `--include-all` is set.
- External package targets and internal module targets both work.
- No existing low-query or aggregation command regresses.
- Evaluation note records exact results for both `mercury_ml` and `true_loop`.

## Review Questions

1. Should `dependency-path` search from symbol to dependency only, or allow dependency-to-symbol reverse paths too? Recommendation: symbol-to-dependency only in v1.
2. Should direct `CALLS -> ExternalPackage` be considered a path to the package even if the module does not import it? Recommendation: yes, because the fact already has call evidence.
3. Should `DEFINED_IN` traversal be reverse-only in v1? Recommendation: yes, to connect a symbol to its module imports without exploding into every symbol in a module.
