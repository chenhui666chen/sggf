# 耳畔星河 — 下一阶段优化指导文档

> **版本**：3.0
> **创建日期**：2026-05-05
> **最后更新**：2026-05-10
> **适用范围**：`backend/app/api/v1/audiobook_api/`、`backend/app/services/audiobook/`、`frontend/src/pages/audiobook/`、`frontend/src/components/audiobook/`、`frontend/src/services/api.ts`
> **上一阶段归档**：`.agent/archive/optimization-guide-ear-galaxy-v2.3-20260505.md`

---

## 文档定位

本文件用于指导“耳畔星河”有声书模块的下一阶段优化。上一阶段 `OPT-00 ~ OPT-31` 已收口，完整台账已归档，不再在当前文档中重复维护历史明细。

当前文档只保留三类内容：

1. 下一阶段值得评估或推进的优化方向。
2. 明确暂不推进的边界条件。
3. 每次新增优化项前必须满足的核验与测试要求。

---

## 当前基线

### 已完成基线

- 后端权限、Repository、软删除过滤、预览端点重构、BrowserPlayer N+1、TTS preview retry config、CosyVoice 路由别名、SHA256 前缀短哈希等已完成。
- `soft_delete` 快照构建已收敛到共享序列化器。
- 有声书积分冻结异常处理已收敛到 `safe_record_audiobook_billing_freeze`。
- `useAudiobookTaskPolling` 已拆分为：
  - `useAudiobookTaskListPolling`
  - `useAudiobookTaskStreamPolling`
  - 薄 wrapper `useAudiobookTaskPolling`
- BrowserPlayer localStorage 已具备 7 天 TTL 清理。
- 无前端消费者的 `narration-styles/{style_id}`、`voice-types/{voice_type}` 详情端点已移除。

### 仍保持搁置的旧项

| 编号 | 结论 | 重新评估条件 |
|------|------|--------------|
| `OPT-20` deprecated preview 端点删除 | 已删除 | 测试阶段确认无真实用户；旧 `/previews/*` 路由已不再注册 |
| `OPT-22` 独立 CosyVoice 克隆列表 API 方法 | 暂不新增 | `getTtsVoices()` 完整目录刷新成为真实性能瓶颈 |
| `OPT-25` 收录按钮按章节独立禁用 | 暂不放开 | 后端确认多章节并发收录安全，前端改为按章节集合状态 |
| `OPT-27` danger/warning 色彩 token 统一 | 暂不混入功能优化 | 单独开展 UI token 清理，并配合视觉回归检查 |

---

## 下一阶段候选优化池

| 编号 | 优先级 | 方向 | 状态 | 风险 | 推荐处理方式 |
|------|--------|------|------|------|--------------|
| V3-01 | P1 | `useAudiobookTaskStreamPolling` 行为测试补强 | 已完成 | 低 | 已提取纯函数并补 Vitest |
| V3-02 | P1 | 后端广义异常捕获边界审计 | 已完成 | 低 | 首轮优先入口已审计完成 |
| V3-03 | P2 | 任务观测性与 trace 统一 | 已完成 | 中高 | 已覆盖导出、生成入口、后台阶段、失败诊断、积分预检与积分冻结 trace |
| V3-04 | P2 | deprecated preview 端点删除准备 | 已完成 | 中 | 测试阶段确认无真实用户后已删除旧 `/previews/*` 路由 |
| V3-05 | P2 | 多章节收录并发安全评估 | 已完成 | 中 | 已改为按章节集合状态禁用 |
| V3-06 | P3 | UI 颜色 token 语义清理 | 已完成 | 低中 | 已新增语义角色层并迁移关键消费者 |
| V3-07 | P1 | 内置音效库文件名与实际素材不匹配 | 首批素材正式导入完成 | 中 | 已建立 Wikimedia Commons CC0/Public Domain 候选清单；首批 10 个已下载素材已通过 manifest 正式导入，当前因未配置云存储为 local_cache |
| V3-08 | P1 | 前端 Checkbox 与 Density Select 状态不一致 | 已完成 | 中 | 已联动更新 density 值 |
| V3-09 | P2 | placeholder.mp3 音效缺少用户可见反馈 | 已完成 | 中 | 已在 effect_timeline/checkpoint/审核报告中暴露未解析音效 warning |
| V3-10 | P2 | 音效/配乐时长估算过于粗糙 | 已完成 | 中 | 已统一为 4.5 字/秒估算 helper |
| V3-11 | P2 | 配乐场景筛选遗漏中等情绪片段 | 已完成 | 低中 | 已扩展情绪关键词与 mood 映射 |
| V3-12 | P2 | intelligent_balance 默认关闭导致 BGM 音量僵化 | 测试补强完成 | 低中 | 保留默认关闭；默认开启需单独做 A/B 听感评估 |
| V3-13 | P3 | 前端 AudioFxConfigPanel 缺少配乐提示信息 | 已完成 | 低 | 已补充配乐功能说明文案 |
| V3-14 | P3 | 音效库外部索引加载未验证文件存在性 | 已完成 | 低 | 已增加加载期文件存在性校验与日志 |
| V3-15 | P1 | `music_index.json` 使用绝对路径导致不可移植 | 已完成 | 高 | 写入新索引为相对路径；混音/试听读取按 base_dir 解析 |
| V3-16 | P1 | MusicComposer 缺少外部索引加载与文件校验 | 已完成 | 高 | 新增 `_load_external_music_library` 与加载期校验 |
| V3-17 | P2 | 音乐池缓存不利用已有索引 | 已完成 | 中 | 预加载索引池；已有变体充足时跳过生成 |
| V3-18 | P3 | `_match_music` 只返回首个匹配缺乏变化 | 已完成 | 低 | 基于包含项目/章节/场景的 seed 稳定选取 |
| V3-19 | P1 | 生成素材入库无质量门控，低质素材无法区分与删除 | 已完成 | 高 | 注册时自动评估质量元数据；新增清理方法 |
| V3-20 | P1 | 段落转化 JSON 解析失败后整批 fallback 导致质量降级 | 已完成 | 高 | 解析失败后拆小重试；补诊断日志并降低批次复杂度 |
| V3-21 | P1 | 角色对白被旁白吞并，旁白演绎情绪偏平 | 已完成 | 高 | 已增强 prompt、明确引语纠偏与旁白情绪补强 |
| V3-22 | P1 | 公开音效资源合规导入与索引标准化 | 第六阶段完成 | 高 | 已落地远端授权防线、本地授权导入、候选发现、credits 导出、项目导出附带与实际使用音效 ID 收窄；Freesound OAuth2 后续单独评估 |
| V3-23 | P1 | 分段重生前端入口隐藏过深，重生后无刷新 | 已完成 | 高 | 审查模式外始终显示重生按钮；重生成功后自动刷新编辑器音频数据 |
| V3-24 | P1 | 音效库/音乐库无前端浏览与管理入口 | 已完成 | 高 | 已新增本地库浏览 API 与前端界面；普通用户仅可浏览/试听/使用，管理入口仅管理员可见；公开平台搜索/下载入口已按合规边界禁用 |
| V3-25 | P2 | 片段音效/配乐输入方式原始，无法从库中选择 | 已完成 | 中 | 改为选择器+搜索；对接音效库/音乐库索引 |
| V3-26 | P2 | 音效下载器/素材清理无前端触发入口 | 已完成 | 中 | 候选审核、manifest 导入、素材清理与单素材删除均收紧为管理员能力；删除保留 dry-run/confirm 和安全路径/OSS 前缀边界 |
| V3-27 | P3 | AudioFxConfigPanel 缺少 intelligent_balance 等高级选项 | 已完成 | 低 | 增加高级选项折叠区 |
| V3-28 | P1 | 生成结果评分无前端入口（用户评分+模型统计查看） | 已完成 | 高 | 仅暴露用户评分提交和模型统计查看；QC/回流为内部自动化无需前端 |
| V3-29 | P2 | 剧本审核报告前端未展示 | 已完成 | 中 | 仅暴露审核报告查看和反馈提交；adjust/regenerate 为占位接口暂不接入 |
| V3-30 | P2 | AI 一致性检查前端未接入 | 已完成 | 中 | 编辑器增加一致性检查按钮与结果展示 |
| V3-31 | P2 | CosyVoice 复刻音色列表查询 API 前端未封装 | 已完成 | 中 | api.ts 补充 listCosyVoiceClones 方法；CustomVoiceList 增加详细视图 |
| V3-32 | P2 | 有声书项目统计字段前端未展示 | 已完成 | 中 | 项目详情页增加完成率/失败数/总大小等指标；章节列表展示耗时和成本 |
| V3-33 | P3 | 智能调度系统无前端入口 | 已完成 | 低 | 新增 SmartDispatchInput 组件；api.ts 封装 smartDispatch/recommendModels |
| V3-34 | — | 内容进化引擎无前端入口 | 无需前端 | — | 纯后端内部优化引擎，无用户操作需求 |
| V3-35 | — | 伏笔追踪/知识图谱/地点层级等无前端入口 | 无需前端 | — | 纯后端分析服务，无用户操作需求；结果通过工作流间接消费 |

---

## V3-01：`useAudiobookTaskStreamPolling` 行为测试补强

### 问题

`OPT-24` 已完成结构拆分，但当前主要依赖 source guard 和类型检查证明拆分边界。SSE 事件解析、progress patch、断线 fallback、终态处理等行为仍缺少更细粒度的可执行测试。

### 建议方向

先从 `useAudiobookTaskStreamPolling.ts` 中提取不依赖 React 生命周期的纯函数，再补 Vitest：

- SSE buffer 解析：
  - 多个 `data:` block
  - 半包残留
  - 坏 JSON 忽略
- progress patch 归一化：
  - `pending` 自动转 `running`
  - progress 单调递增
  - stage 为空时保留旧值
- stream fallback 决策：
  - fetch 不可用
  - response 非 2xx
  - stream 正常关闭后切换 fallback polling

### 验收标准

- 新增纯函数有 focused Vitest。
- `npm test -- src/pages/audiobook/__tests__` 通过。
- `npm run type-check` 通过。
- 不改变 `AudiobookPage.tsx` 对 `useAudiobookTaskPolling` 的调用方式。

### 完成记录（2026-05-05）

- 新增 `frontend/src/pages/audiobook/taskStreamPollingUtils.ts`，提取 SSE buffer 解析、progress patch 归一化、stream fallback 判定。
- `useAudiobookTaskStreamPolling.ts` 改为调用纯函数；`AudiobookPage.tsx` 和 `useAudiobookTaskPolling` 调用方式未变。
- 新增 `frontend/src/pages/audiobook/__tests__/taskStreamPollingUtils.test.ts`，覆盖多 block、半包残留、坏 JSON、progress 单调递增、空 stage 保留旧值、fallback 判定。
- 更新 `taskPollingSource.test.ts`，source guard 锁定新的 fallback helper 边界。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__"`：32 passed，152 passed。
  - `npm run type-check`：通过。
- 未覆盖风险：尚未补基于真实 `fetch`/`ReadableStream` 生命周期的 hook 集成测试；当前以纯函数行为测试和 source guard 覆盖拆分边界。

---

## V3-02：后端广义异常捕获边界审计

### 问题

`backend/app/services/audiobook/**` 和 `backend/app/api/v1/audiobook_api/**` 中存在大量 `except Exception`。部分属于合理兜底，例如后台任务、第三方 API、音频文件清理；但也可能掩盖应暴露的业务错误。

### 执行原则

- 不做全局搜索替换。
- 每次只审计一个模块或一个调用链。
- 先判断异常是否属于：
  - 可恢复的外部依赖失败
  - 清理失败
  - 后台任务容错
  - 应该向调用方暴露的业务失败
- 只有在能明确证明行为更正确时才修改。

### 优先审计入口

1. `routes_script.py`
2. `routes_segment_regen.py`
3. `background_jobs_audio.py`
4. `background_jobs_full.py`
5. `background_jobs_scripts.py`
6. `project_exporter.py`

### 验收标准

- 每个模块输出审计结论：保留、收窄、补日志、补测试或后续观察。
- 若修改异常处理，必须补对应失败场景测试。
- 后台任务不得因非关键清理失败影响主流程。

### 完成记录（2026-05-05）

- 已完成 `routes_script.py` 审计与收窄：
  - `json.loads` 仅捕获 `json.JSONDecodeError`
  - `json.dumps` 仅捕获 `TypeError` / `ValueError`
  - 未知异常不再被转换成业务可预期的 HTTP 错误
- 已完成 `routes_segment_regen.py` 审计与收窄：
  - `_load_chapter_segments` 和片段审查 JSON 保持 `JSONDecodeError` / `TypeError` 捕获。
  - 片段重生成保存阶段仅将 `OSError` / `TempSegmentStoreError` 转换成 HTTP 500。
  - `json.dumps`、`db.commit` 等未知错误不再被误包装为“保存音频失败”。
- 已完成 `background_jobs_audio.py` 审计与收窄：
  - 章节剧本 JSON 解析仅捕获 `JSONDecodeError` / `TypeError`。
  - 项目音效、角色音应用、章节级失败诊断、任务级失败释放积分保留 broad catch，属于后台任务容错边界。
- 已完成 `background_jobs_full.py` 审计：
  - 未发现需要收窄的 JSON 解析边界。
  - 配置加载、章节级失败诊断、任务级失败释放积分保留 broad catch。
- 已完成 `background_jobs_scripts.py` 审计与收窄：
  - 角色标签 JSON 与旧 voice mapping JSON 仅捕获 `JSONDecodeError` / `TypeError`。
  - `voice_manager.load_from_db()`、项目级配置应用、章节级失败记录保留 broad catch，属于非关键配置和后台任务容错边界。
- 已完成 `project_exporter.py` 审计与收窄：
  - `_parse_script_segments` 仅忽略 `JSONDecodeError` / `TypeError`。
  - ffprobe/pydub 探测、导出缓存读取、可选 Audacity 分轨、文件 stat 降级保留 broad catch，属于导出链路可降级边界。
- 新增或更新测试：
  - `backend/tests/test_audiobook_script_routes.py`
  - `backend/tests/test_audiobook_segment_regen_routes.py`
  - `backend/tests/test_audiobook_background_jobs_audio.py`
  - `backend/tests/test_audiobook_background_jobs_scripts.py`
  - `backend/tests/test_audiobook_project_exporter.py`
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_script_routes.py" "backend/tests/test_audiobook_segment_regen_routes.py" "backend/tests/test_audiobook_background_jobs_audio.py" "backend/tests/test_audiobook_background_jobs_scripts.py" "backend/tests/test_audiobook_project_exporter.py" "backend/tests/test_audiobook_route_import_hygiene.py" -q`：42 passed。
- 未覆盖风险：本轮是优先入口首轮审计，不代表全仓库所有 `except Exception` 均已消除；剩余 broad catch 已按当前调用语义记录为保留，后续只有在有失败场景或可复现风险时再单点推进。

---

## V3-03：任务观测性与 trace 统一

### 问题

有声书生成链路涉及排队、断点、积分预检、积分冻结、SSE、轮询、章节音频产物、导出任务。当前各处日志和 detail_json 已有基础信息，但缺少统一 trace 口径。

### 建议方向

先写设计方案，不直接改实现：

- 统一任务 trace id 或复用 celery task id。
- 明确每个阶段需要记录的字段：
  - `audiobook_project_id`
  - `chapter_id`
  - `task_type`
  - `run_id`
  - `celery_task_id`
  - `tts_model`
  - `stage`
  - `progress`
  - `cost_precheck_id`
  - `billing_freeze_event_id`
- 定义日志与 `detail_json` 的边界：
  - 日志用于排障
  - `detail_json` 用于前端展示与任务状态恢复

### 验收标准

- 先产出方案文档。
- 明确兼容策略，不破坏现有前端任务状态展示。
- 选一个低风险任务类型试点。

### 方案记录（2026-05-05）

- 已新增方案文档：`docs/AUDIOBOOK_TASK_TRACE_OBSERVABILITY_PLAN_20260505.md`。
- 方案结论：第一阶段复用现有 `celery_task_id` 作为 `trace_id`，不新增数据库字段，不引入外部 tracing 系统，不改变 SSE data 外层结构。
- 已明确日志、`detail_json`、`checkpoint_json` 的职责边界：
  - 日志用于排障，可包含高基数字段、错误类型、耗时、provider、积分事件等诊断信息。
  - `detail_json` 用于前端展示、任务状态恢复和轻量诊断，只追加稳定兼容字段。
  - `checkpoint_json` 用于章节级断点恢复和运行态，不承担通用展示职责。
- 推荐低风险试点：先从项目导出任务 `export_m4b` / `export_audacity` 与 `build_project_export_task_detail()` 开始。
- 方案阶段未修改业务实现。

### 试点记录（2026-05-05）

- 新增 `backend/app/services/audiobook/task_trace.py`，集中构造并合并有声书任务 trace context。
- `build_project_export_task_detail()` 增加可选 `trace_context` 参数，只追加兼容字段，不覆盖已有 detail 字段。
- `export_m4b` / `export_audacity` 的 running、completed、failed detail 已传入：
  - `trace_id`
  - `celery_task_id`
  - `task_db_id`
  - `task_type`
  - `audiobook_project_id`
  - `stage`
  - `status`
  - `progress`
- 新增 `backend/tests/test_audiobook_task_trace.py`，并更新 `backend/tests/test_audiobook_project_exporter.py`。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q`：20 passed。
- 未覆盖风险：尚未扩展到 `run_script_only`、`run_audio_from_scripts`、`run_full`、积分预检/冻结、失败诊断与前端展示。

### 脚本生成初始 trace 记录（2026-05-05）

- `backend/app/tasks/audiobook_tasks.py` 新增 `_build_initial_generation_task_detail()`。
- `run_script_generation_task()` 初始 `script_adaptation` detail 已追加兼容 trace 字段：
  - `trace_id`
  - `celery_task_id`
  - `task_db_id`
  - `task_type`
  - `audiobook_project_id`
  - `chapter_ids`
  - `chapter_total`
  - `stage`
  - `status`
  - `progress`
  - `tts_model`
- 新增 `backend/tests/test_audiobook_task_trace_contexts.py`，覆盖 `script_only` 初始 detail 契约。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q`：21 passed。

### 音频生成初始 trace 记录（2026-05-05）

- `run_audio_from_scripts_task()` 初始 `tts_synthesis` detail 已追加兼容 trace 字段：
  - `trace_id`
  - `celery_task_id`
  - `task_db_id`
  - `task_type`
  - `audiobook_project_id`
  - `chapter_ids`
  - `chapter_total`
  - `stage`
  - `status`
  - `progress`
  - `tts_model`
- 更新 `backend/tests/test_audiobook_task_trace_contexts.py`，覆盖 `audio_from_scripts` 初始 detail 契约与任务源码接入。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q`：23 passed。

### 完整生成初始 trace 记录（2026-05-05）

- `run_full_audiobook_task()` 初始 `initializing` detail 已追加兼容 trace 字段：
  - `trace_id`
  - `celery_task_id`
  - `task_db_id`
  - `task_type`
  - `audiobook_project_id`
  - `chapter_ids`
  - `chapter_total`
  - `stage`
  - `status`
  - `progress`
  - `tts_model`
- 更新 `backend/tests/test_audiobook_task_trace_contexts.py`，覆盖 `full` 初始 detail 契约与任务源码接入。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q`：25 passed。
- 未覆盖风险：本轮统一了 `run_full`、`run_script_only`、`run_audio_from_scripts` 的初始任务 detail；失败诊断、积分链路和生成后台内部阶段在后续小步接入。

### 失败诊断 trace 记录（2026-05-05）

- `backend/app/services/audiobook/failure_diagnostics.py` 新增失败诊断 `trace_id` 字段。
- 解析优先级：
  - 显式 `task_id`
  - `result.trace_id`
  - `result.celery_task_id`
  - `result.task_id`
  - `result.engine_task_id`
  - `resume_checkpoint.trace_id`
  - `resume_checkpoint.celery_task_id`
  - `resume_checkpoint.task_id`
  - `resume_checkpoint.engine_task_id`
