"""End-to-end tests (mocked stages, no GPU)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.models import ConvertMode, SliceMode, StageName, StageStatus
from pipeline.queue import GpuJobQueue
from pipeline.runner import StageRunner
from pipeline.stages.convert import ConvertResult
from pipeline.stages.merge import MergeResult
from pipeline.stages.separate import SeparateResult
from pipeline.stages.slice import SliceResult
from pipeline.store import ProjectStore


@pytest.fixture
def e2e_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    for sub in (
        "input",
        "output/separated",
        "output/slices",
        "output/converted",
        "output/merged",
    ):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_project(root: Path, store: ProjectStore, pid: str = "song") -> None:
    audio = root / "input" / f"{pid}.flac"
    audio.write_bytes(b"mix")
    store.create_project(pid, audio, display_name=pid.title())


def test_e2e04_legacy_slices_import(e2e_root: Path) -> None:
    """E2E-04: only output/slices/test/ -> auto project.json."""
    store = ProjectStore(e2e_root)
    sdir = e2e_root / "output" / "slices" / "test"
    sdir.mkdir(parents=True)
    (sdir / "test_slice_000.flac").write_bytes(b"s")
    (sdir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    projects = store.scan_and_repair()
    assert any(p.id == "test" for p in projects)
    project = store.get_project("test")
    assert project.stages[StageName.SLICE].status == StageStatus.DONE


def test_e2e_legacy_flat_merged_single_project(e2e_root: Path) -> None:
    store = ProjectStore(e2e_root)
    _make_project(e2e_root, store, "oldsong")
    sep = e2e_root / "output" / "separated"
    (sep / "oldsong_(Vocals)_m.flac").write_bytes(b"v")
    (sep / "oldsong_(Instrumental)_m.flac").write_bytes(b"i")
    (e2e_root / "output" / "merged" / "mixed.flac").write_bytes(b"mixed")

    store.scan_and_repair()
    project = store.get_project("oldsong")
    merge = project.stages[StageName.MERGE]
    assert merge.status == StageStatus.DONE
    assert merge.artifacts.get("legacy_flat") is True
    assert merge.artifacts.get("mixed", "").endswith("output/merged/mixed.flac".replace("/", "\\")) or (
        "merged/mixed.flac" in merge.artifacts.get("mixed", "")
    )


def test_e2e_discover_from_separated_stems(e2e_root: Path) -> None:
    store = ProjectStore(e2e_root)
    (e2e_root / "input" / "hidden.flac").write_bytes(b"x")
    (e2e_root / "output" / "separated" / "hidden_(Vocals)_model.flac").write_bytes(b"v")

    store.scan_and_repair()
    assert store.get_project("hidden").stages[StageName.SEPARATE].status == StageStatus.DONE


@patch("pipeline.runner.run_merge")
@patch("pipeline.runner.run_convert")
@patch("pipeline.runner.run_slice")
@patch("pipeline.runner.run_separate")
def test_e2e01_full_pipeline_mocked(
    mock_sep,
    mock_slice,
    mock_convert,
    mock_merge,
    e2e_root: Path,
) -> None:
    """E2E-01: create -> separate -> full_track convert -> merge(quick)."""
    store = ProjectStore(e2e_root)
    runner = StageRunner(store, GpuJobQueue())
    _make_project(e2e_root, store)

    pid = "song"
    sep_v = e2e_root / "output" / "separated" / f"{pid}_(Vocals)_m.flac"
    sep_i = e2e_root / "output" / "separated" / f"{pid}_(Instrumental)_m.flac"
    sep_v.write_bytes(b"v")
    sep_i.write_bytes(b"i")
    ref = e2e_root / "input" / "ref.wav"
    ref.write_bytes(b"r")
    full = e2e_root / "output" / "converted" / pid / "full.flac"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"full")
    merged = e2e_root / "output" / "merged" / pid
    merged.mkdir(parents=True, exist_ok=True)

    mock_sep.return_value = SeparateResult(vocals=sep_v, instrumental=sep_i)
    mock_slice.return_value = SliceResult(
        e2e_root / "output" / "slices" / pid,
        e2e_root / "output" / "slices" / pid / "manifest.json",
        1,
    )
    mock_convert.return_value = ConvertResult(
        mode=ConvertMode.FULL_TRACK.value,
        converted_dir=full.parent,
        full_track=full,
        converted_count=1,
        total_count=1,
    )
    mixed = merged / "mixed.flac"
    mock_merge.return_value = MergeResult(
        vocals=merged / "vocals.flac",
        mixed=mixed,
        merged_dir=merged,
    )
    mixed.write_bytes(b"m")
    (merged / "vocals.flac").write_bytes(b"v")

    for stage, params in (
        (StageName.SEPARATE, {"mix_audio": str(e2e_root / "input" / "song.flac")}),
        (StageName.CONVERT, {"mode": "full_track", "reference": str(ref)}),
        (StageName.MERGE, {"profile": "quick", "vocals": str(full), "instrumental": str(sep_i)}),
    ):
        result = runner.run_stage(pid, stage, params)
        assert result.success, f"{stage.value}: {result.error}"

    project = store.get_project(pid)
    assert project.stages[StageName.SEPARATE].status == StageStatus.DONE
    assert project.stages[StageName.CONVERT].status == StageStatus.DONE
    assert project.stages[StageName.MERGE].status == StageStatus.DONE
    assert mixed.is_file()


@patch("pipeline.runner.run_convert")
def test_e2e05_batch_queue_two_projects(mock_convert, e2e_root: Path) -> None:
    store = ProjectStore(e2e_root)
    runner = StageRunner(store, GpuJobQueue())
    _make_project(e2e_root, store, "a")
    _make_project(e2e_root, store, "b")

    for pid in ("a", "b"):
        d = e2e_root / "output" / "converted" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}_slice_000.flac").write_bytes(b"c")

    ref = e2e_root / "input" / "ref.wav"
    ref.write_bytes(b"r")

    def _fake_convert(project_id, **kwargs):
        out = e2e_root / "output" / "converted" / project_id
        return ConvertResult(
            mode=ConvertMode.SLICE_BATCH.value,
            converted_dir=out,
            converted_count=1,
            total_count=1,
        )

    mock_convert.side_effect = _fake_convert

    for pid in ("a", "b"):
        sdir = e2e_root / "output" / "slices" / pid
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / f"{pid}_slice_000.flac").write_bytes(b"s")
        (sdir / "manifest.json").write_text("{}", encoding="utf-8")
        result = runner.run_stage(
            pid,
            StageName.CONVERT,
            {
                "reference": str(ref),
                "slices_dir": str(sdir),
                "mode": ConvertMode.SLICE_BATCH.value,
            },
        )
        assert result.success, result.error

    assert store.get_project("a").stages[StageName.CONVERT].status == StageStatus.DONE
    assert store.get_project("b").stages[StageName.CONVERT].status == StageStatus.DONE
