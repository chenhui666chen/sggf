# 织梦映心小说改编与专业知识 RAG 改造指导
> 文档状态：实施指导稿  
> 编写日期：2026-08-02  
> 适用范围：灵感方舟小说项目、织梦映心短剧改编链路、领域知识配置、语义匹配、编剧与导演工作流  
> 目标读者：后端、Agent、提示词、前端与测试开发人员

## 1. 文档目的

本文用于指导织梦映心从当前的“小说正文一次性改写为剧本，再一次性拆分镜头”演进为可追溯、可审查、可分阶段迭代的专业改编系统。

本文重点解决以下问题：

1. 多章节原著被 `source_text[:12000]` 静默截断，后部情节无法进入规划、编剧或分镜上下文。
2. 灵感方舟已经拥有小说大纲、章节、人物、世界设定和 RAG，织梦映心不应再维护第二份小说知识真相。
3. 当前 `planner -> scripter -> storyboarder` 虽然阶段完整，但缺少结构化改编合同和导演交付合同。
4. 当前质量检查偏重生成物和画面技术正确性，缺少原著忠实度、剧作质量和导演选择质量检查。
5. `config/intent_domains.yaml` 与 `core/semantic_matcher.py` 中的确定性规则，不应被错误地整体迁入概率型 RAG。

本文是架构和实施指导，不要求一次性完成全部改造。后续应按阶段、小步、可测试地推进。

## 2. 核心结论

织梦映心应继续采用“小说先行”的产品路径：

```text
小说项目是事实源
→ 编剧负责影视化改编
→ 导演负责视听转译
→ 生成系统负责可执行素材和成片
```

目标不是让编剧脱离原著自由创作，也不是让导演重新解释整部小说。每个阶段都应消费上游已经批准的结构化交付物。

推荐总体原则：

```text
完整大纲：确定性读取
所选章节：确定性覆盖
局部原文：RAG 精确召回
模型能力与参数：确定性配置
导演方法与案例：RAG 动态建议
最终执行：结构化合同 + 硬约束校验
```

特别注意：RAG 的 Top-K 结果不能等价于“完整阅读了用户选择的全部章节”。章节覆盖必须由数据库记录和覆盖清单保证。

## 3. 当前链路与主要问题

### 3.1 当前执行链

当前状态机主要执行顺序如下：

```text
INIT
→ planner
→ SCRIPT
→ scripter
→ WAITING_SCRIPT_APPROVAL（可选）
→ STORYBOARD
→ storyboarder
→ ASSET_LIBRARY
→ KEYFRAMES / MIDFRAMES
→ VIDEO
→ EDIT
→ REVIEW
→ DONE / REWORK
```

核心入口：

- `pipeline/state_machine.py`
- `agents/planner.py`
- `agents/scripter.py`
- `agents/storyboarder_pkg/_run.py`
- `agents/storyboarder_pkg/_storyboard_builders.py`
- `agents/auditor.py`
- `pipeline/autoqc_pkg/`

### 3.2 原著上下文静默截断

当前规划、编剧和导演提示均存在固定截断：

- `agents/planner.py`：规划仅使用 `source_text[:12000]`。
- `agents/scripter.py`：首次改编、扩写核对和部分增强流程仅使用前 12000 字符。
- `agents/storyboarder_pkg/_storyboard_builders.py`：分镜提示仅使用前 12000 字符。

与此同时，后端通过以下链路拼接用户选择的全部章节：

- `backend/app/api/v1/dreamweaver_api/routes_run.py`
- `backend/app/services/chapter_adaptation_assets.py`
- `backend/app/tasks/dreamweaver_tasks_pkg/_task.py`

因此，多章节输入可能出现后部章节、高潮、反转和结局未进入模型上下文的问题。此问题优先级高于扩充通用影视知识。

### 3.3 `planner` 输出未形成有效合同

当前 `planner` 主要产出自然语言 `plan.text` 和预估镜头数。`scripter` 与 `storyboarder` 没有稳定消费一个结构化改编方案，导致规划阶段更多是形式存在。

后续应将其升级为 `adaptation_plan`，明确：

- 本次改编范围；
- 必须保留事件；
- 可压缩事件；
- 可省略事件；
- 允许新增内容；
- 人物弧光；
- 场次计划；
- 结尾钩子；
- 不得提前泄露的信息。

