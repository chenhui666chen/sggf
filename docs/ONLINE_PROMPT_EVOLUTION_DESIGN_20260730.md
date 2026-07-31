# 提示词在线进化服务设计 v2（Champion/Challenger 双路体系 + 进化自动启停）

> 状态：十步实施完成（2026-07-30 设计定稿 v2；§14 步骤 1~10 全部交付），当前处于外部评审驱动的修复迭代期（修复批次逐项登记于 §13）
> v2 修订：吸收工程评审 12 项风险修正——模型解析事实纠错、四层校准门槛、持久任务与数据库账本、实验契约冻结、隐私生命周期、十步实施顺序（详见附录 B）
> 范围：织文无迹（/ai-trace）在线改写链路、prompt_evolution 离线进化体系
> 前置已完成项：禁用词表扩充（novel_rules.py，65 词）、变体生成历史去重注入（meta_optimizer._session_strategy_history）

## 1. 背景与目标

当前提示词进化是纯离线体系：`run_evolution` 在固定测试样本池上迭代，胜出提示词落盘 `best_prompts.json`，在线服务按题材取用。存在四个结构性缺口：

1. **进化信号与真实分布脱节**：离线样本池有过拟合风险（AI 率刷到 0 更可能是刷透了样本池，而非真实分布上同样好），真实用户输入从未回流；
2. **在线服务无质量增强手段**：用户每次只拿到冠军提示词的单路结果，没有择优机制；
3. **变体探索曾无记忆**（已修复：历史去重注入），且探索产出与在线服务之间没有通道；
4. **进化无启停管理**：收敛后继续烧钱探索是负期望，退化后（检测器升级、模型换代）无自动唤醒。

目标：建立"离线进化产出挑战者 → 在线小流量成对实验 → 择优返回提升单次质量 → 统计回流驱动晋升与再进化"的闭环，同时把实验风险与用户体验严格隔离。

## 2. 现状基础与可复用组件

| 现有组件 | 位置 | 在本设计中的角色 |
|---|---|---|
| 离线进化引擎 | `prompt_evolution/engine.py` | 挑战者候选的唯一生产者 |
| 三维评审 + 准入门槛 | `evaluator.py` + `meta_optimizer._is_eligible_success_sample`（保真≥80/事实≥90/完整≥75/风险=low） | 离线准入门槛直接复用 |
| 提示词安全校验 | `meta_optimizer._validate_prompt_safety` | 离线准入第一道过滤 |
| 禁用词残留检查 | `evaluator.py`（引用 `ALL_FORBIDDEN_WORDS`） | 同步硬门槛组成部分 |
| 失败变体过滤 | `engine._failed_variants`（进程内 dict） | 需落盘化后承担准入职责（见 §13 技术债） |
| **在线模型解析** | `ai_trace.py`：`admin_selected_model` > `get_best_model_for_prompt_version(genre, version_id)` > `get_active_model_id(genre)` 兜底 | **实验两路共享的模型解析入口（解析一次、冻结使用，见 §4.1）** |
| 最优提示词存储 | `best_prompts.json` / `EvolutionStorage` | 冠军提示词内容载体；冠军指针迁移至 assignment 表（§8.3） |
| Celery + Redis | `app/celery_app.py`（含 crontab beat），audiobook/feedback/dreamweaver 在用 | 实验任务的**执行器**（非状态权威，见 §5.2） |
| 状态接口 | `/api/v1/prompt-evolution/status` | 扩展实验观测视图 |

> ⚠️ v1 事实纠错：v1 曾假定在线链路统一使用 `get_active_model_id(genre)`，与 `ai_trace.py` 实际的 prompt-model 联合选择逻辑不符。若实施时强制改用题材冠军模型，会绕过已积累的提示词/模型联合表现并造成线上回退。以本节表格为准。

## 3. 核心架构：两阶段挑战者体系

### 3.1 生命周期状态机

```
离线进化 ──→ Candidate（变体 + 策略描述 + 来源批次）
                │ 离线完整准入（§3.2 七条门槛）
                ▼
        Challenger 池（serving_mode = shadow）
                │ 后台持久任务成对实验（不占请求路径，§5.2）
                ▼ 四层校准门槛全过（§3.4）
        eligible ──（人工批准）──→ returnable
                │ best-of-2 择优返回参与服务
                ▼ 晋升硬闸门 + 推荐指标（§8）+ 人工确认
        champion（assignment 表原子切换，旧版本保留可秒级回滚）

任意状态可流转至：
  suspended  近期表现差，暂停流量，保留数据
  eliminated 样本量充分后确认退化，永久淘汰
  cooldown   基础设施故障（供应商超时/检测服务异常），不计质量败场，冷却后恢复
```

挑战者池条目 schema（带版本与内容哈希）：

```json
{
  "challenger_id": "chg_玄幻_20260730_a1b2",
  "genre": "玄幻",
  "prompt_text": "...",
  "prompt_hash": "sha256:...",
  "strategy_desc": "降低连续同构句比例，保留题材语域",
  "strategy_family": "sentence_structure",
  "source_batch": "evolution_20260730_01",
  "offline_gate_passed": true,
  "offline_scores": {"fidelity": 88, "fact": 96, "completeness": 82, "risk": "low"},
  "serving_mode": "shadow",
  "created_at": "...", "state_changed_at": "..."
}
```

`strategy_family` 为策略族标签（句式类/词汇类/实体压缩类/节奏类等），是四层校准门槛（§3.4）与分层统计的分组键。

### 3.2 离线准入门槛（进入在线池的先决条件，七条全过）

1. 语义保真 ≥ 80；2. 事实一致 ≥ 90；3. 信息完整 ≥ 75；4. 过度改写风险 = low；
5. `_validate_prompt_safety` 通过；6. 禁用词残留检查通过；7. 不在失败变体记录中（落盘版）。

> ✅ 已实施（2026-07-30，§14 第 4 步）：纯逻辑 `backend/app/services/prompt_evolution/challenger_pool.py`（测试 `test_challenger_pool.py`，22 用例），持久化 `challenger_repository.py`（测试 `test_challenger_repository.py`，10 用例）。实施决策：
> - 七项门槛原散落 `meta_optimizer` / `evaluator` / `ai_trace_competition` 三处，收敛为单一聚合函数 `evaluate_offline_gate`，按上表顺序短路返回第一个失败项（`OfflineGateResult`）；门槛 ⑤ 复用 `MetaOptimizer._validate_prompt_safety` 单一真源，不重复黑名单；
> - `compute_prompt_hash` / `make_challenger_id` 用确定性 sha256（`sha256:` 前缀，前 16 位），是 `prompt_challengers.challenger_id` 唯一约束与幂等入库的基础；`classify_strategy_family` 从仅有的 `strategy_desc` 关键词派生分层统计分组键；
> - 门槛 ⑦ 的 `_failed_variants`（原 `engine.py` 内存 `{hash: count}`）由 `FailedVariantStore` 转 JSON 落盘（阈值 3 次，与既有行为一致），`get_blocked_hashes()` 喂给 `evaluate_offline_gate`；`ChallengerRepository.upsert_challenger` 幂等 on challenger_id（重复入库返回既有行）；
> - **本步只交付纯逻辑 + 持久化，不接入 live engine loop**（该耦合属 §14 第 6 步 shadow 上线）。

**异步评审的职责因此重新定义**：不再是"第一次判断挑战者是否安全"，而是①评估真实用户分布上的表现；②发现离线样本未覆盖的退化；③修正同步轻量判定的误判；④决定晋升或淘汰。

### 3.3 决策解耦原则（核心裁决）

| 决策 | 回答的问题 | 证据标准 |
|---|---|---|
| **单次返回择优** | 这条请求里哪个文本更好 | 离线准入 + 同步硬门槛 + 排序分显著性 margin + **已按四层门槛校准的判定器** |
| **提示词晋升** | 这个提示词长期更好 | 累计 confirmed 统计 + 置信下界 + 回归检查 + 人工确认 |

两者解耦：挑战者结果可以在晋升之前就返回给用户（实现双路的质量增强目的），前提是判定器校准达标。**明确的风险边界**：择优返回不宣称"用户永远拿到更优"，同步判定无法识别微妙语义漂移；残余风险 = 合格提示词在特定输入上产生硬门槛不可见的退化，通过 margin、熔断与人在环场景分层（§12）控制。

### 3.4 判定器四层校准门槛（v2 修正：替代"整体达标一次性解锁"）

判定器误差随题材、原文长度、改写强度、策略族、实体密度、文体比例漂移——在玄幻+句式去重上校准成功不代表在言情+实体压缩上仍可靠。returnable 解锁须逐层满足最小样本且作废率达标：

| 层级 | 回答的问题 | 最小样本（配置项） | 作废率要求 |
|---|---|---|---|
| 1. 全局判定器基础校准 | 判定器逻辑整体可用吗 | ≥ 200（可用离线回放样本预热，§14 步骤 5） | ≤ 5% |
| 2. 每题材 | 该题材分布上可靠吗 | ≥ 50 / 题材 | ≤ 5% |
| 3. 每策略族 | 该类改写方向上可靠吗 | ≥ 30 / 策略族 | ≤ 5% |
| 4. 每个新挑战者 | 其判定误差分布与校准时一致吗 | ≥ 20~30 / 挑战者 | 无显著漂移 |

第 4 层是**分布一致性检验而非晋升检验**，故样本量（20~30）比晋升要求（≥100）低一个量级——新挑战者仍只需小样本过检即可参与 returnable，避免逐挑战者攒晋升级样本的初衷得以保留。**新挑战者默认只能进入 shadow，不自动继承其他挑战者的 returnable 权限。** 第一版用明确最小样本数，不引入贝叶斯层次模型。

> ✅ 已实施（2026-07-30，§14 第 7 步）：`backend/app/services/prompt_evolution/layered_calibration.py`（测试 `test_layered_calibration.py`，18 用例）。实施决策：
> - **纯逻辑分层聚合**：`build_layered_calibration(samples, thresholds)` 按 genre / strategy_family / challenger_id 三键分组，逐组复用第 1 步的 `compute_replay_consistency`（同一作废率口径 `invalidated / (confirmed + invalidated)`，`infrastructure_failure` 不计入有效样本），产出 `LayeredCalibrationReport`（layer1 全局单组 + layer2/3/4 分组字典 + challenger_context）；
> - **四层门槛**（`CalibrationThresholds.from_env`）：`CALIBRATION_MIN_SAMPLES_GLOBAL/_GENRE/_FAMILY/_CHALLENGER`（默认 200/50/30/20）+ `EXPERIMENT_INVALIDATED_RATE_MAX`（默认 0.05）；第 4 层「无显著漂移」第一版落地为**同一作废率上限**施于挑战者自身样本（不引入贝叶斯层次模型，与本节定调一致）；
> - **解锁判定**：`challenger_unlocked` 要求全局 + 其题材 + 其策略族 + 其自身分布**四层同时达标**；`eligible_challenger_ids` 返回全过者；
> - **状态推进**：`promote_calibrated_challengers` 取本 `evaluation_policy_version` 窗口的已结算样本（`ExperimentRepository.list_settlement_samples` 联 `prompt_challengers` 取 strategy_family，不跨版本聚合，§8.1 硬闸门 #4）→ 四层全过且**仍处 shadow** 的挑战者经 `ChallengerRepository.update_serving_mode`（`assert_transition` 校验）推进到 **eligible（待人工批准，不参与返回）**；已在其他状态的挑战者幂等跳过；
> - **调度**：`experiment_tasks.run_calibration_task`（Celery 薄壳，纯 DB 计算不调供应商）+ beat 每 30 分钟轮询；`EXPERIMENT_ENABLED` 未开启时空转；
> - **边界**：本步只到 `shadow → eligible`（校准的机械产出，用户可见影响为无）；`eligible → returnable` 的人工开闸与 best-of-2 择优返回属 §14 第 8 步。

## 4. 实验契约冻结（v2 新增章节，实施第一步）

> ✅ 已实施（2026-07-30）：`backend/app/services/prompt_evolution/experiment_contract.py`，测试 `backend/tests/test_experiment_contract.py`（18 用例）。实施决策：
> - `EXPERIMENT_EVALUATION_POLICY_VERSION`（experiment-policy-v1）与 ai_trace_competition 的 `EVALUATION_POLICY_VERSION` 独立，两套统计窗口分开演进；
> - 状态机补充裁决：champion 被替换后只能转 suspended（保留可回滚）或 eliminated；suspended 恢复只能回 shadow（重新校准）；cooldown 恢复到冷却前活跃状态但不含 champion；eliminated 为终态；
> - 挑战者索引与分桶做 HMAC 域分离（消息加 `:challenger` 后缀）；
> - `bucket_hits_epsilon(bucket, ε)` 提供 ε 流量判定，前 ε×10000 个桶为实验组。

