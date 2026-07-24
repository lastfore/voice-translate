"""Phase-2 integration checks for project ``mysong`` (GPU stages, log assertions)."""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""

from pipeline import paths
from pipeline.models import ConvertMode, StageName
from pipeline.runner import StageRunner
from pipeline.stage_params import collect_params, default_stage_params
from pipeline.store import ProjectStore

PID = "mysong"


@contextlib.contextmanager
def capture_stderr():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        yield buf


def run_merge_capture_stderr(runner: StageRunner, params: dict) -> tuple[bool, str, str, str | None]:
    logs: list[str] = []
    stderr_text = ""
    error: str | None = None

    def on_progress(event) -> None:
        if event.log_line:
            logs.append(event.log_line)

    with capture_stderr() as buf:
        result = runner.run_stage(PID, StageName.MERGE, params, on_progress=on_progress)
        stderr_text = buf.getvalue()
        error = result.error

    return result.success, "\n".join(logs), stderr_text, error


def main() -> int:
    store = ProjectStore()
    runner = StageRunner(store)
    results: list[tuple[str, bool, str]] = []

    root = paths.get_root()
    full = paths.converted_full_track_path(PID)
    inst = paths.separated_instrumental_path(PID)
    converted_dir = paths.converted_dir(PID)

    if not full.is_file():
        print(f"SKIP: missing {full}")
        return 1
    if not inst or not inst.is_file():
        print(f"SKIP: missing instrumental for {PID}")
        return 1

    ok, _logs, stderr, _err = run_merge_capture_stderr(
        runner,
        {
            "vocals": str(full.relative_to(root)),
            "instrumental": str(inst.relative_to(root)),
            "merge_mode": "whole_track",
            "profile": "quick",
        },
    )
    d1_ok = ok and "converted slice missing" not in stderr and "Slice merge:" not in stderr
    results.append(
        (
            "D1 whole_track + full.flac",
            d1_ok,
            f"success={ok}; slice_warn={'converted slice missing' in stderr}",
        )
    )

    ok, _logs, stderr, err = run_merge_capture_stderr(
        runner,
        {
            "vocals": str(converted_dir.relative_to(root)),
            "instrumental": str(inst.relative_to(root)),
            "merge_mode": "slice_stitch",
            "profile": "balanced",
        },
    )
    d2_ok = ok and ("Slice merge:" in stderr or "converted slice missing" in stderr)
    d2_detail = f"success={ok}; error={err}; stderr_tail={stderr.strip()[-200:]}"
    results.append(("D2 slice_stitch + converted dir", d2_ok, d2_detail))

    values = default_stage_params(StageName.CONVERT.value)
    values["limit"] = 3
    values["skip_existing"] = True
    out = collect_params(StageName.CONVERT.value, values, convert_mode=ConvertMode.FULL_TRACK.value)
    e1_ok = "limit" not in out and "skip_existing" not in out
    results.append(("E1 full_track filters batch params", e1_ok, str(sorted(out.keys()))))

    out2 = collect_params(StageName.CONVERT.value, values, convert_mode=ConvertMode.SLICE_BATCH.value)
    e2_ok = out2.get("limit") == 3 and out2.get("skip_existing") is True
    results.append(("E2 slice_batch keeps limit", e2_ok, str(out2)))

    print("=== Phase 2 mysong ===")
    failed = 0
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {detail}")
        if not passed:
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
