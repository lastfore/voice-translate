"""Pipeline Web UI — Gradio entrypoint."""



from __future__ import annotations



import os

import sys



_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if _ROOT not in sys.path:

    sys.path.insert(0, _ROOT)



os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

os.environ.setdefault("no_proxy", "127.0.0.1,localhost")



import gradio as gr



from pipeline import paths

from pipeline.models import StageName

from pipeline.stage_params import collect_params

from webui import state

from webui.components.batch_queue import build_batch_queue

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

from webui.components.path_input import PathInput

from webui.components.project_sidebar import build_sidebar, wire_sidebar

from webui.components.slice_tuner import build_slice_tuner, wire_slice_tuner

from webui.components.stage_params import StageParamPanel, build_stage_param_panel

from webui.components.wizard import build_wizard, wizard_defaults_updates

from webui.helpers import audio_if_exists, project_choices, read_manifest_preview, save_reference_audio





def _run_stage_stream(project_id, stage, params):

    for log, st in state.run_stage_ui(project_id, stage, params):

        yield log, st





def _panel_updates(pid: str | None, panel: StageParamPanel) -> list:

    if not panel.keys:

        return []

    saved = state.load_saved_stage_params(pid, panel.stage)

    return panel.updates_from_saved(saved)





def _project_field_updates(pid: str | None, *panels: StageParamPanel) -> list:

    d = state.load_project_defaults(pid)

    if not d:

        empty = [gr.update()] * 23

        empty_wizard = [gr.update()] * 6

        return empty + empty_wizard + [u for panel in panels for u in _panel_updates(pid, panel)]



    vocals_p = paths.separated_vocals_path(pid) if pid else None

    inst_p = paths.separated_instrumental_path(pid) if pid else None

    full_p = paths.resolve_converted_full_track(pid) if pid else None
    slice_mode = d.get("slice_mode", SLICE_VAD)
    slices_p = (
        paths.resolve_converted_mode_dir(pid, slice_mode) or paths.resolve_converted_slices_dir(pid)
        if pid
        else None
    )
    mixed_mode_path = paths.merged_mixed_path(pid, slice_mode) if pid else None
    legacy_mixed = paths.merged_dir(pid) / "mixed.flac" if pid else None
    mixed_p = str(
        mixed_mode_path
        if mixed_mode_path and mixed_mode_path.is_file()
        else legacy_mixed
        if legacy_mixed and legacy_mixed.is_file()
        else mixed_mode_path or legacy_mixed
    )

    manifest_preview = read_manifest_preview(d.get("manifest", ""))

    convert_mode = d.get("convert_mode", CONVERT_BATCH)

    slice_mode = d.get("slice_mode", SLICE_VAD)

    base = [

        d.get("stage_status_text", ""),

        d.get("mix_audio", ""),

        d.get("vocals_path", ""),

        d.get("lrc_path", ""),

        d.get("vocals_path", ""),

        d.get("slices_dir", ""),

        d.get("merge_vocals_file", ""),

        d.get("merge_vocals_dir", ""),

        d.get("merge_instrumental", ""),

        d.get("merge_reference", ""),

        audio_if_exists(str(vocals_p) if vocals_p else None),

        audio_if_exists(str(inst_p) if inst_p else None),

        manifest_preview,

        manifest_preview,

        audio_if_exists(str(full_p) if full_p and full_p.is_file() else None),

        audio_if_exists(mixed_p),

        d.get("merge_profile", "full"),

        MERGE_WHOLE,

        convert_mode,

        slice_mode,

        tabs_selected_update(MERGE_WHOLE, [MERGE_WHOLE, MERGE_SLICE]),

        tabs_selected_update(convert_mode, CONVERT_MODES),

        tabs_selected_update(slice_mode, SLICE_MODES),

    ]

    wizard_saved = state.load_wizard_params(pid)

    panel_updates: list = []

    wizard_mode_updates = wizard_defaults_updates(d)

    for panel in panels:

        if panel.stage == "wizard":

            panel_updates.extend(panel.updates_from_saved(wizard_saved))

        else:

            panel_updates.extend(_panel_updates(pid, panel))

    return base + wizard_mode_updates + panel_updates





