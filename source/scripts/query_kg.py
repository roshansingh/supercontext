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
    callers.add_argument("--path")
    callers.add_argument("--line", type=int)
    callers.add_argument("--include-all", action="store_true")
    callers.add_argument("--limit", type=int, default=25)

    callees = subparsers.add_parser("find-callees")
    callees.add_argument("symbol")
    callees.add_argument("--path")
    callees.add_argument("--line", type=int)
    callees.add_argument("--include-all", action="store_true")
    callees.add_argument("--limit", type=int, default=25)

    blast = subparsers.add_parser("blast-radius")
    blast.add_argument("symbol")
    blast.add_argument("--path")
    blast.add_argument("--line", type=int)
    blast.add_argument("--include-all", action="store_true")
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

    who_imports = subparsers.add_parser("who-imports")
    who_imports.add_argument("target")
    who_imports.add_argument("--group-prefix-depth", type=int, default=2)
    who_imports.add_argument("--no-grouping", action="store_true")
    who_imports.add_argument("--limit", type=int, default=25)

    top_internal_deps = subparsers.add_parser("top-internal-dependencies")
    top_internal_deps.add_argument("--relative-only", action="store_true")
    top_internal_deps.add_argument("--limit", type=int, default=25)

    top_fan_in = subparsers.add_parser("top-fan-in-symbols")
    top_fan_in.add_argument("--include-external", action="store_true")
    top_fan_in.add_argument("--limit", type=int, default=25)

    imports_both = subparsers.add_parser("modules-importing-both")
    imports_both.add_argument("left")
    imports_both.add_argument("right")
    imports_both.add_argument("--category", help="Comma-separated import categories to include")
    imports_both.add_argument("--limit", type=int, default=25)

    dep_path = subparsers.add_parser("dependency-path")
    dep_path.add_argument("source")
    dep_path.add_argument("target")
    dep_path.add_argument("--path")
    dep_path.add_argument("--line", type=int)
    dep_path.add_argument("--include-all", action="store_true")
    dep_path.add_argument("--max-depth", type=int, default=4)
    dep_path.add_argument("--limit", type=int, default=5)

    lookup = subparsers.add_parser("lookup-symbol")
    lookup.add_argument("symbol")
    lookup.add_argument("--path")
    lookup.add_argument("--line", type=int)
    lookup.add_argument("--limit", type=int, default=25)

    symbols_file = subparsers.add_parser("symbols-in-file")
    symbols_file.add_argument("path")
    symbols_file.add_argument("--limit", type=int, default=100)

    call_evidence = subparsers.add_parser("evidence-for-call")
    call_evidence.add_argument("caller")
    call_evidence.add_argument("callee")
    call_evidence.add_argument("--path")
    call_evidence.add_argument("--line", type=int)
    call_evidence.add_argument("--limit", type=int, default=25)

    args = parser.parse_args()
    kg = KgSnapshot(args.snapshot)
    if args.command == "summary":
        result = kg.summary()
    elif args.command == "find-callers":
        result = kg.find_callers(
            args.symbol,
            limit=args.limit,
            path=args.path,
            line=args.line,
            include_all=args.include_all,
        )
    elif args.command == "find-callees":
        result = kg.find_callees(
            args.symbol,
            limit=args.limit,
            path=args.path,
            line=args.line,
            include_all=args.include_all,
        )
    elif args.command == "blast-radius":
        result = kg.blast_radius(
            args.symbol,
            depth=args.depth,
            limit=args.limit,
            path=args.path,
            line=args.line,
            include_all=args.include_all,
        )
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
    elif args.command == "who-imports":
        result = kg.who_imports(
            args.target,
            group_prefix_depth=max(1, args.group_prefix_depth),
            no_grouping=args.no_grouping,
            limit=args.limit,
        )
    elif args.command == "top-internal-dependencies":
        result = kg.top_internal_dependencies(relative_only=args.relative_only, limit=args.limit)
    elif args.command == "top-fan-in-symbols":
        result = kg.top_fan_in_symbols(include_external=args.include_external, limit=args.limit)
    elif args.command == "modules-importing-both":
        category_filter = None
        if args.category:
            category_filter = {part.strip() for part in args.category.split(",") if part.strip()}
        result = kg.modules_importing_both(args.left, args.right, category_filter=category_filter, limit=args.limit)
    elif args.command == "dependency-path":
        result = kg.dependency_path(
            args.source,
            args.target,
            path=args.path,
            line=args.line,
            include_all=args.include_all,
            max_depth=min(max(1, args.max_depth), 6),
            limit=min(max(1, args.limit), 25),
        )
    elif args.command == "lookup-symbol":
        result = kg.lookup_symbol(args.symbol, limit=args.limit, path=args.path, line=args.line)
    elif args.command == "symbols-in-file":
        result = kg.symbols_in_file(args.path, limit=args.limit)
    elif args.command == "evidence-for-call":
        result = kg.evidence_for_call(
            args.caller,
            args.callee,
            path=args.path,
            line=args.line,
            limit=args.limit,
        )
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
