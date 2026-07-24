"""Migrate flat ``output/slices/{id}/`` layout to per-mode ``lrc/`` + ``vad/`` subdirs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.migrate_slices_layout import migrate_all_projects, migrate_legacy_slices_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project_id",
        nargs="?",
        help="Project ID to migrate (default: all under output/slices/)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Detect only; do not move files")
    args = parser.parse_args()

    if args.project_id:
        mode = migrate_legacy_slices_layout(args.project_id, dry_run=args.dry_run)
        if mode:
            print(f"[{args.project_id}] migrated to mode={mode}")
        else:
            print(f"[{args.project_id}] nothing to migrate")
        return 0

    results = migrate_all_projects(dry_run=args.dry_run)
    migrated = {pid: mode for pid, mode in results.items() if mode}
    if not migrated:
        print("Nothing to migrate.")
        return 0
    for pid, mode in sorted(migrated.items()):
        print(f"[{pid}] -> {mode}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
