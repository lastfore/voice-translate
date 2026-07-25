"""Tests for slice preview helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import paths
from webui.helpers import (
    audio_for_slice,
    load_manifest_entries,
    load_slice_table,
    resolve_manifest_path,
)


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "output" / "slices").mkdir(parents=True)
    return tmp_path


def test_resolve_manifest_path_new_layout(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "foo" / "lrc"
    mode_dir.mkdir(parents=True)
    manifest = mode_dir / "manifest.json"
    manifest.write_text('{"slices": []}', encoding="utf-8")

    assert resolve_manifest_path("foo", "lrc") == manifest
    assert resolve_manifest_path("foo", "vad") is None


def test_resolve_manifest_path_legacy_vad(root: Path) -> None:
    base = root / "output" / "slices" / "legacy"
    base.mkdir(parents=True)
    manifest = base / "manifest.json"
    manifest.write_text('{"slice_mode": "vad", "slices": []}', encoding="utf-8")

    assert resolve_manifest_path("legacy", "vad") == manifest
    assert resolve_manifest_path("legacy", "lrc") is None


def test_load_slice_table_rows(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "demo" / "lrc"
    mode_dir.mkdir(parents=True)
    (mode_dir / "slice_000.flac").write_bytes(b"x")
    manifest = {
        "slices": [
            {
                "id": "slice_000",
                "file": "slice_000.flac",
                "start_ms": 0,
                "end_ms": 1200,
                "text": "hello",
            }
        ]
    }
    (mode_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    rows, audio, dir_label = load_slice_table("demo", "lrc")
    assert len(rows) == 1
    assert rows[0][0] == "slice_000"
    assert rows[0][3] == "hello"
    assert audio is not None
    assert "slices" in dir_label


def test_audio_for_slice_missing_file(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "demo" / "lrc"
    mode_dir.mkdir(parents=True)
    manifest = {"slices": [{"id": "slice_000", "file": "missing.flac", "start_ms": 0, "end_ms": 1}]}
    (mode_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert audio_for_slice("demo", "lrc", "slice_000") is None


def test_load_manifest_entries_empty_project() -> None:
    assert load_manifest_entries(None, "lrc") == []


def test_tune_status_column(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "demo" / "lrc"
    mode_dir.mkdir(parents=True)
    (mode_dir / "slice_000.flac").write_bytes(b"x")
    manifest = {"slices": [{"id": "slice_000", "file": "slice_000.flac", "start_ms": 0, "end_ms": 1}]}
    (mode_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    overrides = {
        "version": 1,
        "global_defaults": {},
        "slices": {"slice_000": {"semi_tone_shift": 1}},
        "orphans": [],
    }
    (mode_dir / "overrides.json").write_text(json.dumps(overrides), encoding="utf-8")

    rows, _, _ = load_slice_table("demo", "lrc")
    assert rows[0][-1] == "精修"