### 3.4 编剧与导演之间缺少专业交付物

当前导演阶段优先使用 `script_text`，这个方向正确，但主要依赖 Markdown 剧本和简单实体列表。导演需要再次从文本猜测场景目标、潜台词、权力变化和信息策略。

后续应在剧本与分镜之间引入 `director_breakdown`。导演阶段只负责把批准后的剧作意图转成空间、表演、构图和镜头选择，不重新改写小说。

### 3.5 现有审核缺少改编质量维度

现有 `auditor` 和 `AutoQC` 已覆盖画面语义、状态连续性、视频片段、输出完整性和安全审查，但缺少：

- 原著关键事件覆盖；
- 人物关系与事实一致性；
- 无原著依据的新增内容；
- 未来章节信息泄露；
- 场景目标、冲突、转折和潜台词；
- 镜头选择是否服务戏剧意图。

应在昂贵的图片和视频生成之前完成剧本审查和导演审查。

## 4. 目标架构

### 4.1 总体数据流

```text
灵感方舟小说项目
├── PostgreSQL 权威事实
│   ├── 项目大纲与长篇框架
│   ├── 章节正文与结构化摘要
│   ├── 人物与关系
│   ├── 世界设定与硬规则
│   └── 项目记忆
│
├── NovelKnowledgeBase 共用索引
│   ├── plot_outline
│   ├── chapter
│   ├── character
│   └── world_setting
│
└── 织梦映心改编流程
    ├── adaptation_source_bundle
    ├── adaptation_plan
    ├── screenplay
    ├── script_review
    ├── director_breakdown
    ├── storyboard
    ├── director_review
    └── media generation / final review
```

### 4.2 共用与隔离边界

灵感方舟与织梦映心应共用：

- 项目和章节数据库；
- 人物、设定、大纲和记忆；
- Embedding 服务；
- Chroma/向量索引；
- 项目级数据隔离；
- 索引同步和生命周期管理。

两者不应直接共用：

- 最终提示词上下文；
- 检索 Query 构造；
- Top-K 配额；
- 内容排序与压缩策略；
- 任务质量标准。

小说续写关注前文连续性；影视改编关注选中范围的完整覆盖、可视化、戏剧压缩和原著证据。应在 `backend/app/services/dreamweaver/` 下建立改编专用上下文服务，而不是让 Agent 直接操作 Chroma。

## 5. 改编上下文合同

### 5.1 `adaptation_source_bundle`

织梦映心任务启动后，应先构建统一改编源包。建议结构：

```json
{
  "schema_version": "adaptation-source/v1",
  "project": {
    "project_id": 1,
    "title": "项目名",
    "genre": "悬疑",
    "sub_genre": "家庭悬疑"
  },
  "selection": {
    "chapter_ids": [101, 102, 103],
    "chapter_numbers": [12, 13, 14]
  },
  "global_story": {
    "premise": "...",
    "outline": "...",
    "selected_arc": "...",
    "future_boundary": "第15章以后信息不得提前揭示"
  },
  "chapters": [
    {
      "chapter_id": 101,
      "chapter_number": 12,
      "title": "...",
      "summary": "...",
      "adaptation_hint": {},
      "content_hash": "..."
    }
  ],
  "characters": [],
  "world_rules": [],
  "retrieval": {
    "index_ready": true,
    "missing_chapter_ids": [],
    "stale_chapter_ids": []
  }
}
```

数据来源必须分层：

1. 全局大纲确定性读取，优先级为 `epic_framework/epic_volumes_detail -> project_settings.plot_outline -> projects.user_outline_plan`。
2. 用户选择的章节、摘要和 `summary_data` 必须从数据库确定性加载。
3. 具体原文片段在生成某个场次时通过 RAG 召回。
4. 向量索引不可用时，必须使用数据库正文分块降级，不能静默遗漏章节。

### 5.2 `adaptation_plan`

建议结构：

```json
{
  "schema_version": "adaptation-plan/v1",
  "episode_premise": "...",
  "target_duration_s": 180,
  "adaptation_strategy": "faithful_compression",
  "must_keep_events": [],
  "compressible_events": [],
  "omitted_events": [],
  "allowed_inventions": [],
  "forbidden_reveals": [],
  "character_arcs": [],
  "scene_plan": [],
  "ending_hook": "...",
  "source_coverage": []
}
```

