# 有声书双引擎隔离与场景编辑器实施进度（PROGRESS）

> 依据：docs/AUDIOBOOK_ENGINE_ISOLATION_AND_SCENE_EDITOR_IMPLEMENTATION_GUIDE_20260811.md（R22，实施基线）
> 本文档为滚动状态层：只记录执行状态、决策与阻塞，不承载设计事实；设计事实以 GUIDE 为唯一来源。
> 实证承载：真实测试输出、迁移报告与验证 SQL 结果记录于 §5 验证记录。

## 1. 三层文档架构

| 层 | 文件 | 职责 | 更新边界 |
|---|---|---|---|
| GUIDE（设计源） | AUDIOBOOK_ENGINE_ISOLATION_AND_SCENE_EDITOR_IMPLEMENTATION_GUIDE_20260811.md | 稳定设计合同 | 仅三类变更可修改：设计合同变更、供应商能力证伪、架构缺陷暴露 |
| PROGRESS（本文档） | 本文件 | 滚动执行状态 | 随实施推进更新 |
| VALIDATION_RECORDS | 本文档 §5 + 测试文件 | 实证承载 | 真实 PostgreSQL 测试输出、迁移报告、验收 SQL 结果 |

## 2. 实施基线约定

1. **canonical_hash 窄职责**：只承担基础设施层职责，不得包含业务对象识别、checkpoint 查询或迁移调度逻辑。
2. **migration_input_hash 版本化**：固定字段为旧/新 checkpoint 身份、schema/version、migration version、确定性输入摘要，必须测试。
3. **按域立项**（GUIDE §1 拆分路线图）：实施按四域推进——①双引擎配置/批次/快照隔离；②场景 revision/编辑器/发布模型；③run 派发/worker lease/恢复协议；④计费 ledger/mutation service/finalizer。本轮先落地 ①/④ 共享的 Phase 1.1 Expand schema 基础。

## 3. 阶段状态表

状态值域：未开始 / 进行中 / 阻塞 / 待验收 / 已完成 / 已回滚

