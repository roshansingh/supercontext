# Codex KG Coverage Metrics

Status: proposal

Purpose: define coverage metrics for the repository knowledge graph that do not depend on a fixed Q&A set. Q&A validation is still useful, but it should not be the primary way to decide whether the KG understands a repo or an org.

## Problem

Question-answer evaluation is incomplete by design. It measures whether the system can answer the questions we imagined, not whether the KG has broad, useful, and trustworthy coverage across arbitrary repositories.

For public OSS use, we need repo-level and org-level coverage signals that answer:

- Which repos are indexed well?
- Which languages and source surfaces are under-covered?
- Which extractors create useful KG facts?
- Which gaps are explicitly known versus silently missed?
- Did a new extractor improve real graph understanding, or just add low-value rows?

The goal is not one big vanity number. The goal is a coverage dashboard that helps choose the next extractor, normalizer, or linker based on measurable gaps.

## Useful Prior Art

Data-quality programs commonly separate dimensions such as accuracy, completeness, consistency, timeliness, validity, and uniqueness. That maps well to KG quality because more facts are not automatically better facts. Source: IBM, "What Are Data Quality Dimensions?" https://www.ibm.com/think/topics/data-quality-dimensions

OpenTelemetry's demo reports trace coverage by service and capability, not only as one global score. That matrix shape is useful for multi-repo KG coverage: repo by repo, capability by capability. Source: OpenTelemetry trace coverage by service https://opentelemetry.io/docs/demo/telemetry-features/trace-coverage/

Sourcegraph separates precise code navigation from search fallback and tracks index availability by repo/language/indexer. That supports measuring semantic KG coverage by indexed capability, not by whether fallback search happened to find something. Source: Sourcegraph precise code navigation docs https://sourcegraph.com/docs/code-navigation/precise-code-navigation

## Principles

Measure opportunities, not just facts.

Bad metric:

```text
facts increased from 10k to 20k
```

Better metric:

```text
detected 500 HTTP call-site opportunities
320 became CALLS_ENDPOINT facts
120 emitted unresolved_host coverage rows
60 emitted unresolved_target coverage rows
0 were silently ignored
```

Coverage should reward both extraction and honest refusal. A repo with low fact coverage but clear coverage rows is safer than a repo with low fact coverage and no explanation.

## Proposed Scorecard

Track these dimensions per repo, then roll them up across an org.

| Metric | What It Measures | Why It Matters |
|---|---|---|
| Repo inventory coverage | Indexed repos / expected repos | Tells whether the org snapshot is complete. |
| Freshness coverage | Repos indexed at current or acceptable commit age / indexed repos | Prevents answering from stale graph state. |
| Language parser coverage | Parsed source files / source files, grouped by language | Shows whether the basic syntax layer works. |
| Extractor opportunity coverage | Extracted facts / detected opportunities, grouped by predicate | Measures true extractor reach. |
| Evidence grounding coverage | Facts with valid `bytes_ref` / source-backed facts | Ensures claims can be cited and verified. |
| Unsupported scope coverage | Unsupported detected stacks with coverage rows / unsupported detected stacks | Rewards explicit refusal over silent gaps. |
| Unresolved rate | Unresolved opportunities / detected opportunities, grouped by reason | Shows where extractors fail closed. |
| Useful edge coverage | Services with at least one product-useful edge / discovered services | Avoids inflating coverage with low-value facts. |
| Cross-repo linkage coverage | Resolved package-to-repo links / resolvable package imports | Measures multi-repo impact readiness. |
| Trust mix | Facts by derivation class and canonical status | Prevents candidate or inferred facts from hiding weak coverage. |

## Core Formulas

### Repo Inventory Coverage

```text
indexed_repos / expected_repos
```

For OSS, `expected_repos` may be the repos explicitly passed to `build_multi_kg`. For hosted use, it should come from the connected source provider.

### Language Parser Coverage

```text
parsed_files(language) / source_files(language)
```

Parse failures should produce coverage rows with reason, path, language, and source system.

### Extractor Opportunity Coverage

```text
facts_emitted(predicate) / opportunities_detected(predicate)
```

Examples:

- `EXPOSES_ENDPOINT` facts / route declarations detected
- `CALLS_ENDPOINT` facts / HTTP client call sites detected
- `REFERENCES_EVENT_CHANNEL` facts / event-channel string or config references detected
- `IMPORTS` facts / import statements detected
- `DEPLOYS_VIA_CONFIG` facts / deploy config targets detected

This is the most important KG-growth metric because it says whether an extractor converts source opportunities into graph facts.

