"""Tests for phoneme boundary refinement (P2/P4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_phoneme_align():
    script_path = ROOT / "scripts" / "phoneme_align.py"
    spec = importlib.util.spec_from_file_location("phoneme_align_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phoneme_mod():
    return _load_phoneme_align()


def test_remote_returns_not_implemented(phoneme_mod) -> None:
    audio = np.zeros(4410, dtype=np.float32)
    result = phoneme_mod.refine_boundary(
        mode="remote",
        audio=audio,
        sr=44100,
        next_line_text="测试",
        window_start_ms=0.0,
        window_end_ms=500.0,
        fallback=True,
        remote_url="http://example.com/align",
    )
    assert result.skipped
    assert result.reason == "remote_not_implemented"


def test_remote_missing_url(phoneme_mod) -> None:
    audio = np.zeros(4410, dtype=np.float32)
    result = phoneme_mod.refine_boundary(
        mode="remote",
        audio=audio,
        sr=44100,
        next_line_text="测试",
        window_start_ms=0.0,
        window_end_ms=500.0,
        fallback=True,
        remote_url="",
    )
    assert result.skipped
    assert result.reason == "remote_url_missing"


def test_local_cpu_mock_refines_fallback(phoneme_mod, monkeypatch) -> None:
    audio = np.zeros(44100, dtype=np.float32)

    def fake_align(_audio, _sr, _text, _start, _end):
        return 14920.0, ""

    monkeypatch.setattr(phoneme_mod, "align_boundary_local_with_retries", fake_align)
    result = phoneme_mod.refine_boundary(
        mode="local_cpu",
        audio=audio,
        sr=44100,
        next_line_text="下一句",
        window_start_ms=14500.0,
        window_end_ms=15050.0,
        fallback=True,
    )
    assert not result.skipped
    assert result.onset_ms == 14920.0
    assert result.method == "phoneme_local"


def test_local_cpu_skips_non_fallback_when_fallback_only(phoneme_mod) -> None:
    audio = np.zeros(4410, dtype=np.float32)
    result = phoneme_mod.refine_boundary(
        mode="local_cpu",
        audio=audio,
        sr=44100,
        next_line_text="下一句",
        window_start_ms=0.0,
        window_end_ms=500.0,
        fallback=False,
        fallback_only=True,
    )
    assert result.skipped
    assert result.reason == "not_fallback_boundary"


def test_align_boundary_local_empty_text_returns_reason(phoneme_mod) -> None:
    audio = np.zeros(4410, dtype=np.float32)
    onset, reason = phoneme_mod.align_boundary_local(audio, 44100, "  ", 0.0, 500.0)
    assert onset is None
    assert reason == "phoneme_align_empty_text"


def test_align_text_snippet_first_char(phoneme_mod) -> None:
    assert phoneme_mod.align_text_snippet("  我爱你") == "我"
    assert phoneme_mod.align_text_snippet("Hello world") == "H"
    assert phoneme_mod.align_text_snippet("") == ""


def test_align_text_snippet_first_word(phoneme_mod) -> None:
    assert phoneme_mod.align_text_snippet("Hello world", mode="first_word") == "Hello"
    assert phoneme_mod.align_text_snippet("  我爱你", mode="first_word") == "我爱你"


def test_align_text_snippet_full(phoneme_mod) -> None:
    assert phoneme_mod.align_text_snippet("  整句歌词", mode="full") == "整句歌词"


def test_align_boundary_local_with_retries_on_ctc_window(phoneme_mod, monkeypatch) -> None:
    attempts: list[str] = []

    def fake_impl(*_args, **_kwargs):
        attempts.append(_kwargs.get("split_size", ""))
        return None, "phoneme_align_ctc_window_too_short"

    monkeypatch.setattr(phoneme_mod, "_align_boundary_local_impl", fake_impl)
    audio = np.zeros(4410, dtype=np.float32)
    onset, reason = phoneme_mod.align_boundary_local_with_retries(
        audio, 44100, "测", 0.0, 500.0
    )
    assert onset is None
    assert reason == "phoneme_align_ctc_window_too_short"
    assert attempts == ["char", "char", "word"]
