"""Playwright: VAD slice advanced params — submit, persist, and refresh behavior.

Requires Web UI at http://127.0.0.1:7860/

  separator-env\\Scripts\\python.exe tests/run_playwright_vad_slice_params.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""

from pipeline import paths

UI_URL = os.environ.get("PIPELINE_UI_URL", "http://127.0.0.1:7860/")
PROJECT = os.environ.get("VAD_SLICE_TEST_PROJECT", "mysong")
CUSTOM_THRESHOLD = 0.2


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright not installed. Run:\n"
            "  py -m pip install playwright\n"
            "  playwright install chromium"
        ) from exc


def _select_project(page, project_id: str) -> None:
    dropdown = page.get_by_label("当前项目", exact=True)
    dropdown.click()
    page.wait_for_timeout(300)
    pattern = re.compile(rf"\({re.escape(project_id)}\)")
    option = page.get_by_role("option", name=pattern)
    if option.count() > 0:
        option.first.click()
    else:
        page.locator(f'[data-value="{project_id}"]').click()
    page.wait_for_timeout(1000)


def _open_slice_vad(page) -> None:
    page.get_by_role("tab", name="切片", exact=True).click()
    page.wait_for_timeout(500)
    page.get_by_role("tab", name="VAD 断句", exact=True).click()
    page.wait_for_timeout(500)


def _open_vad_accordion(page) -> None:
    summary = page.locator("summary", has_text="VAD 高级参数")
    if summary.count():
        summary.first.click()
        page.wait_for_timeout(400)


def _number_value(page, label: str) -> str:
    box = page.get_by_role("spinbutton", name=label, exact=True)
    if box.count() == 0:
        box = page.get_by_label(label, exact=True)
    return box.first.input_value()


def _set_number(page, label: str, value: str) -> None:
    box = page.get_by_role("spinbutton", name=label, exact=True)
    if box.count() == 0:
        box = page.get_by_label(label, exact=True)
    target = box.first
    target.click()
    target.fill(value)
    target.press("Tab")
    page.wait_for_timeout(300)


def _wait_slice_done(page, timeout_s: float = 120.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        log = page.get_by_role("textbox", name="日志", exact=True)
        if log.count() == 0:
            page.wait_for_timeout(500)
            continue
        text = log.first.input_value()
        if "阶段完成" in text or "Wrote" in text or "失败" in text:
            return text
        page.wait_for_timeout(500)
    return page.get_by_role("textbox", name="日志", exact=True).first.input_value()


def _read_project_slice_params(project_id: str) -> dict:
    meta = paths.project_meta_path(project_id)
    if not meta.is_file():
        return {}
    data = json.loads(meta.read_text(encoding="utf-8"))
    return data.get("stages", {}).get("slice", {}).get("params", {})


def _latest_slice_log(project_id: str) -> Path | None:
    log_dir = paths.project_logs_dir(project_id)
    if not log_dir.is_dir():
        return None
    logs = sorted(log_dir.glob("slice-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def run() -> int:
    sync_playwright = _require_playwright()
    vocals = paths.separated_vocals_path(PROJECT)
    if not vocals or not vocals.is_file():
        print(f"SKIP: no separated vocals for {PROJECT}")
        return 0

    results: list[tuple[str, bool, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(UI_URL, wait_until="load", timeout=60_000)
        page.wait_for_timeout(2000)

        _select_project(page, PROJECT)
        _open_slice_vad(page)
        _open_vad_accordion(page)

        before = _number_value(page, "VAD 灵敏度")
        print(f"UI threshold before edit: {before}")

        _set_number(page, "VAD 灵敏度", str(CUSTOM_THRESHOLD))
        _set_number(page, "最短语音 (ms)", "400")
        after_edit = _number_value(page, "VAD 灵敏度")
        min_speech = _number_value(page, "最短语音 (ms)")
        results.append(
            (
                "ui_accepts_custom_values",
                after_edit == str(CUSTOM_THRESHOLD) and min_speech == "400",
                f"threshold={after_edit}, min_speech={min_speech}",
            )
        )

        saved_before = _read_project_slice_params(PROJECT)
        print(f"project.json slice.params before run: {json.dumps(saved_before, ensure_ascii=False)}")

        page.get_by_role("button", name="运行切片", exact=True).click()
        log_text = _wait_slice_done(page, timeout_s=180.0)
        print(f"slice log tail:\n{log_text[-400:]}")

        after_run_ui = _number_value(page, "VAD 灵敏度")
        saved_after = _read_project_slice_params(PROJECT)
        print(f"project.json slice.params after run: {json.dumps(saved_after, ensure_ascii=False)}")

        results.append(
            (
                "params_persisted_to_project_json",
                saved_after.get("vad_threshold") == CUSTOM_THRESHOLD
                and saved_after.get("min_speech_ms") == 400,
                f"saved vad_threshold={saved_after.get('vad_threshold')}, min_speech_ms={saved_after.get('min_speech_ms')}",
            )
        )
        results.append(
            (
                "ui_after_run_keeps_values",
                after_run_ui == str(CUSTOM_THRESHOLD),
                f"ui threshold after run={after_run_ui}",
            )
        )

        slice_log = _latest_slice_log(PROJECT)
        log_file_note = ""
        if slice_log and slice_log.is_file():
            log_file_note = slice_log.read_text(encoding="utf-8", errors="replace")[-200:]
            print(f"latest slice job log ({slice_log.name}): {log_file_note}")

        page.reload(wait_until="load")
        page.wait_for_timeout(2500)
        _open_slice_vad(page)
        _open_vad_accordion(page)
        after_reload = _number_value(page, "VAD 灵敏度")
        min_speech_reload = _number_value(page, "最短语音 (ms)")
        results.append(
            (
                "ui_after_browser_reload",
                after_reload == str(CUSTOM_THRESHOLD) and min_speech_reload == "400",
                f"threshold={after_reload}, min_speech={min_speech_reload}",
            )
        )

        page.get_by_role("button", name="刷新列表", exact=True).click()
        page.wait_for_timeout(1200)
        _open_slice_vad(page)
        _open_vad_accordion(page)
        after_refresh_btn = _number_value(page, "VAD 灵敏度")
        results.append(
            (
                "ui_after_refresh_list_button",
                after_refresh_btn == str(CUSTOM_THRESHOLD),
                f"threshold={after_refresh_btn}",
            )
        )

        browser.close()

    print("\n=== VAD slice params Playwright results ===")
    failed = 0
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
