"""Tests for reference audio upload endpoint (Phase 2, TC-Phase2-06)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _create_project(client: TestClient, sample_audio: Path, project_id: str = "ref-test") -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


def test_upload_reference_audio(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "ref-upload")
    ref = api_workspace.root / "reference.wav"
    ref.write_bytes(b"fake-ref-audio")

    with ref.open("rb") as fh:
        resp = client.post(
            "/api/projects/ref-upload/reference",
            files={"audio": ("reference.wav", fh, "audio/wav")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reference"].startswith("input/ref-upload/reference")
    assert body["reference"].endswith(".wav")
