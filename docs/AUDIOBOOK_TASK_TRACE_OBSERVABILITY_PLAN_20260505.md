# 耳畔星河任务观测性与 Trace 统一方案

> 版本：1.0
> 日期：2026-05-05
> 状态：导出任务 trace 试点已完成
> 适用范围：有声书任务排队、Celery 后台任务、章节运行态、SSE 进度、轮询状态、项目导出任务

---

## 1. 背景

有声书链路已经具备基本任务状态和进度回传能力：

- `AudiobookTask` 保存任务级状态、`celery_task_id`、`detail_json`、错误信息与时间戳。
- `ChapterAudioRun` 保存章节运行态、`celery_task_id`、`checkpoint_json`、断点和章节级进度。
- `AudiobookJobTracker` 负责更新任务状态、同步章节运行态，并向 SSE 推送进度。
- `/tasks/{task_id}/stream` 使用任务 id 建立 SSE 通道，当前前端传入的是 Celery task id。
- 项目导出任务已有独立 detail builder：`build_project_export_task_detail()`。

现有问题不是“完全不可排障”，而是跨链路定位口径不统一。一次生成或导出失败时，排查人员需要在任务表、章节运行态、SSE 事件、后端日志、积分冻结和文件产物之间手动拼接上下文。

---

## 2. 目标

第一阶段目标是统一观测字段口径，不做大规模架构调整：

1. 明确当前可复用的 trace 入口。
2. 明确日志、`detail_json`、`checkpoint_json` 的字段边界。
3. 给出低风险试点路径。
4. 保持前端任务状态展示兼容。
5. 不新增数据库字段、不引入外部 tracing 系统、不重写 SSE 协议。

非目标：

- 不引入 OpenTelemetry、Jaeger、Zipkin 等外部链路系统。
- 不新增任务事件表。
- 不批量替换全仓库日志格式。
- 不删除或重命名已有 `detail_json` 字段。
- 不改变前端对 `TaskStatus.detail` 的既有读取语义。

---

## 3. 当前链路事实

### 3.1 任务排队

`backend/app/services/audiobook/task_support.py` 中，`enqueue_audiobook_task()` 会创建 `AudiobookTask`，随后生成 `celery_task_id = uuid4()`，写回任务记录，再调用 Celery：

```python
signature.apply_async(task_id=celery_task_id)
```

这意味着 `celery_task_id` 不是 Celery 自动返回后才知道的附属信息，而是在排队前就由业务层生成，并被显式作为 Celery task id 使用。它天然贯穿：

- `AudiobookTask.celery_task_id`
- `ChapterAudioRun.celery_task_id`
- Celery `self.request.id`
- SSE stream id
- 前端任务流订阅参数

### 3.2 章节运行态

`enqueue_chapter_runs()` 为章节创建 `ChapterAudioRun`，并写入相同的 `celery_task_id`。`AudiobookJobTracker._update_chapter_run()` 会把 tracker detail 写入 `checkpoint_json["tracker_detail"]`，并维护章节级状态、阶段、总分段数、更新时间和错误信息。

### 3.3 任务进度与 SSE

`AudiobookJobTracker._update()` 更新 `AudiobookTask` 后形成 snapshot，包含：

- `celery_task_id`
- `status`
- `current_stage`
- `progress`
- `detail_json`
- `error_message`

`_emit_sse_progress()` 当前推送的 SSE data 结构为：

```python
{
    "stage": task_snapshot.get("current_stage"),
    "progress": task_snapshot.get("progress"),
    "detail": task_snapshot.get("detail_json") or {},
    "status": task_snapshot.get("status"),
    "error_message": task_snapshot.get("error_message"),
}
```

`backend/app/services/audiobook/sse_progress.py` 在外层事件中补充：

- `event`
- `data`
- `timestamp`
- `origin`

SSE 通道可使用 Redis pub/sub；Redis 不可用时降级为进程本地队列。这个降级机制不应因 trace 字段改造而改变。

### 3.4 前端消费方式

`frontend/src/pages/audiobook/useAudiobookTaskStreamPolling.ts` 中，SSE `progress` 事件先做轻量 progress patch，再触发任务状态刷新。前端最终仍通过轮询接口获取完整 `TaskStatus`。

因此，向 `detail_json` 增加兼容字段是低风险的；但改变 `stage`、`progress`、`status`、`detail` 的含义会影响前端任务展示，不应在第一阶段做。

### 3.5 项目导出任务

