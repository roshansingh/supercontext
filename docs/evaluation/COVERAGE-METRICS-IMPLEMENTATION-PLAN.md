# Coverage Metrics — Implementation Plan (Debate-19 contract)

**Status:** complete — 11 PRs merged to `main` as of 2026-05-18
**Source:** Debate 19 (`debates/` was local-gitignored and is no longer present; this doc captures the converged contract)
**Related docs:**
- `docs/evaluation/claude-kg-coverage-metrices.md` + `docs/evaluation/codex-kg-coverage-metrices.md` — parallel research inputs (Debate-14 inputs)
- `docs/evaluation/COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md` — incremental ingestion + linker-staleness follow-up (binding sub-spec)
- ADR-0006 — canonical ontology; URN per-kind spec at §3
- ADR-0011 — Python import distribution aliases (used by PyPI resolver PR-9)

## 1. Why this doc

Three load-bearing threads merged into one implementation series:

- **T1 — Debate-14 metric engine.** Converged on 11 coverage metrics across a fleet × per-repo × per-dimension matrix. `CellMetrics`/`MetricValue` output schema with `state ∈ {usable, partial, n_a}`.
- **T2 — Incremental ingestion + linker-staleness gap.** Captured in `COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md`. Adds `supercontext-relink` CLI + `_fleet/cross_repo_links.jsonl` artifacts + `linker_stale` contract flag on `M_cross_repo_linkage`.
- **T3 — Extractor gaps that limit metric meaningfulness.** Per-language `opportunity_detectors()` / `package_resolver()` / `dimension_rules()` / `useful_edges()` hooks all returned empty at start of series. Predicate-level extractor coverage was uneven.

Debate-19 produced a 12-PR plan to land all three coherently. This doc preserves that contract because the source debate file is no longer in the working tree.

## 2. The 11 metrics (from Debate-14)

| # | Metric | One-line definition |
|---|--------|---------------------|
| 1 | `M_inventory` | Indexed repos / expected repos |
| 2 | `M_dimension_classification` | Source files claimed by ≥1 dimension / total discovered source files |
| 3 | `M_freshness` | Entities with last evidence inside per-relation window / total entities |
| 4 | `M_extractor_opportunity` | Facts emitted / opportunities detected, per (predicate, lang, dim) |
| 5 | `M_evidence_grounding` | Facts with a valid `bytes_ref` / source-backed facts |
| 6 | `M_meta_coverage` | `(subject, predicate)` pairs with a coverage row / pairs the 8 MCP tools could be asked about |
| 7 | `M_silent_gap` | Opportunities without (fact OR coverage_row) / opportunities detected (must trend to 0) |
| 8 | `M_trust_mix` | Distribution of facts across `derivation_class` × `canonical_status`, weighted |
| 9 | `M_useful_edge` | Anchor entities with ≥1 product-useful edge / discovered anchor entities (per-dim allowlist) |
| 10 | `M_cross_repo_linkage` | Resolved package-to-repo links / resolvable package imports |
| 11 | `M_identity_health` | Entities with expected per-kind URN/identity / total entities |

Dimensions: `{backend, frontend, ai-ml, iac, data-pipeline, shared-lib, mobile, cli-tool, docs}`.

Composite scoring:

```
cell_score(r, d) = geomean(M_freshness, M_extractor_opportunity, M_evidence_grounding,
                            M_meta_coverage, M_useful_edge, M_trust_mix)
                   × (1 − M_silent_gap)
                   × M_identity_health

repo_score(r)  = Σ_d (source_weight(r,d) / source_weight(r)) × cell_score(r,d)
fleet_score    = mean_r repo_score(r)
```

`cell_score` is `None` when any input metric has `state="n_a"`.

## 3. `CellMetrics` schema (v1 lock)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class CellMetrics:
    repo: str
    dimension: str | None              # None = repo-level (M_inventory, M_cross_repo_linkage)
    metric_values: dict[str, MetricValue]
    cell_score: float | None           # None iff any input metric.state == "n_a"
    contract_flags: tuple[str, ...]    # e.g. ("linker_stale",)
    commit_sha_set: tuple[str, ...]    # sorted; 1-tuple for repo cell, N-tuple for fleet cell

