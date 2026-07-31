"""Tests for three-stem merge with backing vocals."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent


def _load_merge_audio():
    pytest.importorskip("librosa")
    script_path = ROOT / "scripts" / "merge-audio.py"
    spec = importlib.util.spec_from_file_location("merge_audio_backing_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def merge_mod():
    return _load_merge_audio()


def _write_tone(path: Path, freq: float, amp: float, sr: int = 44100, seconds: float = 0.5) -> None:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    audio = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr, subtype="PCM_16")


def test_mix_tracks_three_stem_rms(merge_mod, tmp_path: Path) -> None:
    sr = merge_mod.TARGET_SR
    lead = np.ones(sr, dtype=np.float32) * 0.3
    inst = np.stack([np.ones(sr, dtype=np.float32) * 0.2, np.ones(sr, dtype=np.float32) * 0.2], axis=1)
    backing = np.ones(sr, dtype=np.float32) * 0.1

    mixed = merge_mod.mix_tracks(lead, inst, 0.0, 0.0, backing=backing, backing_gain_db=0.0)
    mono = np.mean(mixed, axis=1)
    expected_rms = merge_mod.rms(lead + inst[:, 0] + backing)
    assert abs(merge_mod.rms(mono) - expected_rms) < 0.02


def test_merge_audio_three_stem(tmp_path: Path, merge_mod) -> None:
    out = tmp_path / "merged"
    vocals = tmp_path / "lead.flac"
    inst = tmp_path / "inst.flac"
    backing = tmp_path / "backing.flac"
    _write_tone(vocals, 440.0, 0.25)
    _write_tone(inst, 220.0, 0.15)
    _write_tone(backing, 880.0, 0.08)

    _, mixed = merge_mod.merge_audio(
        vocals,
        inst,
        out,
        profile_name="quick",
        backing_vocals=backing,
        backing_gain_db=0.0,
        skip_mastering=True,
    )
    assert mixed.is_file()
    audio, sr = sf.read(str(mixed))
    assert sr == merge_mod.TARGET_SR
    assert audio.size > 0


def test_clean_instrumental_ignored_with_backing(tmp_path: Path, merge_mod, capsys) -> None:
    out = tmp_path / "merged"
    vocals = tmp_path / "lead.flac"
    inst = tmp_path / "inst.flac"
    backing = tmp_path / "backing.flac"
    _write_tone(vocals, 440.0, 0.2)
    _write_tone(inst, 220.0, 0.15)
    _write_tone(backing, 880.0, 0.05)

    logs: list[str] = []

    def _on_line(line: str) -> None:
        logs.append(line)

    merge_mod.merge_audio(
        vocals,
        inst,
        out,
        profile_name="quick",
        backing_vocals=backing,
        clean_instrumental_flag=True,
        skip_mastering=True,
        on_line=_on_line,
    )
    assert any("clean_instrumental ignored" in line for line in logs)
