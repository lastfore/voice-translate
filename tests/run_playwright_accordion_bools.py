"""Playwright: bool params outside accordions are visible and submitted correctly.

Requires Web UI at http://127.0.0.1:7860/

Examples:
  py -m pip install playwright && playwright install chromium
  separator-env\\Scripts\\python.exe tests/run_playwright_accordion_bools.py
  separator-env\\Scripts\\python.exe tests/run_playwright_accordion_bools.py --merge
"""

from __future__ import annotations

import argparse
import os
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

UI_URL = os.environ.get("PIPELINE_UI_URL", "http://127.0.0.1:7860/")

# Bool labels that must stay visible without opening parent accordions.
CONVERT_BOOL_LABELS = ("自动 F0 对齐", "FP16 推理", "跳过已有切片")
MERGE_BOOL_LABELS = ("Karaoke 净化伴奏", "跳过母带处理")
WIZARD_BOOL_LABELS = ("自动 F0 对齐",)


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


def _checkbox_visible(page, label: str) -> bool:
    loc = page.get_by_role("checkbox", name=label, exact=True).locator("visible=true")
    return loc.count() > 0


def _wait_for_log_contains(page, needle: str, *, timeout_s: float = 30.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for name in ("日志", "进度 / 日志"):
            boxes = page.get_by_role("textbox", name=name)
            if boxes.count() == 0:
                continue
            text = boxes.first.input_value()
            if needle in text:
                return text
        page.wait_for_timeout(500)
    return ""


def run_visibility_test() -> int:
    sync_playwright = _require_playwright()
    failed: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(UI_URL, wait_until="load", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: cannot open {UI_URL}: {exc}")
            return 1

        page.get_by_role("tab", name="转换", exact=True).click()
        page.wait_for_timeout(600)
        for label in CONVERT_BOOL_LABELS:
            ok = _checkbox_visible(page, label)
            print(f"[{'PASS' if ok else 'FAIL'}] convert visible: {label}")
            if not ok:
                failed.append(f"convert:{label}")

        page.get_by_role("tab", name="合并", exact=True).click()
        page.wait_for_timeout(600)
        for label in MERGE_BOOL_LABELS:
            ok = _checkbox_visible(page, label)
            print(f"[{'PASS' if ok else 'FAIL'}] merge visible: {label}")
            if not ok:
                failed.append(f"merge:{label}")

        page.get_by_role("tab", name="向导", exact=True).click()
        page.wait_for_timeout(600)
        for label in WIZARD_BOOL_LABELS:
            ok = _checkbox_visible(page, label)
            print(f"[{'PASS' if ok else 'FAIL'}] wizard visible: {label}")
            if not ok:
                failed.append(f"wizard:{label}")

        browser.close()

    print("=== Accordion bool visibility ===")
    return 1 if failed else 0


def run_convert_submit_test() -> int:
    """Toggle FP16 (outside accordion) and assert config log reflects fp16=False."""
    sync_playwright = _require_playwright()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(UI_URL, wait_until="load", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: cannot open {UI_URL}: {exc}")
            return 1

        page.get_by_role("tab", name="转换", exact=True).click()
        page.wait_for_timeout(600)

        fp16 = page.get_by_role("checkbox", name="FP16 推理", exact=True)
        fp16.scroll_into_view_if_needed()
        if fp16.is_checked():
            fp16.uncheck(force=True)
        page.wait_for_timeout(200)

        page.get_by_role("button", name="运行转换", exact=True).click()
        log_text = _wait_for_log_contains(page, "fp16=False", timeout_s=45.0)
        ok = "fp16=False" in log_text
        print(f"[{'PASS' if ok else 'FAIL'}] convert config log fp16=False")
        if not ok:
            print("log tail:", log_text[-500:] if log_text else "(empty)")
        browser.close()
        return 0 if ok else 1


def run_merge_submit_test(*, timeout_s: int = 300) -> int:
    """Reuse merge Karaoke path: bool outside accordion must reach backend."""
    import importlib.util

    mod_path = ROOT / "tests" / "run_playwright_merge_karaoke.py"
    spec = importlib.util.spec_from_file_location("run_playwright_merge_karaoke", mod_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.run_ui_test(skip_mastering=True, timeout_s=timeout_s))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--convert",
        action="store_true",
        help="Run convert fp16 submission test only",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Run merge Karaoke submission test only",
    )
    parser.add_argument(
        "--visibility-only",
        action="store_true",
        help="Run visibility checks only",
    )
    args = parser.parse_args()

    if args.convert:
        return run_convert_submit_test()
    if args.merge:
        return run_merge_submit_test()
    if args.visibility_only:
        return run_visibility_test()

    code = run_visibility_test()
    if code != 0:
        return code
    code = run_convert_submit_test()
    if code != 0:
        return code
    return run_merge_submit_test()


if __name__ == "__main__":
    raise SystemExit(main())
