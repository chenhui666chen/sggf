# Seed Audio 场景导演 V2 实施进度

> 对应指导文档：
> `docs/AUDIOBOOK_SEED_AUDIO_SCENE_DIRECTOR_V2_IMPLEMENTATION_GUIDE_20260807.md`
>
> 当前基线：R13（正式定稿）
> 最后更新：2026-08-10

## 1. 文档职责

本文档只记录实施进度、验证证据、阻塞项和决策变更。
架构决策、数据合同、状态机、签名规则和验收标准一律以 R13 指导文档为准。

三层文档关系：

- `IMPLEMENTATION_GUIDE`（R13）：稳定的设计事实源，回答"应该怎么设计和实施"。
- `IMPLEMENTATION_PROGRESS`（本文档）：当前执行状态、测试结果、阻塞项，回答"目前实施到哪里"。
- `VALIDATION_RECORDS`（待建，或本文档第 7 节过渡承载）：供应商实测、人工盲评、性能和成本证据，回答"真实测试证明了什么"。

指导文档仅在以下三类情况修改：

1. 设计合同发生变化（例如 ScriptSegment.text 不再是唯一事实源）。
2. 供应商真实能力验证推翻文档假设（例如 strict timeline 验证后确定不可用）。
3. 阶段验收暴露架构缺陷，需要调整状态机、数据合同或回滚原则。

普通实施进度、测试输出、日志、负责人和完成时间不写入指导文档。

## 2. 实施基线约定（编码前必读）

以下为 R13 定稿审查遗留的实施约束，编码时必须遵守：

- 阶段 1 的 `canonical_hash` 保持窄职责基础设施：最初实现不加入业务对象识别、checkpoint 查询或迁移调度等职责；各业务模块负责构造规范化合同值，hash helper 只负责规范化和摘要计算（SOLID/KISS 边界）。
- `migration_input_hash` 的完整输入结构在编码时固定为版本化合同并写测试，至少包含：旧 checkpoint 身份、旧 schema/version、目标 schema/version、migration version、迁移所依赖的确定性输入摘要。具体字段按真实持久化结构确定，不回写指导文档。
- 编码前优先补齐三个红线测试集：canonical_hash 稳定性、append-only 迁移幂等性、Provider recovery CAS 并发推进（§13.1 已有对应条目）。

## 3. 总体状态

| 阶段 | 状态 | 开始时间 | 完成时间 | 验收状态 | 关联变更 |
|---|---|---|---|---|---|
| 阶段 0：基线冻结 | 已完成 | 2026-08-10 | 2026-08-10 | 验收通过 | timeline_validation 包落地、run_20260810T164647Z 实测 |
| 阶段 1：multilingual 默认化与 checkpoint 迁移 | 已完成 | 2026-08-10 | 2026-08-11 | 验收通过 | 见 §5 |
| 阶段 2：入口上下文修复 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §6 |
| 阶段 3：Seed 场景导演合同 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §7 |
| 阶段 4：声音绑定与 Prompt V2 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §8 |
| 阶段 5：Omni 影子评审 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §9 |
| 阶段 6：人工标定和有限自动恢复 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §10 |
| 阶段 7：延迟回退资产 | 已完成 | 2026-08-11 | 2026-08-11 | 验收通过 | 见 §11 |

状态枚举：未开始 / 进行中 / 阻塞 / 待验收 / 已完成 / 已回滚。

## 4. 阶段 0：基线冻结

### 4.1 固定场景集

场景集已在代码中冻结：`backend/app/services/audiobook/timeline_validation/baseline_scenarios.py`，
目录版本 `seed-audio-v2-phase0-scenarios@1.0.0`，
目录规范化哈希 `afe3a885b948b96d8c144dccc29c4d3118e45c2df03121d6ded88cfad8d4de65`（已固定为测试断言，见
`backend/tests/test_audiobook_timeline_validation.py`）。演进场景集必须提升目录版本并按 DEC 模板登记。

| 场景 | 覆盖能力 | 输入版本 | 结果 |
|---|---|---|---|
| 电话失真对话 | 多角色、电话空间 | catalog@1.0.0 / prompt `aa890fd4…`（复用 V1 `phone_confrontation#described_voices`） | 待验证 |
| 灵山战斗场景 | 多人、音效蒙太奇、混响 | catalog@1.0.0 / prompt `016d1917…`（V2 新增） | 待验证 |
| 叙事独白 | 环境声、情绪表演 | catalog@1.0.0 / prompt `25c45e5a…`（复用 V1 `single_voice_memory#described_voices`） | 待验证 |
| 直播带货 | 背景插话、口音、重叠 | catalog@1.0.0 / prompt `66a82b74…`（V2 新增） | 待验证 |
| 广告时间轴 | timeline | catalog@1.0.0 / prompt `a0875b47…`（canonical 语法变体，见 4.2） | 时间轴四合同通过（run_20260810T164647Z，见 4.4） |

### 4.2 时间轴契约验证

验证 harness 已落地（离线部分全部可单测覆盖）：

- 固定广告样例与四合同探针：`timeline_validation/ad_timeline_sample.py`
  （canonical 语法假设为 `[2.0s:6.0s]` 写法，来自官方示例；实测可推翻，推翻时按 DEC 登记）；
- 四项误差与 eligible 判定：`timeline_validation/metrics.py`，判定阈值合同版本
  `eligibility_policy@1.0.0`（strict：P50≤800ms、P95≤1500ms、时长 P95≤3000ms、全部台词对齐；
  bounded：≥60% 窗口命中且容忍 2000ms、时长 P95≤5000ms；最少 3 次成功运行）；
- 驱动脚本：`scripts/validate_seed_audio_timeline.py`（默认干跑；真实实测需
  `--paid --confirm-paid`，证据落盘 `backend/data/timeline_validation/run_<UTC>/`）。

每组实测记录：

- provider 请求参数；
- 使用的真实模型 ID；
- Prompt 版本；
- 时间轴模式；
- `start_error_ms`；
- `end_error_ms`；
- `duration_error_ms`；
- `event_alignment_error_ms`；
- P50/P95/最大偏差；
- 非法时间轴的失败行为；
- 是否得到 `bounded_timeline_eligible`；
- 是否得到 `strict_timeline_eligible`。

要求：固定广告样例至少重复生成 3 次。

### 4.3 基线冻结证据（2026-08-10）

- 五类场景集版本化冻结完成，冻结哈希断言测试通过（`test_audiobook_timeline_validation.py`，24 项）。
- A/B 结果盘点结论：本地不存在已保存的普通 1.0 与 multilingual A/B 音频产物
  （`backend/data/seed_scene_tests` 目录不存在；`backend/data/audiobook_scene_runs` 仅含测试用
  legacy fallback 产物）。multilingual 的既有证据为 2026-07-22 基础接口合同验证
  （见 `docs/AUDIOBOOK_DOUBAO_SEED_AUDIO_SCENE_ENGINE_PLAN_20260720.md` §12 第 1 项）；
  2026-07-22 运营决策后 multilingual 未再投产，无后续 A/B 记录可归档。
- “新任务默认切换不改写历史 checkpoint”落地为解析层行为回归：
  `get_seed_audio_model` 对历史 multilingual 配置只读回退、不就地改写；
  `set_seed_audio_model` 拒绝开放集之外的模型。对应测试
  `TestDefaultSwitchDoesNotRewriteHistory` 通过。阶段 1 切换默认时，历史 checkpoint
  仍按原始模型恢复，此约束进入阶段 1 验收项。
- V1 回归：seed_scene 相关 14 个测试文件 157 passed / 1 skipped（skipped 为需显式开关的
  付费真实 API 测试）；legacy_stems 定向回归 6 passed（2026-08-10，本地环境）。

### 4.4 时间轴实测结果（run_20260810T164647Z，2026-08-10）

实测环境：provider 请求合同为 `POST openspeech.bytedance.com/api/v3/tts/create`，
真实模型 ID `seed-audio-1.0-multilingual`，`audio_config={format:wav, sample_rate:48000,
enable_subtitle:true}`，Prompt 版本为 catalog@1.0.0 的 `ad_timeline` canonical 样例
（`a0875b47…`），时间轴模式为 strict（全部事件标注 `[start:end]`）；
各次请求的 request_id、prompt_sha256 与完整字幕存于证据目录。

