"""Unit and integration tests for LRC slice onset alignment."""

from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_slice_vocals_lrc():
    script_path = ROOT / "scripts" / "slice-vocals-lrc.py"
    spec = importlib.util.spec_from_file_location("slice_vocals_lrc_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_wav(path: Path, audio: np.ndarray, sr: int = 44100) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def _write_lrc(path: Path, lines: list[tuple[str, str]]) -> None:
    content = "\n".join(f"[{ts}]{text}" for ts, text in lines) + "\n"
    path.write_text(content, encoding="utf-8")


def _synthetic_onset_audio(
    sr: int,
    duration_ms: float,
    onset_ms: float,
    *,
    pre_level: float = 0.001,
    post_level: float = 0.5,
) -> np.ndarray:
    total = int(sr * duration_ms / 1000)
    onset_sample = int(sr * onset_ms / 1000)
    audio = np.full(total, pre_level, dtype=np.float32)
    audio[onset_sample:] = post_level
    return audio


def _synthetic_tail_blip_audio(
    sr: int,
    duration_ms: float,
    *,
    sing_end_ms: float,
    blip_start_ms: float,
    blip_level: float = 0.05,
    sing_level: float = 0.5,
    silence_level: float = 0.0003,
) -> np.ndarray:
    total = int(sr * duration_ms / 1000)
    audio = np.full(total, silence_level, dtype=np.float32)
    audio[: int(sr * sing_end_ms / 1000)] = sing_level
    blip_end = min(int(sr * (blip_start_ms + 50) / 1000), total)
    audio[int(sr * blip_start_ms / 1000) : blip_end] = blip_level
    return audio


@pytest.fixture
def lrc_mod():
    return _load_slice_vocals_lrc()


def test_lrc_strict_matches_legacy_boundaries(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
            ("00:20.00", "line three"),
        ],
    )
    _write_wav(vocals_path, np.zeros(int(44100 * 25), dtype=np.float32))

    _, _, manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        boundary_mode="lrc_strict",
    )

    slices = manifest["slices"]
    assert len(slices) == 3
    assert slices[0]["start_ms"] == 10000
    assert slices[0]["end_ms"] == 15000
    assert slices[1]["start_ms"] == 15000
    assert slices[1]["end_ms"] == 20000
    assert slices[0]["lrc_start_ms"] == 10000
    assert slices[0]["lrc_end_ms"] == 15000
    assert manifest["boundary_mode"] == "lrc_strict"


def test_onset_detected_at_minus_300ms(tmp_path: Path, lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    onset_ms = next_lrc - 300.0
    audio = _synthetic_onset_audio(sr, 25000, onset_ms)

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        search_margin_ms=400,
        onset_min_lead_silence_ms=80,
        min_slice_ms=500,
    )

    assert not result.fallback
    assert result.method == "silence_onset"
    assert result.reason == "aligned_silence"
    assert abs(result.t_cut - onset_ms) <= 20


def test_dual_onset_picks_rightmost_candidate(lrc_mod) -> None:
    sr = 44100
    duration_ms = 25000.0
    early_onset = 14520.0  # brief tail blip (false candidate)
    late_onset = 14700.0  # real next-line onset
    audio = np.full(int(sr * duration_ms / 1000), 0.001, dtype=np.float32)
    early_start = int(sr * early_onset / 1000)
    early_end = int(sr * (early_onset + 30) / 1000)
    audio[early_start:early_end] = 0.5
    audio[int(sr * late_onset / 1000) :] = 0.5

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=15000.0,
        next_line_end_ms=20000.0,
    )

    assert not result.fallback
    assert abs(result.t_cut - late_onset) <= 30


def test_short_slice_triggers_fallback(lrc_mod) -> None:
    sr = 44100
    next_lrc = 6000.0
    # Continuous energy until onset; next line ends at 6400 -> only 480ms after cut at 5920.
    audio = np.full(int(sr * 12), 0.08, dtype=np.float32)
    audio[int(sr * 5920 / 1000) :] = 0.5

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=5000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=6400.0,
        search_margin_ms=800,
        onset_min_lead_silence_ms=20,
        min_slice_ms=500,
    )

    assert result.fallback
    assert result.t_cut == next_lrc
    assert "next_slice_too_short" in result.reason
    assert "safety_margin_skipped" in result.reason


