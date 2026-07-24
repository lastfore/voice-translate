"""Playwright E2E: converted layout paths and merge mode routing.

Tiers:
  --smoke     PW-CVT-01 ~ 08  (UI only, no GPU)
  --submit    PW-CVT-09 ~ 11
  --e2e       PW-CVT-12 ~ 14  (GPU merge)
  --negative  PW-CVT-15 ~ 17
  --all       all tiers

Examples:
  py -m pip install playwright && playwright install chromium
  separator-env\\Scripts\\python.exe -m webui.pipeline_app
  separator-env\\Scripts\\python.exe tests/run_playwright_converted_layout.py --smoke --update-doc
  separator-env\\Scripts\\python.exe tests/run_playwright_converted_layout.py --case PW-CVT-16
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""

from pipeline import paths
from pipeline.store import ProjectStore

UI_URL = os.environ.get("PIPELINE_UI_URL", "http://127.0.0.1:7860/")
DEFAULT_PROJECT = "mysong"
ALT_PROJECT = "test"
DOC_PATH = ROOT / "docs" / "converted产物目录Playwright测试方案.md"
INPUT_AUDIO = ROOT / "input" / "test.flac"
INPUT_LRC = ROOT / "input" / "test.lrc"

CASE_NAMES: dict[str, str] = {
    "PW-CVT-01": "整轨默认路径",
    "PW-CVT-02": "切片默认路径",
    "PW-CVT-03": "帮助文案",
    "PW-CVT-04": "Placeholder",
    "PW-CVT-05": "项目切换",
    "PW-CVT-06": "切片模式联动",
    "PW-CVT-07": "Manifest 预览",
    "PW-CVT-08": "产物预览",
    "PW-CVT-09": "整轨参数下发",
    "PW-CVT-10": "切片参数下发",
    "PW-CVT-11": "模式路径隔离",
    "PW-CVT-12": "D1 whole_track",
    "PW-CVT-13": "D2 slice_stitch",
    "PW-CVT-14": "Karaoke 回归",
    "PW-CVT-15": "混放根目录误用",
    "PW-CVT-16": "Legacy 扁平布局",
    "PW-CVT-17": "缺失整轨",
}

SMOKE_CASES = [f"PW-CVT-{i:02d}" for i in range(1, 9)]
SUBMIT_CASES = [f"PW-CVT-{i:02d}" for i in range(9, 12)]
E2E_CASES = [f"PW-CVT-{i:02d}" for i in range(12, 15)]
NEGATIVE_CASES = [f"PW-CVT-{i:02d}" for i in range(15, 18)]


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    detail: str
    skipped: bool = False


def _require_playwright():
    try:
        from playwright.sync_api import Page, sync_playwright

        return Page, sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright not installed. Run:\n"
            "  py -m pip install playwright\n"
            "  playwright install chromium"
        ) from exc


def _now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _path_value(page, label: str) -> str:
    return page.get_by_role("textbox", name=label, exact=True).input_value()


def _placeholder(page, label: str) -> str:
    return page.get_by_role("textbox", name=label, exact=True).get_attribute("placeholder") or ""


def _goto(page) -> None:
    page.goto(UI_URL, wait_until="load", timeout=60_000)


def _tab(page, name: str) -> None:
    page.get_by_role("tab", name=name, exact=True).click()
    page.wait_for_timeout(500)


def _merge_whole(page) -> None:
    _tab(page, "合并")
    page.get_by_role("tab", name="整轨合并", exact=True).click()
    page.wait_for_timeout(400)


def _merge_slice(page) -> None:
    _tab(page, "合并")
    page.get_by_role("tab", name="切片拼接", exact=True).click()
    page.wait_for_timeout(400)


def _select_project(page, project_id: str) -> None:
    dropdown = page.get_by_label("当前项目", exact=True)
    dropdown.click()
    page.wait_for_timeout(300)
    # Gradio shows "Display (id) — stage icons"; match the id in parentheses.
    pattern = re.compile(rf"\({re.escape(project_id)}\)")
    option = page.get_by_role("option", name=pattern)
    if option.count() > 0:
        option.first.click()
    else:
        page.locator(f'[data-value="{project_id}"]').click()
    page.wait_for_timeout(800)


def _refresh_projects(page) -> None:
    page.get_by_role("button", name="刷新列表", exact=True).click()
    page.wait_for_timeout(800)


def _wait_log(page, *needles: str, timeout_s: float = 45.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for name in ("日志", "进度 / 日志"):
            boxes = page.get_by_role("textbox", name=name)
            if boxes.count() == 0:
                continue
            text = boxes.first.input_value()
            if all(n in text for n in needles) if needles else text.strip():
                return text
            if needles and any(n in text for n in needles):
                return text
        page.wait_for_timeout(500)
    return page.get_by_role("textbox", name="日志").input_value() if page.get_by_role("textbox", name="日志").count() else ""


def _wait_merge_done(page, timeout_s: float = 300.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        log_text = _wait_log(page, timeout_s=1.0)
        if any(token in log_text for token in ("失败", "exit code", "broadcast together with shapes")):
            return log_text
        if "Merge complete" in log_text or "阶段完成" in log_text:
            return log_text
    return _wait_log(page, timeout_s=1.0)


def _unique_project_id(prefix: str = "pwcvt") -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _require_input_fixtures() -> None:
    if not INPUT_AUDIO.is_file():
        raise SystemExit(f"SKIP: missing {INPUT_AUDIO}")
    if not INPUT_LRC.is_file():
        raise SystemExit(f"SKIP: missing {INPUT_LRC}")


def _upload_file_near_label(page, label: str, file_path: Path) -> None:
    block = page.locator(f'label:has-text("{label}")').first
    block.wait_for(state="visible", timeout=10_000)
    # Gradio wraps uploads; climb to row/container and find file input.
    container = block.locator("xpath=ancestor::*[contains(@class,'form') or contains(@class,'block')][1]")
    if container.count() == 0:
        container = block.locator("xpath=ancestor::div[1]")
    file_input = container.locator('input[type="file"]').first
    if file_input.count() == 0:
        file_input = page.locator('input[type="file"]').first
    file_input.set_input_files(str(file_path))


def create_project_via_ui(page, project_id: str) -> None:
    """Create a project through the sidebar「新建项目」flow."""
    _require_input_fixtures()
    accordion = page.locator("summary", has_text="新建项目")
    if accordion.count():
        accordion.first.click()
        page.wait_for_timeout(300)
    page.get_by_label("项目 ID", exact=True).fill(project_id)
    _upload_file_near_label(page, "混音文件", INPUT_AUDIO)
    _upload_file_near_label(page, "歌词 LRC", INPUT_LRC)
    page.get_by_role("button", name="创建项目", exact=True).click()
    page.wait_for_timeout(1200)
    msg = page.locator("text=已创建项目").first
    if msg.count() == 0:
        create_md = page.locator(".markdown").filter(has_text="已创建项目")
        if create_md.count() == 0:
            raise RuntimeError(f"project creation failed for {project_id}")


def setup_legacy_converted_layout(project_id: str) -> None:
    base = paths.converted_dir(project_id)
    base.mkdir(parents=True, exist_ok=True)
    if INPUT_AUDIO.is_file():
        shutil.copy2(INPUT_AUDIO, base / "full.flac")
    else:
        (base / "full.flac").write_bytes(b"legacy")
    (base / f"{project_id}_slice_000.flac").write_bytes(b"slice")


def setup_slices_only_converted(project_id: str, mode: str = "lrc") -> None:
    mode_dir = paths.converted_mode_dir(project_id, mode)
    mode_dir.mkdir(parents=True, exist_ok=True)
    # Copy a tiny slice file if test project has slices, else create stub.
    src = paths.converted_mode_dir("test", mode)
    candidates = list(src.glob("*slice*.flac")) if src.is_dir() else []
    if candidates:
        shutil.copy2(candidates[0], mode_dir / candidates[0].name)
    else:
        (mode_dir / f"{project_id}_slice_000.flac").write_bytes(b"slice")


def cleanup_project(project_id: str) -> None:
    meta = paths.project_meta_path(project_id)
    if meta.is_file():
        shutil.rmtree(meta.parent, ignore_errors=True)
    for rel in (
        paths.input_dir() / f"{project_id}.flac",
        paths.input_dir() / f"{project_id}.lrc",
        paths.converted_dir(project_id),
        paths.slices_dir(project_id),
        paths.merged_dir(project_id),
    ):
        if rel.is_dir():
            shutil.rmtree(rel, ignore_errors=True)
        elif rel.is_file():
            rel.unlink(missing_ok=True)


def _require_mysong_artifacts() -> tuple[Path, Path, Path | None]:
    full = paths.resolve_converted_full_track(DEFAULT_PROJECT)
    inst = paths.separated_instrumental_path(DEFAULT_PROJECT)
    slices = paths.resolve_converted_slices_dir(DEFAULT_PROJECT)
    if not full or not full.is_file():
        raise SystemExit(f"SKIP: missing full track for {DEFAULT_PROJECT}")
    if not inst or not inst.is_file():
        raise SystemExit(f"SKIP: missing instrumental for {DEFAULT_PROJECT}")
    if not slices:
        raise SystemExit(f"SKIP: missing converted slices dir for {DEFAULT_PROJECT}")
    return full, inst, slices


# --- Tier 1: Smoke ---


def test_pw_cvt_01(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _merge_whole(page)
    value = _path_value(page, "人声音频文件")
    ok = value.replace("\\", "/").endswith(f"converted/{DEFAULT_PROJECT}/full/full.flac")
    return CaseResult("PW-CVT-01", ok, value)


def test_pw_cvt_02(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    value = _path_value(page, "转换切片目录")
    norm = value.replace("\\", "/")
    ok = f"converted/{DEFAULT_PROJECT}/" in norm and ("lrc" in norm or "vad" in norm or "slices" in norm)
    return CaseResult("PW-CVT-02", ok, value)


def test_pw_cvt_03(page) -> CaseResult:
    _tab(page, "合并")
    page.get_by_role("tab", name="整轨合并", exact=True).click()
    page.wait_for_timeout(300)
    body = page.content()
    ok_whole = "full/full.flac" in body
    page.get_by_role("tab", name="切片拼接", exact=True).click()
    page.wait_for_timeout(300)
    body = page.content()
    ok_slice = "lrc" in body.lower() or "vad" in body.lower()
    ok = ok_whole and ok_slice
    return CaseResult("PW-CVT-03", ok, f"whole={ok_whole}, slice={ok_slice}")


def test_pw_cvt_04(page) -> CaseResult:
    _merge_whole(page)
    ph_file = _placeholder(page, "人声音频文件")
    _merge_slice(page)
    ph_dir = _placeholder(page, "转换切片目录")
    ok = "full/full.flac" in ph_file and ("lrc" in ph_dir or "vad" in ph_dir)
    return CaseResult("PW-CVT-04", ok, f"file={ph_file!r}; dir={ph_dir!r}")


def test_pw_cvt_05(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _merge_whole(page)
    mysong_path = _path_value(page, "人声音频文件")
    _select_project(page, ALT_PROJECT)
    page.wait_for_timeout(600)
    test_path = _path_value(page, "人声音频文件")
    ok = DEFAULT_PROJECT in mysong_path.replace("\\", "/") and ALT_PROJECT in test_path.replace("\\", "/")
    ok = ok and mysong_path != test_path
    return CaseResult("PW-CVT-05", ok, f"mysong={mysong_path}; test={test_path}")


def test_pw_cvt_06(page) -> CaseResult:
    """Paths follow each project's saved slice_mode (lrc vs vad), not live tab state."""
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    mysong_merge = _path_value(page, "转换切片目录").replace("\\", "/")
    _tab(page, "转换")
    mysong_convert = _path_value(page, "切片目录").replace("\\", "/")

    _select_project(page, ALT_PROJECT)
    page.wait_for_timeout(600)
    _merge_slice(page)
    test_merge = _path_value(page, "转换切片目录").replace("\\", "/")
    _tab(page, "转换")
    test_convert = _path_value(page, "切片目录").replace("\\", "/")

    mysong_mode = "lrc" if "/lrc" in mysong_merge or "/lrc" in mysong_convert else "vad"
    test_mode = "lrc" if "/lrc" in test_merge or "/lrc" in test_convert else "vad"
    mysong_ok = f"converted/{DEFAULT_PROJECT}/" in mysong_merge and f"/{mysong_mode}" in mysong_merge
    test_ok = f"converted/{ALT_PROJECT}/" in test_merge and f"/{test_mode}" in test_merge
    changed = mysong_merge != test_merge
    ok = mysong_ok and test_ok and changed
    return CaseResult(
        "PW-CVT-06",
        ok,
        f"mysong({mysong_mode})={mysong_merge}; test({test_mode})={test_merge}",
    )