`backend/app/services/audiobook/project_export_jobs.py` 中，`build_project_export_task_detail()` 当前已经集中构造导出任务 detail，字段包括：

- `audiobook_project_id`
- `export_type`
- `download_url`
- `force`
- `current_stage`
- `stages`
- `metadata`
- `export_result`
- `error_message`

导出任务阶段相对单一，章节运行态影响小，是第一阶段 trace 试点的低风险入口。

---

## 4. Trace ID 决策

第一阶段使用现有 `celery_task_id` 作为 `trace_id`。

理由：

1. 已经跨 `AudiobookTask`、`ChapterAudioRun`、Celery 和 SSE 存在。
2. 排队前由业务层生成，可在入队、运行、回传阶段保持一致。
3. 不需要数据库迁移。
4. 不需要改变前端订阅参数。
5. 对历史任务兼容，已有 `celery_task_id` 可以直接映射。

降级规则：

- 如果任务没有 `celery_task_id`，不要临时写入一个新的伪 trace。
- 日志和 detail 中保留可定位字段：`audiobook_project_id`、`task_db_id`、`run_id`、`chapter_id`。
- 对同步或历史路径，使用这些字段组合排查，不把它们伪装成全局唯一 trace。

推荐字段：

```json
{
  "trace_id": "same-as-celery-task-id",
  "celery_task_id": "same-as-trace-id",
  "task_db_id": 123,
  "task_type": "audio_from_scripts",
  "audiobook_project_id": 456,
  "chapter_id": 789,
  "run_id": 321
}
```

---

## 5. 字段边界

### 5.1 日志字段

日志用于排障，可以包含高基数和诊断字段，但应避免敏感明文内容。

适合放入日志：

- `trace_id`
- `celery_task_id`
- `task_db_id`
- `task_type`
- `audiobook_project_id`
- `chapter_id`
- `run_id`
- `stage`
- `status`
- `progress`
- `tts_model`
- `provider`
- `error_type`
- `error_message`
- `duration_ms`
- 文件路径摘要或相对路径
- `cost_precheck_id`
- `billing_freeze_event_id`

不适合直接放入日志：

- 完整长文本章节内容
- 完整 prompt
- 原始密钥、token、签名 URL
- 大体积 `checkpoint_json`
- 大体积音频或脚本 payload

### 5.2 `detail_json`

`detail_json` 用于前端展示、任务状态恢复和轻量诊断，必须保持稳定、小而兼容。

适合放入 `detail_json`：

- `trace_id`
- `audiobook_project_id`
- `chapter_id`
- `task_id`
- `task_type`
- `run_id`
- `celery_task_id`
- `current_stage`
- `stage`
- `progress`
- `status`
- `chapter_index`
- `chapter_total`
- `stages`
- `download_url`
- `export_type`
- `error_message`
- `failure_diagnostic` 的摘要字段

不适合放入 `detail_json`：

- 完整异常堆栈
- 大体积脚本内容
- 完整 TTS provider request/response
- 可重复从数据库查询的大对象

### 5.3 `checkpoint_json`

`checkpoint_json` 是章节级断点恢复和运行态字段，不应承担前端通用展示职责。

适合放入 `checkpoint_json`：

- `tracker_detail`
- 已完成分段索引
- 临时产物路径或前缀
- 可恢复进度
- 章节级失败上下文
- `checkpoint_updated_at`

不适合放入 `checkpoint_json`：

- 只为日志查询存在的字段。
- 与断点恢复无关的展示字段。
- 跨项目、跨任务的全局诊断数据。

---

## 6. 统一 Trace Context 结构

第一阶段建议使用轻量 helper 生成 trace context，避免每个调用点手写同一组字段。

建议文件：

```text
backend/app/services/audiobook/task_trace.py
```

建议职责：

1. 从任务、章节 run、显式参数中构造 trace context。
2. 合并到 `detail_json`，只追加字段，不覆盖现有业务字段。
3. 为日志提供结构化 extra 字典。

建议最小函数：

```python
def build_audiobook_trace_context(
    *,
    trace_id: str | None = None,
    celery_task_id: str | None = None,
    task_db_id: int | None = None,
    task_type: str | None = None,
    audiobook_project_id: int | None = None,
    chapter_id: int | None = None,
    run_id: int | None = None,
    stage: str | None = None,
    status: str | None = None,
    progress: float | None = None,
    tts_model: str | None = None,
) -> dict[str, object]:
    ...
```

合并规则：

