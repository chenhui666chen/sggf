# 人物拓展与大纲拓展问题分析及改进方案

## 📋 问题总结

### 问题1：人物识别错误 - 将非人物识别为人物

**现象：**
```
✅ 正则识别到人物数: 44 (标志物, 裴砚之, 甜而不腻, 衣料折痕, 通过花粉...)
```

**根本原因：**
1. **正则表达式过于宽泛**
   - 当前匹配：`([一-龥]{2,4})、` 匹配所有2-4个汉字+顿号
   - 问题：无法区分"张三、李四"（人名）和"标志物、衣料"（物品）

2. **排除关键词不完善**
   - 当前只排除了27个关键词
   - 缺少：物品词、感官词、抽象概念词等

3. **缺少语义验证**
   - 匹配后没有二次验证
   - 低置信度结果直接采纳

**代码位置：** `backend/app/services/agents/outline_expander.py:192-284`

---

### 问题2：人物与大纲脱节

**现象：**
- 人物扩展后，部分人物在大纲中没有对应情节
- 大纲扩展后，部分情节缺少必要的人物支撑
- 人物关系设定丰富，但情节中未体现

**根本原因：**
1. **独立扩展机制**
   - `expand_characters()` 和 `expand_plot_outline()` 独立执行
   - 没有双向验证机制

2. **缺少协同规划**
   - 扩展前不评估人物-情节匹配度
   - 扩展后不验证新增内容的关联性

3. **提示词设计问题**
   - 人物扩展提示词只要求"在情节中的作用"，但不强制验证
   - 大纲扩展提示词不要求明确每个情节涉及的人物

**代码位置：**
- 人物扩展：`outline_expander.py:1187-1400`
- 大纲扩展：`outline_expander.py:286-437`

---

## 🔧 改进方案

### 方案1：智能人物识别器（已实现）

**新增文件：** `backend/app/services/agents/character_recognizer.py`

**核心改进：**

1. **三层过滤机制**
   ```python
   # 第一层：基础过滤
   - 长度检查（2-4字）
   - 排除关键词（扩展到100+个）
   - 排除纯数字、符号

   # 第二层：模式匹配
   - 高置信度：【姓名】：张三（95%）
   - 中置信度：**张三**：男（90%）
   - 低置信度：张三、李四（60%）

   # 第三层：AI语义验证
   - 对低置信度结果使用LLM验证
   - 结合上下文判断是否为人名
   ```

2. **扩展的排除词库**
   ```python
   EXCLUDE_KEYWORDS = {
       # 物品词
       '标志物', '衣料', '折痕', '花粉', '气味', '声音',

       # 感官词
       '甜而不腻', '苦涩', '清香', '浓郁', '淡雅',

       # 抽象概念
       '命运', '机遇', '挑战', '困境', '转折',

       # 情节元素
       '线索', '伏笔', '悬念', '反转', '铺垫',

       # ... 共100+个
   }
   ```

3. **置信度评分系统**
   - 根据匹配模式给出置信度
   - 低于85%的自动触发AI验证
   - 返回验证后的人物列表

**使用方式：**
```python
from app.services.agents.character_recognizer import CharacterRecognizer

recognizer = CharacterRecognizer()
count, names = recognizer.count_characters(
    text=characters_text,
    use_ai_verification=True  # 启用AI验证
)
print(f"识别到 {count} 个人物: {names}")
```

---

### 方案2：人物-大纲协同验证器（已实现）

**新增文件：** `backend/app/services/agents/character_plot_validator.py`

**核心功能：**

#### 2.1 匹配度评估
```python
validator = CharacterPlotValidator()
result = validator.validate_character_plot_alignment(
    characters=characters,
    plot_outline=plot_outline,
    world_setting=world_setting
)

# 返回结果：
{
    "score": 75,  # 匹配度评分 0-100
    "redundant_characters": ["配角A", "配角B"],  # 冗余人物
    "missing_characters": ["反派导师", "中立商人"],  # 缺失人物
    "relationship_issues": ["主角与配角A的关系未在情节中体现"],
    "suggestions": ["建议1", "建议2", "建议3"]
}
```

#### 2.2 协同扩展计划
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
    "expansion_plan": "详细的三阶段扩展计划",
    "recommended_order": "plot_first"  # 或 "character_first" 或 "parallel"
}
```

#### 2.3 情节驱动的人物建议
```python
suggestion = validator.suggest_character_for_plot(
    plot_segment="第10章：主角进入神秘组织...",
    existing_characters=["主角", "导师", "对手"],
    world_setting=world_setting
)

# 返回：
{
    "needs_new_character": True,
    "suggestion": "需要一个组织内部的引路人角色..."
}
```

---

### 方案3：改进扩展流程

**当前流程：**
```
1. 扩展人物（独立）
2. 扩展大纲（独立）
3. 完成
```

**改进后流程：**
```
1. 【验证阶段】评估当前人物-情节匹配度
   ├─ 如果 < 60分：先优化现有关联
   └─ 如果 >= 60分：继续扩展

2. 【规划阶段】生成协同扩展计划
   ├─ 识别冗余人物 → 删除或整合
   ├─ 识别缺失人物 → 优先补充
   └─ 确定扩展顺序（大纲优先/人物优先/并行）

3. 【执行阶段】按计划扩展
   ├─ 如果大纲优先：
   │   ├─ 扩展大纲
   │   ├─ 分析新情节需要的人物
   │   └─ 针对性扩展人物
   │
   └─ 如果人物优先：
       ├─ 扩展人物
       ├─ 为每个新人物设计情节线
       └─ 扩展大纲以容纳新人物

4. 【验证阶段】二次验证
   ├─ 检查每个人物是否有情节支撑
   ├─ 检查每个情节是否有人物执行
   └─ 生成优化建议
