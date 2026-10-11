# AI Director OS 落地实施指导文档

> 版本：v1.1 ｜ 编制日期：2026-08-17 ｜ v1.1 修订：2026-08-18（融入执行层开源工程实践，见 §1.5 与附录 C）｜ v1.3 修订：2026-10-07（多智能体生产体系外部对照，见 §1.7 与附录 D）｜ v1.4 修订：2026-10-07（Agent Skill 生态与论文新进展对照，见 §1.9 与附录 E）｜ v1.5 修订：2026-10-07（短剧板块推翻重建决策与勘察映射，见 §1.11 与附录 F）｜ v1.6 修订：2026-10-07（短剧画布形态决策与 DAG 调度器单列，见 §1.12 与 `docs/SHORT_DRAMA_DAG_CANVAS_GUIDE.md`）｜ 适用工程：拾光工坊（novel_writing_agent）
> 源资产：`ai_director_os/` 三件套（JSON 知识库 296KB / XLSX 数据库 / DOCX 主文档）

---

## 一、项目背景

### 1.1 源体系

AI Director OS V5.0 是一套为 AI 短剧生产设计的「导演决策操作系统」知识体系，以三件套形式交付：

| 件 | 内容 | 角色 |
|---|---|---|
| JSON（Agent_Training） | 37 DC 导演决策案例、102 CF 失败案例、7 域 94 知识单元（含 2026-10 新增 24 个：12 外部借鉴 + adaptation_resource_protocol + 图片层补强 8 单元 + 瑕疵美学 [大象学长第5集，含方言就绪词表] + 视频模型能力演进观察 [大象学长第7集：文内分镜/视频延长/参考三角色 pending 不改架构；生成端声音 2026-10 证据升级为既定路径——已成业界标配、音色参考可用，四轨声音方案（环境音/动作音效生成端原生、对白生成端音色参考、旁白后期 TTS、BGM 后期）作为 Phase 2 增量接入] + 网格化探索工作流 [大象学长第9集：12宫格镜头候选探索 + 25宫格粗排故事板，网格层决策/精排层执行两层分离]；另回填 12 个 PENDING 单元：11 个摄影单元 + world_space [空间地图/先全景后近景/参照物锚定尺度，Higgsfield 长片工作流·大象学长第27集]；model_prompt_dialects 扩展反泛词原则、即梦2.0参考视频移植观察与 L7 Seedance 视频方言公式 [主角@环境@动作@风格@节奏，方言组装就绪]；character_consistency_advanced 扩展 L5 casting 资产包 [视频生成必带角色特写参考] 与 L6 纯AI演员策略 [肖像权规避]；upscaling_pipeline 扩展 L4 后处理提质三件套 [光影重塑/人物优化/材质迭代]，登记于 knowledge_units 板块）、17 AM 系统模块（含 AM-15 视频评价 / AM-16 模型原理修复 / AM-17 知识调度）、R0-R6 修复路由、知识治理协议 | 机器可读 SSOT（唯一事实源候选） |
| XLSX（Database） | 60 Sheets 结构化镜像 | 人读数据库视图 |
| DOCX（Master） | 10 卷章节 + 附加节（4.1.2/4.1.3 切换与转场库、4.4 修复决策、5.1.2 双视角修复、2.1.3/2.1.4 摄影决策表等） | 人读知识文档 |

体系核心能力：知识调度三通道（L1 失败码直索 / L2 结构化触发器 / L3 索引化语义检索）、三触发（T1 失败修复 / T2 分叉决策 / T3 风险前置）、防炫技护栏（动机门禁 / 删除测试 / 炫技率审计）、双视角修复（repair 导演视角 + repair_model 模型原理视角）、编辑链衰减预算、知识治理生命周期（source_type / verification_status / trust_weight）。

### 1.2 目标工程现状

拾光工坊（novel_writing_agent）为三板块全栈平台，必须按产物分层理解，不能把三个板块写成同一套待改造流水线：

- **小说板块（原文层）**：11 Agent 工作流、模块化 Prompt 组装器、RAG、一致性校验、实体提取、双通道反馈回路。**叙事质检已部分落地**：narrative_quality.py 定义 12 个小说失败码（轻/重两档），评审输出「失败码|严重度|证据」，routes_chapter.py 解析后路由局部修订或整章重写，并维护项目级问题记忆与伏笔账本（review_meta）；失败案例在 narrative_failure_cases.json，按场景类型触发。
- **有声书板块（派生层）**：章节原文只读改编为独立 script_json；TTS、voice_consistency_manager、混音管线；已审核剧本禁止 full 重跑从原文覆盖。
- **短剧板块（派生层 + 执行层，v1.5 起重建）**：旧创作链为 scripter.py 把章节文本改写为 Markdown 剧本（节拍是文本行、无结构化 beat）、storyboarder_pkg 的 _shot_profile 为 12 个硬编码镜头模板按索引循环、_frame_prompt 拼接式首尾帧——**此三块 v1.5 决策推翻重写**。但基建与雏形丰富（2026-10 勘察，见附录 F）：六厂商适配器（含剪映 JianyingAPIAdapter）、camera_states 镜头依赖图（10.1 State Engine 雏形）、best_image_selector 图片层加权择优（R-pre 雏形）、autoqc_pkg 13 类失败码 + 修复路由（CF/R0-R6 雏形）、状态机三人工门、Celery + PG 五表 + contract_json 快照机制。
- **平台层**：积分计费、用户中心、管理后台、content_safety_checker

### 1.3 差距结论（v1.5 按代码校正）

工程骨架成熟。差距不在「小说还没有叙事知识」，而在「导演操作系统尚未挂到派生剧本与视听执行层」。

- **小说原文层已有质检闭环**：失败码、修订路由、问题记忆、伏笔账本已在运行。缺口是补强（纯 JSON 字段、删除测试栏、优先级公式），不是从零建 config/narrative_knowledge/，更不是把短剧 DC 翻译进写章节的 prompt。
- **短剧：推翻重建而非增量注入（v1.5 决策）**：旧方案「向 storyboarder 注入决策」取消——scripter / storyboarder 核心逻辑（Markdown 剧本、硬编码镜头模板、拼接式首尾帧）直接删除原地重写为知识驱动的**剧本引擎 + Shot Contract 引擎**（代码路径不变）；autoqc / camera_states / best_image_selector 已有雏形，升级对齐 CF 库、10.1 State Engine、R-pre 即可——重建成本低于增量改造（勘察映射见附录 F）。
- **产物分层，禁止混注**：小说原文是内容源；有声剧本、短剧剧本是派生资产。改编不改动小说原文，因此小说改编电影/短剧不会污染小说正文。DC/CF/Shot Contract 只允许注入派生层与执行层。
- **可共享的是调度协议，不是同一份决策内容**：失败码结构、治理字段、调用审计、Learning Loop 可跨板块复用；小说 NF 与短剧 CF/DC 内容分离，禁止把镜头决策灌进小说创作 agent。

### 1.4 市场背景（决策依据）

- 国内 AI 短剧：产量占 95.3%、播放量仅 4%，万播收益跌至 5-25 元，量产模式已死
- 行业三层结构：低端流量剧（死亡）→ **人机协同精品（利润核心，本工程卡位）** → 高端真人剧
- 海外市场 2026 预计 60 亿美元，AI 剧占上新 87%，分成 70-80%
- 监管：2026-09-01《微短剧发展管理办法》AI 标注、分层备案、11 条红线——合规者受益
- 窗口期约 1-2 年（大厂全链路入场前）

### 1.5 执行层工程实践参照（开源技能生态调研，2026-08-18）

本指导的知识层（DC/CF/AM/R0-R6）最终要落在真实执行链上，而体系现状止步于「生成→QC→修复」，缺「剪辑合成 / 渲染 / 批量」执行层。为此调研六个开源 Agent 技能，只提炼**可沉淀为工程约束**的要素（完整摘录见附录 C）：

| 技能 | 定位 | 提炼的工程化要素 | 落入本指导 |
|---|---|---|---|
| OpenMontage | Agentic 全链制片系统（12 流水线 / 52 工具） | 分级质检（合成前验证→渲染后 ffprobe 自检→人工闸门）、预算管控（总额/单步阈值/超限审批）、流程回放审计 | Phase 2.5/2.6、3.1、4.4 |
| HyperFrames | HTML→确定性 MP4 渲染框架 | 确定性渲染（帧号 = floor(time×fps)，同输入同输出）、合成即代码（可版本管理/可 diff）、lint→预览→渲染闭环 | §3 关键约定、Phase 2.7 |
| Remotion Skills / video-shotcraft | React 程序化视频 + 镜头配方卡库 | 数据集批量渲染、平台画幅预设、配方卡字段（用途/能量/时长/参数/坑点）、节奏卡点 | Phase 2.3/2.7、4.5 |
| FFmpeg Skill | 媒体处理命令词典 | 流拷贝 vs 重编码决策规则、编码基线（CRF/yuv420p/faststart）、坑位参考先行 | Phase 2.5、§8.2 |
| video-use | 真人素材对话式剪辑 | 文本+按需视觉双层读取（词级时间戳主视图）、切点 30ms 音频淡变、词边界剪辑、自评估修复循环 | Phase 2.5 |
| Manim | 数学/科普动画管线 | 内容类型化时长表（揭示后强制呼吸等待）、透明度分层构图、草稿低清/终稿高清分层渲染 | Phase 2.3、§8.3 |

**采纳原则**：只收编「确定性、分级、词典化、模板化」这类可验证的工程约束；执行工具本身保持外接、不进知识 SSOT——决策层管「该不该、对不对」，执行层管「怎么做、可复现」，两层解耦。

---

### 1.6 v1.2 修订要点（相对 v1.1）

1. 纠正「小说缺叙事知识库」：代码已有失败码、修订路由、问题记忆与伏笔账本。
2. 纠正「媒介无关故三板块共享决策内容」：只共享调度协议；DC/CF 不得注入小说创作 agent。
3. 明确产物分层：小说原文是源，有声/短剧剧本是派生资产；改编不回写原文，因此不会污染小说正文。
4. Phase 1 从「新建五文件中枢」改为「盘点补强 + 混注门禁」；短剧导演层不再被小说知识库 MVP 阻塞。

### 1.7 多智能体生产体系对照（开源与论文调研，2026-10-07）

对标 9 个外部项目/论文（与 §1.5 执行层调研互补、不重叠），提炼要素已全部写入 SSOT JSON（完整摘录见附录 D）：

| 项目 | 定位 | 提炼的借鉴要素 | 写入位置 |
|---|---|---|---|
| Co-Director（Google, arXiv 2604.24842） | 生成式叙事全局优化（首个形式化） | MAB 创意配置探索 + AM-15 因子化奖励回传；分层创意参数化 θ 防子 Agent 语义冲突与级联漂移 | 10.7 creative_config_bandit；10.5 hierarchical_creative_config |
| AniMaker（SIGGRAPH Asia 2025） | MCTS 驱动动画叙事 | MCTS-Gen 生成前候选择优（只扩展高分分支）；AniEval 多镜头评价四组维度 | 10.6 candidate_selection_gate；AM-15 评价层 + 知识单元 hybrid_review_protocol |
| AnimeAgent（vivo/UESTC, arXiv 2602.20664） | I2V 分镜生成 | 迪士尼两阶段关键帧法（I2V 轨迹 → 极限帧）；混合主客观评审（CLIP 对艺术变形不敏感、MLLM 评分不稳） | DC-037 + 知识单元 disney_two_stage_keyframe / hybrid_review_protocol |
| FilmAgent（HITsz, arXiv 2501.12909） | 3D 虚拟空间多 Agent 剧组 | Debate-Judge / Critique-Correct-Verify 协作算法；闭合动作词典拦截动作幻觉 | 10.5 collaboration_protocols；知识单元 closed_action_lexicon |
| ArcReel（AGPL, 5.2k★） | 小说→成片自托管工作台 | 重试只补失败项；版本并排对比；逐资产成本可见；剪映草稿导出 | 10.4 retry_discipline / cost_visibility；10.2 version_compare_protocol；Phase 2.7 |
| DramaClaw（Elastic, 3.8k★） | 短剧工业管线 | Story Graph（角色/关系/时间线可查询图谱）；Freezone 双轨探索（试错不污染版本链） | 知识单元 story_graph_ingestion；10.3 exploration_track；Phase 2.2 |
| Toonflow（AGPL, 10k★） | AI 短剧工厂 | 骨骼绑定防脸变形（高动态场景从 prompt 修复升级为机制锁定） | 知识单元 skeleton_binding_high_motion；CF-021/029/082 repair_model |
| AI168漫剧（Apache 2.0） | 漫剧全自动流水线 | 角色四视图参考图（与 Co-Director 多角度拼图独立收敛验证） | 知识单元 multi_angle_reference_collage |
| ViMax（HKUDS, MIT, 3.5k★） | 12 Agent 视频创作框架 | 上下文压缩 / 会话复用 / 渲染检查点断点续传 | 10.5 context_discipline |