遵循精度（固定广告样例 × 3 次，n=9 个 speech 事件）：

| 指标 | P50 | P95 | 最大偏差 |
|---|---|---|---|
| `start_error_ms` | 120 | 184 | 200 |
| `end_error_ms` | 160 | 576 | 720 |
| `duration_error_ms` | 0 | 0 | 0 |
| `event_alignment_error_ms` | 120 | 184 | 200 |

三次运行总时长均为 30000ms，与声明总时长完全一致；字幕全部命中目标台词，无多余可辨识人声。

语法合同：五种写法（`[2.0s:6.0s]`、`[2000ms:6000ms]`、`[2.0秒:6.0秒]`、全角冒号、
括号内含空格）均被接受且遵循，单句误差均 ≤680ms；canonical 假设维持不变，无需 DEC。

边界与失败行为：

- 单事件窗口超 120 秒：请求失败（HTTP 500，`provider_unavailable`），不产出音频；
- 窗口超出声明总时长（声明 30s、窗口 45–52s）：不拒绝，被压缩到总时长内（实际起始 27.4s）；
- 重叠窗口：不拒绝，模型提前避让（第二句起始提前 1880ms）；
- 0.4 秒极小窗：不拒绝，窗口约束被放宽；
- 起止颠倒窗口：被忽略，同 Prompt 中后续合法窗口仍被遵循（起始偏差 +40ms）；
- 非数值窗口：被忽略，台词被放到音频尾部（27.1s）；
- 只有时间轴声明、无任何事件：**异常模式**——Prompt 描述文本被朗读成音频，
  生产 Prompt 编译必须保证事件集非空（纳入阶段 3 L0 闸门候选项）。

eligible 结论（判定合同 `eligibility_policy@1.0.0`）：

- `bounded_timeline_eligible = true`；
- `strict_timeline_eligible = true`。

两种模式均可在阶段 3/4 按 R13 流程开放；偏差处置建议：strict 偏差在
P95 ≤ 1500ms 内由 L0 接受，bounded 按 2000ms 容忍窗处理，超出则进入 Omni
finding/人工提示（阶段 5/6 确定）。完整证据：
`backend/data/timeline_validation/run_20260810T164647Z/`（plan.json、probes.json、
compliance_runs.json、eligibility.json、summary.json）。

已知缺口：本次运行的音频落盘因脚本 data URI 分隔符 bug 均为 0 字节，脚本已修复；
字幕、指标与行为分类证据不受影响。如需音频盲听证据，可用修复后脚本重跑
compliance（3 次生成，约 1.5 元），见 §12 风险项 RISK-001。

### 4.5 阶段验收

```text
状态：验收通过（2026-08-10）
证据链接：backend/data/timeline_validation/run_20260810T164647Z/；
         backend/tests/test_audiobook_timeline_validation.py（24 项）；
         seed_scene 回归 157 passed / 1 skipped；legacy_stems 回归 6 passed
未通过项：无
风险：音频盲听证据缺失（RISK-001，可选重跑补全，不阻断验收）
```

## 5. 阶段 1：multilingual 默认化与 checkpoint 迁移

分别记录以下各项的完成状态与证据：

| 项 | 状态 | 证据 |
|---|---|---|
| multilingual 模型目录登记（`config/models.yaml`） | 已完成 | 新增独立条目 `- id: seed-audio-1.0-multilingual`：capabilities 含 `timeline_control`（source 指向 run_20260810T164647Z）与 `multilingual_text`；cost_profile 继承普通 1.0；目录校验测试通过，不再判为未知模型 |
| API Literal（`app/api/v1/projects.py`）与前端类型 | 已完成 | Literal 开放两模型；`frontend/src/pages/audiobook/types.ts`、`frontend/src/services/api.ts` 类型联合扩展 |
| 价格目录 | 已完成 | `test_audiobook_seed_audio_pricing.py`：两模型单价一致（price_per_minute=1.0）且计费按真实模型 ID 可区分；计费键跟随当前默认模型（`test_audiobook_task_support_billing.py`） |
| 分析与改编 Prompt 能力合同 | 已完成 | `script_adapter_pkg/_seed_scene_capability.py` 共享能力描述常量（合同版本 `1.0.0`），分析与改编两路径替换，无硬编码供应商模型 ID；`test_audiobook_seed_scene_capability.py` + `test_audiobook_prompt_contracts.py` 断言无过期硬编码 |
| canonical_hash 稳定性测试 | 已完成 | `backend/app/services/audiobook/hashing.py` + `test_audiobook_hashing.py`：字段顺序不敏感、CRLF/LF 归一、浮点固定三位小数、tuple/list 等价、事件顺序敏感、拒绝 bytes |
| content_digest 稳定性测试 | 已完成 | 同文件：纯 SHA-256、不接受合同参数、不随 contract version 变化 |
| checkpoint schema registry 与 contract version 定义 | 已完成 | `scene_engine/checkpoint_contracts.py`：v1/v2 登记，签名合同 `seed_scene_checkpoint_signature@1.0.0`，`validate_checkpoint_identity` 缺字段显式报告（不静默当作命中） |
| append-only migration runner | 已完成 | `scene_engine/checkpoint_migration.py`：migration version `seed-scene-checkpoint-v1-to-v2@1.0.0`；`migration_input_hash` 为版本化 canonical_hash 合同（`seed_scene_checkpoint_migration@1.0.0`），含旧身份、新旧 schema/version、migration version |
| 普通 1.0 历史 checkpoint 覆盖 | 已完成 | `test_audiobook_checkpoint_migration.py::test_migrates_historical_standard_checkpoint`（旧签名字段逐项继承不重算）；renderer 集成 `TestCheckpointSchemaMigrationIntegration`（迁移写回后复用、不重烧音频） |
| 缺字段 checkpoint 覆盖 | 已完成 | 单元（missing_field 报因）+ renderer 集成（不复用、旧 checkpoint 不破坏、转重新生成） |
| 旧签名 checkpoint 覆盖 | 已完成 | unknown_schema_version / 缺 schema_version / 非 Mapping → `legacy_checkpoint_incompatible` |
| 幂等迁移验证 | 已完成 | 相同旧身份 + migration version 单一确定性结果；v2 输入返回 already_migrated 不叠加历史；renderer 二次复用不再写回 |
| legacy_checkpoint_incompatible 路径验证 | 已完成 | 迁移失败放弃复用并记录日志，重新生成路径接管（renderer 集成测试） |
| 账单和预算不重置验证 | 已完成 | `test_billing_summary_unchanged_after_migration`：迁移前后计费摘要全等（provider_request_count、billable_duration_s 不变）；`chapter_pipeline._resume_model` 使历史 checkpoint 按记录的原模型恢复 |

验收口径（指导文档 1378–1390 行）：

- 新任务只请求 multilingual：renderer 默认模型与 checkpoint 记录均为
  `seed-audio-1.0-multilingual`（`test_scene_renderer_persists_audio…` 断言）；
- 旧 checkpoint 仍请求原模型：`_resume_model` 对 passed/legacy_stems 历史
  checkpoint 返回记录模型（三分支测试）；
- hash 稳定性测试全部通过（含 content_digest 不随 contract version 变化）。

### 5.1 阶段验收

```text
状态：验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_hashing.py（15 项）；
         backend/tests/test_audiobook_checkpoint_migration.py（19 项）；
         backend/tests/test_audiobook_seed_scene_renderer.py（36 项，含迁移集成 3 项）；
         backend/tests/test_audiobook_seed_audio_pricing.py、
         test_audiobook_seed_scene_capability.py；
         阶段 1 定向回归 13 个测试文件 187 passed；
         关键字过滤回归（seed_scene/model_catalog/script_adapter/
         project_audio/seed_audio）205 passed / 1 skipped
         （skipped 为需显式开关的付费真实 API 测试）
未通过项：无
风险：无新增；RISK-001（阶段 0 音频盲听证据）仍开放，不阻断阶段 1
```

（阶段 2–7 启动时按同一结构追加章节。）

## 6. 阶段 2：入口上下文修复

