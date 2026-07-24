"""E2E: full-profile merge with Karaoke instrumental clean.

Two modes:
  --runner   Direct StageRunner test (no browser; needs GPU + mysong artifacts)
  --ui       Playwright Web UI test (needs server at http://127.0.0.1:7860/)

Examples:
  separator-env\\Scripts\\python.exe tests/run_playwright_merge_karaoke.py --runner
  py -m pip install playwright && playwright install chromium
  separator-env\\Scripts\\python.exe tests/run_playwright_merge_karaoke.py --ui
"""

from __future__ import annotations

import argparse
import json
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

from pipeline import paths
from pipeline.models import StageName
from pipeline.runner import StageRunner
from pipeline.store import ProjectStore

PID = "mysong"
UI_URL = os.environ.get("PIPELINE_UI_URL", "http://127.0.0.1:7860/")


def _require_mysong_artifacts() -> tuple[Path, Path]:
    root = paths.get_root()
    full = paths.resolve_converted_full_track(PID)
    inst = paths.separated_instrumental_path(PID)
    if not full or not full.is_file():
        raise SystemExit(f"SKIP: missing full track for {PID}")
    if not inst or not inst.is_file():
        raise SystemExit(f"SKIP: missing instrumental for {PID}")
    return full, inst


def run_runner_test(*, skip_mastering: bool = True) -> int:
    """Exercise merge + Karaoke via orchestration kernel (no browser)."""
    full, inst = _require_mysong_artifacts()
    root = paths.get_root()
    out_dir = paths.merged_dir(PID) / "_karaoke_e2e"
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.is_file():
                child.unlink()

    store = ProjectStore()
    runner = StageRunner(store)
    params = {
        "vocals": str(full.relative_to(root)),
        "instrumental": str(inst.relative_to(root)),
        "merge_mode": "whole_track",
        "profile": "full",
        "clean_instrumental": True,
        "skip_mastering": skip_mastering,
        "output_dir": str(out_dir.relative_to(root)),
    }

    logs: list[str] = []

    def on_progress(event) -> None:
        if event.log_line:
            logs.append(event.log_line)

    result = runner.run_stage(PID, StageName.MERGE, params, on_progress=on_progress)
    clean = out_dir / "instrumental_clean.flac"
    mixed = out_dir / "mixed.flac"
    log_text = "\n".join(logs)

    print("=== Runner Karaoke E2E ===")
    print(f"success={result.success}")
    if result.error:
        print(f"error={result.error}")
    print(f"instrumental_clean exists={clean.is_file()}")
    print(f"mixed exists={mixed.is_file()}")
    if "Karaoke clean wrote" not in log_text and "Karaoke clean failed" not in log_text:
        print("warn: no Karaoke log lines captured")
    print("log tail:", log_text[-800:])

    if not result.success:
        return 1
    if not clean.is_file():
        print("FAIL: instrumental_clean.flac not created")
        return 1
    if not mixed.is_file():
        print("FAIL: mixed.flac not created")
        return 1
    print("PASS")
    return 0


def run_ui_test(*, skip_mastering: bool = True, timeout_s: int = 300) -> int:
    """Playwright: merge tab + Karaoke checkbox + run."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright not installed. Run:\n"
            "  py -m pip install playwright\n"
            "  playwright install chromium"
        )
        return 2

    full_rel = f"output/converted/{PID}/full/full.flac"
    results: list[tuple[str, bool, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(UI_URL, wait_until="load", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: cannot open {UI_URL}: {exc}")
            return 1

        page.get_by_role("tab", name="合并", exact=True).click()
        page.wait_for_timeout(800)
        page.get_by_role("tab", name="整轨合并", exact=True).click()
        page.wait_for_timeout(400)
        page.get_by_role("radio", name="full", exact=True).click()

        page.get_by_role("textbox", name="人声音频文件").fill(full_rel)

        # Karaoke / skip mastering render outside the 高级参数 accordion (scheme A).
        karaoke = page.get_by_role("checkbox", name="Karaoke 净化伴奏")
        karaoke.scroll_into_view_if_needed()
        karaoke.check(force=True)
        page.wait_for_timeout(300)
        if not karaoke.is_checked():
            results.append(("checkbox", False, "Karaoke checkbox not checked"))
        else:
            results.append(("checkbox", True, "checked"))

        if skip_mastering:
            skip_box = page.get_by_role("checkbox", name="跳过母带处理")
            skip_box.check(force=True)

        page.get_by_role("button", name="运行合并").click()

        deadline = time.time() + timeout_s
        log_text = ""
        while time.time() < deadline:
            page.wait_for_timeout(3000)
            log_text = page.get_by_role("textbox", name="日志").input_value()
            karaoke_started = any(
                token in log_text
                for token in (
                    "clean_instrumental=True",
                    "Karaoke clean",
                    "Loading karaoke",
                    "karaoke",
                )
            )
            if not karaoke_started:
                continue
            if any(token in log_text for token in ("失败", "exit code", "Karaoke clean failed")):
                break
            if "Merge complete" in log_text or "阶段完成" in log_text:
                break
            if "instrumental_clean" in log_text.lower():
                break

        config_ok = "clean_instrumental=True" in log_text or "Karaoke clean" in log_text
        results.append(("config_log", config_ok, log_text.splitlines()[0] if log_text else ""))

        merge_ok = "Merge complete" in log_text or "阶段完成" in log_text
        if "失败" in log_text or "exit code" in log_text:
            merge_ok = False
        results.append(("merge_log", merge_ok, log_text[-400:]))

        merged_root = paths.merged_dir(PID)
        clean_candidates = list(merged_root.glob("**/instrumental_clean.flac"))
        results.append(
            (
                "instrumental_clean",
                bool(clean_candidates),
                str(clean_candidates[0]) if clean_candidates else str(merged_root / "instrumental_clean.flac"),
            )
        )

        browser.close()

    print("=== Playwright Karaoke E2E ===")
    failed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {detail}")
        if not ok:
            failed += 1
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Run Playwright Web UI test (default: --runner)",
    )
    parser.add_argument(
        "--with-mastering",
        action="store_true",
        help="Do not skip Matchering mastering",
    )
    args = parser.parse_args()
    skip_mastering = not args.with_mastering
    if args.ui:
        return run_ui_test(skip_mastering=skip_mastering)
    return run_runner_test(skip_mastering=skip_mastering)


if __name__ == "__main__":
    raise SystemExit(main())