**关键判断**：9 个项目均无结构化失败库、修复路由与知识治理——本体系差异化仍在知识层；唯一被反超的维度是 Co-Director 的全局优化（本次已补入 10.7），且 MAB 与知识库互补而非互斥：MAB 探索创意配置，知识库保证每个配置被专业执行。

### 1.8 v1.3 修订要点（相对 v1.2）

1. SSOT JSON 共 24 处修改：DC-037、7 个外部借鉴知识单元（新顶层板块 knowledge_units，含 depends_on 依赖追踪——同步落地既有 P1 建议）、3 个 CF 骨骼绑定修复路径、AM-15 混合评审升级、10.2/10.3/10.4/10.5/10.6/10.7 共 10 个新字段。
2. Learning Loop 补上探索半边：既有修复成功率统计 + experience_preload 是纯利用（exploitation），新增 MAB 创意配置探索（exploration），两者并行。
3. 择优前移：R-pre 候选择优门位先于 R0，在高价值 beat（情绪爆发/信息揭示/冲突动作族）的视频生成前完成候选筛选，压低 R4 整镜重生成率。
4. 知识治理扩展：source_type 新增 external_paper（同行评审证据，初始信任 0.7）/ external_opensource（工程实践证据，0.6），升级条件同 B 级（5 次调用 + 删除测试全过 → A）。

### 1.9 Agent Skill 生态与论文新进展对照（2026-10-07 第三轮）

对标 15+ 个外部对象（Skill 集合、剪映工具链、论文新进展，与前两轮零重叠），提炼要素已写入 SSOT JSON 与本文档（完整摘录见附录 E）：

| 项目 | 定位 | 提炼的借鉴要素 | 写入位置 |
|---|---|---|---|
| Crayotter（开源, 2026） | 制品接地的长视频编辑 | **轨迹级 RLVR 三层级联奖励**（可验证编辑信号+LLM-judge+人类偏好校准，GRPO）+ 制品接地反思（失败定位到时间线段） | 10.7 trajectory_rlvr |
| MAViS（EACL 2026） | 长序列视频叙事全栈 | **3E 阶段完整性原则**（Explore/Examine/Enhance，不完整不交接）；**剧本-生成器兼容性指南**（剧本适配生成模型能力限制） | 10.5 stage_completeness_3e；知识单元 script_generator_compatibility |
| CHIEF（ICML'26 WS） | 人机共创视频生成 | **persona-conditioned 多观众人格看片反馈**（钩子留存/情绪曲线/弃剧点） | AM-15 产出层 + 10.7 audience_persona_feedback |
| InfinityStory（Adobe） | 无限长视频世界一致性 | **地点锚定规划**（VBench 背景一致性 88.94 最高）；**多主体感知转场**（入画/出画建模） | 知识单元 location_grounded_planning |
| MM-StoryAgent（阿里 X-PLUG） | 沉浸式故事书视频 | 吸引力导向多阶段写作；多通道音频 | 并入 script_generator_compatibility |
| VChain（ACL 2026） | 视觉思维链 | **稀疏关键帧快照**：MLLM 在关键节点生成推理中间态引导生成 | 知识单元 sparse_keyframe_cot |
| AI漫剧Skills（gitee v9.0） | AI 短剧分镜技能集 | **内运动优先**（固定镜头+画面内动态+微运镜分级+动态密度自检）；**模型分档时长参数化**（段/单镜上限随模型版本标定） | 知识单元 internal_motion_priority / model_tiered_duration |
| Shotkit（Apache 2.0） | 五技能预生产系统 | **brand-lock 品牌锁定**；**round×shot 寻址 + 内容哈希 pin**；**critique.json 机读裁决闭环** | 10.2 reproducibility_addressing；10.6 machine_readable_critique；4.5 |
| 剪映工具链（pyJianYingDraft / VectCutAPI / JianYing MCP / capcut-mate / capcut-cli） | 剪映草稿程序化控制 | 轨道/转场/滤镜/关键帧全能力 API；**双剪辑师模式**（同一时间线输入按 output_target 路由 DaVinci/剪映/两者） | Phase 2.7 实现选型 |
| MoneyPrinterTurbo（128k★） | 短视频全自动工厂 | 跨平台一键发布 + **YouTube 自动 AI 标注**；SKILL.md agent 自安装工作流 | Phase 4.3 |
| TerminalSkills ai-video-generator | 短视频生成 Skill | HOOK(3s)/BODY/CTA 结构；150wpm 语速预算公式（词数=时长×2.5） | 并入 script_generator_compatibility |
| MovieAgent / StoryAgent / Cinematic Director | 对照确认 | 场地管理员角色 / LoRA-BE 定制 I2V / 连续性锚+单镜单动作 | 已有对应（AM-03 / 骨骼绑定+DC-037 / Shot Contract+五重 DNA），不重复集成 |

### 1.10 v1.4 修订要点（相对 v1.3）

1. SSOT JSON 共 12 处修改：5 个新知识单元（总数 82）、10.7 两个新字段（trajectory_rlvr / audience_persona_feedback）、10.5 stage_completeness_3e、10.2 reproducibility_addressing、10.6 machine_readable_critique、AM-15 产出层 persona 观众通道。
2. **Learning Loop 三级爬坡定型**：统计回写（现状）→ MAB 创意探索（v1.3）→ 轨迹级 RLVR（v1.4）——RLVR 前置条件 ≥500 条修复轨迹，Phase 3 实测数据积累后启动，不阻塞当前计划。
3. **剧本层薄区补强**（P2 已知缺口）：script_generator_compatibility 单元——生成器友好约束 + 吸引力结构（HOOK/CTA/悬念钩）+ 语速预算公式 + 多阶段写作。
4. **评价双信号**：导演标准分（专业质量）+ persona 观众分（观众反应）双轨输出，冲突时导演优先；观众分回流 Learning Loop 补齐 Audience Signal 空缺。

### 1.11 v1.5 修订要点（短剧板块推翻重建）

1. **决策**：短剧板块推翻重建——旧创作链（Markdown 剧本 / 12 硬编码镜头模板 / 拼接式首尾帧 prompt）**直接删除**，在原代码路径（scripter.py、storyboarder_pkg）**原地重写**为剧本引擎与 Shot Contract 引擎；不保留旧管线 fallback。
2. **勘察校正 §1.2/§1.3**：宿主已有五个雏形（autoqc 13 失败码+修复路由 / camera_states 依赖图 / best_image_selector 加权择优 / JianyingAPIAdapter / 三人工门），v1.2「storyboarder 仅粗分、auditor 无失败码」的判断过时——雏形升级对齐即可，重建成本显著低于原估计。
3. **Phase 2 重排为 8 任务**（2.1 知识挂载 → 2.2 剧本引擎 → 2.3 Contract 引擎 → 2.4 执行层适配 → 2.5 QC/修复升级 → 2.6 编排/版本/调度 → 2.7 合成双通道 → 2.8 全链验证），关键路径 2.1→2.2→2.3→2.5；「向旧 storyboarder 注入」类任务全部取消。
4. **数据兼容**：历史数据靠 contract_json 快照隔离（不迁移）；ShotSchemaV2 旧字段名保留兼容读；前端 RunResponse 走快照兼容层；积分预检按新阶段模型重新标价（风险 R14）。
5. 详细勘察与新旧映射见**附录 F**。

### 1.12 v1.6 修订要点（短剧画布形态决策与 DAG 调度器单列）

1. **决策：不采用无限画布作为短剧板块主创作形态**——DramaClaw Freezone 的借鉴口径本就是机制层双轨（10.3 exploration_track，已由 `pipeline/orchestration_kit.py` ExplorationTrack + round×shot 版本图 + 内容哈希 pin 落地），画布三大收益（非破坏性探索 / 版本隔离 / 满意一键推回）已由机制兑现；UI 层无限画布与「确定性渲染 / 可审计回放 / Files not panels」（附录 E.7）方向相悖，且节点级执行语义与线性状态机 + REWORK 回跳重叠、SPECULATIVE 状态引入 QC/计费/预算三处口径变化（扩大 R14 风险面）。
2. **中间路线**：镜头卡片墙（round×shot 并排 + R-pre 候选 + 成本角标）+ 探索轨面板（一键推回，提交重过 QC）+ camera_states 只读依赖图视图（reactflow 已在依赖中）替代画布 UI；真无限画布列为 Phase 4 后评估项，前置条件为 4.6 调度器落地 + 用户数据验证。
3. **10.4 Episode Production Scheduler 单列为任务 4.6**：现状 orchestration_kit 仅落地 retry_discipline / cost_visibility / exploration_track 三子件，readiness contract / SPECULATIVE / 关键路径 / 资源池的节点级 DAG 调度未实现（`pipeline/` 检索零命中）；此为连续剧集量产刚需，不记画布账。设计契约、三档实施计划（档 A 视图 / 档 B 调度器 / 档 C 画布评估）与验收口径详见 `docs/SHORT_DRAMA_DAG_CANVAS_GUIDE.md`。
4. **SSOT JSON 不修改**：10.3 机制原则未变，仅 UI 承载形态变化，不属于知识体系内容。

## 二、目标与范围

### 2.1 项目目标

**总目标**：将 AI Director OS 落地为「原文下游的导演操作系统」。小说原文继续走已有创作/质检链路并冻结为源；有声剧本与短剧剧本作为独立派生资产承接 DC/CF/AM；执行层补齐剪辑合成、分级质检与可复现渲染。形成「自有 IP（原文）→ 派生精品（剧本/视听）→ 学习回路降本」，而不是用同一套镜头知识改写三个板块。

**分层目标**：

| 层 | 目标 | 可验证结果 |
|---|---|---|
| 架构层 | 调度协议共享，知识内容分库 | 小说 NF 与短剧 CF/DC 分库；按产物注入，禁止跨层混注 |
| 原文层 | 盘点并补强已落地的小说质检 | narrative_quality.py + routes_chapter.py 可路由；补 JSON 字段/删除测试，不新建平行中枢 |
| 派生层 | 短剧/有声剧本挂载导演知识 | scripter/audiobook 只读章节，产出独立 script；Beat → Shot Contract 挂在剧本上 |
| 执行层 | QC/修复/合成可复现 | CF 命中、R0-R6、廉价自检先于 VLM、确定性渲染 |
| 进化层 | Learning Loop 实测运转 | 知识验证状态流转，修复成功率可统计 |
| 验证层 | 端到端全链 Demo | 冻结后的小说章节 → 有声书样章 → 短剧片段；原文不被回写 |

### 2.2 范围

