"""Tests for stage parameter schema."""

from __future__ import annotations

from pipeline.models import StageName
from pipeline.stage_params import (
    collect_params,
    default_stage_params,
    merge_stage_params,
    merge_wizard_params,
    params_for_stage,
)


def test_default_stage_params_include_descriptions() -> None:
    for stage in StageName:
        for param in params_for_stage(stage.value):
            assert param.label
            assert param.description


def test_merge_stage_params_fills_defaults() -> None:
    merged = merge_stage_params(StageName.CONVERT.value, {"diffusion_steps": 25})
    assert merged["diffusion_steps"] == 25
    assert merged["inference_cfg_rate"] == 0.7


def test_collect_params_skips_vad_in_lrc_mode() -> None:
    values = default_stage_params(StageName.SLICE.value)
    values["vad_threshold"] = 0.2
    out = collect_params(StageName.SLICE.value, values, slice_mode="lrc")
    assert "vad_threshold" not in out
    assert "boundary_mode" in out
    assert "onset_energy_threshold_db" in out


def test_collect_params_skips_lrc_in_vad_mode() -> None:
    values = default_stage_params(StageName.SLICE.value)
    values["search_margin_ms"] = 300
    out = collect_params(StageName.SLICE.value, values, slice_mode="vad")
    assert "search_margin_ms" not in out
    assert "vad_threshold" in out


def test_collect_params_keeps_vad_in_vad_mode() -> None:
    values = default_stage_params(StageName.SLICE.value)
    values["vad_threshold"] = 0.2
    out = collect_params(StageName.SLICE.value, values, slice_mode="vad")
    assert out["vad_threshold"] == 0.2


def test_collect_params_skips_batch_only_in_full_track_mode() -> None:
    values = default_stage_params(StageName.CONVERT.value)
    values["limit"] = 3
    out = collect_params(StageName.CONVERT.value, values, convert_mode="full_track")
    assert "limit" not in out
    assert "skip_existing" not in out


def test_collect_params_keeps_batch_only_in_slice_batch_mode() -> None:
    values = default_stage_params(StageName.CONVERT.value)
    values["limit"] = 3
    out = collect_params(StageName.CONVERT.value, values, convert_mode="slice_batch")
    assert out["limit"] == 3


def test_wizard_params_merge_all_stages() -> None:
    saved = {
        StageName.CONVERT.value: {"diffusion_steps": 30},
        StageName.MERGE.value: {"vocals_gain_db": 1.5},
    }
    merged = merge_wizard_params(saved)
    assert merged["diffusion_steps"] == 30
    assert merged["vocals_gain_db"] == 1.5
    assert "model" in merged
