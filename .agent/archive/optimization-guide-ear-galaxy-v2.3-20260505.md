# 耳畔星河 — 项目优化指导文档

> **版本**：2.3
> **创建日期**：2026-05-04
> **最后更新**：2026-05-05
> **适用范围**：`backend/app/api/v1/audiobook_api/`、`backend/app/services/audiobook/`、`frontend/src/pages/audiobook/`、`frontend/src/components/audiobook/`、`frontend/src/services/api.ts`

---

## 文档更新机制

### 状态定义

| 状态 | 含义 |
|------|------|
| 🔴 待处理 | 已识别问题，尚未开始实施 |
| 🟡 进行中 | 正在实施优化 |
| 🟢 已完成 | 优化已完成并通过验证 |
| ⚪ 已搁置 | 经评估暂不实施（需注明原因） |

### 更新规则

1. 每项优化开始实施时，将状态更新为「进行中」，填写实际责任人和开始日期
2. 完成后更新为「已完成」，补充实际实施细节、测试结果及性能对比数据
3. 若决定搁置，更新为「已搁置」并注明搁置原因和重新评估条件
4. 任何状态变更需更新文档顶部的「最后更新」日期

---

## 历史优化总览（OPT-00 ~ OPT-19，均已完成）

| 编号 | 优化项 | 状态 |
|------|--------|------|
| OPT-00 | 统一软删除过滤与恢复入口边界 | 🟢 已完成 |
| OPT-01 | 提取权限验证为 FastAPI Depends 依赖 | 🟢 已完成 |
| OPT-02 | 删除 configure_retry 全局状态修改端点 | 🟢 已完成 |
| OPT-03 | 修复 browser-player N+1 查询 | 🟢 已完成 |
| OPT-04 | 统一数据访问方式为 Repository 模式 | 🟢 已完成 |
| OPT-05 | 拆分 preview_script_segment_audio 长函数 | 🟢 已完成 |
| OPT-06 | 消除 CosyVoice prefix 重复逻辑 | 🟢 已完成 |
| OPT-07 | 简化 AudiobookSetupStep 组件 Props | 🟢 已完成 |
| OPT-08 | 统一按钮样式体系 | 🟢 已完成 |
| OPT-09 | 校准未使用端点清理策略 | 🟢 已完成 |
| OPT-10 | 修复 list_user_audiobook_projects N+1 查询 | 🟢 已完成 |
| OPT-11 | 按钮行窄屏响应式适配 | 🟢 已完成 |
| OPT-12 | 统一按钮 loading 反馈模式 | 🟢 已完成 |
| OPT-13 | 为 disabled 按钮添加 Tooltip 提示 | 🟢 已完成 |
| OPT-14 | 统一删除端点参数传递方式 | 🟢 已完成 |
| OPT-15 | 抽取项目级音频配置解析器 | 🟢 已完成 |
| OPT-16 | 后台任务批量预取章节与音频记录 | 🟢 已完成 |
| OPT-17 | 完善 SSE 与轮询协作策略 | 🟢 已完成 |
| OPT-18 | 优化 BrowserPlayer 移动端布局 | 🟢 已完成 |
| OPT-19 | 补齐章节音频恢复的前端入口 | 🟢 已完成 |

---

## 本轮优化总览（OPT-20 ~ OPT-31）

成本口径：低 = 半天内， 中 = 1-2 天， 高 = 3 天以上或涉及跨模块回归。