### 4.1 模型冻结

冠军路与挑战者路**禁止各自执行模型选择**。流程：按现有规则（`admin_selected` > `get_best_model_for_prompt_version` > `get_active_model_id` 兜底）为冠军请求解析一次最终模型，然后把同一结果显式冻结给两路，实验记录写入：

```
resolved_model_id          两路共用的最终模型
model_selection_source     admin_selected | prompt_combination | genre_model_summary
model_config_version       模型目录版本
prompt_version_id          冠军提示词版本
temperature / max_tokens   两路一致的采样参数
provider_parameters_hash   供应商参数指纹
```

`model_selection_source` 同时作为分层统计维度。第一版固定模型只比提示词；模型竞争继续走现有体系，不与提示词实验混杂。同一次成对实验必须同一输入文本；供应商支持时记录随机种子。

### 4.2 确定性分桶（v2 修正：禁用 Python hash()）

Python `hash()` 受进程随机盐影响，跨 worker/重启不可复现。规范为：

```
bucket = int.from_bytes(
    HMAC_SHA256(server_secret, f"{anonymous_subject_id}:{genre}:{experiment_id}")[:4],
    "big"
) % 10000
```

挑战者选择同样由该 HMAC 确定化派生（分桶 + 挑战者索引一次算出），同一用户在实验周期内稳定命中同一挑战者，不得每请求随机漂移。

### 4.3 版本体系

以下版本随实验记录固化（§7.2），任一实质变化即开启**新的统计窗口**，旧窗口数据按 `evaluation_policy_version` 分组键自然隔离，不与新窗口聚合：

`light_judge_version`、`evaluation_policy_version`、`async_review_prompt_version`、`async_review_model_id`、`detector_provider`、`detector_version`、`champion_prompt_hash`、`challenger_prompt_hash`、`model_catalog_version`。

## 5. 在线双路服务设计

### 5.1 分流

- 确定性 HMAC 分桶（§4.2）；
- **ε 按风险类型分层设定**：
  - shadow 阶段：对用户零影响，约束是**预算**。ε 由每日实验预算反推，小流量期可 30%~50%；
  - returnable 阶段：约束是**风险**。阶梯爬坡 5% → 10% → 20%，连续稳定后封顶 20%；
  - ε 按"题材 + 挑战者"两级维护，防止差挑战者被同题材好挑战者的总体数据掩盖；
- 预算耗尽自动 ε=0，全部走冠军。

> ✅ 已实施（2026-07-30，§14 第 6 步 · 子块 B-1 分流编排）：`backend/app/services/prompt_evolution/shadow_dispatch.py`（测试 `test_shadow_dispatch.py`，13 用例）+ `ChallengerRepository.list_serving`（按 challenger_id 排序保证确定性索引，2 用例）+ `ai_trace.py` reduce 成功返回前旁路挂载。实施决策：
> - `maybe_create_shadow_experiment` 决策链（便宜检查在前）：`EXPERIMENT_ENABLED` 总开关（默认 false 完全惰性）→ 分桶密钥/载荷密钥缺失失败关闭 → opt-in 授权（默认拒绝）→ HMAC 分桶 ε（campaign id 用 `EXPERIMENT_EVALUATION_POLICY_VERSION`，统计窗口内选择恒定）→ `list_serving` 池内 `select_challenger_index` 确定性选 → 结算键幂等预查（`already_exists` 不重复扣预算）→ 四维预算 reserve（global=调用+费用 / genre=费用 / challenger=费用 / user=调用频次，任一失败整体 `rollback` 不留半截占用）→ 原文+冠军产出+分数打包 JSON 经 PayloadVault 加密（任务表只带 opaque ref）→ 创建 pending 实验行，同事务 `commit`；
> - **fail-safe 红线**：整体 try/except，任何异常 `rollback` 后返回 `error:<类型名>`，日志只落异常类型不落原文，绝不影响冠军返回；挂载点本身再包一层 try/except 双保险；
> - 配置经 `ShadowDispatchConfig.from_env` 直读 `EXPERIMENT_*` 环境变量（不动全局 settings）；冠军契约在挂载点用 `FrozenModelContract.freeze` 冻结（resolved_model_id/selection_source/prompt_version_id/temperature=0.8）；
> - **不接 Celery、不调外部 API**——pending 行的认领执行属子块 B-2。

### 5.2 shadow 阶段：持久任务成对实验（v2 修正：禁止裸 fire-and-forget）

> ✅ 已实施（2026-07-30，§14 第 6 步 · 子块 A 持久化层）：`backend/app/services/prompt_evolution/experiment_repository.py`（测试 `test_experiment_repository.py`，15 用例）。实施决策：
> - `ExperimentRepository` 把 `prompt_experiments` 表落地为「创建幂等 → 租约认领 → 可重入状态转换 → 结算 / dead」：`create_experiment` 幂等 on 结算键（复评晚到 / 批次重跑返回既有行，并发双插由唯一约束兜底），`claim_next` 按 `status ∈ statuses 且 (lease_until 为空或已过期)` 认领并续租 + 递增 `attempt_count`，**行级锁 `FOR UPDATE SKIP LOCKED` 保证多 worker 并发认领互斥**（sqlite 方言忽略，不影响单测），`advance_status` 仅当处于期望前态才推进（越态为幂等空操作）；
> - **终态保护**：`record_settlement`/`mark_dead` 对已 settled/dead 行幂等空操作，晚到的重复结算不覆盖 outcome、晚到的重试失败不改判已结算实验；
> - **事务边界由调用方掌控，本层只 `flush` 不 `commit`**（Celery 任务体 / 路由决定提交时机），沿用第 4-5 步「纯持久化 + 纯逻辑，不接 live loop」惯例；
> - `mark_dead` 只落结构化 `last_error_code`，**不落原文**（§10 隐私纪律）；时间统一时区感知 UTC 对齐 `DateTime(timezone=True)` 列；
> - **子块 B-1（分流编排：`shadow_dispatch.py` + `ai_trace.py` 挂载）已完成，见 §5.1 标注；子块 B-2（Celery 执行器）已完成**：`shadow_executor.py`（编排核心，测试 `test_shadow_executor.py`，12 用例）+ `experiment_tasks.py`（Celery 薄壳）+ `celery_app.py` beat 每 5 分钟轮询。子块 B-2 实施决策：
> - **认领→执行分离**：`run_shadow_batch` 先 `claim_next`（`FOR UPDATE SKIP LOCKED`）续租并提交，防执行中崩溃丢认领；`execute_experiment` 逐个跑「载荷读取 → 挑战者生成 → AI 检测 → `judge_pair` 同步轻判 → SemanticJudge 复评 → `classify_verdict` 六分类 → `record_settlement` + 四维预算 `settle` + 载荷删除」，同事务提交；
> - **降级语义（§5.5）**：供应商调用抛异常且未达 `max_attempts` 留 pending（租约到期自动重试），达上限转 dead + `release` 预留额；检测/复评"正常返回但不可用"→ `infrastructure_failure` 正常结算（不进胜率分母）；载荷缺失/过期、挑战者行缺失为不可恢复直接 dead；
> - **异步复评不通过归 `invalidated_win`**（判定器误判计入作废率），不与同步质量硬失败混淆；结算预算必须回到 reserve 当天的账本行（按日滚动，跨天不开新行）；结算 user 维需主体，故 dispatch 加密载荷内补 `subject_id`；
> - **外部调用全部依赖注入**（`ShadowExecutionDeps` 的 rewrite/detect/review），核心 sqlite + 假函数测全状态机；真实装配（PromptEvaluator / 腾讯检测 / SemanticJudge，`asyncio.run` 桥接同步 Celery）在薄壳，`EXPERIMENT_ENABLED` 未开启时任务体空转。

用户请求走**完全正常的冠军单路**，冠军返回即请求结束，shadow 不占用户等待路径。但挑战者实验任务**不得使用裸 `asyncio.create_task`**（现有范式如 `prompt_evolution.py` 的后台任务只依附 API 进程：重启即丢、无认领/超时恢复/幂等重试/死信，多 worker 无法协调预算，可能预算已扣而结果未落账）。

**任务载体：数据库任务表 + 租约为状态权威，Celery 为无状态执行器**（认领→执行→写回；第一版可直接用现有 crontab beat 轮询任务表，无需新建队列）。任务表最小字段：

```
experiment_id, request_id, challenger_id,
status, attempt_count, lease_until, payload_expires_at,
last_error_code, created_at, started_at, finished_at
```

生成、检测、轻量判定、完整复评四段各自定义**可重入的状态转换**（幂等：靠唯一约束去重，见 §6.2）。

**一致性要求分级**（不追求全链路恰好一次）：

| 数据 | 丢失/不一致后果 | 要求 |
|---|---|---|
| shadow 样本 | 统计性数据，丢几条无害 | 至少一次执行 + 幂等去重即可 |
| 预算扣减/结算 | 并发超发、账不平 | 必须原子（DB 事务 + 预留成本） |
| provisional→confirmed/invalidated | 重复结算污染胜率 | 必须原子 + 唯一约束 |
| champion 指针 | 线上事故 | 原子指针 + 审计 + 旧版本保留 |

shadow 期间同步判定器照跑但不作用于返回，异步权威评审揭晓真相，产出判定器校准数据（§3.4 四层门槛的样本来源）。

### 5.3 同步判定器 = 硬门槛 + 排序分 + 不对称 margin

> ✅ 已实施（2026-07-30，§14 第 5 步）：纯函数 `backend/app/services/prompt_evolution/light_judge.py`（测试 `test_light_judge.py`，27 用例）。实施决策：
> - `check_hard_fail` 累计命中所有硬失败原因（非短路，便于观测），依次覆盖：空/过短 → 长度收缩 → 数字/时间丢失（`extract_number_tokens`/`find_missing_numbers` 正则抽取比对）→ 显式人名表实体丢失 → 禁用词残留（复用 `challenger_pool.find_forbidden_words`）→ 模板残留/系统提示泄漏（`has_template_residue`/`has_prompt_leak` 新建，原缺失工具）→ 段落结构破坏 → AI 检测未过（检测不可用或分数缺失一律判失败）→ 内容安全未过；
> - 按 v2 修正，**中文专名启发式不判硬失败**，精确实体一致性交由异步 `fact_consistency`；数字/提示泄漏检测为新建（既有代码库无现成工具），长度收缩/段落数复用文本度量思路；
> - `compute_ranking_score` 合成 AI 痕迹改善 + 长度稳定 + 数字保留 + 结构完整 − 禁用词惩罚（`0.4/0.2/0.2/0.2` 权重，禁用词每命中 −10 封顶 −40），**不做 AI 率单指标择优**；`judge_pair` 两路各算硬门槛后按排序分 + 不对称 `margin`（默认 5.0）择优，平局/小胜返回冠军；
> - **全模块纯函数无 IO / 无外部 API**：AI 分、内容安全结论、检测可用性由调用方传入，使判定器可离线回放验证一致率（§7 异步评审 + §3.4 第 1 层预热同此原则）。

**硬失败条件**（任一命中即本路出局）：

1. 输出为空或异常短；2. 长度相对冠军/原文严重收缩；
3. 数字/时间/日期丢失（正则抽取比对）；
4. 显式人物表实体丢失（灵感方舟场景复用连续性资产人名表）；
5. 新增原文不存在的高风险实体/事实；6. 禁用词、模板残留、系统提示泄漏；
7. 段落结构破坏；8. AI 检测未通过；9. 内容安全检测未通过。

> v2 修正：中文专名启发式（"2-4 字、出现≥2 次、非词表词"）误判率高（常用短语误报、单次出现人名漏报、题材术语误报、随词典漂移），**降级为排序信号 + 告警**，不单独判硬失败。精确实体一致性由异步评审 fact_consistency 承担。

**轻量排序分**（两路都过硬门槛后计算）：

```
score = AI痕迹改善 + 可读性改善 + 长度稳定性 + 实体保留率(含启发式专名) + 结构完整度
        − 禁用词惩罚 − 事实漂移风险
```

**禁止 AI 率单指标择优**：AI 率暴跌（如 99→0）本身是过度改写的高危信号，必须与保真类指标合成。

**不对称 margin**：挑战者排序分须**显著**领先（超过配置阈值）才返回挑战者；平局或小胜一律返回冠军。判定噪声集中在中间地带，margin 压缩误判区间。

### 5.4 returnable 阶段与熔断