- 保留既有 `engine_task_id` 字段语义，不重命名、不删除。
- 更新 `backend/tests/test_audiobook_failure_diagnostics.py`，覆盖显式 trace、result fallback、checkpoint fallback，以及 checkpoint patch 中的 `failure_diagnostic.trace_id`。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_failure_diagnostics.py" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_task_trace_contexts.py" -q`：13 passed。
- 未覆盖风险：生成后台内部阶段 detail 和积分预检链路仍未接入 trace。

### 积分冻结 trace 记录（2026-05-05）

- `safe_record_audiobook_billing_freeze()` 新增可选 `trace_context` 参数，未传入时保持原始调用参数形状。
- `record_audiobook_billing_freeze()` 新增可选 `extra_payload` 参数，只允许以下 trace 诊断字段进入冻结事件日志 payload：
  - `trace_id`
  - `celery_task_id`
  - `task_db_id`
  - `task_type`
  - `stage`
  - `status`
  - `progress`
  - `tts_model`
  - `cost_precheck_id`
  - `billing_freeze_event_id`
- 外部 payload 不允许覆盖 `amount_points`、`amount_yuan`、`audiobook_project_id`、`chapter_ids`、`pricing_status`、`operating_snapshot` 等账务字段。
- 三个排队入口在 `_enqueue_audiobook_task()` 后使用 `async_result.id` 构造 trace context，并写入积分冻结日志：
  - 创建有声书项目的非 `script_only` 任务。
  - 已有脚本生成音频任务。
  - 断点续跑的非 `script_only` 任务。
- 更新测试：
  - `backend/tests/test_audiobook_task_support_billing.py`
  - `backend/tests/test_user_center_billing_events.py`
  - `backend/tests/test_audiobook_task_trace_contexts.py`
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_task_support_billing.py" "backend/tests/test_user_center_billing_events.py::test_audiobook_freeze_event_records_expected_payload" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_route_import_hygiene.py" -q`：13 passed。
- 历史未覆盖风险：积分预检稳定 `cost_precheck_id` 已在 2026-05-06 解决；`billing_freeze_event_id` 需要事件落库后才可得，仍不做反写。

### 后台内部阶段 trace 记录（2026-05-05）

- `AudiobookJobTracker.update_stage()` 作为生成后台阶段的集中写入点，已在写入 `detail_json` 前合并 trace context。
- 新增私有 helper `_merge_task_trace_context()`：
  - 从 `AudiobookTask` 读取 `celery_task_id`、`task_db_id`、`task_type`、`audiobook_project_id`。
  - 从阶段参数读取 `stage`、`progress`。
  - 从 detail 或任务记录读取 `chapter_id`、`status`。
  - 使用 `merge_audiobook_trace_context()` 增量合并，不覆盖已有 detail 同名字段。
- 影响范围：
  - `AudiobookTask.detail_json` 新增兼容 trace 字段。
  - SSE `data.detail` 透传相同兼容字段，外层 `stage`、`progress`、`status`、`error_message` 不变。
  - `ChapterAudioRun.checkpoint_json.tracker_detail` 同步保留相同 trace 字段。
- 更新 `backend/tests/test_audiobook_job_tracker.py`，覆盖任务 detail、SSE detail、章节 tracker detail 三处一致性。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_job_tracker.py" "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_task_support_billing.py" "backend/tests/test_user_center_billing_events.py::test_audiobook_freeze_event_records_expected_payload" "backend/tests/test_audiobook_route_import_hygiene.py" -q`：16 passed。
- 历史未覆盖风险：积分预检稳定 trace id 已在 2026-05-06 解决；前端仍不新增 trace 展示。

### 积分预检 trace 记录（2026-05-06）

- `AudiobookTaskPointsPrecheckSnapshot` 新增稳定 `cost_precheck_id`，格式为 `audiobook-precheck-{sha256前16位}`。
- `cost_precheck_id` 基于有声书模块、用户、项目、有声书项目、章节集合、TTS 模型和预检结果关键成本字段生成；相同输入和成本结果下稳定，不依赖时间戳，不新增数据库字段。
- 结构化预检失败响应通过 `build_task_points_precheck_error_detail()` 自动包含 `cost_precheck_id`，便于前端错误上报与后端日志关联。
- 三个有声书排队/恢复入口在正式冻结积分时将 `cost_precheck_id` 合并进 trace context：
  - 创建有声书项目的非 `script_only` 任务。
  - 已有脚本生成音频任务。
  - 断点续跑的非 `script_only` 任务。
- `record_audiobook_billing_freeze()` 的白名单 payload 已允许 `cost_precheck_id`，并继续禁止外部 payload 覆盖账务关键字段。
- 验证通过：
  - `python -m pytest "backend/tests/test_points_task_precheck.py::test_audiobook_precheck_uses_selected_tts_model_price" "backend/tests/test_points_task_precheck.py::test_audiobook_precheck_cost_id_is_stable_for_same_inputs" "backend/tests/test_audiobook_task_trace_contexts.py::test_audiobook_freeze_routes_pass_trace_context" -q`：3 passed。
  - `python -m pytest "backend/tests/test_audiobook_points_precheck_routes.py::test_audiobook_create_project_blocks_with_structured_precheck_error" "backend/tests/test_user_center_billing_events.py::test_audiobook_freeze_event_records_expected_payload" -q`：2 passed。
  - `python -m pytest "backend/tests/test_points_task_precheck.py" "backend/tests/test_audiobook_points_precheck_routes.py" -q`：10 passed。
  - `python -m pytest "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_task_support_billing.py" -q`：11 passed。
  - `python -m pytest "backend/tests/test_user_center_billing_events.py::test_audiobook_freeze_event_records_expected_payload" "backend/tests/test_user_center_billing_events.py::test_audiobook_freeze_event_uses_tts_pricing_key_when_provided" -q`：2 passed。
- 未覆盖风险：前端仍不展示 trace 字段；当前定位为诊断/上报关联字段，不作为用户界面信息。

---

## V3-04：deprecated preview 端点删除准备

### 问题

`POST /previews/generate`、`GET /previews/{preview_id}` 曾作为 deprecated 兼容端点保留。它们与主链路 TTS preview 的运行时调用方式不同。

### 当前结论

已删除。用户确认当前仍处测试阶段、没有真实用户后，旧兼容端点不再需要继续等待外部兼容窗口。

### 删除前置条件（已满足）

1. 全仓库搜索无前端或后端消费者。
2. 用户确认当前无真实用户，旧端点不存在外部兼容窗口约束。
3. 更新锁定 deprecated 路由存在的测试，改为断言旧路由不注册且访问返回 404。
4. 保留迁移说明和验证命令。

### 验收标准

- 删除前必须有明确兼容窗口结论；测试阶段无真实用户时，可由用户确认后直接推进。
- 删除后路由表测试应证明旧路由不再注册。

### 核验记录（2026-05-05）

- 前端消费者核验：
  - `frontend/src/services/api.ts` 当前使用的是 `/tts/preview`、`/tts/preview-with-timestamps`、`/projects/{projectId}/chapters/{chapterId}/segments/preview`。
  - `frontend/src/pages/audiobook/useAudiobookCharacterVoicePreview.ts` 调用 `apiClient.previewTTS()`。
  - `frontend/src/pages/audiobook/useAudiobookSegmentPreview.ts` 调用 `apiClient.previewScriptSegmentAudio()`。
  - 未发现前端直接调用 `/api/v1/audiobook/previews/generate` 或 `/api/v1/audiobook/previews/{preview_id}`。
- 后端消费者核验：
  - 删除前 `backend/app/api/v1/audiobook_api/routes_misc.py` 仍注册 deprecated 端点。
  - 删除前 `backend/app/services/audiobook/preview_generator.py` 仅由 deprecated `generate_preview()` 调用，返回的 `audio_url` 指向 `/api/v1/audiobook/previews/{preview_id}`。
  - 未发现业务主链路调用 `default_preview_generator.generate_preview()`。
- 测试锁定情况：
  - `backend/tests/test_audiobook_misc_routes.py` 仍覆盖旧 preview 文件读取、非法 preview id、缺失音频 404、OpenAPI deprecated 标记。
  - `backend/tests/test_sse_retry_preview.py` 仍覆盖旧 `PreviewGenerator` 自身行为。
- 当前结论：
  - 仓库内消费者已基本迁移到新 preview 端点。
  - 删除属于 API 行为变更；在用户确认当前测试阶段无真实用户后已推进。
  - deprecated route 已删除，旧 `PreviewGenerator` 已改为内部不可路由工具，不再返回旧路由 URL。

### 完成记录（2026-05-06）

- 用户确认当前仍处测试阶段、没有真实用户，因此旧 preview 兼容窗口不再阻塞删除。
- `backend/app/api/v1/audiobook_api/routes_misc.py` 已移除：
  - `POST /api/v1/audiobook/previews/generate`
  - `GET /api/v1/audiobook/previews/{preview_id}`
- `backend/tests/test_audiobook_misc_routes.py` 已改为断言：
  - 旧 generate 路由访问返回 404。
  - 旧文件读取路由访问返回 404。
  - OpenAPI 不再暴露旧 preview paths。
  - SSE `/tasks/{task_id}/stream` 仍不是 deprecated。
- `PreviewGenerator` 文件暂不删除，避免源码文件删除；其 `audio_url` 已改为空字符串，避免内部工具继续返回不可访问的旧路由 URL。
- `backend/tests/test_sse_retry_preview.py` 已补充测试，锁定内部 `PreviewGenerator` 不再输出 `/api/v1/audiobook/previews/{preview_id}`。
- `rg` 核验结果：应用代码中已无 `/previews/generate`、`/previews/`、`audiobook/previews`、`generatePreview`、`configureRetry` 旧消费者；仅测试断言和 `default_preview_generator` singleton 名称仍存在。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_misc_routes.py::test_legacy_preview_generate_route_is_removed" "backend/tests/test_audiobook_misc_routes.py::test_legacy_preview_file_route_is_removed" "backend/tests/test_audiobook_misc_routes.py::test_legacy_preview_routes_are_not_registered_but_sse_is_not_deprecated" -q`：3 passed。
  - `python -m pytest "backend/tests/test_sse_retry_preview.py::test_preview_generator_does_not_emit_removed_preview_route" -q`：1 passed。
  - `python -m pytest "backend/tests/test_audiobook_misc_routes.py" "backend/tests/test_sse_retry_preview.py" -q`：32 passed。
  - `python -m pytest "backend/tests/test_audiobook_route_import_hygiene.py" -q`：1 passed。
  - `python -m pytest "backend/tests/test_audiobook_tts_routes_observability.py" "backend/tests/test_segment_preview_service.py" "backend/tests/test_audiobook_segment_regen_routes.py" -q`：23 passed。
- 迁移口径：
  - TTS 快速试听继续使用 `/api/v1/audiobook/tts/preview` 或 `/api/v1/audiobook/tts/preview-with-timestamps`。
  - 剧本片段试听继续使用 `/api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/preview`。

---

## V3-05：多章节收录并发安全评估

### 问题

当前收录按钮全局禁用逻辑偏保守，但直接改为按章节独立禁用会引入新的并发行为。

### 建议方向

先做并发安全评估：

- 后端是否允许同一项目多个章节同时收录。
- 同一章节重复点击如何去重。
- 前端是否需要 `collectingChapterIds: Set<number>`。
- 收录结果回写是否会覆盖其他章节状态。
- 失败提示是否按章节独立显示。

### 验收标准

- 有明确状态模型后再改 UI。
- 至少补状态工具测试或 source guard。
- 不把“按钮可点”当成并发安全证明。

### 评估记录（2026-05-05）

- 当前前端状态：
  - `useAudiobookChapterAudioActions.ts` 使用单值 `collectingChapterId: number | null`。
  - `ChapterAudioResults.tsx` 通过 `collectDisabled={collectingChapterId !== null}` 禁用所有章节收录按钮。
  - `ChapterAudioResultItem.tsx` 只接收当前章节是否 `isCollecting` 与全局 `collectDisabled`。
- 前端收录链路：
  - 每次收录先下载章节音频 blob。
  - `saveExplicitLocalUserAsset()` 写入本地资产索引和 OPFS / external directory / IndexedDB fallback。
  - `apiClient.createUserAsset()` 创建或更新用户资产记录。
  - 章节资产 uuid 由 `buildAudiobookChapterAssetUuid(audiobookProject.id, chapterAudio.chapter_id)` 生成，不同章节天然不同。
- 后端安全性：
  - `UserAssetRecord` 有活跃唯一索引：`user_id + source_module + asset_kind + asset_uuid`，且仅约束未归档记录。
  - `create_user_asset()` 先查 active 记录，存在则 upsert。
  - 并发插入同一 asset uuid 时捕获 `IntegrityError`，回查并更新既有记录。
  - `backend/tests/test_user_assets_routes.py` 已覆盖 upsert 与 duplicate insert race。
- 并发模型结论：
  - 不同章节并发收录：后端可支持，asset uuid 不冲突，本地文件路径也按 asset uuid 分离。
  - 同一章节重复收录：后端可幂等 upsert，但前端仍应保持同一章节按钮禁用，避免重复下载和重复本地写入。
  - external directory 首选驱动下不同章节会写不同文件；仍应避免同一章节重复写同一路径。
- 推荐实现：
  - 将前端状态从 `collectingChapterId: number | null` 改为 `collectingChapterIds: Set<number>`。
  - `ChapterAudioResults.tsx` 中：
    - `isCollecting = collectingChapterIds.has(chapterAudio.chapter_id)`
    - `collectDisabled = collectingChapterIds.has(chapterAudio.chapter_id)`
  - `handleCollectChapterAudio()` 进入时对当前章节做 in-flight guard，finally 中只移除当前章节。
  - 补 focused 测试或 source guard，锁定“不同章节不互相禁用、同一章节仍禁用”的行为。
- 当前结论：可以小步放开不同章节并发收录，但不应去掉同一章节 in-flight guard。

### 完成记录（2026-05-05）

- 新增 `frontend/src/pages/audiobook/chapterAudioCollectingState.ts`：
  - `addCollectingChapterId()`
  - `removeCollectingChapterId()`
- `useAudiobookChapterAudioActions.ts`：
  - 将 `collectingChapterId` 改为 `collectingChapterIds: Set<number>`。
  - 增加 `collectingChapterIdsRef`，对同一章节重复收录做同步 in-flight guard。
  - finally 阶段只移除当前章节，不影响其他正在收录的章节。
- `AudiobookPage.tsx`、`AudiobookCompletionStep.tsx`、`ChapterAudioResults.tsx`：
  - 传递 `collectingChapterIds`。
  - 每个章节只在自身 `collectingChapterIds.has(chapterAudio.chapter_id)` 时禁用。
- 新增测试：
  - `frontend/src/pages/audiobook/__tests__/chapterAudioCollectingState.test.ts`
  - `frontend/src/pages/audiobook/__tests__/collectingStateSource.test.ts`
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__"`：34 files passed，154 tests passed。
  - `npm run type-check`：通过。
- 未覆盖风险：未做浏览器真实 external directory 并发写入的端到端验证；当前依据 asset uuid 分离、前端同章节 guard、后端 upsert/唯一索引测试控制风险。

---

## V3-06：UI 颜色 token 语义清理

### 问题

`danger`、`reviewDanger`、`warning`、`reviewWarning` 等 token 存在部分语义重叠。

### 当前结论

这属于视觉规范整理，不应混入后端或任务流优化。

### 建议方向

- 先列出现有 token 与使用位置。
- 区分通用危险操作、评审风险、警告、待处理状态。
- 修改时配合页面截图或 source guard。

### 验收标准

- 不改变按钮语义。
- 不降低警告/危险状态的可识别性。
- 跑相关前端测试和类型检查。

### 完成记录（2026-05-05）

- `frontend/src/pages/audiobook/audiobookTheme.ts` 新增 `audiobookColorRoles` 语义角色层，保留既有 `audiobookColors` flat token 兼容：
  - `destructiveAction`：删除、不可逆操作。
  - `reviewRisk`：脚本评审分数风险。
  - `taskStatus`：任务/历史状态。
  - `notice.warning`：可恢复警告提示。
- `audiobookButtonSx.dangerOutlined`、`dangerContained` 改为使用 `destructiveAction`，不改变按钮视觉色值。
- 关键消费者迁移：
  - `ChapterDeleteConfirmDialog.tsx`
  - `ChapterActionsMenu.tsx`
  - `ChapterDrawer.tsx`
  - `HistoryDialog.tsx`
  - `scriptReviewReportUtils.ts`
  - `TaskStageDetails.tsx`
  - `ChapterAudioResultItem.tsx`
  - `ScriptEditorConflictNotice.tsx`
- `frontend/src/pages/audiobook/__tests__/buttonStyleSource.test.ts` 新增 source guard，锁定语义角色分组与关键消费者引用。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__"`：34 files passed，155 tests passed。
  - `npm run type-check`：通过。
- 未覆盖风险：本轮不做截图回归和全页面视觉重绘；由于只做 token 语义映射且保留原色值，风险控制在可维护性层面。

---

## 新增优化项准入规则

新增任何 `V3-*` 优化项前，必须满足至少一项：

1. 当前代码中有明确重复、复杂度或行为风险。
2. 有失败测试、线上问题或可复现缺陷。
3. 有性能瓶颈证据。
4. 有明确 API/UX 兼容窗口结论。
5. 有测试补强价值，并能降低后续改动风险。

不满足以上条件的想法，只记录为观察项，不进入实施队列。

---

## 执行顺序建议

1. `V3-01` 已完成：测试补强收益高，能降低后续前端任务流修改风险。
2. `V3-02` 已完成：优先入口按模块审计完成，保留项已有原因。
3. `V3-03` 已完成导出任务 trace 试点、生成入口初始 trace、后台内部阶段 trace、失败诊断 trace、积分预检稳定 id、积分冻结事件 payload trace。
4. `V3-04` 已完成：仓库内未发现前端旧端点消费者，测试阶段确认无真实用户后已删除旧 preview 路由。
5. `V3-05` 已完成：收录按钮已改为按章节集合状态禁用，不同章节可并发收录，同一章节仍有 in-flight guard。
6. `V3-06` 已完成：新增颜色语义角色层并迁移关键消费者，未做视觉重绘。

---

## V3-07：内置音效库文件名与实际素材不匹配

### 问题描述

`SoundEffectDesigner` 的内置音效库引用了大量预期存在的音效文件名，如 `rain_light.mp3`、`rain_heavy.mp3`、`wind.mp3`、`city.mp3`、`forest.mp3`、`footsteps.mp3`、`door_open.mp3` 等。然而，实际 `backend/data/audio_library/sound_effects/` 目录下当前仅存在：

- `effects/action/` 下的 `sfx_action_*.wav`（5 个文件）
- `environment/city_wind/` 下的 `ambient_city_wind_calm_vidu_*.wav`（3 个文件）

当前 `sound_effects_index.json` 的 8 个外部索引条目均指向真实存在的文件；问题不是“外部索引大量不可用”，而是内置硬编码占位文件名与实际素材库不同步。若匹配逻辑命中这些内置占位条目，混音阶段可能无法解析文件并跳过该音效。

### 严重程度评估

**🟡 中等（Medium）**

- 影响范围：所有使用默认音效匹配的有声书项目。
- 用户感知：部分预期音效缺失，但系统主流程仍可完成。
- 业务风险：降低产品体验质量；外部索引已有素材仍可正常使用。

### 根因分析

1. 内置音效库是硬编码的静态映射表，未与实际文件系统保持同步。
2. `_sfx_mixin.py` 的回退逻辑（按 stem rglob）因文件名完全不匹配而失效。
3. 缺失音效的检测仅在运行时通过 `logger.warning` 输出，无前端反馈机制。

### 修复建议

**方案 A：补齐缺失的音效素材文件**

- 在 `sound_effects/` 下按类别创建子目录（`weather/`、`action/`、`environment/` 等）。
- 补齐 `rain_light.mp3`、`rain_heavy.mp3`、`wind.mp3`、`footsteps.mp3`、`door_open.mp3` 等核心音效。
- 更新 `sound_effects_index.json` 索引，确保与文件系统一致。

**方案 B：更新内置库映射为语义匹配的实际文件**

- 将 `sound_effect_designer.py` 内置 `sound_library` 中缺失条目的 `file` 字段改为实际存在的 `sfx_action_*.wav` 或 `ambient_city_wind_*.wav`。
- 仅允许语义一致或高度接近的映射；不要把雨声临时映射为城市风声。
- 风险：现有素材覆盖不足，不能一次性修复所有内置条目。

**方案 C（第一阶段推荐）：外部索引真实素材优先 + 加载期校验**

- 加载外部索引时验证 `file_path` 是否存在；缺失则 warning 并跳过。
- 外部索引与内置库同名时：若内置条目不可精确解析，则允许外部真实素材覆盖内置占位。
- 描述/标签匹配时优先选择可解析到真实文件的候选，避免继续命中 `paper.mp3` 这类占位文件名。
- 不为语义不匹配的条目强行指定临时素材。

### 实施步骤

1. **盘点缺失文件**：遍历 `SoundEffectDesigner._init_sound_library()` 返回的内置 `sound_library` 条目，对比 `sound_effects/` 实际文件，输出缺失清单。
2. **选择修复方案**：根据素材获取成本（自有素材 vs AI 生成 vs 第三方采购）选择方案 A/B/C。
3. **实施方案**：
   - 若选 A：上传/生成素材文件，更新索引。
   - 若选 B：修改 `sound_effect_designer.py` 中内置 `sound_library` 的 `file` 字段。
   - 若选 C：修改 `_load_external_sound_library` 和匹配优先级。