| 编号 | 优先级 | 优化项 | 状态 | 实施成本 | 预期收益 |
|------|--------|--------|------|----------|----------|
| OPT-20 | P2 | 删除 deprecated 预览端点 | ⚪ 已搁置 | 低 | 等待兼容窗口和外部消费者确认后再删 |
| OPT-21 | P1 | 提取 preview retry config 为模块常量 | 🟢 已完成 | 低 | 消除冗余实例创建，代码更清晰 |
| OPT-22 | P2 | 补齐前端 CosyVoice 克隆列表 API 方法 | ⚪ 已搁置 | 低 | 现有 `getTtsVoices()` 已覆盖克隆刷新 |
| OPT-23 | P2 | 提取 soft_delete 快照构建为共享序列化器 | 🟢 已完成 | 中 | 消除 120+ 行重复快照代码，新增字段时只需改一处 |
| OPT-24 | P2 | 拆分 useAudiobookTaskPolling 为 SSE + 轮询双 hook | 🟢 已完成 | 高 | 649 行 → 两个 ~200 行 hook，提升可测试性 |
| OPT-25 | P2 | 收录按钮禁用逻辑改为按章节独立 | ⚪ 已搁置 | 低 | 并行收录需先确认任务并发安全 |
| OPT-26 | P1 | BrowserPlayer localStorage 添加 TTL 清理 | 🟢 已完成 | 低 | 防止长期使用后 localStorage 膨胀 |
| OPT-27 | P2 | 统一 audiobookColors 中 danger/warning 语义 | ⚪ 已搁置 | 中 | review 与通用语义色暂保留边界 |
| OPT-28 | P1 | 删除无前端消费者的详情端点 | 🟢 已完成 | 低 | 收缩 API 表面积 |
| OPT-29 | P1 | 移除 cosyvoice-v3-plus 向后兼容别名路由 | 🟢 已完成 | 低 | 减少 4 条冗余路由注册 |
| OPT-30 | P1 | SHA1 → SHA256 替换 | 🟢 已完成 | 低 | 消除 lint 抑制，符合安全编码规范 |
| OPT-31 | P2 | 提取积分冻结 try/except 为共享辅助函数 | 🟢 已完成 | 低 | 消除 routes_projects 和 routes_subtitle 中的重复模式 |

---

### 2026-05-05 代码核验后的执行结论

- 本轮实际落地：OPT-21、OPT-23、OPT-24、OPT-26、OPT-28、OPT-29、OPT-30、OPT-31，均为低风险、可测试且与当前代码事实一致的局部优化。
- 暂不实施：OPT-20、OPT-22、OPT-25、OPT-27。原因分别是 legacy preview 仍处于兼容窗口、CosyVoice 克隆刷新已有 `getTtsVoices()` 路径、章节收录并发安全性未被证明、review 色彩 token 与通用 danger/warning 仍承担不同语义。
- 后续保留：暂无新的待处理项；当前仍搁置的 OPT-20、OPT-22、OPT-25、OPT-27 维持原结论，建议在兼容窗口、并发安全或视觉规范条件满足后再单独评估。

---

## P1 — 应该修复（效率/可维护性）

---

### OPT-20：删除 deprecated 预览端点

**状态**：⚪ 已搁置
**责任人**：Codex（核验）
**目标完成日期**：—

#### 原始问题

`routes_misc.py` 中 `POST /previews/generate` 和 `GET /previews/{preview_id}` 已标记 `deprecated=True`，前端对应 API 方法已在 OPT-02/OPT-09 中移除，但后端代码仍保留。

**风险**：

1. 增加无效 API 表面积，新开发者可能误用
2. `generate_preview` 使用 `get_llm_client` + `AudiobookEngine` 而非 `runtime_synthesize_speech`，与主链路 TTS 调用方式不一致，行为可能分叉
3. `default_preview_generator` 的输出目录和文件命名与 `SegmentPreviewService` 不同，维护两套预览逻辑增加认知负担

#### 代码核验结论

2026-05-05 核验：`backend/tests/test_audiobook_misc_routes.py` 仍覆盖 legacy preview 文件读取和 deprecated OpenAPI 标记，`preview_generator.py` 仍生成 `/previews/{preview_id}` 形式的音频 URL。直接删除属于破坏性 API 变更，本轮暂不实施；重新评估条件是兼容窗口结束且测试不再锁定该路由。

#### 技术方案

1. 删除 `routes_misc.py` 中 `generate_preview` 和 `get_generated_preview` 两个端点
2. 删除 `routes_misc.py` 中对 `AudiobookEngine`、`default_preview_generator` 的导入
3. 确认 `preview_generator.py` 无其他模块引用后可保留（可能被 segment preview 复用）
4. 运行后端测试确认无回归

#### 预期改进效果

