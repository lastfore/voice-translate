"""TC-Phase0-06 / TC-Phase4-01 (semi-automated): startup scripts must pin
``--workers 1``, activate ``separator-env``, and (for the web bundle) launch
both API (8000) and Vite (5173).

This is a static content check, not a process-launch test — actually running
the .bat files is a manual step, but asserting the committed script contents
is a reasonable automated proxy.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"


def test_start_api_script_exists() -> None:
    assert (_SCRIPTS / "start-pipeline-api.bat").is_file()


def test_start_api_script_pins_single_worker() -> None:
    content = (_SCRIPTS / "start-pipeline-api.bat").read_text(encoding="utf-8")
    assert "--workers 1" in content
    assert "uvicorn api.main:app" in content


def test_start_api_script_activates_separator_env() -> None:
    content = (_SCRIPTS / "start-pipeline-api.bat").read_text(encoding="utf-8")
    assert "separator-env\\Scripts\\activate.bat" in content


def test_start_web_script_exists() -> None:
    assert (_SCRIPTS / "start-pipeline-web.bat").is_file()


def test_start_web_script_launches_api_and_frontend() -> None:
    content = (_SCRIPTS / "start-pipeline-web.bat").read_text(encoding="utf-8")
    assert "start-pipeline-api.bat" in content
    assert "npm run dev" in content
    assert "5173" in content or "frontend" in content


def test_stop_web_script_exists() -> None:
    assert (_SCRIPTS / "stop-pipeline-web.bat").is_file()


def test_stop_web_script_targets_both_ports() -> None:
    content = (_SCRIPTS / "stop-pipeline-web.bat").read_text(encoding="utf-8")
    assert "8000" in content
    assert "5173" in content


def test_stop_api_script_targets_port_8000() -> None:
    content = (_SCRIPTS / "stop-pipeline-api.bat").read_text(encoding="utf-8")
    assert "8000" in content
