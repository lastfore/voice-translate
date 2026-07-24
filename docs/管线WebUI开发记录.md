# 管线 Web UI 开发记录

> 对应设计文档：[管线WebUI设计方案.md](./管线WebUI设计方案.md)  
> 每完成一个 Phase 在本文件追加记录，不等到全部完工再写。

---

## Phase 1：基础（编排内核骨架）

**状态：** ✅ 已完成  
**完成日期：** 2026-07-23

### 目标

- 创建 `pipeline/` 包：`models.py`、`paths.py`、`store.py`
- 实现 `project.json` 读写与 `scan_and_repair()`
- 单元测试：路径解析、项目 CRUD、输入校验与解析

### 交付物

| 文件 | 说明 |
|------|------|
| `pipeline/__init__.py` | 包入口，导出核心类型 |
| `pipeline/models.py` | `Project`、`StageRecord`、`Job`、枚举、`ProgressEvent` 等 |
| `pipeline/paths.py` | `get_root()`、各阶段产物路径 glob 解析 |
| `pipeline/store.py` | `ProjectStore`：CRUD、`scan_and_repair`、输入校验/解析/链预检 |
| `tests/test_paths.py` | 路径解析测试（5 项） |
| `tests/test_store.py` | 项目 CRUD、扫描修复测试（5 项） |
| `tests/test_inputs.py` | `validate` / `resolve` / `validate_pipeline_chain`（6 项） |

### 实现要点

1. **路径统一**：`VOICE_TRANSLATE_ROOT` 环境变量或自动检测仓库根；分离产物用 glob 匹配 `(Vocals)` / `(Instrumental)`，兼容大小写。
2. **双轨模型（v0.2）**：`validate_stage_inputs` 只校验文件存在性，**不**检查上游阶段 `status`；`resolve_stage_inputs` 按「用户覆盖 → 已保存 inputs → artifacts → glob」优先级解析。
3. **旧项目兼容**：`scan_and_repair()` 扫描 `output/slices/`、`output/converted/`、`input/` 音频，自动补建 `output/.projects/{id}/project.json` 并从磁盘推断阶段状态。
4. **project.json**：含 `schema_version`、`stages.*.inputs`（用户指定输入）与 `artifacts`（产出索引）分离。

### 测试

```powershell
cd D:\code\voice-translate
py -m pytest tests/ -v
```

**结果：** 16 passed（2026-07-23）

### 未包含（留给 Phase 2+）

- `pipeline/runner.py`、`pipeline/queue.py`
- `pipeline/stages/*` 阶段执行
- `webui/` Gradio 界面
- `scripts/start-pipeline-webui.bat`

### 已知限制

- `separator-env` 内无 `pip`/`pytest`，本地测试使用系统 `py -m pytest`。
- `delete_project(remove_files=True)` 仅删除 slices/converted/merged 子目录，不清理 `separated/` 全局产物。

---

## Phase 2：阶段执行（编排内核执行层）

**状态：** ✅ 已完成  
**完成日期：** 2026-07-23

### 目标

- `stages/separate.py`、`stages/slice.py`、`stages/convert.py`、`stages/merge.py`
- `GpuJobQueue` + `StageRunner`
- 抽取 `convert_slices()`；新增整段转换入口 `convert_full.py`
- 单元/集成测试（Runner 使用 mock，避免 GPU 依赖）

### 交付物

| 文件 | 说明 |
|------|------|
| `pipeline/venv_runner.py` | separator-env / seed-vc-env 子进程封装 |
| `pipeline/stages/separate.py` | `audio-separator` 子进程 + 模型校验 |
| `pipeline/stages/slice.py` | 动态 import `slice-vocals*.py` |
| `pipeline/stages/convert.py` | 整段（`convert_full` 子进程）+ 切片批量（`convert-slices.py` 子进程） |
| `pipeline/stages/convert_full.py` | Seed-VC 单文件推理 CLI（`-m pipeline.stages.convert_full`） |
| `pipeline/stages/merge.py` | import `merge_audio()` |
| `pipeline/queue.py` | 单 Worker FIFO `GpuJobQueue` |
| `pipeline/runner.py` | `run_stage` / `run_pipeline` / `run_stage_async` |
| `scripts/convert-slices.py` | 抽取可复用 `convert_slices()` |
| `tests/test_queue.py` | 队列 FIFO、失败传播（3 项） |
| `tests/test_runner.py` | Runner 编排 + mock 阶段（4 项） |

### 实现要点

