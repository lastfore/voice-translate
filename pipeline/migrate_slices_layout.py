"""Migrate flat slice/converted/merged layouts to per-mode ``lrc/`` and ``vad/`` subdirs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pipeline import paths
from pipeline.models import SliceMode

_AUDIO_EXTS = {".flac", ".wav", ".mp3", ".ogg"}


def _is_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _AUDIO_EXTS


def _root_has_audio(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(_is_audio(p) for p in directory.iterdir() if p.is_file())


def _is_mode_layout(project_id: str) -> bool:
    base = paths.slices_dir(project_id)
    if not base.is_dir():
        return False
    return any((base / mode).is_dir() for mode in paths.SLICE_MODES)


def infer_manifest_mode(manifest_path: Path, project_id: str) -> str:
    """Guess whether legacy flat manifest came from LRC or VAD slicing."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SliceMode.VAD.value

    if data.get("slice_mode") == SliceMode.LRC.value:
        return SliceMode.LRC.value
    if data.get("lrc"):
        return SliceMode.LRC.value
    slices = data.get("slices") or []
    if slices and isinstance(slices[0], dict) and "text" in slices[0]:
        return SliceMode.LRC.value
    if paths.input_lrc_path(project_id):
        return SliceMode.LRC.value
    return SliceMode.VAD.value


def migrate_legacy_slices_layout(project_id: str, *, dry_run: bool = False) -> str | None:
    """Move flat ``slices/{id}/`` into ``{lrc|vad}/``. Returns migrated mode or None."""
    if _is_mode_layout(project_id):
        return None

    base = paths.slices_dir(project_id)
    if not base.is_dir():
        return None

    legacy_manifest = base / "manifest.json"
    has_root_audio = _root_has_audio(base)
    if not legacy_manifest.is_file() and not has_root_audio:
        return None

    mode = infer_manifest_mode(legacy_manifest, project_id) if legacy_manifest.is_file() else SliceMode.VAD.value
    target = paths.slices_mode_dir(project_id, mode)
    actions: list[str] = []

    # slices
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    for item in sorted(base.iterdir()):
        if item.is_dir():
            continue
        if item.name in {"manifest.json", "overrides.json"} or _is_audio(item):
            dest = target / item.name
            actions.append(f"slices: {item.name} -> {mode}/")
            if not dry_run:
                if dest.exists():
                    continue
                shutil.move(str(item), str(dest))

    # converted: slices/ subdir or flat slice files
    converted_base = paths.converted_dir(project_id)
    converted_target = paths.converted_mode_dir(project_id, mode)
    legacy_converted_slices = paths.converted_slices_dir(project_id)
    if legacy_converted_slices.is_dir() and _root_has_audio(legacy_converted_slices):
        actions.append(f"converted: slices/ -> {mode}/")
        if not dry_run:
            converted_target.mkdir(parents=True, exist_ok=True)
            for item in legacy_converted_slices.iterdir():
                if not item.is_file():
                    continue
                dest = converted_target / item.name
                if dest.exists():
                    continue
                shutil.move(str(item), str(dest))
            if legacy_converted_slices.is_dir() and not any(legacy_converted_slices.iterdir()):
                legacy_converted_slices.rmdir()
    elif converted_base.is_dir():
        slice_files = [
            p
            for p in converted_base.iterdir()
            if _is_audio(p) and p.name.lower() != "full.flac" and "slice" in p.name.lower()
        ]
        if slice_files:
            actions.append(f"converted: {len(slice_files)} flat slice(s) -> {mode}/")
            if not dry_run:
                converted_target.mkdir(parents=True, exist_ok=True)
                for src in slice_files:
                    dest = converted_target / src.name
                    if dest.exists():
                        continue
                    shutil.move(str(src), str(dest))

    # merged: flat mixed.flac
    legacy_mixed = paths.merged_dir(project_id) / "mixed.flac"
    new_mixed = paths.merged_mixed_path(project_id, mode)
    if legacy_mixed.is_file() and not new_mixed.is_file():
        actions.append(f"merged: mixed.flac -> {mode}/mixed.flac")
        if not dry_run:
            new_mixed.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy_mixed), str(new_mixed))

    return mode if actions or legacy_manifest.is_file() or has_root_audio else None


def migrate_all_projects(*, dry_run: bool = False) -> dict[str, str | None]:
    """Migrate every project under ``output/slices/`` that still uses flat layout."""
    results: dict[str, str | None] = {}
    slices_root = paths.output_dir() / "slices"
    if not slices_root.is_dir():
        return results
    for child in sorted(slices_root.iterdir()):
        if child.is_dir():
            results[child.name] = migrate_legacy_slices_layout(child.name, dry_run=dry_run)
    return results