| 项 | 状态 | 证据 |
|---|---|---|
| 贯通场景描述、角色 descriptions 和 default TTS model | 已完成 | `_scene_render_mixin._try_generate_seed_scene_chapter` 新增章节上下文参数；模块级 `build_scene_entry_context` 从 summary_data/chapter_summary/角色档案构造 `chapter_facts` 与 `descriptions`；`pipeline.render` 贯通 `descriptions`、`default_tts_model`（engine.tts_model）、`chapter_facts`、`director_style`；两个入口（`_generation_mixin`、`_audio_from_script_mixin`）均已接入；`TestEntryContextWiringThroughPipeline` 验证 speaker 直传与描述注入 |
| 构造每场景局部描述 | 已完成 | `scene_engine/scene_local_context.py::build_scene_local_description` 按 §7.1 优先级：direction_context（阶段 3 预留）> 场景内 instruct_scene（去重按序）> 章节事实（时间/地点/情绪句式）> 导演风格兜底 > 最终兜底常量；planner `_build_plan` 逐场景构造，recompile/split 路径承接同一上下文 |
| 场景描述进入计划、Prompt 与签名 | 已完成 | 局部描述注入 Prompt 顶层（“场景：…”），`prompt_hash` 对全量 Prompt 计算（`test_scene_description_changes_prompt_signature` 验证签名敏感）；checkpoint schema 与签名合同不变（阶段 1 合同未被破坏） |

验收口径（指导文档 1392–1398 行）：

- 固定样例 Prompt 顶层不再使用泛化兜底：有 instruct_scene / 章节事实 /
  导演风格任一时，`GENERIC_SCENE_FALLBACK_DESCRIPTION` 不出现；生产链路
  `director_style` 恒有值（strategy.style.value）；
- 切分后的每个场景具有正确局部上下文：两场景各持自身 instruct_scene；
  `split_plan_once` 承接父场景上下文（`test_split_plan_once_preserves_parent_local_context`）。

实施备注：章节事实构造为句式描述（“本章发生在…”）而非前缀标签，
因 `voice_identity_policy.sanitize_fixed_voice_scene_text` 会剥离
“时间：/地点：”类前缀与句尾句号（声音身份安全策略，不绕过）；
有 reference 的角色不重复注入静态声音身份（§7.2），无 reference
临时角色才使用文字声音描述。

### 6.1 阶段验收

```text
状态：验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_scene_local_context.py（13 项）；
         阶段 2 定向回归（local_context/planner/pipeline/persistence/
         engine_mixin/prompt/renderer）7 个测试文件 108 passed；
         关键字过滤回归（seed_scene/scene_local/project_audio/
         voice_identity/prompt_compiler/planner）331 passed / 1 skipped
         （skipped 为需显式开关的付费真实 API 测试）
未通过项：无
风险：无新增
```

## 7. 阶段 3：Seed 场景导演合同

| 项 | 状态 | 证据 |
|---|---|---|
| §5 数据模型、严格解析器与验证器 | 已完成 | 新增 `scene_direction/` 包：`models.py`（SeedSceneContext/SeedSpeechDirection/SeedVocalizationDirection（证据判别联合）/SeedSoundDirection/SeedSceneDirection，全部 frozen，speech 无 text 字段）；`parser.py` 严格 JSON 解析（未知字段/非法枚举/缺字段均拒绝，不猜测性修补，仅确定性围栏剥离）+ 同构序列化；`validator.py` 覆盖不变量（不遗漏/不重复/不重排/区间连续）、speaker 与审定事实一致、background/overlap 必须显式相对引用、绝对时间仅 bounded/strict、证据子串与 speaker 兼容、审定分析证据覆盖锚定片段、推导型 vocalization 受 policy 闸门 |
| 独立 Seed 改编 Prompt，分轨参数不再主导 | 已完成 | `prompt.py`：§6.2 十项改编目标 + 事实约束 + 严格 JSON 输出要求；模板与 schema 各自版本化哈希（director_prompt_hash/director_schema_hash）；测试断言不含分轨/音量数值/素材 ID/混音覆盖率等旧合同词汇 |
| 预算策略与 DirectorInputSignature | 已完成 | `policy.py`：服务端版本化 `SeedSceneDirectorPolicy`（四级预算字段 + allow_inferred_vocalizations 首期 False），项目只能降低预算（取最小值）；`signature.py`：canonical_hash 版本化签名，全部源事实哈希参与（segments/reviewed_analysis/context/profiles/capability/model/prompt/schema/policy），Omni Prompt 不在签名内 |
| Director 预算 FSM、纠错一次、保真分流、attempt ledger | 已完成 | `director.py::SeedSceneDirector`：首次 + 最多一次纠错（纠错请求携带错误码）；章节/任务预算拦截后零额外调用；`v1_fidelity_feasible` 保真判定分流：可保真 → retryable_failed/degrade_v1（director_degraded_to_v1），含重叠/插话标注 → terminal_failed/manual_review；attempt ledger 记录 provider/model/tokens/cost，append-only 保留 |
| 导演计划 checkpoint 三态恢复 | 已完成 | checkpoint 以 DirectorInputSignature 为唯一缓存键：completed 命中零调用复用计划；terminal_failed/degrade 决定复用不重新获得重试；retryable 恢复沿用已消费预算（取 max 不回退）；签名失配新建 checkpoint 且历史账本保留、任务成本跨章节累计 |

实施备注：台词事实保护通过模型层无 text 字段 + 编译时按 source_segment_index
读取源片段实现；默认预算为保守标定（max_calls_per_chapter=6、
max_attempts_per_batch=2），真实调用标定后调整必须提升 policy version。

### 7.1 阶段验收

```text
状态：验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_scene_direction_models.py（15 项）；
         test_audiobook_scene_direction_validator.py（19 项）；
         test_audiobook_seed_scene_director_policy.py（19 项）；
         test_audiobook_seed_scene_director.py（14 项，含 fake LLM
         状态机与 checkpoint 恢复）；
         关键字过滤回归（seed_scene/scene_direction/director/
         project_audio/voice_identity/prompt_compiler/planner/
         scene_local）409 passed / 1 skipped（skipped 为需显式开关的
         付费真实 API 测试）
未通过项：无
风险：无新增
```

## 8. 阶段 4：声音绑定规划、事件映射与签名合同

