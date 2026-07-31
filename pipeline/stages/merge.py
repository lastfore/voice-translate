"""Merge vocals with instrumental backing track."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline import paths
from pipeline.models import ProgressEvent, StageName

if TYPE_CHECKING:
    from pipeline.stage_log import StageLogWriter


@dataclass
class MergeResult:
    vocals: Path
    mixed: Path
    merged_dir: Path


def _load_merge_module():
    root = paths.get_root()
    script_path = root / "scripts" / "merge-audio.py"
    spec = importlib.util.spec_from_file_location("merge_audio_script", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["merge_audio_script"] = module
    spec.loader.exec_module(module)
    return module


def run_merge(
    project_id: str,
    vocals: Path,
    instrumental: Path,
    output_dir: Path,
    *,
    profile: str = "full",
    reference: Path | None = None,
    original_vocals: Path | None = None,
    manifest: Path | None = None,
    slices_dir: Path | None = None,
    clean_instrumental: bool = False,
    vocals_gain_db: float = 0.0,
    instrumental_gain_db: float = 0.0,
    backing_vocals: Path | None = None,
    backing_gain_db: float = 0.0,
    include_backing: bool = True,
    skip_mastering: bool = False,
    boundary_crossfade_ms: int = 0,
    boundary_crossfade_curve: str = "equal_power",
    boundary_zero_crossing: bool = True,
    boundary_lufs_match_ms: int = 0,
    splice_wsola_search_ms: int = 0,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    stage_log: StageLogWriter | None = None,
) -> MergeResult:
    vocals = Path(vocals).resolve()
    instrumental = Path(instrumental).resolve()
    output_dir = Path(output_dir).resolve()

    if not vocals.exists():
        raise FileNotFoundError(f"vocals not found: {vocals}")
    if not instrumental.is_file():
        raise FileNotFoundError(f"instrumental not found: {instrumental}")

    job_id = f"merge-{project_id}"

    def _emit(message: str, percent: float) -> None:
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.MERGE,
                    job_id=job_id,
                    percent=percent,
                    message=message,
                    log_line=None if stage_log else message,
                )
            )

    if stage_log:
        stage_log.exec_context(
            handler="scripts/merge-audio.py",
            profile=profile,
            clean_instrumental=str(clean_instrumental).lower(),
            skip_mastering=str(skip_mastering).lower(),
            vocals_gain_db=str(vocals_gain_db),
            instrumental_gain_db=str(instrumental_gain_db),
            boundary_crossfade_ms=str(boundary_crossfade_ms),
            boundary_crossfade_curve=boundary_crossfade_curve,
            boundary_zero_crossing=str(boundary_zero_crossing).lower(),
            boundary_lufs_match_ms=str(boundary_lufs_match_ms),
            splice_wsola_search_ms=str(splice_wsola_search_ms),
            backing_vocals=str(backing_vocals) if backing_vocals else "",
            backing_gain_db=str(backing_gain_db),
            include_backing=str(include_backing).lower(),
        )

    _emit(f"Merging with profile={profile}", 5.0)
    merge_mod = _load_merge_module()
    splice = merge_mod.SpliceParams(
        boundary_crossfade_ms=boundary_crossfade_ms,
        boundary_crossfade_curve=boundary_crossfade_curve,
        boundary_zero_crossing=boundary_zero_crossing,
        boundary_lufs_match_ms=boundary_lufs_match_ms,
        splice_wsola_search_ms=splice_wsola_search_ms,
    )

    def _karaoke_line(line: str) -> None:
        if stage_log:
            stage_log.line(line)
        else:
            _emit(line, 45.0)

    vocals_out, mixed_out = merge_mod.merge_audio(
        vocals,
        instrumental,
        output_dir,
        profile_name=profile,
        reference=reference.resolve() if reference else None,
        original_vocals=original_vocals.resolve() if original_vocals else None,
        manifest=manifest.resolve() if manifest else None,
        slices_dir=slices_dir.resolve() if slices_dir else None,
        clean_instrumental_flag=clean_instrumental,
        vocals_gain_db=vocals_gain_db,
        instrumental_gain_db=instrumental_gain_db,
        backing_vocals=backing_vocals.resolve() if backing_vocals else None,
        backing_gain_db=backing_gain_db,
        include_backing=include_backing,
        skip_mastering=skip_mastering,
        on_line=_karaoke_line,
        splice=splice,
    )
    _emit("Merge complete", 100.0)
    return MergeResult(vocals=vocals_out, mixed=mixed_out, merged_dir=output_dir)
