"""Smoke tests for webui module imports."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("gradio")


@pytest.fixture(autouse=True)
def _clear_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)


def test_build_app_imports() -> None:
    from webui.pipeline_app import build_app

    app = build_app()
    assert app is not None


def test_state_helpers() -> None:
    from webui.helpers import format_stage_icons

    text = format_stage_icons({"separate": "done", "slice": "not_run"})
    assert "●分离" in text
    assert "○切片" in text
