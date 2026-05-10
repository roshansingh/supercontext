# Next Gap Analysis After PR17

Date: 2026-05-10

## Current Readout

PR17 changes the product-validation picture. The earlier full goldset judgement still shows Q088 and Q106 as partial, but the event-focused judgement generated after the event-evidence work shows Q088, Q095, and Q106 as Pass. Combined with the already passing Q082, Q083, and Q100, the current evidence says the KG + EvidencePacket + thin synthesis layer can answer the selected LatticeAI goldset scenarios when the right facts are present.

This is a real product signal, but it is still narrow: one private multi-repo corpus, a small goldset, and some hand-authored scenario plans.

## Evidence Summary

| Area | Status | Evidence |
|---|---|---|
| Single-repo low/medium surfaces | Healthy | Mercury ML and True Loop smoke surfaces pass on symbol, import, caller/callee, and dependency-path queries. |
| Cross-repo HTTP/API scenarios | Healthy | Q082, Q083, and Q100 judged Pass in the full LatticeAI goldset. |
| Cross-repo event scenarios | Improved to Pass | Q088 and Q106 judged Pass in the event-focused rerun after producer/consumer extraction. |
| Answer synthesis | Not the current blocker | Failures were caused by missing/under-retrieved evidence; when packets are complete, answers are useful and cited. |
| Evaluation hygiene | Weak | Full goldset and event-focused docs disagree because they were generated at different moments. |

## Ranked Gaps

| Rank | Gap | Why It Matters | Recommended Scope |
|---:|---|---|---|
| 1 | Consolidated evaluation harness/report | Contradictory judgement artifacts make product progress hard to trust. | One command should build/run low, medium, and goldset checks and emit one canonical summary. |
| 2 | Broader multi-repo validation corpus | LatticeAI is strong evidence but still one org. | Add one OSS multi-repo corpus with 10-15 gold questions and ground truth. |
| 3 | Source-level config/env citations | Current answers sometimes cite resolved values but not the exact settings/env consumer line. | Emit evidence for JS/TS `process.env.*`, `import.meta.env.*`, Python settings constants, and config-object resolved source locations. |
| 4 | Scenario-plan generality | Scenario plans still contain private goldset logic in product source. | Move private scenario plans out of `source/` before OSS publication; keep generic retrieval primitives in product code. |
| 5 | Contract drift answer enrichment | Q100 passes but could better surface service-locality drift and code-only endpoints. | Improve answer shaping using existing endpoint reconciliation facts before adding new extraction. |

## Recommended Next PR

Do not add another broad extractor yet. The next focused PR should be an evaluation-quality PR:

1. Add a consolidated product-validation runner that executes the supported low/medium smoke checks plus selected goldset scenarios.
2. Produce one canonical markdown report with scenario status, evidence completeness, answer status, and failure owner.
3. Mark stale/partial artifacts as superseded or move them under an archive path to avoid conflicting readouts.
4. Keep the runner generic; LatticeAI-specific questions remain test input, not product logic.

## Next Feature After That

After the evaluation harness is reliable, the highest-value product feature is generic config/env source citation:

- JS/TS env usage: `process.env.NAME`, `import.meta.env.NAME`.
- Python settings/config constants: resolved constant source file and line.
- ConfigParser object bridge: expose the original `.ini` file and option line in evidence, not only the resolved value.

This should improve Q082 and event answers naturally without hardcoded repo names, queue names, domains, or scenario IDs.

