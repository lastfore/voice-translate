"""Project sidebar components."""

from __future__ import annotations

from collections.abc import Callable

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

    with gr.Accordion("删除项目", open=False):
        delete_scope = gr.Radio(
            choices=[
                ("仅从列表移除（保留所有文件）", "metadata"),
                ("删除产物（保留 input 原文件）", "artifacts"),
                ("彻底删除（含 input 与 separated）", "all"),
            ],
            value="all",
            label="删除范围",
        )
        delete_preview = gr.Markdown("*请先选择项目*")
        delete_preview_btn = gr.Button("刷新预览", size="sm")
        delete_confirm = gr.Checkbox(label="我确认删除以上路径，且知晓不可恢复", value=False)
        delete_btn = gr.Button("删除当前项目", variant="stop")
        delete_msg = gr.Markdown("")

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
        delete_scope,
        delete_preview,
        delete_preview_btn,
        delete_confirm,
        delete_btn,
        delete_msg,
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
    delete_scope: gr.Radio,
    delete_preview: gr.Markdown,
    delete_preview_btn: gr.Button,
    delete_confirm: gr.Checkbox,
    delete_btn: gr.Button,
    delete_msg: gr.Markdown,
    project_state: gr.State,
    *,
    field_refresh_fn: Callable | None = None,
    field_refresh_outputs: list | None = None,
) -> None:
    def _preview(pid: str | None, scope: str):
        return state.preview_project_deletion_ui(pid, scope)

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
            _preview(value, "all"),
        )

    def _on_select(pid: str | None, scope: str):
        defaults = state.load_project_defaults(pid)
        return pid, defaults.get("stage_status_text", "*未选择项目*"), _preview(pid, scope)

    def _create(pid, name, audio, lrc_file):
        lrc_path = None
        if lrc_file:
            lrc_path = lrc_file if isinstance(lrc_file, str) else getattr(lrc_file, "name", None)
        ok, msg = state.create_project_ui(pid, audio, lrc_path, name)
        if not ok:
            return msg, gr.Dropdown(), None, "*未选择项目*", _preview(None, "all")
        summaries = state.get_projects()
        choices = project_choices(summaries)
        defaults = state.load_project_defaults(pid)
        return (
            msg,
            gr.Dropdown(choices=choices, value=pid),
            pid,
            defaults.get("stage_status_text", ""),
            _preview(pid, "all"),
        )

    def _delete(pid: str | None, scope: str, confirmed: bool):
        ok, msg, _deleted = state.delete_project_ui(pid, scope, confirmed=confirmed)
        if not ok:
            return (
                msg,
                gr.Dropdown(),
                pid,
                state.load_project_defaults(pid).get("stage_status_text", "*未选择项目*"),
                _preview(pid, scope),
                False,
            )
        summaries = state.get_projects()
        choices = project_choices(summaries)
        value = choices[0][1] if choices else None
        defaults = state.load_project_defaults(value)
        status = defaults.get("stage_status_text", "*无项目*")
        return (
            msg,
            gr.Dropdown(choices=choices, value=value),
            value,
            status,
            _preview(value, scope),
            False,
        )

    refresh_btn.click(
        _refresh,
        outputs=[project_dropdown, project_state, stage_status, delete_preview],
    )
    project_dropdown.change(
        _on_select,
        inputs=[project_dropdown, delete_scope],
        outputs=[project_state, stage_status, delete_preview],
    )
    delete_scope.change(
        _preview,
        inputs=[project_dropdown, delete_scope],
        outputs=[delete_preview],
    )
    delete_preview_btn.click(
        _preview,
        inputs=[project_dropdown, delete_scope],
        outputs=[delete_preview],
    )
    create_btn.click(
        _create,
        inputs=[new_id, new_name, new_audio, new_lrc],
        outputs=[create_msg, project_dropdown, project_state, stage_status, delete_preview],
    )

    delete_click = delete_btn.click(
        _delete,
        inputs=[project_dropdown, delete_scope, delete_confirm],
        outputs=[
            delete_msg,
            project_dropdown,
            project_state,
            stage_status,
            delete_preview,
            delete_confirm,
        ],
    )
    if field_refresh_fn is not None and field_refresh_outputs:
        delete_click.then(
            field_refresh_fn,
            inputs=[project_state],
            outputs=field_refresh_outputs,
        )
