# 方案验收测试用例 — FastAPI + React

> 适用文档：`docs/管线WebUI迁移对照表-FastAPI-React.md`  
> 目标：为迁移方案提供可执行、可追踪、可维护的验收测试基线  
> 版本：v1.0  
> 日期：2026-07-26

---

## 1. 使用说明（维护约定）

- 本文覆盖迁移方案 Phase 0 ~ Phase 4 的验收口径。
- 每条用例都有唯一 ID（`TC-Px-yy`），便于关联缺陷单与自动化脚本。
- 每条用例明确自动化归属：
  - `pytest`：后端 API、服务层、路径校验、并发语义、队列语义。
  - `Playwright`：前端交互、表单行为、SSE 日志显示、音频预览。
  - `手工`：环境/资源观测（GPU 显存、子进程释放）、灰度上线核验。
- 新增或修改接口时，必须同步更新：
  - `覆盖范围`（本文件第 3 章）
  - `测试用例表`（本文件第 4 章）
  - `自动化落地映射`（本文件第 5 章）
  - `按 Phase 开发中测试设计`（本文件第 8 章）

---

## 2. 验收门禁

- `P0`（阻断级）：必须 100% 通过，任何失败都阻断 Phase 4 收尾和上线。
- `P1`（关键业务）：允许短期遗留低风险项，但必须有 workaround 与修复计划。
- `P2`（体验与非功能）：建议全部通过，至少不留高风险缺陷。

建议执行顺序：

1. 冒烟：全部 `P0` 先跑通。
2. 回归：`P1` 全量 + 与已修复缺陷相关 `P0` 重跑。
3. 稳定性：`P2` + 长时运行抽检。

---

## 3. 覆盖范围总览

| 领域 | 关键能力 | 对应章节 |
|------|----------|----------|
| API 基础 | 健康检查、项目 CRUD、defaults、schema、media | 4.1, 4.2 |
| SSE 与异步边界 | 长任务流式、线程池隔离、取消语义、断连恢复 | 4.3 |
| 安全性 | 路径穿越防护、扩展名白名单、文件端点收口 | 4.4 |
| 前端交互 | 表单渲染、项目切换、切片预览、向导流程 | 4.5 |
| 队列能力 | 批量入队、状态 SSE、串行执行、清队列 | 4.6 |
| 非功能 | 大文件上传、性能、并存期兼容、可观测性 | 4.7 |

---

## 4. 详细测试用例

> 说明：  
> - 自动化归属为“主归属”；必要时可在备注中补充“联动验证”。  
> - “前置条件”未特别说明时，默认 API 与前端均正常启动，且存在可用测试项目。  

### 4.1 P0（阻断级）