4. **补测试**：新增测试验证外部索引缺失文件会跳过、外部真实素材可覆盖不可解析内置占位、匹配时优先返回真实素材。
5. **验证**：运行完整有声书生成流程，检查日志中无"音效文件不存在"警告。

### 预期效果

- 已有外部真实素材不会被不可解析的内置占位遮蔽。
- 索引与文件不同步时，在加载阶段暴露问题。
- 后续补齐语义素材后，内置库命中率可持续提升。

### 验证方法

1. **单元测试**：
   ```bash
   python -m pytest "backend/tests/test_audio_fx_optimizations.py" -q -k "external_sound_library or match_effect_prefers_resolvable"
   ```
2. **集成测试**：运行一个包含多种场景（雨、风、城市、森林）的章节生成，检查最终音频中是否包含对应音效。
3. **日志检查**：搜索 `"⚠️ 音效文件不存在"` 出现次数，修复后应为 0。

### 第一阶段完成记录（2026-05-05）

- `_load_external_sound_library()` 已增加文件存在性校验；缺失文件 warning 后跳过。
- 外部索引条目与内置库同名时，若内置条目不可精确解析，允许外部真实素材覆盖内置占位。
- 描述/标签匹配时优先选择可解析音频文件的候选，避免内置占位遮蔽外部真实素材。
- 新增测试覆盖：
  - 外部索引缺失文件跳过并记录 warning。
  - 外部真实素材覆盖不可解析的内置占位。
  - 语义都匹配时优先返回外部真实素材。
- 未覆盖风险：本轮未补齐 `rain_light.mp3`、`footsteps.mp3` 等缺失素材本身；素材补齐或采购需单独推进。

### Wikimedia CC0/Public Domain 候选启动记录（2026-05-06）

- 已新增 `backend/data/audio_library/sfx_candidates.jsonl`，首批 10 条候选均来自 Wikimedia Commons，许可限定为 `CC0` 或 `Public Domain`。
- 覆盖类别：`environment`、`action`、`emotion`、`transition`。
- 候选条目全部保留：
  - `status=candidate_only`
  - `requires_manual_review=true`
  - `source_url`
  - `file_url`
  - `license`
  - `license_url`
  - `license_commercial=true`
- 本轮未下载原始音频文件，未写入 `sound_effects_index.json`，未进入正式音效库。
- 下一步必须逐条打开 Wikimedia `source_url` 复核文件页、许可、作者和文件适用性；确认后将文件下载到 `backend/data/audio_library/approved_sfx/`，再通过 manifest dry-run/import 入库。
- 本地 Wikimedia API 直连在本轮出现 TLS timeout，因此本轮采用人工候选种子方式；后续如果要恢复自动候选发现，应继续保持只写 `sfx_candidates.jsonl`、不自动下载。
- 验证通过：
  - `backend/data/audio_library/sfx_candidates.jsonl` JSONL 解析通过，10 条候选全部具备来源、许可和文件 URL。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：44 passed。

### Wikimedia manifest dry-run 记录（2026-05-07）

- 已下载并整理到 `backend/data/audio_library/approved_sfx/wikimedia_commons/` 的首批素材：10 个。
- 已新增 `backend/data/audio_library/sfx_import_manifest_wikimedia_commons.jsonl`，仅包含当前已存在本地文件且许可字段完整的条目。
- manifest 条目保留 `source_url`、`license_url`、`author`、`license_commercial`、`attribution_required`、`category`、`style`、`tags` 等审计和分类字段。
- 修复 `manifest-draft` 路由路径解析：`source_dir="approved_sfx"` 现在与正式导入一致，解析到音频库目录内；外部路径继续被限制。
- 修复本地授权素材导入时忽略 manifest `category/style` 的问题：人工审核填写的分类和风格现在优先于自动关键词分类，非法值才回退自动分类。
- dry-run 结果：
  - `candidates=10`
  - `rejected_license=0`
  - `rejected_file=0`
  - `rejected_quality=0`
  - `imported=0`（符合 dry-run，不写索引）
- 本轮仍未执行正式导入，未写入 `sound_effects_index.json`，未触发真实云上传。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audiobook_audio_library_routes.py" "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audio_fx_optimizations.py" -q`：134 passed。

### Wikimedia 首批正式导入记录（2026-05-07）

- 用户已确认执行正式导入。
- 正式导入结果：
  - `candidates=10`
  - `imported=10`
  - `rejected_license=0`
  - `rejected_file=0`
  - `rejected_quality=0`
  - `skipped_existing=0`
- `backend/data/audio_library/sound_effects_index.json` 当前总条目数：20。
- 首批 Wikimedia 条目：10 个，文件全部可解析，质量状态全部为 `accepted`。
- 索引记录口径：
  - 本地已授权导入统一记录为 `source=local_authorized`。
  - Wikimedia Commons 来源通过 `source_url=https://commons.wikimedia.org/...`、`license`、`license_url`、`author` 等字段保留授权审计链。
  - 当前数据库核验：`source=local_authorized` 10 条，`source_url` 指向 Wikimedia Commons 的条目 10 条。
- 本轮正式导入未真实上传云端；后续核验显示当前配置仍为 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=local_fs`，因此 10 个 Wikimedia 来源条目的云端元数据为：
  - `storage_mode=local_cache`
  - `storage_driver=local_fs`
  - `asset_scope=shared_library`
- 已落位分类：
  - `environment/intense`：Rain and thunder
  - `environment/peaceful`：Rain ambience、Flowing water
  - `action/realistic`：Knocking on wood or door、Old school bell 5、Doorbell classic dingdong、Sound Effect - Door Bell
  - `transition/fantasy`：Synthetic bell sound
  - `emotion/realistic`：Whistle 16x
  - `action/intense`：Part of fireworks
- 同步修复：
  - `test_audio_fx_optimizations.py::test_sound_library_structure` 的有效分类断言补充 `transition`，与当前音效分类体系一致。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audiobook_audio_library_routes.py" "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audio_fx_optimizations.py" -q`：134 passed。
- 后续若要满足“共享素材必须在云端”的生产形态，需要先配置 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=dashscope_oss`，再对现有 `local_cache` 共享素材执行受控云端同步；同步动作应保持 dry-run/confirm 边界。

### 共享素材云端同步入口补充（2026-05-07）

- 已新增 `POST /api/v1/audiobook/audio-library/cloud-sync`。
- 设计边界：
  - 默认 `dry_run=true`，只扫描并报告待同步素材，不上传、不写索引。
  - 实际同步必须传入 `dry_run=false, confirm=true`。
  - 实际同步前必须启用 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=dashscope_oss`；未启用时返回 400，不会把 `local_cache` 误标记为云端成功。
  - 支持 `library_type=sfx | music | both`。
  - 优先扫描数据库 `audio_library_assets`；对应类型暂无数据库记录或数据库查询失败时，回退 JSON 索引。
  - 只同步有本地缓存文件且尚未是 `storage_mode=durable_cloud` 的条目。
  - 数据库来源上传成功后回写数据库记录；JSON 回退来源上传成功后回写对应 JSON 索引。
  - 上传成功后回写 `storage_mode`、`storage_driver`、`cloud_uri`、`public_url`、`object_key`、`local_cache_path`、`asset_scope`。
- 已新增 `audio_asset_cloud_storage` 配置查询函数：
  - `get_audio_library_storage_driver()`
  - `is_audio_library_cloud_storage_enabled()`
- 当前真实库 dry-run：
  - `library_type=both`
  - `cloud_enabled=false`
  - `storage_driver=local_fs`
  - `eligible=39`
  - `eligible_by_type.sfx=20`
  - `eligible_by_type.music=19`
  - `uploaded=0`
  - `skipped_missing_file=0`
- 这说明当前 20 个音效索引条目和 19 个音乐索引条目文件都可解析，但均尚未云端化；配置 DashScope OSS 后可通过该入口执行受控同步。
- 已按用户确认尝试执行真实同步：
  - 请求：`POST /api/v1/audiobook/audio-library/cloud-sync`
  - 参数：`{"library_type":"both","dry_run":false,"confirm":true}`
  - 结果：`400`
  - 详情：`云存储未启用，需先配置 AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=dashscope_oss`
  - 索引核验：`durable_cloud=0`，未发生误写或误标记。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：27 passed。
  - `python -m pytest "backend/tests/test_audio_library_asset_repository.py" "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audiobook_audio_library_routes.py" "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" "backend/tests/test_autoqc_utils.py" "backend/tests/test_dreamweaver_vision_review.py" -q`：153 passed。

### 共享素材库数据库权威索引落地（2026-05-07）

#### 新结论

共享素材库应拆成两层权威：

1. **云端数据库**：素材索引、授权审计、质量、分类、标签、来源、云端 URI、本地缓存路径。
2. **对象存储**：真实音频文件本体。

数据库不直接保存 mp3/wav/ogg 二进制，避免数据库备份、复制、预览下载、CDN 和带宽压力被音频文件放大。

#### 已落地代码

- 新增共享素材数据库模型：`backend/app/models/audio_library_asset.py`
  - 表：`audio_library_assets`
  - 覆盖字段：`library_type`、`asset_scope`、`asset_key`、分类/风格/情绪、授权、质量、文件校验、云端 URI、本地缓存路径、标签、来源 payload。
- 新增 Alembic 迁移文件：`backend/alembic/versions/add_audio_library_assets.py`
  - 已执行 `python -m alembic -c "alembic.ini" upgrade head`。
  - 当前版本：`add_audio_library_assets (head)`。
- 新增数据库索引仓储：`backend/app/services/audiobook/audio_library_asset_repository.py`
  - `upsert_audio_library_asset()`
  - `list_audio_library_asset_records()`
  - `audio_library_asset_to_record()`
- 新增受控迁库入口：`POST /api/v1/audiobook/audio-library/db-sync`
  - 默认 `dry_run=true`，只统计 JSON 索引候选，不写数据库。
  - 实际写库必须 `dry_run=false, confirm=true`。
  - 支持 `library_type=sfx | music | both`。
- 浏览、统计、预览接口已调整为：
  - 优先读取数据库 `audio_library_assets`。
  - 如果数据库未迁移、查询失败或暂为空，回退当前 JSON 索引。
  - 迁移期间不破坏现有 JSON 工作流。

#### 已执行动作与当前数据

- 已将 JSON 索引中的 39 条共享素材索引写入当前数据库 `audio_library_assets`。
- 当前数据库核验结果：
  - `total=39`
  - `by_type={"sfx": 20, "music": 19}`
  - `by_source={"vidu": 10, "local_authorized": 10, "mureka": 19}`
  - `commons_source_url_count=10`
  - `by_storage_mode={"local_cache": 39}`
  - `durable_cloud=0`
- `POST /api/v1/audiobook/audio-library/db-sync` 的 dry-run/confirm 入口仍保留，用于后续从 JSON 索引补量同步到数据库。

#### 仍未执行动作

- 未将音频文件本体上传对象存储；对象存储同步仍由 `cloud-sync` 负责。
- 当前 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=local_fs`，所以真实云同步会被 400 拒绝，不会误标记 `durable_cloud`。
- 数据库只保存共享素材索引和授权/质量/URI 元数据，不保存 mp3/wav/ogg 二进制。

#### 验证通过

- `python -m pytest "backend/tests/test_audio_library_asset_repository.py" -q`：2 passed。
- `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：27 passed。
- `python -m pytest "backend/tests/test_autoqc_utils.py" "backend/tests/test_dreamweaver_vision_review.py" -q`：8 passed。
- `python -m pytest "backend/tests/test_audio_library_asset_repository.py" "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audiobook_audio_library_routes.py" "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" "backend/tests/test_autoqc_utils.py" "backend/tests/test_dreamweaver_vision_review.py" -q`：153 passed。

---

## V3-08：前端 Checkbox 与 Density Select 状态不一致

### 问题描述

`AudioFxConfigPanel.tsx` 中，"开启音效" Checkbox 与"音效密度" Select 是两个独立的状态字段：

- `enable_sound_effects`（boolean）
- `sound_effect_density`（`'off' | 'low' | 'medium' | 'high'`）

用户可以：
1. 勾选 Checkbox（`enable_sound_effects=true`），但将 density 选为 `"off"`。
2. 取消勾选 Checkbox（`enable_sound_effects=false`），但 density 仍为 `"medium"`。

虽然后端 `_apply_audio_fx_to_strategy` 会在 `enable_sound_effects=false` 时强制将 `sound_effect_density` 覆盖为 `"off"`，但前端 UI 展示存在误导：
- Checkbox 未勾选时，density Select 被 `disabled`，但显示的值可能是 `"medium"` 而非 `"off"`。
- 用户重新勾选后，density 仍保持之前的值，若之前是 `"off"` 则需手动改回。

### 严重程度评估

**🔴 严重（Critical）→ 实际为 🟡 中等（Medium）**

- 功能层面：后端兜底逻辑确保不会出错。
- 体验层面：状态矛盾造成用户困惑，增加操作成本。
- 修复成本：极低（前端单行改动）。

### 根因分析

1. 前端 `updateValue` 只更新被修改的字段，不联动相关字段。
2. 两个字段在 UI 上语义强关联（"开启"与"密度"），但在数据模型上是平级的。

### 修复建议

在 `AudioFxConfigPanel.tsx` 中，将 Checkbox 的 `onChange` 改为联动更新 density：

```tsx
<Checkbox
  checked={value.enable_sound_effects}
  onChange={(_, checked) =>
    updateValue({
      enable_sound_effects: checked,
      sound_effect_density: checked
        ? value.sound_effect_density === 'off'
          ? 'medium'
          : value.sound_effect_density
        : 'off',
    })
  }
/>
```

配乐部分的 Checkbox 与 density 同理处理。

### 实施步骤

1. 修改 `AudioFxConfigPanel.tsx` 中音效 Checkbox 的 `onChange` 处理器。
2. 修改配乐 Checkbox 的 `onChange` 处理器。
3. 运行前端类型检查和测试。
4. 手动验证：勾选/取消勾选时 density 值是否正确联动。

### 预期效果

- 消除 Checkbox 与 Select 之间的状态矛盾。
- 用户取消勾选后 density 自动变为 `"off"`，重新勾选后自动恢复为 `"medium"`（或之前的非 off 值）。
- 降低用户困惑和操作成本。

### 验证方法

1. **类型检查**：`npm run type-check` 通过。
2. **单元测试**：若存在 `AudioFxConfigPanel` 相关测试，验证状态联动逻辑。
3. **手动验证**：
   - 打开"耳畔星河"项目配置面板。
   - 勾选"开启音效"，确认 density 为 `"medium"`。
   - 将 density 改为 `"high"`。
   - 取消勾选，确认 density 自动变为 `"off"`。
   - 重新勾选，确认 density 恢复为 `"high"`。

### 完成记录（2026-05-05）

- 新增 `frontend/src/pages/audiobook/audioFxConfigPanelUtils.ts`，集中处理音效/配乐 checkbox 与 density 的联动 patch。
- `AudioFxConfigPanel.tsx` 改为调用 helper：
  - 取消音效时 `sound_effect_density` 自动置为 `"off"`。
  - 从 `"off"` 重新开启音效时恢复为 `"medium"`。
  - 配乐 `enable_music` 与 `music_density` 同步处理。
- 新增 `frontend/src/pages/audiobook/__tests__/audioFxConfigPanelUtils.test.ts`，覆盖开启、关闭、保留已有非 off density 三类行为。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__/audioFxConfigPanelUtils.test.ts" "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts"`：14 passed。

---

## V3-09：placeholder.mp3 音效被静默跳过

### 问题描述

当 `SoundEffectDesigner` 的音效库匹配不到合适素材时，`_match_effect` 返回 `audio_file="placeholder.mp3"`。在 `_sfx_mixin.py` 的混音流程中：

1. `effect_path.exists()` 检查 `placeholder.mp3` 不存在。
2. 按 stem `placeholder` 在 `sound_effects/` 下 rglob，无匹配。
3. 该音效被跳过，`skipped_count += 1`。

若后续生成链路没有补齐素材，用户完全听不到这个音效，且没有任何前端反馈。日志中仅输出 `"⚠️ 音效文件不存在"`，但用户不会查看后端日志。

### 严重程度评估

**🟡 中等（Medium）**

- 影响范围：所有音效库未覆盖的场景。
- 用户感知：预期音效缺失，但无明确提示。
- 业务风险：降低沉浸感，但系统整体功能正常。

### 根因分析

1. `placeholder.mp3` 是设计时的占位符，不能在混音阶段当作真实文件。
2. 当前 `ensure_generated_assets()` 已会处理不可解析音效：
   - 环境音通过 `ensure_vidu_ambient_sound()` / Mureka 回退生成。
   - 剩余动作/情绪短效通过 `enhance_effects_with_vidu()` 生成。
3. 仍存在的缺口是：生成失败或未配置生成能力时，placeholder/缺失素材只在日志中体现，缺少用户可见质量反馈。

### 修复建议

**方案 A：维持当前自动生成回退并补测试**

- 保持 `_resolve_effect_audio_path` 对 `placeholder.mp3` 返回 `None` 的语义。
- 通过 `ensure_generated_assets()` 统一处理不可解析素材，不在解析函数里引入异步生成副作用。
- 补充 action / emotion / environment placeholder 生成路径测试。

**方案 B（推荐后续）：质量评审时检测并反馈**

- 在 `ScriptReviewReport` 或生成完成后的质量报告中，统计 `placeholder.mp3` 数量。
- 若超过阈值（如 3 个），向用户展示提示："本次生成有 X 个音效未能匹配素材库，建议补充音效素材或重新生成。"

### 实施步骤

1. **不修改 `_resolve_effect_audio_path` 的职责**：它只负责同步解析本地路径，不直接触发 AI 生成。
2. **保持 `ensure_generated_assets` 作为生成回退入口**：避免重复引入新的生成链路。
3. **后续修改质量评审**：在 `scriptReviewReportUtils.ts` 或后端质量报告中新增 placeholder / unresolved 音效统计。
4. **补测试**：验证 placeholder 音效的处理路径和用户可见反馈。

### 预期效果

- placeholder 音效在可生成时补齐真实素材；生成不可用或失败时向用户明确反馈。
- 提升用户体验透明度。

### 验证方法

1. **单元测试**：模拟 `_match_effect` 返回 `placeholder.mp3`，验证 `_resolve_effect_audio_path` 行为。
2. **集成测试**：运行一个包含大量陌生场景的章节生成，检查最终音频中 placeholder 音效的处理情况。
3. **日志检查**：确认 `"⚠️ 音效文件不存在"` 中无 `placeholder.mp3` 相关记录。

### 本轮结论（2026-05-05）

- 文档原判断“未实现自动生成回退”不准确；当前代码已有 `ensure_generated_assets()` 与 Vidu/Mureka 生成回退。
- 本轮不再把生成逻辑塞进 `_resolve_effect_audio_path()`，避免同步解析函数承担异步生成副作用。
- 后续若推进，应优先补“用户可见未解析音效统计/质量反馈”，而不是重复新增生成入口。

### 完成记录（2026-05-06）

- `SoundEffectDesigner.export_effect_timeline()` 已新增结构化未解析音效统计：
  - `unresolved_effects.unresolved_count`
  - `unresolved_effects.placeholder_count`
  - `unresolved_effects.missing_file_count`
  - `unresolved_effects.items[]`
  - `warnings[].code = unresolved_sound_effect_assets`
- 生成结果中的 `effect_timeline` 继续通过 `build_checkpoint_patch_from_generation_result()` 写入 `ChapterAudioRun.checkpoint_json`，不新增数据库字段。
- `GET /api/v1/script-review/report/{audiobook_project_id}/{chapter_id}` 会读取最近一次 completed run 的 `effect_timeline`，并把未解析音效合并到：
  - `quality_report.audio_balance.unresolved_effect_count`
  - `quality_report.audio_balance.placeholder_effect_count`
  - `quality_report.audio_balance.missing_effect_file_count`
  - `quality_report.audio_warnings[]`
  - `quality_report.issues[]` 中的 `audio_assets` 问题。
- 前端 `ScriptReviewMetricSections` 已展示“未解析音效”统计，`ScriptReviewIssueList` 通过 `audio_assets` 分类展示音效素材问题。
- 仍保持边界：
  - `placeholder.mp3` 不作为真实文件处理。
  - 未解析音效不阻塞章节音频生成，只作为用户可见质量 warning。
  - 不引入公开平台自动下载，也不把异步生成塞进同步路径解析函数。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py::test_export_effect_timeline_reports_unresolved_sound_effect_assets" "backend/tests/test_script_review_routes.py" -q`
  - `python -m pytest "backend/tests/test_temp_segment_store.py::test_build_checkpoint_patch_from_generation_result_includes_effect_timeline" "backend/tests/test_audio_fx_optimizations.py::test_export_effect_timeline_includes_matched_effect_id" -q`
  - `npm test -- "src/pages/audiobook/__tests__/scriptReviewUtils.test.ts" "src/pages/audiobook/__tests__/scriptReviewSource.test.ts"`