**范围内**：
1. 小说原文层补强（盘点已有 12 码与 light/heavy 路由；评审改为可被路由直接消费的结构化字段；修订计划补优先级公式与删除测试栏）。**不做**：把短剧 DC/30 场景决策翻译进小说创作 prompt；不新建与 narrative_quality.py 平行的 config/narrative_knowledge/ 中枢。
2. 短剧派生层导演知识（scripter 只读章节生成独立剧本；Beat 桥接与 Shot Contract 12 字段挂在剧本而非小说正文；T3 预检、QC 挂 CF 库、R0-R6、AM-15、DC-035/036 注入 storyboarder）
3. 有声书派生层增强（声音 DNA 卡、演播评价=AM-15 变体、sound_design 注入；继续只读章节、独立 script_json）
4. 共享协议（调度结构、知识治理字段、Learning Loop、调用审计）。共享协议，不共享决策内容。
5. 端到端验证与基准数据采集（验证原文未被回写）
6. 剪辑合成/渲染执行层约束落地（确定性渲染、分级质检、命令词典化、批量渲染预挂钩——只定约束与选型，不自研引擎）

**范围外（本期不做）**：
- 自研生成模型（继续外接 6 家 API）
- 自研渲染/剪辑引擎（外接 FFmpeg + 代码化合成框架，HyperFrames / Remotion 二选一试点）
- 投放/买量/商业化运营层
- 三件套 DOCX/XLSX 的自动派生管线（落地后 JSON 为 SSOT，其余两件转为归档参考）
- 多租户 SaaS 化改造（仅预留积分计费挂钩点）

---

## 三、目标架构

```
┌──────────────── 叙事知识中枢（新建，工程级共享）────────────────┐
│  知识资产层                                                      │
│  ai_director_os/*.json（短剧 36DC+102CF+7域）                    │
│  prompts/narrative_quality.py + narrative_failure_cases.json   │
│  知识调度层（AM-17 实现）：L1 失败码直索 / L2 beat 路由 / L3 语义 │
│  知识治理层：source_type / verification_status / trust_weight    │
│  Learning Loop：调用审计四元组 → 验证 → 升降权                   │
└──────────────────────────────────────────────────────────────────┘
        │注入（builder.with_xxx）                │注入
   ┌────▼─────┐                          ┌──────▼──────┐
   │ 小说板块  │                          │  短剧板块    │
   │ 11 Agent │                          │ storyboarder │
   │ beat路由  │                          │ ShotContract│
   │ 失败码评审│                          │ QC(R0-R6)   │
   │          │                          │ 合成/渲染    │
   └────┬─────┘                          └──────┬──────┘
        │内容（自有IP）                          │素材
        └──────────► 有声书板块（声音DNA/演播评价）◄┘
```

**关键约定**：JSON 为短剧导演知识 SSOT；小说质检以 narrative_quality.py / narrative_failure_cases.json / review_meta 为已落地 SSOT，不另建平行五文件库。知识按产物分库，未登记不进对应检索池。小说原文只读供给派生层；改编产物不得回写章节。**剧本改编的文本来源与资源复用遵循 adaptation_resource_protocol**：唯一文本源为小说工程冻结章节（source_chapter_version 版本锁定贯穿派生链）；小说工程资源（人物卡/大纲/伏笔账本/实体库）与旧短剧存量资产（定妆图/历史产物/voice 绑定）按「识别→评估→复用→登记」协议只读复用并登记 provenance；复用是输入供给不是创作约束——剧本的独立性与艺术完整性优先，资源与艺术判断冲突时标记差异而非机械套用。合成/渲染层遵循**确定性渲染**原则（帧号 = floor(time × fps)，同输入必同输出）：修复复检可逐帧对比、批量渲染无漂移、可进 CI 回归。

---

## 四、详细实施步骤

### Phase 0 · 资产就位与基线（已完成大半）

| # | 任务 | 涉及位置 | 完成状态 |
|---|---|---|---|
| 0.1 | 三件套迁入工程 | `ai_director_os/` | ✅ 已完成（2026-08-17） |
| 0.2 | 确认 SSOT 约定 | `ai_director_os/README`（口头约定即可） | ✅ SSOT 约定已落地（JSON 为唯一事实源，XLSX/DOCX 归档只读，2026-10-07 确认） |
| 0.3 | 跑通小说板块现有链路并记录基线（1 章：生成耗时 / 评审六维分 / 修订轮次 / token 成本） | `backend/app/api/v1/workflow/` | ✅ 已完成（2026-10-07 降级模式）：`scripts/record_baseline.py` —— 失败码提取 2 个（HOOK_WEAK/DIALOG_STIFF）、revision_mode=light、机读 JSON 输出、extract_time 0ms（regex 即时）；真实基线需 LLM 在线（Phase 4.2 前置） |
| 0.4 | 跑通短剧板块现有链路并记录基线（1 镜：分镜→生图→视频，成功率/耗时/成本） | `/drama` 路由 | ✅ 已完成（2026-10-07 降级模式）：`scripts/record_baseline.py` —— 剧本引擎 1.1ms（fallback_structured，1 场）/ Contract 引擎 2.7ms（director_os_contract_v2，3 镜 15s）/ 修复路由 1.1ms（R3/CF-030）/ 全链 4.9ms；真实基线需 LLM+生图/生视频 API |

基线文件：`ai_director_os/baseline_phase0.json`（改造前后对比的依据）。

**验收**：两份基线报告（改造前后对比的依据）。

### Phase 1 · 盘点小说已有闭环 + 补强（不再从零建中枢）

小说失败码与修订路由已在运行，本阶段只补缺口，并明确与短剧知识的边界。

| # | 任务 | 详情 | 涉及位置 | 状态口径 |
|---|---|---|---|---|
| 1.1 ✅ | 盘点现有小说质检 | 以 NOVEL_FAILURE_CODES（12 码）+ narrative_failure_cases.json + review_meta 为 SSOT，写对照表；不新建 config/narrative_knowledge/ 五文件平行库 | backend/app/services/prompts/narrative_quality.py | **已完成（2026-10-07）**：勘察确认实际 13 码（7 轻 + 6 重，NEW_FACT_UNSOURCED 后补）；`FAILURE_CODE_OUTPUT_SPEC`（L50-60）约定输出行格式；regex 解析链 `_FAILURE_LINE_RE`→`extract_failure_codes`→`resolve_revision_mode`（light/heavy 二元路由）+ `STRUCTURAL_FAILURE_CODES`（STRUCT_BROKEN/STALL_NO_PROGRESS→硬停止）全部在线；cases 字段对齐 CF 规范（triggers/judgment_signals/prevention/repair_model）且 repair_model 已注入修订 prompt |
| 1.2 ✅ | 结构化字段补强 | 评审除散文报告外，增加可机读 failure_codes JSON 字段，减少正则从报告抽取 | workflow_runtime.py、agents.json、routes_chapter.py | **已完成（2026-10-07）**：新增 `backend/app/services/prompts/novel_enhancements.py` → `build_review_payload()` 评审完成后调用产出机读 JSON（chapter_number/revision_mode/failure_codes[{code,severity,class,evidence}]/has_heavy/quality_memory_top/foreshadow_open_count）；供 WS 响应/落库/修订计划消费（接线点在 routes_chapter 评审回调，一行调用） |
| 1.3 ✅ | 修订计划补栏 | iteration_coordinator 增加优先级公式依据 + 删除测试两栏；无效场景走删除而非修补 | agents.json | **已完成（2026-10-07）**：`novel_enhancements.build_revision_plan()`——优先级公式 `Revision Priority = Severity(HIGH3/MED2/LOW1) × Recurrence(1+0.5×quality_memory_hits) × ClassWeight(heavy1.5/light1.0)` + 每条带 `delete_test`（问题/if_damaged→repair / if_intact→delete 两栏）+ top_priority；quality_memory 复发加成（测试验证） |
| 1.4 ✅ | 边界门禁 | 代码与评审清单写死：短剧 DC/CF/Shot Contract 不得注入小说创作/修订 agent | builder / scripter / storyboarder 分入口 | **已完成（2026-10-07）**：`novel_enhancements.assert_no_director_knowledge()` fail-fast 门禁——扫描 prompt/agent_config/评审文本，命中 DC-0xx/CF-xxx/Shot Contract/七族/R0-R6/R-pre/AM-15+ 即抛 ValueError；`scan_novel_boundary()` CI 扫描模式（报告不抛错）；小说层现状勘察确认零 pipeline import、零 config/director_knowledge 访问（纯目录隔离已天然成立，本阶段补主动门禁） |
| 1.5 ✅ | 对照验证 | 同一章节只验证小说 NF 路由可消费；禁止用「注入短剧 DC 后小说分数上升」作为成功标准 | 测试章节 | **已完成（2026-10-07）**：`test_nf_route_heavy_vs_light` + `test_cases_fields_alignment` 回归确认 NF 路由与 cases 字段已落地（勘察校正经指导文档原标「待做」的保守估计——实际 NF 路由/repair_model 注入/T3 预防均在线运行）；门禁测试 `test_assert_no_director_knowledge_blocks_markers` + `test_scan_novel_boundary_catches_mix` 证明短剧知识无法进入小说层 prompt；测试 10/10 + 全量回归 75/75 |

**验收**：对照表完成；failure_codes 可被修订路由直接消费；修订计划含删除测试栏；门禁测试证明导演知识未进入小说正文 prompt。

### Phase 2 · 短剧板块重建（v1.5：推翻旧创作链，原地重写）

> 决策（2026-10-07）：旧创作链（Markdown 剧本 / 12 硬编码镜头模板 / 拼接式首尾帧 prompt）**直接删除**，在原代码路径原地重写；autoqc / camera_states / best_image_selector 等雏形升级对齐；历史数据靠 contract_json 快照隔离、不迁移。勘察与新旧映射见附录 F。