- 双路并行 → 同步硬门槛 → 两路都通过时按排序分 + margin 择优返回；
- 每次择优记录 `returned_variant + light_judge_result + async_review_result`；
- **运行期熔断**：判定器滚动作废率越限（如 7 日窗口 > 5%）→ 自动降级为恒返回冠军，报警待人工介入。校准是持续监控的，不是一次性的。

> ✅ 已实施（2026-07-30，§14 第 8 步 · 子块 A 择优核心）：`backend/app/services/prompt_evolution/returnable_service.py`（测试 `test_returnable_service.py`，17 用例）。实施决策：
> - `ReturnableConfig.from_env` 读 `EXPERIMENT_ENABLED` / `EXPERIMENT_EPSILON_RETURNABLE`（默认 0.0）/ `EXPERIMENT_MARGIN_THRESHOLD`（默认 5.0）/ `EXPERIMENT_BUCKET_SECRET` / `EXPERIMENT_AI_SCORE_THRESHOLD`（默认 25.0，复用 shadow 执行器同名项）/ `EXPERIMENT_INVALIDATED_RATE_MAX`（默认 0.05）；
> - `choose_returnable_variant`（async）决策链（便宜检查在前，异常一律回退冠军）：总开关 → 分桶密钥 → **opt-in 授权**（returnable 同样拿原文生成挑战者，§10 合规，默认拒绝）→ **运行期熔断** `is_circuit_open`（交付时复用 `list_settlement_samples` 全量累计口径，后经四轮评审修复②改造为 returnable 场景滚动窗口 + 最小样本门槛，见 §13 #10）→ ε 分桶（`RETURNABLE_CAMPAIGN` 加 `:returnable` 后缀与 shadow 域分离，防 returnable 组恒为 shadow 子集）→ `list_serving(genre, RETURNABLE)` 池内 `select_challenger_index` 确定性选 → 双路生成（挑战者复用冠军冻结 model_id，§4.1）→ `judge_pair`（硬门槛 + margin）择优 → 按 `returned_variant` 返回胜者文本；
> - **fail-safe 红线**：全程 try/except，任何异常回退冠军（reason=`error:<类型名>`），日志只落异常类型不落原文；检测不可用（`detect_fn` 返回 None）经 judge_pair 硬门槛判失败自然回退冠军（§5.5）；
> - **外部调用全部依赖注入**（`ReturnableDeps` 的 async rewrite_fn/detect_fn + consent_registry），核心 sqlite + 假 async 依赖可测；真实装配（PromptEvaluator._rewrite_text / 腾讯检测）在 reduce 端点挂载（子块 C）；
> - **边界**：子块 A 只交付择优核心，不落库、不挂载。**子块 B**（returnable 命中双路结果落库统计回流，保障第 9 步晋升与本节熔断有持续样本）与**子块 C**（ai_trace `reduce` 端点挂载 + 响应 `returned_variant` 字段 + fail-safe 双保险）已随后交付（见下两块）。人工开闸链路：第 7 步仅交付仓储方法 `update_serving_mode`（含 `assert_transition` 校验），管理审批入口（服务层 `approve_returnable` + `POST /challengers/{challenger_id}/returnable` 端点）于四轮评审修复①补齐（§13 #9）。

> ✅ 已实施（2026-07-30，§14 第 8 步 · 子块 B 命中结果落库统计回流）：`returnable_service.persist_returnable_experiment`（测试 `test_returnable_service.py` +5 用例）+ `shadow_executor.execute_experiment` 预置分支（测试 `test_shadow_executor.py` +5 用例）。实施决策：
> - **落库回流**：仅对真正跑双路的命中（`reason == "best_of_2"` 且有 `challenger_id`）复用实验行落一条 pending（`serving_mode=returnable`）+ 加密载荷，载荷内 `preset_challenger` 预置同步双路结果（挑战者文本 + AI 分 + `light_judge_result` + `returned_variant`）；幂等键三元组不变，命中既有行返回其 id；`ReturnableConfig` 增 `payload_key` / `payload_ttl_seconds`（读 `EXPERIMENT_PAYLOAD_KEY` / `EXPERIMENT_PAYLOAD_TTL`，与 shadow 同源）；挑战者行缺失或无载荷密钥则跳过；
> - **执行器预置分支**：载荷含 `preset_challenger` 时跳过 rewrite/detect/judge_pair，复用同步双路结果，只补异步复评（`review_fn`）→ `classify_verdict` → `record_settlement`，与 shadow 共用同一结算尾段（DRY），returnable 的 confirmed/invalidated/loss/infra_failure 样本自然汇入 `list_settlement_samples`，供第 9 步晋升与本节熔断；
> - **预算分离（§5.1）**：returnable 由风险治理（ε 阶梯 + 熔断 + margin），执行器对非 shadow 行跳过 `_settle_budgets` / `_release_budgets`，不占用/回写 shadow 预算；
> - **fail-safe**：`persist_returnable_experiment` 任何异常静默回滚返回 `None`，绝不影响用户返回；日志只落异常类型不落原文。**子块 C**（reduce 端点挂载）已随后交付（见下块）。

> ✅ 已实施（2026-07-30，§14 第 8 步 · 子块 C reduce 端点挂载）：`returnable_service.returnable_reduce`（编排层，测试 `test_returnable_service.py` +3 用例）+ `ai_trace.py` reduce 端点真实装配 + `ReduceResponse.returned_variant` 字段（测试 `test_ai_trace_admin_contract.py` +1 契约用例）。**首个对用户可见请求路径生效**。实施决策：
> - **编排层 `returnable_reduce`**：组合 `choose_returnable_variant`（择优）+ `persist_returnable_experiment`（命中落库），集中 config/request_id 默认化；纯组合无副作用，fail-safe 由 choose/persist 各自保证；与前几步「纯逻辑 + async 编排 + 落库 + 真实装配挂载」分层一致（DRY）；
> - **reduce 端点只做真实装配**：把 `PromptEvaluator._rewrite_text` + 腾讯检测（全文不截断）包成 async 依赖注入 `ReturnableDeps` 调 `returnable_reduce`；挑战者胜出即覆盖响应 `reduced_text` / `new_ai_score` / `improvement`，响应加 `returned_variant`（`champion`/`challenger`，未评估为 `None`）；
> - **落库位置在 shadow 分流之后**：确保 shadow 记录的是覆盖前的原始冠军文本；`EXPERIMENT_ENABLED` 默认关闭全惰性；
> - **fail-safe 双保险**：编排内部 choose/persist 各自兜底，端点再包一层旁路 `try`（任何异常回退冠军，只记异常类型名，绝不影响用户返回）。**至此第 8 步 returnable 开闸三子块（A 择优核心 / B 落库回流 / C 端点挂载）全部完成。**

### 5.5 超时、取消与降级决策表（v2 补全）

| Champion | Challenger | 检测服务 | 结果 |
|---|---|---|---|
| 成功 | 成功 | 成功 | 进入硬门槛与排序择优 |
| 成功 | 超时/失败 | 任意 | 返回 Champion |
| 失败 | 成功 | 成功 | 仅当 Challenger 为 returnable 且通过全部硬门槛才返回，否则报错 |
| 失败 | 成功 | 失败 | 统一失败，不得绕过质量门槛 |
| 失败 | 失败 | 任意 | 返回统一生成错误 |
| 成功 | 成功 | 检测失败 | 返回 Champion，本次不做探索返回 |

补充语义：

- **overall deadline**：请求级总超时（非仅挑战者分支），冠军 180s / 挑战者 120s / 请求总 200s（配置项）；
- **客户端断开**：冠军路取消；已发起的挑战者任务转为纯 shadow 样本继续完成并落账（成本已发生，数据不浪费）；
- **供应商不支持取消**时，已发生成本照常计入预算账本；
- **timeout 归类**：挑战者供应商超时 = `infrastructure_failure`，**不进胜率分母**（防止基础设施波动污染晋升统计），触发 cooldown 而非质量败场；
- 在线挑战者禁止沿用离线进化的 300→600s 超时扩张策略。

## 6. 存储与账本（v2 新增章节：在线实验任务、预算与冠军指针以数据库为权威，禁用 JSON 覆盖写）

`EvolutionStorage` 的普通 JSON 读写不能承载在线实验：多 worker 互相覆盖、复评晚到重复结算、状态转换无原子性、预算并发超发、晋升读不到一致快照、写一半进程退出损坏文件。`AtomicJsonStore`（ai_trace_competition.py）可作为本地配置/低并发统计的过渡，**不作为多实例在线实验权威账本**。本章权威边界限于实验任务、预算账本与冠军指针；启停调度的 holdout/sentinel/scheduler 三份信号账本为本地 JSON + 进程内原子写（单机单 worker 部署前提），该边界显式登记于 §13 #6。

### 6.1 表结构（SQLAlchemy + Alembic，四张起步，现为五张核心表）

> ✅ 已实施（2026-07-30）：模型 `backend/app/models/prompt_experiment.py`，迁移 `backend/alembic/versions/add_prompt_experiment_tables.py`（down_revision=add_user_voice_public_pool），测试 `backend/tests/test_prompt_experiment_models.py`（11 用例）。实施决策：
> - SQLAlchemy 2.0 `Mapped`/`mapped_column` 风格、Integer 自增主键、方言中立 `JSON`（非 JSONB）、`DateTime(timezone=True)` + `server_default=func.now()`，与既有模型一致；
> - `prompt_experiments` 只有 `payload_ref` + `payload_expires_at`，**无任何原文列**（原文归 §10 PayloadVault），测试以列名断言强约束；
> - 迁移手写并带 `inspector.has_table` 幂等保护（与项目现有迁移一致，env.py 不导入 models 故不走 autogenerate）；
> - 已注册进 `app/models/__init__.py`。
>
> ✅ 增量迁移（2026-07-25，§11.2 信号 3a）：`add_champion_ai_score_to_experiments.py`（down_revision=add_prompt_experiment_tables）向 `prompt_experiments` 新增可空列 `champion_ai_score FLOAT`（冠军原始 AI 检测分，结算落库供休眠期在线退化唤醒判定）。仅新增列不改既有语义，向后兼容；带 has_table + 列存在性幂等守卫，含 downgrade。
>
> ✅ 增量迁移（2026-07-25，五轮评审修复①，§13 #12）：`add_prompt_challenger_state_transitions.py`（down_revision=add_champion_ai_score_to_experiments，当前 head）新增第五表 `prompt_challenger_state_transitions`（挑战者 serving_mode 状态迁移审计），带幂等守卫，含 downgrade。迁移链：`add_prompt_experiment_tables → add_champion_ai_score_to_experiments → add_prompt_challenger_state_transitions`。

| 表 | 职责 | 说明 |
|---|---|---|
| `prompt_challengers` | 挑战者池（§3.1 schema + serving_mode 状态机） | |
| `prompt_experiments` | 实验任务 + 成对结果 + 异步复评结果 | 任务字段（§5.2）与复评结果合并为一行（一对一），四段状态机在此表推进 |
| `prompt_experiment_budgets` | 预算账本 | 含未结算任务的预留成本字段，幂等扣减、失败释放 |
| `prompt_champion_assignments` | 冠军指针历史（带生效区间） | 每行即审计记录，合并 audit_logs 职责；提示词内容仍在 EvolutionStorage，本表只存指针+哈希 |
| `prompt_challenger_state_transitions` | 挑战者 serving_mode 状态迁移审计（五轮评审修复①新增，§13 #12） | 记录 challenger_id / genre / from_mode / to_mode / operator / reason(String(500)) / created_at；只记录真实发生的状态变更 |

字段稳定后按需拆表（拆分低成本，反向合并痛苦）。

### 6.2 关键约束

- 实验表唯一约束：`(request_id, challenger_id, evaluation_policy_version)` —— 防复评晚到重复结算，也是"至少一次执行"的幂等基础；
- `provisional_win → confirmed_win / invalidated_win` 状态转换在事务内完成；
- 预算扣减与任务创建同事务；结算与状态转换同事务。

## 7. 异步权威评审与统计体系

