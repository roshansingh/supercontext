from __future__ import annotations

import argparse
import json

from source.kg.queries import KgSnapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Query a minimal local KG snapshot.")
    parser.add_argument("--snapshot", required=True, help="Directory containing JSONL KG files")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary")

    callers = subparsers.add_parser("find-callers")
    callers.add_argument("symbol")
    callers.add_argument("--limit", type=int, default=25)

    blast = subparsers.add_parser("blast-radius")
    blast.add_argument("symbol")
    blast.add_argument("--depth", type=int, default=2)
    blast.add_argument("--limit", type=int, default=25)

    imports = subparsers.add_parser("modules-importing")
    imports.add_argument("package")
    imports.add_argument("--limit", type=int, default=25)

    top_deps = subparsers.add_parser("top-dependencies")
    top_deps.add_argument("--limit", type=int, default=25)
    top_deps.add_argument("--include-stdlib", action="store_true")
    top_deps.add_argument("--include-unknown", action="store_true")

    dep_info = subparsers.add_parser("dependency-info")
    dep_info.add_argument("package")

    args = parser.parse_args()
    kg = KgSnapshot(args.snapshot)
    if args.command == "summary":
        result = kg.summary()
    elif args.command == "find-callers":
        result = kg.find_callers(args.symbol, limit=args.limit)
    elif args.command == "blast-radius":
        result = kg.blast_radius(args.symbol, depth=args.depth, limit=args.limit)
    elif args.command == "modules-importing":
        result = kg.modules_importing(args.package, limit=args.limit)
    elif args.command == "top-dependencies":
        result = kg.top_dependencies(
            limit=args.limit,
            exclude_stdlib=not args.include_stdlib,
            exclude_unknown=not args.include_unknown,
        )
    elif args.command == "dependency-info":
        result = kg.dependency_info(args.package)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