```

---

## 🎯 集成方案

### 修改 `outline_expander.py`

在 `expand_characters_incremental()` 方法中集成新组件：

```python
def expand_characters_incremental(self, main_characters: str, world_setting: str,
                                 plot_outline: str, current_character_count: int,
                                 increment: int = 5) -> Dict[str, Any]:
    """渐进式扩展人物体系（改进版）"""

    # 🆕 步骤1：使用智能识别器统计人物
    from app.services.agents.character_recognizer import CharacterRecognizer

    recognizer = CharacterRecognizer()
    if current_character_count == 0:
        current_character_count, character_names = recognizer.count_characters(
            main_characters,
            use_ai_verification=True
        )
        print(f"🎯 智能识别：当前有 {current_character_count} 个人物")

    # 🆕 步骤2：验证人物-情节匹配度
    from app.services.agents.character_plot_validator import CharacterPlotValidator

    validator = CharacterPlotValidator()
    validation = validator.validate_character_plot_alignment(
        characters=main_characters,
        plot_outline=plot_outline,
        world_setting=world_setting
    )

    print(f"📊 人物-情节匹配度: {validation['score']}/100")

    # 🆕 步骤3：根据匹配度决定策略
    if validation['score'] < 60:
        print("⚠️ 匹配度较低，优先优化现有人物与情节的关联")
        # 返回优化建议而不是直接扩展
        return {
            "should_optimize_first": True,
            "validation": validation,
            "optimization_suggestions": validation['suggestions']
        }

    # 🆕 步骤4：生成协同扩展计划
    plan = validator.generate_integrated_expansion_plan(
        characters=main_characters,
        plot_outline=plot_outline,
        world_setting=world_setting,
        target_character_count=current_character_count + increment,
        target_chapter_count=len(plot_outline.split('##'))
    )

    print(f"📋 扩展策略: {plan['recommended_order']}")

    # 步骤5：执行扩展（原有逻辑）
    # ... 原有的扩展代码 ...

    # 🆕 步骤6：扩展后验证
    post_validation = validator.validate_character_plot_alignment(
        characters=expanded_characters,
        plot_outline=plot_outline,
        world_setting=world_setting
    )

    print(f"✅ 扩展后匹配度: {post_validation['score']}/100")

    return {
        "all_characters": expanded_characters,
        "current_character_count": current_character_count + increment,
        "pre_validation_score": validation['score'],
        "post_validation_score": post_validation['score'],
        "should_continue": post_validation['score'] >= 70,
        # ... 其他返回值 ...
    }
```

---

## 📊 预期效果

### 改进前
```
输入：人物文本（包含"标志物、衣料折痕"等）
输出：识别到44个人物（错误）
问题：大量非人物被识别
```

### 改进后
```
输入：相同的人物文本
处理：
  1. 正则匹配 → 候选50个
  2. 基础过滤 → 剩余30个
  3. AI验证 → 确认15个真实人物
输出：识别到15个人物（准确）
```

### 协同效果

**改进前：**
- 人物扩展：新增5个人物
- 大纲扩展：新增10章
- 问题：3个人物在大纲中无情节，2章缺少关键人物

**改进后：**
- 验证匹配度：65/100
- 生成计划：建议先扩展大纲，再针对性补充人物
- 执行扩展：
  - 大纲新增10章，明确每章涉及的人物
  - 根据新情节补充3个必要人物
  - 删除2个冗余人物
- 二次验证：85/100
- 结果：人物与情节高度匹配

---

## 🚀 实施步骤

### 第一步：集成智能识别器（立即）
1. 在 `outline_expander.py` 中导入 `CharacterRecognizer`
2. 替换 `count_characters_in_text()` 方法
3. 测试识别准确率

### 第二步：集成协同验证器（优先）
1. 在扩展前调用 `validate_character_plot_alignment()`
2. 根据匹配度决定是否继续扩展
3. 扩展后再次验证

### 第三步：优化提示词（重要）
1. 人物扩展提示词：强制要求每个人物关联具体情节
2. 大纲扩展提示词：要求每章明确涉及的人物
3. 添加"人物-情节对照表"输出要求

### 第四步：添加用户反馈（可选）
1. 在前端显示匹配度评分
2. 显示冗余/缺失人物提示
3. 允许用户选择扩展策略

---

## 💡 额外建议

### 1. 渐进式验证
不要等到扩展完成才验证，而是：
- 每扩展5个人物 → 验证一次
- 每扩展10章 → 验证一次
- 及时调整策略

### 2. 人物-情节对照表
在扩展结果中生成：
```
| 人物 | 主要情节 | 章节范围 |
|------|---------|---------|
| 主角 | 修炼、突破、战斗 | 1-50章 |
| 导师 | 指导、传承 | 5-20章 |
| 对手 | 竞争、冲突 | 15-45章 |
```

### 3. 情节-人物需求表
在大纲扩展时生成：
```
| 章节 | 情节 | 需要人物 | 当前人物 | 缺口 |
|------|------|---------|---------|------|
| 第10章 | 进入组织 | 引路人 | 无 | 需补充 |
| 第15章 | 内部冲突 | 对立派系 | 有 | 满足 |
```

---

## 📝 总结

**核心问题：**
1. 人物识别不准确 → 导致扩展基数错误
2. 人物与大纲脱节 → 导致内容不协调

**解决方案：**
1. 智能识别器 → 提高识别准确率
2. 协同验证器 → 确保人物与情节相辅相成
3. 改进流程 → 验证-规划-执行-再验证

**预期收益：**
- 人物识别准确率：从60% → 95%
- 人物-情节匹配度：从50分 → 85分
- 用户满意度：显著提升