1. **双 venv 隔离**：分离/切片/合并走 separator-env（import 或 `audio-separator` CLI）；转换走 seed-vc-env 子进程，`PYTHONPATH` 指向仓库根。
2. **GPU 串行**：所有阶段经 `GpuJobQueue` 入队，单线程 Worker 执行。
3. **进度回调**：各 stage 发射 `ProgressEvent`；Runner 写入 `output/.projects/{id}/logs/{job_id}.log`。
4. **状态回写**：成功后 `ProjectStore.update_stage(done)` 写入 `artifacts` / `params`。

### 测试

```powershell
py -m pytest tests/ -v
```

**结果：** 23 passed（2026-07-23）

### 手动集成验证（需 GPU + 模型）

```powershell
# 在 Python 中（separator-env 激活后）
python -c "
from pipeline import ProjectStore, StageRunner, StageName
store = ProjectStore()
runner = StageRunner(store)
# store.create_project('test', Path('input/test.flac'))  # 需先有输入
# runner.run_stage('test', StageName.SEPARATE)
"
```

### 未包含（留给 Phase 3）

- Gradio Web UI
- `start-pipeline-webui.bat`

---

## Phase 3：Web UI

**状态：** ✅ 已完成  
**完成日期：** 2026-07-23

### 目标

- `webui/pipeline_app.py` 骨架 + 项目侧栏
- 分离 / 切片 / 转换 / 合并 Tab
- 向导 Tab + 批量队列 Tab
- `start-pipeline-webui.bat` / `stop-pipeline-webui.bat`

### 交付物

| 文件 | 说明 |
|------|------|
| `webui/state.py` | ProjectStore / StageRunner 桥接、批量队列 |
| `webui/helpers.py` | 阶段图标、路径、上传保存 |
| `webui/pipeline_app.py` | Gradio 主入口（侧栏 + 6 Tab） |
| `webui/components/project_sidebar.py` | 项目列表、新建、刷新 |
| `webui/components/wizard.py` | 向导：单步 / 从此步 / 全流程 |
| `webui/components/batch_queue.py` | 多项目批量队列 |
| `webui/components/artifacts.py` | 产物试听辅助 |
| `scripts/start-pipeline-webui.bat` | 启动（separator-env + 自动装 gradio） |
| `scripts/stop-pipeline-webui.bat` | 停止 7860 端口 |
| `requirements-webui.txt` | `gradio==5.23.0` |
| `tests/test_webui_state.py` | state 桥接冒烟测试 |

### 启动

```powershell
scripts\start-pipeline-webui.bat
# 浏览器 http://127.0.0.1:7860/
```

> 启动脚本会清空 `HTTP_PROXY`/`HTTPS_PROXY`，避免 Gradio 因 SOCKS 代理报错。  
> 首次运行若缺 Gradio，会通过 `uv pip install` 装入 `separator-env`。

### 测试

```powershell
py -m pytest tests/ -v
# 25 passed
```

---

## Phase 4：收尾

**状态：** ✅ 已完成  
**完成日期：** 2026-07-23

### 目标

- 旧 `output/` 目录自动导入（含扁平 `merged/`、separated 文件名发现）
- 更新 `README.md` 入口说明
- 端到端测试（mock，无 GPU）

### 交付物

| 变更 | 说明 |
|------|------|
| `pipeline/paths.py` | `infer_project_ids_from_separated()`、legacy flat merged 路径 |
| `pipeline/store.py` | `scan_and_repair` 增强：separated 发现、旧版 `output/merged/mixed.flac` 索引 |
| `tests/test_e2e.py` | E2E-01/04/05 + 旧项目导入用例 |
| `tests/test_paths_legacy.py` | 分离文件名解析测试 |
| `README.md` | 管线 Web UI 快速开始、目录结构、脚本清单 |

### 旧项目兼容规则

1. `output/slices/{id}/`、`output/converted/{id}/`、`input/{id}.*` — 自动 bootstrap `project.json`
2. `output/separated/{id}_(Vocals)_*.flac` — 从文件名推断项目 ID
3. 扁平 `output/merged/mixed.flac` — 在**仅一个项目**或**唯一有分离产物**时写入 merge 阶段索引（`legacy_flat: true`），不移动原文件

### 测试

```powershell
py -m pytest tests/ -q
# 40 passed, 1 skipped（2026-07-24，含 test_merge_partial）
```

### 待后续验收

- [x] 真实 GPU 端到端：分离 → VAD 切片 → 转换(limit) → 合并（Playwright，见下文）
- [ ] §10.3 完整清单剩余项（刷新恢复、批量队列、向导全流程）

---

## GPU 实机验收（Playwright）

**状态：** ✅ 核心流程已通过  
**验收日期：** 2026-07-24  
**测试工具：** Playwright MCP（`user-playwright`）  
**测试项目：** `mysong`（`input/mysong.flac` + `input/mysong.lrc`）  
**UI 路径：** 各阶段 Tab 独立运行（非向导一键全流程）