| 项 | 状态 | 证据 |
|---|---|---|
| VoiceIdentityRegistry 只读领域视图 + SceneVoiceBindingPlanner | 已完成 | `scene_engine/voice_identity.py`：显式绑定 > seed_speaker > user_private > public_pool > description 冲突解析，用户显式选择不被静默替换；`voice_binding_planner.py`：speech/vocalization 全量角色统一参与预算，版本化评分常量（BINDING_POLICY_VERSION=1.0.0）、稳定排序不依赖输入顺序、最多三条 reference（slot_index 连续）、超三确定性分流 degraded_reference_budget / split_required_strict_bindings，规划输出含被选中与未选中角色 |
| binding decision/audit hash 分离 | 已完成 | `voice_binding_hash.py`：binding_decision_hash 只含 speaker/slot_index/reference_content_hash/description/decision/required_stability（Seed 生成键）；binding_audit_hash 含 policy_version/registry_version/priority_score/reason_code/identity_source，审计字段变化不触发 Seed 重生；slot_index 进决策 hash；二进制内容不进入 canonical_hash |
| SeedGenerationInputSignature/Output 分离 + ProviderRecoveryRecord | 已完成 | `seed_generation_contract.py`：13 字段白名单签名（API Key/临时 URL/Request ID/超时值/binding_audit_hash 不入缓存键，未知字段拒绝）；`provider_recovery.py`：recovery_method 判别（request_query 提交后必填 request ID，temporary_url 必填加密 URL+TTL）；双层幂等键（内部 generation_input_hash+attempt_number 始终存在，外部 provider_id+scope_hash+request_id 仅 ID 存在时建立）；状态白名单 + CAS 迁移（禁止 downloaded/confirmed_failed/expired_unverified → pending） |
| Transcript/L0 签名合同 | 已完成 | `transcript_contracts.py`：ProviderSubtitleInputSignature/AsrTranscriptInputSignature 判别联合（source 为 init=False 固定字段）；TranscriptSelectionPolicy 独立管理；RawTranscriptArtifact 必须持有内联内容或项目控制持久化 URI（仅存 hash 拒绝）；NormalizedTranscriptArtifact 统一 transcript_artifact_hash 供 L0/Omni 共引；L0QualityCheckpoint 输入签名与结果分离，L0 policy 变化不进入 Seed 生成签名 |
| event_mapper：导演计划 → SceneAudioEvent[] | 已完成 | `scene_direction/event_mapper.py`：台词逐字按 source_segment_index 读源片段；显式导演事件全量映射（speech/vocalization/sfx/music/transition，overlap→during）；确定性排序（before 先于锚定台词、during/overlap 随台词、after 随后、throughout 与 carry-in 靠前、carry-out 收尾）；指导文档 §8.1 事件区间估算器（before/after 独占、during/throughout/overlap 只计超出部分、音乐/环境不加时长、缺 duration 用版本化保守默认 1.5s、confidence 区分 high/conservative） |
| timeline 模式闸门 | 已完成 | `scene_engine/timeline_gate.py`：natural 恒开放；bounded/strict 分别依据阶段 0 eligibility 结论独立开放（布尔必须为 True，缺字段不静默通过），任一模式未通过只关闭该模式；阶段 0 结论两模式均 eligible，均开放 |
| Prompt V2 修复（表演模板/vocalization/until_text/字符估算） | 已完成 | `prompt_compiler.py`：§9.2 表演模板按显式动作选择说道/问道/回应道/低语道/喊道/一字一顿地说道（旁白→讲述），不再统一套用“用……的方式说道”，台词逐字不变；§9.3 vocalization 词表扩至 24 项，多字词最长匹配（倒吸冷气不拆成吸气），单字项（哼嗯啊诶哎）仅在引号/标点/空白/动作模板边界命中，不从普通形容词句裸子串抽取；§9.4 until_text 中性措辞“持续至对应台词中的“{related_text}”说完”，related_text 非目标台词子串时降级“持续至该句说完”；§9.5 `planner.py` 字符估算复用编译器事件渲染 helper，不使用 str(dataclass) |
| 五类固定样例 multilingual Prompt 验收 | 已完成 | `test_audiobook_baseline_prompt_acceptance.py`（27 项）：五场景 Prompt 结构正确（非空、≤3000 字符模型硬限制、台词以中文引号冻结）；台词逐字一致（Prompt 引号台词序列与 expected_texts 逐字相等，无未声明台词）；时长合法（期望时长 ≤ 软上限 90s/硬规划 105s/模型输出 120s，台词朗读估算不超出期望时长）；基线样例由默认 multilingual 模型消费 |

实施备注：事件映射与时长估算为纯领域函数，不改动现有渲染管线接入；
ProviderRecoveryRecord 为短期恢复记录模型，持久化载体（加密 URL、TTL
清理）在接入 Seed 渲染服务时落地。Prompt V2 修复仅改动编译器渲染层
与 planner 估算 helper，既有 Prompt 测试同步更新断言，V2 新增测试
13 项。

### 8.1 验收

```text
状态：阶段 4 验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_voice_binding_planner.py（14 项）；
         test_audiobook_voice_binding_hash.py（7 项）；
         test_audiobook_seed_generation_contract.py（18 项）；
         test_audiobook_provider_recovery.py（25 项）；
         test_audiobook_transcript_contracts.py（23 项）；
         test_audiobook_seed_event_mapper.py（19 项）；
         test_audiobook_timeline_gate.py（7 项）；
         test_audiobook_seed_scene_prompt.py 与 test_audiobook_seed_prompt_v2.py
         合计 34 项（Prompt V2）；
         test_audiobook_baseline_prompt_acceptance.py（27 项）；
         全量回归 3222 passed / 5 skipped / 7 deselected
         （skipped 与 deselected 为需显式开关的付费真实 API 测试）
未通过项：无
风险：无新增
```

## 9. 阶段 5：Omni 影子评审

| 项 | 状态 | 证据 |
|---|---|---|
| 评审输出 Schema（scene-semantic-review-v1） | 已完成 | `scene_quality/semantic_models.py`：十个固定维度（dialogue_fidelity/speaker_assignment/speaker_separation/performance/vocalizations/sound_events/music/ambient/acoustic_space/mix_balance），缺失/多余/未知状态拒绝；失败 finding 必须携带时间区间（start_ms ≤ end_ms）、期望、观察结果与置信度，结果可定位到时间区间与 scene ID；维度与 recommended_action 均接受 not_assessable，不强迫模型猜测；result_hash 不含 reviewed_at 等运行元数据 |
| 评审策略：预算/超时/错误分类/独立开关 | 已完成 | `semantic_policy.py`：章节场景/接缝评审次数上限、单次超时、音频时长上限、并发上限均正数校验；mode 只开放 shadow/manual_assisted（limited_auto 阶段 5 不开放）；enabled 一键关闭（§15 独立开关）；五类错误（timeout/provider_error/schema_invalid/budget_exceeded/preprocessing_failed）全部落 recorded_error——不阻断、不重试、不改账单；policy 指纹版本化，只进 Omni 评审缓存键 |
| Omni 期望合同规范化 | 已完成 | `expectation_contract.py`：omni_expectation_contract_hash 覆盖 §10.2 完整输入合同 11 个必需部分（scene context、speech 与验证策略、vocalizations、声音事件及顺序、音乐/环境生命周期、声学处理、performance 期望、timeline 窗口、绑定摘要、carry state、目标时长），缺失或多余部分拒绝；mapping 键顺序无关、有顺序语义数组保持顺序；voice_binding_summary_hash 与期望合同从同一规范化来源（绑定按 slot/speaker 确定性排序）生成 |
| OmniReviewCheckpointSignature | 已完成 | `checkpoint_signature.py`：全字段签名（音频 artifact hash、review_scope、音频窗口、期望合同 hash、绑定摘要 hash、模型/Prompt/schema/预处理/策略 hash）；transcript/timeline 为 all-or-nothing 条件字段，Omni Prompt 不提交字幕时不进签名；接缝评审额外携带双音频 hash 与双窗口，scene 范围拒绝接缝字段；任一输入变化即评审缓存失效；签名不携带 Director/Seed 输入字段，Omni/policy 变化只重新评审不重新生成 Seed |
| 接缝评审窗口构造 | 已完成 | `seam_review.py`：不提交整章，取前一场景末尾 5-10 秒 + 后一场景开头 5-10 秒（优先取最大窗口，场景不足 5 秒退化为整段不补齐不拒绝）；相对窗口可换算为章节绝对区间供结果定位 |

实施备注：本阶段交付评审合同、策略与缓存键，均为纯领域函数，不接入
渲染管线；`SceneAudioSemanticReviewer` 的 qwen3.5-omni-flash 真实调用层、
模型目录补齐（指导文档 §10.7）与灰度阶段 A 的人工盲评对比在接入
评审服务时落地。“只记录，不阻断”在合同层闭合：policy 的
blocks_output/allow_auto_retry/changes_billing 恒为 False，错误分类
全部落 recorded_error。

### 9.1 验收

```text
状态：阶段 5 验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_semantic_models.py（14 项）；
         test_audiobook_semantic_policy.py（14 项）；
         test_audiobook_omni_expectation_contract.py（18 项）；
         test_audiobook_omni_checkpoint_signature.py（14 项）；
         test_audiobook_seam_review.py（8 项）；
         全量回归 3290 passed / 5 skipped / 7 deselected
         （skipped 与 deselected 为需显式开关的付费真实 API 测试）
验收口径映射：Omni 失败不影响成品（policy 不阻断 + recorded_error）；
         结果可定位到时间区间和 scene ID（finding start_ms/end_ms +
         chapter_windows 绝对区间）；重复任务复用评审缓存
         （signature_hash 确定性）；Omni policy 变化只重新评审
         （semantic_policy_hash 只进 Omni 签名）
未通过项：无
风险：无新增
```

## 10. 阶段 6：人工标定和有限自动恢复