---

## V3-10：音效/配乐时长估算过于粗糙

### 问题描述

多处代码使用 `text_length / 10.0` 估算片段时长（假设 10 字/秒）：

- `sound_effect_designer.py` L222：`estimated_duration = text_length / 10`
- `_parallel_mixin.py`：配乐设计时 `seg_duration = seg_len / 10.0`

实际中文朗读语速约为 4-5 字/秒。10 字/秒的估算偏快，导致：
1. 音效的 `timestamp` 计算偏早，可能在人声未开始时叠加。
2. 配乐的 `duration` 字段基于错误估算（`min(max(seg_duration, 20.0), 120.0)`），可能导致配乐过短或过长。
3. 虽然 `_realign_timelines_with_durations` 会用真实音频时长修正，但配乐的 `duration` 字段在修正前已用于覆盖率计算和混音决策。

### 严重程度评估

**🟡 中等（Medium）**

- 影响范围：所有使用默认时长估算的音效和配乐。
- 用户感知：音效/配乐与人声的同步可能存在轻微偏差。
- 业务风险：时间线对齐机制部分缓解，但初始估算错误仍影响混音质量。

### 根因分析

1. 10 字/秒是开发初期的粗略假设，未根据实际 TTS 输出校准。
2. 未接入 TTS 模型的实际语速参数（如 CosyVoice 的 `speed` 字段）。

### 修复建议

**方案 A（推荐）：调整估算速率为 4.5 字/秒**

- 将 `text_length / 10` 改为 `text_length / 4.5`。
- 简单、低风险、立即生效。

**方案 B：接入 TTS 实际语速参数**

- 从 `voice_profile` 或 `voice_params` 中读取 `speed`/`rate` 字段。
- 计算实际语速 = 基准语速 × speed 系数。
- 更精确，但实现复杂度更高。

**方案 C：使用历史 TTS 输出校准**

- 收集已生成音频的实际时长与文本长度，计算平均语速。
- 动态更新估算参数。
- 最精确，但需要数据积累和统计基础设施。

### 实施步骤

1. **选择方案**：建议先实施方案 A（调整为 4.5 字/秒），作为快速修复。
2. **修改代码**：
   - `sound_effect_designer.py` L222
   - `_parallel_mixin.py` 中配乐设计的时长估算
3. **补测试**：更新相关测试中的预期时长。
4. **验证**：运行生成流程，对比修正前后的时间线差异。

### 预期效果

- 音效 `timestamp` 估算准确度提升约 50%。
- 配乐 `duration` 更接近实际需求，覆盖率计算更合理。
- 减少 `_realign_timelines_with_durations` 的修正幅度。

### 验证方法

1. **单元测试**：验证 `estimated_duration` 计算逻辑。
2. **对比测试**：选取同一段文本，对比 10 字/秒 vs 4.5 字/秒估算的时长与实际 TTS 输出时长的误差。
3. **集成测试**：运行完整章节生成，检查音效/配乐时间线是否更贴合人声。

### 完成记录（2026-05-05）

- 新增 `backend/app/services/audiobook/duration_estimator.py`：
  - `AUDIOBOOK_ESTIMATED_CHARS_PER_SECOND = 4.5`
  - `estimate_narration_duration_seconds()`
- `SoundEffectDesigner.design_effects()` 已使用统一 helper 估算音效时间线 timestamp。
- `_parallel_mixin.py` 配乐候选场景的章节总时长、片段起点和片段时长已使用统一 helper。
- `_timeline_mixin.py` 的后续时间线对齐估算也改为同一 helper，避免音效/配乐初始时间轴和对齐估算不一致。
- `SegmentPreviewService.estimate_duration_seconds()` 已复用统一 helper，并保留单段试听 3 秒最小时长。
- `AudioQualityReviewer` 的音效密度、章节时长和平均片段时长评审已复用统一 helper，避免继续按 10 字/秒高估音效密度。
- 新增测试覆盖：
  - 45 字片段后下一音效 timestamp 为 10 秒。
  - 配乐候选场景章节总时长和 start_time 使用 4.5 字/秒估算。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py" -q`：34 passed。
  - `python -m pytest "backend/tests/test_segment_preview_service.py" "backend/tests/test_audiobook_audio_quality_reviewer.py" -q`：6 passed。
- 历史未覆盖风险已于 2026-05-06 收口：`audio_quality_reviewer.py` 与 `segment_preview_service.py` 不再保留独立 10 字/秒估算逻辑。

---

## V3-11：配乐场景筛选遗漏中等情绪片段

### 问题描述

`_parallel_mixin.py` 在筛选需要配乐的片段时，使用以下条件：

```python
has_strong_emotion = any(key in emotion for key in ["tense", "sad", "happy", "excited", "solemn"])
if not has_explicit_music and not has_strong_emotion:
    continue
```

只有 `tense`、`sad`、`happy`、`excited`、`solemn` 被视为"强情绪"。以下情绪被排除：
- `angry`（愤怒）
- `fearful`（恐惧）
- `nervous`（紧张）
- `mysterious`（神秘）
- `peaceful`（平静，但可能适合轻音乐）

这意味着这些情绪的片段在没有显式 `music_cue` 时不会获得配乐，降低了沉浸感。

### 严重程度评估

**🟡 中等（Medium）→ 实际为 🟢 轻微（Low）**

- 影响范围：特定情绪场景的配乐覆盖。
- 用户感知：部分情绪场景缺少配乐，但系统整体功能正常。
- 业务风险：体验降级，但非阻断性问题。

### 根因分析

1. 强情绪关键词列表是手动维护的，未覆盖所有情绪类型。
2. 情绪分类与音乐匹配逻辑之间缺少映射表。

### 修复建议

扩展 `has_strong_emotion` 的关键词列表：

```python
has_strong_emotion = any(
    key in emotion
    for key in [
        "tense", "sad", "happy", "excited", "solemn",
        "angry", "fear", "nervous", "mysterious", "epic",
    ]
)
```

同时，考虑为 `peaceful` 场景也添加轻音乐（但可能增加音乐密度，需评估）。

### 实施步骤

1. 修改 `_parallel_mixin.py` 中的 `has_strong_emotion` 判断逻辑。
2. 更新相关测试中的预期行为。
3. 验证：运行包含多种情绪的章节生成，检查配乐覆盖范围。

### 预期效果

- 愤怒、恐惧、紧张、神秘等场景的配乐覆盖率提升。
- 整体配乐体验更连贯。

### 验证方法

1. **单元测试**：模拟不同情绪片段，验证是否被纳入配乐筛选。
2. **集成测试**：运行包含 `angry`、`fearful`、`mysterious` 场景的章节，检查日志中是否设计了配乐。

### 完成记录（2026-05-05）

- `_parallel_mixin.py` 新增 `MUSIC_WORTHY_EMOTION_KEYWORDS` 与 `_has_music_worthy_emotion()`，补充：
  - `angry`
  - `fear`
  - `fearful`
  - `nervous`
  - `mysterious`
  - `suspense`
  - `epic`
- 新增 `_map_music_mood_from_emotion()`，让筛选和 mood 映射使用同一套规则。
- `fearful` / `nervous` / `suspense` 会映射为 `tense`；`mysterious` 会映射为 `mysterious`。
- 新增测试覆盖：无显式 `music_cue` 的 `fearful` 片段会进入配乐候选，且 mood 为 `tense`。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py" -q`：34 passed。

---

## V3-12：intelligent_balance 默认关闭导致 BGM 音量僵化

### 问题描述

`_music_mixin.py` 中的智能音量平衡默认关闭：

```python
intelligent_balance = audio_fx.get("intelligent_balance", False)
```

当 `intelligent_balance=False` 时，BGM 使用固定基准音量 `-36dB` 再减 `3dB`（即 `-39dB`）。对于紧张/史诗场景，`-39dB` 的 BGM 可能过于微弱，难以营造氛围。

智能音量平衡的逻辑（`_calculate_intelligent_bgm_volume`）会根据场景类型和情绪动态调整：
- 开场/结尾：`+5dB`
- 主题音乐：`+3dB`
- 紧张/史诗：`+8dB`
- 平静/悲伤：`-5dB`

但该逻辑仅在 `intelligent_balance=True` 时生效。需要注意：当前 `_calculate_intelligent_bgm_volume()` 的情绪分支不只作用于 `opening`/`ending`/`theme`，`underscore` 只要携带 `mood`，也会获得 `tense` / `epic` / `peaceful` / `sad` / `joyful` / `romantic` 的音量调整。

### 严重程度评估

**🟡 中等（Medium）→ 实际为 🟢 轻微（Low）**

- 影响范围：所有使用默认 BGM 音量的项目。
- 用户感知：部分场景配乐可能过弱。
- 业务风险：体验降级，但用户可通过调整 `base_bgm_volume` 手动补偿。

### 根因分析

1. `intelligent_balance` 默认关闭，可能是出于保守策略（避免音量突变）。
2. 若生成出的配乐 timeline 缺少准确 `mood`，智能音量即使开启也无法体现正确情绪差异。

### 修复建议

**方案 A：默认开启 intelligent_balance**

- 将默认值从 `False` 改为 `True`。
- 在 `AudioFxConfig` schema 中也同步更新默认值。
- 风险：会改变现有项目的默认混音音量，可能造成听感回归；不建议在无兼容评估时直接改。

**方案 B（推荐先做）：补测试核实现有智能音量行为**

- 验证 `underscore + tense/epic/peaceful/sad/joyful/romantic` 的音量分支是否符合预期。
- 验证配乐 timeline 的 `mood` 是否从 `_parallel_mixin.py` 正确传入。
- 若测试发现缺口，再针对 mood 传递或计算函数修复。

**方案 C：前端增加智能音量开关**

- 在 `AudioFxConfigPanel` 中增加"智能音量平衡" Checkbox，让用户自主选择。
- 默认是否开启需单独做兼容评估；若新增开关，应先保证历史项目默认行为不变。

### 实施步骤

1. **先补测试**：验证不同 `music_type` 和 `mood` 下的 `_calculate_intelligent_bgm_volume()` 输出。
2. **核验 timeline**：确认 `_parallel_mixin.py` 输出的配乐 cue 包含正确 mood。
3. **兼容评估**：对比默认关闭与默认开启的同章节混音响度，再决定是否修改默认值。
4. **若决定改默认值**：需要同步后端 schema、前端默认配置和迁移说明。

### 预期效果

- 紧张/史诗场景的 BGM 更突出，增强氛围感。
- 平静/悲伤场景的 BGM 更低调，不干扰人声。
- 整体混音质量提升。

### 验证方法

1. **单元测试**：模拟不同 `music_type` 和 `mood`，验证 `_calculate_intelligent_bgm_volume` 输出。
2. **集成测试**：运行同一段文本在 `tense` 和 `peaceful` 情绪下的生成，对比 BGM 音量差异。
3. **主观听感**：人工试听验证 BGM 与人声的平衡是否自然。

### 本轮结论（2026-05-05）

- 原文“underscore 未做情绪感知调整”不准确；当前计算函数的 mood 分支对 underscore 也生效。
- `intelligent_balance` 默认值暂不从 `False` 改为 `True`，因为这会改变现有项目默认混音行为。
- `_calculate_intelligent_bgm_volume()` 与配乐 timeline mood 传递测试已在 2026-05-06 补齐；后续只在完成同章节 A/B 听感评估后，再考虑是否默认开启。

### 完成记录（2026-05-06）

- 已补充 `test_intelligent_bgm_volume_adjusts_underscore_moods`，覆盖 `underscore` 在 `tense`、`epic`、`peaceful`、`sad`、`joyful`、`romantic`、`mysterious` 下的音量计算。
- 已补充 `test_music_composer_export_timeline_preserves_mood`，防止 `MusicComposer.export_music_timeline()` 后续遗漏 `mood` 字段。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py::test_music_composer_export_timeline_preserves_mood" "backend/tests/test_audio_fx_optimizations.py::test_intelligent_bgm_volume_adjusts_underscore_moods" -q`：8 passed。
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py" -q`：66 passed。
- 当前结论不变：生产默认值继续保持 `intelligent_balance=False`，避免未做 A/B 听感验证前改变历史项目默认混音结果。

---

## V3-13：前端 AudioFxConfigPanel 缺少配乐提示信息

### 问题描述

`AudioFxConfigPanel.tsx` 中，音效部分有提示信息：

> "提示：音效将由 AI 根据章节内容智能匹配，支持大雨、街道、森林等场景识别。"

但配乐部分没有对应的提示。用户可能不理解"AI 配乐"具体做什么，以及配乐密度选项（"稀疏"、"适中"、"丰富"）的实际差异。

### 严重程度评估

**🟢 轻微（Low）**

- 影响范围：所有使用音频配置面板的用户。
- 用户感知：对配乐功能理解不足，可能导致配置不当。
- 业务风险：极低，纯体验优化。

### 修复建议

在配乐 Checkbox 下方添加提示信息，与音效部分的提示对称：

```tsx
{value.enable_music && (
  <Box sx={{ mt: 2, p: 1.5, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
    <Typography variant="caption" color="text.secondary">
      提示：配乐将由 AI 根据情节节奏和情感基调自动设计，支持悬疑、史诗、浪漫等多种风格。
    </Typography>
  </Box>
)}
```

### 实施步骤

1. 修改 `AudioFxConfigPanel.tsx`，在配乐 density Select 下方添加提示 Box。
2. 运行前端类型检查和测试。
3. 手动验证提示是否正确显示。

### 预期效果

- 用户对配乐功能的理解更直观。
- 降低因误解导致的配置不当。

### 验证方法

1. **类型检查**：`npm run type-check` 通过。
2. **手动验证**：打开配置面板，勾选"开启背景音乐"，确认提示文案显示正确。

### 完成记录（2026-05-05）

- `AudioFxConfigPanel.tsx` 已在开启背景音乐时显示配乐提示：
  - “配乐将由 AI 根据情节节奏和情感基调自动设计，支持悬疑、史诗、浪漫等多种风格。”
- 该改动与 V3-08 同步完成。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__/audioFxConfigPanelUtils.test.ts" "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts"`：14 passed。

---

## V3-14：音效库外部索引加载未验证文件存在性

### 问题描述

`SoundEffectDesigner._load_external_sound_library()` 从 `sound_effects_index.json` 加载音效条目时，不验证 `file_path` 指向的文件是否存在：

```python
for entry in data:
    library.append({
        "name": entry.get("name", ""),
        "file": entry.get("file_path", ""),
        ...
    })
```

当前索引中有 8 个条目，与 `sound_effects/` 下的 8 个实际文件匹配。但如果索引与文件不同步（如索引更新但文件未上传，或文件被删除），会导致运行时跳过这些音效，且仅在混音阶段通过 `logger.warning` 提示。

### 严重程度评估

**🟢 轻微（Low）**

- 影响范围：依赖外部索引的音效匹配。
- 用户感知：特定音效缺失，但系统整体功能正常。
- 业务风险：低，当前索引与文件同步。

### 修复建议

在 `_load_external_sound_library` 中增加文件存在性校验：

```python
file_path = entry.get("file_path", "")
if file_path:
    full_path = self.audio_library_dir / file_path
    if not full_path.exists():
        logger.warning("音效索引条目文件不存在: %s", full_path)
        continue  # 或标记为缺失
```

### 实施步骤

1. 修改 `sound_effect_designer.py` 中的 `_load_external_sound_library`。
2. 补测试：模拟索引中存在但文件缺失的情况。
3. 验证：检查日志中是否正确输出缺失警告。

### 预期效果

- 索引与文件不同步时，问题在加载阶段即被发现。
- 减少运行时混音阶段的意外跳过。

### 验证方法

1. **单元测试**：创建临时索引文件，指向不存在的路径，验证加载行为。
2. **日志检查**：确认 `"音效索引条目文件不存在"` 日志正确输出。

### 完成记录（2026-05-05）

- `_load_external_sound_library()` 已在加载期校验 `file_path`：
  - 绝对路径要求文件存在。
  - 相对路径按 `AUDIO_LIBRARY_DIR / file_path` 和 `SOUND_EFFECTS_DIR / file_path` 校验。
  - 缺失文件记录 warning 并跳过，不加入 `sound_library`。
- 新增测试覆盖缺失索引条目不会进入音效库，且日志包含 `"音效索引条目文件不存在"`。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py" -q`：34 passed。

---

## 执行顺序建议

1. `V3-01` 已完成：测试补强收益高，能降低后续前端任务流修改风险。
2. `V3-02` 已完成：优先入口按模块审计完成，保留项已有原因。
3. `V3-03` 已完成导出任务 trace 试点、生成入口初始 trace、后台内部阶段 trace、失败诊断 trace、积分预检稳定 id、积分冻结事件 payload trace。
4. `V3-04` 已完成：仓库内未发现前端旧端点消费者，测试阶段确认无真实用户后已删除旧 preview 路由。
5. `V3-05` 已完成：收录按钮已改为按章节集合状态禁用，不同章节可并发收录，同一章节仍有 in-flight guard。
6. `V3-06` 已完成：新增颜色语义角色层并迁移关键消费者，未做视觉重绘。
7. `V3-07` 首批素材正式导入完成：外部真实素材优先、索引校验、不可解析内置占位覆盖已完成；首批 10 个 Wikimedia Commons CC0/Public Domain 已入库，当前因未配置云存储为 `local_cache`；云端 dry-run/confirm 同步入口已落地，待配置 OSS 后执行真实同步。
8. `V3-08` 已完成：前端 checkbox 与 density 已联动。
9. `V3-09` 已完成：不改生成链路；当前已有生成回退，未解析音效通过 `effect_timeline`、checkpoint 和审核报告展示用户可见 warning。
10. `V3-10` 已完成：音效/配乐/时间线对齐、单段试听和质量评审估算统一到 4.5 字/秒 helper。
11. `V3-11` 已完成：配乐候选情绪关键词和 mood 映射已扩展。
12. `V3-12` 测试补强完成：智能音量算法和 timeline mood 传递已有回归覆盖；默认开启仍需单独听感评估。
13. `V3-13` 已完成：前端配乐提示文案已补充。
14. `V3-14` 已完成：外部索引加载期已验证文件存在性。
15. `V3-15` 已完成：`music_index.json` 新写入条目使用相对路径，混音/试听读取时按 base_dir 解析。
16. `V3-16` 已完成：MusicComposer 新增 `_load_external_music_library` 与加载期文件校验。
17. `V3-17` 已完成：MusicComposer 初始化时从 `music_index.json` 预加载音乐池缓存，已有变体数量充足时直接复用。
18. `V3-18` 已完成：`_match_music` 改为基于包含项目、章节、场景和起点的 seed 稳定选取。
19. `V3-19` 已完成：注册时自动评估质量元数据；新增低质/孤立素材清理方法。
20. `V3-20` 已完成：段落转化 JSON 解析失败后按更小 chunk 重试，减少整批 fallback；日志改为记录解析错误上下文。
21. `V3-21` 已完成：角色对白归属 prompt、明确引语纠偏和旁白情绪补强已落地。

---

## V3-15：`music_index.json` 使用绝对路径导致不可移植

### 问题

`ai_music.py` 的 `_update_music_index()` 在写入索引时使用 `str(cache_file)`，而 `cache_file` 是 `Path` 对象解析后的绝对路径（如 `C:\Users\cuigu\novel_writing_agent\backend\data\audio_library\music_cache\xxx.mp3`）。

这导致：
1. 索引文件不可移植——换机器、改目录后所有 `file_path` 失效。
2. `_resolve_music_path` 读取索引时需额外处理绝对路径，且 `Path(file_path).exists()` 依赖本机路径。
3. 与 `sound_effects_index.json` 的设计不一致——音效索引使用相对路径（如 `sound_effects/environment/city_wind/xxx.wav`）。

### 修复方案

写入时将 `cache_file` 转为相对于 `audio_library_dir` 的相对路径；读取时按 `base_dir / file_path` 解析。

### 完成记录（2026-05-05）

- `_update_music_index()` 中 `file_path` 改为 `cache_file.relative_to(self.cache_dir.parent)` 的 POSIX 格式字符串。
- 新增 `resolve_audio_library_file_path()` helper，统一按素材库根目录解析索引中的相对路径，同时兼容旧绝对路径。
- `_music_mixin._resolve_music_path()` 和 `SegmentPreviewService.resolve_music_path()` 读取索引时已按 `base_dir / file_path` 解析相对路径。
- 存量 `music_index.json` 已完成一次性迁移：19 条 `file_path` 均由素材库内部绝对路径改为 `music_cache/*.mp3` 相对路径；迁移后无剩余绝对路径，且全部文件可解析。
- 新增测试覆盖：
  - 索引写入的 `file_path` 为相对路径格式。
  - 混音链路读取 `music_index.json` 的相对 `file_path`。
  - 单段试听读取 `music_index.json` 的相对 `file_path`。

---

## V3-16：MusicComposer 缺少外部索引加载与文件校验

