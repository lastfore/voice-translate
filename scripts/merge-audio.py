"""Merge converted vocals with instrumental backing track."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "output" / "merged"
DEFAULT_MODEL_DIR = ROOT / "separator-env" / "models" / "audio-separator"

TARGET_SR = 44100
KARAOKE_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
MAX_STRETCH_RATIO = 0.05
SILENCE_THRESHOLD_DB = -40.0
SILENCE_FLOOR = 0.01


@dataclass(frozen=True)
class SpliceParams:
    boundary_crossfade_ms: int = 0
    boundary_crossfade_curve: str = "equal_power"
    boundary_zero_crossing: bool = True
    boundary_lufs_match_ms: int = 0
    splice_wsola_search_ms: int = 0


@dataclass
class Profile:
    name: str
    stitch_slices: bool
    silence_mask: bool
    rms_match: bool
    time_align: bool
    pedalboard_fx: bool
    karaoke_clean: bool
    mastering: bool


PROFILES: dict[str, Profile] = {
    "quick": Profile("quick", False, False, False, False, False, False, False),
    "balanced": Profile("balanced", True, True, True, False, False, False, False),
    "full": Profile("full", True, True, True, True, True, True, True),
}


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(str(path), always_2d=True)
    return audio.astype(np.float32), sr


def to_samples_channels(audio: np.ndarray) -> np.ndarray:
    """Return shape (num_samples, num_channels)."""
    if audio.ndim == 1:
        return audio[:, np.newaxis]
    if audio.shape[0] < audio.shape[1] and audio.shape[0] <= 8:
        return audio.T
    return audio


def to_mono(audio: np.ndarray) -> np.ndarray:
    samples = to_samples_channels(audio)
    if samples.shape[1] == 1:
        return samples[:, 0]
    return np.mean(samples, axis=1).astype(np.float32)


def resample_audio(audio: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    if sr == target_sr:
        return audio
    samples = to_samples_channels(audio)
    channels = [
        librosa.resample(samples[:, ch], orig_sr=sr, target_sr=target_sr, res_type="soxr_hq")
        for ch in range(samples.shape[1])
    ]
    return np.stack(channels, axis=1).astype(np.float32)


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))


def apply_gain_db(audio: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db == 0.0:
        return audio
    return audio * (10.0 ** (gain_db / 20.0))


def match_rms_level(audio: np.ndarray, reference: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    ref = rms(reference)
    cur = rms(audio)
    if cur < eps or ref < eps:
        return audio
    return audio * (ref / cur)


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


def build_silence_mask(reference: np.ndarray, sr: int, threshold_db: float = SILENCE_THRESHOLD_DB) -> np.ndarray:
    frame = max(int(sr * 0.02), 1)
    hop = frame
    if reference.size < frame:
        return np.ones_like(reference, dtype=np.float32)
    rms_frames = librosa.feature.rms(y=reference, frame_length=frame, hop_length=hop)[0]
    rms_db = 20.0 * np.log10(np.maximum(rms_frames, 1e-10))
    mask_frames = np.where(rms_db > threshold_db, 1.0, SILENCE_FLOOR).astype(np.float32)
    mask = np.repeat(mask_frames, hop)
    if mask.size < reference.size:
        mask = np.pad(mask, (0, reference.size - mask.size), constant_values=SILENCE_FLOOR)
    return mask[: reference.size]


def stretch_to_length(audio: np.ndarray, sr: int, target_len: int) -> np.ndarray:
    if target_len <= 0:
        return np.array([], dtype=np.float32)
    if len(audio) == target_len:
        return audio.astype(np.float32, copy=True)

    ratio = len(audio) / target_len
    if abs(1.0 - ratio) > MAX_STRETCH_RATIO:
        print(
            f"Warning: stretch ratio {ratio:.3f} exceeds ±{MAX_STRETCH_RATIO:.0%}; "
            "clamping to limit.",
            file=sys.stderr,
        )
        if ratio > 1.0 + MAX_STRETCH_RATIO:
            ratio = 1.0 + MAX_STRETCH_RATIO
        elif ratio < 1.0 - MAX_STRETCH_RATIO:
            ratio = 1.0 - MAX_STRETCH_RATIO

    stretched = audio
    try:
        import pyrubberband as pyrb

        stretched = pyrb.time_stretch(audio.astype(np.float32), sr, ratio)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: Rubber Band unavailable ({exc}); using librosa time_stretch.", file=sys.stderr)
        stretched = librosa.effects.time_stretch(audio.astype(np.float32), rate=ratio)

    if len(stretched) > target_len:
        return stretched[:target_len].astype(np.float32)
    if len(stretched) < target_len:
        return np.pad(stretched, (0, target_len - len(stretched))).astype(np.float32)
    return stretched.astype(np.float32)


def overlay_segment(
    timeline: np.ndarray,
    segment: np.ndarray,
    start: int,
    fade_in_ms: int,
    fade_out_ms: int,
    sr: int,
) -> np.ndarray:
    seg = apply_fade(segment, sr, fade_in_ms, fade_out_ms)
    end = start + len(seg)
    if end > len(timeline):
        timeline = np.pad(timeline, (0, end - len(timeline)))
    timeline[start:end] += seg
    return timeline


def effective_crossfade_ms(base_ms: int, boundary_method: str | None) -> int:
    if base_ms <= 0:
        return 0
    if boundary_method == "legato_onset":
        return min(base_ms, 10)
    return base_ms


def compute_crossfade_gains(num_samples: int, curve: str) -> tuple[np.ndarray, np.ndarray]:
    if num_samples <= 0:
        return np.array([], dtype=np.float32), np.array([], dtype=np.float32)
    t = np.linspace(0.0, 1.0, num_samples, dtype=np.float32)
    if curve == "linear":
        return 1.0 - t, t
    g_out = np.cos(t * np.pi / 2.0)
    g_in = np.sin(t * np.pi / 2.0)
    return g_out, g_in


def find_zero_crossing_offset(samples: np.ndarray, search_radius: int) -> int:
    """Find offset within ±search_radius for a near-zero crossing (same-slope preference)."""
    if search_radius <= 0 or len(samples) < 3:
        return 0

    best_offset = 0
    best_score = float("inf")
    for offset in range(-search_radius, search_radius + 1):
        idx = offset
        if idx < 1 or idx >= len(samples) - 1:
            continue
        prev_v = float(samples[idx - 1])
        cur_v = float(samples[idx])
        next_v = float(samples[idx + 1])
        if prev_v * next_v > 0:
            continue
        slope = next_v - prev_v
        score = abs(cur_v) + (0.001 if slope >= 0 else 0.0)
        if score < best_score:
            best_score = score
            best_offset = offset
    return best_offset


def _get_boundary_method(manifest: dict, slice_index: int) -> str | None:
    if slice_index <= 0:
        return None
    slices = manifest.get("slices") or []
    if slice_index < len(slices):
        method = slices[slice_index].get("boundary_method")
        if method:
            return str(method)
    diagnostics = manifest.get("boundary_diagnostics") or []
    diag_index = slice_index - 1
    if diag_index < len(diagnostics):
        return str(diagnostics[diag_index].get("method") or "")
    return None


def _apply_segment_fades(
    segment: np.ndarray,
    sr: int,
    fade_in_ms: int,
    fade_out_ms: int,
    *,
    skip_fade_in: bool = False,
    skip_fade_out: bool = False,
) -> np.ndarray:
    fade_in = 0 if skip_fade_in else fade_in_ms
    fade_out = 0 if skip_fade_out else fade_out_ms
    return apply_fade(segment, sr, fade_in, fade_out)


def overlay_with_boundary_crossfade(
    timeline: np.ndarray,
    segment: np.ndarray,
    boundary_sample: int,
    splice: SpliceParams,
    sr: int,
    boundary_method: str | None,
    fade_in_ms: int,
    fade_out_ms: int,
) -> tuple[np.ndarray, dict[str, object] | None]:
    """Place segment with equal-power/linear crossfade centered on boundary_sample."""
    tau_ms = effective_crossfade_ms(splice.boundary_crossfade_ms, boundary_method)
    overlap = int(tau_ms * sr / 1000)
    if overlap < 2:
        timeline = overlay_segment(timeline, segment, boundary_sample, fade_in_ms, fade_out_ms, sr)
        return timeline, None

    start_pos = boundary_sample - overlap // 2
    end_pos = start_pos + len(segment)
    if end_pos > len(timeline):
        timeline = np.pad(timeline, (0, end_pos - len(timeline)))

    head_len = min(overlap, len(segment))
    zc_offset = 0
    head_start = 0
    if splice.boundary_zero_crossing and head_len >= 3:
        search = min(int(sr * 5 / 1000), max(overlap // 4, 1))
        zc_offset = find_zero_crossing_offset(segment[: head_len + search], search)
        head_start = max(0, zc_offset)
        head_len = min(overlap, len(segment) - head_start)

    tail_start = start_pos
    tail_end = tail_start + head_len
    tail_a = timeline[tail_start:tail_end].copy()
    head_b = segment[head_start : head_start + head_len].astype(np.float32, copy=False)

    if len(tail_a) < head_len:
        tail_a = np.pad(tail_a, (0, head_len - len(tail_a)))
    elif len(tail_a) > head_len:
        tail_a = tail_a[:head_len]

    g_out, g_in = compute_crossfade_gains(head_len, splice.boundary_crossfade_curve)
    mixed = g_out * tail_a + g_in * head_b
    timeline[tail_start:tail_end] = mixed

    remainder = segment[head_start + head_len :]
    if remainder.size > 0:
        rem = _apply_segment_fades(remainder, sr, fade_in_ms, fade_out_ms, skip_fade_in=True)
        rem_start = tail_end
        rem_end = rem_start + len(rem)
        if rem_end > len(timeline):
            timeline = np.pad(timeline, (0, rem_end - len(timeline)))
        timeline[rem_start:rem_end] += rem

    meta: dict[str, object] = {
        "boundary_sample": boundary_sample,
        "tau_ms": tau_ms,
        "overlap_samples": head_len,
        "boundary_method": boundary_method or "",
        "zero_crossing_offset": zc_offset,
        "curve": splice.boundary_crossfade_curve,
    }
    return timeline, meta


def _rms_db(audio: np.ndarray) -> float:
    return float(20.0 * np.log10(max(rms(audio), 1e-10)))


def apply_boundary_lufs_match(
    prev_segment: np.ndarray,
    segment: np.ndarray,
    window_ms: int,
    sr: int,
) -> np.ndarray:
    """Approximate boundary loudness match (RMS dB) with smooth gain envelope on segment."""
    if window_ms <= 0 or segment.size == 0 or prev_segment.size == 0:
        return segment

    window_samples = int(window_ms * sr / 1000)
    if window_samples <= 0:
        return segment

    tail = prev_segment[-window_samples:]
    head = segment[:window_samples]
    if tail.size == 0 or head.size == 0:
        return segment

    delta_db = _rms_db(tail) - _rms_db(head)
    if abs(delta_db) <= 2.0:
        return segment

    target_gain = 10.0 ** (delta_db / 20.0)
    fade_len = min(len(segment), max(int(sr * 0.05), window_samples))
    envelope = np.ones(len(segment), dtype=np.float32)
    t = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
    envelope[:fade_len] = target_gain + (1.0 - target_gain) * t
    return (segment * envelope).astype(np.float32)


def _normalized_cross_correlation(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return -1.0
    a = a.astype(np.float64, copy=False)
    b = b.astype(np.float64, copy=False)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom < 1e-12:
        return -1.0
    return float(np.dot(a, b) / denom)


def ncc_splice_offset(
    prev_segment: np.ndarray,
    segment: np.ndarray,
    search_ms: int,
    sr: int,
) -> int:
    """Return sample shift for segment to maximize NCC with prev tail (±search_ms)."""
    if search_ms <= 0:
        return 0

    delta_samples = int(search_ms * sr / 1000)
    ref_len = min(len(prev_segment), len(segment), 2 * delta_samples)
    if ref_len < 8:
        return 0

    tail = prev_segment[-ref_len:]
    head = segment[:ref_len]
    step = max(int(sr / 1000), 1)
    best_delta = 0
    best_score = -2.0

    for delta in range(-delta_samples, delta_samples + 1, step):
        if delta >= 0:
            a = tail[delta:]
            b = head[: ref_len - delta]
        else:
            a = tail[: ref_len + delta]
            b = head[-delta:]
        if a.size < 8 or b.size < 8:
            continue
        n = min(a.size, b.size)
        score = _normalized_cross_correlation(a[:n], b[:n])
        if score > best_score:
            best_score = score
            best_delta = delta
    return best_delta


def shift_segment_phase(segment: np.ndarray, delta_samples: int) -> np.ndarray:
    """Circular-ish shift for splice phase tweak (pad/truncate, no manifest change)."""
    if delta_samples == 0 or segment.size == 0:
        return segment
    if delta_samples > 0:
        if delta_samples >= len(segment):
            return np.zeros_like(segment)
        return np.concatenate(
            [np.zeros(delta_samples, dtype=np.float32), segment[:-delta_samples]]
        )
    shift = -delta_samples
    if shift >= len(segment):
        return np.zeros_like(segment)
    return np.concatenate([segment[shift:], np.zeros(shift, dtype=np.float32)])


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_manifest(vocals: Path, manifest: Path | None) -> Path | None:
    if manifest and manifest.exists():
        return manifest
    if vocals.is_dir():
        candidate = vocals / "manifest.json"
        if candidate.exists():
            return candidate
        candidate = ROOT / "output" / "slices" / "manifest.json"
        if candidate.exists():
            return candidate
    return None


def build_from_whole_track(
    vocals_path: Path,
    profile: Profile,
    original_vocals: Path | None,
) -> np.ndarray:
    audio, sr = load_audio(vocals_path)
    vocals = to_mono(resample_audio(audio, sr, TARGET_SR))

    if profile.silence_mask or profile.rms_match:
        if original_vocals is None:
            print("Warning: --original-vocals not set; skipping mask/RMS matching.", file=sys.stderr)
        else:
            ref_audio, ref_sr = load_audio(original_vocals)
            reference = to_mono(resample_audio(ref_audio, ref_sr, TARGET_SR))
            min_len = min(len(vocals), len(reference))
            vocals = vocals[:min_len]
            reference = reference[:min_len]
            if profile.silence_mask:
                vocals *= build_silence_mask(reference, TARGET_SR)
            if profile.rms_match:
                vocals = match_rms_level(vocals, reference)

    return vocals.astype(np.float32)


def _align_segment_to_reference(
    segment: np.ndarray,
    reference_segment: np.ndarray | None,
    profile: Profile,
    manifest_target_len: int = 0,
) -> np.ndarray:
    """Match segment length to reference before mask/RMS; pad/trim when time_align is off."""
    if reference_segment is not None:
        target_len = len(reference_segment)
    elif manifest_target_len > 0:
        target_len = manifest_target_len
    else:
        return segment

    if len(segment) == target_len:
        return segment
    if profile.time_align:
        return stretch_to_length(segment, TARGET_SR, target_len)
    if len(segment) > target_len:
        return segment[:target_len]
    return np.pad(segment, (0, target_len - len(segment)))


def build_from_slices(
    manifest_path: Path,
    converted_dir: Path,
    slices_dir: Path,
    profile: Profile,
    original_vocals: Path | None,
    *,
    splice: SpliceParams | None = None,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    manifest = load_manifest(manifest_path)
    fade_in_ms = int(manifest.get("fade_in_ms", 8))
    fade_out_ms = int(manifest.get("fade_out_ms", 15))
    splice = splice or SpliceParams()
    crossfade_enabled = splice.boundary_crossfade_ms > 0
    splice_logs: list[dict[str, object]] = []

    if original_vocals is not None:
        ref_audio, ref_sr = load_audio(original_vocals)
        timeline_len = len(to_mono(resample_audio(ref_audio, ref_sr, TARGET_SR)))
    else:
        last_end = max(int(item["end_ms"]) for item in manifest["slices"])
        timeline_len = int(last_end * TARGET_SR / 1000) + TARGET_SR

    timeline = np.zeros(timeline_len, dtype=np.float32)

    converted_count = 0
    fallback_count = 0
    prev_segment: np.ndarray | None = None
    for slice_index, item in enumerate(manifest["slices"]):
        original_slice_path = slices_dir / item["file"]
        converted_path = converted_dir / item["file"]
        if converted_path.exists():
            audio_path = converted_path
            converted_count += 1
        elif original_slice_path.exists():
            audio_path = original_slice_path
            fallback_count += 1
            print(
                f"Warning: converted slice missing, using original: {item['file']}",
                file=sys.stderr,
            )
        else:
            raise FileNotFoundError(
                f"Neither converted nor original slice found: {converted_path}"
            )

        converted, conv_sr = load_audio(audio_path)
        segment = to_mono(resample_audio(converted, conv_sr, TARGET_SR))
        reference_segment = None
        if original_slice_path.exists():
            orig_audio, orig_sr = load_audio(original_slice_path)
            reference_segment = to_mono(resample_audio(orig_audio, orig_sr, TARGET_SR))

        manifest_target_len = int((item["end_ms"] - item["start_ms"]) * TARGET_SR / 1000)
        segment = _align_segment_to_reference(
            segment, reference_segment, profile, manifest_target_len
        )

        if profile.silence_mask and reference_segment is not None:
            segment *= build_silence_mask(reference_segment, TARGET_SR)
        if profile.rms_match and reference_segment is not None:
            segment = match_rms_level(segment, reference_segment)

        boundary_method = _get_boundary_method(manifest, slice_index)
        boundary_meta_extra: dict[str, object] = {}

        if slice_index > 0 and prev_segment is not None:
            if splice.boundary_lufs_match_ms > 0:
                segment = apply_boundary_lufs_match(
                    prev_segment,
                    segment,
                    splice.boundary_lufs_match_ms,
                    TARGET_SR,
                )
                boundary_meta_extra["lufs_match_ms"] = splice.boundary_lufs_match_ms
            if (
                splice.splice_wsola_search_ms > 0
                and boundary_method == "legato_onset"
            ):
                wsola_delta = ncc_splice_offset(
                    prev_segment,
                    segment,
                    splice.splice_wsola_search_ms,
                    TARGET_SR,
                )
                if wsola_delta != 0:
                    segment = shift_segment_phase(segment, wsola_delta)
                    boundary_meta_extra["wsola_delta_samples"] = wsola_delta

        start = int(item["start_ms"] * TARGET_SR / 1000)
        use_crossfade = crossfade_enabled and slice_index > 0
        if use_crossfade:
            seg_for_overlay = _apply_segment_fades(
                segment,
                TARGET_SR,
                fade_in_ms,
                fade_out_ms,
                skip_fade_in=True,
                skip_fade_out=True,
            )
            timeline, boundary_meta = overlay_with_boundary_crossfade(
                timeline,
                seg_for_overlay,
                start,
                splice,
                TARGET_SR,
                boundary_method,
                fade_in_ms,
                fade_out_ms,
            )
            if boundary_meta is not None:
                boundary_meta["slice_id"] = item.get("id", f"slice_{slice_index:03d}")
                boundary_meta.update(boundary_meta_extra)
                splice_logs.append(boundary_meta)
        else:
            if crossfade_enabled and slice_index == 0:
                timeline = overlay_segment(timeline, segment, start, fade_in_ms, 0, TARGET_SR)
            else:
                timeline = overlay_segment(
                    timeline, segment, start, fade_in_ms, fade_out_ms, TARGET_SR
                )
            if slice_index > 0 and boundary_meta_extra:
                splice_logs.append(
                    {
                        "slice_id": item.get("id", f"slice_{slice_index:03d}"),
                        "boundary_method": boundary_method or "",
                        **boundary_meta_extra,
                    }
                )

        prev_segment = segment.copy()

    if fallback_count:
        print(
            f"Slice merge: {converted_count} converted, {fallback_count} original fallback",
            file=sys.stderr,
        )

    return timeline.astype(np.float32), splice_logs


def _resolve_vocals_input(vocals: Path, profile: Profile) -> Path:
    """Map project converted root to full/ or slices/ when using the new layout."""
    if not vocals.is_dir():
        return vocals
    slices_sub = vocals / "slices"
    full_file = vocals / "full" / "full.flac"
    if profile.stitch_slices and slices_sub.is_dir():
        return slices_sub
    if full_file.is_file():
        return full_file
    return vocals


def build_vocal_track(
    vocals: Path,
    profile: Profile,
    manifest: Path | None,
    original_vocals: Path | None,
    slices_dir: Path | None,
    *,
    splice: SpliceParams | None = None,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    vocals = _resolve_vocals_input(vocals, profile)
    manifest_path = resolve_manifest(vocals, manifest)
    # Slice stitching only applies when --vocals points at a converted slices directory.
    # A single whole-track file (e.g. full.flac) must not fall back to manifest stitching
    # just because a project manifest exists.
    use_slices = profile.stitch_slices and manifest_path is not None and vocals.is_dir()

    if use_slices:
        converted_dir = vocals if vocals.is_dir() else vocals.parent
        slice_ref_dir = slices_dir or manifest_path.parent
        return build_from_slices(
            manifest_path, converted_dir, slice_ref_dir, profile, original_vocals, splice=splice
        )

    if vocals.is_dir():
        flacs = sorted(vocals.glob("*.flac")) + sorted(vocals.glob("*.wav"))
        if len(flacs) != 1:
            raise ValueError(
                f"--vocals directory {vocals} has {len(flacs)} audio files; "
                "provide --manifest for slice mode or a single whole-track file."
            )
        vocals = flacs[0]

    return build_from_whole_track(vocals, profile, original_vocals), []


def clean_instrumental(
    instrumental_path: Path,
    output_dir: Path,
    model_dir: Path,
    *,
    on_line: Callable[[str], None] | None = None,
) -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="karaoke-clean-"))
    try:
        from pipeline.venv_runner import run_subprocess, separator_cli_cmd, separator_env

        def _log(line: str) -> None:
            if on_line:
                on_line(line)
            else:
                print(line, file=sys.stderr)

        cmd = separator_cli_cmd(
            str(instrumental_path),
            "--model_filename",
            KARAOKE_MODEL,
            "--model_file_dir",
            str(model_dir),
            "--output_format",
            "flac",
            "--output_dir",
            str(work_dir),
            "--single_stem",
            "Instrumental",
        )
        _log(f"Running Karaoke clean: {' '.join(cmd)}")
        result = run_subprocess(cmd, env=separator_env(), on_line=_log)
        if result.returncode != 0:
            detail = (result.stdout or "").strip()
            tail = detail[-2000:] if detail else "(no subprocess output)"
            raise RuntimeError(
                f"Karaoke clean failed with exit code {result.returncode}. Last output:\n{tail}"
            )

        candidates = list(work_dir.glob("*Instrumental*.flac")) + list(work_dir.glob("*instrumental*.flac"))
        if not candidates:
            raise RuntimeError(f"Karaoke model produced no instrumental stem in {work_dir}")

        clean_path = output_dir / "instrumental_clean.flac"
        shutil.copy2(candidates[0], clean_path)
        _log(f"Karaoke clean wrote {clean_path.name}")
        return clean_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def apply_pedalboard(vocals: np.ndarray, instrumental: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    from pedalboard import Compressor, HighpassFilter, LowShelfFilter, Pedalboard, Reverb

    vocal_board = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=100),
            Compressor(threshold_db=-20, ratio=2.5),
            Reverb(room_size=0.12, wet_level=0.08, dry_level=0.92),
        ]
    )
    inst_board = Pedalboard(
        [
            LowShelfFilter(cutoff_frequency_hz=350, gain_db=-2.0, q=0.7),
        ]
    )

    vocals_out = vocal_board(vocals, sr)
    samples = to_samples_channels(instrumental)
    if samples.shape[1] == 1:
        inst_out = inst_board(samples[:, 0], sr)
    else:
        processed = [inst_board(samples[:, ch], sr) for ch in range(samples.shape[1])]
        inst_out = np.stack(processed, axis=1)
    return vocals_out.astype(np.float32), inst_out.astype(np.float32)


def mix_tracks(
    vocals: np.ndarray,
    instrumental: np.ndarray,
    vocals_gain_db: float,
    instrumental_gain_db: float,
) -> np.ndarray:
    vocals = apply_gain_db(vocals, vocals_gain_db)
    instrumental = apply_gain_db(instrumental, instrumental_gain_db)

    inst = to_samples_channels(instrumental)
    target_len = max(len(vocals), inst.shape[0])
    if len(vocals) < target_len:
        vocals = np.pad(vocals, (0, target_len - len(vocals)))
    if inst.shape[0] < target_len:
        pad = np.zeros((target_len - inst.shape[0], inst.shape[1]), dtype=np.float32)
        inst = np.vstack([inst, pad])

    if inst.shape[1] == 1:
        mixed = vocals[:target_len] + inst[:, 0]
        return np.stack([mixed, mixed], axis=1).astype(np.float32)

    vocal_stereo = np.stack([vocals[:target_len], vocals[:target_len]], axis=1)
    return (vocal_stereo + inst[:target_len]).astype(np.float32)


def write_flac(path: Path, audio: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = to_samples_channels(audio)
    sf.write(str(path), samples, sr, subtype="PCM_16")


def apply_mastering(mixed_path: Path, reference_path: Path, output_path: Path) -> None:
    import matchering as mg

    with tempfile.TemporaryDirectory(prefix="matchering-") as tmp:
        tmp_dir = Path(tmp)
        target_wav = tmp_dir / "target.wav"
        reference_wav = tmp_dir / "reference.wav"
        mastered_wav = tmp_dir / "mastered.wav"

        audio, sr = load_audio(mixed_path)
        ref, ref_sr = load_audio(reference_path)
        sf.write(str(target_wav), to_samples_channels(audio), sr)
        sf.write(str(reference_wav), to_samples_channels(resample_audio(ref, ref_sr, sr)), sr)

        mg.process(
            target=str(target_wav),
            reference=str(reference_wav),
            results=[mg.pcm16(str(mastered_wav))],
        )
        mastered, master_sr = load_audio(mastered_wav)
        write_flac(output_path, mastered, master_sr)


def merge_audio(
    vocals: Path,
    instrumental: Path,
    output_dir: Path,
    *,
    profile_name: str = "full",
    reference: Path | None = None,
    original_vocals: Path | None = None,
    manifest: Path | None = None,
    slices_dir: Path | None = None,
    clean_instrumental_flag: bool = False,
    vocals_gain_db: float = 0.0,
    instrumental_gain_db: float = 0.0,
    skip_mastering: bool = False,
    model_dir: Path = DEFAULT_MODEL_DIR,
    on_line: Callable[[str], None] | None = None,
    splice: SpliceParams | None = None,
) -> tuple[Path, Path]:
    profile = PROFILES[profile_name]
    output_dir.mkdir(parents=True, exist_ok=True)
    splice = splice or SpliceParams()

    vocal_track, splice_logs = build_vocal_track(
        vocals, profile, manifest, original_vocals, slices_dir, splice=splice
    )
    vocals_out = output_dir / "vocals.flac"
    write_flac(vocals_out, vocal_track, TARGET_SR)

    if (
        profile.stitch_slices
        and splice_logs
        and (
            splice.boundary_crossfade_ms > 0
            or splice.boundary_lufs_match_ms > 0
            or splice.splice_wsola_search_ms > 0
        )
    ):
        if on_line:
            on_line(
                f"Splice crossfade enabled: boundary_crossfade_ms={splice.boundary_crossfade_ms} "
                f"curve={splice.boundary_crossfade_curve} boundaries={len(splice_logs)}"
            )
            if splice.boundary_lufs_match_ms > 0:
                on_line(f"Splice LUFS match window={splice.boundary_lufs_match_ms}ms")
            if splice.splice_wsola_search_ms > 0:
                on_line(f"Splice WSOLA search=±{splice.splice_wsola_search_ms}ms (legato only)")
            for entry in splice_logs:
                wsola = entry.get("wsola_delta_samples")
                wsola_text = f" wsola={wsola}" if wsola else ""
                on_line(
                    f"[SPLICE] {entry.get('slice_id')} tau_ms={entry.get('tau_ms')} "
                    f"overlap={entry.get('overlap_samples')} method={entry.get('boundary_method')} "
                    f"zc_offset={entry.get('zero_crossing_offset')}{wsola_text}"
                )
        splice_meta_path = output_dir / "splice_meta.json"
        splice_meta_path.write_text(
            json.dumps(
                {
                    "boundary_crossfade_ms": splice.boundary_crossfade_ms,
                    "boundary_crossfade_curve": splice.boundary_crossfade_curve,
                    "boundary_zero_crossing": splice.boundary_zero_crossing,
                    "boundary_lufs_match_ms": splice.boundary_lufs_match_ms,
                    "splice_wsola_search_ms": splice.splice_wsola_search_ms,
                    "boundaries": splice_logs,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    inst_audio, inst_sr = load_audio(instrumental)
    inst_audio = resample_audio(inst_audio, inst_sr, TARGET_SR)

    inst_path = instrumental
    if clean_instrumental_flag and profile.karaoke_clean:
        if on_line:
            on_line("Starting Karaoke instrumental clean...")
        inst_path = clean_instrumental(instrumental, output_dir, model_dir, on_line=on_line)
        inst_audio, inst_sr = load_audio(inst_path)
        inst_audio = resample_audio(inst_audio, inst_sr, TARGET_SR)

    if profile.pedalboard_fx:
        vocal_track, inst_audio = apply_pedalboard(vocal_track, inst_audio, TARGET_SR)
        write_flac(vocals_out, vocal_track, TARGET_SR)

    mixed = mix_tracks(vocal_track, inst_audio, vocals_gain_db, instrumental_gain_db)
    mixed_path = output_dir / "mixed.flac"
    write_flac(mixed_path, mixed, TARGET_SR)

    if profile.mastering and not skip_mastering:
        if reference is None:
            print("Warning: --reference not set; skipping Matchering.", file=sys.stderr)
        else:
            mastered_path = output_dir / "mixed_mastered.flac"
            apply_mastering(mixed_path, reference, mastered_path)
            shutil.copy2(mastered_path, mixed_path)

    return vocals_out, mixed_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge converted vocals with instrumental")
    parser.add_argument("--vocals", type=Path, required=True, help="Converted vocal file or directory")
    parser.add_argument("--instrumental", type=Path, required=True, help="Instrumental stem")
    parser.add_argument("--reference", type=Path, help="Original mix for Matchering reference")
    parser.add_argument("--original-vocals", type=Path, help="Original separated vocals for mask/RMS")
    parser.add_argument("--manifest", type=Path, help="Slice manifest.json path")
    parser.add_argument("--slices-dir", type=Path, help="Original slices directory")
    parser.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="full")
    parser.add_argument("--clean-instrumental", action="store_true")
    parser.add_argument("--vocals-gain", type=float, default=0.0)
    parser.add_argument("--instrumental-gain", type=float, default=0.0)
    parser.add_argument("--skip-mastering", action="store_true")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()

    try:
        vocals_out, mixed_out = merge_audio(
            args.vocals,
            args.instrumental,
            args.output_dir,
            profile_name=args.profile,
            reference=args.reference,
            original_vocals=args.original_vocals,
            manifest=args.manifest,
            slices_dir=args.slices_dir,
            clean_instrumental_flag=args.clean_instrumental,
            vocals_gain_db=args.vocals_gain,
            instrumental_gain_db=args.instrumental_gain,
            skip_mastering=args.skip_mastering,
            model_dir=args.model_dir,
        )
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote vocals: {vocals_out}")
    print(f"Wrote mixed:  {mixed_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
