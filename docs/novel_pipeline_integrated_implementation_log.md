# 小说流水线整合改进 —— 实施记录

- 基线文档：`docs/novel_pipeline_integrated_improvement_guide.md`（以下简称《指南》）
- 实施范围：《指南》第 13 节推荐落地顺序的全部五批
- 实施原则：每批独立实现、独立测试；不破坏现有数据；新增字段全部可空；消化/指标失败不阻断正文保存

## 1. 总体实施状态

| 批次 | 内容 | 状态 | 测试结果 |
|---|---|---|---|
| 第 1 批 | 人物运行态验收 + 统一伏笔上下文适配器 | ✅ 完成（卷级主链路接线于第二轮补齐） | 7+3 + 5 通过 |
| 第 2 批 | P1 细纲驱动写前连续性闸门 | ✅ 完成 | 12 通过 |
| 第 3 批 | P2 写后结构化消化 `narrative_state_v1` | ✅ 完成（第二轮补首尾截取+跨章债务滚动） | 8+4 通过 |
| 第 4 批 | P3 张力趋势 + 浅层文风漂移 | ✅ 完成 | 9 通过 |
| 第 5 批 | P4 可暂停自动推进与熔断 | ✅ 完成（`empty_output` 已于第二轮接线） | 12+1 通过 |
| 第二轮 | 审计缺口修复（见 2.6） | ✅ 完成 | 11 新增用例（含 1 新测试文件）全通过 |
| 第三轮 | 消化步思考模式关闭 + 指导文档对齐实现基线（见 2.7） | ✅ 完成 | 1 新增用例通过 |
| 第四轮 | 与上一章高度重复检测 + 指导文档清掉过时搭车表（见 2.8） | ✅ 完成 | 2 新增用例通过 |

最终合并回归（七个测试文件）：**67 passed**。所有修改文件均通过 `py_compile` 编译检查。

> 表述修正记录：初版本记录将第 1 批/第 5 批表述为“全部完成”，经第二轮审计核实：
> 第 1 批当时卷级 `new_foreshadowings` 适配函数已实现但主链路未传参；第 5 批当时 `empty_output` 仅为预留接口。
> 两项均已在第二轮修复（见 2.6）。

## 2. 各批实施明细

### 2.1 第 1 批：运行态验收 + 统一伏笔适配器

**改动文件**

- `backend/app/services/foreshadow_adapter.py`（修改）
  - `UNIFIED_STATUSES` / `_UNSETTLED_STATUSES` / `_merge_into` 的 status_rank 补入框架状态 `planted`。
  - `review_meta.foreshadow_ledger` 读取增加类型防护（ledger 非 dict、entries 非 list 时安全降级为空）。
  - 保守归并：规范化文本完全相同且窗口不冲突才合并，符合《指南》6.4「宁可两条暂不合并」。
- `backend/app/api/v1/workflow/routes_chapter.py`（修改）
  - 章节规划 prompt 接入统一伏笔任务（`build_unified_foreshadow_tasks` + `format_unified_foreshadow_section`），失败时回退旧 `format_foreshadow_ledger`。
- `backend/tests/test_foreshadow_adapter.py`（新增，7 测试）
- `backend/tests/test_character_runtime_acceptance.py`（新增，5 测试）
  - 验收核心角色 prompt 含性格/价值观；含调用点静态回归（排除函数定义自身，仅统计真实调用）。

> ⚠️ 第二轮审计发现：本批初版交付时，框架层与章节账本已接入统一适配器，但卷级 `new_foreshadowings` 适配函数（`adapt_volume_foreshadow_text`）虽已实现，主链路调用 `build_unified_foreshadow_tasks` 时未传 `volume_foreshadow_texts`，三层统一读取当时仅完成两层。已于第二轮补齐（见 2.6 缺口 1）。

### 2.2 第 2 批：P1 细纲驱动写前连续性闸门

**新增 `backend/app/services/pre_generation_gate.py`**（纯规则，不调 LLM）

规则集与级别：