| # | 任务 | 详情 | 涉及位置 |
|---|---|---|---|
| 2.1 ✅ | 知识挂载 | SSOT JSON 拆分脚本（7 域 83 单元 + 37DC + 102CF + 17AM 按域导出）→ `config/director_knowledge/` 知识文件 + 挂载清单 + 完整性校验脚本（计数与 SSOT 对齐）。**已完成（2026-10-07）**：`scripts/split_director_knowledge.py` + 16 个派生文件（含 manifest 逐文件 SHA-256、往返校验、--check-only 模式）；T3 触发器 16 条（15 结构化 auto_trigger + CF-088 qc 内嵌 EMOTION_STALL_CHECK）；**2.2/2.3 急需的 6 个优先单元已回填**（shot_size_system / technique_interference_check / camera_lighting_prompt_lexicon / cinematography_decision_library / cut_technique_library / transition_library，从归档 DOCX 卷二/卷四提取，benchmark×4 + creator_tutorial×2）；另新增 adaptation_resource_protocol（剧本改编资源复用协议，用户决策）；再加 dialogue_coverage（AM-06 信息拥有者原则+五层覆盖）与 resonance_design（AM-10 Click→Watch→Share 三层钩子，DOCX 卷八回填）——**2.2/2.3 所需知识单元全部就位**；内容覆盖 31/83，余 52 个 index-only 单元按需回填 | 新建 `config/director_knowledge/` + 派生脚本 |
| 2.2 ✅ | 剧本引擎（重写 scripter） | 删除 Markdown 剧本生成逻辑。新流程：只读冻结章节 → Story Graph 摄取（角色/关系/时间线可查询图，story_graph_ingestion）→ 结构化剧本 JSON（场 → beat 数组：beat_id / family 七族 / 钩子标记 / 台词；遵循 script_generator_compatibility：生成器友好约束 + HOOK/CTA + 语速预算）→ CCV 协作环 + 闭合动作词典校验 → 3E 完整性门；保留 script_requires_review 人工审核门。**资源复用遵循 adaptation_resource_protocol**：唯一文本源=冻结章节（source_chapter_version 贯穿派生链）；小说工程资源（人物卡/大纲/伏笔账本/实体库）与旧短剧存量资产（定妆图/历史产物/voice 绑定）按「识别→评估→复用→登记」协议只读复用，provenance 四元组入审计；复用是输入供给不是创作约束，剧本独立性与艺术完整性优先（资源不匹配时艺术判断优先并标记差异，删除测试筛除无贡献资源）。**已完成（2026-10-07）**：`agents/scripter_pkg/`（8 模块：_knowledge/_story_graph/_schema/_generate/_ccv/_three_e/_run/_compat）+ `agents/scripter.py` 薄入口；新增 payload 键 script_document / story_graph；兼容层保留 script_text（Markdown 视图，旧标记齐全）/ script_entities / character_profiles / audio_markers 全契约；后端增量 3 处（persistence 收键 / resume 白名单 / routes_script 响应）；幂等短路与人工门保留；LLM 调用 3-4 次/剧本（图 1 + 生成 1 + CCV 1 + Enhance 按需）；无 LLM 降级路径；测试 6/6 通过 + 既有回归 19/19 | `agents/scripter.py` 原地重写 |
| 2.3 ✅ | Shot Contract 引擎（重写 storyboarder 核心） | 删除 _shot_profile 硬编码模板循环与拼接式 _frame_prompt。新引擎：beat 七族路由 → DC-035 运镜八映射 / DC-036 灯光八映射 / DC-037 关键帧来源分叉 / 五级景别系统 / 时长阈值（model_tiered_duration 按模型分档 clamp + 呼吸等待）→ Shot Contract 12 字段 → T3 预检套件（EMOTION_STALL_CHECK 等 16 触发器 + 光学一致性 + 技巧干涉预算）→ R-pre 高价值 beat 标记；保留 _duration 总时长再平衡与 _audio_sync 对白对齐机制。**已完成（2026-10-07）**：勘察发现旧 _run.py 调用 9+ 个未导入未定义函数（分片死代码，一跑即 NameError）——本阶段同时是修复；新架构 `_knowledge/_contract/_precheck/_frame_prompt/_run` 五模块，删除死文件 _shot_profile.py 与 _storyboard_builders.py；**确定性知识编译引擎（零 LLM 依赖）**：T2 七族路由 dispatch DC、景别选型（dialogue_coverage 五层+P1-P8 顺序）、运镜/灯光八映射（含服从度与参考图标记）、DC-037 两阶段法分叉、揭示后呼吸等待 ≥2s、R-pre 标记；T3 预检自动修复（光学矛盾焦距修正/技巧过载降级/快切×复杂运镜→内运动/EMOTION_STALL trim 6s）；兼容层输出 ShotSchemaV2 全字段 storyboard（head/tail state 差异驱动）+ 新增 shot_contracts 键；保留 _duration/_audio_sync/_video_subshots/_entities/_variation/camera_tree/camera_states；script_document 输入时镜数与时长由 beat 计划驱动（导演计划优先），script_text 降级路径沿用旧启发式；测试 5/5 + 串联端到端 + 回归 24/24 | `agents/storyboarder_pkg/`（_shot_profile / _frame_prompt 重写，_run 编排改造） |
| 2.4 ✅ | 执行层适配 | painter：best_image_selector 升级为 R-pre 门位（beat 价值分级 + 权重对齐镜头卡 12 字段）；参考图接入多角度拼图（multi_angle_reference_collage）。dreamweaver：引擎路由（slideshow / wan-i2v / t2v / kling_omni）保留，camera_states 升级为 10.1 State Engine（显式 End State = Start State + Verified Transitions 契约 + 状态域字段 + 修复后 State Transition 重算）；保留 viseme 口型与主体桥接。**已完成（2026-10-07）**：①R-pre 门位——新 `painter_pkg/_r_pre.py`（高价值族双候选、预算 ≤2/镜、门位元数据）+ `_keyframes.py` 逐镜候选数（t2i 4 处 + edit 2 处调用点全部按 shot 分级）；②语义评分权重对齐——`best_image_selector._semantic_weights`：帧 prompt 含 Contract 标记（景别/运镜/光照/画面要点/状态约束）时 description_accuracy 0.10→0.25（Contract 命中度优先）、quality 0.25→0.15，identity 恒 0.30；③State Engine——`camera_states.py` 每 state 显式 start_state/end_state + 轨迹级 transition_summary（verified/gaps/missing）+ `recalculate_state_transitions()` 修复后重算入口（2.5 修复路由消费）；④多角度拼图——`asset_library._character_views_for` 成本分级（主角四视图 front/bust_three_quarter/side/back、次要两视图、背景单正面，env 显式配置不被裁），importance 从 character_profiles 联动；测试 11/11 + 回归 35/35 | `painter_pkg` / `dreamweaver_agent_pkg` / `agents/camera_states.py` |
| 2.5 ✅ | QC / 修复升级 | autoqc 13 类 failure_type ↔ CF 库 L1 直索映射表（失败码→CF 编号→repair_model）；_routing.py 重写为 R0-R6 决策树（R2/R3 执行词典：流拷贝 vs 重编码、帧精确裁剪、loudnorm、词边界切点 30ms 淡变）+ 编辑链衰减预算四止损；vlm_utils 升级 AM-15：廉价自检前置（ffprobe/帧采样/音频）→ 混合评审（客观通道 + MLLM 仲裁 + 跨镜头维度）→ persona 观众双轨 → critique.json 双格式输出。**已完成（2026-10-07）**：①CF L1 映射——新 `autoqc_pkg/_cf_map.py`：13 failure_type 静态映射（电影语言类直索 CF-109/110/034/030/028/015/029/014，基建类标 R 级走资产层，semantic/overall 标 L3 兜底）+ 惰性加载 CF 库（102 案例，repair_model 优先）+ `mapping_report()` 覆盖率审计；②R0-R6 路由知识层——`_routing.py` 增量升级（接口不变）：`_route_base`（原逻辑）+ `_apply_repair_knowledge`（action→R 级映射 + cf_hits + R2/R3 执行词典 + `recalculate_state_transitions` 标记 + 双视角修复纪律）+ `_enforce_edit_budget`（四止损：R3 轮次 ≥2 / 资产轮次 ≥3 / 同类失败重复 ≥2 → 强制 R3→R4 升级 rerun_video）；③AM-15——新 `autoqc_pkg/_am15.py`：四阶段（廉价自检 ffprobe/blackdetect/freezedetect→混合评审客观否决权限物理类+跨镜头 transition_summary 客观输入→persona 三人格双轨（导演优先 Soft Gate）→markdown+critique.json 双格式，repair_dispatch 直接供路由消费），VLM 注入式回调（无 VLM/无文件全降级但骨架完整）；auditor/编排接线留 2.6；测试 10/10 + Phase 2 全量回归 45/45 | `pipeline/autoqc_pkg/` + `agents/auditor.py` + `agents/vlm_utils.py` |
| 2.6 ✅ | 编排 / 版本 / 调度 | 状态机阶段语义强类型化（ctx.payload dict → 阶段契约）；三人工门对齐 human_gates 与知识调度点；handoff 加 3E 门位 + 上下文纪律；版本图 round×shot 寻址 + 内容哈希 pin（10.2）；重试只补失败项 + 逐资产成本可见（10.4）；修复试错走探索轨（10.3）。**已完成（2026-10-07）**：新 `pipeline/orchestration_kit.py` 编排套件六件套——①阶段契约 `STAGE_CONTRACTS`（8 阶段 required/optional 产出清单）+ `check_stage_handoff`/`record_stage_handoff`（3E Examine 门位，默认 warn 不阻断、DREAMWEAVER_HANDOFF_MODE=block 可阻断，run_until_done 单点记录 payload['stage_handoffs']）；②版本图 `shot_address` round×shot 寻址（round 2 永不覆盖 round 1）+ `pin_run_inputs` run.json 内容哈希 pin（prompt/config/storyboard/contracts/source_version 全固定）+ `verify_reproducibility`（match/drift 复现验证）；③`select_retry_items` 重试只补失败项（成功项复用缓存，不为已成功素材重复付费）；④`CostLedger` 逐资产成本台账（模型/token/秒数/费用，按镜头与模型聚合，payload['cost_ledger']）；⑤`ExplorationTrack` 探索轨（试错不写 Canon、不占编辑链预算，提交强制重过 QC）；⑥`run_am15_stage` AM-15 编排接线（REVIEW 分支：双格式报告挂 payload['am15_report'] + repair_dispatch 供修复路由，失败静默降级；2.5 遗留接线完成）；state_machine 仅 2 处最小插入（run_until_done handoff 记录 + REVIEW 分支 AM-15），阶段流零改动；三人工门（WAITING_SCRIPT_APPROVAL/WAITING_APPROVAL/WAITING_VIDEO_CONFIRMATION）原样保留即已对齐 human_gates；测试 10/10 + Phase 2 全量回归 55/55 | `pipeline/state_machine.py` + backend tasks |
| 2.7 ✅ | 合成双通道 | editor.py 合成能力保留，统一编码基线（CRF/yuv420p/faststart）+ 确定性渲染验证；JianyingAPIAdapter 接入剪映草稿导出（工具链选型与双剪辑师模式见附录 E.8；宿主 JIANYING_MCP_GUIDE 衔接）。**已完成（2026-10-07）**：①编码基线——editor.py 两处重编码路径注入 `-crf 20`（与既有 libx264/yuv420p/+faststart 组成完整基线，源码级测试防回归）；②新 `agents/synthesis_kit.py`——`ENCODING_BASELINE` 受控常量 + `encoder_args()`（禁止即兴拼接）+ `verify_encoding_baseline()`（ffprobe 校验 codec/pix_fmt + moov-before-mdat faststart 检测，无文件/无 ffprobe 降级不阻断）；③剪映草稿导出——`export_jianying_draft()`：离线生成 draft_content.json（pyJianYingDraft 社区最小结构 v3：materials.videos/audios/texts + 三轨 tracks + fm 溯源）+ jianying-editor-report.md（Windows/macOS 导入路径 + 手动任务清单，对齐 video-agent-jianying-editor 报告模式），云端控制可选 JianyingAPIAdapter（adapters/model_adapters L1024）或 VectCutAPI；④`run_synthesis_dual_channel()` 双通道编排挂 REVIEW 阶段（通道 A merged.mp4 基线校验 + 通道 B 剪映导出，DREAMWEAVER_JIANYING_EXPORT 开关，报告挂 payload['synthesis_channels']）；测试 8/8 + Phase 2 全量回归 63/63 | `agents/editor.py` + adapters |
| 2.8 ✅ | 全链验证 | 新引擎 3 镜样例全链：Story Graph → 剧本引擎 → Contract → T3 → 生成 → R-pre → AM-15 → R0-R6 → 合成双通道；含 MAB 创意配置首次采样（10.7）。**已完成（2026-10-07，降级模式）**：`scripts/verify_full_chain.py` demo 脚本——8 阶段链路贯通（script 带降级 family 演示标记 → contract 3 镜 + T3 预检 → State Engine → AM-15 → R0-R6 路由（state failure → CF-030 直索 R3 + recalc 标记）→ State 重算 → 合成双通道（剪映草稿+报告落盘）→ 输入哈希 pin match）；验收清单 8/8 PASS（全链跑通/T3 拦截能力单测覆盖/R-pre 标记 ≥1/AM-15 双格式跨镜头/R 级正确/State 重算/剪映结构/输入确定性）；MAB 首次采样留 Phase 3.3（10.7 激活时）；端到端测试 2/2 + **Phase 2 全量回归 65/65**。渲染侧逐帧一致与真实生成验证归 Phase 0.4 基线 + Phase 4.2 基准对比 | demo 脚本 |

**验收**：3 镜样例新引擎全链跑通；T3 预检拦截 ≥1 类构造性错误（如特写×广角矛盾）；R-pre 在高价值 beat 生效且择优命中率 ≥70%；AM-15 输出 critique.json 双格式（含跨镜头维度）；R0-R6 命中正确等级且编辑链预算生效；State Transition 修复后重算；同一 Contract 二次渲染逐帧一致；剪映草稿可在剪映专业版打开；旧管线代码已删除且历史 run 可通过 contract_json 快照回放。

### Phase 3 · 学习回路与治理激活 + 有声书增强

