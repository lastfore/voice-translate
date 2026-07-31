"""Run one or more phoneme boundary alignments in an isolated process (Windows stability)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phoneme_align import align_boundary_local_with_retries, align_text_snippet  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Phoneme align worker (subprocess)")
    parser.add_argument("vocals", type=Path, help="Path to vocals audio")
    parser.add_argument("jobs_json", type=Path, help="JSON file: list of align jobs")
    args = parser.parse_args()

    if not args.vocals.is_file():
        print(json.dumps({"error": f"vocals not found: {args.vocals}"}), file=sys.stderr)
        return 2
    if not args.jobs_json.is_file():
        print(json.dumps({"error": f"jobs file not found: {args.jobs_json}"}), file=sys.stderr)
        return 2

    jobs = json.loads(args.jobs_json.read_text(encoding="utf-8-sig"))
    if not isinstance(jobs, list):
        print(json.dumps({"error": "jobs_json must be a JSON array"}), file=sys.stderr)
        return 2

    audio, sr = sf.read(str(args.vocals), always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    results: list[dict[str, object]] = []
    for job in jobs:
        boundary_index = int(job["boundary_index"])
        text = align_text_snippet(str(job.get("text", "")))
        window_start_ms = float(job["window_start_ms"])
        window_end_ms = float(job["window_end_ms"])
        try:
            onset_ms, skip_reason = align_boundary_local_with_retries(
                audio,
                sr,
                text,
                window_start_ms,
                window_end_ms,
            )
        except Exception:
            onset_ms, skip_reason = None, "phoneme_align_worker_error"
        results.append(
            {
                "boundary_index": boundary_index,
                "onset_ms": onset_ms,
                "skip_reason": skip_reason,
            }
        )
        # Release MMS between jobs when batching N>1 in one process.
        if len(jobs) > 1:
            from phoneme_align import _reset_alignment_model

            _reset_alignment_model()

    sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
