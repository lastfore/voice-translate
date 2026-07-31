"""Tests for deharmonize stage (mocked separator)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from pipeline import paths
from pipeline.models import StageName, StageStatus
from pipeline.stages.deharmonize import (
    compute_backing_ratio,
    find_karaoke_stems,
    rename_stems_to_lead_backing,
    run_deharmonize,
    write_deharmonize_meta,
)
from pipeline.store import ProjectStore


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "output" / "separated").mkdir(parents=True)
    return tmp_path


def _write_tone(path: Path, amp: float = 0.3) -> None:
    sr = 44100
    t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False, dtype=np.float32)
    sf.write(str(path), (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr)


def test_rename_stems_to_lead_backing(root: Path) -> None:
    sep = paths.separated_dir()
    raw_lead = sep / "song_(Vocals)_karaoke.flac"
    raw_back = sep / "song_(Instrumental)_karaoke.flac"
    _write_tone(raw_lead, 0.4)
    _write_tone(raw_back, 0.1)

    lead, backing = rename_stems_to_lead_backing(
        raw_lead, raw_back, "song", "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt", sep
    )
    assert "(Lead)" in lead.name
    assert "(Backing)" in backing.name
    assert lead.is_file() and backing.is_file()


def test_compute_backing_ratio(root: Path) -> None:
    orig = root / "orig.flac"
    back = root / "back.flac"
    _write_tone(orig, 0.4)
    _write_tone(back, 0.08)
    ratio = compute_backing_ratio(orig, back)
    assert 0.15 < ratio < 0.25


def test_find_karaoke_stems(root: Path) -> None:
    sep = paths.separated_dir()
    lead = sep / "in_(Vocals)_model.flac"
    back = sep / "in_(Instrumental)_model.flac"
    _write_tone(lead)
    _write_tone(back)
    found_lead, found_back = find_karaoke_stems(sep)
    assert found_lead == lead
    assert found_back == back


def test_find_karaoke_stems_nested_input_vocals_tag(root: Path) -> None:
    """Input basename may contain lowercase (vocals) from separate stage."""
    sep = paths.separated_dir()
    lead = sep / "loveyou_(vocals)_kim_(Vocals)_karaoke.flac"
    back = sep / "loveyou_(vocals)_kim_(Instrumental)_karaoke.flac"
    _write_tone(lead)
    _write_tone(back)
    found_lead, found_back = find_karaoke_stems(sep)
    assert found_lead == lead
    assert found_back == back


def test_run_deharmonize_skips_low_backing(root: Path) -> None:
    mixed = root / "mixed.flac"
    _write_tone(mixed, 0.5)
    sep = paths.separated_dir()
    raw_lead = sep / "mixed_(Vocals)_karaoke.flac"
    raw_back = sep / "mixed_(Instrumental)_karaoke.flac"
    _write_tone(raw_lead, 0.48)
    _write_tone(raw_back, 0.01)

    ok = MagicMock(returncode=0, stdout="", stderr="")

    with patch("pipeline.stages.deharmonize.run_subprocess", return_value=ok):
        with patch("pipeline.stages.deharmonize.find_karaoke_stems", return_value=(raw_lead, raw_back)):
            result = run_deharmonize(
                "mixed",
                mixed,
                skip_backing_ratio_threshold=0.10,
            )

    assert result.skipped is True
    assert result.skip_reason == "low_backing_energy"
    assert result.lead_vocals is None
    meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
    assert meta["skipped"] is True


def test_run_deharmonize_produces_lead_backing(root: Path) -> None:
    mixed = root / "mixed.flac"
    _write_tone(mixed, 0.5)
    sep = paths.separated_dir()
    raw_lead = sep / "mixed_(Vocals)_karaoke.flac"
    raw_back = sep / "mixed_(Instrumental)_karaoke.flac"
    _write_tone(raw_lead, 0.35)
    _write_tone(raw_back, 0.15)

    ok = MagicMock(returncode=0, stdout="", stderr="")

    with patch("pipeline.stages.deharmonize.run_subprocess", return_value=ok):
        with patch("pipeline.stages.deharmonize.find_karaoke_stems", return_value=(raw_lead, raw_back)):
            result = run_deharmonize("mixed", mixed, skip_backing_ratio_threshold=0.10)

    assert result.skipped is False
    assert result.lead_vocals and result.backing_vocals
    assert paths.has_deharmonize_artifacts("mixed")


def test_store_resolve_lead_after_deharmonize(root: Path) -> None:
    store = ProjectStore(root)
    audio = root / "input" / "song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    _write_tone(audio)
    store.create_project("song", audio)

    sep = paths.separated_dir()
    mixed = sep / "song_(Vocals)_sep.flac"
    lead = sep / "song_(Lead)_karaoke.flac"
    backing = sep / "song_(Backing)_karaoke.flac"
    _write_tone(mixed)
    _write_tone(lead)
    _write_tone(backing)
    write_deharmonize_meta(
        paths.deharmonize_meta_path("song"),
        project_id="song",
        model="karaoke.ckpt",
        skipped=False,
        skip_reason=None,
        backing_ratio=0.3,
        params={},
    )

    project = store.scan_and_repair()[0]
    assert project.stages[StageName.DEHARMONIZE].status == StageStatus.DONE

    resolved_slice = store.resolve_stage_inputs("song", StageName.SLICE)
    assert "Lead" in resolved_slice["vocals"]

    resolved_merge = store.resolve_stage_inputs("song", StageName.MERGE, {"merge_mode": "whole_track"})
    assert resolved_merge.get("backing_vocals")
    assert "Lead" in resolved_merge.get("original_vocals", "")


def test_store_without_deharmonize_uses_separate_vocals(root: Path) -> None:
    store = ProjectStore(root)
    audio = root / "input" / "song.flac"
    audio.parent.mkdir(parents=True, exist_ok=True)
    _write_tone(audio)
    store.create_project("song", audio)

    sep = paths.separated_dir()
    mixed = sep / "song_(Vocals)_sep.flac"
    _write_tone(mixed)

    store.scan_and_repair()
    resolved = store.resolve_stage_inputs("song", StageName.SLICE)
    assert "Vocals" in resolved["vocals"]
    assert "Lead" not in resolved["vocals"]
