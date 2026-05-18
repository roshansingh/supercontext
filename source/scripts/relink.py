from __future__ import annotations

import argparse
import json
from pathlib import Path

from source.kg.build.relink import default_output_dir, relink_snapshot_dirs, resolve_snapshot_dirs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh fleet-level cross-repo linker artifacts from existing snapshots. "
            "The original repo trees recorded in snapshot manifests must still exist so package metadata can be read."
        )
    )
    parser.add_argument(
        "--snapshot-dir",
        action="append",
        required=True,
        help="Snapshot directory, or fleet directory containing per-repo snapshot subdirectories; repeat as needed",
    )
    parser.add_argument(
        "--out",
        help="Output directory for fleet linker artifacts; required unless --snapshot-dir points to one fleet directory",
    )
    parser.add_argument(
        "--tenant",
        help="Tenant id to validate against snapshot manifests; it must match because entity IDs are tenant-scoped",
    )
    args = parser.parse_args()

    raw_snapshot_dirs = tuple(Path(path) for path in args.snapshot_dir)
    snapshot_dirs = resolve_snapshot_dirs(raw_snapshot_dirs)
    out = Path(args.out) if args.out else default_output_dir(raw_snapshot_dirs)
    manifest = relink_snapshot_dirs(snapshot_dirs, out, tenant_id=args.tenant)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
