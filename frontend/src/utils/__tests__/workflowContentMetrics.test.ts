import { describe, expect, it } from 'vitest'

import {
  estimateChapterCount,
  estimateCharacterCount,
  extractCharacterNames,
} from '../workflowContentMetrics'

describe('workflowContentMetrics', () => {
  it('支持多种人物卡格式并自动去重', () => {
    const characters = `
## 主角阵营
### 【姓名】：林烬
【角色定位】：主角

### 苏璃
年龄/性别：20/女
角色定位：核心配角

- 韩七；定位=重要配角；动机=活下去
- 墨苍：导师

### 人物关系
- 林烬 ↔ 苏璃：盟友
`

    expect(extractCharacterNames(characters)).toEqual(['林烬', '苏璃', '韩七', '墨苍'])
    expect(estimateCharacterCount(characters)).toBe(4)
  })

  it('按章节标题统计时会忽略正文中的章节引用', () => {
    const outline = `
故事概览
### 第1章 初入长安
这一章会呼应第3章埋下的伏笔。

2. 第 2 章：雨夜追凶
Chapter 3 Turning Point
第4回 江湖相逢
`

    expect(estimateChapterCount(outline)).toBe(4)
  })

  it('章节列表写在同一行时会回退到内联统计', () => {
    const outline = '第1章 初始；第2章 转折；第3章 收束'

    expect(estimateChapterCount(outline)).toBe(3)
  })

  it('兼容灵感方舟的人物标题与阶段式大纲格式', () => {
    const characters = `
# 《情绪猎人》人物设定详案

## 一、主角阵营：挣扎的变量与同路人

### **陈骁（主角）**
- **基本信息**：26岁，前大学生。

### **“回声” / 沈墨（关键配角·情报贩子）**
- **基本信息**：28岁，前数据分析师。

### **“莫比乌斯” / 未知（黑市商人）**
- **基本信息**：年龄、性别、外貌皆不详。
`
    const outline = `
# 《情绪猎人》情节大纲

## 一、主线情节

**第一阶段：觉醒与追猎（第1-30章）**
- **关键节点**：
  - 第3章：第一次生死战

## 二、第一章大纲

**章节标题建议**：《第一滴恐惧》
`

    expect(extractCharacterNames(characters)).toEqual(['陈骁', '沈墨', '莫比乌斯'])
    expect(estimateCharacterCount(characters)).toBe(3)
    expect(estimateChapterCount(outline)).toBe(1)
  })
})
