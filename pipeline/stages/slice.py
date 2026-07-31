"""Vocal slicing stage (VAD or LRC)."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pipeline import paths
from pipeline.models import ProgressEvent, SliceMode, StageName, rel_path
from pipeline.slice_overrides import load as load_overrides
from pipeline.slice_overrides import merge_after_reslice
from pipeline.slice_overrides import save as save_overrides
from pipeline.venv_runner import run_subprocess, separator_env, separator_python

if TYPE_CHECKING:
    from pipeline.stage_log import StageLogWriter


@dataclass
class SliceResult:
    slices_dir: Path
    manifest: Path
    slice_count: int


def _load_script_module(name: str, filename: str):
    root = paths.get_root()
    script_path = root / "scripts" / filename
    if not script_path.is_file():
        raise FileNotFoundError(f"script not found: {script_path}")
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _phoneme_align_needs_subprocess(phoneme_align_mode: str) -> bool:
    """Torch MMS in uvicorn worker thread can crash on Windows; isolate in subprocess."""
    return phoneme_align_mode == "local_cpu"


def _format_subprocess_failure(result: subprocess.CompletedProcess[str], *, cmd_name: str) -> str:
    raw = ((result.stdout or "") + (result.stderr or "")).strip()
    code = result.returncode
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # Drop tqdm progress-only lines so crashes surface real tracebacks.
    useful = [
        ln
        for ln in lines
        if not re.match(r"^(Loading weights:|Warning: You are sending)", ln)
        and "|" not in ln[:40]
    ]
    detail = "\n".join(useful[-20:]) if useful else raw[-2000:]
    if code == 0:
        return detail or f"{cmd_name} failed without output"
    if code == -1073741819 or code == 3221225477:
        hint = (
            "native crash (ACCESS_VIOLATION) in phoneme/Torch subprocess; "
            "retry after API restart or check OMP/MKL thread limits"
        )
        return f"{cmd_name} exit={code} {hint}" + (f"\n{detail}" if detail else "")
    return f"{cmd_name} exit={code}" + (f"\n{detail}" if detail else "")


def _log_lrc_boundaries(
    stage_log: StageLogWriter,
    meta: dict[str, Any],
    *,
    boundary_mode: str,
    search_margin_ms: int,
    onset_min_lead_silence_ms: int,
    min_slice_ms: int,
    onset_energy_threshold_db: float,
    safety_margin_ms: int,
    g2p_preroll_ms: int,
    boundary_zcr_weight: float,
    phoneme_align_mode: str,
    phoneme_align_fallback_only: bool,
) -> None:
    aligned = meta.get("aligned_boundary_count", 0)
    valley = meta.get("valley_boundary_count", 0)
    fallback = meta.get("fallback_boundary_count", 0)
    phoneme_applied = meta.get("phoneme_align_applied_count", 0)
    phoneme_remote_skipped = meta.get("phoneme_align_skipped_remote_count", 0)
    phoneme_skip_counts = meta.get("phoneme_align_skip_counts") or {}
    skip_summary = " ".join(
        f"{reason}={count}" for reason, count in sorted(phoneme_skip_counts.items())
    )
    stage_log.info(
        "LRC boundaries "
        f"mode={meta.get('boundary_mode', boundary_mode)} "
        f"aligned={aligned} valley={valley} fallback={fallback} "
        f"search_margin_ms={meta.get('search_margin_ms', search_margin_ms)} "
        f"onset_min_lead_silence_ms={meta.get('onset_min_lead_silence_ms', onset_min_lead_silence_ms)} "
        f"min_slice_ms={meta.get('min_slice_ms', min_slice_ms)} "
        f"onset_energy_threshold_db={meta.get('onset_energy_threshold_db', onset_energy_threshold_db)} "
        f"safety_margin_ms={meta.get('safety_margin_ms', safety_margin_ms)} "
        f"g2p_preroll_ms={meta.get('g2p_preroll_ms', g2p_preroll_ms)} "
        f"boundary_zcr_weight={meta.get('boundary_zcr_weight', boundary_zcr_weight)} "
        f"phoneme_align_mode={meta.get('phoneme_align_mode', phoneme_align_mode)} "
        f"phoneme_align_fallback_only={str(meta.get('phoneme_align_fallback_only', phoneme_align_fallback_only)).lower()} "
        f"phoneme_align_applied={phoneme_applied}"
        + (f" phoneme_align_skip={skip_summary}" if skip_summary else "")
    )
    if phoneme_remote_skipped:
        stage_log.info(
            f"WARN phoneme_align_mode=remote skipped {phoneme_remote_skipped} boundaries "
            "(remote_not_implemented)"
        )
    for item in meta.get("boundary_diagnostics", []):
        status = "aligned" if item.get("aligned") else "fallback"
        delta = item.get("delta_ms", 0)
        delta_text = f" delta={delta:.2f}ms" if float(delta) > 0.01 else ""
        margin_applied = int(item.get("safety_margin_applied_ms", 0))
        margin_text = f" margin={margin_applied}ms" if margin_applied > 0 else ""
        g2p_used = float(item.get("g2p_preroll_ms_used", 0))
        g2p_text = f" g2p={g2p_used:.0f}ms" if g2p_used > 0 else ""
        phoneme_text = " phoneme=1" if item.get("phoneme_align_applied") else ""
        phoneme_skip = item.get("phoneme_align_skip_reason") or ""
        phoneme_skip_text = f" phoneme_skip={phoneme_skip}" if phoneme_skip else ""
        stage_log.info(
            f"[BOUNDARY] i={int(item['boundary_index']):02d} {item['next_slice_id']} "
            f"{status} method={item['method']} reason={item['reason']} "
            f"t_cut={item['t_cut_ms']} lrc={item['next_lrc_ms']}{delta_text}{margin_text}{g2p_text}"
            f"{phoneme_skip_text}{phoneme_text}"
        )
    example = meta.get("first_fallback_example")
    if example:
        stage_log.info(f"LRC first fallback example: {example}")


def _run_lrc_slice_subprocess(
    *,
    root: Path,
    project_id: str,
    lrc_path: Path,
    vocals: Path,
    output_dir: Path,
    boundary_mode: str,
    search_margin_ms: int,
    onset_min_lead_silence_ms: int,
    min_slice_ms: int,
    onset_energy_threshold_db: float,
    safety_margin_ms: int,
    g2p_preroll_ms: int,
    boundary_zcr_weight: float,
    phoneme_align_mode: str,
    phoneme_align_fallback_only: bool,
    phoneme_align_remote_url: str,
    phoneme_align_remote_timeout_s: int,
    stage_log: StageLogWriter | None = None,
) -> tuple[list[Path], Path, dict[str, Any]]:
    script = root / "scripts" / "slice-vocals-lrc.py"
    cmd: list[str | Path] = [
        separator_python(),
        script,
        lrc_path,
        vocals,
        "-o",
        output_dir,
        "--song-name",
        project_id,
        "--boundary-mode",
        boundary_mode,
        "--search-margin-ms",
        str(search_margin_ms),
        "--onset-min-lead-silence-ms",
        str(onset_min_lead_silence_ms),
        "--min-slice-ms",
        str(min_slice_ms),
        "--onset-energy-threshold-db",
        str(onset_energy_threshold_db),
        "--safety-margin-ms",
        str(safety_margin_ms),
        "--g2p-preroll-ms",
        str(g2p_preroll_ms),
        "--boundary-zcr-weight",
        str(boundary_zcr_weight),
        "--phoneme-align-mode",
        phoneme_align_mode,
        "--phoneme-align-fallback-only" if phoneme_align_fallback_only else "--no-phoneme-align-fallback-only",
        "--phoneme-align-remote-timeout-s",
        str(phoneme_align_remote_timeout_s),
    ]
    if phoneme_align_remote_url:
        cmd.extend(["--phoneme-align-remote-url", phoneme_align_remote_url])

    def _on_line(line: str) -> None:
        if stage_log and line.strip():
            stage_log.info(line)

    result = run_subprocess(
        cmd,
        cwd=root,
        env=separator_env(),
        on_line=_on_line if stage_log else None,
    )
    if result.returncode != 0:
        raise RuntimeError(_format_subprocess_failure(result, cmd_name="slice-vocals-lrc.py"))

    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"slice subprocess did not write manifest: {manifest_path}")

    meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    written = sorted(output_dir.glob("*.flac"))
    if not written:
        raise RuntimeError("No slices were produced")
    return written, manifest_path, meta


def run_slice(
    project_id: str,
    vocals: Path,
    output_dir: Path,
    *,
    mode: str = SliceMode.VAD.value,
    lrc_path: Path | None = None,
    vad_threshold: float = 0.45,
    min_speech_ms: int = 250,
    min_silence_ms: int = 500,
    speech_pad_ms: int = 80,
    boundary_mode: str = "onset_aligned",
    search_margin_ms: int = 400,
    onset_min_lead_silence_ms: int = 80,
    min_slice_ms: int = 500,
    onset_energy_threshold_db: float = -40.0,
    safety_margin_ms: int = 80,
    g2p_preroll_ms: int = 0,
    boundary_zcr_weight: float = 0.0,
    phoneme_align_mode: str = "off",
    phoneme_align_fallback_only: bool = True,
    phoneme_align_remote_url: str = "",
    phoneme_align_remote_timeout_s: int = 30,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    stage_log: StageLogWriter | None = None,
) -> SliceResult:
    vocals = Path(vocals).resolve()
    output_dir = Path(output_dir).resolve()
    if not vocals.is_file():
        raise FileNotFoundError(f"vocals not found: {vocals}")

    job_id = f"slice-{project_id}"

    def _emit(message: str, percent: float) -> None:
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.SLICE,
                    job_id=job_id,
                    percent=percent,
                    message=message,
                    log_line=None if stage_log else message,
                )
            )

    slice_mode = paths.normalize_slice_mode(mode)
    root = paths.get_root()

    if mode == SliceMode.LRC.value:
        if lrc_path is None:
            raise ValueError("LRC mode requires lrc_path")
        lrc_resolved = Path(lrc_path).resolve()
        if stage_log:
            stage_log.exec_context(
                handler="scripts/slice-vocals-lrc.py",
                mode="lrc",
                lrc_path=rel_path(lrc_resolved, root),
                vocals=rel_path(vocals, root),
                output_dir=rel_path(output_dir, root),
                boundary_mode=boundary_mode,
                search_margin_ms=str(search_margin_ms),
                onset_min_lead_silence_ms=str(onset_min_lead_silence_ms),
                min_slice_ms=str(min_slice_ms),
                onset_energy_threshold_db=str(onset_energy_threshold_db),
                safety_margin_ms=str(safety_margin_ms),
                g2p_preroll_ms=str(g2p_preroll_ms),
                boundary_zcr_weight=str(boundary_zcr_weight),
                phoneme_align_mode=phoneme_align_mode,
                phoneme_align_fallback_only=str(phoneme_align_fallback_only).lower(),
            )
    else:
        if stage_log:
            stage_log.exec_context(
                handler="scripts/slice-vocals.py",
                mode="vad",
                vad_threshold=str(vad_threshold),
                min_speech_ms=str(min_speech_ms),
                min_silence_ms=str(min_silence_ms),
                speech_pad_ms=str(speech_pad_ms),
            )

    _emit("Starting slice", 0.0)

    overrides_path = paths.slices_overrides_path(project_id, slice_mode)
    old_overrides = load_overrides(overrides_path)
    old_manifest_path = output_dir / "manifest.json"
    old_manifest: dict | None = None
    if old_manifest_path.is_file():
        old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))

    if mode == SliceMode.LRC.value:
        if lrc_path is None:
            raise ValueError("LRC mode requires lrc_path")
        lrc_path = Path(lrc_path).resolve()
        lrc_kwargs = {
            "boundary_mode": boundary_mode,
            "search_margin_ms": search_margin_ms,
            "onset_min_lead_silence_ms": onset_min_lead_silence_ms,
            "min_slice_ms": min_slice_ms,
            "onset_energy_threshold_db": onset_energy_threshold_db,
            "safety_margin_ms": safety_margin_ms,
            "g2p_preroll_ms": g2p_preroll_ms,
            "boundary_zcr_weight": boundary_zcr_weight,
            "phoneme_align_mode": phoneme_align_mode,
            "phoneme_align_fallback_only": phoneme_align_fallback_only,
            "phoneme_align_remote_url": phoneme_align_remote_url,
            "phoneme_align_remote_timeout_s": phoneme_align_remote_timeout_s,
        }
        if _phoneme_align_needs_subprocess(phoneme_align_mode):
            if stage_log:
                stage_log.info(
                    "phoneme_align_mode=local_cpu: running slice in separator-env subprocess "
                    "(isolates Torch from API process)"
                )
            written, manifest_path, meta = _run_lrc_slice_subprocess(
                root=root,
                project_id=project_id,
                lrc_path=lrc_path,
                vocals=vocals,
                output_dir=output_dir,
                stage_log=stage_log,
                **lrc_kwargs,
            )
        else:
            mod = _load_script_module("slice_vocals_lrc", "slice-vocals-lrc.py")
            written, manifest_path, meta = mod.slice_vocals_lrc(
                lrc_path,
                vocals,
                output_dir,
                song_name=project_id,
                **lrc_kwargs,
            )
        if stage_log and isinstance(meta, dict):
            _log_lrc_boundaries(
                stage_log,
                meta,
                boundary_mode=boundary_mode,
                search_margin_ms=search_margin_ms,
                onset_min_lead_silence_ms=onset_min_lead_silence_ms,
                min_slice_ms=min_slice_ms,
                onset_energy_threshold_db=onset_energy_threshold_db,
                safety_margin_ms=safety_margin_ms,
                g2p_preroll_ms=g2p_preroll_ms,
                boundary_zcr_weight=boundary_zcr_weight,
                phoneme_align_mode=phoneme_align_mode,
                phoneme_align_fallback_only=phoneme_align_fallback_only,
            )
    else:
        mod = _load_script_module("slice_vocals", "slice-vocals.py")
        written, manifest_path = mod.slice_vocals(
            vocals,
            output_dir,
            threshold=vad_threshold,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )

    count = len(written)
    if count == 0:
        raise RuntimeError("No slices were produced")

    if manifest_path.is_file():
        new_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        merged = merge_after_reslice(
            old_overrides,
            new_manifest,
            mode=slice_mode,
            old_manifest=old_manifest,
        )
        save_overrides(overrides_path, merged)

    _emit("Slice complete", 100.0)
    return SliceResult(slices_dir=output_dir, manifest=manifest_path, slice_count=count)
