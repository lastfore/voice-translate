"""Update a single row in docs/converted产物目录Playwright测试方案.md."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "converted产物目录Playwright测试方案.md"
NAMES = {
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


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: update_playwright_doc.py CASE_ID STATUS NOTE")
        return 2
    case_id, status, note = sys.argv[1], sys.argv[2], sys.argv[3]
    name = NAMES.get(case_id, case_id)
    text = DOC.read_text(encoding="utf-8")
    pattern = rf"\| {re.escape(case_id)} \| {re.escape(name)} \| [^|]+ \| [^|]+ \| [^|]+ \|"
    replacement = f"| {case_id} | {name} | {status} | {now_cst()} | {note} |"
    new_text, n = re.subn(pattern, replacement, text, count=1)
    if n != 1:
        print(f"warn: row not updated for {case_id}")
        return 1
    DOC.write_text(new_text, encoding="utf-8")
    print(f"updated {case_id} -> {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
