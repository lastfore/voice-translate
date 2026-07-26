"""Smoke tests for webui state bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import Project, StageName, StageRecord, StageStatus, utc_now_iso
from pipeline.store import ProjectStore
from webui import state


@pytest.fixture
def ui_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VOICE_TRANSLATE_ROOT", str(tmp_path))
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir(parents=True)
    return tmp_path


def test_refresh_and_create_project(ui_workspace: Path) -> None:
    audio = ui_workspace / "t.flac"
    audio.write_bytes(b"x")
    ok, msg = state.create_project_ui("demo", str(audio), None, "Demo Song")
    assert ok, msg
    summaries = state.refresh_projects()
    assert any(s["id"] == "demo" for s in summaries)


def test_load_project_defaults_empty() -> None:
    assert state.load_project_defaults(None) == {}


def test_project_choices_gradio_tuple_order() -> None:
    from webui.helpers import format_project_choice, project_choices

    summaries = [
        {
            "id": "demo",
            "display_name": "Demo Song",
            "stages": {"separate": "done", "slice": "not_run"},
        }
    ]
    choices = project_choices(summaries)
    assert choices == [(format_project_choice(summaries[0]), "demo")]


def test_load_project_defaults_prefers_slice_stage_mode(ui_workspace: Path) -> None:
    store = ProjectStore(ui_workspace)
    now = utc_now_iso()
    project = Project(id="demo", display_name="demo", created_at=now, updated_at=now)
    project.stages[StageName.SLICE] = StageRecord(
        status=StageStatus.DONE,
        params={"mode": "vad", "active_slice_mode": "vad"},
    )
    project.stages[StageName.CONVERT] = StageRecord(
        status=StageStatus.DONE,
        params={"active_slice_mode": "lrc"},
    )
    store.save_project(project)

    defaults = state.load_project_defaults("demo")
    assert defaults["slice_mode"] == "vad"