| # | 任务 | 详情 | 涉及位置 |
|---|---|---|---|
| 3.1 ✅ | 调用审计 | 四元组（trigger_type / problem_statement / applied_knowledge_id / delete_test_result）落库；配套生产流程回放视图（提案→脚本→分镜→素材→修复→渲染逐节点可回溯，含每步所用模型与开销，剪辑决策持久化可续作）。**已完成**：`knowledge_hub.AuditTrail`——四元组 `AuditEntry` dataclass + `record_knowledge_usage()` 落 JSONL 库 + `replay_view()` 按 run_id 聚合（stages/cost/models_used/trace） |
| 3.2 ✅ | 知识治理运转 | verification_status 流转（pending→verified→deprecated）；trust_weight 接入 L3 排序；时效检查（180 天/落后模型 2 版本）。**已完成**：`KnowledgeGovernance`——单向状态流转（verified→pending 拒绝）+ trust_weight 升降（verified=1.0/deprecated=0.3）+ `stale_check()`（>180 天 → 检索优先 -30%）+ `l3_sort_key()`（trust × source_rank × 时效因子） |
| 3.3 ✅ | Learning Loop 实测 | repair_model 成功率统计回写 Repair_Learning；B 级知识 5 次调用 + delete_test 全过 → 升 A；激活 MAB 创意配置探索（10.7 creative_config_bandit：AM-15 因子化奖励回传 → MAB 迭代 → Top 配置经 experience_preload 固化，exploitation 与 exploration 并行）；接通 persona 观众反馈（10.7 audience_persona_feedback：观众分回流作 Audience Signal，与导演分双轨）；长期启动轨迹级强化学习（10.7 trajectory_rlvr：制品接地 + 三层级联奖励——可验证编辑信号/LLM-judge/人类偏好校准，前置条件 ≥500 条修复轨迹，Learning Loop 三级爬坡：统计→MAB→RL）。**已完成**：`LearningLoop`——`record_repair()` + `repair_success_rate()`（按 CF 统计）+ `check_b_to_a_upgrade()`（≥5 调用+delete_test 全过）+ MAB UCB1（`mab_record`/`mab_best_arm`/`mab_preload_config`，≥10 样本×avg≥0.7 收敛固化）+ persona 信号（`record_persona_signal`/`audience_signal_summary`，导演优先 Soft Gate）+ `rlvr_readiness()`（≥500 轨迹后启动，当前测试已验证阈值） |
| 3.4 ✅ | 有声书增强 | 声音 DNA 卡（角色×音色×语速×情感基线，规范 voice_consistency_manager）；演播评价标准（AM-15 变体：感知=ASR+音频特征，评价=演播标准）；sound_design 4 项注入 BGM/音效。**已完成**：`audiobook_enhancements`——`VoiceDNA` dataclass + `build_voice_dna_from_character()`（情感基线→音色/语速/音域自动推荐）+ `audiobook_am15_eval()` 演播评价变体（感知=ASR+音频，评价=voice_consistency/rate/emotion/pacing）+ `inject_sound_design()` 4 项注入（emotion_first_music/music_scene_matching/sound_design_formula/sfx_search_method，BGM genre+mix_style+SFX hints） |
| 3.5 ✅ | novel_agent 收编 | 泛化 RAG 助手并入工作流体系（作为检索执行器）。**已完成（无需操作）**：勘察确认 `agents/novel_agent.py` 不存在——RAG 助手已在 backend/app/services/ 现有工作流体系内（chroma 向量检索 + 实体提取），无独立游离文件待收编 | `agents/novel_agent.py` |

**验收**：至少 10 条知识单元完成验证状态流转；修复成功率有首批实测数据。

### Phase 4 · 端到端验证与商业化预挂钩

| # | 任务 | 详情 |
|---|---|---|
| 4.1 | 全链 Demo | 一部小说章节 → 有声书样章 → 短剧片段（3-5 镜）完整链路演示 |
| 4.2 | 基准对比 | 对照 Phase 0 基线输出：评审分提升 / 重生成率下降 / 单位质量成本曲线 |
| 4.3 ✅ | 合规预挂钩 | AI 标注字段、备案信息留痕（content_safety_checker + 生产记录）对齐 9 月新规；跨平台发布参照 MoneyPrinterTurbo（一键发布 TikTok/Instagram/YouTube Shorts，YouTube 发布自动标注 AI 生成内容——标注自动化实现样板）。**已完成**：`commercial_hooks`——`ComplianceRecord`（run/stage/model/knowledge_ids/ai_generated/content_safety/timestamp 留痕）+ `publish_compliance_check()`（YouTube auto_ai_label / TikTok+Instagram 手动标注提示 / 时长超限检测） |
| 4.4 ✅ | SaaS 挂钩点 | 知识中枢调用纳入积分计量；管理后台展示知识验证状态/修复成功率；预算管控三档——项目总额上限 / 单步费用阈值 / 超限人工审批（超限即熔断，不静默扣费）。**已完成**：`commercial_hooks`——`points_charge()`（阶段权重×token/秒换算：SCRIPT 1.0/STORYBOARD 0.5/KEYFRAMES 3.0/VIDEO 5.0）+ `BudgetControl.charge()`（三档：pass/require_approval/block 熔断）+ `admin_dashboard_data()`（知识治理+修复成功率+调用统计三合一后台数据源） |
| 4.5 ✅ | 批量栏目预挂钩 | 固定栏目模板化验证：一条通过验收的模板 + JSON 数据集 → 参数注入 → 批量渲染 N 条成片，验证边际成本趋零路径；品牌锁定（Shotkit brand-lock 模式）：品牌资产 → 冻结参数快照（与 image_generation.style_presets 风格预设同构），批量产物品牌一致性由快照保证。**已完成**：`commercial_hooks`——`BrandLock`（品牌参数快照 + sha256 哈希，同配置同 hash 保证一致性）+ `batch_render_plan()`（模板+数据集→参数注入→N 条成片计划 + brand-lock 注入 + 边际成本趋零 projection） |
| 4.6 | Episode Production Scheduler（10.4 DAG） | 节点级调度器：run 编译为 Production DAG（八类任务粒度）；readiness contract + SPECULATIVE 状态（低成本候选禁 Commit）；串行/并行判定与关键路径优先（Criticality = Slack^-1 × Failure Risk × Dependency Reach × Delivery Weight）；资源池并发管控与 Review Batch；Repair Task 插入不重建整集（REWORK 降级为场景级兜底）。配套档 A 镜头板视图（卡片墙/探索轨面板/依赖图视图）。设计契约与验收口径见 `docs/SHORT_DRAMA_DAG_CANVAS_GUIDE.md` 档 A/档 B（决策依据 §1.12） |

**验收**：全链 Demo 录制；成本对比报告可支撑「单位质量成本随产量下降」主张；批量渲染 ≥5 条同模板成片且质量一致性抽检通过。

---

## 五、资源需求

### 5.1 人力

| 角色 | 投入 | 职责 |
|---|---|---|
| 全栈主程（1） | 全程 | 架构落地、Phase 1/2 核心开发 |
| LLM 应用工程（1，可兼职） | Phase 2-3 | prompt 注入调优、AM-15 评价链、Learning Loop |
| 导演知识顾问（0.5，人工抽检） | Phase 1-2 | SD/NF 知识翻译质量抽检、AM-15 评分校准 |
| 内容测试运营（0.5） | Phase 2-4 | 样例生产、基线数据、A/B 记录 |

### 5.2 模型 API（工程已有适配器，需备积分）

| 用途 | 通道 | 说明 |
|---|---|---|
| 小说创作/评审 | dashscope / volcengine | 11 Agent 工作流 |
| 生图 | Seedream / Vidu / qwen-image | 资产与首尾帧 |
| 视频生成 | Seedance / Kling / Wan / Hailuo / PixVerse / Vidu | 按路由器能力标签 |
| AM-15 感知 | Qwen-VL（通义全模态） | 逐镜切分与评价 |
| TTS/音乐 | mureka + TTS | 有声书 |

预算原则：Phase 2-4 以「3-5 镜样例 × 多轮修复」为测试基线；正式产量按单部 5-15 万成本模型另行核算。

### 5.3 基础设施
现有栈复用：FastAPI / Celery / Redis / PostgreSQL / 向量库 / 对象存储。新增仅知识文件目录与审计表（1 张）。执行层工具链：FFmpeg 必备（修复词典 / 合成 / 自检）；代码化合成框架 HyperFrames 或 Remotion 二选一试点（Phase 2.7）——均开源、零 API 费用，渲染算力走本地/CI。

---

## 六、时间计划（单人主导 + AI 辅助节奏，多人并行可压缩约 40%）

| 阶段 | 内容 | 参考周期 | 里程碑 |
|---|---|---|---|
| Phase 0 | 基线记录 | 0.5 周 | 两份基线报告 |
| Phase 1 | 知识中枢 + 小说闭环 | 2-3 周 | 小说 A/B 差异数据 |
| Phase 2 | 短剧板块重建（原地重写） | 4-6 周（雏形对齐，较增量方案省时） | 3 镜全链 Demo（新引擎） |
| Phase 3 | 学习回路 + 有声书 | 3-4 周 | 首批实测成功率数据 |
| Phase 4 | 全链验证 + 预挂钩 | 2 周（后持续） | 成本对比报告 |
| **合计** | | **约 12-16 周** | 窗口期（1-2 年）内充裕，建议 Phase 2 完成即启动小规模内容试产 |

关键路径：Phase 1.1（混注门禁）→ Phase 2.1（知识挂载）→ Phase 2.2（剧本引擎）→ Phase 2.3（Contract 引擎）→ Phase 2.5（QC/修复升级）。旧管线直接删除、无双轨兼容负担；短剧重建可与 Phase 1.2/1.3 并行。

---

## 七、风险评估与应对策略

| # | 风险 | 等级 | 影响 | 应对 |
|---|---|---|---|---|
| R1 | 大厂全链路入场（即梦+剪映+番茄）稀释差异化 | 高 | 估值/竞争力折半 | 差异化锚定知识层+数据飞轮（大厂拼管线不拼方法论）；加速 Learning Loop 实测数据积累 |
| R2 | 生成 API 依赖（涨价/限流/竞品化） | 高 | 成本失控 | 路由器保持 6 家可切换；低服从度能力（精确光位等）走参考图而非文字；adapter 层已隔离 |
| R3 | 端到端实测暴露设计缺陷（Learning Loop 设计值≠实测） | 中高 | 阶段返工 | Phase 0 强制基线；Phase 2.8 用最小样例先行验证，宁可早失败 |
| R4 | 爆款随机性（0.47% 爆款率）导致内容业务预期落空 | 中高 | 收入不及预期 | 定位以 SaaS 工具+技术服务打底，内容只做验证；不押注单部爆款 |
| R5 | 知识注入导致 prompt 膨胀/性能劣化 | 中 | 成本与质量双损 | 严守 L1/L2 优先、L3 兜底；单次注入 ≤ 对应组（禁止全库）；监控 token 预算 |
| R6 | 三件套漂移（改 JSON 忘改镜像） | 中 | 知识不一致 | 本期起 JSON 为 SSOT；DOCX/XLSX 归档只读；变更走 JSON 单点 |
| R7 | 9 月新规合规成本（标注/备案/红线） | 中 | 上线延迟 | Phase 4.3 预挂钩；content_safety_checker + 生产留痕已有基础 |
| R8 | AM-15 评价与人类导演标准偏差（通用 VLM 电影语法 <60% 准确率） | 中 | QC 误判 | 评价层强制注入 12 字段+CF 库标准；导演顾问抽检校准；评分只作 Soft Gate 初筛；**混合主客观评审**（客观指标通道：人脸一致性/动作完成度/帧间形变 + MLLM 主观分，冲突仲裁，AnimeAgent 实证）补全单一 VLM 不可靠问题 |
| R9 | 编辑链衰减未被遵守（多轮编辑越修越坏） | 低中 | 资产报废 | 衰减预算硬编码止损（四条件任一触发强制升级 R4） |
| R10 | 窗口期内未达 Phase 2 里程碑 | 中 | 战略被动 | Phase 2 完成即试产，不等全链完美；MVP 纪律（知识 40-50 条起步，拒绝仿规模） |
| R11 | 执行层质量漂移（渲染非确定性 / 编码参数随意 / agent 即兴拼命令） | 中 | 修复复检失去可比基准，批量产出不一致 | 强制确定性渲染与统一编码基线（CRF/yuv420p/faststart）；合成与修复命令仅出自受控词典模板；渲染后 ffprobe 自检纳入分级质检 |
| R12 | VLM 评价成本随产量线性膨胀 | 中 | 单位质量成本不降反升，Learning Loop 主张失效 | 分级质检：ffprobe/帧采样/音频分析廉价首轮拦截，VLM 降级为可疑镜头 + 抽检；KPI 监控廉价拦截率（≥60%） |
| R13 | 外部借鉴知识未实测（2026-10 新增 7 知识单元 + DC-037 + 骨骼绑定路径均为 external_paper/external_opensource 级信任） | 中 | 未验证知识污染决策 | verification_status=pending 不进高权重检索；5 次调用 + 删除测试全过升 A；升级前只在小流量 beat 试运行（R-pre 候选择优天然提供 A/B 对照） |
| R14 | 旧短剧管线直接删除的兼容断裂（前端 RunResponse 20+ 字段、历史 run 回放、积分预检按旧阶段计价） | 中 | 旧项目不可用 / 计费错乱 | contract_json 快照隔离 + ShotSchemaV2 兼容读层；删除前跑全量历史 run 回放冒烟；积分预检按新阶段模型重新标价并灰度上线 |

