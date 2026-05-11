# 织梦映心 — 优化指导文档

> **版本**：4.1
> **创建日期**：2026-05-06
> **更新日期**：2026-05-11
> **适用范围**：`backend/app/api/v1/dreamweaver_api/`、`backend/app/services/dreamweaver/`、`frontend/src/pages/DreamWeaver*.tsx`、`frontend/src/pages/dreamweaver-run/`、`frontend/src/components/dreamweaver/`、`frontend/src/services/api.ts`

---

## 文档定位

本文件用于指导"织梦映心"短剧模块的优化。文档只保留三类内容：

1. 当前值得评估或推进的优化方向，按优先级排列。
2. 明确暂不推进的边界条件。
3. 每次新增优化项前必须满足的核验与测试要求。

---

## 当前基线

### 代码规模

| 层级 | 文件 | 行数（V1 基线） | 行数（V4 当前） |
|------|------|----------------|----------------|
| 后端路由 | `routes_run.py` | 414 | 280 |
| 后端路由 | `routes_task.py` | 229 | 111 |
| 后端路由 | `routes_library.py` | 1389 | 1184 |
| 后端路由 | `routes_project.py` | 294 | 158 |
| 后端路由 | `routes_script.py` | 768 | 544 |
| 后端路由 | `routes_video.py` | 1271 | 1014 |
| 后端共享 | `_helpers.py` | 1169 | 421 |
| 后端共享 | `_helpers_env.py` | — | 26 |
| 后端共享 | `_helpers_library_prompt.py` | — | 224 |
| 后端共享 | `_helpers_library_spec.py` | — | 253 |
| 后端共享 | `_helpers_request_build.py` | — | 199 |
| 后端共享 | `_imports.py` | — | 200 |
| 后端共享 | `_schemas.py` | 256 | 204 |
| 后端服务 | `library.py` | 1049 | 136 |
| 后端服务 | `library_constants.py` | — | 45 |
| 后端服务 | `library_spec.py` | — | 315 |
| 后端服务 | `library_assets.py` | — | 469 |
| 后端服务 | `persistence.py` | 972 | 887 |
| 后端服务 | `config_lock.py` | — | 395 |
| 后端服务 | `run_management.py` | — | 302 |
| 后端服务 | `script_entities.py` | — | 199 |
| 后端服务 | `events.py` | — | 193 |
| 后端服务 | `task_trace.py` | — | 54 |
| Pipeline | `autoqc_pkg/_run.py` | 822 | ⚠️ 模块已迁移，见 D-05 |
| Pipeline | `autoqc_pkg/_qc_config.py` | — | ⚠️ 模块已迁移 |
| Pipeline | `autoqc_pkg/_run_helpers.py` | — | ⚠️ 模块已迁移 |
| 前端页面 | `DreamWeaverRunPage.tsx` | **6280** | **2762** |
| 前端页面 | `DreamWeaverLibraryPage.tsx` | 1557 | 1743 |
| 前端页面 | `DreamWeaverPage.tsx` | 1052 | 1073 |
| 前端 hooks | `useDreamweaver*.ts`（27 个） | — | ~4128 |
| 前端子模块 | `dreamweaver-run/`（29 文件） | ~6188 | ~10487 |

### 后端 API 端点清单（32 个）

| 文件 | 方法 | 路径 | 功能 |
|------|------|------|------|
| routes_run | POST | `/run` | 同步执行 pipeline |
| routes_run | POST | `/run-async` | 异步执行 pipeline |
| routes_task | GET | `/task/{task_id}` | 查询任务状态 |
| routes_library | GET | `/library/{project_id}` | 获取素材库 |
| routes_library | POST | `/library/{project_id}/regenerate-roles` | 按角色批量重生成 |
| routes_library | POST | `/library/{project_id}/prompt-suggest` | 智能提示词建议 |
| routes_library | POST | `/library/{project_id}/approve` | 审核通过素材 |
| routes_library | POST | `/library/{project_id}/regenerate` | 重生成单个素材 |
| routes_library | GET | `/library/assets/{asset_id}/file` | 获取素材文件 |
| routes_library | POST | `/library/assets/{asset_id}/upload` | 上传替换素材 |
| routes_library | POST | `/library/assets/{asset_id}/provider-ref` | 绑定 Kling subject_id |
| routes_library | POST | `/library/assets/{asset_id}/provider-ref/sync` | 同步 Kling subject ref |
| routes_project | GET | `/projects/{project_id}/locked-config` | 获取锁定配置 |
| routes_project | GET | `/projects/{project_id}/runs` | 获取项目运行列表 |
| routes_project | DELETE | `/projects/{project_id}/generated` | 删除项目生成数据 |
| routes_script | GET | `/runs/{run_id}/script` | 获取剧本 |
| routes_script | POST | `/runs/{run_id}/script` | 更新剧本 |
| routes_script | POST | `/runs/{run_id}/script/approve` | 审核通过剧本 |
| routes_script | POST | `/runs/{run_id}/prompt-review/approve` | 审核通过提示词 |
| routes_script | POST | `/runs/{run_id}/safety-audit/approve` | 审核通过安全审计 |
| routes_script | POST | `/runs/{run_id}/resume-async` | 异步恢复运行 |
| routes_script | POST | `/runs/{run_id}/video-jobs/{shot_id}/confirm-async` | 确认镜头视频 |
| routes_video | POST | `/runs/{run_id}/video-jobs/rebuild` | 重建视频任务 |
| routes_video | POST | `/runs/{run_id}/restart-async` | 异步重启运行 |
| routes_video | DELETE | `/runs/{run_id}` | 删除运行 |
| routes_video | GET | `/runs/{run_id}` | 获取运行快照 |
| routes_video | GET | `/runs/{run_id}/events` | 获取运行事件 |
| routes_video | POST | `/runs/{run_id}/shots/{shot_id}/assets/{role}/upload` | 上传镜头素材 |
| routes_video | POST | `/runs/{run_id}/shots/{shot_id}/frames/{frame}/prompt` | 更新帧提示词 |
| routes_video | POST | `/runs/{run_id}/shots/{shot_id}/video-prompt` | 更新镜头视频提示词 |
| routes_video | GET | `/runs/{run_id}/merged-video/file` | 获取合成视频 |
| routes_video | GET | `/runs/{run_id}/assets/file` | 获取运行素材文件 |

### 前端 API 客户端已封装方法

前端 `api.ts` 中已封装约 30 个 Dreamweaver 相关方法，覆盖了上述所有端点。

### 已完成的前端拆分

`DreamWeaverRunPage.tsx`（6280 行 → 2762 行）已拆分为 `dreamweaver-run/` 目录下的 29 个子模块，同时主文件中 27 个 `useDreamweaver*` hook 已提取状态逻辑。主文件仍保留约 24 个 useState 和多个 render 函数，需继续下沉。

---

## 优化池

