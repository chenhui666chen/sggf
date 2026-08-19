# 协同扩展模式内容质量风险与修复方案

- 日期：2026-08-17（2026-08-18 增补：服务端实测 + 风险 4 修复）
- 范围：`backend/app/services/story_expansion_coord_pkg/`（协同扩展协调器）+ `backend/app/services/agents/outline_expansion/_incrementalexpansion.py`（扩展执行器）+ `backend/app/services/agents/character_plot_validator.py`（对齐验证器）+ `backend/app/api/v1/workflow/routes_expand.py`（路由层）
- 关联测试：`backend/tests/test_story_expansion_full_flow.py`（协同扩展全流程离线集成测试，10 项）
- 状态：四项修复已实施；风险 1/2/4 已通过服务端真实调用验证，风险 3 为离线验证（2026-08-18）

> **实施记录（2026-08-17）**
> - 修复 1（delta 分批）：`_execution_mixin.py` 新增 `_split_delta_chapter_batches` / `_summarize_generated_chapter_dicts`，`_generate_new_chapters_for_op` 改为批循环，批间注入前批摘要（标题+关键事件+钩子）与"延续冲突梯度、禁止雷同"指令；常量 `DELTA_CHAPTER_BATCH_MAX_PER_CALL = 4`
> - 修复 2（对齐闸门）：`_base.py` 新增 `_alignment_gate_should_retry` / `_format_alignment_issue_brief` / `_apply_alignment_gate`；`_alignment_mixin.py` 新增 `_generate_alignment_repair_patch`（增量补丁：缺失人物卡/章节职责行/关系补丁，只增不改）与 `_apply_alignment_repair_patch`；`execute()` 后处理接线。结果新增 `alignment_gate_status`（passed/repaired/failed_after_retry）与 `alignment_gate_retry`
> - 修复 3（epic 两段）：`_incrementalexpansion.py` 的 `generate_epic_framework` 在卷数 ≥ 6 时拆两段（骨架 → 伏笔表+人物生命周期），第二段以第一段骨架为硬约束；卷数校验失败增加 warning 日志（兜底前后各一处）
> - 验证：批拆分(4/5/8/9/10/12/25)、批间衔接、闸门三状态+异常非阻塞、补丁应用精度(含第12/120章干扰与不存在章节忽略)、epic 两段/单段分流全部断言通过；`test_story_expansion_full_flow.py` + `test_iteration_agent_prompt_bindings.py` 共 10 项回归通过

> **实施记录（2026-08-18）：服务端实测 + 风险 4（见第七节）**
> - 实测发现的配套缺陷修复（详见 7.3）：
>   - 章节卡 JSON 截断抢救：`_base.py` 新增 `_invoke_chapter_json`（按章数动态预算 + `response_format=json_object` 禁思考模式）与 `_salvage_truncated_chapter_json`（括号配对回收尾部截断前的完整章节卡）；`_execution_mixin.py` 批内失败即时重试 1 次
>   - validator 模型路由：`character_plot_validator.py` 支持注入模型，`_base.py` 复用扩展运行时已验证的 planner 模型（修复 default 任务模型无 Key 时闸门静默失效）
>   - validator 解析容错：评分/章节标题正则容忍粗体（`**总分** **:** **78分**`）、编号标题（`## 1. 冗余人物`）、圆点列表变体
>   - 响应序列化透传：`routes_expand.py` 白名单序列化曾丢弃 `alignment_gate_status` 等字段（闸门实际已运行但状态不可见），`schemas/story_expansion.py` 补齐 4 字段
> - 风险 4 修复（结构债跨轮承接，详见第七节）：新增 `deferred` 状态与 `alignment_structural_debt` 字段、修复器问题分类、人物覆盖约束与批间戏份提示
> - 服务端实测：项目 101 真实调用 5 轮，覆盖批次拆分（[3,3]/[4,3]/[1]）、闸门四状态（passed/failed_after_retry/deferred/债务清空）、结构债跨轮闭环（deferred 落库 → 下轮加载注入 → 新章精准承接）；离线测试 10 项全过

---

## 一、背景

协同扩展系统提供 4 种扩展模式（delta 单轮增量 / iterative 分轮迭代 / epic 长篇框架 / volume_detail 单卷细化）。经对执行链路的代码审查与离线集成测试验证，各模式的**逻辑一致性保障**（锁定旧内容、锚点衔接、卷间摘要承接、伏笔三段式、对齐修复）是完备的；但在**内容生成质量**层面存在 3 个可识别的"稀释风险点"——即随生成规模增大，单章/单卷字段质量趋于稀释、套路化的系统性风险。

