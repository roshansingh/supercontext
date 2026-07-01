# Review Context Lead Gate

Date: 2026-07-01

## Purpose

This note records the focused PR-review packet change that adds a compact usage gate to `review_context`.

The product problem is cost and routing, not KG rebuild quality: after repo-scope resolution, some PR-review packets have useful symbol-anchor, changed-symbol, or impact evidence, while low-coverage packets still should not consume reviewer attention as broad context.

## Change

`review_context` now emits:

- `review_lead_status`: a compact usage gate with `coverage_status`, `recommended_action`, changed-anchor counts, impact-edge counts, and source-coordinate counts.
- `review_leads`: a small top-level lead packet rooted in changed files/ranges, including changed symbols, direct callers/callees, transitive callers, and source coordinates.

For low-coverage `diff_anchor_only` packets, broad app/runtime/framework sections are omitted by default. The packet recommends direct source review and keeps coordinates/gaps instead of returning broader context.

Relevant implementation and tests:

- [source/kg/product/mcp_tools.py](../../source/kg/product/mcp_tools.py)
- [tests/test_mcp_tools.py](../../tests/test_mcp_tools.py)

## Focused Evidence

Fixture: one changed config file with no changed symbols or direct impact edges.

Baseline on current `main` before this change:

```text
packet chars: 13,852
review_lead_status present: false
application_impact present: true
runtime_surfaces present: true
review_answer_packet.application present: true
review_answer_packet.runtime present: true
```

After this change:

```text
packet chars: 7,707
review_lead_status.coverage_status: low_coverage
review_lead_status.recommended_action: fall_back_to_plain_review
application_impact present: false
runtime_surfaces present: false
review_answer_packet.application present: false
review_answer_packet.runtime present: false
```

This is a 44% reduction for the low-coverage fixture and removes broad app/runtime expansions from the default low-coverage packet.

Fixture: one changed symbol with direct caller and callee evidence.

Baseline before this change:

```text
packet chars: 28,575
review_lead_status present: false
changed_symbol_count: 1
direct_caller_count: 1
direct_callee_count: 1
```

After this change:

```text
packet chars: 31,152
review_lead_status.coverage_status: useful
review_lead_status.recommended_action: use_supercontext_packet
review_lead_status.changed_symbol_count: 1
review_lead_status.direct_impact_count: 2
review_leads.changed_symbols[0]: handle_checkout
review_leads.direct_callers[0]: payments.api.submit_checkout
review_leads.direct_callees[0]: payments.gateway.charge_card
```

The anchored packet grows modestly because it now carries a dedicated lead/gate section, but it exposes the exact compact routing signal needed by the PR-review harness.

## Interpretation

This PR is diagnostic and cost-control work. It is not expected to create a large recall jump by itself.

Expected validation outcome:

```text
low-coverage cases should fall back to plain review and stop paying for broad context
useful-coverage cases should expose symbol-anchor, changed-symbol, and caller/callee leads directly
quality movement should be measured by lead -> reviewer finding -> verifier accepted -> canonical matched
```

If compact useful-coverage packets improve review quality, the next investment should expand anchor coverage with targeted language fallback parsers. If this only reduces cost, the next investment should be contract edges plus ranked risk hypotheses.
