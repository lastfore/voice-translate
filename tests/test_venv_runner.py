"""Tests for venv subprocess helpers."""

from __future__ import annotations

from pipeline.venv_runner import separator_cli_cmd


def test_separator_cli_cmd_uses_python_not_exe_shim() -> None:
    cmd = separator_cli_cmd("input.flac", "--model_filename", "model.ckpt")
    assert cmd[0].endswith("python.exe") or cmd[0].endswith("python")
    assert cmd[1] == "-c"
    assert "audio_separator.utils.cli" in cmd[2]
    assert cmd[3] == "input.flac"
    assert "audio-separator" not in cmd
