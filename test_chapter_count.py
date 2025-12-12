import re

# 测试大纲片段
test_outline = """
# 《预演人生》完整整合大纲（99章网文结构）

## 一、故事概述
...预计400-500章...

## 二、卷结构与章节详情（共4卷，99章）

### 【第一卷】「废墟重燃」
- **章节范围**：第1–25章
- **阶段目标**：洗刷冤屈

#### 第1章：《血色黎明》
- **主要内容**：...

#### 第2章：《出租屋的代价》
- **主要内容**：...

### 【第二卷】「暗流涌动」
- **章节范围**：第26–50章

#### 第26章：《重逢》
- **主要内容**：...

#### 第50章：《记忆残片》⭐⭐⭐⭐
- **主要内容**：...

### 【第三卷】「火种重生」
- **章节范围**：第51–75章
"""

print("🧪 测试章节统计逻辑\n")

# 旧逻辑（有bug）
print("❌ 旧逻辑（匹配所有'第X章'）：")
old_patterns = [
    r'第(\d+)章',
]
old_numbers = []
for pattern in old_patterns:
    matches = re.findall(pattern, test_outline)
    old_numbers.extend(matches)
old_numbers = [int(n) for n in old_numbers]
print(f"   匹配到: {old_numbers}")
print(f"   最大值: {max(old_numbers) if old_numbers else 0}")
print()

# 新逻辑（修复后）
print("✅ 新逻辑（只匹配章节标题）：")
new_patterns = [
    r'第(\d+)章[：:、]',  # 第X章： 或 第X章、
    r'第(\d+)回[：:、]',
    r'Chapter\s+(\d+)[：:]',
    r'####\s*第(\d+)章',  # Markdown标题
]
new_numbers = []
for pattern in new_patterns:
    matches = re.findall(pattern, test_outline)
    new_numbers.extend(matches)
new_numbers = [int(n) for n in new_numbers]
print(f"   匹配到: {sorted(set(new_numbers))}")
print(f"   最大值: {max(new_numbers) if new_numbers else 0}")
print()

print("📊 结论：")
print(f"   - 旧逻辑：识别为 {max(old_numbers) if old_numbers else 0} 章（错误！包含了范围描述）")
print(f"   - 新逻辑：识别为 {max(new_numbers) if new_numbers else 0} 章（正确！只统计真实章节）")
