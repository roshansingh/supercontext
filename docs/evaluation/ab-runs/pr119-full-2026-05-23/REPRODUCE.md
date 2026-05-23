# Reproduce pr119-full-2026-05-23

Report:

- Markdown: `docs/evaluation/ab-runs/pr119-full-2026-05-23/ab-report.md`
- Analysis: `docs/evaluation/ab-runs/pr119-full-2026-05-23/trace-analysis.md`
- JSON: `docs/evaluation/ab-runs/pr119-full-2026-05-23/ab-report.json`

Expected result:

- 18 paired tasks / 36 host runs
- `mcp_on=11`, `mcp_off=4`, `tie=3`
- correctness: `mcp_on=11`, `mcp_off=4`, `tie=3`
- evidence: `mcp_on=13`, `mcp_off=3`, `tie=2`
- MCP denials/errors: `0`

## Pull Existing LangSmith Runs

Requires access to LangSmith project `supercontext-ab-eval`.
This section contains private LangSmith run-group IDs for the current private repo.
Redact or remove it before publishing the repository publicly.

```bash
RUN_GROUP_IDS="213f622c-00fb-4e85-a07a-53ef10f1f251,3d55878c-77ad-4c27-8853-f4fd44fa6ff6,88e27d7a-4dff-460b-981f-64c116c1c37a,59f1569f-bfb3-407b-b3b2-d005ddba41eb,14923c69-ed1b-4fff-a1e2-12ff47197f77,43568c39-3535-46a6-99e2-3ab0159887d9,3c6264df-eb11-4f8b-a3a7-b9982a31d941,e458ae8d-12ef-4310-ab0f-86ff2cc23dce,bfcd16d0-355e-4076-8758-953c773ff478,20f1df23-8220-46b8-ba58-4367f156b369,8811b846-7494-459b-ae66-baab78abf530,83bec78f-18a1-42d6-b6c7-fd18c8c87529,1f7216de-4da5-48dc-a397-b7f28f2b1961,0b89cd77-378e-4686-9393-e34f12dc7414,e25c57c0-3d95-413f-a797-49a01e20512d,b57023be-5338-4da8-b956-42e57a5518e6"

set -a; source .env; set +a
.venv/bin/python -m source.scripts.pull_ab_traces \
  --project "$LANGSMITH_PROJECT" \
  --run-group-ids "$RUN_GROUP_IDS" \
  --limit 100 \
  --out data/ab_runs/pr119-full-2026-05-23/traces.jsonl
```

Then run the delta/judge/report commands from `docs/evaluation/AB_REPRODUCTION.md` with:

- run id: `pr119-full-2026-05-23`
- seed: `119`
- judge model: `gpt-4.1-mini`

## Rerun From Scratch

Use the same private 23-repo KG snapshot used for the checked-in report, or rebuild an equivalent snapshot first. Then run `default-v1` with seed `119` using the commands in `docs/evaluation/AB_REPRODUCTION.md`.

If a long run is interrupted, rerun only missing task IDs into another `data/ab_runs/<run-id>-cont/` directory, then combine exactly one `mcp_on` and one `mcp_off` row per task before computing deltas.
