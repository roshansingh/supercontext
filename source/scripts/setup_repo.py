from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from source.kg.build.pipeline import build_kg


DEFAULT_SNAPSHOT_DIR = ".bettercontext/kg"


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Bettercontext for a local repository.")
    parser.add_argument("--repo", default=".", help="Repository to index. Defaults to the current directory.")
    parser.add_argument(
        "--out",
        help="Snapshot output directory. Defaults to <repo>/.bettercontext/kg.",
    )
    parser.add_argument(
        "--tenant",
        help="Tenant id for graph identity; non-empty value overrides SUPERCONTEXT_TENANT_ID.",
    )
    parser.add_argument("--strict-extractors", action="store_true", help="Exit non-zero if any extractor fails.")
    parser.add_argument("--serve", action="store_true", help="Start the local MCP server after building the snapshot.")
    parser.add_argument("--host", default="127.0.0.1", help="MCP host for --serve. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=3845, help="MCP port for --serve. Defaults to 3845.")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    out = Path(args.out).expanduser().resolve() if args.out else repo / DEFAULT_SNAPSHOT_DIR
    manifest = build_kg(repo, out, strict_extractors=args.strict_extractors, tenant_id=args.tenant)

    print(f"Bettercontext KG built: {out}")
    print(f"Repo: {manifest.get('repo_path', repo)}")
    print("")
    print("MCP server command:")
    print(f"  bettercontext-mcp-server --snapshot {out} --host {args.host} --port {args.port}")
    print("")
    print("Install global host skills once per machine:")
    print("  bettercontext-install-mcp-skills --scope global --agent both")

    if args.serve:
        print("")
        print(f"Starting Bettercontext MCP server on http://{args.host}:{args.port}/mcp")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "source.scripts.mcp_server",
                "--snapshot",
                str(out),
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
