"""Project CRUD + defaults — migrated from webui/components/project_sidebar.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.deps import get_store
from api.services import media_service, pipeline_service
from pipeline.store import ProjectStore

router = APIRouter(prefix="/api/projects", tags=["projects"])


class DeleteRequest(BaseModel):
    scope: str = "metadata"
    confirmed: bool = False


def _save_upload_to_temp(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        return Path(tmp.name)


@router.get("")
def list_projects(refresh: bool = False, store: ProjectStore = Depends(get_store)) -> list[dict]:
    return pipeline_service.list_projects(store, refresh=refresh)


@router.post("", status_code=201)
def create_project(
    project_id: str = Form(...),
    display_name: str | None = Form(None),
    audio: UploadFile = File(...),
    lrc: UploadFile | None = File(None),
    store: ProjectStore = Depends(get_store),
) -> dict:
    audio_tmp = _save_upload_to_temp(audio)
    lrc_tmp: Path | None = None
    try:
        if lrc is not None and lrc.filename:
            lrc_tmp = _save_upload_to_temp(lrc)
        return pipeline_service.create_project(
            store, project_id, audio_tmp, lrc_tmp, display_name=display_name
        )
    except pipeline_service.ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except pipeline_service.InvalidProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        audio_tmp.unlink(missing_ok=True)
        if lrc_tmp is not None:
            lrc_tmp.unlink(missing_ok=True)


@router.get("/{project_id}")
def get_project(project_id: str, store: ProjectStore = Depends(get_store)) -> dict:
    try:
        return pipeline_service.get_project(store, project_id)
    except pipeline_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/defaults")
def get_defaults(project_id: str, store: ProjectStore = Depends(get_store)) -> dict:
    try:
        return pipeline_service.get_project_defaults(store, project_id)
    except pipeline_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/delete-preview")
def get_delete_preview(
    project_id: str, scope: str = "metadata", store: ProjectStore = Depends(get_store)
) -> list[dict]:
    return pipeline_service.delete_preview(store, project_id, scope)


@router.delete("/{project_id}")
def delete_project(
    project_id: str, body: DeleteRequest, store: ProjectStore = Depends(get_store)
) -> dict:
    try:
        return pipeline_service.delete_project(
            store, project_id, body.scope, confirmed=body.confirmed
        )
    except pipeline_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except pipeline_service.ProjectBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except pipeline_service.InvalidProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{project_id}/reference")
def upload_reference_audio(
    project_id: str,
    audio: UploadFile = File(...),
    store: ProjectStore = Depends(get_store),
) -> dict:
    """Upload a reference audio file for the convert stage."""
    try:
        store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}") from exc

    tmp = _save_upload_to_temp(audio)
    try:
        saved = media_service.save_reference_audio(project_id, tmp)
    finally:
        tmp.unlink(missing_ok=True)

    if saved is None:
        raise HTTPException(status_code=400, detail="failed to save reference audio")
    return {"reference": saved}