| 阶段 | 内容 | 状态 | 备注 |
|---|---|---|---|
| 1.1-Expand-进度表 | `audiobook_canonical_migration_progress` 模型+迁移+fail-closed 合同 | 已完成 | R22/P1-1/P1-2/P1-3 合同落点；迁移已应用 |
| 1.1-Expand-audiobook 域 | AudiobookProject/ChapterAudio/ChapterAudioRun/AudiobookTask 新列（可空宽态） | 已完成 | Expand 不收紧任何约束 |
| 1.1-Expand-新表 | scene_edit_revisions/heads、scene_audio_artifacts、ledger_reconciliation_audits、chapter_audio_outputs、task_dispatches、provider_capabilities | 已完成 | 含 append-only trigger |
| 1.1-Expand-billing | billing_usage_ledger 模型与 run 计费封口列 | 已完成 | R18/P2 不可变 trigger |
| 1.1-Migrate | canonical 去重合并执行器（事务 A/B、会话锁、断点续跑）+ 迁移报告与一致性门禁 | 已完成 | 真实 PostgreSQL 测试强制；执行器 11 项 + 报告 4 项全绿 |
| 1.1-Migrate-历史回填 | engine_mode/快照/run_engine_mode_snapshot/chapter_audio_id synthetic/celery_task_id/dispatch_status 幂等回填 | 已完成 | `history_backfill.py`，7 项合同测试全绿，dev 库已执行且二次执行全 0 |
| 1.1-Contract | 唯一索引/NOT NULL/CHECK 收窄 | 已完成 | 门禁化收窄已施加于 dev 库（见 §5.6）；部分项依赖新写路径代码，明确暂缓（见 §5.6 暂缓清单） |
| 1.2-引擎分支服务 | `project_audio_config.py` 引擎分支化核心服务（get/set_engine_branch、resolve_engine_mode、scene_generation_preferences、snapshot builder） | 已完成 | 43 项纯 Python 单元测试全绿 |
| 1.2-运行时改造 | `project_audio_runtime.py` 运行时解析器增加 engine_mode 参数 + resolve_from_snapshot/resolve_from_run_input | 已完成 | 向后兼容（engine_mode=None 保持旧行为） |
| 1.3-API 合约 | `projects.py` Pydantic 模型扩字段（CharacterAudioConfig +3、新增 EngineBranchConfig/SceneGenerationPreferences/EnginePreferencesResponse）+ 路由引擎分支读写 | 已完成 | 7 项真实 PG 测试全绿；GET/PUT audio-config 按引擎分支读写；新增 GET engine-preferences 端点 |
| 1.4-批次创建冻结 | `app_service.py` 创建批次替换硬编码 engine_mode 为 `resolve_engine_mode`；写入 `engine_config_snapshot`+`engine_config_fingerprint`；`snapshot_status='frozen'`；`task_support.py` billing_context 改由 `resolve_engine_mode` 驱动 | 已完成 | auto 在计费前解析（GUIDE §1.4）；创建/恢复/字幕链路自动受益 |
| 1.5-消费方快照化 | `background_jobs_full/audio` 运行时配置优先从 `engine_config_snapshot` 解析（回退实时）；`routes_segment_preview` 同改造；`background_jobs_scripts` 删除 voice_mapping 写回路径 | 已完成 | 优先级子集；remix/tasks/subtitle 等后续排期 |
| 1.6-章节状态按引擎过滤 | `list_audiobook_projects` 增加 `engine_mode` 查询参数过滤；返回结构增加 `engine_mode`；`_serialize_chapter_audio_summary` 增加 `render_status`/`render_status_detail` | 已完成 | 不传时行为不变（兼容） |
| 2.1-引擎选择器上移 | 引擎选择器移至章节队列卡片顶部（SetupStep/NarrationAudioConfigPanel） | 已完成 | GUIDE §2.1 |
| 2.2-音色绑定按引擎分支持久化 | payload 输出 `engines` 分支（buildProjectAudioConfigPayload）+ 分支读取回退（resolveBranchSavedCharacters）+ 切换引擎重载（useAudiobookVoiceActions/buildInitialProjectVoiceSettings） | 已完成 | GUIDE §2.2 |
| 2.3-章节状态按引擎过滤与结构化 | `isChapterGeneratedForEngine` 双引擎完成条件 + `resolveChapterStateById` 结构化状态（renderStatus/executionStatus/locked/exportable） | 已完成 | GUIDE §2.3/验收 9 |
| 2.4-生成编排入口分流 | `_generation`/`_audio_from_script`/`_parallel` mixin 按引擎分支：seed_scene 跳过 AudioDirector 策略与音效配乐应用（strategy=None + strategy_skipped 指标 + director_style 容错），prepare_render_assets 恒 False | 已完成 | GUIDE §2.4 |
| 2.5-三维投影与幂等发布协议 | `aggregate_scene_render_status`（Seed 四态聚合）+ run 投影写入（result_render_status/detail 随终态，无论是否发布）+ `chapter_output_publish.py` 幂等完整发布协议（锁行/幂等短路 R9 一致性检查/前置校验/CAS 镜像列/supersede/published 单事务） | 已完成 | GUIDE §2.4 规则 4；artifact 状态机留待阶段 3 |
| 3.1-点击章节分流 | `handleOpenGeneratedChapter` 按 §2.5 规则定位批次（返回 engine_mode/render_status，替换"取第一个"）；legacy_stems → 剧本编辑器，seed_scene → 场景编辑器 + 批次切换器（多批次时） | 已完成 | GUIDE §3.1 |
| 3.2-后端场景编辑接口 | `routes_scene_editor.py`：editor-document 聚合 + 三类编辑（dialogue/director_override/voice_binding 双写）+ dialogue-review 审批端点 + 旧 script 直写拒绝 + 媒体授权 | 已完成 | GUIDE §3.2；19 项 API 测试全绿 |
| 3.3-SceneEditorDocument | 稳定投影模型（三维投影命名统一 R9/R10、last_revisions 三条链、scene_audio_url 授权） | 已完成 | GUIDE §3.3 |
| 3.4-artifact 登记与试听 | `SceneAudioArtifact` 登记（staged，含 chapter_audio_id 作用域）+ 发布事务内状态机（active/superseded）+ stream/audit-stream 端点 | 已完成 | GUIDE §3.4；audit-stream 归属校验 bug 已修复（见 §5.10） |
| 3.5-前端场景编辑器 | `SceneChapterEditor.tsx` 三段式编辑（台词/导演覆盖/音色）+ 409 冲突提示 + 试听 + 批次切换器 | 已完成 | GUIDE §3.5；标题展示章节序号（回退内部 id） |
| 3.6-路由注册 | 新端点挂载到 audiobook 路由（前缀 /audiobook，与既有命名空间一致） | 已完成 | GUIDE §3.6 |
| 3.7-重渲染入口 | `routes_projects.py` generate-audio-from-scripts 携带 `revision_set_hash` 时校验与当前编辑基线一致（失配 409 + `current_revision_set_hash`），三条链 head 投影透传 enqueue 冻结进 `run_input_snapshot`；前端 `SceneChapterEditor` 「重渲染整章」按钮（approved + hash 双条件启用） | 已完成 | GUIDE §3.2/验收 8；真实 API + 浏览器 E2E 验证（§5.11） |
| 4.1-run_input_snapshot 恢复链 | `task_support.py` `build_run_input_snapshot_for_chapter`（方案 A 自包含正文：audio_from_scripts 内嵌 script_facts + revision 投影，full/script_only 内嵌 source_chapter_content）+ `_build_resume_input_context` 恢复只消费快照不读实时值 | 已完成 | 验收 8/19；并发编辑下恢复仍按快照（§5.11） |
| 8.3-artifact/输出保留清理 | `scripts/cleanup_expired_artifacts.py`：superseded/staged 超 30 天删物理文件 + 墓碑（file_status='purged'）；published 与 published_run_id 镜像引用禁止清理；共享路径防误删 | 已完成 | GUIDE §8.3；dry-run 真实 PG 验证（§5.11） |
| 5.1-dispatch_service | `dispatch_service.py` 可靠派发服务：dispatcher CAS 租约认领 stale pending run + worker 租约协议（acquire/heartbeat/reclaim）+ 条件补偿 + beat 定时任务（每 2 分钟） | 已完成 | GUIDE §5 六步第 4 步/R10/R11；34 项合同测试全绿（§5.12） |
| 5.2-task_aggregation | `task_aggregation_service.py` 父任务聚合：normalize_run_status 投影 + 六条互斥矩阵穷尽规则 + refresh 持久化 | 已完成 | GUIDE R13/P0-a/R17/P1-2；13 项投影 + 10 项矩阵测试全绿（§5.12） |
| 5.3-ledger_transition | `ledger_transition_service.py` 统一 ledger 转态：pending 创建（幂等）→ succeeded/confirmed_failed/manual_reconciliation + 终态关账 + strict barrier | 已完成 | GUIDE R17/P1-4/R11/P1-2；4 项转态 + 3 项 barrier 测试全绿（§5.12） |
| 5.4-billing_finalizer | `billing_finalizer_service.py` 统一 finalizer：try_finalize_run（终态+无有效 lease+barrier+未封口）+ beat 扫描器（每 3 分钟）+ settle 幂等 | 已完成 | GUIDE R17/P0/R18/P0；4 项前置条件测试全绿（§5.12） |
| 5.5-provider_capability | `provider_capability_service.py` 供应商派发能力配置：seed/query + 6 个已知供应商 | 已完成 | GUIDE R11/P1-3（§5.12） |
| 5.6-reconcile_api | `admin/billing.py` 人工收敛端点 `POST /ledger/{ledger_id}/reconcile`：无锁预读仅路由 → run FOR UPDATE → ledger FOR UPDATE 锁后重读 → CAS → 审计 → finalizer 联动 | 已完成 | GUIDE R15/P1-4/R21/P2-3；三层锁序（§5.12） |
| 5.7-celery_beat | `celery_app.py` beat_schedule 新增 `audiobook-dispatch-stale-pending`（*/2 min）+ `audiobook-billing-finalizer-scan`（*/3 min） | 已完成 | GUIDE R11/R18（§5.12） |
| 5.8-billing_snapshot | `billing_snapshot_builder.py` 计价快照构建器：usage_kind→pricing_key→unit 唯一映射表（四处同源）+ 单价解析（tts 元/万字符→元/字符、seed 元/秒）+ 金额计算 + 积分换算 | 已完成 | GUIDE 验收 19/23，R18/P1-3（§5.13） |
| 5.9-入队接入 | `task_support.py` 入队写派发意图（每 run 独立 celery_task_id + dispatch_status/attempts/next_dispatch_at/predecessor_run_id）+ 入队事务内锁定唯一 active ChapterAudio（R10/P0-4）+ TaskDispatch 父子关系 + billing_snapshot/billing_account_user_id 冻结 + 批量 apply_async 三态（成功 dispatched/明确失败条件补偿） | 已完成 | GUIDE §1.4/R10/R11（§5.13）；真实 API + PG E2E 26/26 |
| 5.10-逐run任务 | `audiobook_tasks.py` 新增 `audiobook.run_chapter_dispatch`：CAS 租约认领 + 心跳线程续租（R12/P0-1）+ 按 run_type 执行现有 background 单章 + 终态处理（清租约/关账/finalizer/父聚合） | 已完成 | GUIDE R10/P0-2/R11/P1-1/R18/P0（§5.13） |
| 5.11-派发修正 | `dispatch_service.py`：任务映射统一到逐 run 任务 + `clear_worker_lease` + dispatched 未认领超时重投（R12/P1-5） | 已完成 | GUIDE R12/P1-5（§5.13） |
| 5.12-finalizer修复 | `billing_finalizer_service.py`：`_execute_settle` 接口修复（原调用签名不匹配 TypeError→永远 settle 失败）+ run/批次级 key 兼容回退 + 金额按计价快照计算 + `try_finalize_run` 账户 advisory 锁前置（R21/P2-3 无锁预读仅路由） | 已完成 | GUIDE R14/P1-e/R17/P1-3/R19/P0（§5.13） |
| 5.13-终态接入 | `update_chapter_run_state` 终态分支清租约 + 按证据关账（R18/P0）；结算由逐 run 任务外层 / beat 扫描器在账户锁内执行 | 已完成 | GUIDE R18/P0（§5.13） |
| 5.14-前端穷举映射 | `StageStatus` 联合类型新增 cancelled/completed_with_partial_failure（types.ts）+ STAGE_STATUS_LABELS（constants.ts）+ STAGE_STATUS_COLORS（TaskStageDetails）+ audiobookTheme.taskStatus 颜色角色 + coerceStageStatus 识别 | 已完成 | GUIDE R15/P1-3 验收 81（§5.14）；tsc 0 错误 + 5 项测试 |
| 5.15-真实PG并发测试 | `test_audiobook_domain34_concurrency_contract.py`：验收 48（并发唯一 active，仅一个成功 + loser IntegrityError）+ 验收 83（worker 终态关账 × 人工收敛同一 ledger，无死锁仅一方生效） | 已完成 | GUIDE R10/P0-4/R17/P0/R20/P1-1（§5.14）；修复模型缺部分唯一索引声明 |
| 5.16-remix发布接入 | `publish_legacy_chapter_output`（R9/P0-2 legacy 发布谓词：锁行/幂等短路/staged 恰一条/CAS 镜像列/supersede）+ `build_chapter_audio_output_path` run 级路径 + remix 删除直写改 on_output_ready 登记发布 + 运行时改从批次快照解析 | 已完成 | GUIDE §1.5/验收 30/R8（§5.14）；6 项 legacy 发布测试全绿 |
| 5.17-恢复快照化 | `routes_tasks.py` 恢复预检/配置改从 run_input_snapshot（run_options/engine_mode 冻结值优先，无快照回退 run 列/实时）+ `routes_segment_regen.py` 两处运行时改从批次快照解析（无快照回退实时） | 已完成 | GUIDE §1.5/验收 8/19（§5.15） |
| 5.18-恢复证据服务 | `ledger_recovery_service.py`：persist_result_url_evidence（encrypted_result_url/persisted_at/commit_stage=result_persisted）+ decide_recovery_method（request_query/temporary_url/replay/manual 按实际证据决策，能力快照优先，禁止用当前配置解释历史调用） | 已完成 | GUIDE R12/P1-3/R13/P0-b 验收 70（§5.15）；8 项测试 |
| 5.19-synthetic回填 | `synthetic_migration_run_backfill.py`：历史产物归属回填（有匹配 completed run → published_run_id + published 输出 + legacy_unverified；无 → migration_placeholder synthetic run 不可恢复/结算/重试/派发） | 已完成 | GUIDE R9/P1-1/R10/P1-1 验收 38/50（§5.15）；4 项测试 |
| 5.20-job_id/SSE | `AudiobookTaskStatus.job_id = task:{id}` 命名空间 + `get_task_for_user` 兼容 task:{id} 与 celery_task_id 双解析 + SSE 事件 data 携带 run_id（detail 透传）与 job_id | 已完成 | GUIDE R13/P1-a 验收 56/68（§5.15）；真实 API 验证 task:65 解析 200 |
| 5.21-token fencing | `dispatch_service.py` 结果回写（success/unknown/补偿）全部加 `dispatch_claim_token` CAS 条件——迟到 dispatcher 返回/补偿被拒绝，接管者状态保持 | 已完成 | GUIDE R14/P1-d 验收 76（§5.16）；真实 PG 双 dispatcher 测试 |
| 5.22-崩溃窗口测试 | `test_audiobook_domain34_concurrency_contract.py` 新增验收 52：供应商成功本地未落账崩溃 → 恢复按 attempt_key 幂等补录 succeeded，无重复入账 | 已完成 | GUIDE R10/P1-3 验收 52（§5.16） |
| 5.23-legacy展示投影 | `routes_tasks._resolve_resume_source_run` 优先按 AudiobookTaskDispatch 父子关系定位（纯 DB 投影），历史 run 回退 celery_task_id | 已完成 | GUIDE R13/P1-a 验收 66（§5.16） |
| 5.24-复制合同 | `chapter_script_copy_service.py`：copy_approved_script（source_script_hash/source_script_review_version/source_provenance_json 持久化 + 保持 approved + 幂等） | 已完成 | GUIDE §2.1 验收 25（§5.16）；3 项测试 |
| 5.25-分阶段checkpoint | `derived_facts_service.py`：derived_execution_facts 三子项冻结（append-only）+ 恢复阶段决策 + 子项 hash 独立校验；`background_jobs_full` 完成写回点冻结接入（可提取子项才冻结，不阻塞） | 已完成 | GUIDE R9/P0-4/R10/P1-2 验收 37/51（§5.16）；10 项测试 |
| 5.26-ledger历史清洗 | `ledger_history_cleanup.py`：succeeded 缺定价事实从 run_input_snapshot 确定性恢复（snapshot_id+prices 匹配）或显式转 manual_reconciliation；unit 变体归一化（second/char）无法归一转人工；幂等 | 已完成 | GUIDE R17/P1-4 验收 85（§5.17）；5 项测试 |
| 5.27-Contract收尾迁移 | `contract_audiobook_isolation_finalize.py`：snapshot_status/chapter_audio_id/celery_task_id NOT NULL + celery UNIQUE + tasks CHECK stage2 收窄（fail-closed 数据门禁）；历史回填已执行（chapter_audio_id 9/snapshot 2/celery 1） | **已完成（用户沙箱外执行）** | GUIDE §1.1/R14/P1-b 验收 66/74（§5.17）；alembic current = contract_audiobook_isolation_finalize (head)；写路径兼容修复后 E2E 26/26 |
| 5.28-收窄兼容修复 | 收窄暴露创建路径缺口：`create_run`/`create_runs` 缺 chapter_audio_id 参数（INSERT 撞 NOT NULL）；`enqueue_chapter_runs` 创建前预解析 active ChapterAudio 随 INSERT 落库；`update_chapter_run_state`/`job_tracker` 兜底创建同样补齐 | 已完成 | Contract 收窄后写路径兼容（§5.17）；215 项回归 + E2E 26/26 |
| 5.29-逐run派发cutover | `enqueue_audiobook_task` 移除批量 signature.apply_async，改为逐 run `try_dispatch_run`（每 run 独立消息 + 独立固定 celery_task_id）；async_result 兼容为父任务 id 占位；失败由 dispatcher beat 兜底 | 已完成 | GUIDE R10/P0-2 验收 47（§5.18）；E2E 26/26 |
| 5.30-入队冻结同事务 | R10/P0-3 + R11/P0-2：`enqueue_chapter_runs` 移除内部 commit（只 flush）；`safe_record_audiobook_billing_freeze` 增加 `raise_on_error`（失败抛→整体回滚）；`lock_billing_account` 账户锁 helper（非 PG 降级 no-op）；7 个调用方（routes_projects ×2/routes_tasks/routes_recover ×3/routes_subtitle）全部改同事务模式（账户锁→enqueue(commit_result=False)→freeze(raise_on_error=True)→统一 commit） | 已完成 | GUIDE R10/P0-3/R11/P0-2 验收 45/55（§5.18）；事务回滚验证 + E2E 26/26 |
| 5.31-派发时序修复 | **真实 worker 暴露竞态**：同事务模式下 try_dispatch_run 在事务提交前 send_task → worker 消费时 run 未提交为 dispatched → 租约认领失败（run 卡 dispatched+queued）；修复：enqueue 不再事务内派发（run 保持 pending 落库），新增 `dispatch_pending_runs`（提交后逐 run 即时派发，best-effort），7 个调用方 commit 后显式调用；失败由 dispatcher beat 兜底 | 已完成 | GUIDE R11/P0-1（先落库后投递）（§5.18）；真实 worker 日志验证 + E2E 26/26 |
| 5.32-阶段进度持久化回归 | **真实任务暴露回归**：cutover 后 `run_chapter_dispatch_task` 传 tracker=None → 引擎阶段事件不写父任务 detail_json.stages → 前端阶段网格永远“等待中”，且协作暂停（pause_check_fn）与父任务 mark_running 失效；修复：① tracker 经 AudiobookTaskDispatch（run_id→task_id）解析父任务（outbox 下 run.celery_task_id 是每 run 独立 uuid，不能作查找键），mark_running 传父任务自身 celery_task_id（SSE key）；② `acquire_worker_lease` coalesce 写 run.started_at（首次认领记录，接管不覆盖） | 已完成 | 真实 DB 复核（run 120→task 74 命中）；audiobook 回归 1820 通过（4 项存量失败与本次无关） |
| 5.33-legacy混音音量一致性修复 | **用户反馈角色对白比旁白小 + BGM 偏大**（项目 84 实测整章 -21.5 LUFS/LRA 12.5，配乐母带 -14.6 LUFS）；修复：① `audio_mixer` 新增逐段响度对齐 `_match_segment_loudness`（拼接前拉齐到 -20dBFS 基准，±1dB 死区 + 提升上限 12dB + 峰值 -1dB 保护），消除多供应商 TTS 原生响度差并恢复 ducking 阈值有效性；② `_normalize_loudness` 从 dBFS 近似改为复用 scene_engine 两遍 loudnorm 真实 EBU R128（失败降级近似）；③ `_calculate_intelligent_bgm_volume` 增益收窄（opening/ending +5→+3、theme +3→+2、tense/epic +8→+4、joyful/romantic +2→+1，钳制上限 -10→-12） | 已完成 | 新增 7 项测试（含真实 LUFS 验证 ±2.5）；audio 回归 2090 通过（8 项失败 + 11 项 error 经 stash 对照均为存量）；需重启 Celery worker 生效，存量章节需 remix 重混才应用新参数 |
| 5.34-候选登记撞 Contract 约束修复 | **真实接口 500**：`POST .../regeneration-candidate` 写 run 时 `celery_task_id`/`chapter_audio_id` 均为 NULL，撞 Contract 收窄的 NOT NULL（+UNIQUE）约束；修复：① `register_segment_candidate_asset` 生成每 run 独立 uuid 占位（同步候选无真实 Celery 任务，与 outbox 逐 run uuid 语义一致）并经 `_ensure_active_chapter_audio` 解析运行作用域；② `update_chapter_run_state` 兜底创建同步补 `celery_task_id or str(uuid4())`（同类潜在缺口） | 已完成 | 真实 PG 验证（项目 84 章 10：run 125 写入成功）；候选/重生成回归 60 项全过 |