`scripter` 必须消费该合同，不能仅根据截断后的 `source_text` 自由决定结构。

### 5.3 `screenplay` 与溯源

短期可继续保留 `script_text` 作为展示和兼容字段，但应逐步增加结构化场次：

```json
{
  "scene_id": "scene_03",
  "heading": "内景·厨房·夜",
  "dramatic_goal": "女主确认父亲是否撒谎",
  "character_wants": {},
  "beats": [],
  "dialogue": [],
  "turning_point": "...",
  "source_refs": [
    {
      "chapter_id": 101,
      "chunk_id": "101-008",
      "start_offset": 6400,
      "end_offset": 7380
    }
  ]
}
```

必须支持从剧本场次回溯到原著证据，否则无法可靠执行忠实度审查。

### 5.4 `director_breakdown`

建议结构：

```json
{
  "scene_id": "scene_03",
  "dramatic_goal": "女主试探父亲是否撒谎",
  "point_of_view": "女主",
  "power_shift": {
    "before": "父亲掌控谈话",
    "after": "女主确认父亲隐瞒事实"
  },
  "subtext": "表面讨论晚餐，实际进行信任审判",
  "information_policy": {
    "reveal": [],
    "withhold": []
  },
  "emotional_beats": [],
  "visual_strategy": {
    "blocking": "...",
    "camera_principle": "...",
    "key_prop": "..."
  }
}
```

`storyboarder` 应消费批准后的剧本和 `director_breakdown`，不再重新检索整部小说或重新判断改编方向。

## 6. 小说 RAG 共用方案

### 6.1 现有可复用能力

现有实现已经支持：

- `NovelKnowledgeBase`：`backend/app/services/agents/knowledge_base.py`；
- 向量同步：`backend/app/services/vector_sync.py`；
- Typed-RAG：`backend/app/services/workflow_context_builder.py`；
- 增强检索 API：`backend/app/api/v1/knowledge.py`；
- 章节正文、人物、世界设定、情节大纲等类型；
- 章节编辑后重新同步；
- 项目删除时清理向量数据。

织梦映心应复用底层知识库，但新建改编检索服务，例如：

```text
backend/app/services/dreamweaver/
├── adaptation_context.py
├── adaptation_retrieval.py
├── adaptation_fidelity.py
└── adaptation_contracts.py
```

### 6.2 必须先修复的项目隔离风险

当前 `_similarity_search()` 和 `_similarity_search_with_score()` 在带过滤条件的查询失败后，会退化为无过滤搜索。这可能召回其他项目内容。

强制要求：

```text
如果调用方指定 project_id：
    过滤查询失败 → 返回空结果或抛出明确错误
    禁止执行无过滤降级

查询返回后：
    再次校验每条结果的 project_id
    不匹配的结果必须丢弃并记录告警
```

该问题在织梦映心接入共用 RAG 前必须解决。

### 6.3 章节索引元数据要求

当前章节向量元数据不足以支持原文定位。建议至少包含：

```json
{
  "type": "chapter",
  "project_id": "1",
  "chapter_id": "101",
  "chapter_number": "12",
  "chunk_index": 8,
  "start_offset": 6400,
  "end_offset": 7380,
  "content_hash": "...",
  "source_updated_at": "..."
}
```

检索必须支持精确 `chapter_ids`，不能仅使用连续的 `chapter_range` 表示用户选择范围。

### 6.4 索引健康检查

每次改编任务应在规划前检查：

- 所选章节是否全部已索引；
- 索引哈希是否与数据库正文一致；
- 当前向量库是否为持久模式；
- API 与 Celery 是否访问同一索引；
- Embedding 模型和索引版本是否一致。

建议输出：

```json
{
  "selected_chapter_count": 5,
  "indexed_chapter_count": 4,
  "missing_chapter_ids": [105],
  "stale_chapter_ids": [103],
  "vectorstore_mode": "persistent",
  "ready": false
}
```

缺失时可以补索引；向量系统不可用时应从数据库直接分块降级。不得把“没有召回”解释为“原著没有相关内容”。

### 6.5 索引生命周期

必须覆盖所有正文变更路径：

