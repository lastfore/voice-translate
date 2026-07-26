# Gradio 管线 UI 安全删除计划

> 状态：待执行  
> 日期：2026-07-26  
> 前提：FastAPI + React 迁移已完成验收（见 `docs/phase-test-checklist.md` §7）

## 结论

**管线 Gradio UI（`webui/`）已无保留必要，可按本计划安全下线。**

**范围说明**

- **删除**：管线 Gradio（`webui/`、`start-pipeline-webui.bat` 等）
- **保留**：`seed-vc/` 内 Gradio、`start-seed-vc-webui.bat`（Seed-VC 调试 UI 仍需要，占用 7860 端口）

---

## Phase 0 — 删除前门禁（全部打勾再动手）

- [ ] 新 UI 可正常用：`scripts\start-pipeline-web.bat` → http://127.0.0.1:5173/
- [ ] 自动化全绿：
  ```powershell
  py -m pytest tests/api/ -q
  cd frontend; npx playwright test --project=chromium
  ```
- [ ] 确认没有人在用 7860 管线 UI（只应剩 Seed-VC 或空）
- [ ] **备份/打 tag**（建议）：`git tag pre-remove-gradio-webui`

---

## Phase 1 — 测试迁离 `webui/`（删目录前必做）

当前仍直接 import `webui` 的测试：

| 文件 | 依赖 | 迁移动作 |
|------|------|----------|
| `tests/test_mode_panel.py` | `webui.mode_utils` | 将 `webui/mode_utils.py` 移到 `pipeline/mode_utils.py`（无 Gradio 依赖），改 import |
| `tests/test_slice_preview.py` | `webui.helpers.*` | 改 import 到已迁移模块：<br>• `api.services.slice_service`（`load_manifest_entries`, `load_slice_table`, `slice_audio_url`）<br>• `api.services.media_service`（`resolve_convert_preview_audio`）<br>• manifest 路径用 `paths.resolve_slices_mode_dir` + `manifest.json` 替代 `resolve_manifest_path` |
| `tests/test_webui_state.py` | `webui.state`, `webui.helpers` | **删除**，逻辑已由以下覆盖：<br>• `tests/api/test_projects.py`<br>• `api/services/pipeline_service.py` 相关测试（缺则补 1～2 条） |
| `tests/test_webui.py` | `webui.pipeline_app`, Gradio | **删除**（`tests/api/test_health.py` 已替代） |

**可选补测**（删 `test_webui_state.py` 前确认已覆盖）：

- [ ] `get_project_defaults` 的 `slice_mode` 优先级（原 `test_load_project_defaults_prefers_slice_stage_mode`）
- [ ] `format_project_choice` → 已有 `frontend/src/lib/format.ts`，前端单测或 API 列表格式即可

**迁完验证**：

```powershell
py -m pytest tests/test_mode_panel.py tests/test_slice_preview.py -q
py -m pytest tests/ -q
```

此时应 **不再有任何** `from webui` import（可用 `rg "from webui|import webui" --glob "*.py"` 确认）。

---

## Phase 2 — 删除文件与脚本

### 整目录删除

```
webui/
```

### 脚本删除

```
scripts/start-pipeline-webui.bat
scripts/stop-pipeline-webui.bat
requirements-webui.txt          # 仅服务 separator-env 的 Gradio
```

### Gradio 专用旧 E2E（已被 `frontend/e2e/` 替代，建议删除）

```
tests/test_webui.py
tests/test_webui_state.py
tests/run_playwright_vad_slice_params.py
tests/run_playwright_accordion_bools.py
tests/run_playwright_merge_karaoke.py
tests/run_playwright_converted_layout.py
```

> 若需留档：移到 `tests/legacy/gradio/` 并加 `README` 标注废弃，CI 不跑。

---

## Phase 3 — 文档与入口更新

### 必改（用户会看到的）

| 文件 | 改动 |
|------|------|
| `README.md` | `webui/` → `frontend/` + `api/`；启动改为 `start-pipeline-web.bat`；访问地址改为 `5173`；脚本表去掉 pipeline-webui 两行，加入 `start/stop-pipeline-web.bat` |
| `docs/phase-test-checklist.md` | `TC-P2-05` / `TC-Phase4-03` 双 UI 并存项改为「Gradio 已移除」 |
| `docs/管线WebUI迁移对照表-FastAPI-React.md` | Phase 4「删除 webui/」勾选完成；§11 并存风险行删除或标历史 |

### 建议加顶部废弃说明（不必全文改）

- `docs/管线WebUI设计方案.md` — 顶部：`[已废弃] 管线 UI 已迁移至 FastAPI+React，本文仅作历史参考`
- 其他仍大量引用 `webui/pipeline_app.py` 的方案文档同理

### 不要改错

- `docs/Seed-VC安装指南.md`、`start-seed-vc-webui.bat` — **保留**（7860 给 Seed-VC 用）

---

## Phase 4 — 依赖清理（可选但推荐）

`separator-env` 里若仅为管线 Gradio 装了 gradio：

```powershell
separator-env\Scripts\activate
uv pip uninstall gradio
# 或：uv pip install -r requirements-api.txt  # 不含 gradio
```

- [ ] 确认 `start-pipeline-api.bat` / `start-pipeline-web.bat` 启动正常
- [ ] **不要**动 `seed-vc-env` 的 gradio

---

## Phase 5 — 删除后验证清单

```powershell
# 1. 无残留引用
rg "webui\.|start-pipeline-webui|pipeline_app" --glob "!docs/**" --glob "!*.md"

# 2. 全量测试
py -m pytest tests/ -q
cd frontend; npx playwright test --project=chromium

# 3. 手工冒烟
scripts\start-pipeline-web.bat
# 浏览器：建项目 → 分离/切片/转换/合并/向导/批量 各 Tab 点一遍
scripts\stop-pipeline-web.bat
```

### 通过标准

- [ ] `tests/` 全绿（允许既有 flaky cancellation 项单独串行重跑）
- [ ] Playwright 14 passed
- [ ] 7860 仅 Seed-VC 使用，与管线 UI 无冲突
- [ ] 现有 `output/.projects/` 项目在新 UI 中可正常打开

---

## Phase 6 — 提交建议

```
chore: remove deprecated Gradio pipeline webui

- Delete webui/ and pipeline-webui start/stop scripts
- Migrate tests off webui.helpers/state to api.services/pipeline
- Update README and migration docs for FastAPI+React entrypoint
```

---

## 回滚

若删除后发现问题：

```powershell
git checkout pre-remove-gradio-webui -- webui/ scripts/start-pipeline-webui.bat scripts/stop-pipeline-webui.bat
```

数据层（`output/.projects/`）未动，回滚 UI 不影响项目文件。

---

## 工作量估计

| 阶段 | 耗时 |
|------|------|
| Phase 1 测试迁移 | 1～2 小时 |
| Phase 2～3 删除 + 文档 | 30～60 分钟 |
| Phase 4～5 验证 | 30 分钟 |
| **合计** | **约半天** |

---

## 相关文档

- 迁移对照：`docs/管线WebUI迁移对照表-FastAPI-React.md`
- 验收记录：`docs/phase-test-checklist.md`
- 新 UI 启动：`scripts/start-pipeline-web.bat` / `scripts/stop-pipeline-web.bat`
