"""Artifact preview endpoints — convert preview + manifest preview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_store
from api.services import media_service
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/projects", tags=["artifacts"])


def _ensure_project_exists(store: ProjectStore, project_id: str) -> None:
    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc


@router.get("/{project_id}/artifacts/convert-preview")
def convert_preview(
    project_id: str,
    mode: str = Query("slice_batch"),
    slice_mode: str = Query("lrc"),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    """Return a playable URL for the convert-stage preview audio."""
    _ensure_project_exists(store, project_id)
    url = media_service.resolve_convert_preview_audio(project_id, mode, slice_mode)
    return {"url": url}


@router.get("/{project_id}/manifest-preview")
def manifest_preview(
    project_id: str,
    mode: str = Query("lrc"),
    max_rows: int = Query(8, ge=1, le=100),
    store: ProjectStore = Depends(get_store),
) -> dict[str, Any]:
    """Return a concise text preview of the current slice manifest."""
    _ensure_project_exists(store, project_id)
    preview = media_service.read_manifest_preview(project_id, mode, max_rows=max_rows)
    return {"preview": preview}
