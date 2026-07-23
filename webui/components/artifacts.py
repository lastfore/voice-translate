"""Reusable artifact preview helpers."""

from __future__ import annotations

import gradio as gr

from webui.helpers import audio_if_exists, first_audio_in_dir


def artifact_audio_row(label: str) -> gr.Audio:
    return gr.Audio(label=label, type="filepath", interactive=False)


def update_separate_artifacts(vocals_path: str | None, inst_path: str | None) -> tuple:
    return audio_if_exists(vocals_path), audio_if_exists(inst_path)


def update_convert_artifacts(
    mode: str,
    full_track: str | None,
    converted_dir: str | None,
) -> tuple:
    if mode == "full_track":
        return audio_if_exists(full_track), None, None, None, None
    previews = first_audio_in_dir(converted_dir, limit=3)
    while len(previews) < 3:
        previews.append(None)
    return previews[0], previews[1], previews[2], None, None


def update_merge_artifacts(vocals: str | None, mixed: str | None) -> tuple:
    return audio_if_exists(vocals), audio_if_exists(mixed)
