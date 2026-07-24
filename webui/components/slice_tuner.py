"""Slice fine-tuning panel for the convert stage."""

from __future__ import annotations

import json
from dataclasses import dataclass

import gradio as gr

from pipeline import paths
from pipeline.models import StageName
from pipeline.slice_overrides import (
    apply_slice_override,
    clear_orphans,
    clear_slice_overrides,
    load as load_overrides,
    save as save_overrides,
)
from pipeline.stage_params import collect_params
from webui import state
from webui.components.stage_params import StageParamPanel, build_stage_param_panel
from webui.helpers import audio_if_exists, save_reference_audio


@dataclass
class SliceTunerBundle:
    slice_mode: gr.State
    slice_checks: gr.CheckboxGroup
    source_audio: gr.Audio
    converted_audio: gr.Audio
    tune_ref: gr.Audio
    tune_params: StageParamPanel
    orphans_view: gr.Textbox
    save_btn: gr.Button
    retune_btn: gr.Button
    clear_btn: gr.Button
    clear_orphans_btn: gr.Button
    status: gr.Markdown
    log: gr.Textbox


def _manifest_entries(project_id: str | None, slice_mode: str) -> list[dict]:
    if not project_id:
        return []
    manifest_path = paths.slices_manifest_path(project_id, slice_mode)
    if not manifest_path.is_file():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(data.get("slices") or [])


def _choice_label(item: dict, overrides_path) -> str:
    overrides = load_overrides(overrides_path)
    tuned = " [精修]" if item.get("id") in overrides.slices else ""
    text = item.get("text")
    text_part = f' "{text}"' if text else ""
    return f"{item.get('id')} | {item.get('start_ms')}-{item.get('end_ms')}ms{text_part}{tuned}"


def slice_choices(project_id: str | None, slice_mode: str) -> list[str]:
    if not project_id:
        return []
    overrides_path = paths.slices_overrides_path(project_id, slice_mode)
    return [_choice_label(item, overrides_path) for item in _manifest_entries(project_id, slice_mode)]


def _ids_from_labels(labels: list[str]) -> list[str]:
    return [label.split(" | ", 1)[0] for label in labels if label]


def _first_selected_path(project_id: str, slice_mode: str, slice_id: str, *, converted: bool) -> str | None:
    entries = _manifest_entries(project_id, slice_mode)
    item = next((entry for entry in entries if entry.get("id") == slice_id), None)
    if not item:
        return None
    file_name = str(item.get("file", ""))
    if converted:
        base = paths.resolve_converted_mode_dir(project_id, slice_mode) or paths.converted_mode_dir(
            project_id, slice_mode
        )
    else:
        base = paths.resolve_slices_mode_dir(project_id, slice_mode) or paths.slices_mode_dir(
            project_id, slice_mode
        )
    candidate = base / file_name
    return str(candidate) if candidate.is_file() else None


def build_slice_tuner() -> SliceTunerBundle:
    gr.Markdown(
        "对选中切片保存 per-slice 转换参数（含参考音色），并仅重转选中片。"
        " 当前模式与「切片」Tab 的 LRC/VAD 选择一致。"
    )
    slice_mode = gr.State("lrc")
    slice_checks = gr.CheckboxGroup(choices=[], label="切片列表", value=[])
    with gr.Row():
        source_audio = gr.Audio(label="原始切片", type="filepath", interactive=False)
        converted_audio = gr.Audio(label="转换结果", type="filepath", interactive=False)
    tune_ref = gr.Audio(label="参考音频（可覆盖项目默认）", type="filepath")
    tune_params = build_stage_param_panel(
        StageName.CONVERT,
        keys={
            "diffusion_steps",
            "length_adjust",
            "inference_cfg_rate",
            "auto_f0_adjust",
            "semi_tone_shift",
            "fp16",
        },
        accordion_label="精修参数",
        open=True,
    )
    orphans_view = gr.Textbox(label="未匹配 overrides (orphans)", lines=3, interactive=False)
    with gr.Row():
        save_btn = gr.Button("保存为覆盖")
        retune_btn = gr.Button("重转选中片", variant="primary")
        clear_btn = gr.Button("清除选中覆盖")
        clear_orphans_btn = gr.Button("清除 orphans")
    tune_log = gr.Textbox(label="日志", lines=6)
    tune_status = gr.Markdown("")
    return SliceTunerBundle(
        slice_mode=slice_mode,
        slice_checks=slice_checks,
        source_audio=source_audio,
        converted_audio=converted_audio,
        tune_ref=tune_ref,
        tune_params=tune_params,
        orphans_view=orphans_view,
        save_btn=save_btn,
        retune_btn=retune_btn,
        clear_btn=clear_btn,
        clear_orphans_btn=clear_orphans_btn,
        status=tune_status,
        log=tune_log,
    )


