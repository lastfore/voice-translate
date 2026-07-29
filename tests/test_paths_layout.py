"""Tests for per-mode slice/converted/merged path layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import paths
from pipeline.migrate_slices_layout import migrate_legacy_slices_layout


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir(parents=True)
    return tmp_path


def test_mode_path_helpers(root: Path) -> None:
    assert paths.slices_mode_dir("song", "lrc") == root / "output" / "slices" / "song" / "lrc"
    assert paths.converted_mode_dir("song", "vad") == root / "output" / "converted" / "song" / "vad"
    assert paths.merged_mixed_path("song", "lrc") == root / "output" / "merged" / "song" / "lrc" / "mixed.flac"
    assert paths.merged_full_mixed_path("song") == root / "output" / "merged" / "song" / "full" / "mixed.flac"
    assert paths.slices_overrides_path("song", "lrc") == root / "output" / "slices" / "song" / "lrc" / "overrides.json"


def test_resolve_converted_mode_dir(root: Path) -> None:
    base = paths.converted_mode_dir("demo", "lrc")
    base.mkdir(parents=True)
    (base / "song_slice_000.flac").write_bytes(b"x")
    assert paths.resolve_converted_mode_dir("demo", "lrc") == base
    assert paths.resolve_converted_slices_dir("demo") == base


def test_migrate_flat_slices_to_lrc(root: Path) -> None:
    (root / "input" / "demo.lrc").write_text("[00:00.00]line\n", encoding="utf-8")
    base = paths.slices_dir("demo")
    base.mkdir(parents=True)
    manifest = {
        "slice_mode": "lrc",
        "slices": [{"id": "slice_000", "file": "demo_slice_000.flac", "start_ms": 0, "text": "line"}],
    }
    (base / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base / "demo_slice_000.flac").write_bytes(b"x")

    mode = migrate_legacy_slices_layout("demo")
    assert mode == "lrc"
    assert (paths.slices_mode_dir("demo", "lrc") / "manifest.json").is_file()
    assert (paths.slices_mode_dir("demo", "lrc") / "demo_slice_000.flac").is_file()
    assert not (base / "manifest.json").exists()


def test_migrate_flat_converted_slices_subdir(root: Path) -> None:
    base = paths.slices_dir("demo")
    base.mkdir(parents=True)
    (base / "demo_slice_000.flac").write_bytes(b"x")
    legacy_conv = paths.converted_slices_dir("demo")
    legacy_conv.mkdir(parents=True)
    (legacy_conv / "demo_slice_000.flac").write_bytes(b"y")

    mode = migrate_legacy_slices_layout("demo")
    assert mode == "vad"
    assert (paths.converted_mode_dir("demo", "vad") / "demo_slice_000.flac").is_file()


def test_has_per_project_merged_mode_dirs(root: Path) -> None:
    mixed = paths.merged_mixed_path("demo", "lrc")
    mixed.parent.mkdir(parents=True)
    mixed.write_bytes(b"x")
    assert paths.has_per_project_merged("demo")
    assert paths.has_per_project_merged("demo", "lrc")
    assert not paths.has_per_project_merged("demo", "vad")


def test_has_per_project_merged_full_dir(root: Path) -> None:
    mixed = paths.merged_full_mixed_path("demo")
    mixed.parent.mkdir(parents=True)
    mixed.write_bytes(b"x")
    assert paths.has_per_project_merged("demo")
    assert paths.has_per_project_merged("demo", "full")
    assert not paths.has_per_project_merged("demo", "lrc")


def test_resolve_merged_output_dir(root: Path) -> None:
    assert paths.resolve_merged_output_dir("song", "whole_track", "lrc") == root / "output" / "merged" / "song" / "full"
    assert paths.resolve_merged_output_dir("song", "slice_stitch", "vad") == root / "output" / "merged" / "song" / "vad"