def test_manifest_contains_lrc_fields(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    audio = _synthetic_onset_audio(44100, 20000, 14700.0)
    _write_wav(vocals_path, audio)

    _, _, manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, out_dir)

    assert manifest["boundary_mode"] == "onset_aligned"
    assert "search_margin_ms" in manifest
    assert "onset_min_lead_silence_ms" in manifest
    assert manifest["slices"][1]["lrc_start_ms"] == 15000
    assert manifest["slices"][1]["start_ms"] <= manifest["slices"][1]["lrc_start_ms"]
    assert "boundary_in_fallback" in manifest["slices"][1]


def test_manifest_contains_boundary_diagnostics(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    audio = _synthetic_onset_audio(44100, 20000, 14700.0)
    _write_wav(vocals_path, audio)

    _, _, manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, out_dir)

    diagnostics = manifest["boundary_diagnostics"]
    assert len(diagnostics) == 1
    item = diagnostics[0]
    assert item["boundary_index"] == 0
    assert item["next_slice_id"] == "slice_001"
    assert item["aligned"] is True
    assert item["method"] == "silence_onset"
    assert item["reason"] == "aligned_silence"
    assert item["delta_ms"] > 0


def test_format_boundary_diagnostic_line(lrc_mod) -> None:
    item = lrc_mod.BoundaryDiagnostic(
        boundary_index=2,
        next_slice_id="slice_003",
        next_lrc_ms=34480.0,
        t_cut_ms=34433.63,
        aligned=True,
        reason="aligned_legato",
        method="legato_onset",
        delta_ms=46.37,
    )
    line = lrc_mod.format_boundary_diagnostic_line(item)
    assert "[BOUNDARY]" in line
    assert "i=02 slice_003" in line
    assert "aligned" in line
    assert "method=legato_onset" in line
    assert "reason=aligned_legato" in line
    assert "delta=46.37ms" in line


def test_legato_fallback_on_continuous_rise(lrc_mod) -> None:
    sr = 44100
    audio = np.full(int(sr * 20), 0.08, dtype=np.float32)
    rise_start = int(sr * 14500 / 1000)
    rise_end = int(sr * 14600 / 1000)
    for sample in range(rise_start, rise_end):
        progress = (sample - rise_start) / max(rise_end - rise_start, 1)
        audio[sample] = 0.08 + 0.35 * progress
    audio[rise_end:] = 0.45

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=15000.0,
        next_line_end_ms=20000.0,
        search_margin_ms=800,
        onset_min_lead_silence_ms=80,
        min_slice_ms=500,
    )

    assert not result.fallback
    assert result.method == "legato_onset"
    assert result.reason == "aligned_legato"
    assert result.t_cut < 15000.0


def test_legato_used_when_silence_path_fails_in_slice(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    sr = 44100
    audio = np.full(int(sr * 20), 0.08, dtype=np.float32)
    rise_start = int(sr * 14500 / 1000)
    rise_end = int(sr * 14600 / 1000)
    for sample in range(rise_start, rise_end):
        progress = (sample - rise_start) / max(rise_end - rise_start, 1)
        audio[sample] = 0.08 + 0.35 * progress
    audio[rise_end:] = 0.45
    _write_wav(vocals_path, audio)

    _, _, manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, out_dir)

    diagnostic = manifest["boundary_diagnostics"][0]
    assert diagnostic["method"] == "legato_onset"
    assert diagnostic["aligned"] is True
    assert manifest["slices"][1]["start_ms"] < manifest["slices"][1]["lrc_start_ms"]