### 各模式质量能力基线（修复前）

| 模式 | 逻辑保障机制 | 质量评级 |
|---|---|---|
| volume_detail（单卷细化） | 上一卷摘要承接 + 待处理伏笔清单 + 全书核心主线约束 + 框架头/尾约束 + 大卷自动分段生成 + 卷末交接检查 + 按卷规模选模型（plus/r1） | A |
| epic（长篇框架） | 总纲→阶段路线图→力量成长线→分卷→全书伏笔表（埋设/铺垫/回收）→人物生命周期表 + 滚动细化防漂移策略 | A-（框架层） |
| iterative（分轮迭代） | 大纲+人物交替推进，轮间 `evaluate_story_coordination` 校验，空转停止保护 + 尾差补章 | B+ |
| delta（单轮增量） | 计划→人物→大纲三段式，锚点章+后继章上下文，插入式扩展衔接要求，LLM 对齐验证（2026-08-17 接入） | B |

---

## 二、三个稀释风险点

### 风险 1：delta 模式一次性生成稀释（影响最大）

**位置**：`story_expansion_coord_pkg/_execution_mixin.py` → `_generate_new_chapters_for_op()`（L399-L448）

**现象**：delta 计划层 `outline_ops` 的 `count` 由 LLM 自定（无上限约束）。一次要 8-10 章时，所有章节卡在**单次 JSON 调用**里产出。章数越多，单章字段质量越稀释：
- 冲突设计趋同（"①障碍→②升级→③爆发"模板复读）
- 结尾钩子套路化（悬念/危机/反转三选一轮转）
- `character_progress`、`plot_function` 等结构职责字段退化为情绪描述

**对照**：volume_detail 模式对大卷已做分段生成（`_story_should_chunk_volume_detail`），delta 缺少同等机制——这是同系统内的保护不一致。

**修复方案**：delta 分批生成
- `_generate_new_chapters_for_op()` 内对 `count > 4` 的操作按 3-4 章/批拆分为多次 `_invoke_json` 调用
- 批间携带已生成批次的章节标题+关键事件摘要作为衔接上下文（保持冲突升级梯度与钩子递进）
- 批次结果合并后再进入现有的 `parse_outline_blocks` → 锚点插入流程，对外接口不变
- 预期改动量：仅 `_generate_new_chapters_for_op()` 内部，约 40-60 行

### 风险 2：对齐验证是"告警"而非"闸门"

**位置**：`story_expansion_coord_pkg/_base.py` → `_run_character_plot_alignment_validation()` / `_merge_character_plot_alignment_into_result()`；`_execution_mixin.py` → `execute()` 统一后处理（2026-08-17 接入）

**现象**：LLM 级人物-情节对齐验证结果（`character_plot_alignment`，含评分/冗余人物/缺失人物/关系问题）评分 < 60 时只追加告警文本到 `coordination_summary` 与 `alignment_warnings`，**不会触发自动重做**。低分结果照常落库，依赖用户看到告警后手动再扩一次。

同理，规则级 `alignment_repairs`（名字级自动修复）只能救"人物没出场"，救不了"人物出场但对情节无推动"——后者只有闸门能拦截。

**修复方案**：验证升级为闸门 + 有限自动重跑
- `execute()` 后处理中：`score < 50` 或（冗余 + 缺失合计 ≥ 3 项）时，自动重跑一次人物-大纲协同（把首轮对齐问题清单注入重跑 prompt 作为修正指令）
- 重跑仍低分才放行，并在结果中显著标记（`alignment_gate_status: "failed_after_retry"`）
- 重跑上限 1 次，防止成本失控与循环震荡
- 预期改动量：`execute()` 后处理 + 重跑 prompt 构造，约 60-80 行

### 风险 3：epic 框架单次 JSON 负载过重

**位置**：`agents/outline_expansion/_incrementalexpansion.py` → `generate_epic_framework()`（L655-L768）