> ✅ 已实施（2026-07-30，§14 第 5 步）：verdict 六分类 `backend/app/services/prompt_evolution/review_verdict.py`（测试 `test_review_verdict.py`，21 用例）+ 离线回放校准 `replay_calibration.py`（测试 `test_replay_calibration.py`，14 用例）。实施决策：
> - `classify_verdict` 纯映射，优先级 `infrastructure_failure > hard_failure > 同步判胜分支 > loss`；`async_review_hard_fail`/`async_review_confirms_win` 从 SemanticJudge 风格输出（保真/事实/完整/风险/置信）派生硬失败与胜负，硬门槛与既有 `SemanticJudge`（保真<80、事实<90、完整<75、风险=high、置信<0.6）一致，**不重建评审模型，仅做确定性归类**；
> - `compute_replay_consistency` 聚合作废率（`invalidated / (confirmed + invalidated)`）与一致率，`calibration_layer1_passed` 校验第 1 层门槛（有效样本 ≥200 且作废率 ≤5%，`infrastructure_failure` 不计入样本量）；
> - **数据限制**：磁盘进化历史 `PromptVersion.to_dict` 将原文/改写文截断为 100 字符，故回放同步门槛以分数类口径（AI 检测阈值、内容安全，不受截断影响）为准，全文结构类硬门槛不参与离线回放，待 shadow（§14 步骤 6）拿到完整全文后纳入逐层校准（§14 步骤 7）；
> - **本步只交付纯逻辑，不接 live 异步评审任务**（该耦合属 §14 第 6 步 shadow 上线）。

### 7.1 统计分类（晋升只使用 confirmed_win）

```
provisional_win        同步判胜，待异步确认
confirmed_win          异步评审确认的胜场
invalidated_win        同步判胜被异步作废（判定器误判，入作废率监控）
loss                   确认败场
hard_failure           质量硬失败（计入挑战者质量记录）
infrastructure_failure 供应商超时/检测异常（不计质量败场，触发 cooldown）
```

### 7.2 实验记录 schema（v2 补版本字段）

```json
{
  "request_id": "...", "genre": "玄幻",
  "champion_id": "...", "challenger_id": "...",
  "assignment_bucket": 4271, "serving_mode": "shadow|returnable",
  "resolved_model_id": "...", "model_selection_source": "prompt_combination",
  "model_config_version": "...", "prompt_version_id": "...",
  "provider_parameters_hash": "...",
  "light_judge_version": "v1", "evaluation_policy_version": "v1",
  "async_review_prompt_version": "v1", "async_review_model_id": "...",
  "detector_provider": "...", "detector_version": "...",
  "champion_prompt_hash": "sha256:...", "challenger_prompt_hash": "sha256:...",
  "model_catalog_version": "...",
  "light_judge_result": {"hard_fail": false, "score_champion": 71, "score_challenger": 78, "margin_passed": true},
  "returned_variant": "champion|challenger",
  "async_review_result": {"fidelity": 91, "fact": 95, "completeness": 88, "verdict": "confirmed_win"},
  "invalidated_win": false,
  "latency_ms": {"champion": 42000, "challenger": 51000},
  "cost": {"generation": 0.012, "detection": 0.002, "review": 0.008}
}
```

## 8. 晋升机制（v2 修正：硬闸门与推荐指标两分法）

### 8.1 硬闸门（不可绕过；绕过须单独授权 + 填写原因 + 审计日志）

1. 最小有效样本量（≥ 100，配置项）；
2. 离线安全准入通过（§3.2）；
3. 异步硬失败率 ≤ 上限（≤ 1%）；
4. 评审策略版本一致（不得跨 `evaluation_policy_version` 窗口聚合）；
5. 不存在未处理的安全事件。

### 8.2 推荐指标（管理员可权衡）

异步有效胜率 ≥ 60%；Wilson 95% CI 下界 > 50%（小流量期可放宽至 90% 置信）；作废率 ≤ 5%；P95 延迟不高于冠军 20%；单请求成本不超预算上限；题材覆盖达最低量。

### 8.3 切换与回滚

第一版不做自动晋升：系统推荐 → 管理员确认 → `prompt_champion_assignments` **原子指针更新**（不覆盖 `best_prompts.json` 原文件）→ 旧版本保留，秒级回滚。

连败处理三分法：suspended（近期差暂停）/ eliminated（样本充分确认退化）/ cooldown（基础设施问题不计质量账）。

**best-of-2 常态化后晋升的意义**：①非实验流量（ε 外单路请求）的质量基线；②预算耗尽 ε=0 时用户仍有好基线；③收敛探索空间。

> ✅ 已实施（2026-07-30，§14 第 9 步 · 子块 A 晋升统计 + 硬闸门/推荐评估）：`backend/app/services/prompt_evolution/promotion.py`（测试 `test_promotion.py`，20 用例）。纯逻辑，不触 DB、不接外部 API。实施决策：
> - **Wilson 置信下界**：`wilson_lower_bound(successes, total, z=1.96)`，`total=0` 返回 `0.0`（无证据不放行）；`z` 可配（1.96=95% / 1.645=90%，小流量期放宽，§8.2）；
> - **晋升统计口径（§7.1）**：`aggregate_challenger_stats(verdicts)` 复用 `replay_calibration.compute_replay_consistency`（同一作废率与有效样本口径，DRY）产出 `ChallengerStats`——胜负分母 `decisive_total = confirmed_win + loss`，`win_rate = confirmed / decisive_total`；`invalidated_win` 不计胜负仅入 `invalidation_rate = invalidated / (confirmed + invalidated)`；`infrastructure_failure` 不计质量账、不进有效样本与任何分母（§5.5）；`effective_total`、`hard_fail_rate = hard_failure / effective_total`；`wilson_lower_bound` 以 `decisive_total` 为分母；
> - **硬闸门（§8.1，不可绕过，全部满足才 `hard_gate_passed`）**：①有效样本 ≥ `PROMOTION_MIN_EFFECTIVE_SAMPLES`（默认 100）②离线安全准入通过（`offline_gate_passed` 由 §3.2 上游传入）③硬失败率 ≤ `PROMOTION_MAX_HARD_FAIL_RATE`（默认 0.01）④评审策略版本一致（数据源 `list_settlement_samples` 已按 `evaluation_policy_version` 过滤天然保证，`evaluate_promotion_gate` 显式断言 `policy_version_consistent`）⑤无未处理安全事件（`has_unresolved_safety_incident`）；未过条目名进 `hard_gate_failures`；
> - **推荐指标（§8.2，硬闸门通过 且 全部满足才 `recommended`）**：有效胜率 ≥ `PROMOTION_MIN_WIN_RATE`（0.60）、Wilson 下界 > `PROMOTION_MIN_WILSON_LOWER_BOUND`（0.50）、作废率 ≤ `PROMOTION_MAX_INVALIDATION_RATE`（0.05）；P95 延迟 / 单请求成本 / 题材覆盖第一版为 informational 不阻断；未过项进 `recommend_failures`；
> - **边界**：本子块只交付纯统计与门槛评估；从 `ExperimentRepository` 按挑战者聚合样本、`prompt_champion_assignments` 原子指针切换与秒级回滚（§8.3）属**子块 B**，管理员 API + 文档收尾属**子块 C**。

> ✅ 已实施（2026-07-30，§14 第 9 步 · 子块 B 原子切换 + 回滚服务层）：`backend/app/services/prompt_evolution/champion_assignment_repository.py` + `champion_promotion.py` + `ExperimentRepository.list_outcomes_for_challenger`（测试 `test_champion_promotion.py`，13 用例）。实施决策：
> - **指针仓储 `ChampionAssignmentRepository`**：`get_current`（`effective_until IS NULL` = 当前指针）/ `switch_champion`（原子关旧行 `effective_until=now` + 开新行，`previous_version_id` 自动取自当前指针，**只 flush 不 commit**，事务边界交服务层）/ `list_history`（按 `effective_from` 升序，每行即审计记录）；本表只存指针 + 哈希，不覆盖 `best_prompts.json`（§8.3）；
> - **按挑战者聚合数据源**：`ExperimentRepository.list_outcomes_for_challenger(challenger_id, evaluation_policy_version, light_judge_version=None)` 取该挑战者本策略版本窗口的已结算 verdict 序列（不跨版本，§8.1 #4），喂给子块 A 的 `aggregate_challenger_stats`；
> - **晋升编排 `promote_champion`**：校验挑战者处 `returnable`（`eligible→champion` 非法，须先经第 8 步开闸）→ 聚合统计 → `evaluate_promotion_gate` 硬闸门 → 未过且未授权则拒绝（`reason=hard_gate_failed`，指针/serving_mode 均不动）；授权须填 `override_reason`（否则抛 `ValueError`）并记入 `gate_overridden` 审计 → **同事务原子**：切指针 + 挑战者 `returnable→champion` + 旧冠军挑战者 `champion→suspended`（保留可回滚）→ `commit`；
> - **回滚 `rollback_champion`**：以指针表为冠军权威，秒级重指历史版本（取其内容哈希）+ 降级当前冠军挑战者；**不强改历史挑战者 serving_mode**（`suspended→champion` 非法），指针即事实来源；
> - **原子性（§6.2）**：指针切换与 serving_mode 推进同一 session，任一步抛错整体回滚，杜绝半更新。**管理员 API 挂载 + §14 步骤 9 收尾属子块 C。**

> ✅ 已实施（2026-07-30，§14 第 9 步 · 子块 C 管理员晋升/回滚/推荐查询 API）：`backend/app/api/v1/prompt_evolution.py` 新增三端点（测试 `test_champion_promotion_api.py`，11 用例：契约 + sqlite 集成）。实施决策：
> - **推荐查询 `GET /champion/recommendation`（require_admin，只读）**：列出该题材 `returnable` 挑战者（`ChallengerRepository.list_serving`），逐个经子块 A 的 `aggregate_challenger_stats` + `evaluate_promotion_gate` 计算硬闸门/推荐指标，供管理员权衡；不改任何状态；
> - **晋升执行 `POST /champion/promote`（require_admin）**：调子块 B 的 `promote_champion`；`offline_gate_passed`（§8.1 #2）取自挑战者行、`operator` 取登录管理员 `username`，均不信任客户端；硬闸门未过且未授权时返回 `promoted=False` + 失败项（HTTP 200，供前端展示），绕过须填 `override_reason` 否则转 HTTP 400；
> - **回滚 `POST /champion/rollback`（require_admin）**：调 `rollback_champion`，目标版本不在指针历史时返回 HTTP 404；
> - **契约对齐**：三端点均挂 `require_admin`（与 start/stop/resume 一致），沿用 `Depends(get_db)` 会话注入范式；服务层已被子块 B 13 用例覆盖，本子块聚焦接线与序列化的契约 + 集成验证。**至此第 9 步晋升闭环三子块（A 统计门槛 / B 原子切换回滚 / C 管理员 API）全部交付。**

## 9. 成本模型与实验预算（v2：预算先于 shadow 上线）

> ✅ 已实施（2026-07-30，§14 第 6 步 · 子块 A 持久化层）：`backend/app/services/prompt_evolution/budget_ledger.py`（测试 `test_budget_ledger.py`，13 用例）。实施决策：
> - `BudgetLedger` 把 `prompt_experiment_budgets` 落地为按 (日期 × 维度 × 维度键) 一行的三段式原子扣减：`reserve`（预留预估成本 + 占用调用配额，熔断开启或叠加后越限则拒绝返回 `False`）→ `settle`（成功：释放预留额 + 累加实际花费）/ `release`（失败/取消：仅释放预留额，**调用配额不回退**防并发超发）；**三个资金路径均加行级锁 `FOR UPDATE`**，同一账本行的 read-modify-write 串行化，防并发双双越限（sqlite 方言忽略，不影响单测）；
> - `is_exhausted` 供上游把 ε 降为 0：熔断 / 费用（已用 + 预留）达上限 / 调用达上限任一命中即耗尽；**无账本行视为未设限（不耗尽）**；`reserved_cost` 释放以 `max(0, ...)` 防负；
> - 与仓储同惯例：只 `flush` 不 `commit`，纯持久化不接 Celery / 外部 API，sqlite 内存库可测；供应商熔断的**触发判定与连接真实供应商属子块 B**。

```
增量成本 = ε × ( 挑战者生成 + 挑战者AI检测 + 异步完整评审(可能多次LLM调用)
              + 重试期望成本 + 供应商长尾超时重复调用 )
```

shadow 请求虽不返回挑战者，成本照付。**没有原子预算账本前禁止开启 shadow**——ε 再低也挡不住并发超发，这是账本问题不是比例问题。

预算账本（`prompt_experiment_budgets`）维度：全局日预算（调用数 + 费用）、按题材预算、单挑战者预算、**单用户实验频率上限**、未结算任务预留成本、供应商连续超时/错误率熔断、幂等扣减与失败释放。预算耗尽自动 ε=0。

## 10. 隐私与原文生命周期（v2 补全：覆盖异步任务全程）