| ID | 验收点 | 前置条件 | 步骤（摘要） | 预期结果 | 自动化归属 |
|----|--------|----------|--------------|----------|------------|
| TC-P0-01 | API 启动参数强制单 worker | 可执行启动脚本 | 运行 `scripts/start-pipeline-api.bat`，检查启动参数 | 使用 `uvicorn --workers 1`，无多 worker | 手工 |
| TC-P0-02 | 健康检查可用 | API 已启动 | 请求健康检查端点 | 返回 200；响应结构符合约定 | pytest |
| TC-P0-03 | 项目创建（multipart） | 准备混音文件与可选 lrc | 调用 `POST /api/projects` 创建项目 | 项目创建成功，`GET /api/projects` 可见 | pytest |
| TC-P0-04 | defaults 回填完整性 | 至少 1 个已存在项目 | 调用 `GET /api/projects/{id}/defaults` | 返回 `stage_params`、`mode`、`artifacts` 等关键字段且可用 | pytest |
| TC-P0-05 | 路径穿越防护 | API 已启动 | 调用 `/api/media?path=../../../...` | 请求被拒绝（4xx），无目录外文件泄露 | pytest |
| TC-P0-06 | 扩展名白名单生效 | 准备合法与非法扩展样本 | 分别访问 `/api/media` | 合法返回 200；非法返回 4xx | pytest |
| TC-P0-07 | 单阶段 SSE 连续推送 | 可运行阶段任务项目 | 调 `POST /api/projects/{id}/stages/separate/run` | 收到连续日志/状态并以 `done` 收尾 | pytest |
| TC-P0-08 | 全流程 SSE 连续性 | 同上 | 调 `POST /api/projects/{id}/pipeline/run` | 多阶段日志不断流、顺序正确、最终完成 | pytest |
| TC-P0-09 | 任务取消语义生效 | 前端可触发运行 | 运行阶段任务后触发取消 | 后端任务转 `CANCELLED`，子进程被清理 | Playwright |
| TC-P0-10 | 长任务下事件循环不阻塞 | 触发长任务运行中 | 并发请求健康检查、项目列表、SSE 状态 | 请求持续可响应，无全局阻塞 | pytest |
| TC-P0-11 | 批量队列 GPU 串行 | 至少 2 个待处理任务 | 入队并执行批量队列 | 任一时刻仅 1 个任务 `running`，顺序可解释 | pytest |
| TC-P0-12 | Collapsible 下 bool 参数不丢值 | 前端参数表单可操作 | 折叠高级区并提交 `fp16/skip_existing` 等 bool | API 收到值与 UI 勾选一致 | Playwright |

### 4.2 P1（关键业务）

| ID | 验收点 | 前置条件 | 步骤（摘要） | 预期结果 | 自动化归属 |
|----|--------|----------|--------------|----------|------------|
| TC-P1-01 | 删除预览准确性 | 存在可删除项目 | 调 `GET /api/projects/{id}/delete-preview` | 预览与实际删除范围一致 | pytest |
| TC-P1-02 | 删除范围控制 | 同上 | 分别执行 `metadata/artifacts/all` 删除 | 仅删除选定范围，结果可回读验证 | pytest |
| TC-P1-03 | Schema 过滤参数正确 | API 可访问 schema | 调 `/api/params/schema` 传 `vad_only/slice_batch_only/keys` | 返回参数集合精确匹配过滤条件 | pytest |
| TC-P1-04 | Schema 缓存策略有效 | 可重复请求 schema | 连续请求相同 schema，切换页面重复加载 | 后端命中缓存；前端不重复拉取（除显式 invalidate） | pytest |
| TC-P1-05 | 项目切换 remount 行为 | 前端可切换项目 | 在 A 修改未提交参数，切换到 B | B 页面加载 B defaults，无 A 脏值污染 | Playwright |
| TC-P1-06 | 切片表行选与音频预览 | 项目含切片数据 | 打开切片页，点击行播放音频 | 行数据与音频对应，音频可播放 | Playwright |
| TC-P1-07 | overrides 查询与保存 | 项目存在切片 | 调 `GET/PUT /slices/overrides` 并回读 | 保存后回读一致，格式合法 | pytest |
| TC-P1-08 | overrides 清理 orphan | overrides 存在失效项 | 调 `POST /slices/overrides/clear-orphans` | 仅 orphan 被清除，合法项保留 | pytest |
| TC-P1-09 | 批量状态常驻 SSE | 前端/后端均可观察队列 | 订阅 `GET /api/batch/status`，执行 enqueue/run/clear | 状态实时推送，无 polling 依赖 | Playwright |
| TC-P1-10 | 向导“从此步到最后” | 向导流程可用 | 在任一步触发 run-from | 日志跨阶段连续，最终产物路径有效 | Playwright |

### 4.3 P2（体验与非功能）

