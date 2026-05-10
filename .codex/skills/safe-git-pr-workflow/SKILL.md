---
name: safe-git-pr-workflow
description: Use for Git/PR work in this repository, especially staging, committing, pushing, creating PRs, resolving review comments, or recovering from git index/ref lock errors caused by sandboxed .git writes.
---

# Safe Git PR Workflow

Use this skill for Git operations in this repository.

## Failure Patterns To Avoid

- Do not run multiple Git commands in parallel if any command writes `.git`.
- Never parallelize `git add`, `git mv`, `git commit`, `git checkout`, `git fetch`, `git pull`, `git branch`, or `git push`.
- If a Git command fails with `index.lock`, `.git/config`, `FETCH_HEAD`, or remote-ref lock errors, retry the same required operation with escalation instead of changing strategy.
- If `git push` reports that the remote branch updated but local remote-tracking ref update failed, do not push again. Run escalated `git fetch origin <branch>` to refresh local refs.
- Do not delete `.git/index.lock` unless you have checked for an active Git process and the user has approved the destructive cleanup.

## Standard Flow

1. Inspect scope first:

```bash
git status --short --branch
git diff --stat
```

2. Keep unrelated files out of the commit.

If an untracked or modified file is unrelated to the current task, mention it and leave it unstaged.

3. Stage explicitly.

Prefer exact paths over `git add -A` when unrelated files exist.

```bash
git add path/to/file.py path/to/other.md
```

4. Commit with a factual message.

```bash
git commit -m "Short imperative summary"
```

5. Before creating a PR for the first time, run one Claude pre-PR review.

Only do this once per PR, after coding is finished, tests pass, and the local semantic self-review is complete.

```bash
python .codex/scripts/request_claude_pre_pr_review.py --base main
```

Read the generated file under `docs/reviews/`. It must use the same review structure as existing `docs/reviews/PR-*-REVIEW.md` files: metadata, verdict, summary, what works, real issues, pass conditions, and final verdict. For every finding, explicitly decide `accept`, `deny`, or `act`.

- `accept` / `act`: make the fix, add a regression test when behavior changes, rerun checks, and commit.
- `deny`: record the concrete reason in PR notes or review discussion.

Do not create the PR until accepted/actionable Claude findings are handled.

6. Push once.

```bash
git push
```

If push succeeds remotely but local tracking update fails:

```bash
git fetch origin <current-branch>
```

7. Verify final state:

```bash
git status --short --branch
```

8. After every push to a PR branch, poll auto-Copilot review.

Do not manually request Copilot review immediately. Auto-review is configured, but GitHub only reviews new pushes automatically when the `Review new pushes` option is active; otherwise it may review only once.

```bash
python .codex/scripts/poll_copilot_review.py --pr <PR_NUMBER>
```

The poll script waits on the default 6-minute schedule: 2 minutes, 2 minutes, then 1 minute and 1 minute. If no current-head Copilot activity appears after the first 2-minute poll, it requests `@copilot` once as a fallback and continues polling.

For every Copilot thread, explicitly decide `accept`, `deny`, or `act`, reply with that decision, and resolve the thread. If a fix is made, rerun the semantic review checklist, push, and repeat the polling loop.

## PR Review Comments

- Fetch unresolved review threads before editing.
- Patch only the reviewed issue unless the fix requires a small adjacent change.
- Reply with exactly what changed and resolve the thread after pushing.
- Verify all review threads are resolved before final response.

## Escalation Guidance

Use escalation for Git commands that write `.git` when sandbox errors appear, especially:

- `git add`
- `git checkout`
- `git commit`
- `git fetch`
- `git pull`
- `git branch --set-upstream-to`

Do not escalate broad shell scripts for Git recovery. Escalate the narrow Git command that failed.
