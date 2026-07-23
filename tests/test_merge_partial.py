"""Tests for partial-slice merge fallback (convert limit < manifest size)."""

from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _write_wav(path: Path, audio: np.ndarray, sr: int = 44100) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def _load_merge_audio():
    pytest.importorskip("librosa")
    script_path = ROOT / "scripts" / "merge-audio.py"
    spec = importlib.util.spec_from_file_location("merge_audio_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def merge_mod():
    return _load_merge_audio()


def test_build_from_slices_falls_back_to_original(tmp_path: Path, merge_mod) -> None:
    slices_dir = tmp_path / "slices"
    converted_dir = tmp_path / "converted"
    slices_dir.mkdir()
    converted_dir.mkdir()

    slice_names = [f"part_slice_{i:03d}.wav" for i in range(4)]
    for name in slice_names:
        audio = np.linspace(-0.1, 0.1, 4410, dtype=np.float32)
        _write_wav(slices_dir / name, audio)

    # Only convert first two slices (simulates --limit 2).
    for name in slice_names[:2]:
        audio = np.linspace(0.0, 0.2, 4410, dtype=np.float32)
        _write_wav(converted_dir / name, audio)

    manifest_path = slices_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fade_in_ms": 8,
                "fade_out_ms": 15,
                "slices": [
                    {
                        "id": f"slice_{i:03d}",
                        "file": name,
                        "start_ms": i * 1000,
                        "end_ms": (i + 1) * 1000,
                    }
                    for i, name in enumerate(slice_names)
                ],
            }
        ),
        encoding="utf-8",
    )

    profile = merge_mod.PROFILES["balanced"]
    timeline = merge_mod.build_from_slices(
        manifest_path,
        converted_dir,
        slices_dir,
        profile,
        original_vocals=None,
    )

    assert timeline.shape[0] > 0
    assert np.any(timeline != 0)


def test_build_from_slices_missing_both_raises(tmp_path: Path, merge_mod) -> None:
    slices_dir = tmp_path / "slices"
    converted_dir = tmp_path / "converted"
    slices_dir.mkdir()
    converted_dir.mkdir()

    manifest_path = slices_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fade_in_ms": 8,
                "fade_out_ms": 15,
                "slices": [
                    {
                        "id": "slice_000",
                        "file": "missing.wav",
                        "start_ms": 0,
                        "end_ms": 1000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    profile = merge_mod.PROFILES["balanced"]
    with pytest.raises(FileNotFoundError, match="Neither converted nor original"):
        merge_mod.build_from_slices(
            manifest_path,
            converted_dir,
            slices_dir,
            profile,
            original_vocals=None,
        )
