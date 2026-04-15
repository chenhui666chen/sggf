import { describe, expect, it } from 'vitest'

import { normalizeMarkdownContent } from '../normalizeMarkdownContent'

describe('normalizeMarkdownContent', () => {
  it('将分卷标题和卷内字段标准化为 Markdown 结构', () => {
    const input = `## 五、分卷规划（共3卷）
【第1卷】 枯荣逆旅
章节规模：60-80章
卷定位：序幕与立足篇，展示世界观与主角核心能力。
下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。
【第2卷】 黑松诡影
章节规模：60-80章`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('### 【第1卷】 枯荣逆旅')
    expect(result).toContain('- **章节规模：** 60-80章')
    expect(result).toContain('- **卷定位：** 序幕与立足篇，展示世界观与主角核心能力。')
    expect(result).toContain('### 【第2卷】 黑松诡影')
    expect(result).not.toContain('下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。\n【第2卷】 黑松诡影')
  })

  it('保持原有 Markdown 列表不被重复改写', () => {
    const input = `## 五、分卷规划（共2卷）
【第1卷】 烬墟微光
- 章节规模：1-75章
- 核心目标：在边荒集市存活`

    const result = normalizeMarkdownContent(input)

    expect(result).toContain('### 【第1卷】 烬墟微光')
    expect(result).toContain('- 章节规模：1-75章')
    expect(result).toContain('- 核心目标：在边荒集市存活')
  })

  it('普通 Markdown 内容保持稳定', () => {
    const input = `# 标题

## 小节
- 列表项`

    expect(normalizeMarkdownContent(input)).toBe(input)
  })
})