| ID | 验收点 | 前置条件 | 步骤（摘要） | 预期结果 | 自动化归属 |
|----|--------|----------|--------------|----------|------------|
| TC-P2-01 | 大文件上传稳定性 | 准备大体积 flac | 上传并创建项目 | 上传成功，无明显内存异常/崩溃 | 手工 |
| TC-P2-02 | SSE 断连后重试幂等 | 可人工制造断连 | 任务中断后重发同参数 | 可重跑完成，产物状态一致可解释 | 手工 |
| TC-P2-03 | 日志显示截断策略 | 运行长日志任务 | 观察日志面板累计显示 | 按策略截断，关键尾部与状态保留 | Playwright |
| TC-P2-04 | 切片表大数据量性能 | 切片数量 > 100 | 滚动、选中、切换 | 交互流畅，无明显卡顿 | Playwright |
| TC-P2-05 | 双 UI 并存期兼容 | 旧 UI 与新 UI 可同时访问 | 分别通过两套 UI 操作同项目 | `output/.projects` schema 不被破坏 | 手工 |
| TC-P2-06 | 错误可观测性与可诊断性 | 可构造错误输入 | 构造参数错误/路径错误/不存在项目 | 返回错误可读且可定位（状态码+消息） | pytest |

---

## 5. 自动化落地映射（建议）

### 5.1 pytest（后端）

- 目录建议：`tests/api/`
- 建议文件拆分：
  - `test_api_health.py`：`TC-P0-02`
  - `test_api_projects.py`：`TC-P0-03`, `TC-P0-04`, `TC-P1-01`, `TC-P1-02`
  - `test_api_media_security.py`：`TC-P0-05`, `TC-P0-06`
  - `test_api_sse_stage.py`：`TC-P0-07`, `TC-P0-08`, `TC-P0-10`
  - `test_api_batch.py`：`TC-P0-11`
  - `test_api_params_schema.py`：`TC-P1-03`, `TC-P1-04`
  - `test_api_slice_overrides.py`：`TC-P1-07`, `TC-P1-08`
  - `test_api_observability.py`：`TC-P2-06`

### 5.2 Playwright（前端 E2E）

- 目录建议：`frontend/e2e/`
- 建议文件拆分：
  - `project-switch.spec.ts`：`TC-P1-05`
  - `stage-params-collapsible.spec.ts`：`TC-P0-12`
  - `slice-preview.spec.ts`：`TC-P1-06`
  - `stage-cancel.spec.ts`：`TC-P0-09`
  - `wizard-run-from.spec.ts`：`TC-P1-10`
  - `batch-status-sse.spec.ts`：`TC-P1-09`
  - `log-truncation.spec.ts`：`TC-P2-03`
  - `slice-table-performance.spec.ts`：`TC-P2-04`

### 5.3 手工（环境与上线核验）

- 建议维护清单：`docs/manual-checklist-release.md`
- 重点手工项：
  - `TC-P0-01`（启动参数约束）
  - `TC-P2-01`（大文件上传与内存）
  - `TC-P2-02`（断连重试幂等）
  - `TC-P2-05`（双 UI 并存兼容）

---

## 6. 通过标准（发布判定）

- 发布前必须满足：
  - 全部 `P0` 通过。
  - `P1` 失败项为 0，或仅保留经评审批准的非阻断缺陷且有回退方案。
  - `P2` 不存在高风险缺陷（安全、数据损坏、任务失控）。
- 若出现以下任一情况，必须阻断发布：
  - 路径校验可绕过。
  - 任务取消导致孤儿进程长期占用 GPU。
  - 批量队列并行执行破坏单 GPU 串行语义。

---

## 7. 变更记录

- `v1.0`（2026-07-26）
  - 首次建立 FastAPI + React 迁移方案验收用例基线。
  - 为每条用例增加自动化归属（`pytest` / `Playwright` / `手工`）。

---

## 8. 按 Phase 的开发中测试设计

> 目标：解决“整体验收通过，但阶段开发过程缺少门禁”的问题。  
> 原则：每个 Phase 都有“新增必测 + 历史回归必跑 + 阶段出口标准”。

### 8.1 Phase 0（API 骨架）

**阶段目标**

- API 基础能力可用：项目、defaults、schema、media、单阶段 SSE。
- 线程/异步边界落地：阻塞任务线程池隔离，SSE 在长任务下不断流。
- 取消语义落地：客户端断开触发后端 cleanup。