- 收缩 2 个无效端点
- 消除不一致的 TTS 调用路径
- 减少约 40 行代码

#### 实施步骤

1. [ ] 删除 `routes_misc.py` 中 `generate_preview` 端点
2. [ ] 删除 `routes_misc.py` 中 `get_generated_preview` 端点
3. [ ] 清理 `routes_misc.py` 中不再需要的导入（`AudiobookEngine`、`default_preview_generator`、`Path` 等）
4. [ ] 确认 `preview_generator.py` 无其他引用
5. [ ] 运行后端测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| — | — | — |

---

### OPT-21：提取 preview retry config 为模块常量

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`routes_tts.py` 中 `_build_preview_retry_config()` 每次调用返回相同参数的 `RetryConfig`，属于不必要的函数包装：

```python
def _build_preview_retry_config() -> RetryConfig:
    return RetryConfig(max_retries=4, base_delay=1.0, max_delay=8.0, exponential_base=2.0, jitter=True)
```

该函数在 `tts_preview` 和 `tts_preview_with_timestamps` 两个端点中被调用，每次创建新实例。

#### 技术方案

将函数替换为模块级常量：

```python
_PREVIEW_RETRY_CONFIG = RetryConfig(
    max_retries=4,
    base_delay=1.0,
    max_delay=8.0,
    exponential_base=2.0,
    jitter=True,
)
```

替换所有 `_build_preview_retry_config()` 调用为 `_PREVIEW_RETRY_CONFIG`。

#### 预期改进效果

- 消除冗余函数包装
- 预览端点共享同一 RetryConfig 实例
- 代码意图更清晰

#### 实施步骤

1. [x] 在 `routes_tts.py` 中将 `_build_preview_retry_config()` 替换为 `_PREVIEW_RETRY_CONFIG` 常量
2. [x] 替换 `tts_preview` 中的调用
3. [x] 替换 `tts_preview_with_timestamps` 中的调用
4. [x] 删除 `_build_preview_retry_config` 函数
5. [x] 运行测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 将 preview retry 配置替换为 `_PREVIEW_RETRY_CONFIG` 模块常量 | `python -m pytest backend/tests/test_audiobook_tts_model_ids.py -q` 通过 |

---

### OPT-22：补齐前端 CosyVoice 克隆列表 API 方法

**状态**：⚪ 已搁置
**责任人**：Codex（核验）
**目标完成日期**：—

#### 原始问题

后端 `GET /tts/voices/cosyvoice-v3.5-plus/clones` 端点已实现，但前端 `api.ts` 中无对应方法。当前 CosyVoice 工作面板在创建/删除音色后，只能通过重新调用 `getTtsVoices()` 刷新整个音色目录来间接获取更新后的克隆列表。

**影响**：

1. 创建/删除克隆后，需要重新加载整个音色目录（含静态音色 + 克隆音色），响应体积大、延迟高
2. 无法在克隆操作后精准刷新克隆列表，用户体验不够即时

#### 代码核验结论

2026-05-05 核验：`useAudiobookVoiceActions.ts` 在创建、设计、删除 CosyVoice 自定义音色后已经调用 `refreshVoiceCatalog('cosyvoice-v3.5-plus')`，该路径通过 `apiClient.getTtsVoices()` 获取后端合并后的克隆音色列表。当前没有必要新增一套前端 API 方法和合并逻辑；除非后续完整音色目录响应成为实际性能瓶颈，否则维持现状更符合 KISS/YAGNI。

#### 技术方案

1. 在 `api.ts` 中添加 `listCosyVoiceV3PlusClones` 方法：

```typescript
listCosyVoiceV3PlusClones(prefix?: string) {
  return this.client.get<{
    meta: Record<string, unknown>
    voices: Array<{
      voice_id: string
      status: string
      gmt_create: string
      gmt_modified: string
      custom_type?: string
      voice_prompt?: string
      preview_text?: string
      preview_audio?: string
      display_name?: string
    }>
  }>('/api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones', {
    params: prefix ? { prefix } : undefined,
  })
}
```

2. 在 CosyVoice 工作面板的创建/删除回调中，优先调用此方法刷新克隆列表，再合并到音色目录中