### 问题

`SoundEffectDesigner` 已具备完整的外部索引加载机制（`_load_external_sound_library` + 加载期文件存在性校验），但 `MusicComposer` 完全缺失对等能力：

1. `_init_music_library()` 返回的静态字典引用的文件（如 `suspense_1.mp3`、`joy_1.mp3`）均不存在于磁盘，但无加载期校验。
2. `music_index.json` 包含 AI 生成的真实素材，但 `MusicComposer` 从不读取该索引到 `music_library`。
3. 当 AI 生成不可用时，`_match_music()` 只能匹配到不存在的占位文件，混音阶段全部跳过。

### 架构不对称对比

| 能力 | SoundEffectDesigner | MusicComposer |
|------|---------------------|---------------|
| 内置占位库 | ✅ `_init_sound_library` | ✅ `_init_music_library` |
| 外部索引加载 | ✅ `_load_external_sound_library` | ❌ 缺失 |
| 加载期文件校验 | ✅ `_external_sound_file_exists` | ❌ 缺失 |
| 外部覆盖内置占位 | ✅ 已实现 | ❌ 缺失 |
| 新素材注册 | ✅ `register_new_effect` | ❌ 缺失 |

### 修复方案

为 `MusicComposer` 新增 `_load_external_music_library()` 方法，与 `SoundEffectDesigner` 的对等能力保持一致：
1. 从 `music_index.json` 加载条目到 `music_library`。
2. 加载期校验 `file_path` 是否可解析到本地文件。
3. 外部真实素材可覆盖内置不可解析的占位条目。
4. 按 `bucket` 字段组织条目，便于音乐池缓存预加载。

### 完成记录（2026-05-05）

- `MusicComposer` 新增 `_load_external_music_library()` 方法。
- 加载期校验 `file_path`：绝对路径要求文件存在，相对路径按 `music_index.json` 所在目录解析；默认索引路径下等价于 `AUDIO_LIBRARY_DIR / file_path`。
- 外部条目与内置库同名时，若内置条目文件不可解析，允许外部真实素材覆盖。
- 新增测试覆盖：外部索引加载、缺失文件跳过、覆盖不可解析内置占位、自定义索引目录解析相对路径。

---

## V3-17：音乐池缓存不利用已有索引

### 问题

`MusicComposer._music_pool_cache` 是纯内存字典，重启后丢失。而 `music_index.json` 中已有按 `bucket` 和 `variant` 组织的 AI 生成素材，完全可以在初始化时预加载到池缓存中。

当前行为：
1. 引擎启动 → `_music_pool_cache = {}`（空）
2. 首次请求 `underscore:tense` 池 → 调用 Mureka API 生成 5 个变体
3. 即使 `music_index.json` 中已有 5 个 `underscore:tense` 条目，仍会重复生成

### 修复方案

在 `_load_external_music_library()` 加载索引后，按 `bucket` 字段将已有条目分组填入 `_music_pool_cache`。

### 完成记录（2026-05-05）

- `_load_external_music_library()` 加载索引后，按 `bucket` 字段将可解析的条目分组填入 `_music_pool_cache`。
- `_ensure_music_pool()` 在调用 API 前先检查池缓存；已有同 bucket/mood/duration 且变体数量不少于请求数量时，截取前 `pool_size` 个复用并跳过 API 调用。
- 新增测试覆盖：预加载池缓存、池缓存命中时跳过 API 调用。

---

## V3-18：`_match_music` 只返回首个匹配缺乏变化

### 问题

`_match_music(mood)` 遍历 `music_library` 字典，返回第一个 mood 匹配的条目。由于 Python 3.7+ 字典保持插入顺序，同一 mood 永远返回同一首音乐。

对于有声书这种长内容场景，连续多个紧张场景使用完全相同的背景音乐，听感单调。

### 修复方案

改为基于 seed 的稳定随机选取：调用方传入项目、章节、场景、起点和 mood 等上下文，`_match_music()` 从匹配列表中选取一首。同一上下文重复生成保持稳定，不同章节或不同场景可得到变化。

### 完成记录（2026-05-05）

- `_match_music()` 改为收集所有 mood 匹配条目后，使用 `_stable_choice_index(seed or mood, len(matches))` 选取。
- 静态库降级的场景配乐 seed 已包含 `audiobook_project_id`、`chapter_id`、`scene_id`、`start_time` 和 mood，避免跨章节同 `scene_id` 固定命中同一首。
- AI 音乐池选曲 seed 已包含项目、章节、场景、起点、mood 和 bucket。
- 新增测试覆盖：多匹配时基于 seed 稳定选取、静态库降级 seed 包含项目与章节上下文。

---

## V3-19：生成素材入库无质量门控，低质素材无法区分与删除

### 问题

AI 生成的音乐和音效素材在入库时完全没有质量评估：

1. **`SoundEffectDesigner.register_new_effect()`**：直接写入索引，不检查素材质量。
2. **`MurekaO1Client._update_music_index()`**：同样直接写入，不检查素材质量。
3. 索引条目中**没有质量元数据**（无 `quality_score`、`quality_grade`、`quality_status`）。
4. **没有库素材清理方法**——无法删除低质或孤立条目。
5. `AudioMixer.analyze_quality()` 可以评估音频质量，但从未用于库素材。

### 影响

- 低质素材（静音、响度异常、损坏或异常超长）混入库中，后续匹配到时混音阶段跳过或产出劣质音频。
- 索引膨胀：大量不可用条目占据索引空间，加载时增加校验开销。
- 无法自动清理：只能手动编辑 JSON 索引和删除磁盘文件。

### 修复方案

**1. 注册时自动评估质量**

为 `SoundEffectDesigner` 和 `MurekaO1Client` 各新增 `_assess_audio_quality(file_path)` 方法：
- 使用 pydub 检测关键指标：可解码性、真实时长、响度（dBFS）、静音比例。
- 音效的短时长不作为低质量依据；点击、脚步、开关、翻页、武器碰撞等点状音效天然很短，只能因静音、响度异常、损坏等真实质量问题被降级。

### 2026-05-11 补充落地记录

- 已按“短音效不因时长短降级”规则重评历史音效质量，索引与数据库同步后音效库质量状态为：`accepted=768`、`tolerated=1`、无质量状态 `8`。
- 已继续导入本地已授权 CC0 manifest 剩余项：6 条候选中 2 条地铁脚步音效通过质量门禁并入库，4 条环境音因音频质量门禁拒绝，未进入索引。
- 已从 Wikimedia Commons 小批量发现并筛选 CC0/Public Domain 音频候选，排除音乐、播客、访谈朗读、超大长录音和明显不适合作为音效的条目。
- 新增下载批次：
  - 候选清单：`backend/data/audio_library/sfx_candidates_wikimedia_cc0_pd_continued_20260511.json`
  - 本地授权文件目录：`backend/data/audio_library/approved_sfx/wikimedia_cc0_pd_continued_20260511/`
  - 入库 manifest：`backend/data/audio_library/sfx_import_manifest_wikimedia_cc0_pd_continued_20260511.jsonl`
- 该 Wikimedia 批次 41 条候选中 39 条通过质量门禁并入库，2 条被拒绝；入库分布：`action=6`、`environment=13`、`emotion=8`、`transition=12`。
- 已用 ffprobe 回填该批次 39 条真实 `duration` 与 `duration_bucket`，并同步 `audio_library_assets` 数据库。
- 当前音效库总量：`818`，质量状态：`accepted=809`、`tolerated=1`、无质量状态 `8`；分类分布：`action=416`、`environment=163`、`emotion=128`、`transition=111`。
- 2026-05-11 追加补库：
  - Wikimedia Commons 第二批候选已生成：`backend/data/audio_library/sfx_candidates_wikimedia_cc0_pd_continued2_20260511.json`，但当前本机到 `upload.wikimedia.org` / `commons.wikimedia.org` 连续 TLS timeout；未伪造下载，候选保留待网络恢复后继续审核/下载。
  - 已修复本地授权素材导入的两个问题：低响度但可用的环境/点状音效会在复制到素材库目标文件后尝试响度规范化，原始授权文件不改；manifest 中的 `source_payload_json` 会保留进索引和数据库，便于按 zip 包内成员审计来源。
  - 已重新评估并补入 4 条此前因低响度被拒的已授权素材：森林环境、夜虫环境、呼吸、闹钟滴答；全部上传到 `aliyun_oss`，并回填真实 `duration`。
  - 已从本地已下载且许可已核验为 CC0 的 Kenney / OpenGameArt 素材包筛选 85 条有声小说常用音效，生成 `backend/data/audio_library/sfx_import_manifest_cc0_story_sfx_expansion_20260511.jsonl`，本地文件目录为 `backend/data/audio_library/approved_sfx/cc0_story_sfx_expansion_20260511/`。
  - 85 条新素材全部通过 dry-run、质量门禁、云端上传和数据库同步；入库分类：`action/realistic=35`、`action/intense=8`、`environment/peaceful=7`、`emotion/horror=7`、`environment/realistic=7`、`environment/scifi=5`、`transition/fantasy=4`、`transition/intense=4`、`transition/scifi=4`、`action/scifi=2`、`action/horror=1`、`environment/intense=1`。
  - 85 条新素材的 `duration_bucket`：`short=69`、`medium=15`、`long=1`；短素材保留为有效音效，不因时长短降级。
  - 当前音效库总量：`907`；JSON 索引与 `audio_library_assets` 数据库一致；全部 `storage_mode=durable_cloud`、`storage_driver=aliyun_oss`。质量状态：`accepted=898`、`tolerated=1`、无质量状态 `8`。
  - 云端抽样 HEAD 验证通过：新入库前 5 条素材在 OSS 均返回 `200`，`content_type=audio/wav`。
  - 回归验证：`python -m pytest "backend/tests/test_sfx_library_downloader.py::test_filter_results_keeps_short_effects_by_default" "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_registers_quality_checked_file" "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_attaches_cloud_metadata_for_shared_library" "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_normalizes_quiet_licensed_file_before_quality_check" "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_preserves_manifest_source_payload" "backend/tests/test_audio_fx_optimizations.py::test_sound_effect_quality_does_not_penalize_valid_short_effects" -q`：6 passed。
- 评分 0~100，映射为等级 A/B/C/D 和状态 accepted/tolerated/rejected。
- 注册时将 `quality_score`、`quality_grade`、`quality_status` 写入索引条目。
- 使用 `setdefault` 避免覆盖调用方已提供的质量元数据。

**2. 低质素材清理方法**

为 `SoundEffectDesigner` 和 `MusicComposer` 各新增：
- `purge_low_quality_assets(min_score=40.0, dry_run=False)`：删除已有明确质量结论且 `quality_status=rejected` 或 `quality_score < min_score` 的条目；缺失质量元数据的历史条目不按 0 分处理，需先回填或人工评估。
- `purge_orphan_entries(dry_run=False)`：清理文件已不存在的孤立索引条目。
- `dry_run=True` 时仅统计不实际删除，便于预览。
- 磁盘文件删除只允许发生在当前索引所在素材库目录内；索引中若存在素材库外部绝对路径，只移除索引记录，不删除外部文件。

**3. 质量评估阈值**

| 指标 | 扣分 | 说明 |
|------|------|------|
| 音乐时长 < 3.0s | -40 | 过短音乐不可用 |
| 音乐时长 < 10.0s | -10 | 短音乐可用但需注意 |
| dBFS < -40 | -30 | 极低响度，几乎静音 |
| dBFS < -30 | -15 | 响度偏低 |
| 静音比例 > 80% | -40 | 几乎全静音 |
| 静音比例 > 50% | -20 | 静音占比过高 |

| 分数 | 等级 | 状态 | 说明 |
|------|------|------|------|
| ≥75 | B | accepted | 良好 |
| ≥60 | C | accepted | 可用 |
| ≥40 | C | tolerated | 勉强可用，建议替换 |
| <40 | D | rejected | 不可用 |

### 完成记录（2026-05-05）

- `SoundEffectDesigner` 新增 `_assess_audio_quality()` 方法，`register_new_effect()` 注册时自动写入质量元数据。
- `MurekaO1Client` 新增 `_assess_audio_quality()` 方法，`_update_music_index()` 写入时自动写入质量元数据。
- `SoundEffectDesigner` 新增 `purge_low_quality_assets()` 和 `purge_orphan_entries()` 方法。
- `MusicComposer` 新增 `purge_low_quality_assets()` 和 `purge_orphan_entries()` 方法。
- 清理逻辑已补安全边界：只删除素材库目录内文件；素材库外部绝对路径只从索引移除，不触碰磁盘文件。
- 低质清理已补历史兼容边界：缺失 `quality_score`/`quality_status` 的存量条目不会被当作 0 分误删。
- 当前真实存量索引状态：`music_index.json` 19 条、`sound_effects_index.json` 8 条均为可解析相对路径，但仍缺少质量元数据；质量字段会在后续新入库时写入，存量质量回填需单独任务。
- 新增测试覆盖：质量评估、低质清理、孤立清理、dry_run 预演、素材库外部绝对路径保护、无质量元数据历史条目保护。

---

## V3-20：段落转化 JSON 解析失败后整批 fallback 导致质量降级

### 问题

生产日志显示，段落转化阶段 1183 字输入返回 10659 字符 JSON，但响应中出现重复字段块和残缺字段，最终 `parse_llm_json_array()` 报错：

```text
LLM返回的JSON格式错误: Expecting ',' delimiter
```

旧行为会把整个批次直接降级为原文 fallback，再由长片段拆分逻辑切成多个旁白片段。流程不中断，但第一批 LLM 生成的音效、配乐、情绪、角色指令等精品标注全部丢失。

### 根因

1. 单个批次对当前重字段 JSON schema 来说偏大，模型输出容易膨胀并污染结构。
2. 解析失败后的恢复策略过粗，只能整批 fallback。
3. 日志中的“JSON截断检测 OK”仅基于响应长度阈值，不能证明模型没有被 token 或结构问题截断。
4. 错误日志只打印前 1000 字，无法定位 `char 7008` 这类中段错误位置。

### 修复方案

- 将段落转化批次目标从 1200 字下调到 850 字，硬上限从 1600 字下调到 1200 字，降低单次输出复杂度。
- 新增 `_split_paragraph_for_parse_retry()`：JSON 解析失败后优先按原始换行拆分，多行 batch 可逐段重试；单行长文本再按句子和硬上限拆分。
- `_transform_paragraph()` 增加 `allow_parse_retry` 参数，避免拆小重试时无限递归。
- 解析失败时记录 `json_len`、`error_char` 和错误位置前后上下文，替换误导性的“截断检测 OK”为“长度阈值检查”。
- 提示词字段合约增加约束：
  - 每个 key 只能出现一次。
  - 每段 `sound_effects` 最多 2 个。
  - `music_cue` 只在开场、转场、高潮、强情绪片段出现。
  - 精品字段与 simple 字段不得重复表达同一个听觉事件。

### 完成记录（2026-05-05）

- `TransformMixin._transform_paragraph()` 已在 `LLMJsonParseError` 后自动拆小重试，成功结果会合并返回，避免整批 fallback。
- 新增 `_format_json_error_context()` 输出解析错误位置上下文，便于定位模型输出污染点。
- 新增测试覆盖：首次返回坏 JSON 后，按更小 chunk 重试并保留两个有效片段。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_segment_validation.py" -q`：21 passed。
  - `python -m pytest "backend/tests/test_audiobook_llm_runtime.py" -q -k "json"`：5 passed。

---

## V3-21：角色对白被旁白吞并，旁白演绎情绪偏平

### 问题

生成结果中出现两个明显质量问题：

1. **说话人归属不足**：角色台词没有被拆成 `dialogue`，所有片段都落到 `speaker=旁白`，后续音色分配无法区分角色。
2. **旁白情绪偏平**：紧张、诡异、压迫类场景仍大量使用 `neutral`，`performance_notes` 不够具体，TTS 只能按平直旁白处理。

### 根因

1. 段落转化 prompt 只要求 `speaker` 填“角色名或旁白”，但没有强制“直接引语必须拆成 dialogue”。
2. 原规则允许“动作/心理 + 台词”合并，容易诱导模型把角色台词合并进 narration。
3. 校验层对 `dialogue + speaker=旁白` 的处理过于保守，只会降级为 narration；即使 `original_text` 中有明确“角色名 + 说/道/问/喊 + 引号台词”，也不会恢复说话人。
4. 旁白情绪推断关键词不足，缺少对“裂隙、浊气、鬼爪、诡异、未知势力”等悬疑/压迫意象的识别；缺少默认的旁白演绎提示补强。

### 修复方案

- **Prompt 约束增强**
  - 明确要求中文引号、日式引号、`角色说/道/问/喊/低声` 后的台词必须拆成 `dialogue`。
  - `dialogue.speaker` 必须是真实角色名，禁止使用旁白。
  - `narration.speaker` 必须为旁白，且 `text` 不得包含角色引号台词。
  - 删除“可把动作/心理 + 台词合成一个单位”的宽松表达，改为“旁白动作/心理 + dialogue 台词”拆分。

- **校验层防线**
  - 新增基于 `original_text` 的明确引语纠偏：仅当原文存在“清晰角色名 + 说话动词 + 引号台词”，且 `text` 与引号内台词匹配时，才把旁白片段恢复为 `dialogue` 并填入角色名。
  - 不根据“他/她/有人/男人/女人”等模糊主体强行猜说话人，避免误判。
  - 从明确归因语中读取 `低声/怒吼/喊/哽咽` 等表演提示，用于补足对白 emotion。

- **旁白情绪增强**
  - 扩展文本情绪关键词，识别 `mysterious` 场景。
  - 当旁白仍为 `neutral/calm` 且文本含强意象时，自动补成更准确的 emotion。
  - 根据 emotion 补默认 `instruct_emotion`，例如 `mysterious/tense/fearful -> fearful`。
  - 对缺失或泛化的 `performance_notes` 补可执行旁白演绎要求：语速、声线、重读、停顿目标。

### 完成记录（2026-05-05）

- `TransformMixin._transform_paragraph()` prompt 已新增对白归属和旁白情绪层次硬性要求。
- `_segment_validation.py` 已新增明确引语说话人恢复、对白归因情绪推断、旁白情绪和表演提示补强。
- 新增测试覆盖：
  - 明确原文 `陆衍低声道：“别碰我。”` 被错误标成旁白时，可恢复为 `dialogue/speaker=陆衍/emotion=whisper`。
  - 含“黑色裂隙、浊气”等压迫意象的旁白，可自动补 `mysterious/fearful` 和具体 `performance_notes`。
  - transform prompt 必须包含“直接引语必须拆成 dialogue”“不要把角色台词归到旁白”“旁白也必须有情绪层次”等约束。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_segment_validation.py" -q`：24 passed。
  - `python -m pytest "backend/tests/test_audiobook_segment_validation.py" "backend/tests/test_audiobook_llm_runtime.py" -q`：52 passed。

### 未覆盖风险

- 当前校验层只纠正“明确角色名 + 说话动词 + 引号台词”的高置信场景；对“他说/她问”这类代词归因不做恢复，需要依赖 LLM prompt 和上下文连续性。
- 如果原文无引号且只有口语化直接句，仍可能被保守地保留为旁白；这类场景后续可交给 LLM script review 或更完整的上下文解析处理。

---

## V3-22：公开音效资源合规导入与索引标准化

### 问题

项目音效库（`sound_effects_index.json`）当前仅有少量内置和 AI 生成的音效素材。确实需要补充真实世界音效，但旧方案把“公开平台素材允许商用”和“可以通过平台 API 系统性下载并纳入本地素材库”混为一谈，存在合规风险：

1. 音效种类和数量不足，难以覆盖环境音、动作音、情绪音、转场音等全场景需求。
2. 只筛选素材许可证不够，还必须核验平台 API 条款、批量下载限制、署名义务和再分发限制。
3. 手动下载或自动下载若缺少审计元数据，后续无法证明素材来源、许可状态和署名义务。
4. 下载的音效若缺少标准化分类、命名、质量评估和索引字段，检索效率低且容易混入不可用素材。

### 修订结论

本项不再表述为“从多个公开素材库系统性下载”。修订为：

- **合规导入**：只从条款允许、授权明确、可保留来源证据的公开素材源中导入素材。
- **非镜像式策略**：禁止 mass download、站点镜像、规避频率限制或把第三方素材库复制成本地公开素材库。
- **默认 dry-run**：自动流程默认只生成候选清单；真正下载前必须确认来源准入和许可义务。
- **只用于混音输出**：外部素材作为内部混音素材，不向用户开放原始素材下载，不作为独立素材包出售或分发。
- **许可审计优先于数量**：宁可先引入少量 CC0 / 已授权素材，也不要追求来源数量。

### 来源准入矩阵

