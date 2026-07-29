"""Stage parameter schema endpoint — migrated from webui/components/stage_params.py.

Schema comes from ``pipeline/stage_params.py`` (the single source of truth for
defaults). It only changes when the process restarts, so responses are cached
with ``functools.lru_cache`` keyed on the filter combination (docs §5.2).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from pipeline.models import StageName
from pipeline.stage_params import (
    SEPARATOR_MODEL_PROFILES,
    StageParam,
    list_separator_models,
    params_for_stage,
    resolve_default,
)

router = APIRouter(prefix="/api/params", tags=["params"])


def _param_to_dict(param: StageParam) -> dict[str, Any]:
    choices: list[str] | None = None
    if param.choices_fn is not None:
        choices = list(param.choices_fn())
    elif param.choices is not None:
        choices = list(param.choices)
    return {
        "key": param.key,
        "label": param.label,
        "description": param.description,
        "param_type": param.param_type,
        "default": resolve_default(param),
        "choices": choices,
        "minimum": param.minimum,
        "maximum": param.maximum,
        "step": param.step,
        "wizard": param.wizard,
        "vad_only": param.vad_only,
        "lrc_only": param.lrc_only,
        "slice_batch_only": param.slice_batch_only,
        "full_track_only": param.full_track_only,
    }


@lru_cache(maxsize=16)
def _build_schema_cached(
    stage: str,
    vad_only: bool,
    lrc_only: bool,
    slice_batch_only: bool,
    keys: tuple[str, ...] | None,
) -> dict[str, Any]:
    items = params_for_stage(stage)
    if vad_only:
        items = [p for p in items if p.vad_only]
    if lrc_only:
        items = [p for p in items if p.lrc_only]
    if slice_batch_only:
        items = [p for p in items if p.slice_batch_only]
    if keys:
        key_set = set(keys)
        items = [p for p in items if p.key in key_set]
    return {
        "stage": stage,
        "params": [_param_to_dict(p) for p in items],
        "sections": [],
    }


def warm_schema_cache() -> None:
    """Pre-populate the cache for the plain (unfiltered) schema of every stage."""
    for stage in StageName:
        _build_schema_cached(stage.value, False, False, False, None)


def clear_schema_cache() -> None:
    """Test helper — drop cached schema responses."""
    _build_schema_cached.cache_clear()


@router.get("/schema")
def get_schema(
    stage: str = Query(...),
    vad_only: bool = False,
    lrc_only: bool = False,
    slice_batch_only: bool = False,
    keys: str | None = None,
) -> dict[str, Any]:
    try:
        StageName(stage)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"unknown stage: {stage}") from exc

    key_tuple = tuple(sorted(k.strip() for k in keys.split(",") if k.strip())) if keys else None
    return _build_schema_cached(stage, vad_only, lrc_only, slice_batch_only, key_tuple)


@router.get("/separator-models")
def separator_models() -> dict[str, Any]:
    """Installed models + comparison profiles (migration doc §5.2)."""
    installed = set(list_separator_models())
    profiles = {
        name: {**profile, "installed": name in installed}
        for name, profile in SEPARATOR_MODEL_PROFILES.items()
    }
    for name in sorted(installed):
        if name not in profiles:
            profiles[name] = {"installed": True, "note": "已安装，详见 audio-separator 文档"}
    return {"models": sorted(installed), "profiles": profiles}
