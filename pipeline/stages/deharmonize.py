"""Deharmonize stage — split mixed vocals into lead + backing via Karaoke model."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf

from pipeline import paths
from pipeline.models import ProgressEvent, StageName
from pipeline.venv_runner import ProgressLineCallback, run_subprocess, separator_cli_cmd, separator_env, separator_python

if TYPE_CHECKING:
    from pipeline.stage_log import StageLogWriter

DEFAULT_KARAOKE_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
DEFAULT_SKIP_THRESHOLD = 0.10
_PROGRESS_RE = re.compile(r"(\d+)%|Processing|Separating", re.IGNORECASE)
_VOCALS_OUT_RE = re.compile(r"\(Vocals\)_")
_INSTRUMENTAL_OUT_RE = re.compile(r"\(Instrumental\)_")


@dataclass
class DeharmonizeResult:
    lead_vocals: Path | None
    backing_vocals: Path | None
    meta_path: Path
    skipped: bool
    skip_reason: str | None
    backing_ratio: float | None


def model_tag(model_filename: str) -> str:
    """Filename-safe model tag (strip .ckpt)."""
    return Path(model_filename).stem


def lead_output_name(project_id: str, model: str) -> str:
    return f"{project_id}_(Lead)_{model_tag(model)}.flac"


def backing_output_name(project_id: str, model: str) -> str:
    return f"{project_id}_(Backing)_{model_tag(model)}.flac"


def _rms_mono(path: Path) -> float:
    audio, _ = sf.read(str(path), always_2d=True)
    samples = audio.astype(np.float64)
    if samples.size == 0:
        return 0.0
    mono = np.mean(samples, axis=1)
    return float(np.sqrt(np.mean(np.square(mono))))


def compute_backing_ratio(orig_vocals: Path, backing_vocals: Path) -> float:
    orig_rms = _rms_mono(orig_vocals)
    backing_rms = _rms_mono(backing_vocals)
    if orig_rms < 1e-10:
        return 0.0
    return backing_rms / orig_rms


def find_karaoke_stems(output_dir: Path, *, after_mtime: float | None = None) -> tuple[Path, Path]:
    """Locate Vocals + Instrumental stems from Karaoke separation output."""
    candidates = sorted(output_dir.glob("*.flac"), key=lambda p: p.stat().st_mtime, reverse=True)
    if after_mtime is not None:
        candidates = [p for p in candidates if p.stat().st_mtime >= after_mtime - 1.0]

    lead: Path | None = None
    backing: Path | None = None
    for path in candidates:
        name = path.name
        if _VOCALS_OUT_RE.search(name) and "(backing)" not in name.lower() and "(lead)" not in name.lower():
            if lead is None:
                lead = path
        elif _INSTRUMENTAL_OUT_RE.search(name):
            if backing is None:
                backing = path
    if lead is None or backing is None:
        names = ", ".join(p.name for p in candidates[:8])
        raise RuntimeError(
            f"Karaoke separation finished but Vocals/Instrumental stems not found in {output_dir} "
            f"(recent files: {names or 'none'})"
        )
    return lead, backing


def rename_stems_to_lead_backing(
    vocals_stem: Path,
    backing_stem: Path,
    project_id: str,
    model: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Rename Karaoke Vocals/Instrumental outputs to ``(Lead)`` / ``(Backing)``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lead_path = output_dir / lead_output_name(project_id, model)
    backing_path = output_dir / backing_output_name(project_id, model)
    shutil.copy2(vocals_stem, lead_path)
    shutil.copy2(backing_stem, backing_path)
    return lead_path, backing_path


def write_deharmonize_meta(
    meta_path: Path,
    *,
    project_id: str,
    model: str,
    skipped: bool,
    skip_reason: str | None,
    backing_ratio: float | None,
    params: dict[str, Any],
) -> None:
    payload = {
        "project_id": project_id,
        "model": model,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "backing_ratio": backing_ratio,
        "params": params,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_deharmonize(
    project_id: str,
    mixed_vocals: Path,
    *,
    model: str = DEFAULT_KARAOKE_MODEL,
    segment_size: int = 256,
    overlap: int = 8,
    invert_spect: bool = True,
    skip_backing_ratio_threshold: float = DEFAULT_SKIP_THRESHOLD,
    force: bool = False,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_log_line: ProgressLineCallback | None = None,
    stage_log: StageLogWriter | None = None,
) -> DeharmonizeResult:
    """Run Karaoke model on mixed vocals; emit lead/backing stems or skip."""
    root = paths.get_root()
    mixed_vocals = Path(mixed_vocals).resolve()
    if not mixed_vocals.is_file():
        raise FileNotFoundError(f"mixed vocals not found: {mixed_vocals}")

    output_dir = paths.separated_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = paths.deharmonize_meta_path(project_id)
    model_dir = paths.get_separator_env() / "models" / "audio-separator"

    run_params = {
        "model": model,
        "segment_size": segment_size,
        "overlap": overlap,
        "invert_spect": invert_spect,
        "skip_backing_ratio_threshold": skip_backing_ratio_threshold,
        "force": force,
    }

    job_id = f"deharmonize-{project_id}"
    percent = 0.0

    def _emit(message: str, pct: float | None = None) -> None:
        nonlocal percent
        if pct is not None:
            percent = pct
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.DEHARMONIZE,
                    job_id=job_id,
                    percent=percent,
                    message=message,
                    log_line=None if stage_log else message,
                )
            )

    def _line_handler(line: str) -> None:
        if stage_log:
            stage_log.line(line)
        elif on_log_line:
            on_log_line(line)
        match = _PROGRESS_RE.search(line)
        if match and match.group(1):
            _emit(line, float(match.group(1)))
        else:
            _emit(line, None)

    _emit(f"Deharmonizing {mixed_vocals.name}", 0.0)

    import time

    t_before = time.time()
    cmd = separator_cli_cmd(
        str(mixed_vocals),
        "--model_filename",
        model,
        "--model_file_dir",
        str(model_dir),
        "--output_format",
        "flac",
        "--output_dir",
        str(output_dir),
        "--mdxc_segment_size",
        str(segment_size),
        "--mdxc_overlap",
        str(overlap),
    )
    if invert_spect:
        cmd.append("--invert_spect")

    if stage_log:
        stage_log.cmd(
            [str(x) for x in cmd],
            cwd=str(root),
            python=str(separator_python()),
        )

    result = run_subprocess(cmd, cwd=root, env=separator_env(), on_line=_line_handler)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()
        raise RuntimeError(f"audio-separator Karaoke failed (code {result.returncode}): {detail}")

    raw_lead, raw_backing = find_karaoke_stems(output_dir, after_mtime=t_before)
    backing_ratio = compute_backing_ratio(mixed_vocals, raw_backing)

    skip_reason: str | None = None
    if not force and backing_ratio < skip_backing_ratio_threshold:
        skip_reason = "low_backing_energy"
        if stage_log:
            stage_log.info(
                f"deharmonize_skipped: {skip_reason} backing_ratio={backing_ratio:.4f} "
                f"threshold={skip_backing_ratio_threshold}"
            )
        write_deharmonize_meta(
            meta_path,
            project_id=project_id,
            model=model,
            skipped=True,
            skip_reason=skip_reason,
            backing_ratio=backing_ratio,
            params=run_params,
        )
        _emit(f"Skipped deharmonize ({skip_reason})", 100.0)
        return DeharmonizeResult(
            lead_vocals=None,
            backing_vocals=None,
            meta_path=meta_path,
            skipped=True,
            skip_reason=skip_reason,
            backing_ratio=backing_ratio,
        )

    lead_path, backing_path = rename_stems_to_lead_backing(
        raw_lead, raw_backing, project_id, model, output_dir
    )
    write_deharmonize_meta(
        meta_path,
        project_id=project_id,
        model=model,
        skipped=False,
        skip_reason=None,
        backing_ratio=backing_ratio,
        params=run_params,
    )
    if stage_log:
        stage_log.info(f"backing_ratio={backing_ratio:.4f}")
    _emit("Deharmonize complete", 100.0)
    return DeharmonizeResult(
        lead_vocals=lead_path,
        backing_vocals=backing_path,
        meta_path=meta_path,
        skipped=False,
        skip_reason=None,
        backing_ratio=backing_ratio,
    )
