"""Phoneme-level boundary refinement (P2 local CPU, P4 remote stub)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = SCRIPT_DIR.parent
# Same layout as scripts/slice-vocals.bat and pipeline/venv_runner.separator_env().
_HF_HOME = _REPO_ROOT / "separator-env" / "models" / "hf-cache"
_HF_HOME.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_HF_HOME))
# Windows + CUDA-build Torch on CPU: multi-thread BLAS during boundary detect then
# inference can ACCESS_VIOLATION. Limit threads before any torch import.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_ALIGNMENT_MODEL = None
_ALIGNMENT_TOKENIZER = None
_TORCH_CONFIGURED = False


def _configure_torch_cpu() -> None:
    global _TORCH_CONFIGURED
    if _TORCH_CONFIGURED:
        return
    try:
        import torch

        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
    except ImportError:
        pass
    _TORCH_CONFIGURED = True


class PhonemeAlignMode(str, Enum):
    OFF = "off"
    LOCAL_CPU = "local_cpu"
    REMOTE = "remote"


@dataclass(frozen=True)
class PhonemeAlignResult:
    onset_ms: float | None = None
    skipped: bool = False
    reason: str = ""
    message: str = ""
    method: str = ""


def _ms_to_sample(ms: float, sr: int) -> int:
    return max(int(ms / 1000 * sr), 0)


def _reset_alignment_model() -> None:
    global _ALIGNMENT_MODEL, _ALIGNMENT_TOKENIZER
    _ALIGNMENT_MODEL = None
    _ALIGNMENT_TOKENIZER = None


def preload_alignment_model() -> None:
    """Load MMS model once before boundary loop (avoids load mid numpy/torch mix)."""
    _configure_torch_cpu()
    _load_alignment_model()


def _load_alignment_model():
    global _ALIGNMENT_MODEL, _ALIGNMENT_TOKENIZER
    if _ALIGNMENT_MODEL is not None:
        return _ALIGNMENT_MODEL, _ALIGNMENT_TOKENIZER

    _configure_torch_cpu()
    import torch
    from ctc_forced_aligner import load_alignment_model

    device = "cpu"
    dtype = torch.float32
    model, tokenizer = load_alignment_model(device, dtype=dtype)
    model.eval()
    _ALIGNMENT_MODEL = model
    _ALIGNMENT_TOKENIZER = tokenizer
    return model, tokenizer


def _resample_to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return audio.astype(np.float32, copy=False)
    import torch
    import torchaudio.functional as F

    wav = torch.from_numpy(audio.astype(np.float32, copy=False))
    out = F.resample(wav, sr, 16000)
    return out.numpy()


def align_boundary_local(
    audio: np.ndarray,
    sr: int,
    text: str,
    window_start_ms: float,
    window_end_ms: float,
) -> tuple[float | None, str]:
    """Return (absolute onset ms, skip reason). skip reason is empty on success."""
    return _align_boundary_local_impl(
        audio, sr, text, window_start_ms, window_end_ms, split_size="char"
    )


def _align_boundary_local_impl(
    audio: np.ndarray,
    sr: int,
    text: str,
    window_start_ms: float,
    window_end_ms: float,
    *,
    split_size: str,
) -> tuple[float | None, str]:
    text = text.strip()
    if not text:
        return None, "phoneme_align_empty_text"

    start_sample = _ms_to_sample(window_start_ms, sr)
    end_sample = min(_ms_to_sample(window_end_ms, sr), len(audio))
    if end_sample <= start_sample:
        return None, "phoneme_align_invalid_window"

    segment = audio[start_sample:end_sample].astype(np.float32, copy=False)
    if segment.size == 0:
        return None, "phoneme_align_invalid_window"

    segment = _resample_to_16k(segment, sr)

    _configure_torch_cpu()
    try:
        import torch
        from ctc_forced_aligner import (
            generate_emissions,
            get_alignments,
            get_spans,
            postprocess_results,
            preprocess_text,
        )
    except ImportError:
        return None, "phoneme_align_import_error"

    try:
        model, tokenizer = _load_alignment_model()
        wav = torch.from_numpy(segment)
        with torch.inference_mode():
            emissions, stride = generate_emissions(model, wav, batch_size=1)
            tokens_starred, text_starred = preprocess_text(
                text,
                romanize=True,
                language="zho",
                split_size=split_size,
            )
            segments, scores, blank_token = get_alignments(emissions, tokens_starred, tokenizer)
            spans = get_spans(tokens_starred, segments, blank_token)
            word_ts = postprocess_results(text_starred, spans, stride, scores)
    except AssertionError:
        return None, "phoneme_align_ctc_mismatch"
    except Exception as exc:
        if "targets length is too long" in str(exc):
            return None, "phoneme_align_ctc_window_too_short"
        return None, "phoneme_align_failed"

    if not word_ts:
        return None, "phoneme_align_no_timestamps"

    first = word_ts[0]
    start_s = float(getattr(first, "start", first.get("start", 0) if isinstance(first, dict) else 0))
    onset_ms = window_start_ms + start_s * 1000.0
    return onset_ms, ""


def align_boundary_local_with_retries(
    audio: np.ndarray,
    sr: int,
    text: str,
    window_start_ms: float,
    window_end_ms: float,
) -> tuple[float | None, str]:
    """Retry with wider window / alternate tokenization on CTC mismatch."""
    attempts: list[tuple[float, float, str]] = [
        (window_start_ms, window_end_ms, "char"),
        (max(0.0, window_start_ms - 80.0), window_end_ms + 80.0, "char"),
        (max(0.0, window_start_ms - 150.0), window_end_ms + 150.0, "word"),
    ]
    last_reason = "phoneme_align_failed"
    for ws, we, split_size in attempts:
        onset_ms, reason = _align_boundary_local_impl(
            audio, sr, text, ws, we, split_size=split_size
        )
        if onset_ms is not None:
            return onset_ms, ""
        last_reason = reason or last_reason
        if reason not in (
            "phoneme_align_ctc_mismatch",
            "phoneme_align_no_timestamps",
            "phoneme_align_ctc_window_too_short",
        ):
            break
    return None, last_reason


def _separator_python() -> Path:
    exe = _REPO_ROOT / "separator-env" / "Scripts" / "python.exe"
    if exe.is_file():
        return exe
    return Path(sys.executable)


def _worker_env() -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["HTTP_PROXY"] = ""
    env["HTTPS_PROXY"] = ""
    env["ALL_PROXY"] = ""
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env.setdefault("HF_HOME", str(_HF_HOME))
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("CUDA_VISIBLE_DEVICES", "")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    env.setdefault("TRANSFORMERS_VERBOSITY", "error")
    return env


def run_phoneme_align_subprocess(
    vocals_path: Path,
    jobs: list[dict[str, object]],
    *,
    timeout_s: int = 300,
) -> list[dict[str, object]]:
    """Run align jobs in a fresh separator-env subprocess (one or more boundaries)."""
    import json
    import subprocess
    import tempfile

    if not jobs:
        return []

    script = SCRIPT_DIR / "phoneme-align-worker.py"
    python = _separator_python()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(jobs, tmp, ensure_ascii=False)
        jobs_path = Path(tmp.name)

    try:
        proc = subprocess.run(
            [str(python), str(script), str(vocals_path), str(jobs_path)],
            cwd=str(_REPO_ROOT),
            env=_worker_env(),
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    finally:
        jobs_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode in (-1073741819, 3221225477):
            raise RuntimeError(
                f"phoneme-align-worker native crash (exit={proc.returncode}): {detail[-500:]}"
            )
        raise RuntimeError(
            f"phoneme-align-worker exit={proc.returncode}: {detail[-500:]}"
        )

    payload = json.loads(proc.stdout.strip())
    results = payload.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"phoneme-align-worker invalid output: {proc.stdout[:200]}")
    return results


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def inter_boundary_delay_s() -> float:
    """Pause after each phoneme worker exits (Windows Torch stability)."""
    return max(0.0, _env_float("PHONEME_ALIGN_INTER_BOUNDARY_DELAY_S", 0.25))


def crash_retry_delay_s() -> float:
    """Pause before re-launching worker after native crash."""
    return max(0.0, _env_float("PHONEME_ALIGN_CRASH_RETRY_DELAY_S", 1.0))


def crash_retry_count() -> int:
    return max(1, _env_int("PHONEME_ALIGN_CRASH_RETRIES", 3))


def align_text_snippet(line_text: str, *, mode: str = "first_char") -> str:
    """Text fed to CTC aligner. Default: first non-space character of next line."""
    text = line_text.strip()
    if not text:
        return ""
    if mode == "full":
        return text
    if mode == "first_word":
        parts = text.split()
        if parts:
            return parts[0]
    for ch in text:
        if not ch.isspace():
            return ch
    return ""


def sleep_inter_boundary_delay(delay_s: float | None = None) -> None:
    import time

    wait = inter_boundary_delay_s() if delay_s is None else max(0.0, delay_s)
    if wait > 0:
        time.sleep(wait)


def sleep_crash_retry_delay(delay_s: float | None = None) -> None:
    import time

    wait = crash_retry_delay_s() if delay_s is None else max(0.0, delay_s)
    if wait > 0:
        time.sleep(wait)


def default_subprocess_batch_size() -> int:
    raw = os.environ.get("PHONEME_ALIGN_SUBPROCESS_BATCH", "1")
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def refine_boundary(
    *,
    mode: str,
    audio: np.ndarray,
    sr: int,
    next_line_text: str,
    window_start_ms: float,
    window_end_ms: float,
    fallback: bool,
    fallback_only: bool = True,
    remote_url: str = "",
    remote_timeout_s: int = 30,
) -> PhonemeAlignResult:
    if mode == PhonemeAlignMode.OFF.value or not mode:
        return PhonemeAlignResult(skipped=True, reason="disabled")

    if mode == PhonemeAlignMode.REMOTE.value:
        if not remote_url:
            return PhonemeAlignResult(
                skipped=True,
                reason="remote_url_missing",
                message="phoneme_align_mode=remote requires phoneme_align_remote_url",
            )
        return PhonemeAlignResult(
            skipped=True,
            reason="remote_not_implemented",
            message="phoneme_align_mode=remote is reserved; use local_cpu or off",
        )

    if mode != PhonemeAlignMode.LOCAL_CPU.value:
        return PhonemeAlignResult(skipped=True, reason="unknown_mode", message=f"unknown mode: {mode}")

    if fallback_only and not fallback:
        return PhonemeAlignResult(skipped=True, reason="not_fallback_boundary")

    align_text = align_text_snippet(next_line_text)
    onset_ms, align_skip_reason = align_boundary_local_with_retries(
        audio,
        sr,
        align_text,
        window_start_ms,
        window_end_ms,
    )
    if onset_ms is None:
        return PhonemeAlignResult(
            skipped=True,
            reason=align_skip_reason or "phoneme_align_error",
        )

    return PhonemeAlignResult(
        onset_ms=onset_ms,
        skipped=False,
        reason="phoneme_local",
        method="phoneme_local",
    )
