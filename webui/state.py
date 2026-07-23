"""Bridge between Gradio UI and pipeline orchestration kernel."""

from __future__ import annotations

import threading
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline import paths
from pipeline.models import ConvertMode, SliceMode, StageName
from pipeline.stage_params import collect_params, merge_stage_params, merge_wizard_params
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

_store = ProjectStore()
_gpu_queue = GpuJobQueue()
_runner = StageRunner(_store, _gpu_queue)

_batch_lock = threading.Lock()
_batch_items: list[dict[str, Any]] = []
_batch_running = False


@dataclass
class BatchItem:
    project_id: str
    stages: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    error: str | None = None


def get_store() -> ProjectStore:
    return _store


def get_runner() -> StageRunner:
    return _runner


def refresh_projects() -> list[dict]:
    _store.scan_and_repair()
    return [p.to_summary() for p in _store.list_projects()]


def get_projects() -> list[dict]:
    return [p.to_summary() for p in _store.list_projects()]


def create_project_ui(
    project_id: str,
    audio_upload: str | None,
    lrc_upload: str | None,
    display_name: str | None,
) -> tuple[bool, str]:
    pid = (project_id or "").strip()
    if not pid:
        return False, "请填写项目 ID"
    if not audio_upload:
        return False, "请上传混音文件"
    try:
        project = _store.create_project(
            pid,
            Path(audio_upload),
            Path(lrc_upload) if lrc_upload else None,
            display_name=display_name.strip() if display_name else None,
        )
        return True, f"已创建项目：{project.display_name}"
    except Exception as exc:  # noqa: BLE001 - UI boundary
        return False, str(exc)


def load_saved_stage_params(
    project_id: str | None,
    stage: str,
    *,
    wizard_only: bool = False,
) -> dict[str, Any]:
    saved: dict[str, Any] = {}
    if project_id:
        try:
            project = _store.get_project(project_id)
            saved = dict(project.stages[StageName(stage)].params)
        except KeyError:
            pass
    return merge_stage_params(stage, saved, wizard_only=wizard_only)


