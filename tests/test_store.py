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


def test_collect_project_artifacts(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "input" / "upload.flac"
    audio.write_bytes(b"fake")
    store.create_project("foo", audio)
    (root / "output" / "separated" / "foo_(Vocals)_x.flac").write_bytes(b"v")
    (root / "output" / "slices" / "foo" / "lrc").mkdir(parents=True)
    (root / "output" / "slices" / "foo" / "lrc" / "manifest.json").write_text(
        '{"slices": []}', encoding="utf-8"
    )

    from pipeline.paths import collect_project_artifacts, paths_for_scope

    group = collect_project_artifacts("foo")
    assert group.metadata
    assert any("slices" in str(p) for p in group.artifacts)
    assert any(p.name.endswith(".flac") for p in group.inputs)

    meta_paths = paths_for_scope(group, "metadata")
    assert meta_paths and all("projects" in str(p) for p in meta_paths)

    all_paths = paths_for_scope(group, "all")
    assert any("input" in str(p) for p in all_paths)


def test_delete_project_scopes(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "input" / "upload.flac"
    audio.write_bytes(b"fake")
    store.create_project("foo", audio)
    (root / "input" / "foo.lrc").write_text("lrc", encoding="utf-8")
    (root / "output" / "separated" / "foo_(Vocals)_x.flac").write_bytes(b"v")
    slices = root / "output" / "slices" / "foo"
    slices.mkdir(parents=True)
    (slices / "slice.flac").write_bytes(b"s")

    store.delete_project("foo", scope="metadata")
    assert not (root / "output" / ".projects" / "foo").exists()
    assert (root / "input" / "foo.flac").is_file()
    assert slices.is_dir()

    store.create_project("foo", root / "input" / "foo.flac")
    store.delete_project("foo", scope="artifacts")
    assert not slices.exists()
    assert (root / "input" / "foo.flac").is_file()

    store.create_project("foo", root / "input" / "foo.flac")
    deleted = store.delete_project("foo", scope="all")
    assert deleted
    assert not (root / "input" / "foo.flac").exists()
    assert not (root / "output" / "separated" / "foo_(Vocals)_x.flac").exists()


def test_preview_project_deletion(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "a.flac"
    audio.write_bytes(b"x")
    store.create_project("p1", audio)
    rows = store.preview_project_deletion("p1", "all")
    assert rows
    assert any(kind == "input" for kind, _ in rows)


def test_resolve_convert_inputs_prefers_slice_stage_mode(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)
    vad_dir = root / "output" / "slices" / "song" / "vad"
    vad_dir.mkdir(parents=True)
    (vad_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    project = store.get_project("song")
    project.stages[StageName.SLICE].params = {
        "mode": "vad",
        "active_slice_mode": "vad",
    }
    project.stages[StageName.CONVERT].params = {
        "mode": "full_track",
        "active_slice_mode": "lrc",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs(
        "song",
        StageName.CONVERT,
        {"mode": "slice_batch", "slice_mode": "vad", "active_slice_mode": "vad"},
    )
    assert resolved["mode"] == "slice_batch"
    assert resolved["slice_mode"] == "vad"
    assert resolved["slices_dir"].replace("\\", "/").endswith("slices/song/vad")
    assert resolved["output_dir"].replace("\\", "/").endswith("converted/song/vad")


def test_resolve_convert_output_dir_follows_explicit_slice_mode(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)
    vad_dir = root / "output" / "slices" / "song" / "vad"
    lrc_dir = root / "output" / "slices" / "song" / "lrc"
    vad_dir.mkdir(parents=True)
    lrc_dir.mkdir(parents=True)
    (vad_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")
    (lrc_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    project = store.get_project("song")
    project.stages[StageName.CONVERT].inputs = {
        "slices_dir": "output/slices/song/vad",
        "output_dir": "output/converted/song/lrc",
        "slice_mode": "lrc",
        "active_slice_mode": "lrc",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs(
        "song",
        StageName.CONVERT,
        {"mode": "slice_batch", "slice_mode": "lrc", "active_slice_mode": "lrc"},
    )
    assert resolved["slices_dir"].replace("\\", "/").endswith("slices/song/lrc")
    assert resolved["output_dir"].replace("\\", "/").endswith("converted/song/lrc")
    assert resolved["slice_mode"] == "lrc"


def test_resolve_convert_manifest_follows_slices_dir_mode(workspace: tuple[Path, ProjectStore]) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)
    lrc_dir = root / "output" / "slices" / "song" / "lrc"
    vad_dir = root / "output" / "slices" / "song" / "vad"
    lrc_dir.mkdir(parents=True)
    vad_dir.mkdir(parents=True)
    (lrc_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")
    (vad_dir / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    project = store.get_project("song")
    project.stages[StageName.CONVERT].inputs = {
        "slices_dir": "output/slices/song/vad",
        "manifest": "output/slices/song/lrc/manifest.json",
        "output_dir": "output/converted/song/lrc",
        "slice_mode": "lrc",
        "active_slice_mode": "lrc",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs("song", StageName.CONVERT, {"mode": "slice_batch"})
    assert resolved["slices_dir"].replace("\\", "/").endswith("slices/song/vad")
    assert resolved["manifest"].replace("\\", "/").endswith("slices/song/vad/manifest.json")
    assert resolved["output_dir"].replace("\\", "/").endswith("converted/song/vad")
    assert resolved["slice_mode"] == "vad"


def test_active_slice_mode_prefers_vad_when_both_artifact_sets_exist(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    lrc = root / "input" / "song.lrc"
    lrc.write_text("[00:00.00]x", encoding="utf-8")
    store.create_project("song", audio, lrc_path=lrc)

    project = store.get_project("song")
    project.stages[StageName.SLICE].artifacts = {
        "lrc": {"slices_dir": "output/slices/song/lrc"},
        "vad": {"slices_dir": "output/slices/song/vad"},
    }
    project.stages[StageName.SLICE].params = {"mode": "vad", "active_slice_mode": "vad"}
    store.save_project(project)

    assert store._active_slice_mode(project) == "vad"


def test_resolve_merge_original_vocals_from_instrumental_override(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "mysong.flac"
    audio.write_bytes(b"x")
    store.create_project("mysong", audio)

    sep = root / "output" / "separated"
    sep.mkdir(parents=True, exist_ok=True)
    test_vocals = sep / "test_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
    test_other = sep / "test_(other)_mel_band_roformer_kim_ft_unwa.flac"
    test_vocals.write_bytes(b"v")
    test_other.write_bytes(b"i")

    converted = root / "output" / "converted" / "mysong" / "vad"
    converted.mkdir(parents=True)
    (converted / "slice_000.flac").write_bytes(b"c")

    project = store.get_project("mysong")
    project.stages[StageName.MERGE].inputs = {
        "original_vocals": "output/separated/mysong_(vocals)_mel_band_roformer_kim_ft_unwa.flac",
        "instrumental": "output/separated/test_(other)_mel_band_roformer_kim_ft_unwa.flac",
        "vocals": "output/converted/mysong/vad",
        "merge_mode": "slice_stitch",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs(
        "mysong",
        StageName.MERGE,
        {
            "merge_mode": "slice_stitch",
            "instrumental": "output/separated/test_(other)_mel_band_roformer_kim_ft_unwa.flac",
        },
    )
    assert resolved["original_vocals"].replace("\\", "/").endswith(
        "output/separated/test_(vocals)_mel_band_roformer_kim_ft_unwa.flac"
    )


def test_resolve_merge_slice_mode_follows_vad_converted_dir(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)

    converted_vad = root / "output" / "converted" / "song" / "vad"
    converted_vad.mkdir(parents=True)
    (converted_vad / "slice_000.flac").write_bytes(b"c")
    slices_lrc = root / "output" / "slices" / "song" / "lrc"
    slices_vad = root / "output" / "slices" / "song" / "vad"
    slices_lrc.mkdir(parents=True)
    slices_vad.mkdir(parents=True)
    (slices_lrc / "manifest.json").write_text('{"slices": []}', encoding="utf-8")
    (slices_vad / "manifest.json").write_text('{"slices": []}', encoding="utf-8")

    project = store.get_project("song")
    project.stages[StageName.SLICE].params = {"mode": "vad", "active_slice_mode": "vad"}
    project.stages[StageName.CONVERT].artifacts = {
        "vad": {"converted_dir": "output/converted/song/vad"},
    }
    project.stages[StageName.MERGE].inputs = {
        "vocals": "output/converted/song/vad",
        "slices_dir": "output/slices/song/lrc",
        "manifest": "output/slices/song/lrc/manifest.json",
        "slice_mode": "lrc",
        "active_slice_mode": "lrc",
        "merge_mode": "slice_stitch",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs(
        "song",
        StageName.MERGE,
        {"merge_mode": "slice_stitch", "slice_mode": "vad", "active_slice_mode": "vad"},
    )
    assert resolved["slice_mode"] == "vad"
    assert resolved["slices_dir"].replace("\\", "/").endswith("slices/song/vad")
    assert resolved["manifest"].replace("\\", "/").endswith("slices/song/vad/manifest.json")
    assert resolved["output_dir"].replace("\\", "/").endswith("merged/song/vad")


def test_resolve_merge_whole_track_output_dir(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)

    full = root / "output" / "converted" / "song" / "full" / "full.flac"
    full.parent.mkdir(parents=True)
    full.write_bytes(b"c")
    inst = root / "output" / "separated" / "song_(Instrumental)_m.flac"
    inst.parent.mkdir(parents=True, exist_ok=True)
    inst.write_bytes(b"i")

    resolved = store.resolve_stage_inputs(
        "song",
        StageName.MERGE,
        {"merge_mode": "whole_track"},
    )
    assert resolved["output_dir"].replace("\\", "/").endswith("merged/song/full")
    assert resolved["merge_mode"] == "whole_track"


def test_resolve_slice_output_dir_follows_mode_override(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    lrc = root / "input" / "song.lrc"
    lrc.write_text("[00:00.00]x", encoding="utf-8")
    store.create_project("song", audio, lrc_path=lrc)

    project = store.get_project("song")
    project.stages[StageName.SLICE].inputs = {
        "mode": "vad",
        "output_dir": "output/slices/song/vad",
    }
    store.save_project(project)

    resolved = store.resolve_stage_inputs("song", StageName.SLICE, {"mode": "lrc"})
    assert resolved["mode"] == "lrc"
    assert resolved["output_dir"].replace("\\", "/").endswith("slices/song/lrc")


def test_active_slice_mode_honors_active_slice_mode_override(
    workspace: tuple[Path, ProjectStore],
) -> None:
    root, store = workspace
    audio = root / "input" / "song.flac"
    audio.write_bytes(b"x")
    store.create_project("song", audio)
    project = store.get_project("song")
    project.stages[StageName.SLICE].params = {"mode": "vad", "active_slice_mode": "vad"}
    store.save_project(project)

    assert store._active_slice_mode(project, {"active_slice_mode": "lrc"}) == "lrc"
