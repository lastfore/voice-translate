"""Local filesystem browsing for ``PathInput`` — migrated from webui/components/path_input.py.

Gap-fill note (Phase 1): the migration doc (§5.3/§7) lists ``GET /api/fs/browse``
as part of the target API surface, but Phase 0 only shipped ``/api/media``.
This router closes that gap so the React ``PathInput``/``FileBrowserDialog``
components have a real backend to talk to.

Every path this module touches goes through
``media_service.resolve_safe_path()`` (docs §5.0) — never construct a
directory listing from a raw, unvalidated request path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.services.media_service import UnsafePathError, resolve_safe_path
from pipeline import paths

router = APIRouter(prefix="/api/fs", tags=["filesystem"])


def _rel(p: Path, root: Path) -> str:
    rel = p.resolve().relative_to(root).as_posix()
    return "" if rel == "." else rel


def _normalize_extensions(extensions: str | None) -> set[str] | None:
    if not extensions:
        return None
    out: set[str] = set()
    for raw in extensions.split(","):
        ext = raw.strip().lower()
        if not ext:
            continue
        out.add(ext if ext.startswith(".") else f".{ext}")
    return out or None


def _entry(child: Path, root: Path) -> dict[str, Any]:
    is_dir = child.is_dir()
    return {
        "name": child.name,
        "path": _rel(child, root),
        "is_dir": is_dir,
    }


@router.get("/browse")
def browse(
    path: str = Query(""),
    extensions: str | None = Query(None, description="Comma-separated file extension whitelist, e.g. '.flac,.wav'"),
    dirs_only: bool = Query(False, description="Directory-picker mode: only list subdirectories"),
) -> dict[str, Any]:
    root = paths.get_root().resolve()

    if not path or path.strip() in ("", "."):
        target = root
    else:
        try:
            target = resolve_safe_path(path, must_exist=True, allow_extensions=None, root=root)
        except UnsafePathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {path}")

    ext_filter = _normalize_extensions(extensions)

    try:
        children = sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    entries: list[dict[str, Any]] = []
    for child in children:
        if child.is_dir():
            entries.append(_entry(child, root))
            continue
        if dirs_only:
            continue
        if ext_filter is not None and child.suffix.lower() not in ext_filter:
            continue
        entries.append(_entry(child, root))

    parent = _rel(target.parent, root) if target != root else None

    return {
        "path": _rel(target, root),
        "parent": parent,
        "entries": entries,
    }
