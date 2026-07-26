"""Tests for convert stage mode parameter mapping (Phase 2, TC-Phase2-01)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline import paths
from pipeline.stages.convert import ConvertResult


def _create_project(client: TestClient, sample_audio: Path, project_id: str = "conv") -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


def _write_manifest_and_slices(root: Path, project_id: str, mode: str) -> None:
    mode_dir = root / "output" / "slices" / project_id / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    (mode_dir / "s0.flac").write_bytes(b"fake")
    manifest = mode_dir / "manifest.json"
    manifest.write_text(
        json.dumps({"slices": [{"id": "s0", "file": "s0.flac"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _fake_convert_result(project_id: str, root: Path, mode: str) -> ConvertResult:
    converted_dir = paths.converted_mode_dir(project_id, "lrc")
    converted_dir.mkdir(parents=True, exist_ok=True)
    full_track = None
    if mode == "full_track":
        full_track = converted_dir / "full.flac"
        full_track.write_bytes(b"full")
    return ConvertResult(
        mode=mode,
        converted_dir=converted_dir,
        full_track=full_track,
        converted_count=1,
        total_count=1,
    )


def test_convert_slice_batch_uses_slices_dir(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "conv-batch")
    _write_manifest_and_slices(api_workspace.root, "conv-batch", "lrc")
    ref = api_workspace.root / "input" / "conv-batch" / "reference.wav"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"ref")

    captured: dict = {}

    def _fake_convert(project_id: str, **kwargs):
        captured["project_id"] = project_id
        captured["kwargs"] = kwargs
        return _fake_convert_result("conv-batch", api_workspace.root, "slice_batch")

    with patch("pipeline.runner.run_convert", side_effect=_fake_convert):
        resp = client.post(
            "/api/projects/conv-batch/stages/convert/run",
            json={"params": {"mode": "slice_batch", "slice_mode": "lrc", "active_slice_mode": "lrc"}},
        )
    assert resp.status_code == 200

    assert captured["kwargs"]["mode"] == "slice_batch"


def test_convert_full_track_uses_source_vocals(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "conv-full")
    vocals = api_workspace.root / "input" / "conv-full" / "vocals.flac"
    vocals.parent.mkdir(parents=True, exist_ok=True)
    vocals.write_bytes(b"vocals")
    ref = api_workspace.root / "input" / "conv-full" / "reference.wav"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"ref")

    captured: dict = {}

    def _fake_convert(project_id: str, **kwargs):
        captured["project_id"] = project_id
        captured["kwargs"] = kwargs
        return _fake_convert_result("conv-full", api_workspace.root, "full_track")

    with patch("pipeline.runner.run_convert", side_effect=_fake_convert):
        resp = client.post(
            "/api/projects/conv-full/stages/convert/run",
            json={"params": {"mode": "full_track", "source_vocals": str(vocals), "active_slice_mode": "lrc"}},
        )
    assert resp.status_code == 200

    assert captured["kwargs"]["mode"] == "full_track"
    assert captured["kwargs"]["source_vocals"] == vocals