@dataclass(frozen=True)
class MetricValue:
    value: float | None                # None iff state == "n_a"
    state: Literal["usable", "partial", "n_a"]
    reason: str | None                 # None iff state == "usable"; required otherwise
```

Persisted as JSONL, one record per `(snapshot, repo, dimension)` at `<snapshot>/metrics.jsonl`.

The `state` field is the load-bearing addition: makes "we couldn't measure" distinguishable from "we measured low coverage."

Three contract flags, all tool/predicate-specific (per ADR-0006 partial-coverage rule — NOT whole-cell killers):
- `M_evidence_grounding < 1.0` on a surfaced fact → flag the fact (ADR-0005 violation)
- `M_meta_coverage < 1.0` on a `(tool, subject, predicate)` triple → tool's own partial-coverage contract decides warn vs refuse
- `M_silent_gap > 0` on a safety-critical tool input → tool refuses *only if* missing scope is relevant to the requested answer
- `linker_stale=true` on `M_cross_repo_linkage` when fleet linker output predates per-repo snapshots OR `repo_commit_sha_set` mismatches

## 4. PR sequence — 12 PRs

Branched from `main` (not `dotnet-support`). Each PR independently green via `python -m compileall -q source && python -m unittest discover -s tests`.

### Implementation status (2026-05-18)

| PR | Scope | Status | Merge / branch |
|----|-------|--------|----------------|
| PR-1 | Metric engine: all 11 metrics in `source/kg/metrics/`, `CellMetrics`/`MetricValue`, dimension classifier, per-language `dimension_rules.yaml`, shared loader, `tool_predicates.yaml`, CLI | ✅ merged | PR #80 (`debate19-pr1-metrics-foundation`) |
| PR-2 | `metrics.jsonl` persistence + `--compare A B` delta mode | ✅ merged | PR #82 (`debate19-pr2-metrics-persistence`) |
| PR-3 | Runner dimension-tagging — `Coverage.scope_ref` carries `dimension` + `path_prefix` conditionally | ✅ merged | PR #83 (`debate19-pr3-runner-dimensions`) |
| PR-4 | Per-kind URN per ADR-0006 §3; preserves `entity_id`; moves `M_identity_health` off baseline-zero | ✅ merged | PR #84 (`debate19-pr4-per-kind-urn`) |
| PR-5 | Python HTTP-client opportunity detector (`httpx`/`requests`/`aiohttp`) | ✅ merged | PR #85 (`debate19-pr5-python-http-opportunities`) |
| PR-6 | TS HTTP-client (`axios`/`fetch`) + Terraform domain-literal opportunity detectors | ✅ merged | PR #86 (`debate19-pr6-ts-terraform-opportunities`) |
| PR-7 | `useful_edges.yaml` per-dim content; linker predicates marked `source: linker` | ✅ merged | PR #87 (`debate19-pr7-useful-edge-config`) |
| PR-8 | Extract linker into `source/kg/build/relink.py` + `supercontext-relink` CLI + `_fleet/` artifacts + `linker_stale` flag | ✅ merged | PR #88 (`debate19-pr8-relink-only`) — bundles the original PR-8 refactor + PR-9 CLI |
| **PR-9** | Python PyPI package resolver | ✅ merged | PR #89 (`debate19-pr9-python-package-resolver`) — was PR-10 in the original plan |
| **PR-10** | TS npm package resolver | ✅ merged | PR #90 (`debate19-pr10-typescript-package-resolver`) — was PR-11 in the original plan |
| **PR-11** | BACKLOG-only — parked ontology/extractor follow-ups | ✅ merged | PR #91 (`debate19-pr11-backlog-followups`) — was PR-12 |

Note on numbering drift: the converged plan originally had 12 PRs and treated the linker refactor (PR-8) and the relink CLI (PR-9) as separate. PR #88 landed both as one PR. Current numbering above reflects what actually shipped.

## 5. Completed PR slices and parked follow-ups

### PR-9 (was PR-10) — Python PyPI package resolver

**Goal:** `LanguageSupport.package_resolver()` for Python returns a real resolver instead of `None`; centralizes `pyproject.toml`/`setup.cfg`/`setup.py` parsing for the relink path.

**Files:**

| # | File | Change |
|---|------|--------|
| 9.1 | `source/kg/languages/python/package_resolver.py` (NEW) | `PythonPackageResolver` — reads target repos' Python distribution metadata; consults ADR-0011 alias rules; exposes `resolve(import_root, target_repos) -> str | None` |
| 9.2 | `source/kg/build/multi_repo.py` | No direct change on current `main`; multi-repo builds already delegate cross-repo linking through `source/kg/build/relink.py` |
| 9.3 | `source/kg/build/relink.py` (MODIFY) | Use `PythonPackageResolver` for cross-repo Python linkage in relink-only path |
| 9.4 | `source/kg/languages/python/language.py` (MODIFY) | `package_resolver()` returns `PythonPackageResolver()` instead of `None` |
| 9.5 | `tests/languages/test_python_package_resolver.py` (NEW) | Standalone resolver test with fixture distribution metadata |

**Metric impact:** `M_cross_repo_linkage` for Python-only snapshots moves from `state="partial"` to `state="usable"` when linker output is current. Mixed-language snapshots remain `partial` until every language represented in `manifest.counts.files_by_language` has a resolver.

**Verification:**
- `python -m compileall -q source && python -m unittest discover -s tests`
- Existing `tests/test_multi_repo_identity.py` Python cases continue passing — proves refactor is behavior-preserving
- Standalone resolver test passes with fixture metadata

### PR-10 (was PR-11) — TS npm package resolver

**Goal:** Mirror of PR-9 for TypeScript/JavaScript.

**Files:**

| # | File | Change |
|---|------|--------|
| 10.1 | `source/kg/languages/typescript/package_resolver.py` (NEW) | `TypeScriptPackageResolver` — reads `package.json` `name` + scoped/unscoped aliases |
| 10.2 | `source/kg/build/multi_repo.py` | No direct change expected on current `main`; multi-repo builds already delegate cross-repo linking through `source/kg/build/relink.py` |
| 10.3 | `source/kg/build/relink.py` (MODIFY) | Use TS resolver |
| 10.4 | `source/kg/languages/typescript/language.py` (MODIFY) | `package_resolver()` returns resolver |
| 10.5 | `tests/languages/test_typescript_package_resolver.py` (NEW) | Standalone resolver test |

**Metric impact:** `M_cross_repo_linkage` for TS imports moves from `state="partial"` to `state="usable"`. After both PR-9 + PR-10 land, M_cross_repo_linkage is `state="usable"` for the two production languages.

### PR-9 implementation result

Merged as PR #89 on 2026-05-18.

Files changed:
- `source/kg/languages/python/package_resolver.py`
- `source/kg/languages/python/language.py`
- `source/kg/languages/python/normalization/imports.py`
- `source/kg/build/relink.py`
- `source/kg/metrics/compute.py`
- `tests/languages/test_python_package_resolver.py`
- `tests/languages/test_python_typescript_wrappers.py`
- `tests/metrics/test_compute.py`
- `tests/test_relink.py`

Verification:
- `.venv/bin/python -m compileall -q source`
- `.venv/bin/python -m unittest discover -s tests`
- CI `test` check passed on PR #89

Reviewer loop:
- Claude pre-PR review run twice; actionable findings handled.
- Copilot review loop completed on current head `80bac0a68c6c` with zero actionable feedback.

Evaluation movement:
- Python-only snapshots can now report `M_cross_repo_linkage` as `usable` when linker output is current.
- Mixed Python/TypeScript snapshots remain `partial` until PR-10 lands the TypeScript/npm resolver.

### PR-10 implementation result

Merged as PR #90 on 2026-05-18.

Files changed:
- `source/kg/languages/typescript/package_resolver.py`
- `source/kg/languages/typescript/language.py`
- `source/kg/build/relink.py`
- `source/kg/metrics/compute.py`
- `tests/languages/test_typescript_package_resolver.py`
- `tests/languages/test_python_typescript_wrappers.py`
- `tests/metrics/test_compute.py`
- `tests/test_relink.py`

Verification:
- `.venv/bin/python -m compileall -q source`
- `.venv/bin/python -m unittest discover -s tests`
- CI `test` check passed on PR #90

Reviewer loop:
- Claude pre-PR review run once before PR; suggested fallback tests were added.
- Copilot review completed on current head `bd494d34e4f9` with zero actionable feedback.

Evaluation movement:
- Python and TypeScript snapshots can now report `M_cross_repo_linkage` as `usable` when linker output is current.
- `rg -n "package_resolver\\s*\\(\\).*|return None" source/kg/languages -g 'language.py'` now only reports the template language support.

### PR-11 (was PR-12) — BACKLOG-only follow-ups (no code)

**Goal:** Park the deferred ontology/extractor gaps so they don't get lost.

**BACKLOG.md additions:**

| Row | When triggered |
|-----|----------------|
| CODEOWNERS extractor for ownership facts — emit canonical `OWNS` unless ADR-0006 later ratifies an `OWNED_BY` inverse | When deploy-blocker semantics or PR-bot ownership routing becomes a product surface |
| `USES_SCHEMA` qualifier with version chains — partial today; required for deploy-blocker semantics | When `deploy_blockers_for` lands meaningfully |
| `evidence.valid_from`/`valid_to` envelope — ADR-0006 §36 binding; current `Evidence` dataclass omits | When time-window-based `M_freshness` reporting becomes needed |
| `CALLS` grain elevation from `CodeSymbol → CodeSymbol` to `Service → Endpoint` — required for accurate cross-service metric semantics | When inter-service blast-radius queries land |
| Kafka producer/consumer detectors for `PRODUCES_EVENT`/`CONSUMES_EVENT` outside of boto3 | When org-level Kafka deployments need cross-service event tracing |
| `DEPLOYS_VIA_CONFIG`, `PROVIDES_RESOURCE`, `DEPENDS_ON_MODULE` predicate landings + ADR-0006 ratification | When Terraform broader IaC semantics needed (Helm/k8s/Pulumi additions) |
| Per-file incremental extraction — `build_kg --incremental --since-commit <sha>` rebuilds only files changed in the diff | When fleet repos exceed sizes where full per-repo rebuild on each commit becomes the bottleneck |
| Org dashboard / metric run history — `metrics.jsonl` accumulation + visualization | When customer-facing reporting becomes a feature requirement |

No code changes in PR-11; pure tracked-deferral housekeeping.

### PR-11 implementation result

Merged as PR #91 on 2026-05-18.

Files changed:
- `BACKLOG.md`
- `docs/evaluation/COVERAGE-METRICS-IMPLEMENTATION-PLAN.md`

Verification:
- `.venv/bin/python -m compileall -q source`
- `.venv/bin/python -m unittest discover -s tests`
- CI `test` check passed on PR #91

Reviewer loop:
- Claude pre-PR review approved; ownership wording was adjusted after verifying ADR-0006 already includes canonical `OWNS`.
- Copilot review completed on current head `2c42d4cae133` with zero actionable feedback.

## 6. Verification gates

After each PR:

```bash
python -m compileall -q source
python -m unittest discover -s tests
```

After PR-9 + PR-10 lands:

```bash
# Confirm resolvers are real
rg -n "package_resolver\\s*\\(\\)\\s*:\\s*\\n\\s*return None" source/kg/languages/{python,typescript}
# expect: zero hits