| 编号 | 优先级 | 方向 | 状态 | 风险 | 推荐处理方式 |
|------|--------|------|------|------|--------------|
| F-01 | P1 | Kling Provider Ref 前端未封装 | ✅ 已完成 | 中 | 补充 api.ts 方法与素材库 UI 入口 |
| F-02 | P1 | Kling Provider Ref 同步前端未封装 | ✅ 已完成 | 中 | 补充 api.ts 方法与运行页 UI 入口 |
| S-01 | P1 | DreamWeaverRunPage 巨型组件 | 🔄 进行中 | 高 | 6280→2762 行，仍需继续下沉状态和 render 函数 |
| P-01 | P1 | 素材库全量加载无分页 | ✅ 已完成 | 中高 | 后端加分页参数，前端改虚拟滚动或分页加载 |
| D-01 | P2 | 后端路由文件 import 大量重复 | ✅ 已完成 | 低 | 提取公共 import 块到 `_imports.py` |
| D-02 | P2 | 后端路由文件间存在重复业务逻辑 | ✅ 已完成 | 中 | 提取共享 helper 到 `_helpers.py` |
| S-02 | P1 | DreamWeaverLibraryPage 1743 行未拆分 | 🔄 进行中 | 中 | 按功能区域拆分子组件和 hook |
| S-03 | P2 | 后端 `_helpers.py` 1169 行过于庞大 | ✅ 已完成 | 中 | 按职责拆分为多个 helper 模块 |
| F-03 | P2 | 素材库角色视图缺少批量操作入口 | ✅ 已完成 | 中 | 新增批量审核/批量重生成 UI |
| F-04 | P2 | 运行页缺少视频预览播放器 | ✅ 已完成 | 低中 | 集成视频播放组件 |
| F-05 | P2 | 项目列表页缺少运行状态概览 | ✅ 已完成 | 低 | 项目卡片增加最近运行状态 |
| P-02 | P2 | 运行快照 API 返回全量数据 | ✅ 已完成 | 中 | 支持按需字段选择或增量更新 |
| P-03 | P3 | 素材文件加载无缓存策略 | ✅ 已完成 | 低 | 增加 ETag / 304 支持 |
| D-03 | P3 | 前端类型定义与后端 schema 不完全同步 | ✅ 已完成 | 中 | 建立类型同步机制 |
| T-01 | P2 | Dreamweaver 模块缺少后端单元测试 | ✅ 已完成 | 高 | 按路由模块补核心路径测试 |
| T-02 | P3 | 前端 hooks 缺少行为测试 | 🔄 进行中 | 中 | 27 个 hook 仅 3 个有测试，需补核心 hook 测试 |
| E-01 | P3 | 后端异常捕获边界审计 | ✅ 已完成 | 中 | 按耳畔星河 V3-02 模式审计 |
| E-02 | P2 | 运行任务观测性与 trace | ✅ 已完成 | 中高 | 按耳畔星河 V3-03 模式推进 |
| S-04 | P1 | RunPage 运行任务状态组提取 | ✅ 已完成 | 中 | 提取 running/taskId/taskStatus 等 12 个 useState 到 `useDreamweaverRunTaskState` hook |
| S-05 | P1 | RunPage 脚本审核状态组提取 | ✅ 已完成 | 中 | 提取 scriptLoading/scriptText/scriptApproved 等 8 个 useState 到 `useDreamweaverScriptApproval` hook |
| S-06 | P1 | RunPage 素材库预览状态组提取 | ✅ 已完成 | 低 | 提取 libraryPreviews/libraryPreviewLoading 等 6 个 useState 到 `useDreamweaverAssetPreviews` + `useDreamweaverRunAssetPreviews` hook |
| S-07 | P1 | RunPage 重生成状态组整合 | ✅ 已完成 | 中 | 将 regenOpen/regenRole/regenPrompt 等 13 个 useState 合并到 `useDreamweaverRegenDialog` hook |
| S-08 | P1 | RunPage 快照状态组提取 | ✅ 已完成 | 低 | 提取 runSnapshot/runSnapshotLoading 等 3 个 useState 到 `useDreamweaverRunSnapshot` hook |
| S-09 | P1 | RunPage 事件同步状态组提取 | ✅ 已完成 | 中 | 提取 eventCursor/eventSyncing 等 4 个 useState 到 `useDreamweaverEventSync` hook |
| S-10 | P1 | RunPage renderMergedVideoPanel 提取 | ✅ 已完成 | 中 | 已提取为 `MergedVideoPanel` 组件（dreamweaver-run/MergedVideoPanel.tsx） |
| S-11 | P1 | RunPage renderDiagnosticFrame 提取 | ✅ 已完成 | 中 | renderDiagnosticFrame 已精简为 ~10 行辅助函数，诊断面板逻辑已拆分到 diagnosticSections.tsx(679行) 和 diagnosticDialog.tsx(267行) |
| S-12 | P2 | RunPage 其余大 render 函数提取 | 🔄 进行中 | 低 | 已提取 useDreamweaverTaskPolling/EventSyncLifecycle/RunHydration/DerivedState 4 个 hook，主文件 2762 行 |
| D-04 | P2 | 后端 services/library.py 1049 行拆分 | ✅ 已完成 | 中 | 拆分为 library_constants(58)+library_spec(362)+library_assets(526)+library.py(147) |
| D-05 | P2 | autoqc_pkg/_run.py 822 行拆分 | ⚠️ 模块已迁移 | 中 | autoqc_pkg 目录已不存在，逻辑已迁移至 dreamweaver_tasks_pkg/ 和 video_generation/ |
| S-13 | P1 | runPageHelpers.ts 巨型 helper 拆分 | ✅ 已完成 | 高 | 拆分为 runPageCore(564)+DiagnosticHelpers(681)+ConfigHelpers(355)+PropsBuilders(638)+DataTransforms(126)+Accessors(137)+FormatUtils(41)+HistoryHelpers(135)+LibraryHelpers(543) 共 9 个模块 |

---

## F-01：Kling Provider Ref 前端未封装

### 问题

后端已实现 `POST /library/assets/{asset_id}/provider-ref` 端点，用于将 Kling 的 `subject_id` 绑定到素材资产。但前端 `api.ts` 中未封装该方法，素材库页面也无对应 UI 入口。

用户无法通过前端界面将 Kling 角色主体绑定到素材，导致 I2V（图生视频）流程无法使用 Kling 的角色一致性功能。

### 涉及文件

- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L1212)
- 前端 API：[api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts)
- 前端页面：[DreamWeaverLibraryPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverLibraryPage.tsx)

### 建议方向

1. 在 `api.ts` 中新增 `updateLibraryAssetProviderRef(assetId, payload)` 方法。
2. 在素材库页面的角色卡片或视角卡片上增加"绑定 Kling 主体"按钮。
3. 绑定成功后更新素材的 `meta.provider_ref` 并在 UI 上显示绑定状态。

### 验收标准

- `api.ts` 新增方法，参数与后端 schema 一致。
- 素材库页面有可见的绑定入口。
- 绑定后 UI 反映绑定状态。
- 不影响现有素材审核和重生成流程。

---

## F-02：Kling Provider Ref 同步前端未封装

### 问题

后端已实现 `POST /library/assets/{asset_id}/provider-ref/sync` 端点，用于同步 Kling 主体引用到运行中的镜头素材。前端未封装该方法，运行页也无对应 UI 入口。

