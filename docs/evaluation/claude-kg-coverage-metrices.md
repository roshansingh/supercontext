# Claude KG Coverage Metrics

Status: proposal

Purpose: define **intrinsic** coverage metrics for the RKG — signals derived from the graph's own ontological contract, not from a fixed Q&A set. Q&A acceptance corpus (`docs/evaluation/PRODUCT-QUERY-SET.md`) remains useful as a *gate*; it is unfit as a *coverage signal* because it is bounded by the questions we imagined.

Designed to answer, per repo and per fleet of 100+ repos:

- Which repos are well-indexed vs hollow?
- Which extractors / allowlist entries would lift coverage *and how much*?
- Where are silent gaps (graph returns `[]` instead of refusing)?
- Is added coverage moving the product wedge, or just inflating fact counts?

## Why Q&A coverage is broken

Q&A pass-rate is a function of test-set imagination. Bounded by what *we* think to ask; production usage is unbounded. It rewards memorization of golden answers, not graph quality. It cannot catch silent gaps — when the graph returns `[]` because no extractor ever ran, the Q&A scores no worse than when it returns `[]` because nothing exists.

Better: measure the graph against **its own contract**. ADR-0006 already specifies the shape facts must have, the derivation classes, the promotion rules, and the coverage sidecar. Coverage = how close real data is to that specification, sliced by relation and scope.

## Prior art (informing this design)

- **CycloneDX completeness**: distinguishes *known empty* vs *unknown* in SBOM scopes. ADR-0006 §7 already adopts this; the `coverage` row's `state` field encodes it. Implication: a graph with rich `coverage` rows is *more* honest than one with rich facts but no coverage rows.
- **SCIP / LSIF**: code-intel completeness measured as resolved-reference ratio per file. Direct analog for our `CALLS` and `IMPORTS` relations.
- **Sourcegraph precise-nav coverage**: tracked per repo × language × indexer, not as one global number. Matrix shape transfers to multi-repo RKG fleets.
- **Data-quality dimensions** (accuracy, completeness, consistency, timeliness, validity, uniqueness): standard framing. More facts ≠ better facts.
- **OpenTelemetry trace coverage**: per-service capability matrix rather than one global score. Same pattern recommended here.

## Principles

1. **Measure opportunities, not just facts.** A repo with 320 `CALLS` facts out of 500 detected call-site opportunities (and 180 honest `coverage` rows for the rest) is *better* than a repo with 320 facts and silence on the rest.
2. **Reward honest refusal as much as extraction.** A `coverage` row with `state='uninstrumented'` is a covered scope. Silent skip is not.
3. **Per-relation, per-scope, not one number.** A single composite is fine for ranking; the dashboard must let an engineer drill to the failing (repo, relation, predicate, framework) cell.
4. **Composite uses geomean with knockouts.** Arithmetic mean lets zeros hide. Geomean punishes them. Knockouts on cited-ratio < 1.0 for surfaced facts and meta-coverage < 1.0 (ADR-0005 + loud-refusal contract violations).
5. **Gaming-resistant by construction.** Every metric below has a paired defense metric that crashes when the cheap trick is tried.

## Coverage axes (orthogonal — combine, don't substitute)

| # | Axis | Question it answers | Why orthogonal |
|---|------|---------------------|----------------|
| A | **Closure** | Do entities have edges the ontology says they should? | Catches missing edges |
| B | **Surface ↔ interior** | Borders mapped vs wiring mapped? | Borders cheap, wiring valuable |
| C | **Derivation tier** | What % facts are authoritative/deterministic vs `inferred_llm`? | Catches "we faked it with LLM" |
| D | **Evidence density** | Facts per evidence row; % facts with resolvable `bytes_ref` | Catches uncited facts (ADR-0005 contract) |
| E | **Promotion-readiness** | % candidate facts meeting promotion threshold | Tells you candidate-sidecar headroom |
| F | **Meta-coverage** | % `(subject, predicate)` pairs with *any* `coverage` row | Catches silent gaps — Q&A never can |
| G | **Cross-service edge density** | Inter-service edges per service-pair | Product wedge is cross-service; floor metric |
| H | **Schema traceability** | % Endpoints/Events with schema + consumer chain | Drives `deploy_blockers_for` |
| I | **Anchor-point hit rate** | % call/event sites caught by typed extractor vs heuristic | Direct ROI signal for allowlist work |
| J | **Freshness** | % entities with evidence in last commit window | Stale ≠ missing |
| K | **Polyglot reach** | LOC / manifests under instrumented lang+framework | Loud-refusal contract |
| L | **Identity health** | % entities with stable URN; alias conflict rate | Graph quality, not quantity |

