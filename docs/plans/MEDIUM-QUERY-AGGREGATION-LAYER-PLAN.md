# Medium Query Aggregation Layer Plan

Status: proposal for review
Date: 2026-05-08
Input evidence: `docs/evaluation/MEDIUM-QUERY-RUN-2026-05-08.md`

## Goal

Add a deterministic aggregation layer over existing KG facts to improve medium-tier queries without adding new extractors, LLM behavior, or storage changes.

This layer should convert normalized `IMPORTS`, `CALLS`, `Entity`, and `Evidence` rows into grouped/ranked answers.

## Why This Is Next

The medium-query run shows the current KG can already answer direct symbol, import, and evidence lookups. The next failures are mostly missing query aggregations:

- Q023: modules importing both dependency families.
- Q025: most depended-on internal modules.
- Q030: top risky functions by fan-in.
- Q017: direct `who-imports` works, but grouped internal-module output is missing.

These do not require deeper parsing. They require deterministic grouping, counting, ranking, and evidence sampling over facts already present in both `mercury_ml` and `true_loop`.

## Proposed Query Surfaces

| Command | Medium query | Purpose |
|---|---|---|
| `who-imports TARGET` | Q017 | Show modules importing an internal module or dependency, grouped by package/path area with citations. |
| `top-internal-dependencies` | Q025 | Rank internal `CodeModule` dependencies by importer count. |
| `top-fan-in-symbols` | Q030 | Rank `CodeSymbol` targets by number of callers. |
| `modules-importing-both A B` | Q023 | Find modules that import both normalized dependencies/packages/modules. |

Optional later additions, not in this slice:

- `dependency-impact PACKAGE` for Q027.
- `external-api-heavy-callers` for Q024.
- mixed call/import path search for Q026.

## Language Independence

The aggregation layer should be language-independent. It consumes normalized graph facts, not source files.

Required input contract:

```text
Entity.kind = CodeModule | CodeSymbol | ExternalPackage
Fact.predicate = IMPORTS | CALLS
Fact.qualifier.category = internal_module | relative_internal_module | third_party | stdlib | node_builtin | unknown
Evidence.bytes_ref = repo + commit_sha + path + line_start + line_end
```

Python and TS/JS differences remain inside extraction and normalization. Aggregation should treat both languages through the shared KG shape.

Language-specific details that the aggregator may expose but must not interpret deeply:

| Detail | Handling |
|---|---|
| Python `stdlib` vs TS/JS `node_builtin` | Treat both as built-in dependencies for filtering. |
| Python module names vs TS path-derived module names | Display module identity and evidence path; do not assume naming semantics. |
| TS `is_type_only` imports | Preserve in output; default behavior can include them but mark them. |
| Extractor precision differences | Do not infer beyond facts; return evidence and source system. |

## Implementation Shape

Recommended file layout:

```text
source/kg/aggregations.py
source/kg/queries.py
source/scripts/query_kg.py
docs/evaluation/
```

`source/kg/aggregations.py` should contain pure helper functions or a small class that operates on a `KgSnapshot`-like object:

```python
class KgAggregations:
    def who_imports(target: str, limit: int = 25) -> JsonObject: ...
    def top_internal_dependencies(limit: int = 25) -> list[JsonObject]: ...
    def top_fan_in_symbols(limit: int = 25) -> list[JsonObject]: ...
    def modules_importing_both(left: str, right: str, limit: int = 25) -> list[JsonObject]: ...
```

`source/kg/queries.py` can either instantiate/use this helper or expose thin wrappers. Keep existing PR4 query behavior unchanged.

`source/scripts/query_kg.py` should add CLI commands:

```bash
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml who-imports mercury_ml.chatbot.apis.openai_instructor --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop top-internal-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-fan-in-symbols --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing-both pandas sklearn --limit 10
```

## Output Contracts

### `who-imports`

Return:

- `status`
- `target`
- `importer_count`
- `groups`
- `importers`
- sample evidence per importer

Grouping can be by first two module path segments for now, for example:

```text
mercury_ml.chatbot
mercury_ml.intent_based_predictions
src.lib
src.app
```

### `top-internal-dependencies`

Rank `IMPORTS` facts where the object entity is `CodeModule` and qualifier category is `internal_module` or `relative_internal_module`.

Return:

- module display name
- importer count
- importer samples
- evidence samples

### `top-fan-in-symbols`

Rank `CALLS` facts where the object entity is `CodeSymbol`.

Return:

- symbol display name
- caller count
- caller samples
- evidence samples

### `modules-importing-both`

Find subject modules that have `IMPORTS` facts matching both inputs.

Inputs should match the same candidates currently used by `modules-importing`: entity name, raw import, import root, distribution name, or module name.

Return:

- module
- left evidence
- right evidence
- normalized left/right qualifier metadata

## Expected Evaluation Movement

| Query | Current status | Expected after implementation |
|---|---|---|
| Q017 | Partial | Pass |
| Q023 | Fail | Pass |
| Q025 | Fail | Pass |
| Q030 | Fail | Pass |

Possible partial improvement:

| Query | Why partial |
|---|---|
| Q027 | Direct importers can be shown, but “break first” ranking still needs call-site/dependency usage scoring. |
| Q024 | May improve if external package call facts are usable, but this should not be bundled unless evidence is clear. |

## Verification Plan

Run at minimum:

```bash
python -m compileall -q source
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml who-imports mercury_ml.chatbot.apis.openai_instructor --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop who-imports src.lib.debug-logger --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml modules-importing-both pandas sklearn --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop modules-importing-both react next --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-internal-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop top-internal-dependencies --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/mercury_ml top-fan-in-symbols --limit 10
python -m source.scripts.query_kg --snapshot data/kg_runs/true_loop top-fan-in-symbols --limit 10
```

Then create an evaluation note under `docs/evaluation/` recording:

- before/after for Q017, Q023, Q025, Q030
- exact command output summary
- remaining medium blockers

## Scope Boundaries

In scope:

- deterministic aggregation over current JSONL snapshot facts
- grouped/ranked outputs with evidence samples
- works for both Python and TS/JS snapshots if normalized facts exist

Out of scope:

- new language extraction
- type-aware call resolution
- PR diff parsing
- endpoint/schema/k8s/catalog fixtures
- LLM summarization
- product-level natural-language query parsing

## Open Questions For Review

1. Should `who-imports` replace or wrap the existing `modules-importing` command?
2. Should `top-fan-in-symbols` count duplicate evidence rows for the same caller/callee fact once or by evidence count? Recommendation: count unique facts once.
3. Should TS `is_type_only=true` imports count in `top-internal-dependencies` by default? Recommendation: include but mark; add filtering later only if evaluation shows noise.
4. Should grouping use module prefixes or filesystem path prefixes? Recommendation: module prefixes for now, evidence path always included.
