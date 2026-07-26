"""Tests for artifact preview endpoints (Phase 2, migration doc §5.9)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _create_project(client: TestClient, sample_audio: Path, project_id: str = "art") -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


def _write_manifest(root: Path, project_id: str, mode: str, slices: list[dict]) -> Path:
    mode_dir = root / "output" / "slices" / project_id / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    manifest = mode_dir / "manifest.json"
    manifest.write_text(json.dumps({"slices": slices}, ensure_ascii=False), encoding="utf-8")
    return mode_dir


def test_manifest_preview_returns_slice_list(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "manifest-preview")
    _write_manifest(
        api_workspace.root,
        "manifest-preview",
        "lrc",
        [
            {"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "hello", "file": "s0.flac"},
            {"id": "s1", "start_ms": 1000, "end_ms": 2000, "text": "world", "file": "s1.flac"},
        ],
    )

    resp = client.get("/api/projects/manifest-preview/manifest-preview", params={"mode": "lrc"})
    assert resp.status_code == 200
    preview = resp.json()["preview"]
    assert "s0" in preview
    assert "s1" in preview
    assert "id | file | start_ms | end_ms" in preview


def test_convert_preview_full_track(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "convert-full")
    full_dir = api_workspace.root / "output" / "converted" / "convert-full" / "full"
    full_dir.mkdir(parents=True, exist_ok=True)
    (full_dir / "full.flac").write_bytes(b"fake")

    resp = client.get("/api/projects/convert-full/artifacts/convert-preview", params={"mode": "full_track"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "/api/media?path=output/converted/convert-full/full/full.flac"


def test_convert_preview_slice_batch(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "convert-batch")
    mode_dir = api_workspace.root / "output" / "converted" / "convert-batch" / "lrc"
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "s0.flac").write_bytes(b"fake")

    resp = client.get(
        "/api/projects/convert-batch/artifacts/convert-preview", params={"mode": "slice_batch", "slice_mode": "lrc"}
    )
    assert resp.status_code == 200
    assert resp.json()["url"] == "/api/media?path=output/converted/convert-batch/lrc/s0.flac"
