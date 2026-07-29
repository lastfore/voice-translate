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
        "boundary_mode": "onset_aligned",
        "search_margin_ms": 400,
        "onset_min_lead_silence_ms": 80,
        "min_slice_ms": 500,
        "vad_threshold": 0.45,
        "min_speech_ms": 250,
        "min_silence_ms": 500,
        "speech_pad_ms": 80,
    }
    groups = build_param_groups(StageName.SLICE, params, {"mode": "lrc"})
    all_keys = (
        set(groups.wizard)
        | set(groups.advanced)
        | set(groups.defaulted)
        | set(groups.slice_mode_params)
    )
    assert "vad_threshold" not in all_keys
    assert "min_speech_ms" not in all_keys
    assert "min_silence_ms" not in all_keys
    assert "speech_pad_ms" not in all_keys
    assert groups.mode.get("mode") == "lrc"
    assert groups.slice_mode_label == "lrc"
    assert groups.slice_mode_params.get("boundary_mode") == "onset_aligned"
    assert groups.slice_mode_params.get("search_margin_ms") == 400
    assert groups.slice_mode_params.get("onset_min_lead_silence_ms") == 80
    assert groups.slice_mode_params.get("min_slice_ms") == 500
    assert groups.slice_mode_params.get("onset_energy_threshold_db") == -40.0
    assert "boundary_mode" not in groups.wizard


def test_stage_log_writer_lrc_params_line(root: Path) -> None:
    captured: list[str] = []
    writer = StageLogWriter(
        project_id="song",
        stage=StageName.SLICE,
        job_id="slice-x",
        log_path=root / "slice.log",
        root=root,
        on_progress=lambda e: captured.append(e.log_line or ""),
    )
    groups = build_param_groups(
        StageName.SLICE,
        {
            "mode": "lrc",
            "search_margin_ms": 350,
            "onset_min_lead_silence_ms": 90,
        },
        {"mode": "lrc"},
    )
    writer.params(groups)

    lrc_line = next(line for line in captured if line.startswith("[PARAM] lrc:"))
    assert "boundary_mode=onset_aligned" in lrc_line
    assert "search_margin_ms=350" in lrc_line
    assert "onset_min_lead_silence_ms=90" in lrc_line
    assert "min_slice_ms=500" in lrc_line


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
