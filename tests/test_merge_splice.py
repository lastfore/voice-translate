"""Tests for merge splice crossfade (P0/P3)."""

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
    spec = importlib.util.spec_from_file_location("merge_splice_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def merge_mod():
    return _load_merge_audio()


def _make_two_slice_manifest(
    tmp_path: Path,
    *,
    boundary_method: str = "valley_onset",
    subdir: str = ".",
) -> tuple[Path, Path, Path]:
    base = tmp_path if subdir in (".", "") else tmp_path / subdir
    slices_dir = base / "slices"
    converted_dir = base / "converted"
    slices_dir.mkdir(parents=True)
    converted_dir.mkdir(parents=True)

    sr = 44100
    duration = sr  # 1 second each
    tone_a = 0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 1, duration, dtype=np.float32))
    tone_b = 0.3 * np.sin(2 * np.pi * 880 * np.linspace(0, 1, duration, dtype=np.float32))

    names = ["part_slice_000.wav", "part_slice_001.wav"]
    for name, tone in zip(names, [tone_a, tone_b]):
        _write_wav(slices_dir / name, tone, sr)
        _write_wav(converted_dir / name, tone, sr)

    manifest_path = slices_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "fade_in_ms": 8,
                "fade_out_ms": 15,
                "boundary_diagnostics": [
                    {
                        "boundary_index": 0,
                        "method": boundary_method,
                        "next_slice_id": "slice_001",
                    }
                ],
                "slices": [
                    {
                        "id": "slice_000",
                        "file": names[0],
                        "start_ms": 0,
                        "end_ms": 1000,
                    },
                    {
                        "id": "slice_001",
                        "file": names[1],
                        "start_ms": 1000,
                        "end_ms": 2000,
                        "boundary_method": boundary_method,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, converted_dir, slices_dir


def test_crossfade_zero_preserves_legacy_overlay(tmp_path: Path, merge_mod) -> None:
    manifest_path, converted_dir, slices_dir = _make_two_slice_manifest(tmp_path)
    profile = merge_mod.PROFILES["balanced"]
    splice_off = merge_mod.SpliceParams(boundary_crossfade_ms=0)

    timeline_legacy, _ = merge_mod.build_from_slices(
        manifest_path, converted_dir, slices_dir, profile, None, splice=splice_off
    )

    # Rebuild with default SpliceParams (also 0)
    timeline_default, logs = merge_mod.build_from_slices(
        manifest_path, converted_dir, slices_dir, profile, None
    )

    np.testing.assert_allclose(timeline_legacy, timeline_default, rtol=0, atol=1e-6)
    assert logs == []


def test_equal_power_midpoint_energy(tmp_path: Path, merge_mod) -> None:
    manifest_path, converted_dir, slices_dir = _make_two_slice_manifest(tmp_path)
    profile = merge_mod.PROFILES["balanced"]
    splice = merge_mod.SpliceParams(boundary_crossfade_ms=20, boundary_crossfade_curve="equal_power")

    timeline, logs = merge_mod.build_from_slices(
        manifest_path, converted_dir, slices_dir, profile, None, splice=splice
    )

    assert len(logs) == 1
    overlap = int(logs[0]["overlap_samples"])
    boundary = int(logs[0]["boundary_sample"])
    start = boundary - overlap // 2
    region = timeline[start : start + overlap]
    mid = float(np.sqrt(np.mean(region**2)))
    left = float(np.sqrt(np.mean(timeline[max(0, start - overlap) : start] ** 2)))
    right = float(
        np.sqrt(np.mean(timeline[start + overlap : start + 2 * overlap] ** 2))
    )
    ref = max(left, right, 1e-6)
    ratio_db = 20 * np.log10(max(mid, 1e-8) / ref)
    assert -3.0 <= ratio_db <= 3.0


def test_zero_crossing_reduces_jump(merge_mod) -> None:
    sr = 44100
    segment = np.sin(2 * np.pi * 440 * np.linspace(0, 0.01, int(sr * 0.01), dtype=np.float32))
    offset = merge_mod.find_zero_crossing_offset(segment, search_radius=50)
    assert isinstance(offset, int)
    assert -50 <= offset <= 50


def test_effective_crossfade_clamps_legato(merge_mod) -> None:
    assert merge_mod.effective_crossfade_ms(20, "legato_onset") == 10
    assert merge_mod.effective_crossfade_ms(20, "valley_onset") == 20
    assert merge_mod.effective_crossfade_ms(0, "legato_onset") == 0


def test_lufs_match_reduces_boundary_delta(tmp_path: Path, merge_mod) -> None:
    manifest_path, converted_dir, slices_dir = _make_two_slice_manifest(tmp_path)
    profile = merge_mod.PROFILES["balanced"]

    # Boost second slice head for measurable mismatch
    conv_b = converted_dir / "part_slice_001.wav"
    sr = 44100
    tone = 0.6 * np.sin(2 * np.pi * 880 * np.linspace(0, 1, sr, dtype=np.float32))
    _write_wav(conv_b, tone, sr)

    splice = merge_mod.SpliceParams(boundary_lufs_match_ms=300)
    timeline, logs = merge_mod.build_from_slices(
        manifest_path, converted_dir, slices_dir, profile, None, splice=splice
    )

    boundary = int(1000 * sr / 1000)
    w = int(0.3 * sr)
    before = timeline[boundary - w : boundary]
    after = timeline[boundary : boundary + w]
    delta_db = abs(merge_mod._rms_db(before) - merge_mod._rms_db(after))
    assert timeline.shape[0] > 0
    assert logs
    assert logs[0].get("lufs_match_ms") == 300
    assert delta_db < 6.0


def test_wsola_only_on_legato(tmp_path: Path, merge_mod, monkeypatch) -> None:
    manifest_path, converted_dir, slices_dir = _make_two_slice_manifest(
        tmp_path, boundary_method="silence_onset"
    )
    profile = merge_mod.PROFILES["balanced"]
    splice = merge_mod.SpliceParams(splice_wsola_search_ms=15)

    called = {"count": 0}
    original = merge_mod.ncc_splice_offset

    def counting(*args, **kwargs):
        called["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(merge_mod, "ncc_splice_offset", counting)
    merge_mod.build_from_slices(
        manifest_path, converted_dir, slices_dir, profile, None, splice=splice
    )
    assert called["count"] == 0

    manifest_path2, converted_dir2, slices_dir2 = _make_two_slice_manifest(
        tmp_path, boundary_method="legato_onset", subdir="legato"
    )
    called["count"] = 0
    _, logs = merge_mod.build_from_slices(
        manifest_path2, converted_dir2, slices_dir2, profile, None, splice=splice
    )
    assert called["count"] == 1
    assert any("wsola_delta_samples" in entry for entry in logs)


def test_quick_profile_with_crossfade_param(tmp_path: Path, merge_mod) -> None:
    manifest_path, converted_dir, slices_dir = _make_two_slice_manifest(tmp_path)
    profile = merge_mod.PROFILES["quick"]
    splice = merge_mod.SpliceParams(boundary_crossfade_ms=15)

    # quick profile: stitch_slices=False — whole-track path ignores splice params without error
    whole = np.linspace(0.0, 0.2, 44100, dtype=np.float32)
    whole_path = converted_dir / "full.wav"
    _write_wav(whole_path, whole)

    vocal_track, logs = merge_mod.build_vocal_track(
        whole_path,
        profile,
        manifest_path,
        None,
        slices_dir,
        splice=splice,
    )
    assert vocal_track.shape[0] > 0
    assert logs == []