| 规则 | 检查内容 | 级别 | 失败码 |
|---|---|---|---|
| A1/A2 | 细纲要求回收伏笔但规划缺失/未声明 | blocking | CONTINUITY_BREAK |
| A3 | 细纲无伏笔事项但规划声明回收 | warning | — |
| A4 | 规划缺伏笔事项字段 | info | — |
| B1 | 早于揭秘卷提前揭示 | blocking | CONTINUITY_BREAK |
| B2 | 埋设卷不一致 | warning | — |
| C1 | 对 revealed/recovered/abandoned 再回收 | blocking | CONTINUITY_BREAK |
| F1 | 死亡角色出场（回忆/闪回语境豁免） | blocking | LOGIC_BREAK |
| F2 | 未出场角色被计划出场 | blocking | LOGIC_BREAK |
| E1 | 计划同时写「只暗示」和「明确揭示」 | warning | — |
| D1 | 伏笔 open 且 ≥20 章未推进 | warning | STALL_NO_PROGRESS |

输出结构带 `phase="pre_generation"`，符合《指南》6.6；内部异常吞掉返回空列表，不阻断生成。

**接入点**（`routes_chapter.py`）：章节规划生成后、正文生成前执行闸门；blocking 时自动重规划 ≤2 轮（`temperature=0.5`，反馈注入重规划 prompt）；仍失败则保存 `review_meta.pre_generation_gate`（闸门报告 + 规划草稿前 8000 字）并抛错转人工，不丢弃用户已有章节；warning 注入正文/分段 prompt 作为提醒。

测试：`backend/tests/test_pre_generation_gate.py`，12 通过；当批回归 27 passed。

### 2.3 第 3 批：P2 写后结构化消化

**新增 `backend/app/services/narrative_state_extractor.py`**

- 消化只走 `chapter_post_save` 异步路径，不扩展评审 prompt（遵循《指南》文末轻量化约束，详见第 4.3 节）。
- 输出结构：`plan_alignment / events / character_changes / foreshadowing / narrative_debts / quality_metrics`（quality_metrics 为第 4 批搭车扩展）。
- 幂等键 = 章号 + `EXTRACTOR_VERSION`（v1），同章同版本重复消化直接跳过。
- 滚动窗口 `MAX_STORED_CHAPTERS=20`；无增量章节只记 `plan_alignment`，不重复沉淀细纲内容。
- 全流程不抛异常：消化失败只记日志，绝不影响正文保存。

**注入**：`_build_chapter_plan_user_prompt` 新增 `narrative_state_text` 参数（token 预算 weights 0.03），渲染【叙事状态增量】块，优先级：未偿还债务（逾期 ≥2 章标注）> 人物变化 > 未闭合事件。

**落库**：`chapter_post_save.py` 新增步骤 1.8（位于人物状态快照之后）。

测试：`backend/tests/test_narrative_state_extractor.py`，8 通过。

### 2.4 第 4 批：P3 张力趋势 + 浅层文风漂移

**新增 `backend/app/services/narrative_metrics.py`**

- **张力指标搭车**：5 项指标（tension/conflict_progress/emotion_change/information_gain/ending_hook，0-100 clamp）随 P2 消化 LLM 一次输出，不新增模型调用；`TREND_WINDOW=10` 章滚动。
- **趋势策略**（《指南》8.1）：连续两章 tension<40 → 规划诊断建议；单章 hook<40 且 progress<40 → 定向修订建议；单章低谷只记录不强制重写。建议文本经 `format_quality_trend_advice` 注入下一章规划的质量记忆段。
- **文风漂移**（《指南》8.2）：纯 Python 浅层特征（平均句长、对话占比、套话密度、感叹号密度），基线 ≥3 章才判定漂移，相对偏差 >0.35 或套话密度增量 >2.0 触发；只记录修订信号到 `review_meta.style_trend`，绝不覆盖用户稿件。
- 文本 <400 字不计算特征（样本不足）。

**落库**：`chapter_post_save.py` 新增步骤 1.9。

测试：`backend/tests/test_narrative_metrics.py`，9 通过。

### 2.5 第 5 批：P4 可暂停自动推进与熔断

**新增 `backend/app/services/narrative_circuit_breaker.py`**