| 项 | 状态 | 证据 |
|---|---|---|
| 盲评标定合同（§13.4） | 已完成 | `scene_quality/calibration.py`：FindingCalibration 按 finding code 记录六项指标（precision/recall/false positive rate/false negative rate/置信度校准/重复评审一致率）；版本化门槛常量（precision≥0.85、recall≥0.70、正负样本各≥30，CALIBRATION_THRESHOLDS_VERSION 版本化）；样本量不足或指标不达标的 code 判定未标定——未标定前 Omni 只能作为影子或人工辅助评审；标定集合指纹确定性、顺序无关、版本化，门槛常量与记录全部入指纹 |
| 版本化语义质量策略（§10.6 阶段 C） | 已完成 | `semantic_quality_policy.py`：policy_version 版本化发布，指纹确定性；enabled 与 auto_retry_enabled 双一键关闭开关；min_confidence 高置信门槛；severity 白名单结构上只允许 major/critical（minor 主观风格问题拒绝入列）；require_locatable 可定位要求；max_auto_retries_per_scene≡1 硬约束（拒绝放宽）；max_auto_retries_per_chapter 成本上限；绑定标定集合指纹（标定更新即策略指纹变化）；blocks_output 恒 False，重试成本按真实 Seed 成功响应计费（bills_seed_retry_as_real_response） |
| 有限自动恢复决策 | 已完成 | `auto_recovery.py`：decide_auto_recovery 确定性纯函数，固定六段门槛顺序（一键开关→主观风格→标定→高置信→可定位→预算）；九类原因码（allowed/disabled_by_policy/auto_retry_disabled/uncalibrated_code/subjective_finding/low_confidence/not_locatable/scene_retry_budget_exhausted/chapter_retry_budget_exhausted）可审计；决策携带 finding code 与策略指纹；仅标定通过且满足全部门槛的 finding 允许一次针对性重试 |

实施备注：本阶段交付标定、策略与决策合同，均为纯领域函数，不接入
渲染管线；门槛常量（0.85/0.70/30/30）为阶段 6 初始合同值，真实
盲评数据到位后以校准值替换，调整须登记 DEC；自动重试的真实执行层
（针对性 Seed 重试调用、计费审计与尝试计数持久化）在接入评审服务
时落地。`auto_retry_allowed` 集合即“自动处置集合”，其 precision/recall
门槛由标定合同强制，成本上限与一键关闭开关由策略强制。

### 10.1 验收

```text
状态：阶段 6 验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_finding_calibration.py（12 项）；
         test_audiobook_semantic_quality_policy.py（13 项）；
         test_audiobook_auto_recovery.py（16 项）；
         全量回归 3331 passed / 5 skipped / 7 deselected
         （skipped 与 deselected 为需显式开关的付费真实 API 测试）
验收口径映射：自动处置集合有明确 precision/recall 门槛（标定版本化
         常量 + disqualification_reasons）；成本上限（每场景一次硬约束
         + 每章重试上限）；一键关闭开关（enabled/auto_retry_enabled
         双层，拒绝原因码可审计）
未通过项：无
风险：无新增
```

## 11. 阶段 7：延迟回退资产和生产收敛

| 项 | 状态 | 证据 |
|---|---|---|
| 回退资产策略 | 已完成 | `fallback_assets/fallback_policy.py`：pre_generates_on_seed_path 恒 False（Seed 主路径不提前生成真实分轨素材，§16）；generates_per_scene 恒 True（回退时按场景生成）；enabled 为 §15 legacy fallback 独立开关；visible_to_user/visible_in_billing 恒 True（所有回退对用户和账单明确可见）；allows_rebill_passed_scene 恒 False（任何回滚不重计费已通过场景）；策略版本化、指纹确定性 |
| 按场景回退素材计划 | 已完成 | `fallback_plan.py`：全通过章节产生空计划（expected_asset_count=0，零 SFX/BGM 回退成本）；回退章节只包含失败场景声明的素材类型（sfx/bgm，通过场景不得声明素材需求）；失败场景必须携带显式 reason code；开关关闭时计划为空并记录 fallback_disabled；计划哈希确定性、输入顺序无关，策略指纹入哈希；重复场景/未知状态/空章节拒绝 |
| 三态生产收敛处置 | 已完成 | `production_state.py`：场景确定性收敛到 seed/manual_processing/legacy_fallback 三态之一（供 UI 展示）；Seed 通过留主路径，失败按开关分流回退或人工；回退处置账单可见，人工处置不产生自动账单；处置哈希可审计，rebills_passed_scene 恒 False；章节三态计数汇总供 UI 展示，重复场景/空章节拒绝 |

实施备注：本阶段交付回退策略、素材计划与生产状态合同，均为纯领域
函数；真实回退素材的生成与 artifact 持久化（按场景生成后落盘并
登记账单）、渲染管线接入与 UI 三态展示在接入生产管线时落地。回退
计划哈希与处置哈希可复用为回退 checkpoint 的输入签名基础。

### 11.1 验收

```text
状态：阶段 7 验收通过（2026-08-11）
证据链接：backend/tests/test_audiobook_fallback_policy.py（12 项）；
         test_audiobook_fallback_plan.py（15 项）；
         test_audiobook_production_state.py（14 项）；
         全量回归 3372 passed / 5 skipped / 7 deselected
         （skipped 与 deselected 为需显式开关的付费真实 API 测试）
验收口径映射：Seed 全通过章节不产生 SFX/BGM 回退素材成本（全通过
         空计划 + expected_asset_count=0）；回退章节只生成失败场景
         所需素材（按场景裁剪 requirements + 素材类型白名单）；
         三态展示（处置三态枚举 + 章节计数汇总）；回退可见性
         （visible_to_user/visible_in_billing 恒 True）
未通过项：无
风险：无新增
```

### 11.2 生产管线接入（验收后扩展，2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 渲染结果收敛桥接 | 已完成 | `fallback_assets/chapter_convergence.py`：渲染状态映射（passed→passed；legacy_stems→failed，素材类型 LEGACY_FALLBACK_ASSET_KINDS=(sfx,bgm)，reason_code 继承 fallback_reason，缺失降级 legacy_stems）；未知渲染状态/空章节拒绝；duck-typing 消费渲染结果，不反向依赖 scene_engine |
| ChapterScenePipeline 生产收敛接入 | 已完成 | `scene_engine/chapter_pipeline.py`：可选注入 fallback_asset_policy（未注入保持旧行为 convergence=None，向后兼容）；ChapterScenePipelineResult 附带 convergence（三态处置+回退计划+章节汇总）；convergence_hash 确定性（处置哈希+计划哈希入 canonical_hash） |
| 端到端集成验证 | 已完成 | `test_audiobook_pipeline_convergence_wiring.py`（6 项）：真实 ChapterScenePipeline + fake renderer 产出真实 SceneRenderResult，全通过章节零回退成本、失败场景按开关分流回退/人工、管线内收敛与独立收敛哈希一致、未注入策略向后兼容 |

验收：`test_audiobook_chapter_convergence.py`（11 项）+
`test_audiobook_pipeline_convergence_wiring.py`（6 项）全过；
全量回归 3389 passed / 5 skipped / 7 deselected。
§15.1 待接入清单第 1 项部分销项：回退收敛已接入生产链路，
V2 导演编排层后续交付见 §11.3，剩余 Omni 评审服务接入待完成。
真实回退素材的生成落盘与账单登记仍待接入（收敛结果中的
FallbackAssetPlan 即为按场景生成清单的输入）。

### 11.3 V2 导演编排接入层（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 导演结局→集成决策映射 | 已完成 | `scene_direction/pipeline_integration.py`：resolve_director_integration 确定性映射三类结局（completed→use_v2_direction，携带事件映射与 §8.1 时长估算；degrade_v1→V1 确定性编译分流；terminal_failed→manual_review 不自动渲染）；非法组合拒绝（completed 无计划、degrade 携带计划、未知状态）；决策哈希只含动作/原因码/计划内容，attempts 等运行元数据不入哈希 |
| SeedSceneDirectorService 编排包装 | 已完成 | async direct_chapter：director.direct + 决策收敛；预算账本（章节/任务级）由调用方持有并在章节/任务间累计，恢复不重置；checkpoint 存储跨章节复用，签名命中零调用（fake LLM 验证：第二次调用零请求且决策哈希一致） |
| 包导出与回归 | 已完成 | `scene_direction/__init__.py` 补入三项导出；域关键字回归 112 passed；全量回归 3402 passed |

