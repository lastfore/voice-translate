"""Shared UI formatting and path helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipeline import paths
from pipeline.models import StageName, StageStatus

STAGE_LABELS: dict[str, str] = {
    StageName.SEPARATE.value: "分离",
    StageName.SLICE.value: "切片",
    StageName.CONVERT.value: "转换",
    StageName.MERGE.value: "合并",
}


def format_stage_icons(stage_status: dict[str, str]) -> str:
    parts: list[str] = []
    for key, label in STAGE_LABELS.items():
        status = stage_status.get(key, StageStatus.NOT_RUN.value)
        if status == StageStatus.DONE.value:
            icon = "●"
        elif status == StageStatus.RUNNING.value:
            icon = "◐"
        elif status == StageStatus.FAILED.value:
            icon = "✗"
        else:
            icon = "○"
        parts.append(f"{icon}{label}")
    return " ".join(parts)


def format_project_choice(summary: dict) -> str:
    icons = format_stage_icons(summary.get("stages", {}))
    return f"{summary['display_name']} ({summary['id']}) — {icons}"


def project_choices(summaries: list[dict]) -> list[tuple[str, str]]:
    # Gradio 5 Dropdown/CheckboxGroup: (display_name, value)
    return [(format_project_choice(s), s["id"]) for s in summaries]


def abs_path(value: str | None) -> Path | None:
    if not value or not str(value).strip():
        return None
    p = Path(value)
    if not p.is_absolute():
        p = paths.get_root() / p
    return p.resolve() if p.exists() else None


def is_directory_path(value: str | None) -> bool:
    p = abs_path(value)
    return p is not None and p.is_dir()


def split_vocals_paths(vocals: str | None) -> tuple[str, str]:
    """Return (whole_track_file, slice_directory) paths from a resolved vocals value."""
    if not vocals or not str(vocals).strip():
        return "", ""
    if is_directory_path(vocals):
        return "", str(vocals)
    return str(vocals), ""


def audio_if_exists(value: str | None) -> str | None:
    p = abs_path(value)
    return str(p) if p and p.is_file() else None


def first_audio_in_dir(directory: str | None, limit: int = 5) -> list[str]:
    p = abs_path(directory)
    if p is None or not p.is_dir():
        return []
    exts = {".flac", ".wav", ".mp3", ".ogg"}
    files = sorted(f for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts)
    return [str(f) for f in files[:limit]]


def save_upload(upload_path: str | None, dest: Path) -> Path | None:
    if not upload_path:
        return None
    src = Path(upload_path)
    if not src.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def save_reference_audio(project_id: str, upload_path: str | None) -> str | None:
    if not upload_path:
        return None
    ref_dir = paths.input_dir() / project_id
    ref_dir.mkdir(parents=True, exist_ok=True)
    dest = ref_dir / "reference.wav"
    src = Path(upload_path)
    suffix = src.suffix.lower() or ".wav"
    dest = ref_dir / f"reference{suffix}"
    saved = save_upload(upload_path, dest)
    return str(saved) if saved else None


def count_manifest_slices(manifest_path: str | Path | None) -> int:
    p = abs_path(str(manifest_path)) if manifest_path else None
    if p is None or not p.is_file():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return len(data.get("slices") or [])
    except (json.JSONDecodeError, OSError):
        return 0


def format_slice_mode_status(project_id: str) -> str:
    """Summarize LRC/VAD slice trees for sidebar display."""
    parts: list[str] = []
    for mode in paths.SLICE_MODES:
        mode_dir = paths.resolve_slices_mode_dir(project_id, mode)
        if not mode_dir:
            parts.append(f"{mode.upper()}: —")
            continue
        manifest = mode_dir / "manifest.json"
        count = count_manifest_slices(manifest)
        converted = paths.resolve_converted_mode_dir(project_id, mode)
        conv_mark = "✓" if converted else "○"
        parts.append(f"{mode.upper()}: {count}片 {conv_mark}")
    return "  ".join(parts)


def read_manifest_preview(manifest_path: str | None, max_rows: int = 8) -> str:
    p = abs_path(manifest_path)
    if p is None or not p.is_file():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        slices = data.get("slices") or []
        lines = ["id | file | start_ms | end_ms"]
        for item in slices[:max_rows]:
            lines.append(
                f"{item.get('id')} | {item.get('file')} | {item.get('start_ms')} | {item.get('end_ms')}"
            )
        if len(slices) > max_rows:
            lines.append(f"... 共 {len(slices)} 条")
        return "\n".join(lines)
    except (json.JSONDecodeError, OSError):
        return ""