#### 预期改进效果

- 克隆操作后可精准刷新，无需重载整个音色目录
- 响应体积从完整目录（可能含数百音色）缩小到仅克隆列表

#### 实施步骤

1. [ ] 在 `api.ts` 中添加 `listCosyVoiceV3PlusClones` 方法
2. [ ] 在 CosyVoice 工作面板 hook 中，创建/删除后调用此方法刷新
3. [ ] 运行前端测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| — | — | — |

---

### OPT-23：提取 soft_delete 快照构建为共享序列化器

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`AudiobookProjectRepository.soft_delete()` 和 `ChapterAudioRepository.soft_delete()` 各自包含 60+ 行快照 JSON 构建逻辑，字段逐一 `.isoformat()` 序列化。两个方法的快照结构高度相似但各自手写：

- `AudiobookProjectRepository.soft_delete()`：序列化 AudiobookProject + ChapterAudio 列表 + AudiobookTask 列表
- `ChapterAudioRepository.soft_delete()`：序列化 ChapterAudio + AudiobookTask 列表

**风险**：

1. 新增模型字段时，需同步修改两处快照构建，容易遗漏
2. 两个方法中 AudiobookTask 的序列化逻辑完全相同但重复编写
3. `.isoformat()` 调用散落各处，缺少 None 安全处理

#### 技术方案

1. 在 `repository.py` 中提取共享序列化函数：

```python
def _safe_iso(dt_value) -> str | None:
    if dt_value is None:
        return None
    return dt_value.isoformat()

def _serialize_audiobook_project_snapshot(project: AudiobookProject) -> dict:
    return {
        'id': project.id,
        'project_id': project.project_id,
        'status': project.status,
        # ... 其余字段
        'created_at': _safe_iso(project.created_at),
        'updated_at': _safe_iso(project.updated_at),
        'deleted_at': _safe_iso(project.deleted_at),
    }

def _serialize_chapter_audio_snapshot(audio: ChapterAudio) -> dict:
    return {
        'id': audio.id,
        'audiobook_project_id': audio.audiobook_project_id,
        # ... 其余字段
        'deleted_at': _safe_iso(audio.deleted_at),
    }

def _serialize_task_snapshot(task: AudiobookTask) -> dict:
    return {
        'id': task.id,
        'celery_task_id': task.celery_task_id,
        # ... 其余字段
    }
```

2. 两个 `soft_delete` 方法调用共享序列化器构建快照

#### 预期改进效果

- 消除约 120 行重复快照代码
- 新增字段只需修改序列化器一处
- `_safe_iso` 统一 None 安全处理

#### 实施步骤

1. [x] 在 `repository.py` 中实现 `_safe_iso`、`_serialize_audiobook_project_snapshot`、`_serialize_chapter_audio_snapshot`、`_serialize_task_snapshot`
2. [x] 重构 `AudiobookProjectRepository.soft_delete()` 使用共享序列化器
3. [x] 重构 `ChapterAudioRepository.soft_delete()` 使用共享序列化器
4. [x] 运行删除/恢复相关测试验证快照内容不变

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 提取 soft_delete 快照共享序列化器并复用到项目/章节软删除 | `python -m pytest backend/tests/test_audiobook_delete_routes.py -q` 通过 |

---

## P2 — 建议修复（体验/规范性）

---

### OPT-24：拆分 useAudiobookTaskPolling 为 SSE + 轮询双 hook

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`useAudiobookTaskPolling.ts` 共 649 行，混合了以下职责：

1. SSE 连接生命周期管理（连接、断线降级、重连）
2. SSE 事件解析（`consumeSseEventBuffer`、`applyStreamProgressPatch`）
3. 轮询降级逻辑（`pollTaskStatus`、`scheduleNextPoll`）
4. 任务状态管理（`applyTaskStatusUpdate`、`setTaskStatusesAndRef`）
5. 任务聚焦与完成处理（`focusNextActiveTask`、`handleTaskNotFound`）

单一 hook 承担过多职责，可测试性和可维护性较差。

#### 技术方案