**Phase 新增必测用例**

| ID | 用例 | 关键检查点 | 自动化归属 |
|----|------|------------|------------|
| TC-Phase0-01 | API 基础骨架可用 | 健康检查、CORS、基础路由可访问 | pytest |
| TC-Phase0-02 | `resolve_safe_path()` 收口覆盖 | `/api/media`、文件类端点统一走安全路径解析 | pytest |
| TC-Phase0-03 | schema 缓存策略 | 相同参数请求命中缓存，响应结构稳定 | pytest |
| TC-Phase0-04 | `run_stage` 非阻塞 | 运行长任务时健康检查和列表接口不阻塞 | pytest |
| TC-Phase0-05 | 取消任务清理子进程 | abort 后任务状态与子进程释放符合预期 | Playwright |
| TC-Phase0-06 | 启动参数单 worker 约束 | 启动脚本固定 `--workers 1` | 手工 |

**Phase 必跑回归包（引用第 4 章）**

- `TC-P0-01` ~ `TC-P0-10`（至少覆盖到取消与非阻塞）。

**Phase 出口标准**

- `TC-Phase0-*` 全通过。
- 回归包无阻断失败。
- 若 `TC-Phase0-05` 失败，禁止进入 Phase 1。

### 8.2 Phase 1（前端壳 + 分离/切片）

**阶段目标**

- React 壳、项目上下文、分离/切片页面可用。
- 项目切换遵循 `key={projectId}` remount，不引入脏值串写。
- 前端 SSE 基础能力和参数提交稳定。

**Phase 新增必测用例**

| ID | 用例 | 关键检查点 | 自动化归属 |
|----|------|------------|------------|
| TC-Phase1-01 | 项目切换 remount 机制 | A 项目未提交参数不污染 B 项目 defaults | Playwright |
| TC-Phase1-02 | 分离页运行与回填 | `run` 后日志完成，defaults/artifacts 刷新 | Playwright |
| TC-Phase1-03 | 切片页模式切换 | `vad/lrc` 切换后表格与音频预览对应正确 | Playwright |
| TC-Phase1-04 | bool 参数提交可靠性 | Collapsible 折叠/展开状态下参数值一致 | Playwright |
| TC-Phase1-05 | 旧项目缓存清理 | 切换项目后旧 query 缓存不污染新页面 | Playwright |
| TC-Phase1-06 | 页面卸载触发取消 | 路由离开或刷新触发 abort 并停止任务 | Playwright |

**Phase 必跑回归包（引用第 4 章）**

- `TC-P0-11`, `TC-P0-12`, `TC-P1-05`, `TC-P1-06`。

**Phase 出口标准**

- `TC-Phase1-*` 全通过。
- `TC-P0-12` 与 `TC-P1-05` 任何一条失败，禁止进入 Phase 2。

### 8.3 Phase 2（转换/合并 + 精修）

**阶段目标**

- Convert 三子模式、Merge 双模式、SliceTuner 精修链路完整可用。
- overrides 全生命周期（读写清理重转）稳定。
- 产物预览与参考音频上传行为正确。

**Phase 新增必测用例**

| ID | 用例 | 关键检查点 | 自动化归属 |
|----|------|------------|------------|
| TC-Phase2-01 | Convert 三模式参数映射 | `slice_batch/full_track` 等模式参数落地正确 | pytest |
| TC-Phase2-02 | 精修 overrides 生命周期 | 查询、保存、回读、清 orphan 全链路正确 | pytest |
| TC-Phase2-03 | 精修重转选中切片 | 仅选中切片重转，日志与产物对应 | Playwright |
| TC-Phase2-04 | Merge 双模式可运行 | `whole_track/slice_stitch` 都可完成并产出 mixed | Playwright |
| TC-Phase2-05 | manifest preview 一致性 | 预览文本与当前项目清单一致 | pytest |
| TC-Phase2-06 | 参考音频上传与回填 | 上传后 defaults 与相关页面回填生效 | Playwright |