> ✅ 已实施（2026-07-30）：`backend/app/services/prompt_evolution/experiment_privacy.py`，测试 `backend/tests/test_experiment_privacy.py`（14 用例）。实施决策：
> - `ExperimentConsentRegistry`：授权位独立文件存储，默认拒绝（未记录/已撤回均无授权），原子写（临时文件 + os.replace）；
> - `PayloadVault`：Fernet 加密落盘（任意字符串密钥经 SHA-256 派生），opaque reference = uuid4 hex（不含原文与主体信息），索引仅存 subject_id + expires_at；
> - 失败关闭：加密密钥为空拒绝构造，禁止明文兜底落盘；
> - TTL 语义：get 时惰性清除过期载荷 + `purge_expired()` 兜底批扫（可挂现有 Celery beat）；撤回授权走 `delete_by_subject` 批量删除；
> - 测试覆盖静态加密断言（磁盘全文件扫描无明文字节）与日志纪律断言（caplog 全量检查无原文）。

结构化信号回流（不存原文）仍是终态原则：

```json
{
  "genre": "玄幻", "input_length_bucket": "3000-5000",
  "entity_retention": 0.96, "ai_score_delta": -18,
  "fidelity_score": 91, "fact_score": 95, "completeness_score": 88,
  "challenger_id": "..."
}
```

但 shadow 挑战者必须拿到原文才能生成，须明确全生命周期规则：

1. **默认仅对 opt-in 用户执行 shadow**——匿名化用户标识 ≠ 取得"用于产品优化"的授权，二者独立处理；授权位单独存储；
2. 任务表/队列**只传 opaque payload reference**，原文短期载荷单独加密存储；
3. 载荷严格 TTL（`payload_expires_at`），处理完成立即删除，worker 失败由 TTL 兜底清理；
4. 用户撤回授权时，取消尚未处理的任务（按 subject_id 批量作废 pending 任务并删载荷）；
5. 日志与 `last_error_code` **禁止输出文本内容**；
6. 结构化指标与原文物理分离；
7. **供应商训练条款**：逐家核对 API 数据使用条款，"是否允许用于训练"作为模型目录元数据字段，shadow 任务分派时过滤不合规供应商；
8. 若必须留存文本用于人工排查：用户协议授权、脱敏、保留周期、支持退出、加密与访问控制。

## 11. 进化自动启停（休眠/唤醒门槛）

"效果特别好"是相对当前环境的快照。三个不会停的漂移源：①AI 检测器是对抗方，持续迭代；②改写模型换代；③输入分布漂移（题材热度、生成主链提示词更新）。进化应从"常开"转为"监控 + 按需触发"三态：**运行中 → 休眠 → 被唤醒**。

### 11.1 休眠门槛（何时停）

| 条件 | 建议规则 |
|---|---|
| 达标 + 边际收益枯竭 | 综合分达标，且连续 3 批次最佳提升 < 2 分（跨批次层，区别于单次运行内已有 stop conditions） |
| 新鲜样本验证 | 休眠前用未参与进化的新样本复评冠军，与样本池分差 < 阈值（防过拟合假象带水分入眠） |
| 预算触顶 | 周期进化费用达上限，强制休眠 |

### 11.2 唤醒门槛（比休眠门槛更重要——风险不对称）

| 信号源 | 触发规则 | 成本 |
|---|---|---|
| 在线冠军退化 | 滚动窗口 AI 率均值上升越限 / 异步评审保真、事实分下降 / 用户重跑率上升 | 零（双路体系天然产出） |
| 挑战者反超 | 某挑战者 confirmed 胜率显著超冠军（说明休眠判断错了） | 零 |
| 环境变更事件 | 胜出模型切换 / 检测服务版本变化 / 新增题材 / 生成主链提示词大改 | 事件驱动 |
| 哨兵巡检 | 休眠期每周小批新鲜样本评估冠军（无在线流量时的兜底） | 低 |

### 11.3 滞回与定向唤醒

- 开、关阈值分离（如休眠"连续 3 批提升<2 分"，唤醒"AI 率回升>8 分或保真降>5 分"），缓冲带防抖动启停；
- 唤醒后**定向进化**：把退化信号写入变体生成提示词（复用 `_session_strategy_history` 注入通道），探索对准退化方向；
- 休眠 ≠ 失明（成对实验持续监控冠军）、休眠 ≠ 停止择优（best-of-2 照常），休眠只停"离线生成新变体"。

本章为后续优化，**不是第一版阻塞项**（依赖 §5-§7 的统计信号，实施排最后）。

> ✅ 已实施（2026-07-25，§14 第 10 步 · 子块 A 启停调度纯逻辑）：`backend/app/services/prompt_evolution/evolution_scheduler.py`（测试 `test_evolution_scheduler.py`，26 用例：阈值 + 休眠/唤醒门槛 + 三态转移 + 滞回）。与 `promotion.py` 子块 A 同构，纯逻辑不触 DB/Celery/外部 API。实施要点：
> - **三态常量** `running / sleeping / awake`（§11 首段），`SchedulerThresholds`（frozen dataclass + `from_env`，休眠/唤醒阈值分离形成 §11.3 滞回缓冲带）；
> - **休眠门槛 `evaluate_sleep_gate`（§11.1）**：两条独立触发（OR）——①预算触顶强制休眠；②达标 + 连续 N 批最佳提升 < 阈值（边际枯竭）+ holdout 分差 ≤ 上限（防过拟合假象带水分入眠）三者 AND；批次不足不判枯竭；
> - **唤醒门槛 `evaluate_wake_gate`（§11.2 风险不对称，OR）**：冠军 AI 率回升 / 保真降 / 挑战者 Wilson 下界反超 / 环境变更事件 / 哨兵巡检退化，任一命中即唤醒，返回全部命中原因；
> - **状态转移 `decide_next_state`（§11.3 滞回隔离）**：running 只判休眠门槛、sleeping 只判唤醒门槛、awake 消费一次即转 running 重启定向进化；按当前态只判一侧天然防抖动。**信号采集 + 状态落盘 + beat 编排属子块 B，管理面板属子块 C。**

> ✅ 已实施（2026-07-25，§14 第 10 步 · 子块 B 信号采集 + 状态落盘 + beat 编排）：`scheduler_state.py` + `scheduler_orchestration.py` + `experiment_tasks.py` 薄壳（测试 `test_evolution_scheduler_orchestration.py`，43 用例：落盘 + 信号采集 + 三态转移编排 + 环境变更快照 + 冠军 AI 率回升）。实施决策：
> - **三态落盘 `SchedulerStateStore`**：按题材存三态到 `data/prompt_evolution/scheduler_state.json`（复用临时文件 + `os.replace` 原子写范式），`get`（默认 running）/ `set`（状态变化，刷新 updated_at，可选 `env_snapshot` 抓拍入眠环境指纹）/ `touch`（仅刷新 last_tick_at，保留快照）/ `snapshot`（供子块 C 面板）；
> - **信号采集**：`compute_recent_improvements`（进化历史摘要该题材 completed 批次相邻 `best_score` 差，综合分越低越好差为正=提升）、`is_genre_converged`（进化历史摘要该题材最新完成批次 `best_score ≤ target_score` 即达标，§11.1）、`compute_champion_fidelity_drop`（champion 异步复评滚动窗口保真度量 `mean(semantic_fidelity, fact_consistency)` 基线窗均值 − 近窗均值，正=保真下降，§11.2；有效样本 < 2×window 返回 0.0）、`compute_best_challenger_wilson_lower_bound`（returnable 挑战者结算序列逐个聚合取最大 Wilson 下界，§11.2 反超）；`experiment_repository.list_champion_reviews` 提供按 `finished_at` 升序的只读复评序列；
> - **环境变更（§11.2 信号 4 接真实源）**：入眠（running→sleeping）时把当前环境版本指纹（`evaluation_policy_version` + `light_judge_version`，任务层稳定可得的版本常量；无稳定来源的 model_catalog_version 不纳入，宁缺毋臆造）抓拍进 `env_snapshot`；sleeping 期每次 tick 用当前指纹与快照对比，不一致即置 `environment_changed` 唤醒。无快照/空指纹不误触发；
> - **冠军在线 AI 率回升（§11.2 信号 3a 接真实源，2026-07-25）**：结算路径落库冠军原始 AI 检测分——`record_settlement` 增只写可选参 `champion_ai_score`（终态幂等保护不变），`shadow_executor` 结算时把加密载荷取出的分值传入（载荷本体仍按 §10 即删）；DB 增量迁移 `add_champion_ai_score_to_experiments`（可空列，历史行为空）。`experiment_repository.list_champion_ai_scores` 提供按 `finished_at` 升序、排除空值的只读序列；`compute_champion_ai_score_rise` 以近窗均值 − 基线窗均值算回升幅度（正=AI 率回升=在线退化，与 fidelity_drop 同窗口参数；有效样本 < 2×window 返回 0.0 不触发）；
> - **holdout 分差（§11.1 信号 2 接真实源，2026-07-25）**：留出集 + 新鲜复评 + 低频缓存三段（`holdout_probe.py`，测试 `test_holdout_probe.py` 17 用例）——①`TestSample` 增 `is_holdout` 持久化字段（旧 JSON 缺省训练侧，向后兼容），`is_holdout_sample_id` 按 `sample_id` 哈希以 `HOLDOUT_RATIO=0.3`（结构参数）确定性划分（同一样本恒定归属、增删不漂移），`TestSampleManager.apply_holdout_split` 幂等划分落盘、`get_samples_by_genre` 增 `holdout` 过滤；②`evaluate_holdout_gap` 取当前冠军全文（`storage.get_prompt_selection`）分别在训练/留出样本上跑 `PromptEvaluator.evaluate_prompt`，gap = holdout_avg − training_avg（平均 AI 得分越低越好，正=留出显著更差=过拟合假象），写 `data/prompt_evolution/holdout_scores.json` 缓存（原子写，含 `champion_hash`/`policy`；冠军与 policy 均未变跳过重算控成本，无冠军/单侧无样本跳过）；③beat 任务 `prompt_experiment.run_holdout_eval` 每日 03:40 UTC 低频逐题材复评（纯 JSON + 外部评分 API，不建 DB 会话；单题材失败不中断），tick 装配 `holdout_score_gap` 为只读缓存（`HoldoutScoreStore.get_gap`：无缓存/损坏/policy 不一致降级 0.0 中性，不阻止入眠不误触发）；
> - **编排层与依赖注入分离 `SchedulerTickDeps`**：已接入真实源的信号（预算触顶 `BudgetLedger.is_exhausted` / 跨批次提升 / **综合分达标** / **冠军保真下降** / **冠军在线 AI 率回升** / 挑战者反超 / **环境变更**〔`env_fingerprint` 指纹对比〕/ **holdout 分差**〔读 `holdout_probe` 低频缓存〕/ **哨兵巡检退化**〔读 `sentinel_probe` 低频缓存〕）已在 tick 采集或经任务层装配注入，**至此 §11 全部启停信号均已接入数据源**；
> - **哨兵巡检（§11.2 信号 5 接真实源，2026-07-25）**：`sentinel_probe.py`（测试 `test_sentinel_probe.py`，14 用例）——哨兵语料为 holdout 留出子集按 `sample_id` 排序取前 `SENTINEL_SAMPLE_COUNT=5`（结构参数，恒定语料保证跨次可比）；`run_sentinel_probe_for_genre` 对当前冠军做新鲜 AI 检测（复用 `evaluate_prompt` 平均分口径；保真侧无现成聚合出口不臆造），同冠军 + 同 policy 首次探测建基线，后续 `last − baseline > wake_ai_score_rise`（复用 §11.2 现有唤醒阈值，不新增阈值）即置退化；冠军/policy 变更基线重置（不可比）；退化标志写 `sentinel_state.json`（原子写），tick 经 `SentinelStateStore.is_degraded` 只读消费，无缓存/损坏/policy 不一致一律 False（不误唤醒，安全侧）。哨兵不按 champion_hash 跳过重测（目的正是对同一冠军探测检测器/环境漂移），成本控制在任务层：只探 sleeping 题材（唤醒信号仅 sleeping 期被消费）+ 低频 beat；
> - **beat 薄壳**：`prompt_experiment.run_scheduler_tick`（`EXPERIMENT_ENABLED` 未开启空转 → 装配真实源 → 逐题材 tick → 落盘）+ 每 60 分钟轮询；`prompt_experiment.run_holdout_eval` 每日低频复评写缓存；`prompt_experiment.run_sentinel_probe` 每 12 小时（04:10/16:10 UTC，与 holdout 复评错峰）对 sleeping 题材哨兵探测写缓存。**管理面板/手动启停端点属子块 C。**

