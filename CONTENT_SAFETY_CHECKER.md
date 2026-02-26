# 内容安全检查与自动修复功能

## 功能概述

为了解决 DashScope API 的内容安全检查（DataInspectionFailed）问题，系统现在会自动检测并修复可能触发内容安全检查的提示词。

## 工作原理

### 1. 内容安全检查

在调用 DashScope API 之前，系统会先检查提示词中是否包含敏感词汇：

- **暴力相关**: 杀、死、血、伤、武器、枪、刀、剑等
- **色情相关**: 裸、胸、臀、性感、诱惑等
- **政治相关**: 领导人、政党、选举、政治等
- **违法相关**: 毒品、赌博、犯罪、违法等

### 2. 自动修复

如果检测到敏感词汇，系统会自动使用更安全的词汇进行替换：

**示例：**

| 原始词汇 | 替换词汇 | 类别 |
|---------|---------|------|
| 杀 | 击败、制服、战胜 | 暴力 |
| 死 | 倒下、失去意识、战败 | 暴力 |
| 血 | 红光、光芒、能量 | 暴力 |
| 武器 | 装备、器具、工具 | 暴力 |
| 枪 | 法器、宝物、道具 | 暴力 |
| 裸 | 身着、穿着、披着 | 色情 |
| 性感 | 美丽、动人、迷人 | 色情 |
| 领导人 | 长者、智者、领袖 | 政治 |
| 政党 | 团体、组织、阵营 | 政治 |
| 毒品 | 药物、药剂、丹药 | 违法 |

### 3. 修复策略

系统提供三种修复策略：

- **conservative（保守）**: 只替换高风险词汇
- **moderate（中等）**: 替换高、中风险词汇（默认）
- **aggressive（激进）**: 替换所有敏感词汇

## 使用方法

### 自动模式（推荐）

系统默认启用自动检查和修复，无需任何配置：

```python
# 自动检查和修复
result = adapter.generate(
    prompt="一个手持武器的战士",  # 会被自动修复
    width=1024,
    height=768
)
```

### 手动模式

如果需要手动控制，可以使用 `ContentSafetyChecker`：

```python
from adapters.content_safety_checker import ContentSafetyChecker, check_and_fix_prompt

# 检查提示词
checker = ContentSafetyChecker()
issues = checker.check("一个手持武器的战士")

# 获取修复建议
suggestions = checker.get_fix_suggestions("一个手持武器的战士")

# 自动修复
fixed_prompt = checker.auto_fix("一个手持武器的战士", strategy="moderate")

# 便捷函数
fixed_prompt, issues, description = check_and_fix_prompt(
    "一个手持武器的战士",
    strategy="moderate"
)
```

## 日志输出

当启用内容安全检查时，控制台会输出详细的日志：

```
🔍 [内容安全检查] 检查提示词...
⚠️ [内容安全检查] 检测到 2 个敏感词，已自动修复：violence(2)
📝 [内容安全检查] 原始提示词: 一个手持武器的战士
✨ [内容安全检查] 修复后提示词: 一个手持装备的勇士
```

## 修改的文件

- `adapters/content_safety_checker.py` - 内容安全检查器实现
- `adapters/model_adapters.py` - 集成内容安全检查到 T2I/I2V/T2V

## 配置选项

### 修改修复策略

在 `adapters/model_adapters.py` 中修改策略：

```python
# 保守策略（只修复高风险）
fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy="conservative")

# 中等策略（修复高、中风险）- 默认
fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy="moderate")

# 激进策略（修复所有敏感词）
fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy="aggressive")
```

### 自定义敏感词库

在 `adapters/content_safety_checker.py` 中修改：

```python
SENSITIVE_KEYWORDS = {
    "violence": {
        "high": ["杀", "死", "血", ...],
        "medium": ["击倒", "击败", ...],
        "low": ["对抗", "较量", ...]
    },
    # 添加更多类别...
}
```

### 自定义替换建议

在 `adapters/content_safety_checker.py` 中修改：

```python
REPLACEMENT_SUGGESTIONS = {
    "violence": {
        "杀": ["击败", "制服", "战胜"],
        # 添加更多替换...
    },
    # 添加更多类别...
}
```

## 最佳实践

1. **使用自动模式**: 让系统自动处理内容安全检查
2. **查看日志**: 关注控制台输出，了解修复情况
3. **调整策略**: 根据实际需求选择合适的修复策略
4. **自定义词库**: 根据项目特点添加特定的敏感词
5. **测试验证**: 修复后手动验证提示词是否符合预期

## 注意事项

1. **自动修复可能改变原意**: 系统会尽量保持原意，但可能略有差异
2. **不是 100% 准确**: 内容安全检查是启发式的，可能误判或漏判
3. **需要人工审核**: 修复后的提示词建议人工审核
4. **遵守平台规则**: 最终仍需遵守阿里云的内容安全政策

## 故障排除

### 问题：修复后的提示词不符合预期

**解决方案**：
1. 使用 `conservative` 策略，减少修复范围
2. 自定义替换建议，提供更合适的词汇
3. 手动修改提示词，避免敏感词汇

### 问题：仍然触发内容安全检查

**解决方案**：
1. 使用 `aggressive` 策略，扩大修复范围
2. 添加更多敏感词到词库
3. 简化提示词，减少复杂描述
4. 使用更抽象、更通用的描述

### 问题：误报（安全提示词被修复）

**解决方案**：
1. 从敏感词库中移除相关词汇
2. 使用 `conservative` 策略
3. 手动绕过自动修复（修改代码）

## 相关文档

- [DashScope 错误码文档](https://help.aliyun.com/zh/model-studio/error-code#inappropriate-content)
- [DASHSCOPE_RATE_LIMIT_IMPROVEMENTS.md](./DASHSCOPE_RATE_LIMIT_IMPROVEMENTS.md)
- [ALIYUN_RATE_LIMIT_SOLUTION.md](./ALIYUN_RATE_LIMIT_SOLUTION.md)