- `trace_id = trace_id or celery_task_id`
- 值为 `None` 的字段不写入。
- 不修改传入的原始 `detail`。
- 当现有 detail 已有同名业务字段时，不改变原有含义。
- 第一阶段可把 trace 字段放在顶层，优先兼容现有前端读取方式；如后续字段增加，再考虑 `detail["trace"]` 子对象。

---

## 7. 第一阶段试点

推荐先在项目导出任务试点，而不是直接改全量生成链路。

推荐入口：

- `audiobook.export_m4b`
- `audiobook.export_audacity`
- `build_project_export_task_detail()`
- `_run_project_export_task()`

理由：

1. 导出任务 stage 单一，状态模型简单。
2. 已有集中 detail builder，改动面小。
3. 不直接影响多章节 TTS、断点恢复和章节并发。
4. 更容易写 focused pytest。

试点内容：

1. 新增 `task_trace.py` 纯 helper。
2. `build_project_export_task_detail()` 接收可选 trace context 或 trace 字段参数。
3. 导出任务 detail 中增加：
   - `trace_id`
   - `celery_task_id`
   - `task_db_id`
   - `task_type`
   - `audiobook_project_id`
   - `stage`
   - `status`
4. SSE data 结构保持不变，只让 `data.detail` 中出现新增兼容字段。
5. 补充导出 detail builder 测试，证明旧字段仍存在，新字段按预期出现。

暂不试点：

- 多章节 `audio_from_scripts` 全链路。
- 积分冻结链路全量改造。
- 前端任务 UI 新增 trace 展示。
- 数据库 schema 变更。

---

## 8. 后续扩展顺序

完成导出任务试点并通过测试后，再按风险从低到高推进：

1. `run_script_only`：脚本生成链路，章节运行态压力低于音频生成。
2. `run_audio_from_scripts`：音频生成链路，涉及 TTS、断点和分段进度，需要更完整测试。
3. `run_full`：全流程生成链路，最后统一。
4. `failure_diagnostics.py`：把 `trace_id` 写入失败诊断摘要。
5. 积分冻结：冻结事件 payload 可先接入 `trace_id` / `celery_task_id` / `task_type` 等已稳定字段；`cost_precheck_id`、`billing_freeze_event_id` 仅在可稳定获取时接入。

每一步都应保持：

- 只增量加入字段。
- 不改变既有字段含义。
- 不把日志字段强行塞进 `detail_json`。
- 不扩大 `checkpoint_json` 的职责。

---

## 9. 兼容策略

必须保持兼容：

- `AudiobookTask.as_dict()` 仍返回 `detail: self.detail_json or {}`。
- SSE data 仍保持 `stage`、`progress`、`detail`、`status`、`error_message`。
- 前端仍可通过 `/tasks/{task_id}/stream` 和 polling fallback 获取状态。
- 现有 `detail_json.stages`、`download_url`、`export_result` 等字段不改名。

允许新增：

- `detail.trace_id`
- `detail.celery_task_id`
- `detail.task_db_id`
- `detail.task_type`
- `detail.run_id`
- `detail.chapter_id`
- `detail.tts_model`
- `detail.cost_precheck_id`
- `detail.billing_freeze_event_id`

新增字段必须满足：

- 缺失时前端不报错。
- 历史任务没有这些字段时仍可展示。
- 字段值不能依赖外部服务实时查询。

---

## 10. 测试建议

第一阶段实现时至少补充：

1. `task_trace.py` 纯函数单元测试：
   - `trace_id` 复用 `celery_task_id`
   - `None` 字段不输出
   - 不修改输入 detail
   - 已有字段不被意外覆盖
2. `project_export_jobs.py` 测试：
   - 旧字段仍完整存在
   - 新 trace 字段按传入参数出现
   - error detail 仍保留 `error_message`
3. 如改动 `AudiobookJobTracker`：
   - SSE payload 外层结构不变
   - `detail` 中新增字段不会覆盖已有 detail

建议命令：

```bash
python -m pytest "backend/tests/test_audiobook_project_exporter.py" -q
```

如新增独立 helper 测试：

```bash
python -m pytest "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q
```

---

## 11. 验收标准

方案阶段验收：

- 已明确 `celery_task_id` 作为第一阶段 `trace_id`。
- 已明确日志、`detail_json`、`checkpoint_json` 的职责边界。
- 已选定项目导出任务作为低风险试点。
- 已明确不新增数据库字段、不改 SSE 协议、不改前端展示语义。

