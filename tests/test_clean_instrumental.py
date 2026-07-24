"""Tests for Karaoke clean error reporting in merge-audio."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_merge_audio():
    pytest.importorskip("librosa")
    script_path = ROOT / "scripts" / "merge-audio.py"
    spec = importlib.util.spec_from_file_location("merge_audio_clean_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def merge_mod():
    return _load_merge_audio()


def test_clean_instrumental_raises_with_subprocess_output(tmp_path: Path, merge_mod) -> None:
    inst = tmp_path / "inst.flac"
    inst.write_bytes(b"x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    failed = MagicMock(returncode=120, stdout="CUDA out of memory\nboom", stderr="")

    with patch("pipeline.venv_runner.run_subprocess", return_value=failed):
        with pytest.raises(RuntimeError, match="exit code 120") as exc_info:
            merge_mod.clean_instrumental(inst, out_dir, tmp_path / "models")

    assert "CUDA out of memory" in str(exc_info.value)