# Confirm M_cross_repo_linkage state shift for Python + TS cells
python -m source.scripts.coverage_metrics --snapshot data/kg_runs/<fleet>
# expect: no MetricValue(state="partial", reason starts with "package_resolver hooks are not implemented ...") for Python/TS dims
```

After PR-11 (BACKLOG-only):

```bash
# Confirm rows added; no source diff
git diff --stat main
# expect: only BACKLOG.md modified
```

## 7. Explicit non-changes (this 12-PR series)

- No new ADR.
- No LICENSE / CONTRIBUTING.md (user-deferred).
- No Java/.NET extractor PRs (separate series).
- No per-file incremental extraction (BACKLOG'd in PR-11).
- No mutation of per-repo `facts.jsonl` during relink (immutability guarantee — fleet linking is a projection at `_fleet/cross_repo_links.jsonl`).
- No new predicates added to `SUPPORTED_FACT_PREDICATES` (`DEPLOYS_VIA_CONFIG`, `PROVIDES_RESOURCE`, `DEPENDS_ON_MODULE` BACKLOG'd in PR-11).
- No CODEOWNERS extractor (BACKLOG'd in PR-11).

## 8. Codex's key narrowings (preserved for future reference)

These were the load-bearing R1/R2 corrections during Debate-19 convergence:

1. **Per-kind URN moved early (PR-4, not last).** `Entity.entity_id` is independent of `urn` (`source/kg/core/models.py` uses `stable_hash(kind, identity)`); changing URN format is a safe refactor. `M_identity_health` should not stay baseline-zero through 11 other PRs.

2. **Linker plumbing bundled into one coherent PR.** Original plan split `linker_stale` flag (PR-4) from relink CLI (PR-11). Codex correctly observed: a flag that fires before the artifact it depends on exists is under-specified. PR #88 landed extraction + CLI + `_fleet/manifest.json` + flag together.

3. **Relink foundation before new resolvers.** Current linker already does semantic package matching from manifest-declared metadata; the missing capability is operational (extracting it). New PyPI/npm resolvers reuse the centralized parsing instead of duplicating.

4. **`n_a` spelling everywhere (not `n/a`).** Avoids JSONL-row escape headaches and false deltas across schema revisions.

5. **`commit_sha_set` is a `CellMetrics` field, not a side-channel.** Lets a metric record self-describe which commits it aggregated.

6. **Parked extractor gaps stay parked.** `OWNED_BY` / `USES_SCHEMA` version chains / `valid_from`/`valid_to` / loud-refusal completeness are real ADR-0006 gaps but the affected metrics can mark `state="partial"` with reason rather than block this series.

7. **`useful_edges.yaml` distinguishes adapter vs linker predicates.** `RESOLVES_TO_REPO` and `RESOLVES_TO_SERVICE` are emitted by the linker (not the adapter pipeline) and are not in `SUPPORTED_FACT_PREDICATES`. The YAML carries `source: linker` to keep them usable for `M_useful_edge` without expanding the adapter allowlist.

## 9. Open questions (post-implementation)

Surfaced during PR-4 review (`docs/reviews/PRE-PR-REVIEW-debate19-pr4-per-kind-urn-MANUAL.md`):

- **CodeSymbol URN drops `symbol_kind` from identity.** `entity_id` keys on it; `urn` does not. Two symbols with same `(tenant_id, repo, module, qualname)` but different `symbol_kind` get distinct entity IDs but identical URNs. Decision call for ontology owners; recommendation is to include `symbol_kind` as an extra URN segment.
- **Empty-string vs `None` host on Endpoint URN.** `None` → `_` placeholder; `""` → hash fallback. Inconsistency; extractor normalization protects production but a future direct constructor could hit the empty-string path.
- **`_looks_like_hash_urn` heuristic** keys on a 24-hex-char tail. A real identity field of exactly 24 hex characters would false-positive. Consider prefixing new URNs with a `v1:` marker for stronger detection.

Surfaced earlier but still relevant for the incremental story:

- **Opt-in compat mode for mutating per-repo `facts.jsonl`** — currently fleet linking is a projection at `_fleet/cross_repo_links.jsonl`. Confirm no consumer needs per-repo facts files to carry cross-repo links.
- **Should `M_inventory` also gain a `linker_stale` flag, or is the flag specific to `M_cross_repo_linkage`?**
- **Linker-freshness threshold** — strict timestamp/commit-set correctness is the v1 default. A configurable window (`stale if fleet older than 24h`) is acceptable only as a dashboard warning threshold, not as correctness semantics.

## 10. Cross-references

- 11-metric definitions, dimensions, composite formula: §2, §3 above
- Incremental ingestion safety guarantees: `COVERAGE-METRICS-INCREMENTAL-AND-LINKING-GAPS.md` (binding sub-spec)
- ADR-0006 per-kind URN format (PR-4): `adr/0006-canonical-ontology-and-fact-metadata-envelope.md`
- ADR-0005 evidence grounding contract: drives `M_evidence_grounding` knockout flag
- ADR-0011 Python distribution aliases: input to PR-9 PyPI resolver
- PR-4 review with surfaced URN issues: `docs/reviews/PRE-PR-REVIEW-debate19-pr4-per-kind-urn-MANUAL.md`