Phase 1.1 三个发布单元（Expand → Migrate → Contract）已于 2026-08-15 全部完成并通过阶段验证（见 §5.5/§5.6）。

域 3+4 服务层（阶段 5.1-5.7）已于 2026-08-15 完成，34 项合同级测试全绿（见 §5.12）。

域 3+4 接入层（阶段 5.8-5.13）已于 2026-08-15 完成，53 项合同级测试 + 26 项真实 API/PG E2E 全绿（见 §5.13）。

域 3+4 收尾（阶段 5.14-5.16）已于 2026-08-15 完成：前端穷举映射 + 真实 PG 并发测试 + remix 发布接入，169 项回归全绿（见 §5.14）。

域 3+4 补完（阶段 5.17-5.20）已于 2026-08-15 完成：恢复快照化 + 恢复证据服务 + synthetic 回填 + job_id/SSE，192 项回归全绿（见 §5.15）。

域 3+4 终章（阶段 5.21-5.25）已于 2026-08-15 完成：token fencing + 崩溃窗口测试 + legacy 投影 + 复制合同 + 分阶段 checkpoint，210 项回归全绿（见 §5.16）。

域 3+4 收窄准备（阶段 5.26-5.27）已于 2026-08-15 完成：ledger 历史清洗服务 + Contract 收尾迁移文件 + 历史回填执行（215 项回归全绿，见 §5.17）。

**Contract 收窄已应用**（用户沙箱外执行）：alembic current = contract_audiobook_isolation_finalize (head)；3 个 NOT NULL + celery UNIQUE + tasks CHECK stage2 全部生效；收窄暴露的创建路径缺口已修复（create_run/create_runs/enqueue/job_tracker 兜底补齐 chapter_audio_id），215 项回归 + E2E 26/26 全绿（§5.17）。

域 3+4 派发与事务收口（阶段 5.29-5.30）已于 2026-08-15 完成：逐 run 派发 cutover + 入队/冻结同事务化（7 调用方全量改造），215 项回归 + E2E 26/26 全绿（§5.18）。

域 3+4 派发时序修复（阶段 5.31）已于 2026-08-15 完成：真实 worker 日志暴露"事务内 send_task→worker 认领失败"竞态，修复为提交后派发（dispatch_pending_runs），215 项回归 + E2E 26/26 全绿（§5.18）。

阶段进度持久化回归修复（阶段 5.32）已于 2026-08-15 完成：cutover 后 tracker=None 导致前端阶段网格永远"等待中"与协作暂停失效，修复为经 AudiobookTaskDispatch 解析父任务 tracker 并注入三个 run_type 分支，同时补齐 run.started_at 首次认领记录；需重启 Celery worker 生效。

legacy 混音音量一致性修复（阶段 5.33）已于 2026-08-15 完成：针对"角色对白比旁白小 + BGM 偏大"的听感问题（根因：多供应商 TTS 原生响度不一致且无逐段校准 + 整轨 dBFS 近似归一化偏差约 5 LU + 智能配乐增益过高），实施逐段响度对齐、真实 EBU R128 整轨归一化、配乐增益收窄三项修复；两者互为因果（对白轻 → ducking 阈值不触发 → 配乐显得大），逐段对齐同时缓解两个问题。需重启 Celery worker 生效；存量章节音频不会自动变化，需 remix 重新混音。

候选登记撞 Contract 约束修复（阶段 5.34）已于 2026-08-16 完成：单段重生成候选接口 500，根因是 `register_segment_candidate_asset` 同步写 run 路径未适配 §5.27 Contract 收窄（celery_task_id NOT NULL+UNIQUE、chapter_audio_id NOT NULL），与 §5.28 同类缺口但遗漏此路径；修复为每 run 独立 uuid 占位 + 复用 active ChapterAudio 解析，同时补齐 update_chapter_run_state 兜底创建的同类风险；真实 PG 验证写入成功，仅需重启后端（uvicorn）生效。

## 4. 风险与决策记录

