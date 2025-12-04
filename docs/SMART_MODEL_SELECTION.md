# 🤖 智能模型选择机制

## 📋 概述

随着小说章节的增加，输入上下文会越来越长。为了应对这一挑战，我们实现了**智能模型选择机制**，根据章节数自动选择最合适的AI模型。

## 🎯 核心策略

### 模型对比

| 模型 | 输入限制 | 适用场景 | 优势 | 成本 |
|------|---------|---------|------|------|
| **qwen-max** | 30,720 tokens | 短篇小说（<20章） | 文笔最好、速度快 | 低 |
| **qwen-long** | 10,000,000 tokens | 中长篇小说（20-100章） | 几乎无限制 | 中 |
| **deepseek-r1** | 128,000 tokens | 复杂推理、规划 | 逻辑推理强 | 低 |

### 智能选择规则

#### 📌 章节规划阶段（Planning Stage）

```
0-50章：  qwen-max  （85% token使用率）
50+章：   qwen-long （30% token使用率，更宽松）
```

**理由**：
- 章节规划需要强推理能力，qwen-max表现最佳
- 规划阶段输入相对较少，50章内可用qwen-max
- 50章以上切换到qwen-long，放宽限制至30%使用率

#### 📌 内容创作阶段（Content Creation Stage）

```
0-20章：   qwen-max  （85% token使用率）
20-50章：  qwen-long （40% token使用率）
50+章：    qwen-long （20% token使用率，非常宽松）
```

**理由**：
- 内容创作需要最好的文笔，优先使用qwen-max
- 20章后输入变长，切换到qwen-long
- 随着章节增加，逐步放宽限制（40% → 20%）

## 📊 Token预算动态调整

### qwen-max模式（0-20章）

```python
'previous_chapters_analysis': 8,000 tokens
'chapter_plan': 3,000 tokens
'characters': 4,000 tokens
'world_setting': 4,000 tokens
'plot_outline': 6,000 tokens
```

**总预算**：~26,000 tokens（85%使用率）

### qwen-long模式（20-50章）

```python
'previous_chapters_analysis': 15,000 tokens  # 约2倍
'chapter_plan': 5,000 tokens
'characters': 8,000 tokens
'world_setting': 8,000 tokens
'plot_outline': 12,000 tokens  # 约2倍
```

**总预算**：~120,000 tokens（40%使用率）

### qwen-long模式（50+章）

```python
'previous_chapters_analysis': 30,000 tokens  # 约4倍
'chapter_plan': 8,000 tokens
'characters': 15,000 tokens
'world_setting': 15,000 tokens
'plot_outline': 25,000 tokens  # 约4倍
```

**总预算**：~300,000 tokens（20%使用率）

## 🔧 实现细节

### 1. 上下文优化器（ContextOptimizer）

```python
# backend/app/services/agents/context_optimizer.py

class ContextOptimizer:
    # 智能模型选择策略
    MODEL_SELECTION_STRATEGY = {
        'chapter_planning': {
            'thresholds': [
                (0, 50, 'qwen-max', 0.85),
                (50, 999, 'qwen-long', 0.30),
            ]
        },
        'content_creation': {
            'thresholds': [
                (0, 20, 'qwen-max', 0.85),
                (20, 50, 'qwen-long', 0.40),
                (50, 999, 'qwen-long', 0.20),
            ]
        }
    }
    
    def __init__(self, current_chapter: int, stage: str):
        # 智能选择模型和目标比例
        self.selected_model, self.target_token_ratio = self._select_model_and_ratio()
```

### 2. 工作流集成（Workflow）

```python
# backend/app/api/v1/workflow.py

# 章节规划阶段
context_optimizer = get_context_optimizer(
    current_chapter=next_chapter_number,
    stage='chapter_planning'
)
selected_plan_model = context_optimizer.selected_model

chapter_plan = await streaming_service.generate_chapter_streaming(
    prompt=plan_user_prompt,
    system_prompt=plan_system_prompt,
    on_chunk=on_plan_chunk,
    model=selected_plan_model,  # 使用智能选择的模型
)

# 内容创作阶段
context_optimizer = get_context_optimizer(
    current_chapter=next_chapter_number,
    stage='content_creation'
)
selected_content_model = context_optimizer.selected_model

chapter_draft = await streaming_service.generate_chapter_streaming(
    prompt=content_user_prompt,
    system_prompt=content_system_prompt,
    on_chunk=on_content_chunk,
    model=selected_content_model,  # 使用智能选择的模型
)
```

## 📈 效果分析

### 场景1：短篇小说（10章）

- **使用模型**：qwen-max
- **Token使用**：约15,000 tokens
- **优势**：最佳文笔质量，响应快速
- **成本**：低

### 场景2：中篇小说（30章）

- **使用模型**：qwen-long
- **Token使用**：约80,000 tokens
- **优势**：充足的上下文空间
- **成本**：中等

### 场景3：长篇小说（80章）

- **使用模型**：qwen-long
- **Token使用**：约250,000 tokens
- **优势**：几乎无限制的上下文
- **成本**：中等

## ✅ 优势总结

1. **自动适应**：根据章节数自动选择最佳模型
2. **成本优化**：短篇用qwen-max（便宜），长篇用qwen-long（必要）
3. **质量保证**：优先使用最佳文笔模型（qwen-max）
4. **动态放宽**：随着章节增加，逐步放宽token限制
5. **透明可控**：日志清晰显示模型选择和token使用情况

## 🚀 未来优化方向

1. **用户自定义**：允许用户手动覆盖模型选择
2. **成本监控**：实时显示token消耗和成本估算
3. **混合策略**：对于特别长的大纲，可能分段处理
4. **缓存机制**：重复使用的内容（如世界观）可以缓存

## 📝 使用建议

### 何时需要调整阈值？

如果你发现：
- **20章就超限了**：降低阈值到15章
- **30章才超限**：提高阈值到25章
- **大纲特别长**：降低`plot_outline`的max_tokens

### 如何调整？

修改 `context_optimizer.py` 中的 `MODEL_SELECTION_STRATEGY`：

```python
'content_creation': {
    'thresholds': [
        (0, 15, 'qwen-max', 0.85),     # 改为15章
        (15, 40, 'qwen-long', 0.40),   # 15-40章
        (40, 999, 'qwen-long', 0.20),  # 40+章
    ]
}
```

## 🎉 总结

智能模型选择机制让你的小说创作系统能够**自动适应不同规模的项目**，从短篇到长篇都能流畅运行，既保证质量又控制成本！