- 状态持久化于 `review_meta.circuit_breaker`：`{paused, reason, paused_at_chapter, streaks, history}`，history 滚动上限 20 条。
- 熔断条件（《指南》9.2）：
  - 连续 ≥2 章写前闸门 blocking 未解决（`gate_blocking`）；
  - 连续 ≥3 章结构化消化失败（`digest_failure`）；
  - 伏笔账本无法解析（`ledger_corrupt`，立即熔断）；
  - 模型输出为空/重复（`empty_output`，初版仅预留接口，第二轮已接线至正文输出校验点，见 2.6 缺口 2）。
- `generation_success` / `digest_success` 分别重置对应连续计数；人工确认后 `confirm_and_resume` 清零计数并保留 history 以便追溯。
- 全部为纯函数且绝不抛异常，落库由调用方负责。

**接线点**

| 位置 | 信号 |
|---|---|
| `generate-next-chapter` endpoint 入口（项目校验后、取锁前） | 暂停 → HTTP 409（携带 reason/paused_at_chapter）；`resume_after_confirmation=true` 时解除并继续 |
| 闸门 blocking 最终失败保存报告处 | `gate_blocking` |
| 任务尾部 review_meta 沉淀处 | `generation_success`（重置计数） |
| `chapter_post_save` 步骤 1.8 消化后 | `digest_success` / `digest_failure` |
| 统一伏笔适配异常且账本存在时 | `ledger_corrupt` |

**Schema**：`GenerateNextChapterRequest` 新增 `resume_after_confirmation: bool = False`。

测试：`backend/tests/test_narrative_circuit_breaker.py`，12 通过（含 schema 字段与 endpoint 接线静态回归）；第二轮补 `empty_output` 接线回归后 13 通过。

### 2.6 第二轮：审计缺口修复（五项）

基于外部审计反馈，逐项核实并修复：

**缺口 1：卷级伏笔接入主链路**

- 事实核实：`VolumeConnector` 的 `prev_volume_summary`（含 `new_foreshadowings`）仅在卷细化时临时生成，**不持久化**；可用数据源为 `WorkflowEpicFrameworkState.epic_volumes_detail`（DB 字段）与 `chapter_generation_context.current_volume_context`。
- 修复：`foreshadow_adapter.py` 新增 `extract_volume_foreshadow_texts`（纯规则解析“遗留伏笔/已埋下的伏笔/新伏笔”等引导词行，容忍引导词与冒号间的括号说明）；`routes_chapter.py` 主链路从两个数据源提取后传入 `build_unified_foreshadow_tasks(volume_foreshadow_texts=...)`。
- 测试：解析兼容测试、端到端进入统一任务测试、routes 接线静态回归。

**缺口 2：`empty_output` 熔断接线**

- 修复：`routes_chapter.py` 正文产出后（额度确认前，免费档可退额）检测空输出/占位模板→记录 `empty_output` 信号（立即熔断）并落库→抛错终止任务；信号记录自身失败不阻断。
- 说明：**重复输出检测**（与上一章文本比对）本轮未实现，列入后续项。

**缺口 3：思考模式关闭落地**

- 事实核实：`StreamingService → UnifiedLLMClient.chat_stream → model_hub → adapter` 的 kwargs 透传链完整支持 `extra_body`；但小说主链路初版未显式传入禁用参数。
- 修复：`streaming_service.py` 两个生成方法新增 `disable_thinking` 参数，启用时透传 `extra_body={"thinking": {"type": "disabled"}}`；章节规划、闸门重规划、分段正文、单遍正文四处调用点显式启用。
- 测试：假 LLM 客户端集成测试（验证 kwargs 透传与默认不附加）+ 静态回归。
- 第三轮补充：写后消化 LLM（短 JSON 抽取步）初版未覆盖，已在第三轮经 `create_model_llm(extra_body=...)` 接入（见 2.7）；评审/迭代改稿步保持现状。

**缺口 4：消化正文首尾拼接截取**

- 修复：`_build_digest_prompt` 正文输入由 `chapter_content[:6000]` 改为 `_head_tail_excerpt`（前 4000 + 后 2500，中段标注省略）；章节结尾是钩子/伏笔证据/叙事债务最集中位置，不再被截断丢失。

**缺口 5：叙事债务跨章滚动继承**

