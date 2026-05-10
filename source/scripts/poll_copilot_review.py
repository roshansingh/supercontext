from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


COPILOT_LOGINS = {"copilot", "copilot-pull-request-reviewer"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll a PR for Copilot auto-review feedback.")
    parser.add_argument("--pr", type=int, help="Pull request number. Defaults to the current branch PR.")
    parser.add_argument("--repo", help="owner/name. Defaults to `gh repo view`.")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    repo = args.repo or _gh_text(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    pr_number = args.pr or int(_gh_text(["pr", "view", "--json", "number", "--jq", ".number"]))

    head_sha = _gh_text(["pr", "view", str(pr_number), "--json", "headRefOid", "--jq", ".headRefOid"])
    head_created_at = _head_commit_created_at(repo, head_sha)
    deadline = time.monotonic() + args.timeout_seconds
    attempt = 1
    while True:
        result = _poll_once(repo, pr_number, head_sha, head_created_at)
        _print_summary(result, attempt, repo, pr_number, head_sha)
        if result["feedback"]:
            return
        if time.monotonic() >= deadline:
            print("No Copilot feedback appeared within the polling window.")
            return
        sleep_seconds = min(args.interval_seconds, max(0, int(deadline - time.monotonic())))
        time.sleep(sleep_seconds)
        attempt += 1


def _poll_once(repo: str, pr_number: int, head_sha: str, head_created_at: str) -> dict[str, Any]:
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
        if _is_copilot_user(comment.get("user")) and str(comment.get("created_at", "")) >= head_created_at
    ]
    copilot_events = [
        event
        for event in events
        if event.get("event") == "copilot_work_started"
        or _is_copilot_user(event.get("requested_reviewer"))
    ]
    return {
        "activity": bool(copilot_events or copilot_reviews or unresolved_threads or copilot_issue),
        "feedback": bool(unresolved_threads or copilot_issue),
        "reviews": copilot_reviews,
        "threads": unresolved_threads,
        "issue_comments": copilot_issue,
        "events": copilot_events,
    }


def _print_summary(result: dict[str, Any], attempt: int, repo: str, pr_number: int, head_sha: str) -> None:
    print(f"Poll {attempt}: {repo} PR #{pr_number} @ {head_sha[:12]}")
    print(f"Copilot activity: {'yes' if result['activity'] else 'no'}")
    print(
        "Copilot feedback: "
        f"{len(result['reviews'])} reviews, "
        f"{len(result['threads'])} unresolved threads, "
        f"{len(result['issue_comments'])} issue comments"
    )
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


def _head_commit_created_at(repo: str, head_sha: str) -> str:
    commit = _gh_json(["api", f"repos/{repo}/commits/{head_sha}"])
    return str(commit.get("commit", {}).get("committer", {}).get("date", ""))


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
