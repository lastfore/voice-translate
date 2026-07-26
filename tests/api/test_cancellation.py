"""TC-Phase0-05 (docs §4.1.4): task cancellation must terminate the running
subprocess and flip the job status to CANCELLED.

Phase 0 has no frontend yet, so the doc's originally-Playwright-tagged
TC-Phase0-05 is replaced with a pytest suite at three levels, from the
kernel up to the route:

1. ``GpuJobQueue.cancel_current()`` + ``pipeline.venv_runner`` process
   registry — proves a *real* subprocess gets terminate()/kill()ed and the
   queue reports CANCELLED (not FAILED) once the work function unwinds.
2. ``StageRunner.cancel(job_id)`` — the same, one layer up, through the
   runner's public cancellation API.
3. ``api.routers.stages.stream_stage_events`` — the actual SSE generator used
   by the route: cancelling the asyncio task driving it must trigger
   ``runner.cancel(job_id)`` and terminate the subprocess, exactly like an
   aborted ``fetch()`` should.

Note on what is *not* covered here: a genuine end-to-end "browser tab
closed" disconnect depends on OS/ASGI-transport-level socket teardown
timing. A manual investigation (see docs/phase-test-checklist.md Phase 0
notes) found that Starlette's ``Request.is_disconnected()`` only reports
True once uvicorn's protocol has already flagged the connection lost in its
receive-message queue; simulating that deterministically inside pytest
(without a real browser / real TCP client) proved unreliable in this
environment within a reasonable timeout budget, and is deferred to a
Playwright-based E2E test once the Phase 1 frontend exists. The
``is_disconnected()`` polling branch itself is still real production code —
it is exercised by test #3 below by injecting a stub that flips to True,
independent of real transport timing.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from api.routers.stages import stream_stage_events
from pipeline import venv_runner
from pipeline.models import Job, JobStatus, StageName
from pipeline.queue import GpuJobQueue
from pipeline.stages.separate import SeparateResult

_SLEEP_30S = [sys.executable, "-c", "import time; time.sleep(30)"]


def _real_subprocess_work():
    """Work function that blocks on a real, killable subprocess."""
    for _ in venv_runner.iter_subprocess_lines(_SLEEP_30S):
        pass
    return "should not reach here if cancelled"


def test_cancel_current_terminates_real_subprocess_and_marks_cancelled() -> None:
    q = GpuJobQueue()
    job = Job("cancel-1", "stage", None, JobStatus.QUEUED, "2026-01-01T00:00:00+08:00")
    q.enqueue(job, _real_subprocess_work)

    deadline = time.time() + 5
    while time.time() < deadline and q.current_job() is None:
        time.sleep(0.02)
    assert q.current_job() is not None, "job never reached RUNNING"

    t0 = time.time()
    assert q.cancel_current() is True

    result = q.wait("cancel-1", timeout=10.0)
    elapsed = time.time() - t0

    assert result.status == JobStatus.CANCELLED
    assert elapsed < 5.0, "real subprocess should be terminated near-instantly, not run the full 30s sleep"
    q.shutdown()


def test_cancel_current_on_idle_queue_is_noop() -> None:
    q = GpuJobQueue()
    assert q.cancel_current() is False
    q.shutdown()


def test_stage_runner_cancel_marks_stage_result_failed_with_cancelled_error(
    runner_workspace_with_real_subprocess,
) -> None:
    store, runner, pid, mix = runner_workspace_with_real_subprocess
    job_ids: list[str] = []

    result_holder: dict[str, object] = {}

    def _run():
        with patch(
            "pipeline.runner.run_separate",
            side_effect=lambda *a, **k: _fake_separate_real_subprocess(*a, **k),
        ):
            result_holder["result"] = runner.run_stage(
                pid, StageName.SEPARATE, {"mix_audio": str(mix)}, on_job_id=job_ids.append
            )

    import threading

    th = threading.Thread(target=_run)
    th.start()

    deadline = time.time() + 5
    while time.time() < deadline and not job_ids:
        time.sleep(0.02)
    assert job_ids, "job id was never reported"
    time.sleep(0.1)  # let the fake stage enter the subprocess loop

    t0 = time.time()
    assert runner.cancel(job_ids[0]) is True
    th.join(timeout=10)
    elapsed = time.time() - t0

    assert not th.is_alive()
    assert elapsed < 5.0
    result = result_holder["result"]
    assert result.success is False
    assert "cancel" in (result.error or "").lower()


def _fake_separate_real_subprocess(project_id, mix_audio, *, model, on_progress=None, on_log_line=None):
    for _ in venv_runner.iter_subprocess_lines(_SLEEP_30S):
        pass
    return SeparateResult(vocals=Path("v"), instrumental=Path("i"))


@pytest.fixture
def runner_workspace_with_real_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.runner import StageRunner
    from pipeline.store import ProjectStore

    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir()
    (tmp_path / "output" / "separated").mkdir(parents=True)
    mix = tmp_path / "input" / "song.flac"
    mix.write_bytes(b"audio")

    store = ProjectStore(tmp_path)
    store.create_project("song", mix)
    q = GpuJobQueue()
    runner = StageRunner(store, q)
    try:
        yield store, runner, "song", mix
    finally:
        q.shutdown()


class _StubRequestDisconnected:
    """Stub for the ``is_disconnected`` dependency injected into stream_stage_events."""

    def __init__(self) -> None:
        self.disconnected = False

    async def __call__(self) -> bool:
        return self.disconnected


@pytest.mark.asyncio
async def test_stream_stage_events_cancels_running_job_on_task_cancel(
    runner_workspace_with_real_subprocess,
) -> None:
    """Directly drives the production SSE generator (not the HTTP layer) and
    cancels the asyncio task consuming it — this is exactly what happens when
    Starlette's StreamingResponse body-iteration task is cancelled following
    a real client disconnect, without depending on socket-level timing."""
    store, runner, pid, mix = runner_workspace_with_real_subprocess
    is_disconnected = _StubRequestDisconnected()

    async def _drain() -> list[str]:
        frames = []
        with patch("pipeline.runner.run_separate", side_effect=_fake_separate_real_subprocess):
            async for frame in stream_stage_events(
                runner, pid, StageName.SEPARATE, {"mix_audio": str(mix)}, is_disconnected=is_disconnected
            ):
                frames.append(frame)
        return frames

    task = asyncio.create_task(_drain())

    deadline = time.time() + 5
    while time.time() < deadline and runner.queue.current_job() is None:
        await asyncio.sleep(0.02)
    assert runner.queue.current_job() is not None, "stage job never started running"

    job_id = runner.queue.current_job().job_id
    t0 = time.time()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # Give the queue worker a moment to unwind the killed subprocess and
    # report the final status.
    deadline = time.time() + 5
    status = runner.queue.get_status(job_id)
    while time.time() < deadline and status == JobStatus.RUNNING:
        await asyncio.sleep(0.05)
        status = runner.queue.get_status(job_id)
    elapsed = time.time() - t0

    assert status == JobStatus.CANCELLED
    assert elapsed < 5.0, "cancellation should terminate the real subprocess near-instantly"


@pytest.mark.asyncio
async def test_stream_stage_events_cancels_on_is_disconnected_true(
    runner_workspace_with_real_subprocess,
) -> None:
    """Exercises the polling branch (``await is_disconnected()``) directly,
    independent of real ASGI-transport socket-close timing."""
    store, runner, pid, mix = runner_workspace_with_real_subprocess
    is_disconnected = _StubRequestDisconnected()

    frames: list[str] = []

    async def _drain() -> None:
        with patch("pipeline.runner.run_separate", side_effect=_fake_separate_real_subprocess):
            async for frame in stream_stage_events(
                runner, pid, StageName.SEPARATE, {"mix_audio": str(mix)}, is_disconnected=is_disconnected
            ):
                frames.append(frame)

    task = asyncio.create_task(_drain())

    deadline = time.time() + 5
    while time.time() < deadline and runner.queue.current_job() is None:
        await asyncio.sleep(0.02)
    assert runner.queue.current_job() is not None, "stage job never started running"
    job_id = runner.queue.current_job().job_id

    is_disconnected.disconnected = True

    deadline = time.time() + 5
    status = runner.queue.get_status(job_id)
    while time.time() < deadline and status == JobStatus.RUNNING:
        await asyncio.sleep(0.05)
        status = runner.queue.get_status(job_id)

    await asyncio.wait_for(task, timeout=5.0)

    assert status == JobStatus.CANCELLED