1. 提取 `useAudiobookTaskListPolling` — 负责项目任务列表轮询和自动聚焦
   - 输入：`selectedProjectId`、`trackedAudiobookProjectIds`、`currentTaskId`、`currentAudiobookProjectId`、`activeStep`
   - 内含：`pollTaskList`、`scheduleNextPoll`、`buildTrackedTaskPollResult`、`selectActiveTaskFocusCandidate`

2. 提取 `useAudiobookTaskStreamPolling` — 负责当前任务 SSE 连接、断线降级和流式状态刷新
   - 输入：`currentTaskId`、`taskStatusesRef`、`setTaskStatusesAndRef`、`focusAudiobookTask`
   - 内含：`consumeSseEventBuffer`、`startTaskProgressStream`、`pollTaskStatus`、`applyStreamProgressPatch`

3. `useAudiobookTaskPolling` 保留为薄 wrapper，仅负责 `taskStatusesRef` 同步并组合两个子 hook

#### 预期改进效果

- 649 行 → 三个 ~200 行 hook
- SSE 连接和轮询可独立测试
- 新增 SSE 事件类型时只需修改 stream hook

#### 实施步骤

1. [x] 提取 `useAudiobookTaskListPolling` hook
2. [x] 提取 `useAudiobookTaskStreamPolling` hook
3. [x] 重构 `useAudiobookTaskPolling` 组合两个子 hook
4. [x] 更新 source guard 测试以覆盖拆分后的文件边界
5. [x] 运行前端测试验证任务轮询行为不变

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 将 `useAudiobookTaskPolling` 拆分为列表轮询与 SSE 两个独立 hook，并保留薄 wrapper | `npm test -- src/pages/audiobook/__tests__/taskPollingSource.test.ts`、`npm run type-check`、`npm test -- src/pages/audiobook/__tests__` 通过 |

---

### OPT-25：收录按钮禁用逻辑改为按章节独立

**状态**：⚪ 已搁置
**责任人**：Codex（核验）
**目标完成日期**：—

#### 原始问题

`ChapterAudioResultItem.tsx` 中收录按钮的禁用条件为 `collectDisabled={collectingChapterId !== null}`，即任何章节正在收录时，所有章节的收录按钮都被禁用。

**分析**：如果收录操作是独立的（不同章节的收录互不影响），则全局禁用过于保守，用户需要等待一个章节收录完成后才能收录下一个。

#### 代码核验结论

2026-05-05 核验：当前前端只有单一 `collectingChapterId` 状态，并未维护多章节并发收录队列或结果回写冲突处理。直接把禁用条件改成“仅当前章节禁用”会允许新的并发行为，但没有相应的并发安全测试。此项暂不实施；重新评估条件是收录流程确认支持并行写入，或先将 `collectingChapterId` 重构为按章节集合状态。

#### 技术方案

将 `collectDisabled` 逻辑改为仅禁用正在收录的章节：

```tsx
const collectDisabled = collectingChapterId !== null && collectingChapterId !== chapterAudio.chapter_id
```

同时调整 Tooltip 提示文案，区分"当前章节正在收录"和"其他章节正在收录"两种状态。

#### 预期改进效果

- 允许用户并行收录多个章节音频
- 提升批量操作效率

#### 实施步骤

1. [ ] 修改 `ChapterAudioResults.tsx` 中 `collectingChapterId` 传递逻辑
2. [ ] 修改 `ChapterAudioResultItem.tsx` 中 `collectDisabled` 计算逻辑
3. [ ] 更新 Tooltip 提示文案
4. [ ] 运行前端测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| — | — | — |

---

### OPT-26：BrowserPlayer localStorage 添加 TTL 清理

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`BrowserPlayer.tsx` 通过 `browserPlayerUtils.ts` 中的 `writeStoredBrowserPlayerState` 持久化播放器状态到 `localStorage`，键名格式为 `audiobook_browser_player_state_v1:{projectId}`。此前没有 TTL 或容量清理机制，长期使用后可能积累过期状态并恢复过时播放位置。

#### 技术方案