---

## 八、质量标准

### 8.1 知识资产质量
- 所有知识单元必含：id / beat_family 或 failure_code / 适用场景 / 修复或决策内容 / source_type / verification_status（未登记不进检索池）
- 新增知识单元登记 knowledge_units 板块（含 depends_on 依赖追踪与治理字段），core_knowledge 各域为 id 索引；depends_on 引用的单元必须存在（依赖完整性校验）
- 小说 SD 源自三件套 30 场景 DC 翻译，NF 与评审六维一一映射（≥8 码）
- 短剧知识文件与 `ai_director_os/*.json` SSOT 逐条对应，派生脚本可校验

### 8.2 工程质量
- 注入接口幂等：同 beat 重复注入不重复展开；单镜注入总量 ≤ 1 个决策组 + 1 个失败组
- 失败码评审输出为结构化 JSON（可被修订路由直接消费，无散文解析）
- 预检规则可单独测试（16 触发器 + 光学一致性 + 干涉各配 ≥1 用例）
- 修复路由 R0-R6 每级 ≥1 测试用例；编辑链预算四止损条件有单元测试
- 合成/修复命令模板化：所有 FFmpeg 与合成命令出自受控词典与参数模板，禁止运行时即兴拼接（可审计、可回归）
- 渲染可复现：同一 Contract + 同素材二次渲染逐帧一致；编码基线统一（CRF / 像素格式 / faststart），产物元数据可被 ffprobe 校验

### 8.3 内容质量
- 小说：A/B 对比下评审六维均分不劣化且目标维度（钩子/节奏/情绪）可测提升
- 短剧：AM-15 逐镜评分 + CF 命中号可追溯；修复后复检通过率纳入统计；信息类镜头节奏含「呼吸等待」（关键揭示后保留 ≥2s），成片无未解释的匀速赶场
- 字幕逐词级时间轴对齐（口播/对白类）；任何剪辑删改后字幕强制重对齐
- 分级质检分层统计：廉价自检（ffprobe/帧采样/音频）拦截率与 VLM 抽检覆盖率分开采集
- 防滥用：炫技率（未过删除测试调用占比）< 15%；每镜主动技巧 ≤2、主导技巧 =1

### 8.4 合规质量
- AI 生成内容标注字段齐备；生产记录可回溯（谁/何时/哪个模型/哪个知识单元）

---

## 九、验收标准

| 阶段 | 验收项（DoD） |
|---|---|
| Phase 0 | 基线报告 2 份（小说/短剧各一），含耗时、评分、成本基线 |
| Phase 1 | ① 现有小说 12 码/案例/记忆对照表完成 ② failure_codes 可机读且端到端可路由 ③ 修订计划含优先级公式与删除测试栏 ④ 混注门禁测试通过（导演知识未进入小说正文 prompt） |
| Phase 2 | ① 3 镜样例全链跑通（Beat→Contract→预检→生成→AM-15→修复→回写→合成渲染）② 预检拦截 ≥1 类构造错误 ③ AM-15 报告结构与 E03-S17 模板字段一致 ④ 修复路由命中正确等级 ⑤ 廉价自检先于 VLM 拦截 ≥1 类渲染缺陷 ⑥ 同 Contract 二次渲染逐帧一致 |
| Phase 3 | ① ≥10 条知识完成验证状态流转 ② 修复成功率首批实测表 ③ 调用审计四元组落库可查 ④ 有声书声音 DNA 卡与演播评价上线 |
| Phase 4 | ① 全链 Demo（小说章节→有声书→短剧片段）② 成本对比报告支撑降本主张 ③ 合规字段过检 ④ 管理后台可见知识治理看板 ⑤ 批量渲染 ≥5 条同模板成片且质量一致 |
| **最终** | 一条命令可复跑的端到端演示 + 全部 KPI 采集点在线 |

---

## 十、关键成功指标（KPI）

### 10.1 系统层（Phase 2 起）
| 指标 | 目标 |
|---|---|
| 修复一次通过率（QC 失败→修复→复检通过） | ≥60%（首测基线后逐季提升） |
| 整镜重生成率 | ≤30%（编辑/剪辑层消化 ≥70%） |
| 编辑链平均轮次 | ≤2（镜头）/ ≤3（资产图） |
| 预检拦截率（生成前拦截 / 生成后发现） | ≥40% 的可预防缺陷前移 |
| 廉价自检拦截率（VLM 前被 ffprobe/帧采样/音频分析拦截占比） | ≥60%（VLM 降级为可疑镜头 + 抽检） |
| 渲染可复现率（同 Contract 二次渲染逐帧一致） | 100% |
| 候选择优命中率（高价值 beat 双候选中高分候选最终通过 QC 比例） | ≥70% |
| AM-15 混合评审双通道覆盖率（评分必含客观+主观两通道） | 100% |

### 10.2 知识层（Phase 3 起）
| 指标 | 目标 |
|---|---|
| L1 直索命中率（失败码直接命中案例） | ≥70% |
| 炫技率 | <15% |
| B 级知识升级率（pending→verified） | 月均 ≥10% 活跃知识 |
| 知识调用-采纳比 | ≥50%（注入后被实际参考） |

### 10.3 内容层（Phase 4 起）
| 指标 | 目标 |
|---|---|
| 小说评审六维均分 | 较基线不劣化；目标维（钩子/节奏/情绪）可测提升。不以短剧 DC 注入小说为手段 |
| 短剧单镜单位质量成本 | 随产量呈下降斜率（Learning Loop 核心主张） |
| AM-15 评分与人工抽检相关性 | ≥0.7 |

### 10.4 商业层（Phase 4 后持续）
| 指标 | 参照 |
|---|---|
| SaaS ARR | 情景 B（500-1000 万）→ 情景 C（1000 万+爆款案例） |
| 出海内容分账 | 首年验证 1 部跑通分账/付费链路 |
| 估值支撑 | 情景 A（1500-3000 万，资产包）→ 情景 D（3-10 亿，数据飞轮）依赖上述全部 KPI 兑现 |

---

## 附录 A · 关键资产与文件索引

| 资产 | 路径 |
|---|---|
| 三件套 SSOT | `ai_director_os/AI_Director_OS_V5_Agent_Training_R6_11_MASTER_CONTENT_INTEGRITY_CHECK.json` |
| 数据库视图（归档） | `ai_director_os/AI_Director_OS_V5_Database_R6_11_*.xlsx` |
| 主文档（归档） | `ai_director_os/AI_Director_OS_V5_Master_R6_11_*.docx` |
| 小说质检（已落地，补强而非新建平行库） | `backend/app/services/prompts/narrative_quality.py、narrative_failure_cases.json；review_meta` |
| 短剧知识挂载（待建） | `config/director_knowledge/`（从 SSOT 派生） |
| Prompt 组装 | `backend/app/services/prompts/builder.py`、`agents.json` |
| 小说工作流 | `backend/app/api/v1/workflow/`、`agents/novel_agent.py`（待收编） |
| 一致性 | `backend/app/services/setting_consistency.py`（境界迁配置） |
| 反馈回路 | `backend/app/services/feedback_loop.py`、`prompt_evolution/` |
| 短剧包（v1.5 原地重写） | `agents/scripter.py`（剧本引擎）/ `agents/storyboarder_pkg`（Contract 引擎）/ `painter_pkg`（R-pre）/ `dreamweaver_agent_pkg`（State Engine）/ `agents/auditor.py` + `pipeline/autoqc_pkg`（CF 对齐+R0-R6）/ `agents/vlm_utils.py`（AM-15）/ `agents/editor.py` + `adapters/JianyingAPIAdapter`（合成双通道） |
| 短剧基建（复用） | `adapters/`（六厂商+工厂+限流）、`agents/character_manager.py` / `asset_library.py` / `semantic_asset_index.py` / `voice_consistency_manager.py` / `audio_sync_manager.py`、`pipeline/state_machine.py`、`backend/app/models/dreamweaver.py`（PG 五表）、`backend/app/services/points_task_precheck.py`、`content_safety_checker.py` |
| 短剧 QC 雏形（升级） | `pipeline/autoqc_pkg/_routing.py`（4 类修复动作 → R0-R6）/ `pipeline/autoqc_pkg/`（13 failure_type → CF L1 直索） |
| 短剧镜头依赖图雏形（升级） | `agents/camera_states.py`（依赖图 → 10.1 State Engine）/ `agents/camera_tree.py`（景别分组树） |
| 短剧图像择优雏形（升级） | `agents/best_image_selector.py`（semantic/vlm/file_size 链 → R-pre 门位） |
| 短剧数据契约 | `schemas/task_spec.py`、`schemas/storyboard_item.json`（ShotSchemaV2）、`backend/app/models/dreamweaver.py`（五表 + contract_json 快照） |
| 短剧编排 | `backend/app/api/v1/dreamweaver_api/`（routes_run/script/library/video/task/project）、`app/tasks/dreamweaver_tasks.py`（Celery） |

## 附录 B · 术语速查

| 术语 | 含义 |
|---|---|
| DC / SD | 导演决策案例（37，只进派生/执行层）/ 小说场景类型（已有 match_scene_type，不新建 SD 库） |
| CF / NF | 失败案例库（102，短剧，待挂 auditor）/ 小说失败码（已落地 12 码，见 narrative_quality.py） |
| T1/T2/T3 | 知识触发：失败修复 / 分叉决策 / 风险前置 |
| L1/L2/L3 | 检索通道：失败码直索 / 结构化触发器 / 语义兜底 |
| R0-R6 | 修复路由：接受/元数据/剪辑/局部编辑/整镜重生成/镜组重建/场景重构 |
| R-pre | 生成前候选择优门位（先于 R0：高价值 beat 双候选 → VLM 预评 → 只扩展高分分支） |
| MAB / θ | 多臂老虎机创意配置探索 / 因子化创意配置（创意风格×叙事模式×美学原型，10.5 下发 / 10.7 迭代） |
| RLVR | 轨迹级强化学习（可验证奖励）：Learning Loop 第三级爬坡——统计→MAB→RL（10.7 trajectory_rlvr） |
| 3E | 阶段完整性协议：Explore 探索 / Examine 检查 / Enhance 补全（10.5，不完整不交接） |
| repair / repair_model | 导演视角修复 / 模型原理视角修复（双视角） |
| beat 七族 | 信息揭示/情绪爆发/关系状态/冲突动作/开场建置/收尾定格/交互细节 |
| 删除测试 | 移除该元素叙事是否受损？不受损→删（元素级质量门禁） |
| 炫技率 | 未通过删除测试的知识调用占比（<15%） |
| SSOT | 单一事实源（本工程 = Agent_Training JSON） |