- 修复：消化 prompt 新增 `resolved_debts` 字段；`merge_narrative_state_into_review_meta` 维护 `narrative_state_v1.open_debts` / `open_events` 滚动集合（既有 + 本章新增 − 本章兑现/闭合，归一化去重，上限 12 条）；`format_narrative_state_section` 优先读滚动集合，旧数据无滚动键时回退最近章。第 10 章产生、第 11 章未提及的债务，第 12 章规划仍可见并标注逾期。
- 测试：债务跨章继承、resolved 移除、事件滚动闭合、长章首尾保留四组测试。

### 2.7 第三轮：消化步思考模式关闭与文档基线对齐

**消化步 disable_thinking 接线**

- 背景：第二轮思考模式关闭仅覆盖规划/正文四处调用点；写后消化 LLM（短 JSON 抽取步）未接入，与《指南》7.5“模型判断步用短 JSON、不占思考预算”的要求不一致。
- 事实核实：`create_model_llm` 的 kwargs 经 `ModelHubChatModel.runtime_options` 透传至 `model_hub.call`，支持 `extra_body`。
- 修复：`narrative_state_extractor.py` 消化 LLM 创建时传入 `extra_body={"thinking": {"type": "disabled"}}`；静态回归断言接线与透传链存在。

**指导文档对齐**

- `docs/novel_pipeline_integrated_improvement_guide.md` 头部新增实施基线标注：本文是开工规格，现状以本记录为准。
- §4 路线图逐批标注实施状态；§5.2 补伏笔适配器实施现状与已知局限；§7.1 将“轻量搭车评审步”标注为已定方案（全部走 post_save）；§7.5 思考模式策略补实施现状。

### 2.15 改稿保细纲/规划情节，必改项硬拦截，规划禁止重播前章节拍

- 改稿 prompt 新增【本章精确细纲】【本章创作规划】；保情节以细纲+规划为准，不再要求“保持初稿情节/不少于90%字数”。【必改】删减时删减优先，不得为保篇幅留下注水桥段。
- `_iteration_review_has_unresolved_required_items` 除核验表“未执行”外，剩余关键问题中的【必改】/MUST 也视为未完成。
- 规划约束补充：不得把细纲短过场扩写成与前章同构的重头戏，情况变化必须写清。
- 规划通过后写入 `review_meta.last_chapter_plan`（plan+outline），主链路改稿调用传入 `chapter_plan` 与 `current_chapter_outline`。
- 测试：`test_iteration_must_fix_enforcement.py`。

### 2.16 G1：细纲过场升格/前章同构重播闸门

- pre_generation_gate.py 新增 G1：细纲将该场面标为过场、规划扩成催租/收租完整一场、且前章摘要已有同构场面时，记 STALL_NO_PROGRESS warning。
- 细纲若把该场面写入关键事件，视为合法升级，不报。
- should_replan_for_warnings() 让 G1 触发 1 轮重规划；仍未消除则放行并注入正文闸门提醒，不阻断生成。
- 
outes_chapter.py 闸门调用补传 previous_chapters_summary。
- 测试：	est_pre_generation_gate.py 现 15 passed。

### 2.17 ??????????????????

- ???`detect_duplicate_names` ???+???????????????/???/??/??????????????????????????????? post_save ?? 4 ????
- ????? `collect_duplicate_name_conflicts`????????????????????????????/???/?????????
- ?? 102 ?? `detect_all_conflicts` total_count=0?
- ???`backend/tests/test_setting_duplicate_name_conflicts.py` 3 passed?

### 2.18 ???????????

- ??????????????????????????????+ ???????
- ?? `chapter_structure_guard.py`????????STRUCT_BROKEN / ???????????? 60% ???????
- ????????????STRUCT_BROKEN hint ??????????????
- ???`test_segment_structure_guards.py` + ??????11 passed?

### 2.14 浏览器重跑第5章：review_meta 合并验收通过

- 章节 id=129《孙妈闹社，阿九带信》（3786字），post_save 完成；写后消化 alignment=partial，事件3/人物变化3/伏笔4/债务5。
- `narrative_state_v1.chapters` 同时保留 `4` 与 `5`（修复前只剩 `5`）。
- `open_debts` 保留第4章四条未还债（打捞许可、档案原件、戏妆旧案、巡捕房压案），并追加第5章新债（线人费、黑市买家、铜钥匙追踪、染血绸缎、第九个）。证明评审整包覆盖已消除。
- 正文有戏妆/压案/巡捕房/铜钥匙/红纸/负心，无「打捞许可」「档案」字面；属规划承接粒度问题，不是状态丢失。
- 伏笔账本 entries 仍为空；设定一致性 warning 4 条；Chroma 主库版本不兼容已 fallback cleanroom，不影响消化落库。

