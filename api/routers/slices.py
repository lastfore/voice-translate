"""Slice table endpoints — migrated from webui/components/slice_preview.py.

Includes Phase 1 ``GET /api/projects/{id}/slices`` and Phase 2 overrides
endpoints (§5.5).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_store
from api.services import slice_service
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/projects", tags=["slices"])


class OverridesPayload(BaseModel):
    slice_ids: list[str]
    params: dict[str, Any] = {}


def _ensure_project_exists(store: ProjectStore, project_id: str) -> None:
    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc


@router.get("/{project_id}/slices")
def get_slices(
    project_id: str,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    return slice_service.load_slice_table(project_id, mode)


@router.get("/{project_id}/slices/{slice_id}/audio")
def get_slice_audio(
    project_id: str,
    slice_id: str,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    url = slice_service.slice_audio_url(project_id, mode, slice_id)
    if url is None:
        raise HTTPException(status_code=404, detail=f"slice not found: {slice_id}")
    return {"url": url}


@router.get("/{project_id}/slices/{slice_id}/audio/converted")
def get_converted_slice_audio(
    project_id: str,
    slice_id: str,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    url = slice_service.converted_slice_audio_url(project_id, mode, slice_id)
    if url is None:
        raise HTTPException(status_code=404, detail=f"converted slice not found: {slice_id}")
    return {"url": url}


@router.get("/{project_id}/slices/overrides")
def get_overrides(
    project_id: str,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    return slice_service.load_overrides(project_id, mode)


@router.put("/{project_id}/slices/overrides")
def put_overrides(
    project_id: str,
    body: OverridesPayload,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    return slice_service.save_overrides(project_id, mode, body.slice_ids, body.params)


@router.delete("/{project_id}/slices/overrides")
def delete_overrides(
    project_id: str,
    mode: str = Query("lrc"),
    slice_ids: list[str] | None = Body(None),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    return slice_service.delete_overrides(project_id, mode, slice_ids)


@router.post("/{project_id}/slices/overrides/clear-orphans")
def clear_overrides_orphans(
    project_id: str,
    mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    _ensure_project_exists(store, project_id)
    return slice_service.clear_overrides_orphans(project_id, mode)