def test_reslice_preserves_overrides_via_lrc_start_ms(tmp_path: Path, lrc_mod) -> None:
    from pipeline.models import SliceMode
    from pipeline.slice_overrides import SliceOverrides, merge_after_reslice

    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    audio = _synthetic_onset_audio(44100, 20000, 14700.0)
    _write_wav(vocals_path, audio)

    _, _, old_manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        boundary_mode="lrc_strict",
    )
    old = SliceOverrides(slices={"slice_001": {"semi_tone_shift": 2}})

    _, _, new_manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, out_dir)

    merged = merge_after_reslice(
        old,
        new_manifest,
        mode=SliceMode.LRC.value,
        old_manifest=old_manifest,
    )
    assert merged.slices["slice_001"]["semi_tone_shift"] == 2
    assert not merged.orphans


def test_merge_timeline_continuous_after_onset_align(tmp_path: Path, lrc_mod) -> None:
    pytest.importorskip("librosa")
    spec = importlib.util.spec_from_file_location(
        "merge_audio_onset_test",
        ROOT / "scripts" / "merge-audio.py",
    )
    assert spec and spec.loader
    merge_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = merge_mod
    spec.loader.exec_module(merge_mod)

    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    slices_dir = tmp_path / "slices"
    converted_dir = tmp_path / "converted"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
            ("00:20.00", "line three"),
        ],
    )
    audio = np.full(int(44100 * 25), 0.001, dtype=np.float32)
    for onset in (14700.0, 19700.0):
        audio[int(44100 * onset / 1000) :] = 0.4
    _write_wav(vocals_path, audio)

    _, manifest_path, manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, slices_dir)
    converted_dir.mkdir()

    for item in manifest["slices"]:
        src = slices_dir / str(item["file"])
        dst = converted_dir / str(item["file"])
        dst.write_bytes(src.read_bytes())

    profile = merge_mod.PROFILES["balanced"]
    timeline, _ = merge_mod.build_from_slices(
        manifest_path,
        converted_dir,
        slices_dir,
        profile,
        original_vocals=vocals_path,
    )

    starts = [float(item["start_ms"]) for item in manifest["slices"]]
    ends = [float(item["end_ms"]) for item in manifest["slices"]]
    for idx in range(len(starts) - 1):
        assert ends[idx] == starts[idx + 1]
    assert timeline.shape[0] > 0


def test_valley_cuts_before_tail_blip(lrc_mod) -> None:
    sr = 44100
    next_lrc = 2680.0
    audio = _synthetic_tail_blip_audio(
        sr,
        duration_ms=3000,
        sing_end_ms=1800,
        blip_start_ms=2600,
    )

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=0.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=5000.0,
        search_margin_ms=400,
        min_slice_ms=500,
    )

    assert not result.fallback
    assert result.method == "valley_onset"
    assert result.reason == "aligned_valley"
    assert result.t_cut < 2600.0
    assert result.t_cut >= 1800.0


def test_valley_searches_latter_half_only(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    line_start = 10000.0
    search_margin = 400
    window_start = max(line_start + 500, next_lrc - search_margin)
    valley_window_start = window_start + (next_lrc - window_start) * 0.5

    audio = np.full(int(sr * 20), 0.001, dtype=np.float32)
    audio[: int(sr * 14600 / 1000)] = 0.5
    audio[int(sr * 14600 / 1000) : int(sr * valley_window_start / 1000)] = 0.0005
    audio[int(sr * valley_window_start / 1000) : int(sr * 14900 / 1000)] = 0.002
    audio[int(sr * 14950 / 1000) : int(sr * 15000 / 1000)] = 0.5

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=line_start,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        search_margin_ms=search_margin,
        min_slice_ms=500,
    )

    assert not result.fallback
    assert result.method == "valley_onset"
    assert result.t_cut >= valley_window_start


def test_valley_fails_falls_to_onset(lrc_mod) -> None:
    sr = 44100
    onset_ms = 14700.0
    audio = _synthetic_onset_audio(sr, 20000, onset_ms)

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=15000.0,
        next_line_end_ms=20000.0,
        search_margin_ms=400,
        onset_min_lead_silence_ms=80,
        min_slice_ms=500,
    )

    assert not result.fallback
    assert result.method == "silence_onset"
    assert abs(result.t_cut - onset_ms) <= 20