### 2.13 浏览器第5章复现 review_meta 整包覆盖，并修复深合并

- 项目 102 经浏览器工作流生成第5章《孙妈闹社，阿九带信》（4139字），post_save 正常完成。
- 根因：`_run_next_chapter_quality_review()` 返回当章新建 review_meta（多模型评审字段），`routes_chapter.py` 评审落库整包写入 `project_settings.review_meta`。`update_project_settings_fields()` 原先不读旧值，导致第1-4章 `narrative_state_v1` 被冲掉；随后第5章消化只能在空账本上滚动，open_debts 只剩第5章新债。
- 修复：`update_project_settings_fields()` 写入 review_meta 前先 load 旧值，做顶层 merge（旧键保留，incoming 同名键覆盖）。单测覆盖“评审 meta 不含 narrative_state_v1 时不得丢债”。
- 回滚：删除章节 id=128（第5章），清空 chapter_draft/review_report/final_version，去掉第5章 quality_memory/trend/breaker 记录，并按第4章摘要恢复 4 条 open_debts（打捞许可、档案原件、戏妆旧案、巡捕房压案），供浏览器重跑第5章验收。

### 2.12 真实链路第4章（规划 prompt 债务注入已落盘）

- 项目 102 生成第4章《老陈上门，私查暗限》（4241字）。
- 规划 prompt 捕获文件确认含【未偿还叙事债务】及铜钥匙/别查/红纸/唱戏。prompt 长度 45348。
- 正文承接这些债务（铜钥匙、别查、红纸、戏腔、锁簧、老陈），并按细纲推进老陈上门私查。
- 消化后 open_debts 滚动为第4章新欠账：打捞许可、档案未交付、前两具戏妆男尸身份、巡捕房压案。

### 2.11 真实链路第3章（债务是否进入下一章）

- 项目 102 继续生成第3章《遗物追音，幻听初现》（3175字）。
- 正文明确承接第2章债务：负心红纸、铜钥匙、戏腔、食指均出现，并非复读第2章。
- 写后 open_debts 滚动为第3章新欠账（铜钥匙对应哪扇门、唱戏声来源、别查警告发出者、红纸脂粉指向），说明债务会更新而不是只堆积第2章原文。
- 
arrative_state_v1/style_trend/quality_trend 当前窗口为第3章。规划 prompt 注入捕获因后台任务输出未回传到本轮会话，但正文用词已证明债务进入了创作。

### 2.10 真实链路联调（项目 102）

- 第一次：后台任务引用了 HTTP 入口才有的 previous_chapter_content，失败后改为从 previous_chapters_payload 还原上一章全文。
- 第二次：第1章生成成功（3567字）。start_chapter_post_save_task 使用 daemon 线程，脚本退出后消化未落库。
- 第三次：同步补抽第1章后生成第2章（4282字，承接浮尸食指）。随后同步消化，
arrative_state_v1/quality_trend/style_trend 写入；熔断记录 generation_success + 两次 digest_success。
- 伏笔账本仍为空：规划未产出可解析伏笔事项，属字段依赖而非熔断误伤。
- 第1章消化结果被第2章滚动窗口覆盖（当前 chapters 仅有 2），属 MAX_STORED 合并行为，债务从第2章起滚动。

### 2.9 第五轮：评审改稿关思考、显式 ID 归并、C3 设定 warning

- 评审、迭代计划、改稿、复评四处 `generate_chapter_streaming` 增加 `disable_thinking=True`。规划/正文/消化此前已关闭。
- 跨层伏笔：除规范化文本全同外，卷/章条目若显式引用 `fs_fw_*` 且窗口不冲突，可合并到框架条目。同义词仍不自动合并。
- C 类事实图仍不做 blocking。闸门新增 C3：规划`设定调用/关键设定`不在设定清单中则 warning，主链路传入 `plan_settings_catalog`。
- `routes_chapter.py` 本轮不整文件拆分，避免主路径搬迁风险。

