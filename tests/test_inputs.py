"""Tests for validate_stage_inputs, resolve_stage_inputs, validate_pipeline_chain."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import ConvertMode, SliceMode, StageName
from pipeline.store import ProjectStore


@pytest.fixture
def store_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectStore, str, Path]:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    root = tmp_path
    (root / "input").mkdir()
    (root / "output" / "separated").mkdir(parents=True)
    (root / "output" / "slices" / "proj").mkdir(parents=True)
    (root / "output" / "converted" / "proj").mkdir(parents=True)

    mix = root / "input" / "proj.flac"
    mix.write_bytes(b"mix")
    vocals = root / "output" / "separated" / "proj_(Vocals)_m.flac"
    vocals.write_bytes(b"v")
    inst = root / "output" / "separated" / "proj_(Instrumental)_m.flac"
    inst.write_bytes(b"i")
    ref = root / "input" / "ref.wav"
    ref.write_bytes(b"r")
    (root / "output" / "slices" / "proj" / "proj_slice_000.flac").write_bytes(b"s")
    (root / "output" / "slices" / "proj" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "output" / "converted" / "proj" / "proj_slice_000.flac").write_bytes(b"c")

    store = ProjectStore(root)
    store.create_project("proj", mix)
    return store, "proj", root


def test_validate_separate_requires_mix(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    store, _, _ = store_with_project
    ok, errors = store.validate_stage_inputs(StageName.SEPARATE, {})
    assert not ok
    assert any("mix_audio" in e for e in errors)


def test_validate_convert_full_track(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    store, pid, root = store_with_project
    vocals = root / "output" / "separated" / "proj_(Vocals)_m.flac"
    ref = root / "input" / "ref.wav"
    ok, errors = store.validate_stage_inputs(
        StageName.CONVERT,
        {
            "mode": ConvertMode.FULL_TRACK.value,
            "source_vocals": str(vocals),
            "reference": str(ref),
        },
    )
    assert ok, errors


def test_resolve_slice_without_separate_done(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    """Independent slice: resolve vocals from glob without separate.status == done."""
    store, pid, root = store_with_project
    project = store.get_project(pid)
    assert project.stages[StageName.SEPARATE].status.value == "not_run"

    inputs = store.resolve_stage_inputs(pid, StageName.SLICE)
    assert inputs.get("vocals")
    ok, errors = store.validate_stage_inputs(StageName.SLICE, inputs)
    assert ok, errors


def test_resolve_convert_slice_batch(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    store, pid, root = store_with_project
    ref = root / "input" / "ref.wav"
    inputs = store.resolve_stage_inputs(
        pid,
        StageName.CONVERT,
        {"reference": str(ref), "mode": ConvertMode.SLICE_BATCH.value},
    )
    ok, errors = store.validate_stage_inputs(StageName.CONVERT, inputs)
    assert ok, errors
    assert "slices_dir" in inputs or "manifest" in inputs


def test_validate_pipeline_chain_success(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    store, pid, root = store_with_project
    ref = root / "input" / "ref.wav"
    ok, plan = store.validate_pipeline_chain(
        pid,
        [StageName.SEPARATE, StageName.SLICE, StageName.CONVERT, StageName.MERGE],
        convert_mode=ConvertMode.SLICE_BATCH,
        slice_mode=SliceMode.VAD,
        reference=str(ref),
    )
    if not ok:
        assert isinstance(plan, list)
        pytest.fail(f"chain validation failed: {plan}")
    assert isinstance(plan, dict)
    assert "separate" in plan
    assert "merge" in plan


def test_suggest_next_stage(store_with_project: tuple[ProjectStore, str, Path]) -> None:
    store, pid, _ = store_with_project
    # Has vocals separated + slices + converted -> suggest merge
    assert store.suggest_next_stage(pid) == StageName.MERGE
