"""Tests for stage param panel layout (bool promotion)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.models import StageName
from pipeline.stage_params import params_for_stage, partition_bool_params


def test_merge_bool_params_ordered_before_numeric() -> None:
    params = params_for_stage(StageName.MERGE.value)
    bool_params, other_params = partition_bool_params(params)
    bool_keys = {p.key for p in bool_params}
    assert {"clean_instrumental", "include_backing", "skip_mastering"}.issubset(bool_keys)
    assert {"vocals_gain_db", "instrumental_gain_db", "backing_gain_db"}.issubset({p.key for p in other_params})


def test_convert_bool_params_partitioned() -> None:
    params = params_for_stage(StageName.CONVERT.value)
    bool_params, other_params = partition_bool_params(params)
    bool_keys = {p.key for p in bool_params}
    assert bool_keys == {"auto_f0_adjust", "fp16", "skip_existing"}
    assert "diffusion_steps" in {p.key for p in other_params}


def test_wizard_convert_bool_partitioned() -> None:
    params = params_for_stage(StageName.CONVERT.value, wizard_only=True)
    bool_params, other_params = partition_bool_params(params)
    assert [p.key for p in bool_params] == ["auto_f0_adjust"]
    assert {p.key for p in other_params} >= {"diffusion_steps", "inference_cfg_rate", "semi_tone_shift"}


if __name__ == "__main__":
    test_merge_bool_params_ordered_before_numeric()
    test_convert_bool_params_partitioned()
    test_wizard_convert_bool_partitioned()
    print("OK")
