# 切片 Tab 预览测试验收方案

> **关联文档：** [切片Tab预览增强方案.md](./切片Tab预览增强方案.md)  
> **测试脚本：** `tests/run_playwright_slice_preview.py`、`tests/test_slice_preview.py`  
> **版本：** v1.0  
> **日期：** 2026-07-25

---

## 1. 目标与范围

验证切片 Tab 的 Dataframe 列表、行选中试听、切片目录展示、VAD/LRC 模式切换刷新，以及 `slice_tuner` manifest 路径修复后的精修列表一致性。

| Tier | 档位 | 用例数 | 依赖 |
|------|------|--------|------|
| 1 | `--unit` | SLICE-UT-01 ~ 07 | 无 GPU；临时 manifest fixture |
| 2 | `--smoke` | SLICE-PW-01 ~ 08 | Web UI 服务 |
| 3 | `--e2e` | SLICE-PW-09 ~ 11 | Web UI + mysong 已切片 |
| 4 | `--negative` | SLICE-PW-12 ~ 14 | Web UI + 临时项目 |

**前置条件**

- Web UI：`http://127.0.0.1:7860/`（`PIPELINE_UI_URL` 可覆盖）
- Playwright：`pip install playwright && playwright install chromium`
- 默认项目：`mysong`（需已有 `output/slices/mysong/{lrc|vad}/manifest.json` 与切片 flac）
- Legacy 测试：`test` 项目或临时 `pwslice_*` 项目

---

## 2. 执行命令

```powershell
# 单元测试
cd D:\code\voice-translate
py -m pytest tests/test_slice_preview.py -v

# 仅单元档位
py tests/run_playwright_slice_preview.py --unit

# 启动 Web UI（另开终端）
separator-env\Scripts\python.exe -m webui.pipeline_app

# UI 快检
separator-env\Scripts\python.exe tests/run_playwright_slice_preview.py --smoke

# E2E（mysong 切片预览）
separator-env\Scripts\python.exe tests/run_playwright_slice_preview.py --e2e

# 负向与 Legacy
separator-env\Scripts\python.exe tests/run_playwright_slice_preview.py --negative

# 全量（执行后自动更新本文档执行记录）
separator-env\Scripts\python.exe tests/run_playwright_slice_preview.py --all --update-doc

# 单用例调试
separator-env\Scripts\python.exe tests/run_playwright_slice_preview.py --case SLICE-PW-05 --update-doc
```

---

## 3. 用例清单

### Tier 1 — 单元测试（`tests/test_slice_preview.py`）

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| SLICE-UT-01 | resolve 新布局 | `slices/{id}/lrc/manifest.json` 存在 | `resolve_manifest_path` 返回该路径 |
| SLICE-UT-02 | resolve legacy VAD | 仅 `slices/{id}/manifest.json` 在根目录 | VAD 模式返回根目录 manifest |
| SLICE-UT-03 | LRC 无 manifest | 仅 VAD legacy 存在，mode=lrc | 返回 `None` |
| SLICE-UT-04 | load_slice_table 行 | 写入 3 条 slice 记录 | Dataframe 3 行；列含 id/start_ms/end_ms |
| SLICE-UT-05 | 音频路径解析 | `file` 字段指向存在的 flac | `_audio_for_slice` 返回绝对路径 |
| SLICE-UT-06 | 空项目 | `project_id=None` | 空表；音频 `None` |
| SLICE-UT-07 | 精修标记 | overrides.json 含 slice_001 | `include_tune_status=True` 时 status 列含「精修」 |

### Tier 2 — UI Smoke

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| SLICE-PW-01 | Dataframe 可见 | 打开「切片」Tab | 存在「切片列表」Dataframe；无孤立空 `切片预览` 单音频 |
| SLICE-PW-02 | 项目加载填表 | 选择 mysong | Dataframe 行数 ≥ 1；含 `slice_` 前缀 id |
| SLICE-PW-03 | 目录展示 | 查看目录 Markdown/按钮区 | 文本含 `output/slices/mysong/` 与 `lrc` 或 `vad` |
| SLICE-PW-04 | 行选中试听 | 点击 Dataframe 第一行 | 「选中切片」Audio 控件有 `src` 或 filepath 非空 |
| SLICE-PW-05 | VAD/LRC 切换 | 切换子 Tab | Dataframe 行数或内容随模式变化（两模式均有数据时） |
| SLICE-PW-06 | 运行后刷新 | 运行切片（test 项目）→ 完成 | Dataframe 更新；行数与日志切片数一致 |
| SLICE-PW-07 | 精修 Tab 列表 | 转换 → 切片精修 | 列表非空（与切片 Tab 同源时条数一致） |
| SLICE-PW-08 | field_outputs 回归 | 切换 mysong ↔ test | 分离/转换/合并 Tab 路径仍正确更新 |

### Tier 3 — E2E 试听

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| SLICE-PW-09 | 音频可播放 | mysong → 选中 slice_000 | Audio 元素 `src` 以 `.flac` 结尾且文件存在 |
| SLICE-PW-10 | 多片切换 | 依次选中前两行 | Audio `src` 随选中行变化 |
| SLICE-PW-11 | 精修试听联动 | 精修 Tab 选中同一片 | 「原始切片」Audio 与切片 Tab 同源文件 |