| 来源 | 建议级别 | 使用边界 | 原因 |
|------|----------|----------|------|
| 自有录制 / 自有生成 / 已购买商用素材包 | P0 | 优先入库 | 权利链最清晰，可直接建立内部素材库 |
| CC0 素材源 | P0 | 可自动导入，但仍需记录来源、下载时间、hash | 无署名义务，合规成本最低 |
| Openverse | P1 | 优先作为 CC/公共领域候选发现入口，不直接假设可下载；导入前核验原始来源页和许可 | 可聚合发现 CC 素材，但真实权利仍以源站为准 |
| Wikimedia Commons | P1 | 可作为候选源；导入前必须读取 license、artist、source page、attribution | 元数据较完整，但许可类型复杂 |
| Freesound | P1（需授权） | 仅在确认 API 商业使用权限后启用自动下载；否则只做人工候选清单或用户自带授权导入 | 素材许可与 API 商业使用条款是两层约束；CC-BY 还需要署名 |
| Pixabay | P2（需验证） | 不把 `pageURL` 当音频下载地址；确认官方音频 API/下载 URL 后再接入；素材不得作为原始文件再分发 | 许可允许范围较宽，但 API 和独立再分发限制需核验 |
| Mixkit | P2（人工导入优先） | 适合人工精选导入；自动化前需确认条款是否允许批量下载和本地库化 | 免费商用素材较友好，但未必适合自动抓取 |
| ZapSplat | P2（人工导入优先） | 需区分账号级许可、署名义务和下载限制；不建议直接自动抓取 | 商用和署名规则依账号/订阅变化 |
| OpenGameArt | P3 | 仅人工导入明确 CC0/CC-BY 的音效；排除 GPL/OGA-BY/不清晰许可 | 平台许可混杂，游戏素材许可不一定适合有声书再利用 |
| Internet Archive | P3 | 只做人工候选；逐条核验 rights/license | 元数据质量不稳定，自动判断风险高 |
| BBC Sound Effects | 排除 | 默认不导入 | 常见条款偏个人、教育、研究用途；商业使用需单独授权 |

### 许可策略

- `CC0` / Public Domain：优先自动导入，仍记录来源和 hash。
- `CC-BY`：允许导入，但必须记录作者、来源页、license URL，并生成 `attribution_text`，用于项目 credits。
- `CC-BY-SA`：默认不自动导入。只有在明确项目能承担 ShareAlike 义务并能正确传播许可信息时，才可通过白名单启用。
- `CC-BY-NC`、`Sampling+`、未知许可、缺失许可：一律拒绝。
- 平台自定义免费许可：逐平台建立 adapter 策略，不允许用“license_commercial=True”泛化处理。
- 所有来源必须记录 `retrieved_at` 和 `license_checked_at`；后续条款变化不回溯改变历史记录，但新导入必须按当前条款重新核验。

### 标准化索引字段

外部音效入库时，`sound_effects_index.json` 至少需要以下字段：

- `id`：稳定 ID，建议 `{category}_{source}_{source_id}_{hash10}`。
- `name`：清洗后的展示名。
- `file_path`：素材库内相对路径。
- `category`：稳定目录维度，如 `environment/realistic`。
- `style`：风格标签。
- `duration`：真实音频探测时长，不只使用 API 元数据。
- `duration_bucket`：`short`（≤3s）、`medium`（3-10s）、`long`（>10s）。
- `scenes`：适用场景数组。
- `tags`：平台标签与本地补充标签。
- `source` / `source_id` / `source_url`：来源证据。
- `author` / `author_url`：作者信息，无法取得时不得导入 CC-BY 素材。
- `license` / `license_url` / `license_version`。
- `license_commercial`：是否允许商用。
- `attribution_required` / `attribution_text`。
- `redistribution_allowed`：是否允许原始素材再分发；默认 `false`。
- `raw_asset_exposure`：默认 `internal_only`。
- `retrieved_at` / `license_checked_at`。
- `sha256` / `file_size` / `content_type`。
- `quality_score` / `quality_grade` / `quality_status`：复用 V3-19 的质量评估逻辑。

### 分类与目录规则

- 目录只承载稳定维度：`sound_effects/{category}/{style}/{effect_id}.{ext}`。
- 时长、场景、许可、质量、作者、来源等作为索引字段，不进入路径。
- 检索必须基于索引字段，不依赖路径字符串解析全部语义。
- 命名不再使用 6 位短 hash，建议至少使用 10 位 hash，并保留 `source_id` 的安全化片段降低碰撞风险。

### AI 生成音效自动入库规则

- 用户调用 Vidu / Mureka 等音效生成链路成功生成素材后，必须走统一注册入口，写入本地索引、共享数据库索引，并在质量通过时尝试写入云端对象存储元数据。
- 生成音效的 `category` 统一为 `category/style` 形式，顶层分类只允许：
  - `environment`：环境床、自然/城市氛围、空间底噪。
  - `action`：门、脚步、碰撞、翻页、铃声、武器、爆炸等短触发音。
  - `emotion`：心跳、呼吸、低鸣、耳鸣、尖啸、心理压迫等情绪氛围短效。
  - `transition`：转场、闪回、法术切换、提示性过渡音。
- `style` 只承载用户听感风格，当前标准值为 `realistic`、`cinematic`、`fantasy`、`scifi`、`horror`、`peaceful`、`intense`。
- `scenes` 用于用户筛选使用场景，当前标准维度为 `indoor`、`outdoor`、`battle`、`travel`、`mystery`、`romance`、`horror`、`general`，可附加具体 `scene_id` 作为上下文标签。
- 普通动作 Foley 默认 `action/realistic`，只有描述明确包含战斗、爆炸、奇幻、恐怖、转场等语义时才切换为 `intense`、`fantasy`、`horror` 或 `cinematic`。
- 旧索引中的 `effects/action` 等历史分类必须在查询层兼容归一为 `action/realistic`，缺少 `scenes` 的历史条目可按名称、描述、标签和路径做保守推断。

### 实现修复要求

当前 `backend/app/services/audiobook/sfx_library_downloader.py` 只能视为原型，后续必须修复后才能启用真实下载：

1. `PixabayAdapter` 不得把 `pageURL` 当音频文件下载地址；在确认官方音频 API 和真实下载 URL 前，默认禁用自动下载。
2. `FreesoundAdapter` 需要区分预览文件和原始下载；原始下载需按官方 OAuth2 下载端点实现，并增加商业 API 授权开关，默认关闭。
3. 搜索结果必须拉取作者、来源页、license URL 等审计字段；字段不完整时不得自动入库。
4. 下载后必须验证 `Content-Type`、文件大小、可解码音频时长和 `sha256`，拒绝 HTML 页面、空文件、静音/损坏音频；音效不得仅因时长短被拒绝，但仍可按 `max_duration` 拦截异常超长素材。
5. 入库必须复用 V3-19 的质量评估逻辑，禁止绕过质量门控直接写索引。
6. `dry_run=True` 只生成候选清单，不写索引、不创建文件。
7. 生成 `license_manifest.jsonl` 或等价导出，用于后续有声书项目 credits。
8. 对 CC-BY 素材，最终导出有声书项目时需要能汇总 attribution。

### 平台扩展建议

不要为了“多个平台”而扩展来源。推荐顺序：

1. **先做自有/已购买/CC0 素材导入器**：支持本地目录扫描、manifest 校验、质量评估和索引注册。
2. **再做 Openverse/Wikimedia 候选发现**：只建立候选清单和许可审计，不直接批量下载。
3. **Freesound 仅在 API 商业授权明确后启用自动下载**；否则作为人工候选来源。
4. **Pixabay、Mixkit、ZapSplat 作为人工精选来源**，等确认下载 API 和条款后再做 adapter。
5. **BBC Sound Effects 默认排除**，除非取得商业授权。

### 完成记录（2026-05-06 第一阶段）

- 文档已将本项从“系统性下载已完成”收紧为“合规导入方案已修订，代码需复核”。
- 新增来源准入矩阵、许可策略、索引字段要求、目录命名规则和后续实现修复要求。
- 不再建议把 Freesound/Pixabay 直接作为可用自动下载能力。
- `SfxLibraryDownloader` 已改为合规导入器语义，不再描述为公开素材库镜像式下载器。
- 默认来源从 `["freesound", "pixabay"]` 收紧为 `["freesound"]`；Pixabay 自动搜索/下载默认禁用，确认官方音频 API 前不返回候选。
- Freesound 增加 `allow_freesound_commercial_api` 授权开关；未确认商业 API 授权时，搜索和真实下载都会拒绝，`dry_run` 仍可生成候选记录。
- Freesound 搜索不再把 preview URL 当作真实下载 URL，只保留 `preview_url`；原始下载仍需后续按 OAuth2 下载端点实现。
- `SfxSearchResult` 和索引记录新增来源与许可审计字段：`source_url`、`author`、`author_url`、`license_url`、`attribution_required`、`attribution_text`、`retrieved_at`、`license_checked_at`、`redistribution_allowed=false`、`raw_asset_exposure=internal_only`。
- `generate_effect_id()` 从 6 位 hash 改为包含安全化 `source_id` 和 10 位 SHA256 hash，降低碰撞风险。
- 下载后新增文件校验：拒绝 HTML/XML/空文件/不可识别音频，记录 `sha256`、`file_size`、`content_type`。
- 入库前复用 `SoundEffectDesigner._assess_audio_quality()` 写入 `quality_score`、`quality_grade`、`quality_status`，拒绝低质下载文件直接入库。
- `dry_run=True` 只返回候选记录，不创建文件、不写索引。
- 新增/更新测试覆盖：许可审计字段、CC-BY 缺署名拒绝、Pixabay 禁用、Freesound 授权开关、HTML 下载拒绝、质量门控复用、ID 命名规则。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：33 passed。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" -q`：89 passed。

### 完成记录（2026-05-06 第二阶段）

- 已落地本地已授权素材导入器 `SfxLibraryDownloader.import_local_assets(source_dir, manifest_path, dry_run=False, overwrite=False)`。
- 支持 `license_manifest.jsonl`、JSON 数组、JSON 对象 `{ "assets": [...] }` 三种 manifest 格式；导入项通过 `file` / `path` 指向本地素材文件。
- 本地导入来源统一写为 `source=local_authorized`，继续使用标准目录 `sound_effects/{category}/{style}/{effect_id}.{ext}` 和标准索引字段。
- manifest 许可校验更严格：必须具备 `license`、`license_url`、`source_url`，且 `license_commercial` 必须明确为真或可由许可名判定为商用；`CC-BY` 等需要署名的素材还必须具备 `author` 或 `attribution_text`。
- `license_commercial` / `attribution_required` 支持布尔值和字符串布尔值解析，避免 `"false"` 被 Python truthy 规则误判为可商用。
- `dry_run=True` 只生成候选记录，不复制文件、不写索引。
- 非 dry-run 导入会复制本地素材到标准音效库目录，复用 `_inspect_downloaded_file()` 和 `SoundEffectDesigner._assess_audio_quality()` 写入 `sha256`、`file_size`、`content_type`、`quality_score`、`quality_grade`、`quality_status`。
- 质量拒绝的新复制文件会被清理，不留下未入库孤立素材；已有目标文件未启用 `overwrite` 时不会被误删。
- 新增测试覆盖：本地 manifest dry-run、不完整许可拒绝、CC0 缺来源页拒绝、字符串 `"false"` 商用标记拒绝、成功导入写索引、低质素材拒绝并清理目标文件。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：39 passed。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" -q`：95 passed。

### 完成记录（2026-05-06 第三阶段）

- 已落地 `SfxLibraryDownloader.discover_public_candidates()`，用于从公开来源生成音效候选 JSONL 清单。
- 新增 `SfxCandidate` 候选记录结构，字段包含 `source`、`source_id`、`source_url`、`file_url`、`license`、`license_url`、`author`、`author_url`、`duration`、`mime_type`、`query`、`discovered_at`、`license_checked_at`、`requires_manual_review=true`、`status=candidate_only`。
- 新增 `OpenverseCandidateAdapter`：使用 Openverse audio search 生成候选；只保留可商用候选，过滤 `NC`、`Sampling+`、`BY-SA` 等当前策略不自动导入的许可；不输出 `download_url`。
- 新增 `WikimediaCandidateAdapter`：使用 Wikimedia Commons `imageinfo.extmetadata` 读取 `LicenseShortName`、`LicenseUrl`、`Artist`、`ObjectName`、`AttributionRequired` 等候选审计字段；仅写候选清单。
- 候选发现输出默认写入 `sfx_candidates.jsonl`，或由调用方传入 `output_path`；不会写 `sound_effects_index.json`，不会下载文件，不会创建音效库素材文件。
- 候选记录保留 `file_url` 仅用于人工复核和后续 manifest 准备，不作为自动下载入口。
- 新增测试覆盖：Openverse 候选字段映射和 NC 过滤、Wikimedia extmetadata 映射、候选 JSONL 导出不写索引/不下载。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：42 passed。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" -q`：98 passed。

### 完成记录（2026-05-06 第四阶段）

- 已落地 `SfxLibraryDownloader.export_attribution_credits()`，从 `sound_effects_index.json` 汇总需要署名的音效素材。
- 输出 `license_manifest.jsonl` 和 `CREDITS.md` 两种文件；默认输出到音效索引同级目录，也可由调用方传入 `jsonl_path` / `markdown_path`。
- 只汇总 `attribution_required=true` 或按许可名判断需要署名的素材；`CC0` / Public Domain / 内部素材不进入 credits。
- 支持传入 `used_effect_ids`，项目导出会优先按实际混音使用过的音效 ID 汇总；未传入或旧数据无使用记录时汇总整个索引中的需署名素材作为保守回退。
- 以 `attribution_text + source_url + license_url` 去重，避免同一素材多个索引条目重复出现在 credits 中。
- 若索引条目缺少 `attribution_text`，但具备 `name`、`author`、`source_url`、`license`、`license_url`，会生成标准署名文本；字段不足时跳过该条，避免输出不可审计 credits。
- credits 记录保留 `raw_asset_exposure=internal_only` 和 `redistribution_allowed=false`，继续明确不开放原始素材再分发。
- 新增测试覆盖：JSONL/Markdown credits 输出、CC0 跳过、按 `used_effect_ids` 过滤、重复署名去重。
- 验证通过：
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：44 passed。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" -q`：100 passed。

### 完成记录（2026-05-06 第五阶段）

- 已将库级 credits 导出接入项目导出链路。
- `build_project_m4b_export()` 生成 M4B 后会写相邻 sidecar 文件：
  - `{output}.CREDITS.md`
  - `{output}.license_manifest.jsonl`
- `build_project_audacity_export()` 生成 Audacity ZIP 时会写相邻 sidecar 文件，并把 `CREDITS.md`、`license_manifest.jsonl` 打入 ZIP 根目录。
- `_load_cached_project_export_result()` 命中缓存返回前会刷新 sidecar credits，避免缓存导出结果缺少最新合规文件。
- `collect_project_export_output_files()` 已纳入 M4B / Audacity 的 credits sidecar，删除项目导出产物时会一起清理。
- 项目导出结果和 manifest 中新增 `credits` 字段，记录 `stats`、`jsonl_path`、`markdown_path`。
- 第五阶段先以全库汇总作为保守回退；第六阶段已从混音时间线提取 `used_effect_ids` 并收窄项目导出 credits，见下方第六阶段记录。
- 新增/更新测试覆盖：导出清理列表包含 credits sidecar、项目导出 credits helper 委托音效库导出器、M4B sidecar 生成、Audacity ZIP 内含 credits 文件。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_project_exporter.py" -q`：19 passed。
  - `python -m pytest "backend/tests/test_audiobook_project_exporter.py" "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" -q`：119 passed。

### 完成记录（2026-05-06 第六阶段）

- `SoundEffectCue` 新增 `effect_id` 字段，用于记录本次混音实际命中的音效库 ID。
- `_match_effect()` 在精确 ID 命中时记录该 ID，在描述/标签命中时记录最佳匹配条目的 `name`；Vidu / Mureka 生成并入库的素材返回 cue 时记录生成的 `effect_id`。
- `export_effect_timeline()` 输出每个 timeline item 的 `effect_id`，使后续 checkpoint 和导出 credits 能追溯实际使用素材。
- `_audio_from_script_mixin.py` 和 `_generation_mixin.py` 在生成结果顶层写入 `effect_timeline`，仅在 timeline 非空时输出，保持旧结果结构兼容。
- `build_checkpoint_patch_from_generation_result()` 会把合法的 `effect_timeline.timeline` 持久化进 `ChapterAudioRun.checkpoint_json`。
- `project_exporter._collect_project_used_effect_ids()` 会按项目读取每个已导出章节最新的 `completed` run checkpoint，收集实际使用的 `effect_id`。
- `build_project_m4b_export()` 和 `build_project_audacity_export()` 刷新 sidecar credits 时会传入实际 `used_effect_ids`；如果旧章节缺少 timeline 或未收集到任何 ID，则继续回退到全库署名，避免漏署名。
- 新增/更新测试覆盖：timeline 输出 `effect_id`、checkpoint patch 持久化 `effect_timeline`、项目导出从 checkpoint 收集 used IDs、缓存 M4B 导出刷新 credits 时传入 used IDs。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py::test_export_effect_timeline_includes_matched_effect_id" -q`：1 passed。
  - `python -m pytest "backend/tests/test_temp_segment_store.py::test_build_checkpoint_patch_from_generation_result_includes_effect_timeline" -q`：1 passed。
  - `python -m pytest "backend/tests/test_audiobook_project_exporter.py::test_project_export_collects_used_effect_ids_from_checkpoints" "backend/tests/test_audiobook_project_exporter.py::test_cached_m4b_export_uses_checkpoint_effect_ids_for_credits" -q`：2 passed。
  - `python -m pytest "backend/tests/test_audio_fx_optimizations.py" "backend/tests/test_temp_segment_store.py" "backend/tests/test_audiobook_project_exporter.py" -q`：115 passed。
  - `python -m pytest "backend/tests/test_audiobook_project_exporter.py" "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" "backend/tests/test_temp_segment_store.py" -q`：159 passed。
  - `python -m compileall "backend/app/services/audiobook/agents/sound_effect_designer.py" "backend/app/services/audiobook/background_jobs_shared.py" "backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py" "backend/app/services/audiobook/engine_pkg/_generation_mixin.py" "backend/app/services/audiobook/project_exporter.py"`：通过。

### 未覆盖风险

- 当前已落地远端合规防线、本地已授权素材 manifest 导入、Openverse/Wikimedia 候选发现、元数据/文件/质量门控。
- Openverse/Wikimedia 候选发现仅用于人工筛选；候选 `file_url` 不能直接作为自动下载依据，正式入库仍必须走本地 manifest 导入并重新校验来源页、许可和质量。
- Freesound 原始文件下载仍未实现 OAuth2 下载端点；未确认商业 API 授权前只能 dry-run 或人工导入。
- Pixabay/Mixkit/ZapSplat 仍只建议人工精选；未验证官方音频下载 API 和条款前不做自动 adapter。
- 旧项目、旧章节、手工导入音频或无 `effect_timeline` 的 run 无法收集实际 `effect_id`，项目导出会回退到全库署名；这可能过度署名，但不会漏署名。
- 当前仅从每个导出章节最新的 `completed` run checkpoint 收集 `effect_id`；如果未来支持更复杂的手工混音或多轨编辑，需要同步记录项目级素材使用清单。
- 平台条款会变化；每个新 adapter 启用前必须重新核验官方条款。
- 公开素材可能包含第三方权利风险，例如人声、品牌、影视采样、隐私或表演权问题；自动化只能降低许可风险，不能完全消除权利链风险。

---

## V3-23：分段重生前端入口隐藏过深，重生后无刷新

### 问题

后端已实现片段重新生成 API（`POST /projects/{id}/chapters/{cid}/segments/{idx}/regenerate`）和片段审查 API，前端也封装了 `apiClient.regenerateSegment()` 和 `useAudiobookSegmentReviewActions` hook。但当前存在以下体验问题：

1. **入口隐蔽**：[ScriptSegmentActions.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/ScriptSegmentActions.tsx) 中"重新生成"按钮和评分组件仅在 `reviewMode === true` 时渲染。用户必须先进入剧本编辑器，再点击"进入审查模式"，才能看到重生按钮。普通用户很难发现这个功能。
2. **重生后无刷新**：[useAudiobookSegmentReviewActions.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/useAudiobookSegmentReviewActions.ts) 中 `handleRegenerateSegment` 成功后仅显示 snackbar，不刷新剧本编辑器中的片段音频数据，用户听不到新生成的音频。
3. **重生参数不可选**：前端只传 `reason/tts_model/voice_id/emotion`，用户无法在重生时选择不同的 TTS 模型或音色（后端 API 已支持）。
4. **缺少批量重生**：只能逐个片段重生，无法批量标记"需重生"后一键执行。

### 修复方案

