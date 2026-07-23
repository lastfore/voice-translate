"""Tests for StageRunner (mocked stage execution)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.models import StageName, StageStatus
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.stages.merge import MergeResult
from pipeline.stages.separate import SeparateResult
from pipeline.stages.slice import SliceResult
from pipeline.store import ProjectStore


@pytest.fixture
def runner_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectStore, StageRunner, str, Path]:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    root = tmp_path
    (root / "input").mkdir()
    (root / "output" / "separated").mkdir(parents=True)
    mix = root / "input" / "song.flac"
    mix.write_bytes(b"audio")

    store = ProjectStore(root)
    store.create_project("song", mix)
    runner = StageRunner(store, GpuJobQueue())
    return store, runner, "song", root


def test_run_slice_stage_mocked(runner_workspace: tuple[ProjectStore, StageRunner, str, Path]) -> None:
    store, runner, pid, root = runner_workspace
    vocals = root / "output" / "separated" / "song_(Vocals)_m.flac"
    vocals.write_bytes(b"v")
    slices_dir = root / "output" / "slices" / pid
    manifest = slices_dir / "manifest.json"

    fake = SliceResult(slices_dir=slices_dir, manifest=manifest, slice_count=3)
    with patch("pipeline.runner.run_slice", return_value=fake):
        result = runner.run_stage(pid, StageName.SLICE, {"vocals": str(vocals)})

    assert result.success
    project = store.get_project(pid)
    assert project.stages[StageName.SLICE].status == StageStatus.DONE
    assert project.stages[StageName.SLICE].artifacts.get("slices_dir")


def test_run_separate_validation_fails(runner_workspace: tuple[ProjectStore, StageRunner, str, Path]) -> None:
    _, runner, pid, _ = runner_workspace
    result = runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": "/nonexistent.flac"})
    assert not result.success
    assert result.error


def test_run_merge_mocked(runner_workspace: tuple[ProjectStore, StageRunner, str, Path]) -> None:
    store, runner, pid, root = runner_workspace
    vocals = root / "output" / "converted" / pid / "full.flac"
    vocals.parent.mkdir(parents=True)
    vocals.write_bytes(b"v")
    inst = root / "output" / "separated" / "song_(Instrumental)_m.flac"
    inst.write_bytes(b"i")
    merged = root / "output" / "merged" / pid

    fake = MergeResult(
        vocals=merged / "vocals.flac",
        mixed=merged / "mixed.flac",
        merged_dir=merged,
    )
    merged.mkdir(parents=True, exist_ok=True)
    fake.vocals.write_bytes(b"x")
    fake.mixed.write_bytes(b"x")

    with patch("pipeline.runner.run_merge", return_value=fake):
        result = runner.run_stage(
            pid,
            StageName.MERGE,
            {"vocals": str(vocals), "instrumental": str(inst), "profile": "quick"},
        )

    assert result.success
    assert store.get_project(pid).stages[StageName.MERGE].status == StageStatus.DONE


def test_run_separate_mocked(runner_workspace: tuple[ProjectStore, StageRunner, str, Path]) -> None:
    store, runner, pid, root = runner_workspace
    mix = root / "input" / "song.flac"
    vocals = root / "output" / "separated" / "song_(Vocals)_m.flac"
    inst = root / "output" / "separated" / "song_(Instrumental)_m.flac"
    fake = SeparateResult(vocals=vocals, instrumental=inst)

    with patch("pipeline.runner.run_separate", return_value=fake):
        result = runner.run_stage(pid, StageName.SEPARATE, {"mix_audio": str(mix)})

    assert result.success
    project = store.get_project(pid)
    assert project.stages[StageName.SEPARATE].status == StageStatus.DONE
    assert "vocals" in project.stages[StageName.SEPARATE].artifacts