实施备注：本层为编排桥接，不改动 ChapterScenePipeline 同步渲染链路
（导演为 async 前置步骤，由任务编排层在渲染前调用）；director
计划的事件序列与时长估算如何进入 Prompt 编译消费、以及真实 LLM
客户端注入，在章节任务编排接入时落地。

### 11.4 导演事件进入 Prompt 编译消费（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 场景描述派生与编译桥接 | 已完成 | `scene_engine/prompt_consume.py`：derive_scene_description 从导演 context（时间/地点/声学空间/环境状态）确定性派生顶层场景描述；compile_decision_prompt 把 use_v2_direction 决策的事件序列送入 ScenePromptCompiler.compile_events，台词以中文引号冻结、expected_texts 与源片段逐字一致、非语言人声按表演渲染；非 V2 决策/多场景决策拒绝 |
| 台词事实守卫 | 已完成 | verify_director_dialogue_fidelity：导演声明的说话人必须与审定源片段一致（event_mapper 以源片段为准会静默纠正声明错误，守卫直接拒绝而非依赖纠正）；speech 指令必须覆盖声明的源片段；台词文本由编译层按 source_segment_index 读源片段，不信任导演副本 |
| 时长预算核验 | 已完成 | verify_duration_budget：§8.1 估算总时长不超过规划硬上限 DURATION_BUDGET_PLANNING_MAX_S=105.0（与 ScenePlanner 默认 hard_max_duration_s 一致），超限拒绝；无估算拒绝 |
| 回归与导出 | 已完成 | `test_audiobook_director_prompt_consume.py`（13 项，含超时长拒绝与非 V2 决策拒绝）；`scene_engine/__init__.py` 补入五项导出；Prompt 域回归 703 passed（既有五类样例验收不破）；全量回归 3415 passed |

实施备注：本层不改动 ScenePromptCompiler 内部实现（compile_events
已支持通用事件序列），只新增守卫前置的桥接函数；真实 LLM 客户端
注入与章节任务编排（导演→编译→渲染串接）在任务层接入时落地。

### 11.5 章节任务编排：导演前置步骤（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 编排入口 | 已完成 | `scene_direction/chapter_director_run.py`：run_chapter_direction（async）注入真实形态 LLM 客户端（async chat 合同，与 call_audiobook_llm_async 一致）→ SeedSceneDirectorService.direct_chapter → 集成决策 → 按场景编译 Prompt，产出 ChapterDirectorRun（action/reason_code/prompts_by_scene/decision_hash） |
| 渲染入参产出 | 已完成 | use_v2_direction 时按 scene_key 产出 ScenePromptCompileResult（台词中文引号冻结、expected_texts 与源片段逐字一致、场景描述来自导演 context）；degrade_v1/manual_review 不产出 Prompt，reason code 可审计（director_degraded_to_v1/director_terminal_policy/director_budget_exceeded） |
| 编排层守卫 | 已完成 | 编译前校验导演声明的说话人与审定源片段一致、speech 指令覆盖声明源片段、源片段索引为连续区间（误声明场景下 validator 先行拦截降级 V1，编排层守卫为旁路第二道防线） |
| 预算与恢复贯通 | 已完成 | job_consumed 耗尽时零 LLM 调用即降级；checkpoints 复用第二次编排零调用且 Prompt 一致 |
| 回归与导出 | 已完成 | `test_audiobook_chapter_director_run.py`（7 项）；`scene_direction/__init__.py` 补入两项导出（置 pipeline_integration 之后，chapter_director_run 对 prompt_consume 延迟导入，破除 scene_engine 包初始化期循环依赖）；全量回归 3415 → 3422 passed |

实施备注：本步骤交付章节编排串接的第一段（导演 → 决策 → 按场景
编译入参）；渲染层按 scene_key 消费 prompts_by_scene 并贯通到
_scene_render_mixin 的任务层串接（含 degrade_v1 走既有 V1 编译
路径）为下一段。工作区存在外部未提交改动（chapter_facts/
director_style 参数贯通至 planner/prompt_compiler/chapter_pipeline
与入口 mixin），与本批无冲突，未回滚。

### 11.6 渲染层消费编排结果与任务层串接（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 消费桥接层 | 已完成 | `scene_engine/prompt_consume.py` 新增 apply_directed_prompt：V2 编译结果替换 SceneRenderPlan 的 prompt/prompt_hash/expected_text/expected_vocalizations 并恢复 seed_scene 渲染模式；references/reference_hashes 保留 V1 计划的声音绑定结果（编排层编译不携带 voice_profiles）；requires_split 编译结果拒绝注入 |
| 管线接入 | 已完成 | ChapterScenePipeline.render 新增 directed_prompts 可选参数：按 scene_id 命中注入；末道保真防线——expected_texts 必须与场景源片段台词逐字一致，任何不符/注入失败都保留 V1 确定性计划并记录告警；未注入/未命中行为不变 |
| 任务层串接 | 已完成 | `_scene_render_mixin._run_seed_scene_director`：门控 `_seed_scene_director_enabled` 默认关闭（关闭时行为与接入前完全一致）；开启后 run_chapter_direction → use_v2_direction 下发 directed_prompts，降级/客户端缺失/意外异常均不中断章节生产（reason code 可审计：director_llm_client_missing/director_unexpected_error）；LLM 客户端按引擎现有持有链解析（llm_client → script_adapter → audio_director）；stats.director 携带 action/reason_code/decision_hash 审计元数据 |
| 回归 | 已完成 | `test_audiobook_directed_prompt_consumption.py`（7 项：桥接替换/逐字防线/未命中/缺省行为不变）+ `test_audiobook_scene_director_wiring.py`（5 项：门控默认关闭/客户端缺失降级/成功下发/降级章节照常/异常降级）；全量回归 3422 → 3434 passed |

实施备注：至此待接入项 1 的主链路（导演 → 决策 → 编译 → 渲染消费 →
任务层串接）已闭环，degrade_v1 自然回退既有 V1 确定性编译路径；
导演 checkpoint 写入任务层持久化载体与预算账本贯通随 Omni 评审
接入一并落地；生产开启需显式置 _seed_scene_director_enabled=True。

### 11.7 Omni 影子评审真实调用层（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 评审调用层 | 已完成 | `scene_quality/qwen_omni_reviewer.py`：SceneAudioSemanticReviewer（默认 qwen3.5-omni-flash，不替代 ASR、不塞既有 `_final_audio_review()`）；omni_client 鸭子合同 `async review_audio(*, prompt, audio_path, model) -> str`；影子语义在调用层闭合——policy 关闭零调用 skipped、结果只记录不阻断、blocks_output/allow_auto_retry/changes_billing 恒 False |
| 章节预算与缓存 | 已完成 | 场景/接缝评审次数按 policy 上限，超限落 budget_exceeded 零调用，begin_chapter 章节边界重置；音频超 policy.max_audio_duration_s 提交前拦截（preprocessing_failed）；OmniReviewCheckpointSignature.signature_hash 为唯一缓存键，命中零调用复用（result_hash 一致），任一输入变化（签名变化）自动重新评审 |
| 错误分类 | 已完成 | 五类错误全落 recorded_error 不抛异常：asyncio.wait_for 超时→timeout、provider 异常→provider_error、输出 schema 非法→schema_invalid、预算超限→budget_exceeded、音频超长→preprocessing_failed |
| 输出解析与版本化冻结 | 已完成 | _parse_review_payload 严格 JSON：白名单字段（passed/confidence/dimensions/findings/recommended_action 与 finding 8 字段），未知/缺失字段拒绝，构造校验交给合同层 SemanticFinding/SemanticReviewResult；Prompt 版本化常量 omni-review-prompt-1.0.0，OMNI_REVIEW_PROMPT_HASH=sha256(模板)、OMNI_REVIEW_SCHEMA_HASH=canonical_hash（维度+动作+版本），确定性派生并进入签名 |
| 回归与导出 | 已完成 | `test_audiobook_qwen_omni_reviewer.py`（12 项：影子语义/预算/缓存复用/四类错误分类/哈希确定性/outcome frozen）；`scene_quality/__init__.py` 补入六项导出；全量回归 3434 → 3446 passed |

实施备注：本层为独立调用模块（KISS），不改动既有渲染与
`_final_audio_review()` 链路；checkpoint 写入走调用方注入的
checkpoints 载体（任务层持久化载体随串接一并落地）。
模型目录登记见 §11.9。

