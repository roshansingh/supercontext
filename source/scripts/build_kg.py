from __future__ import annotations

import argparse
import json

from source.kg.pipeline import build_kg


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a minimal local KG snapshot from a local repo.")
    parser.add_argument("--repo", required=True, help="Path to the input repository")
    parser.add_argument("--out", required=True, help="Output directory for JSONL KG files")
    args = parser.parse_args()

    manifest = build_kg(args.repo, args.out)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