### 2.8 第四轮：重复输出检测与指导文档去歧义

**重复输出检测**

- 背景：第二轮只拦截空串和占位模板；连续两章几乎复读不会熔断。
- 修复：`narrative_circuit_breaker.detect_invalid_chapter_output()` 增加与上一章全文的规范化比对；完全相同或字符 n-gram overlap ≥ 0.92 视为重复。短章（<400 字）不判，避免误伤。
- 接线：`routes_chapter.py` 保存上一章完整正文到 `previous_chapter_content`，正文校验点改走统一检测函数。

**指导文档**

- 删除 §7.1 与文末残留的“轻量搭车评审步”对照表，避免与已定方案冲突。
- §14 补齐适配器/闸门/消化/熔断等实施文件。

## 3. 验收对照

对照《指南》第 12 节量化验收：

| 批次 | 验收标准 | 落实情况 |
|---|---|---|
| 第 1 批 | 核心角色 prompt 含性格/价值观；旧账本可读；误合并为 0 | 验收测试覆盖；归并仅在规范化文本相同且窗口不冲突时发生 |
| 第 2 批 | 高置信冲突阻断；解析失败只 warning | 纯规则高置信路径才 blocking；闸门内部异常返回空列表不阻断 |
| 第 3 批 | 无增量不重复写细纲；消化失败不影响正文；幂等 | 无增量只记 plan_alignment；全流程不抛异常；章号+版本幂等键 |
| 第 4 批 | 低谷章不误强制重写；风格分不覆盖用户稿 | 低谷只记录；漂移只产修订信号，无任何稿件写回路径 |
| 第 5 批 | 连续失败熔断；人工确认后可恢复 | 连续计数阈值熔断 + 409 阻断 + resume 恢复，均有测试 |

误报率/归并准确率按《指南》要求不在首期给出百分比，误报/漏报样本可通过 `review_meta.pre_generation_gate` 报告与 `circuit_breaker.history` 留痕积累。

## 4. 过程中发现的问题与处理

### 4.1 `planted` 状态映射 bug（第 1 批发现）

框架层伏笔状态 `planted` 不在适配器 `UNIFIED_STATUSES` 中，被误映射为 `open`，会改变未结算集合语义。修复：`UNIFIED_STATUSES`、`_UNSETTLED_STATUSES`、归并 status_rank 三处同步补入 `planted`，并补测试。

### 4.2 `foreshadow_ledger` 类型防护缺失（第 1 批发现）

历史项目中 `review_meta.foreshadow_ledger` 可能为字符串等非 dict 结构，直接 `.get` 会抛 AttributeError 中断规划 prompt 构建。修复：读取处加 isinstance 防护，损坏时降级为空账本（并作为第 5 批 `ledger_corrupt` 熔断信号的判定基础之一）。

### 4.3 评审步轻量化约束的决策（第 3 批）

《指南》7.1 提出轻量字段可「搭车评审步」，但文末新增约束要求：搭车必须是短 JSON 独立小预算，评审输出接近上限即回退 post_save。为规避评审 prompt 膨胀风险，P2 消化直接采用 post_save 异步路径，未扩展评审 prompt；张力指标（P3）同样搭车消化 LLM 而非评审 LLM。该决策牺牲少量实时性，换取评审步稳定性。

### 4.4 伏笔事项解析重复实现（第 2 批发现）

闸门初版自行复制了伏笔事项解析逻辑，与 `prompts/narrative_quality._parse_foreshadow_items` 重复（违 DRY）。修复：改为导入复用，并删除冗余正则与重复字面量。

### 4.5 文风特征短文本边界（第 4 批发现）

`compute_style_features` 对 <400 字文本返回空字典，初版测试样本（320/380 字）全部落入该分支导致断言失败。修复：扩充测试样本至 ≥570 字；该阈值本身保留（短章特征统计不稳定）。

### 4.6 调用点静态回归的误判（第 1 批发现）

验收测试用「匹配位置前 40 字符是否含函数定义串」来排除定义自身，但该串出现在匹配点之后，无法排除。修复：改为检查前 4 字符是否以 `def ` 结尾。

