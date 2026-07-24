"""Generate Gradio controls from ``pipeline.stage_params`` schema."""

from __future__ import annotations

from dataclasses import dataclass, field

import gradio as gr

from pipeline.models import StageName
from pipeline.stage_params import (
    StageParam,
    merge_stage_params,
    params_for_stage,
    resolve_default,
    separator_model_comparison_markdown,
)


@dataclass
class StageParamPanel:
    stage: str
    components: dict[str, gr.Component] = field(default_factory=dict)
    keys: list[str] = field(default_factory=list)

    def input_components(self) -> list[gr.Component]:
        return [self.components[k] for k in self.keys]

    def values_to_dict(self, *values: object) -> dict[str, object]:
        return dict(zip(self.keys, values))

    def updates_from_saved(self, saved: dict[str, object] | None) -> list:
        if self.stage == "wizard":
            values = dict(saved or {})
            return [gr.update(value=values[k]) for k in self.keys]
        merged = merge_stage_params(self.stage, saved)  # type: ignore[arg-type]
        return [gr.update(value=merged[k]) for k in self.keys]


def _build_component(param: StageParam) -> gr.Component:
    info = param.description
    if param.param_type == "bool":
        return gr.Checkbox(label=param.label, value=bool(param.default), info=info)
    if param.param_type == "int":
        return gr.Number(
            label=param.label,
            value=int(param.default),
            precision=0,
            minimum=param.minimum,
            maximum=param.maximum,
            step=param.step or 1,
            info=info,
        )
    if param.param_type == "float":
        return gr.Number(
            label=param.label,
            value=float(param.default),
            minimum=param.minimum,
            maximum=param.maximum,
            step=param.step or 0.01,
            info=info,
        )
    if param.param_type == "choice":
        choices = list(param.choices or ())
        if param.choices_fn is not None:
            choices = param.choices_fn()
        default = resolve_default(param)
        return gr.Dropdown(
            label=param.label,
            choices=choices,
            value=default,
            info=info,
            allow_custom_value=True,
        )
    return gr.Textbox(label=param.label, value=str(param.default), info=info)


def _param_matches_filter(
    param: StageParam,
    *,
    vad_only: bool | None,
    slice_batch_only: bool | None,
    full_track_only: bool | None,
    keys: set[str] | None,
) -> bool:
    if keys is not None and param.key not in keys:
        return False
    if vad_only is True and not param.vad_only:
        return False
    if vad_only is False and param.vad_only:
        return False
    if slice_batch_only is True and not param.slice_batch_only:
        return False
    if slice_batch_only is False and param.slice_batch_only:
        return False
    if full_track_only is True and not param.full_track_only:
        return False
    if full_track_only is False and param.full_track_only:
        return False
    return True


def build_stage_param_panel(
    stage: str | StageName,
    *,
    wizard_only: bool = False,
    accordion_label: str = "高级参数",
    open: bool = False,
    vad_only: bool | None = None,
    slice_batch_only: bool | None = None,
    full_track_only: bool | None = None,
    keys: set[str] | None = None,
) -> StageParamPanel:
    stage_key = stage.value if isinstance(stage, StageName) else stage
    param_list = [
        p
        for p in params_for_stage(stage_key, wizard_only=wizard_only)
        if _param_matches_filter(
            p,
            vad_only=vad_only,
            slice_batch_only=slice_batch_only,
            full_track_only=full_track_only,
            keys=keys,
        )
    ]
    panel = StageParamPanel(stage=stage_key)
    if not param_list:
        return panel

    with gr.Accordion(accordion_label, open=open):
        for param in param_list:
            panel.components[param.key] = _build_component(param)
            panel.keys.append(param.key)
        if stage_key == StageName.SEPARATE.value:
            gr.Markdown(separator_model_comparison_markdown())
    return panel


def build_wizard_param_panels() -> StageParamPanel:
    """Combined wizard-only params from slice / convert / merge (+ separate model)."""
    combined = StageParamPanel(stage="wizard")
    sections = [
        (StageName.SEPARATE, "分离参数"),
        (StageName.SLICE, "切片参数 (VAD)"),
        (StageName.CONVERT, "转换参数"),
        (StageName.MERGE, "合并参数"),
    ]
    for stage, title in sections:
        params = params_for_stage(stage.value, wizard_only=True)
        if not params:
            continue
        with gr.Accordion(title, open=False):
            for param in params:
                if param.key in combined.components:
                    continue
                combined.components[param.key] = _build_component(param)
                combined.keys.append(param.key)
    return combined
