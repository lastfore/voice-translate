"""Wizard tab for guided pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass

import gradio as gr

from pipeline.models import ConvertMode, SliceMode, StageName
from pipeline.stage_params import collect_params
from webui import state
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
    convert_mode: gr.Radio
    slice_mode: gr.Radio
    reference: gr.Audio
    merge_profile: gr.Radio
    run_step_btn: gr.Button
    run_from_btn: gr.Button
    run_all_btn: gr.Button
    log: gr.Textbox
    status: gr.Markdown
    mixed_preview: gr.Audio


def build_wizard(project_state: gr.State) -> WizardBundle:
    step = gr.Radio(
        choices=[label for label, _ in WIZARD_STAGES],
        value=WIZARD_STAGES[0][0],
        label="当前步骤",
    )
    convert_mode = gr.Radio(
        [ConvertMode.SLICE_BATCH.value, ConvertMode.FULL_TRACK.value],
        value=ConvertMode.SLICE_BATCH.value,
        label="转换模式",
    )
    slice_mode = gr.Radio(
        [SliceMode.LRC.value, SliceMode.VAD.value],
        value=SliceMode.LRC.value,
        label="切片模式",
    )
    reference = gr.Audio(label="参考音频", type="filepath")
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
        convert_mode=convert_mode,
        slice_mode=slice_mode,
        reference=reference,
        merge_profile=merge_profile,
        run_step_btn=run_step_btn,
        run_from_btn=run_from_btn,
        run_all_btn=run_all_btn,
        log=log,
        status=status,
        mixed_preview=mixed_preview,
    )
    wire_wizard(project_state, bundle)
    return bundle


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
    }
    params.update(collect_params(StageName.SEPARATE.value, wizard_values))
    params.update(
        collect_params(StageName.SLICE.value, wizard_values, slice_mode=smode),
    )
    params.update(collect_params(StageName.CONVERT.value, wizard_values))
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
        out.update(collect_params(StageName.CONVERT.value, runtime_params))
        return out
    if stage == StageName.MERGE:
        out = {"profile": runtime_params.get("profile")}
        out.update(collect_params(StageName.MERGE.value, runtime_params))
        return out
    return {}


def wire_wizard(project_state: gr.State, bundle: WizardBundle) -> None:
    wizard_inputs = [
        project_state,
        bundle.step,
        bundle.convert_mode,
        bundle.slice_mode,
        bundle.reference,
        bundle.merge_profile,
        *bundle.wizard_panel.input_components(),
    ]

    def _run_one(pid, step_label, cmode, smode, ref, profile, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        stage = _stage_from_label(step_label)
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        runtime = _wizard_runtime_params(pid, cmode, smode, ref, profile, wizard_values)
        params = _stage_params_for_step(stage, runtime, smode)
        text, st = "", ""
        for text, st in state.run_stage_ui(pid, stage.value, params):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    def _run_from(pid, step_label, cmode, smode, ref, profile, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        from_stage = _stage_from_label(step_label)
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        params = _wizard_runtime_params(pid, cmode, smode, ref, profile, wizard_values)
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

    def _run_all(pid, cmode, smode, ref, profile, *param_values):
        if not pid:
            yield "", "请先选择项目", None
            return
        wizard_values = bundle.wizard_panel.values_to_dict(*param_values)
        params = _wizard_runtime_params(pid, cmode, smode, ref, profile, wizard_values)
        text, st = "", ""
        for text, st in state.run_pipeline_ui(
            pid, convert_mode=cmode, slice_mode=smode, params=params
        ):
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
