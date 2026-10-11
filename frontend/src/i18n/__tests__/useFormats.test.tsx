/**
 * useFormats 的契约。
 *
 * format.ts 刻意保持 React 无关（每个函数都接 locale 参数），这一层只做一件事：
 * 把当前语言柯里化进去。所以要测的是"绑定是否完整、是否真的跟着语言走"，
 * 而不是格式化本身——那是 format.test.ts 那 31 个测试的职责。
 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import * as formatModule from '../format'
import { I18nProvider } from '../I18nProvider'
import { createI18n } from '../client'
import { useFormats } from '../useFormats'
import type { i18n as I18nInstance } from 'i18next'

// 与 format.test.ts 用同一个样本，两边的期望值可以直接对照。
const SAMPLE = '2026-03-15T08:30:45Z'
const UTC = { timeZone: 'UTC' } as const

/**
 * format.ts 里不接 locale 的底层辅助：toDate 只做类型归一，getDateParts 返回的是
 * 日期分量而非文案。业务真要用时直接从 format.ts 导入，不必经过这一层。
 */
const NOT_LOCALIZED = ['toDate', 'getDateParts']

const localizedFormatters = Object.keys(formatModule)
  .filter((name) => typeof (formatModule as Record<string, unknown>)[name] === 'function')
  .filter((name) => !NOT_LOCALIZED.includes(name))
  .sort()

function FormatsProbe() {
  const formats = useFormats()

  return (
    <span
      data-keys={Object.keys(formats).sort().join(',')}
      data-date={formats.formatDate(SAMPLE, UTC)}
      data-compact={formats.formatCompactNumber(12345)}
      data-list={formats.formatList(['A', 'B', 'C'])}
    />
  )
}

/** 验证调用方仍能用 options 覆盖已经绑定好的语言。 */
function OverrideProbe() {
  const formats = useFormats()

  return <span data-date={formats.formatDate(SAMPLE, { ...UTC, locale: 'en-US' })} />
}

function renderFormats(instance?: I18nInstance) {
  return renderToStaticMarkup(
    <I18nProvider instance={instance}>
      <FormatsProbe />
    </I18nProvider>,
  )
}

function attr(markup: string, name: string) {
  return markup.match(new RegExp(`data-${name}="([^"]*)"`))?.[1] ?? ''
}

describe('useFormats', () => {
  it('exposes exactly the locale-aware formatters of format.ts', () => {
    // 反射对比而非手抄清单：format.ts 新增一个格式化函数却忘了在这里绑定，
    // 那个调用点就会继续用写死的 locale，而且不会有任何报错。
    expect(localizedFormatters.length).toBeGreaterThan(10)
    expect(attr(renderFormats(), 'keys').split(',')).toEqual(localizedFormatters)
  })

  it('formats in the provider language without being told which one', () => {
    const markup = renderFormats()

    expect(attr(markup, 'date')).toBe('2026年3月15日')
    expect(attr(markup, 'compact')).toContain('万')
    expect(attr(markup, 'list')).toContain('、')
  })

  it('follows the instance when the app runs in English', () => {
    const markup = renderFormats(createI18n({ language: 'en-US' }))

    expect(attr(markup, 'date')).toBe('Mar 15, 2026')
    expect(attr(markup, 'compact')).toMatch(/K$/)
    expect(attr(markup, 'list')).toBe('A, B, and C')
  })

  it('still lets a single call override the language', () => {
    // 混排场景（中文界面里引用一段英文原文的日期）需要这个逃生口。
    const markup = renderToStaticMarkup(
      <I18nProvider>
        <OverrideProbe />
      </I18nProvider>,
    )

    expect(attr(markup, 'date')).toBe('Mar 15, 2026')
  })

  it('fails fast outside the provider', () => {
    expect(() => renderToStaticMarkup(<FormatsProbe />)).toThrow('I18nProvider')
  })
})