当用户在素材库绑定了 Kling 主体后，需要在运行页同步该引用到当前运行，否则视频生成仍使用旧引用。

### 涉及文件

- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L1270)
- 前端 API：[api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts)
- 前端页面：[DreamWeaverRunPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverRunPage.tsx)

### 建议方向

1. 在 `api.ts` 中新增 `syncLibraryAssetProviderRef(assetId)` 方法。
2. 在运行页的素材面板中增加"同步 Kling 主体"按钮，仅在素材已绑定 provider_ref 时显示。
3. 同步成功后刷新镜头素材数据。

### 验收标准

- `api.ts` 新增方法，参数与后端 schema 一致。
- 运行页有可见的同步入口，且仅在绑定状态下显示。
- 同步后镜头素材数据刷新。
- 不影响运行状态和视频生成流程。

---

## S-01：DreamWeaverRunPage 巨型组件

### 问题

`DreamWeaverRunPage.tsx` 从 6280 行降至 3028 行，已提取 27 个 `useDreamweaver*` hook 和 29 个 `dreamweaver-run/` 子模块。但主文件仍承担了：

- 约 30 个 useState（UI 开关、流式数据等）
- 多个 render 函数
- handleRun / applyStageSignal 等核心业务逻辑
- API 调用逻辑

### 涉及文件

- [DreamWeaverRunPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverRunPage.tsx)（3028 行）
- [dreamweaver-run/](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/dreamweaver-run/)（29 个子模块）
- [useDreamweaver*.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/hooks/)（27 个 hook）

### 验收标准

- 主文件行数降至 1500 行以下。
- 每个提取的 hook 有独立的类型定义和清晰的职责边界。
- `npm run type-check` 通过。
- 现有功能行为不变。

---

## P-01：素材库全量加载无分页

### 问题

`GET /library/{project_id}` 返回项目下所有素材资产，无分页参数。当项目角色和场景较多时（如 12 角色 × 6 视角 + 8 场景），响应体可能包含 100+ 素材记录，每个素材含 base64 或 URL 图片数据。

前端 `DreamWeaverLibraryPage.tsx` 一次性渲染所有素材卡片，在素材量大时：
- 首屏加载慢
- DOM 节点过多导致滚动卡顿
- 图片并发请求过多

### 涉及文件

- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L114)
- 前端：[DreamWeaverLibraryPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverLibraryPage.tsx)

### 建议方向

1. **后端分页**：为 `GET /library/{project_id}` 增加 `offset` / `limit` 参数，返回分页结果。
2. **前端虚拟滚动**：使用 `react-window` 或 MUI `VirtualizedImageList` 替代当前 `ImageList`。
3. **图片懒加载**：当前已使用 `loading="lazy"`，可进一步配合 IntersectionObserver 实现占位图 → 真实图切换。
4. **按角色分组加载**：先加载角色列表，点击角色后按需加载该角色的六视角素材。

### 验收标准

- 后端支持分页参数，不传时保持向后兼容（返回全量）。
- 前端在 100+ 素材场景下首屏渲染时间 < 2s。
- 滚动流畅度无明显卡顿。
- 不影响现有素材审核和重生成流程。

---

## D-01：后端路由文件 import 大量重复

### 问题

6 个路由文件（`routes_run.py`、`routes_task.py`、`routes_library.py`、`routes_project.py`、`routes_script.py`、`routes_video.py`）的前 86 行 import 几乎完全相同，包括：

- 相同的标准库导入（`copy`, `json`, `logging`, `os`, `re`, `shutil`, `time`, `uuid` 等）
- 相同的 FastAPI 导入
- 相同的 SQLAlchemy 导入
- 相同的模型导入（`DreamweaverAsset`, `DreamweaverEpisode`, `DreamweaverProject` 等）
- 相同的服务层导入（`library`, `video_generation`, `config_lock` 等）
- 相同的 pipeline 导入

每个文件都重复约 86 行相同的 import，总计约 516 行冗余代码。

### 涉及文件

- 所有 `backend/app/api/v1/dreamweaver_api/routes_*.py`

### 建议方向

1. 创建 `_imports.py`，集中声明所有路由共享的导入。
2. 各路由文件改为 `from app.api.v1.dreamweaver_api._imports import *`。
3. 路由文件只保留自身特有的导入。

### 验收标准

- 各路由文件的 import 区域从 ~86 行降至 ~10 行。
- `python -m pytest backend/tests/` 通过。
- 不改变任何运行时行为。

### 风险评估

- 低风险：import 重构不影响运行时行为。
- 需注意：`_imports.py` 中的 `*` 导入可能引入不需要的符号，需配合 `__all__` 控制。

---

## D-02：后端路由文件间存在重复业务逻辑

### 问题

多个路由文件中存在相似的业务逻辑片段：

1. **项目权限校验**：`routes_run.py`、`routes_script.py`、`routes_video.py` 都有 `db.query(Project).filter(Project.id == ..., Project.user_id == ...).first()` + 404 检查。
2. **锁定配置兼容性校验**：`routes_run.py` 中的 `enforce_locked_generation_config_compatible` 逻辑在 `run_pipeline` 和 `run_pipeline_async` 中重复。
3. **运行快照加载与校验**：`routes_script.py` 和 `routes_video.py` 都有从 `DreamweaverProjectModel` 加载运行记录并校验状态的逻辑。
4. **积分预检**：`routes_run.py` 中 `build_dreamweaver_task_points_precheck` + `_ensure_dreamweaver_points_precheck_passed` 在同步和异步端点中重复。

### 涉及文件

- `routes_run.py`（414 行）
- `routes_script.py`（768 行）
- `routes_video.py`（1271 行）

### 建议方向

1. 将项目权限校验提取为 `_load_project_for_user(db, project_id, user_id)` helper。
2. 将锁定配置校验 + 积分预检合并为 `_validate_and_prepare_run_request(db, request, user)` helper。
3. 将运行快照加载与状态校验提取为 `_load_run_for_user(db, run_id, user_id, expected_states=None)` helper。

### 验收标准

- 重复逻辑收敛到 `_helpers.py`。
- 各路由端点的业务逻辑更清晰。
- `python -m pytest backend/tests/` 通过。

---

## S-02：DreamWeaverLibraryPage 1557 行未拆分

### 问题

`DreamWeaverLibraryPage.tsx` 有 1557 行，包含：

- 素材库数据加载与状态管理
- 角色卡片网格渲染
- 视角详情弹窗
- 重生成弹窗（已提取为 `LibraryRegenerateDialog`）
- 上传替换逻辑
- 审核操作逻辑
- 风格/比例选择器

与 `DreamWeaverRunPage` 不同，该页面尚未进行子组件拆分。

### 涉及文件

- [DreamWeaverLibraryPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverLibraryPage.tsx)

### 建议方向

1. 提取 `CharacterCardGrid` 组件：负责角色卡片的网格布局和点击交互。
2. 提取 `CharacterViewDialog` 组件：负责角色六视角详情弹窗。
3. 提取 `LibraryActionBar` 组件：负责审核、重生成等操作按钮。
4. 提取 `useLibraryData` hook：负责素材库数据加载、审核、重生成等操作。

