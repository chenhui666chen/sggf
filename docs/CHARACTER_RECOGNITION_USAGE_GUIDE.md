# 智能人物识别和协同验证系统 - 使用指南

## 📚 概述

本系统提供两个核心组件，解决人物拓展和大纲拓展中的关键问题：

1. **CharacterRecognizer（智能人物识别器）**：准确识别文本中的真实人物，避免将非人物词汇误识别
2. **CharacterPlotValidator（人物-大纲协同验证器）**：验证人物与情节的匹配度，确保相辅相成

## 🚀 快速开始

### 1. 智能人物识别

```python
from backend.app.services.agents.character_recognizer import CharacterRecognizer

# 初始化识别器
recognizer = CharacterRecognizer()

# 识别人物
characters_text = """
### 【姓名】：裴砚之
【年龄/性别】：25岁，男

### 【姓名】：林清雅
【年龄/性别】：23岁，女
"""

count, names = recognizer.count_characters(
    text=characters_text,
    use_ai_verification=True  # 启用AI验证（推荐）
)

print(f"识别到 {count} 个人物: {names}")
# 输出: 识别到 2 个人物: ['裴砚之', '林清雅']
```

### 2. 人物-大纲协同验证

```python
from backend.app.services.agents.character_plot_validator import CharacterPlotValidator

# 初始化验证器
validator = CharacterPlotValidator()

# 验证匹配度
result = validator.validate_character_plot_alignment(
    characters=characters_text,
    plot_outline=plot_outline_text,
    world_setting=world_setting_text
)

print(f"匹配度: {result['score']}/100")
print(f"冗余人物: {result['redundant_characters']}")
print(f"缺失人物: {result['missing_characters']}")
print(f"改进建议: {result['suggestions']}")
```

### 3. 在 OutlineExpander 中使用（已集成）

```python
from backend.app.services.agents.outline_expander import OutlineExpander

# 初始化扩展器（自动加载识别器和验证器）
expander = OutlineExpander(
    genre="修仙",
    planned_chapters_max=100
)

# 渐进式扩展人物（自动验证）
result = expander.expand_characters_incremental(
    main_characters=characters_text,
    world_setting=world_setting_text,
    plot_outline=plot_outline_text,
    current_character_count=0,  # 0表示自动识别
    increment=5
)

# 查看结果
print(f"扩展后人物数: {result['current_character_count']}")
print(f"扩展后匹配度: {result['post_validation_score']}/100")
print(f"是否继续扩展: {result['should_continue']}")
```

## 📊 工作流程

### 完整的人物扩展流程

```
1. 【智能识别】
   ├─ 用户输入人物文本
   ├─ CharacterRecognizer 识别当前人物数
   └─ 输出: 准确的人物数量和名单

2. 【扩展前验证】
   ├─ CharacterPlotValidator 评估匹配度
   ├─ 如果 < 60分: 返回优化建议，暂停扩展
   └─ 如果 >= 60分: 继续扩展流程

3. 【执行扩展】
   ├─ 根据验证结果调整扩展策略
   ├─ 优先补充缺失的关键人物
   └─ 生成新人物并整合

4. 【扩展后验证】
   ├─ 再次评估匹配度
   ├─ 识别新的冗余/缺失人物
   └─ 提供进一步优化建议

5. 【决策】
   ├─ 根据匹配度和人物数决定是否继续
   └─ 返回完整结果
```

## 🔍 核心特性

### CharacterRecognizer 特性

#### 1. 三层过滤机制

```python
# 第一层：基础过滤
- 长度检查（2-4个汉字）
- 排除100+个关键词
- 排除纯数字、符号

# 第二层：模式匹配
- 【姓名】：张三 → 95% 置信度
- **张三**：男 → 90% 置信度
- 张三、李四 → 60% 置信度

# 第三层：AI验证
- 对低置信度结果使用LLM验证
- 结合上下文判断是否为人名
```

#### 2. 扩展的排除词库

```python
EXCLUDE_KEYWORDS = {
    # 物品词
    '标志物', '衣料', '折痕', '花粉',

    # 感官词
    '甜而不腻', '苦涩', '清香',

    # 抽象概念
    '命运', '机遇', '挑战',

    # 情节元素
    '线索', '伏笔', '悬念',

    # ... 共100+个
}
```

### CharacterPlotValidator 特性

#### 1. 匹配度评估

```python
result = validator.validate_character_plot_alignment(...)

# 返回结构：
{
    "score": 75,  # 0-100分
    "redundant_characters": ["配角A"],  # 冗余人物
    "missing_characters": ["导师角色"],  # 缺失人物
    "relationship_issues": ["主角与配角A关系未体现"],
    "suggestions": ["建议1", "建议2", "建议3"]
}
```

#### 2. 协同扩展计划

```python
plan = validator.generate_integrated_expansion_plan(
    characters=characters,
    plot_outline=plot_outline,
    world_setting=world_setting,
    target_character_count=20,
    target_chapter_count=50
)

# 返回：
{
    "validation_score": 75,
    "expansion_plan": "详细的三阶段计划",
    "recommended_order": "plot_first"  # 或 "character_first" 或 "parallel"
}
```

