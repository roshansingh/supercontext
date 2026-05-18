from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a one-time Claude Code pre-PR review.")
    parser.add_argument("--base", default="main", help="Base branch to diff against.")
    parser.add_argument("--out", help="Output markdown path. Defaults to docs/reviews/PRE-PR-REVIEW-<branch>-<timestamp>.md.")
    parser.add_argument("--model", default="opus", help="Claude model alias or full model name.")
    parser.add_argument("--max-budget-usd", default="5")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args()

    branch = _git_text(["branch", "--show-current"]) or "detached"
    merge_base = _git_text(["merge-base", args.base, "HEAD"])
    diff_stat = _git_text(["diff", "--stat", f"{merge_base}..HEAD"])
    committed_diff = _git_text(["diff", "--find-renames", f"{merge_base}..HEAD"])
    working_tree_stat = _git_text(["diff", "--stat"])
    working_tree_diff = _git_text(["diff", "--find-renames"])
    status = _git_text(["status", "--short", "--branch"])

    prompt = _prompt(
        base=args.base,
        branch=branch,
        status=status,
        diff_stat=diff_stat,
        committed_diff=committed_diff,
        working_tree_stat=working_tree_stat,
        working_tree_diff=working_tree_diff,
    )
    review = _run_claude(prompt, args.model, args.max_budget_usd, args.timeout_seconds)
    output_path = Path(args.out) if args.out else _default_output_path(branch)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(review.rstrip() + "\n", encoding="utf-8")
    print(output_path)


def _prompt(
    *,
    base: str,
    branch: str,
    status: str,
    diff_stat: str,
    committed_diff: str,
    working_tree_stat: str,
    working_tree_diff: str,
) -> str:
    return f"""You are Claude Code reviewing a pull request before it is opened.

Task:
- Review the diff for correctness, maintainability, missing tests, and workflow violations.
- Prioritize real bugs and behavioral regressions over style.
- Do not suggest broad rewrites or speculative architecture.
- Do not edit files. Return markdown only.
- For each finding, include severity, file/path, evidence from the diff, and a concrete fix.
- If no findings, say so and list residual risks.
- Write the review using the required output format below.

Required output format:

# Pre-PR Review — <branch or change title>

**PR:** Pre-PR for `<branch>`
**Diff:** <insert diff stat summary>
**Tests:** <state what evidence is present in the prompt, or "Not verified by reviewer">
**Verdict:** <Approve / Approve with reservations / Request changes>

---

## Summary

<Concise overview of the change and review result.>

## What Works

<Numbered subsections or bullets for good design/test choices.>

## Real Issues

<Findings ordered by severity. Each finding must include severity, file/path, evidence, and concrete fix. If none, say "No blocking findings.">

## Questions / Assumptions

<Only include if needed.>

## Pass Conditions

<Concrete conditions to satisfy before PR creation.>

## Verdict

<Final short verdict.>

Base branch: {base}
Current branch: {branch}

Git status:
```text
{status}
```

Diff stat for committed branch changes:
```text
{diff_stat}
```

Committed branch diff:
```diff
{committed_diff}
```

Uncommitted working-tree diff stat:
```text
{working_tree_stat}
```

Uncommitted working-tree diff:
```diff
{working_tree_diff}
```
"""


def _run_claude(prompt: str, model: str, max_budget_usd: str, timeout_seconds: int) -> str:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model",
                model,
                "--max-budget-usd",
                max_budget_usd,
                "--output-format",
                "text",
            ],
            input=prompt,
            capture_output=True,
            check=True,
            env=env,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Claude Code CLI not found. Install or authenticate `claude` before creating the PR.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Claude pre-PR review failed: {detail}") from exc
    return result.stdout


def _default_output_path(branch: str) -> Path:
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-") or "branch"
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    return Path("docs/reviews") / f"PRE-PR-REVIEW-{safe_branch}-{timestamp}.md"


def _git_text(args: list[str]) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
