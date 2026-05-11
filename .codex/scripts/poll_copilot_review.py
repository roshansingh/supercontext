from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


COPILOT_LOGINS = {"copilot", "copilot-pull-request-reviewer"}
DEFAULT_POLL_DELAYS_SECONDS = (120, 120, 60, 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Request and poll a PR for Copilot review feedback.")
    parser.add_argument("--pr", type=int, help="Pull request number. Defaults to the current branch PR.")
    parser.add_argument("--repo", help="owner/name. Defaults to `gh repo view`.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        help="Use a fixed polling interval instead of the default 2m, 2m, 1m, 1m schedule.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=sum(DEFAULT_POLL_DELAYS_SECONDS),
        help="Maximum polling window. Defaults to 6 minutes.",
    )
    parser.add_argument(
        "--skip-request",
        action="store_true",
        help="Only poll; do not request @copilot first. Use only when verifying an already-requested review.",
    )
    args = parser.parse_args()

    repo = args.repo or _gh_text(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    pr_number = args.pr or int(_gh_text(["pr", "view", "--json", "number", "--jq", ".number"]))

    head_sha = _gh_text(["pr", "view", str(pr_number), "--json", "headRefOid", "--jq", ".headRefOid"])
    head_pushed_at = _head_commit_pushed_at(repo, head_sha)
    poll_delays = _poll_delays(args.interval_seconds, args.timeout_seconds)
    if not args.skip_request:
        if _request_copilot_review(repo, pr_number):
            print(f"Requested @copilot review for PR #{pr_number} at head {head_sha[:12]}.")
        else:
            print(f"Attempted @copilot review request for PR #{pr_number}; continuing to poll current head.")
    started_at = time.monotonic()
    attempt = 1
    while True:
        result = _poll_once(repo, pr_number, head_sha, head_pushed_at)
        _print_summary(result, attempt, repo, pr_number, head_sha)
        if result["actionable_feedback"]:
            return
        if result["review_completed"]:
            print("Copilot review completed for the current head with no actionable feedback.")
            return
        if attempt > len(poll_delays):
            if result["activity"]:
                print("Copilot activity appeared, but no completed review or actionable feedback arrived in time.")
            else:
                print(
                    "No current-head Copilot activity appeared within the polling window after requesting review. "
                    "Stop here unless the user manually requests Copilot in the UI and asks to poll again."
                )
            return
        sleep_seconds = poll_delays[attempt - 1]
        time.sleep(sleep_seconds)
        attempt += 1


def _poll_once(repo: str, pr_number: int, head_sha: str, head_pushed_at: str) -> dict[str, Any]:
    reviews = _gh_json(["api", f"repos/{repo}/pulls/{pr_number}/reviews"])
    issue_comments = _gh_json(["api", f"repos/{repo}/issues/{pr_number}/comments"])
    events = _gh_json(["api", f"repos/{repo}/issues/{pr_number}/events"])
    unresolved_threads = _unresolved_copilot_threads(repo, pr_number)

    copilot_reviews = [
        review
        for review in reviews
        if _is_copilot_user(review.get("user")) and review.get("commit_id") == head_sha
    ]
    copilot_issue = [
        comment
        for comment in issue_comments
        if _is_copilot_user(comment.get("user")) and str(comment.get("created_at", "")) >= head_pushed_at
    ]
    copilot_events = [
        event
        for event in events
        if str(event.get("created_at", "")) >= head_pushed_at
        and (event.get("event") == "copilot_work_started" or _is_copilot_user(event.get("requested_reviewer")))
    ]
    return {
        "activity": bool(copilot_events or copilot_reviews or unresolved_threads or copilot_issue),
        "review_completed": bool(copilot_reviews),
        "actionable_feedback": bool(unresolved_threads or copilot_issue),
        "reviews": copilot_reviews,
        "threads": unresolved_threads,
        "issue_comments": copilot_issue,
        "events": copilot_events,
    }


def _poll_delays(interval_seconds: int | None, timeout_seconds: int) -> list[int]:
    if timeout_seconds <= 0:
        return []
    if interval_seconds is not None:
        delay = max(1, interval_seconds)
        delays = []
        remaining = timeout_seconds
        while remaining > 0:
            next_delay = min(delay, remaining)
            delays.append(next_delay)
            remaining -= next_delay
        return delays

    delays: list[int] = []
    elapsed = 0
    for delay in DEFAULT_POLL_DELAYS_SECONDS:
        if elapsed >= timeout_seconds:
            break
        next_delay = min(delay, timeout_seconds - elapsed)
        delays.append(next_delay)
        elapsed += next_delay
    return delays


def _print_summary(result: dict[str, Any], attempt: int, repo: str, pr_number: int, head_sha: str) -> None:
    print(f"Poll {attempt}: {repo} PR #{pr_number} @ {head_sha[:12]}")
    print(f"Copilot activity: {'yes' if result['activity'] else 'no'}")
    print(f"Copilot current-head review completed: {'yes' if result['review_completed'] else 'no'}")
    print(
        "Copilot actionable feedback: "
        f"{len(result['threads'])} unresolved threads, "
        f"{len(result['issue_comments'])} issue comments"
    )
    print(f"Copilot reviews on current head: {len(result['reviews'])}")
    for thread in result["threads"]:
        comment = thread["comments"][0]
        print(f"- unresolved: {thread.get('path')} {comment.get('url')}")
        body = str(comment.get("body", "")).strip().replace("\n", " ")
        print(f"  {body[:240]}")
    for review in result["reviews"]:
        state = review.get("state", "UNKNOWN")
        submitted_at = review.get("submitted_at", "")
        print(f"- review: {state} {submitted_at}")


def _is_copilot_user(user: Any) -> bool:
    if not isinstance(user, dict):
        return False
    login = str(user.get("login", "")).casefold()
    return login in COPILOT_LOGINS or "copilot" in login


def _head_commit_pushed_at(repo: str, head_sha: str) -> str:
    owner, name = repo.split("/", 1)
    query = """
    query($owner:String!, $name:String!, $oid:GitObjectID!) {
      repository(owner:$owner, name:$name) {
        object(oid:$oid) {
          ... on Commit {
            pushedDate
            committedDate
          }
        }
      }
    }
    """
    payload = _gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-f",
            f"oid={head_sha}",
            "-f",
            f"query={query}",
        ]
    )
    commit = payload.get("data", {}).get("repository", {}).get("object") or {}
    pushed_at = commit.get("pushedDate")
    committed_at = commit.get("committedDate")
    if not pushed_at and not committed_at:
        raise RuntimeError(f"Could not resolve pushedDate or committedDate for head commit {head_sha}")
    return str(pushed_at or committed_at)


