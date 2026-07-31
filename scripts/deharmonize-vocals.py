"""CLI: split mixed vocals into lead + backing stems via Karaoke model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import paths
from pipeline.stages.deharmonize import DEFAULT_KARAOKE_MODEL, DEFAULT_SKIP_THRESHOLD, run_deharmonize


def main() -> int:
    parser = argparse.ArgumentParser(description="Deharmonize mixed vocals into lead + backing stems")
    parser.add_argument("vocals", type=Path, help="Mixed vocals FLAC (from separate stage)")
    parser.add_argument("--project-id", type=str, required=True, help="Project id for output naming")
    parser.add_argument("--model", type=str, default=DEFAULT_KARAOKE_MODEL, help="Karaoke model filename")
    parser.add_argument("--segment-size", type=int, default=256, help="MDXC segment size")
    parser.add_argument("--overlap", type=int, default=8, help="MDXC overlap")
    parser.add_argument("--invert-spect", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--skip-threshold",
        type=float,
        default=DEFAULT_SKIP_THRESHOLD,
        help="Skip when backing/orig RMS ratio is below this",
    )
    parser.add_argument("--force", action="store_true", help="Run even when backing energy is low")
    args = parser.parse_args()

    try:
        result = run_deharmonize(
            args.project_id,
            args.vocals.resolve(),
            model=args.model,
            segment_size=args.segment_size,
            overlap=args.overlap,
            invert_spect=args.invert_spect,
            skip_backing_ratio_threshold=args.skip_threshold,
            force=args.force,
            on_log_line=lambda line: print(line, file=sys.stderr),
        )
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Meta: {result.meta_path}")
    if result.skipped:
        print(f"Skipped: {result.skip_reason} (backing_ratio={result.backing_ratio:.4f})")
        return 0
    print(f"Lead:    {result.lead_vocals}")
    print(f"Backing: {result.backing_vocals}")
    print(f"backing_ratio={result.backing_ratio:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
