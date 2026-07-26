"""Nested sub-tab mode selectors — shared constants and wiring helpers."""

from __future__ import annotations

import gradio as gr

from webui.mode_utils import mode_from_tab_index

# Merge
MERGE_WHOLE = "whole_track"
MERGE_SLICE = "slice_stitch"
MERGE_MODES = [MERGE_WHOLE, MERGE_SLICE]
MERGE_TAB_LABELS = ["整轨合并", "切片拼接"]

# Convert
CONVERT_BATCH = "slice_batch"
CONVERT_FULL = "full_track"
CONVERT_MODES = [CONVERT_BATCH, CONVERT_FULL]
CONVERT_TAB_LABELS = ["切片批量", "整轨快捷"]

# Slice
SLICE_VAD = "vad"
SLICE_LRC = "lrc"
SLICE_MODES = [SLICE_VAD, SLICE_LRC]
SLICE_TAB_LABELS = ["VAD 断句", "LRC 歌词断句"]

MERGE_WHOLE_HELP = (
    "适用于转换阶段使用 **整轨快捷** 模式，产物为 `output/converted/{项目}/full/full.flac`。"
    " 请选择单个音频文件作为人声输入。"
)
MERGE_SLICE_HELP = (
    "适用于 **切片 → 批量转换** 流程。系统读取 `output/slices/{项目}/{lrc|vad}/manifest.json`，"
    " 在 `output/converted/{项目}/{lrc|vad}/` 中查找转换切片；缺失项回退到原始切片。"
)


def wire_mode_tabs(
    tab_mode_pairs: list[tuple[gr.Tab, str]],
    state: gr.State,
    *,
    tabs: gr.Tabs | None = None,
    index_state: gr.State | None = None,
) -> None:
    """Sync hidden mode (and optional tab index) when the user selects a nested sub-tab."""
    ordered_modes = [mode for _, mode in tab_mode_pairs]
    default_mode = ordered_modes[0] if ordered_modes else ""

    if tabs is not None:

        def _on_tabs_select(evt: gr.SelectData):
            mode = mode_from_tab_index(evt.index, ordered_modes, default_mode)
            if index_state is not None:
                return evt.index, mode
            return mode

        outputs: list = [index_state, state] if index_state is not None else [state]
        tabs.select(_on_tabs_select, outputs=outputs)

    for i, (tab, mode) in enumerate(tab_mode_pairs):
        if index_state is not None:

            def _on_tab_select(idx: int = i, m: str = mode):
                return idx, m

            tab.select(_on_tab_select, outputs=[index_state, state])
        else:
            tab.select(lambda m=mode: m, outputs=[state])


def tabs_selected_update(mode: str, modes: list[str]) -> dict:
    """Return Gradio update dict for the tab index matching *mode*."""
    try:
        index = modes.index(mode)
    except ValueError:
        index = 0
    return gr.update(selected=index)