| 日期 | 决策/风险 | 结论 |
|---|---|---|
| 2026-08-15 | Alembic 存在 14 个未合并 heads，当前 DB 版本 `add_user_voice_public_pool` | 新迁移线性挂在当前 DB head 之后，不处理历史 heads 合并（范围外） |
| 2026-08-15 | 合同级测试必须真实 PostgreSQL（advisory lock/ON CONFLICT/trigger 无法用 SQLite 验证） | 测试使用 backend/.env 的 DATABASE_URL，专用测试 schema 隔离，不污染 dev 数据 |
| 2026-08-15 | Contract 暂缓项门禁哲学（fail-closed） | snapshot_status NOT NULL、runs.chapter_audio_id NOT NULL、celery_task_id NOT NULL+UNIQUE、tasks CHECK stage2 均依赖新写路径代码全部改造后才可施加；严禁先迁移后部署（R14/P1-b） |
| 2026-08-15 | Alembic 多 heads：存在无关分支 `add_prompt_challenger_state_transitions` | audiobook 分支用定向 revision 名应用（`alembic upgrade contract_audiobook_isolation_schema`），不合并无关分支 |
| 2026-08-15 | 域 3+4 服务层采用纯 Python 单元测试（mock db），不依赖真实 PostgreSQL | 合同级测试覆盖投影映射/聚合矩阵/转态逻辑/barrier/finalizer 前置条件；真实 PG 并发测试留待 E2E 阶段 |
| 2026-08-15 | SessionLocal 导入路径为 `app.db.base`（非 `app.db.session`） | dispatch_service/billing_finalizer_service 的 Celery 任务函数使用 `from app.db.base import SessionLocal` |
| 2026-08-15 | 现有计费 freeze 为批次级 key（`audiobook:{project_id}`），GUIDE 要求 run 级（`audiobook:{project_id}:run:{run_id}`） | finalizer settle 双 key 兼容：run 级优先、批次级回退（现有批次冻结不挂死）；批次→run 级迁移另行排期 |
| 2026-08-15 | 入队路径保持既有批量 apply_async 派发（旧 worker 兼容），逐 run 任务仅供 dispatcher 重放 | 双执行窗口（apply_async 成功但 dispatched 标记未落库前崩溃）极窄且不产生重复计费（ledger 由租约保护）；cutover 逐 run 派发为独立部署步骤 |
| 2026-08-15 | `update_chapter_run_state` 终态关账无账户锁（与人工收敛路径无锁序环，CAS 条件防双写） | 严格三层锁序的 finalizer 由逐 run 任务外层 / beat 扫描器在账户锁内执行（R19/P0） |
| 2026-08-15 | `billing_account_user_id` 入队时取 Project.user_id（freeze 在 enqueue 后独立事务，无法同事务写入） | 近似值 + freeze 独立落库；严格同事务冻结（R11/P0-2）依赖入队/冻结事务合并改造，另行排期 |
| 2026-08-15 | 入队路径内 `db.commit()` 保留（既有行为，移除属 R10/P0-3 cutover 步骤） | 事务所有权改造（内部 commit 全移除）与 freeze 同事务化绑定部署窗口，另行排期 |
| 2026-08-15 | 模型层缺失 `uq_chapter_audio_active_unique` 部分唯一索引声明（仅 Alembic 迁移建过，create_all 不生效） | 模型 `ChapterAudio.__table_args__` 补 Index 声明，与 Contract 迁移一致；并发测试由此暴露并修复 |
| 2026-08-15 | remix 历史直写 `ChapterAudio` 镜像列路径已删除（发布协议唯一写路径） | 旧直写测试断言同步更新（on_output_ready 语义）；发布失败时产物保持 staged 不破坏旧已发布 |
| 2026-08-15 | **环境问题：浏览器访问的 3000/8000 是 Docker 旧镜像容器**（前端镜像打包 7 月 dist；后端镜像无 reconcile 端点） | 已重建 `frontend`/`backend` 镜像并重启容器（npm run build + docker compose build/up）；容器内验证新哈希 JS 与 reconcile 端点；浏览器需硬刷新（/assets/ 1 年 immutable 缓存） |
| 2026-08-15 | 分阶段 checkpoint 完整插桩侵入 full 生成核心链路（engine_pkg mixin 内部阶段完成点）风险过高 | 采用 KISS 落点：`derived_facts_service` 服务层完整合同（冻结/恢复决策/hash 校验）+ full 完成写回点最小接入（可提取子项才冻结、不阻塞）；engine 内部插桩留待后续排期 |
| 2026-08-15 | 测试环境（无真实用户）可执行 Contract 收窄；但执行沙箱拦截 DDL 命令（alembic upgrade/docker exec+python 均被拒，只读 current 可跑） | 迁移文件与数据门禁已就绪（回填完成、无 NULL/无重复/无暂停态）；需用户在沙箱外终端执行 `python -m alembic upgrade contract_audiobook_isolation_finalize` |
| 2026-08-15 | **收窄暴露写路径缺口**：chapter_audio_id NOT NULL 后 `create_runs` INSERT 不带 chapter_audio_id → NotNullViolation | 修复：create_run/create_runs 增加 chapter_audio_id/chapter_audio_ids 参数；enqueue_chapter_runs 创建前预解析 active ChapterAudio；update_chapter_run_state/job_tracker 兜底创建补齐；E2E 26/26 验证通过 |
| 2026-08-15 | 批次级 freeze 保持现状（GUIDE 要求 run 级冻结但金额按整批估算拆分语义不明） | settle 已双 key 兼容（run 级优先/批次级回退）；freeze 批次级 + settle run 级在功能上自洽，run 级 freeze 迁移记入后续排期 |
| 2026-08-15 | **真实 worker 暴露派发竞态**：同事务模式下 try_dispatch_run 在事务提交前 send_task → worker 消费消息时 run 未提交为 dispatched → acquire_worker_lease 认领失败（日志 "run_id=118 租约认领失败"） | 修复：事务内不派发（run 保持 pending 落库），提交后 dispatch_pending_runs 逐 run 即时派发；7 调用方 commit 后显式调用；dispatcher beat 兜底重放 |

## 5. 验证记录

### 5.18 缺陷修复：即时派发 send-before-commit 竞态 + dev 环境 beat 缺失（2026-08-16）

**背景**：全量清除后首次生成（项目 93）：run 131（script_only）正常完成；run 132（audio_from_scripts）worker 日志"租约认领失败（未派发）"后永久卡 queued。

**根因（两因叠加）**：
1. `try_dispatch_run` 先 `send_task` 后 flush `dispatch_status='dispatched'`（commit 更晚）——worker 毫秒级消费（实测投递到消费 1ms）读到未提交的 pending，租约前置条件（dispatched）不满足 → 消息被 ACK 丢弃。run 132 时间线：创建 .065 → 投递 .136 → 消费 .137。
2. 兜底链 `_requeue_stale_dispatched`（120s 未认领重投）依赖 `audiobook.dispatch_stale_pending` beat 任务，而 `dev.bat` 从未启动 celery beat → 卡死无法自愈。

**实施落点**：
- `dispatch_service.py` `try_dispatch_run`：改为先落库后投递——dispatched 状态 + attempts 先 commit 再 `send_task`；明确失败走补偿（cancelled）+ commit；unknown 保留 dispatched 状态由超时重投兜底（原 unknown 状态无任何兜底链覆盖）。
- `dev.bat`/`dev-kill.ps1`：新增 celery beat tab（4 服务→5 服务），kill 脚本特征匹配已兼容 beat 进程。

**测试**：新增 `test_dispatch_commit_before_send.py` 4 项（真实 PG，schema 隔离）：send 时刻独立会话可见 dispatched（修复前必红）/投递失败补偿 cancelled/unknown 保留 dispatched 可重投/重复派发 skipped；回归 domain34 并发合同 + domain3/4 集成 + billing 共 44 passed。

**处置**：run 132 以固定 celery_task_id 重投解救，租约认领成功进入 tts_synthesis；worker 启动时间晚于音效修复（§5.17），本次合成已含高能窗口修复。

**结论**：即时派发竞态闭环，兜底链（beat）纳入 dev 环境标准启动。

### 5.17 缺陷修复：分轨合成音效"显示有但试听/成品均不可闻"（2026-08-16）

**背景**：用户反馈项目 84（铜棺葬仙）legacy_stems 模式下，时间轴显示已配置音效（如"骨裂声"），但试听无输出、整章成品也听不见；仅"重新生成"候选可试听保存。

**根因定案（三重叠加）**：
1. `duration` 截断盲取素材头部——`AudioMixer.add_sound_effect` 按 cue duration 截取素材时只取头部，而一次性音效（骨裂、拔刀、脚步）声体位于素材中后段（骨裂声素材 3528ms 中声体在 2250-2500ms，头部 2.25s 为 -50~-62dB 静默）→ 叠加的是静默前奏。14 条 cue 审计中 4 条中招。
2. 音量公式过度压低——base_gain(-7) + volume 折算(-8.9) + ducking(-6) ≈ -22dB，叠加静默段后低于听阈。成品互相关扫描仅检出唯一躲过截断的环境床（fa4bee，高能区在素材头部且循环长播）。
3. 试听同链路受累——片段窗口仅 0.765s，音效被钳到 0.5s 静默头，预览输出峰值实测 -56.7 dBFS（近静音）→ 用户判定"无法试听"。重新生成走 stored asset（完整素材、无截断）故可用。

**实施落点（三处最小修复）**：
- `audio_mixer.py`：新增 `_select_energetic_window` 静态方法——非循环截断时滑动扫描选取能量最高的 duration 窗口（能量 6dB 内优先取更早窗口，保留起始手感；素材不超长原样返回；循环环境床不走此路径，避免相位跳变）。整章叠加与试听渲染共用 `add_sound_effect`，`segment_preview_service`/`background_jobs_remix` 两处调用方自动受益。
- `_sfx_mixin.py` / `_music_mixin.py`：诚实计数——`add_sound_effect`/`add_background_music` 静默失败时原样返回入参对象，改用对象同一性（`result is mixed_audio`）区分真实叠加与静默跳过，跳过时显性 warning + `skipped` 计数，杜绝 `applied` 虚报误导排查。

**测试**：
- 新增 `test_audio_mixer_sfx_window.py` 6 项：高能窗口命中后段声体/能量接近优先早窗口/不截断原样返回/截断后声体可闻/loop 路径不受影响/静默 no-op 计 skipped、真实叠加计 applied。
- 回归：新增 6 项 + `test_segment_timeline_preview.py` + `test_audiobook_remix.py` 共 33 passed 零失败；`test_audio_fx_optimizations.py` 103 passed（1 项既有失败位于 `_parallel_mixin` seed_scene 路径，与本修改正交，系工作树既有残留，未回滚）。
- E2E：复现片段 index=8 试听渲染，修复前预览峰值 -56.7 dBFS → 修复后 -8.8 dBFS，声体落入试听窗口。

**实施中发现并修正的问题**：
- 既有 `applied_count` 无条件自增——静默失败也计入 applied，导致离线复现数据不可信 → 本次一并修复为对象同一性诚实计数。

**遗留（不处理/记录）**：
- run 121 运行期 23:08-23:11 worker 日志已随 app.log 轮转丢失，确切运行期行为不可考；既有章节需重新生成/重混才能补上音效（设计层修复对后续生成生效）。
- segments 1/2/3 的 `sfx_audio_path`/`audio_path` 指向陈旧持久化 ref（`chapter_segments_persistent_sfx/`），容器内文件已丢失——次要问题，超出本次范围。
- BGM 未检出但检测方法仅在对白间隙验证、结论存疑；BGM 低音量系此前响度对齐任务有意设定，不动。

**结论**：根因闭环（截断+音量+试听同链路），33 项回归全绿，E2E 预览峰值提升约 48dB，后续生成的音效可闻可试听。

### 5.16 阶段 5 终章：token fencing + 崩溃窗口测试 + legacy 投影 + 复制合同 + 分阶段 checkpoint（2026-08-15）

