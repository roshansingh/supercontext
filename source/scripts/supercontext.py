from __future__ import annotations

import argparse
import sys

from source.scripts import supercontext_org


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="supercontext",
        description="SuperContext command line interface.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    org_parser = subparsers.add_parser("org", help="Manage org-wide SuperContext KG workspaces")
    org_parser.add_argument("org_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command == "org":
        sys.argv = ["supercontext org", *args.org_args]
        supercontext_org.main()
        return
    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