- 新建章节；
- 手工编辑章节；
- AI 工作流生成并保存章节；
- 批量导入；
- Book Parser 导入；
- 恢复、删除和重排章节；
- 旧项目数据回填。

章节 upsert 应统一走 `vector_sync` 的单一入口，避免业务路由自行创建 `NovelKnowledgeBase()` 后重复删除和写入。

## 7. 领域配置、语义匹配与专业知识 RAG 边界

### 7.1 三层职责

```text
第一层：Canonical Configuration
config/intent_domains.yaml

负责：
- 标准 ID 与同义词
- 模型能力与模态
- 参数范围
- 运镜、景别、构图枚举
- 提示词模板
- 基础场景候选规则
```

```text
第二层：Semantic Matcher
core/semantic_matcher.py

负责：
- 用户语言归一化
- 风格与场景分类
- 模型候选评分
- 本地低延迟匹配
```

```text
第三层：Creative Knowledge RAG

负责：
- 编剧与导演方法
- 场景推荐理由
- 适用条件与反例
- 替代视觉策略
- 优质提示词案例
- 模型生成经验
```

### 7.2 不应进入 RAG 的内容

以下内容必须保持确定性：

- `modalities`；
- `creative_modes`；
- `constraints`；
- 标准风格、运镜、景别、构图和光线 ID；
- 模型支持的时长和分辨率；
- 请求字段与提示词模板；
- 最终参数合法性校验；
- `semantic_matcher` 的匹配算法、权重和阈值。

原因是 RAG 为概率召回，不能保证硬约束每次出现，也可能召回旧版本。

### 7.3 适合进入 RAG 的内容

- `scene_rules.reason` 中的导演解释；
- 某项运镜何时适用、何时不适用；
- 同一戏剧目标的替代镜头方案；
- `prompt_examples` 中经验证的模型专属案例；
- 对话、悬疑、动作、离别等场景的视听方法；
- 竖屏短剧的构图和调度知识；
- I2V/T2V 的经验性限制；
- AutoQC 统计得到的模型稳定性经验。

硬能力与经验必须区分：

```text
“模型只支持 5/10/15 秒” → 配置硬约束
“15 秒复杂环绕更易失真” → RAG 经验知识
```

### 7.4 消除词汇重复事实源

`core/semantic_matcher.py` 当前存在重复的 `STYLE_VOCABULARY` 键。同名键会被后面的定义覆盖，导致前面更丰富的同义词失效。

长期目标：

```text
intent_domains.yaml
→ DomainKnowledgeLoader
→ semantic_matcher 构建本地索引
```

`semantic_matcher.py` 只保留算法和最小加载失败 fallback，不再手工维护完整领域词汇。

继续使用并加强：

- `scripts/verify_model_config.py`
- 领域词汇一致性测试
- 新增风格、场景和运镜的回归测试

## 8. 质量闸门

### 8.1 原著覆盖闸门

进入编剧阶段前必须满足：

- 用户选择的每个 `chapter_id` 都出现在覆盖清单；
- 每章存在摘要或可生成摘要；
- 关键事件能够对应到章节；
- 缺失或陈旧索引已显式报告；
- 大纲来源明确。

禁止继续依赖前 12000 字符作为“全部原著”。

### 8.2 剧本审查闸门

人工批准前至少检查：

- 必须保留事件覆盖率；
- 是否遗漏关键因果；
- 是否改变人物关系或秘密；
- 是否存在无依据新增事实；
- 是否泄露所选范围之后的信息；
- 每场是否具有目标、阻力、代价和转折；
- 对白是否承担冲突而非背景说明。

忠实度审查与剧作质量审查应分开计分和报告。

### 8.3 人工编辑一致性闸门

用户保存人工剧本后，现有 `script_entities` 可能陈旧。建议保存时记录：

```json
{
  "script_entities_status": "stale",
  "script_entities_source_hash": "旧哈希"
}
```

批准前重新抽取实体，并要求：

```text
script_entities_source_hash == hash(script_text)
```

否则禁止进入素材库和分镜阶段。

### 8.4 导演审查闸门

生成图片和视频前检查：

- 镜头是否服务场景目标和权力变化；
- 是否过度使用同一景别或无意义运镜；
- 关键揭示是否得到视觉强调；
- 是否可以用动作和空间替代解释性对白；
- 轴线、视线和人物站位是否连续；
- 镜头数量、时长和模型能力是否可执行。

