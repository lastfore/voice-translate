"""Voice conversion stage (full track + slice batch)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline import paths
from pipeline.models import ConvertMode, ProgressEvent, StageName
from pipeline.venv_runner import run_subprocess, seed_vc_python

if TYPE_CHECKING:
    from pipeline.stage_log import StageLogWriter

_PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]\s*(.+)")


@dataclass
class ConvertResult:
    mode: str
    converted_dir: Path
    full_track: Path | None = None
    converted_count: int = 0
    total_count: int = 0


def run_convert(
    project_id: str,
    *,
    mode: str = ConvertMode.SLICE_BATCH.value,
    source_vocals: Path | None = None,
    reference: Path,
    slices_dir: Path | None = None,
    manifest: Path | None = None,
    output_dir: Path | None = None,
    output_path: Path | None = None,
    diffusion_steps: int = 40,
    length_adjust: float = 1.0,
    inference_cfg_rate: float = 0.7,
    auto_f0_adjust: bool = True,
    semi_tone_shift: int = 0,
    fp16: bool = True,
    skip_existing: bool = True,
    limit: int = 0,
    slice_mode: str = "lrc",
    slice_ids: list[str] | None = None,
    overrides_path: Path | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    stage_log: StageLogWriter | None = None,
) -> ConvertResult:
    reference = Path(reference).resolve()
    if not reference.is_file():
        raise FileNotFoundError(f"reference not found: {reference}")

    root = paths.get_root()
    job_id = f"convert-{project_id}"

    def _emit(message: str, percent: float, log_line: str | None = None) -> None:
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.CONVERT,
                    job_id=job_id,
                    percent=percent,
                    message=message,
                    log_line=None if stage_log else log_line,
                )
            )

    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(root)

    if mode == ConvertMode.FULL_TRACK.value:
        source = Path(source_vocals).resolve() if source_vocals else None
        if source is None or not source.is_file():
            raise FileNotFoundError("full_track mode requires source_vocals")
        dest = Path(output_path) if output_path else paths.converted_full_track_path(project_id)
        dest = dest.resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            seed_vc_python(),
            "-m",
            "pipeline.stages.convert_full",
            "--source",
            str(source),
            "--reference",
            str(reference),
            "--output",
            str(dest),
            "--diffusion-steps",
            str(diffusion_steps),
            "--length-adjust",
            str(length_adjust),
            "--inference-cfg-rate",
            str(inference_cfg_rate),
            "--semi-tone-shift",
            str(semi_tone_shift),
        ]
        if auto_f0_adjust:
            cmd.append("--auto-f0-adjust")
        else:
            cmd.append("--no-auto-f0-adjust")
        if fp16:
            cmd.append("--fp16")
        else:
            cmd.append("--no-fp16")

        def _line(line: str) -> None:
            if stage_log:
                stage_log.line(line)
            _emit(line, 50.0)

        _emit("Converting full track", 0.0)
        if stage_log:
            stage_log.cmd([str(x) for x in cmd], cwd=str(root), python=str(seed_vc_python()))
        result = run_subprocess(cmd, cwd=root, env=env, on_line=_line)
        if result.returncode != 0:
            raise RuntimeError((result.stdout or result.stderr or "convert_full failed").strip())
        if not dest.is_file():
            raise RuntimeError(f"expected output not found: {dest}")
        _emit("Full track conversion complete", 100.0)
        return ConvertResult(
            mode=mode,
            converted_dir=paths.converted_dir(project_id),
            full_track=dest,
            converted_count=1,
            total_count=1,
        )

    # slice_batch via subprocess CLI
    smode = paths.normalize_slice_mode(slice_mode)
    out_dir = Path(output_dir) if output_dir else paths.converted_mode_dir(project_id, smode)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sdir = Path(slices_dir).resolve() if slices_dir else paths.resolve_slices_mode_dir(project_id, smode)
    if sdir is None:
        sdir = paths.slices_dir(project_id)
    sdir = sdir.resolve()
    if not sdir.is_dir():
        raise FileNotFoundError(f"slices_dir not found: {sdir}")

    manifest_path = Path(manifest).resolve() if manifest else paths.slices_manifest_path(project_id, smode)
    if not manifest_path.is_file():
        manifest_path = None

    cmd = [
        seed_vc_python(),
        str(root / "scripts" / "convert-slices.py"),
        str(sdir),
        "--reference",
        str(reference),
        "--output",
        str(out_dir),
        "--diffusion-steps",
        str(diffusion_steps),
        "--length-adjust",
        str(length_adjust),
        "--inference-cfg-rate",
        str(inference_cfg_rate),
        "--semi-tone-shift",
        str(semi_tone_shift),
    ]
    if manifest_path:
        cmd.extend(["--manifest", str(manifest_path)])
    if auto_f0_adjust:
        cmd.append("--auto-f0-adjust")
    else:
        cmd.append("--no-auto-f0-adjust")
    if fp16:
        cmd.append("--fp16")
    else:
        cmd.append("--no-fp16")
    if skip_existing:
        cmd.append("--skip-existing")
    else:
        cmd.append("--force")
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    if slice_ids:
        cmd.extend(["--slice-ids", ",".join(slice_ids)])
    overrides_file = overrides_path or paths.slices_overrides_path(project_id, smode)
    if overrides_file.is_file():
        cmd.extend(["--overrides", str(overrides_file.resolve())])

    converted = 0
    total = 0

    def _batch_line(line: str) -> None:
        nonlocal converted, total
        if stage_log:
            stage_log.line(line)
        match = _PROGRESS_RE.search(line)
        if match:
            converted = int(match.group(1))
            total = int(match.group(2))
            pct = (converted / total * 100.0) if total else 0.0
            _emit(f"[{converted}/{total}] {match.group(3)}", pct)
        else:
            _emit(line, (converted / total * 100.0) if total else 0.0)

    _emit("Starting slice batch conversion", 0.0)
    if stage_log:
        stage_log.cmd([str(x) for x in cmd], cwd=str(root), python=str(seed_vc_python()))
    result = run_subprocess(cmd, cwd=root, env=env, on_line=_batch_line)
    if result.returncode != 0:
        raise RuntimeError((result.stdout or result.stderr or "convert-slices failed").strip())

    # Parse final line "Done: X/Y"
    done_match = re.search(r"Done:\s*(\d+)/(\d+)", result.stdout or "")
    if done_match:
        converted = int(done_match.group(1))
        total = int(done_match.group(2))

    _emit(f"Converted {converted}/{total} slices", 100.0)
    return ConvertResult(
        mode=mode,
        converted_dir=out_dir,
        full_track=None,
        converted_count=converted,
        total_count=total,
    )
