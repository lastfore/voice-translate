"""Tests for GET /api/projects/{id}/slices (Phase 1 gap-fill, SliceTable.tsx backing)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _create_project(client: TestClient, sample_audio: Path, project_id: str = "sliced") -> None:
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
    for item in slices:
        (mode_dir / item["file"]).write_bytes(b"fake-audio")
    manifest = mode_dir / "manifest.json"
    manifest.write_text(json.dumps({"slices": slices}, ensure_ascii=False), encoding="utf-8")
    return mode_dir


def test_slices_not_found_project_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/nope/slices", params={"mode": "lrc"})
    assert resp.status_code == 404


def test_slices_empty_project_returns_empty_rows(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "empty")
    resp = client.get("/api/projects/empty/slices", params={"mode": "lrc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "lrc"
    assert body["rows"] == []
    assert body["dir_path"] is None
    assert body["first_audio_url"] is None


def test_slices_returns_manifest_rows_with_audio_urls(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "sliced")
    _write_manifest(
        api_workspace.root,
        "sliced",
        "lrc",
        [
            {"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "hello", "file": "s0.flac"},
            {"id": "s1", "start_ms": 1000, "end_ms": 2000, "text": "world", "file": "s1.flac"},
        ],
    )

    resp = client.get("/api/projects/sliced/slices", params={"mode": "lrc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "lrc"
    assert body["dir_path"] == "output/slices/sliced/lrc"
    assert len(body["rows"]) == 2
    row0 = body["rows"][0]
    assert row0["id"] == "s0"
    assert row0["start_ms"] == 0
    assert row0["text"] == "hello"
    assert row0["audio_url"] == "/api/media?path=output/slices/sliced/lrc/s0.flac"
    assert body["first_audio_url"] == row0["audio_url"]

    # The audio_url must actually be servable via /api/media.
    audio_resp = client.get(row0["audio_url"])
    assert audio_resp.status_code == 200


def test_slices_mode_normalizes_unknown_value_to_lrc(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "modenorm")
    _write_manifest(
        api_workspace.root,
        "modenorm",
        "lrc",
        [{"id": "s0", "start_ms": 0, "end_ms": 500, "text": "", "file": "s0.flac"}],
    )
    resp = client.get("/api/projects/modenorm/slices", params={"mode": "not-a-real-mode"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "lrc"


def test_slice_audio_endpoint_returns_media_url(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "audiolookup")
    _write_manifest(
        api_workspace.root,
        "audiolookup",
        "vad",
        [{"id": "v0", "start_ms": 0, "end_ms": 500, "text": "", "file": "v0.flac"}],
    )
    resp = client.get("/api/projects/audiolookup/slices/v0/audio", params={"mode": "vad"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "/api/media?path=output/slices/audiolookup/vad/v0.flac"


def test_slice_audio_endpoint_missing_slice_is_404(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "audiomissing")
    _write_manifest(
        api_workspace.root,
        "audiomissing",
        "vad",
        [{"id": "v0", "start_ms": 0, "end_ms": 500, "text": "", "file": "v0.flac"}],
    )
    resp = client.get("/api/projects/audiomissing/slices/does-not-exist/audio", params={"mode": "vad"})
    assert resp.status_code == 404
