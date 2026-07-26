"""Batch queue endpoints — migrated from webui/components/batch_queue.py.

- GET /api/batch/status  SSE  (persistent subscription)
- POST /api/batch/enqueue
- POST /api/batch/run     SSE  (triggers execution)
- POST /api/batch/clear
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.deps import get_batch_service, get_runner, get_store
from api.services.batch_service import BatchService
from pipeline.models import StageName
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/batch", tags=["batch"])

_SSE_POLL_TIMEOUT_S = 0.1


def sse_frame(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_batch_status(
    service: BatchService,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    service.subscribe(queue)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=_SSE_POLL_TIMEOUT_S)
                yield sse_frame("status", payload)
            except asyncio.TimeoutError:
                if await is_disconnected():
                    return
                continue
    finally:
        service.unsubscribe(queue)


@router.get("/status")
async def batch_status(
    request: Request,
    service: BatchService = Depends(get_batch_service),
) -> StreamingResponse:
    generator = _stream_batch_status(service, is_disconnected=request.is_disconnected)
    return StreamingResponse(generator, media_type="text/event-stream")


@router.post("/enqueue")
def enqueue_batch(
    body: dict[str, Any],
    service: BatchService = Depends(get_batch_service),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    project_id = body.get("project_id", "")
    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc

    stages = body.get("stages", [])
    valid_stages = [s for s in stages if s in StageName._value2member_map_]
    if not valid_stages:
        raise HTTPException(status_code=400, detail="stages must be a non-empty list of valid stage names")

    item = service.enqueue(
        project_id=project_id,
        stages=valid_stages,
        params=body.get("params", {}),
    )
    return item.to_dict()


@router.post("/clear")
def clear_batch(
    body: dict[str, Any] | None = None,
    service: BatchService = Depends(get_batch_service),
) -> dict[str, Any]:
    payload = body or {}
    removed = service.clear(
        remove_done=payload.get("remove_done", True),
        remove_failed=payload.get("remove_failed", True),
        remove_pending=payload.get("remove_pending", False),
    )
    return {"removed": removed}


@router.post("/run")
async def run_batch(
    request: Request,
    service: BatchService = Depends(get_batch_service),
    runner: StageRunner = Depends(get_runner),
    store: ProjectStore = Depends(get_store),
) -> StreamingResponse:
    # Ensure runner/store are the same singletons the service uses (the Depends
    # graph in api/deps.py wires them together).
    _ = runner, store

    try:
        progress_queue = service.run()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def gen() -> AsyncIterator[str]:
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(progress_queue.get(), timeout=_SSE_POLL_TIMEOUT_S)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    continue
                if payload.get("type") == "done":
                    yield sse_frame("done", {"success": True})
                    return
                if payload.get("type") == "log":
                    yield sse_frame("log", payload.get("event", {}))
        finally:
            # Drain the queue so the worker thread can exit cleanly if it is
            # still pushing progress events after the client disconnects.
            while not progress_queue.empty():
                try:
                    progress_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    return StreamingResponse(gen(), media_type="text/event-stream")