**现象**：10 卷以上的长篇框架要求单次 JSON 返回全部内容：故事定位 + 阶段路线图 + 力量成长线 + 全部卷条目 + 全书伏笔表 + 人物生命周期表。风险有二：
- JSON 越长，卷与卷之间的**梯度逻辑**（冲突升级是否成立、阶段收束标记是否递进）越容易糊掉
- 解析失败静默 fallback 到 `{"volumes": []}`，框架为空时下游只能拿原文兜底，无告警

**修复方案**：epic 分两段生成
- 第一段：故事定位 + 阶段路线图 + 力量成长线 + 全部卷条目（结构性骨架）
- 第二段：以第一段骨架为约束上下文，生成全书伏笔表 + 人物生命周期表（依附性细节）
- 两段合并为完整框架 JSON；`volumes` 数量校验失败时至少 warning 级日志（不再静默）
- 预期改动量：`generate_epic_framework()` 拆分，约 50-70 行

---

## 三、修复优先级与实施顺序

| 顺序 | 项 | 理由 | 依赖 |
|---|---|---|---|
| 1 | 风险 1（delta 分批） | 改动最小、直接消除最常见的质量稀释入口（delta 是默认模式） | 无 |
| 2 | 风险 2（验证闸门） | 把已有验证资产从"可看"升级为"可用"，闭环质量防线 | 无（与 1 并行可做） |
| 3 | 风险 3（epic 分段） | 框架层风险暴露频率低于 delta，但影响全书结构 | 建议在 1、2 验证后实施 |

三项修复均在协调器/执行器内部完成，**不改变对外接口**（`execute()` 签名、返回结构仅新增可选字段），前端与路由层无需适配。

## 四、验收标准

1. **风险 1**：`count=8` 的 outline_op 分批生成后，各章 `conflict_design` 无跨章雷同（人工抽检 + 相似度抽检），钩子类型分布不呈现机械轮转；单批调用章数 ≤ 4
2. **风险 2**：构造 score<50 的对齐结果（可在集成测试中脚本化），断言触发重跑且重跑 prompt 含首轮问题清单；重跑上限 1 次；高分结果零额外调用
3. **风险 3**：10 卷以上框架生成拆为 2 次调用，第二段 prompt 含第一段骨架；`volumes` 数量不符时日志可见告警
4. 全量回归：`test_story_expansion_full_flow.py`（2 项）+ `test_iteration_agent_prompt_bindings.py`（8 项）通过

## 五、不变式（修复期间必须保持）

- delta 锁定旧内容：只增不重写，已有章节视为锁定
- 分批/分段生成的合并结果仍需通过 `parse_outline_blocks` 解析与锚点插入校验
- 对齐验证保持非阻塞语义的兜底路径（无 Key/调用失败时返回 None，不影响扩展结果本身）
- `character_plot_alignment` 字段结构（score/redundant_characters/missing_characters/relationship_issues/suggestions）不变更，仅新增可选的 `alignment_gate_status`

## 六、关联资产

- 集成测试（离线确定性，LLM 边界脚本化）：`backend/tests/test_story_expansion_full_flow.py`
- 人物卡归档单测：`backend/tests/test_character_archive_orphans.py`
- 人物卡软归档迁移：`backend/alembic/versions/add_character_source_and_archived_at.py`
- 人物弧光锚点系统定案（规划期报人物成长线缺口，架构级）：`docs/CHARACTER_ARC_ANCHOR_DESIGN_20260818.md`
- 对齐验证器：`backend/app/services/agents/character_plot_validator.py`
- 本轮已完成的配套改动（2026-08-17）：
  - 上下文预算扩容（世界观 2500→8000 / 大纲 5000→20000 / 人物 4000→12000 字符），适配 1M 上下文档位模型
  - LLM 人物-情节对齐验证接入 `execute()` 统一后处理（4 种模式全覆盖）
  - 高潮指示大纲节奏驱动化（`chapter_planning.get_climax_instruction`），取模节奏仅作无细纲兜底

---

## 七、增补（2026-08-18）：风险 4 —— 情节级问题不可修复导致 failed_after_retry 成为终态死胡同

### 7.1 风险描述

**位置**：`story_expansion_coord_pkg/_alignment_mixin.py` → `_generate_alignment_repair_patch()`；`_base.py` → `_apply_alignment_gate()`

**现象**：修复补丁只允许三类**注记级**增量（缺失人物卡 / 章节职责补充行 / 关系补丁），但真实项目（101《窃天者：星轨残篇》）的对齐失败问题多为**情节结构级**：