> ✅ 已实施（2026-07-25，§14 第 10 步 · 子块 C 状态面板 + 手动休眠/唤醒 API）：`backend/app/api/v1/prompt_evolution.py` 新增三端点（测试 `test_evolution_scheduler_api.py`，11 用例：契约 + tmp_path 集成）。实施决策：
> - **状态快照 `GET /scheduler/state`（require_admin，只读）**：按 `EVOLUTION_GENRES` 逐题材读 `SchedulerStateStore`（无记录默认 running），返回三态 + reasons + updated_at/last_tick_at，供管理面板观测；不改任何状态；
> - **手动休眠 `POST /scheduler/sleep`（require_admin）**：置 sleeping（reasons 含 `manual_sleep` + 可选备注），落盘；未知题材（不在 `EVOLUTION_GENRES`）返回 HTTP 400 防脏记录；
> - **手动唤醒 `POST /scheduler/wake`（require_admin）**：置 awake（过渡态，下一次 beat tick 消费转 running 触发定向进化，§11 三态语义），reasons 含 `manual_wake` + 可选备注；未知题材 400；
> - **可测性**：状态账本装配为可注入依赖 `get_scheduler_state_store`（默认落盘路径），测试用 `tmp_path` override；三端点均挂 `require_admin`（与 champion/start/stop 一致）。**至此第 10 步启停调度三子块（A 纯逻辑 / B 信号采集落盘 beat / C 管理面板 API）全部交付，§14 十步实施收官。**

## 12. 场景分层策略

| 场景 | 特征 | 策略 |
|---|---|---|
| 织文无迹 /ai-trace | **人在环**：用户在屏幕前审阅结果，不满意可重跑，单次漂移伤害被人工兜底 | 先行开放 returnable 择优返回 |
| 灵感方舟正文生成 | 无人值守，结果直接入库 | 维持保守：仅 shadow 采数据，择优返回待 ai-trace 验证成熟后评估 |

## 13. 遗留技术债（实施前/中顺带处理）

1. `engine._failed_variants` 进程内 dict，重启失忆——落盘后才能承担离线准入第 7 条职责；
2. `novel_rules.SENTENCE_PATTERN_FIXES` 全仓无消费点，死配置——删除或接入 `postprocess_text`；
3. 离线样本池过拟合——建立留出集（holdout），进化停止与休眠判定均用新鲜样本复核。✅ 已处理（2026-07-25，§11 子块 B 信号 2）：`is_holdout` 确定性划分 + `holdout_probe` 冠军新鲜复评 + 休眠门槛 `holdout_score_gap` 消费；进化停止侧（运行内 stop conditions）如需复用留出集另行评估；
4. 极端评分告警——"原始 99 → 改写后 0"类分数触发过度改写复查而非直接采信。
5. 启停信号真实数据源接入（§11 · 子块 B）——✅ 全部接入完毕（2026-07-25）：综合分达标（`is_genre_converged`，信号 1）、holdout 分差（`holdout_probe` 留出复评缓存，信号 2）、冠军在线 AI 率回升（`champion_ai_score` 结算落库 + `compute_champion_ai_score_rise`，信号 3a）、冠军保真下降（`compute_champion_fidelity_drop`，信号 3b）、环境变更（入眠 `env_snapshot` 指纹快照对比，信号 4）、哨兵巡检退化（`sentinel_probe` 定时探测缓存，信号 5）。
6. 外部评审采纳项（2026-07-25 启停信号治理，三步）：①题材列表双份维护——✅ 已处理：`EVOLUTION_GENRES` 收敛为 `experiment_contract.py` 单一定义点，API 面板与调度 beat 任务均 import 引用同一对象（契约测试 + 同一性断言防漂移，新增题材只改契约模块）；②holdout/sentinel 缓存无新鲜度校验（任务停摆后旧缓存无限有效）——✅ 已处理（步骤 B）：`get_gap` 超 `HOLDOUT_GAP_MAX_AGE_HOURS=48h`（2× 每日 beat 周期）降级 0.0、`is_degraded` 超 `SENTINEL_STATE_MAX_AGE_HOURS=24h`（2× 12h beat 周期）降级 False，时间戳缺失/不可解析按超龄保守降级并落 warning 日志，`now` 可注入（陈旧判定 `is_record_stale` 单一实现于 holdout_probe，sentinel 复用）；③调度面板无信号可观测性（无法区分真实值与降级默认值）——✅ 已处理（步骤 C）：`GET /scheduler/state` 逐题材附 `signals` 元数据块（`holdout: {gap, computed_at, stale, defaulted}` / `sentinel: {degraded, checked_at, stale, defaulted}`），值为 tick 真实消费口径（含降级），`stale` = 有记录但时间戳超龄，`defaulted` = 消费的是降级默认值；观测口径由 store 层 `describe_signal` 提供（与消费逻辑同处防漂移），API 层纯读缓存组装不触发外部调用不改状态。**部署前提边界**：holdout/sentinel/scheduler 三份 JSON 账本均为本地文件 + 进程内原子写，隐含"单机单 Celery worker（beat 与 worker 同宿主）"部署前提；多实例/多 worker 部署需先迁移共享存储（DB 表或 Redis）并处理 read-modify-write 竞态，属显式登记的架构边界而非缺陷。
7. 二轮评审修复（2026-07-25，TTL 治理补丁）：①（高）holdout 生产端保鲜闭环——`evaluate_holdout_gap` 缓存复用条件从"hash+policy 未变"收紧为 `is_gap_record_consumable`（hash 未变 + policy 一致 + gap 数值 + 时间戳新鲜），超龄必须重算刷新，杜绝"冠军不变 → 永久 skipped_cached → 消费端 TTL 降级后永久 0.0 不可恢复"；②（中）未来时间戳判 stale——`is_record_stale` 对 `age < 0`（时钟异常/人工改动）按超龄处理，无容差参数（KISS）；③（中）sentinel `degraded` 严格 bool 校验——`is_sentinel_record_consumable` 统一 `is_degraded`/`describe_signal` 口径，合法 JSON 但类型损坏（如 `"false"` 字符串）不经真值转换误唤醒，面板同步标记 `defaulted`。两 store 均以"记录可消费"单一判定函数收敛消费/观测/生产三处口径，防再次漂移。
8. 三轮评审修复（2026-07-25，gap 严格有限数值校验）：holdout `gap` 此前接受 bool（int 子类穿透 `isinstance` 检查，`true` 被当 1.0 消费）与 NaN/Infinity（Python json 默认解析的非标准值，NaN 使休眠门槛比较恒 False 永不休眠、-inf 反向放行带水分入眠，且面板 `defaulted=false` 无从察觉）。修复：①消费边界——新增 `is_finite_number`（排除 bool + `math.isfinite`），`is_gap_record_consumable` 改用之，get_gap/describe_signal/evaluate_holdout_gap 三处口径自动跟随；②生产边界——`evaluate_holdout_gap` 落盘前校验 `training_avg`/`holdout_avg` 有限（两有限数相减必有限，gap 无需重复验），非法抛 `ValueError`（含题材与非法字段名）由任务层现有单题材兜底接住，旧缓存不被污染、保留至 TTL 到期自然降级。与二轮 sentinel 严格 bool 修复原则对称。
9. 四轮评审修复①（2026-07-25，returnable 人工开闸闭环）：此前 `eligible → returnable` 在生产链路不可达——`update_serving_mode(x, "returnable")` 无任何生产调用点，第 8 步 `returnable_reduce` 的 `list_serving(genre, RETURNABLE)` 永远为空，best-of-2 择优成断头链路。修复：`returnable_service.approve_returnable`（限定从 eligible 出发，cooldown 恢复走既有状态机路径不经本入口；operator + reason 交付时仅落应用日志，后经五轮评审修复①升级为同事务落审计表，见 #12）+ 管理端点 `POST /challengers/{challenger_id}/returnable`（`require_admin`，审批原因必填，非 eligible 400 / 不存在 404），复刻冠军晋升端点范式。
10. 四轮评审修复②（2026-07-25，熔断窗口化）：`is_circuit_open` 此前消费 `list_settlement_samples` 全生命周期累计样本（含 shadow），无时间窗、无场景隔离、无最小样本门槛——危险侧要害是历史稀释（shadow ε≈0.3 vs returnable ε=0.05 样本量级碾压 + 旧样本淹没近期退化，判定器真实退化时熔断迟迟不开），安全侧是小样本过度熔断（1/1=100% 即停摆）。修复：仓储新增 `list_recent_returnable_outcomes(policy, since)`（`serving_mode='returnable'` + `finished_at >= since`，与校准用全量查询刻意分开）；`is_circuit_open` 改为滚动窗口 `EXPERIMENT_CIRCUIT_WINDOW_HOURS`（默认 168h，§5.4 既定 7 日）+ 最小有效样本门槛 `EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES`（默认复用 replay 校准同语义常量 `DEFAULT_MIN_SAMPLES=200`），样本不足视为预热态不熔断（统计可信前由校准层门槛兜底），`now` 可注入。（预热期无条件放行后经五轮评审修复②升级为双层规则，见 #13）
11. 四轮评审修复③（2026-07-25，文档一致性收口，纯文档无代码改动）：①文档头状态行"实施中"与"十步收官"并置含混——收口为"十步实施完成 + 评审修复迭代期"；②§5.4 子块 A/B 仍挂"🔄 部分实施"且尾注"子块 B/C 待实施"，与子块 C"三子块全部完成"陈述互相矛盾——统一收口为 ✅ 并互链；③§5.4 子块 A 边界段"人工开闸 API 第 7 步已交付"为错误陈述（第 7 步仅交付仓储方法，管理 API 实为四轮修复①交付）——已更正；④§6 标题"数据库为权威，禁用 JSON 覆盖写"全称陈述与 holdout/sentinel/scheduler 三份本地 JSON 信号账本（§13 #6 登记边界）矛盾——标题限定为"在线实验任务、预算与冠军指针以数据库为权威"；⑤§15 配置清单与代码脱节（`PROMOTION_MIN_SAMPLES`/`_CI_LEVEL` 等旧名无消费点、`EVOLUTION_SLEEP_*` 通配名与实名不符、遗漏 `EXPERIMENT_MAX_ATTEMPTS`/`EXPERIMENT_ESTIMATED_COST` 及本轮 CIRCUIT 两项、`EXPERIMENT_CHALLENGER_TIMEOUT`/`EXPERIMENT_OVERALL_DEADLINE` 无消费点未标注）——重写为"环境变量实名 / 设计预留 / 结构常量"三张表；⑥§14 各步骤测试数量为交付时点快照、随修复批次持续过期——表后加口径声明（权威以 pytest 实际收集为准），不再逐处追改数字。
12. 五轮评审修复①（2026-07-25，人工开闸持久化审计）：`approve_returnable` 此前 operator + reason 仅落应用日志——日志可轮转/丢失/多实例分散、无事务保证（commit 后进程在 logger 前退出即"状态已变更、审批无痕"）、无稳定审计事件 ID，不构成审计记录；而冠军晋升的 `prompt_champion_assignments` 每行即审计（operator/reason 落库），同为流量管理动作标准不对齐。修复：新增第五表 `prompt_challenger_state_transitions`（challenger_id / genre / from_mode / to_mode / operator / reason(String(500)) / created_at，迁移 `add_prompt_challenger_state_transitions` 带幂等守卫，当前 head）；`approve_returnable` 改为同一事务「校验 eligible → `update_serving_mode` → 插入审计行 → 统一 commit」，拒绝/不存在时不留审计行（审计只记录真实发生的状态变更），日志降级为辅助可观测。（其中 `update_serving_mode` 盲写经六轮评审修复①升级为 `transition_serving_mode` 条件更新，见 #15）
13. 五轮评审修复②（2026-07-25，熔断预热期双层规则）：#10 交付的熔断在 `effective_total < circuit_min_samples`（默认 200）时无条件放行是硬切换两态——预热期 150 样本 80% 作废率也不熔断；"校准层兜底"只覆盖开闸前的 shadow 历史，兜不住开闸后的供应商漂移/检测器异常/returnable 分布差异。修复：`is_circuit_open` 改为双层规则——成熟期（≥ `circuit_min_samples`）沿用 `invalidation_rate_max`（0.05）；预热期（`warmup_min_samples` ≤ 有效样本 < `circuit_min_samples`）用更宽的 `warmup_invalidation_rate_max` 兜底严重劣化；低于 `warmup_min_samples` 证据不足仍不熔断。新增配置 `EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES`（默认 20）/ `EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX`（默认 0.20）——**默认值为评审建议初值（文档此前无既定值），上线前按业务风险复核**。（`warmup_min_samples` 与 `circuit_min_samples` 的跨字段约束"须严格小于"后经七轮评审修复②补齐，见 #18。）
14. 五轮评审修复③④（2026-07-25，输入验证边界收紧）：③（中）`ReturnableConfig` 此前无任何范围校验——`EXPERIMENT_CIRCUIT_WINDOW_HOURS=-1` 使 `since` 落在未来、熔断静默永久关闭（危险侧）；`"nan"` 是合法 float 解析不走 `_env_float` 回退。修复：`__post_init__` 集中范围校验覆盖所有构造路径（window 有限正数、min_samples/warmup_min_samples ≥ 1、epsilon 与两个作废率 ∈ [0,1]、payload_ttl > 0），非法配置带配置名抛 ValueError 失败关闭；新增 `_env_int` 使 int 字段的 nan/inf 与其它非法串一致回退默认值（回退语义后经六轮评审修复②升级为失败关闭，见 #16）。④（低）reason 此前仅 `min_length=1`，纯空白/换行注入可通过。修复：服务层 `normalize_approval_reason`（空白统一规范化为单个空格 + strip 拒纯空白 + 上限 500 对齐审计表 `String(500)` 失败关闭），`approve_returnable` 入口防御验证不依赖 HTTP 层；API 层 `ApproveReturnableRequest` 加 `max_length=500` + `field_validator` 复用同一函数（ValueError → 422），单一规则来源防两层漂移。
15. 六轮评审修复①（2026-07-25，人工开闸并发竞态）：#12 交付的开闸流程是「SELECT（无行锁）→ 内存断言 eligible → 盲写 UPDATE → 插审计行」——READ COMMITTED 下两个并发审批都能读到 eligible 并各自提交成功，产生两条 `eligible → returnable` 审计行（第二条无对应真实状态变更，违背 #12"审计只记录真实发生的状态变更"），且两次都返回 200，管理端无法区分重复点击与真正迁移。修复：`ChallengerRepository` 新增 `transition_serving_mode`（条件更新 `UPDATE ... WHERE challenger_id=:id AND serving_mode=:from_mode` + 影响行数判定，不依赖行锁/隔离级别，sqlite 测试可真实验证）；`approve_returnable` 只在条件更新命中（rowcount=1）时插入审计行，未命中时重读真实状态抛 ValueError（HTTP 400，消息含当前状态）失败关闭。既有 `update_serving_mode` 保留并加注释限定单 worker 调度器上下文（champion_promotion / layered_calibration）使用。并发测试以陈旧读模拟覆盖：只有一个请求成功、全库仅一条审计行。
16. 六轮评审修复②（2026-07-25，配置解析失败关闭）：#14 交付后 `_env_float`/`_env_int` 对"已设置但不可解析"的值（如 `EXPERIMENT_CIRCUIT_WINDOW_HOURS=abc`）仍静默回退默认值——部署侧变量值写错时服务以看似正常的默认策略启动，与 #14"非法配置失败关闭"精神不一致；`_env_int` 经 `float→int` 还会把 `"10.9"` 隐式截断为 10。修复：两类区分——未设置或空白串视为未配置用默认值；已设置但不可解析抛带配置名 ValueError（`非法配置 {name}={raw!r}`）失败关闭；`_env_int` 改为直接 `int(raw)` 解析拒绝小数串。数值范围合法性仍由 `__post_init__` 兜底（`"nan"`/`"inf"` 是合法 float 解析，在构造期被范围校验拦截）。范围限定 `returnable_service.py`（评审点名范围），其他模块同类解析器不在本批次扩散。
17. 六轮评审修复③（2026-07-25，文档五表口径统一，纯文档无代码改动）：#12 新增第五表后，§6.1 标题"四张起步"、四表表格、§14 步骤 3"四表模型"、附录 A/B"数据库四表"仍为四表口径，与 #12 互相冲突，读者会误以为状态迁移审计表不属于正式持久化设计。修复：§6.1 标题标注"现为五张核心表"并保留"四张起步"为历史叙述；✅ 块补第五表增量迁移登记（含完整迁移链）并更正 `add_champion_ai_score_to_experiments`"当前 head"过期陈述（附带发现，head 已被 `add_prompt_challenger_state_transitions` 取代）；表格增 `prompt_challenger_state_transitions` 行；§14 步骤 3 与附录 A/B 补"交付时点四表、现为五表"边界注，历史快照不改写只加指向。

