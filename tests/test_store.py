"""Tests for pipeline.store ProjectStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import StageName, StageStatus
from pipeline.store import ProjectStore


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ProjectStore]:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir()
    (tmp_path / "output" / "separated").mkdir(parents=True)
    (tmp_path / "output" / "slices").mkdir(parents=True)
    (tmp_path / "output" / "converted").mkdir(parents=True)
    store = ProjectStore(tmp_path)
    return tmp_path, store


def test_create_and_get_project(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "input" / "upload.flac"
    audio.write_bytes(b"fake")

    project = store.create_project("mysong", audio, display_name="My Song")
    assert project.id == "mysong"
    assert project.display_name == "My Song"
    assert (root / "input" / "mysong.flac").is_file()

    loaded = store.get_project("mysong")
    assert loaded.display_name == "My Song"
    assert loaded.stages[StageName.SEPARATE].status == StageStatus.NOT_RUN


def test_create_duplicate_raises(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "a.flac"
    audio.write_bytes(b"x")
    store.create_project("dup", audio)
    with pytest.raises(ValueError, match="already exists"):
        store.create_project("dup", audio)


def test_update_stage(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "a.flac"
    audio.write_bytes(b"x")
    store.create_project("p1", audio)

    store.update_stage(
        "p1",
        StageName.SEPARATE,
        status=StageStatus.DONE,
        artifacts={"vocals": "output/separated/p1_(Vocals)_x.flac"},
    )
    project = store.get_project("p1")
    assert project.stages[StageName.SEPARATE].status == StageStatus.DONE
    assert "vocals" in project.stages[StageName.SEPARATE].artifacts


def test_scan_and_repair_from_slices(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    slice_dir = root / "output" / "slices" / "legacy"
    slice_dir.mkdir(parents=True)
    (slice_dir / "legacy_slice_000.flac").write_bytes(b"x")
    (slice_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    repaired = store.scan_and_repair()
    ids = {p.id for p in repaired}
    assert "legacy" in ids

    project = store.get_project("legacy")
    assert project.stages[StageName.SLICE].status == StageStatus.DONE


def test_scan_infers_separate_from_output(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    sep = root / "output" / "separated"
    (sep / "song_(Vocals)_model.flac").write_bytes(b"v")
    (root / "input" / "song.flac").write_bytes(b"m")

    store.create_project("song", root / "input" / "song.flac")
    project = store.get_project("song")
    updated = store._infer_stage_state(project)
    assert updated.stages[StageName.SEPARATE].status == StageStatus.DONE