| 问题类型 | 典型样本 | 注记级补丁能否解决 |
|---|---|---|
| 人物弧光缺失 | 苏婉儿（查父母死因→毒医→地下医疗网）需跨多章主动行动线 | 否——一行"人物职责补充"不构成情节点，复验必仍失败 |
| 冗余人物 | 夜枭设定为关键情报角色但存在感低，需与主角建立利益/情感纠葛 | 否——需要实质互动情节 |
| 转变铺垫不足 | 萧铁衣从"誓杀主角"到"倒戈合作"缺渐进过程 | 否——需多章铺垫 |
| 缺失承载人物 | 需要"皇子反派"具象化朝堂博弈 | 加卡反而恶化（新增未引用人物），需承载其功能的情节节点 |

后果：修复+复验两次 LLM 调用注定失败，白白消耗成本；`failed_after_retry` 成为终态死胡同，问题永远无法闭环。

### 7.2 修复方案：三层组合

**层 1 —— 结构债跨轮承接（核心）**

`failed_after_retry` 不再是终态。情节级问题持久化为"结构债"（`alignment_structural_debt` 字段，随扩展结果存入 `generation_history`），**下一轮扩展的章节卡生成 prompt 自动注入**，由新增章节实质承接——完全兼容 delta 锁定语义（不改旧章，新章兑现）。

- `routes_expand.py` → `_load_structural_debt_from_history()`：发起扩展时回溯最近 5 条已完成记录读取最新非空债务（验证器不可用的轮次不写该字段，向前回溯避免误清），传入 `execute(structural_debt=...)`
- `_execution_mixin.py`：两条 delta 生成路径（有/无章节大纲）的每批 prompt 注入【上轮遗留结构债】段
- 债务生命周期：本轮 gate 验证可用即显式重置为空（`passed` 时清空，最新状态覆盖存储，旧债不残留）

**层 2 —— 修复器问题分类（省无效成本）**

修复 prompt 先区分问题层级：注记级（可补丁）才生成补丁；情节级原样列入 `plot_level_issues`。

状态机升级（`alignment_gate_status` 新增 `deferred`）：
- 全部情节级 / 修复器无可补输出 → `deferred` + 问题清单写入结构债，**跳过注定失败的修复+复验调用**（省 2 次 LLM 调用）
- 注记级 + 情节级混合 → 正常补丁→复验流程，情节级债仍记录
- 修复器全空输出（真实环境观察到）→ 保守兜底：首验问题清单整体转结构债

**层 3 —— 生成时人物覆盖约束（预防优于修复）**

- 每批章节卡 prompt 增加【人物覆盖约束】：`involved_characters` 中人物必须有实质行动；主要人物轮转出场，单人不得连续缺席超 2 章
- `_build_character_presence_hint()`：批间统计已生成章节的人物出场率，零出场人物在下一批 prompt 中强制补戏

三层关系：层 3 压降发生率 → 层 2 省掉无效成本 → 层 1 兜底承接存量债。

### 7.3 实测中发现的配套缺陷（已修复）

| # | 缺陷 | 现象 | 修复 |
|---|---|---|---|
| 1 | 思考模型挤占输出预算 | deepseek-v4-pro `thinking: enabled` 导致章节卡 JSON 尾部截断，整批解析失败 | `_invoke_chapter_json`：按章数动态预算 + `response_format={"type": "json_object"}` 自动禁思考 |
| 2 | 截断即整批丢弃 | 尾部截断的 JSON 中前几章卡完整，却被整体丢弃 | `_salvage_truncated_chapter_json`：括号配对（含字符串内花括号）回收完整章节对象 |
| 3 | validator 模型路由静默失效 | validator 走 default 任务模型（qwen3.7-plus），服务进程该链路无 Key → 闸门不设状态直接放行 | validator 支持注入模型，复用扩展运行时已验证的 planner 模型（deepseek-v4-pro） |
| 4 | validator 解析正则脆弱 | 模型实测输出 `**总分** **:** **78分**`、`## 1. 冗余人物`，旧正则要求紧邻冒号 → score 恒 0、sections 漏提取，闸门误判 | 正则容错：总分后容忍 0-16 个非数字字符；标题容忍编号/粗体变体；列表容忍圆点 |
| 5 | 响应序列化丢弃闸门字段 | `routes_expand.py` 白名单逐字段序列化，`alignment_gate_status` 等字段被丢弃——闸门实际已运行但状态对前端/DB 不可见 | schema 补 4 字段（gate_status / gate_retry / structural_debt / character_plot_alignment）并透传 |

