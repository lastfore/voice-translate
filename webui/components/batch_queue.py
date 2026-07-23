"""Batch queue tab."""

from __future__ import annotations

import gradio as gr

from webui import state
from webui.helpers import project_choices


def build_batch_queue(project_state: gr.State) -> None:
    gr.Markdown("多项目任务按提交顺序串行执行（GPU 任务自动排队）。")

    project_checks = gr.CheckboxGroup(choices=[], label="选择项目")
    stage_checks = gr.CheckboxGroup(
        choices=["separate", "slice", "convert", "merge"],
        label="执行阶段",
        value=["convert"],
    )
    convert_mode = gr.Radio(["slice_batch", "full_track"], value="slice_batch", label="转换模式")
    slice_mode = gr.Radio(["lrc", "vad"], value="lrc", label="切片模式")
    merge_profile = gr.Radio(["quick", "balanced", "full"], value="full", label="合并 Profile")

    with gr.Row():
        enqueue_btn = gr.Button("加入队列")
        run_btn = gr.Button("执行队列", variant="primary")
        clear_btn = gr.Button("清除已完成")

    queue_view = gr.Textbox(label="队列状态", lines=10)
    status = gr.Markdown("")

    def _refresh_checks():
        summaries = state.get_projects()
        choices = project_choices(summaries)
        return gr.CheckboxGroup(choices=[c[1] for c in choices], value=[])

    refresh_btn = gr.Button("刷新项目列表", size="sm")
    refresh_btn.click(_refresh_checks, outputs=[project_checks])

    def _enqueue(selected_labels, stages, cmode, smode, profile):
        if not selected_labels:
            return "请选择项目", state.batch_queue_status()
        # Map label back to id
        summaries = state.get_projects()
        id_map = {format_choice(s): s["id"] for s in summaries}
        ids = [id_map[label] for label in selected_labels if label in id_map]
        msg = state.enqueue_batch(ids, stages, {"profile": profile, "mode": cmode})
        return msg, state.batch_queue_status()

    enqueue_btn.click(
        _enqueue,
        inputs=[project_checks, stage_checks, convert_mode, slice_mode, merge_profile],
        outputs=[status, queue_view],
    )

    run_btn.click(
        lambda cmode, smode, profile: state.run_batch_queue_ui(cmode, smode, profile),
        inputs=[convert_mode, slice_mode, merge_profile],
        outputs=[queue_view, status],
    )

    def _clear():
        state.clear_batch_queue()
        return state.batch_queue_status(), "已清除已完成项"

    clear_btn.click(_clear, outputs=[queue_view, status])


def format_choice(summary: dict) -> str:
    from webui.helpers import format_project_choice

    return format_project_choice(summary)
