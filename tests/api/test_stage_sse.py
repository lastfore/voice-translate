"""TC-P0-07 (single-stage SSE continuous push) + TC-Phase0-04 / TC-P0-10
(run_stage must not block the event loop under a long-running task).

Real separation needs a GPU model, so the underlying stage function
(``pipeline.runner.run_separate``) is mocked with a controllable-delay fake
that still exercises the full thread/async boundary (docs §4.4): it runs
inside ``anyio.to_thread.run_sync`` on a worker thread, and reports progress
through the same ``on_progress`` -> ``asyncio.Queue`` -> SSE frame path a real
stage would use.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from pipeline.models import ProgressEvent, StageName
from pipeline.stages.separate import SeparateResult


def _slow_fake_separate(total_delay: float, steps: int = 3):
    def _fn(project_id, mix_audio, *, model, on_progress=None, on_log_line=None, stage_log=None, **kwargs):
        for i in range(steps):
            time.sleep(total_delay / steps)
            if on_progress:
                on_progress(
                    ProgressEvent(
                        project_id=project_id,
                        stage=StageName.SEPARATE,
                        job_id="fake-job",
                        percent=(i + 1) * (100.0 / steps),
                        message=f"step {i + 1}/{steps}",
                        log_line=f"log line {i + 1}",
                    )
                )
        vocals = mix_audio.parent / "fake_vocals.flac"
        instrumental = mix_audio.parent / "fake_instrumental.flac"
        vocals.write_bytes(b"v")
        instrumental.write_bytes(b"i")
        return SeparateResult(vocals=vocals, instrumental=instrumental)

    return _fn


def _create_project(api_workspace, sample_audio: Path, project_id: str) -> None:
    client = TestClient(api_workspace.app)
    with sample_audio.open("rb") as fh:
        resp = client.post(
            "/api/projects",
            data={"project_id": project_id},
            files={"audio": ("sample.flac", fh, "audio/flac")},
        )
    assert resp.status_code == 201, resp.text


async def _collect_sse_frames(app, project_id: str, stage: str = "separate") -> list[str]:
    frames: list[str] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        async with ac.stream(
            "POST", f"/api/projects/{project_id}/stages/{stage}/run", json={"params": {}}
        ) as response:
            assert response.status_code == 200
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    frames.append(frame)
    return frames


@pytest.mark.asyncio
async def test_stage_run_sse_streams_progress_then_done(api_workspace, sample_audio: Path) -> None:
    _create_project(api_workspace, sample_audio, "sse-happy")

    with patch("pipeline.runner.run_separate", side_effect=_slow_fake_separate(0.3, steps=3)):
        frames = await _collect_sse_frames(api_workspace.app, "sse-happy")

    log_frames = [f for f in frames if f.startswith("event: log")]
    done_frames = [f for f in frames if f.startswith("event: done")]
    assert len(log_frames) >= 3, f"expected multiple progress frames, got: {frames}"
    assert len(done_frames) == 1
    assert '"success": true' in done_frames[0] or '"success":true' in done_frames[0]


@pytest.mark.asyncio
async def test_stage_run_sse_unknown_stage_is_404(api_workspace, sample_audio: Path) -> None:
    _create_project(api_workspace, sample_audio, "sse-badstage")
    transport = httpx.ASGITransport(app=api_workspace.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/projects/sse-badstage/stages/not-a-stage/run", json={"params": {}}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stage_run_sse_unknown_project_is_404(api_workspace) -> None:
    transport = httpx.ASGITransport(app=api_workspace.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/projects/does-not-exist/stages/separate/run", json={"params": {}}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_stage_does_not_block_event_loop(api_workspace, sample_audio: Path) -> None:
    """While a (mocked) long stage runs, health/list requests must keep responding quickly."""
    _create_project(api_workspace, sample_audio, "sse-nonblocking")

    with patch("pipeline.runner.run_separate", side_effect=_slow_fake_separate(1.2, steps=6)):
        transport = httpx.ASGITransport(app=api_workspace.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:

            async def _drive_stage() -> None:
                async with ac.stream(
                    "POST",
                    "/api/projects/sse-nonblocking/stages/separate/run",
                    json={"params": {}},
                ) as resp:
                    async for _ in resp.aiter_text():
                        pass

            async def _probe_other_endpoints() -> list[float]:
                timings: list[float] = []
                for _ in range(8):
                    t0 = time.monotonic()
                    health_resp = await ac.get("/api/health")
                    projects_resp = await ac.get("/api/projects")
                    timings.append(time.monotonic() - t0)
                    assert health_resp.status_code == 200
                    assert projects_resp.status_code == 200
                    await asyncio.sleep(0.05)
                return timings

            stage_task = asyncio.create_task(_drive_stage())
            timings = await _probe_other_endpoints()
            await stage_task

    assert max(timings) < 0.5, (
        f"health/list requests should stay responsive while a stage runs, got timings={timings}"
    )
