from __future__ import annotations

import argparse
import json

from source.kg.build.multi_repo import build_multi_kg


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one KG snapshot from multiple local repositories.")
    parser.add_argument("--repo", action="append", required=True, help="Path to an input repository; repeat per repo")
    parser.add_argument("--out", required=True, help="Output directory for combined JSONL KG files")
    parser.add_argument("--strict-extractors", action="store_true", help="Exit non-zero if any extractor fails")
    args = parser.parse_args()

    manifest = build_multi_kg(args.repo, args.out, strict_extractors=args.strict_extractors)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
