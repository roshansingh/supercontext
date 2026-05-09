from __future__ import annotations

import argparse
import json

from source.kg.build.pipeline import build_kg


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a minimal local KG snapshot from a local repo.")
    parser.add_argument("--repo", required=True, help="Path to the input repository")
    parser.add_argument("--out", required=True, help="Output directory for JSONL KG files")
    parser.add_argument("--strict-extractors", action="store_true", help="Exit non-zero if any extractor fails")
    args = parser.parse_args()

    manifest = build_kg(args.repo, args.out, strict_extractors=args.strict_extractors)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
