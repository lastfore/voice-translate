"""Tests for batch queue API (Phase 3, TC-P0-11 / TC-Phase3-*)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from pipeline.models import JobStatus, ProgressEvent, StageName
from pipeline.stages.separate import SeparateResult


def _create_project(client: TestClient, sample_audio: Path, project_id: str) -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


def _fake_separate(delay: float = 0.1):
    def _fn(project_id, mix_audio, *, model, on_progress=None, on_log_line=None):
        time.sleep(delay)
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.SEPARATE,
                    job_id="fake",
                    percent=100.0,
                    message="done",
                    log_line="done",
                )
            )
        vocals = mix_audio.parent / "fake_vocals.flac"
        instrumental = mix_audio.parent / "fake_instrumental.flac"
        vocals.write_bytes(b"v")
        instrumental.write_bytes(b"i")
        return SeparateResult(vocals=vocals, instrumental=instrumental)

    return _fn


def test_enqueue_returns_item(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "batch-enq")
    resp = client.post(
        "/api/batch/enqueue",
        json={"project_id": "batch-enq", "stages": ["separate"], "params": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == "batch-enq"
    assert body["stages"] == ["separate"]
    assert body["status"] == "pending"


def test_enqueue_unknown_project_is_404(api_workspace) -> None:
    client = TestClient(api_workspace.app)
    resp = client.post(
        "/api/batch/enqueue",
        json={"project_id": "nope", "stages": ["separate"], "params": {}},
    )
    assert resp.status_code == 404


def test_enqueue_invalid_stages_is_400(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "batch-bad-stages")
    resp = client.post(
        "/api/batch/enqueue",
        json={"project_id": "batch-bad-stages", "stages": ["not_a_stage"], "params": {}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_batch_run_sse_streams_logs_and_done(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "batch-sse")
    client.post(
        "/api/batch/enqueue",
        json={"project_id": "batch-sse", "stages": ["separate"], "params": {}},
    )

    with patch("pipeline.runner.run_separate", side_effect=_fake_separate(0.01)):
        transport = httpx.ASGITransport(app=api_workspace.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream("POST", "/api/batch/run") as response:
                assert response.status_code == 200
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                    if "event: done" in body:
                        break

    assert "event: log" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_batch_run_is_serial(api_workspace, sample_audio: Path) -> None:
    """TC-P0-11: only one batch item executes at a time."""
    client = TestClient(api_workspace.app)
    for i in range(2):
        _create_project(client, sample_audio, f"batch-serial-{i}")
        client.post(
            "/api/batch/enqueue",
            json={"project_id": f"batch-serial-{i}", "stages": ["separate"], "params": {}},
        )

    call_count = {"active": 0, "max": 0}

    def _fake_separate_tracking(project_id, mix_audio, *, model, on_progress=None, on_log_line=None):
        call_count["active"] += 1
        call_count["max"] = max(call_count["max"], call_count["active"])
        time.sleep(0.05)
        call_count["active"] -= 1
        if on_progress:
            on_progress(
                ProgressEvent(
                    project_id=project_id,
                    stage=StageName.SEPARATE,
                    job_id="fake",
                    percent=100.0,
                    message="done",
                    log_line="done",
                )
            )
        vocals = mix_audio.parent / "fake_vocals.flac"
        instrumental = mix_audio.parent / "fake_instrumental.flac"
        vocals.write_bytes(b"v")
        instrumental.write_bytes(b"i")
        return SeparateResult(vocals=vocals, instrumental=instrumental)

    with patch("pipeline.runner.run_separate", side_effect=_fake_separate_tracking):
        transport = httpx.ASGITransport(app=api_workspace.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream("POST", "/api/batch/run") as response:
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                    if "event: done" in body:
                        break

    assert call_count["max"] == 1


def test_clear_removes_completed_items(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "batch-clear")
    resp = client.post(
        "/api/batch/enqueue",
        json={"project_id": "batch-clear", "stages": ["separate"], "params": {}},
    )
    item_id = resp.json()["id"]

    with patch("pipeline.runner.run_separate", side_effect=_fake_separate(0.01)):
        client.post("/api/batch/run").read()

    resp = client.post("/api/batch/clear", json={"remove_done": True, "remove_failed": True})
    assert resp.status_code == 200
    assert resp.json()["removed"] == 1

    snapshot = api_workspace.batch_service.snapshot()
    assert all(item["id"] != item_id for item in snapshot["items"])
