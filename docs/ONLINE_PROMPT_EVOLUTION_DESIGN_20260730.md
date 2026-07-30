# 提示词在线进化服务设计 v2（Champion/Challenger 双路体系 + 进化自动启停）

> 状态：设计定稿 v2，未实施（2026-07-30）
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

## 4. 实验契约冻结（v2 新增章节，实施第一步）

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

### 5.2 shadow 阶段：持久任务成对实验（v2 修正：禁止裸 fire-and-forget）

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

## 6. 存储与账本（v2 新增章节：数据库为权威，禁用 JSON 覆盖写）

`EvolutionStorage` 的普通 JSON 读写不能承载在线实验：多 worker 互相覆盖、复评晚到重复结算、状态转换无原子性、预算并发超发、晋升读不到一致快照、写一半进程退出损坏文件。`AtomicJsonStore`（ai_trace_competition.py）可作为本地配置/低并发统计的过渡，**不作为多实例在线实验权威账本**。

### 6.1 表结构（SQLAlchemy + Alembic，四张起步）

| 表 | 职责 | 说明 |
|---|---|---|
| `prompt_challengers` | 挑战者池（§3.1 schema + serving_mode 状态机） | |
| `prompt_experiments` | 实验任务 + 成对结果 + 异步复评结果 | 任务字段（§5.2）与复评结果合并为一行（一对一），四段状态机在此表推进 |
| `prompt_experiment_budgets` | 预算账本 | 含未结算任务的预留成本字段，幂等扣减、失败释放 |
| `prompt_champion_assignments` | 冠军指针历史（带生效区间） | 每行即审计记录，合并 audit_logs 职责；提示词内容仍在 EvolutionStorage，本表只存指针+哈希 |

字段稳定后按需拆表（拆分低成本，反向合并痛苦）。

### 6.2 关键约束

- 实验表唯一约束：`(request_id, challenger_id, evaluation_policy_version)` —— 防复评晚到重复结算，也是"至少一次执行"的幂等基础；
- `provisional_win → confirmed_win / invalidated_win` 状态转换在事务内完成；
- 预算扣减与任务创建同事务；结算与状态转换同事务。

## 7. 异步权威评审与统计体系

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

## 9. 成本模型与实验预算（v2：预算先于 shadow 上线）

```
增量成本 = ε × ( 挑战者生成 + 挑战者AI检测 + 异步完整评审(可能多次LLM调用)
              + 重试期望成本 + 供应商长尾超时重复调用 )
```

shadow 请求虽不返回挑战者，成本照付。**没有原子预算账本前禁止开启 shadow**——ε 再低也挡不住并发超发，这是账本问题不是比例问题。

预算账本（`prompt_experiment_budgets`）维度：全局日预算（调用数 + 费用）、按题材预算、单挑战者预算、**单用户实验频率上限**、未结算任务预留成本、供应商连续超时/错误率熔断、幂等扣减与失败释放。预算耗尽自动 ε=0。

## 10. 隐私与原文生命周期（v2 补全：覆盖异步任务全程）

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

## 12. 场景分层策略

| 场景 | 特征 | 策略 |
|---|---|---|
| 织文无迹 /ai-trace | **人在环**：用户在屏幕前审阅结果，不满意可重跑，单次漂移伤害被人工兜底 | 先行开放 returnable 择优返回 |
| 灵感方舟正文生成 | 无人值守，结果直接入库 | 维持保守：仅 shadow 采数据，择优返回待 ai-trace 验证成熟后评估 |

## 13. 遗留技术债（实施前/中顺带处理）

1. `engine._failed_variants` 进程内 dict，重启失忆——落盘后才能承担离线准入第 7 条职责；
2. `novel_rules.SENTENCE_PATTERN_FIXES` 全仓无消费点，死配置——删除或接入 `postprocess_text`；
3. 离线样本池过拟合——建立留出集（holdout），进化停止与休眠判定均用新鲜样本复核；
4. 极端评分告警——"原始 99 → 改写后 0"类分数触发过度改写复查而非直接采信。

## 14. 实施顺序 v2（十步，分步执行、每步完成后确认再推进）

| 步骤 | 内容 | 用户可见影响 |
|---|---|---|
| 1 | **冻结实验契约**：模型解析冻结、生成参数、HMAC 分桶、评审版本体系、状态机定义（§4） | 无（设计产出） |
| 2 | **隐私规则**：用户授权位、原文短期载荷加密/TTL/删除/日志规则（§10） | 无 |
| 3 | **持久化底座**：实验任务表、实验账本、预算账本、assignment 审计表（Alembic 迁移，§6） | 无 |
| 4 | **挑战者池**：接入离线七项准入（含 `_failed_variants` 落盘），生成带版本与内容哈希的 Challenger Pool | 无 |
| 5 | **判定器先行**：完整实现同步轻量判定器 + 异步权威评审，**先用离线回放样本验证一致率**（进化历史三元组回放，上线前预热第 1 层校准） | 无 |
| 6 | **shadow 上线**：持久任务 + 原子预算 + 供应商熔断 + 任务重试同时启用，禁止裸 fire-and-forget | 无（不占请求路径） |
| 7 | **四层校准**：按全局 → 题材 → 策略族 → 挑战者逐层积累样本完成判定器校准（§3.4） | 无 |
| 8 | **returnable 开闸**：人工批准少量挑战者进入低 ε（5%）returnable，双路并行 + 硬门槛 + margin 择优，逐级放量 | ai-trace 实验组开始拿到择优结果 |
| 9 | **晋升闭环**：硬闸门 + 晋升推荐 + champion 原子切换 + 秒级回滚（§8） | 冠军更替 |
| 10 | **启停调度 + 面板**：休眠/唤醒调度器（§11）、管理观测面板 | 进化费用下降，退化自动唤醒 |

