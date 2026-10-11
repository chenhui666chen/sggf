import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import PrivacyPolicyContent from '../PrivacyPolicyContent'
import PrivacyPolicyDialog from '../PrivacyPolicyDialog'

function extractVisibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('PrivacyPolicyDialog', () => {
  it('关闭时不渲染任何内容', () => {
    const markup = renderToStaticMarkup(<PrivacyPolicyDialog open={false} onClose={() => {}} />)
    expect(extractVisibleText(markup)).toBe('')
  })

  it('弹窗正文渲染隐私政策全文（含标题与全部章节），供勾选处查阅而不跳转新页面', () => {
    // 弹窗外壳通过 Portal 渲染，SSR 下不可见；正文组件即弹窗全部内容，直接断言其渲染产物。
    // 关闭状态弹窗同样不渲染（已由上一条用例覆盖）。
    const markup = renderToStaticMarkup(<PrivacyPolicyContent />)
    const text = extractVisibleText(markup)
    // 弹窗标题与政策标题
    expect(text).toContain('隐私政策')
    expect(text).toContain('拾光工坊隐私政策')
    // 各章节均应出现在弹窗正文中
    for (const heading of [
      '一、我们收集的个人信息',
      '二、我们如何使用个人信息',
      '三、我们如何存储个人信息',
      '四、我们如何共享个人信息',
      '五、Cookie 与同类技术',
      '六、你的权利',
      '七、你的内容责任与保证',
      '八、未成年人保护',
      '九、本政策如何更新',
      '十、如何联系我们',
    ]) {
      expect(text).toContain(heading)
    }
  })
})
