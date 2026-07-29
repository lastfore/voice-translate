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


def test_separated_instrumental_other_stem(root: Path) -> None:
    sep = root / "output" / "separated"
    vocal = sep / "mysong_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
    vocal.write_bytes(b"x")
    other = sep / "mysong_(other)_mel_band_roformer_kim_ft_unwa.flac"
    other.write_bytes(b"x")

    assert paths.separated_vocals_path("mysong") == vocal
    assert paths.separated_instrumental_path("mysong") == other


def test_paired_vocals_from_instrumental(root: Path) -> None:
    sep = root / "output" / "separated"
    vocal = sep / "test_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
    vocal.write_bytes(b"x")
    other = sep / "test_(other)_mel_band_roformer_kim_ft_unwa.flac"
    other.write_bytes(b"x")

    assert paths.paired_vocals_from_instrumental(other) == vocal
    assert paths.paired_vocals_from_instrumental(vocal) is None


def test_input_audio_path_multiple_extensions(root: Path) -> None:
    (root / "input" / "demo.wav").write_bytes(b"x")
    assert paths.input_audio_path("demo") == root / "input" / "demo.wav"
    assert paths.input_audio_path("missing") is None


def test_project_meta_path(root: Path) -> None:
    assert paths.project_meta_path("test") == root / "output" / ".projects" / "test" / "project.json"


def test_slices_and_converted_dirs(root: Path) -> None:
    assert paths.slices_dir("abc") == root / "output" / "slices" / "abc"
    assert paths.converted_dir("abc") == root / "output" / "converted" / "abc"
    assert paths.converted_full_dir("abc") == root / "output" / "converted" / "abc" / "full"
    assert paths.converted_slices_dir("abc") == root / "output" / "converted" / "abc" / "slices"
    assert paths.converted_full_track_path("abc") == root / "output" / "converted" / "abc" / "full" / "full.flac"
    assert paths.merged_dir("abc") == root / "output" / "merged" / "abc"
    assert paths.merged_full_dir("abc") == root / "output" / "merged" / "abc" / "full"


def test_resolve_converted_layout_new_and_legacy(root: Path) -> None:
    base = root / "output" / "converted" / "demo"
    (base / "full").mkdir(parents=True)
    (base / "full" / "full.flac").write_bytes(b"x")
    (base / "slices").mkdir()
    (base / "slices" / "song_slice_000.flac").write_bytes(b"x")

    assert paths.resolve_converted_full_track("demo") == base / "full" / "full.flac"
    assert paths.resolve_converted_slices_dir("demo") == base / "slices"
    assert paths.has_converted_artifacts("demo")


def test_resolve_converted_layout_legacy_flat(root: Path) -> None:
    base = root / "output" / "converted" / "legacy"
    base.mkdir(parents=True)
    (base / "full.flac").write_bytes(b"x")
    (base / "song_slice_000.flac").write_bytes(b"x")

    assert paths.resolve_converted_full_track("legacy") == base / "full.flac"
    assert paths.resolve_converted_slices_dir("legacy") == base


def test_collect_project_artifacts_paths(root: Path) -> None:
    (root / "output" / ".projects" / "foo").mkdir(parents=True)
    (root / "input" / "foo.flac").write_bytes(b"x")
    (root / "output" / "slices" / "foo").mkdir(parents=True)

    group = paths.collect_project_artifacts("foo")
    assert group.metadata
    assert group.artifacts
    assert group.inputs

    scoped = paths.paths_for_scope(group, "all")
    assert any("foo.flac" in str(p) for p in scoped)