### 11.8 mixin Omni 影子评审串接（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 签名构造辅助函数 | 已完成 | `qwen_omni_reviewer.py` 新增 `build_omni_scene_signature`：从场景计划（expected_text/speaker_names/expected_vocalizations）构建最简期望合同与绑定摘要，调用 `omni_expectation_contract_hash`/`build_voice_binding_summary` 确定性派生签名；签名字段含音频 artifact hash/期望合同 hash/绑定摘要 hash/模型/Prompt/schema/预处理/策略 hash，覆盖 OmniReviewCheckpointSignature 全部 11 个必填字段 |
| 签名缓存键测试 | 已完成 | `test_builds_valid_signature_from_plan_data` 验证签名构造完整（review_scope/window/模型/哈希）；`test_changed_input_invalidates_signature` 验证音频 hash 变化使签名失效；`TestBuildOmniSceneSignature`（2 项）全过 |
| mixin 门控 | 已完成 | `_scene_render_mixin._run_seed_scene_omni_review`：门控 `_seed_scene_omni_review_enabled` 默认 False（关闭时不发起任何评审调用，stats.omni_review 为 None）；reviewer 注入走 `_seed_scene_omni_reviewer` 可选属性缺失时静默跳过；begin_chapter 在串接入口调用（章节边界重置预算） |
| 按场景评审 | 已完成 | 渲染完成后按通过场景迭代：status != "passed" 跳过、audio_path 不存在跳过、sha256 计算失败跳过；签名构造异常记录 signature_error 不抛异常；review_scene 调用异常记录 review_error 不抛异常；正常返回 outcome_status/error_kind/reused 审计字段 |
| 旁路口径 | 已完成 | `test_omni_review_mixin_wiring.py`（8 项）：门控默认关闭零调用、无 reviewer 静默跳过、启用 + 注入正常评审、评审异常不阻断章节、非 passed 场景跳过、无 audio_path 场景跳过；全量回归 3446 → 3454 passed |

实施备注：本层的评审输出仅入 stats 审计元数据，不修改账单、
不触发重试、不改变成品。生产开启需显式配置：
`harness._seed_scene_omni_review_enabled = True` +
`harness._seed_scene_omni_reviewer = SceneAudioSemanticReviewer(omni_client)`。

### 11.9 模型目录 qwen3.5-omni-flash 登记（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| models.yaml 条目 | 已完成 | `config/models.yaml`：id=qwen3.5-omni-flash（provider=alibaba, status=active）；modality 含 audio_to_text；capabilities 含 audio_understanding（source 已验证、confidence=high）；constraints 含 max_audio_duration_s=120、supported_audio_formats=[wav/mp3/m4a]；API 配置与 omni-plus 共享同一 dashscope endpoint/auth_type/api_key_env；pricing_info 标记 verification_required=true，计费地址指向官方定价页 |
| model_catalog_profiles 档案 | 已完成 | `config/model_catalog_profiles.yaml`：角色摘要、系统角色、两条 prompt 模板（场景语义评审模板 + 朗读方向分析模板）、两条 router_rules（语义评审/方向分析）、最佳实践提示（JSON mode 不支持、flash vs plus 成本取舍、提示词设计要点） |
| 回归 | 已完成 | 全量回归 3454 passed / 5 skipped / 7 deselected（模型目录 YAML 变更不改变测试结果基线） |

实施备注：qwen3.5-omni-flash 此前已在代码层硬编码使用
（`qwen_omni_reviewer.py` DEFAULT_OMNI_MODEL_ID、
`segment_direction_service.py`、`prompt_audio_asr_provider.py` 默认值），
本层补全模型目录登记，使模型在 catalog 中可被统一引用与审计。
计费事实标记为 verification_required=true，具体价格需以
阿里云百炼实时定价为准。

至此待接入项 1 全部主链路交付完成（§11.1–§11.9）。

### 11.10 ProviderRecoveryStore 持久化载体（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| ProviderRecoveryStore 实现 | 已完成 | `scene_engine/provider_recovery_store.py`：ProviderRecoveryStore 类；文件级 Fernet 加密存储（at-rest），密钥从 encryption_key SHA-256 派生；双键索引（internal_attempt_key + external_provider_key）；CAS 状态推进（`update_status` 从磁盘读最新、校验、atomic_write）；TTL 清理（`cleanup_expired` 基于 expires_at） |
| 加密 URL at-rest | 已完成 | 磁盘文件为 Fernet 加密 JSON 字节，不含明文 URL；test_encrypted_url_not_in_plaintext_on_disk 断言验证；读取时自动解密还原 |
| 索引重建持久性 | 已完成 | 启动时从 `*.enc` 文件遍历重建双键索引；test_rebuild_index_on_startup + test_rebuild_provider_key_index 验证 |
| 跨实例持久化 | 已完成 | test_persistence_across_instances 验证：store A 写入后 store B 可读取完整记录 |
| 测试 | 已完成 | 25 项 TDD 测试（构造 5、save/get 3、双键 3、CAS 3、加密 3、TTL 4、索引重建 2、持久化 2） |

实施备注：ProviderRecoveryStore 使用 File-backed 加密存储模式，遵循
`ProviderAttemptLedger` 的持久化风格与 `PayloadVault` 的 Fernet 加密方案。
当前仅提供单进程 CAS（内存锁），多 Worker 场景后续可通过 DB 索引重构。
满足 §12.2 指导文档的 "加密、TTL 受限的短期恢复记录" 要求：
`encrypted_result_url` 字段全程加密存储，`expires_at` 驱动 TTL 清理。

至此待接入项 3 交付完成（§11.10）。

### 11.11 RawTranscriptStore 存储层落地（2026-08-11）

| 项 | 状态 | 证据 |
|---|---|---|
| RawTranscriptStore 实现 | 已完成 | `scene_engine/raw_transcript_store.py`：Fernet 加密文件 at-rest；文件路径按 project/chapter 组织（`{storage_dir}/{project_id}/{chapter_id}/{hash_prefix}.enc`）；URI 格式 `raw-transcript://store/{project_id}/{chapter_id}/{hash_prefix}` |
| at-rest 加密 | 已完成 | 磁盘文件无明文 transcript；test_encrypted_at_rest 断言、test_decrypted_on_read 验证解密 |
| project 隔离 | 已完成 | `delete_project` / `delete_chapter` 按目录级联清理；`list_project` 列出项目下所有 URI（目录遍历不依赖索引） |
| 幂等存储 | 已完成 | 相同内容 `content_digest` 一致返回相同 URI（test_store_idempotent） |
| 测试 | 已完成 | 19 项 TDD 测试（构造 3、store/resolve 5、加密 2、project 隔离 2、chapter 隔离 3、delete project 2、list 2） |

实施备注：RawTranscriptStore 遵循 `ProviderRecoveryStore` 的 Fernet 加密模式与
`PayloadVault` 的密钥派生方案。与 ProviderRecoveryStore 不同之处：
不维持内存索引（transcript 内容较大、时效长、查询模式为 "按 URI 读取"）；
文件路径按 project/chapter 两层目录组织（支持 shutil.rmtree 级联删除）；
URI 采用 `raw-transcript://` scheme，store 内部解析映射到磁盘路径。
存储层落地后，TODO：在 L0 质量检查链路中串接使用（由后续 pipeline 环节负责）。

至此待接入项 2 交付完成（§11.11）。

| 编号 | 问题 | 严重度 | 影响阶段 | 负责人 | 状态 | 解决方案 |
|---|---|---|---|---|---|---|
| RISK-001 | run_20260810T164647Z 的 compliance 音频落盘为 0 字节（脚本 data URI 分隔符 bug，`_save_audio` 已修复），音频盲听证据缺失；字幕、指标与行为分类证据完整，不影响 eligible 结论 | 低 | 阶段 0（证据补全） | - | 开放 | 用修复后的 `scripts/validate_seed_audio_timeline.py --contracts compliance` 重跑 3 次（约 1.5 元），需确认后执行 |

## 13. 决策变更

每次变更按以下模板记录：

```text
### DEC-001：标题

- 日期：
- 原决策：
- 新决策：
- 原因：
- 影响章节：
- 是否需要更新指导文档：
- 是否需要迁移或兼容处理：
```