### 7.4 服务端实测记录（项目 101，5 轮真实调用）

| 轮次 | 目标 | 验证点 | 结果 |
|---|---|---|---|
| 1 | 0→6 章 | 批次拆分、章节识别、人物落库 | [3,3] 两批；6 章标题全识别；6 人物卡落库；score=79 |
| 2 | 6→8 章 | 闸门状态透出（时序上先发现缺陷 5） | [2] 单批；8 章正确追加；score=82 |
| 3 | 8→9 章 | gate 状态字段闭环 | `failed_after_retry`（score=75 但 12 项问题，正确触发修复） |
| 4 | 9→10 章 | deferred 状态 + 债务落库 | 服务端日志"2 项情节级问题转为结构债（deferred）" |
| 5 | 10→11 章 | **结构债跨轮闭环** | 日志"加载上轮结构债（77 字符）注入本轮扩展"；第 11 章精准承接两项债务（苏婉儿被掳开启身世线 / 夜枭介入并建立利益交易）；新一轮债务滚动更新 |

### 7.5 增补验收标准

1. 修复器返回全情节级问题 → `deferred`，不触发复验调用（`recheck_calls == []`）✔（离线断言）
2. 混合问题 → 补丁应用 + 复验 + 情节级债记录 ✔（离线断言）
3. 首验通过 → `passed` 且债务显式清空 ✔（离线断言）
4. 修复器全空输出 → 首验问题清单整体转结构债 ✔（离线断言）
5. 结构债与人物覆盖约束注入每批 prompt；批间零出场人物补戏提示 ✔（离线断言）
6. 服务端跨轮闭环：deferred 落库 → 下轮加载 → 新章承接 ✔（实测第 5 轮）
7. 离线回归：`test_story_expansion_full_flow.py` 10 项全过 ✔

### 7.6 剩余待验证项

- ~~iterative 模式的服务端实测~~ ✔（2026-08-18 实测，见 7.7）
- ~~epic_framework 模式的服务端实测~~ ✔（2026-08-18 实测，见 7.8；模型路由修复后复测见 7.8.1）
- ~~结构债跨轮承接闭环~~ ✔（任务 93：91 轮写入的 6 项债务被加载注入，见 7.8.1）
- ~~volume_detail 模式的服务端实测~~ ✔（2026-08-18 任务 94 实测，见 7.9）
- ~~结构债注入后对齐分数的多轮走势~~ ✔（58→40→52 回升验证纠偏有效，见 7.9）
- `repaired` 状态（注记级补丁成功修复）的服务端真实出现（iterative/epic 走到 mixed 路径但复验未过；任务 93/94 均 patches=0 直接全情节级——当验证器把问题全判情节级时该状态不可达，属预期行为）
- 多轮 iterative（实测单轮即达标收敛；多轮路径当前仅离线验证）
- 批间戏份提示的服务端触发（需 >4 章多批任务且首批漏人物）
- deferred / 结构债在前端 UI 的呈现（当前仅 DB 与日志可见）
- 长期项：人物弧光锚点系统（人物卡成长线映射章节区间，规划期报缺口，架构级改动）

### 7.7 iterative 模式服务端实测记录（2026-08-18，项目 101 第 6 轮）

**触发设计**：章节 11→12（+1）、人物 6→15（+9，人物增量 9 > `SHORT_CHARACTER_DELTA_LIMIT=8` 触发 iterative）——低成本触发分轮编排，全程约 8 分钟。

| 验证点 | 结果 |
|---|---|
| 模式判定 | `execution_mode=iterative`，reason："本次需新增 1 章、9 人，超出单轮 delta 适用范围，切换为分轮协同" |
| 策略自动解析 | `strategy=character_first`（人物缺口 9 > 章节缺口 1，自动选择） |
| 轮次编排 | 轮 1 同时执行 plot 侧（+1 章：第12章《暗夜寻踪：丹房杀机》）与 character 侧（6→15，新增 赵无羁/墨痕/苍梧/清玄/云瑶/铁山/玄机子/星瞳/老鬼 9 人）；轮记录含 before/after 双侧计数、validation 子记录 |
| 目标精确收敛 | 12 章 / 15 人整，达标即终止（stop_reasons 空——无异常停止） |
| 结构债跨轮注入 | 本轮加载上轮 1195 字符债务；第 12 章内容再次精准承接（救回苏婉儿开启身世线、夜枭关键介入、与沈清秋利益交易——正是上轮债务三项） |
| **闸门 mixed 路径（服务端首次）** | 注记补丁应用 `{cards:1, duty_patches:4, relationship_patches:3}` → 复验 score=58 未过 → `failed_after_retry` **且** 3 项情节级问题自动写入结构债（云瑶/清玄冗余、沈清秋信任危机）——补丁+复验+债务记录全链路真实运行，债务无需人工干预自动滚动 |