**实施落点**：
- token fencing（验收 76，R14/P1-d）：`dispatch_service.py` 结果回写三处（success→dispatched / unknown / 明确失败补偿）全部加 `dispatch_claim_token == claim_token` CAS 条件——迟到 dispatcher 的返回与补偿被拒绝（rowcount=0），已接管 run 不被取消、desired_run_id 不变；`_compensate_failed_dispatch` 增加 claim_token 参数（无 token 的即时派发场景保持原语义）。
- 崩溃窗口测试（验收 52，R10/P1-3）：真实 PG——供应商调用前写 pending → 模拟崩溃 → 恢复按 attempt_key 重放（幂等返回原记录）→ 补录 succeeded，断言仅一条 ledger、无重复入账、无丢失用量。
- legacy 展示投影（验收 66，R13/P1-a）：`_resolve_resume_source_run` 优先按 `AudiobookTaskDispatch` 父子关系（task_id → run 列表）定位（纯 DB 投影、不做 broker 关联），历史 run（legacy- 前缀、无 TaskDispatch）回退 celery_task_id 查询。
- 复制合同（验收 25，§2.1）：`chapter_script_copy_service.py`——`copy_approved_script` 把源批次已审批剧本复制到目标批次（script_json/审定证据/status 保持 approved），持久化 `source_script_hash`（确定性 sha256）/`source_script_review_version`/`source_provenance_json`（含来源 batch/chapter_audio/复制时点/合同版本），幂等（同源跳过）。
- 分阶段 checkpoint（验收 37/51，R9/P0-4/R10/P1-2）：`derived_facts_service.py`——`freeze_derived_fact`（三子项顺序冻结、append-only 拒绝覆盖、顶层镜像 hash 键）、`resolve_resume_stage`（最后冻结子项的下一阶段：voice_binding/scene_planning/scene_rendering；中间缺失不跳过）、`verify_derived_facts`（子项 hash 独立校验）、`summarize_frozen_stages`（审计）；`background_jobs_full` 完成写回点接入（script_segments_payload→generated_script_facts、stats.characters→voice_resolution、scene_topology→scene_topology，可提取才冻结、异常不阻塞完成）。

**测试**：
- 新增：token fencing mock 3 项（success 回写 CAS/迟到补偿拒绝/匹配 token 生效）+ 真实 PG 双 dispatcher 1 项（A 认领→B 接管→A 迟到补偿被拒、B 状态保持）+ 崩溃窗口 1 项 + 复制合同 3 项 + derived facts 10 项（阶段顺序/冻结推进/append-only/恢复决策/断裂不跳过/hash 校验/篡改暴露/摘要）。
- 回归：15 套件 `210 passed`（192 + 3 fencing mock + 1 真实 PG fencing + 1 崩溃窗口 + 3 复制 + 10 derived facts）零失败。
- E2E：`smoke_domain34_integration.py` 26/26 通过（新代码全链路）。

**实施中发现并修正的问题**：
- 原实现结果回写无 token CAS——迟到 dispatcher 会覆盖接管者状态（验收 76 缺口）→ 已修复三处回写 + 补偿。
- 分阶段 checkpoint 完整插桩风险过高 → KISS 落点（服务层完整合同 + 写回点最小接入），engine 内部插桩记入决策留待排期。

**结论**：验收 25/37/51/52/66/76 全部闭环，210 项回归全绿，26 项真实 E2E 通过。

### 5.15 阶段 5 补完：恢复快照化 + 恢复证据服务 + synthetic 回填 + job_id/SSE + 环境修复（2026-08-15）

**实施落点**：
- 恢复快照化（§1.5/验收 8/19）：`routes_tasks.py` 恢复路径的 tts_model/output_format/narration_style/generate_subtitle/engine_mode 全部改从 `run_input_snapshot`（run_options/engine_config_payload 冻结值优先，无快照回退 run 列/实时解析）；计费键随引擎模式（seed_scene → seed 模型键）。`routes_segment_regen.py` 新增 `_resolve_runtime_config_from_batch`（批次快照优先、无快照回退实时），两处解析（片段重生成 + 时间线试听）接入。
- 恢复证据服务（验收 70）：`ledger_recovery_service.py`——`persist_result_url_evidence`（encrypted_result_url/result_url_expires_at/result_url_persisted_at/commit_stage=result_persisted 单调推进）+ `decide_recovery_method`（①有 request_id 且调用时能力支持查询→request_query ②有未过期结果 URL→temporary_url ③幂等键已发送且调用时能力接受→replay ④无证据→manual；capability_snapshot_json 优先，禁止用当前能力表解释历史调用）。
- synthetic migration run 回填（验收 38/50）：`synthetic_migration_run_backfill.py`——有 audio_path 且无 published_run_id 的历史章节：有匹配 completed run（full/audio_from_scripts/chapter_remix）→ 回填 published_run_id + published 输出 + `legacy_unverified`（可导出、不作 CAS 基线，seed 历史 render_status 保持 null）；无匹配 → 创建 `migration_placeholder` synthetic run（completed/cancelled/resumable=False，不可恢复/结算/重试/派发）+ 指针回填。幂等（二次执行扫描 0）。
- job_id/SSE（验收 56/68）：`AudiobookTaskStatus` 新增 `job_id = task:{AudiobookTask.id}` 命名空间（保留 celery_task_id 兼容）；`get_task_for_user` 支持 `task:{id}` 与 celery_task_id 双解析；SSE 事件 data 携带 `run_id`（detail 透传）与 `job_id`。

**测试**：
- 新增：恢复证据 8 项（URL 落库/四种证据组合/能力快照决策/过期回退/值域）+ synthetic 回填 4 项（owner 归属/synthetic 创建/幂等/无产物跳过）+ job_id 4 项（状态响应命名空间/task:{id} 解析/celery 兼容/SSE 字段）。
- 回归：13 套件 `192 passed`（169 + 8 恢复证据 + 4 synthetic + 4 job_id + 7 history_backfill）零失败。
- 真实 API E2E：`smoke_domain34_integration.py` 26/26 通过；新增 job_id 验证——状态响应含 `job_id=task:65`，按 `task:65` 查询 200（验收 68 兼容期解析）。

**环境修复（用户反馈浏览器显示旧版本）**：
- 根因：`:3000` 由 Docker 容器 `novel_frontend` 服务旧镜像（打包 2026-07-23 dist），`:8000` 容器 `novel_backend` 为旧镜像（无 reconcile 端点）；本地源码修改从未重建进镜像。
- 修复：`npm run build` 重建 dist（38.6s）→ `docker compose build frontend/backend` → `docker compose up -d frontend/backend`；容器内验证——index.html 引用新哈希 `index-BERYdI-6.js`、`billing_snapshot_builder/ledger_recovery_service/synthetic_migration_run_backfill` 三新文件存在、HEALTH 200、reconcile 端点注册、366 路径。
- 用户操作提示：浏览器硬刷新（nginx /assets/ 1 年 immutable 缓存）。

**结论**：恢复快照化/恢复证据/synthetic 回填/job_id-SSE 全部闭环，192 项回归全绿，26 项真实 E2E + job_id 真实 API 验证通过；前端/后端 Docker 容器已同步最新代码。

### 5.14 阶段 5 收尾：前端穷举映射 + 真实 PG 并发测试 + remix 发布接入（2026-08-15）

**实施落点**：
- 前端 StageStatus 穷举映射（验收 81，R15/P1-3）：`types.ts` 联合类型新增 `'cancelled'`/`'completed_with_partial_failure'`；`constants.ts` STAGE_STATUS_LABELS 补文案（已取消/部分完成）；`TaskStageDetails.tsx` STAGE_STATUS_COLORS 补颜色（导出供测试）；`audiobookTheme.ts` taskStatus 补两键颜色角色（warning 系）；`utils.ts` coerceStageStatus 识别新值（未知值仍回退 pending）。
- 真实 PG 并发合同测试：`test_audiobook_domain34_concurrency_contract.py` 2 项——验收 48（双事务并发首次创建同一章节 active ChapterAudio：部分唯一索引保证仅一个成功、loser 捕获 IntegrityError、最终恰好 1 条 active）；验收 83（worker 终态关账 UPDATE×人工收敛 CAS 并发交错：两路径锁序一致无死锁、worker 不碰 manual 行、人工收敛成功转态）。
- remix 发布接入（§1.5/验收 30/R8）：`chapter_output_publish.py` 新增 `publish_legacy_chapter_output`（legacy 发布谓词 `result_render_status='completed'`：锁行/幂等短路含 R9 一致性检查/staged 恰一条/CAS 镜像列/旧输出 supersede/本 run published，跳过场景 artifact 完整性）；`background_jobs_shared.build_chapter_audio_output_path` 增加 run_id 参数（run 级路径）；`background_jobs_remix.py` 删除直写镜像列改 `on_output_ready` 回调（upsert staged + 发布，与终态同事务）、运行时改从批次快照解析（无快照回退实时）。

**测试**：
- 前端：`stageStatusExhaustiveMapping.test.ts` 5 项（labels/theme/colors 穷举完备 + coerce 识别 + 未知回退）；`tsc --noEmit` 0 错误（TS 穷举强制）；audiobook 目录 68 文件 373 测试全绿。
- 后端：`test_chapter_output_publish.py` 新增 6 项 legacy 发布测试（非 completed 拒绝/run 未终态拒绝/正常发布 CAS 镜像列/幂等短路/旧输出 supersede/CAS miss 保持旧产物 + 迟到 run 保持 staged）；`test_audiobook_remix.py` 2 项更新为 on_output_ready 语义。
- 回归：11 套件 `169 passed`（域3+4 合同 34 + 接入 19 + 并发 2 + 计费 6 + wiring 2 + 快照 10 + 重渲染 4 + 冻结过滤 29 + 发布 26 + 场景编辑 19 + remix 18）零失败。
- E2E：`smoke_domain34_integration.py` 26/26 再次通过（新代码全链路）。

**实施中发现并修正的问题**：
- 模型层缺失 `uq_chapter_audio_active_unique` 部分唯一索引声明（仅 Alembic 迁移建过）→ 测试 create_all 环境无索引 → 并发插入双成功。修复：`ChapterAudio.__table_args__` 补 Index 声明（与 Contract 迁移定义一致，dev 库幂等）。
- 并发测试模块 DATABASE_URL 被其他测试模块 setdefault 的占位值污染（test:test 无凭据）→ 修复为无条件从 .env 读取。
- remix 旧测试断言直写镜像列行为 → 更新为 on_output_ready 交付语义。

