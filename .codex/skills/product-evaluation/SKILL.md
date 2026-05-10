---
name: product-evaluation
description: Use when evaluating product value, running low/medium/goldset validation, interpreting canonical validation reports, deciding the next highest-value KG/product gap, or before proposing the next validation-driven feature in this repository.
---

# Product Evaluation

Use this skill whenever the task is about product validation, evaluation reports, goldset results, answer quality, or choosing the next feature from evidence.

## Core Principle

Evaluate before adding features. The goal is to prove whether the KG plus evidence packet plus answer layer gives correct, useful, cited answers that are better than raw agentic repo search. Speed and cost matter only after answer quality is good enough.

## Standard Workflow

1. Run or inspect the canonical report first.

```bash
python -m source.scripts.run_product_validation
```

If the task is a focused regression, run the smallest relevant scenario or query surface as well.

2. Separate evaluation layers.

- Deterministic smoke checks validate query surfaces and basic KG regressions.
- Evidence packets validate whether KG retrieval gathered the right facts.
- Answer synthesis validates whether the model used the packet correctly.
- Goldset judgement validates final answer quality against independent ground truth.

3. Classify every failure.

Use these buckets:

- `missing KG fact`: extractor/linker did not create the needed entity/fact/evidence.
- `bad retrieval plan`: fact exists but the scenario did not retrieve it.
- `bad synthesis`: packet was sufficient but the answer was wrong, noisy, or overconfident.
- `bad ground truth`: expected answer is stale, wrong, incomplete, or not mechanically judgeable.
- `coverage gap`: system correctly refuses or stays partial because source/language/runtime scope is uninstrumented.

4. Pick the next highest-value gap.

Prefer repeated patterns across goldset partial/fail cases over one-off failures. A next PR is high-value when it converts multiple partial/fail scenarios into pass or strengthens a core product claim such as cross-repo impact, event lineage, deploy impact, or contract drift.

5. State the recommended next PR narrowly.

Define:

- exact capability to add or fix
- affected query IDs/scenarios
- expected movement in evaluation
- verification command/report to rerun
- why it is generic and not fixture-specific

## Decision Rules

- If evidence packet is missing ground-truth facts, improve extraction/linking or retrieval planning before touching synthesis.
- If packet has all required facts but answer is weak, improve answer aggregation/synthesis.
- If deterministic smoke fails, fix query/KG regression before interpreting goldset.
- If judgement is missing for an answer-only scenario, add/repair ground truth before using it as product evidence.
- If the proposed fix relies on repo names, variable names, product domains, or keyword lists specific to one fixture, reject it unless it is explicitly isolated as private fixture configuration.

## What Not To Do

- Do not add brittle repo-specific keyword extraction to make one goldset pass.
- Do not trust answer self-score over independent judgement.
- Do not treat a faster answer as product validation if quality is partial or unjudged.
- Do not broaden extraction scope without showing which evaluated failures it should move.
- Do not overwrite historical evaluation docs manually; regenerate canonical output or write a short gap-analysis doc when needed.

## Expected Output

For evaluation interpretation, answer with:

- current validation status
- strongest product-value signal
- weakest blocking gap
- next recommended PR
- exact report/commands that should validate movement
