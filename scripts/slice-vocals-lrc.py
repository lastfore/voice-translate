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

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SLICES_ROOT = ROOT / "output" / "slices"

FADE_IN_MS = 8
FADE_OUT_MS = 15

DEFAULT_BOUNDARY_MODE = "onset_aligned"
DEFAULT_SEARCH_MARGIN_MS = 400
DEFAULT_ONSET_MIN_LEAD_SILENCE_MS = 80
DEFAULT_MIN_SLICE_MS = 500
DEFAULT_ONSET_ENERGY_THRESHOLD_DB = -40.0
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


@dataclass(frozen=True)
class BoundaryDetectionResult:
    t_cut: float
    fallback: bool
    reason: str
    method: str = "lrc_strict"

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


def _apply_min_slice_guard(
    best_t: float,
    *,
    line_start_ms: float,
    next_lrc_ts: float,
    next_line_end_ms: float,
    min_slice_ms: int,
    method: str,
) -> BoundaryDetectionResult:
    if (best_t - line_start_ms) < min_slice_ms:
        return BoundaryDetectionResult(
            t_cut=next_lrc_ts,
            fallback=True,
            reason="current_slice_too_short",
            method="lrc_fallback",
        )
    if (next_line_end_ms - best_t) < min_slice_ms:
        return BoundaryDetectionResult(
            t_cut=next_lrc_ts,
            fallback=True,
            reason="next_slice_too_short",
            method="lrc_fallback",
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
    search_margin_ms: int = DEFAULT_SEARCH_MARGIN_MS,
    onset_min_lead_silence_ms: int = DEFAULT_ONSET_MIN_LEAD_SILENCE_MS,
    min_slice_ms: int = DEFAULT_MIN_SLICE_MS,
    onset_energy_threshold_db: float = DEFAULT_ONSET_ENERGY_THRESHOLD_DB,
) -> BoundaryDetectionResult:
    """Detect aligned cut point between adjacent lyric lines."""
    window_start_ms = max(line_start_ms + min_slice_ms, next_lrc_ts - search_margin_ms)
    window_end_ms = next_lrc_ts

    if window_end_ms <= window_start_ms:
        return BoundaryDetectionResult(
            t_cut=next_lrc_ts,
            fallback=True,
            reason="window_empty",
            method="lrc_fallback",
        )

    times, envelope = compute_rms_envelope(audio, sr, window_start_ms, window_end_ms)
    if envelope.size == 0:
        return BoundaryDetectionResult(
            t_cut=next_lrc_ts,
            fallback=True,
            reason="envelope_empty",
            method="lrc_fallback",
        )

    peak = float(np.max(envelope))
    if peak <= 1e-12:
        return BoundaryDetectionResult(
            t_cut=next_lrc_ts,
            fallback=True,
            reason="silent_window",
            method="lrc_fallback",
        )

    threshold = peak * (10.0 ** (onset_energy_threshold_db / 20.0))
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
            return BoundaryDetectionResult(
                t_cut=next_lrc_ts,
                fallback=True,
                reason="no_onset_candidate",
                method="lrc_fallback",
            )
        return _apply_min_slice_guard(
            legato_t,
            line_start_ms=line_start_ms,
            next_lrc_ts=next_lrc_ts,
            next_line_end_ms=next_line_end_ms,
            min_slice_ms=min_slice_ms,
            method="legato",
        )

    return _apply_min_slice_guard(
        best_t,
        line_start_ms=line_start_ms,
        next_lrc_ts=next_lrc_ts,
        next_line_end_ms=next_line_end_ms,
        min_slice_ms=min_slice_ms,
        method="silence",
    )


def compute_boundaries(
    lyrics: list[LrcLine],
    audio: np.ndarray,
    sr: int,
    duration_ms: float,
    params: BoundaryParams,
) -> tuple[list[float], list[bool], list[BoundaryDiagnostic]]:
    """Return aligned start_ms per slice, entry-boundary fallback flags, and diagnostics."""
    n = len(lyrics)
    starts = [lyrics[0].start_ms]
    fallbacks = [False]
    diagnostics: list[BoundaryDiagnostic] = []

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
        else:
            result = detect_boundary(
                audio,
                sr,
                line_start_ms=starts[i],
                next_lrc_ts=next_lrc,
                next_line_end_ms=next_line_end_ms,
                search_margin_ms=params.search_margin_ms,
                onset_min_lead_silence_ms=params.onset_min_lead_silence_ms,
                min_slice_ms=params.min_slice_ms,
                onset_energy_threshold_db=params.onset_energy_threshold_db,
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
            )
        )

    return starts, fallbacks, diagnostics


def format_boundary_diagnostic_line(item: BoundaryDiagnostic) -> str:
    status = "aligned" if item.aligned else "fallback"
    delta = f" delta={item.delta_ms:.2f}ms" if item.delta_ms > 0.01 else ""
    return (
        f"[BOUNDARY] i={item.boundary_index:02d} {item.next_slice_id} "
        f"{status} method={item.method} reason={item.reason} "
        f"t_cut={item.t_cut_ms:.2f} lrc={item.next_lrc_ms:.2f}{delta}"
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
    )

    starts, fallbacks, diagnostics = compute_boundaries(
        lyrics, audio, sr, duration_ms, params
    )

    aligned_count = 0
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
        "sample_rate": sr,
        "fade_in_ms": FADE_IN_MS,
        "fade_out_ms": FADE_OUT_MS,
        "aligned_boundary_count": aligned_count,
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
