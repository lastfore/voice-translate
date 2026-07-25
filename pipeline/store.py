"""Project CRUD, persistence, and input validation."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.paths import DeleteScope, collect_project_artifacts, paths_for_scope, rel_to_root
from pipeline.migrate_slices_layout import migrate_legacy_slices_layout
from pipeline.models import (
    MAX_JOB_HISTORY,
    ConvertMode,
    Job,
    JobStatus,
    Project,
    SliceMode,
    StageName,
    StageRecord,
    StageStatus,
    rel_path,
    utc_now_iso,
)

_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _abs_from_input(root: Path, value: str | Path | None) -> Path | None:
    if value is None or value == "":
        return None
    p = Path(value)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def _path_exists(value: str | Path | None, root: Path) -> bool:
    p = _abs_from_input(root, value)
    return p is not None and p.exists()


def _dir_has_audio(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    exts = {".flac", ".wav", ".mp3", ".ogg"}
    return any(p.suffix.lower() in exts for p in directory.iterdir() if p.is_file())


def _slices_dir_usable(value: str | Path | None, root: Path) -> bool:
    p = _abs_from_input(root, value)
    if p is None or not p.is_dir():
        return False
    if (p / "manifest.json").is_file():
        return True
    return _dir_has_audio(p)


class ProjectStore:
    """Project CRUD and state persistence."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or paths.get_root()).resolve()

    def _meta_path(self, project_id: str) -> Path:
        return paths.project_meta_path(project_id)

    def _load_raw(self, project_id: str) -> Project:
        meta = self._meta_path(project_id)
        if not meta.is_file():
            raise KeyError(f"Project not found: {project_id}")
        data = json.loads(meta.read_text(encoding="utf-8"))
        return Project.from_dict(data)

    def list_projects(self) -> list[Project]:
        meta_root = paths.projects_meta_dir()
        if not meta_root.is_dir():
            return []
        projects: list[Project] = []
        for child in sorted(meta_root.iterdir()):
            if not child.is_dir():
                continue
            meta_file = child / "project.json"
            if meta_file.is_file():
                try:
                    projects.append(Project.from_dict(json.loads(meta_file.read_text(encoding="utf-8"))))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    def get_project(self, project_id: str) -> Project:
        return self._load_raw(project_id)

    def save_project(self, project: Project) -> None:
        project.updated_at = utc_now_iso()
        project.save(self._meta_path(project.id), self.root)

    def create_project(
        self,
        project_id: str,
        audio_path: Path,
        lrc_path: Path | None = None,
        display_name: str | None = None,
    ) -> Project:
        if not _PROJECT_ID_RE.match(project_id):
            raise ValueError(
                f"Invalid project_id '{project_id}': use letters, digits, underscore, hyphen only"
            )
        if self._meta_path(project_id).is_file():
            raise ValueError(f"Project already exists: {project_id}")

        audio_path = Path(audio_path).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        paths.input_dir().mkdir(parents=True, exist_ok=True)
        dest_audio = paths.input_dir() / f"{project_id}{audio_path.suffix.lower()}"
        if audio_path != dest_audio:
            shutil.copy2(audio_path, dest_audio)

        dest_lrc: Path | None = None
        if lrc_path is not None:
            lrc_path = Path(lrc_path).resolve()
            if not lrc_path.is_file():
                raise FileNotFoundError(f"LRC file not found: {lrc_path}")
            dest_lrc = paths.input_dir() / f"{project_id}.lrc"
            if lrc_path != dest_lrc:
                shutil.copy2(lrc_path, dest_lrc)

        now = utc_now_iso()
        project = Project(
            id=project_id,
            display_name=display_name or project_id,
            created_at=now,
            updated_at=now,
            input_audio=rel_path(dest_audio, self.root),
            input_lrc=rel_path(dest_lrc, self.root) if dest_lrc else None,
        )
        self.save_project(project)
        return project

    def delete_project(
        self,
        project_id: str,
        *,
        scope: DeleteScope = "metadata",
        remove_files: bool | None = None,
    ) -> list[str]:
        """Delete project paths for *scope* and return removed paths (repo-relative)."""
        if remove_files is not None:
            scope = "artifacts" if remove_files else "metadata"

        group = collect_project_artifacts(project_id)
        targets = paths_for_scope(group, scope)
        if not targets:
            return []

        deleted: list[str] = []
        sorted_targets = sorted(targets, key=lambda p: len(p.resolve().parts), reverse=True)
        scheduled_dirs: list[Path] = []

        for target in sorted_targets:
            resolved = target.resolve()
            if any(resolved.is_relative_to(parent) for parent in scheduled_dirs):
                continue
            try:
                if resolved.is_dir():
                    shutil.rmtree(resolved, ignore_errors=False)
                    scheduled_dirs.append(resolved)
                elif resolved.is_file():
                    resolved.unlink(missing_ok=True)
                deleted.append(rel_to_root(resolved))
            except OSError:
                continue
        return deleted

    def preview_project_deletion(self, project_id: str, scope: DeleteScope) -> list[tuple[str, str]]:
        group = collect_project_artifacts(project_id)
        rows: list[tuple[str, str]] = []
        for path in paths_for_scope(group, scope):
            kind = "metadata"
            if path in group.artifacts:
                kind = "artifact"
            elif path in group.inputs:
                kind = "input"
            rows.append((kind, rel_to_root(path)))
        return rows

    def update_stage(
        self,
        project_id: str,
        stage: StageName,
        *,
        status: StageStatus,
        params: dict | None = None,
        inputs: dict | None = None,
        artifacts: dict | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> Project:
        project = self.get_project(project_id)
        record = project.stages[stage]
        record.status = status
        if params is not None:
            record.params = params
        if inputs is not None:
            record.inputs = inputs
        if artifacts is not None:
            record.artifacts = artifacts
        if error is not None or status in (StageStatus.DONE, StageStatus.NOT_RUN):
            record.error = error
        if started_at is not None:
            record.started_at = started_at
        if finished_at is not None:
            record.finished_at = finished_at
        if status == StageStatus.RUNNING and record.started_at is None:
            record.started_at = utc_now_iso()
        if status in (StageStatus.DONE, StageStatus.FAILED) and record.finished_at is None:
            record.finished_at = utc_now_iso()
        self.save_project(project)
        return project

    def save_stage_inputs(self, project_id: str, stage: StageName, inputs: dict) -> Project:
        project = self.get_project(project_id)
        project.stages[stage].inputs = dict(inputs)
        self.save_project(project)
        return project

    def add_job(self, project_id: str, job: Job) -> Project:
        project = self.get_project(project_id)
        project.jobs.insert(0, job)
        project.jobs = project.jobs[:MAX_JOB_HISTORY]
        self.save_project(project)
        return project

    def scan_and_repair(self) -> list[Project]:
        """Scan output/ for existing artifacts and create or update project.json."""
        repaired: list[Project] = []
        seen_ids: set[str] = set()

        slices_root = paths.output_dir() / "slices"
        if slices_root.is_dir():
            for child in slices_root.iterdir():
                if child.is_dir():
                    migrate_legacy_slices_layout(child.name)

        for existing in self.list_projects():
            seen_ids.add(existing.id)
            updated = self._infer_stage_state(existing)
            self.save_project(updated)
            repaired.append(updated)

        # Discover from slices/
        slices_root = paths.output_dir() / "slices"
        if slices_root.is_dir():
            for child in slices_root.iterdir():
                if child.is_dir() and child.name not in seen_ids:
                    project = self._bootstrap_project(child.name)
                    seen_ids.add(child.name)
                    repaired.append(project)

        # Discover from converted/
        converted_root = paths.output_dir() / "converted"
        if converted_root.is_dir():
            for child in converted_root.iterdir():
                if child.is_dir() and child.name not in seen_ids:
                    project = self._bootstrap_project(child.name)
                    seen_ids.add(child.name)
                    repaired.append(project)

        # Discover from input audio without meta
        if paths.input_dir().is_dir():
            for audio in paths.input_dir().iterdir():
                if audio.suffix.lower() not in {".flac", ".wav", ".mp3", ".ogg", ".m4a"}:
                    continue
                pid = audio.stem
                if pid not in seen_ids and _PROJECT_ID_RE.match(pid):
                    project = self._bootstrap_project(pid)
                    seen_ids.add(pid)
                    repaired.append(project)

        # Discover from separated/ vocal stem filenames
        for pid in paths.infer_project_ids_from_separated():
            if pid not in seen_ids and _PROJECT_ID_RE.match(pid):
                project = self._bootstrap_project(pid)
                seen_ids.add(pid)
                repaired.append(project)

        # Re-infer stage state (incl. legacy flat merged) with full project id set
        all_ids = set(seen_ids)
        final: list[Project] = []
        for pid in sorted(all_ids):
            try:
                project = self.get_project(pid)
            except KeyError:
                continue
            project = self._infer_stage_state(project, all_ids)
            self.save_project(project)
            final.append(project)

        return final

    def _active_slice_mode(self, project: Project, overrides: dict | None = None) -> str:
        if overrides:
            if overrides.get("slice_mode"):
                return paths.normalize_slice_mode(str(overrides["slice_mode"]))
            mode_val = overrides.get("mode")
            if mode_val in paths.SLICE_MODES:
                return paths.normalize_slice_mode(str(mode_val))
        for stage in (StageName.CONVERT, StageName.MERGE, StageName.SLICE):
            params = project.stages[stage].params
            if params.get("active_slice_mode"):
                return paths.normalize_slice_mode(str(params["active_slice_mode"]))
            if stage == StageName.SLICE and params.get("mode") in paths.SLICE_MODES:
                return paths.normalize_slice_mode(str(params["mode"]))
        if project.input_lrc and paths.input_lrc_path(project.id):
            return SliceMode.LRC.value
        return SliceMode.VAD.value

    def _bootstrap_project(self, project_id: str) -> Project:
        now = utc_now_iso()
        audio = paths.input_audio_path(project_id)
        lrc = paths.input_lrc_path(project_id)
        project = Project(
            id=project_id,
            display_name=project_id,
            created_at=now,
            updated_at=now,
            input_audio=rel_path(audio, self.root) if audio else None,
            input_lrc=rel_path(lrc, self.root) if lrc else None,
        )
        project = self._infer_stage_state(project)
        self.save_project(project)
        return project

    def _legacy_merge_eligible(self, project_id: str, all_project_ids: set[str]) -> bool:
        if paths.has_per_project_merged(project_id):
            return False
        if not paths.legacy_flat_merged_mixed().is_file():
            return False
        if len(all_project_ids) == 1:
            return project_id in all_project_ids
        with_sep = {pid for pid in all_project_ids if paths.separated_vocals_path(pid)}
        return len(with_sep) == 1 and project_id in with_sep

    def _infer_stage_state(self, project: Project, all_project_ids: set[str] | None = None) -> Project:
        pid = project.id

        vocals = paths.separated_vocals_path(pid)
        instrumental = paths.separated_instrumental_path(pid)
        if vocals or instrumental:
            rec = project.stages[StageName.SEPARATE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            rec.artifacts = {
                k: v
                for k, v in {
                    "vocals": rel_path(vocals, self.root) if vocals else None,
                    "instrumental": rel_path(instrumental, self.root) if instrumental else None,
                }.items()
                if v
            }

        sdir = paths.slices_dir(pid)
        slice_mode_art: dict[str, dict[str, str]] = {}
        for mode in paths.SLICE_MODES:
            mode_dir = paths.resolve_slices_mode_dir(pid, mode)
            if not mode_dir:
                continue
            manifest = mode_dir / "manifest.json"
            entry: dict[str, str] = {"slices_dir": rel_path(mode_dir, self.root)}
            if manifest.is_file():
                entry["manifest"] = rel_path(manifest, self.root)
            slice_mode_art[mode] = entry

        if slice_mode_art:
            rec = project.stages[StageName.SLICE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            active = self._active_slice_mode(project)
            rec.artifacts = dict(slice_mode_art)
            if active in slice_mode_art:
                rec.artifacts["slices_dir"] = slice_mode_art[active]["slices_dir"]
                if "manifest" in slice_mode_art[active]:
                    rec.artifacts["manifest"] = slice_mode_art[active]["manifest"]
        elif sdir.is_dir() and _dir_has_audio(sdir):
            rec = project.stages[StageName.SLICE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            manifest = paths.slices_manifest_path(pid)
            rec.artifacts = {
                "slices_dir": rel_path(sdir, self.root),
                "manifest": rel_path(manifest, self.root) if manifest.is_file() else None,
            }
            rec.artifacts = {k: v for k, v in rec.artifacts.items() if v}

        cdir = paths.converted_dir(pid)
        full = paths.resolve_converted_full_track(pid)
        convert_mode_art: dict[str, dict[str, str]] = {}
        for mode in paths.SLICE_MODES:
            converted = paths.resolve_converted_mode_dir(pid, mode)
            if converted:
                convert_mode_art[mode] = {"converted_dir": rel_path(converted, self.root)}

        slices = paths.resolve_converted_slices_dir(pid)
        if full or slices or convert_mode_art:
            rec = project.stages[StageName.CONVERT]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            artifacts: dict[str, Any] = dict(convert_mode_art)
            if slices:
                active = self._active_slice_mode(project)
                artifacts["converted_dir"] = rel_path(slices, self.root)
                if active not in artifacts:
                    artifacts[active] = {"converted_dir": rel_path(slices, self.root)}
            elif cdir.is_dir() and _dir_has_audio(cdir):
                artifacts["converted_dir"] = rel_path(cdir, self.root)
            if full:
                artifacts["full_track"] = rel_path(full, self.root)
            rec.artifacts = {k: v for k, v in artifacts.items() if v}

        merge_mode_art: dict[str, dict[str, str]] = {}
        for mode in paths.SLICE_MODES:
            mixed = paths.merged_mixed_path(pid, mode)
            if mixed.is_file():
                merge_mode_art[mode] = {
                    "merged_dir": rel_path(mixed.parent, self.root),
                    "mixed": rel_path(mixed, self.root),
                }
                vocals = mixed.parent / "vocals.flac"
                if vocals.is_file():
                    merge_mode_art[mode]["vocals"] = rel_path(vocals, self.root)

        mdir = paths.merged_dir(pid)
        mixed = mdir / "mixed.flac"
        if merge_mode_art:
            rec = project.stages[StageName.MERGE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            active = self._active_slice_mode(project)
            rec.artifacts = dict(merge_mode_art)
            if active in merge_mode_art:
                rec.artifacts.update(merge_mode_art[active])
        elif mixed.is_file():
            rec = project.stages[StageName.MERGE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            rec.artifacts = {
                "merged_dir": rel_path(mdir, self.root),
                "mixed": rel_path(mixed, self.root),
                "vocals": rel_path(mdir / "vocals.flac", self.root)
                if (mdir / "vocals.flac").is_file()
                else None,
            }
            rec.artifacts = {k: v for k, v in rec.artifacts.items() if v}

        ids = all_project_ids if all_project_ids is not None else {project.id}
        if self._legacy_merge_eligible(pid, ids):
            legacy_dir = paths.legacy_flat_merged_dir()
            legacy_mixed = paths.legacy_flat_merged_mixed()
            rec = project.stages[StageName.MERGE]
            if rec.status == StageStatus.NOT_RUN:
                rec.status = StageStatus.DONE
            rec.artifacts = {
                "merged_dir": rel_path(legacy_dir, self.root),
                "mixed": rel_path(legacy_mixed, self.root),
                "legacy_flat": True,
            }
            legacy_vocals = legacy_dir / "vocals.flac"
            if legacy_vocals.is_file():
                rec.artifacts["vocals"] = rel_path(legacy_vocals, self.root)

        return project

    def validate_stage_inputs(self, stage: StageName, inputs: dict) -> tuple[bool, list[str]]:
        """Hard gate: required files/params for this run."""
        errors: list[str] = []

        if stage == StageName.SEPARATE:
            if not _path_exists(inputs.get("mix_audio"), self.root):
                errors.append("mix_audio: 混音文件路径不存在")

        elif stage == StageName.SLICE:
            if not _path_exists(inputs.get("vocals"), self.root):
                errors.append("vocals: 人声音轨路径不存在")
            mode = inputs.get("mode", SliceMode.VAD.value)
            if mode == SliceMode.LRC.value and not _path_exists(inputs.get("lrc"), self.root):
                errors.append("lrc: LRC 模式需要歌词文件")

        elif stage == StageName.CONVERT:
            mode = inputs.get("mode", ConvertMode.SLICE_BATCH.value)
            if not _path_exists(inputs.get("reference"), self.root):
                errors.append("reference: 参考音频路径不存在")
            if mode == ConvertMode.FULL_TRACK.value:
                if not _path_exists(inputs.get("source_vocals"), self.root):
                    errors.append("source_vocals: 整段模式需要源人声文件")
            else:
                manifest_ok = _path_exists(inputs.get("manifest"), self.root)
                slices_dir_val = inputs.get("slices_dir")
                slices_ok = False
                if slices_dir_val:
                    p = _abs_from_input(self.root, slices_dir_val)
                    slices_ok = p is not None and p.is_dir() and _dir_has_audio(p)
                if not manifest_ok and not slices_ok:
                    errors.append("slices_dir/manifest: 切片批量模式需要切片目录或 manifest.json")

        elif stage == StageName.MERGE:
            vocals_val = inputs.get("vocals")
            if not _path_exists(vocals_val, self.root):
                errors.append("vocals: 人声音轨路径不存在")
            elif vocals_val:
                p = _abs_from_input(self.root, vocals_val)
                if p is not None and p.is_dir() and not _dir_has_audio(p):
                    errors.append("vocals: 人声目录内无音频文件")
                elif p is not None and p.is_file() and p.suffix.lower() not in {
                    ".flac",
                    ".wav",
                    ".mp3",
                    ".ogg",
                }:
                    errors.append("vocals: 人声路径不是支持的音频文件")
            if not _path_exists(inputs.get("instrumental"), self.root):
                errors.append("instrumental: 伴奏轨路径不存在")

        return (len(errors) == 0, errors)

    def resolve_stage_inputs(
        self,
        project_id: str,
        stage: StageName,
        overrides: dict | None = None,
    ) -> dict[str, Any]:
        """Resolve inputs per priority: overrides > saved inputs > artifacts > glob."""
        project = self.get_project(project_id)
        record = project.stages[stage]
        resolved: dict[str, Any] = dict(record.inputs)
        if overrides:
            for key, value in overrides.items():
                if value is not None and value != "":
                    resolved[key] = value

        pid = project_id

        if stage == StageName.SEPARATE:
            if not resolved.get("mix_audio"):
                audio = paths.input_audio_path(pid)
                if audio:
                    resolved["mix_audio"] = rel_path(audio, self.root)
                elif project.input_audio:
                    resolved["mix_audio"] = project.input_audio

        elif stage == StageName.SLICE:
            if not resolved.get("vocals"):
                art_vocals = record.artifacts.get("vocals") or project.stages[StageName.SEPARATE].artifacts.get(
                    "vocals"
                )
                if art_vocals and _path_exists(art_vocals, self.root):
                    resolved["vocals"] = art_vocals
                else:
                    vocals = paths.separated_vocals_path(pid)
                    if vocals:
                        resolved["vocals"] = rel_path(vocals, self.root)
            if not resolved.get("lrc"):
                lrc = paths.input_lrc_path(pid)
                if lrc:
                    resolved["lrc"] = rel_path(lrc, self.root)
                elif project.input_lrc:
                    resolved["lrc"] = project.input_lrc
            if not resolved.get("mode"):
                resolved["mode"] = (
                    SliceMode.LRC.value if resolved.get("lrc") and _path_exists(resolved.get("lrc"), self.root) else SliceMode.VAD.value
                )
            slice_mode = paths.normalize_slice_mode(resolved.get("mode"))
            resolved.setdefault("output_dir", rel_path(paths.slices_mode_dir(pid, slice_mode), self.root))

        elif stage == StageName.CONVERT:
            mode = resolved.get("mode", ConvertMode.SLICE_BATCH.value)
            slice_mode = self._active_slice_mode(project, overrides)
            if not resolved.get("reference"):
                ref = paths.project_reference_path(pid)
                if ref:
                    resolved["reference"] = rel_path(ref, self.root)
            if mode == ConvertMode.FULL_TRACK.value:
                if not resolved.get("source_vocals"):
                    art = record.artifacts.get("full_track")
                    sep_vocals = project.stages[StageName.SEPARATE].artifacts.get("vocals")
                    for candidate in (art, sep_vocals):
                        if candidate and _path_exists(candidate, self.root):
                            resolved["source_vocals"] = candidate
                            break
                    if not resolved.get("source_vocals"):
                        vocals = paths.separated_vocals_path(pid)
                        if vocals:
                            resolved["source_vocals"] = rel_path(vocals, self.root)
                resolved.setdefault("output_path", rel_path(paths.converted_full_track_path(pid), self.root))
            else:
                slice_art = project.stages[StageName.SLICE].artifacts.get(slice_mode)
                if isinstance(slice_art, dict):
                    if not resolved.get("slices_dir") and slice_art.get("slices_dir"):
                        resolved["slices_dir"] = slice_art["slices_dir"]
                    if not resolved.get("manifest") and slice_art.get("manifest"):
                        resolved["manifest"] = slice_art["manifest"]
                if not resolved.get("slices_dir") or not _path_exists(resolved.get("slices_dir"), self.root):
                    mode_dir = paths.resolve_slices_mode_dir(pid, slice_mode)
                    if mode_dir:
                        resolved["slices_dir"] = rel_path(mode_dir, self.root)
                    elif paths.slices_dir(pid).is_dir():
                        resolved["slices_dir"] = rel_path(paths.slices_dir(pid), self.root)
                if not resolved.get("manifest") or not _path_exists(resolved.get("manifest"), self.root):
                    manifest = paths.slices_manifest_path(pid, slice_mode)
                    if manifest.is_file():
                        resolved["manifest"] = rel_path(manifest, self.root)
                resolved.setdefault("output_dir", rel_path(paths.converted_mode_dir(pid, slice_mode), self.root))
                resolved["slice_mode"] = slice_mode
                resolved["active_slice_mode"] = slice_mode

        elif stage == StageName.MERGE:
            merge_mode = overrides.get("merge_mode", "whole_track") if overrides else "whole_track"
            slice_mode = self._active_slice_mode(project, overrides)
            if overrides and overrides.get("merge_mode"):
                vocals_saved = resolved.get("vocals")
                if vocals_saved:
                    vpath = _abs_from_input(self.root, vocals_saved)
                    if vpath:
                        if merge_mode == "slice_stitch" and vpath.is_file():
                            resolved.pop("vocals", None)
                        elif merge_mode == "whole_track" and vpath.is_dir():
                            resolved.pop("vocals", None)
            if not resolved.get("vocals"):
                convert_art = project.stages[StageName.CONVERT].artifacts
                if merge_mode == "slice_stitch":
                    mode_art = convert_art.get(slice_mode)
                    cdir = mode_art.get("converted_dir") if isinstance(mode_art, dict) else None
                    if not cdir:
                        cdir = convert_art.get("converted_dir")
                    if cdir and _path_exists(cdir, self.root):
                        cpath = _abs_from_input(self.root, cdir)
                        if cpath and cpath.is_dir():
                            resolved["vocals"] = cdir
                    if not resolved.get("vocals"):
                        slices = paths.resolve_converted_mode_dir(pid, slice_mode) or paths.resolve_converted_slices_dir(pid)
                        if slices:
                            resolved["vocals"] = rel_path(slices, self.root)
                    if not resolved.get("vocals"):
                        full = paths.resolve_converted_full_track(pid)
                        if full:
                            resolved["vocals"] = rel_path(full, self.root)
                else:
                    full = convert_art.get("full_track")
                    cdir = convert_art.get("converted_dir")
                    for candidate in (full, cdir):
                        if candidate and _path_exists(candidate, self.root):
                            cpath = _abs_from_input(self.root, candidate)
                            if cpath and cpath.is_file():
                                resolved["vocals"] = candidate
                                break
                    if not resolved.get("vocals"):
                        full = paths.resolve_converted_full_track(pid)
                        if full:
                            resolved["vocals"] = rel_path(full, self.root)
                        else:
                            slices = paths.resolve_converted_slices_dir(pid)
                            if slices:
                                resolved["vocals"] = rel_path(slices, self.root)
            if not resolved.get("instrumental"):
                art_inst = project.stages[StageName.SEPARATE].artifacts.get("instrumental")
                if art_inst and _path_exists(art_inst, self.root):
                    resolved["instrumental"] = art_inst
                else:
                    inst = paths.separated_instrumental_path(pid)
                    if inst:
                        resolved["instrumental"] = rel_path(inst, self.root)
            if not resolved.get("reference"):
                audio = paths.input_audio_path(pid)
                if audio:
                    resolved["reference"] = rel_path(audio, self.root)
                elif project.input_audio:
                    resolved["reference"] = project.input_audio
            if not resolved.get("original_vocals"):
                sep_vocals = project.stages[StageName.SEPARATE].artifacts.get("vocals")
                if sep_vocals and _path_exists(sep_vocals, self.root):
                    resolved["original_vocals"] = sep_vocals
                else:
                    vocals = paths.separated_vocals_path(pid)
                    if vocals:
                        resolved["original_vocals"] = rel_path(vocals, self.root)
            if not resolved.get("manifest") or not _path_exists(resolved.get("manifest"), self.root):
                manifest = paths.slices_manifest_path(pid, slice_mode)
                if manifest.is_file():
                    resolved["manifest"] = rel_path(manifest, self.root)
            if not resolved.get("slices_dir") or not _slices_dir_usable(resolved.get("slices_dir"), self.root):
                mode_dir = paths.resolve_slices_mode_dir(pid, slice_mode)
                if mode_dir:
                    resolved["slices_dir"] = rel_path(mode_dir, self.root)
                elif paths.slices_dir(pid).is_dir():
                    resolved["slices_dir"] = rel_path(paths.slices_dir(pid), self.root)
            resolved.setdefault("output_dir", rel_path(paths.merged_mode_dir(pid, slice_mode), self.root))
            resolved["slice_mode"] = slice_mode
            resolved["active_slice_mode"] = slice_mode

        return resolved

    def suggest_next_stage(self, project_id: str) -> StageName | None:
        """Soft recommendation based on existing artifacts (UI hint only)."""
        project = self.get_project(project_id)
        has_input = bool(project.input_audio and _path_exists(project.input_audio, self.root))
        has_sep = bool(paths.separated_vocals_path(project_id))
        has_slices = any(
            paths.resolve_slices_mode_dir(project_id, mode) for mode in paths.SLICE_MODES
        ) or (paths.slices_dir(project_id).is_dir() and _dir_has_audio(paths.slices_dir(project_id)))
        has_convert = paths.has_converted_artifacts(project_id)
        has_merge = paths.has_per_project_merged(project_id) or (
            paths.legacy_flat_merged_mixed().is_file()
            and self._legacy_merge_eligible(project_id, {p.id for p in self.list_projects()} | {project_id})
        )

        if has_merge:
            return None
        if has_convert:
            return StageName.MERGE
        if has_slices:
            return StageName.CONVERT
        if has_sep:
            return StageName.SLICE
        if has_input:
            return StageName.SEPARATE
        return None

    def validate_pipeline_chain(
        self,
        project_id: str,
        stages: list[StageName],
        **pipeline_params: Any,
    ) -> tuple[bool, dict[str, dict] | list[str]]:
        """Pre-flight: resolve + validate each stage in the chain."""
        plan: dict[str, dict] = {}
        all_errors: list[str] = []

        convert_mode = pipeline_params.get("convert_mode", ConvertMode.SLICE_BATCH)
        slice_mode = pipeline_params.get("slice_mode", SliceMode.LRC)

        for stage in stages:
            overrides: dict[str, Any] = {}
            if stage == StageName.CONVERT:
                cm = convert_mode.value if isinstance(convert_mode, ConvertMode) else convert_mode
                overrides["mode"] = cm
                if cm != ConvertMode.FULL_TRACK.value:
                    sm = slice_mode.value if isinstance(slice_mode, SliceMode) else slice_mode
                    overrides["slice_mode"] = sm
                    overrides["active_slice_mode"] = sm
            if stage == StageName.SLICE:
                overrides["mode"] = (
                    slice_mode.value if isinstance(slice_mode, SliceMode) else slice_mode
                )
            for key in ("reference", "profile", "merge_profile"):
                if key in pipeline_params and pipeline_params[key]:
                    overrides[key] = pipeline_params[key]

            inputs = self.resolve_stage_inputs(project_id, stage, overrides)
            ok, errors = self.validate_stage_inputs(stage, inputs)
            plan[stage.value] = inputs
            if not ok:
                all_errors.extend(f"[{stage.value}] {e}" for e in errors)

        if all_errors:
            return False, all_errors
        return True, plan
