# 人物防扁平化与动态演变改造指导

## 1. 文档目的

本文指导小说创作链路补齐以下闭环：

```text
人物基线生成
  -> 结构化保存
  -> 写作运行态编译
  -> 章节生成与续写
  -> 章节事件提取
  -> 人物状态快照/变更记录
  -> 下一章节继续注入
```

本文不是“新增更多人物字段”的简单清单。改造重点是确保已有的人物信息真正进入写作上下文，并且能够区分稳定基线与剧情驱动的动态状态。

## 2. 当前事实与结论

### 2.1 已有能力

`ParsedCharacter` 已包含较完整的人物基线字段：

- `personality`
- `worldview`
- `motivation`
- `abilities`
- `limitation`
- `background`
- `growth_direction`
- `relationships`
- `mainline_role`
- `mainline_clues`

`ParsedCharacter.build_profile()` 已经能够输出“性格锚点”“核心动机”“能力与限制”“成长方向”等段落。

`Character` ORM 也已经保存身份、阵营、关系、题材扩展字段和部分动态状态，例如 `appearance_status`、`life_status`、`current_realm_item_id`、`relations`、`genre_fields_json`。因此，不能将当前问题描述为“数据库没有人物结构化能力”。

### 2.2 已确认的主要断点

`backend/app/services/character_runtime_context.py` 中的 `build_character_runtime_brief()` 当前编译身份、动机、关系和主线信息，但没有接收或输出 `personality`、`worldview`。

该函数被以下运行态上下文构建函数使用：

- `build_core_character_anchor_context_from_text()`
- `build_character_prompt_context_from_text()`
- `build_character_runtime_metadata()`

因此，角色卡中的性格和价值倾向在依赖运行态摘要的写作路径中存在断链。该问题是 P0 优先级。

### 2.3 需要谨慎表述的第 1 章问题

不能笼统地说“第 1 章完全没有人物上下文”。当前 `execute_streaming` 路径已经尝试使用人物 RAG，并在 RAG 为空时回退到 `build_character_prompt_context_from_text()` 或截断后的角色文本。

仍需核对旧 coordinator、后台任务、章节重写和分段生成路径是否使用同一套上下文编译器。P1 的目标应是统一所有章节生成入口，而不是只修改一个第 1 章调用点。

## 3. 改造原则

### 3.1 基线与动态状态分离

稳定人物基线不能被章节状态覆盖：

- 基线：性格、价值观、原始动机、能力、限制、成长方向。
- 动态状态：当前目标、当前信念、情绪状态、关系变化、能力变化、已知信息和状态证据。

### 3.2 单一运行态编译入口

所有写作路径都应调用统一的人物上下文编译器，避免每条链路自行拼接角色文本。

### 3.3 先注入、后校验、再持久化

生成前注入人物约束，生成后检查行为是否违背基线或当前状态，再保存可追溯的状态变化。

### 3.4 向后兼容

旧角色档案可能无法解析完整字段。缺失字段应返回空值并保留已有 `profile`/原始文本回退，不得因单个角色解析失败而阻断章节生成。

## 4. 分阶段实施方案

## P0：修复运行态性格注入

### 4.1 修改范围

目标文件：

- `backend/app/services/character_runtime_context.py`
- 相关运行态上下文测试

### 4.2 接口调整

为 `build_character_runtime_brief()` 增加可选参数：

```python
personality: Any = None,
worldview: Any = None,
limitation: Any = None,
growth_direction: Any = None,
```

第一阶段至少输出性格和价值倾向：

```text
性格：谨慎多疑，先验证后行动；价值倾向：重承诺胜过个人利益
```

建议对每个字段分别截断，并对最终片段设置总长度上限，避免角色数量增加后挤占章节写作 token。

### 4.3 调用点同步

在以下函数调用 `build_character_runtime_brief()` 时传入对应 `ParsedCharacter` 字段：

- `build_core_character_anchor_context_from_text()`
- `build_character_prompt_context_from_text()`
- `build_character_runtime_metadata()`

不要在 `ChapterPromptBuilder` 内再次解析角色文本。`ChapterPromptBuilder` 只负责 prompt 结构，不负责人物业务规则。

