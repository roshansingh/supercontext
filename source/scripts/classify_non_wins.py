from __future__ import annotations

import argparse
from pathlib import Path

from source.kg.eval.classify_non_wins import classify_non_wins, write_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a SuperContext A/B non-win classification report.")
    parser.add_argument("--report", required=True, help="Input sanitized ab-report.json.")
    parser.add_argument("--raw-root", help="Optional raw run root with */mcp_on/record.json files.")
    parser.add_argument("--report-md", help="Optional ab-report.md with caveat table fallback evidence.")
    parser.add_argument("--post-pr119", action="append", default=[], help="Optional focused rerun judged-deltas JSONL.")
    parser.add_argument("--out", required=True, help="Output loss-classification.md path.")
    args = parser.parse_args()

    result = classify_non_wins(
        Path(args.report),
        Path(args.raw_root) if args.raw_root else None,
        report_md_path=Path(args.report_md) if args.report_md else None,
        post_pr119_paths=[Path(path) for path in args.post_pr119],
    )
    write_markdown(result, Path(args.out))


if __name__ == "__main__":
    main()
