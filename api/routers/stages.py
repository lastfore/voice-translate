"""Single-stage SSE execution — migrated from webui/state.py run_stage_ui().

Implements the thread/async boundary and cancellation contract mandated by
docs §4.1.2/§4.1.4/§4.4:

- ``runner.run_stage`` (synchronous, blocking) is executed via
  ``anyio.to_thread.run_sync`` so it never runs on the event loop thread.
- Progress callbacks fire on the GPU worker thread; they cross back to the
  event loop via ``loop.call_soon_threadsafe`` + an ``asyncio.Queue``.
- Client disconnect (fetch ``AbortController.abort()``) surfaces as either
  ``request.is_disconnected()`` returning True while we poll, or an
  ``asyncio.CancelledError`` raised into the generator — either path calls
  ``runner.cancel(job_id)`` (itself dispatched to a worker thread, since it
  can block briefly on ``subprocess.terminate()``/``wait()``).

``stream_stage_events`` is a module-level function (not a route-local closure)
specifically so tests can drive it directly and assert the cancellation path
fires without depending on ASGI-transport-level disconnect timing, which is
transport/OS dependent and awkward to simulate deterministically in tests
(see tests/api/test_cancellation.py for the full rationale).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.deps import get_runner, get_store
from api.schemas.stage import StageRunRequest
from pipeline.models import ProgressEvent, StageName
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/projects", tags=["stages"])

_POLL_TIMEOUT_S = 0.1


def sse_frame(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_stage_events(
    runner: StageRunner,
    project_id: str,
    stage: StageName,
    params: dict[str, Any],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Drive ``runner.run_stage`` off the event loop and yield SSE frames.

    ``is_disconnected`` is injected (rather than reading ``request`` directly)
    so unit tests can supply a stub without spinning up a full ASGI request.
    """
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
    job_holder: dict[str, str] = {}

    def on_progress(event: ProgressEvent) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, event)

    def on_job_id(job_id: str) -> None:
        job_holder["job_id"] = job_id

    task = asyncio.create_task(
        anyio.to_thread.run_sync(runner.run_stage, project_id, stage, params, on_progress, on_job_id)
    )

    async def _cancel_running_job() -> None:
        job_id = job_holder.get("job_id")
        if job_id:
            await anyio.to_thread.run_sync(runner.cancel, job_id)

    async def _cancel_and_reap() -> None:
        """Cancel the running job and wait for ``task`` to actually finish.

        ``task`` wraps a blocking call on a worker thread (``anyio.to_thread``);
        cancelling/abandoning the *asyncio* task does not stop that thread — the
        real subprocess kill (via ``_cancel_running_job``) is what makes
        ``runner.run_stage`` return. We must still await ``task`` here rather
        than abandon it: leaving it orphaned means it keeps running against a
        ``ProjectStore``/env state that may no longer be current by the time it
        finally writes its result (observed in tests as a stale worker thread
        racing a *later* request's project files), and it becomes an unbounded,
        untracked background thread outside the request's lifetime.
        """
        await _cancel_running_job()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except BaseException:  # noqa: BLE001 - best-effort reap, never mask the original cancellation
            pass

    try:
        while not task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=_POLL_TIMEOUT_S)
                yield sse_frame("log", event.to_ui_dict())
            except asyncio.TimeoutError:
                if await is_disconnected():
                    await _cancel_and_reap()
                    return
                continue

        while not progress_queue.empty():
            yield sse_frame("log", progress_queue.get_nowait().to_ui_dict())

        result = await task
        yield sse_frame(
            "done",
            {"success": result.success, "error": result.error, "artifacts": result.artifacts},
        )
    except asyncio.CancelledError:
        await _cancel_and_reap()
        raise
    except Exception as exc:  # noqa: BLE001 - surface as SSE error frame, not a 500
        yield sse_frame("error", {"message": str(exc)})


@router.post("/{project_id}/stages/{stage}/run")
async def run_stage(
    project_id: str,
    stage: str,
    body: StageRunRequest,
    request: Request,
    runner: StageRunner = Depends(get_runner),
    store: ProjectStore = Depends(get_store),
) -> StreamingResponse:
    try:
        stage_enum = StageName(stage)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"unknown stage: {stage}") from exc

    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc

    params = dict(body.params)
    generator = stream_stage_events(
        runner, project_id, stage_enum, params, is_disconnected=request.is_disconnected
    )
    return StreamingResponse(generator, media_type="text/event-stream")