**结论**：验收 48/81/83 + remix 发布接入闭环，169 项回归全绿，26 项真实 E2E 通过。

### 5.13 阶段 5 续：域 3+4 接入层（计价快照冻结/入队派发意图/逐 run worker 任务/finalizer 修复/终态关账）（2026-08-15）

**实施落点**：
- `billing_snapshot_builder.py`：usage_kind→pricing_key→unit 唯一映射表（R18/P1-3 四处同源）+ 单价解析（TTS 元/万字符→元/字符、Seed 元/分钟→元/秒）+ 金额计算 + 积分换算 + 计价策略字段对齐 PointsPricingPolicyConfig。
- `task_support.py` 入队接入：每 run 独立 celery_task_id + dispatch_status/attempts/next_dispatch_at/predecessor_run_id（R11/P0-1 outbox）+ 入队事务内锁定唯一 active ChapterAudio（R10/P0-4 SAVEPOINT 并发协议）+ TaskDispatch 父子关系（R11/P0-3）+ billing_snapshot/billing_account_user_id 冻结（验收 19/23）+ 批量 apply_async 三态（成功→dispatched；明确失败→条件补偿 R11/P1-4；未知→unknown）。
- `audiobook_tasks.py` 新增 `audiobook.run_chapter_dispatch`（R10/P0-2 每 run 独立消息）：CAS 租约认领（失败立即终止）→ 心跳线程续租（R12/P0-1）→ 按 run_type 复用现有 background 单章 → 终态处理（清租约 + 关账 + finalizer + 父聚合，独立短事务）。
- `dispatch_service.py`：任务映射统一到逐 run 任务 + `clear_worker_lease`（token 匹配防误清）+ dispatched 未认领超时重投（R12/P1-5）。
- `billing_finalizer_service.py`：**`_execute_settle` 接口修复**（原调用 `record_points_billing_settle(db=, billing_key=, total_quantity=, run_id=)` 与实际签名不匹配→TypeError→finalizer 永远 settle 失败；改为正确参数 + 金额按计价快照计算 + run/批次级 key 兼容回退）+ `try_finalize_run` 账户 advisory 锁前置（无锁预读仅路由 R21/P2-3 → 账户锁 → run 行锁）。
- `update_chapter_run_state` 终态分支：清租约 + 按证据关账（R18/P0）；最终结算由逐 run 任务外层 / beat 扫描器在账户锁内执行。

**测试**：
- 新增套件：`test_audiobook_domain3_domain4_integration.py` → `19 passed`：billing_snapshot 构建（映射表/legacy+seed 双分支单价/金额计算/积分换算/单源断言）+ 入队意图冻结（幂等不覆盖）+ 终态清租约关账（终态触发/非终态不触发）+ settle 参数合同（正确 billing_key/target_user_id/金额/复合串仅审计）+ 批次级 key 兼容回退 + 零 ledger 跳过不挂死 + clear_worker_lease token 语义 + dispatched 未认领重投 + 逐 run 任务参数/任务名 + finalizer 账户锁先于 run 锁。
- 回归：域 3+4 合同 34 + 接入 19 + 计费 6 + wiring 2 + 快照 10 + 重渲染 4 + 冻结过滤 29 + 发布 15 + 场景编辑 19 → `144 passed` 零回归。

**真实 API + PostgreSQL E2E**（`.tmp/smoke_domain34_integration.py`）→ `SMOKE_D3D4_INTEGRATION_ALL_OK`（26/26）：
- 真实 API 入队 script_only → DB 验证：dispatch_status=dispatched（批量派发成功）、独立 celery_task_id、chapter_audio_id 绑定（验收 36 运行作用域）、billing_account_user_id、billing_snapshot 冻结（tts/remix prices + points_per_yuan）、desired_run_id 指针、TaskDispatch 记录。
- worker 租约协议（真实 PG）：acquire → heartbeat（token 匹配）→ wrong token 拒绝 → 重复认领拒绝 → clear。
- dispatcher stale-pending 认领：CAS 认领 + send_task 投递到 `audiobook.run_chapter_dispatch`（`dispatched: 1`）。
- 父任务聚合：run completed → 父任务 completed（全 succeeded → completed）。
- finalizer：终态 run → 关账 0 + barrier 通过 + settle 跳过（无 active freeze）+ `billing_finalized_at` 封口；重复 finalize 幂等短路（already_finalized）。
- 任务注册：run_chapter_dispatch / dispatch_stale_pending / billing_finalizer_scan 全部注册。

**实施中发现并修正的问题**：
- `_execute_settle` 调用 `record_points_billing_settle` 参数名不匹配（`total_quantity`/`run_id` 非实际参数）→ TypeError 被 except 吞掉返回 settle_failed → finalizer 永远无法结算。修复后 E2E 验证 finalize 成功。
- TaskDispatch 复合外键 `(run_id, chapter_audio_id)` 失败：run.chapter_audio_id 赋值后未 flush 就插 TaskDispatch → run 行在 DB 中仍是 NULL。修复：先 flush run 作用域再插 TaskDispatch。
- ChapterAudio 双指针外键失败：desired_run_id 更新与 run.chapter_audio_id 更新同 flush 顺序不确定 → 拆两次 flush（先 run 作用域，再 desired 指针）。

**结论**：域 3+4 接入层全部闭环（计价快照冻结/入队派发意图/逐 run 任务/租约协议/finalizer/终态关账），53 项合同测试 + 26 项真实 E2E 全绿，144 项回归零失败。

### 5.12 阶段 5：域 3+4 服务层（可靠派发/worker 租约/父任务聚合/ledger 转态/finalizer/人工收敛 API）（2026-08-15）

**实施落点**：
- 域 3（可靠派发/worker 租约/恢复协议）：`dispatch_service.py`（dispatcher CAS 租约认领 stale pending run + worker 租约协议 acquire/heartbeat/reclaim + 条件补偿 + beat 定时任务每 2 分钟）；`task_aggregation_service.py`（normalize_run_status 投影 + 六条互斥矩阵穷尽规则 + refresh 持久化）。
- 域 4（计费 ledger/mutation service/finalizer）：`ledger_transition_service.py`（统一 ledger 转态 pending→succeeded/confirmed_failed/manual_reconciliation + 终态关账 + strict barrier）；`billing_finalizer_service.py`（统一 finalizer try_finalize_run + beat 扫描器每 3 分钟 + settle 幂等）；`provider_capability_service.py`（供应商派发能力配置 seed/query + 6 个已知供应商）；`admin/billing.py` 人工收敛端点 `POST /ledger/{ledger_id}/reconcile`（无锁预读仅路由 → run FOR UPDATE → ledger FOR UPDATE 锁后重读 → CAS → 审计 → finalizer 联动，三层锁序）。
- Celery beat 配置：`celery_app.py` 新增 `audiobook-dispatch-stale-pending`（*/2 min）+ `audiobook-billing-finalizer-scan`（*/3 min）。

**测试**：
- 新增套件：`test_audiobook_domain3_domain4_contracts.py` → `34 passed`：
  - `TestNormalizeRunStatus`（13 项）：pending→queued/completed→succeeded/expired→cancelled/canceled→cancelled/null→unknown/空串→unknown/任意值→unknown 等全部投影映射。
  - `TestParentTaskAggregationMatrix`（10 项）：R17/P1-2 穷尽规则——①任一 unknown→failed ②任一 running/queued→running ③全 succeeded→completed ④全 cancelled→cancelled ⑤succeeded+failed/cancelled→completed_with_partial_failure ⑥无 succeeded+failed→failed + {cancelled,failed}→failed + 无子派发→None。
  - `TestLedgerTransitionService`（4 项）：pending 创建（status=pending, commit_stage=pre_call）+ 同 attempt_key 幂等 + 无供应商证据→confirmed_failed + 已发请求结果不明→manual_reconciliation。
  - `TestStrictBarrier`（3 项）：全终态通过 / pending 残留拒绝 / manual_reconciliation 残留拒绝。
  - `TestFinalizerPreconditions`（4 项）：终态集合包含 completed/failed/cancelled/canceled/expired 不含 running/pending + lease 有效/过期/null 三态。
- 回归：`test_audiobook_task_support_billing.py` 6 passed + `test_audiobook_seed_scene_billing_wiring.py` 2 passed → 无回归。

**实施中发现并修正的问题**：
- `dispatch_service.py` 和 `billing_finalizer_service.py` 的 Celery 任务函数初始使用 `from app.db.session import SessionLocal`，实际 `SessionLocal` 定义在 `app.db.base`（第 97 行）→ 修复为 `from app.db.base import SessionLocal`。

**结论**：域 3+4 服务层全部闭环，34 项合同级测试全绿，既有测试零回归。

**真实 API E2E**（uvicorn 8000 + 真实 PG，`.tmp/smoke_domain34_e2e.py`）→ `SMOKE_D3D4_ALL_OK`（16/16）：
- OpenAPI 端点注册：reconcile 端点 `POST /api/v1/admin/billing/ledger/{ledger_id}/reconcile` 已注册，POST 方法 + 请求体 schema + 200/422 响应码齐全。
- 认证拒绝：无 token 访问 → 403；非管理员访问 → 403（权限检查在参数校验之前，正确行为）。
- 服务模块导入链：dispatch_service（MAX_ATTEMPTS=5, LEASE_SEC=90）/ ledger_transition / billing_finalizer（TERMINAL 集合正确）/ task_aggregation（投影验证通过）/ provider_capability（6 个已知供应商）全部导入成功。
- Celery beat 配置：`audiobook-dispatch-stale-pending`（*/2 min）+ `audiobook-billing-finalizer-scan`（*/3 min）均已注册。

**浏览器 E2E**（Browser subagent，e2e_d3d4_admin 账号）：
- Swagger UI：reconcile 端点在 admin/admin-billing 分组下可见，描述完整（「管理员人工对账收敛」+ 单事务原子收敛流程描述），Schema 区域 LedgerReconcileRequest/Response 模型可见。
- 前端主界面：登录页/Dashboard/创作工坊首页/有声书 Dashboard 全部正常渲染，零回归。
- 控制台/网络：0 error / 0 warn / 全部 HTTP 200 无 4xx/5xx。
- 截图证据：`.tmp/e2e_swagger_02_reconcile_endpoint.png`、`.tmp/e2e_frontend_05_audiobook_dashboard.png`。