### 4.7 `routes_chapter.py` 体积风险（观察项）

该文件已超 2700 行，本次五批均在其中插入逻辑（每处均以独立 try/except 包裹、局部 import，确保失败不阻断主流程）。建议后续把章节生成任务拆分为独立模块，本次为控制变更范围未做结构重构。

### 4.8 评审落库整包覆盖 narrative_state_v1（浏览器第5章发现）

`update_project_settings_fields(review_meta=...)` 原为整包覆盖。评审步传入当章新建对象后，跨章消化/债务/文风趋势会被抹掉。已改为顶层深合并；后续若某键需要整表替换，仍由 incoming 同名键覆盖。

## 5. 已知局限与设计取舍（仍成立的风险，非回归）

以下各项均为预期取舍或分期约束，已在代码中按此行为，不当作实现遗漏处理：

1. **卷级伏笔来自长文本规则抽取，非结构化 JSON**：`new_foreshadowings` 不持久化，只能从卷明细/卷上下文的“遗留伏笔/新伏笔”等引导词行抽取；若卷连接器输出未渲染成这些引导词，存在召回缺口。属召回问题，不是“没传参”。
2. **跨层伏笔归并保守**：只在规范化文本完全相同且窗口不冲突时合并；框架“主角真实身份”与卷摘要“身世线索”仍常是两条，闸门对未合并条目会漏检。安全优先，属预期。
3. **P1 C 类完整事实图未做**：道具/设定“本章是否建立”、前置线索证据仍是 warning 或跳过，与《指南》6.5 分期一致，P1 不视为闭环。
4. **`empty_output` 已含空串、占位和高度重复**：短章不参与重复判定；轻度改写复读（低于 0.92 overlap）仍可能漏检，属预期阈值取舍。
5. **闸门质量依赖规划字段可解析**：A/B/E 规则依赖“情节作用/伏笔事项/涉及人物”等结构化行；规划写成散文时规则降级为 info/漏报。设计取舍。
6. **`routes_chapter.py` 过重**：五批逻辑均在同一文件（每处独立 try/except + 局部 import），主流程稳定但后续改闸门/熔断/伏笔易互相踩。维护风险，见 4.7 与后续项 5。

## 6. 遗留与后续建议

1. **轻度复读与自动推进循环**：高度重复已熔断；同情节换句复读、跨章隔代复读未做。无人值守连续生成若要上，再补更细的相似度策略。
2. **C 类完整事实图**（道具/设定「本章是否建立」、前置线索证据）按《指南》6.5 属 P2 之后阶段，本次仅落设定清单 warning 级。
3. **闸门误报标注集**：建议基于 `review_meta.pre_generation_gate` 留样建立标注集，再定发布门槛数字。
4. **语义级文风指标**（叙述/动作/心理比例、视角切换）按《指南》8.2 后置，需 LLM 判断，首期未做。
5. **`routes_chapter.py` 拆分**：见 4.7。
6. **卷级伏笔数据源局限**：`prev_volume_summary.new_foreshadowings` 不持久化，当前只能从 `epic_volumes_detail` 与卷上下文文本规则提取；若后续卷细化结果落库，可改为直接读结构化字段。
7. **评审/迭代改稿步的思考模式**：已关闭。同义词归并、C 类事实图 blocking、`routes_chapter.py` 拆分仍未做。

## 7. 验证记录

```text
py_compile: routes_chapter.py / schemas.py / chapter_post_save.py /
            narrative_circuit_breaker.py / foreshadow_adapter.py /
            narrative_state_extractor.py / streaming_service.py

tests/test_foreshadow_adapter.py              10 passed（7 + 卷级 3）
tests/test_character_runtime_acceptance.py     5 passed
tests/test_pre_generation_gate.py             12 passed
tests/test_narrative_state_extractor.py       12 passed（8 + 滚动/首尾 4）
tests/test_narrative_metrics.py                9 passed
tests/test_narrative_circuit_breaker.py       15 passed（13 + 重复检测 2）
tests/test_thinking_mode_disabled.py           4 passed（第二轮 3 + 消化步 1）
合并回归                                       67 passed
```

## 8. 新增/修改文件清单

新增：

