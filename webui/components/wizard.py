"""Wizard tab for guided pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass, field

import gradio as gr

from pipeline.models import StageName
from pipeline.stage_params import collect_params
from webui import state
from webui.components.mode_panel import (
    CONVERT_BATCH,
    CONVERT_FULL,
    CONVERT_MODES,
    MERGE_SLICE,
    MERGE_SLICE_HELP,
    MERGE_WHOLE,
    MERGE_WHOLE_HELP,
    SLICE_LRC,
    SLICE_MODES,
    SLICE_TAB_LABELS,
    SLICE_VAD,
    tabs_selected_update,
    wire_mode_tabs,
)
from webui.mode_utils import mode_from_tab_index, tab_index_for_mode
from webui.components.stage_params import StageParamPanel, build_wizard_param_panels
from webui.helpers import audio_if_exists, save_reference_audio


WIZARD_STAGES = [
    ("1. 词曲分离", StageName.SEPARATE),
    ("2. 声乐切片", StageName.SLICE),
    ("3. 歌声转换", StageName.CONVERT),
    ("4. 人声伴奏结合", StageName.MERGE),
]


@dataclass
class WizardBundle:
    wizard_panel: StageParamPanel
    step: gr.Radio
    slice_mode: gr.State
    convert_mode: gr.State
    merge_mode: gr.State
    slice_tab_index: gr.State
    convert_tab_index: gr.State
    merge_tab_index: gr.State
    slice_subtabs: gr.Tabs
    convert_subtabs: gr.Tabs
    merge_subtabs: gr.Tabs
    reference: gr.Audio
    merge_profile: gr.Radio
    run_step_btn: gr.Button
    run_from_btn: gr.Button
    run_all_btn: gr.Button
    log: gr.Textbox
    status: gr.Markdown
    mixed_preview: gr.Audio
    _mode_outputs: list[gr.Component] = field(default_factory=list)

    def field_outputs(self) -> list[gr.Component]:
        return [
            *self._mode_outputs,
            *self.wizard_panel.input_components(),
        ]


def build_wizard(project_state: gr.State) -> WizardBundle:
    step = gr.Radio(
        choices=[label for label, _ in WIZARD_STAGES],
        value=WIZARD_STAGES[0][0],
        label="当前步骤",
    )

    gr.Markdown("### 切片模式")
    slice_mode = gr.State(SLICE_VAD)
    slice_tab_index = gr.State(0)
    with gr.Tabs(selected=0) as slice_subtabs:
        with gr.Tab(SLICE_TAB_LABELS[0], id="wiz_slice_vad") as wiz_slice_vad_tab:
            gr.Markdown("无歌词时按 VAD 自动断句。")
        with gr.Tab(SLICE_TAB_LABELS[1], id="wiz_slice_lrc") as wiz_slice_lrc_tab:
            gr.Markdown("有 LRC 歌词时按歌词时间轴断句。")

    gr.Markdown("### 转换模式")
    convert_mode = gr.State(CONVERT_BATCH)
    convert_tab_index = gr.State(0)
    with gr.Tabs(selected=0) as convert_subtabs:
        with gr.Tab("切片批量", id="wiz_convert_batch") as wiz_convert_batch_tab:
            gr.Markdown("对每个切片批量执行歌声转换（推荐）。")
        with gr.Tab("整轨快捷", id="wiz_convert_full") as wiz_convert_full_tab:
            gr.Markdown("对整段人声一次性转换，产物为 `full.flac`。")

    reference = gr.Audio(label="参考音频", type="filepath")

    gr.Markdown("### 合并模式")
    merge_mode = gr.State(MERGE_WHOLE)
    merge_tab_index = gr.State(0)
    with gr.Tabs(selected=0) as merge_subtabs:
        with gr.Tab("整轨合并", id="wiz_merge_whole") as wiz_merge_whole_tab:
            gr.Markdown(MERGE_WHOLE_HELP)
        with gr.Tab("切片拼接", id="wiz_merge_slice") as wiz_merge_slice_tab:
            gr.Markdown(MERGE_SLICE_HELP)

    merge_profile = gr.Radio(["quick", "balanced", "full"], value="full", label="合并 Profile")

    wizard_panel = build_wizard_param_panels()

    run_step_btn = gr.Button("运行当前步骤", variant="secondary")
    run_from_btn = gr.Button("从此步跑到最后", variant="secondary")
    run_all_btn = gr.Button("一键全流程", variant="primary")

    log = gr.Textbox(label="进度 / 日志", lines=12, max_lines=30)
    status = gr.Markdown("")
    mixed_preview = gr.Audio(label="mixed.flac 试听", type="filepath", interactive=False)

    bundle = WizardBundle(
        wizard_panel=wizard_panel,
        step=step,
        slice_mode=slice_mode,
        convert_mode=convert_mode,
        merge_mode=merge_mode,
        slice_tab_index=slice_tab_index,
        convert_tab_index=convert_tab_index,
        merge_tab_index=merge_tab_index,
        slice_subtabs=slice_subtabs,
        convert_subtabs=convert_subtabs,
        merge_subtabs=merge_subtabs,
        reference=reference,
        merge_profile=merge_profile,
        run_step_btn=run_step_btn,
        run_from_btn=run_from_btn,
        run_all_btn=run_all_btn,
        log=log,
        status=status,
        mixed_preview=mixed_preview,
        _mode_outputs=[
            slice_mode,
            convert_mode,
            merge_mode,
            slice_tab_index,
            convert_tab_index,
            merge_tab_index,
            slice_subtabs,
            convert_subtabs,
            merge_subtabs,
        ],
    )

    wire_mode_tabs(
        [(wiz_slice_vad_tab, SLICE_VAD), (wiz_slice_lrc_tab, SLICE_LRC)],
        slice_mode,
        tabs=slice_subtabs,
        index_state=slice_tab_index,
    )
    wire_mode_tabs(
        [(wiz_convert_batch_tab, CONVERT_BATCH), (wiz_convert_full_tab, CONVERT_FULL)],
        convert_mode,
        tabs=convert_subtabs,
        index_state=convert_tab_index,
    )
    wire_mode_tabs(
        [(wiz_merge_whole_tab, MERGE_WHOLE), (wiz_merge_slice_tab, MERGE_SLICE)],
        merge_mode,
        tabs=merge_subtabs,
        index_state=merge_tab_index,
    )

    wire_wizard(project_state, bundle)
    return bundle


def wizard_defaults_updates(d: dict) -> list:
    """Return Gradio updates for wizard mode states and sub-tabs."""
    convert_mode = d.get("convert_mode", CONVERT_BATCH)
    slice_mode = d.get("slice_mode", SLICE_VAD)
    return [
        slice_mode,
        convert_mode,
        MERGE_WHOLE,
        tab_index_for_mode(slice_mode, SLICE_MODES),
        tab_index_for_mode(convert_mode, CONVERT_MODES),
        tab_index_for_mode(MERGE_WHOLE, [MERGE_WHOLE, MERGE_SLICE]),
        tabs_selected_update(slice_mode, SLICE_MODES),
        tabs_selected_update(convert_mode, CONVERT_MODES),
        tabs_selected_update(MERGE_WHOLE, [MERGE_WHOLE, MERGE_SLICE]),
    ]


def _stage_from_label(label: str) -> StageName:
    for text, stage in WIZARD_STAGES:
        if text == label:
            return stage
    return StageName.SEPARATE


def _wizard_runtime_params(
    pid,
    cmode,
    smode,
    ref,
    profile,
    merge_mode,
    wizard_values: dict[str, object],
) -> dict[str, object]:
    reference = ref
    if pid and ref:
        saved = save_reference_audio(pid, ref)
        if saved:
            reference = saved

    params: dict[str, object] = {
        "mode": cmode,
        "reference": reference,
        "profile": profile,
        "merge_mode": merge_mode,
    }
    params.update(collect_params(StageName.SEPARATE.value, wizard_values))
    params.update(collect_params(StageName.SLICE.value, wizard_values, slice_mode=smode))
    params.update(collect_params(StageName.CONVERT.value, wizard_values, convert_mode=cmode))
    params.update(collect_params(StageName.MERGE.value, wizard_values))
    params["slice_mode"] = smode
    return params


def _stage_params_for_step(stage: StageName, runtime_params: dict[str, object], smode: str) -> dict[str, object]:
    if stage == StageName.SEPARATE:
        return collect_params(StageName.SEPARATE.value, runtime_params)
    if stage == StageName.SLICE:
        out = {"mode": smode}
        out.update(collect_params(StageName.SLICE.value, runtime_params, slice_mode=smode))
        return out
    if stage == StageName.CONVERT:
        out = {
            "mode": runtime_params.get("mode"),
            "reference": runtime_params.get("reference"),
        }
        cmode = str(runtime_params.get("mode", CONVERT_BATCH))
        out.update(collect_params(StageName.CONVERT.value, runtime_params, convert_mode=cmode))
        return out
    if stage == StageName.MERGE:
        out = {
            "profile": runtime_params.get("profile"),
            "merge_mode": runtime_params.get("merge_mode", MERGE_WHOLE),
        }
        out.update(collect_params(StageName.MERGE.value, runtime_params))
        return out
    return {}


def wire_wizard(project_state: gr.State, bundle: WizardBundle) -> None:
    wizard_inputs = [
        project_state,
        bundle.step,
        bundle.convert_tab_index,
        bundle.slice_tab_index,
        bundle.reference,
        bundle.merge_profile,
        bundle.merge_tab_index,
        *bundle.wizard_panel.input_components(),
    ]

    def _run_one(pid, step_label, convert_tab_index, slice_tab_index, ref, profile, merge_tab_index, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        cmode = mode_from_tab_index(convert_tab_index, CONVERT_MODES, CONVERT_BATCH)
        smode = mode_from_tab_index(slice_tab_index, SLICE_MODES, SLICE_VAD)
        merge_mode_val = mode_from_tab_index(merge_tab_index, [MERGE_WHOLE, MERGE_SLICE], MERGE_WHOLE)
        stage = _stage_from_label(step_label)
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        runtime = _wizard_runtime_params(pid, cmode, smode, ref, profile, merge_mode_val, wizard_values)
        params = _stage_params_for_step(stage, runtime, smode)
        text, st = "", ""
        for text, st in state.run_stage_ui(pid, stage.value, params):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    def _run_from(pid, step_label, convert_tab_index, slice_tab_index, ref, profile, merge_tab_index, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        cmode = mode_from_tab_index(convert_tab_index, CONVERT_MODES, CONVERT_BATCH)
        smode = mode_from_tab_index(slice_tab_index, SLICE_MODES, SLICE_VAD)
        merge_mode_val = mode_from_tab_index(merge_tab_index, [MERGE_WHOLE, MERGE_SLICE], MERGE_WHOLE)
        from_stage = _stage_from_label(step_label)
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        params = _wizard_runtime_params(pid, cmode, smode, ref, profile, merge_mode_val, wizard_values)
        text, st = "", ""
        for text, st in state.run_pipeline_ui(
            pid,
            convert_mode=cmode,
            slice_mode=smode,
            params=params,
            from_stage=from_stage,
        ):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    def _run_all(pid, convert_tab_index, slice_tab_index, ref, profile, merge_tab_index, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        cmode = mode_from_tab_index(convert_tab_index, CONVERT_MODES, CONVERT_BATCH)
        smode = mode_from_tab_index(slice_tab_index, SLICE_MODES, SLICE_VAD)
        merge_mode_val = mode_from_tab_index(merge_tab_index, [MERGE_WHOLE, MERGE_SLICE], MERGE_WHOLE)
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        params = _wizard_runtime_params(pid, cmode, smode, ref, profile, merge_mode_val, wizard_values)
        text, st = "", ""
        for text, st in state.run_pipeline_ui(pid, convert_mode=cmode, slice_mode=smode, params=params):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    bundle.run_step_btn.click(
        _run_one,
        inputs=wizard_inputs,
        outputs=[bundle.log, bundle.status, bundle.mixed_preview],
    )
    bundle.run_from_btn.click(
        _run_from,
        inputs=wizard_inputs,
        outputs=[bundle.log, bundle.status, bundle.mixed_preview],
    )
    bundle.run_all_btn.click(
        _run_all,
        inputs=wizard_inputs,
        outputs=[bundle.log, bundle.status, bundle.mixed_preview],
    )


def paths_merged(project_id: str):
    from pipeline import paths

    return paths.merged_dir(project_id) / "mixed.flac"
