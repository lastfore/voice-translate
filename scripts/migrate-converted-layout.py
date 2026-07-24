"""Migrate flat ``output/converted/{id}/`` layout to ``full/`` + ``slices/`` subdirs."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import paths

_AUDIO_EXTS = {".flac", ".wav", ".mp3", ".ogg"}


def _is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _AUDIO_EXTS


def migrate_project(project_id: str, *, dry_run: bool = False) -> list[str]:
    base = paths.converted_dir(project_id)
    actions: list[str] = []
    if not base.is_dir():
        return actions

    full_dir = paths.converted_full_dir(project_id)
    slices_dir = paths.converted_slices_dir(project_id)
    legacy_full = paths.converted_legacy_full_track_path(project_id)
    new_full = paths.converted_full_track_path(project_id)

    if legacy_full.is_file() and not new_full.is_file():
        actions.append(f"move {legacy_full} -> {new_full}")
        if not dry_run:
            full_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_full), str(new_full))

    slice_files = [
        p
        for p in base.iterdir()
        if _is_audio(p) and p.name.lower() != "full.flac" and "slice" in p.name.lower()
    ]
    if slice_files:
        actions.append(f"move {len(slice_files)} slice file(s) -> {slices_dir}/")
        if not dry_run:
            slices_dir.mkdir(parents=True, exist_ok=True)
            for src in slice_files:
                dest = slices_dir / src.name
                if dest.exists():
                    actions.append(f"skip existing {dest}")
                    continue
                shutil.move(str(src), str(dest))

    return actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project_id",
        nargs="?",
        help="Project ID to migrate (default: all under output/converted/)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without moving files")
    args = parser.parse_args()

    converted_root = paths.output_dir() / "converted"
    if not converted_root.is_dir():
        print("No converted output directory found.")
        return 0

    project_ids = [args.project_id] if args.project_id else sorted(p.name for p in converted_root.iterdir() if p.is_dir())
    if not project_ids:
        print("No projects to migrate.")
        return 0

    total = 0
    for pid in project_ids:
        actions = migrate_project(pid, dry_run=args.dry_run)
        if actions:
            print(f"[{pid}]")
            for line in actions:
                print(f"  {line}")
            total += 1
    if total == 0:
        print("Nothing to migrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