- `backend/app/services/pre_generation_gate.py`
- `backend/app/services/narrative_state_extractor.py`
- `backend/app/services/narrative_metrics.py`
- `backend/app/services/narrative_circuit_breaker.py`
- `backend/tests/test_foreshadow_adapter.py`
- `backend/tests/test_character_runtime_acceptance.py`
- `backend/tests/test_pre_generation_gate.py`
- `backend/tests/test_narrative_state_extractor.py`
- `backend/tests/test_narrative_metrics.py`
- `backend/tests/test_narrative_circuit_breaker.py`
- `backend/tests/test_thinking_mode_disabled.py`（第二轮）

修改：

- `backend/app/services/foreshadow_adapter.py`
- `backend/app/api/v1/workflow/routes_chapter.py`
- `backend/app/api/v1/workflow/schemas.py`
- `backend/app/services/chapter_post_save.py`
- `backend/app/services/streaming_service.py`（第二轮：`disable_thinking` 参数）
- `docs/novel_pipeline_integrated_improvement_guide.md`（第三轮：实施基线标注，非代码）
- `backend/app/services/workflow_context_builder.py`（review_meta 顶层 merge，避免整包覆盖）
- `backend/tests/test_workflow_context_builder.py`（合并保留 narrative_state_v1）

## 2.19 评审「保存并继续」不再清空全书章节

问题：评审页点「保存并继续」后，列表只剩最新重生的一章。根因是 `save_stage_content` 在 `stage==review and continue_workflow` 时 `DELETE FROM chapters WHERE project_id=...`。

修复：

- 评审保存并继续、内容阶段保存：只覆盖当前最后一章旧稿，不删前面章节。
- 前端提示改为「改写当前章节（不会清空前面章节）」。
- 回归：`test_save_stage_content_review_continue_only_deletes_latest_chapter`。

## 2.20 章节初稿「保存并继续」改为原地更新，不再删章

初稿弹窗 `saveWorkflowStageContent('content', ..., continue)` 与「仅保存」原先都会 `DELETE` 当前最后一章；后续评审/迭代只写 `project_settings`，不会把该章写回 `chapters`，列表会缺章。

现改为 `UPDATE chapters SET content/word_count WHERE id=最后一章`。评审保存并继续不再改章节表（请求体是评审报告）。

## 2.21 Chroma 版本不兼容时不再复用已损坏 cleanroom

现网 chromadb 1.1.1 只支持 sysdb=9；主库/旧 fallback/旧 cleanroom 都已是 sysdb=10（含 00010-collection-schema），直接打开会 rust panic。旧逻辑复用同名 cleanroom，等于反复掉进空且同样不兼容的库。

现改为每次发现不兼容时新建带时间戳的 cleanroom。旧向量暂时读不到，但至少新写入可被当前运行时检索。完整回填需更高版本 chromadb 或从 chapters 重建。

## 2.22 生成进度被掐后不再被僵尸锁永久 409

前端断流/热重载后，生成任务执行体已死，但 Redis 锁可能仍被心跳续满 TTL。`force_release_stale` 只回收 TTL 过短的锁，于是页面显示中断、再点生成却一直「该项目正在生成章节中」。

现改为：拿锁失败且本进程该项目没有活跃 generate-next-chapter 任务时，`force_release` 无条件清锁再重试。真正在跑的任务仍 409。

判定依据是本进程登记的真实 syncio.Task（create_task 之后才写入），不是 task_id 集合：任务未完成 → 409；无任务或 done() → 清孤儿锁后重试。单机单 uvicorn 可分清；多 worker 仍可能误判（本进程看不到别机任务）。

## 2.23 刷新后恢复 generate_next_chapter

生成下一章的进度/完成 WebSocket 只认 Redux 里的 taskId。刷新后 running-tasks 虽返回 generate_next_chapter，前端只恢复 workflow_stage_*，于是页面空闲、后续事件全丢。现将该类任务写入 startGenerateNextChapter；若任务已结束则刷新章节列表。

## 2.24 评审保存并继续改为覆盖最后一章

评审/初稿「保存并继续」跑完迭代后，前端 autoSaveChapter 会 POST 新建章节，于是旧章保留、同名新章出现。现改为有最后一章则 PUT 覆盖；保存并继续会写入返回的 task_id，避免自动推进再开一轮。
