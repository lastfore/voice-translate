"""Audio/file serving — migrated from webui/helpers.py (abs_path/audio_if_exists).

Every path here goes through ``media_service.resolve_safe_path()`` (docs §5.0);
never construct a ``FileResponse`` from a raw request value.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from api.services.media_service import ALLOWED_AUDIO_EXTS, UnsafePathError, resolve_safe_path

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("")
def get_media(path: str = Query(...)) -> FileResponse:
    try:
        resolved = resolve_safe_path(path, must_exist=True, allow_extensions=ALLOWED_AUDIO_EXTS)
    except UnsafePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(resolved)