def test_fallback_applies_safety_margin(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    audio = np.zeros(int(sr * 20), dtype=np.float32)

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        safety_margin_ms=80,
        min_slice_ms=500,
    )

    assert result.fallback
    assert result.method == "lrc_fallback_margin"
    assert result.t_cut == next_lrc - 80
    assert result.safety_margin_applied_ms == 80
    assert result.reason == "silent_window"


def test_safety_margin_skipped_when_too_short(lrc_mod) -> None:
    sr = 44100
    next_lrc = 6000.0
    audio = np.full(int(sr * 12), 0.08, dtype=np.float32)

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=5000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=6400.0,
        safety_margin_ms=80,
        min_slice_ms=500,
    )

    assert result.fallback
    assert result.t_cut == next_lrc
    assert "safety_margin_skipped" in result.reason
    assert result.safety_margin_applied_ms == 0


def test_safety_margin_zero_disables(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    audio = np.zeros(int(sr * 20), dtype=np.float32)

    result, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        safety_margin_ms=0,
        min_slice_ms=500,
    )

    assert result.fallback
    assert result.method == "lrc_fallback"
    assert result.t_cut == next_lrc
    assert result.safety_margin_applied_ms == 0


def test_lrc_strict_unchanged_with_tail_blip(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:00.00", "line one"),
            ("00:02.68", "line two"),
        ],
    )
    audio = _synthetic_tail_blip_audio(
        44100,
        duration_ms=5000,
        sing_end_ms=1800,
        blip_start_ms=2600,
    )
    _write_wav(vocals_path, audio)

    _, _, manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        boundary_mode="lrc_strict",
        safety_margin_ms=80,
    )

    assert manifest["slices"][0]["end_ms"] == 2680
    assert manifest["slices"][1]["start_ms"] == 2680


def test_manifest_contains_valley_fields(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:00.00", "line one"),
            ("00:02.68", "line two"),
        ],
    )
    audio = _synthetic_tail_blip_audio(
        44100,
        duration_ms=5000,
        sing_end_ms=1800,
        blip_start_ms=2600,
    )
    _write_wav(vocals_path, audio)

    _, _, manifest = lrc_mod.slice_vocals_lrc(lrc_path, vocals_path, out_dir)

    assert manifest["safety_margin_ms"] == 80
    assert "valley_boundary_count" in manifest
    assert manifest["valley_boundary_count"] >= 1
    diag = manifest["boundary_diagnostics"][0]
    assert "safety_margin_applied_ms" in diag


def test_g2p_extends_window_for_sibilant(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    onset_ms = next_lrc - 80.0
    audio = _synthetic_onset_audio(sr, 25000, onset_ms, pre_level=0.001, post_level=0.5)

    result_off, g2p_off = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        next_line_text="思君",
        g2p_preroll_ms=0,
        search_margin_ms=50,
        onset_min_lead_silence_ms=80,
    )
    result_on, g2p_on = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        next_line_text="思君",
        g2p_preroll_ms=100,
        search_margin_ms=50,
        onset_min_lead_silence_ms=80,
    )

    assert g2p_off == 0.0
    assert g2p_on == 100.0
    assert abs(result_on.t_cut - onset_ms) <= 25
    assert result_on.t_cut < result_off.t_cut - 10


def test_g2p_disabled_when_zero(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    audio = _synthetic_onset_audio(sr, 25000, next_lrc - 300.0)

    result_a, g2p_a = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        next_line_text="思",
        g2p_preroll_ms=0,
    )
    result_b, g2p_b = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        g2p_preroll_ms=0,
    )

    assert g2p_a == 0.0
    assert g2p_b == 0.0
    assert result_a.t_cut == result_b.t_cut


