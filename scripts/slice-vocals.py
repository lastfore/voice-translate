"""Slice vocal FLAC into phrase-level segments using Silero VAD."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa
from silero_vad import get_speech_timestamps, load_silero_vad

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "output" / "slices"

VAD_THRESHOLD = 0.45
MIN_SPEECH_MS = 250
MIN_SILENCE_MS = 500
SPEECH_PAD_MS = 80
FADE_IN_MS = 8
FADE_OUT_MS = 15


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


def slice_vocals(
    input_path: Path,
    output_dir: Path,
    *,
    threshold: float = VAD_THRESHOLD,
    min_speech_duration_ms: int = MIN_SPEECH_MS,
    min_silence_duration_ms: int = MIN_SILENCE_MS,
    speech_pad_ms: int = SPEECH_PAD_MS,
) -> tuple[list[Path], Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    model = load_silero_vad()
    audio, sr = sf.read(str(input_path), always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    vad_wav = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)
    vad_tensor = __import__("torch").from_numpy(vad_wav)
    timestamps = get_speech_timestamps(
        vad_tensor,
        model,
        threshold=threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=min_silence_duration_ms,
        speech_pad_ms=speech_pad_ms,
    )

    stem = input_path.stem
    written: list[Path] = []
    manifest_slices: list[dict[str, object]] = []

    for index, ts in enumerate(timestamps):
        start = int(ts["start"] / 16000 * sr)
        end = int(ts["end"] / 16000 * sr)
        start = max(start, 0)
        end = min(end, len(audio))
        if end <= start:
            continue

        segment = apply_fade(audio[start:end], sr, FADE_IN_MS, FADE_OUT_MS)
        out_name = f"{stem}_slice_{index:03d}.flac"
        out_path = output_dir / out_name
        sf.write(str(out_path), segment, sr, subtype="PCM_16")
        written.append(out_path)
        manifest_slices.append(
            {
                "id": f"slice_{index:03d}",
                "file": out_name,
                "start_ms": round(start / sr * 1000, 2),
                "end_ms": round(end / sr * 1000, 2),
            }
        )

    try:
        source = str(input_path.relative_to(ROOT))
    except ValueError:
        source = str(input_path)

    manifest = {
        "source": source,
        "sample_rate": sr,
        "fade_in_ms": FADE_IN_MS,
        "fade_out_ms": FADE_OUT_MS,
        "slices": manifest_slices,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return written, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Slice vocal audio with Silero VAD")
    parser.add_argument("input", type=Path, help="Path to vocals FLAC/WAV file")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    try:
        outputs, manifest_path = slice_vocals(args.input, args.output_dir)
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not outputs:
        print("No speech segments detected.")
        return 0

    print(f"Wrote {len(outputs)} slices to {args.output_dir}")
    print(f"Wrote manifest: {manifest_path}")
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
