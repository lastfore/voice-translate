"""Tests for per-slice override persistence."""

from __future__ import annotations

from pipeline.models import SliceMode
from pipeline.slice_overrides import (
    SliceOverrides,
    apply_slice_override,
    effective_params,
    merge_after_reslice,
)


def test_effective_params_merge_order() -> None:
    overrides = SliceOverrides(
        global_defaults={"semi_tone_shift": 0, "diffusion_steps": 40},
        slices={"slice_001": {"semi_tone_shift": 2}},
    )
    eff = effective_params("slice_001", overrides, {"diffusion_steps": 30})
    assert eff["semi_tone_shift"] == 2
    assert eff["diffusion_steps"] == 30


def test_merge_after_reslice_lrc_text_match() -> None:
    old = SliceOverrides(
        slices={"slice_000": {"semi_tone_shift": 3}},
    )
    old_manifest = {
        "slices": [
            {"id": "slice_000", "start_ms": 1000, "end_ms": 2000, "text": "hello"},
        ]
    }
    new_manifest = {
        "slices": [
            {"id": "slice_000", "start_ms": 1050, "end_ms": 2050, "text": "hello"},
        ]
    }
    merged = merge_after_reslice(
        old,
        new_manifest,
        mode=SliceMode.LRC.value,
        old_manifest=old_manifest,
    )
    assert merged.slices["slice_000"]["semi_tone_shift"] == 3
    assert not merged.orphans


def test_apply_slice_override_multiple_ids() -> None:
    base = SliceOverrides()
    updated = apply_slice_override(base, ["a", "b"], {"semi_tone_shift": 4})
    assert updated.slices["a"]["semi_tone_shift"] == 4
    assert updated.slices["b"]["semi_tone_shift"] == 4