def test_zcr_valley_prefers_silence_gap(lrc_mod) -> None:
    sr = 44100
    next_lrc = 15000.0
    window_start = next_lrc - 400
    total = int(sr * 25)
    audio = np.full(total, 0.04, dtype=np.float32)
    gap_center = next_lrc - 280
    gap_start = int(sr * (gap_center - 30) / 1000)
    gap_end = int(sr * (gap_center + 30) / 1000)
    audio[gap_start:gap_end] = 0.0005
    valley_rms = int(sr * (next_lrc - 120) / 1000)
    audio[valley_rms : valley_rms + int(sr * 0.05)] = 0.015

    result_plain, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        boundary_zcr_weight=0.0,
        search_margin_ms=400,
    )
    result_zcr, _ = lrc_mod.detect_boundary(
        audio,
        sr,
        line_start_ms=10000.0,
        next_lrc_ts=next_lrc,
        next_line_end_ms=20000.0,
        boundary_zcr_weight=0.25,
        search_margin_ms=400,
    )

    assert not result_plain.fallback
    assert not result_zcr.fallback
    assert result_zcr.t_cut <= result_plain.t_cut


@pytest.mark.integration
def test_remote_phoneme_align_skipped_in_manifest(tmp_path: Path, lrc_mod) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    _write_wav(vocals_path, np.zeros(int(44100 * 20), dtype=np.float32))

    _, _, manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        phoneme_align_mode="remote",
        phoneme_align_remote_url="http://example.com/align",
    )

    assert manifest["phoneme_align_mode"] == "remote"
    assert manifest["phoneme_align_skipped_remote_count"] >= 1
    assert manifest["phoneme_align_skip_counts"]["remote_not_implemented"] >= 1


def test_phoneme_fallback_only_skip_counts_in_manifest(tmp_path: Path, lrc_mod, monkeypatch) -> None:
    lrc_path = tmp_path / "song.lrc"
    vocals_path = tmp_path / "vocals.wav"
    out_dir = tmp_path / "slices"

    _write_lrc(
        lrc_path,
        [
            ("00:10.00", "line one"),
            ("00:15.00", "line two"),
        ],
    )
    _write_wav(vocals_path, np.zeros(int(44100 * 20), dtype=np.float32))

    def fake_refine_boundary(**_kwargs):
        from phoneme_align import PhonemeAlignResult

        return PhonemeAlignResult(skipped=True, reason="not_fallback_boundary")

    monkeypatch.setattr(lrc_mod, "refine_boundary", fake_refine_boundary)

    _, _, manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        phoneme_align_mode="local_cpu",
        phoneme_align_fallback_only=True,
    )

    assert manifest["phoneme_align_applied_count"] == 0
    assert manifest["phoneme_align_skip_counts"]["not_fallback_boundary"] == 1
    assert manifest["boundary_diagnostics"][0]["phoneme_align_skip_reason"] == "not_fallback_boundary"


@pytest.mark.integration
def test_loveyou_reslice_when_available(lrc_mod) -> None:
    """Run against local loveyou assets when present."""
    lrc_path = ROOT / "input" / "loveyou.lrc"
    vocals_path = ROOT / "output" / "separated" / "loveyou_(Vocals)_mel_band_roformer_kim_ft_unwa.flac"
    if not lrc_path.is_file() or not vocals_path.is_file():
        pytest.skip("loveyou fixtures not available")

    out_dir = ROOT / "output" / "slices" / "loveyou" / "lrc-test-onset"
    old_manifest_path = ROOT / "output" / "slices" / "loveyou" / "lrc" / "manifest.json"
    old_count = None
    if old_manifest_path.is_file():
        old_count = len(json.loads(old_manifest_path.read_text(encoding="utf-8")).get("slices", []))

    _, _, manifest = lrc_mod.slice_vocals_lrc(
        lrc_path,
        vocals_path,
        out_dir,
        song_name="loveyou",
    )

    slices = manifest["slices"]
    if old_count is not None:
        assert len(slices) == old_count
    for index, item in enumerate(slices):
        if index == 0:
            continue
        assert float(item["start_ms"]) <= float(item["lrc_start_ms"]) + 1.0
