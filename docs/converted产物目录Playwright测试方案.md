# converted 产物目录 Playwright 测试方案

> **关联文档：** [converted产物目录改造与合并修复方案.md](./converted产物目录改造与合并修复方案.md)  
> **测试脚本：** `tests/run_playwright_converted_layout.py`  
> **版本：** v1.0  
> **日期：** 2026-07-24

---

## 1. 目标与范围

验证 Web UI 在 converted 目录改造后的路径绑定、合并模式路由与 D1/D2 端到端回归。与 `run_playwright_merge_karaoke.py` 保持独立，本套件专注路径与模式。

| Tier | 档位 | 用例数 | 依赖 |
|------|------|--------|------|
| 1 | `--smoke` | PW-CVT-01 ~ 08 | Web UI 服务 |
| 2 | `--submit` | PW-CVT-09 ~ 11 | Web UI + mysong 元数据 |
| 3 | `--e2e` | PW-CVT-12 ~ 14 | Web UI + GPU + mysong 产物 |
| 4 | `--negative` | PW-CVT-15 ~ 17 | Web UI；16/17 使用临时项目 |

**前置条件**

- Web UI：`http://127.0.0.1:7860/`（可通过 `PIPELINE_UI_URL` 覆盖）
- Playwright：`pip install playwright && playwright install chromium`
- 默认项目：`mysong`；切换用例使用 `test`
- Legacy 用例源文件：`input/test.flac`、`input/test.lrc`

---

## 2. 执行命令

```bash
# 安装依赖
py -m pip install playwright
playwright install chromium

# 启动 Web UI（另开终端）
separator-env\Scripts\python.exe -m webui.pipeline_app

# 快检（PR 推荐）
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --smoke

# 提交校验
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --submit

# E2E 合并
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --e2e

# 负向与 Legacy
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --negative

# 全量（执行后自动更新本文档执行记录）
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --all --update-doc

# 单用例调试
separator-env\Scripts\python.exe tests/run_playwright_converted_layout.py --case PW-CVT-01 --update-doc
```

---

## 3. 用例清单

### Tier 1 — UI Smoke

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| PW-CVT-01 | 整轨默认路径 | 选 mysong → 合并 → 整轨合并 | `人声音频文件` 以 `full/full.flac` 结尾 |
| PW-CVT-02 | 切片默认路径 | 选 mysong → 合并 → 切片拼接 | `转换切片目录` 含 `converted/mysong/` 与 `lrc` 或 `vad` |
| PW-CVT-03 | 帮助文案 | 查看合并子 Tab Markdown | 整轨含 `full/full.flac`；切片含 `{lrc\|vad}` |
| PW-CVT-04 | Placeholder | 读取路径框 placeholder | 与新布局约定一致 |
| PW-CVT-05 | 项目切换 | mysong ↔ test | 路径随项目 ID 更新 |
| PW-CVT-06 | 切片模式联动 | 对比 mysong / test 项目路径 | 各项目 `converted/{id}/{lrc\|vad}/` 与保存的 slice_mode 一致 |
| PW-CVT-07 | Manifest 预览 | 切片拼接 Tab | `manifest 预览` 含 `slice` |
| PW-CVT-08 | 产物预览 | 转换 Tab | `产物` 音频控件可访问（有预览或为空但不报错） |

### Tier 2 — 提交校验

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| PW-CVT-09 | 整轨参数下发 | 整轨 + quick + 跳过母带 → 运行 | 日志含 `profile=quick`；无 `directory has N audio files` |
| PW-CVT-10 | 切片参数下发 | 切片 + balanced → 运行 | 日志含 `profile=balanced`；无 `directory has N audio files` |
| PW-CVT-11 | 模式路径隔离 | 对比整轨/切片 Tab 路径框 | 整轨为文件路径；切片为目录路径；二者不同 |

### Tier 3 — E2E 合并

| ID | 名称 | 映射 | 通过标准 |
|----|------|------|----------|
| PW-CVT-12 | whole_track + quick | D1 | 合并成功；无 `converted slice missing` / `Slice merge:` |
| PW-CVT-13 | slice_stitch + balanced | D2 | 合并成功；无 `broadcast` 错误；允许切片回退日志 |
| PW-CVT-14 | Karaoke 回归 | — | 委托 `run_playwright_merge_karaoke.py --ui` |

