import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import IterationDegradedAlert from '../IterationDegradedAlert'

vi.mock('react-i18next', () => ({
  useTranslation: () => {
    const zhMap: Record<string, string> = {
      'workflow.finalDialog.degradedTitle': '本轮迭代未达评分线',
      'workflow.finalDialog.degradedDesc': '已交付当前最高评分版本，可继续编辑或再次迭代。',
      'workflow.finalDialog.degradedDescWithScore': '已交付当前最高评分版本（{{score}} 分），可继续编辑或再次迭代。',
    }
    return {
      t: (key: string, params?: Record<string, string>) =>
        (zhMap[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => params?.[name] || ''),
    }
  },
}))

function visibleText(markup: string): string {
  return markup
    .replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('IterationDegradedAlert', () => {
  it('warns user when iteration delivered a degraded version with score', () => {
    const text = visibleText(renderToStaticMarkup(<IterationDegradedAlert degraded score={8} />))

    expect(text).toContain('本轮迭代未达评分线')
    expect(text).toContain('8')
  })

  it('falls back to score-less wording when score is unknown', () => {
    const text = visibleText(renderToStaticMarkup(<IterationDegradedAlert degraded score={null} />))

    expect(text).toContain('本轮迭代未达评分线')
    expect(text).not.toContain('{{score}}')
  })

  it('renders nothing when iteration passed normally', () => {
    expect(renderToStaticMarkup(<IterationDegradedAlert degraded={false} score={9.5} />)).toBe('')
  })
})