### 4.4 P0 验收

至少增加以下测试：

1. 给定包含 personality/worldview 的角色卡，运行态摘要包含这两个字段。
2. 两个角色身份和动机相同、性格不同，摘要仍然可区分。
3. personality/worldview 为空时，输出与旧逻辑兼容。
4. 超长字段被截断，且不会超过函数约定的总长度。
5. `build_core_character_anchor_context_from_text()` 和 `build_character_prompt_context_from_text()` 均能看到性格锚点。

## P1：统一章节生成入口的人物上下文

### 5.1 建立调用路径矩阵

在修改前列出所有 `ChapterPromptBuilder.build_user_prompt()` 调用位置，至少覆盖：

- streaming 首章生成
- 普通章节续写
- 后台生成
- 分段生成
- 章节重写/修订
- 旧 coordinator 或备用路径

每个入口记录：

- 是否传入 `core_character_anchor_context`
- 是否传入 `focus_character_relationship_context`
- 是否传入 `character_runtime_context`
- 是否传入 `rag_character_context`
- 是否有原始角色文本回退

### 5.2 统一构建顺序

推荐顺序：

```text
当前章节人物筛选
  -> 核心人物锚点
  -> 焦点人物关系
  -> 人物运行态摘要
  -> RAG 细节补充
  -> 原始角色文本作为最后回退
```

首章没有前文状态时，应明确使用“初始基线”而不是空字符串。后续章节则优先使用当前状态快照，再用角色基线补充稳定约束。

### 5.3 P1 验收

1. 所有章节生成入口都有统一的人物上下文来源。
2. 首章至少注入核心人物的身份、动机、性格锚点和价值倾向。
3. RAG 为空时仍能依靠角色文本生成有效上下文。
4. 某个角色解析失败不会导致整章 prompt 构建失败。
5. 测试能够断言最终 `user_prompt` 中出现人物上下文，而不是只断言上游函数返回非空。

## P2：持久化人物基线与动态快照

### 6.1 第一阶段：增加基线字段

如果产品确实需要数据库级查询，建议为 `characters` 表增加以下可空列：

- `personality`
- `worldview`
- `motivation`
- `limitation`
- `growth_direction`

字段应使用 `Text`，因为这些内容不是稳定枚举值，也不适合限制在短字符串长度内。

同步逻辑 `sync_parsed_characters_to_db()` 需要同时处理创建和更新，并遵守现有的非空优先策略，避免空解析结果覆盖已有值。

必须提供 Alembic 迁移，并验证旧数据可正常启动。迁移不应删除或重写 `profile`。

### 6.2 第二阶段：增加章节级状态快照

不要把动态状态直接写回上述基线列。建议新建类似 `character_state_snapshots` 的表，最小字段包括：

- `id`
- `project_id`
- `character_id`
- `chapter_id`
- `current_motivation`
- `current_belief`
- `emotional_state`
- `relationship_state_json`
- `known_information`
- `state_changes_json`
- `evidence_text`
- `created_at`

同一角色同一章节应具备唯一约束，重复保存应幂等。

### 6.3 P2 验收

1. 新角色基线字段可从 `ParsedCharacter` 正确同步。
2. 旧角色没有这些字段时仍可通过 `profile` 回退。
3. 动态快照不会修改原始人物基线。
4. 快照可按章节排序并恢复某一章节的人物状态。
5. 重复执行章节后保存不会生成重复快照。

## P3：说话风格与行为一致性

### 7.1 speech_style 字段

可在 `ParsedCharacter` 增加可选 `speech_style`，但应控制职责范围。建议包含：

- 语气和句式
- 常用表达
- 称谓习惯
- 禁用或回避的表达
- 情绪激烈时的变化

首期不要引入复杂的语音学模型或独立风格服务，只将其压缩为写作 prompt 可用的短摘要。

### 7.2 生成后校验

在质量审查或章节后处理阶段增加可解释检查：

- 是否出现明显违背核心价值观的行为。
- 是否无视人物能力限制。
- 是否在没有剧情证据时突然改变动机或关系。
- 同场角色对白是否出现高度同质化。

