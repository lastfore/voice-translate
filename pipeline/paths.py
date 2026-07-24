"""Centralized path resolution for the voice-translate pipeline."""

from __future__ import annotations

import os
import re
from pathlib import Path

_VOCALS_STEM_RE = re.compile(r"^(.+?)_\(Vocals\)_", re.IGNORECASE)


def get_root() -> Path:
    """Repository root: VOICE_TRANSLATE_ROOT env, else parent of pipeline/."""
    env = os.environ.get("VOICE_TRANSLATE_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def get_separator_env() -> Path:
    env = os.environ.get("SEPARATOR_ENV")
    if env:
        return Path(env).resolve()
    return get_root() / "separator-env"


def get_seed_vc_env() -> Path:
    env = os.environ.get("SEED_VC_ENV")
    if env:
        return Path(env).resolve()
    return get_root() / "seed-vc-env"


def input_dir() -> Path:
    return get_root() / "input"


def output_dir() -> Path:
    return get_root() / "output"


def projects_meta_dir() -> Path:
    return output_dir() / ".projects"


def project_meta_path(project_id: str) -> Path:
    return projects_meta_dir() / project_id / "project.json"


def project_logs_dir(project_id: str) -> Path:
    return projects_meta_dir() / project_id / "logs"


def separated_dir() -> Path:
    return output_dir() / "separated"


def _glob_first(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None


def separated_vocals_path(project_id: str) -> Path | None:
    """Glob match ``{id}_(Vocals)_*.flac`` (case-insensitive Vocals)."""
    base = separated_dir()
    if not base.is_dir():
        return None
    for pattern in (
        f"{project_id}_(Vocals)_*.flac",
        f"{project_id}_(vocals)_*.flac",
        f"{project_id}_*(Vocals)*.flac",
    ):
        hit = _glob_first(base, pattern)
        if hit:
            return hit
    # Fallback: any file containing project_id and Vocals
    for path in sorted(base.glob("*.flac")):
        name_lower = path.name.lower()
        if project_id.lower() in name_lower and "vocal" in name_lower and "instrumental" not in name_lower:
            return path
    return None


def separated_instrumental_path(project_id: str) -> Path | None:
    """Glob match instrumental stem; MDXC models emit ``(Other)`` instead of ``(Instrumental)``."""
    base = separated_dir()
    if not base.is_dir():
        return None
    for pattern in (
        f"{project_id}_(Instrumental)_*.flac",
        f"{project_id}_(instrumental)_*.flac",
        f"{project_id}_(Other)_*.flac",
        f"{project_id}_(other)_*.flac",
    ):
        hit = _glob_first(base, pattern)
        if hit:
            return hit
    for path in sorted(base.glob("*.flac")):
        name_lower = path.name.lower()
        if project_id.lower() not in name_lower or "vocal" in name_lower:
            continue
        if "instrumental" in name_lower or "(other)" in name_lower:
            return path
    return None


def slices_dir(project_id: str) -> Path:
    return output_dir() / "slices" / project_id


def slices_manifest_path(project_id: str) -> Path:
    return slices_dir(project_id) / "manifest.json"


def converted_dir(project_id: str) -> Path:
    return output_dir() / "converted" / project_id


def converted_full_dir(project_id: str) -> Path:
    return converted_dir(project_id) / "full"


def converted_slices_dir(project_id: str) -> Path:
    return converted_dir(project_id) / "slices"


_AUDIO_EXTS = {".flac", ".wav", ".mp3", ".ogg"}


def _is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _AUDIO_EXTS


def _dir_has_audio(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(_is_audio_file(p) for p in directory.iterdir())


def _dir_has_slice_flacs(directory: Path) -> bool:
    """True when directory holds per-slice audio (legacy flat or slices/)."""
    if not directory.is_dir():
        return False
    for path in directory.iterdir():
        if not _is_audio_file(path):
            continue
        if path.name.lower() == "full.flac":
            continue
        if "slice" in path.name.lower():
            return True
    return False


def converted_full_track_path(project_id: str) -> Path:
    """Canonical write path for whole-track conversion (new layout)."""
    return converted_full_dir(project_id) / "full.flac"


def converted_legacy_full_track_path(project_id: str) -> Path:
    return converted_dir(project_id) / "full.flac"


def resolve_converted_full_track(project_id: str) -> Path | None:
    """New layout ``full/full.flac``, then legacy ``full.flac`` at project root."""
    new = converted_full_track_path(project_id)
    if new.is_file():
        return new
    legacy = converted_legacy_full_track_path(project_id)
    return legacy if legacy.is_file() else None


def resolve_converted_slices_dir(project_id: str) -> Path | None:
    """New layout ``slices/``, then legacy flat directory with slice files."""
    new = converted_slices_dir(project_id)
    if new.is_dir() and _dir_has_audio(new):
        return new
    legacy = converted_dir(project_id)
    if legacy.is_dir() and _dir_has_slice_flacs(legacy):
        return legacy
    return None


def has_converted_artifacts(project_id: str) -> bool:
    return resolve_converted_full_track(project_id) is not None or resolve_converted_slices_dir(
        project_id
    ) is not None


def merged_dir(project_id: str) -> Path:
    return output_dir() / "merged" / project_id


def legacy_flat_merged_dir() -> Path:
    """Pre-WebUI flat merge output (``output/merged/`` without project subdir)."""
    return output_dir() / "merged"


def legacy_flat_merged_mixed() -> Path:
    return legacy_flat_merged_dir() / "mixed.flac"


def extract_project_id_from_vocals_filename(filename: str) -> str | None:
    match = _VOCALS_STEM_RE.match(filename)
    return match.group(1) if match else None


def infer_project_ids_from_separated() -> set[str]:
    """Discover project IDs from ``output/separated/*_(Vocals)_*.flac`` names."""
    base = separated_dir()
    if not base.is_dir():
        return set()
    ids: set[str] = set()
    for path in base.glob("*.flac"):
        pid = extract_project_id_from_vocals_filename(path.name)
        if pid:
            ids.add(pid)
    return ids


def has_per_project_merged(project_id: str) -> bool:
    return (merged_dir(project_id) / "mixed.flac").is_file()


def input_audio_path(project_id: str) -> Path | None:
    """Resolve input/{id}.* for common audio extensions."""
    base = input_dir()
    for ext in (".flac", ".wav", ".mp3", ".ogg", ".m4a"):
        candidate = base / f"{project_id}{ext}"
        if candidate.is_file():
            return candidate
    return None


def input_lrc_path(project_id: str) -> Path | None:
    candidate = input_dir() / f"{project_id}.lrc"
    return candidate if candidate.is_file() else None


def project_reference_path(project_id: str) -> Path | None:
    """Reference audio under input/{id}/reference.wav or input/{id}_reference.wav."""
    candidates = [
        input_dir() / project_id / "reference.wav",
        input_dir() / f"{project_id}_reference.wav",
        input_dir() / project_id / "reference.flac",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None