**观察**：闸门 mixed 路径与离线测试 `test_alignment_gate_mixed_issues_records_debt_after_recheck` 行为完全一致；新增 9 人物导致对齐分数回落（63/58）属预期——一次性补 9 人的稀释效应由下一轮结构债自动纠偏（云瑶/清玄已在债务中标记冗余）。

### 7.8 epic_framework 模式服务端实测记录（2026-08-18，项目 102《雾锁津门：听尸者与百鬼局》）

**触发设计**：新建项目走完 concept/structure 两阶段后，以 `expansion_mode=epic_framework`、`total_volumes=7`、`total_chapters_min/max=300/500` 触发协同扩展（7 卷 ≥ 6 触发两段式生成），全程约 8 分 45 秒（含一轮完整重试）。

| 验证点 | 结果 |
|---|---|
| 两段式生成 | `🏗️ 第一阶段（结构骨架）完成：volumes=7, stage_roadmap=3` → `🗺️ 第二阶段（伏笔表+人物生命周期）完成：foreshadowings=8, character_lifecycle=7`——骨架与补全两段真实分离执行 ✔ |
| 骨架渲染 | `outline_merger` 解析成功：共 7 卷，头部 2474 字符（总纲/阶段路线图），尾部 1934 字符（伏笔表/人物周期）✔ |
| 卷数校验兜底（服务端首次） | 第二轮骨架 JSON 解析退化为 `volumes=0`（上游 qwen3.7-flash 流式 RemoteProtocolError 中断的连锁），触发 `⚠️ 卷数校验未通过：期望 7 卷，实际可解析卷：无，启用文本兜底重生成` → 兜底文本重生成后解析成功 7 卷——失败自愈链路真实运行 ✔ |
| 分轮执行 | `execution_rounds=2`（round 1 框架+人物+卷细化后未收敛，round 2 整体重建框架并达标） |
| 人物卡同步 | `parsed=21, created=21`；characters 表累计 42 人（两轮各 21 人累积落库）✔ |
| 对齐闸门 | 首验 score=58（<60 且问题数 ≥3）→ 注记补丁 21 项 → 复验 `character_plot_alignment.score=68` 未达阈值 → `alignment_gate_status=failed_after_retry`（与 7.7 iterative 实测同路径）|
| **结构债持久化（epic 场景首次）** | `alignment_structural_debt` 自动写入 6 项情节级债务：陈太太/林管家功能重叠、李姐冗余、张师傅并入老陈头、王哥未完成、误导性祟缺失、中立角色关系无情节节点——下一轮扩展将自动加载注入 |
| 产出完整性 | `expanded_outline` 含总纲/终局/核心矛盾/阶段路线图/7 卷规划（卷定位、核心目标、伏笔任务、卷末爆点、下卷交接）；`epic_total_volumes=7` 落库 ✔ |

**观察与遗留**：
1. **多轮重建的累积副作用**：round 2 整体重建框架后，round 1 的 21 人物卡未清理，characters 表累积两套卡（42 人）。对齐验证在债务中已标记冗余人物，可由下轮债务纠偏，但"重建轮是否应作废上一轮人物卡"值得作为后续优化项评估。**→ 已于 7.10 完成防复发修复（来源打标 + 孤儿卡软归档）。**
2. epic 场景的 `failed_after_retry` 不再是死胡同：结构债机制在 7 卷长篇上同样生效，冗余人物/缺失祟/关系断点等情节级问题将滚动进入下一轮。
3. 稳定性备注：实测期间后端两次非代码因素中断（进程关闭、`--reload` 热重载杀后台任务）。**建议：执行协同扩展等长任务时后端不要以 `--reload` 模式运行**（文件监视器会因脚本/pyc 写入重启 worker 并静默杀死后台任务），已在两段式生成处补充 `🏗️/🗺️` 阶段日志标记便于观测。

