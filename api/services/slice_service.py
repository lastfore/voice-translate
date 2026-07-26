"""Slice table / preview logic — migrated from webui/helpers.py + slice_preview.py.

Backs ``GET /api/projects/{id}/slices`` (SliceTable.tsx) and the Phase 2
overrides lifecycle endpoints (§5.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.slice_overrides import (
    SliceOverrides,
    apply_slice_override,
    clear_orphans,
    clear_slice_overrides,
    load as load_overrides_model,
    save as save_overrides_model,
)

from api.services.media_service import media_url_for


class ProjectNotFoundError(Exception):
    pass


def _manifest_path(project_id: str, slice_mode: str) -> Path | None:
    mode_dir = paths.resolve_slices_mode_dir(project_id, slice_mode)
    if mode_dir is None:
        return None
    manifest = mode_dir / "manifest.json"
    return manifest if manifest.is_file() else None


def load_manifest_entries(project_id: str, slice_mode: str) -> list[dict[str, Any]]:
    manifest_path = _manifest_path(project_id, slice_mode)
    if manifest_path is None:
        return []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return list(data.get("slices") or [])
    except (json.JSONDecodeError, OSError):
        return []


def _tune_status_for_slice(project_id: str, slice_mode: str, slice_id: str) -> str:
    overrides_path = paths.slices_overrides_path(project_id, slice_mode)
    if not overrides_path.is_file():
        return ""
    from pipeline.slice_overrides import load as load_overrides

    overrides = load_overrides(overrides_path)
    return "tuned" if slice_id in overrides.slices else ""


def slice_audio_url(project_id: str, slice_mode: str, slice_id: str) -> str | None:
    entries = load_manifest_entries(project_id, slice_mode)
    item = next((entry for entry in entries if str(entry.get("id")) == slice_id), None)
    if item is None:
        return None
    mode_dir = paths.resolve_slices_mode_dir(project_id, slice_mode)
    if mode_dir is None:
        return None
    file_name = str(item.get("file", ""))
    return media_url_for(str(mode_dir / file_name)) if file_name else None


def load_slice_table(project_id: str, slice_mode: str) -> dict[str, Any]:
    """Structured equivalent of ``webui.helpers.load_slice_table``.

    Response shape consumed by ``SliceTable.tsx``::

        {
          "mode": "lrc",
          "dir_path": "output/slices/mysong/lrc" | None,
          "rows": [{"id", "start_ms", "end_ms", "text", "file", "status", "audio_url"}],
          "first_audio_url": "/api/media?path=..." | None,
        }
    """
    normalized = paths.normalize_slice_mode(slice_mode)
    entries = load_manifest_entries(project_id, normalized)
    mode_dir = paths.resolve_slices_mode_dir(project_id, normalized)

    root = paths.get_root().resolve()
    dir_path = mode_dir.resolve().relative_to(root).as_posix() if mode_dir else None

    rows: list[dict[str, Any]] = []
    for item in entries:
        slice_id = str(item.get("id", ""))
        file_name = str(item.get("file", "") or "")
        audio_url = media_url_for(str(mode_dir / file_name)) if mode_dir and file_name else None
        rows.append(
            {
                "id": slice_id,
                "start_ms": item.get("start_ms"),
                "end_ms": item.get("end_ms"),
                "text": item.get("text") or "",
                "file": file_name,
                "status": _tune_status_for_slice(project_id, normalized, slice_id),
                "audio_url": audio_url,
            }
        )

    first_audio_url = rows[0]["audio_url"] if rows else None

    return {
        "mode": normalized,
        "dir_path": dir_path,
        "rows": rows,
        "first_audio_url": first_audio_url,
    }


def converted_slice_audio_url(project_id: str, slice_mode: str, slice_id: str) -> str | None:
    """URL for the converted (re-tuned) slice audio, if it exists."""
    entries = load_manifest_entries(project_id, slice_mode)
    item = next((entry for entry in entries if str(entry.get("id")) == slice_id), None)
    if item is None:
        return None
    file_name = str(item.get("file", ""))
    converted_dir = paths.resolve_converted_mode_dir(project_id, slice_mode)
    if converted_dir is None or not file_name:
        return None
    return media_url_for(str(converted_dir / file_name))


def load_overrides(project_id: str, slice_mode: str) -> dict[str, Any]:
    """Return the overrides sidecar for *project_id* / *slice_mode* as JSON.

    Mirrors ``webui.components.slice_tuner`` read side: returns the slices
    map, global defaults, and orphans list.
    """
    normalized = paths.normalize_slice_mode(slice_mode)
    overrides_path = paths.slices_overrides_path(project_id, normalized)
    data = load_overrides_model(overrides_path)
    return {
        "slice_mode": normalized,
        "global_defaults": data.global_defaults,
        "slices": data.slices,
        "orphans": data.orphans,
    }


def save_overrides(
    project_id: str,
    slice_mode: str,
    slice_ids: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Apply per-slice convert params and persist the overrides sidecar."""
    normalized = paths.normalize_slice_mode(slice_mode)
    overrides_path = paths.slices_overrides_path(project_id, normalized)
    current = load_overrides_model(overrides_path)
    updated = apply_slice_override(current, slice_ids, params)
    save_overrides_model(overrides_path, updated)
    return load_overrides(project_id, normalized)


def delete_overrides(project_id: str, slice_mode: str, slice_ids: list[str] | None = None) -> dict[str, Any]:
    """Remove per-slice overrides. If *slice_ids* is None, clear all overrides."""
    normalized = paths.normalize_slice_mode(slice_mode)
    overrides_path = paths.slices_overrides_path(project_id, normalized)
    current = load_overrides_model(overrides_path)
    if slice_ids is None:
        updated = SliceOverrides(
            version=current.version,
            global_defaults=current.global_defaults,
            slices={},
            orphans=current.orphans,
        )
    else:
        updated = clear_slice_overrides(current, slice_ids)
    save_overrides_model(overrides_path, updated)
    return load_overrides(project_id, normalized)


def clear_overrides_orphans(project_id: str, slice_mode: str) -> dict[str, Any]:
    """Drop the orphan list from the overrides sidecar."""
    normalized = paths.normalize_slice_mode(slice_mode)
    overrides_path = paths.slices_overrides_path(project_id, normalized)
    current = load_overrides_model(overrides_path)
    updated = clear_orphans(current)
    save_overrides_model(overrides_path, updated)
    return load_overrides(project_id, normalized)
