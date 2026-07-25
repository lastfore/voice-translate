"""Centralized path resolution for the voice-translate pipeline."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DeleteScope = Literal["metadata", "artifacts", "all"]

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


SLICE_MODES = ("lrc", "vad")


def normalize_slice_mode(mode: str | None) -> str:
    if mode in SLICE_MODES:
        return mode
    return "lrc"


def slices_mode_dir(project_id: str, mode: str) -> Path:
    return slices_dir(project_id) / normalize_slice_mode(mode)


def slices_manifest_path(project_id: str, mode: str | None = None) -> Path:
    if mode is not None:
        return slices_mode_dir(project_id, mode) / "manifest.json"
    return slices_dir(project_id) / "manifest.json"


def slices_overrides_path(project_id: str, mode: str) -> Path:
    return slices_mode_dir(project_id, mode) / "overrides.json"


def converted_mode_dir(project_id: str, mode: str) -> Path:
    return converted_dir(project_id) / normalize_slice_mode(mode)


def merged_mode_dir(project_id: str, mode: str) -> Path:
    return merged_dir(project_id) / normalize_slice_mode(mode)


def merged_mixed_path(project_id: str, mode: str) -> Path:
    return merged_mode_dir(project_id, mode) / "mixed.flac"


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


def resolve_converted_slices_dir(project_id: str, mode: str | None = None) -> Path | None:
    """Resolve converted slice directory for *mode* (or legacy layouts)."""
    if mode is not None:
        resolved = resolve_converted_mode_dir(project_id, mode)
        if resolved is not None:
            return resolved

    for candidate_mode in SLICE_MODES:
        resolved = resolve_converted_mode_dir(project_id, candidate_mode)
        if resolved is not None:
            return resolved

    new = converted_slices_dir(project_id)
    if new.is_dir() and _dir_has_audio(new):
        return new
    legacy = converted_dir(project_id)
    if legacy.is_dir() and _dir_has_slice_flacs(legacy):
        return legacy
    return None


def resolve_converted_mode_dir(project_id: str, mode: str) -> Path | None:
    """``converted/{id}/{mode}/`` when it contains slice audio."""
    mode_dir = converted_mode_dir(project_id, mode)
    if mode_dir.is_dir() and _dir_has_audio(mode_dir):
        return mode_dir
    return None


def resolve_slices_mode_dir(project_id: str, mode: str) -> Path | None:
    """``slices/{id}/{mode}/`` when it exists; legacy flat root as *vad* fallback."""
    mode_dir = slices_mode_dir(project_id, mode)
    manifest = slices_manifest_path(project_id, mode)
    if mode_dir.is_dir() and (manifest.is_file() or _dir_has_audio(mode_dir)):
        return mode_dir
    if normalize_slice_mode(mode) == "vad":
        base = slices_dir(project_id)
        legacy_manifest = base / "manifest.json"
        if base.is_dir() and (legacy_manifest.is_file() or _dir_has_audio(base)):
            return base
    return None


def has_converted_artifacts(project_id: str) -> bool:
    if resolve_converted_full_track(project_id) is not None:
        return True
    return resolve_converted_slices_dir(project_id) is not None


def has_per_project_merged(project_id: str, mode: str | None = None) -> bool:
    if mode is not None:
        return merged_mixed_path(project_id, mode).is_file()
    if (merged_dir(project_id) / "mixed.flac").is_file():
        return True
    return any(merged_mixed_path(project_id, m).is_file() for m in SLICE_MODES)


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


@dataclass
class ProjectArtifactGroup:
    metadata: list[Path]
    artifacts: list[Path]
    inputs: list[Path]


def _unique_existing(paths_list: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths_list:
        if not path.exists():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _separated_stem_paths(project_id: str) -> list[Path]:
    base = separated_dir()
    if not base.is_dir():
        return []
    hits: list[Path] = []
    for path in sorted(base.glob("*.flac")):
        name_lower = path.name.lower()
        if project_id.lower() not in name_lower:
            continue
        hits.append(path)
    return hits


def collect_project_artifacts(project_id: str) -> ProjectArtifactGroup:
    """Enumerate on-disk paths associated with *project_id*."""
    metadata: list[Path] = []
    meta_dir = projects_meta_dir() / project_id
    if meta_dir.exists():
        metadata.append(meta_dir)

    artifacts: list[Path] = []
    for directory in (slices_dir(project_id), converted_dir(project_id), merged_dir(project_id)):
        if directory.exists():
            artifacts.append(directory)
    artifacts.extend(_separated_stem_paths(project_id))

    inputs: list[Path] = []
    audio = input_audio_path(project_id)
    if audio is not None:
        inputs.append(audio)
    lrc = input_lrc_path(project_id)
    if lrc is not None:
        inputs.append(lrc)
    ref = project_reference_path(project_id)
    if ref is not None:
        inputs.append(ref)
    ref_dir = input_dir() / project_id
    if ref_dir.is_dir():
        inputs.append(ref_dir)

    return ProjectArtifactGroup(
        metadata=_unique_existing(metadata),
        artifacts=_unique_existing(artifacts),
        inputs=_unique_existing(inputs),
    )


def paths_for_scope(group: ProjectArtifactGroup, scope: DeleteScope) -> list[Path]:
    if scope == "metadata":
        return list(group.metadata)
    if scope == "artifacts":
        return _unique_existing(group.metadata + group.artifacts)
    return _unique_existing(group.metadata + group.artifacts + group.inputs)


def rel_to_root(path: Path) -> str:
    root = get_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path.resolve())