### 8.5 成片审查

保留现有 `auditor` 和 `AutoQC`，并逐步增加：

- 成片相对剧本的叙事覆盖；
- 关键情绪转折是否可感知；
- 镜头是否表达了 `director_breakdown`；
- 技术通过但叙事失败的独立报告。

## 9. 分阶段实施计划

### 阶段 0：建立基线

目标：证明问题并为后续对照提供数据。

任务：

1. 建立包含单章、多章、超 12000 字、非连续章节的固定样本。
2. 记录当前规划、剧本、分镜实际看到的字符范围。
3. 记录关键事件覆盖率、人物一致性和后部章节遗漏率。
4. 固化当前输出作为回归基线。

验收：能够稳定复现后部章节缺失，而不是只依赖人工判断。

### 阶段 1：确定性改编源包

目标：不依赖新增 RAG 能力，先保证所有选中章节进入规划。

任务：

1. 新增 `adaptation_source_bundle` schema 和构建服务。
2. 确定性读取全局大纲、所选章节摘要和改编提示。
3. 为每章生成覆盖清单和 `content_hash`。
4. 让 `planner` 消费完整摘要集合。
5. 将 `source_text[:12000]` 替换为显式上下文预算与覆盖报告。

验收：任意所选章节都出现在规划输入和覆盖报告中；不再静默丢弃。

### 阶段 2：结构化改编方案与剧本

目标：建立专业编剧合同。

任务：

1. 将 `planner` 输出升级为 `adaptation_plan`。
2. `scripter` 按场次生成剧本并记录 `source_refs`。
3. 增加忠实度和剧作质量审查。
4. 前端审核页展示原著证据、改编剧本和审查问题。
5. 修复人工修改后实体陈旧问题。

验收：每个场次可回溯原著；必须保留事件覆盖率可计算。

### 阶段 3：完善并共用小说 RAG

目标：可靠召回场次所需原文证据。

任务：

1. 修复项目过滤 fail-open。
2. 补充章节块定位元数据。
3. 支持精确 `chapter_ids`。
4. 统一章节 upsert 和索引生命周期。
5. 增加索引健康检查和数据库降级路径。
6. 增加检索 trace 和证据引用。

验收：不能串项目；缺失索引不会导致章节静默遗漏；引用可定位原文。

### 阶段 4：导演拆解与导演知识 RAG

目标：让导演负责视听决策，而不是再次改编小说。

任务：

1. 新增 `director_breakdown`。
2. 从 `scene_rules.reason` 和 `prompt_examples` 提炼首批知识卡。
3. 按场景、任务、模型和模态检索导演知识。
4. RAG 只产生候选建议，最终由确定性配置校验。
5. 增加导演审查闸门。

验收：相同场景不再机械套用固定运镜；每个重要镜头有可解释的戏剧理由。

### 阶段 5：领域配置单一事实源

目标：消除 YAML 与 Python 词汇重复。

任务：

1. 让 `semantic_matcher` 从 `DomainKnowledgeLoader` 构建词汇。
2. 删除重复字典定义，仅保留最小 fallback。
3. 扩展 `verify_model_config.py`。
4. 为新风格、场景和运镜建立一致性测试。

验收：新增标准词汇只修改一个权威配置入口，匹配、校验和模型路由同步生效。

## 10. 建议测试矩阵

### 10.1 单元测试

- 改编源包覆盖全部 `chapter_ids`；
- 大纲来源优先级；
- 章节摘要解析和错误降级；
- `adaptation_plan` schema 校验；
- 剧本实体哈希失效与重抽取；
- 强制项目过滤失败时禁止无过滤搜索；
- 章节块 offset 和 hash 正确；
- `semantic_matcher` 从 YAML 加载词汇；
- 重复键和配置漂移检查。

### 10.2 集成测试

- 多章节 DreamWeaver 任务；
- 超 12000 字输入；
- 非连续章节选择；
- 索引缺失、陈旧和不可用；
- 人工修改剧本后继续运行；
- 恢复任务时合同和原著版本一致；
- API 与 Celery 使用同一向量索引；
- 不同用户和项目之间无召回污染。

