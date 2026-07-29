"""Wizard / full-pipeline execution endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.deps import get_runner, get_store
from pipeline.models import ConvertMode, ProgressEvent, SliceMode, StageName
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/projects", tags=["pipeline"])

_SSE_POLL_TIMEOUT_S = 0.1


def sse_frame(event_type: str, data: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_pipeline_events(
    runner: StageRunner,
    project_id: str,
    stages: list[StageName] | None,
    params: dict[str, Any],
    store: ProjectStore,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    progress_queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()

    def on_progress(event: ProgressEvent) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, event)

    convert_mode = params.get("convert_mode", "slice_batch")
    if isinstance(convert_mode, str):
        convert_mode = ConvertMode(convert_mode)
    slice_mode_raw = params.get("slice_mode")
    if slice_mode_raw is not None:
        slice_mode = SliceMode(slice_mode_raw) if isinstance(slice_mode_raw, str) else slice_mode_raw
    else:
        slice_mode = SliceMode(store.resolve_pipeline_slice_mode(project_id))
    pipeline_params = {k: v for k, v in params.items() if k not in ("convert_mode", "slice_mode")}

    task = asyncio.create_task(
        anyio.to_thread.run_sync(
            lambda: runner.run_pipeline(
                project_id,
                stages=stages,
                convert_mode=convert_mode,
                slice_mode=slice_mode,
                stop_on_error=True,
                on_progress=on_progress,
                **pipeline_params,
            )
        )
    )

    try:
        while not task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=_SSE_POLL_TIMEOUT_S)
                yield sse_frame("log", event.to_ui_dict())
            except asyncio.TimeoutError:
                if await is_disconnected():
                    return
                continue

        while not progress_queue.empty():
            yield sse_frame("log", progress_queue.get_nowait().to_ui_dict())

        result = await task
        yield sse_frame(
            "done",
            {"success": result.success, "error": result.error, "stage_results": [sr.__dict__ for sr in result.stage_results]},
        )
    except asyncio.CancelledError:
        raise


@router.post("/{project_id}/pipeline/run")
async def run_pipeline(
    project_id: str,
    body: dict[str, Any],
    request: Request,
    runner: StageRunner = Depends(get_runner),
    store: ProjectStore = Depends(get_store),
) -> StreamingResponse:
    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc

    params = dict(body.get("params", {}))
    stages_raw = body.get("stages")
    from_stage_raw = body.get("from_stage")

    stages: list[StageName] | None = None
    if stages_raw is not None:
        try:
            stages = [StageName(s) for s in stages_raw]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid stage: {exc}") from exc
    elif from_stage_raw is not None:
        try:
            from_stage = StageName(from_stage_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid from_stage: {exc}") from exc
        all_stages = list(StageName)
        idx = all_stages.index(from_stage)
        stages = all_stages[idx:]

    generator = stream_pipeline_events(
        runner, project_id, stages, params, store, is_disconnected=request.is_disconnected
    )
    return StreamingResponse(generator, media_type="text/event-stream")
