"""TC-Phase0-06 (semi-automated): scripts/start-pipeline-api.bat must pin
``--workers 1``, since the GPU job queue is an in-process singleton and
multiple worker processes would each build their own queue, breaking the
single-GPU serialization guarantee (docs §4.4/§11).

This is a static content check, not a process-launch test — actually running
uvicorn from the .bat file is a manual/TC-Phase0-06 "手工" step, but asserting
the flag is present in the committed script is a reasonable automated proxy.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "start-pipeline-api.bat"


def test_start_script_exists() -> None:
    assert _SCRIPT_PATH.is_file(), f"missing {_SCRIPT_PATH}"


def test_start_script_pins_single_worker() -> None:
    content = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--workers 1" in content
    assert "uvicorn api.main:app" in content


def test_start_script_activates_separator_env() -> None:
    content = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "separator-env\\Scripts\\activate.bat" in content