### 5.11 阶段 4：验收 6/7/8 闭环（场景编辑分流 + 编辑历史 + run_input_snapshot + 重渲染 + 保留清理）（2026-08-15）

**实施落点**：验收 6（台词编辑→script_json + script_status 重置 pending + 清空三类审定证据；导演覆盖→SceneEditRevision 不修改原文；音色绑定→双写且仅当前章节已发布产物置 stale）；验收 7（scene_edit_revisions append-only + heads 表可 UPDATE 指针）；验收 8/19（run_input_snapshot 方案 A 自包含正文，按 run_type 合同冻结，恢复只消费快照）；§3.2 重渲染入口（revision_set_hash 409 校验 + head 投影冻结）；§8.3 保留期清理脚本。

**测试**：
- 新增套件：`test_run_input_snapshot_contract.py` 10 项（快照自包含/按 run_type 冻结/恢复消费快照/损坏回退）+ `test_rerender_revision_set_hash.py` 4 项（正确 hash 入队 + 快照冻结投影/stale 409/无 hash 兼容/失配不入队）+ `test_cleanup_expired_artifacts.py` 4 项（superseded 超期清理/staged 终态超期清理/published 与镜像引用保护/共享路径防误删）→ 全绿。
- 验收 6 补强：`test_scene_editor_routes.py` 增加台词编辑清空 `script_review_json`/`script_review_version` 审定证据断言 → 19 passed。
- 回归：后端 212 passed（含场景编辑/发布/快照全链路）+ 真实 PostgreSQL 合同 22 passed + 前端 vitest 869 passed + `tsc --noEmit` 0 错误。
- 修复回归暴露缺陷：`test_audiobook_project_completion_summary.py` 的 SimpleNamespace 缺 `render_status_detail` 字段（1.6 序列化新字段）→ 补齐。

**真实 API E2E**（uvicorn 8000 + 真实 PG，`.tmp/smoke_rerender_e2e.py`，已随任务清理）→ `SMOKE_RERENDER_ALL_OK`：
- 登录 200 → editor-document 200（revision_set_hash）→ 正确 hash `POST generate-audio-from-scripts` 200 入队；DB 验证新 run 冻结 `run_input_snapshot`：`signed_payload.script_facts` = 已审批剧本两段正文、`revision_set_hash` 一致、`revision_projection` 齐全、`input_signature` 存在。
- stale hash → 409「场景编辑基线已变化，请刷新后重试」；无 hash → 200 兼容（旧客户端不破坏）。
- 恢复链路：并发修改实时 `script_json` 后 `_build_resume_input_context` 的 `script_hash` 仍等于快照 script_facts 哈希（恢复不读实时值，验收 19）。
- 清理脚本：`python scripts/cleanup_expired_artifacts.py` dry-run 真实 PG 正常（0 超期项，符合预期；清理逻辑由 4 项测试覆盖）。

**浏览器 E2E**（Browser subagent，e2e_rerender 账号）：登录 → `/audiobook/42`（注意：前端路由参数是小说项目 id 42，67 是批次 id）→ 点击「第1章 · Rerender Chapter 1」→ 「场景编辑器 · 第 1 章」对话框打开（台词编辑/导演覆盖/音色编辑三 Tab，`script_status: approved` 芯片）→ 「重渲染整章」按钮可用 → 点击 → `POST` 200 → 绿色提示「已提交重渲染，请在任务队列中查看进度」。截图证据：tmp/e2e_rerender_success.png、tmp/e2e_rerender_scene_editor_open.png、tmp/e2e_rerender_chapter_list.png。

**实施中发现并修正的问题**：
- 后端进程无 `--reload` 且启动早于代码修改 → 真实 API 验证加载旧代码（快照 NULL、预检 estimate_unavailable 假象）；重启后端后全链路通过。教训：真实 API 验证前必须确认服务进程加载最新代码。
- smoke 播种脚本更新章节正文后仅 `flush` 未 `commit`，被后续幂等分支回滚 → 正文过短触发预检 `estimate_unavailable`；补 `commit` 修复。

**结论**：验收 6/7/8 与 §3.2 重渲染、§8.3 保留清理全部闭环，零回归；GUIDE 文档目标完成。

### 5.10 阶段 3：章节编辑器分流与场景编辑器（2026-08-15）

- 后端 API 测试（新文件 `backend/tests/test_scene_editor_routes.py`）→ `19 passed`：editor-document 聚合（scenes/execution_status/published_render_status/last_revisions）、三类编辑（dialogue 语义变化→pending + 清空三类评审证据、director_override 不修改原文、voice_binding 双写 Project 音色 + 局部 stale）、409 冲突（旧 base_revision_hash → 409 + current_head_revision_hash）、dialogue-review 状态机（pending→reviewed→approved）、stream 媒体授权（play_token 凭证优先、superseded artifact 404）、audit-stream（管理员/所有者可见 superseded，非管理员非所有者 403）。
- 回归（后端）：`test_scene_edit_revision_service.py` + `test_chapter_output_publish.py` + `test_scene_editor_routes.py` → `54 passed`。
- 前端：`npx vitest run` → 166 文件 `868 passed`（SceneChapterEditor 6 项含批次切换器/disablePortal/章节序号优先）；`npx tsc --noEmit` 0 错误。
- 真实 API 冒烟（Postgres 播种 e2e 数据 + uvicorn 8000，`.tmp/smoke_scene_editor.py`）→ `SMOKE_ALL_OK` 9 步全通过：登录/editor-document 聚合/导演覆盖+投影/dialogue 编辑（script_status→pending）/幂等重放/409 冲突/dialogue-review/stream（play_token 200 + 音频字节）/audit-stream（x-artifact-status=active）。
- **冒烟发现并修复服务端 bug**：`audit_stream_scene_artifact` 非管理员分支把 `artifact.audiobook_project_id`（批次 id）误当 `project_id` 传给 `ProjectRepository.get_user_project` → 真实 Postgres 下 403（SQLite 测试因 project.id 与批次 id 同为 1 而掩盖）。修复：先 `db.get(AudiobookProject, artifact.audiobook_project_id)` 取真实 project_id 再校验归属；回归测试 `test_audit_stream_owner_check_uses_project_id_not_batch_id`（prepend_dummy_batch 使批次 id ≠ project id）。
- 浏览器端到端（Browser subagent，e2e_scene_editor 账号）：登录 → 有声书页 → 切换"场景生成"引擎 → 点击"第1章 已生成"卡片 → 场景编辑器对话框打开（场景列表 scene_1/scene_2 已通过 + 时长 + 试听按钮；三 Tab：台词编辑/导演覆盖/音色编辑）→ 导演覆盖 Tab 显示已有指令"语速放慢，语气阴冷"+ 稳定锚点 seg_a → 台词编辑追加【E2E测试】保存 → 绿色提示"台词编辑已保存" → 持久化核验：script 接口 seg_a 文本含追加内容、script_status reviewed→pending。截图证据：tmp/e2e_scene_editor_0*.png。
- E2E 发现并修复显示问题：对话框标题原显示内部章节 id（"第 58 章"），与全站"第 N 章"（chapter_number）惯例不一致 → `SceneChapterEditor` 新增 `chapterNumber` prop（缺省回退 chapterId），AudiobookPage 打开时从 chapters 查找序号传入；新增测试 `prefers chapterNumber over chapterId in the dialog title`，6 passed。
- 结论：阶段 3 零回归，向后兼容（legacy_stems 仍走剧本编辑器；batch 内 artifact supersede 显式排除当前 run_id）。遗留：重渲染入口（传 revision_set_hash + run_input_snapshot 自包含正文）与物理文件保留策略（GUIDE §8）未在本轮启用（渲染链路既有实现兼容，属排期项）。

### 5.9 阶段 2：前端布局/状态隔离/编排分流/三维投影（2026-08-15）

- 新增测试：`backend/tests/test_chapter_output_publish.py` → `15 passed`——聚合 6（全部 passed/含回退/manual_review 优先/空 failed/terminal_policy/非 Mapping 容错）+ 发布协议 9（publish staged/CAS 不命中/supersede 旧输出/幂等短路/损坏不短路/不可发布拒绝/desired_run 变更保留旧产物/run 非 completed 拒绝/staged 计数/upsert 幂等）。SQLite 部分唯一索引退化（`uq_chapter_audio_output_published` 全局唯一）已通过 DROP INDEX 规避，Postgres 语义由真实库保证。
- 回归（后端）：`test_audiobook_seed_scene_renderer.py` 37 + `test_audiobook_runtime_truth.py` 24 + `test_audio_config_freeze_and_filter.py` 28（含 render_status 序列化 4 项）+ `test_audiobook_expand_schema_contract.py` 14（单独跑全过，并行冲突为既有共享库行为）→ 全绿。
- 前端：`npx vitest run` → 165 文件 `860 passed`（修复 setupStepSource.test.ts 过期断言：引擎选择器已不在 NarrationAudioConfigPanel）；`npx tsc --noEmit` 0 错误（修复 3 处：resolveBranchSavedCharacters 签名放宽 Partial、isChapterGeneratedForEngine 让 engineMode 参与 legacy_stems/seed_scene 分支、applyProjectVoiceAssignments 移除未用参数）。
- 应用冒烟：uvicorn 临时实例（127.0.0.1:8001，避免干扰 8000 存量服务）启动成功，`GET /health` 200；openapi 全量 schema 加载无 import 错误。
- 真实 API 端到端（临时实例 + 临时用户，script_only 不触计费）：注册/登录 200、无 token 访问 403 拒绝、主项目创建/章节创建/有声书项目创建/详情/列表全部 200；`PUT /projects/{id}/audio-config` 写入 seed_scene engines 分支（tts_models 角色 + scene_generation_preferences.terminal_policy=manual_review）→ `GET` 回读完整一致——§2.2 引擎分支持久化真实链路验证通过。
- 结论：阶段 2 零回归，向后兼容（legacy_stems 行为不变，run_id 缺失降级旧直写）。遗留：§1.5 的 run 级路径（`build_chapter_audio_output_path` 加 run_id）未完成属既有遗留，本次 output_path 保持批次级；SceneAudioArtifact 状态机（发布协议 g 步）留待阶段 3。

