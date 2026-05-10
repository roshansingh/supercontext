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

5. Push once.

```bash
git push
```

If push succeeds remotely but local tracking update fails:

```bash
git fetch origin <current-branch>
```

6. Verify final state:

```bash
git status --short --branch
```

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
