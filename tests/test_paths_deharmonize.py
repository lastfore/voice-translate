"""Tests for lead/backing path globs (deharmonize P0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import paths


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "output" / "separated").mkdir(parents=True)
    return tmp_path


def test_separated_lead_and_backing_glob(root: Path) -> None:
    sep = root / "output" / "separated"
    lead = sep / "mysong_(Lead)_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.flac"
    backing = sep / "mysong_(Backing)_mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.flac"
    lead.write_bytes(b"x")
    backing.write_bytes(b"x")

    assert paths.separated_lead_vocals_path("mysong") == lead
    assert paths.separated_backing_vocals_path("mysong") == backing
    assert paths.has_deharmonize_artifacts("mysong") is True


def test_has_deharmonize_false_when_incomplete(root: Path) -> None:
    sep = root / "output" / "separated"
    (sep / "mysong_(Lead)_model.flac").write_bytes(b"x")
    assert paths.has_deharmonize_artifacts("mysong") is False


def test_deharmonize_meta_path(root: Path) -> None:
    assert paths.deharmonize_meta_path("demo") == root / "output" / "separated" / "demo_deharmonize_meta.json"
