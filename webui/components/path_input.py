"""Path input with native file picker + manual path entry."""

from __future__ import annotations

from dataclasses import dataclass

import gradio as gr


def _path_from_upload(upload: str | list[str] | None) -> str:
    if upload is None:
        return ""
    if isinstance(upload, list):
        return upload[0] if upload else ""
    return str(upload)


@dataclass
class PathInput:
    """Text field for server paths, paired with a file/directory picker."""

    text: gr.Textbox
    picker: gr.File

    @classmethod
    def build(
        cls,
        label: str,
        *,
        file_types: list[str] | None = None,
        directory: bool = False,
        placeholder: str = "",
    ) -> PathInput:
        hint = "选择文件夹" if directory else "选择文件"
        with gr.Row(equal_height=True):
            text = gr.Textbox(
                label=label,
                placeholder=placeholder or f"可手动输入路径，或点击右侧「{hint}」",
                scale=4,
            )
            picker = gr.File(
                label=hint,
                file_types=file_types,
                file_count="directory" if directory else "single",
                type="filepath",
                scale=1,
            )
        return cls(text=text, picker=picker)

    def wire(self) -> None:
        self.picker.change(
            lambda upload: _path_from_upload(upload),
            inputs=[self.picker],
            outputs=[self.text],
        )

    def input_component(self) -> gr.Textbox:
        return self.text