## Concrete metric formulas

### A. Closure coverage

```
closure(NodeType, Predicate) =
  |{e ∈ entities of NodeType : ∃ fact(e, Predicate, *)}| / |entities of NodeType|
```

Per `(NodeType, Predicate)`. Goes from 0 (nothing wired) to 1 (every entity has the expected edge).

Example: `closure(Service, OWNED_BY)` = fraction of services with an Owner edge.

**Gaming risk:** add low-confidence edges to pump A. Defense: C (tier) and D (density) drop, composite catches it.

**Fleet rollup:** `mean` and `min` per `(NodeType, Predicate)` across repos. Heatmap → where extractors fail systemically.

### B. Surface ↔ interior balance

```
surface  = closure(Endpoint, *) + closure(Event, *) + closure(Deployable, *)
interior = closure(Service, DEPENDS_ON) + closure(Service, CALLS)
         + closure(Endpoint, USES_SCHEMA) + closure(Event, USES_SCHEMA)
balance  = interior / max(surface, ε)
```

`balance < 0.3` → "we know the shape but not the wiring". `balance > 0.8` → healthy. Cross-service product wedge requires interior; surface-only RKG is a service catalog, not change-safety.

### C. Derivation-tier composition

```
tier_score(Predicate) =
  w_auth · share(authoritative_declared) +
  w_det  · share(deterministic_static) +
  w_run  · share(runtime_observed) +
  w_llm  · share(inferred_llm)

w_auth=1.0   w_det=0.9   w_run=0.7   w_llm=0.3
```

Weights track the precedence in ADR-0006 §6. Aggregate = relation-weighted mean.

Repos with deep allowlist hits score high here even at moderate edge count. Tells product *where* the next extractor pays off — high-volume relations with low tier_score are the candidates.

### D. Evidence density

```
cited_ratio(Predicate)   = |facts with ≥1 evidence with bytes_ref| / |facts|
evidence_per_fact_p50    = median(|evidence per fact|)
distinct_sources_p50     = median(|distinct source_system per fact|)
```

ADR-0005 Mode A requires commit-pinned bytes for surfaced facts. `cited_ratio < 1.0` for surfaced predicates is a **contract violation** — knockout.

**Gaming risk:** cite same `bytes_ref` everywhere. Defense: `distinct_sources_p50` and an exact-duplicate-bytes_ref count flag suspicious clustering.

### E. Promotion-readiness

```
promotion_ready(Predicate) =
  |{candidate facts : distinct sources ≥ 2 OR runtime_obs in last 14d ≥ 10}|
  / |candidate facts|
```

Per ADR-0006 §9 Q3 defaults. High = candidate sidecar carries real signal. Low = candidates are LLM noise that won't promote.

### F. Meta-coverage — **build first, highest signal**

```
meta_coverage(tenant) =
  |{(subject, predicate) pairs with any coverage row}|
  / |{(subject, predicate) pairs the 8 MCP tools could be asked about}|
```

This is the metric Q&A *cannot* produce. If `meta_coverage < 1.0`, some tool calls will silently return `[]` because the system never recorded "this scope is uninstrumented." The loud-refusal contract (PRD §7 + ADR-0006 §7) demands meta_coverage = 1.0 over the tool surface. Knockout if violated.

Already tracked partially in `BACKLOG.md` ("Loud refusal at ingestion"). This metric is the test for that contract.

### G. Cross-service edge density

```
xservice_density =
  |inter-service edges| / (|Services| · (|Services| - 1))

inter-service edges ⊆ {CALLS, EMITS_EVENT, CONSUMES_EVENT, DEPENDS_ON, USES_SCHEMA}
                       restricted to subject.service ≠ object.service
```

Below floor → product wedge cannot deliver, regardless of other metrics. This is the metric tied to *why the buyer is buying* (PRD §11 north-star). Knockout floor.

### H. Schema-evolution traceability

```
schema_trace(Endpoint) =
  1 if  (∃ fact: Endpoint USES_SCHEMA s)
    AND (∃ fact: Service CONSUMES_SCHEMA s)
    AND (s has ≥2 versions in evidence)
  else 0

H = mean(schema_trace) over Endpoints with public surface
```

