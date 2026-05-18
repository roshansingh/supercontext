# Coverage Metrics — Incremental Ingestion + Cross-Repo Linking Gaps

**Status:** open follow-up to Debate 14. The debate transcript is a local agent-debate artifact, not a committed repository file.
**Date:** 2026-05-17

## Why this doc exists

Debate 14 converged on **11 coverage metrics** (`M_inventory`, `M_dimension_classification`, `M_freshness`, `M_extractor_opportunity`, `M_evidence_grounding`, `M_meta_coverage`, `M_silent_gap`, `M_trust_mix`, `M_useful_edge`, `M_cross_repo_linkage`, `M_identity_health`) and a plan to implement them as a projection over JSONL snapshots. The converged plan is sound for a **fleet built in one shot** but has gaps the moment an org adds repo N+1 to an existing N-repo fleet.

This doc captures:

1. What incremental ingestion **does** preserve (per-repo determinism)
2. Where it **silently breaks** (cross-repo linker)
3. Whether the converged metric set actually catches the breakage (yes for extent, no for staleness)
4. What needs to land for incremental ingestion to be safe + a metric output that's trustworthy

Out of scope: Debate 14's metric semantics themselves (those are final).

## 1. Per-repo determinism — what incremental ingestion preserves

KG row IDs are content-hashed via `stable_hash(...)` over the row's identifying fields in `source/kg/core/models.py`. Timestamps are not in the hash. So for a given `commit_sha`:

| Row kind | ID derivation | Identical across runs? |
|---|---|---|
| `entity_id` | `ent_{stable_hash(kind, identity)}` in `models.py` | ✅ yes |
| `fact_id` | `fact_{stable_hash(predicate, subject_id, object_id, qualifier)}` in `models.py` | ✅ yes |
| `evidence_id` | `ev_{stable_hash(target_type, target_id, source_system, source_ref, bytes_ref)}` in `models.py` | ✅ yes |
| `coverage_id` | `cov_{stable_hash(tenant_id, predicate, scope_ref, source_system)}` in `models.py` | ✅ yes |
| `ingested_at` field value | `utc_now_iso()` per row in `models.py` | ❌ differs per run, but **not part of any hash** |

**Consequence:** adding repo #11 to a fleet leaves repos #1–#10's snapshots **bit-identical in IDs**. Re-running `build_kg` on an unchanged repo also produces ID-identical output. The remaining timestamp diffs (`ingested_at`, `checked_at`, `built_at`) do not affect KG identity or graph topology; they can affect freshness-window metrics such as `M_freshness`.

## 2. Where incremental silently breaks — cross-repo linker

`source/kg/build/multi_repo.py` runs a **package linker** after per-repo extraction. The linker produces cross-repo artifacts that depend on the **full set of repos given to it**:

- `ExternalPackage` entity dedup across repos
- `RESOLVES_TO_REPO` facts (e.g., a PyPI distribution imported in repo A maps to repo B if B publishes that distribution)
- Manifest fields: `linker.provider_count`, `linker.link_count`, `linker.ambiguous_package_count`

If the linker is run over `{1..10}` and later a snapshot for repo 11 is added without re-running the linker:

- Repo 11's imports of packages exported by repos 1–10 → **unresolved** (linker never saw them as a resolution target)
- Repos 1–10's imports of packages exported by repo 11 → **unresolved** (snapshots 1–10 still hold the linker's view from when only 1–10 existed)
- `ExternalPackage` dedup may miss the repo-11-published package, double-counting it as an external

This PR adds a `bettercontext-relink` entry point so the linker can be refreshed without re-running extraction. Before this command existed, the only workaround was to re-run `build_multi_kg`, which re-extracts everything and defeats the point of incremental ingestion.

Current storage shape matters here:

- `build_multi_kg(...)` writes one combined snapshot through `JsonlKgStore(output_dir).write(...)`, not one mutable snapshot per input repo.
- The combined manifest stores `built_at`, repo list, and linker counts, while `JsonlKgStore.write(...)` writes `entities.jsonl`, `facts.jsonl`, `evidence.jsonl`, `coverage.jsonl`, and `manifest.json` in that one output directory.
- The CLI wrapper `source/scripts/build_multi_kg.py` accepts repeated `--repo` inputs and one `--out` directory for from-source builds. The relink-only path is now owned by `source/scripts/relink.py`.

**Design implication:** relink-only should introduce an explicit fleet-level artifact instead of mutating per-repo JSONL files by default. Mutating per-repo `facts.jsonl` would mix repo-local extraction output with a fleet projection and make the same repo snapshot differ depending on which fleet it was linked in.

