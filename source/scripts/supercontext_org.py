from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from source.kg.core.models import canonical_json
from source.kg.org.git import GitClient
from source.kg.org.workspace import DiscoveredRepo
from source.kg.org.workspace import build_org, default_org_home, init_org, load_org_config, sync_org
from source.kg.product.mcp_tools import call_tool
from source.kg.query.snapshot import KgSnapshot
from source.scripts.mcp_host import format_host_for_url, is_loopback_host


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage org-wide SuperContext KG workspaces.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create an org workspace config")
    init_parser.add_argument("--provider", choices=["github"], required=True)
    init_parser.add_argument("--org", required=True)
    init_parser.add_argument("--home", help="Workspace home. Defaults to ~/.supercontext/orgs/<provider>/<org>.")
    init_parser.add_argument("--include", action="append", default=[], help="Repo glob to include; repeatable.")
    init_parser.add_argument("--exclude", action="append", default=[], help="Repo glob to exclude; repeatable.")
    init_parser.add_argument("--clone-protocol", choices=["ssh", "https"], default="https")

    sync_parser = subparsers.add_parser("sync", help="Discover and clone/fetch org repos into the managed cache")
    sync_parser.add_argument("--home", help="Workspace home. Defaults from --provider/--org when provided.")
    sync_parser.add_argument("--provider", choices=["github"], default="github")
    sync_parser.add_argument("--org", help="Org name when --home is omitted.")
    sync_parser.add_argument("--repo-timeout-seconds", type=int, default=300)
    sync_parser.add_argument("--fail-fast", action="store_true", help="Stop on the first repo clone/fetch failure.")

    build_parser = subparsers.add_parser("build", help="Build the org KG from the synced repo cache")
    build_parser.add_argument("--home", help="Workspace home. Defaults from --provider/--org when provided.")
    build_parser.add_argument("--provider", choices=["github"], default="github")
    build_parser.add_argument("--org", help="Org name when --home is omitted.")
    build_parser.add_argument("--sync-first", action="store_true", help="Run org sync before building.")
    build_parser.add_argument("--repo-timeout-seconds", type=int, default=300)
    build_parser.add_argument("--fail-fast", action="store_true", help="Stop sync-first on the first repo clone/fetch failure.")
    build_parser.add_argument("--force", action="store_true", help="Rebuild even if synced repo heads are unchanged.")
    build_parser.add_argument("--strict-extractors", action="store_true")
    build_parser.add_argument("--tenant", help="Tenant id for graph identity. Defaults to the org name.")

    serve_parser = subparsers.add_parser("serve", help="Serve the org KG over the local MCP server")
    serve_parser.add_argument("--home", help="Workspace home. Defaults from --provider/--org when provided.")
    serve_parser.add_argument("--provider", choices=["github"], default="github")
    serve_parser.add_argument("--org", help="Org name when --home is omitted.")
    serve_parser.add_argument("--build-first", action="store_true", help="Build before starting the MCP server.")
    serve_parser.add_argument("--sync-first", action="store_true", help="Sync before optional build and serve.")
    serve_parser.add_argument("--repo-timeout-seconds", type=int, default=300)
    serve_parser.add_argument("--fail-fast", action="store_true", help="Stop sync-first on the first repo clone/fetch failure.")
    serve_parser.add_argument("--force", action="store_true", help="Force rebuild when --build-first is set.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=3845)

    review_parser = subparsers.add_parser("review", help="Call review_context for a local diff against the org KG")
    review_parser.add_argument("--home", help="Workspace home. Defaults from --provider/--org when provided.")
    review_parser.add_argument("--provider", choices=["github"], default="github")
    review_parser.add_argument("--org", help="Org name when --home is omitted.")
    review_parser.add_argument("--repo", required=True, help="Review repo anchor, either repo or owner/repo.")
    review_parser.add_argument("--worktree", default=".", help="Local worktree containing the diff. Defaults to cwd.")
    review_parser.add_argument("--base", default="main", help="Base ref for git diff. Defaults to main.")
    review_parser.add_argument(
        "--head",
        default="HEAD",
        help="Head ref for git diff. Defaults to HEAD; uncommitted worktree changes are not included.",
    )
    review_parser.add_argument("--requested-surface", action="append", default=[], help="Review surface to request; repeatable.")
    review_parser.add_argument("--include-deploy-blockers", action="store_true")
    review_parser.add_argument("--limit", type=int, default=25)

    args = parser.parse_args()
    if args.command == "init":
        _init(args)
    elif args.command == "sync":
        _sync(args)
    elif args.command == "build":
        _build(args)
    elif args.command == "serve":
        _serve(parser, args)
    elif args.command == "review":
        _review(args)
    else:
        parser.error(f"Unsupported command: {args.command}")


def _init(args: argparse.Namespace) -> None:
    home = Path(args.home).expanduser().resolve() if args.home else default_org_home(args.provider, args.org)
    config = init_org(
        provider=args.provider,
        org=args.org,
        home=home,
        include=tuple(args.include),
        exclude=tuple(args.exclude),
        clone_protocol=args.clone_protocol,
    )
    print(f"SuperContext org workspace initialized: {config.home}")
    print("")
    print("Next steps:")
    print(f"  supercontext org sync --home {shlex.quote(str(config.home))}")
    print(f"  supercontext org build --home {shlex.quote(str(config.home))}")
    print(f"  supercontext org serve --home {shlex.quote(str(config.home))}")


def _sync(args: argparse.Namespace) -> None:
    home = _workspace_home(args)
    result = sync_org(
        home,
        git_client=GitClient(timeout_seconds=args.repo_timeout_seconds),
        progress=_print_sync_progress,
        continue_on_error=not args.fail_fast,
    )
    print(f"SuperContext org sync complete: {home}")
    print(f"Repos: {result.repo_count}")
    print(f"Changed: {result.changed_count}")
    print(f"Unchanged: {result.unchanged_count}")
    print(f"Failed: {result.failed_count}")
    for error in result.errors:
        print(f"warning: skipped {error['repo']}: {error['error']}: {error['message']}")


def _build(args: argparse.Namespace) -> None:
    home = _workspace_home(args)
    if args.sync_first:
        sync_org(
            home,
            git_client=GitClient(timeout_seconds=args.repo_timeout_seconds),
            progress=_print_sync_progress,
            continue_on_error=not args.fail_fast,
        )
    result = build_org(
        home,
        force=args.force,
        strict_extractors=args.strict_extractors,
        tenant_id=args.tenant,
        progress=_print_build_progress,
    )
    if result.skipped:
        print(f"SuperContext org KG unchanged; using existing snapshot: {result.snapshot_dir}")
    else:
        print(f"SuperContext org KG built: {result.snapshot_dir}")
    print(f"Repos: {result.repo_count}")


def _serve(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not is_loopback_host(args.host):
        parser.error("org serve only supports loopback hosts; run the MCP server directly for public binds")
    home = _workspace_home(args)
    if args.sync_first:
        sync_org(
            home,
            git_client=GitClient(timeout_seconds=args.repo_timeout_seconds),
            progress=_print_sync_progress,
            continue_on_error=not args.fail_fast,
        )
    if args.build_first:
        build_org(home, force=args.force, progress=_print_build_progress)
    config = load_org_config(home)
    command = [
        sys.executable,
        "-P",
        "-m",
        "source.scripts.mcp_server",
        "--snapshot",
        str(config.snapshot_dir),
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    print(f"Starting SuperContext org MCP server on http://{format_host_for_url(args.host)}:{args.port}/mcp")
    subprocess.run(command, check=True)


def _review(args: argparse.Namespace) -> None:
    home = _workspace_home(args)
    config = load_org_config(home)
    worktree = Path(args.worktree).expanduser().resolve()
    changed_files = _git_changed_files(worktree, base=args.base, head=args.head)
    if not changed_files:
        raise SystemExit("No changed files found for the requested base/head refs.")
    changed_ranges = _git_changed_ranges(worktree, base=args.base, head=args.head)
    arguments: dict[str, object] = {
        "repo": args.repo,
        "changed_files": changed_files,
        "changed_ranges": changed_ranges,
        "limit": args.limit,
    }
    if args.requested_surface:
        arguments["requested_surfaces"] = list(args.requested_surface)
    if args.include_deploy_blockers:
        arguments["include_deploy_blockers"] = True
    result = call_tool(KgSnapshot(config.snapshot_dir), "review_context", arguments)
    print(canonical_json(result))


def _git_changed_files(worktree: Path, *, base: str, head: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", f"{base}...{head}"],
        cwd=str(worktree),
        text=True,
        stderr=subprocess.PIPE,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def _git_changed_ranges(worktree: Path, *, base: str, head: str) -> list[dict[str, int | str]]:
    output = subprocess.check_output(
        ["git", "diff", "--unified=0", "--no-color", "--no-ext-diff", f"{base}...{head}"],
        cwd=str(worktree),
        text=True,
        stderr=subprocess.PIPE,
    )
    ranges: list[dict[str, int | str]] = []
    current_path: str | None = None
    for line in output.splitlines():
        if line.startswith("+++ "):
            current_path = _diff_new_path(line[4:].strip())
            continue
        if current_path is None or not line.startswith("@@ "):
            continue
        parsed_range = _parse_diff_hunk_range(line)
        if parsed_range is None:
            continue
        start_line, line_count = parsed_range
        if line_count <= 0:
            continue
        ranges.append(
            {
                "path": current_path,
                "start_line": start_line,
                "end_line": start_line + line_count - 1,
            }
        )
    return ranges


def _parse_diff_hunk_range(line: str) -> tuple[int, int] | None:
    parts = line.split()
    if len(parts) < 3 or not parts[2].startswith("+"):
        return None
    payload = parts[2][1:]
    if not payload:
        return None
    pieces = payload.split(",", 1)
    try:
        start_line = int(pieces[0])
        line_count = int(pieces[1]) if len(pieces) == 2 else 1
    except ValueError:
        return None
    return start_line, line_count


def _diff_new_path(raw_path: str) -> str | None:
    if raw_path == "/dev/null":
        return None
    if raw_path.startswith("b/"):
        return raw_path[2:]
    return raw_path


def _workspace_home(args: argparse.Namespace) -> Path:
    if args.home:
        return Path(args.home).expanduser().resolve()
    if not args.org:
        raise SystemExit("--org is required when --home is omitted")
    return default_org_home(args.provider, args.org)


def _print_sync_progress(index: int, total: int, repo: DiscoveredRepo) -> None:
    print(f"[{index}/{total}] syncing {repo.full_name}", flush=True)


def _print_build_progress(index: int, total: int, repo_path: Path) -> None:
    print(f"[{index}/{total}] indexing {repo_path.name}", flush=True)


if __name__ == "__main__":
    main()
