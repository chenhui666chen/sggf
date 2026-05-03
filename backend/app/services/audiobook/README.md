# 有声书生成系统

更新时间：2026-05-03

## 模块定位

有声书模块负责把小说章节转换为可播放、可导出、可恢复的章节音频。当前能力已经覆盖后端 Web API、前端管理页、Celery 后台任务、SSE 实时进度、剧本编辑/评审、断点恢复、章节音频结果、字幕生成、整本导出和可选 AI 配乐。

早期文档中的“Web API、前端管理界面、实时进度推送仍是下一步”已经过期；这些能力现在是主链路的一部分。

## 当前能力

| 能力 | 当前状态 | 主要入口 |
| --- | --- | --- |
| 完整生成 | 已实现 | `AudiobookEngine.generate_chapter_audio()`、`audiobook.run_full` |
| 仅生成剧本 | 已实现 | `generate_audiobook_scripts_background()`、`audiobook.run_script_only` |
| 基于已审核剧本生成音频 | 已实现 | `generate_audiobook_audio_from_scripts_background()`、`audiobook.run_audio_from_scripts` |
| 角色音色与旁白风格 | 已实现 | `voice_manager*.py`、`narration_styles.py`、前端音色配置面板 |
| TTS 模型适配 | 已实现 | `tts_engine.py`、`tts_engine_pkg/`、`tts_model_ids.py` |
| 音频混合与最终评审 | 已实现 | `audio_mixer.py`、`engine_pkg/_review_mixin.py` |
| 字幕与试听预览 | 已实现 | `subtitle_generator.py`、`preview_generator.py`、相关 API 路由 |
| 任务状态与实时进度 | 已实现 | `AudiobookTask`、`AudiobookJobTracker`、`sse_progress.py` |
| 章节 run 与断点恢复 | 已实现主链路 | `ChapterAudioRun`、`task_support.py`、`temp_segment_store.py` |
| 整本 M4B/Audacity 导出 | 已实现 | `project_exporter.py`、`project_export_jobs.py` |
| 可选 AI 配乐 | 已实现基础生成与缓存 | `ai_music.py`、`agents/music_composer.py` |

## 架构概览

```text
API / Frontend
  -> task_support.enqueue_audiobook_task()
  -> AudiobookTask + ChapterAudioRun
  -> Celery audiobook task
  -> background_jobs_* orchestration
  -> AudiobookEngine
  -> ScriptAdapter / VoiceManager / TTSEngine / AudioMixer
  -> ChapterAudio + ChapterAudioRun checkpoint
  -> SSE progress + polling fallback
```

核心边界：

- API 层负责鉴权、参数校验、项目/章节读取和任务入队。
- `task_support.py` 负责创建任务、预生成 Celery task id、预创建章节 run、构建和校验恢复 checkpoint。
- Celery worker 只执行后台任务，不再依赖 FastAPI 进程内状态。
- `AudiobookJobTracker` 负责同步 `audiobook_tasks`、关联章节 run 和 SSE 事件。
- `AudiobookEngine` 负责剧本、TTS、混音、评审等生成逻辑。

## 任务与恢复

任务状态分两层：

- `AudiobookTask`：面向任务列表、当前任务焦点和 SSE/polling 的顶层任务记录。
- `ChapterAudioRun`：面向单章节恢复、失败诊断、临时 segment 资产和 checkpoint 的章节运行记录。

入队顺序已经收口为：

1. 创建 `AudiobookTask`。
2. 预生成 Celery task id。
3. 写入 `AudiobookTask.celery_task_id`。
4. 为章节预创建 `ChapterAudioRun` 和初始 checkpoint。
5. 如需恢复，在投递前绑定恢复 checkpoint。
6. 调用 `apply_async(task_id=...)` 投递 Celery 任务。

