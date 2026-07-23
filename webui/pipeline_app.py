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
from webui.components.project_sidebar import build_sidebar, wire_sidebar
from webui.components.stage_params import StageParamPanel, build_stage_param_panel
from webui.components.wizard import build_wizard
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
        empty = [gr.update()] * 16
        return empty + [u for panel in panels for u in _panel_updates(pid, panel)]

    vocals_p = paths.separated_vocals_path(pid) if pid else None
    inst_p = paths.separated_instrumental_path(pid) if pid else None
    full_p = paths.converted_full_track_path(pid) if pid else None
    slice_preview = None
    if pid and paths.slices_dir(pid).is_dir():
        flacs = sorted(paths.slices_dir(pid).glob("*.flac"))
        if flacs:
            slice_preview = str(flacs[0])
    mixed_p = str(paths.merged_dir(pid) / "mixed.flac") if pid else None
    base = [
        d.get("stage_status_text", ""),
        d.get("mix_audio", ""),
        d.get("vocals_path", ""),
        d.get("slice_mode", "vad"),
        d.get("lrc_path", ""),
        d.get("convert_mode", "slice_batch"),
        d.get("vocals_path", ""),
        d.get("slices_dir", ""),
        d.get("merge_vocals", ""),
        d.get("merge_inst", ""),
        d.get("merge_reference", ""),
        audio_if_exists(str(vocals_p) if vocals_p else None),
        audio_if_exists(str(inst_p) if inst_p else None),
        read_manifest_preview(d.get("manifest", "")),
        audio_if_exists(str(full_p) if full_p and full_p.is_file() else None),
        audio_if_exists(mixed_p),
    ]
    wizard_saved = state.load_wizard_params(pid)
    panel_updates: list = []
    for panel in panels:
        if panel.stage == "wizard":
            panel_updates.extend(panel.updates_from_saved(wizard_saved))
        else:
            panel_updates.extend(_panel_updates(pid, panel))
    return base + panel_updates


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
                        sep_mix = gr.Textbox(label="混音路径")
                        sep_params = build_stage_param_panel(StageName.SEPARATE)
                        sep_run = gr.Button("运行分离", variant="primary")
                        sep_log = gr.Textbox(label="日志", lines=8)
                        sep_status = gr.Markdown("")
                        sep_vocals = gr.Audio(label="人声", type="filepath", interactive=False)
                        sep_inst = gr.Audio(label="伴奏", type="filepath", interactive=False)

                    with gr.Tab("切片"):
                        slice_vocals = gr.Textbox(label="源人声路径")
                        slice_mode = gr.Radio(["vad", "lrc"], value="vad", label="模式")
                        slice_lrc = gr.Textbox(label="LRC 路径")
                        slice_params = build_stage_param_panel(StageName.SLICE)
                        slice_run = gr.Button("运行切片", variant="primary")
                        slice_log = gr.Textbox(label="日志", lines=8)
                        slice_status = gr.Markdown("")
                        slice_manifest = gr.Textbox(label="manifest", lines=6)
                        slice_p1 = gr.Audio(label="切片预览", type="filepath", interactive=False)

                    with gr.Tab("转换"):
                        convert_mode = gr.Radio(["slice_batch", "full_track"], value="slice_batch", label="模式")
                        convert_source = gr.Textbox(label="源人声（整段）")
                        convert_sdir = gr.Textbox(label="切片目录（批量）")
                        convert_ref = gr.Audio(label="参考音频", type="filepath")
                        convert_params = build_stage_param_panel(StageName.CONVERT)
                        convert_run = gr.Button("运行转换", variant="primary")
                        convert_log = gr.Textbox(label="日志", lines=8)
                        convert_status = gr.Markdown("")
                        convert_out = gr.Audio(label="产物", type="filepath", interactive=False)

                    with gr.Tab("合并"):
                        merge_vocals = gr.Textbox(label="人声")
                        merge_inst = gr.Textbox(label="伴奏")
                        merge_ref = gr.Textbox(label="原曲参考")
                        merge_profile = gr.Radio(["quick", "balanced", "full"], value="full", label="Profile")
                        merge_params = build_stage_param_panel(StageName.MERGE)
                        merge_run = gr.Button("运行合并", variant="primary")
                        merge_log = gr.Textbox(label="日志", lines=8)
                        merge_status = gr.Markdown("")
                        merge_mixed = gr.Audio(label="mixed.flac", type="filepath", interactive=False)

                    with gr.Tab("批量队列"):
                        build_batch_queue(project_state)

        param_panels = [
            wizard_bundle.wizard_panel,
            sep_params,
            slice_params,
            convert_params,
            merge_params,
        ]

        field_outputs = [
            stage_status,
            sep_mix,
            slice_vocals,
            slice_mode,
            slice_lrc,
            convert_mode,
            convert_source,
            convert_sdir,
            merge_vocals,
            merge_inst,
            merge_ref,
            sep_vocals,
            sep_inst,
            slice_manifest,
            convert_out,
            merge_mixed,
            *wizard_bundle.wizard_panel.input_components(),
            *sep_params.input_components(),
            *slice_params.input_components(),
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
            return _run_stage_stream(pid, StageName.SEPARATE.value, params)

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
            params = {"vocals": vocals, "mode": mode, "lrc": lrc}
            params.update(
                collect_params(
                    StageName.SLICE.value,
                    slice_params.values_to_dict(*param_values),
                    slice_mode=mode,
                )
            )
            return _run_stage_stream(pid, StageName.SLICE.value, params)

        slice_run.click(
            run_slice,
            inputs=[project_state, slice_vocals, slice_mode, slice_lrc, *slice_params.input_components()],
            outputs=[slice_log, slice_status],
        ).then(
            lambda pid: _project_field_updates(pid, *param_panels),
            inputs=[project_state],
            outputs=field_outputs,
        )

        def run_convert(pid, mode, source, sdir, ref, *param_values):
            reference = save_reference_audio(pid, ref) if pid and ref else ref
            params = {"mode": mode, "source_vocals": source, "slices_dir": sdir, "reference": reference}
            params.update(collect_params(StageName.CONVERT.value, convert_params.values_to_dict(*param_values)))
            return _run_stage_stream(pid, StageName.CONVERT.value, params)

        convert_run.click(
            run_convert,
            inputs=[
                project_state,
                convert_mode,
                convert_source,
                convert_sdir,
                convert_ref,
                *convert_params.input_components(),
            ],
            outputs=[convert_log, convert_status],
        ).then(
            lambda pid: _project_field_updates(pid, *param_panels),
            inputs=[project_state],
            outputs=field_outputs,
        )

        def run_merge(pid, vocals, inst, ref, profile, *param_values):
            params = {"vocals": vocals, "instrumental": inst, "reference": ref, "profile": profile}
            params.update(collect_params(StageName.MERGE.value, merge_params.values_to_dict(*param_values)))
            return _run_stage_stream(pid, StageName.MERGE.value, params)

        merge_run.click(
            run_merge,
            inputs=[
                project_state,
                merge_vocals,
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