检查结果应给出证据片段和严重等级，不建议首期直接自动回滚全文。可以先作为质量评分和修订提示，避免误判破坏用户稿件。

### 7.3 P3 验收

1. 同一角色在不同章节的语言风格具有可检测的稳定特征。
2. 角色状态变化必须能关联到章节或事件证据。
3. 校验失败结果可定位到角色、章节和文本片段。
4. 校验模块不阻断缺少旧字段的历史项目。

## 5. 推荐的数据流

```text
角色扩展文本
  -> CharacterTextParser
  -> ParsedCharacter
  -> Character 基线字段 + profile
                          |
                          v
                 运行态上下文编译器
                          |
                          +--> 核心角色锚点
                          +--> 焦点人物关系
                          +--> 人物当前状态
                          +--> RAG 细节
                          |
                          v
                     ChapterPromptBuilder
                          |
                          v
                       章节生成
                          |
                          v
                   章节后处理/状态提取
                          |
                          v
                 CharacterStateSnapshot
```

## 6. 不建议的实现方式

### 6.1 不要只把完整 profile 原样塞进每个 prompt

这会造成 token 浪费、上下文噪声和不同入口行为不一致。应由运行态编译器按角色重要性和当前章节筛选字段。

### 6.2 不要用动态值覆盖静态基线

例如不能把“当前因背叛而动摇”直接覆盖原始 worldview。应保存为章节状态或变更记录。

### 6.3 不要只修改 streaming 路径

如果旧 coordinator、后台任务和重写路径仍使用旧逻辑，人物一致性会因入口不同而变化。

### 6.4 不要把质量审查当作事前约束

质量审查只能发现部分问题。核心人物约束必须在生成前进入 prompt，生成后再用审查补强。

## 7. 测试策略

### 7.1 单元测试

- 角色字段清洗、截断和空值兼容。
- 运行态摘要字段完整性。
- 角色优先级筛选和上下文总长度限制。
- 状态快照幂等写入。

### 7.2 集成测试

- 从角色卡文本解析到数据库同步。
- 从数据库/角色文本到章节 prompt。
- RAG 有值、无值、异常时的回退链路。
- 首章、续写、重写路径使用同一人物上下文规则。

### 7.3 回归测试

重点覆盖：

- 历史项目只有 `profile` 没有新字段。
- 旧格式角色卡无法完整解析。
- 关系字段是 JSON、纯文本或损坏 JSON。
- 多角色超过上下文上限。
- 角色已归档但仍被历史章节引用。

## 8. 验收指标

改造完成后，不以“数据库多了几列”作为完成标准，而以以下行为验收：

1. 首章和续写 prompt 中，核心人物能稳定出现性格和价值倾向。
2. 同身份、同动机但不同性格的角色在运行态摘要中可区分。
3. 章节生成入口之间的人物上下文内容和优先级一致。
4. 动态状态不会覆盖人物基线，并能追溯到章节证据。
5. 缺失字段的历史项目仍可生成章节。
6. 人物行为偏离人设时，系统能指出角色、章节、原因和证据。

## 9. 推荐实施顺序

```text
第一步：补运行态 personality/worldview 注入并加单测
第二步：盘点并统一所有章节生成入口
第三步：增加 Character 基线列和同步迁移
第四步：设计并落地章节级动态状态快照
第五步：增加 speech_style 与生成后行为一致性检查
```

P0 和 P1 可以独立上线；P2 涉及数据库迁移和状态模型，应在 P0/P1 的上下文链路稳定后实施；P3 应以可观测质量检查起步，不要一开始就引入自动全文回滚。

## 10. 相关代码位置

- `backend/app/services/character_parser_pkg/_dataclasses.py`
- `backend/app/services/character_parser_pkg/_sync.py`
- `backend/app/services/character_runtime_context.py`
- `backend/app/services/agents/chapter_prompt_builder.py`
- `backend/app/api/v1/workflow/execute_streaming.py`
- `backend/app/services/auto_tracking.py`
- `backend/app/services/chapter_post_save.py`
- `backend/app/services/agents/character_plot_validator.py`
- `backend/app/models/character.py`