Drives `deploy_blockers_for`. H < 0.5 → that tool largely refuses; expected and honest, but a coverage gap.

### I. Anchor-point hit rate (drives roadmap)

```
anchor_hit(framework_signature) =
  |call sites caught by typed extractor for framework|
  / |call sites in repos importing/using framework|
```

Denominator = static import + usage count (e.g., `aiohttp.ClientSession`, `kafka.KafkaProducer`, `axios.post`, gRPC stubs).
Numerator = call sites that produced a `deterministic_static` `CALLS` / `EMITS_EVENT` fact.

Maps 1:1 to `docs/graph-building/TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md`. Output:

> "Adding `kafka-python` producer extractor lifts I from 0.42 → 0.61, lifts closure(Service, EMITS_EVENT) from 0.31 → 0.58, lifts xservice_density by Δ. Estimated work: 1.5 days. Ranked #2 by expected fleet Δ."

Direct ROI signal. Stops extractor work from being driven by gut feel.

### J. Freshness

```
fresh(entity) = (now - max(evidence.ingested_at)) < window(predicate)
```

`window` per ADR-0006 §9 Q11 — per-relation defaults, tenant-overridable. Fleet rollup = `% fresh` per relation.

### K. Polyglot reach

```
polyglot_reach = LOC under (lang, framework) ∈ allowlist / total LOC in tenant repos
```

Anything outside allowlist must produce `coverage.state='uninstrumented'` for the relevant predicates. K and F together = "we know what we don't know."

### L. Identity health

```
urn_stability = |entities with human-readable URN per ADR-0006 §3| / |entities|
alias_conflict_rate = |aliases colliding across entities| / |aliases|
```

`urn_stability < 1.0` = hash-only URNs (v0 baseline). Catches drift back to opaque IDs.

## Composite — single score with knockouts

```
RKG_score = geomean(A_closure, C_tier, D_cited, F_meta, G_xservice)
            × freshness_decay(J)
            × polyglot_reach(K)

KNOCKOUTS:
  F < 1.0                                  → flag "silent gap"
  G < floor                                → flag "no product wedge"
  D < 1.0 for surfaced predicates          → flag "ADR-0005 violation"
  cited_ratio of any surfaced relation < 1.0 → block release of that relation
```

Geomean — not arithmetic — so any single zero collapses the score. Prevents "great elsewhere, terrible here" hiding.

## Gaming-resistance check

| Cheap trick | Defense |
|-------------|---------|
| Mass-produce `inferred_llm` candidates | E (promotion-readiness) crashes; C tier shifts toward `inferred_llm`; composite drops |
| Cite same `bytes_ref` everywhere | D `distinct_sources_p50` and bytes_ref dedup exposes |
| Add fake services to pump G denominator | L (identity health) breaks; promotion-readiness drops |
| Skip emitting `coverage` rows for uninstrumented scopes | F drops directly |
| Hand-curate one demo repo to 0.99 | Fleet `min(repo_score)` and variance metrics catch |
| Inflate closure with duplicate edges | `distinct_object_count` per `(subject, predicate)` exposes |

Every primary metric has at least one paired defense metric. Composite uses both.

## Fleet rollup (100+ repos)

Per repo: vector of (A, B, C, D, E, F, G, H, I, J, K, L). Per fleet:

- **Heatmap**: rows=repos, cols=metrics, color=value. Eyeball weak repos and weak metrics simultaneously.
- **Weak-link rollup**: `min` over repos per metric — "what's the worst repo for cross-service density?"
- **Weighted mean**: weight repos by `service_count × deploy_freq × blast_radius_centrality` so a tiny utility repo doesn't drag the headline number.
- **Δ-impact table**: derived from anchor-point counts — "if extractor X lands, expected fleet Δ per metric."
- **Variance**: high variance across repos = inconsistent extractor reach; low variance = uniformly good or uniformly bad.

## Map to current code

Existing `Coverage` row (`source/kg/core/models.py:97`) carries `(tenant_id, predicate, scope_ref, state, source_system, checked_at)`. Sufficient for F. Insufficient for B/G/H/I/J/K which need either node-level rollups or anchor-point catalogs.

Suggested extensions (low risk, all additive):