#### 7.8.1 epic 框架生成的模型路由断层与修复（2026-08-18）

**根因（由任务 89 终端日志定位）**：任务 89 启动后进度停在 18% 长达 20 分钟，03:31:37 `qwen3.7-flash` 流式调用 `ReadTimeout`。排查发现模型路由断层——协同扩展动态选模明明选择了 `planner=deepseek-v4-pro（max_tokens=23588, timeout=989s）`，但该选模结果只作用于协调器自身的 `_invoke_text/_invoke_json` 调用；epic 框架两段式生成（全书最大单次 LLM 调用，est_output≈2 万 token）在 `OutlineExpander` 内部走 `CreativeDirectorAgent`，其固定 `task_type='concept'` 路由到 qwen3.7-flash（默认 600s 级超时），动态选模与动态超时完全未接入。flash 级模型扛不住超长输出，流式中途停滞 → ReadTimeout → 靠兜底重生成为主路径"续命"（任务 89 的 20 分钟黑箱、任务 91 运行中的 RemoteProtocolError 均为同一根因）。

**修复**（对齐 `plot_architect_r1/plus` 既有注入模式，`tests/test_story_expansion_full_flow.py` 10/10 通过）：
1. `agents.py`：`CreativeDirectorAgent` 支持注入自定义 `llm`（原仅 `PlotArchitectAgent` 支持）。
2. `outline_expansion/_base.py`：新增 `creative_director_pro = CreativeDirectorAgent(llm=deepseek-v4-pro 64K 超长输出配置)`。
3. `_incrementalexpansion.py` epic 两段式（骨架 JSON / 伏笔表详情 JSON / 文本兜底）与 `_epicframework.py` 旧路径的框架生成调用全部切换至 `creative_director_pro`。
4. 协同扩展其余小输出子调用（补丁/关系/戏份分布等）保持默认 `creative_director`（qwen 路由）不动，控制成本。

**修复后实测（任务 93，2026-08-18，项目 102 epic 重建，14m20s）**：

| 验证点 | 任务 89/91（修复前） | 任务 93（修复后） |
|---|---|---|
| 框架第一阶段 | qwen3.7-flash 卡死 20 分钟 ReadTimeout / RemoteProtocolError 后 volumes=0 走兜底 | deepseek 直连一次通过：volumes=7, stage_roadmap=3（2m22s） |
| 框架第二阶段 | — | deepseek 直连一次通过：foreshadowings=14, character_lifecycle=12（1m40s，比 91 的 8/7 更丰富） |
| 卷数兜底重生成 | 91 触发过（失败自愈） | 未触发（主路径成功，无需兜底） |
| 人物卡同步 | 91 全量新建 21 张（两轮累积两套卡） | upsert 生效：parsed=21, created=16, updated=5 |
| 结构债跨轮承接 | 91 写入 6 项债务 | **加载上轮债务（186 字符）注入本轮**，闭环首次完整运行 |

**对齐闸门观察**：本轮 score=40 → `failed_after_retry`，新增 5 项结构债（311 字符）滚动至下一轮。分数低于 91 轮的 58，但问题层次明显加深——由"人物功能重叠/冗余"表浅问题转为"伏笔缺引爆空间、情感锚点与主线错位、权源缺失、关系标签无触发场景"等情节级深层问题。符合结构债驱动"逐轮解决表层、暴露深层"的设计预期。

**遗留**：`repaired` 状态仍未真实出现（本轮 patches=0，验证器直接全部判为情节级）；多轮后对齐分数走势已在任务 94 得到验证（见 7.9）。

### 7.9 volume_detail 模式服务端实测记录（2026-08-18，项目 102 任务 94）

**触发设计**：在任务 93 epic 框架（7 卷）基础上，`expansion_mode=volume_detail`、`target_volume_index=1`、`volume_chapters_min/max=40/60`、`volume_character_increment=4`，传入 58 人物卡文本，全程约 18 分钟。

