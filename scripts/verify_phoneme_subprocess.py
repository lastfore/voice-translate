"""Verify phoneme subprocess stability with first-char text, delays, and crash retries."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from phoneme_align import (  # noqa: E402
    align_text_snippet,
    crash_retry_count,
    crash_retry_delay_s,
    inter_boundary_delay_s,
    run_phoneme_align_subprocess,
    sleep_crash_retry_delay,
    sleep_inter_boundary_delay,
)


def _jobs_from_manifest(manifest_path: Path) -> tuple[Path, list[dict]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    vocals = (ROOT / manifest["source"]).resolve()
    jobs: list[dict] = []
    for item in manifest.get("boundary_diagnostics", []):
        bi = int(item["boundary_index"])
        next_lrc = float(item["next_lrc_ms"])
        t_cut = float(item["t_cut_ms"])
        full_text = manifest["slices"][bi + 1]["text"]
        jobs.append(
            {
                "boundary_index": bi,
                "text": align_text_snippet(full_text),
                "window_start_ms": max(t_cut - 400, next_lrc - 700),
                "window_end_ms": next_lrc + 50.0,
            }
        )
    return vocals, jobs


def run_serial_with_retries(
    vocals: Path,
    jobs: list[dict],
    *,
    inter_delay_s: float,
    crash_delay_s: float,
    max_crash_attempts: int,
) -> dict:
    success = 0
    soft_fail = 0
    crashes = 0
    skip_reasons: Counter[str] = Counter()
    per_boundary: list[dict] = []
    t0 = time.perf_counter()

    for job in jobs:
        bi = int(job["boundary_index"])
        align_result: dict | None = None
        crash_attempts = 0
        for attempt in range(max_crash_attempts):
            try:
                raw = run_phoneme_align_subprocess(vocals, [job])
                align_result = raw[0]
                break
            except RuntimeError as exc:
                if "native crash" not in str(exc):
                    raise
                crash_attempts += 1
                if attempt >= max_crash_attempts - 1:
                    crashes += 1
                    align_result = {
                        "boundary_index": bi,
                        "onset_ms": None,
                        "skip_reason": "phoneme_align_subprocess_crash",
                    }
                else:
                    sleep_crash_retry_delay(crash_delay_s)
        sleep_inter_boundary_delay(inter_delay_s)

        assert align_result is not None
        onset = align_result.get("onset_ms")
        skip = str(align_result.get("skip_reason") or "")
        if onset is not None:
            success += 1
            status = "ok"
        else:
            soft_fail += 1
            status = "soft_fail"
            skip_reasons[skip or "unknown"] += 1
        per_boundary.append(
            {
                "boundary_index": bi,
                "status": status,
                "onset_ms": onset,
                "skip_reason": skip,
                "crash_attempts": crash_attempts,
                "align_text": job["text"],
            }
        )

    elapsed = time.perf_counter() - t0
    total = len(jobs)
    return {
        "total": total,
        "success": success,
        "soft_fail": soft_fail,
        "crashes": crashes,
        "success_rate": round(success / total, 4) if total else 0.0,
        "skip_reasons": dict(skip_reasons),
        "inter_delay_s": inter_delay_s,
        "crash_delay_s": crash_delay_s,
        "max_crash_attempts": max_crash_attempts,
        "elapsed_s": round(elapsed, 1),
        "per_boundary": per_boundary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "output/slices/loveyou/lrc/manifest.json",
    )
    parser.add_argument("--inter-delay", type=float, default=-1.0)
    parser.add_argument("--crash-delay", type=float, default=-1.0)
    parser.add_argument("--crash-retries", type=int, default=-1)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    inter_delay_s = inter_boundary_delay_s() if args.inter_delay < 0 else args.inter_delay
    crash_delay_s = crash_retry_delay_s() if args.crash_delay < 0 else args.crash_delay
    max_crash_attempts = crash_retry_count() if args.crash_retries <= 0 else args.crash_retries

    vocals, jobs = _jobs_from_manifest(args.manifest)
    print(
        f"vocals={vocals} jobs={len(jobs)} inter_delay={inter_delay_s}s "
        f"crash_delay={crash_delay_s}s retries={max_crash_attempts}",
        flush=True,
    )
    summary = run_serial_with_retries(
        vocals,
        jobs,
        inter_delay_s=inter_delay_s,
        crash_delay_s=crash_delay_s,
        max_crash_attempts=max_crash_attempts,
    )
    brief = {k: v for k, v in summary.items() if k != "per_boundary"}
    print(json.dumps(brief, ensure_ascii=False, indent=2), flush=True)
    if args.output:
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.output}", flush=True)
    return 0 if summary["success"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
