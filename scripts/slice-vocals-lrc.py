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


def slice_vocals_lrc(
    lrc_path: Path,
    vocals_path: Path,
    output_dir: Path,
    *,
    song_name: str | None = None,
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

    written: list[Path] = []
    manifest_slices: list[dict[str, object]] = []

    for index, line in enumerate(lyrics):
        start_ms = line.start_ms
        if index + 1 < len(lyrics):
            end_ms = lyrics[index + 1].start_ms
        else:
            end_ms = duration_ms

        start_sample = max(int(start_ms / 1000 * sr), 0)
        end_sample = min(int(end_ms / 1000 * sr), len(audio))
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
                "text": line.text,
                "lrc_line": line.line_no,
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
        "sample_rate": sr,
        "fade_in_ms": FADE_IN_MS,
        "fade_out_ms": FADE_OUT_MS,
        "slices": manifest_slices,
    }
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
    args = parser.parse_args()

    song_name = args.song_name or args.lrc.stem
    output_dir = args.output_dir or (DEFAULT_SLICES_ROOT / song_name)

    try:
        outputs, manifest_path, manifest = slice_vocals_lrc(
            args.lrc,
            args.vocals,
            output_dir,
            song_name=song_name,
        )
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not outputs:
        print("No slices written.")
        return 1

    print(f"Wrote {len(outputs)} slices to {output_dir}")
    print(f"Wrote manifest: {manifest_path}")
    print(f"Skipped metadata lines; first slice: [{manifest['slices'][0]['start_ms']}ms] {manifest['slices'][0]['text']}")
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
