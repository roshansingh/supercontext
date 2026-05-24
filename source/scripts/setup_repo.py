from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from source.kg.build.pipeline import build_kg
from source.scripts.mcp_host import format_host_for_url, is_loopback_host


DEFAULT_SNAPSHOT_DIR = ".supercontext/kg"
LEGACY_SNAPSHOT_DIR = ".bettercontext/kg"


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SuperContext for a local repository.")
    parser.add_argument("--repo", default=".", help="Repository to index. Defaults to the current directory.")
    parser.add_argument(
        "--out",
        help="Snapshot output directory. Defaults to <repo>/.supercontext/kg.",
    )
    parser.add_argument(
        "--tenant",
        help="Tenant id for graph identity; non-empty value overrides SUPERCONTEXT_TENANT_ID.",
    )
    parser.add_argument("--strict-extractors", action="store_true", help="Exit non-zero if any extractor fails.")
    parser.add_argument("--serve", action="store_true", help="Start the local MCP server after building the snapshot.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Loopback MCP host for --serve. Defaults to 127.0.0.1. "
            "For non-loopback binds, run the MCP server directly with --allow-public."
        ),
    )
    parser.add_argument("--port", type=int, default=3845, help="MCP port for --serve. Defaults to 3845.")
    args = parser.parse_args()
    if args.serve and not is_loopback_host(args.host):
        parser.error("--serve only supports loopback hosts; run the MCP server directly with --allow-public for public binds")

    repo = Path(args.repo).expanduser().resolve()
    out = Path(args.out).expanduser().resolve() if args.out else repo / DEFAULT_SNAPSHOT_DIR
    if not args.out:
        _warn_for_legacy_snapshot(repo, out)
    manifest = build_kg(repo, out, strict_extractors=args.strict_extractors, tenant_id=args.tenant)

    print(f"SuperContext KG built: {out}")
    print(f"Repo: {manifest.get('repo_path', repo)}")
    server_command = _mcp_server_command(out, args.host, args.port)
    print("")
    print("MCP server command:")
    print(f"  {shlex.join(server_command)}")
    print("")
    print("Install global host skills once per machine:")
    print("  supercontext-install-mcp-skills --scope global --agent both")

    if args.serve:
        print("")
        print(f"Starting SuperContext MCP server on http://{format_host_for_url(args.host)}:{args.port}/mcp")
        subprocess.run(server_command, check=True)


def _mcp_server_command(snapshot: Path, host: str, port: int) -> list[str]:
    return [
        sys.executable,
        "-P",
        "-m",
        "source.scripts.mcp_server",
        "--snapshot",
        str(snapshot),
        "--host",
        host,
        "--port",
        str(port),
    ]


def _warn_for_legacy_snapshot(repo: Path, out: Path) -> None:
    legacy_out = repo / LEGACY_SNAPSHOT_DIR
    legacy_manifest = legacy_out / "manifest.json"
    if legacy_manifest.exists() and not out.exists():
        print(
            "Warning: detected legacy BetterContext KG snapshot at "
            f"{legacy_out}. SuperContext will build a new snapshot at {out}. "
            "Remove the legacy directory after verifying the new snapshot."
        )


if __name__ == "__main__":
    main()
