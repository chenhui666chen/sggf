/**
 * 格式化工具测试
 */
import { describe, it, expect } from 'vitest'
import { 
  formatMarkdownToHtml, 
  formatSimpleText, 
  hasMarkdownFormat, 
  smartFormat 
} from '../formatContent'

describe('formatContent', () => {
  describe('hasMarkdownFormat', () => {
    it('应该检测到 Markdown 标题', () => {
      expect(hasMarkdownFormat('### 标题')).toBe(true)
      expect(hasMarkdownFormat('## 标题')).toBe(true)
      expect(hasMarkdownFormat('# 标题')).toBe(true)
    })

    it('应该检测到加粗文本', () => {
      expect(hasMarkdownFormat('这是**加粗**文本')).toBe(true)
    })

    it('应该检测到列表', () => {
      expect(hasMarkdownFormat('- 列表项')).toBe(true)
      expect(hasMarkdownFormat('1. 有序列表')).toBe(true)
    })

    it('应该检测到分隔线', () => {
      expect(hasMarkdownFormat('---')).toBe(true)
    })

    it('纯文本应该返回 false', () => {
      expect(hasMarkdownFormat('这是普通文本')).toBe(false)
    })
  })

  describe('formatMarkdownToHtml', () => {
    it('应该转换标题', () => {
      const result = formatMarkdownToHtml('### 三级标题')
      expect(result).toContain('<h3')
      expect(result).toContain('三级标题')
    })

    it('应该转换加粗文本', () => {
      const result = formatMarkdownToHtml('这是**加粗**文本')
      expect(result).toContain('<strong')
      expect(result).toContain('加粗')
    })

    it('应该转换无序列表', () => {
      const input = '- 项目1\n- 项目2'
      const result = formatMarkdownToHtml(input)
      expect(result).toContain('<ul')
      expect(result).toContain('<li')
      expect(result).toContain('项目1')
    })

    it('应该转换有序列表', () => {
      const input = '1. 第一项\n2. 第二项'
      const result = formatMarkdownToHtml(input)
      expect(result).toContain('<ol')
      expect(result).toContain('<li')
      expect(result).toContain('第一项')
    })

    it('应该转换分隔线', () => {
      const result = formatMarkdownToHtml('---')
      expect(result).toContain('<hr')
    })

    it('应该转换段落', () => {
      const input = '第一段\n\n第二段'
      const result = formatMarkdownToHtml(input)
      expect(result).toContain('<p style=')
      expect(result).toContain('第一段')
      expect(result).toContain('第二段')
    })

    it('应该将分卷标题识别为独立块级标题', () => {
      const input = `## 五、分卷规划（共3卷）
【第1卷】 枯荣逆旅
下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。
【第2卷】 黑松诡影
章节规模：60-80章`
      const result = formatMarkdownToHtml(input)

      expect(result).toContain('>【第1卷】 枯荣逆旅</h3>')
      expect(result).toContain('>【第2卷】 黑松诡影</h3>')
      expect(result).not.toContain('下卷交接：地脉波动引来赤发老鬼的贪念与天律盟的正式调查。<br />【第2卷】 黑松诡影')
    })
  })

  describe('formatSimpleText', () => {
    it('应该将换行符转换为 <br />', () => {
      const result = formatSimpleText('第一行\n第二行')
      expect(result).toContain('<br />')
    })

    it('应该处理多个连续换行', () => {
      const result = formatSimpleText('第一行\n\n\n第二行')
      expect(result).toContain('<br />')
    })
  })

  describe('smartFormat', () => {
    it('应该对 Markdown 内容使用 formatMarkdownToHtml', () => {
      const input = '### 标题\n\n这是**加粗**文本'
      const result = smartFormat(input)
      expect(result).toContain('<h3')
      expect(result).toContain('<strong')
    })

    it('应该对纯文本使用 formatSimpleText', () => {
      const input = '第一行\n第二行'
      const result = smartFormat(input)
      expect(result).toContain('<br />')
      expect(result).not.toContain('<h3')
    })

    it('应该处理空字符串', () => {
      const result = smartFormat('')
      expect(result).toBe('')
    })
  })

  describe('复杂场景测试', () => {
    it('应该正确处理质量评审报告格式', () => {
      const input = `### 📊 质量评审报告

#### 一、总体评分
- 故事性评分：**8.2/10分**

***综合评分分析***：本章在情节推进、人物塑造等方面表现优秀。

---

#### 二、分项评估

1. 逻辑一致性 ⭐⭐⭐⭐
- 场景设定符合世界观
- 人物对话符合性格`

      const result = formatMarkdownToHtml(input)
      
      // 检查标题
      expect(result).toContain('<h3')
      expect(result).toContain('质量评审报告')
      
      // 检查列表
      expect(result).toContain('<ul')
      expect(result).toContain('<li')
      
      // 检查加粗
      expect(result).toContain('<strong')
      expect(result).toContain('8.2/10分')
      
      // 检查分隔线
      expect(result).toContain('<hr')
      
      // 检查有序列表
      expect(result).toContain('<ol')
    })

    it('应该处理混合格式内容', () => {
      const input = `# 大标题

这是一个段落，包含**加粗**文本。

## 二级标题

- 列表项 1
- 列表项 2

---

### 三级标题

1. 有序列表 1
2. 有序列表 2`

      const result = formatMarkdownToHtml(input)
      
      expect(result).toContain('<h1')
      expect(result).toContain('<h2')
      expect(result).toContain('<h3')
      expect(result).toContain('<ul')
      expect(result).toContain('<ol')
      expect(result).toContain('<hr')
      expect(result).toContain('<strong')
    })
  })
})

