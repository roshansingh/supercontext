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

5. Before creating a PR for the first time, run the first automated Claude pre-PR review.

Do this after coding is finished, tests pass, and the local semantic self-review is complete.

Run the project helper yourself:

```bash
python3 .codex/scripts/request_claude_pre_pr_review.py --base main
```

The helper invokes Claude Code CLI in non-interactive review mode, includes the branch diff against `main`, includes any uncommitted working-tree diff, tells Claude not to edit files, and writes the markdown review under `docs/reviews/`. If the helper reports that `claude` is missing or unauthenticated, stop and report that blocker instead of creating the PR.

When invoking Claude directly with `claude -p`, unset Anthropic API key environment variables in that command so Claude uses the locally authenticated Claude Code session:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN claude -p "<prompt>"
```

Read the generated review file. It must follow the helper's embedded format: metadata, verdict, summary, what works, real issues, questions or assumptions, pass conditions, and final verdict. For every finding, explicitly decide `accept`, `deny`, or `act`.

- `accept` / `act`: make the fix, add a regression test when behavior changes, rerun checks, and commit.
- `deny`: record the concrete reason in PR notes or review discussion.

Do not create the PR until accepted/actionable Claude findings are handled.

Do not run Claude again before the first Copilot review. Each PR gets at most two Claude reviews unless the user explicitly asks otherwise.

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

8. After every push to a PR branch, request and verify Copilot review state.

Reality to account for: Copilot auto-reviews the first PR push, but follow-up pushes usually do not auto-review. After every follow-up push, explicitly request Copilot review from the CLI, then poll.

The reliable documented request path is:

```bash
gh pr edit <PR_NUMBER> --add-reviewer @copilot
```

The poll script uses that first. If GitHub refuses the reviewer request, the script posts a PR comment fallback:

```text
@copilot please review the latest changes on this PR head (<sha>).
```

Treat the comment fallback as experimental because GitHub documents reviewer requests, not PR comments, as the official Copilot code-review trigger.

```bash
python .codex/scripts/poll_copilot_review.py --pr <PR_NUMBER>
```

The poll script requests `@copilot` first, then waits on the default 8-minute schedule: 3 minutes, 2 minutes, then 1 minute, 1 minute, and 1 minute. Use `--skip-request` only when the user has already manually requested Copilot for the current head and asks you to poll. Use `--no-comment-fallback` only when comment noise is unacceptable.

Interpret the result precisely:
- If a current-head Copilot review completes with zero unresolved threads or issue comments, the review step is done.
- If current-head Copilot activity starts but no completed review appears within 8 minutes, stop and report that review activity did not finish in time.
- If no current-head Copilot activity appears within 8 minutes after the CLI request, stop and report that the request produced no review activity.

For every Copilot thread, explicitly decide `accept`, `deny`, or `act`, reply with that decision, and resolve the thread.

After implementing changes from the first Copilot review batch, before pushing those changes, run Claude Code exactly one more time:

```bash
python3 .codex/scripts/request_claude_pre_pr_review.py --base main
```

This is the second and final Claude review for the PR. For each finding, decide `accept`, `deny`, or `act`. Implement accepted/actionable findings with tests when behavior changes, but do not run Claude again unless the user explicitly asks.

If a fix is made, rerun the semantic review checklist, push, request Copilot again, and repeat until a requested current-head review completes with zero actionable feedback.

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