**Phase 必跑回归包（引用第 4 章）**

- `TC-P1-03`, `TC-P1-04`, `TC-P1-07`, `TC-P1-08`。

**Phase 出口标准**

- `TC-Phase2-*` 全通过。
- overrides 相关用例（`TC-Phase2-02/03`）必须零失败才能进 Phase 3。

### 8.4 Phase 3（向导 + 批量队列）

**阶段目标**

- 向导三种运行路径（单步/从此步/全流程）稳定。
- 批量队列状态统一 SSE（无 polling），并维持单 GPU 串行。
- 多客户端同时观察状态时保持一致性。

**Phase 新增必测用例**

| ID | 用例 | 关键检查点 | 自动化归属 |
|----|------|------------|------------|
| TC-Phase3-01 | 向导单步运行 | 当前步参数提交、日志和产物一致 | Playwright |
| TC-Phase3-02 | 向导从此步到最后 | 阶段串联顺序与 done 事件完整 | Playwright |
| TC-Phase3-03 | 向导全流程运行 | 从首步到合并流程可闭环完成 | Playwright |
| TC-Phase3-04 | 批量状态常驻 SSE | 入队、运行、清队列时状态实时推送 | Playwright |
| TC-Phase3-05 | run/status 双 SSE 一致性 | `run` 日志与 `status` 列表状态不冲突 | pytest |
| TC-Phase3-06 | 队列串行与顺序性 | 同时多任务入队仍保持单任务运行 | pytest |
| TC-Phase3-07 | 多订阅者一致性 | 多个前端订阅同一 status，状态视图一致 | pytest |

**Phase 必跑回归包（引用第 4 章）**

- `TC-P0-11`, `TC-P1-09`, `TC-P1-10`。

**Phase 出口标准**

- `TC-Phase3-*` 全通过。
- 任意队列一致性失败（`TC-Phase3-05/06/07`）阻断进入 Phase 4。

### 8.5 Phase 4（收尾与发布）

**阶段目标**

- 一键启动、文档、E2E、性能优化项达到可发布状态。
- 并存期兼容可验证，且不破坏 `output/.projects` schema。
- 发布前全量回归稳定。

**Phase 新增必测用例**

| ID | 用例 | 关键检查点 | 自动化归属 |
|----|------|------------|------------|
| TC-Phase4-01 | 一键启动脚本可用 | `start-pipeline-web.bat` 可拉起前后端并连通 | 手工 |
| TC-Phase4-02 | 全量 E2E 冒烟通过 | 核心页面主路径均通过，无阻断失败 | Playwright |
| TC-Phase4-03 | 双 UI 并存兼容性 | 新旧 UI 操作同项目不破坏 store schema | 手工 |
| TC-Phase4-04 | 切片表性能优化验收 | 大数据量场景交互达到预期 | Playwright |
| TC-Phase4-05 | 日志截断策略验收 | 长日志可控、关键状态保留 | Playwright |
| TC-Phase4-06 | 大文件上传稳态 | 大文件上传和处理期间无明显资源失控 | 手工 |

**Phase 必跑回归包（引用第 4 章）**

- 全部 `TC-P0-*`、`TC-P1-*`、`TC-P2-*`。

**Phase 出口标准**

- `TC-Phase4-*` 全通过。
- 全局用例无阻断失败，满足第 6 章发布判定。

### 8.6 每个 Phase 的最小执行集（便于日常开发）

| 时机 | 必跑集合 |
|------|----------|
| 每次提交前（开发者本地） | 当期 `TC-PhaseX-*` + 上一 Phase 的阻断项 |
| 每日集成（CI） | 当期 `TC-PhaseX-*` + 全部 `TC-P0-*` |
| Phase 提测前 | 当期 `TC-PhaseX-*` + 全部 `TC-P0-*` + 相关 `TC-P1-*` |
| Phase 结束评审 | 当期 `TC-PhaseX-*` 全通过 + 对应回归包全通过 |
