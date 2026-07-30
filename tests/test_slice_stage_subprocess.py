"""Slice stage subprocess isolation for phoneme_align_mode=local_cpu."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.stages.slice import _phoneme_align_needs_subprocess, run_slice


def test_phoneme_align_needs_subprocess_only_local_cpu() -> None:
    assert _phoneme_align_needs_subprocess("local_cpu") is True
    assert _phoneme_align_needs_subprocess("off") is False
    assert _phoneme_align_needs_subprocess("remote") is False


@pytest.fixture
def lrc_slice_assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    import numpy as np
    import soundfile as sf

    lrc = tmp_path / "test.lrc"
    lrc.write_text("[00:00.00]hello\n[00:01.00]world\n", encoding="utf-8")
    vocals = tmp_path / "vocals.flac"
    sr = 22050
    audio = np.zeros(sr * 2, dtype=np.float32)
    sf.write(str(vocals), audio, sr)
    out_dir = tmp_path / "slices"
    return lrc, vocals, out_dir


def test_local_cpu_uses_subprocess_not_inprocess(lrc_slice_assets: tuple[Path, Path, Path]) -> None:
    lrc, vocals, out_dir = lrc_slice_assets
    manifest = {
        "aligned_boundary_count": 1,
        "valley_boundary_count": 0,
        "fallback_boundary_count": 0,
        "phoneme_align_applied_count": 1,
        "phoneme_align_skip_counts": {},
        "boundary_diagnostics": [],
        "slices": [{"id": "slice_000"}],
    }

    fake_flac = out_dir / "proj_slice_000.flac"
    fake_manifest = out_dir / "manifest.json"

    def _fake_subprocess(cmd, cwd=None, env=None, on_line=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        fake_flac.write_bytes(b"")
        fake_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        if on_line:
            on_line("Wrote 1 slices")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    mock_mod = MagicMock()

    with (
        patch("pipeline.stages.slice.run_subprocess", side_effect=_fake_subprocess) as mock_run,
        patch("pipeline.stages.slice._load_script_module", return_value=mock_mod) as mock_load,
    ):
        result = run_slice(
            "proj",
            vocals,
            out_dir,
            mode="lrc",
            lrc_path=lrc,
            phoneme_align_mode="local_cpu",
        )

    mock_run.assert_called_once()
    mock_load.assert_not_called()
    mock_mod.slice_vocals_lrc.assert_not_called()
    assert result.slice_count == 1
    assert result.manifest == fake_manifest


def test_off_mode_stays_inprocess(lrc_slice_assets: tuple[Path, Path, Path]) -> None:
    lrc, vocals, out_dir = lrc_slice_assets
    fake_flac = out_dir / "proj_slice_000.flac"
    fake_manifest = out_dir / "manifest.json"
    fake_flac.parent.mkdir(parents=True, exist_ok=True)
    fake_flac.write_bytes(b"")
    fake_manifest.write_text('{"slices": [{"id": "slice_000"}]}', encoding="utf-8")

    mock_mod = MagicMock()
    mock_mod.slice_vocals_lrc.return_value = (
        [fake_flac],
        fake_manifest,
        {"boundary_diagnostics": [], "phoneme_align_skip_counts": {}},
    )

    with (
        patch("pipeline.stages.slice.run_subprocess") as mock_run,
        patch("pipeline.stages.slice._load_script_module", return_value=mock_mod) as mock_load,
    ):
        result = run_slice(
            "proj",
            vocals,
            out_dir,
            mode="lrc",
            lrc_path=lrc,
            phoneme_align_mode="off",
        )

    mock_run.assert_not_called()
    mock_load.assert_called_once()
    mock_mod.slice_vocals_lrc.assert_called_once()
    assert result.slice_count == 1