- **FE-01**：[ScriptSegmentActions.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/ScriptSegmentActions.tsx) 始终显示"重新生成"按钮（不必进入审查模式），审查模式仅额外显示评分组件。
- **FE-02**：`handleRegenerateSegment` 成功后，自动刷新当前章节的剧本数据或至少更新被重生片段的 `audio_path`。
- **FE-08**：重生按钮点击后弹出轻量对话框，允许用户选择 TTS 模型/音色/情感（可选，默认使用当前配置）。
- **FE-09**：审查模式增加多选 + 批量重生（P3，后续迭代）。

### 涉及文件

- `frontend/src/pages/audiobook/ScriptSegmentActions.tsx`
- `frontend/src/pages/audiobook/useAudiobookSegmentReviewActions.ts`
- `frontend/src/pages/audiobook/ScriptEditorDialog.tsx`（可能需传递刷新回调）

### 验收标准

- 不进入审查模式也能看到"重新生成"按钮。
- 重生成功后，剧本编辑器中该片段的音频自动更新，用户可直接试听新音频。
- 重生按钮点击后可选择 TTS 模型/音色（或使用默认值快速重生）。

---

## V3-24：音效库/音乐库无前端浏览与管理入口

### 问题

后端已实现完整的音效库和音乐库索引系统：

- `sound_effects_index.json`：音效库索引，包含分类、许可、时长、质量等元数据。
- `music_index.json`：音乐库索引，包含情绪、风格、时长、质量等元数据。
- `SoundEffectDesigner`：音效匹配、注册、质量评估、低质/孤立清理。
- `MusicComposer`：配乐生成、索引加载、质量评估、低质/孤立清理。
- `SfxLibraryDownloader`：本地已授权素材 manifest 导入、公开候选发现、许可审计、credits 导出。

原问题是**库管理功能无 HTTP API 暴露，前端也无任何浏览/管理入口**。用户无法：

1. 浏览已有音效库/音乐库中的素材。
2. 按分类、风格、场景、时长等维度搜索和筛选素材。
3. 预览音效/配乐片段。
4. 查看素材的许可信息、来源、质量评分。
5. 安全检查缺失文件或孤立索引。

### 修订边界

本项不再包含“公开平台搜索/下载”能力。V3-22 已明确禁止把公开素材平台当作可直接镜像下载的音效库来源，因此 V3-24 的前端入口只允许浏览、搜索、筛选、预览本地已入库素材，并允许 dry-run 检查缺失索引。

公开平台相关能力只能进入候选发现和人工审核流程，正式入库必须走本地已授权素材 manifest 导入。

### 已落地 API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v1/audiobook/audio-library/stats` | GET | 获取音效库/音乐库统计与筛选项 |
| `/api/v1/audiobook/audio-library/sound-effects` | GET | 浏览音效库索引，支持分类、标签、场景、关键词筛选 |
| `/api/v1/audiobook/audio-library/music` | GET | 浏览音乐库索引，支持风格、情绪、关键词筛选 |
| `/api/v1/audiobook/audio-library/preview/{file_type}/{file_id}` | GET | 预览音效或音乐文件 |
| `/api/v1/audiobook/audio-library/cleanup` | POST | 默认 `dry_run=true`，只统计缺失索引；实际写索引必须 `dry_run=false` 且 `confirm=true` |
| `/api/v1/audiobook/audio-library/sound-effects/search` | POST | 已禁用，返回 403，提示走候选审核流程 |
| `/api/v1/audiobook/audio-library/sound-effects/download` | POST | 已禁用，返回 403，提示走本地 manifest 导入 |

### 已落地前端界面

- `AudioFxConfigPanel` 已提供“浏览素材库”入口。
- `AudioLibraryBrowser` 以 Dialog 方式展示音效库/音乐库。
- 支持音效分类/场景筛选、音乐风格/情绪筛选、关键词搜索、预览播放。
- 支持展示质量评分/等级/状态、授权协议/商用状态、来源、作者、署名要求、入库时间和授权检查时间。
- “检查缺失文件”按钮只触发 dry-run 检查，不直接删除文件或改写索引。
- 前端已移除“从公开库导入”、公开库搜索和下载按钮。

### 涉及文件

**后端**：
- `backend/app/api/v1/audiobook_api/routes_audio_library.py`
- `backend/app/api/v1/audiobook_api/__init__.py`

**前端**：
- `frontend/src/pages/audiobook/AudioLibraryBrowser.tsx`
- `frontend/src/pages/audiobook/AudioFxConfigPanel.tsx`
- `frontend/src/services/api.ts`

### 验收标准

- 用户可在有声书页面打开音效库/音乐库浏览界面。
- 支持按分类、风格、情绪筛选和关键词搜索。
- 可预览音效/配乐片段。
- 不暴露公开平台自动搜索/下载入口。
- 缺失文件检查默认 dry-run；实际写入必须显式确认。

### 完成记录（2026-05-06 第一阶段）

- 后端新增并注册 `routes_audio_library.py`，提供本地音效库/音乐库 stats、browse、preview 与 cleanup API。
- 前端新增 `AudioLibraryBrowser.tsx`，并从 `AudioFxConfigPanel.tsx` 提供入口。
- `frontend/src/services/api.ts` 已封装本地库浏览、预览和 cleanup API。
- 前端 source guard 已锁定：浏览器组件不包含“从公开库导入”、`searchPublicSfx`、`downloadSfxToLibrary` 或 `CloudDownloadIcon`。
- 后端公开平台直接搜索和自动下载路由均返回 403，避免绕过候选审核和本地 manifest 导入流程。
- `cleanup` 默认 `dry_run=true`，不改写索引；传入 `dry_run=false` 但缺少 `confirm=true` 时返回 400。
- 2026-05-10 补充：素材库前端管理动作已按角色收紧，普通用户只保留浏览、筛选、试听和使用素材；候选审核、manifest 导入、素材清理和单素材删除仅管理员可见。
- 2026-05-10 补充：后端已强制管理接口管理员权限，普通用户访问候选清单、manifest 草稿/导入、JSON/云端同步、云端列举/检查/清理、本地清理和单素材删除均返回 403。
- 2026-05-10 补充：新增 `POST /api/v1/audiobook/audio-library/assets/{library_type}/{asset_id}/delete`，用于管理员试听确认后的单素材删除；默认 `dry_run=true`，实际删除必须 `dry_run=false, confirm=true`，且只删除素材库目录内本地文件或受控 OSS 前缀内对象。
- 2026-05-10 补充：音效库统计新增 `sfx_scenes`，浏览接口新增 `scene` 参数；浏览响应透传 `style` / `scenes`，并对旧 `effects/action` 分类和缺失 `scenes` 的历史条目做兼容归一。
- 2026-05-10 补充：`AudioLibraryBrowser` 和片段 `AudioPicker` 已展示音效分类与场景标签，用户可按场景筛选或用场景关键词搜索素材。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__/audioLibraryBrowserSource.test.ts"`：8 passed。
  - `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：17 passed。

### 完成记录（2026-05-06 浏览元数据增强）

- 后端 `SfxLibraryEntry` / `MusicLibraryEntry` browse 响应已透传索引中的质量、授权、来源、作者、署名和时间字段。
- `frontend/src/services/api.ts` 已补齐音效库/音乐库浏览响应的可选元数据类型，兼容历史缺字段索引。
- `AudioLibraryBrowser` 已在音效和音乐列表中展示质量、授权、商用状态、署名要求、作者、来源、入库时间与授权检查时间；`attribution_text` 单独展示，便于后续导出或人工核验。
- 本次仍不启用公开平台自动下载；公开候选发现和正式入库边界继续遵循 V3-22 / V3-26。
- 验证通过：
  - `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py::test_browse_sound_effects_returns_quality_license_and_attribution_metadata" "backend/tests/test_audiobook_audio_library_routes.py::test_browse_music_returns_quality_license_and_attribution_metadata" -q`：2 passed。
  - `npm test -- "src/pages/audiobook/__tests__/audioLibraryBrowserSource.test.ts"`：6 passed。
  - `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：17 passed。
  - `npm run type-check`：passed。

### 后续可选增强

- V3-24 当前已覆盖浏览、搜索、预览、质量/授权/来源展示；后续不再扩大公开平台能力。
- 若后续继续增强，应只考虑更细的筛选项（如按授权、商用状态、质量状态筛选），且继续保持本地已入库素材浏览边界。

---

## V3-25：片段音效/配乐输入方式原始，无法从库中选择

### 问题

[ScriptSegmentDetailsPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/ScriptSegmentDetailsPanel.tsx) 中音效和配乐的输入方式为纯文本输入框：

- 音效：`<TextField label="音效提示（逗号分隔）" />`，用户需手动输入如 `rain, wind, thunder`。
- 配乐：`<TextField label="配乐提示" />`，用户需手动输入如 `suspense`。

这种方式存在以下问题：

1. 用户不知道有哪些可用音效/配乐，只能凭记忆输入关键词。
2. 无法从已有音效库/音乐库中选择，输入的关键词可能与库中素材不匹配。
3. 无法预览选中的音效/配乐效果。
4. 输入格式容易出错（拼写、分隔符等）。

### 修复方案

- 将音效输入改为**选择器 + 搜索**组件：点击后弹出音效库搜索面板，用户可按分类浏览或关键词搜索，选中后自动填入。
- 将配乐输入改为**选择器 + 搜索**组件：点击后弹出音乐库搜索面板，按情绪/风格筛选，选中后自动填入。
- 选择器中支持预览音效/配乐片段。
- 保留手动输入模式作为高级选项（折叠区）。

### 前置依赖

- V3-24（音效库/音乐库浏览 API 与前端界面）

### 涉及文件

- `frontend/src/pages/audiobook/ScriptSegmentDetailsPanel.tsx`
- `frontend/src/pages/audiobook/AudioPicker.tsx`

### 验收标准

- 音效/配乐输入从纯文本改为选择器 + 搜索。
- 可从已有库中浏览和选择素材。
- 选中后自动填入正确格式。
- 支持预览选中素材。
- 音效候选项展示分类和适用场景标签，便于按有声小说使用场景快速判断。

---

## V3-26：音效下载器/素材清理无前端触发入口

### 问题

后端已实现 `SfxLibraryDownloader` 的本地已授权素材 manifest 导入、公开候选发现、credits 导出，以及 `purge_low_quality_assets`/`purge_orphan_entries` 等素材清理能力。旧方案曾计划把 Freesound/Pixabay API Key 配置和公开平台下载入口放到前端，但该方向与 V3-22 的合规边界冲突。

当前仍缺少的是：

1. `sfx_candidates.jsonl` 候选清单的人工审核界面。
2. 将审核通过的候选转换为本地导入 manifest 的流程。
3. 本地已授权素材 manifest 导入的前端入口。
4. 低质/孤立素材清理的 dry-run 预览与显式确认执行界面。

### 修订边界

- 不做 Freesound/Pixabay API Key 前端配置。
- 不从前端触发公开平台自动搜索/下载。
- 不把 Openverse/Wikimedia 的 `file_url` 当作直接下载地址。
- 正式入库必须来自本地已授权文件和 manifest，并重新做许可、来源、文件、质量校验。
- 清理类操作默认 dry-run，实际写入或删除必须要求用户显式确认。

### 已落地

- `AudioLibraryBrowser` 提供“检查缺失文件”按钮，只调用 cleanup dry-run。
- `cleanup` 后端默认 `dry_run=true`，并要求 `dry_run=false` 时必须 `confirm=true`。
- 后端公开平台直接搜索和下载路由已禁用，返回 403。

**V3-26A：候选清单审核**

- 后端新增：
  - `GET /api/v1/audiobook/audio-library/sound-effects/candidates`
  - `POST /api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft`
- 前端新增 `SfxCandidateReviewDialog.tsx`。
- 支持读取 `sfx_candidates.jsonl`，展示来源、许可、作者、时长、mime type、查询词、候选状态。
- 支持人工标记 `approved/rejected/needs_info`。
- 审核通过后只生成本地导入 manifest 草稿，不自动下载或写入音效索引。

**V3-26B：本地 manifest 导入**

- 后端新增 `POST /api/v1/audiobook/audio-library/sound-effects/import-manifest`。
- 前端新增 `SfxManifestImportDialog.tsx`。
- 支持填写本地已授权素材目录与 manifest 路径。
- 后端调用 `SfxLibraryDownloader.import_local_assets(..., dry_run=True)` 先预检。
- 用户勾选确认后，才允许 `dry_run=false, confirm=true` 执行非 dry-run 导入。
- 路由限制 `manifest_path` 和 `source_dir` 必须位于音频素材库目录内，避免任意路径导入。

**V3-26C：素材清理**

- 后端 `cleanup` 返回 `details.missing_entries`、`details.low_quality_entries`、`details.orphaned_files` 明细。
- 前端新增 `AudioLibraryPurgeDialog.tsx`。
- 支持缺失索引、孤立文件、低质素材 dry-run 预览。
- 实际清理必须二次确认，且后端要求 `dry_run=false`、`confirm=true`。
- 删除文件时只允许删除素材库目录内文件；索引中指向素材库外部的绝对路径不会被删除。

### 前置依赖

- V3-24（音效库/音乐库浏览 API 与前端界面）

### 涉及文件

**后端**（新增）：
- `backend/app/api/v1/audiobook_api/routes_audio_library.py`（候选审核、manifest 导入、清理 API）

**前端**（新增）：
- `frontend/src/pages/audiobook/SfxCandidateReviewDialog.tsx`
- `frontend/src/pages/audiobook/SfxManifestImportDialog.tsx`
- `frontend/src/pages/audiobook/AudioLibraryPurgeDialog.tsx`

**前端**（修改）：
- `frontend/src/services/api.ts`
- `frontend/src/pages/audiobook/AudioLibraryBrowser.tsx`

### 验收标准

- 不出现 Freesound/Pixabay API Key 配置界面。
- 不出现公开平台自动下载按钮。
- 可审核候选清单并生成本地导入 manifest。
- 可对本地 manifest 导入执行 dry-run 预检和显式确认导入。
- 可从前端触发低质/孤立素材清理 dry-run，并展示统计和明细。

### 完成记录（2026-05-06）

- 前端素材库浏览器仅保留本地库浏览、搜索、预览、候选审核、manifest 导入和素材清理入口。
- 后端禁用公开平台直接搜索/下载路由，防止绕开 V3-22 的合规流程。
- `frontend/src/services/api.ts` 已移除 `downloadSfxToLibrary` helper，浏览器 source guard 覆盖不再引用公开下载。
- 新增 `SfxCandidateReviewDialog.tsx`：
  - 读取 `sfx_candidates.jsonl`。
  - 支持人工审核候选。
  - 只生成本地 manifest 草稿，不自动下载、不写入音效索引。
- 新增 `SfxManifestImportDialog.tsx`：
  - 支持本地 manifest dry-run 预检。
  - 必须勾选确认后才执行实际导入。
  - 后端导入路由要求 `dry_run=false` 且 `confirm=true`。
- 新增 `AudioLibraryPurgeDialog.tsx`：
  - 支持缺失索引、低质素材、孤立文件 dry-run 预览。
  - 实际清理必须勾选确认，后端只删除素材库目录内文件。
- 2026-05-10 权限边界补充：
  - 普通用户只能查看、试听和使用已入库音频素材。
  - 候选审核、manifest 草稿生成、本地 manifest 导入、JSON/云端同步、云端对象列举/存在性检查/清理、批量清理和单素材删除全部要求管理员权限。
  - 管理员可在试听后对单个素材执行删除；后端仍默认 dry-run，非 dry-run 必须显式确认。
  - 智能删除低质素材继续通过批量 cleanup/cloud-cleanup 走质量元数据判断，不允许普通用户触发。
- 验证通过：
  - `npm test -- "src/pages/audiobook/__tests__/audioLibraryBrowserSource.test.ts"`：7 passed。
  - `npm run type-check`：通过。
  - `python -m pytest "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audiobook_audio_library_routes.py" -q`：51 passed。

### 真实库 dry-run 核验（2026-05-06）

- 当前处于测试阶段且无真实用户，但 cleanup 仍先按 dry-run 核验，不直接删除。
- 对 `backend/data/audio_library/` 执行本地只读扫描，按 cleanup 规则检查：
  - `sound_effects_index.json`：10 条索引，保留 10 条。
  - `music_index.json`：19 条索引，保留 19 条。
  - 缺失索引：0。
  - 低质素材：0。
  - 孤立文件：0。
  - 预计释放空间：0 bytes。
- 结论：当前真实测试素材库没有需要实际清理的目标，因此未执行真实删除。
- 回归验证通过：
  - `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：17 passed。
  - `python -m pytest "backend/tests/test_sfx_library_downloader.py" -q`：44 passed。

### 未覆盖风险

- 候选审核界面当前只生成 manifest 草稿，不提供在线打开来源页或文件预览；人工核验仍需用户在外部完成。
- 本地导入路径目前要求位于音频素材库目录内，避免任意路径读取；如果后续要支持浏览系统目录，需要单独设计受控文件选择/上传流程。
- cleanup 的真实删除已限制在素材库目录内；即使测试阶段允许删除，也保留 dry-run 和显式确认约束，避免误删源码或配置文件。

---

## V3-27：AudioFxConfigPanel 缺少 intelligent_balance 等高级选项

### 问题

[AudioFxConfigPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/AudioFxConfigPanel.tsx) 当前仅提供音效/配乐的开关和密度选择。后端 `AudioFxConfig` 实际支持更多高级配置：

- `intelligent_balance`：智能音量平衡（V3-12 已实现但默认关闭，前端无开关）。
- 音量平衡策略、BGM 音量微调等。

这些高级选项对专业用户有价值，但直接展示会增加界面复杂度。

### 修复方案

- 在 AudioFxConfigPanel 底部增加"高级选项"折叠区（Accordion/Collapse）。
- 折叠区内放置 `intelligent_balance` 开关、音量平衡策略选择等。
- 默认折叠，不影响普通用户的使用体验。

### 涉及文件

- `frontend/src/pages/audiobook/AudioFxConfigPanel.tsx`
- `frontend/src/pages/audiobook/types.ts`（扩展 `AudioFxConfig` 类型）

### 验收标准

- 高级选项默认折叠，不影响现有界面。
- 展开后可配置 `intelligent_balance` 等高级选项。
- 配置值正确传递到后端。

---

## V3-28：生成结果评分无前端入口（用户评分+模型统计查看）

### 问题

后端反馈系统（`/api/v1/feedback`）有 4 个端点，按用户操作需求分类：

| 端点 | 用户是否需要操作 | 说明 |
|------|-----------------|------|
| `POST /feedback/user-rating` | ✅ 需要 | 用户对生成结果打分+文字反馈 |
| `GET /feedback/model-stats/{model_id}` | ✅ 需要 | 查看某模型的用户评分统计 |
| `POST /feedback/qc-result` | ❌ 不需要 | AutoQC 自动提交，用户无需操作 |
| `POST /feedback/apply-to-profiles` | ❌ 不需要 | 后端定时任务自动回流，用户无需操作 |

前端 `/api/v1/feedback` 零引用，用户无法对生成结果评分，也无法查看模型反馈统计。

### 修复方案

- **生成结果评分**：在生成结果展示区域增加评分组件（1-5 星 + 可选文字反馈），调用 `POST /feedback/user-rating`。
- **模型统计查看**：在模型档案页面增加"反馈统计"Tab，调用 `GET /feedback/model-stats/{model_id}`。
- **api.ts 封装**：仅补充 `submitUserRating`、`getModelFeedbackStats` 两个方法。QC 提交和回流由后端自动化完成。

### 涉及文件

- `frontend/src/services/api.ts`（新增 2 个 API 方法）
- `frontend/src/pages/ModelCatalogPage.tsx`（增加反馈统计 Tab）
- `frontend/src/components/GenerationRatingWidget.tsx`（新增，通用评分组件）

### 验收标准

- 用户可在生成结果旁提交评分和文字反馈。
- 模型档案页面可查看反馈统计。

---

## V3-29：剧本审核报告前端未展示

### 问题

后端剧本审核系统（`/api/v1/script-review`）有 5 个端点，按用户操作需求分类：

| 端点 | 用户是否需要操作 | 说明 |
|------|-----------------|------|
| `GET /script-review/report/{project_id}/{chapter_id}` | ✅ 需要 | 查看审核报告（质量评分+问题片段） |
| `POST /script-review/feedback` | ✅ 需要 | 提交审核反馈 |
| `GET /script-review/script/{project_id}/{chapter_id}` | ⚠️ 可选 | 剧本片段详情，与现有 script GET 有重叠 |
| `POST /script-review/adjust` | ❌ 占位接口 | 后端未实现，暂不接入 |
| `POST /script-review/regenerate` | ❌ 占位接口 | 后端未实现，暂不接入 |

前端 `/api/v1/script-review` 零引用。审核报告和反馈流程对用户有价值，但 adjust/regenerate 是占位接口暂不接入。

### 修复方案

