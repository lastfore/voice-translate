"""Project + stage orchestration business logic — migrated from webui/state.py.

Differences from the Gradio-era ``webui/state.py``:

- No ``*_ui()`` naming, no ``(ok, message)`` tuples or Markdown strings meant
  for direct display — functions return structured dicts/dataclasses or raise
  a domain exception that the router layer translates into an HTTP error.
- Long-running stage execution (``run_stage`` / ``run_pipeline``) is *not*
  wrapped here — routers call ``pipeline.runner.StageRunner`` directly inside
  ``anyio.to_thread.run_sync`` so the thread/async boundary (docs §4.4) stays
  visible at the call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.models import ConvertMode, SliceMode, StageName
from pipeline.stage_params import merge_stage_params, merge_wizard_params
from pipeline.store import ProjectStore

from api.services.media_service import media_url_for, split_vocals_paths


def _resolve_merged_mixed_path(merge_artifacts: dict[str, Any], active_slice_mode: str) -> str | None:
    """Pick mixed.flac from per-mode merge artifacts, with legacy top-level fallback."""
    if not merge_artifacts:
        return None
    mode_art = merge_artifacts.get(active_slice_mode)
    if isinstance(mode_art, dict) and mode_art.get("mixed"):
        return str(mode_art["mixed"])
    top = merge_artifacts.get("mixed")
    if top:
        return str(top)
    for mode in paths.SLICE_MODES:
        nested = merge_artifacts.get(mode)
        if isinstance(nested, dict) and nested.get("mixed"):
            return str(nested["mixed"])
    return None


class PipelineServiceError(Exception):
    """Base class for pipeline_service domain errors."""


class ProjectNotFoundError(PipelineServiceError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"project not found: {project_id}")
        self.project_id = project_id


class InvalidProjectError(PipelineServiceError):
    """Bad input while creating/mutating a project (maps to HTTP 400)."""


class ProjectExistsError(PipelineServiceError):
    """Project id already exists (maps to HTTP 409)."""


class ProjectBusyError(PipelineServiceError):
    """A stage is currently RUNNING, refuse the mutation (maps to HTTP 409)."""


def list_projects(store: ProjectStore, *, refresh: bool = False) -> list[dict[str, Any]]:
    """Return project summaries. ``refresh=True`` re-scans output/ for orphaned artifacts."""
    if refresh:
        store.scan_and_repair()
    return [p.to_summary() for p in store.list_projects()]


def create_project(
    store: ProjectStore,
    project_id: str,
    audio_path: Path,
    lrc_path: Path | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    pid = (project_id or "").strip()
    if not pid:
        raise InvalidProjectError("project_id is required")
    if audio_path is None:
        raise InvalidProjectError("audio file is required")

    try:
        project = store.create_project(
            pid,
            audio_path,
            lrc_path,
            display_name=display_name.strip() if display_name else None,
        )
    except ValueError as exc:
        # ProjectStore.create_project raises ValueError both for bad ids and
        # for "already exists" — the message text is the only differentiator.
        if "already exists" in str(exc):
            raise ProjectExistsError(str(exc)) from exc
        raise InvalidProjectError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise InvalidProjectError(str(exc)) from exc
    return project.to_summary()


def get_project(store: ProjectStore, project_id: str) -> dict[str, Any]:
    try:
        project = store.get_project(project_id)
    except KeyError as exc:
        raise ProjectNotFoundError(project_id) from exc
    return project.to_summary()


def delete_preview(store: ProjectStore, project_id: str, scope: str) -> list[dict[str, str]]:
    normalized = scope if scope in ("metadata", "artifacts", "all") else "metadata"
    rows = store.preview_project_deletion(project_id, normalized)  # type: ignore[arg-type]
    return [{"kind": kind, "path": rel} for kind, rel in rows]


def delete_project(
    store: ProjectStore,
    project_id: str,
    scope: str,
    *,
    confirmed: bool,
) -> dict[str, Any]:
    pid = (project_id or "").strip()
    if not pid:
        raise InvalidProjectError("project_id is required")
    if not confirmed:
        raise InvalidProjectError("deletion requires confirmed=true")

    normalized = scope if scope in ("metadata", "artifacts", "all") else "metadata"
    try:
        project = store.get_project(pid)
    except KeyError:
        project = None
    if project is not None:
        from pipeline.models import StageStatus

        for record in project.stages.values():
            if record.status == StageStatus.RUNNING:
                raise ProjectBusyError(f"project {pid} has a stage still running")

    deleted = store.delete_project(pid, scope=normalized)  # type: ignore[arg-type]
    if not deleted:
        raise ProjectNotFoundError(pid)
    return {"project_id": pid, "scope": normalized, "deleted": deleted}


def load_saved_stage_params(
    store: ProjectStore,
    project_id: str | None,
    stage: str,
    *,
    wizard_only: bool = False,
) -> dict[str, Any]:
    saved: dict[str, Any] = {}
    if project_id:
        try:
            project = store.get_project(project_id)
            saved = dict(project.stages[StageName(stage)].params)
        except KeyError:
            pass
    return merge_stage_params(stage, saved, wizard_only=wizard_only)


def load_wizard_params(store: ProjectStore, project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return merge_wizard_params(None)
    try:
        project = store.get_project(project_id)
        saved = {name.value: dict(project.stages[name].params) for name in StageName}
    except KeyError:
        return merge_wizard_params(None)
    return merge_wizard_params(saved)


def get_project_defaults(store: ProjectStore, project_id: str) -> dict[str, Any]:
    """Structured equivalent of ``webui.state.load_project_defaults``.

    Raises :class:`ProjectNotFoundError` instead of returning ``{}`` — the
    router layer maps that to HTTP 404.
    """
    try:
        project = store.get_project(project_id)
    except KeyError as exc:
        raise ProjectNotFoundError(project_id) from exc

    sep = project.stages[StageName.SEPARATE]
    sl = project.stages[StageName.SLICE]
    cv = project.stages[StageName.CONVERT]
    mg = project.stages[StageName.MERGE]

    resolved_sep = store.resolve_stage_inputs(project_id, StageName.SEPARATE)

    active_slice_mode = store._active_slice_mode(project)
    resolved_slice = store.resolve_stage_inputs(project_id, StageName.SLICE, {"mode": active_slice_mode})
    resolved_convert = store.resolve_stage_inputs(
        project_id,
        StageName.CONVERT,
        {"slice_mode": active_slice_mode, "active_slice_mode": active_slice_mode},
    )
    resolved_merge = store.resolve_stage_inputs(
        project_id,
        StageName.MERGE,
        {"merge_mode": "whole_track", "slice_mode": active_slice_mode},
    )
    resolved_merge_slice = store.resolve_stage_inputs(
        project_id,
        StageName.MERGE,
        {"merge_mode": "slice_stitch", "slice_mode": active_slice_mode},
    )
    merge_vocals_file, merge_vocals_dir = split_vocals_paths(resolved_merge.get("vocals", ""))
    _, merge_vocals_dir_slice = split_vocals_paths(resolved_merge_slice.get("vocals", ""))
    if not merge_vocals_dir_slice:
        merge_vocals_dir_slice = resolved_merge_slice.get("vocals", "")

    stage_status = {name.value: project.stages[name].status.value for name in StageName}
    merge_slice_mode = paths.normalize_slice_mode(
        mg.params.get("active_slice_mode") or mg.params.get("slice_mode") or active_slice_mode
    )

    return {
        "display_name": project.display_name,
        "input_audio": project.input_audio,
        "input_lrc": project.input_lrc,
        "mix_audio": resolved_sep.get("mix_audio", ""),
        "vocals_path": resolved_slice.get("vocals", sep.artifacts.get("vocals", "")),
        "lrc_path": resolved_slice.get("lrc", project.input_lrc or ""),
        "slice_mode": active_slice_mode,
        "active_slice_mode": active_slice_mode,
        "convert_mode": cv.params.get("mode", ConvertMode.SLICE_BATCH.value),
        "reference": resolved_convert.get("reference", ""),
        "slices_dir": resolved_convert.get("slices_dir", resolved_slice.get("slices_dir", "")),
        "manifest": (
            resolved_merge_slice.get("manifest")
            or resolved_slice.get("manifest")
            or resolved_convert.get("manifest", sl.artifacts.get("manifest", ""))
        ),
        "merge_vocals_file": merge_vocals_file,
        "merge_vocals_dir": merge_vocals_dir_slice or merge_vocals_dir,
        "merge_instrumental": resolved_merge.get("instrumental", ""),
        "merge_reference": resolved_merge.get("reference", project.input_audio or ""),
        "merge_profile": mg.params.get("profile", "full"),
        "merge_mode": "whole_track",
        "stage_status": stage_status,
        "stage_params": {
            name.value: load_saved_stage_params(store, project_id, name.value) for name in StageName
        },
        "wizard_params": load_wizard_params(store, project_id),
        "artifacts": {
            "sep_vocals": media_url_for(sep.artifacts.get("vocals")),
            "sep_instrumental": media_url_for(sep.artifacts.get("instrumental")),
            "convert_full_track": media_url_for(cv.artifacts.get("full_track")),
            "convert_dir": (
                (cv.artifacts.get(active_slice_mode) or {}).get("converted_dir")
                if isinstance(cv.artifacts.get(active_slice_mode), dict)
                else cv.artifacts.get("converted_dir")
            ),
            "mixed": media_url_for(_resolve_merged_mixed_path(mg.artifacts, merge_slice_mode)),
        },
    }