### 验收方案

| 项 | 取值 |
|----|------|
| 切片模式 | **VAD**（不使用 LRC） |
| 转换模式 | `slice_batch` |
| 试跑片数 | `limit=3` |
| 参考音频 | `seed-vc/examples/source/ref.flac`（UI 上传后存为 `input/mysong/reference.flac`） |
| 合并 Profile | `full` |

对应设计文档 E2E-02 的 **VAD + 部分转换** 变体（非 LRC 全量 42 片）。

### 验收结果

| 阶段 | Tab | 结果 | 关键验证点 |
|------|-----|------|------------|
| 词曲分离 | 分离 | ✅ | 日志 `Separation complete`；人声/伴奏试听 5:13；产物写入 `output/separated/` |
| 声乐切片 | 切片 | ✅ | 模式 `vad`；`Wrote 14 slices`；`manifest.json` 14 条 |
| 歌声转换 | 转换 | ✅ | `slice_batch` + `limit=3`；`output/converted/mysong/` 3 个 flac |
| 人声伴奏结合 | 合并 | ✅ | `profile=full`；`output/merged/mysong/mixed.flac`（~39 MB，5:13） |

侧栏阶段指示：●分离 ●切片 ●转换 ●合并 均为完成态。

### 验收中发现的问题与修复

#### 1. ffmpeg 被 Smart App Control 拦截

- **现象：** 分离阶段报 `应用程序控制策略已阻止此文件`；`ffmpeg -version` 失败（Policy ID `{0283ac0f-...}`）。
- **原因：** Windows 11 Smart App Control 拦截未签名可执行文件（含 Chocolatey shim 与真实 `ffmpeg.exe`）。
- **处理：** 关闭 Smart App Control 后 `ffmpeg 8.1.2` 恢复正常；分离日志可见 `FFmpeg installed`。

#### 2. `limit=N` 时合并失败

- **现象：** 转换 `limit=3` 成功后，合并报 `Converted slice not found: ..._slice_003.flac`。
- **原因：** `scripts/merge-audio.py` 的 `build_from_slices()` 遍历完整 manifest（14 片），要求每片均有转换产物。
- **修复：** 转换产物缺失时回退到 `output/slices/{id}/` 原始切片，stderr 输出 `Warning: converted slice missing, using original` 及汇总 `Slice merge: N converted, M original fallback`。
- **验证：** CLI 重跑 `limit=3` 全流程合并成功；Playwright 合并 Tab 重试通过。

### 相关变更

| 文件 | 说明 |
|------|------|
| `scripts/merge-audio.py` | 部分转换时合并回退原始切片 |
| `tests/test_merge_partial.py` | 回退逻辑单元测试（需 `librosa`，无则 skip） |

### 未覆盖（§10.3 其余项）

- [ ] 刷新页面后项目状态恢复
- [ ] 批量队列 2+ 项目串行执行
- [ ] 向导 Tab 一键全流程
- [ ] 现有 CLI 脚本独立可用性复测

---

## converted 产物目录改造与合并修复

**状态：** ✅ 已完成  
**完成日期：** 2026-07-24  
**设计文档：** [converted产物目录改造与合并修复方案.md](./converted产物目录改造与合并修复方案.md)

### 目标

- `output/converted/{id}/` 拆分为 `full/`（整轨）与 `slices/`（批量切片）
- 修复 `balanced` profile 下部分转换 + 原始切片回退时的长度对齐（broadcast）错误
- 保留旧式扁平目录的 fallback 解析

### 交付物

| 文件 | 说明 |
|------|------|
| `pipeline/paths.py` | `converted_full_dir`、`converted_slices_dir`、`resolve_*`、`has_converted_artifacts` |
| `scripts/merge-audio.py` | `_align_segment_to_reference`、`_resolve_vocals_input` |
| `pipeline/stages/convert.py` | 整轨写入 `full/full.flac`，批量写入 `slices/` |
| `pipeline/store.py` | 合并输入解析与 `scan_and_repair` 适配新布局 |
| `scripts/migrate-converted-layout.py` | 可选迁移脚本（扁平 → 子目录） |
| `tests/test_paths.py` | 新布局 + legacy fallback 测试 |
| `tests/test_merge_partial.py` | 长度不一致 + balanced profile 测试 |

### 测试

```powershell
py -m pytest tests/test_paths.py tests/test_merge_partial.py -q
separator-env\Scripts\python.exe tests/run_phase2_mysong.py
```

**结果：** 单元测试通过；Phase 2 mysong D1/D2/E1/E2 全部 PASS（2026-07-24）