试点实现验收：

- 导出任务 detail 中出现兼容 trace 字段。
- 旧导出字段和前端状态展示不受影响。
- focused pytest 通过。
- 没有新增外部依赖。
- 没有执行数据库迁移。

---

## 12. 后续决策点

试点完成后再判断是否继续扩大范围：

- 如果 trace 字段能显著缩短排障路径，再接入脚本生成和音频生成任务。
- 如果字段开始膨胀，优先收紧日志/detail/checkpoint 边界，而不是新增更多嵌套结构。
- 如果需要跨服务全链路追踪，再单独评估 OpenTelemetry；当前阶段不提前引入。

---

## 13. 试点落地记录

日期：2026-05-05

已完成低风险导出任务试点：

- 新增 `backend/app/services/audiobook/task_trace.py`：
  - `build_audiobook_trace_context()` 统一构造 trace context。
  - `merge_audiobook_trace_context()` 将 trace context 增量合并到 detail，且不覆盖已有 detail 字段。
- 更新 `backend/app/services/audiobook/project_export_jobs.py`：
  - `build_project_export_task_detail()` 增加可选 `trace_context` 参数。
  - 保持 `audiobook_project_id`、`export_type`、`download_url`、`current_stage`、`stages`、`export_result`、`error_message` 等既有字段不变。
- 更新 `backend/app/tasks/audiobook_tasks.py`：
  - `export_m4b` / `export_audacity` 的 running、completed、failed detail 均传入 trace context。
  - trace 字段包括 `trace_id`、`celery_task_id`、`task_db_id`、`task_type`、`audiobook_project_id`、`stage`、`status`、`progress`。

已补测试：

- `backend/tests/test_audiobook_task_trace.py`
- `backend/tests/test_audiobook_project_exporter.py`

验证命令：

```bash
python -m pytest "backend/tests/test_audiobook_task_trace.py" "backend/tests/test_audiobook_project_exporter.py" -q
```

结果：20 passed。

后续增量记录：

- 2026-05-05：`run_script_only` 初始 `script_adaptation` detail 已接入 trace context，字段包括 `trace_id`、`celery_task_id`、`task_db_id`、`task_type`、`audiobook_project_id`、`chapter_ids`、`chapter_total`、`stage`、`status`、`progress`、`tts_model`。本次只覆盖任务初始 detail，不改后台内部阶段。
- 2026-05-05：`run_audio_from_scripts` 初始 `tts_synthesis` detail 已接入 trace context，字段与 `run_script_only` 初始 detail 保持一致。本次只覆盖任务初始 detail，不改音频生成后台内部阶段。
- 2026-05-05：`run_full` 初始 `initializing` detail 已接入 trace context，字段与其他生成入口保持一致。本次只覆盖任务初始 detail，不改完整生成后台内部阶段。
- 2026-05-05：`failure_diagnostics.py` 已在失败诊断摘要中新增 `trace_id`，优先使用显式 `task_id`，再从 `result` 和 `resume_checkpoint` 的 `trace_id` / `celery_task_id` / `task_id` / `engine_task_id` 继承；既有 `engine_task_id` 保持不变。
- 2026-05-05：积分冻结事件 payload 已接入 trace context。创建项目、已有脚本生成音频、断点续跑三个排队入口在 `_enqueue_audiobook_task()` 后复用 `async_result.id` 构造 `trace_id` / `celery_task_id`，并写入 `record_audiobook_billing_freeze()` 的 `extra_payload`。底层只允许 trace 诊断字段进入冻结日志 payload，不允许覆盖金额、项目、章节、pricing、operating snapshot 等账务字段。
- 2026-05-05：`AudiobookJobTracker.update_stage()` 已在后台内部阶段集中合并 trace context。写入 `AudiobookTask.detail_json` 前从任务记录和阶段参数补齐 `trace_id` / `celery_task_id` / `task_db_id` / `task_type` / `audiobook_project_id` / `chapter_id` / `stage` / `status` / `progress`，同时让 SSE `data.detail` 和 `ChapterAudioRun.checkpoint_json.tracker_detail` 共享同一批兼容字段；SSE 外层结构不变，既有 detail 同名字段不被覆盖。

仍未扩展的范围：

- 未改积分预检链路。
- 未在冻结事件落库后反写 `billing_freeze_event_id`。
- 未改前端展示逻辑。
- 未改数据库 schema。
- 未改 SSE data 外层结构。