1. 在 `writeStoredBrowserPlayerState` 写入时附加 `savedAt` 时间戳
2. 在 `readStoredBrowserPlayerState` 读取时检查 TTL（建议 7 天），过期自动删除
3. 保持按当前项目 key 的惰性清理；暂不在初始化时全量扫描 `localStorage`，避免播放器启动阶段引入额外遍历

```typescript
const BROWSER_PLAYER_STATE_TTL_MS = 7 * 24 * 60 * 60 * 1000 // 7 天

function readStoredBrowserPlayerState(storage: Storage, projectId: number, totalChapters: number) {
  const raw = storage.getItem(buildPlayerStateKey(projectId))
  if (!raw) return DEFAULT_PLAYER_STATE
  try {
    const parsed = JSON.parse(raw)
    if (parsed.savedAt && Date.now() - parsed.savedAt > BROWSER_PLAYER_STATE_TTL_MS) {
      storage.removeItem(buildPlayerStateKey(projectId))
      return DEFAULT_PLAYER_STATE
    }
    return normalizePlayerStateSnapshot(parsed, totalChapters)
  } catch {
    storage.removeItem(buildPlayerStateKey(projectId))
    return DEFAULT_PLAYER_STATE
  }
}
```

#### 预期改进效果

- 防止 localStorage 无限膨胀
- 过期状态自动清理，避免恢复过时的播放位置

#### 实施步骤

1. [x] 在 `writeStoredBrowserPlayerState` 中添加 `savedAt` 字段
2. [x] 在 `readStoredBrowserPlayerState` 中添加 TTL 检查和自动清理
3. [x] 运行 `browserPlayerUtils.test.ts` 验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 为 BrowserPlayer 持久化状态写入 `savedAt`，读取时按 7 天 TTL 清理过期状态 | `npm test -- src/components/audiobook/__tests__/browserPlayerUtils.test.ts` 通过 |

---

### OPT-27：统一 audiobookColors 中 danger/warning 语义

**状态**：⚪ 已搁置
**责任人**：Codex（核验）
**目标完成日期**：—

#### 原始问题

`audiobookTheme.ts` 中存在语义重叠的颜色 token：

| Token | 色值 | 用途 |
|-------|------|------|
| `danger` | #c2185b | 粉红，用于通用危险操作 |
| `reviewDanger` | #c62828 | 正红，用于评审中的危险标记 |
| `warning` | #e65100 | 深橙，用于通用警告 |
| `reviewWarning` | #f57c00 | 浅橙，用于评审中的警告标记 |

这些颜色在视觉上差异不大但语义不同，开发者容易混淆使用场景。

#### 代码核验结论

2026-05-05 核验：`reviewDanger` / `reviewWarning` 当前只在脚本评审和叙事风格展示中使用，和删除、危险操作使用的 `dangerMain` / `dangerContained` 仍有业务语义边界。此项属于视觉规范整理，不应和路由/存储行为优化混在同一轮改动中；暂不实施，后续如做 UI token 清理，应单独配合视觉回归检查。

#### 技术方案

1. `danger` 统一为 `#c62828`（正红，用于删除/危险操作）
2. `warning` 统一为 `#e65100`（深橙，用于警告/待处理）
3. 删除 `reviewDanger` 和 `reviewWarning`，评审场景使用主语义色
4. 全局搜索替换引用了 `reviewDanger` / `reviewWarning` 的组件

#### 预期改进效果

- 颜色 token 语义更清晰，降低开发者选择成本
- 减少维护的颜色变体数量

#### 实施步骤

1. [ ] 修改 `audiobookColors` 中 `danger` 色值为 `#c62828`
2. [ ] 删除 `reviewDanger` 和 `reviewWarning` token
3. [ ] 全局搜索替换引用了这两个 token 的组件
4. [ ] 运行前端测试验证视觉一致性

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| — | — | — |

---

### OPT-28：删除无前端消费者的详情端点

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

以下后端端点无前端消费者：

| 端点 | 原因 |
|------|------|
| `GET /narration-styles/{style_id}` | 前端 `getNarrationStyles()` 列表接口已包含完整数据 |
| `GET /voice-types/{voice_type}` | 前端 `getVoiceTypes()` 列表接口已包含完整数据 |

