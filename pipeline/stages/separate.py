"""Audio separation stage (MelBand-RoFormer via audio-separator)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline import paths
from pipeline.models import ProgressEvent, StageName
from pipeline.venv_runner import ProgressLineCallback, run_subprocess, separator_env, separator_python

DEFAULT_MODEL = "mel_band_roformer_kim_ft_unwa.ckpt"
_PROGRESS_RE = re.compile(r"(\d+)%|Processing|Separating", re.IGNORECASE)


@dataclass
class SeparateResult:
    vocals: Path
    instrumental: Path


def verify_separator_model() -> tuple[bool, str]:
    """Return (ok, message). Uses separator-env python + verify script."""
    root = paths.get_root()
    script = root / "scripts" / "verify-separator-model.py"
    if not script.is_file():
        return False, f"verify script missing: {script}"

    result = run_subprocess(
        [separator_python(), script],
        cwd=root,
        env=separator_env(),
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        return True, output.strip() or "model OK"
    return False, output.strip() or "separator model verification failed"


def run_separate(
    project_id: str,
    mix_audio: Path,
    *,
    model: str = DEFAULT_MODEL,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    on_log_line: ProgressLineCallback | None = None,
) -> SeparateResult:
    """Run audio-separator; outputs land in output/separated/."""
    root = paths.get_root()
    mix_audio = Path(mix_audio).resolve()
    if not mix_audio.is_file():
        raise FileNotFoundError(f"mix audio not found: {mix_audio}")

    ok, msg = verify_separator_model()
    if not ok:
        raise RuntimeError(msg)

    paths.separated_dir().mkdir(parents=True, exist_ok=True)
    model_dir = paths.get_separator_env() / "models" / "audio-separator"
    model_dir.mkdir(parents=True, exist_ok=True)

    job_id = f"separate-{project_id}"
    percent = 0.0

    def _emit(message: str, pct: float | None = None, log_line: str | None = None) -> None:
        nonlocal percent
        if pct is not None:
            percent = pct
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.SEPARATE,
                    job_id=job_id,
                    percent=percent,
                    message=message,
                    log_line=log_line,
                )
            )

    def _line_handler(line: str) -> None:
        if on_log_line:
            on_log_line(line)
        match = _PROGRESS_RE.search(line)
        if match and match.group(1):
            _emit(line, float(match.group(1)), line)
        else:
            _emit(line, None, line)

    _emit(f"Separating {mix_audio.name}", 0.0)

    cmd = [
        "audio-separator",
        str(mix_audio),
        "--model_filename",
        model,
        "--model_file_dir",
        str(model_dir),
        "--output_format",
        "flac",
        "--output_dir",
        str(paths.separated_dir()),
    ]

    # On Windows, invoke via separator python -m if audio-separator not directly callable
    result = run_subprocess(cmd, cwd=root, env=separator_env(), on_line=_line_handler)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()
        raise RuntimeError(f"audio-separator failed (code {result.returncode}): {detail}")

    vocals = paths.separated_vocals_path(project_id)
    instrumental = paths.separated_instrumental_path(project_id)

    # Fallback: glob by stem of input file
    if vocals is None:
        stem = mix_audio.stem
        vocals = paths.separated_vocals_path(stem)
        instrumental = paths.separated_instrumental_path(stem)

    if vocals is None or instrumental is None:
        raise RuntimeError(
            "Separation finished but vocals/instrumental outputs were not found in output/separated/"
        )

    _emit("Separation complete", 100.0)
    return SeparateResult(vocals=vocals, instrumental=instrumental)
