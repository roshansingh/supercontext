---
name: implement-debate
description: Use when the user asks Codex to implement a specific converged agent debate, apply a debate plan, or finish a debate end-to-end across one or more PRs in this repository. Orchestrates debate readiness checks, scoped implementation, semantic self-review, Claude pre-PR review, Copilot review loops, merge-to-main, and follow-up PR sequencing.
---

# Implement Debate

Implement a converged debate as a sequence of small PRs until the debate plan is complete. This skill composes the repo-local `safe-git-pr-workflow` and `pre-pr-semantic-review` skills; load those skills when this skill is used.

## Start Conditions

1. Resolve the debate file.
   - If the user names a number, use `debates/N-*.md`.
   - If the user says "implement it" without a number, use the latest converged debate only if unambiguous; otherwise ask which debate.
2. Read `~/.codex/agent-debate/agent-guardrails.md` and the debate file.
3. Verify readiness before coding:
   - Debate has `STATUS: CONVERGED`.
   - Dispute Log has no `OPEN` rows.
   - If a `## Plan` exists, it has `PLAN_STATUS: CONVERGED`.
4. If the plan is not converged, run the plan phase first:

```bash
./orchestrate.sh --resume "<debate-file>" --plan
```

Stop and report if the debate still is not converged after the plan phase.

## PR Slicing

1. Identify the next unimplemented PR slice from the debate plan. Prefer explicit headings like `PR-1`, `PR 2`, `Step 1`, or a checklist under `## Plan`.
2. If the debate is not split into PRs, make one smallest coherent PR.
3. Keep each PR scoped to one reviewable behavior change. Do not mix unrelated cleanup, evaluation docs, or generated artifacts unless required by that PR slice.
4. Start every PR slice from latest `main`:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b <short-debate-pr-branch>
```

If unrelated local files exist, leave them unstaged and name them in status updates.

## Per-PR Implementation Loop

For each PR slice:

1. Implement the planned change surgically.
2. Add focused regression tests for behavior changes. For extractor, normalization, query, loader, validation, or review-fix changes, use the `pre-pr-semantic-review` checklist before push.
3. Run focused tests, then wider checks appropriate to the change. If product value or validation movement is involved, use `product-evaluation`.
4. Run self-review:

```bash
git diff --stat
git diff --check
python3 -m compileall -q source
python3 -m unittest discover -s tests
```

If the full suite has known unrelated failures, record exact failures and keep focused tests green.

5. Run the first Claude pre-PR review before creating the PR:

```bash
python3 .codex/scripts/request_claude_pre_pr_review.py --base main
```

Read the generated review under `docs/reviews/`. For every Claude finding, explicitly decide `accept`, `deny`, or `act`.

- `accept` or `act`: implement the fix, add a regression test when behavior changes, and rerun checks.
- `deny`: document the concrete evidence in PR notes.

Do not run Claude again before the first Copilot review. Stop and report if the helper is missing, unauthenticated, or cannot write the review file.

6. Commit only the intended files. Keep generated validation noise and unrelated user files out of the commit.
7. Push the branch and create/update the PR.

## Copilot Review Loop

After every push to the PR branch:

1. Request and poll Copilot using the project script:

```bash
python3 .codex/scripts/poll_copilot_review.py --pr <PR_NUMBER>
```

2. If Copilot produces review threads or issue comments, fetch them, verify each claim against code, and decide `accept`, `deny`, or `act`.
3. Reply to every Copilot thread with the decision and evidence or fix summary, then resolve the thread.
4. After implementing changes from the first Copilot feedback batch, before pushing those changes, run Claude Code exactly one more time:

```bash
python3 .codex/scripts/request_claude_pre_pr_review.py --base main
```

This is the second and final Claude review for the PR. For each finding, decide `accept`, `deny`, or `act`; implement accepted/actionable findings with tests when behavior changes. Do not run Claude again for later Copilot batches unless the user explicitly asks.

5. If any code or doc change is made, rerun the relevant checks and push again.
6. Repeat Copilot review until a requested current-head Copilot review completes with zero actionable feedback.

Do not merge if Copilot review activity never appears, review activity times out before completion, required checks fail, or unresolved review threads remain. Report the blocker instead.

## Merge And Continue

When the PR has:

- focused checks passing,
- known unrelated full-suite failures documented if present,
- Claude findings handled,
- current-head Copilot review completed with zero actionable feedback,
- required GitHub checks passing or no required checks configured,

merge it to `main` using the repo's normal merge-commit flow:

```bash
gh pr merge <PR_NUMBER> --merge --delete-branch
git checkout main
git pull --ff-only origin main
```

Then update the debate file with an `## Implementation Results` entry for that PR:

- PR number and branch
- files changed
- commands/tests run
- evaluation movement, if applicable
- deviations from the debate plan

If the debate has more PR slices, start the next slice from the updated `main` and repeat the full loop. Finish only when every debate PR slice is implemented, reviewed, merged, and recorded.

## Stop Conditions

Stop and report clearly when:

- debate readiness is not converged,
- the next PR slice is ambiguous,
- local unrelated changes block checkout or merge,
- Claude review helper is missing or unauthenticated,
- Copilot does not complete a current-head review,
- required checks fail for reasons outside the current slice,
- implementation reveals that the converged plan is technically wrong.