### Tier 4 — 负向与兼容

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| PW-CVT-15 | 混放根目录误用 | 切片 Tab 填 `converted/mysong/` 根目录 | 失败可读；无 NumPy broadcast 栈 |
| PW-CVT-16 | Legacy 扁平布局 | UI 新建临时项目 + 写入扁平 converted | 整轨解析 legacy `full.flac`；切片解析 legacy 根目录 |
| PW-CVT-17 | 缺失整轨 | 临时项目仅切片产物 → 整轨合并 | 路径为空或运行报可读错误 |

---

## 4. 临时项目约定（PW-CVT-16 / 17）

1. Playwright 展开「新建项目」手风琴
2. 填写唯一 `项目 ID`（前缀 `pwcvt_` + 时间戳）
3. 上传 `input/test.flac`、`input/test.lrc`
4. 点击「创建项目」
5. 用例所需时在 `output/converted/{id}/` 写入 fixture
6. 点击「刷新列表」并重新选中项目
7. `finally` 中删除项目元数据与产物目录

---

## 5. 与现有测试分工

| 脚本 | 职责 |
|------|------|
| `run_playwright_converted_layout.py` | 路径/模式 UI 测试（本方案） |
| `run_playwright_merge_karaoke.py` | Karaoke 净化伴奏（PW-CVT-14 调用） |
| `run_phase2_mysong.py` | Runner 层 D1/D2 对照 |
| `test_paths.py` / `test_merge_partial.py` | 单元测试 |

---

## 6. 执行记录

<!-- EXECUTION_LOG_START -->
| 用例 ID | 名称 | 状态 | 最近执行 (UTC+8) | 备注 |
|---------|------|------|------------------|------|
| PW-CVT-01 | 整轨默认路径 | 通过 | 2026-07-25 02:51:39 | output/converted/mysong/full/full.flac |
| PW-CVT-02 | 切片默认路径 | 通过 | 2026-07-25 02:52:03 | output/converted/mysong/lrc |
| PW-CVT-03 | 帮助文案 | 通过 | 2026-07-25 02:52:27 | whole=true, slice=true |
| PW-CVT-04 | Placeholder | 通过 | 2026-07-25 02:52:52 | placeholder含full/full.flac与{lrc|vad} |
| PW-CVT-05 | 项目切换 | 通过 | 2026-07-25 02:53:50 | mysong=lrc; test=lrc 路径切换正确 |
| PW-CVT-06 | 切片模式联动 | 通过 | 2026-07-25 02:54:12 | mysong/test均为lrc路径且不同 |
| PW-CVT-07 | Manifest 预览 | 通过 | 2026-07-25 03:01:18 | manifest预览含slice_000 |
| PW-CVT-08 | 产物预览 | 通过 | 2026-07-25 03:01:18 | 产物组件存在 |
| PW-CVT-09 | 整轨参数下发 | 通过 | 2026-07-25 03:01:39 | 日志含profile=quick |
| PW-CVT-10 | 切片参数下发 | 通过 | 2026-07-25 03:01:59 | 日志含profile=balanced |
| PW-CVT-11 | 模式路径隔离 | 通过 | 2026-07-25 03:02:20 | 整轨file与切片dir隔离 |
| PW-CVT-12 | D1 whole_track | 通过 | 2026-07-25 03:02:40 | D1 Merge complete无切片回退 |
| PW-CVT-13 | D2 slice_stitch | 通过 | 2026-07-25 03:13:50 | D2 Merge complete无broadcast错误 |
| PW-CVT-14 | Karaoke 回归 | 通过 | 2026-07-25 03:15:34 | Karaoke clean + Merge complete |
| PW-CVT-15 | 混放根目录误用 | 通过 | 2026-07-25 03:17:48 | 无broadcast错误(根目录误用未成功合并) |
| PW-CVT-16 | Legacy 扁平布局 | 通过 | 2026-07-25 03:18:49 | legacy full.flac与根目录切片回退 |
| PW-CVT-17 | 缺失整轨 | 通过 | 2026-07-25 03:19:48 | 无整轨时路径为空 |
<!-- EXECUTION_LOG_END -->

---

## 7. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-24 | 初版：用例设计、执行记录表、与改造方案对齐 |
| 2026-07-24 | 实现 `tests/run_playwright_converted_layout.py`；PW-CVT-06 改为项目级 slice_mode 路径对比 |
| 2026-07-25 | Playwright MCP 全量执行 17/17 通过；修复 merge 路径解析与 manifest/slices_dir 陈旧数据 |
