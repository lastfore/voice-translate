"""Tests for wizard / full-pipeline SSE endpoint (TC-P0-08)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from pipeline.models import PipelineResult, ProgressEvent, StageName, StageResult


def _create_project(client: TestClient, sample_audio: Path, project_id: str) -> None:
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_pipeline_run_sse_streams_all_stages(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "pipeline-sse")

    def _fake_run_pipeline(project_id, *, stages, on_progress=None, **kwargs):
        for stage in stages or list(StageName):
            if on_progress:
                on_progress(
                    ProgressEvent(
                        project_id=project_id,
                        stage=stage,
                        job_id="fake",
                        percent=100.0,
                        message=f"{stage.value} done",
                        log_line=f"{stage.value} done",
                    )
                )
        return PipelineResult(
            project_id=project_id,
            success=True,
            stage_results=[StageResult(project_id, stage, True) for stage in (stages or list(StageName))],
        )

    with patch.object(api_workspace.runner, "run_pipeline", side_effect=_fake_run_pipeline):
        transport = httpx.ASGITransport(app=api_workspace.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/api/projects/pipeline-sse/pipeline/run",
                json={"params": {}},
            ) as response:
                assert response.status_code == 200
                body = ""
                async for chunk in response.aiter_text():
                    body += chunk
                    if "event: done" in body:
                        break

    for stage in ("separate", "slice", "convert", "merge"):
        assert f"{stage} done" in body, f"missing log for {stage}"
    assert "event: done" in body


def test_pipeline_run_from_stage(api_workspace, sample_audio: Path) -> None:
    client = TestClient(api_workspace.app)
    _create_project(client, sample_audio, "pipeline-from")

    def _fake_run_pipeline(project_id, *, stages, on_progress=None, **kwargs):
        for stage in stages or []:
            if on_progress:
                on_progress(
                    ProgressEvent(
                        project_id=project_id,
                        stage=stage,
                        job_id="fake",
                        percent=100.0,
                        message=f"{stage.value} done",
                        log_line=f"{stage.value} done",
                    )
                )
        return PipelineResult(
            project_id=project_id,
            success=True,
            stage_results=[StageResult(project_id, stage, True) for stage in (stages or [])],
        )

    with patch.object(api_workspace.runner, "run_pipeline", side_effect=_fake_run_pipeline):
        resp = client.post("/api/projects/pipeline-from/pipeline/run", json={"from_stage": "convert", "params": {}})
        assert resp.status_code == 200
        body = resp.read().decode()

    assert "convert done" in body
    assert "merge done" in body
    assert "separate done" not in body
