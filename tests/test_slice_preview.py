"""Tests for slice preview helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import media_service, slice_service
from pipeline import paths


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "output" / "slices").mkdir(parents=True)
    return tmp_path


def _manifest_path(project_id: str, slice_mode: str) -> Path | None:
    mode_dir = paths.resolve_slices_mode_dir(project_id, slice_mode)
    if mode_dir is None:
        return None
    manifest = mode_dir / "manifest.json"
    return manifest if manifest.is_file() else None


def test_resolve_manifest_path_new_layout(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "foo" / "lrc"
    mode_dir.mkdir(parents=True)
    manifest = mode_dir / "manifest.json"
    manifest.write_text('{"slices": []}', encoding="utf-8")

    assert _manifest_path("foo", "lrc") == manifest
    assert _manifest_path("foo", "vad") is None


def test_resolve_manifest_path_legacy_vad(root: Path) -> None:
    base = root / "output" / "slices" / "legacy"
    base.mkdir(parents=True)
    manifest = base / "manifest.json"
    manifest.write_text('{"slice_mode": "vad", "slices": []}', encoding="utf-8")

    assert _manifest_path("legacy", "vad") == manifest
    assert _manifest_path("legacy", "lrc") is None


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

    table = slice_service.load_slice_table("demo", "lrc")
    assert len(table["rows"]) == 1
    assert table["rows"][0]["id"] == "slice_000"
    assert table["rows"][0]["text"] == "hello"
    assert table["first_audio_url"] is not None
    assert table["dir_path"] is not None
    assert "slices" in table["dir_path"]


def test_audio_for_slice_missing_file(root: Path) -> None:
    mode_dir = root / "output" / "slices" / "demo" / "lrc"
    mode_dir.mkdir(parents=True)
    manifest = {"slices": [{"id": "slice_000", "file": "missing.flac", "start_ms": 0, "end_ms": 1}]}
    (mode_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert slice_service.slice_audio_url("demo", "lrc", "slice_000") is None


def test_resolve_convert_preview_slice_batch(root: Path) -> None:
    mode_dir = root / "output" / "converted" / "demo" / "lrc"
    mode_dir.mkdir(parents=True)
    (mode_dir / "demo_slice_000.flac").write_bytes(b"x")

    url = media_service.resolve_convert_preview_audio("demo", "slice_batch", "lrc")
    assert url is not None
    assert "demo_slice_000.flac" in url


def test_resolve_convert_preview_full_track(root: Path) -> None:
    full_dir = root / "output" / "converted" / "demo" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "full.flac").write_bytes(b"x")

    url = media_service.resolve_convert_preview_audio("demo", "full_track", "lrc")
    assert url is not None
    assert "full.flac" in url


def test_load_manifest_entries_empty_project() -> None:
    assert slice_service.load_manifest_entries("", "lrc") == []


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

    table = slice_service.load_slice_table("demo", "lrc")
    assert table["rows"][0]["status"] == "tuned"