def _request_copilot_review(repo: str, pr_number: int) -> bool:
    reviewer_logins = ("copilot-pull-request-reviewer", "copilot")
    for reviewer in reviewer_logins:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{repo}/pulls/{pr_number}/requested_reviewers",
                    "-f",
                    f"reviewers[]={reviewer}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            print(f"Timed out requesting Copilot review as {reviewer}.", file=sys.stderr)
            continue
        if result.returncode == 0:
            return True
        message = (result.stderr or result.stdout or "").strip()
        if "Review cannot be requested" in message or "already requested" in message.lower():
            return True
        if message:
            print(message, file=sys.stderr)
    return False


def _unresolved_copilot_threads(repo: str, pr_number: int) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    query = """
    query($owner:String!, $name:String!, $number:Int!) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first:100) {
            nodes {
              id
              isResolved
              path
              comments(first:20) {
                nodes {
                  databaseId
                  author { login }
                  body
                  url
                }
              }
            }
          }
        }
      }
    }
    """
    payload = _gh_json(
        [
            "api",
            "graphql",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={pr_number}",
            "-f",
            f"query={query}",
        ]
    )
    nodes = payload["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    unresolved = []
    for node in nodes:
        if node.get("isResolved"):
            continue
        comments = node.get("comments", {}).get("nodes", [])
        copilot_comments = [comment for comment in comments if _is_copilot_user(comment.get("author"))]
        if copilot_comments:
            unresolved.append({"id": node.get("id"), "path": node.get("path"), "comments": copilot_comments})
    return unresolved


def _gh_text(args: list[str]) -> str:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _gh_json(args: list[str]) -> Any:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout or "[]")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
