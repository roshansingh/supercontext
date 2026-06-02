# Coverage Metrics

SuperContext coverage metrics score how complete, useful, and trustworthy a KG snapshot is. Most metrics are `0.0` to `1.0`, where higher is better. `M_silent_gap` is the exception: lower is better because it measures missed opportunities.

The metric formulas are intentionally language-neutral. They consume canonical
snapshot inputs: manifest language counts, entities, facts, evidence, coverage
rows, package classifications, dimension assignments, and opportunity rows. A
language improves metric quality by emitting those inputs through its language
plugin. If a language has no opportunity detector for a predicate, opportunity
metrics should be read as `n_a` rather than evidence that no gap exists.

## Metrics

### `M_inventory`
Measures indexed repositories divided by expected repositories. Helps catch incomplete fleet snapshots before interpreting graph quality; for example, indexing 21 of 23 expected repos scores `21 / 23 = 0.91`.

### `M_dimension_classification`
Measures discovered source files that were assigned to at least one product dimension, such as `backend`, `frontend`, `iac`, or `ai-ml`. Helps show whether the repo was understood structurally; for example, if 800 of 1,000 source files are classified, the score is `0.80`.

### `M_freshness`
Measures entities whose latest evidence is within the configured freshness window. Helps prevent stale answers; for example, a repo where 950 of 1,000 entities were seen within the freshness window scores `0.95`.

### `M_extractor_opportunity`
Measures emitted facts divided by detected extraction opportunities, grouped by predicate, language, and dimension. Helps identify where an extractor is leaving value on the table; for example, 320 `CALLS_ENDPOINT` facts from 500 HTTP-call opportunities scores `0.64`.

### `M_evidence_grounding`
Measures source-backed facts that have valid `bytes_ref` evidence coordinates. Helps enforce citation quality; for example, if 990 of 1,000 source facts have repo, commit, file, and line evidence, the score is `0.99`.

### `M_meta_coverage`
Measures expected tool-scope pairs that have an explicit coverage row. Helps distinguish "nothing exists" from "we never checked"; for example, an unsupported Java repo should emit `LANGUAGE_SUPPORT` coverage instead of silently returning empty results.

### `M_silent_gap`
Measures detected opportunities that produced neither a fact nor a coverage row. Helps catch unsafe silence; for example, 25 unreported unresolved HTTP calls out of 500 opportunities gives `25 / 500 = 0.05`, and the target is `0.0`.

### `M_trust_mix`
Measures the quality mix of facts by `derivation_class` and `canonical_status`. Helps avoid inflated coverage from weak or candidate facts; for example, deterministic static facts score higher than LLM-inferred candidate facts.

### `M_useful_edge`
Measures anchor entities that have at least one product-useful edge for their dimension. Helps avoid vanity fact counts; for example, a frontend repo with many files but no endpoint-call, import, or deploy edges will score poorly.

### `M_cross_repo_linkage`
Measures resolved package-to-repo links divided by resolvable package imports. Helps evaluate multi-repo impact readiness; for example, if 8 internal package imports can be linked to provider repos and 2 remain unresolved, the score is `0.80`.

### `M_identity_health`
Measures entities with expected stable identity and URN shape. Helps keep graph nodes deduplicated and linkable across runs; for example, `CodeSymbol` identities must include enough namespace, module, qualname, and kind information to avoid collisions.

## Output

`coverage_metrics` writes `<snapshot>/metrics.jsonl`. `coverage_report` renders `coverage-run.json` and `coverage-run.md` under `docs/evaluation/runs/<run-id>/`.
