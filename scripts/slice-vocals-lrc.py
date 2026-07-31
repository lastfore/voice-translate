"""Slice vocal FLAC by LRC lyric timestamps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from lrc_g2p_preroll import lookup_preroll_ms
from phoneme_align import (
    PhonemeAlignMode,
    PhonemeAlignResult,
    align_text_snippet,
    crash_retry_count,
    crash_retry_delay_s,
    inter_boundary_delay_s,
    refine_boundary,
    run_phoneme_align_subprocess,
    sleep_crash_retry_delay,
    sleep_inter_boundary_delay,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SLICES_ROOT = ROOT / "output" / "slices"

FADE_IN_MS = 8
FADE_OUT_MS = 15

DEFAULT_BOUNDARY_MODE = "onset_aligned"
DEFAULT_SEARCH_MARGIN_MS = 400
DEFAULT_ONSET_MIN_LEAD_SILENCE_MS = 80
DEFAULT_MIN_SLICE_MS = 500
DEFAULT_ONSET_ENERGY_THRESHOLD_DB = -40.0
DEFAULT_SAFETY_MARGIN_MS = 80
RMS_FRAME_MS = 10

# [mm:ss.xx] or [mm:ss.xxx]
LRC_LINE_RE = re.compile(r"^\[(\d+):(\d{2})\.(\d{2,3})\](.*)$")
LRC_TAG_RE = re.compile(r"^\[[a-zA-Z]+:.+\]$")
METADATA_TEXT_RE = re.compile(
    r"^(曲|词|编曲|制作|监制|混音|录音|母带|演唱|歌手|专辑|出品)[:：]"
)
OFFSET_RE = re.compile(r"^\[offset:\s*(-?\d+)\s*\]$", re.IGNORECASE)


@dataclass(frozen=True)
class LrcLine:
    start_ms: float
    text: str
    line_no: int


@dataclass(frozen=True)
class BoundaryParams:
    boundary_mode: str = DEFAULT_BOUNDARY_MODE
    search_margin_ms: int = DEFAULT_SEARCH_MARGIN_MS
    onset_min_lead_silence_ms: int = DEFAULT_ONSET_MIN_LEAD_SILENCE_MS
    min_slice_ms: int = DEFAULT_MIN_SLICE_MS
    onset_energy_threshold_db: float = DEFAULT_ONSET_ENERGY_THRESHOLD_DB
    safety_margin_ms: int = DEFAULT_SAFETY_MARGIN_MS
    g2p_preroll_ms: int = 0
    boundary_zcr_weight: float = 0.0
    phoneme_align_mode: str = PhonemeAlignMode.OFF.value
    phoneme_align_fallback_only: bool = True
    phoneme_align_remote_url: str = ""
    phoneme_align_remote_timeout_s: int = 30
    phoneme_align_inter_delay_s: float = -1.0
    phoneme_align_crash_retry_delay_s: float = -1.0
    phoneme_align_crash_retries: int = -1


@dataclass(frozen=True)
class BoundaryDetectionResult:
    t_cut: float
    fallback: bool
    reason: str
    method: str = "lrc_strict"
    safety_margin_applied_ms: int = 0

    @property
    def aligned(self) -> bool:
        return not self.fallback


@dataclass(frozen=True)
class BoundaryDiagnostic:
    boundary_index: int
    next_slice_id: str
    next_lrc_ms: float
    t_cut_ms: float
    aligned: bool
    reason: str
    method: str
    delta_ms: float
    safety_margin_applied_ms: int = 0
    g2p_preroll_ms_used: float = 0.0
    phoneme_align_applied: bool = False
    phoneme_align_skip_reason: str = ""


def apply_fade(audio: np.ndarray, sr: int, fade_in_ms: int, fade_out_ms: int) -> np.ndarray:
    if audio.size == 0:
        return audio

    out = audio.astype(np.float32, copy=True)
    fade_in = min(int(sr * fade_in_ms / 1000), max(out.shape[0] // 4, 1))
    fade_out = min(int(sr * fade_out_ms / 1000), max(out.shape[0] // 4, 1))

    if fade_in > 0:
        out[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out > 0:
        out[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)

    return out


def parse_lrc_timestamp(minutes: str, seconds: str, fraction: str) -> float:
    frac = int(fraction)
    if len(fraction) == 2:
        frac_ms = frac * 10
    else:
        frac_ms = frac
    return (int(minutes) * 60 + int(seconds)) * 1000 + frac_ms


def is_metadata_line(text: str, start_ms: float) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if METADATA_TEXT_RE.match(stripped):
        return True
    # Common title line: [00:00.00]Song - Artist
    if start_ms == 0 and " - " in stripped:
        return True
    return False


def read_lrc_text(lrc_path: Path) -> str:
    raw = lrc_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {lrc_path}; expected UTF-8 or GBK")


def parse_lrc(lrc_path: Path) -> tuple[list[LrcLine], int]:
    offset_ms = 0
    raw_lines: list[LrcLine] = []

    for line_no, raw in enumerate(read_lrc_text(lrc_path).splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        offset_match = OFFSET_RE.match(line)
        if offset_match:
            offset_ms = int(offset_match.group(1))
            continue

        if LRC_TAG_RE.match(line):
            continue

        match = LRC_LINE_RE.match(line)
        if not match:
            continue

        minutes, seconds, fraction, text = match.groups()
        start_ms = parse_lrc_timestamp(minutes, seconds, fraction) + offset_ms
        raw_lines.append(LrcLine(start_ms=start_ms, text=text.strip(), line_no=line_no))

    lyrics = [item for item in raw_lines if not is_metadata_line(item.text, item.start_ms)]
    if not lyrics:
        raise ValueError(f"No lyric lines found in {lrc_path}")

    return lyrics, offset_ms


def _ms_to_sample(ms: float, sr: int) -> int:
    return max(int(ms / 1000 * sr), 0)


def compute_rms_envelope(
    audio: np.ndarray,
    sr: int,
    start_ms: float,
    end_ms: float,
    *,
    frame_ms: int = RMS_FRAME_MS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (times_ms, rms) for half-overlapped frames inside [start_ms, end_ms]."""
    start_sample = _ms_to_sample(start_ms, sr)
    end_sample = min(_ms_to_sample(end_ms, sr), len(audio))
    if end_sample <= start_sample:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    segment = audio[start_sample:end_sample].astype(np.float64, copy=False)
    frame_samples = max(int(sr * frame_ms / 1000), 1)
    hop_samples = max(frame_samples // 2, 1)
    if segment.size < frame_samples:
        rms = np.array([float(np.sqrt(np.mean(segment**2)))], dtype=np.float64)
        times = np.array([start_ms], dtype=np.float64)
        return times, rms

    rms_values: list[float] = []
    time_values: list[float] = []
    for offset in range(0, segment.size - frame_samples + 1, hop_samples):
        frame = segment[offset : offset + frame_samples]
        rms_values.append(float(np.sqrt(np.mean(frame**2))))
        center_sample = start_sample + offset + frame_samples // 2
        time_values.append(center_sample / sr * 1000)

    return np.array(time_values, dtype=np.float64), np.array(rms_values, dtype=np.float64)


def compute_zcr_envelope(
    audio: np.ndarray,
    sr: int,
    start_ms: float,
    end_ms: float,
    *,
    frame_ms: int = RMS_FRAME_MS,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (times_ms, zcr) aligned with RMS frame centers in [start_ms, end_ms]."""
    start_sample = _ms_to_sample(start_ms, sr)
    end_sample = min(_ms_to_sample(end_ms, sr), len(audio))
    if end_sample <= start_sample:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    segment = audio[start_sample:end_sample]
    frame_samples = max(int(sr * frame_ms / 1000), 1)
    hop_samples = max(frame_samples // 2, 1)
    if segment.size < frame_samples:
        return np.array([start_ms], dtype=np.float64), np.array([0.0], dtype=np.float64)

    zcr_values: list[float] = []
    time_values: list[float] = []
    for offset in range(0, segment.size - frame_samples + 1, hop_samples):
        frame = segment[offset : offset + frame_samples]
        signs = np.sign(frame)
        signs[signs == 0] = 1
        crossings = int(np.sum(signs[1:] != signs[:-1]))
        zcr_values.append(crossings / max(len(frame) - 1, 1))
        center_sample = start_sample + offset + frame_samples // 2
        time_values.append(center_sample / sr * 1000)

    return np.array(time_values, dtype=np.float64), np.array(zcr_values, dtype=np.float64)


def _detect_legato_onset(
    times: np.ndarray,
    envelope: np.ndarray,
    threshold: float,
) -> float | None:
    """Pick the steepest energy rise above threshold; tie-break toward later frames."""
    if len(envelope) < 2:
        return None

    best_idx: int | None = None
    best_slope = -1.0
    for idx in range(1, len(envelope)):
        if envelope[idx] < threshold:
            continue
        slope = float(envelope[idx] - envelope[idx - 1])
        if slope > best_slope or (slope == best_slope and (best_idx is None or idx > best_idx)):
            best_slope = slope
            best_idx = idx

    if best_idx is None:
        return None
    return float(times[best_idx])


def _detect_energy_valley(
    times: np.ndarray,
    envelope: np.ndarray,
    threshold: float,
    valley_window_start_ms: float,
    *,
    zcr: np.ndarray | None = None,
    zcr_weight: float = 0.0,
) -> float | None:
    """Pick the best valley frame below threshold; optional ZCR joint scoring."""
    mask = times >= valley_window_start_ms
    if not np.any(mask):
        return None

    indices = np.where(mask)[0]
    candidates = [int(idx) for idx in indices if envelope[idx] < threshold]
    if not candidates:
        return None

    if zcr_weight > 0 and zcr is not None and len(zcr) == len(envelope):
        e_vals = np.array([float(envelope[idx]) for idx in candidates], dtype=np.float64)
        z_vals = np.array([float(zcr[idx]) for idx in candidates], dtype=np.float64)
        e_min, e_max = float(np.min(e_vals)), float(np.max(e_vals))
        z_min, z_max = float(np.min(z_vals)), float(np.max(z_vals))
        e_norm = (e_vals - e_min) / (e_max - e_min + 1e-12)
        z_norm = (z_vals - z_min) / (z_max - z_min + 1e-12)
        scores = e_norm + zcr_weight * z_norm
        best_local = int(np.argmin(scores))
        best_idx = candidates[best_local]
        min_score = float(scores[best_local])
        tied = [idx for idx, score in zip(candidates, scores) if float(score) == min_score]
        best_idx = min(tied)
        return float(times[best_idx])

    min_rms = min(float(envelope[idx]) for idx in candidates)
    best_idx = min(idx for idx in candidates if float(envelope[idx]) == min_rms)
    return float(times[best_idx])


def _apply_safety_margin(
    t_cut: float,
    *,
    next_lrc_ts: float,
    line_start_ms: float,
    next_line_end_ms: float,
    min_slice_ms: int,
    safety_margin_ms: int,
    is_fallback: bool,
) -> tuple[float, int, str]:
    """Return (t_cut, applied_ms, reason_suffix)."""
    if not is_fallback or safety_margin_ms <= 0:
        return t_cut, 0, ""

    candidate = next_lrc_ts - safety_margin_ms
    if (candidate - line_start_ms) < min_slice_ms:
        return next_lrc_ts, 0, "safety_margin_skipped"
    if (next_line_end_ms - candidate) < min_slice_ms:
        return next_lrc_ts, 0, "safety_margin_skipped"

    return candidate, safety_margin_ms, ""


def _make_fallback_result(
    reason: str,
    *,
    next_lrc_ts: float,
    line_start_ms: float,
    next_line_end_ms: float,
    min_slice_ms: int,
    safety_margin_ms: int,
) -> BoundaryDetectionResult:
    t_cut, applied_ms, suffix = _apply_safety_margin(
        next_lrc_ts,
        next_lrc_ts=next_lrc_ts,
        line_start_ms=line_start_ms,
        next_line_end_ms=next_line_end_ms,
        min_slice_ms=min_slice_ms,
        safety_margin_ms=safety_margin_ms,
        is_fallback=True,
    )
    full_reason = f"{reason} {suffix}".strip() if suffix else reason
    method = "lrc_fallback_margin" if applied_ms > 0 else "lrc_fallback"
    return BoundaryDetectionResult(
        t_cut=t_cut,
        fallback=True,
        reason=full_reason,
        method=method,
        safety_margin_applied_ms=applied_ms,
    )


def _apply_min_slice_guard(
    best_t: float,
    *,
    line_start_ms: float,
    next_lrc_ts: float,
    next_line_end_ms: float,
    min_slice_ms: int,
    safety_margin_ms: int,
    method: str,
) -> BoundaryDetectionResult:
    if (best_t - line_start_ms) < min_slice_ms:
        return _make_fallback_result(
            "current_slice_too_short",
            next_lrc_ts=next_lrc_ts,
            line_start_ms=line_start_ms,
            next_line_end_ms=next_line_end_ms,
            min_slice_ms=min_slice_ms,
            safety_margin_ms=safety_margin_ms,
        )
    if (next_line_end_ms - best_t) < min_slice_ms:
        return _make_fallback_result(
            "next_slice_too_short",
            next_lrc_ts=next_lrc_ts,
            line_start_ms=line_start_ms,
            next_line_end_ms=next_line_end_ms,
            min_slice_ms=min_slice_ms,
            safety_margin_ms=safety_margin_ms,
        )
    return BoundaryDetectionResult(
        t_cut=best_t,
        fallback=False,
        reason=f"aligned_{method}",
        method=f"{method}_onset",
    )


def detect_boundary(
    audio: np.ndarray,
    sr: int,
    *,
    line_start_ms: float,
    next_lrc_ts: float,
    next_line_end_ms: float,
    next_line_text: str = "",
    search_margin_ms: int = DEFAULT_SEARCH_MARGIN_MS,
    onset_min_lead_silence_ms: int = DEFAULT_ONSET_MIN_LEAD_SILENCE_MS,
    min_slice_ms: int = DEFAULT_MIN_SLICE_MS,
    onset_energy_threshold_db: float = DEFAULT_ONSET_ENERGY_THRESHOLD_DB,
    safety_margin_ms: int = DEFAULT_SAFETY_MARGIN_MS,
    g2p_preroll_ms: int = 0,
    boundary_zcr_weight: float = 0.0,
) -> tuple[BoundaryDetectionResult, float]:
    """Detect aligned cut point between adjacent lyric lines."""
    g2p_used = 0.0
    lookback_ms = search_margin_ms
    if g2p_preroll_ms > 0 and next_line_text.strip():
        pre_roll = lookup_preroll_ms(next_line_text, g2p_preroll_ms)
        if pre_roll > 0:
            g2p_used = pre_roll
            lookback_ms = max(search_margin_ms, int(pre_roll))
    window_start_ms = max(line_start_ms + min_slice_ms, next_lrc_ts - lookback_ms)
    window_end_ms = next_lrc_ts

    if window_end_ms <= window_start_ms:
        return (
            _make_fallback_result(
                "window_empty",
                next_lrc_ts=next_lrc_ts,
                line_start_ms=line_start_ms,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=min_slice_ms,
                safety_margin_ms=safety_margin_ms,
            ),
            g2p_used,
        )

    times, envelope = compute_rms_envelope(audio, sr, window_start_ms, window_end_ms)
    if envelope.size == 0:
        return (
            _make_fallback_result(
                "envelope_empty",
                next_lrc_ts=next_lrc_ts,
                line_start_ms=line_start_ms,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=min_slice_ms,
                safety_margin_ms=safety_margin_ms,
            ),
            g2p_used,
        )

    zcr = None
    if boundary_zcr_weight > 0:
        z_times, zcr = compute_zcr_envelope(audio, sr, window_start_ms, window_end_ms)
        if len(z_times) != len(times):
            zcr = None

    peak = float(np.max(envelope))
    if peak <= 1e-12:
        return (
            _make_fallback_result(
                "silent_window",
                next_lrc_ts=next_lrc_ts,
                line_start_ms=line_start_ms,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=min_slice_ms,
                safety_margin_ms=safety_margin_ms,
            ),
            g2p_used,
        )

    threshold = peak * (10.0 ** (onset_energy_threshold_db / 20.0))
    valley_window_start_ms = window_start_ms + (window_end_ms - window_start_ms) * 0.5
    valley_t = _detect_energy_valley(
        times,
        envelope,
        threshold,
        valley_window_start_ms,
        zcr=zcr,
        zcr_weight=boundary_zcr_weight,
    )
    if valley_t is not None:
        return (
            _apply_min_slice_guard(
                valley_t,
                line_start_ms=line_start_ms,
                next_lrc_ts=next_lrc_ts,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=min_slice_ms,
                safety_margin_ms=safety_margin_ms,
                method="valley",
            ),
            g2p_used,
        )

    lead_frames = max(int(round(onset_min_lead_silence_ms / RMS_FRAME_MS)), 1)

    best_t: float | None = None
    for idx in range(len(envelope) - 1, lead_frames - 1, -1):
        if envelope[idx] < threshold:
            continue
        lead_slice = envelope[idx - lead_frames : idx]
        if lead_slice.size < lead_frames or np.any(lead_slice >= threshold):
            continue
        best_t = float(times[idx])
        break

    if best_t is None:
        legato_t = _detect_legato_onset(times, envelope, threshold)
        if legato_t is None:
            return (
                _make_fallback_result(
                    "no_onset_candidate",
                    next_lrc_ts=next_lrc_ts,
                    line_start_ms=line_start_ms,
                    next_line_end_ms=next_line_end_ms,
                    min_slice_ms=min_slice_ms,
                    safety_margin_ms=safety_margin_ms,
                ),
                g2p_used,
            )
        return (
            _apply_min_slice_guard(
                legato_t,
                line_start_ms=line_start_ms,
                next_lrc_ts=next_lrc_ts,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=min_slice_ms,
                safety_margin_ms=safety_margin_ms,
                method="legato",
            ),
            g2p_used,
        )

    return (
        _apply_min_slice_guard(
            best_t,
            line_start_ms=line_start_ms,
            next_lrc_ts=next_lrc_ts,
            next_line_end_ms=next_line_end_ms,
            min_slice_ms=min_slice_ms,
            safety_margin_ms=safety_margin_ms,
            method="silence",
        ),
        g2p_used,
    )


def compute_boundaries(
    lyrics: list[LrcLine],
    audio: np.ndarray,
    sr: int,
    duration_ms: float,
    params: BoundaryParams,
    *,
    vocals_path: Path | None = None,
) -> tuple[list[float], list[bool], list[BoundaryDiagnostic], int, int, dict[str, int]]:
    """Return aligned start_ms per slice, entry-boundary fallback flags, and diagnostics."""
    n = len(lyrics)
    starts = [lyrics[0].start_ms]
    fallbacks = [False]
    diagnostics: list[BoundaryDiagnostic] = []
    phoneme_applied_count = 0
    phoneme_skipped_remote_count = 0
    phoneme_skip_counts: dict[str, int] = {}
    use_phoneme_subprocess = (
        params.phoneme_align_mode == PhonemeAlignMode.LOCAL_CPU.value
        and vocals_path is not None
        and vocals_path.is_file()
    )
    inter_delay_s = (
        params.phoneme_align_inter_delay_s
        if params.phoneme_align_inter_delay_s >= 0
        else inter_boundary_delay_s()
    )
    crash_delay_s = (
        params.phoneme_align_crash_retry_delay_s
        if params.phoneme_align_crash_retry_delay_s >= 0
        else crash_retry_delay_s()
    )
    max_crash_attempts = (
        params.phoneme_align_crash_retries
        if params.phoneme_align_crash_retries > 0
        else crash_retry_count()
    )

    def _apply_phoneme_result(
        boundary_index: int,
        result: BoundaryDetectionResult,
        g2p_used: float,
        next_lrc: float,
        next_line_end_ms: float,
        align_result: PhonemeAlignResult,
    ) -> tuple[BoundaryDetectionResult, bool, str]:
        phoneme_applied = False
        phoneme_skip_reason = ""
        if align_result.skipped and align_result.reason:
            phoneme_skip_reason = align_result.reason
            phoneme_skip_counts[align_result.reason] = (
                phoneme_skip_counts.get(align_result.reason, 0) + 1
            )
        if align_result.reason == "remote_not_implemented":
            nonlocal phoneme_skipped_remote_count
            phoneme_skipped_remote_count += 1
        if align_result.onset_ms is not None:
            refined = _apply_min_slice_guard(
                align_result.onset_ms,
                line_start_ms=starts[boundary_index],
                next_lrc_ts=next_lrc,
                next_line_end_ms=next_line_end_ms,
                min_slice_ms=params.min_slice_ms,
                safety_margin_ms=params.safety_margin_ms,
                method="phoneme",
            )
            if not refined.fallback:
                result = refined
                phoneme_applied = True
                nonlocal phoneme_applied_count
                phoneme_applied_count += 1
        return result, phoneme_applied, phoneme_skip_reason

    def _subprocess_align_result(item: dict[str, object]) -> PhonemeAlignResult:
        skip = str(item.get("skip_reason") or "")
        onset = item.get("onset_ms")
        return PhonemeAlignResult(
            onset_ms=float(onset) if onset is not None else None,
            skipped=onset is None,
            reason=skip or ("phoneme_local" if onset is not None else "phoneme_align_error"),
            method="phoneme_local" if onset is not None else "",
        )

    for i in range(n - 1):
        next_lrc = lyrics[i + 1].start_ms
        next_line_end_ms = lyrics[i + 2].start_ms if i + 2 < n else duration_ms

        if params.boundary_mode == "lrc_strict":
            result = BoundaryDetectionResult(
                t_cut=next_lrc,
                fallback=False,
                reason="lrc_strict_mode",
                method="lrc_strict",
            )
            g2p_used = 0.0
        else:
            result, g2p_used = detect_boundary(
                audio,
                sr,
                line_start_ms=starts[i],
                next_lrc_ts=next_lrc,
                next_line_end_ms=next_line_end_ms,
                next_line_text=lyrics[i + 1].text,
                search_margin_ms=params.search_margin_ms,
                onset_min_lead_silence_ms=params.onset_min_lead_silence_ms,
                min_slice_ms=params.min_slice_ms,
                onset_energy_threshold_db=params.onset_energy_threshold_db,
                safety_margin_ms=params.safety_margin_ms,
                g2p_preroll_ms=params.g2p_preroll_ms,
                boundary_zcr_weight=params.boundary_zcr_weight,
            )

        phoneme_applied = False
        phoneme_skip_reason = ""
        if params.phoneme_align_mode != PhonemeAlignMode.OFF.value:
            if params.phoneme_align_fallback_only and not result.fallback:
                phoneme_skip_reason = "not_fallback_boundary"
                phoneme_skip_counts["not_fallback_boundary"] = (
                    phoneme_skip_counts.get("not_fallback_boundary", 0) + 1
                )
            else:
                align_window_start = max(
                    starts[i] + params.min_slice_ms,
                    next_lrc - params.search_margin_ms,
                )
                if params.g2p_preroll_ms > 0:
                    pre_roll = lookup_preroll_ms(lyrics[i + 1].text, params.g2p_preroll_ms)
                    if pre_roll > 0:
                        align_window_start = max(
                            align_window_start,
                            next_lrc - max(params.search_margin_ms, int(pre_roll)),
                        )
                if use_phoneme_subprocess:
                    assert vocals_path is not None
                    job = {
                        "boundary_index": i,
                        "text": align_text_snippet(lyrics[i + 1].text),
                        "window_start_ms": align_window_start,
                        "window_end_ms": next_lrc + 50.0,
                    }
                    align_result = PhonemeAlignResult(
                        skipped=True, reason="phoneme_align_subprocess_crash"
                    )
                    for attempt in range(max_crash_attempts):
                        try:
                            raw = run_phoneme_align_subprocess(vocals_path, [job])
                            align_result = _subprocess_align_result(raw[0])
                            break
                        except RuntimeError as exc:
                            if "native crash" not in str(exc):
                                raise
                            if attempt >= max_crash_attempts - 1:
                                align_result = PhonemeAlignResult(
                                    skipped=True,
                                    reason="phoneme_align_subprocess_crash",
                                    message=str(exc)[-200:],
                                )
                            else:
                                sleep_crash_retry_delay(crash_delay_s)
                    sleep_inter_boundary_delay(inter_delay_s)
                    result, phoneme_applied, phoneme_skip_reason = _apply_phoneme_result(
                        i, result, g2p_used, next_lrc, next_line_end_ms, align_result
                    )
                else:
                    align_result = refine_boundary(
                        mode=params.phoneme_align_mode,
                        audio=audio,
                        sr=sr,
                        next_line_text=lyrics[i + 1].text,
                        window_start_ms=align_window_start,
                        window_end_ms=next_lrc + 50.0,
                        fallback=result.fallback,
                        fallback_only=params.phoneme_align_fallback_only,
                        remote_url=params.phoneme_align_remote_url,
                        remote_timeout_s=params.phoneme_align_remote_timeout_s,
                    )
                    result, phoneme_applied, phoneme_skip_reason = _apply_phoneme_result(
                        i, result, g2p_used, next_lrc, next_line_end_ms, align_result
                    )

        starts.append(result.t_cut)
        fallbacks.append(result.fallback)
        diagnostics.append(
            BoundaryDiagnostic(
                boundary_index=i,
                next_slice_id=f"slice_{i + 1:03d}",
                next_lrc_ms=next_lrc,
                t_cut_ms=round(result.t_cut, 2),
                aligned=result.aligned,
                reason=result.reason,
                method=result.method,
                delta_ms=round(next_lrc - result.t_cut, 2),
                safety_margin_applied_ms=result.safety_margin_applied_ms,
                g2p_preroll_ms_used=round(g2p_used, 2),
                phoneme_align_applied=phoneme_applied,
                phoneme_align_skip_reason=phoneme_skip_reason,
            )
        )

    return starts, fallbacks, diagnostics, phoneme_applied_count, phoneme_skipped_remote_count, phoneme_skip_counts


def format_boundary_diagnostic_line(item: BoundaryDiagnostic) -> str:
    status = "aligned" if item.aligned else "fallback"
    delta = f" delta={item.delta_ms:.2f}ms" if item.delta_ms > 0.01 else ""
    margin = (
        f" margin={item.safety_margin_applied_ms}ms"
        if item.safety_margin_applied_ms > 0
        else ""
    )
    phoneme_skip = (
        f" phoneme_skip={item.phoneme_align_skip_reason}"
        if item.phoneme_align_skip_reason
        else ""
    )
    phoneme_applied = " phoneme=1" if item.phoneme_align_applied else ""
    return (
        f"[BOUNDARY] i={item.boundary_index:02d} {item.next_slice_id} "
        f"{status} method={item.method} reason={item.reason} "
        f"t_cut={item.t_cut_ms:.2f} lrc={item.next_lrc_ms:.2f}{delta}{margin}"
        f"{phoneme_skip}{phoneme_applied}"
    )


def slice_vocals_lrc(
    lrc_path: Path,
    vocals_path: Path,
    output_dir: Path,
    *,
    song_name: str | None = None,
    boundary_mode: str = DEFAULT_BOUNDARY_MODE,
    search_margin_ms: int = DEFAULT_SEARCH_MARGIN_MS,
    onset_min_lead_silence_ms: int = DEFAULT_ONSET_MIN_LEAD_SILENCE_MS,
    min_slice_ms: int = DEFAULT_MIN_SLICE_MS,
    onset_energy_threshold_db: float = DEFAULT_ONSET_ENERGY_THRESHOLD_DB,
    safety_margin_ms: int = DEFAULT_SAFETY_MARGIN_MS,
    g2p_preroll_ms: int = 0,
    boundary_zcr_weight: float = 0.0,
    phoneme_align_mode: str = PhonemeAlignMode.OFF.value,
    phoneme_align_fallback_only: bool = True,
    phoneme_align_remote_url: str = "",
    phoneme_align_remote_timeout_s: int = 30,
) -> tuple[list[Path], Path, dict[str, object]]:
    if not lrc_path.exists():
        raise FileNotFoundError(f"LRC file not found: {lrc_path}")
    if not vocals_path.exists():
        raise FileNotFoundError(f"Vocals file not found: {vocals_path}")

    lyrics, offset_ms = parse_lrc(lrc_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio, sr = sf.read(str(vocals_path), always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    duration_ms = len(audio) / sr * 1000
    prefix = song_name or lrc_path.stem
    params = BoundaryParams(
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
        phoneme_align_remote_url=phoneme_align_remote_url,
        phoneme_align_remote_timeout_s=phoneme_align_remote_timeout_s,
    )

    if phoneme_align_mode == PhonemeAlignMode.LOCAL_CPU.value:
        pass  # phoneme align runs per-boundary in separator-env subprocess

    starts, fallbacks, diagnostics, phoneme_applied_count, phoneme_skipped_remote_count, phoneme_skip_counts = (
        compute_boundaries(
            lyrics, audio, sr, duration_ms, params, vocals_path=vocals_path.resolve()
        )
    )

    aligned_count = 0
    valley_count = 0
    fallback_count = 0
    first_fallback_example: dict[str, object] | None = None

    written: list[Path] = []
    manifest_slices: list[dict[str, object]] = []

    for index, line in enumerate(lyrics):
        start_ms = starts[index]
        if index + 1 < len(lyrics):
            end_ms = starts[index + 1]
            lrc_end_ms = lyrics[index + 1].start_ms
        else:
            end_ms = duration_ms
            lrc_end_ms = duration_ms

        lrc_start_ms = line.start_ms
        boundary_in_fallback = fallbacks[index]

        if index > 0 and not boundary_in_fallback and start_ms < lrc_start_ms:
            aligned_count += 1
        if index > 0 and not boundary_in_fallback:
            diag = diagnostics[index - 1]
            if diag.method == "valley_onset":
                valley_count += 1
        if index > 0 and boundary_in_fallback:
            fallback_count += 1
            if first_fallback_example is None:
                first_fallback_example = {
                    "slice_id": f"slice_{index:03d}",
                    "start_ms": round(start_ms, 2),
                    "lrc_start_ms": round(lrc_start_ms, 2),
                }

        start_sample = _ms_to_sample(start_ms, sr)
        end_sample = min(_ms_to_sample(end_ms, sr), len(audio))
        if end_sample <= start_sample:
            continue

        segment = apply_fade(audio[start_sample:end_sample], sr, FADE_IN_MS, FADE_OUT_MS)
        out_name = f"{prefix}_slice_{index:03d}.flac"
        out_path = output_dir / out_name
        sf.write(str(out_path), segment, sr, subtype="PCM_16")
        written.append(out_path)
        manifest_slices.append(
            {
                "id": f"slice_{index:03d}",
                "file": out_name,
                "start_ms": round(start_ms, 2),
                "end_ms": round(end_ms, 2),
                "lrc_start_ms": round(lrc_start_ms, 2),
                "lrc_end_ms": round(lrc_end_ms, 2),
                "text": line.text,
                "lrc_line": line.line_no,
                "boundary_in_fallback": boundary_in_fallback,
                **(
                    {
                        "boundary_method": diagnostics[index - 1].method,
                        "boundary_reason": diagnostics[index - 1].reason,
                        "phoneme_align_applied": diagnostics[index - 1].phoneme_align_applied,
                        "g2p_preroll_ms_used": diagnostics[index - 1].g2p_preroll_ms_used,
                    }
                    if index > 0
                    else {}
                ),
            }
        )

    try:
        source = str(vocals_path.relative_to(ROOT))
    except ValueError:
        source = str(vocals_path)

    try:
        lrc_rel = str(lrc_path.relative_to(ROOT))
    except ValueError:
        lrc_rel = str(lrc_path)

    manifest: dict[str, object] = {
        "source": source,
        "lrc": lrc_rel,
        "offset_ms": offset_ms,
        "slice_mode": "lrc",
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
        "phoneme_align_applied_count": phoneme_applied_count,
        "phoneme_align_skipped_remote_count": phoneme_skipped_remote_count,
        "phoneme_align_skip_counts": phoneme_skip_counts,
        "sample_rate": sr,
        "fade_in_ms": FADE_IN_MS,
        "fade_out_ms": FADE_OUT_MS,
        "aligned_boundary_count": aligned_count,
        "valley_boundary_count": valley_count,
        "fallback_boundary_count": fallback_count,
        "boundary_diagnostics": [
            {
                "boundary_index": item.boundary_index,
                "next_slice_id": item.next_slice_id,
                "next_lrc_ms": item.next_lrc_ms,
                "t_cut_ms": item.t_cut_ms,
                "aligned": item.aligned,
                "reason": item.reason,
                "method": item.method,
                "delta_ms": item.delta_ms,
                "safety_margin_applied_ms": item.safety_margin_applied_ms,
                "g2p_preroll_ms_used": item.g2p_preroll_ms_used,
                "phoneme_align_applied": item.phoneme_align_applied,
                "phoneme_align_skip_reason": item.phoneme_align_skip_reason,
            }
            for item in diagnostics
        ],
        "slices": manifest_slices,
    }
    if first_fallback_example is not None:
        manifest["first_fallback_example"] = first_fallback_example

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return written, manifest_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice vocal audio by LRC timestamps")
    parser.add_argument("lrc", type=Path, help="Path to LRC lyrics file")
    parser.add_argument("vocals", type=Path, help="Path to separated vocals FLAC/WAV")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Output directory (default: output/slices/<song_name>)",
    )
    parser.add_argument("--song-name", type=str, help="Prefix for slice filenames")
    parser.add_argument(
        "--boundary-mode",
        choices=("onset_aligned", "lrc_strict"),
        default=DEFAULT_BOUNDARY_MODE,
        help="Boundary alignment mode (default: onset_aligned)",
    )
    parser.add_argument(
        "--search-margin-ms",
        type=int,
        default=DEFAULT_SEARCH_MARGIN_MS,
        help="Max look-back before next LRC timestamp (default: 400)",
    )
    parser.add_argument(
        "--onset-min-lead-silence-ms",
        type=int,
        default=DEFAULT_ONSET_MIN_LEAD_SILENCE_MS,
        help="Required quiet interval before onset (default: 80)",
    )
    parser.add_argument(
        "--min-slice-ms",
        type=int,
        default=DEFAULT_MIN_SLICE_MS,
        help="Minimum slice duration; shorter boundaries fall back to LRC (default: 500)",
    )
    parser.add_argument(
        "--onset-energy-threshold-db",
        type=float,
        default=DEFAULT_ONSET_ENERGY_THRESHOLD_DB,
        help="Onset threshold relative to window peak in dB (default: -40)",
    )
    parser.add_argument(
        "--safety-margin-ms",
        type=int,
        default=DEFAULT_SAFETY_MARGIN_MS,
        help="Fallback margin before next LRC timestamp in ms (default: 80)",
    )
    parser.add_argument(
        "--g2p-preroll-ms",
        type=int,
        default=0,
        help="G2P-based preroll before boundary search (default: 0)",
    )
    parser.add_argument(
        "--boundary-zcr-weight",
        type=float,
        default=0.0,
        help="Weight for zero-crossing rate in boundary scoring (default: 0)",
    )
    parser.add_argument(
        "--phoneme-align-mode",
        choices=tuple(m.value for m in PhonemeAlignMode),
        default=PhonemeAlignMode.OFF.value,
        help="Phoneme boundary refinement mode (default: off)",
    )
    parser.add_argument(
        "--phoneme-align-fallback-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only refine fallback boundaries with phoneme align (default: true)",
    )
    parser.add_argument(
        "--phoneme-align-remote-url",
        type=str,
        default="",
        help="Remote phoneme align service URL (phoneme_align_mode=remote)",
    )
    parser.add_argument(
        "--phoneme-align-remote-timeout-s",
        type=int,
        default=30,
        help="Remote phoneme align timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    song_name = args.song_name or args.lrc.stem
    output_dir = args.output_dir or (DEFAULT_SLICES_ROOT / song_name)

    try:
        outputs, manifest_path, manifest = slice_vocals_lrc(
            args.lrc,
            args.vocals,
            output_dir,
            song_name=song_name,
            boundary_mode=args.boundary_mode,
            search_margin_ms=args.search_margin_ms,
            onset_min_lead_silence_ms=args.onset_min_lead_silence_ms,
            min_slice_ms=args.min_slice_ms,
            onset_energy_threshold_db=args.onset_energy_threshold_db,
            safety_margin_ms=args.safety_margin_ms,
            g2p_preroll_ms=args.g2p_preroll_ms,
            boundary_zcr_weight=args.boundary_zcr_weight,
            phoneme_align_mode=args.phoneme_align_mode,
            phoneme_align_fallback_only=args.phoneme_align_fallback_only,
            phoneme_align_remote_url=args.phoneme_align_remote_url,
            phoneme_align_remote_timeout_s=args.phoneme_align_remote_timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not outputs:
        print("No slices written.")
        return 1

    print(f"Wrote {len(outputs)} slices to {output_dir}")
    print(f"Wrote manifest: {manifest_path}")
    print(
        f"Boundaries: aligned={manifest.get('aligned_boundary_count', 0)} "
        f"valley={manifest.get('valley_boundary_count', 0)} "
        f"fallback={manifest.get('fallback_boundary_count', 0)} "
        f"mode={manifest.get('boundary_mode')}"
    )
    if manifest.get("first_fallback_example"):
        print(f"First fallback example: {manifest['first_fallback_example']}")
    for item in manifest.get("boundary_diagnostics", [])[:5]:
        print(
            f"Boundary i={item['boundary_index']:02d} {item['next_slice_id']} "
            f"{'aligned' if item['aligned'] else 'fallback'} "
            f"method={item['method']} reason={item['reason']} "
            f"t_cut={item['t_cut_ms']} lrc={item['next_lrc_ms']}"
        )
    remaining = len(manifest.get("boundary_diagnostics", [])) - 5
    if remaining > 0:
        print(f"... and {remaining} more boundaries (see manifest boundary_diagnostics)")
    print(
        f"Skipped metadata lines; first slice: [{manifest['slices'][0]['start_ms']}ms] "
        f"{manifest['slices'][0]['text']}"
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