def build_app() -> gr.Blocks:

    with gr.Blocks(title="Voice Translate Pipeline", theme=gr.themes.Soft()) as app:

        gr.Markdown(

            "# 管线 Web UI\n"

            "词曲分离 → 切片 → 歌声替换 → 人声伴奏结合。"

            " 各 Tab 可独立运行；高级参数会随项目保存，切换项目后自动恢复。"

        )



        project_state = gr.State(value=None)



        with gr.Row():

            with gr.Column(scale=1, min_width=280):

                (

                    project_dropdown,

                    stage_status,

                    refresh_btn,

                    new_id,

                    new_name,

                    new_audio,

                    new_lrc,

                    create_btn,

                    create_msg,

                ) = build_sidebar()

                wire_sidebar(

                    project_dropdown,

                    stage_status,

                    refresh_btn,

                    new_id,

                    new_name,

                    new_audio,

                    new_lrc,

                    create_btn,

                    create_msg,

                    project_state,

                )



            with gr.Column(scale=3):

                with gr.Tabs():

                    with gr.Tab("向导"):

                        wizard_bundle = build_wizard(project_state)



                    with gr.Tab("分离"):

                        sep_mix_input = PathInput.build(

                            "混音路径",

                            file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                        )

                        sep_mix = sep_mix_input.text

                        sep_params = build_stage_param_panel(StageName.SEPARATE)

                        sep_run = gr.Button("运行分离", variant="primary")

                        sep_log = gr.Textbox(label="日志", lines=8)

                        sep_status = gr.Markdown("")

                        sep_vocals = gr.Audio(label="人声", type="filepath", interactive=False)

                        sep_inst = gr.Audio(label="伴奏", type="filepath", interactive=False)



                    with gr.Tab("切片"):

                        slice_vocals_input = PathInput.build(

                            "源人声路径",

                            file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                        )

                        slice_vocals = slice_vocals_input.text

                        slice_mode = gr.State(SLICE_VAD)

                        with gr.Tabs(selected=0) as slice_subtabs:

                            with gr.Tab(SLICE_TAB_LABELS[0], id="slice_vad") as slice_vad_tab:

                                gr.Markdown(

                                    "无歌词时按语音活动检测（VAD）自动断句。"

                                    " 可在下方高级参数中调节灵敏度与最短片段长度。"

                                )

                                slice_vad_params = build_stage_param_panel(

                                    StageName.SLICE,

                                    vad_only=True,

                                    accordion_label="VAD 高级参数",

                                )

                            with gr.Tab(SLICE_TAB_LABELS[1], id="slice_lrc") as slice_lrc_tab:

                                gr.Markdown("有 LRC 歌词时按歌词时间轴断句，切分更贴合语义。")

                                slice_lrc_input = PathInput.build("LRC 路径", file_types=[".lrc"])

                                slice_lrc = slice_lrc_input.text

                        slice_run = gr.Button("运行切片", variant="primary")

                        slice_log = gr.Textbox(label="日志", lines=8)

                        slice_status = gr.Markdown("")

                        slice_manifest = gr.Textbox(label="manifest 预览", lines=6)

                        slice_p1 = gr.Audio(label="切片预览", type="filepath", interactive=False)



                    with gr.Tab("转换"):

                        convert_mode = gr.State(CONVERT_BATCH)

                        with gr.Tabs(selected=0) as convert_subtabs:

                            with gr.Tab("切片批量", id="convert_batch") as convert_batch_tab:

                                gr.Markdown(

                                    "对切片目录中的每个片段批量执行歌声转换。"

                                    " 适合精细控制每句歌词的转换效果。"

                                )

                                convert_sdir_input = PathInput.build(
                                    "切片目录",
                                    directory=True,
                                    placeholder="例如 output/slices/{项目}/{lrc|vad}/",
                                )

                                convert_sdir = convert_sdir_input.text

                            with gr.Tab("整轨快捷", id="convert_full") as convert_full_tab:

                                gr.Markdown("对整段人声音频一次性转换，产物为 `full.flac`。")

                                convert_source_input = PathInput.build(

                                    "源人声（整段）",

                                    file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                                )

                                convert_source = convert_source_input.text

                            with gr.Tab("切片精修", id="convert_tune") as convert_tune_tab:
                                slice_tuner = build_slice_tuner()

                        convert_ref = gr.Audio(label="参考音频", type="filepath")

                        convert_params = build_stage_param_panel(
                            StageName.CONVERT,
                            accordion_label="转换参数",
                        )

                        convert_run = gr.Button("运行转换", variant="primary")

                        convert_log = gr.Textbox(label="日志", lines=8)

                        convert_status = gr.Markdown("")

                        convert_out = gr.Audio(label="产物", type="filepath", interactive=False)



                    with gr.Tab("合并"):

                        gr.Markdown(

                            "请选择与转换阶段一致的模式。"

                            " **整轨合并** 使用 `full.flac`；**切片拼接** 使用转换切片目录 + manifest。"

                        )

                        merge_mode = gr.State(MERGE_WHOLE)

                        with gr.Tabs(selected=0) as merge_subtabs:

                            with gr.Tab("整轨合并", id="merge_whole") as merge_whole_tab:

                                gr.Markdown(MERGE_WHOLE_HELP)

                                merge_vocals_file_input = PathInput.build(

                                    "人声音频文件",

                                    file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                                    placeholder="例如 output/converted/{项目}/full/full.flac",

                                )

                                merge_vocals_file = merge_vocals_file_input.text

                            with gr.Tab("切片拼接", id="merge_slice") as merge_slice_tab:

                                gr.Markdown(MERGE_SLICE_HELP)

                                merge_vocals_dir_input = PathInput.build(

                                    "转换切片目录",

                                    directory=True,

                                    placeholder="例如 output/converted/{项目}/{lrc|vad}/",

                                )

                                merge_vocals_dir = merge_vocals_dir_input.text

                                merge_manifest_preview = gr.Textbox(

                                    label="manifest 预览",

                                    lines=6,

                                    interactive=False,

                                )

                        merge_inst_input = PathInput.build(

                            "伴奏",

                            file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                        )

                        merge_inst = merge_inst_input.text

                        merge_ref_input = PathInput.build(

                            "原曲参考",

                            file_types=[".flac", ".wav", ".mp3", ".ogg", ".m4a"],

                        )

                        merge_ref = merge_ref_input.text

                        merge_profile = gr.Radio(["quick", "balanced", "full"], value="full", label="Profile")

                        merge_params = build_stage_param_panel(StageName.MERGE)

                        merge_run = gr.Button("运行合并", variant="primary")

                        merge_log = gr.Textbox(label="日志", lines=8)

                        merge_status = gr.Markdown("")

                        merge_mixed = gr.Audio(label="mixed.flac", type="filepath", interactive=False)



                    with gr.Tab("批量队列"):

                        build_batch_queue(project_state)



        path_inputs = [

            sep_mix_input,

            slice_vocals_input,

            slice_lrc_input,

            convert_source_input,

            convert_sdir_input,

            merge_vocals_file_input,

            merge_vocals_dir_input,

            merge_inst_input,

            merge_ref_input,

        ]

        for path_input in path_inputs:

            path_input.wire()



        wire_mode_tabs(

            [(slice_vad_tab, SLICE_VAD), (slice_lrc_tab, SLICE_LRC)],

            slice_mode,

        )

        wire_mode_tabs(

            [(convert_batch_tab, CONVERT_BATCH), (convert_full_tab, CONVERT_FULL)],

            convert_mode,

        )

        wire_slice_tuner(slice_tuner, project_state, slice_mode)

        wire_mode_tabs(

            [(merge_whole_tab, MERGE_WHOLE), (merge_slice_tab, MERGE_SLICE)],

            merge_mode,

        )



        param_panels = [

            wizard_bundle.wizard_panel,

            sep_params,

            slice_vad_params,

            convert_params,

            merge_params,

        ]



        field_outputs = [

            stage_status,

            sep_mix,

            slice_vocals,

            slice_lrc,

            convert_source,

            convert_sdir,

            merge_vocals_file,

            merge_vocals_dir,

            merge_inst,

            merge_ref,

            sep_vocals,

            sep_inst,

            slice_manifest,

            merge_manifest_preview,

            convert_out,

            merge_mixed,

            merge_profile,

            merge_mode,

            convert_mode,

            slice_mode,

            merge_subtabs,

            convert_subtabs,

            slice_subtabs,

            *wizard_bundle.field_outputs(),

            *sep_params.input_components(),

            *slice_vad_params.input_components(),

            *convert_params.input_components(),

            *merge_params.input_components(),

        ]



        project_state.change(

            lambda pid: _project_field_updates(pid, *param_panels),

            inputs=[project_state],

            outputs=field_outputs,

        )



        def run_separate(pid, mix, *param_values):

            params = {"mix_audio": mix}

            params.update(collect_params(StageName.SEPARATE.value, sep_params.values_to_dict(*param_values)))

            yield from _run_stage_stream(pid, StageName.SEPARATE.value, params)



        sep_run.click(

            run_separate,

            inputs=[project_state, sep_mix, *sep_params.input_components()],

            outputs=[sep_log, sep_status],

        ).then(

            lambda pid: _project_field_updates(pid, *param_panels),

            inputs=[project_state],

            outputs=field_outputs,

        )



        def run_slice(pid, vocals, mode, lrc, *param_values):

            params = {"vocals": vocals, "mode": mode, "lrc": lrc if mode == SLICE_LRC else ""}

            params.update(

                collect_params(

                    StageName.SLICE.value,

                    slice_vad_params.values_to_dict(*param_values),

                    slice_mode=mode,

                )

            )

            yield from _run_stage_stream(pid, StageName.SLICE.value, params)



        slice_run.click(

            run_slice,

            inputs=[

                project_state,

                slice_vocals,

                slice_mode,

                slice_lrc,

                *slice_vad_params.input_components(),

            ],

            outputs=[slice_log, slice_status],

        ).then(

            lambda pid: _project_field_updates(pid, *param_panels),

            inputs=[project_state],

            outputs=field_outputs,

        )



        def run_convert(pid, mode, source, sdir, ref, slice_mode_val, *param_values):

            reference = save_reference_audio(pid, ref) if pid and ref else ref

            all_values = convert_params.values_to_dict(*param_values)

            if mode == CONVERT_FULL:

                params = {"mode": mode, "source_vocals": source, "reference": reference}

            else:

                params = {
                    "mode": mode,
                    "slices_dir": sdir,
                    "reference": reference,
                    "slice_mode": slice_mode_val,
                    "active_slice_mode": slice_mode_val,
                }

            params.update(

                collect_params(StageName.CONVERT.value, all_values, convert_mode=mode)

            )

            slice_mode = params.get("active_slice_mode") or slice_mode_val or ""
            config_line = (
                f"[配置] mode={params.get('mode')} slice_mode={slice_mode or '-'} "
                f"diffusion_steps={params.get('diffusion_steps')} "
                f"semi_tone_shift={params.get('semi_tone_shift')} "
                f"inference_cfg_rate={params.get('inference_cfg_rate')} "
                f"length_adjust={params.get('length_adjust')} "
                f"skip_existing={params.get('skip_existing')} "
                f"fp16={params.get('fp16')} auto_f0_adjust={params.get('auto_f0_adjust')} "
                f"limit={params.get('limit')}"
            )

            yield config_line, "运行中..."

            yield from _run_stage_stream(pid, StageName.CONVERT.value, params)



        convert_run.click(

            run_convert,

            inputs=[

                project_state,

                convert_mode,

                convert_source,

                convert_sdir,

                convert_ref,

                slice_mode,

                *convert_params.input_components(),

            ],

            outputs=[convert_log, convert_status],

        ).then(

            lambda pid: _project_field_updates(pid, *param_panels),

            inputs=[project_state],

            outputs=field_outputs,

        )



        def run_merge(
            pid,
            mode,
            vocals_file,
            vocals_dir,
            inst,
            ref,
            profile,
            *param_values,
        ):

            vocals = vocals_file if mode == MERGE_WHOLE else vocals_dir

            params = {

                "vocals": vocals,

                "instrumental": inst,

                "reference": ref,

                "profile": profile,

                "merge_mode": mode,

            }

            params.update(collect_params(StageName.MERGE.value, merge_params.values_to_dict(*param_values)))

            config_line = (
                f"[配置] profile={profile}, clean_instrumental={params.get('clean_instrumental')}, "
                f"skip_mastering={params.get('skip_mastering')}"
            )

            yield config_line, "运行中..."

            yield from _run_stage_stream(pid, StageName.MERGE.value, params)



        merge_run.click(

            run_merge,

            inputs=[

                project_state,

                merge_mode,

                merge_vocals_file,

                merge_vocals_dir,

                merge_inst,

                merge_ref,

                merge_profile,

                *merge_params.input_components(),

            ],

            outputs=[merge_log, merge_status],

        ).then(

            lambda pid: _project_field_updates(pid, *param_panels),

            inputs=[project_state],

            outputs=field_outputs,

        )



        def initial_load():

            summaries = state.refresh_projects()

            choices = project_choices(summaries)

            value = choices[0][1] if choices else None

            return (

                gr.Dropdown(choices=choices, value=value),

                value,

                *_project_field_updates(value, *param_panels),

            )



        app.load(

            initial_load,

            outputs=[project_dropdown, project_state, *field_outputs],

        )



    return app





def main() -> None:

    port = int(os.environ.get("PIPELINE_WEBUI_PORT", "7860"))

    app = build_app()

    app.queue(default_concurrency_limit=2)

    app.launch(server_name="127.0.0.1", server_port=port, show_error=True)





if __name__ == "__main__":

    main()