顶层失败会同步收敛同一 `celery_task_id` 下仍未完成的章节 run，避免恢复检查看到悬挂的 `queued`/`running` 状态。已完成或已有章节级失败诊断的 run 不会被覆盖。

## 前端与 API

主要后端路由位于 `backend/app/api/v1/audiobook_api/`，前端主页面位于 `frontend/src/pages/AudiobookPage.tsx` 和 `frontend/src/pages/audiobook/`。

常用接口类型：

- 项目创建与详情：`/api/v1/audiobook/projects`
- 剧本生成、评审和编辑：`routes_script.py`、`routes_review.py`
- 音频生成与恢复：`routes_projects.py`、`routes_subtitle.py`
- 任务列表和任务状态：`routes_tasks.py`
- SSE 实时进度：`/api/v1/audiobook/tasks/{task_id}/stream`
- 章节音频下载/播放/导出：`routes_download.py`、`project_exporter.py`

前端任务同步使用 SSE 为主、轮询兜底；SSE effect 不依赖整个任务 map，避免高频 progress 更新导致连接反复重建。

## 配置

常用环境变量：

| 变量 | 用途 |
| --- | --- |
| `DASHSCOPE_API_KEY` | 阿里云百炼/CosyVoice 等 DashScope 能力 |
| `CELERY_BROKER_URL` | Celery broker，通常为 Redis |
| `CELERY_RESULT_BACKEND` | Celery result backend，通常为 Redis |
| `AUDIOBOOK_TTS_CACHE_TTL_SECONDS` | 可选，TTS 音频缓存 TTL，默认 7 天 |
| `AUDIOBOOK_TTS_CACHE_MAX_SIZE` | 可选，TTS 内存缓存最大条目数，默认 500 |
| `AUDIOBOOK_TTS_CACHE_REDIS_ENABLED` | 可选，是否为 TTS 音频缓存启用 Redis 二级缓存，默认关闭 |
| `AUDIOBOOK_TTS_CACHE_REDIS_URL` | 可选，TTS 音频缓存 Redis 地址 |
| `MUREKA_API_KEY` | 可选，Mureka AI 配乐；缺失时走模拟/降级路径 |
| `MUREKA_MAX_CONCURRENT` | 可选，Mureka 并发上限，默认 1 |
| `MUREKA_WATERMARK_TRIM` | 可选，Mureka 音频尾部水印裁剪秒数 |

## 已知边界

- 细粒度 UI 临时态已覆盖评审弹窗、已选问题、已选片段、编辑器展开片段和审查上下文；真实 DOM 菜单锚点不做跨刷新持久化。
- 跨标签页草稿冲突当前保留显式选择，不做自动合并，避免误覆盖用户草稿。
- segment 级 checkpoint 已支持恢复材料校验、缓存复用、内容摘要校验、失败片段原因记录和只重试失败/缺失 segment；provider 已接收但未返回可用音频时的实际扣费不可由本地 checkpoint 反推，已通过 TTS 统计字段与内部估算分离。
- TTS 音频缓存按模型、provider、音色参数、情绪、规范化文本和校验版本隔离；缓存命中仍会执行输出校验，校验失败会删除缓存并重新合成。
- AI 配乐是可选增强能力，不应成为主音频生成链路的硬依赖。

## 验证入口

后端最小回归：

```powershell
.\.venv\Scripts\python.exe -m pytest "backend/tests/test_audiobook_job_tracker.py" "backend/tests/test_audiobook_task_enqueue_order.py" "backend/tests/test_audiobook_runtime_truth.py" "backend/tests/test_audiobook_failure_diagnostics.py" "backend/tests/test_audiobook_final_audio_review.py"
```

前端检查：

```powershell
cd frontend
npm run type-check
npx vitest run "src/pages/audiobook/__tests__/taskPollingSource.test.ts" "src/pages/audiobook/__tests__/taskUtils.test.ts" "src/pages/audiobook/__tests__/taskSessionStorageUtils.test.ts"
```