### 5.8 Phase 1.4 批次创建冻结 + Phase 1.5 消费方快照化（子集） + Phase 1.6 章节状态过滤（2026-08-15）

- `python -m pytest backend/tests/test_audio_config_freeze_and_filter.py -v` → `29 passed`：resolve_engine_mode 在创建流程的归一化行为（含 auto 判定优先顺序）、snapshot builder（fingerprint 确定性+差异校验+字段完整性）、billing_context 改由 resolve 驱动（auto→归一化 vs get 返回原文）、resolve_from_snapshot 与实时解析结果一致性（legacy/seed 双分支）、parse_engine_config_snapshot 边界（None/空/损坏/非 dict/缺字段）、无快照回退行为、render_status 序列化（None/rendered_all_seed/rendered_with_fallback/detail）。
- 回归：`test_project_audio_config_engine_branch.py` 43 passed + `test_audio_config_api_engine_branch.py` 7 passed（真实 PostgreSQL）。
- 应用冒烟：`from app.main import app` 加载成功，411 条路由全部注册；`python -m py_compile` 全部修改文件通过。
- 真实 API 端到端（uvicorn 127.0.0.1:8000，停止 Docker novel_backend 避免端口劫持后验证）：OpenAPI spec 中 `GET /audiobook/projects/by-project/{project_id}` 参数含 `engine_mode`（query, optional）；`POST /audiobook/projects` 存在；`engine-preferences` 端点注册。
- 浏览器端到端（Browser subagent）：Swagger UI 正常加载（361 路径/407 端点），`engine_mode` 查询参数确认可见；截图 tmp/e2e_freeze_swagger.png。
- 结论：Phase 1.4-1.6 改动零回归，向后兼容（无快照批次走实时配置回退，不传 engine_mode 行为不变）。

### 5.7 Phase 1.2 引擎分支服务 + Phase 1.3 API 合约（2026-08-15）

- `python -m pytest backend/tests/test_project_audio_config_engine_branch.py -v` → `43 passed`：覆盖 get/set_engine_branch、resolve_engine_mode（auto 判定优先顺序）、get/set_characters_for_model（§2.2 五层回退）、get/set_audio_fx（引擎分支+旧顶层 fallback）、get/set_scene_generation_preferences（含旧键迁移映射）、snapshot builder（fingerprint 确定性+差异校验）、常量完整性。
- `python -m pytest backend/tests/test_audio_config_api_engine_branch.py -v` → `7 passed`（真实 PostgreSQL，专用 schema `audiobook_audio_config_api_test`，结束 `DROP SCHEMA CASCADE`）：GET audio-config 返回 engines 字段与 resolved engine_mode；PUT 写入引擎分支（验证引擎分支持久化+旧顶层未被覆盖）、engines 字段合并写入、legacy_stems 默认模型镜像顶层；GET engine-preferences 按 seed_scene/legacy_stems 分别返回 scene_generation_preferences/audio_fx。
- 应用冒烟：`from app.main import app` 加载成功，411 条路由全部注册。

### 5.1 Phase 1.1 Expand 迁移应用（dev 库）

- `alembic upgrade expand_canonical_migration_progress` 与 `alembic upgrade expand_audiobook_isolation_schema` 均成功应用，`alembic current` = `expand_audiobook_isolation_schema (head)`。
- dev 库产物核验（`.tmp/verify_expand.py`）：8 张新表齐全；append-only trigger `trg_ledger_reconciliation_audits_append_only`、`trg_scene_edit_revisions_append_only` 存在；`audiobook_tasks.status` 扩至 32 且 `ck_audiobook_tasks_status_stage1` 存在；复合唯一键 `uq_chapter_audio_run_scope`、双指针复合外键、部分唯一索引均落库。

### 5.2 Phase 1.1 Expand 合同测试（真实 PostgreSQL，14 项全绿）

- 命令：`python -m pytest backend/tests/test_audiobook_expand_schema_contract.py -v`（仓库根目录运行）
- 结果：`14 passed`。覆盖 ledger 四态 CHECK/可结算性、audit 单调性、append-only trigger（dev 库事务回滚）、双指针 RESTRICT、部分唯一索引。
- 隔离：专用 schema `audiobook_expand_test`，结束 `DROP SCHEMA CASCADE`，不污染 dev 数据；trigger 验证走 dev 库单事务整体回滚。
- 进度表合同：`python -m pytest backend/tests/test_canonical_migration_progress_contract.py -v` 12 项全绿（此前已记录）。

### 5.3 Phase 1.1 Migrate 执行器与报告（真实 PostgreSQL）

- `python -m pytest backend/tests/test_canonical_dedup_migrator_contract.py -v` → `11 passed`：canonical 优先级、事务 A 同事务 completed、软删除无物理删除、断点续跑跳过/重跑、事务 B fail-closed、会话锁忙退出与正常释放。
- `python -m pytest backend/tests/test_canonical_migration_report_contract.py -v` → `4 passed`：进度聚合、全表无重复 active 验证、completed 不一致组枚举、ready_for_contract_index 门禁。
- 四套件回归：`python -m pytest backend/tests/test_canonical_migration_progress_contract.py backend/tests/test_audiobook_expand_schema_contract.py backend/tests/test_canonical_dedup_migrator_contract.py` → `37 passed`（报告套件另计）。
- 执行器落点：`app/services/audiobook/canonical_dedup_migrator.py`（`select_canonical`/`_merge_group_txn`/`run_canonical_dedup_migration`）；报告落点：`app/services/audiobook/canonical_migration_report.py`（`build_migration_report`）。

### 5.4 实施中发现并修正的事实偏差

- `chapter_audios.id` 参与双指针复合外键本地列，SQLAlchemy 隐式关闭自增；已在模型显式 `autoincrement=True` 保持与 dev 库 SERIAL 一致（不影响既有数据）。
- ORM 侧 `Project`/`Chapter` 的 `status`/`word_count`/`display_no` 等仅 Python 默认无 server default，裸 SQL 种子须显式补值（已在测试中补齐）。

### 5.5 阶段验证：应用冒烟与真实 API/浏览器端到端（2026-08-15）

- 应用冒烟：`from app.main import app` 加载成功，118 条 audiobook 路由全部注册。
- 真实 API 端到端冒烟（uvicorn 127.0.0.1:8000，`.tmp/e2e_smoke.py`，已随任务清理）：openapi 可达、注册/登录、/auth/me、GET /audiobook/projects、POST /projects、GET audiobook by-project 全部 200，FAILED: 0——验证 Expand 不破坏旧版本 API 路径（R19 Expand 原则）。
- 浏览器端到端（Browser subagent，管理员会话）：主界面/有声书仪表盘/项目详情章节队列均正常渲染；36 条 XHR/fetch 全部 200，无 4xx/5xx，控制台无严重错误。截图证据：tmp/e2e_main_home.png、tmp/e2e_audiobook_dashboard.png、tmp/e2e_audiobook_project_detail.png。
- 结论：Phase 1.1 Expand/Migrate 对存量功能零回归；Contract 单元（唯一索引/NOT NULL/CHECK 收窄）待门禁证据齐备后另行执行。

### 5.6 Phase 1.1 Migrate 历史回填 + Contract 收窄（2026-08-15）

**历史回填**（`app/services/audiobook/history_backfill.py`，单事务、幂等确定性）：
- `python -m pytest backend/tests/test_history_backfill_contract.py -v` → `7 passed`。
- dev 库执行报告：projects engine_mode=40、snapshot_status=40、run_engine_mode_snapshot=76、synthetic_chapter_audios_created=24、runs_repointed=76、celery_task_id=35、dispatch_status=76；二次执行全部为 0（幂等复核通过）。

**Contract 收窄**（`app/services/audiobook/contract_constraints.py` + `backend/alembic/versions/contract_audiobook_isolation_schema.py`）：
- `python -m pytest backend/tests/test_contract_constraints_contract.py -v` → `6 passed`：fail-closed 数据门禁（NULL 残留/快照不一致拒绝收窄）、CHECK 值域拒绝、部分唯一索引 INVALID 身份校验与重建。
- 六套件全量回归：progress(12) + expand(14) + migrator(11) + report(4) + backfill(7) + contract(6) = `54 passed`。
- dev 库产物核验（验证 SQL 输出）：5 个新 CHECK（ck_audiobook_projects_engine_mode/snapshot_status/snapshot_consistency、ck_chapter_audio_runs_dispatch_status/status）；engine_mode/dispatch_status = NOT NULL + server default；`uq_chapter_audio_active_unique` valid=True ready=True，定义 `CREATE UNIQUE INDEX ... (audiobook_project_id, chapter_id) WHERE (deleted_at IS NULL)`；`ix_audiobook_projects_engine_mode_deleted` 存在；数据 sanity：engine_mode NULL=0、chapter_audio_id NULL=0、dispatch NULL=0、celery NULL=0、重复 active 组=0。`alembic current` = `contract_audiobook_isolation_schema (head)`。
- 写路径兼容：模型补 `server_default` 后 ORM 省略列由 DB 默认兜底；`app_service.py` 创建批次显式写 engine_mode/snapshot_status。Contract 收窄后浏览器端到端 36 条请求全部 200（延续 §5.5 会话复核），存量读写路径零破坏。

**暂缓项清单**（门禁依赖新写路径代码，另行排期）：

| 暂缓项 | 解锁门禁 |
|---|---|
| `snapshot_status` NOT NULL | 全部 project 构造点显式写入三态值 |
| `chapter_audio_runs.chapter_audio_id` NOT NULL | 新派发路径保证 run 必挂 chapter_audio（本轮已回填历史 NULL） |
| `celery_task_id` NOT NULL + UNIQUE | 新派发协议每 run 独立 task id（旧批量入队共享 id，本轮已回填 legacy-run-{id}） |
| `audiobook_tasks` CHECK stage2 收窄 | 先部署新代码 + drain 旧 worker，再施加（R14/P1-b，严禁先迁移后部署） |