18. 七轮评审修复（2026-07-25，配置有限值与跨字段约束）：#14 集中范围校验遗漏 `ai_threshold`/`margin_threshold` 两字段。①（中高）`ai_threshold` 未校验有限值与范围——`EXPERIMENT_AI_SCORE_THRESHOLD=nan` 是合法 float 解析穿过 `_env_float`，硬门槛 `check_hard_fail` 为 `ai_score > ai_threshold`，任何分 `> nan` 恒 False → AI 分硬门槛静默失效（危险侧，非安全降级且面板无从察觉）；`inf` 恒真误杀、负值放宽。`margin_threshold` 同理：负值/-inf 使无显著领先的挑战者通过 margin（放水），inf 永不返回挑战者，nan 恒不过。修复：`__post_init__` 新增两项——`ai_threshold` 须有限且 ∈ [0,100]（业务量表，`compute_ranking_score` 以 100.0 为最差占位）、`margin_threshold` 须有限非负（排序分差值无固定上限故不设上界）。②（低）预热与成熟门槛无跨字段约束——`warmup_min_samples(200) >= circuit_min_samples(20)` 时 #13 预热分支 `warmup ≤ 有效样本 < circuit` 区间为空集、预热保护静默失效。修复：`__post_init__` 元组校验后追加跨字段约束 `warmup_min_samples < circuit_min_samples`（严格小于，消息含两个配置名）；文档未定义"相等 = 关闭预热"语义，失败关闭。范围限定 `returnable_service.py`。（新约束暴露既有熔断测试 `_config(circuit_min_samples=2)` 默认 warmup=20 参数不自洽，为其显式传 `warmup_min_samples=1`，不改断言语义。）（其中 `ai_threshold` 校验此时仅覆盖 `ReturnableConfig` 构造路径，shadow 装配路径的同项绕过后经八轮评审修复①以公共 `parse_ai_threshold` 统一，见 #19。）

19. 八轮评审修复（2026-07-25，AI 阈值配置双路径统一）：#18 的 `ai_threshold` 校验只覆盖 `ReturnableConfig` 构造路径，但 shadow 执行器装配 `experiment_tasks._build_deps` 仍以裸 `float(os.getenv("EXPERIMENT_AI_SCORE_THRESHOLD", "25.0"))` 独立解析——`nan/inf/-1` 成功穿透直接进 `ShadowExecutionDeps.ai_threshold`，绕过 #18 有限值 + [0,100] 校验，形成两套配置语义（returnable 严拒、shadow 放行）：同一实验策略在 shadow 校准阶段与 returnable 线上阶段用不同 AI 硬门槛，`nan` 使 shadow 侧 `ai_score > ai_threshold` 恒 False、硬门槛静默失效并污染校准数据与作废率统计（作废率又是熔断与四层校准的输入）。修复：`returnable_service.py` 提取公共 `parse_ai_threshold(default=25.0)`（`_env_float` 解析 + 有限值 [0,100] 校验，与 `__post_init__` 同一规则），`ReturnableConfig.from_env` 与 `_build_deps` 均复用之（单一解析校验来源，不让 Celery 装配耦合整个 returnable 配置）；`_build_deps` 将该解析前置到重模块导入之前 fast-fail。shadow 路径测试覆盖 `nan/inf/-inf/-1/101/abc` 均拒。`EXPERIMENT_MAX_ATTEMPTS` 仍为裸 `int()` 解析（同类配置治理债），审查明示不属本轮 AI 阈值问题，登记为后续统一处理项（空值默认 / 非整数拒绝 / < 1 拒绝 / 错误含配置名）。（该后续项已由九轮评审修复结清，见 #20。）

20. 九轮评审修复（2026-07-25，MAX_ATTEMPTS 配置校验，结清 #19 后续项）：`experiment_tasks._build_deps` 的 `EXPERIMENT_MAX_ATTEMPTS` 仍为裸 `int(os.getenv(...))`——`abc` 抛无配置名语义的 ValueError，`0/-1` 成功装配传入执行器，执行器判定 `attempt_count >= deps.max_attempts` 使任务首次异常即入 dead、预期重试保护失效。修复：`returnable_service.py` 新增公共 `parse_max_attempts(default=3)`（与 `parse_ai_threshold` 对称，`_env_int` 解析 + `>= 1` 范围校验，`1.5` 小数串由 `_env_int` 直接 `int()` 拒绝，非法抛带 `EXPERIMENT_MAX_ATTEMPTS` 配置名 ValueError）；`_build_deps` 改用之并与 `parse_ai_threshold` 并列在重导入前 fast-fail。测试覆盖单元层（`abc/0/-1/1.5` 拒 + 合法值/默认/边界 1）与 shadow 装配层。至此 shadow 装配的两项配置（AI 阈值、重试次数）均经公共解析器校验失败关闭。

## 14. 实施顺序 v2（十步，分步执行、每步完成后确认再推进）

| 步骤 | 内容 | 用户可见影响 |
|---|---|---|
| 1 ✅ | **冻结实验契约**：模型解析冻结、生成参数、HMAC 分桶、评审版本体系、状态机定义（§4）。已落地 `experiment_contract.py` + 18 测试 | 无（纯契约模块） |
| 2 ✅ | **隐私规则**：用户授权位、原文短期载荷加密/TTL/删除/日志规则（§10）。已落地 `experiment_privacy.py` + 14 测试 | 无 |
| 3 ✅ | **持久化底座**：实验任务表、实验账本、预算账本、assignment 审计表（Alembic 迁移，§6）。已落地 `prompt_experiment.py` 四表模型 + `add_prompt_experiment_tables` 迁移 + 10 测试（交付时点为四表；后经五轮评审修复①增至五表，见 §6.1 / §13 #12） | 无 |
| 4 ✅ | **挑战者池**：接入离线七项准入（含 `_failed_variants` 落盘），生成带版本与内容哈希的 Challenger Pool。已落地 `challenger_pool.py`（七门槛聚合 + id/hash 生成 + 策略族分类）+ `challenger_repository.py`（`FailedVariantStore` 落盘 + 幂等入库）+ 32 测试 | 无 |
| 5 ✅ | **判定器先行**：完整实现同步轻量判定器 + 异步权威评审，**先用离线回放样本验证一致率**（进化历史三元组回放，上线前预热第 1 层校准）。已落地 `light_judge.py`（硬门槛 + 排序分 + 不对称 margin）+ `review_verdict.py`（verdict 六分类）+ `replay_calibration.py`（一致率/作废率 + 第 1 层校准门槛）+ 62 测试 | 无 |
| 6 ✅ | **shadow 上线**：持久任务 + 原子预算 + 供应商熔断 + 任务重试同时启用，禁止裸 fire-and-forget。**子块 A**（持久化层）：`experiment_repository.py`（任务表创建幂等/租约认领 `FOR UPDATE SKIP LOCKED`/可重入状态转换/终态保护/结算/dead）+ `budget_ledger.py`（预算 reserve/settle/release 行级锁 + 熔断 + 耗尽判定）+ 28 测试。**子块 B-1**（分流编排）：`shadow_dispatch.py`（开关→授权→ε→确定性选→幂等预查→四维预算→加密载荷→pending 行，fail-safe）+ `list_serving` + `ai_trace.py` 旁路挂载 + 15 测试。**子块 B-2**（Celery 执行器）：`shadow_executor.py`（认领→生成→检测→轻判→复评→六分类→结算 + 预算 settle/release + 载荷删除，重试/死信降级）+ `experiment_tasks.py` 薄壳 + beat 每 5 分钟轮询 + 12 测试。`EXPERIMENT_ENABLED` 默认关闭全惰性 | shadow 全链路打通（不占请求路径，不返回给用户） |
| 7 ✅ | **四层校准**：按全局 → 题材 → 策略族 → 挑战者逐层积累样本完成判定器校准（§3.4）。已落地 `layered_calibration.py`（分层聚合 + 四层门槛 + 四层全过解锁 + `shadow → eligible` 推进）+ `ExperimentRepository.list_settlement_samples`（联表取本策略版本已结算样本）+ `ChallengerRepository.update_serving_mode`（`assert_transition` 校验）+ `run_calibration_task` 薄壳 + beat 每 30 分钟轮询 + 18 测试 | 无（eligible 不参与返回） |
| 8 ✅ | **returnable 开闸**：人工批准少量挑战者进入低 ε（5%）returnable，双路并行 + 硬门槛 + margin 择优，逐级放量。**子块 A**（择优核心）：`returnable_service.py`（ε 分桶域分离 / 熔断 / 决策链短路回退 / 双路 best-of-2 择优，async 依赖注入）+ 17 测试。**子块 B**（命中落库回流）：`persist_returnable_experiment`（命中复用实验行落 pending + 预置双路结果加密载荷，预算分离）+ `shadow_executor` 预置分支（跳过重复生成只补异步复评）+ 10 测试。**子块 C**（reduce 端点挂载）：`returnable_reduce` 编排层 + `ai_trace.py` 真实装配（`_rewrite_text` + 腾讯检测）+ `ReduceResponse.returned_variant` 字段 + fail-safe 双保险 + 4 测试。**四轮评审补齐（§13 #9/#10）**：人工开闸管理端点 `POST /challengers/{challenger_id}/returnable`（服务层 `approve_returnable`，打通 eligible→returnable 生产链路）+ 熔断窗口化（returnable 场景 168h 滚动窗口 + 最小有效样本门槛）。`EXPERIMENT_ENABLED` 默认关闭全惰性 | ai-trace 实验组开始拿到择优结果 |
| 9 ✅ | **晋升闭环**：硬闸门 + 晋升推荐 + champion 原子切换 + 秒级回滚（§8）。**子块 A**（统计门槛）：`promotion.py`（Wilson 下界 + `aggregate_challenger_stats` 复用 `compute_replay_consistency` 口径一致 + 硬闸门/推荐指标评估）+ 20 测试。**子块 B**（原子切换回滚）：`champion_assignment_repository.py`（指针关旧开新，只 flush 不 commit）+ `champion_promotion.py`（returnable 校验 → 硬闸门 → 同事务切指针 + serving_mode 推进 + 旧冠军降级；秒级回滚以指针表为权威）+ `ExperimentRepository.list_outcomes_for_challenger` + 13 测试。**子块 C**（管理员 API）：`prompt_evolution.py` 新增 `GET /champion/recommendation` + `POST /champion/promote` + `POST /champion/rollback`（均 `require_admin`，硬闸门不信任客户端）+ 11 测试 | 冠军更替 |
| 10 ✅ | **启停调度 + 面板**：休眠/唤醒调度器（§11）、管理观测面板。**子块 A**（纯逻辑）：`evolution_scheduler.py`（三态 + 休眠 AND 门槛 / 唤醒 OR 门槛 / 滞回按当前态只判一侧 / 状态转移）+ 26 测试。**子块 B**（信号采集落盘 beat）：`scheduler_state.py`（三态原子落盘）+ `scheduler_orchestration.py`（跨批次提升 / 挑战者反超 / 预算触顶真实采集，其余中性默认）+ `experiment_tasks.py` 薄壳 + beat 每 60 分钟轮询 + 18 测试。**子块 C**（管理面板 API）：`prompt_evolution.py` 新增 `GET /scheduler/state` + `POST /scheduler/sleep` + `POST /scheduler/wake`（均 `require_admin`）+ 11 测试 | 进化费用下降，退化自动唤醒 |

