"""Slice list preview: Dataframe + row-selected audio playback."""

from __future__ import annotations

from dataclasses import dataclass

import gradio as gr

from pipeline import paths
from webui.helpers import (
    SLICE_TABLE_HEADERS,
    audio_for_slice,
    audio_if_exists,
    load_slice_table,
)


@dataclass
class SlicePreviewBundle:
    slice_table: gr.Dataframe
    preview_audio: gr.Audio
    slices_dir_label: gr.Markdown
    open_dir_btn: gr.Button


def build_slice_preview(*, label: str = "切片列表") -> SlicePreviewBundle:
    slice_table = gr.Dataframe(
        headers=SLICE_TABLE_HEADERS,
        datatype=["str", "number", "number", "str", "str", "str"],
        label=label,
        interactive=True,
        row_count=(0, "dynamic"),
    )
    preview_audio = gr.Audio(label="选中切片", type="filepath", interactive=False)
    slices_dir_label = gr.Markdown("*无切片目录*")
    open_dir_btn = gr.Button("显示目录路径", size="sm")
    return SlicePreviewBundle(
        slice_table=slice_table,
        preview_audio=preview_audio,
        slices_dir_label=slices_dir_label,
        open_dir_btn=open_dir_btn,
    )


def slice_preview_values(project_id: str | None, slice_mode: str) -> tuple[list[list], str | None, str]:
    rows, audio, dir_label = load_slice_table(project_id, slice_mode)
    return rows, audio_if_exists(audio), dir_label


def wire_slice_preview(
    bundle: SlicePreviewBundle,
    project_state: gr.State,
    slice_mode: gr.State,
) -> None:
    def _refresh(pid: str | None, smode: str | None):
        return slice_preview_values(pid, smode or "lrc")

    def _on_row_select(pid: str | None, smode: str | None, evt: gr.SelectData):
        if not pid or evt.index is None:
            return None
        row_idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        rows, _, _ = load_slice_table(pid, smode or "lrc", include_tune_status=False)
        if row_idx < 0 or row_idx >= len(rows):
            return None
        slice_id = str(rows[row_idx][0])
        return audio_if_exists(audio_for_slice(pid, smode or "lrc", slice_id))

    def _show_dir(pid: str | None, smode: str | None):
        if not pid:
            return "*请先选择项目*"
        mode_dir = paths.resolve_slices_mode_dir(pid, smode or "lrc")
        if mode_dir is None:
            return "*无切片目录*"
        return f"**路径（请手动复制）：** `{mode_dir}`"

    slice_mode.change(
        _refresh,
        inputs=[project_state, slice_mode],
        outputs=[bundle.slice_table, bundle.preview_audio, bundle.slices_dir_label],
    )
    bundle.slice_table.select(
        _on_row_select,
        inputs=[project_state, slice_mode],
        outputs=[bundle.preview_audio],
    )
    bundle.open_dir_btn.click(
        _show_dir,
        inputs=[project_state, slice_mode],
        outputs=[bundle.slices_dir_label],
    )
