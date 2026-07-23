"""Wizard tab for guided pipeline execution."""

from __future__ import annotations

import gradio as gr

from pipeline.models import ConvertMode, SliceMode, StageName
from webui import state
from webui.helpers import audio_if_exists, save_reference_audio


WIZARD_STAGES = [
    ("1. 词曲分离", StageName.SEPARATE),
    ("2. 声乐切片", StageName.SLICE),
    ("3. 歌声转换", StageName.CONVERT),
    ("4. 人声伴奏结合", StageName.MERGE),
]


def build_wizard(project_state: gr.State) -> tuple:
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

    run_step_btn = gr.Button("运行当前步骤", variant="secondary")
    run_from_btn = gr.Button("从此步跑到最后", variant="secondary")
    run_all_btn = gr.Button("一键全流程", variant="primary")

    log = gr.Textbox(label="进度 / 日志", lines=12, max_lines=30)
    status = gr.Markdown("")
    mixed_preview = gr.Audio(label="mixed.flac 试听", type="filepath", interactive=False)

    wire_wizard(
        project_state,
        step,
        convert_mode,
        slice_mode,
        reference,
        merge_profile,
        run_step_btn,
        run_from_btn,
        run_all_btn,
        log,
        status,
        mixed_preview,
    )
    return step, log, status, mixed_preview


def _stage_from_label(label: str) -> StageName:
    for text, stage in WIZARD_STAGES:
        if text == label:
            return stage
    return StageName.SEPARATE


def _wizard_params(pid, convert_mode, slice_mode, reference, merge_profile):
    ref = reference
    if pid and reference:
        saved = save_reference_audio(pid, reference)
        if saved:
            ref = saved
    return {
        "mode": convert_mode,
        "reference": ref,
        "profile": merge_profile,
        "slice_mode": slice_mode,
    }


def wire_wizard(
    project_state,
    step,
    convert_mode,
    slice_mode,
    reference,
    merge_profile,
    run_step_btn,
    run_from_btn,
    run_all_btn,
    log,
    status,
    mixed_preview,
) -> None:
    def _run_one(pid, step_label, cmode, smode, ref, profile):
        if not pid:
            yield "", "请先选择项目", None
            return
        stage = _stage_from_label(step_label)
        params = _wizard_params(pid, cmode, smode, ref, profile)
        if stage == StageName.SLICE:
            params = {"mode": smode}
        elif stage == StageName.MERGE:
            params = {"profile": profile}
        elif stage == StageName.CONVERT:
            params = {"mode": cmode, "reference": params.get("reference")}
        else:
            params = {}
        text, st = "", ""
        for text, st in state.run_stage_ui(pid, stage.value, params):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    def _run_from(pid, step_label, cmode, smode, ref, profile):
        if not pid:
            yield "", "请先选择项目", None
            return
        from_stage = _stage_from_label(step_label)
        params = _wizard_params(pid, cmode, smode, ref, profile)
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

    def _run_all(pid, cmode, smode, ref, profile):
        if not pid:
            yield "", "请先选择项目", None
            return
        params = _wizard_params(pid, cmode, smode, ref, profile)
        text, st = "", ""
        for text, st in state.run_pipeline_ui(
            pid, convert_mode=cmode, slice_mode=smode, params=params
        ):
            yield text, st, None
        yield text, st, audio_if_exists(str(paths_merged(pid)))

    run_step_btn.click(
        _run_one,
        inputs=[project_state, step, convert_mode, slice_mode, reference, merge_profile],
        outputs=[log, status, mixed_preview],
    )
    run_from_btn.click(
        _run_from,
        inputs=[project_state, step, convert_mode, slice_mode, reference, merge_profile],
        outputs=[log, status, mixed_preview],
    )
    run_all_btn.click(
        _run_all,
        inputs=[project_state, convert_mode, slice_mode, reference, merge_profile],
        outputs=[log, status, mixed_preview],
    )


def paths_merged(project_id: str):
    from pipeline import paths

    return paths.merged_dir(project_id) / "mixed.flac"
