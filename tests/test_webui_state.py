"""Smoke tests for webui state bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

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