| 验证点 | 结果 |
|---|---|
| 模式路由 | `mode=volume_detail` 确认；卷细化走 `volume_detail_expand→deepseek-v4-pro`（est_output≈19.7 万 token，动态超时 6309s）✔ |
| 单卷细化主路径 | 第 1 卷 **1-50 章**一次生成成功（4m53s），章节编号校验通过，卷一致性校验通过，`大纲拼接完成：1/7 卷已展开` ✔ |
| 结构债注入 | 93 轮 5 项债务（311 字符）加载注入 ✔ |
| 人物卡同步 | 增量补 2 人（parsed=2, created=2，请求 increment=4 由规划判定补 2）✔ |
| 对齐闸门 | score=**52** → `failed_after_retry`，patches=0，新增 7 项结构债（361 字符） |

**结构债纠偏走势（关键验证）**：91 轮 58（epic 首建）→ 93 轮 40（epic 重建暴露深层）→ **94 轮 52（volume_detail 回升 +12）**。93 轮的 5 项债务（伏笔缺引爆空间、情感锚点错位、权源缺失、关系无触发场景）**未再出现**于 94 轮新债务——已被第 1 卷细化吸收解决；94 轮新债务全部是更深一层的情节级问题（邪教权贵容器无对应角色、灭门案知情者无出场位、王妈情感支撑线未铺陈、反派派系斗争缺行动线、信任升级机制缺跨章铺垫等）。"逐轮剥洋葱、分数先降后升"的设计预期得到真实数据支撑。

**观察**：`repaired` 状态在连续两轮 patches=0 后确认——当验证器将问题全部判为情节级（需结构债而非注记补丁）时该状态按设计不可达，非缺陷；delta/iterative 模式下的 mixed 路径仍可能触达它。

### 7.10 风险 5：epic 框架重建导致人物卡无限累积（2026-08-18 已修复）

**风险描述**（源自 7.8 遗留 1，项目 102 实测暴露）：`parse_and_sync_characters` 只做 upsert 从不清理。epic 模式每轮重建都会生成一套全新人物名单，旧框架人物卡永久残留——项目 102 经 91/93 两轮重建 + 94 卷细化后 characters 表累积至 58 张，其中大量为旧框架孤儿卡。累积后果：① 后续轮次的人物卡文本预算被死卡挤占；② 对齐验证的冗余人物告警噪音增大；③ 弧光锚点等按人物聚合的能力（见 `CHARACTER_ARC_ANCHOR_DESIGN_20260818.md`）会被幽灵人物污染。

**根因**：人物卡无来源标记，系统无法区分"协同扩展管线生成"与"用户手动创建"——前者重建后应随框架失效，后者任何情况下不可触碰。

**修复方案（来源打标 + 软归档，非物理删除）**：

| 层 | 改动 |
|---|---|
| Schema | `characters` 表新增 `source`（`expansion`=协同扩展管线；`NULL`=历史数据或手动创建，永不自动归档）与 `archived_at`（非空=已随框架重建软归档）两列；迁移：`backend/alembic/versions/add_character_source_and_archived_at.py`（幂等，缺列才加） |
| 同步打标 | `parse_and_sync_characters` 落库时统一写 `source='expansion'`，upsert 命中已归档卡时自动解除归档（再引用复活语义），并返回 `normalized_names` 供归档比对 |
| 孤儿归档 | 新增 `archive_orphan_expansion_characters(project_id, keep_normalized_names, db_session)`：仅归档 `source='expansion' 且 archived_at IS NULL 且规范化名称不在新框架名单` 的卡片；重复调用幂等 |
| 触发点 | `routes_expand.py` 人物卡同步后，仅当 `execution_mode=epic` 且本轮前已存在 epic 框架（`had_epic_framework_before`，即"重建"语义）且 `parsed>0`（本轮解析失败时不清空整表）才调用；归档失败仅告警不阻断扩展主流程 |
| 存量清理 | 项目 102 的 58 张存量卡一次性回填 `source` 打标（存量数据修复，非代码路径） |

**安全边界**：手动创建/历史卡片（`source` 为 NULL）在任何路径下不被归档；软归档保留全部数据，误归档可由后续轮次再引用自动复活；首建 epic（无旧框架）不触发归档。

**验证**：`backend/tests/test_character_archive_orphans.py` 4/4 通过——① 同步打标并返回规范化名单；② 重建只归档扩展孤儿（手动卡不受影响）；③ 重复归档幂等 + 再引用自动解除归档；④ 空 keep 名单且无扩展卡时安全。全流程 `test_story_expansion_full_flow.py` 10/10 无回归。