def test_pw_cvt_07(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    preview = _path_value(page, "manifest 预览")
    ok = "slice" in preview.lower()
    return CaseResult("PW-CVT-07", ok, preview[:120] or "(empty)")


def test_pw_cvt_08(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _tab(page, "转换")
    audio = page.get_by_label("产物", exact=True)
    ok = audio.count() > 0
    detail = "audio component present" if ok else "missing 产物 component"
    return CaseResult("PW-CVT-08", ok, detail)


# --- Tier 2: Submit ---


def test_pw_cvt_09(page) -> CaseResult:
    _require_mysong_artifacts()
    _select_project(page, DEFAULT_PROJECT)
    _merge_whole(page)
    page.get_by_role("radio", name="quick", exact=True).click()
    skip = page.get_by_role("checkbox", name="跳过母带处理", exact=True)
    if not skip.is_checked():
        skip.check(force=True)
    page.get_by_role("button", name="运行合并", exact=True).click()
    log_text = _wait_log(page, "profile=quick", timeout_s=60.0)
    ok = "profile=quick" in log_text and "directory has" not in log_text
    return CaseResult("PW-CVT-09", ok, log_text[-300:] if log_text else "(empty)")


def test_pw_cvt_10(page) -> CaseResult:
    _require_mysong_artifacts()
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    page.get_by_role("radio", name="balanced", exact=True).click()
    page.get_by_role("button", name="运行合并", exact=True).click()
    log_text = _wait_log(page, "profile=balanced", timeout_s=60.0)
    ok = "profile=balanced" in log_text and "directory has" not in log_text
    return CaseResult("PW-CVT-10", ok, log_text[-300:] if log_text else "(empty)")


def test_pw_cvt_11(page) -> CaseResult:
    _select_project(page, DEFAULT_PROJECT)
    _merge_whole(page)
    file_path = _path_value(page, "人声音频文件")
    _merge_slice(page)
    dir_path = _path_value(page, "转换切片目录")
    file_norm = file_path.replace("\\", "/")
    dir_norm = dir_path.replace("\\", "/")
    ok = (
        file_norm.endswith(".flac")
        and "/full/" in file_norm
        and dir_path
        and not dir_norm.endswith(".flac")
        and file_path != dir_path
    )
    return CaseResult("PW-CVT-11", ok, f"file={file_path}; dir={dir_path}")


# --- Tier 3: E2E ---


def test_pw_cvt_12(page) -> CaseResult:
    _require_mysong_artifacts()
    _select_project(page, DEFAULT_PROJECT)
    _merge_whole(page)
    page.get_by_role("radio", name="quick", exact=True).click()
    skip = page.get_by_role("checkbox", name="跳过母带处理", exact=True)
    if not skip.is_checked():
        skip.check(force=True)
    page.get_by_role("button", name="运行合并", exact=True).click()
    log_text = _wait_merge_done(page)
    ok = ("Merge complete" in log_text or "阶段完成" in log_text)
    ok = ok and "converted slice missing" not in log_text and "Slice merge:" not in log_text
    ok = ok and "失败" not in log_text and "broadcast" not in log_text.lower()
    return CaseResult("PW-CVT-12", ok, log_text[-400:])


def test_pw_cvt_13(page) -> CaseResult:
    _require_mysong_artifacts()
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    page.get_by_role("radio", name="balanced", exact=True).click()
    skip = page.get_by_role("checkbox", name="跳过母带处理", exact=True)
    if not skip.is_checked():
        skip.check(force=True)
    page.get_by_role("button", name="运行合并", exact=True).click()
    log_text = _wait_merge_done(page)
    ok = ("Merge complete" in log_text or "阶段完成" in log_text)
    ok = ok and "broadcast together with shapes" not in log_text
    ok = ok and "operands could not be broadcast" not in log_text
    ok = ok and "失败" not in log_text
    return CaseResult("PW-CVT-13", ok, log_text[-400:])


def test_pw_cvt_14(page) -> CaseResult:
    mod_path = ROOT / "tests" / "run_playwright_merge_karaoke.py"
    spec = importlib.util.spec_from_file_location("run_playwright_merge_karaoke", mod_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    code = int(mod.run_ui_test(skip_mastering=True, timeout_s=300))
    return CaseResult("PW-CVT-14", code == 0, f"exit_code={code}")


# --- Tier 4: Negative ---


def test_pw_cvt_15(page) -> CaseResult:
    _require_mysong_artifacts()
    _select_project(page, DEFAULT_PROJECT)
    _merge_slice(page)
    bad = f"output/converted/{DEFAULT_PROJECT}"
    page.get_by_role("textbox", name="转换切片目录", exact=True).fill(bad)
    page.get_by_role("radio", name="balanced", exact=True).click()
    skip = page.get_by_role("checkbox", name="跳过母带处理", exact=True)
    if not skip.is_checked():
        skip.check(force=True)
    page.get_by_role("button", name="运行合并", exact=True).click()
    log_text = _wait_merge_done(page, timeout_s=120.0)
    failed = "失败" in log_text or "exit code" in log_text or "Error" in log_text
    no_broadcast = "broadcast together with shapes" not in log_text
    ok = failed and no_broadcast
    return CaseResult("PW-CVT-15", ok, log_text[-400:])


def test_pw_cvt_16(page) -> CaseResult:
    project_id = _unique_project_id("pwcvt_legacy")
    try:
        create_project_via_ui(page, project_id)
        setup_legacy_converted_layout(project_id)
        ProjectStore().scan_and_repair()
        _refresh_projects(page)
        _select_project(page, project_id)
        _merge_whole(page)
        whole = _path_value(page, "人声音频文件").replace("\\", "/")
        _merge_slice(page)
        slice_dir = _path_value(page, "转换切片目录").replace("\\", "/")
        whole_ok = whole.endswith(f"converted/{project_id}/full.flac")
        slice_ok = slice_dir.endswith(f"converted/{project_id}") or f"converted/{project_id}/" in slice_dir
        ok = whole_ok and slice_ok
        return CaseResult("PW-CVT-16", ok, f"whole={whole}; slice={slice_dir}")
    finally:
        cleanup_project(project_id)
        _refresh_projects(page)


def test_pw_cvt_17(page) -> CaseResult:
    project_id = _unique_project_id("pwcvt_nofull")
    try:
        create_project_via_ui(page, project_id)
        setup_slices_only_converted(project_id, "lrc")
        ProjectStore().scan_and_repair()
        _refresh_projects(page)
        _select_project(page, project_id)
        _merge_whole(page)
        whole = _path_value(page, "人声音频文件").strip()
        if whole:
            page.get_by_role("radio", name="quick", exact=True).click()
            skip = page.get_by_role("checkbox", name="跳过母带处理", exact=True)
            if not skip.is_checked():
                skip.check(force=True)
            page.get_by_role("button", name="运行合并", exact=True).click()
            log_text = _wait_merge_done(page, timeout_s=90.0)
            ok = "失败" in log_text or "not found" in log_text.lower() or "不存在" in log_text
            detail = log_text[-300:]
        else:
            ok = True
            detail = "whole track path empty as expected"
        return CaseResult("PW-CVT-17", ok, detail)
    finally:
        cleanup_project(project_id)
        _refresh_projects(page)


CASE_RUNNERS: dict[str, Callable] = {
    "PW-CVT-01": test_pw_cvt_01,
    "PW-CVT-02": test_pw_cvt_02,
    "PW-CVT-03": test_pw_cvt_03,
    "PW-CVT-04": test_pw_cvt_04,
    "PW-CVT-05": test_pw_cvt_05,
    "PW-CVT-06": test_pw_cvt_06,
    "PW-CVT-07": test_pw_cvt_07,
    "PW-CVT-08": test_pw_cvt_08,
    "PW-CVT-09": test_pw_cvt_09,
    "PW-CVT-10": test_pw_cvt_10,
    "PW-CVT-11": test_pw_cvt_11,
    "PW-CVT-12": test_pw_cvt_12,
    "PW-CVT-13": test_pw_cvt_13,
    "PW-CVT-14": test_pw_cvt_14,
    "PW-CVT-15": test_pw_cvt_15,
    "PW-CVT-16": test_pw_cvt_16,
    "PW-CVT-17": test_pw_cvt_17,
}


def update_test_doc(results: list[CaseResult]) -> None:
    if not DOC_PATH.is_file():
        print(f"warn: doc not found: {DOC_PATH}")
        return
    text = DOC_PATH.read_text(encoding="utf-8")
    start = "<!-- EXECUTION_LOG_START -->"
    end = "<!-- EXECUTION_LOG_END -->"
    if start not in text or end not in text:
        print("warn: execution log markers missing in doc")
        return

    result_map = {r.case_id: r for r in results}
    rows = [
        "| 用例 ID | 名称 | 状态 | 最近执行 (UTC+8) | 备注 |",
        "|---------|------|------|------------------|------|",
    ]
    for case_id in sorted(CASE_NAMES):
        name = CASE_NAMES[case_id]
        if case_id in result_map:
            r = result_map[case_id]
            if r.skipped:
                status, note, ts = "跳过", r.detail[:80], _now_cst()
            elif r.ok:
                status, note, ts = "通过", r.detail[:80], _now_cst()
            else:
                status, note, ts = "失败", r.detail[:80], _now_cst()
        else:
            status, note, ts = "待执行", "—", "—"
        rows.append(f"| {case_id} | {name} | {status} | {ts} | {note} |")

    new_block = start + "\n" + "\n".join(rows) + "\n" + end
    text = re.sub(
        re.escape(start) + r".*?" + re.escape(end),
        new_block,
        text,
        count=1,
        flags=re.DOTALL,
    )
    DOC_PATH.write_text(text, encoding="utf-8")
    print(f"Updated {DOC_PATH.relative_to(ROOT)}")


def run_cases(case_ids: list[str], *, headless: bool = True) -> list[CaseResult]:
    Page, sync_playwright = _require_playwright()
    results: list[CaseResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            _goto(page)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: cannot open {UI_URL}: {exc}")
            browser.close()
            return [CaseResult(cid, False, str(exc), skipped=True) for cid in case_ids]

        _refresh_projects(page)

        for case_id in case_ids:
            runner = CASE_RUNNERS.get(case_id)
            if not runner:
                results.append(CaseResult(case_id, False, "unknown case"))
                continue
            print(f"--- {case_id} {CASE_NAMES.get(case_id, '')} ---")
            try:
                result = runner(page)
            except SystemExit as exc:
                result = CaseResult(case_id, False, str(exc), skipped=True)
            except Exception as exc:  # noqa: BLE001
                result = CaseResult(case_id, False, f"{type(exc).__name__}: {exc}")
            results.append(result)
            status = "PASS" if result.ok else ("SKIP" if result.skipped else "FAIL")
            print(f"[{status}] {case_id}: {result.detail[:200]}")

        browser.close()
    return results


def resolve_case_list(args: argparse.Namespace) -> list[str]:
    if args.case:
        return [args.case]
    cases: list[str] = []
    if args.smoke or args.all:
        cases.extend(SMOKE_CASES)
    if args.submit or args.all:
        cases.extend(SUBMIT_CASES)
    if args.e2e or args.all:
        cases.extend(E2E_CASES)
    if args.negative or args.all:
        cases.extend(NEGATIVE_CASES)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--e2e", action="store_true")
    parser.add_argument("--negative", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--case", metavar="PW-CVT-XX")
    parser.add_argument("--update-doc", action="store_true", help="Write results to docs/converted产物目录Playwright测试方案.md")
    parser.add_argument("--headed", action="store_true", help="Run browser headed")
    args = parser.parse_args()

    case_ids = resolve_case_list(args)
    if not case_ids:
        parser.error("Specify --smoke, --submit, --e2e, --negative, --all, or --case")

    print("=== Playwright converted layout ===")
    print(f"cases: {', '.join(case_ids)}")
    results = run_cases(case_ids, headless=not args.headed)

    if args.update_doc:
        update_test_doc(results)

    failed = sum(1 for r in results if not r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    passed = sum(1 for r in results if r.ok)
    print(f"=== summary: pass={passed} fail={failed} skip={skipped} ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