1. **`source/kg/queries/metrics.py`** — pure-Python aggregation over JSONL. Computes A, C, D, F, J. ~1 day from current store shape.
2. **`source/kg/extraction/anchor_inventory.py`** — counts import-sites and usage-sites per framework signature. Provides denominator for I. ~2-3 days.
3. **`coverage.scope_ref.reason`** field — per `BACKLOG.md` line 32. Required for F beyond binary state ("uninstrumented because language not in allowlist" vs "uninstrumented because path excluded").
4. **`evidence.bytes_ref` resolvability check** — CI gate verifying every surfaced fact's `bytes_ref` resolves to the committed bytes. Enforces D = 1.0 for surfaced relations.
5. **`source/kg/queries/fleet_metrics.py`** — multi-repo rollup over `MultiRepoBuild` (`source/kg/build/multi_repo.py`).

## Build order (highest signal first)

1. **F (meta-coverage)** — already half-built; closes loud-refusal contract; uncovers silent gaps Q&A misses. ~1 day from current JSONL.
2. **C (derivation tier)** — pure aggregation over `evidence.derivation_class`. ~half day. Immediate signal on "is this graph deterministic or vibes."
3. **I (anchor-point hit rate)** — requires anchor inventory denominator. ~2-3 days. Direct ROI input for extractor allowlist sprints.
4. **G (cross-service density)** — needs `Service` entity to be real (currently v0 has `CodeSymbol`-grain `CALLS`). Tied to closing the v0 divergence "CALLS grain = CodeSymbol→CodeSymbol not Service→Endpoint." Larger but the most product-aligned metric.
5. **D (evidence density / cited_ratio)** — wire as CI gate not a dashboard number. Contract enforcement.
6. **A, B, H, J, K, L** — flesh out the dashboard once 1-5 land.
7. **E** — meaningful only after promotion rules are actually enforced (currently everything defaults `canonical_status='canonical'`).

## Mapping to existing artifacts

| Metric | Ties to | Status |
|--------|---------|--------|
| A closure | ADR-0006 §2 (10 nodes, 15 relations) | computable from JSONL today |
| B balance | PRD §3 wedge | computable from JSONL today |
| C tier | ADR-0006 §6 derivation classes | computable from JSONL today |
| D cited | ADR-0005 Mode A | computable today; needs `bytes_ref` resolvability check |
| E promotion | ADR-0006 §9 Q3 promotion rules | depends on promotion enforcement (not yet wired) |
| F meta | ADR-0006 §7, PRD §7, BACKLOG "Loud refusal" | partially wired; needs `coverage.scope_ref.reason` |
| G xservice | PRD §3 + ADR-0009 | depends on Service-grain entities |
| H schema | ADR-0006 USES_SCHEMA + Tool Query Contract ADR | depends on schema version tracking |
| I anchor | `TYPED-CLIENT-EXTRACTOR-ALLOWLIST.md` | new; needs anchor inventory |
| J freshness | ADR-0006 §9 Q11 | computable once `valid_from`/`valid_to` lands on evidence |
| K polyglot | BACKLOG "Loud refusal at ingestion" | depends on LOC denominator extraction |
| L identity | ADR-0006 §3 URN scheme | computable today; v0 baseline ~0 |

## Open questions

- Anchor inventory: import-site count only, or full call-site count via AST? (Latter ≈ 5× slower, more precise denominator)
- Composite weights: tenant-overridable or fleet-fixed?
- F denominator: enumerated tool surface (8 tools × N entity types) or open-ended `(subject, predicate)` lattice from ontology?
- Fleet weighting: deploy-freq from where? CI metadata not yet ingested.
- "100 repos overall coverage" — one tenant with 100 repos vs 100 tenants? Composite formula differs (per-tenant ontological closure vs cross-tenant fleet stats).
- Should there be a **target curve** per metric (e.g., expected closure(Service, OWNED_BY) for a healthy repo is ≥ 0.9) or only relative ranking?
- Anchor-hit ROI projection assumes extractor lift is independent across frameworks — is that true, or do anchor sets overlap?

## What this rejects

- **Fact count as a coverage metric.** "Facts up 10k → 20k" is a vanity number that ignores tier, citation, and refusal-coverage. Drop.
- **Q&A pass-rate as primary coverage.** Keep as acceptance gate; not a coverage signal.
- **Single global score without knockouts.** Hides ADR-0005 / loud-refusal violations.
- **Arithmetic mean composite.** Lets a strong B drown a zero F. Geomean only.
- **One metric per repo.** Insufficient; need per-`(repo, relation, framework)` cell to drive extractor work.