### Evidence Grounding Coverage

```text
facts_with_bytes_ref / source_backed_facts
```

A valid `bytes_ref` should include:

```text
repo
commit_sha
path
line_start
line_end
```

### Silent Gap Rate

```text
opportunities_without_fact_or_coverage / opportunities_detected
```

This should trend toward zero. It is one of the best safety metrics because silent misses create false confidence.

### Useful Edge Coverage

```text
services_with_useful_edges / discovered_services
```

Useful edges are product-relevant relations such as:

```text
EXPOSES_ENDPOINT
CALLS_ENDPOINT
DOCUMENTS_ENDPOINT
PRODUCES_EVENT
CONSUMES_EVENT
REFERENCES_EVENT_CHANNEL
DEPLOYS_VIA_CONFIG
ROUTES_DOMAIN_TO_DEPLOY
IMPORTS
DEPENDS_ON
RESOLVES_TO_REPO
RESOLVES_TO_SERVICE
```

The exact predicate set should be maintained as a source-of-truth allowlist, not duplicated in ad hoc reporting code.

### Cross-Repo Linkage Coverage

```text
resolved_package_links / resolvable_package_imports
```

This measures whether external package facts are connected to other indexed repos or services when package metadata allows a unique match.

## Org-Level Report Shape

For many repos, use a matrix instead of one score.

```text
Repo        Parse  Imports  Symbols  Endpoints  Events  Deploy  Evidence  Freshness
api         98%    96%      81%      72%        64%     90%     99%       fresh
web         99%    94%      76%      68%        n/a     40%     98%       fresh
worker      95%    91%      70%      n/a        82%     55%     97%       stale
```

Then add an org rollup:

```text
100 repos expected
94 indexed
81 fresh
72 have service identity
58 have endpoint/event/deploy coverage
23 have unsupported stack warnings
12 are high-risk: important repos with low extractor coverage
```

## Preventing Useless Coverage Growth

Coverage should not increase just because the graph has more rows. A change should be considered valuable when it improves one or more of these:

- More detected opportunities become canonical facts.
- More unsupported opportunities become explicit coverage rows.
- Silent gap rate decreases.
- Useful edge coverage increases.
- Cross-repo linkage increases.
- Evidence grounding coverage stays high.
- Trust mix does not degrade toward low-confidence candidate facts.

Examples of weak or misleading improvements:

- Adding many low-value string facts that do not support product queries.
- Extracting duplicate facts from multiple broad scanners.
- Converting unresolved cases into guessed canonical facts.
- Improving one private fixture through repo-name or product-domain heuristics.
- Increasing fact count while evidence coverage drops.

## How To Use These Metrics

Before adding an extractor:

1. Measure current opportunities, facts, coverage rows, unresolved rows, and silent gaps for the target predicate.
2. Add the extractor or normalizer.
3. Rebuild the same snapshots.
4. Compare scorecard deltas.
5. Accept the change only if it improves useful edge coverage, opportunity coverage, or explicit coverage without increasing false positives.

For example:

```text
Before:
Detected HTTP client call sites: 500
CALLS_ENDPOINT facts: 210
Coverage rows: 170
Silent gaps: 120

After:
Detected HTTP client call sites: 500
CALLS_ENDPOINT facts: 330
Coverage rows: 160
Silent gaps: 10
```

This is a real coverage improvement. It created more graph facts and made the remaining gaps explicit.

## First Implementation Slice

A pragmatic first report can be built from existing JSONL snapshots:

- Count repos from `manifest.json` or multi-repo build inputs.
- Count source files by language from repo discovery.
- Count entities and facts by kind/predicate.
- Count evidence rows with valid `bytes_ref`.
- Count coverage rows by `predicate`, `state`, `source_system`, and `scope_ref.reason`.
- Count orphan services with no useful edges.
- Count facts without evidence.
- Count stale snapshots by comparing indexed commit or build time to a configured freshness threshold.

The first version does not need to prove every opportunity denominator. It can start with predicates where opportunities are already detected, such as imports, parser failures, route declarations, HTTP call sites, event references, and config scans.

## Open Questions

- What is the source of truth for `expected_repos` in OSS versus hosted mode?
- Which predicates count as product-useful edges for the first scorecard?
- Which opportunity detectors are cheap and generic enough to run before full extraction?
- Should coverage be weighted by repo importance, such as production service versus test fixture?
- Should freshness be measured by commit age, branch divergence, or both?
- How should private ignored/deferred scopes be represented so they do not look like failures?