---

## 附录 C · 执行层工程实践摘录（开源技能调研，2026-08-18）

> 来源为公开开源仓库与官方文档（HyperFrames、OpenMontage、remotion-dev/skills、video-shotcraft、n0an/ffmpeg-skill、browser-use/video-use、Manim）。此处仅摘录**已转化为本指导约束**的要素（对应 §1.5 映射表），细节以各上游仓库为准。

### C.1 确定性渲染（HyperFrames）
- 逐帧驱动（seek-driven）而非实时录制：帧号 = floor(time × fps)，每帧独立捕获后 FFmpeg 编码——同输入必同输出，可 diff、可进 CI 回归
- 合成即代码：HTML 声明轨道与时间（data-start / data-duration / data-track-index），无专有时间线格式，可版本管理
- 生产闭环：lint（结构校验）→ 预览（单帧/低清）→ 渲染（高清），对应「预检→样片→成片」成本分层

### C.2 分级质检 / 预算管控 / 流程回放（OpenMontage）
- 三道闸门：合成前验证（防"幻灯片式"空转成片）→ 渲染后自检（ffprobe 元数据、帧采样黑帧/静态检测、音频分析）→ 人工审批（提案/脚本/分镜/渲染节点）
- 预算管控：总上限 + 单步阈值 + 超限逐单审批；生产看板支持逐节点回放与开销审计
- 多提供商打分调度：按任务能力打分择优；云端 API 与本地模型（离线 TTS + 免费素材库零成本路径）可切换

### C.3 批量渲染与配方卡（Remotion 官方 skills / video-shotcraft）
- 数据集批量：JSON 数据集 → 参数注入 → 循环渲染 N 条成片（固定栏目边际成本趋零）
- 官方技能按子任务分域（markup / render / captions / studio / saas 各自独立 SKILL）——对应本指导知识单元的粒度纪律
- 镜头配方卡字段：用途 / 能量感 / 建议时长 / 参数 / 实现要点 / 已知坑点，与镜头卡 12 字段同构；平台画幅预设（9:16 / 16:9 / 1:1）与节奏卡点（cut 对齐 beat）内置

### C.4 修复执行词典（FFmpeg 技能）
- 流拷贝 vs 重编码：改封装 / 关键帧对齐段拼接用 `-c copy`（快 10-100 倍、无损）；改分辨率 / 滤镜 / 帧精确裁剪必须重编码
- 编码基线：web MP4 用 libx264 + CRF 18-23 + yuv420p + faststart；Apple H.265 加 hvc1；音频归一 loudnorm
- 坑位先行：写命令前必读对应坑位参考（seeking 精度、滤镜顺序、流选择器）——对应本指导「命令出自受控词典，禁止即兴拼接」约束

### C.5 真人素材剪辑（video-use）
- 双层读取：词级时间戳转录文本（约 12KB 主视图）常驻 + 时间线合成图按需生成——LLM「读」视频而非「看」视频，成本从千万 token 帧噪声降到 KB 级文本
- 剪切纪律：剪辑点对齐词边界；每个切点 30ms 音频淡入淡出消爆音；删口误/语气词/死寂后字幕重对齐
- 自评估闭环：渲染后逐切点检查跳帧/爆音/遮挡，不过则自动修复重渲染（≤3 轮）——与编辑链衰减预算同构
- 会话记忆（project.md）持久化剪辑决策，跨会话续剪

### C.6 类型化时长与构图（Manim）
- 内容类型时长表：标题 1.5s、关键公式/揭示 2.0s、变换 1.5s、辅助标注 0.8s、Aha 时刻 2.5s；每个揭示后强制等待（关键 ≥2s、Aha ≥3s）——「呼吸感」不可省
- 透明度分层引导注意力：主体 1.0 / 语境 0.4 / 结构（轴/网格）0.15；逐场景差异化（换主色/布局/入场/疏密），禁止全片同构
- 成本分层渲染：草稿低清（480p15）迭代、终稿才高清（1080p60）

---

## 附录 D · 多智能体生产体系对照摘录（开源与论文调研，2026-10-07）

> 来源为公开论文（arXiv/SIGGRAPH Asia）与开源仓库（Co-Director、AniMaker、AnimeAgent、FilmAgent、ArcReel、DramaClaw、Toonflow、AI168漫剧、ViMax）。此处仅摘录**已转化为 SSOT JSON 修改**的要素（对应 §1.7 映射表），细节以各上游论文/仓库为准。

### D.1 全局优化与分层创意参数化（Co-Director，Google）
- 首个把生成式视频叙事形式化为**全局优化问题**的多智能体框架：Orchestrator（MAB）/ Pre-Production（Creative Brief→Storyline→Visual Assets）/ Production / Post-Production 四层
- 多臂老虎机在因子化创意行动空间 θ=(θcs 创意风格, θnm 叙事模式, θaa 美学原型) 上采样，动态注入所有子 Agent system prompt——解决瀑布管线级联失败、信用分配难题、子 Agent 语义冲突
- MLLM Judge 按因子输出奖励 R=(rcs, rnm, raa) 回传 MAB，迭代 T 轮——探索（新叙事策略）与利用（已验证有效配置）的原则性平衡
- GenAd-Bench：400 场景 × 200 虚构产品（防模型记忆先验），AIDA 层级评价
- 落点：10.7 creative_config_bandit + 10.5 hierarchical_creative_config

### D.2 MCTS-Gen 候选择优与 AniEval 多镜头评价（AniMaker，SIGGRAPH Asia 2025）
- Photography Agent 用 MCTS 启发策略：并行生成多候选片段 → VLM 评估潜力 → 只扩展高分分支——树搜索式预算控制，探索与资源利用平衡
- AniEval 首个多镜头动画评价框架，四组维度：整体质量（VQA_A/VQA_T/MusIQ）/ 文本-视频对齐（一致性/故事一致性/检测/计数）/ 视频一致性（DreamSim/人脸一致性/Warping Error/语义一致性）/ 动作质量（动作识别/动作强度/AC-Score）
- 落点：10.6 candidate_selection_gate（R-pre）+ AM-15 评价层跨镜头维度

### D.3 迪士尼两阶段关键帧 + 混合评审（AnimeAgent，vivo/UESTC）
- 迪士尼「Straight Ahead + Pose to Pose」工作流的 I2V 化：先生成连续运动轨迹，再选取最具表现力的极限帧（EXTREMES）作分镜——I2V 链式推理提供隐式动态一致性约束，克服 T2I「摆拍式」复制粘贴
- 首帧即视觉 dope-sheet：角色参考图初始化首帧，稳定锚定身份与风格
- 双 dope-sheet：Director 解析结构化引导，弥合用户 prompt 与模型偏好 prompt 的错位
- 混合主客观评审：实证 CLIP 对艺术变形不敏感、MLLM 评分缺稳定参照——两者结合才可靠
- 落点：DC-037 + disney_two_stage_keyframe / hybrid_review_protocol

### D.4 协作算法与闭合动作空间（FilmAgent，HITsz-TMG）
- 3D 虚拟片场：15 场景 / 65 演员站位 / 272 机位（165 静态 + 107 动态 9 类）/ **21 个闭合动作**——封闭集合从源头杜绝「不存在的动作」幻觉
- Critique-Correct-Verify（编剧环：Director-Screenwriter-Actor 层层纠错，实证拦下 standing suggest 类幻觉、修复跨场景矛盾）与 Debate-Judge（摄影环：多方案辩论 + 导演裁决）
- 多 Agent 协作的 GPT-4o 胜过单 Agent o1——组织结构的价值
- 落点：10.5 collaboration_protocols + closed_action_lexicon

### D.5 版本/重试/成本/导出工程实践（ArcReel）
- Subagent 架构：主 Agent 只拿精炼摘要，原文大段上下文留在 Subagent——上下文不爆
- 异步任务引擎：RPM 限速、图像/视频独立通道、lease-based 调度、断点续传；批量逐项返回成败，**重试只补失败项，不为已成功内容重复付费**
- 版本管理：每次重生自动存档、一键回滚、多版本并排对比
- 逐资产成本可见：生成前后查看费用与实际用量
- 剪映草稿导出（5.x/6+ 兼容）：全自动合成之外留人工精剪通道
- 落点：10.5 context_discipline / 10.4 retry_discipline + cost_visibility / 10.2 version_compare_protocol / Phase 2.7

### D.6 Story Graph 与 Freezone 双轨（DramaClaw）
- Ingest→Plan→Produce→Deliver 四段；小说解析为**可查询故事图**（角色/关系/时间线，Cognee 实现），剧本生成走图查询
- 剧本多模式（adaptive 自适应改编 / literal 忠实 / staged 分阶段）+ 评审修复环
- Freezone 无限画布：主管线之外自由试生成，满意一键推回——双轨制
- 实证产量：单管线已产出 58 集连续短剧
- 落点：story_graph_ingestion + 10.3 exploration_track + Phase 2.2

### D.7 骨骼绑定防变形（Toonflow）
- 3D/2.5D 角色建模 + 自动骨骼绑定：骨骼锁定身份与比例，运动由骨架驱动——打斗/舞蹈等高动态场景从机制上杜绝脸畸变
- 单集 8 分钟、成本十几元的工业化基准
- 落点：skeleton_binding_high_motion + CF-021/029/082 repair_model 机制级升级路径

### D.8 四视图角色参考（AI168漫剧）
- 角色提取后生成四视图参考图（正面/四分之三/侧面/背面），作为全部分镜与视频的身份基准
- 分镜版本管理（列表/看板双视图）；参考帧双模式（首尾帧 / 场景参考帧）
- 与 Co-Director 的多角度参考拼图（multi-angle reference collages，剧情驱动服装合成）独立收敛——跨项目验证的实践
- 落点：multi_angle_reference_collage

### D.9 上下文管理三件套（ViMax，HKUDS）
- context compaction（上下文压缩）+ session reuse（会话复用）+ render checkpoints（渲染检查点断点续传）
- 双候选关键帧并行生成 + VLM 择优（image_selection.num_candidates=2）——与拾光工坊 best_image_selector 同构，验证了该模式可推广至视频层
- 落点：10.5 context_discipline + candidate_selection_before_commit 图片层复用说明

---

## 附录 E · Agent Skill 生态与论文新进展摘录（第三轮调研，2026-10-07）

> 来源为公开论文（arXiv/ACL/EACL/ICML-WS）与开源 Skill 集合/工具链（Crayotter、MAViS、CHIEF、InfinityStory、MM-StoryAgent、VChain、AI漫剧Skills、Shotkit、剪映工具链、MoneyPrinterTurbo）。此处仅摘录**已转化为 SSOT JSON 修改或本文档修订**的要素（对应 §1.9 映射表）。

### E.1 轨迹级 RLVR 与制品接地（Crayotter）
- 长视频编辑形式化为**制品接地的 Agent 轨迹问题**：规划/执行/修订全部以显式外部状态为条件；策略从可观察制品更新（environment-grounded reflection），而非隐式推理轨迹
- **三层级联奖励**：可验证编辑信号（硬指标）→ LLM-as-judge 多维评分 → 人类偏好校准，GRPO 优化
- 失败可定位到受影响时间线段并局部修订，而非整片重跑
- 落点：10.7 trajectory_rlvr（Learning Loop 三级爬坡第三级）