def load_wizard_params(project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return merge_wizard_params(None)
    try:
        project = _store.get_project(project_id)
        saved = {name.value: dict(project.stages[name].params) for name in StageName}
    except KeyError:
        return merge_wizard_params(None)
    return merge_wizard_params(saved)


def load_project_defaults(project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return {}
    try:
        project = _store.get_project(project_id)
    except KeyError:
        return {}

    sep = project.stages[StageName.SEPARATE]
    sl = project.stages[StageName.SLICE]
    cv = project.stages[StageName.CONVERT]
    mg = project.stages[StageName.MERGE]

    resolved_slice = _store.resolve_stage_inputs(project_id, StageName.SLICE)
    resolved_convert = _store.resolve_stage_inputs(project_id, StageName.CONVERT)
    resolved_merge = _store.resolve_stage_inputs(project_id, StageName.MERGE)
    resolved_sep = _store.resolve_stage_inputs(project_id, StageName.SEPARATE)

    has_lrc = bool(project.input_lrc or paths.input_lrc_path(project_id))
    return {
        "display_name": project.display_name,
        "input_audio": project.input_audio,
        "input_lrc": project.input_lrc,
        "mix_audio": resolved_sep.get("mix_audio", ""),
        "vocals_path": resolved_slice.get("vocals", sep.artifacts.get("vocals", "")),
        "lrc_path": resolved_slice.get("lrc", project.input_lrc or ""),
        "slice_mode": resolved_slice.get("mode", SliceMode.LRC.value if has_lrc else SliceMode.VAD.value),
        "convert_mode": cv.params.get("mode", ConvertMode.SLICE_BATCH.value),
        "reference": resolved_convert.get("reference", ""),
        "slices_dir": resolved_slice.get("slices_dir", sl.artifacts.get("slices_dir", "")),
        "manifest": sl.artifacts.get("manifest", ""),
        "merge_vocals": resolved_merge.get("vocals", ""),
        "merge_instrumental": resolved_merge.get("instrumental", ""),
        "merge_reference": resolved_merge.get("reference", project.input_audio or ""),
        "merge_profile": mg.params.get("profile", "full"),
        "stage_status_text": _stage_status_line(project_id),
        "stage_params": {
            name.value: load_saved_stage_params(project_id, name.value)
            for name in StageName
        },
        "wizard_params": load_wizard_params(project_id),
    }


def _stage_status_line(project_id: str) -> str:
    from webui.helpers import format_stage_icons

    project = _store.get_project(project_id)
    return format_stage_icons({k.value: v.status.value for k, v in project.stages.items()})


def run_stage_ui(
    project_id: str | None,
    stage: str,
    params: dict | None = None,
) -> Generator[tuple[str, str], None, None]:
    """Yield (log_text, status_message) for Gradio."""
    if not project_id:
        yield "", "请先选择项目"
        return

    log_lines: list[str] = []
    final_status = "运行中..."

    for event in _runner.run_stage_async(project_id, stage, params or {}):
        if event.get("done"):
            if event.get("success"):
                final_status = "阶段完成"
                if event.get("artifacts"):
                    final_status += f" — {event['artifacts']}"
            else:
                final_status = f"失败：{event.get('error', 'unknown')}"
            yield "\n".join(log_lines), final_status
            return
        msg = event.get("message") or event.get("log_line") or ""
        if msg:
            log_lines.append(msg)
        pct = event.get("percent")
        if pct is not None:
            log_lines.append(f"[{pct:.0f}%] {msg}")
        yield "\n".join(log_lines[-80:]), final_status


def run_pipeline_ui(
    project_id: str | None,
    *,
    stages: list[StageName] | None = None,
    convert_mode: str = ConvertMode.SLICE_BATCH.value,
    slice_mode: str = SliceMode.LRC.value,
    params: dict | None = None,
    from_stage: StageName | None = None,
) -> Generator[tuple[str, str], None, None]:
    if not project_id:
        yield "", "请先选择项目"
        return

    chain = list(stages or StageName)
    if from_stage is not None:
        try:
            start = chain.index(from_stage)
            chain = chain[start:]
        except ValueError:
            pass

    extra = dict(params or {})
    all_logs: list[str] = []

    for stage in chain:
        stage_params = dict(extra)
        if stage == StageName.SLICE:
            stage_params.setdefault("mode", slice_mode)
        if stage == StageName.CONVERT:
            stage_params.setdefault("mode", convert_mode)

        for log, status in run_stage_ui(project_id, stage.value, stage_params):
            all_logs = log.split("\n") if log else all_logs
            yield "\n".join(all_logs), f"[{stage.value}] {status}"


def enqueue_batch(
    project_ids: list[str],
    stages: list[str],
    params: dict | None = None,
) -> str:
    global _batch_items
    if not project_ids:
        return "请至少选择一个项目"
    if not stages:
        return "请至少选择一个阶段"

    with _batch_lock:
        for pid in project_ids:
            _batch_items.append(
                {
                    "project_id": pid,
                    "stages": list(stages),
                    "params": dict(params or {}),
                    "status": "queued",
                    "error": None,
                }
            )
    return f"已加入队列：{len(project_ids)} 个项目"


def batch_queue_status() -> str:
    with _batch_lock:
        if not _batch_items:
            return "队列为空"
        lines = []
        for i, item in enumerate(_batch_items, 1):
            stages = ",".join(item["stages"])
            lines.append(f"{i}. {item['project_id']} [{stages}] — {item['status']}")
        return "\n".join(lines)


def clear_batch_queue() -> str:
    global _batch_items
    with _batch_lock:
        _batch_items = [item for item in _batch_items if item["status"] == "running"]
    return batch_queue_status()


def run_batch_queue_ui(
    convert_mode: str,
    slice_mode: str,
    merge_profile: str,
) -> Generator[tuple[str, str], None, None]:
    global _batch_running
    with _batch_lock:
        if _batch_running:
            yield batch_queue_status(), "队列正在执行中"
            return
        _batch_running = True

    try:
        while True:
            with _batch_lock:
                pending = next((item for item in _batch_items if item["status"] == "queued"), None)
            if pending is None:
                yield batch_queue_status(), "队列执行完毕"
                break

            pending["status"] = "running"
            yield batch_queue_status(), f"正在处理 {pending['project_id']}..."

            stage_enums = [StageName(s) for s in pending["stages"]]
            params = dict(pending.get("params") or {})
            params.setdefault("profile", merge_profile)

            result = _runner.run_pipeline(
                pending["project_id"],
                stages=stage_enums,
                convert_mode=ConvertMode(convert_mode),
                slice_mode=SliceMode(slice_mode),
                **params,
            )
            pending["status"] = "completed" if result.success else "failed"
            pending["error"] = result.error
            yield batch_queue_status(), (
                f"{pending['project_id']} 完成" if result.success else f"{pending['project_id']} 失败"
            )
    finally:
        with _batch_lock:
            _batch_running = False