> v1 顺序缺陷（已修正）：①预算与熔断晚于 shadow——无原子账本时并发可超发，现提前至步骤 3/6 同期；②同步判定器排在 returnable 阶段实现，与"shadow 校准判定器"目标自相矛盾，现提前至步骤 5。

## 15. 配置项清单（全部可配，不写死）

```
EXPERIMENT_ENABLED                     默认 false，总开关
EXPERIMENT_EPSILON_SHADOW              shadow 分流比例（预算反推，建议 0.3）
EXPERIMENT_EPSILON_RETURNABLE          returnable 阶梯当前值（0.05 起步）
EXPERIMENT_MARGIN_THRESHOLD            择优返回所需排序分领先幅度
EXPERIMENT_INVALIDATED_RATE_MAX        判定器作废率熔断线（0.05）
EXPERIMENT_CHALLENGER_TIMEOUT          挑战者独立超时（120s）
EXPERIMENT_OVERALL_DEADLINE            请求级总超时（200s）
EXPERIMENT_BUCKET_SECRET               HMAC 分桶密钥
EXPERIMENT_PAYLOAD_TTL                 原文载荷保留时长
EXPERIMENT_DAILY_BUDGET_CALLS / _COST / _PER_GENRE / _PER_CHALLENGER / _PER_USER_FREQ
CALIBRATION_MIN_SAMPLES_GLOBAL / _GENRE / _FAMILY / _CHALLENGER   四层校准最小样本（200/50/30/20）
PROMOTION_MIN_SAMPLES / _WIN_RATE / _CI_LEVEL / _HARD_FAIL_MAX
EVOLUTION_SLEEP_* / EVOLUTION_WAKE_*   休眠/唤醒阈值组（滞回成对配置）
```

---

## 附录 A：被否决方案清单（防止实施走回头路）

- "用户永远拿到较优结果"的宣称——同步轻量判定不能识别微妙语义漂移，风险边界见 §3.3；
- "统一 ε=20% 直接上线""在线实时生成变体""AI 率单指标择优""第一版自动晋升""提示词与模型同时实验"；
- shadow 阶段"双路并行等待后仍返回冠军"——改为完全脱离请求路径的持久后台任务；
- **裸 `asyncio.create_task` 作为实验基础设施**——改为 DB 任务表 + 租约 + Celery 执行器；
- **"判定器整体达标一次性解锁所有挑战者"**——统计过度外推，改为四层校准门槛（§3.4）；
- **两路统一改用 `get_active_model_id(genre)`**——与 ai_trace 实际的 prompt-model 联合选择冲突，改为解析一次冻结共享（§4.1）；
- **Python `hash()` 分桶**——进程盐不可复现，改为 HMAC-SHA256；
- **JSON 覆盖写作为在线实验账本**——改为数据库四表 + 事务 + 唯一约束；
- **中文专名启发式作硬门槛**——误判率高，降级为排序信号 + 告警。

## 附录 B：v1 → v2 修订记录

| 修订 | 类型 | 位置 |
|---|---|---|
| 在线模型解析事实纠错 + 模型冻结契约 | 事实错误修正 | §2、§4.1 |
| 判定器校准出口改为四层门槛 | 统计缺陷修正 | §3.4 |
| shadow 持久任务（任务表 + 租约 + 一致性分级） | 基础设施修正 | §5.2 |
| 数据库账本四表 + 唯一约束 | 基础设施修正 | §6 |
| HMAC-SHA256 确定性分桶 | 实现陷阱修正 | §4.2 |
| 超时/取消/降级决策表 + overall deadline | 语义补全 | §5.5 |
| 预算与熔断提前至 shadow 之前 | 顺序修正 | §9、§14 |
| 晋升硬闸门/推荐指标两分法 + 原子指针切换 | 治理修正 | §8 |
| 实验 schema 补九个版本字段 + 统计窗口规则 | 可比性修正 | §4.3、§7.2 |
| 中文专名启发式降级为排序信号 | 判定精度修正 | §5.3 |
| 同步判定器提前至 shadow 之前实现 + 离线回放预热 | 顺序矛盾修正 | §14 步骤 5 |
| 隐私覆盖原文全生命周期（opt-in、opaque reference、TTL、供应商条款） | 合规补全 | §10 |
