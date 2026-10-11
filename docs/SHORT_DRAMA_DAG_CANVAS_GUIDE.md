# 短剧板块 DAG 调度与画布式视图改造指南

> 版本：v1.0 ｜ 编制日期：2026-10-07 ｜ 适用工程：拾光工坊（novel_writing_agent）
> 母文档：`ai_director_os/AI_Director_OS_落地实施指导.md`（v1.6，§1.12 决策记录 / Phase 4.6 任务行）
> 文档定位：本指南是短剧板块「DAG 调度 + 画布式视图」改造的设计唯一事实源（沿用三层文档架构惯例：本指南承载设计契约与验收口径，执行进度另立实施日志，诊断取证另立分析文档）。仅阶段验收后批量更新，不随单次提交改写。

---

## 一、决策记录

### 1.1 画布形态决策（2026-10-07）

**决策：不采用无限画布（Canvas）作为短剧板块 v1.5 的主创作形态。** 依据四维评估：

1. **规划口径澄清**：母文档对 DramaClaw Freezone 的借鉴口径是「双轨制机制」而非「画布 UI」。SSOT JSON `10.3 exploration_track` 中「画布式」仅出现一次且为括号内比喻（描述探索轨素材组合自由度）；正式落点全部是数据与流程机制。附录 E.7 同时采纳 Shotkit「Files, not panels」哲学，与画布面板形态理念相反。
2. **架构适配性**：数据层已「画布就绪」（round×shot 寻址 / 内容哈希 pin / 依赖图 / 镜头级 API），执行层是线性状态机 + 单一 REWORK 回跳；真正的缺口是 10.4 节点级 DAG 调度器——它是连续剧集量产的刚需，不是画布的特供，不应记在画布账上。
3. **功能优势已被机制层兑现**：「满意一键推回」= ExplorationTrack 提交路径（强制重过 QC）；版本隔离 = round×shot + pin + contract_json 快照；非破坏性探索 = writes_canon=False + 编辑链预算不消耗。画布 UI 的净增量只剩依赖可视化与候选并排比较，二者用卡片墙 + 只读图视图即可承载。
4. **成本与风险**：画布 UI + 节点级 dispatch + 节点状态推送 + 前置 DAG 调度器估 5-8 周，直接冲击母文档 §六时间计划与 R10（窗口期里程碑）；节点级重做与 REWORK 整体返工语义重叠需重新统一；SPECULATIVE 状态引入 QC/计费/预算三处口径变化，扩大 R14 兼容风险面。

**采用中间路线：线性主管线 + 双轨机制 + 轻量画布式视图**，分三档推进（见 §三）。真无限画布列为 Phase 4 后评估项（档 C），触发条件见 §3.3。

### 1.2 SSOT JSON 不修改

`10.3 exploration_track` 的机制原则（不写 Canon / 不占编辑链预算 / 提交重过 QC / 开销计入项目预算但单镜上限减半）未变，变的只是 UI 承载形态——不属于知识体系内容，无需 v1.6 SSOT 修订。

### 1.3 与母文档的关系

- 母文档 §1.12 记录本决策摘要；Phase 4.6 为 DAG 调度器任务行，指向本指南档 B。
- 本指南不重复母文档的知识层内容（DC/CF/AM/R0-R6），只承载工程改造契约。
- 冲突时以母文档 + SSOT JSON 的机制原则为准；UI 与调度实现细节以本指南为准。

---

## 二、代码现状（2026-10-07 勘察，事实基线）

### 2.1 已落地（直接复用，不重建）

