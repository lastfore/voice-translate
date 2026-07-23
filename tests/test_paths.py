"""Tests for pipeline.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import paths


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir()
    (tmp_path / "output" / "separated").mkdir(parents=True)
    return tmp_path


def test_get_root_from_env(root: Path) -> None:
    assert paths.get_root() == root.resolve()


def test_separated_vocals_glob(root: Path) -> None:
    sep = root / "output" / "separated"
    vocal = sep / "mysong_(Vocals)_mel_band_roformer_kim_ft_unwa.flac"
    vocal.write_bytes(b"x")
    inst = sep / "mysong_(Instrumental)_mel_band_roformer_kim_ft_unwa.flac"
    inst.write_bytes(b"x")

    assert paths.separated_vocals_path("mysong") == vocal
    assert paths.separated_instrumental_path("mysong") == inst


def test_input_audio_path_multiple_extensions(root: Path) -> None:
    (root / "input" / "demo.wav").write_bytes(b"x")
    assert paths.input_audio_path("demo") == root / "input" / "demo.wav"
    assert paths.input_audio_path("missing") is None


def test_project_meta_path(root: Path) -> None:
    assert paths.project_meta_path("test") == root / "output" / ".projects" / "test" / "project.json"


def test_slices_and_converted_dirs(root: Path) -> None:
    assert paths.slices_dir("abc") == root / "output" / "slices" / "abc"
    assert paths.converted_dir("abc") == root / "output" / "converted" / "abc"
    assert paths.merged_dir("abc") == root / "output" / "merged" / "abc"