> v1 顺序缺陷（已修正）：①预算与熔断晚于 shadow——无原子账本时并发可超发，现提前至步骤 3/6 同期；②同步判定器排在 returnable 阶段实现，与"shadow 校准判定器"目标自相矛盾，现提前至步骤 5。
>
> 测试数量口径：文中各步骤的测试用例数为**交付时点快照**，后续评审修复批次持续新增/改造用例，当前权威数量以 `pytest` 对 prompt_evolution 相关测试文件的实际收集结果为准。

## 15. 配置项清单（与代码实名对齐，2026-07-25 四轮评审修订）

### 15.1 环境变量（代码真实消费，名称与默认值逐一核对）

| 环境变量 | 默认值 | 语义（消费模块） |
|---|---|---|
| `EXPERIMENT_ENABLED` | false | 总开关，关闭全惰性（shadow_dispatch / returnable_service / experiment_tasks） |
| `EXPERIMENT_EPSILON_SHADOW` | 0.0 | shadow 分流比例（shadow_dispatch；预算反推建议 0.3） |
| `EXPERIMENT_EPSILON_RETURNABLE` | 0.0 | returnable 阶梯当前值（returnable_service；0.05 起步） |
| `EXPERIMENT_MARGIN_THRESHOLD` | 5.0 | 择优返回所需排序分领先幅度（returnable_service；须为有限非负数，七轮修复①） |
| `EXPERIMENT_AI_SCORE_THRESHOLD` | 25.0 | 硬门槛 AI 分上限（returnable_service / experiment_tasks；须为有限数且在 [0,100]，七轮修复①；shadow/returnable 共用 `parse_ai_threshold` 单一解析校验，八轮修复①） |
| `EXPERIMENT_INVALIDATED_RATE_MAX` | 0.05 | 判定器作废率上限（returnable_service 熔断 / layered_calibration 校准） |
| `EXPERIMENT_CIRCUIT_WINDOW_HOURS` | 168 | 熔断滚动窗口小时数，§5.4 七日（returnable_service，四轮修复②新增） |
| `EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES` | 200 | 熔断成熟期有效样本门槛，未达时走预热期双层规则（returnable_service，四轮修复②新增，五轮修复②修订语义） |
| `EXPERIMENT_CIRCUIT_WARMUP_MIN_SAMPLES` | 20 | 熔断预热期最小有效样本，低于则证据不足不熔断（returnable_service，五轮修复②新增；**须严格小于 `EXPERIMENT_CIRCUIT_MIN_EFFECTIVE_SAMPLES`，否则预热区间为空、失败关闭，七轮修复②**；**默认值为评审建议初值，上线前按业务风险复核**） |
| `EXPERIMENT_CIRCUIT_WARMUP_INVALIDATED_RATE_MAX` | 0.20 | 熔断预热期作废率上限，越限即熔断（returnable_service，五轮修复②新增；**默认值为评审建议初值，上线前按业务风险复核**） |
| `EXPERIMENT_BUCKET_SECRET` | 空 | HMAC 分桶密钥，缺失时失败关闭（shadow_dispatch / returnable_service） |
| `EXPERIMENT_PAYLOAD_KEY` | 空 | 原文载荷加密密钥，缺失时 PayloadVault 失败关闭（shadow_dispatch / returnable_service） |
| `EXPERIMENT_PAYLOAD_TTL` | 86400 | 原文载荷保留秒数（shadow_dispatch / returnable_service） |
| `EXPERIMENT_ESTIMATED_COST` | 0.01 | 单实验预估成本，预算预留额（shadow_dispatch） |
| `EXPERIMENT_DAILY_BUDGET_CALLS` / `_COST` / `_PER_GENRE` / `_PER_CHALLENGER` / `_PER_USER_FREQ` | 未设不启用 | 四维日预算上限（shadow_dispatch / budget_ledger） |
| `EXPERIMENT_MAX_ATTEMPTS` | 3 | 实验任务最大重试次数（experiment_tasks；须为 >= 1 的整数，经 `parse_max_attempts` 校验失败关闭，九轮修复） |
| `CALIBRATION_MIN_SAMPLES_GLOBAL` / `_GENRE` / `_FAMILY` / `_CHALLENGER` | 200 / 50 / 30 / 20 | 四层校准最小样本（layered_calibration） |
| `PROMOTION_MIN_EFFECTIVE_SAMPLES` | 100 | 晋升硬闸门最小有效样本（promotion） |
| `PROMOTION_MAX_HARD_FAIL_RATE` | 0.01 | 硬闸门硬失败率上限（promotion） |
| `PROMOTION_MIN_WILSON_LOWER_BOUND` | 0.50 | 硬闸门 Wilson 胜率下界（promotion） |
| `PROMOTION_MAX_INVALIDATION_RATE` | 0.05 | 硬闸门作废率上限（promotion） |
| `PROMOTION_MIN_WIN_RATE` | 0.60 | 推荐指标最低胜率（promotion） |
| `PROMOTION_WILSON_Z` | 1.96 | Wilson 置信 z 值，95%；小流量期可放宽 1.645（promotion） |
| `EVOLUTION_CONVERGENCE_BATCHES` | 3 | 休眠门槛：连续考察批次数（evolution_scheduler） |
| `EVOLUTION_MIN_BATCH_IMPROVEMENT` | 2.0 | 休眠门槛：每批最佳提升下限（evolution_scheduler） |
| `EVOLUTION_MAX_HOLDOUT_SCORE_GAP` | 5.0 | 休眠门槛：holdout 复评分差上限（evolution_scheduler） |
| `EVOLUTION_WAKE_AI_SCORE_RISE` | 8.0 | 唤醒门槛：冠军 AI 率回升幅度（evolution_scheduler） |
| `EVOLUTION_WAKE_FIDELITY_DROP` | 5.0 | 唤醒门槛：冠军保真下降幅度（evolution_scheduler） |
| `EVOLUTION_WAKE_CHALLENGER_WILSON` | 0.55 | 唤醒门槛：挑战者 Wilson 下界反超线（evolution_scheduler） |

### 15.2 设计预留（文档定义、代码尚未消费——实施时须先接线再依赖）

| 配置项 | 设计值 | 说明 |
|---|---|---|
| `EXPERIMENT_CHALLENGER_TIMEOUT` | 120s | 挑战者独立超时（§5.5）；当前执行器未读取该变量 |
| `EXPERIMENT_OVERALL_DEADLINE` | 200s | 请求级总超时（§5.5）；当前请求路径未读取该变量 |

### 15.3 结构常量（模块常量而非环境变量，改动即代码变更须走测试）

| 常量 | 值 | 位置 / 语义 |
|---|---|---|
| `EXPERIMENT_EVALUATION_POLICY_VERSION` | `experiment-policy-v1` | experiment_contract；样本统计不跨策略版本消费 |
| `LIGHT_JUDGE_VERSION` | `light-judge-v1` | experiment_contract；轻判定器版本指纹 |
| `EVOLUTION_GENRES` | 七题材列表 | experiment_contract；题材单一定义点（§13 #6①） |
| `HOLDOUT_GAP_MAX_AGE_HOURS` | 48 | holdout_probe；留出复评缓存 TTL（2× 每日 beat 周期） |
| `SENTINEL_STATE_MAX_AGE_HOURS` | 24 | sentinel_probe；哨兵巡检缓存 TTL（2× 12h beat 周期） |
| `replay_calibration.DEFAULT_MIN_SAMPLES` | 200 | 作废率统计可信门槛；熔断最小样本门槛默认复用同值 |

---

## 附录 A：被否决方案清单（防止实施走回头路）

- "用户永远拿到较优结果"的宣称——同步轻量判定不能识别微妙语义漂移，风险边界见 §3.3；
- "统一 ε=20% 直接上线""在线实时生成变体""AI 率单指标择优""第一版自动晋升""提示词与模型同时实验"；
- shadow 阶段"双路并行等待后仍返回冠军"——改为完全脱离请求路径的持久后台任务；
- **裸 `asyncio.create_task` 作为实验基础设施**——改为 DB 任务表 + 租约 + Celery 执行器；
- **"判定器整体达标一次性解锁所有挑战者"**——统计过度外推，改为四层校准门槛（§3.4）；
- **两路统一改用 `get_active_model_id(genre)`**——与 ai_trace 实际的 prompt-model 联合选择冲突，改为解析一次冻结共享（§4.1）；
- **Python `hash()` 分桶**——进程盐不可复现，改为 HMAC-SHA256；
- **JSON 覆盖写作为在线实验账本**——改为数据库表 + 事务 + 唯一约束（v2 定稿时四表，现为五张核心表，见 §6.1）；
- **中文专名启发式作硬门槛**——误判率高，降级为排序信号 + 告警。

## 附录 B：v1 → v2 修订记录

| 修订 | 类型 | 位置 |
|---|---|---|
| 在线模型解析事实纠错 + 模型冻结契约 | 事实错误修正 | §2、§4.1 |
| 判定器校准出口改为四层门槛 | 统计缺陷修正 | §3.4 |
| shadow 持久任务（任务表 + 租约 + 一致性分级） | 基础设施修正 | §5.2 |
| 数据库账本四表 + 唯一约束（后增至五表，见 §6.1） | 基础设施修正 | §6 |
| HMAC-SHA256 确定性分桶 | 实现陷阱修正 | §4.2 |
| 超时/取消/降级决策表 + overall deadline | 语义补全 | §5.5 |
| 预算与熔断提前至 shadow 之前 | 顺序修正 | §9、§14 |
| 晋升硬闸门/推荐指标两分法 + 原子指针切换 | 治理修正 | §8 |
| 实验 schema 补九个版本字段 + 统计窗口规则 | 可比性修正 | §4.3、§7.2 |
| 中文专名启发式降级为排序信号 | 判定精度修正 | §5.3 |
| 同步判定器提前至 shadow 之前实现 + 离线回放预热 | 顺序矛盾修正 | §14 步骤 5 |
| 隐私覆盖原文全生命周期（opt-in、opaque reference、TTL、供应商条款） | 合规补全 | §10 |