### E.2 3E 原则与剧本-生成器兼容性（MAViS，EACL 2026）
- 每阶段 **Explore（生成多方案）→ Examine（完整性检查）→ Enhance（补全增强）**——中间产物不完整不进入下一阶段
- **Script Writing Guidelines**：考虑生成模型能力限制来约束剧本写法——剧本是生成器输入规格而非文学文本
- 落点：10.5 stage_completeness_3e + 知识单元 script_generator_compatibility

### E.3 人格化观众反馈（CHIEF，ICML'26 Workshop）
- persona-conditioned MLLM 以观众人格看片给主观批评（钩子留存/情绪曲线/弃剧点）——补自评盲区
- 创作者驱动迭代 + refiner agent 落实修改；实测无经验学生做出 10 分钟复杂剧情短片
- 落点：AM-15 产出层观众信号通道 + 10.7 audience_persona_feedback

### E.4 地点锚定与主体感知转场（InfinityStory，Adobe）
- **location-grounded planning**：地点资产锚定背景，VBench 背景一致性 88.94（最高）
- **character-aware shot transitions**：多主体入画/出画转场建模（进入方向/画面位置/遮挡），配 10k 多主体转场数据集
- 落点：知识单元 location_grounded_planning（+ 切换技法库补主体感知转场条目）

### E.5 内运动优先与模型分档（AI漫剧Skills，gitee v9.0）
- **内运动体系**：固定镜头注入画面内动态 + 微运镜分级 + 动态密度自检——低运镜服从度的工程解法
- **模型分档时长参数化**：段上限 15s/30s、单镜上限 15s/25s 按 Seedance 2.0/2.5 分档；模型选择提问交互确认
- 四阶段管线（16 大师风格匹配 → 设备选择 → 分镜 → 提示词编译）值得 Storyboard 层 UI 参考
- 落点：知识单元 internal_motion_priority / model_tiered_duration

### E.6 稀疏关键帧视觉思维链（VChain，ACL 2026 Findings）
- MLLM 生成稀疏关键帧快照作为推理中间态，仅在关键时刻对预训练视频生成器做推理时视觉状态适配（sparse inference-time adaptation）——调参高效、最小开销、免密集监督
- 落点：知识单元 sparse_keyframe_cot（AM-09 预演的轻量形态，与 DC-037 轨迹选帧互补）

### E.7 Shotkit 三件宝（Apache 2.0，月产百条视频的预生产系统）
- **brand-lock**：品牌资产（URL/PDF/截图）→ 冻结品牌参数快照，产物品牌一致性由快照保证
- **round×shot 寻址 + 内容哈希 pin**：产物按 output/{run}/{round}/{shot}/ 寻址，round 2 永不覆盖 round 1；run.json 哈希 pin 全部输入（prompt/参考图/模型/参数）
- **critique.json 机读裁决闭环**：每镜批评双格式输出，机读件直接驱动重编译——generate → critique → revise → re-critique 闭环
- 文件哲学：Files, not panels——可审计、可交接、不锁平台
- 落点：10.2 reproducibility_addressing / 10.6 machine_readable_critique / 4.5 brand-lock

### E.8 剪映自动化工具链与跨平台发布
- 工具链选型：pyJianYingDraft（草稿文件读写）/ VectCutAPI 2.3k★（REST+MCP 双协议、网页预览）/ JianYing MCP（轨道/片段/转场/滤镜/蒙版/关键帧/音频/文本全控制，内置 rules 制作规范工具）/ capcut-mate（FastAPI + 云渲染 + 异步任务队列）/ capcut-cli（本地 draft store 直接 JSON in/out）
- **双剪辑师模式**（video-agent-jianying-editor）：与 DaVinci 剪辑师共享同一 visual-timeline.json 输入，制片人按 output_target 路由 resolve/jianying/both——同一时间线多交付目标
- MoneyPrinterTurbo（128k★）：跨平台一键发布 TikTok/Instagram/YouTube Shorts，YouTube 发布**自动标注 AI 生成内容**；v1.3.5 起 agent 可读 SKILL.md 自安装配置
- 落点：Phase 2.7 剪映工具链选型 + Phase 4.3 标注自动化参照

### E.9 对照确认项（已有对应，不重复集成）
- MovieAgent 场地管理员（location manager）→ AM-03 Scene State System 已覆盖
- StoryAgent LoRA-BE 定制 I2V（镜内时序一致）→ CF-021/082 骨骼绑定 + DC-037 两阶段法已覆盖同主题
- Cinematic Director 连续性锚（identity/costume/room）+ 单镜单主动作 → Shot Contract 12 字段 + 五重 DNA + 技巧预算已覆盖
- muapi-cinema-director 意图映射表 → DC-035/036 八映射更细

---

## 附录 F · 宿主工程勘察与新旧映射（2026-10-07，v1.5 重建依据）

> 基于对 `c:\Users\cuigu\novel_writing_agent` 短剧管线的逐文件代码勘察（scripter / storyboarder_pkg / painter_pkg / dreamweaver_agent_pkg / autoqc_pkg / state_machine / adapters / DB 模型 / 路由），支撑 §1.11 决策与 Phase 2 重建任务表。

### F.1 勘察事实（关键位置）

- **剧本层**：`agents/scripter.py` `run(ctx)` L957，LLM 强制生成 Markdown `script_text` + entities JSON；「节拍」为每场 3-6 条文本行（非结构化 beat）；`_is_script_text_valid` L415 模板校验、`_llm_enhance_script` L257 二次润色、`script_requires_review` 人工门（保留）
- **分镜层**：`_storyboard_builders.py` 规则 L26 + LLM L196 双路；分镜字段 25+（ff_desc/lf_desc/motion_desc/state_before/subshots/head_frame{prompt,ratio,subject_pos}/tail_frame…）；`_shot_profile.py` L40-175 **12 模板按 shot_index 取模循环**（推翻对象）；`_duration.py` L258 base 2s+字数/20cps clamp 3-10s、总时长再平衡 L42（机制保留）；`_video_subshots.py` Wan 单容器子分镜时间轴（机制保留、改由 Contract 驱动）；`_frame_prompt.py` L26 拼接式首尾帧（推翻对象，head/tail 差异仅一句 stage_tag）
- **择优雏形**：`best_image_selector.py` `select_best_candidate` L293，selector 链 semantic→vlm→file_size→first；semantic 模式 qwen3-vl-plus 一次对比全部候选，identity 0.4 / structure 0.4 / style 0.2 加权
- **状态图雏形**：`camera_states.py` `build_camera_states` L33，anchor 优先级 camera_last_tail > camera_tree_parent_shot > previous_shot_tail，产出 `depends_on_state_ids`
- **QC 雏形**：`pipeline/autoqc_pkg/` failure_type 13 类（missing_head/tail_frame、ratio_mismatch、shot/cross_shot/camera_continuity_break、semantic_mismatch、state_continuity_mismatch、i2v_fallback、video_clip_quality_below_threshold…）；`_routing.py` L45 修复路由 4 类（revise_storyboard / switch_to_i2v / repair_video_clips / regenerate_shot_ids）
- **编排**：`pipeline/state_machine.py` `step` L247 全阶段流（INIT→planner→SCRIPT→STORYBOARD→ASSET_LIBRARY→KEYFRAMES→MIDFRAMES→VIDEO→EDIT→REVIEW→DONE）+ 三人工门（WAITING_SCRIPT_APPROVAL / WAITING_APPROVAL / WAITING_VIDEO_CONFIRMATION）；Celery `run_dreamweaver_task`；PG 五表 + `runs/{run_id}/` 产物 + `contract_json` 快照

### F.2 复用清单（直接保留）

| 模块 | 能力 | 位置 |
|---|---|---|
| 六厂商适配器 + 工厂/限流/prompt_optimizer | 模型路由（含剪映 JianyingAPIAdapter） | `adapters/` |
| 角色一致性四件套 | 档案 / 定妆图 / 语义检索 / 音色 | `character_manager` / `asset_library` / `semantic_asset_index` / `voice_*` |
| 积分预检 / 内容安全 | 计费与合规 | `points_task_precheck` / `content_safety_checker` |
| Celery + 状态机骨架 + artifacts_io | 编排壳（重写阶段语义，保留骨架） | `pipeline/` |
| PG 五表 + contract_json 快照 | 数据层（兼容读） | `backend/app/models/dreamweaver.py` |
| editor.py 合成 + JianyingAPIAdapter | 合成双通道底座 | `agents/editor.py` / `adapters/` |
| audio_sync / viseme / 主体桥接 | 音画能力 | `dreamweaver_agent_pkg` |

### F.3 推翻清单（删除重写）

| 旧逻辑 | 推翻理由 | 重写为 |
|---|---|---|
| scripter Markdown 剧本 + 文本节拍 | 无结构化 beat，无法挂 DC/CF/七族路由 | 剧本引擎（Story Graph + 结构化 beat + CCV + 闭合动作词典） |
| `_shot_profile` 12 模板循环 | 镜头语言与叙事脱钩（按索引取模，非按 beat 决策） | Shot Contract 引擎（七族路由 + DC-035/036/037 注入 + T3 预检） |
| `_frame_prompt` 拼接式首尾帧 | head/tail 差异仅一句；无光学一致性校验 | Contract 驱动的帧 prompt 编译（12 字段 + 多角度参考协议） |
| `ctx.payload` 无类型 dict 全程传递 | 阶段契约缺失、隐式耦合 | 强类型阶段契约 + handoff 3E 门位 |

### F.4 雏形 → 目标映射（升级改造）

| 宿主雏形 | 指导文档目标 | 升级动作 |
|---|---|---|
| camera_states 镜头依赖图 | 10.1 State Engine | 补 End/Start State 显式契约（End = Start + Verified Transitions）、状态域字段、修复后 State Transition 重算 |
| best_image_selector 加权择优 | R-pre 候选择优（10.6） | 加 beat 价值分级（高价值 beat 双候选）、权重对齐镜头卡 12 字段、扩展到视频层候选 |
| autoqc 13 failure_type + 4 类修复 | CF L1 直索 + R0-R6 | 失败码 ↔ CF 编号映射表；修复路由重写为七级决策树 + 编辑链衰减预算 + 双视角修复（repair_model 优先） |
| 三人工门（WAITING_*） | 10.5 human_gates | 对齐知识调度点与 3E 门位语义，审批走 round×shot 并排对比（10.2） |
| vlm_utils JSON 对话封装 | AM-15 | 廉价自检前置 → 混合评审 → persona 观众双轨 → critique.json 双格式 |

### F.5 数据兼容策略（对应 R14）

1. **历史数据不迁移**：旧 run 的 `contract_json` 快照原样保留，回放走快照 + ShotSchemaV2 兼容读层
2. **shots 表**：Shot Contract 12 字段以映射层方式并存，旧字段名（ff_desc/lf_desc 等）保留兼容读
3. **前端**：RunResponse 20+ 字段由兼容层供给，新字段增量下发
4. **计费**：积分预检按新阶段模型重新标价，灰度上线；删除旧管线前跑全量历史 run 回放冒烟

---

*本文档基于 2026-08-17 前的体系设计、代码审查与市场分析编制；v1.1（2026-08-18）融入开源技能生态执行层工程实践（§1.5、附录 C）；v1.3（2026-10-07）融入多智能体生产体系外部对照（§1.7、附录 D，SSOT JSON 同步 24 处修改）；v1.4（2026-10-07）融入 Agent Skill 生态与论文新进展对照（§1.9、附录 E，SSOT JSON 同步 12 处修改）；v1.5（2026-10-07）按宿主工程真实代码勘察重定短剧板块策略——推翻重建、原地重写（§1.11、Phase 2 重排、附录 F、风险 R14；历史版本备份于 `AI_Director_OS_落地实施指导.backup_2026*.md`）；v1.6（2026-10-07）短剧画布形态决策与 DAG 调度器单列（§1.12、Phase 4.6；设计契约详见 `docs/SHORT_DRAMA_DAG_CANVAS_GUIDE.md`，SSOT JSON 零修改）。执行中按阶段评审滚动修订，修订仅更新本文档与 SSOT JSON 两处。*
