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
from webui import state
from webui.components.batch_queue import build_batch_queue
from webui.components.project_sidebar import build_sidebar, wire_sidebar
from webui.components.wizard import build_wizard
from webui.helpers import audio_if_exists, project_choices, read_manifest_preview, save_reference_audio


def _run_stage_stream(project_id, stage, params):
    for log, st in state.run_stage_ui(project_id, stage, params):
        yield log, st


def _project_field_updates(pid: str | None) -> list:
    d = state.load_project_defaults(pid)
    if not d:
        return [gr.update()] * 16
    vocals_p = paths.separated_vocals_path(pid) if pid else None
    inst_p = paths.separated_instrumental_path(pid) if pid else None
    full_p = paths.converted_full_track_path(pid) if pid else None
    slice_preview = None
    if pid and paths.slices_dir(pid).is_dir():
        flacs = sorted(paths.slices_dir(pid).glob("*.flac"))
        if flacs:
            slice_preview = str(flacs[0])
    mixed_p = str(paths.merged_dir(pid) / "mixed.flac") if pid else None
    return [
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


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Voice Translate Pipeline", theme=gr.themes.Soft()) as app:
        gr.Markdown(
            "# 管线 Web UI\n"
            "词曲分离 → 切片 → 歌声替换 → 人声伴奏结合。"
            " 各 Tab 可独立运行。"
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
                        build_wizard(project_state)

                    with gr.Tab("分离"):
                        sep_mix = gr.Textbox(label="混音路径")
                        sep_run = gr.Button("运行分离", variant="primary")
                        sep_log = gr.Textbox(label="日志", lines=8)
                        sep_status = gr.Markdown("")
                        sep_vocals = gr.Audio(label="人声", type="filepath", interactive=False)
                        sep_inst = gr.Audio(label="伴奏", type="filepath", interactive=False)

                    with gr.Tab("切片"):
                        slice_vocals = gr.Textbox(label="源人声路径")
                        slice_mode = gr.Radio(["vad", "lrc"], value="vad", label="模式")
                        slice_lrc = gr.Textbox(label="LRC 路径")
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
                        convert_run = gr.Button("运行转换", variant="primary")
                        convert_log = gr.Textbox(label="日志", lines=8)
                        convert_status = gr.Markdown("")
                        convert_out = gr.Audio(label="产物", type="filepath", interactive=False)

                    with gr.Tab("合并"):
                        merge_vocals = gr.Textbox(label="人声")
                        merge_inst = gr.Textbox(label="伴奏")
                        merge_ref = gr.Textbox(label="原曲参考")
                        merge_profile = gr.Radio(["quick", "balanced", "full"], value="full", label="Profile")
                        merge_run = gr.Button("运行合并", variant="primary")
                        merge_log = gr.Textbox(label="日志", lines=8)
                        merge_status = gr.Markdown("")
                        merge_mixed = gr.Audio(label="mixed.flac", type="filepath", interactive=False)

                    with gr.Tab("批量队列"):
                        build_batch_queue(project_state)

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
        ]

        project_state.change(_project_field_updates, inputs=[project_state], outputs=field_outputs)

        sep_run.click(
            lambda pid, mix: _run_stage_stream(pid, StageName.SEPARATE.value, {"mix_audio": mix}),
            inputs=[project_state, sep_mix],
            outputs=[sep_log, sep_status],
        ).then(_project_field_updates, inputs=[project_state], outputs=field_outputs)

        slice_run.click(
            lambda pid, v, m, l: _run_stage_stream(
                pid, StageName.SLICE.value, {"vocals": v, "mode": m, "lrc": l}
            ),
            inputs=[project_state, slice_vocals, slice_mode, slice_lrc],
            outputs=[slice_log, slice_status],
        ).then(_project_field_updates, inputs=[project_state], outputs=field_outputs)

        def run_convert(pid, mode, source, sdir, ref):
            reference = save_reference_audio(pid, ref) if pid and ref else ref
            params = {"mode": mode, "source_vocals": source, "slices_dir": sdir, "reference": reference}
            return _run_stage_stream(pid, StageName.CONVERT.value, params)

        convert_run.click(
            run_convert,
            inputs=[project_state, convert_mode, convert_source, convert_sdir, convert_ref],
            outputs=[convert_log, convert_status],
        ).then(_project_field_updates, inputs=[project_state], outputs=field_outputs)

        merge_run.click(
            lambda pid, v, i, r, p: _run_stage_stream(
                pid,
                StageName.MERGE.value,
                {"vocals": v, "instrumental": i, "reference": r, "profile": p},
            ),
            inputs=[project_state, merge_vocals, merge_inst, merge_ref, merge_profile],
            outputs=[merge_log, merge_status],
        ).then(_project_field_updates, inputs=[project_state], outputs=field_outputs)

        def initial_load():
            summaries = state.refresh_projects()
            choices = project_choices(summaries)
            value = choices[0][0] if choices else None
            return (gr.Dropdown(choices=choices, value=value), value, *_project_field_updates(value))

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