def wire_slice_tuner(
    bundle: SliceTunerBundle,
    project_state: gr.State,
    global_slice_mode: gr.State,
) -> None:
    def _refresh(pid, smode):
        smode = smode or "lrc"
        choices = slice_choices(pid, smode)
        overrides_path = paths.slices_overrides_path(pid, smode) if pid else None
        orphans_text = ""
        if overrides_path and overrides_path.is_file():
            orphans = load_overrides(overrides_path).orphans
            orphans_text = json.dumps(orphans, ensure_ascii=False, indent=2) if orphans else ""
        return (
            smode,
            gr.CheckboxGroup(choices=choices, value=[]),
            None,
            None,
            orphans_text,
        )

    def _on_select(pid, smode, selected_labels):
        ids = _ids_from_labels(list(selected_labels or []))
        if not pid or not ids:
            return None, None
        first = ids[0]
        return (
            audio_if_exists(_first_selected_path(pid, smode, first, converted=False)),
            audio_if_exists(_first_selected_path(pid, smode, first, converted=True)),
        )

    def _save(pid, smode, selected_labels, ref, *param_values):
        ids = _ids_from_labels(list(selected_labels or []))
        if not pid:
            return "请先选择项目", ""
        if not ids:
            return "请选择至少一个切片", ""
        overrides_path = paths.slices_overrides_path(pid, smode)
        current = load_overrides(overrides_path)
        values = bundle.tune_params.values_to_dict(*param_values)
        if ref:
            values["reference"] = save_reference_audio(pid, ref) or ref
        updated = apply_slice_override(current, ids, values)
        save_overrides(overrides_path, updated)
        return f"已保存 {len(ids)} 个切片的覆盖参数", ""

    def _retune(pid, smode, selected_labels, ref, *param_values):
        ids = _ids_from_labels(list(selected_labels or []))
        if not pid:
            yield "请先选择项目", ""
            return
        if not ids:
            yield "请选择至少一个切片", ""
            return
        overrides_path = paths.slices_overrides_path(pid, smode)
        current = load_overrides(overrides_path)
        values = bundle.tune_params.values_to_dict(*param_values)
        if ref:
            values["reference"] = save_reference_audio(pid, ref) or ref
        updated = apply_slice_override(current, ids, values)
        save_overrides(overrides_path, updated)

        params = collect_params(StageName.CONVERT.value, values, convert_mode="slice_batch")
        params.update(
            {
                "mode": "slice_batch",
                "slice_mode": smode,
                "active_slice_mode": smode,
                "slice_ids": ids,
                "skip_existing": False,
            }
        )
        if ref:
            params["reference"] = save_reference_audio(pid, ref) or ref
        yield f"重转 {len(ids)} 个切片...", ""
        for log, status in state.run_stage_ui(pid, StageName.CONVERT.value, params):
            yield log, status

    def _clear(pid, smode, selected_labels):
        ids = _ids_from_labels(list(selected_labels or []))
        if not pid or not ids:
            return "请选择切片", ""
        overrides_path = paths.slices_overrides_path(pid, smode)
        current = load_overrides(overrides_path)
        updated = clear_slice_overrides(current, ids)
        save_overrides(overrides_path, updated)
        return f"已清除 {len(ids)} 个切片的覆盖", ""

    def _clear_orphans(pid, smode):
        if not pid:
            return "请先选择项目", ""
        overrides_path = paths.slices_overrides_path(pid, smode)
        current = load_overrides(overrides_path)
        updated = clear_orphans(current)
        save_overrides(overrides_path, updated)
        return "已清除 orphans", ""

    project_state.change(
        _refresh,
        inputs=[project_state, global_slice_mode],
        outputs=[
            bundle.slice_mode,
            bundle.slice_checks,
            bundle.source_audio,
            bundle.converted_audio,
            bundle.orphans_view,
        ],
    )
    global_slice_mode.change(
        _refresh,
        inputs=[project_state, global_slice_mode],
        outputs=[
            bundle.slice_mode,
            bundle.slice_checks,
            bundle.source_audio,
            bundle.converted_audio,
            bundle.orphans_view,
        ],
    )
    bundle.slice_checks.change(
        _on_select,
        inputs=[project_state, global_slice_mode, bundle.slice_checks],
        outputs=[bundle.source_audio, bundle.converted_audio],
    )
    bundle.save_btn.click(
        _save,
        inputs=[
            project_state,
            global_slice_mode,
            bundle.slice_checks,
            bundle.tune_ref,
            *bundle.tune_params.input_components(),
        ],
        outputs=[bundle.status, bundle.log],
    )
    bundle.retune_btn.click(
        _retune,
        inputs=[
            project_state,
            global_slice_mode,
            bundle.slice_checks,
            bundle.tune_ref,
            *bundle.tune_params.input_components(),
        ],
        outputs=[bundle.log, bundle.status],
    )
    bundle.clear_btn.click(
        _clear,
        inputs=[project_state, global_slice_mode, bundle.slice_checks],
        outputs=[bundle.status, bundle.log],
    )
    bundle.clear_orphans_btn.click(
        _clear_orphans,
        inputs=[project_state, global_slice_mode],
        outputs=[bundle.status, bundle.log],
    )
