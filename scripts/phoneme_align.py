"""Phoneme-level boundary refinement (P2 local CPU, P4 remote stub)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

SCRIPT_DIR = __import__("pathlib").Path(__file__).resolve().parent

_ALIGNMENT_MODEL = None
_ALIGNMENT_TOKENIZER = None


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


def _load_alignment_model():
    global _ALIGNMENT_MODEL, _ALIGNMENT_TOKENIZER
    if _ALIGNMENT_MODEL is not None:
        return _ALIGNMENT_MODEL, _ALIGNMENT_TOKENIZER

    import torch
    from ctc_forced_aligner import load_alignment_model

    device = "cpu"
    dtype = torch.float32
    model, tokenizer = load_alignment_model(device, dtype=dtype)
    _ALIGNMENT_MODEL = model
    _ALIGNMENT_TOKENIZER = tokenizer
    return model, tokenizer


def align_boundary_local(
    audio: np.ndarray,
    sr: int,
    text: str,
    window_start_ms: float,
    window_end_ms: float,
) -> float | None:
    """Return absolute onset ms for first aligned character, or None on failure."""
    text = text.strip()
    if not text:
        return None

    start_sample = _ms_to_sample(window_start_ms, sr)
    end_sample = min(_ms_to_sample(window_end_ms, sr), len(audio))
    if end_sample <= start_sample:
        return None

    segment = audio[start_sample:end_sample].astype(np.float32, copy=False)
    if segment.size == 0:
        return None

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
        return None

    try:
        model, tokenizer = _load_alignment_model()
        wav = torch.from_numpy(segment).unsqueeze(0)
        emissions, stride = generate_emissions(model, wav, batch_size=1)
        tokens_starred, text_starred = preprocess_text(
            text,
            romanize=True,
            language="zho",
            split_size="char",
        )
        segments, scores, blank_token = get_alignments(emissions, tokens_starred, tokenizer)
        spans = get_spans(tokens_starred, segments, blank_token)
        word_ts = postprocess_results(text_starred, spans, stride, scores)
    except Exception:
        return None

    if not word_ts:
        return None

    first = word_ts[0]
    start_s = float(getattr(first, "start", first.get("start", 0) if isinstance(first, dict) else 0))
    onset_ms = window_start_ms + start_s * 1000.0
    return onset_ms


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

    onset_ms = align_boundary_local(
        audio,
        sr,
        next_line_text,
        window_start_ms,
        window_end_ms,
    )
    if onset_ms is None:
        return PhonemeAlignResult(skipped=True, reason="phoneme_align_error")

    return PhonemeAlignResult(
        onset_ms=onset_ms,
        skipped=False,
        reason="phoneme_local",
        method="phoneme_local",
    )