- **审核报告查看**：在剧本编辑器中增加"审核报告"按钮，调用 `GET /script-review/report/{project_id}/{chapter_id}`。
- **反馈提交**：在审核报告界面增加反馈提交入口，调用 `POST /script-review/feedback`。
- **api.ts 封装**：仅补充 `getScriptReviewReport`、`submitScriptReviewFeedback` 两个方法。

### 涉及文件

- `frontend/src/services/api.ts`（新增 2 个 API 方法）
- `frontend/src/pages/audiobook/ScriptEditorDialog.tsx`（增加审核报告入口）
- `frontend/src/pages/audiobook/ScriptReviewReportPanel.tsx`（新增）

### 验收标准

- 用户可在剧本编辑器中查看审核报告。
- 用户可提交审核反馈。

---

## V3-30：AI 一致性检查前端未接入

### 问题

后端 `/api/v1/ai-assist/check-consistency` 提供跨章节角色/设定一致性检查，返回不一致列表和修复建议。前端未接入。

同模块其他端点状态：`detect-conflicts` ✅ 已接入、`check-chapter-logic` ✅ 已接入、`generate-character` ⚠️ 间接接入、`health` ❌ 内部接口无需前端。

### 修复方案

- 在编辑器页面增加"一致性检查"按钮，调用 `POST /ai-assist/check-consistency`。
- 展示检查结果：不一致列表、严重程度、修复建议。

### 涉及文件

- `frontend/src/services/api.ts`（新增 `checkConsistency` 方法）
- `frontend/src/pages/EditorPage.tsx`（增加一致性检查入口）
- `frontend/src/components/ConsistencyCheckPanel.tsx`（新增）

### 验收标准

- 用户可在编辑器中触发一致性检查。
- 检查结果展示不一致列表和修复建议。

---

## V3-31：CosyVoice 复刻音色列表查询 API 前端未封装

### 问题

后端 `GET /tts/voices/cosyvoice-v3.5-plus/clones` 可列出当前 API Key 下所有复刻音色。前端已封装创建、删除、上传样本，但**缺少列表查询**。用户无法查看已创建的复刻音色。

### 修复方案

- api.ts 新增 `listCosyVoiceV3PlusClones(prefix?: string)` 方法。
- CosyVoiceVoiceWorkbench 中展示已有复刻音色列表，支持删除。

### 涉及文件

- `frontend/src/services/api.ts`（新增方法）
- `frontend/src/pages/audiobook/CosyVoiceVoiceWorkbench.tsx`（增加列表展示）

### 验收标准

- 用户可查看已有复刻音色列表。
- 支持从列表中删除复刻音色。

---

## V3-32：有声书项目统计字段前端未展示

### 问题

数据库中已有但前端未展示的用户关注字段：

**AudiobookProject**：`total_cost`（总成本）、`total_duration`（总时长）、`completed_chapters`/`failed_chapters`（完成/失败数）

**ChapterAudio**：`tts_cost`（TTS 成本）、`generation_time`（生成耗时）、`script_status`（剧本状态）

内部调试字段（`cache_hit_rate`、`voice_config_hash`、`audio_fx_hash` 等）不需要展示给用户。

### 修复方案

- 项目详情页增加统计概览卡片（总时长、总成本、完成率）。
- 章节列表增加关键指标列（生成耗时、成本、剧本状态）。

### 涉及文件

- `frontend/src/pages/AudiobookPage.tsx`（增加统计概览卡片）
- `frontend/src/pages/audiobook/AudiobookProjectStatsCard.tsx`（新增）

### 验收标准

- 项目详情页展示总时长、总成本、完成率。
- 章节列表展示生成耗时、成本等关键指标。

---

## V3-33：智能调度系统无前端入口

### 问题

后端智能调度系统（`/api/v1/smart-dispatch`）有 5 个端点，按用户操作需求分类：

| 端点 | 用户是否需要操作 | 说明 |
|------|-----------------|------|
| `POST /smart-dispatch/dispatch` | ✅ 需要 | 自然语言调度入口，用户输入需求→系统自动路由执行 |
| `POST /smart-dispatch/recommend-models` | ✅ 需要 | 模型推荐，用户选择任务类型→系统推荐最佳模型 |
| `POST /smart-dispatch/parse-intent` | ❌ 不需要 | dispatch 内部步骤，用户无需单独调用 |
| `POST /smart-dispatch/semantic-match` | ❌ 不需要 | 内部语义匹配，用户无需直接操作 |
| `GET /smart-dispatch/style-vocabulary` | ❌ 不需要 | 内部参考数据，用户无需查看 |

### 修复方案

- 增加"智能助手"入口，提供自然语言输入框，调用 `POST /smart-dispatch/dispatch`。
- 在模型选择场景增加"推荐模型"按钮，调用 `POST /smart-dispatch/recommend-models`。
- api.ts 仅封装 `smartDispatch`、`recommendModels` 两个方法。

### 涉及文件

- `frontend/src/services/api.ts`（新增 2 个 API 方法）
- `frontend/src/components/SmartDispatchInput.tsx`（新增）

### 验收标准

- 用户可通过自然语言描述需求，系统自动调度。
- 用户可获取模型推荐。

---

## V3-34：内容进化引擎 — 无需前端入口

### 结论

纯后端内部优化引擎（`content_evolution/`），基于反馈自动优化生成策略。无用户直接操作需求，结果通过工作流间接消费。**标记为无需前端入口**。

---

## V3-35：伏笔追踪/知识图谱/地点层级等 — 无需前端入口

### 结论

以下后端服务均为纯分析服务，结果通过工作流间接消费，无用户直接操作需求：

- `foreshadowing_tracker.py`：伏笔追踪
- `knowledge_graph.py`：知识图谱（角色关系图已有独立前端入口 `getCharacterRelationshipGraph`）
- `location_hierarchy_extractor.py`：地点层级提取
- `entity_extraction.py`：实体提取
- `consistency_validator.py`：一致性验证（与 V3-30 的 `ai-assist/check-consistency` API 互补，后者已有用户操作入口需求）

**标记为无需前端入口**。

---

## 全面排查汇总

### 需要前端入口的优化项（按优先级）

| 优先级 | 编号 | 模块 | 用户操作 | 需封装的 API 方法数 |
|--------|------|------|----------|-------------------|
| P1 | V3-23 | 有声书-分段重生 | 点击重生按钮 | 0（已有） |
| P1 | V3-24 | 有声书-音效库/音乐库 | 浏览/搜索/预览素材，展示质量/授权/来源元数据 | 已完成 |
| P1 | V3-28 | 生成结果评分 | 打分+查看统计 | 2 |
| P2 | V3-25 | 片段音效/配乐选择 | 从库中选择素材 | 0（依赖 V3-24） |
| P2 | V3-26 | 音效候选审核/manifest 导入/素材清理 | 审核候选、导入本地授权素材、dry-run 清理 | 已完成 |
| P2 | V3-29 | 剧本审核报告 | 查看报告+提交反馈 | 2 |
| P2 | V3-30 | AI 一致性检查 | 触发检查 | 1 |
| P2 | V3-31 | CosyVoice 复刻音色列表 | 查看已有音色 | 1 |
| P2 | V3-32 | 有声书统计字段 | 查看成本/时长 | 0（数据已有） |
| P3 | V3-27 | AudioFxConfig 高级选项 | 配置开关 | 0（类型扩展） |
| P3 | V3-33 | 智能调度 | 自然语言输入+模型推荐 | 2 |

### 无需前端入口的后端功能

| 编号 | 模块 | 原因 |
|------|------|------|
| V3-34 | 内容进化引擎 | 纯内部优化，无用户操作 |
| V3-35 | 伏笔/图谱/地点/实体提取 | 纯分析服务，结果通过工作流间接消费 |
| — | `feedback/qc-result` | AutoQC 自动提交 |
| — | `feedback/apply-to-profiles` | 后端定时任务自动回流 |
| — | `script-review/adjust` | 占位接口，未实现 |
| — | `script-review/regenerate` | 占位接口，未实现 |
| — | `smart-dispatch/parse-intent` | dispatch 内部步骤 |
| — | `smart-dispatch/semantic-match` | 内部语义匹配 |
| — | `smart-dispatch/style-vocabulary` | 内部参考数据 |
| — | `ai-assist/health` | 内部健康检查 |
| — | `audiobook/previews/*` | V3-04 已删除 |

---

## 每轮完成后必须更新

- 当前优化项状态。
- 实际改动文件。
- 测试命令与结果。
- 未覆盖风险。
- 是否需要更新归档或另起新文档。

---

## 2026-05-07 补充：音乐/音效共享素材库云端化

### 新结论

音乐库和音效库属于所有用户共用资产，正式素材不应只依赖单机本地磁盘。合理架构是：

1. 云端对象存储作为共享素材的权威存储。
2. 后端本地 `backend/data/audio_library/` 仅作为导入暂存、质量检测和混音时的缓存镜像。
3. `sound_effects_index.json` 和 `music_index.json` 保留本地 `file_path`，同时增加云端元数据：
   - `storage_mode`
   - `storage_driver`
   - `cloud_uri`
   - `public_url`
   - `object_key`
   - `local_cache_path`
   - `asset_scope`
4. 前端预览和素材浏览应展示云端元数据；预览接口在存在 `public_url` 时优先跳转云端 URL。
5. 用户触发大模型生成的新音乐/音效素材，完成质量检测并写入相应索引时，应自动尝试上传云端；云上传失败时降级保留本地缓存记录，不阻断主生成流程。

### 已落地代码

- 新增 `backend/app/services/audiobook/audio_asset_cloud_storage.py`。
- 新增 `backend/app/models/audio_library_asset.py`、`backend/app/services/audiobook/audio_library_asset_repository.py` 和 Alembic 迁移 `backend/alembic/versions/add_audio_library_assets.py`。
- 授权音效 manifest 导入成功且质量通过后，会写入共享云端元数据。
- Vidu/Mureka 等 AI 生成音效注册成功且质量通过后，会写入共享云端元数据。
- Mureka AI 生成音乐写入 `music_index.json` 且质量通过后，会写入共享云端元数据。
- 素材浏览 API 返回云端元数据字段；预览接口存在 `public_url` 时优先 `307` 跳转云端 URL。
- 素材浏览、统计、预览接口已支持优先读取数据库 `audio_library_assets`，数据库不可用或为空时回退 JSON 索引。
- `cloud-sync` 已支持优先读取并回写数据库 `audio_library_assets`，仅在数据库无对应类型记录或查询失败时回退 JSON 索引。
- 已将当前 39 条共享素材索引写入数据库：
  - `sfx=20`
  - `music=19`
  - `source=vidu` 10 条
  - `source=local_authorized` 10 条（其中 `source_url` 指向 Wikimedia Commons 的条目 10 条）
  - `source=mureka` 19 条
  - 全部仍为 `storage_mode=local_cache`
  - `durable_cloud=0`
- `backend/app/core/config.py` 增加共享音频素材库云存储配置项：
  - `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_POLICY_MODEL`

### 本轮验证

- `python -m alembic -c "alembic.ini" current`：`add_audio_library_assets (head)`
- `python -m pytest "backend/tests/test_audiobook_audio_library_routes.py" -q`：27 passed
- `python -m pytest "backend/tests/test_autoqc_utils.py" "backend/tests/test_dreamweaver_vision_review.py" -q`：8 passed
- `python -m pytest "backend/tests/test_audio_library_asset_repository.py" "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audiobook_audio_library_routes.py" "backend/tests/test_sfx_library_downloader.py" "backend/tests/test_audio_fx_optimizations.py" "backend/tests/test_autoqc_utils.py" "backend/tests/test_dreamweaver_vision_review.py" -q`：153 passed

### 后续执行边界

- 当前默认仍是 `local_fs`，避免开发/测试环境在未确认 OSS 配置时意外发起云上传。
- 当前环境存在 DashScope Key，但 `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=local_fs`，因此对象存储上传仍处于未启用状态。
- 若要让后续 Wikimedia CC0/Public Domain 音效正式进入共享云端库，需要先配置：
  - `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=dashscope_oss`
  - 可选：`AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX=shared/audio_library`
  - 可选：`AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=<可公开访问的 OSS/CDN 域名>`
- 正式 manifest import 仍必须先 dry-run，再由用户确认执行 `dry_run=false, confirm=true`。
- 现有 39 条 `local_cache` 共享素材如需对象存储持久化，应先执行 `cloud-sync` dry-run，再在确认 OSS 配置后执行 `dry_run=false, confirm=true`。

### 2026-05-09 补充：audio.sggf.net 未创建 DNS 时的处理

- 当前确认 `audio.sggf.net` 仍是无效 DNS Host，不能启用 `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=https://audio.sggf.net`。
- `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=dashscope_oss` 可以保留，用于共享素材上传；`AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST` 必须继续为空或注释，避免写入不可访问的公网 URL。
- 自定义域名只作为未来切换能力：DNS/CDN/OSS 映射、HTTPS 证书、测试对象访问和 Range 请求验证通过后，再启用该变量。
- 后端 public URL 动态解析已收紧：只有存在 `object_key` 或 `cloud_uri` 的云端素材才会改写到配置的公网域名；只有旧 `public_url` 的历史记录不再从 URL 路径反推 object key，避免误改写。
- 详细部署和验证步骤见 `docs/AUDIO_LIBRARY_PUBLIC_HOST_DEPLOYMENT.md`。

### 2026-05-10 补充：自有 Aliyun OSS 公共素材库落地

- `audio.sggf.net` 已完成 OSS 自定义域名、HTTPS 和前缀只读验证：
  - `https://audio.sggf.net/shared/audio_library/healthcheck.txt` 返回 `200 OK`。
  - 响应包含 `Accept-Ranges: bytes`，可用于音频播放拖动。
- 新增 `aliyun_oss` 共享素材库 driver，上传目标为自有 Bucket：
  - `AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=aliyun_oss`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET=sggf-audio-library`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX=shared/audio_library`
  - `AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST=https://audio.sggf.net`
- `dashscope_oss` 保留为兼容过渡路径，但不应与 `audio.sggf.net` 公网域名混用；正式共享素材库应使用 `aliyun_oss`。
- 后续真实同步前仍需先配置最小权限 RAM AccessKey，并执行 `cloud-sync` dry-run。

### 2026-05-10 补充：公共素材库权限与删除边界

- 普通用户对公共音频素材库只有只读使用权限：可浏览、筛选、试听、在片段中使用素材。
- 管理能力只允许管理员使用：
  - 候选清单查看与 manifest 草稿生成。
  - 本地已授权 manifest 导入。
  - JSON 索引同步数据库、素材同步云端。
  - 云端对象列举、批量存在性检查、云端清理。
  - 本地/索引 cleanup。
  - 单素材删除。
- 删除策略：
  - 系统/智能清理只基于明确质量元数据、缺失索引或孤立文件，不把缺失质量数据的历史素材当作低质素材误删。
  - 管理员试听后的手动删除走 `POST /api/v1/audiobook/audio-library/assets/{library_type}/{asset_id}/delete`。
  - 所有真实删除仍要求 `dry_run=false` 且 `confirm=true`。
  - 本地文件删除限制在音频素材库目录内；云端对象删除限制在 `AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX` 下。
- 前端 `AudioLibraryBrowser` 已按 `admin/super_admin` 角色隐藏管理按钮；普通用户界面不展示候选审核、manifest 导入、素材清理和删除按钮。
- 验证通过：
  - `python -m pytest "backend/tests/test_audio_library_cloud_storage.py" "backend/tests/test_audiobook_audio_library_routes.py" -q`：51 passed。
  - `npm test -- --run "src/pages/audiobook/__tests__/audioLibraryBrowserSource.test.ts"`：7 passed。
  - `npm run type-check`：passed。

---

## 2026-05-11 追加：公共音效库第二批精选补库

### 本轮目标

- 继续补充有声小说常用音效，但避免继续堆叠同质脚步、普通门声、普通武器声。
- 重点补薄弱和高频叙事场景：药瓶、骰子、锁具、小容器、餐具等真实道具，奇幻反馈，恐怖转场，怪异氛围，少量科幻终端与机器环境。
- 仍然只导入来源和许可明确的 CC0 素材；短音效不因时长短被视为低质量。

### 素材来源与合规边界

- 本轮没有启用外部平台自动下载，也没有批量抓取新平台。
- 仅从本地已保存且已人工核验 CC0 的素材包中精选：
  - `opengameart_cc0_packs/accessory.zip`
  - `opengameart_cc0_packs/tinysized.zip`
  - `opengameart_cc0_packs/rpg_sound_pack.zip`
  - `opengameart_cc0_packs/sci-fi-sfx.zip`
  - `opengameart_cc0_packs/sfx_loops.zip`
  - `opengameart_cc0_packs/water-splash-slime-sfx.zip`
  - `kenney_cc0_packs/kenney_digital-audio.zip`
  - `kenney_cc0_packs/kenney_sci-fi-sounds.zip`
- 生成 manifest 前扫描当前 JSON 索引和历史 manifest 中的 `archive_path`、`archive`、`download_url` 与 `archive_member`，避免重复导入同一源包成员。
- 每条新增素材保留 `source_url`、`download_url`、`author`、`author_url`、`license=CC0`、`license_url`、`license_commercial=true`、`attribution_required=false`、`source_payload_json.archive_path`、`source_payload_json.archive_member`、`source_payload_json.local_sha256`。

### 本轮落地结果

- 新增授权素材目录：`backend/data/audio_library/approved_sfx/cc0_story_sfx_expansion3_20260511/`
- 新增 manifest：`backend/data/audio_library/sfx_import_manifest_cc0_story_sfx_expansion3_20260511.jsonl`
- 本轮新增入库：47 条
- dry-run 结果：47 candidates，0 rejected_license，0 rejected_file，0 rejected_quality
- 正式导入结果：47 imported，0 rejected_quality，0 skipped_existing
- 本轮 47 条全部上传 Aliyun OSS，`storage_mode=durable_cloud`，`storage_driver=aliyun_oss`
- 已同步数据库 `audio_library_assets`

### 本轮新增分类分布

| 分类 | 数量 |
|---|---:|
| `action/realistic` | 19 |
| `transition/horror` | 5 |
| `action/scifi` | 4 |
| `emotion/horror` | 4 |
| `environment/scifi` | 4 |
| `transition/fantasy` | 3 |
| `action/intense` | 2 |
| `emotion/fantasy` | 2 |
| `environment/horror` | 1 |
| `environment/intense` | 1 |
| `environment/realistic` | 1 |
| `transition/scifi` | 1 |

### 当前音效库状态

- JSON 索引总数：954
- DB `sfx` 总数：954
- DB 云端持久化总数：954
- 存储状态：`durable_cloud|aliyun_oss = 954`
- 质量状态：`accepted = 945`，`tolerated = 1`，历史无质量状态记录 = 8
- 本轮改善后的薄弱项：
  - `transition/horror`: 2 -> 7
  - `environment/horror`: 10 -> 11
  - `emotion/fantasy`: 1 -> 3
  - `environment/scifi`: 49 -> 53
  - `action/scifi`: 36 -> 40

### 云端验证

抽样 7 条本轮新增 OSS 对象执行 `HEAD`，均返回 `200`：

- `medicine_pill_bottle_shake_01` -> `audio/wav`
- `medicine_pill_bottle_shake_long` -> `audio/wav`
- `arrow_feathers_rustle` -> `audio/wav`
- `phase_jump_arcane_05` -> `audio/ogg`
- `odd_horror_sting_random6` -> `audio/wav`
- `weird_horror_sting_05` -> `audio/ogg`
- `space_engine_loop_000` -> `audio/ogg`

### 回归测试

```powershell
$env:PYTHONPATH='backend'
$env:PYTHONIOENCODING='utf-8'
python -m pytest `
  "backend/tests/test_sfx_library_downloader.py::test_filter_results_keeps_short_effects_by_default" `
  "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_registers_quality_checked_file" `
  "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_attaches_cloud_metadata_for_shared_library" `
  "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_normalizes_quiet_licensed_file_before_quality_check" `
  "backend/tests/test_sfx_library_downloader.py::test_import_local_assets_preserves_manifest_source_payload" `
  "backend/tests/test_audio_fx_optimizations.py::test_sound_effect_quality_does_not_penalize_valid_short_effects" `
  "backend/tests/test_audio_library_cloud_storage.py" `
  "backend/tests/test_audio_library_asset_repository.py" -q
```

结果：`19 passed`

### 后续建议

- 现阶段继续补库时，应优先筛选仍明显偏少的 `action/fantasy`、`emotion/intense`、`environment/horror`、`transition/intense`，但不要为了数量强行导入低辨识度素材。
- 真实道具类已经进一步补强；后续应减少药瓶、锁具、骰子、门类的重复变体，除非前端试听确认现有素材质量不够。
- 大批量导入前仍保持当前流程：候选精选 -> 授权 manifest -> dry-run -> 正式导入 -> DB 同步 -> OSS 抽样 HEAD -> 测试 -> 文档记录。
