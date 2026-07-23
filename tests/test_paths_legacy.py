"""Tests for legacy path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import paths


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    return tmp_path


def test_extract_project_id_from_vocals_filename() -> None:
    assert paths.extract_project_id_from_vocals_filename("mysong_(Vocals)_model.flac") == "mysong"
    assert paths.extract_project_id_from_vocals_filename("other.wav") is None


def test_infer_project_ids_from_separated(root: Path) -> None:
    sep = root / "output" / "separated"
    sep.mkdir(parents=True)
    (sep / "alpha_(Vocals)_x.flac").write_bytes(b"1")
    (sep / "beta_(Vocals)_y.flac").write_bytes(b"2")
    assert paths.infer_project_ids_from_separated() == {"alpha", "beta"}