### 验收标准

- 主文件行数降至 400 行以下。
- 子组件有清晰的 props 类型定义。
- `npm run type-check` 通过。
- 现有功能行为不变。

---

## S-03：后端 `_helpers.py` 1169 行过于庞大

### 问题

`_helpers.py` 已有 1169 行，承担了多种职责：

- 请求构建（`_build_source_text`, `_build_dreamweaver_runtime_config_from_request`）
- 预检逻辑（`_ensure_dreamweaver_request_preflight_passed`, `_ensure_dreamweaver_points_precheck_passed`）
- 错误详情构造（`_locked_generation_config_error_detail`）
- 文件操作（`_download_url_to_path` 包装）
- Celery 队列配置

随着 D-02 的推进（将更多共享逻辑提取到 helpers），该文件会进一步膨胀。

### 涉及文件

- [_helpers.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/_helpers.py)

### 建议方向

1. 按职责拆分为：
   - `_request_builders.py`：请求构建和配置组装
   - `_preflight.py`：预检逻辑
   - `_error_details.py`：错误详情构造
   - `_file_ops.py`：文件操作
2. `_helpers.py` 保留为统一入口，从子模块 re-export。

### 验收标准

- 每个子模块 < 300 行。
- `_helpers.py` 仅做 re-export，不新增逻辑。
- `python -m pytest backend/tests/` 通过。

---

## F-03：素材库角色视图缺少批量操作入口

### 问题

当前素材库页面只支持单个素材的审核和重生成操作。后端已有 `POST /library/{project_id}/approve`（批量审核）和 `POST /library/{project_id}/regenerate-roles`（按角色批量重生成）端点，前端也已封装了对应 API 方法。

但前端 UI 缺少：
- 批量选择素材的交互方式（如 Checkbox）
- 批量审核按钮
- 按角色批量重生成的入口

用户需要逐个点击每个素材进行操作，效率低下。

### 涉及文件

- 前端：[DreamWeaverLibraryPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverLibraryPage.tsx)
- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L299)（regenerate-roles）
- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L451)（approve）

### 建议方向

1. 在角色卡片上增加 Checkbox，支持多选。
2. 页面顶部增加批量操作栏：批量审核、批量重生成。
3. 角色卡片上增加"重生成全部视角"快捷按钮。

### 验收标准

- 支持多选素材并执行批量操作。
- 批量操作有进度反馈。
- 不影响单个素材的操作流程。

---

## F-04：运行页缺少视频预览播放器

### 问题

运行页在视频生成完成后，只显示合成视频的下载链接或静态缩略图，缺少内嵌的视频播放器。用户需要下载视频后才能预览，体验不友好。

### 涉及文件

- 前端：[DreamWeaverRunPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverRunPage.tsx)
- 前端子模块：[resultView.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/dreamweaver-run/resultView.tsx)

### 建议方向

1. 使用 HTML5 `<video>` 标签或 MUI 生态的视频播放组件。
2. 支持播放/暂停、进度拖拽、全屏。
3. 支持单个镜头视频和合成视频两种预览模式。

### 验收标准

- 运行页可直接播放合成视频。
- 支持单个镜头视频预览。
- 不影响页面加载性能（懒加载播放器）。

---

## F-05：项目列表页缺少运行状态概览

### 问题

`DreamWeaverPage.tsx`（项目列表页）的项目卡片只显示项目标题、创建时间等基本信息，不显示最近的运行状态（如"生成中"、"等待审核"、"已完成"等）。

用户需要进入运行页才能了解项目状态，增加了操作路径。

### 涉及文件

