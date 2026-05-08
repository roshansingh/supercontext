from __future__ import annotations

import argparse
import json

from source.kg.multi_repo import build_multi_kg


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one KG snapshot from multiple local repositories.")
    parser.add_argument("--repo", action="append", required=True, help="Path to an input repository; repeat per repo")
    parser.add_argument("--out", required=True, help="Output directory for combined JSONL KG files")
    args = parser.parse_args()

    manifest = build_multi_kg(args.repo, args.out)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
