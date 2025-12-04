# 大模型分配方案

## 📋 实施日期
2025-12-04

## 🎯 核心原则
- **质量优先**：核心创作任务使用高质量模型
- **场景适配**：超长输入用 qwen-long，深度推理用 DeepSeek R1
- **效率兼顾**：工具类任务使用 qwen-turbo

---

## 🔧 工作流阶段模型分配

| 阶段 | 模型 | 原因 | 任务类型参数 |
|-----|------|------|-------------|
| **1. 故事概念开发** | qwen-max | 需要创意思维和文笔质量 | `concept` |
| **2. 世界观设定** | deepseek-reasoner | 逻辑体系构建最强 | `worldview` |
| **3. 人物设定** | deepseek-reasoner | 人物关系深度分析 | `character` |
| **4. 情节大纲生成** | qwen-long | 需要1+2+3所有内容（超长输入） | `outline` |
| **5. 章节生成** | qwen-max | 文笔质量和创意 | `chapter` |

---

## 🔧 知识库功能模型分配

| 功能 | 模型 | 原因 | 任务类型参数 |
|-----|------|------|-------------|
| **扩展人物** | deepseek-reasoner | 深度推理，分析人物关系 | `character_expand` |
| **扩展大纲** | qwen-long | 115章重构（超长输入） | `outline_expand` |
| **对话优化** | qwen-max | 人物性格一致性 | `dialogue` |
| **AI痕迹处理** | qwen-max | 文笔自然度最高 | `ai_trace` |
| **实体提取** | qwen-turbo | 结构化任务，速度优先 | `entity_extract` |

---

## 📊 模型使用统计

- **qwen-max**（4次）→ 核心创作任务
  - 故事概念开发
  - 章节生成
  - 对话优化
  - AI痕迹处理

- **DeepSeek R1**（3次）→ 逻辑规划任务
  - 世界观设定
  - 人物设定
  - 扩展人物

- **qwen-long**（2次）→ 超长输入任务
  - 情节大纲生成
  - 扩展大纲

- **qwen-turbo**（1次）→ 辅助工具任务
  - 实体提取

---

## 🛠️ 技术实现

### 核心函数：`create_deepseek_llm(task_type)`

**位置**：`backend/app/services/agents/novel_agent.py`

**参数**：
- `task_type`：任务类型标识（默认 "default"）

**自动选择**：
1. 根据 `task_type` 查找对应模型
2. 自动切换 API 配置（阿里云/DeepSeek）
3. 记录日志：任务类型 → 模型 → API

**示例**：
```python
# 扩展大纲时使用 qwen-long
llm = create_deepseek_llm(task_type="outline_expand")

# 扩展人物时使用 deepseek-reasoner
llm = create_deepseek_llm(task_type="character_expand")

# 章节生成时使用 qwen-max
llm = create_deepseek_llm(task_type="chapter")
```

---

## ✅ 已完成的实施

### 1. ✅ 核心函数更新
- [x] 修改 `create_deepseek_llm()` 支持任务类型参数
- [x] 添加任务类型到模型的映射表
- [x] 实现自动API切换逻辑
- [x] 添加关键配置变更日志

### 2. ✅ 扩展器更新
- [x] `OutlineExpander` 使用 `task_type="outline_expand"`

---

## 🔄 待完成的实施

### 3. ⏳ 各Agent更新
需要更新各个Agent的初始化：
- [ ] `CreativeDirectorAgent` → `task_type="concept"`
- [ ] `WorldArchitectAgent` → `task_type="worldview"`
- [ ] `CharacterDesignerAgent` → `task_type="character"`
- [ ] `PlotArchitectAgent` → `task_type="outline"`
- [ ] `ContentCreatorAgent` → `task_type="chapter"`
- [ ] `DialogueAuthenticityEngine` → `task_type="dialogue"`
- [ ] `AITraceReductionProcessor` → `task_type="ai_trace"`
- [ ] `EntityExtractionService` → `task_type="entity_extract"`

---

## 📝 使用说明

### 当前生效范围
✅ **知识库扩展功能**已启用智能模型分配：
- 扩展大纲 → qwen-long
- 扩展人物 → deepseek-reasoner（需后续更新Agent）

### 完全生效时机
待所有Agent更新后，工作流所有阶段将自动使用最优模型。

---

## 🔔 注意事项

1. **DeepSeek R1 限制**：不能设置 `request_timeout` 和 `max_retries`
2. **qwen-long 优势**：支持 1000万 tokens（是 R1 的 156 倍）
3. **日志验证**：每次调用会输出：`🤖 [模型选择] 任务类型=xxx → 模型=xxx`

---

## 📚 相关文件

- `backend/app/services/agents/novel_agent.py` - 核心函数
- `backend/app/services/agents/outline_expander.py` - 扩展器
- `backend/app/services/agents/agents.py` - 各Agent定义
- `backend/app/services/agents/config.py` - 配置管理
- `backend/.env` - 环境变量（当前使用 qwen-long）