## 3. Does any metric capture this gap?

**M_cross_repo_linkage (metric #10)** — defined as `resolved package-to-repo links / resolvable package imports`. It captures **extent** of cross-repo resolution. Per Debate 14 §"Unified metric set" row 10.

But there's a subtle failure mode the metric **does not distinguish**:

| Scenario | M_cross_repo_linkage reading | Truth |
|---|---|---|
| Linker complete, genuinely sparse linkage | low value | accurate — extractors/registry resolvers weak |
| Linker **stale** (incremental flow without relink) | low value | **inaccurate** — linker hasn't seen the latest snapshots; the linkage exists but wasn't computed |

Both produce the same number. A consumer reading `M_cross_repo_linkage = 0.42` cannot tell whether the cause is "improve our resolvers" or "re-run the linker."

**No current metric carries linker-freshness as a separate signal.** Debate 14's `M_freshness` is per-entity (per `evidence.ingested_at`), not per-projection-step. The linker's "last-run" timestamp lives in `manifest.json` `built_at`, which isn't a metric input.

## 4. What we need to make incremental safe

Three components, ordered by dependency:

### 4.1 `relink-only` entry point (load-bearing)

Concrete proposal:

- **New CLI**: `bettercontext-relink --snapshot-dir <fleet-dir>`
- **Behavior**: reads each repo's existing `entities.jsonl` + `manifest.json`; **skips extraction**; runs only the linker step in `source/kg/build/multi_repo.py`; writes fleet-level linker output next to the per-repo snapshots:
  - `_fleet/cross_repo_links.jsonl` for linker facts such as `RESOLVES_TO_REPO`
  - `_fleet/cross_repo_link_evidence.jsonl` for linker evidence
  - `_fleet/manifest.json` with linker `built_at`, `source_system`, `rule_version`, `repo_commit_fingerprints`, informational `repo_commit_sha_set`, `provider_count`, `link_count`, and `ambiguous_package_count`
- **v1 constraint**: the original repo trees recorded in each snapshot `manifest.json.repo_path` must still exist. Relink reads package manifests (`pyproject.toml` / `package.json`) from that tree to identify provider aliases, and rejects git repos whose current `HEAD` no longer matches the snapshot `commit_sha`.
- **Non-goal for v1**: do not write refreshed cross-repo facts back into each repo's `facts.jsonl`. Keep repo-local extraction snapshots immutable and fleet linking as a projection.
- **Determinism guarantee**: `bettercontext-relink` over `{1..11}` must produce the same deterministic linker IDs and link semantics as `build_multi_kg` extracting + linking `{1..11}` from scratch at the same repo commits. Serialized timestamp fields such as `evidence.ingested_at` may differ.

This PR implements the relink-only entry point and routes from-source multi-repo builds through the same linker code path. The remaining gap is consumer integration: metrics and query readers must merge the fleet-level `cross_repo_links.jsonl` projection when they need current cross-repo links.

### 4.2 Linker-freshness contract flag on M_cross_repo_linkage

Concrete proposal:

- Per-fleet check: `linker_built_at >= max(per_repo.built_at)` ⇒ fresh; else stale
- Missing or unparsable per-repo/fleet `built_at` ⇒ stale with `linker_freshness_unknown=true`
- `_fleet/manifest.json.repo_commit_fingerprints` must equal the per-repo identity + commit entries being aggregated; mismatch ⇒ stale even if timestamps look fresh. The older `repo_commit_sha_set` is informational only because duplicate SHAs and `working-tree` snapshots can collapse.
- Stale linker → M_cross_repo_linkage is reported with a contract flag `linker_stale=true` (same shape as Debate 14's existing tool/predicate contract flags on M_evidence_grounding / M_meta_coverage / M_silent_gap)
- Consumers reading M10 always see the flag; can distinguish "improve resolvers" from "re-run linker"

This is additive to Debate 14's metric set — no new metric, just a flag on the existing one. Lands cheaply with the metric aggregator.

### 4.3 Metric output persistence (operational ergonomics)

Concrete proposal:

- `bettercontext-coverage-metrics` writes `metrics.jsonl` (one record per metric per cell) next to `entities.jsonl` etc.
- Each metric run records its `commit_sha_set` (sha per repo it aggregated) so historical comparisons can detect "snapshot drift" vs "extractor change"
- Delta mode: `bettercontext-coverage-metrics --compare snapshotA snapshotB` emits Δ per metric per cell

Without persistence, every metric query recomputes from JSONL. Fine for v1; needed for any production org dashboard.

## 5. Correct incremental ingestion flow (after the proposed changes)

```bash
# Existing fleet
ls data/kg_runs/
# team-a/  team-b/  ...  team-j/  _fleet/

# Add repo #11
bettercontext-build-kg --repo /work/team-new --out data/kg_runs/team-new

# Refresh the cross-repo linker only — re-extraction skipped
bettercontext-relink --snapshot-dir data/kg_runs/ --out data/kg_runs/_fleet

# Re-aggregate metrics from a combined snapshot today.
# Per-repo snapshots plus --fleet-dir need the follow-up fingerprint-aware metrics reader
# that merges _fleet/cross_repo_links.jsonl before M_cross_repo_linkage is complete.
bettercontext-coverage-metrics --snapshot data/kg_runs/combined

# Relinked cross-repo link facts/evidence should match the linker slice from a from-source build:
#   bettercontext-build-multi-kg --repo /work/team-a --repo /work/team-b ... --out data/kg_runs/combined-parity
```

Without `bettercontext-relink`, the org's choice today is:

- **Run full rebuild** every time a repo is added → O(N) extraction cost on every increment; correct
- **Skip linker refresh** → cheap; M_cross_repo_linkage silently degrades, and the metric can't tell you why

## 6. Relation to Debate 14

Debate 14 §"Final converged metric matrix" treats per-repo and fleet metrics as a projection over the JSONL union (plan rows #6, #11, #13). It does not specify whether the JSONL union is the result of (a) one batched build or (b) incremental builds + a re-linked union. That ambiguity is what this doc closes.

The 11 converged metrics remain unchanged. Three minor additions integrate cleanly:

- **Plan row #11 (`compute.py`)** — also reads `manifest.json:built_at` and `commit_sha` from each per-repo snapshot plus `_fleet/manifest.json:built_at` and `repo_commit_fingerprints`; computes `linker_stale = fleet.built_at < max(repo.built_at) OR repo_commit_fingerprints mismatch`, and attaches it as a contract flag to M_cross_repo_linkage when true
- **Plan row #17 (BACKLOG)** — add a row: "Relink-only entry point — `bettercontext-relink --snapshot-dir`. Needed for incremental ingestion correctness. Triggered when a second repo is added to an existing fleet without a re-extraction window."
- **New plan row (post-Debate-14 follow-up PR)** — `source/kg/build/relink.py` extracting the linker step from `multi_repo.py` so both `build_multi_kg` and the new CLI invoke the same code path. `build_multi_kg` may continue writing a combined snapshot; `relink.py` should additionally support fleet-level link artifacts for incremental snapshot directories.

None of these changes the converged metric semantics. They make the metric output trustworthy when the fleet was built incrementally.

## 7. BACKLOG additions to file

| Row | When triggered |
|---|---|
| Relink-only entry point (`bettercontext-relink --snapshot-dir`) — extract linker step from `source/kg/build/multi_repo.py` into a standalone `source/kg/build/relink.py`; both `build_multi_kg` and the new CLI invoke the same code path; relink writes fleet-level `_fleet/cross_repo_links.jsonl`, `_fleet/cross_repo_link_evidence.jsonl`, and `_fleet/manifest.json` by default | When second repo is added to an existing fleet OR when M_cross_repo_linkage starts being reported externally |
| Linker-freshness contract flag on M_cross_repo_linkage — `linker_stale` flag derived from manifest `built_at` comparison plus `_fleet/manifest.json.repo_commit_fingerprints` equality | Lands with the Debate-14 metric implementation PR (cheap addition to `compute.py`) |
| Metric output persistence — `metrics.jsonl` per snapshot; delta mode `--compare snapshotA snapshotB` | When an org dashboard or run-history feature is requested |
| Per-file incremental extraction — `build_kg --incremental --since-commit <sha>` rebuilds only files changed in the diff | When fleet repos exceed sizes where full per-repo rebuild on each commit becomes the bottleneck |

## 8. Open questions

- Do we ever need an opt-in compatibility mode that writes cross-repo facts back into per-repo `facts.jsonl`, or is the fleet-level `_fleet/cross_repo_links.jsonl` artifact sufficient for all metric/query consumers?
- Linker-freshness threshold: strict timestamp/commit-set correctness should be the default. A configurable window (`stale if fleet older than 24h`) is acceptable only as a dashboard warning threshold, not as correctness semantics.
- Should `M_inventory` also gain a `linker_stale` contract flag, or is the flag specific to M10?
- Per-file incremental extraction is a separate concern from linker incrementality. Worth a separate doc once it becomes the bottleneck.