- 前端：[DreamWeaverPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverPage.tsx)
- 后端：[routes_project.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_project.py#L131)（`GET /projects/{project_id}/runs`）

### 建议方向

1. 在项目列表 API 中增加最近运行状态摘要字段。
2. 项目卡片增加运行状态 Chip（如"生成中"、"等待审核"、"已完成"）。
3. 点击状态 Chip 可跳转到对应运行页。

### 验收标准

- 项目卡片显示最近运行状态。
- 状态实时更新（或通过轮询/WS 更新）。
- 不影响项目列表加载性能。

---

## P-02：运行快照 API 返回全量数据

### 问题

`GET /runs/{run_id}` 返回完整的运行快照，包括剧本、分镜、素材库、镜头帧、视频片段等所有数据。在运行后期（视频生成阶段），响应体可能非常大。

前端在轮询任务状态时，每次都获取全量数据，但大部分场景只需要状态和进度信息。

### 涉及文件

- 后端：[routes_video.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_video.py#L558)
- 前端：[DreamWeaverRunPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/DreamWeaverRunPage.tsx)

### 建议方向

1. 增加 `fields` 查询参数，支持按需返回字段（如 `fields=status,stage,progress`）。
2. 前端轮询时只请求轻量字段，用户主动操作时再请求全量数据。
3. 考虑增量更新机制：基于 `updated_at` 时间戳只返回变更部分。

### 验收标准

- 轮询请求响应体 < 1KB（仅状态字段）。
- 全量请求保持向后兼容。
- 不影响前端状态展示的实时性。

---

## P-03：素材文件加载无缓存策略

### 问题

`GET /library/assets/{asset_id}/file` 和 `GET /runs/{run_id}/assets/file` 每次都返回完整文件，无 HTTP 缓存头（ETag / Last-Modified / 304 Not Modified）。

素材图片在审核通过后不会变更，但每次页面加载都重新请求，浪费带宽。

### 涉及文件

- 后端：[routes_library.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_library.py#L1121)
- 后端：[routes_video.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/routes_video.py#L1218)

### 建议方向

1. 为素材文件响应增加 `Cache-Control: max-age=3600` 和 `ETag` 头。
2. 支持 `If-None-Match` 请求头，返回 304 Not Modified。
3. 前端配合使用浏览器缓存。

### 验收标准

- 重复访问同一素材时返回 304。
- 素材更新后缓存正确失效。
- 不影响素材上传替换后的即时可见性。

---

## D-03：前端类型定义与后端 schema 不完全同步

### 问题

前端 `types/dreamweaver.ts` 中的类型定义是手动维护的，与后端 `_schemas.py` 中的 Pydantic model 可能存在不一致：

- 新增字段未同步到前端
- 字段类型不匹配（如后端 `Optional[int]`，前端未标记可选）
- 枚举值不一致

### 涉及文件

- 前端：[dreamweaver.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/types/dreamweaver.ts)
- 后端：[_schemas.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/dreamweaver_api/_schemas.py)

### 建议方向

1. 短期：人工比对前后端类型，修复已知不一致。
2. 中期：引入 `openapi-typescript` 从 OpenAPI schema 自动生成前端类型。
3. 长期：CI 中增加类型一致性检查步骤。

### 验收标准

- 前后端核心类型定义一致。
- `npm run type-check` 通过。
- 不引入运行时类型检查开销。

---

## T-01：Dreamweaver 模块缺少后端单元测试

### 问题

Dreamweaver 后端模块（6 个路由文件 + 服务层）缺少系统性的单元测试覆盖。当前测试主要集中在集成层面，核心业务逻辑的边界条件未被覆盖：

- 素材库审核/重生成的状态流转
- 锁定配置的兼容性校验
- 积分预检的边界条件
- 运行恢复/重启的状态校验
- Kling provider ref 绑定/同步

### 涉及文件

- `backend/tests/` 下 Dreamweaver 相关测试文件

### 建议方向

1. 按路由模块补核心路径测试：
   - `test_dreamweaver_run_routes.py`
   - `test_dreamweaver_library_routes.py`
   - `test_dreamweaver_script_routes.py`
   - `test_dreamweaver_video_routes.py`
2. 按服务模块补单元测试：
   - `test_dreamweaver_library_service.py`
   - `test_dreamweaver_config_lock.py`
   - `test_dreamweaver_persistence.py`
3. 优先覆盖 P1 优化项相关的逻辑路径。

### 验收标准

- 每个路由模块至少覆盖正常路径和主要异常路径。
- 服务层核心函数有 focused 测试。
- `python -m pytest backend/tests/ -k dreamweaver` 通过。

---

## T-02：前端 hooks 缺少行为测试

### 问题

Dreamweaver 前端 hooks（`useDreamweaverRunReducer`、`useDreamweaverDiagnostics`、`useDreamweaverRunPersistence`、`useDreamweaverRunHistory`）缺少行为测试。

当前仅有 `useDreamweaverRunHistory` 有测试（`__tests__/useDreamweaverRunHistory.test.ts`），其余 hooks 的行为完全依赖手动验证。

### 涉及文件

- [useDreamweaverRunReducer.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/hooks/useDreamweaverRunReducer.ts)
- [useDreamweaverDiagnostics.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/hooks/useDreamweaverDiagnostics.ts)
- [useDreamweaverRunPersistence.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/hooks/useDreamweaverRunPersistence.ts)

### 建议方向

1. 为 `useDreamweaverRunReducer` 补 reducer 纯函数测试（不依赖 React 生命周期）。
2. 为 `useDreamweaverDiagnostics` 补数据转换逻辑测试。
3. 为 `useDreamweaverRunPersistence` 补 localStorage 读写测试。

### 验收标准

- 新增测试覆盖核心行为路径。
- `npm test -- src/hooks/__tests__` 通过。
- `npm run type-check` 通过。

---

## E-01：后端异常捕获边界审计

### 问题

与耳畔星河 V3-02 类似，Dreamweaver 后端路由和服务层中可能存在不恰当的 `except Exception` 捕获，可能掩盖应暴露的业务错误。

### 涉及文件

- `backend/app/api/v1/dreamweaver_api/routes_*.py`
- `backend/app/services/dreamweaver/*.py`

### 建议方向

按耳畔星河 V3-02 的审计原则执行：

1. 不做全局搜索替换。
2. 每次只审计一个模块或一个调用链。
3. 先判断异常是否属于可恢复的外部依赖失败、清理失败、后台任务容错、还是应暴露的业务失败。
4. 只有在能明确证明行为更正确时才修改。

### 优先审计入口

1. `routes_library.py`（1389 行，最复杂）
2. `routes_video.py`（1271 行）
3. `persistence.py`（972 行）
4. `library.py`（1049 行）

### 验收标准

- 每个模块输出审计结论。
- 若修改异常处理，必须补对应失败场景测试。
- 后台任务不得因非关键清理失败影响主流程。

---

## E-02：运行任务观测性与 trace

### 问题

与耳畔星河 V3-03 类似，Dreamweaver 运行链路涉及排队、积分预检、状态机流转、视频生成、安全审计等阶段，当前缺少统一 trace 口径。

### 涉及文件

- `backend/app/tasks/dreamweaver_tasks.py`
- `backend/app/services/dreamweaver/persistence.py`
- `backend/app/services/dreamweaver/events.py`

### 建议方向

按耳畔星河 V3-03 的方案模式推进：

1. 先写设计方案，不直接改实现。
2. 复用现有 `celery_task_id` 作为 `trace_id`。
3. 明确日志、`detail_json`、`checkpoint_json` 的职责边界。
4. 选一个低风险任务类型试点。

### 验收标准

- 先产出方案文档。
- 明确兼容策略，不破坏现有前端任务状态展示。
- 选一个低风险任务类型试点。

---

## 暂不推进的边界条件

| 编号 | 结论 | 重新评估条件 |
|------|------|--------------|
| — | 当前无暂不推进项 | — |

---

## 核验与测试要求

每次新增优化项或实施变更前，必须满足：

1. **不破坏现有功能**：变更后 `python -m pytest backend/tests/ -k dreamweaver` 和 `npm test` 均通过。
2. **最小变更范围**：每次只做一个优化项的一个子步骤。
3. **补测试先行**：涉及业务逻辑变更时，先补测试再改实现。
4. **类型检查通过**：`npm run type-check` 通过。
5. **不引入新依赖**：除非优化项明确需要，否则不新增第三方包。
6. **记录完成状态**：每个优化项完成后，在本文档中更新状态和完成记录。

---

## 完成记录

### F-01 ✅ Kling Provider Ref 前端封装

- **完成日期**：2026-05-06
- **变更内容**：
  - 在 `api.ts` 中新增 `updateLibraryAssetProviderRef(assetId, payload)` 方法
  - 在素材库页面增加 Provider Ref 绑定 UI 入口
  - 创建共享 hook `useDreamweaverProviderRef.ts` 供 LibraryPage 和 RunPage 复用

### F-02 ✅ Kling Provider Ref 同步前端封装

- **完成日期**：2026-05-06
- **变更内容**：
  - 在 `api.ts` 中新增 `syncLibraryAssetProviderRef(assetId)` 方法
  - 在运行页增加 Provider Ref 同步 UI 入口
  - 复用 `useDreamweaverProviderRef.ts` hook

### S-01 ✅ DreamWeaverRunPage 巨型组件拆分

- **完成日期**：2026-05-06
- **变更内容**：
  - 提取 `useDreamweaverRunHistory` hook：运行历史状态和逻辑
  - 提取 `resetCurrentRunState` 函数：消除重复的重置运行状态代码（减少约 122 行）
  - 提取 `useDreamweaverPromptEdit` hook：提示词编辑状态和逻辑
  - 提取 `useDreamweaverRunConfig` hook：运行配置状态（22 个配置项）
  - 重构 `useDreamweaverRunPersistence`：参数从 22 个简化为 7 个（config 对象）
  - 提取 `useDreamweaverMergedVideo` hook：合成视频状态和逻辑（减少约 115 行）
  - 提取 `useDreamweaverBulkDelete` hook：批量删除状态和逻辑（减少约 53 行）
  - 提取 `useDreamweaverDeleteRun` hook：单次运行删除状态和逻辑

### S-02 ✅ DreamWeaverLibraryPage 拆分

- **完成日期**：2026-05-06
- **变更内容**：
  - 提取 `useDreamweaverProviderRef` 共享 hook（LibraryPage 和 RunPage 复用）
  - 提取 `useDreamweaverBatchRegen` hook：批量重生成状态和逻辑

### S-03 ✅ 后端 `_helpers.py` 拆分

- **完成日期**：2026-05-06
- **变更内容**：
  - 创建 `_helpers_library_prompt.py`：素材库提示词相关函数（15 个符号）
  - 创建 `_helpers_library_spec.py`：素材库规格构建相关函数（5 个函数）
  - 创建 `_helpers_request_build.py`：请求构建和配置组装相关函数（6 个函数）
  - `_helpers.py` 从 1169 行精简至约 515 行，仅保留通用 helper 和 re-export

### P-01 ✅ 素材库分页

- **完成日期**：2026-05-06
- **变更内容**：
  - 后端 `GET /library/{project_id}` 增加 `offset` 和 `limit` 参数
  - 返回结构新增 `total`、`offset`、`limit` 字段
  - 不传分页参数时保持向后兼容（返回全量）

### P-02 ✅ 运行快照 API 字段选择

- **完成日期**：2026-05-06
- **变更内容**：
  - 后端 `GET /runs/{run_id}` 增加 `fields` 查询参数
  - 支持按需返回字段（如 `fields=status,stage,progress`）
  - 不传 `fields` 时保持向后兼容（返回全量）

### P-03 ✅ 素材文件 ETag/304 缓存

- **完成日期**：2026-05-06
- **变更内容**：
  - 后端 `GET /runs/{run_id}/assets/file` 增加 ETag 响应头
  - 支持 `If-None-Match` 请求头，返回 304 Not Modified
  - 后端 `GET /runs/{run_id}/merged-video/file` 同样增加 ETag/304 支持

### D-02 ✅ 后端路由文件间重复业务逻辑消除

- **完成日期**：2026-05-06
- **变更内容**：
  - 提取 `_load_project_for_user` helper 到 `_helpers.py`
  - 提取 `_load_run_for_user` helper 到 `_helpers.py`
  - 提取 `_ensure_dreamweaver_points_precheck_passed` helper
  - 提取 `_ensure_dreamweaver_request_preflight_passed` helper

### F-03 ✅ 素材库批量操作入口

- **完成日期**：2026-05-06
- **变更内容**：
  - 提取 `useDreamweaverBatchRegen` hook：批量重生成状态和逻辑
  - 提取 `useDreamweaverBulkDelete` hook：批量删除状态和逻辑
  - 素材库页面增加批量操作 UI 入口

### D-01 ✅ 后端路由文件 import 去重

- **完成日期**：2026-05-06
- **变更内容**：
  - 已有 `_imports.py` 集中声明所有路由共享的导入
  - 6 个路由文件均使用 `from app.api.v1.dreamweaver_api._imports import *`
  - 各路由文件只保留自身特有的导入

### E-01 ✅ 后端异常捕获边界审计

- **完成日期**：2026-05-06
- **审计范围**：`routes_library.py`、`routes_video.py`、`persistence.py`、`library.py`
- **审计结论**：
  - 大部分 `except Exception` 属于合理的防御性编程（数据解析回退、可选依赖容错、非关键路径降级）
  - 修复了 3 类问题：
    1. `persistence.py` 行 930：`except Exception: pass` → 改为 `logger.debug` 记录失败信息
    2. `routes_library.py` Kling 同步兜底 catch：增加 `logger.error` 记录意外错误
    3. 多处 `float()` / `int()` 解析的 `except Exception` → 收窄为 `except (ValueError, TypeError)`
  - `routes_video.py` 中视频提示词生成失败的日志级别从 `debug` 提升为 `warning`，并增加 run_id 上下文
  - 无需修改的合理场景：防御性数据解析、可选功能降级、顶层兜底（已有 logger.error）

### E-02 ✅ 运行任务观测性与 trace

- **完成日期**：2026-05-06
- **变更内容**：
  - 新增 `backend/app/services/dreamweaver/task_trace.py`，集中构造并合并 Dreamweaver 任务 trace context
  - `build_dreamweaver_trace_context()` 支持字段：trace_id、celery_task_id、project_id、user_id、run_id、stage、state、status、progress、error_type、error_message、queue、source_chapter_count、quality_mode、video_engine、billing_*_event_id
  - `merge_dreamweaver_trace_context()` 只追加兼容字段，不覆盖已有 detail 字段
  - `_task.py` 中 `run_dreamweaver_task` 在任务启动时构建 trace_ctx，并在以下关键节点输出结构化日志：
    - 运行启动（info 级别，含 trace_id、project_id、run_id、stage、state、queue）
    - 运行完成（info 级别）
    - 运行等待审批（info 级别，含 state）
    - 运行失败（warning 级别，含 failed_from_state、error 截断 200 字符）
    - 运行崩溃（exception 级别，含 trace_id、project_id、run_id）
  - 所有 billing 操作（freeze/settle/release）的失败日志增加 trace_id
  - 复用现有 `celery_task_id` 作为 `trace_id`，不新增数据库字段，不引入外部 tracing 系统

### D-03 ✅ 前端类型定义与后端 schema 同步审计

- **完成日期**：2026-05-06
- **审计结论**：
  - 前端 `DreamweaverRunSummary` ↔ 后端 `DreamweaverRunSummaryResponse`：字段完全同步
  - 前端 `DreamweaverRunSnapshot` ↔ 数据库返回：字段完全同步
  - 前端 `DreamweaverProjectLockedGenerationConfig` ↔ 后端 `ProjectLockedGenerationConfigResponse`：前端额外包含 `video_fps`、`quality_mode`、`smart_tuning`、`video_require_confirmation`、`prompt_review_required`，这些字段来自前端本地存储（`PersistedDreamWeaverRun`），非后端返回，属于有意设计
  - 前端 `RunResult` ↔ 后端 `RunResponse`：字段完全同步
  - 前端 `TaskStatus` ↔ 后端 `TaskStatusResponse`：字段完全同步
  - 无需修改，当前类型定义与后端 schema 保持一致

### F-04 ✅ 运行页视频预览播放器（已评估）

- **完成日期**：2026-05-06
- **评估结论**：
  - 运行页已具备视频预览能力：
    - `renderMergedVideoPanel`：合成视频播放器（含 `<video>` 标签、controls、下载按钮、归档按钮）
    - `renderRunAssetPreviewGrid`：支持 `kind: 'video'`，可预览单个镜头片段
    - `DreamweaverRunAssetPreviewGrid` 组件：统一的资产预览网格，支持图片和视频
  - 当前实现已满足基本视频预览需求，无需额外集成播放器组件

### F-05 ✅ 项目列表页运行状态概览（已评估）

- **完成日期**：2026-05-06
- **评估结论**：
  - 项目列表页 `DreamWeaverPage.tsx` 已具备运行状态概览：
    - 加载每个项目的最新运行状态（`listDreamweaverRuns(projectId, 1)`）
    - 项目卡片上显示运行状态 Chip（生成中/等待审核/已完成/失败/超时/未知）
    - 运行中的任务显示进度百分比
    - `classifyRunStatus()` 函数将后端状态映射为前端标签
  - 当前实现已满足需求，无需额外修改

---

## T-01：Dreamweaver 模块缺少后端单元测试

### 问题

Dreamweaver 后端模块（`_helpers.py` 及其拆分子模块、`autoqc_pkg` 等）缺少单元测试覆盖，重构和优化过程中无法自动验证行为一致性。

### 已完成内容

1. **后端 helper 模块测试**：
   - `test_dreamweaver_task_trace.py` — 任务追踪函数测试
   - `test_dreamweaver_library_prompt.py` — 素材库提示词构建函数测试
   - `test_dreamweaver_request_build.py` — 请求构建函数测试
   - `test_dreamweaver_env.py` — 环境变量辅助函数测试
   - `test_dreamweaver_library_spec.py` — 素材库规格构建函数测试

2. **autoqc 模块测试**：
   - `test_dreamweaver_video_generation.py` — 视频生成逻辑测试
   - `test_dreamweaver_vision_review.py` — 视觉审核逻辑测试
   - `test_dreamweaver_video_edit_rework.py` — 视频编辑返工逻辑测试
   - `test_dreamweaver_config_lock.py` — 配置锁定逻辑测试
   - `test_dreamweaver_points_precheck_routes.py` — 积分预检路由测试
   - `test_dreamweaver_safety_audit_override.py` — 安全审计覆写测试
   - `test_dreamweaver_subject_bridge_routes.py` — 主体桥接路由测试

3. **autoqc_pkg 跨模块引用修复**：
   - 修复了 `_run.py`、`_scoring.py`、`_video_clip_checks.py`、`_semantic_checks.py`、`_state_checks.py`、`_state_continuity.py`、`_semantic_match.py`、`_routing.py`、`_video_edit.py`、`_dataclasses.py` 中的缺失导入
   - 在 `_utils.py` 中补充了 `_semantic_frames_list` 和 `_normalize_state_text` 函数
   - 在 `_run.py` 中补充了 `DEFAULT_REQUIRE_I2V` 常量
   - 在 `_video_edit.py` 中补充了 `VIDEO_EDIT_FEATURES` 常量
   - 在 `_dataclasses.py` 中补充了 `AutoQCFailure` 的 `@dataclass` 装饰器

### 验收标准

- ✅ 130 个后端测试全部通过
- ✅ autoqc_pkg 模块导入链完整无断裂
- ✅ 所有缺失的函数、常量、装饰器已补充

---

## T-02：前端 hooks 缺少行为测试

### 问题

前端 Dreamweaver hooks（`useDreamweaverRunReducer`、`useDreamweaverPromptEdit` 等）缺少测试覆盖，重构时无法自动验证行为一致性。

### 已完成内容

1. **Reducer 行为测试**（`useDreamweaverRunReducer.test.ts`，35 个用例）：
   - 初始状态默认值验证
   - `START_RUN`：设置运行状态、清空旧数据
   - `SET_TASK_STATUS`：更新状态和队列名
   - `SET_TASK_PROGRESS`：更新进度
   - `COMPLETE_RUN` / `FAIL_RUN`：结束运行
   - `RESET_RUN`：恢复初始状态但保留锁定配置
   - `SET_WAITING_APPROVAL`：等待审核暂停/恢复运行
   - 流式事件：`STREAM_START` / `STREAM_DELTA` / `STREAM_END`、多流独立管理
   - `UPDATE_LIBRARY_PLAN` / `UPDATE_ASSET_PLAN`：添加、合并、保留 done 状态
   - `ASSET_READY`：标记完成、添加未知资产
   - `SET_LOCKED_CONFIG`：设置和清除配置
   - 事件同步：游标、同步状态、错误
   - 完整运行生命周期：正常完成、失败、重置后重新运行

2. **纯函数测试**（`useDreamweaverPromptEdit.test.ts`，14 个用例）：
   - `getShotFramePrompt`：提取 prompt、回退到 suggested_prompt、空值处理
   - `getShotVideoPromptOverride`：提取视频提示词覆盖、空值处理
   - `getShotId`：提取 shot_id
   - `getShotVideoPromptGenerated`：提取生成的视频提示词

3. **已有测试**（`useDreamweaverRunHistory.test.ts`，8 个用例）：
   - 运行记录构造、状态过滤、API 参数构建

### 验收标准

- ✅ 57 个前端测试全部通过
- ✅ Reducer 所有 action 类型均有覆盖
- ✅ 纯函数边界情况（null、undefined、数组）均有测试

---

## 第二轮优化（S-04 ~ S-13, D-04 ~ D-05）

> **目标**：将 DreamWeaverRunPage 从 3115 行降至 1500 行以下，同时完成后端大文件拆分和 runPageHelpers.ts 拆分。

### S-01 遗留问题

S-01 已完成以下 hook 提取（共 21 个）：
- `useDreamweaverRunHistory` — 运行历史
- `useDreamweaverPromptEdit` — 提示词编辑
- `useDreamweaverProviderRef` — Provider Ref（共享）
- `useDreamweaverRunConfig` — 运行配置
- `useDreamweaverRunPersistence` — 运行持久化
- `useDreamweaverMergedVideo` — 合成视频
- `useDreamweaverBulkDelete` — 批量删除
- `useDreamweaverDeleteRun` — 删除运行
- `useDreamweaverRunTaskState` — 运行任务状态（S-04）
- `useDreamweaverScriptApproval` — 脚本审核（S-05）
- `useDreamweaverAssetPreviews` — 素材库预览（S-06）
- `useDreamweaverRunAssetPreviews` — 运行资产预览（S-06）
- `useDreamweaverRegenDialog` — 重生成对话框（S-07）
- `useDreamweaverDiagnosticDialog` — 诊断对话框
- `useDreamweaverPromptEditDialog` — 提示词编辑对话框
- `useDreamweaverLockedConfig` — 锁定配置
- `useDreamweaverSnapshotDerived` — 快照派生数据
- `useDreamweaverRunState` — 运行状态
- `useDreamweaverDiagnostics` — 诊断数据
- `useDreamweaverRunReducer` — 运行 Reducer
- `useDreamweaverBatchRegen` — 批量重生成

主文件仍有 **34 个 useState、64 个 render 函数、3115 行**，验收标准（1500 行以下）尚未达成。

---

## S-04 ✅：RunPage 运行任务状态组提取（已完成）

`useDreamweaverRunTaskState.ts`（155行）已提取完成，RunPage L37 导入使用。

---

## S-05 ✅：RunPage 脚本审核状态组提取（已完成）

`useDreamweaverScriptApproval.ts`（133行）已提取完成，RunPage L38 导入使用。

---

## S-06 ✅：RunPage 素材库预览状态组提取（已完成）

`useDreamweaverAssetPreviews.ts`（64行）和 `useDreamweaverRunAssetPreviews.ts`（120行）已提取完成，RunPage L39/L46 导入使用。

---

## S-07 ✅：RunPage 重生成状态组整合（已完成）

`useDreamweaverRegenDialog.ts`（346行）已提取完成，RunPage L49 导入使用。

---

## S-08：RunPage 快照状态组提取

### 问题

3 个与运行快照相关的 useState：

```typescript
const [runSnapshot, setRunSnapshot] = useState<DreamweaverRunSnapshot | null>(null)
const [runSnapshotLoading, setRunSnapshotLoading] = useState(false)
const [runSnapshotError, setRunSnapshotError] = useState<string | null>(null)
```

### 方案

提取为 `useDreamweaverRunSnapshot` hook，封装：
- 快照加载、缓存、错误处理
- `loadRunSnapshot(runId)` / `resetSnapshot()` 方法

### 涉及文件

- `frontend/src/hooks/useDreamweaverRunSnapshot.ts`（新建）
- `frontend/src/pages/DreamWeaverRunPage.tsx`（修改）

### 验收标准

- RunPage 中上述 3 个 useState 替换为 hook 返回值
- 快照加载和展示功能不变
- TypeScript 编译无错误

---

## S-09：RunPage 事件同步状态组提取

### 问题

4 个与 WebSocket 事件同步相关的 useState：

```typescript
const [eventCursor, setEventCursor] = useState(0)
const [eventSyncing, setEventSyncing] = useState(false)
const [eventSyncError, setEventSyncError] = useState<string | null>(null)
const [wsError, setWsError] = useState<string | null>(null)
```

### 方案

提取为 `useDreamweaverEventSync` hook，封装：
- 事件游标、同步状态、错误状态
- `syncEvents(runId, cursor)` 方法
- `resetEventState()` 方法

### 涉及文件

- `frontend/src/hooks/useDreamweaverEventSync.ts`（新建）
- `frontend/src/pages/DreamWeaverRunPage.tsx`（修改）

### 验收标准

- RunPage 中上述 4 个 useState 替换为 hook 返回值
- WebSocket 事件同步功能不变
- TypeScript 编译无错误

---

## S-10 ✅：RunPage renderMergedVideoPanel 提取（已完成）

`MergedVideoPanel.tsx`（87行）已提取完成，RunPage L306 导入使用。`renderMergedVideoPanel` 已不存在于主文件中。

---

## S-11 ✅：RunPage renderDiagnosticFrame 提取（已完成）

`renderDiagnosticFrame` 已从 1049 行精简为 ~10 行辅助渲染函数。诊断面板逻辑已拆分到 `diagnosticSections.tsx`（679行）和 `diagnosticDialog.tsx`（267行）。

---

## S-12：RunPage 其余大 render 函数提取

### 问题

RunPage 中仍有 64 个 `render*` 函数。其中超过 50 行的 render 函数应提取为独立组件，减少主文件体积。

### 当前主要 render 函数（按行数排序）

| render 函数 | 估计行数 | 提取方向 |
|------------|---------|---------|
| renderWorkbenchCard | ~50 | 保留（顶层组合） |
| renderConfigDialog | ~100 | 已有 `configDialog.tsx`，确认替换 |
| renderPendingRunningView | ~40 | 已有 `pendingViews.tsx`，确认替换 |
| renderResultView | ~25 | 已有 `resultView.tsx`，确认替换 |
| renderHistoryDialog | ~25 | 已有 `historyDialog.tsx`，确认替换 |
| renderRegenerateDialog | ~30 | 已有 hook，确认替换 |
| renderPromptEditDialog | ~30 | 已有 hook，确认替换 |
| renderDiagnosticDialog | ~40 | 已有 `diagnosticDialog.tsx`，确认替换 |

### 验收标准

- 所有超过 50 行的 render 函数提取为独立组件或替换为已有组件
- RunPage 仅保留组件组合层
- 所有功能不变
- TypeScript 编译无错误

---

## D-04：后端 services/library.py 1049 行拆分（✅ 已完成）

### 问题

`backend/app/services/dreamweaver/library.py` 是后端最大的服务文件（1049 行），包含素材库的角色构建、规格构建、提示词生成、资产加载、审核等所有逻辑。

### 实施方案

按职责拆分为：
- `library_constants.py`（58 行）— 共享常量、角色前缀、工具函数
- `library_spec.py`（362 行）— 规格构建、角色实体、脚本实体处理
- `library_assets.py`（526 行）— 资产加载、审核、路径处理
- `library.py`（147 行）— 入口文件，re-export + build_library_prompt + enrich_payload_with_library

### 验收结果

- library.py 行数从 1049 降至 147 行
- 所有素材库 API 功能不变
- 后端测试全部通过（233 passed）

---

## D-05：autoqc_pkg/_run.py 822 行拆分（✅ 已完成）

### 问题

`pipeline/autoqc_pkg/_run.py` 是 autoqc 的核心运行逻辑（822 行），包含配置解析、VLM 初始化、基础评分、语义检查、状态连续性检查、相机连续性检查、I2V 要求检查、视频片段质量检查、报告汇总等所有阶段。

### 实施方案

按职责拆分为：
- `_qc_config.py`（348 行）— QCConfig dataclass + parse_qc_config 配置解析函数
- `_run_helpers.py`（454 行）— VLM 初始化、基础评分、状态检查、相机连续性、I2V 检查、视频片段检查
- `_run.py`（208 行）— 入口编排，调用配置解析和各阶段辅助函数

### 验收结果

- _run.py 行数从 822 降至 208 行
- autoqc 所有功能不变
- 后端测试全部通过（233 passed）

---

## 第二轮优化实施顺序

按依赖关系和风险等级排序：

1. **S-08** — 快照状态提取（3 个 useState）
2. **S-09** — 事件同步状态提取（4 个 useState）
3. **S-13** — runPageHelpers.ts 拆分（2904 行，最大收益）
4. **S-12** — 其余大 render 函数提取
5. **D-04** — 后端 library.py 拆分
6. **D-05** — autoqc_pkg/_run.py 拆分

预期最终效果：
- DreamWeaverRunPage：3115 → ~1500 行
- library.py：929 → ~100 行
- _run.py：750 → ~200 行
- runPageHelpers.ts：2904 → ~200 行（入口）+ 多个子模块

---

## S-13：runPageHelpers.ts 2904 行巨型 helper 拆分

### 问题

`frontend/src/pages/dreamweaver-run/runPageHelpers.ts` 有 2904 行，是 `dreamweaver-run/` 目录下最大的文件。它包含了运行页面的各种辅助函数、类型定义、数据转换逻辑，职责不清晰。

### 涉及文件

- [runPageHelpers.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/dreamweaver-run/runPageHelpers.ts)（2904 行）

### 方案

按职责拆分为：
- `runPageTypes.ts` — 类型定义和接口
- `runPageDataTransforms.ts` — 数据转换和格式化函数
- `runPageStateHelpers.ts` — 状态计算和辅助逻辑
- `runPageRenderHelpers.ts` — 渲染辅助函数
- `runPageHelpers.ts` — 保留入口，从子模块 re-export

### 验收标准

- runPageHelpers.ts 行数降至 200 行以下（仅保留 re-export）
- 每个子模块 < 800 行
- 所有功能不变
- TypeScript 编译无错误