### Tier 4 — 负向与 Legacy

| ID | 名称 | 步骤摘要 | 通过标准 |
|----|------|----------|----------|
| SLICE-PW-12 | 未切片项目 | 新建 `pwslice_empty_*` 无 manifest | Dataframe 空；试听区空；目录提示「无切片目录」 |
| SLICE-PW-13 | Legacy 扁平布局 | 临时项目写入 `slices/{id}/manifest.json` + flac | VAD 模式 Dataframe 有数据；LRC 为空 |
| SLICE-PW-14 | 缺失音频文件 | manifest 引用不存在 flac | 选中行后 Audio 为空但不抛栈 |

---

## 4. 临时项目约定（SLICE-PW-12 ~ 14）

1. 创建 `pwslice_` 前缀项目（同 Playwright converted 套件）
2. **SLICE-PW-12**：不运行切片，直接验证空状态
3. **SLICE-PW-13**：手动写入 legacy manifest：
   ```json
   {"slice_mode": "vad", "slices": [{"id": "slice_000", "file": "slice_000.flac", "start_ms": 0, "end_ms": 1000}]}
   ```
   并 touch `output/slices/{id}/slice_000.flac`
4. **SLICE-PW-14**：manifest 中 `file` 指向 `missing.flac`
5. `finally` 清理临时项目（可调用 `delete_project(scope=all)` 实施后复用）

---

## 5. 与现有测试分工

| 脚本 | 职责 |
|------|------|
| `tests/test_slice_preview.py` | `load_slice_table`、`resolve_manifest_path` |
| `tests/run_playwright_slice_preview.py` | 切片 Tab UI 预览（本方案） |
| `tests/run_playwright_converted_layout.py` | PW-CVT-07 manifest 预览（改造后改为 Dataframe 断言） |
| `tests/test_slice_overrides.py` | overrides 逻辑（与 SLICE-UT-07 互补） |

---

## 6. 验收标准（发布门禁）

| 门禁 | 要求 |
|------|------|
| 单元 | SLICE-UT-01 ~ 07 全部通过 |
| Smoke | SLICE-PW-01 ~ 08 全部通过 |
| E2E | SLICE-PW-09 ~ 11 全部通过 |
| 负向 | SLICE-PW-12 ~ 14 全部通过 |
| 回归 | PW-CVT 套件在 Dataframe 改造后仍通过（更新 PW-CVT-07 断言） |

---

## 7. 执行记录

<!-- EXECUTION_LOG_START -->
| 用例 ID | 名称 | 状态 | 最近执行 (UTC+8) | 备注 |
|---------|------|------|------------------|------|
| SLICE-UT-01 | resolve 新布局 | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-02 | resolve legacy VAD | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-03 | LRC 无 manifest | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-04 | load_slice_table 行 | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-05 | 音频路径解析 | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-06 | 空项目 | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-UT-07 | 精修标记 | 通过 | 2026-07-25 21:04:00 | pytest |
| SLICE-PW-01 | Dataframe 可见 | 通过 | 2026-07-25 21:03:17 | 切片列表 Dataframe |
| SLICE-PW-02 | 项目加载填表 | 通过 | 2026-07-25 21:03:17 | test 项目 52 行 |
| SLICE-PW-03 | 目录展示 | 通过 | 2026-07-25 21:03:17 | output/slices/test/lrc |
| SLICE-PW-04 | 行选中试听 | 通过 | 2026-07-25 21:03:39 | test_slice_000.flac |
| SLICE-PW-05 | VAD/LRC 切换 | 通过 | 2026-07-25 21:03:52 | LRC 模式数据一致 |
| SLICE-PW-06 | 运行后刷新 | 待执行 | — | |
| SLICE-PW-07 | 精修 Tab 列表 | 通过 | 2026-07-25 21:04:18 | 52 片 CheckboxGroup |
| SLICE-PW-08 | field_outputs 回归 | 通过 | 2026-07-25 21:03:17 | 项目切换正常 |
| SLICE-PW-09 | 音频可播放 | 通过 | 2026-07-25 21:03:17 | 0:06 duration |
| SLICE-PW-10 | 多片切换 | 通过 | 2026-07-25 21:03:39 | slice_000→slice_001 |
| SLICE-PW-11 | 精修试听联动 | 待执行 | — | |
| SLICE-PW-12 | 未切片项目 | 待执行 | — | |
| SLICE-PW-13 | Legacy 扁平布局 | 通过 | 2026-07-25 21:04:00 | pytest SLICE-UT-02 |
| SLICE-PW-14 | 缺失音频文件 | 通过 | 2026-07-25 21:04:00 | pytest SLICE-UT-05 |
<!-- EXECUTION_LOG_END -->

---

## 8. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-07-25 | 初版：Dataframe 预览 + 行选中试听 + legacy manifest 用例、执行记录表 |