| 能力 | 位置 | 说明 |
|---|---|---|
| 探索轨双轨机制 | `pipeline/orchestration_kit.py` `ExplorationTrack` | try_record（writes_canon=False / consumes_edit_budget=False）+ commit（重过 QC）+ per_shot_cost_cap |
| 版本隔离寻址 | 同上 `shot_address` | round×shot 寻址，round 2 永不覆盖 round 1 |
| 可复现锚点 | 同上 `pin_run_inputs` / `verify_reproducibility` | run.json 内容哈希 pin（prompt/config/storyboard/contracts/source_version） |
| 逐资产成本台账 | 同上 `CostLedger` | 按镜头与模型聚合，payload['cost_ledger'] |
| 重试只补失败项 | 同上 `select_retry_items` | 成功项复用缓存，不重复付费 |
| 镜头依赖图 | `agents/camera_states.py` | depends_on_state_ids + start/end state 契约 + recalculate_state_transitions |
| 景别分组树 | `agents/camera_tree.py` | 依赖图可视化数据源之一 |
| Story Graph | `agents/scripter_pkg/_story_graph.py` | 角色/关系/时间线可查询图 |
| 镜头级任务 API | `backend/app/api/v1/dreamweaver_api/routes_script.py` | `/runs/{run_id}/video-jobs/{shot_id}/confirm-async`，含 depends_on_shot_id 依赖校验 |
| 历史数据隔离 | `backend/app/models/dreamweaver.py` | PG 五表 + contract_json 快照 + ShotSchemaV2 兼容读 |
| 线性编排 | `pipeline/state_machine.py` | INIT→SCRIPT→…→REVIEW→DONE + REWORK 回跳 + 三人工门 |
| reactflow 依赖 | `frontend/package.json`（^11.11.4） | 小说板块 RelationshipGraph / CharacterCardManager 已在用，画布技术选型成本≈0 |

### 2.2 未落地（本指南改造范围）

| 缺口 | 证据 | 归属 |
|---|---|---|
| 10.4 节点级 DAG 调度器 | `pipeline/` 全目录检索 SPECULATIVE / critical_path / scheduler 零命中；SSOT JSON 10.4 仅有原则（task_granularity 8 类 / readiness_contract / serial_vs_parallel / critical_path / resource_scheduler） | 档 B |
| 镜头卡片墙 / 探索轨面板 / 依赖图视图 | `DreamWeaverRunPage.tsx` 现为五步线性预览（脚本→分镜→资产→镜头→成片），无并排对比与探索轨入口 | 档 A |
| Celery 任务粒度 | 任务以整个 run 为单位，agent 包（scripter/painter/dreamweaver）为 `run(ctx)` 粗粒度入口、内部按镜头循环——包内逻辑已逐镜可独立执行，但外层无节点级任务队列 | 档 B |

---

## 三、改造目标（分三档）

> 严格区分：档 A/B/C 均为净新增能力，不推翻 §2.1 任何已落地机制；档 A 不依赖档 B，档 C 依赖档 B。

### 3.1 档 A · 镜头板视图（立即做，估 1-2 周）

在 DreamWeaverRunPage 现有五步预览之上增量叠加，不改变线性主管线与三人工门：

- **A.1 镜头卡片墙**：round×shot 网格布局；同镜多 round 并排对比（数据源 `shot_address` + runs/{run_id}/ 产物）；R-pre 双候选缩略并列；每卡片成本角标（数据源 CostLedger.by_shot）；卡片点击进入既有单镜操作（video-jobs confirm-async 等）。
- **A.2 探索轨面板**：探索候选区展示 ExplorationTrack.attempts（含试错成本）；「满意一键推回」按钮走 ExplorationTrack.commit 提交路径（后端强制重过 QC，前端明示该语义）；面板内显示单镜探索预算余量（per_shot_cost_cap，主轨减半规则）。
- **A.3 依赖图只读视图**：reactflow 渲染 camera_states 依赖图（节点=镜头 state，边=depends_on_state_ids；camera_tree 分组着色）；服务三人工门审批——「改这镜会波及哪些下游」一目了然；只读，不提供拖拽连线改依赖（依赖变更仍走管线，防绕过 readiness 校验）。

**档 A 验收口径**：
1. 卡片墙同镜 ≥2 round 并排可见且成本角标与 CostLedger 一致；
2. 探索轨提交后产物进入 round+1 寻址且 QC 重过（有测试用例）；探索轨预算超限被拦截；
3. 依赖图视图节点/边数与 camera_states 输出一致（快照对拍测试）；
4. 五步线性预览与三人工门行为零回归（既有测试全过）。

### 3.2 档 B · Episode Production Scheduler（10.4 DAG，量产刚需，对应母文档 Phase 4.6）

把 SSOT JSON 10.4 原则实现为节点级调度器，落点 `pipeline/`（新模块，不重写 state_machine 骨架）：

