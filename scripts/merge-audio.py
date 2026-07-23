"""Merge converted vocals with instrumental backing track."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
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


def build_from_slices(
    manifest_path: Path,
    converted_dir: Path,
    slices_dir: Path,
    profile: Profile,
    original_vocals: Path | None,
) -> np.ndarray:
    manifest = load_manifest(manifest_path)
    fade_in_ms = int(manifest.get("fade_in_ms", 8))
    fade_out_ms = int(manifest.get("fade_out_ms", 15))

    if original_vocals is not None:
        ref_audio, ref_sr = load_audio(original_vocals)
        timeline_len = len(to_mono(resample_audio(ref_audio, ref_sr, TARGET_SR)))
    else:
        last_end = max(int(item["end_ms"]) for item in manifest["slices"])
        timeline_len = int(last_end * TARGET_SR / 1000) + TARGET_SR

    timeline = np.zeros(timeline_len, dtype=np.float32)

    converted_count = 0
    fallback_count = 0
    for item in manifest["slices"]:
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

        target_len = int((item["end_ms"] - item["start_ms"]) * TARGET_SR / 1000)
        if reference_segment is not None:
            target_len = len(reference_segment)

        if profile.time_align and reference_segment is not None:
            segment = stretch_to_length(segment, TARGET_SR, len(reference_segment))
        elif target_len > 0 and len(segment) != target_len and profile.time_align:
            segment = stretch_to_length(segment, TARGET_SR, target_len)

        if profile.silence_mask and reference_segment is not None:
            segment *= build_silence_mask(reference_segment, TARGET_SR)
        if profile.rms_match and reference_segment is not None:
            segment = match_rms_level(segment, reference_segment)

        start = int(item["start_ms"] * TARGET_SR / 1000)
        timeline = overlay_segment(timeline, segment, start, fade_in_ms, fade_out_ms, TARGET_SR)

    if fallback_count:
        print(
            f"Slice merge: {converted_count} converted, {fallback_count} original fallback",
            file=sys.stderr,
        )

    return timeline.astype(np.float32)


def build_vocal_track(
    vocals: Path,
    profile: Profile,
    manifest: Path | None,
    original_vocals: Path | None,
    slices_dir: Path | None,
) -> np.ndarray:
    manifest_path = resolve_manifest(vocals, manifest)
    use_slices = profile.stitch_slices and manifest_path is not None

    if use_slices:
        converted_dir = vocals if vocals.is_dir() else vocals.parent
        slice_ref_dir = slices_dir or manifest_path.parent
        return build_from_slices(manifest_path, converted_dir, slice_ref_dir, profile, original_vocals)

    if vocals.is_dir():
        flacs = sorted(vocals.glob("*.flac")) + sorted(vocals.glob("*.wav"))
        if len(flacs) != 1:
            raise ValueError(
                f"--vocals directory {vocals} has {len(flacs)} audio files; "
                "provide --manifest for slice mode or a single whole-track file."
            )
        vocals = flacs[0]

    return build_from_whole_track(vocals, profile, original_vocals)


def clean_instrumental(
    instrumental_path: Path,
    output_dir: Path,
    model_dir: Path,
) -> Path:
    work_dir = Path(tempfile.mkdtemp(prefix="karaoke-clean-"))
    try:
        from pipeline.venv_runner import separator_cli_cmd, separator_env

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
        )
        print(f"Running Karaoke clean: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, env=separator_env())

        candidates = list(work_dir.glob("*Instrumental*.flac")) + list(work_dir.glob("*instrumental*.flac"))
        if not candidates:
            raise RuntimeError(f"Karaoke model produced no instrumental stem in {work_dir}")

        clean_path = output_dir / "instrumental_clean.flac"
        shutil.copy2(candidates[0], clean_path)
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
) -> tuple[Path, Path]:
    profile = PROFILES[profile_name]
    output_dir.mkdir(parents=True, exist_ok=True)

    vocal_track = build_vocal_track(vocals, profile, manifest, original_vocals, slices_dir)
    vocals_out = output_dir / "vocals.flac"
    write_flac(vocals_out, vocal_track, TARGET_SR)

    inst_audio, inst_sr = load_audio(instrumental)
    inst_audio = resample_audio(inst_audio, inst_sr, TARGET_SR)

    inst_path = instrumental
    if clean_instrumental_flag and profile.karaoke_clean:
        inst_path = clean_instrumental(instrumental, output_dir, model_dir)
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
