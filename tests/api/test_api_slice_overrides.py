"""Tests for slice overrides lifecycle (Phase 2, migration doc §5.5 / TC-Phase2-02)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _create_project(client: TestClient, sample_audio: Path, project_id: str = "tuned") -> None:
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


def test_overrides_not_found_project_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.get("/api/projects/nope/slices/overrides", params={"mode": "lrc"})
    assert resp.status_code == 404


def test_overrides_empty_returns_defaults(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "tuned-empty")
    resp = client.get("/api/projects/tuned-empty/slices/overrides", params={"mode": "lrc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["slice_mode"] == "lrc"
    assert "global_defaults" in body
    assert body["slices"] == {}
    assert body["orphans"] == []


def test_overrides_save_and_read_back(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "tuned-save")
    _write_manifest(
        api_workspace.root,
        "tuned-save",
        "lrc",
        [{"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "hello", "file": "s0.flac"}],
    )

    resp = client.put(
        "/api/projects/tuned-save/slices/overrides",
        params={"mode": "lrc"},
        json={"slice_ids": ["s0"], "params": {"diffusion_steps": 10, "fp16": False}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["slices"]["s0"]["diffusion_steps"] == 10
    assert body["slices"]["s0"]["fp16"] is False

    resp = client.get("/api/projects/tuned-save/slices/overrides", params={"mode": "lrc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["slices"]["s0"]["diffusion_steps"] == 10


def test_overrides_delete_selected(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "tuned-delete")
    _write_manifest(
        api_workspace.root,
        "tuned-delete",
        "lrc",
        [
            {"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "a", "file": "s0.flac"},
            {"id": "s1", "start_ms": 1000, "end_ms": 2000, "text": "b", "file": "s1.flac"},
        ],
    )

    client.put(
        "/api/projects/tuned-delete/slices/overrides",
        params={"mode": "lrc"},
        json={"slice_ids": ["s0", "s1"], "params": {"diffusion_steps": 20}},
    )

    resp = client.request(
        "DELETE",
        "/api/projects/tuned-delete/slices/overrides",
        params={"mode": "lrc"},
        content=json.dumps(["s0"]),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "s0" not in body["slices"]
    assert "s1" in body["slices"]


def test_overrides_clear_all(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "tuned-clear")
    _write_manifest(
        api_workspace.root,
        "tuned-clear",
        "lrc",
        [{"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "a", "file": "s0.flac"}],
    )

    client.put(
        "/api/projects/tuned-clear/slices/overrides",
        params={"mode": "lrc"},
        json={"slice_ids": ["s0"], "params": {"diffusion_steps": 30}},
    )

    resp = client.delete("/api/projects/tuned-clear/slices/overrides", params={"mode": "lrc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["slices"] == {}


def test_overrides_clear_orphans(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "tuned-orphan")
    _write_manifest(
        api_workspace.root,
        "tuned-orphan",
        "lrc",
        [{"id": "s0", "start_ms": 0, "end_ms": 1000, "text": "a", "file": "s0.flac"}],
    )

    client.put(
        "/api/projects/tuned-orphan/slices/overrides",
        params={"mode": "lrc"},
        json={"slice_ids": ["s0"], "params": {"diffusion_steps": 40}},
    )

    # Remove the slice from the manifest so the saved override becomes an orphan.
    _write_manifest(api_workspace.root, "tuned-orphan", "lrc", [])

    resp = client.post(
        "/api/projects/tuned-orphan/slices/overrides/clear-orphans", params={"mode": "lrc"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["orphans"] == []