- **B.1 节点模型**：按 10.4 task_granularity 八类（Design/Asset/Generation/Repair/QC/Editorial/Commit/Delivery）把 run 编译为 Production DAG；节点身份 = round×shot 寻址 + 内容哈希 pin（复用 orchestration_kit，不另造寻址）。
- **B.2 readiness contract**：Hard Prerequisites 未满足不启动；Soft Reference 未锁可进 SPECULATIVE 状态生成低成本候选但禁止 Commit；涉及 Knowledge/关键 Prop/身份的 Hard State 镜头禁止 Speculative Final；上游 Accepted State 变化后按 Read Set 判定是否取消下游。
- **B.3 串行/并行判定**：落实 10.4 serial_vs_parallel 三类 + 禁止伪并行（后镜依赖前镜未选定 Take 时不得同时生成）。
- **B.4 关键路径**：Criticality = Path Slack^-1 × Failure Risk × Dependency Reach × Delivery Weight；Slack≈0 最高优先级，前置设计不稳定时优先解决设计/Reference 而非盲目加生成次数。
- **B.5 资源池调度**：按资源池区分（Premium Video API / Fast Draft API / Voice / Upscale / Human QC）；每模型维护 concurrency_limit / rate_limit / p50-p95 成功率 / cost_per_attempt；多候选并行设 candidate_cap；高失败率镜头预留 Fallback Slot；人类审核是稀缺资源，安排 Review Batch。
- **B.6 与 REWORK 语义统一**：节点级修复（Repair Task 插入现有 DAG，不重建整集）替代「REWORK 整体回跳」成为主路径；REWORK 保留为场景级兜底（R6 场景重构）。编辑链衰减预算四止损继续生效。
- **B.7 计费与预算接线**：SPECULATIVE 候选走 Fast Draft 低积分档；探索轨节点开销计入项目预算但单镜上限减半（BudgetControl 三档熔断按节点接线）。

**档 B 验收口径**：
1. 同场互不依赖镜头并行、状态接力镜头串行的调度测试（构造 DAG 断言启动顺序）；
2. SPECULATIVE 节点产物无法 Commit（硬拦截测试）；
3. 关键路径镜头在资源紧张时优先获得槽位（优先级注入测试）；
4. Repair Task 插入不触发整集重建（既有 round 产物哈希不变）；
5. 逐节点成本可见且与 CostLedger 汇总一致；
6. 三人工门与阶段契约（STAGE_CONTRACTS）零回归。

### 3.3 档 C · 真无限画布（Phase 4 后评估，本期不做）

**触发条件（全部满足才立项评估）**：
1. 档 B 调度器已落地并通过验收（画布只是调度器之上的视图绑定层）；
2. SaaS 用户数据显示高阶创作者存在「跨镜头自由组合探索」的真实高频需求（非营销假设）；
3. 档 A 卡片墙 + 依赖图视图的替代能力经用户验证确不足够。

**设计约束（届时生效）**：画布节点状态（queued/running/failed/speculative）必须与档 B 调度器状态机一一对应，禁止 UI 侧私有状态；自由连线必须过 readiness contract 校验；画布操作全量进调用审计。

---

## 四、边界与约束

1. **不修改**：SSOT JSON、`10.3 exploration_track` 机制原则、三人工门、STAGE_CONTRACTS 阶段契约、contract_json 快照兼容策略（R14）、确定性渲染原则。
2. **不引入**：画布私有数据格式（产物寻址只认 round×shot + 内容哈希，Files not panels）；UI 侧绕过 QC 的提交路径；与 BudgetControl 并行的第二套计费口径。
3. **兼容读**：档 A 前端新视图全部基于既有 RunResponse 兼容层 + orchestration_kit payload 键增量下发，不新增破坏性字段。
4. **TDD**：档 A/B 每项验收口径先写失败测试再实现（沿用项目 test-driven-development skill）。

---

## 五、实施顺序与依赖

```
档 A（A.1/A.2/A.3 可并行，无前置） ──► 用户验证反馈
                                          │
档 B（B.1→B.2→B.3/B.4→B.5→B.6/B.7）  ◄────┘（反馈修正验收口径）
                                          │
档 C 评估（触发条件 §3.3 全满足才立项） ◄──┘
```

档 A 与档 B 可并行开工（A 不依赖 B）；档 B 内部 B.1 节点模型是一切前置。

---

*本指南 v1.0（2026-10-07）依据母文档 v1.6 §1.12 决策设立；勘察事实基线见 §二（当日核验：orchestration_kit / state_machine / routes_script / camera_states / DreamWeaverRunPage / frontend package.json）。执行中按档验收滚动修订，修订仅更新本文档；涉及机制原则变更时同步母文档与 SSOT JSON。*