这些端点属于过度实现，增加了 API 表面积但无实际消费者。

#### 技术方案

1. 删除 `routes_review.py` 中 `get_narration_style` 端点
2. 删除 `routes_smart_chunk.py` 中 `get_voice_type_detail` 端点
3. 运行后端测试确认无其他模块依赖

#### 预期改进效果

- 收缩 2 个无效端点
- 减少路由注册和维护负担

#### 实施步骤

1. [x] 删除 `routes_review.py` 中 `get_narration_style` 端点
2. [x] 删除 `routes_smart_chunk.py` 中 `get_voice_type_detail` 端点
3. [x] 清理不再需要的导入
4. [x] 运行后端测试验证

#### 实施说明

2026-05-05 已移除两个详情端点，并补充路由表守卫测试，确认 `narration-styles/{style_id}` 与 `voice-types/{voice_type}` 不再注册。

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 删除无前端消费者的详情端点并更新后端路由测试 | `python -m pytest backend/tests/test_audiobook_misc_routes.py backend/tests/test_audiobook_narration_style_routes.py backend/tests/test_audiobook_smart_chunk_routes.py -q` 通过 |

---

### OPT-29：移除 cosyvoice-v3-plus 向后兼容别名路由

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`routes_tts.py` 中 4 个端点各注册了 `cosyvoice-v3-plus` 向后兼容别名路由（`include_in_schema=False`）：

```python
@router.post("/tts/voices/cosyvoice-v3.5-plus/clones")
@router.post("/tts/voices/cosyvoice-v3-plus/clones", include_in_schema=False)
```

共 4 条冗余路由注册。前端已统一使用 `cosyvoice-v3.5-plus` 路径，兼容别名无实际消费者。

#### 技术方案

1. 删除所有 `cosyvoice-v3-plus` 别名路由装饰器
2. 确认前端无 `cosyvoice-v3-plus` 路径引用

#### 预期改进效果

- 减少 4 条冗余路由注册
- 路由表更清晰

#### 实施步骤

1. [x] 删除 `routes_tts.py` 中 4 个 `cosyvoice-v3-plus` 别名路由装饰器
2. [x] 全局搜索确认前端无 `cosyvoice-v3-plus` 路径引用
3. [x] 运行后端测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 删除 `cosyvoice-v3-plus` 向后兼容别名路由 | `python -m pytest backend/tests/test_audiobook_misc_routes.py backend/tests/test_audiobook_tts_model_ids.py backend/tests/test_audiobook_tts_routes_observability.py -q` 通过 |

---

### OPT-30：SHA1 → SHA256 替换

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`routes_tts.py` 中 `_build_cosyvoice_voice_prefix` 使用 `hashlib.sha1` 并附带 `noqa: S324` 抑制 lint 告警：

```python
digest = hashlib.sha1(f"{user_id}:{cleaned_name}".encode("utf-8")).hexdigest()[:6]  # noqa: S324
```

虽然此处不涉及安全性（仅用于生成音色前缀的短哈希），但使用 SHA256 更规范且无需 lint 抑制。

#### 技术方案

```python
digest = hashlib.sha256(f"{user_id}:{cleaned_name}".encode("utf-8")).hexdigest()[:6]
```

注意：此修改会导致现有音色前缀变更。但由于前缀本身是随机生成的（`secrets.token_hex(1)` 后缀占主导），且前缀仅在创建时使用，不影响已有音色。

#### 预期改进效果

- 消除 lint 抑制
- 符合安全编码规范

#### 实施步骤

1. [x] 将 `hashlib.sha1` 替换为 `hashlib.sha256`
2. [x] 删除 `noqa: S324` 注释
3. [x] 运行测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 将 CosyVoice 前缀短哈希从 SHA1 切换为 SHA256 | `python -m pytest backend/tests/test_audiobook_tts_model_ids.py::test_cosyvoice_prefix_builder_uses_sha256_digest -q` 通过 |

---

### OPT-31：提取积分冻结 try/except 为共享辅助函数

**状态**：🟢 已完成
**责任人**：Codex
**目标完成日期**：2026-05-05

#### 原始问题

