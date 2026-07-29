"""Path safety and media/file helpers — migrated from webui/helpers.py.

This module is the single collection point for path validation (see migration
doc §5.0 / §11). Every endpoint that accepts a user-controlled filesystem path
must resolve it through :func:`resolve_safe_path` before touching the
filesystem — never call ``Path(...).open()``/``FileResponse(...)`` directly
with a raw request value.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipeline import paths

ALLOWED_AUDIO_EXTS = {".flac", ".wav", ".mp3", ".m4a", ".ogg", ".lrc"}
ALLOWED_BROWSE_EXTS = ALLOWED_AUDIO_EXTS | {".json", ".txt"}


class UnsafePathError(Exception):
    """Raised when a user-supplied path fails safety validation."""


def resolve_safe_path(
    raw: str,
    *,
    must_exist: bool = True,
    allow_extensions: set[str] | None = None,
    root: Path | None = None,
) -> Path:
    """Resolve a user-supplied path to a safe absolute path under *root*.

    - ``root`` defaults to ``paths.get_root()``; pass a narrower root (e.g.
      ``paths.get_separator_env()``) to further restrict an endpoint.
    - The resolved path must be ``root``-relative (blocks ``..`` traversal and
      absolute paths that point outside root).
    - ``allow_extensions`` — case-insensitive suffix whitelist (``None`` skips
      this check, used for directory-browsing endpoints).
    - ``must_exist=True`` (default) requires the resolved path to exist.
    """
    root = (root or paths.get_root()).resolve()
    if not raw:
        raise UnsafePathError("empty path")

    raw_path = Path(raw)
    candidate = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"path outside root: {candidate}") from exc

    if allow_extensions is not None and candidate.suffix.lower() not in allow_extensions:
        raise UnsafePathError(f"extension not allowed: {candidate.suffix}")

    if must_exist and not candidate.exists():
        raise UnsafePathError(f"not found: {candidate}")

    return candidate


def abs_media_path(value: str | None) -> Path | None:
    """API analogue of ``webui.helpers.abs_path`` — resolves or returns None.

    Unlike :func:`resolve_safe_path`, this never raises; callers that need to
    surface a 4xx to the HTTP client should call ``resolve_safe_path`` directly.
    """
    if not value or not str(value).strip():
        return None
    try:
        return resolve_safe_path(str(value), must_exist=True, allow_extensions=None)
    except UnsafePathError:
        return None


def media_url_for(value: str | None) -> str | None:
    """API analogue of ``webui.helpers.audio_if_exists`` — returns a ``/api/media`` URL."""
    resolved = abs_media_path(value)
    if resolved is None or not resolved.is_file():
        return None
    root = paths.get_root().resolve()
    rel = resolved.relative_to(root).as_posix()
    return f"/api/media?path={rel}"


def is_directory_path(value: str | None) -> bool:
    p = abs_media_path(value)
    return p is not None and p.is_dir()


def split_vocals_paths(vocals: str | None) -> tuple[str, str]:
    """Return (whole_track_file, slice_directory) from a resolved vocals value."""
    if not vocals or not str(vocals).strip():
        return "", ""
    if is_directory_path(vocals):
        return "", str(vocals)
    return str(vocals), ""


def first_audio_in_dir(directory: str | None, limit: int = 5) -> list[str]:
    p = abs_media_path(directory)
    if p is None or not p.is_dir():
        return []
    exts = {".flac", ".wav", ".mp3", ".ogg"}
    files = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)
    return [str(f) for f in files[:limit]]


def resolve_convert_preview_audio(
    project_id: str | None,
    convert_mode: str,
    slice_mode: str,
) -> str | None:
    """Preview audio for convert tab: full track file or first converted slice."""
    if not project_id:
        return None
    if convert_mode == "full_track":
        full_p = paths.resolve_converted_full_track(project_id)
        return media_url_for(str(full_p) if full_p else None)
    from api.services.slice_service import load_converted_slice_table

    table = load_converted_slice_table(project_id, slice_mode)
    if table["first_audio_url"]:
        return table["first_audio_url"]
    for alt in paths.SLICE_MODES:
        if alt == paths.normalize_slice_mode(slice_mode):
            continue
        alt_table = load_converted_slice_table(project_id, alt)
        if alt_table["first_audio_url"]:
            return alt_table["first_audio_url"]
    mode_dir = paths.resolve_converted_mode_dir(project_id, slice_mode) or paths.resolve_converted_slices_dir(
        project_id, slice_mode
    )
    if mode_dir is not None:
        previews = first_audio_in_dir(str(mode_dir), limit=1)
        if previews:
            return media_url_for(previews[0])
    return None


def save_upload(upload_path: str | Path, dest: Path) -> Path | None:
    src = Path(upload_path)
    if not src.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def save_reference_audio(project_id: str, upload_path: str | Path) -> str | None:
    """Persist a reference audio upload under ``input/{project_id}/reference.*``."""
    ref_dir = paths.input_dir() / project_id
    ref_dir.mkdir(parents=True, exist_ok=True)
    src = Path(upload_path)
    suffix = src.suffix.lower() or ".wav"
    dest = ref_dir / f"reference{suffix}"
    saved = save_upload(upload_path, dest)
    if saved is None:
        return None
    root = paths.get_root().resolve()
    return str(saved.resolve().relative_to(root)).replace("\\", "/")


def read_manifest_preview(project_id: str | None, slice_mode: str, max_rows: int = 8) -> str:
    """Return a concise text preview of the current slice manifest."""
    if not project_id:
        return ""
    mode_dir = paths.resolve_slices_mode_dir(project_id, slice_mode)
    if mode_dir is None:
        return ""
    manifest = mode_dir / "manifest.json"
    if not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    slices = list(data.get("slices") or [])
    lines = ["id | file | start_ms | end_ms"]
    for item in slices[:max_rows]:
        lines.append(
            f"{item.get('id')} | {item.get('file')} | {item.get('start_ms')} | {item.get('end_ms')}"
        )
    if len(slices) > max_rows:
        lines.append(f"... 共 {len(slices)} 条")
    return "\n".join(lines)
