"""Unit tests for pipeline/stage_log.py — Phase 1."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.models import StageName
from pipeline.stage_log import (
    ParamLogGroups,
    StageLogWriter,
    build_param_groups,
    format_cmd_lines,
    pick_inputs,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


def test_build_param_groups_lrc_slice_excludes_vad(root: Path) -> None:
    """P1-TC-001: LRC slice mode must not include VAD-only params."""
    params = {
        "mode": "lrc",
        "vad_threshold": 0.45,
        "min_speech_ms": 250,
        "min_silence_ms": 500,
        "speech_pad_ms": 80,
    }
    groups = build_param_groups(StageName.SLICE, params, {"mode": "lrc"})
    all_keys = set(groups.wizard) | set(groups.advanced) | set(groups.defaulted)
    assert "vad_threshold" not in all_keys
    assert "min_speech_ms" not in all_keys
    assert "min_silence_ms" not in all_keys
    assert "speech_pad_ms" not in all_keys
    assert groups.mode.get("mode") == "lrc"


def test_build_param_groups_advanced_vs_defaulted(root: Path) -> None:
    """P1-TC-002: non-default params go to advanced; defaults to defaulted keys."""
    params = {
        "mode": "slice_batch",
        "length_adjust": 1.05,
        "skip_existing": True,
        "fp16": False,
        "diffusion_steps": 40,
        "inference_cfg_rate": 0.7,
        "auto_f0_adjust": True,
        "semi_tone_shift": 0,
        "limit": 0,
    }
    groups = build_param_groups(StageName.CONVERT, params, {"mode": "slice_batch"})
    assert groups.advanced.get("length_adjust") == 1.05
    assert groups.advanced.get("fp16") is False
    assert "skip_existing" in groups.defaulted
    assert "length_adjust" not in groups.defaulted


def test_stage_log_writer_section_order(root: Path) -> None:
    """P1-TC-003: [JOB] -> [INPUT] -> [PARAM] order is stable."""
    log_path = root / "projects_meta" / "song" / "logs" / "separate-abc.log"
    log_path.parent.mkdir(parents=True)
    file_lines: list[str] = []

    def _capture(event) -> None:
        if event.log_line:
            file_lines.append(event.log_line)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(event.log_line + "\n")

    writer = StageLogWriter(
        project_id="song",
        stage=StageName.SEPARATE,
        job_id="separate-abc",
        log_path=log_path,
        root=root,
        on_progress=_capture,
    )
    writer.job_header(queued_at="2026-07-29T15:30:01+08:00", created_at="2026-07-29T15:30:01+08:00")
    writer.inputs({"mix_audio": "input/song.flac"})
    writer.params(ParamLogGroups(mode={"model": "test.ckpt"}, wizard={"model": "test.ckpt"}))

    text = log_path.read_text(encoding="utf-8")
    job_idx = text.index("[JOB]")
    input_idx = text.index("[INPUT]")
    param_idx = text.index("[PARAM]")
    assert job_idx < input_idx < param_idx
    assert "[INPUT] mix_audio=" in text


def test_format_cmd_three_lines(root: Path) -> None:
    """P1-TC-004: cmd produces python, cwd, and argv lines."""
    log_path = root / "log.txt"
    captured: list[str] = []

    writer = StageLogWriter(
        project_id="song",
        stage=StageName.SEPARATE,
        job_id="separate-x",
        log_path=log_path,
        root=root,
        on_progress=lambda e: captured.append(e.log_line or ""),
    )
    argv = ["/venv/python.exe", "script.py", "--flag", "value"]
    writer.cmd(argv, cwd="D:/voice-translate", python="/venv/python.exe")

    cmd_lines = [ln for ln in captured if ln.startswith("[CMD]")]
    assert len(cmd_lines) == 3
    assert any("python=" in ln for ln in cmd_lines)
    assert any("cwd=" in ln for ln in cmd_lines)
    argv_line = next(ln for ln in cmd_lines if "argv:" in ln)
    assert "script.py --flag value" in argv_line


def test_format_cmd_lines_helper() -> None:
    lines = format_cmd_lines(["a", "b"], cwd="/root", python="/py")
    assert len(lines) == 3
    assert lines[2] == "[CMD] argv: a b"


def test_pick_inputs_convert_slice_batch(root: Path) -> None:
    inputs = {
        "source_vocals": "output/separated/song/vocals.flac",
        "reference": "input/ref.wav",
        "slices_dir": "output/slices/song/lrc",
        "manifest": "output/slices/song/lrc/manifest.json",
        "output_dir": "output/converted/song/lrc",
        "mode": "slice_batch",
    }
    picked = pick_inputs(StageName.CONVERT, inputs, {"mode": "slice_batch"}, root)
    assert picked["reference"] == "input/ref.wav"
    assert picked["slices_dir"] == "output/slices/song/lrc"
    assert "output_path" not in picked