`routes_projects.py` 和 `routes_subtitle.py` 中积分冻结逻辑完全重复：

```python
try:
    record_audiobook_billing_freeze(
        db=db,
        actor_user_id=current_user.id,
        actor_username=current_user.username,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=...,
        request_context=raw_request,
        tts_pricing_key=tts_model,
    )
except Exception as exc:
    logger.warning("记录有声书积分冻结失败 audiobook_project_id=%s: %s", audiobook_project_id, exc)
```

此模式在 `create_audiobook_project`、`generate_audio_from_scripts`、`resume_chapter_generation` 三个端点中重复出现。

#### 技术方案

在 `task_support.py` 中提取共享辅助函数：

```python
def safe_record_audiobook_billing_freeze(
    *,
    db: Session,
    current_user: User,
    audiobook_project_id: int,
    chapter_ids: list[int],
    raw_request: Request,
    tts_pricing_key: str,
) -> None:
    try:
        record_audiobook_billing_freeze(
            db=db,
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=chapter_ids,
            request_context=raw_request,
            tts_pricing_key=tts_pricing_key,
        )
    except Exception as exc:
        logger.warning(
            "记录有声书积分冻结失败 audiobook_project_id=%s chapter_ids=%s: %s",
            audiobook_project_id,
            chapter_ids,
            exc,
        )
```

替换三个端点中的重复 `try/except`。

#### 预期改进效果

- 消除 3 处重复 try/except
- 积分冻结异常处理逻辑集中管理

#### 实施步骤

1. [x] 在 `task_support.py` 中实现 `safe_record_audiobook_billing_freeze`
2. [x] 替换 `routes_projects.py` 中 `create_audiobook_project` 的重复代码
3. [x] 替换 `routes_projects.py` 中 `generate_audio_from_scripts` 的重复代码
4. [x] 替换 `routes_subtitle.py` 中 `resume_chapter_generation` 的重复代码
5. [x] 运行后端测试验证

#### 实施记录

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-05 | 提取积分冻结安全记录辅助函数并替换 3 处重复 try/except | `python -m pytest backend/tests/test_audiobook_task_support_billing.py backend/tests/test_audiobook_points_precheck_routes.py backend/tests/test_audiobook_task_enqueue_order.py -q` 通过 |

---

## 审计校准结论

### 后端代码审计

- 权限校验、Repository 访问、软删除过滤已通过 OPT-00~04 统一收敛，本轮无新增重复
- deprecated 预览端点已核验为兼容窗口内的历史遗留（OPT-20），本轮暂不删除
- `soft_delete` 快照构建已提取为共享序列化器（OPT-23），项目/章节软删除复用同一套任务与章节音频快照函数
- 积分冻结 `try/except` 已收敛到 `safe_record_audiobook_billing_freeze`（OPT-31），3 个端点复用同一异常处理入口

### 前端优化评估

- 按钮样式体系已通过 OPT-08 统一，`danger`/`reviewDanger` 颜色语义重叠仍保留为后续视觉整理项（OPT-27）
- 窄屏响应式已通过 OPT-11 适配，本轮未新增 `ChapterAudioResultItem` 细化布局问题
- `useAudiobookTaskPolling` 已拆分为 `useAudiobookTaskListPolling` 与 `useAudiobookTaskStreamPolling`（OPT-24），薄 wrapper 仅负责组合与状态引用同步
- 收录按钮全局禁用逻辑过于保守（OPT-25），但并发安全性未证明，暂不放开

### 前后端协作检查

- SSE 任务流已被 `useAudiobookTaskPolling.ts` 实际接入，并由拆分后的 stream hook 负责
- `POST /previews/generate`、`GET /previews/{preview_id}` 仍保留为 deprecated 兼容端点（OPT-20）
- `GET /tts/voices/cosyvoice-v3.5-plus/clones` 暂无独立前端 API 方法，但当前通过 `getTtsVoices()` 已能完成克隆刷新（OPT-22）
- `GET /narration-styles/{style_id}`、`GET /voice-types/{voice_type}` 已移除（OPT-28）
- `cosyvoice-v3-plus` 别名路由已移除（OPT-29）
