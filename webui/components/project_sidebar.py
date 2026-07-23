"""Project sidebar components."""

from __future__ import annotations

import gradio as gr

from webui import state
from webui.helpers import project_choices


def build_sidebar() -> tuple:
    gr.Markdown("## 项目")
    project_dropdown = gr.Dropdown(label="当前项目", choices=[], value=None, interactive=True)
    stage_status = gr.Markdown("*未选择项目*")
    refresh_btn = gr.Button("刷新列表", size="sm")

    with gr.Accordion("新建项目", open=False):
        new_id = gr.Textbox(label="项目 ID", placeholder="例如 mysong")
        new_name = gr.Textbox(label="显示名称（可选）")
        new_audio = gr.Audio(label="混音文件", type="filepath")
        new_lrc = gr.File(label="歌词 LRC（可选）", file_types=[".lrc"])
        create_btn = gr.Button("创建项目", variant="primary")
        create_msg = gr.Markdown("")

    return (
        project_dropdown,
        stage_status,
        refresh_btn,
        new_id,
        new_name,
        new_audio,
        new_lrc,
        create_btn,
        create_msg,
    )


def wire_sidebar(
    project_dropdown: gr.Dropdown,
    stage_status: gr.Markdown,
    refresh_btn: gr.Button,
    new_id: gr.Textbox,
    new_name: gr.Textbox,
    new_audio: gr.Audio,
    new_lrc: gr.File,
    create_btn: gr.Button,
    create_msg: gr.Markdown,
    project_state: gr.State,
) -> None:
    def _refresh():
        summaries = state.refresh_projects()
        choices = project_choices(summaries)
        value = choices[0][1] if choices else None
        defaults = state.load_project_defaults(value)
        status = defaults.get("stage_status_text", "*无项目*")
        return (
            gr.Dropdown(choices=choices, value=value),
            value,
            status,
        )

    def _on_select(pid: str | None):
        defaults = state.load_project_defaults(pid)
        return pid, defaults.get("stage_status_text", "*未选择项目*")

    def _create(pid, name, audio, lrc_file):
        lrc_path = None
        if lrc_file:
            lrc_path = lrc_file if isinstance(lrc_file, str) else getattr(lrc_file, "name", None)
        ok, msg = state.create_project_ui(pid, audio, lrc_path, name)
        if not ok:
            return msg, gr.Dropdown(), None, "*未选择项目*"
        summaries = state.get_projects()
        choices = project_choices(summaries)
        defaults = state.load_project_defaults(pid)
        return (
            msg,
            gr.Dropdown(choices=choices, value=pid),
            pid,
            defaults.get("stage_status_text", ""),
        )

    refresh_btn.click(_refresh, outputs=[project_dropdown, project_state, stage_status])
    project_dropdown.change(_on_select, inputs=[project_dropdown], outputs=[project_state, stage_status])
    create_btn.click(
        _create,
        inputs=[new_id, new_name, new_audio, new_lrc],
        outputs=[create_msg, project_dropdown, project_state, stage_status],
    )