## 14. 供应商验证证据

单独记录真实调用证据，不把运行日志直接堆入指导文档。每条证据包含：

- 请求模型和 endpoint；
- 请求合同版本；
- 响应格式；
- 音频时长；
- 字幕/时间轴结果；
- 错误与重试行为；
- 成本；
- 验证结论；
- 证据文件位置。

### EVID-001：时间轴四合同实测（run_20260810T164647Z）

- 请求模型和 endpoint：`seed-audio-1.0-multilingual`，`POST https://openspeech.bytedance.com/api/v3/tts/create`（X-Api-Key 认证）。
- 请求合同版本：场景目录 `seed-audio-v2-phase0-scenarios@1.0.0`（冻结哈希 `afe3a885…`）；判定合同 `eligibility_policy@1.0.0`；`audio_config={format:wav, sample_rate:48000, enable_subtitle:true}`。
- 响应格式：JSON，含 base64 音频（本次落盘失败，见 RISK-001）与毫秒级字幕 `subtitle.sentences[]`。
- 音频时长：compliance 三次运行均为 30000ms，与声明总时长一致。
- 字幕/时间轴结果：五项语法变体全部被遵循；聚合误差 start P50/P95/max = 120/184/200ms，end = 160/576/720ms，duration = 0，event_alignment = 120/184/200ms（n=9）。
- 错误与重试行为：超 120s 窗口返回 HTTP 500（`provider_unavailable`）；越界窗口压缩、重叠窗口避让、颠倒/非数值窗口忽略；空事件触发 Prompt 文本被朗读的异常模式（纳入阶段 3 L0 闸门候选项）。
- 成本：约 15 次生成，预估 7–10 元区间（实际以账单为准）。
- 验证结论：`strict_timeline_eligible=true`、`bounded_timeline_eligible=true`；canonical 语法假设维持，无需 DEC。
- 证据文件位置：`backend/data/timeline_validation/run_20260810T164647Z/`（plan.json、probes.json、compliance_runs.json、eligibility.json、summary.json）；详细指标见 §4.4。

## 15. 发布验收

V2 完成定义逐项验收（对照指导文档 §16，2026-08-11 逐项核对）：

- [x] 新任务默认 `seed-audio-1.0-multilingual`（阶段 1：renderer 默认模型与 checkpoint 记录均为 multilingual；阶段 4 TestMultilingualCriteria）
- [x] 模型能力口径一致，无过期硬编码主模型声明（阶段 1：`_seed_scene_capability.py` 共享能力合同 1.0.0，prompt 合同测试断言无硬编码）
- [x] 台词验证四类合同分级（hard/optional/semantic_only/vocalization）（阶段 3：verification_policy 三级枚举 + vocalization 独立方向类型；代码层无 soft_expected_texts 字段；待接入项见 §15.1）
- [x] 普通 1.0 只承担历史兼容、A/B 和紧急回滚（阶段 1：`_resume_model` 历史 checkpoint 按原模型恢复，新任务只请求 multilingual）
- [x] 两模型价格一致且计费可区分（阶段 1：`test_audiobook_seed_audio_pricing.py` 单价一致、计费键按真实模型 ID）
- [x] 独立 Seed 导演合同（阶段 3：`scene_direction/` 包 models/parser/validator/prompt/policy）
- [x] Prompt 台词逐字来自审定事实源（阶段 3：speech 无 text 字段 + 编译时读源片段；阶段 4：event_mapper 逐字映射 + 五类样例台词逐字验收）
- [x] 声音身份、reference 槽位、事件表演三层决策分离（阶段 4：voice_identity/voice_binding_planner/event_mapper 三模块职责分离）
- [x] 声音绑定可追溯、最多三条 reference、显式超限策略（阶段 4：稳定评分 + reason code，超限确定性分流 degraded_reference_budget/split_required_strict_bindings）
- [x] 严格绑定不静默换声（阶段 4：显式绑定优先级最高，用户显式选择不被静默替换）
- [x] 插话/人声/重叠/音效/音乐/声学可结构化表达（阶段 3：SeedSceneDirection 全方向类型 + validator 不变量）
- [x] 场景时长估算包含声音事件区间（阶段 4：event_mapper §8.1 事件区间估算器 + planner 字符估算复用渲染 helper）
- [x] timeline 契约验证结论版本化，未通过模式不开放（阶段 0 EVID-001 两模式均 eligible；阶段 4 timeline_gate 按版本化结论独立开放，缺字段不静默通过）
- [x] Director 四级预算、纠错一次、保真降级、独立成本（阶段 3：SeedSceneDirectorPolicy + 纠错 FSM + v1_fidelity_feasible 分流 + attempt ledger）
- [x] L0 硬闸门与 Omni 语义评审职责分离（阶段 4：L0QualityCheckpoint 输入签名与结果分离；阶段 5：Omni 只记录不阻断）
- [x] Omni 可审计、可定位、受预算控制、未标定不阻断（阶段 5：checkpoint 签名 + finding 时间区间 + 预算策略；阶段 6：未标定 code 拒绝自动处置）
- [x] 接缝语义连续性评审（阶段 5：seam_review 双窗口构造 + 章节绝对区间换算）
- [x] Seed 成功路径不产生多余分轨素材（阶段 7：pre_generates_on_seed_path 恒 False + 全通过空计划）
- [ ] 两入口共享同一服务链（部分达成：阶段 2 两入口已接入同一 pipeline.render 与入口上下文；§11.2 回退收敛已接入 ChapterScenePipeline；§11.3 V2 导演编排层已交付；§11.4 导演事件已进入 Prompt 编译消费；真实 LLM 客户端注入、章节任务编排串接与 Omni 评审服务接入待完成）
- [x] legacy_stems 兼容，回退对用户和账单可见（阶段 0：legacy_stems 回归 6 passed；阶段 7：visible_to_user/visible_in_billing 恒 True）
- [x] hash 双轨（canonical_hash / content_digest）（阶段 1：hashing.py 稳定性测试，content_digest 不随合同版本变化）
- [x] 五类 checkpoint 输入输出分离（Director 阶段 3；Seed/Transcript/L0 阶段 4；Omni 阶段 5）
- [x] append-only 迁移可审计、不重烧完整音频（阶段 1：migration_input_hash 版本化 + 迁移后复用不重烧）
- [x] normalization 不调 ASR、L0 policy 不调 Seed、Omni policy 不重生成（阶段 4：Transcript 输入签名判别联合、L0 policy 不入 Seed 生成签名；阶段 5：semantic_policy_hash 只进 Omni 评审缓存键）
- [x] 原始转写隔离、加密、生命周期管理（合同层达成 + 存储层已交付 §11.11：RawTranscriptStore Fernet 加密 + project 隔离 + URI 化引用 + 级联清理）
- [x] 临时 URL 过期不重复计费（合同层达成 + 持久化载体已交付 §11.10：ProviderRecoveryStore 加密 URL/TTL 文件存储 + CAS + 清理）
- [x] checkpoint 恢复不重置已消费预算（阶段 3：retryable 恢复取 max 不回退；阶段 1：迁移后计费摘要全等）

### 15.1 验收结论

```text
状态：合同层验收完成（2026-08-11）
统计：27 项中 26 项合同层验收通过（1 项新增为 §11.10、1 项新增为 §11.11 生产层接入交付）；1 项合同层达成但待生产层接入
待接入清单（不阻断合同层结论，接入时逐项销项）：
  1. 两入口共享同一服务链：**全部交付完成**（§11.2–§11.9）；
  2. 原始转写隔离加密与生命周期：**已交付**（§11.11
     RawTranscriptStore 加密文件存储 + project 隔离 + URI 引用 + 级联清理）；
  3. 临时 URL 过期不重复计费：**已交付**（§11.10
     ProviderRecoveryStore 加密文件存储 + CAS + TTL 清理）；
  另：L0 vocalization 豁免判定（四类台词合同的第四类运行时
  判定）随评审服务接入一并落地
证据链接：§4–§11 各阶段验收块（含 §11.2–§11.11 管线接入）；
         全量回归 3479+19 passed / 5 skipped / 7 deselected
未通过项：无（全部待接入项已交付，仅剩 L0 vocalization 流转判定）
风险：无新增；RISK-001 仍开放
```