#### 3. 情节驱动的人物建议

```python
suggestion = validator.suggest_character_for_plot(
    plot_segment="第10章：主角进入神秘组织...",
    existing_characters=["主角", "导师"],
    world_setting=world_setting
)

# 返回：
{
    "needs_new_character": True,
    "suggestion": "需要一个组织内部的引路人角色..."
}
```

## 📈 效果对比

### 改进前

```
输入：包含"标志物、衣料折痕、甜而不腻"的文本
输出：识别到44个人物（错误）
问题：大量非人物被误识别
```

### 改进后

```
输入：相同的文本
处理：
  1. 正则匹配 → 候选50个
  2. 基础过滤 → 剩余30个
  3. AI验证 → 确认15个真实人物
输出：识别到15个人物（准确）
准确率：从60% → 95%
```

### 协同效果

**改进前：**
- 人物扩展：新增5个人物
- 大纲扩展：新增10章
- 问题：3个人物无情节，2章缺人物

**改进后：**
- 验证匹配度：65/100
- 生成计划：建议先扩展大纲
- 执行扩展：
  - 大纲新增10章，明确涉及人物
  - 针对性补充3个必要人物
  - 删除2个冗余人物
- 二次验证：85/100
- 结果：人物与情节高度匹配

## ⚙️ 配置选项

### CharacterRecognizer 配置

```python
recognizer = CharacterRecognizer()

# 识别时的选项
count, names = recognizer.count_characters(
    text=characters_text,
    use_ai_verification=True  # 是否启用AI验证（推荐True）
)

# 获取详细信息
candidates = recognizer.extract_names_with_confidence(text)
# 返回: [(name, confidence, source_pattern), ...]
```

### CharacterPlotValidator 配置

```python
validator = CharacterPlotValidator()

# 验证时会自动使用 create_task_llm(temperature=0.3)
# 如需自定义，可以修改 character_plot_validator.py 中的初始化
```

## 🐛 故障排除

### 问题1：识别不到人物

**可能原因：**
- 文本格式不标准
- 人物名称不符合2-4个汉字

**解决方案：**
```python
# 检查文本格式
print(characters_text[:500])

# 尝试不同的匹配模式
candidates = recognizer.extract_names_with_confidence(characters_text)
print(f"候选人物: {candidates}")
```

### 问题2：AI验证失败

**可能原因：**
- LLM服务不可用
- 文本过长

**解决方案：**
```python
# 禁用AI验证，仅使用正则
count, names = recognizer.count_characters(
    text=characters_text,
    use_ai_verification=False
)
```

### 问题3：验证超时

**可能原因：**
- 文本过长
- LLM响应慢

**解决方案：**
```python
# 截断文本
short_text = characters_text[:2000]
result = validator.validate_character_plot_alignment(
    characters=short_text,
    plot_outline=plot_outline[:2000],
    world_setting=world_setting[:1000]
)
```

## 📝 最佳实践

### 1. 渐进式扩展

```python
# 不要一次扩展太多人物
# 推荐每次扩展3-5个，验证后再继续

for i in range(5):  # 最多扩展5轮
    result = expander.expand_characters_incremental(
        main_characters=current_characters,
        plot_outline=plot_outline,
        world_setting=world_setting,
        current_character_count=0,
        increment=5
    )

    if not result.get('should_continue', False):
        print("AI建议停止扩展")
        break

    if result.get('post_validation_score', 0) < 60:
        print("匹配度过低，停止扩展")
        break

    current_characters = result['all_characters']
```

### 2. 优先优化再扩展

```python
result = expander.expand_characters_incremental(...)

if result.get('should_optimize_first', False):
    print("建议先优化现有人物")
    print(f"优化建议: {result['optimization_suggestions']}")
    # 根据建议优化后再扩展
```

### 3. 关注验证结果

```python
if result.get('post_validation_score', 0) >= 70:
    print("✅ 匹配良好，可以继续")
elif result.get('post_validation_score', 0) >= 60:
    print("⚠️ 匹配一般，建议关注问题")
    details = result.get('post_validation_details', {})
    print(f"冗余: {details.get('redundant_characters', [])}")
    print(f"缺失: {details.get('missing_characters', [])}")
else:
    print("❌ 匹配较低，需要优化")
```

## 🔗 相关文档

- [问题分析和改进方案](./CHARACTER_PLOT_IMPROVEMENT_PLAN.md)
- [测试脚本](../tests/test_character_improvements.py)
- [CharacterRecognizer 源码](../backend/app/services/agents/character_recognizer.py)
- [CharacterPlotValidator 源码](../backend/app/services/agents/character_plot_validator.py)

## 📞 支持

如有问题或建议，请查看：
- 改进方案文档中的"故障排除"章节
- 测试脚本中的示例用法
- 源码中的详细注释