### 10.3 质量评测

固定比较：

```text
A：当前链路
B：确定性改编源包 + 结构化改编方案
C：B + 原著 RAG
D：C + 导演知识 RAG
```

评价指标：

- 选中章节覆盖率；
- 必须保留事件覆盖率；
- 原著事实冲突数；
- 无依据新增事实数；
- 人物一致性；
- 场景冲突和转折完整性；
- 镜头选择多样性与合理性；
- 可拍摄性；
- 成片叙事可理解性；
- 检索结果有效率；
- 单次任务成本和耗时。

## 11. 可观测性要求

每次运行建议记录：

- 大纲来源与版本；
- 选中章节 ID、编号和正文哈希；
- 每阶段上下文字符数或 token 数；
- 每章是否进入规划；
- RAG 查询、过滤条件、候选数和最终引用；
- 是否发生数据库分块降级；
- `adaptation_plan`、剧本、导演拆解的 schema 版本；
- 忠实度和导演审查结果；
- 人工修改和批准信息；
- 返工目标和原因。

禁止日志记录完整敏感正文。日志只记录 ID、哈希、长度、状态和必要摘要。

## 12. 兼容性与迁移原则

1. 保留现有 `script_text`、`script_entities` 和 `storyboard` 字段，逐步添加新合同。
2. 新字段使用显式 `schema_version`，恢复历史任务时按版本适配。
3. 不要求历史运行全部重建索引；只在重跑到 `SCRIPT` 或更早阶段时检查源版本。
4. 新质量闸门先支持报告模式，再根据评测切换为阻断模式。
5. 向量系统不可用时保留数据库确定性降级，不让整个创作流程因 RAG 故障完全不可用。
6. 不在 Agent 内直接查询数据库或向量库，统一通过服务层构建上下文。

## 13. 明确不做的事项

第一轮不做：

- 新建第二套织梦映心小说知识库；
- 把全部原著、大纲和领域配置一次性塞进提示词；
- 用 Top-K 召回替代章节覆盖；
- 把模型硬约束存入 RAG 并依赖召回执行；
- 一开始引入复杂知识图谱或大量多 Agent；
- 一次性重写整个状态机；
- 在没有评测集的情况下批量灌入影视书籍全文。

## 14. 开发任务模板

后续每个改造任务应至少包含：

```text
目标：本任务解决的单一问题
现状证据：相关文件、调用路径和可复现行为
输入合同：读取哪些字段及版本
输出合同：新增或修改哪些字段及版本
失败策略：阻断、告警或确定性降级
兼容范围：历史运行和旧 API 如何处理
测试：单元、集成和质量样本
可观测性：需要记录哪些非敏感诊断信息
验收标准：可自动验证的完成条件
```

建议按以下顺序创建具体开发任务：

1. 修复 RAG 强制过滤 fail-open。
2. 建立多章节覆盖基线测试。
3. 新增 `adaptation_source_bundle`。
4. 新增结构化 `adaptation_plan`。
5. 分场生成剧本并记录原著引用。
6. 增加剧本忠实度审查。
7. 修复人工剧本与实体不一致。
8. 完善章节向量元数据和索引健康检查。
9. 新增 `director_breakdown`。
10. 建立导演知识卡 RAG。
11. 让 `semantic_matcher` 从 YAML 构建索引。
12. 完善前端证据和审查工作台。

## 15. 完成定义

该方向完成的最低标准不是“已经接入 RAG”，而是同时满足：

1. 所选章节不再被静默截断或遗漏。
2. 全局大纲和章节范围具有确定性覆盖。
3. 每个剧本场次能够回溯原著证据。
4. 编剧改编与导演视听决策职责分离。
5. 剧本批准前完成忠实度和剧作质量检查。
6. 生成素材前完成导演质量检查。
7. RAG 查询严格按用户和项目隔离。
8. 向量系统故障时存在明确、可观测的数据库降级路径。
9. 硬约束继续由配置和结构化校验执行。
10. 新方案通过固定样本证明质量提升，而不是仅增加知识库规模。

最终目标是形成以下稳定闭环：

```text
小说事实
→ 可追溯改编决策
→ 可审查剧本
→ 可解释导演方案
→ 可执行分镜
→ 技术与叙事双重质检
→ 定向返工
```

