/**
 * 拾光字标的渲染契约。
 *
 * 项目没有 jsdom，验的是静态渲染能钉住的几件事：品牌名走 i18n 而不是写死、
 * 那点"光"用黄铜主色并且随明暗模式反相、SVG 是装饰性的（可访问名由可见文字
 * 承担）、以及 size 档确实改变字标尺寸。
 *
 * 颜色断言之所以成立，是因为 SVG 的 fill/stroke 走**直接属性**而不是 emotion 的
 * sx——renderToStaticMarkup 不会把 sx 生成的样式内联进标记，却会原样留下属性值。
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import BrandWordmark from '../BrandWordmark'
import { I18nProvider, bootstrapI18n } from '@/i18n'
import { THEME_MODE_STORAGE_KEY, ThemeModeProvider } from '@/theme'

interface StubOptions {
  readonly systemPrefersDark?: boolean
}

/** 让 ThemeModeProvider 读到指定的持久化模式；口径与 ThemeModeToggle.test.tsx 一致。 */
function withStoredMode<T>(mode: string, run: () => T, options: StubOptions = {}): T {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => (key === THEME_MODE_STORAGE_KEY ? mode : null),
      setItem: () => {},
    },
    matchMedia: (query: string) => ({
      media: query,
      matches: options.systemPrefersDark ?? false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }),
  })

  try {
    return run()
  } finally {
    vi.unstubAllGlobals()
  }
}

function renderWordmark(size?: 'sm' | 'md' | 'lg'): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <BrandWordmark size={size} />
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

function svgWidth(markup: string): number | undefined {
  const match = markup.match(/<svg[^>]*\swidth="(\d+)"/)

  return match ? Number(match[1]) : undefined
}

describe('BrandWordmark', () => {
  it('renders the brand name from i18n rather than a hard-coded string', () => {
    expect(renderWordmark()).toContain('拾光工坊')
  })

  it('follows the interface language', async () => {
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <ThemeModeProvider>
          <BrandWordmark />
        </ThemeModeProvider>
      </I18nProvider>,
    )

    expect(markup).toContain('Shiguang Studio')
    expect(markup).not.toContain('拾光工坊')
  })

  it('paints the gathered-light dot in brass that flips with the mode', () => {
    // 浅色黄铜 #8c6a1f，深色亮黄铜 #d9b45a：字标必须跟着模式反相，
    // 否则暗色下会是一块死沉的暗铜。
    const light = withStoredMode('light', () => renderWordmark())
    const dark = withStoredMode('dark', () => renderWordmark())

    expect(light.toLowerCase()).toContain('#8c6a1f')
    expect(dark.toLowerCase()).toContain('#d9b45a')
  })

  it('marks the glyph decorative so the visible text carries the accessible name', () => {
    const markup = renderWordmark()

    expect(markup).toContain('aria-hidden="true"')
    expect(markup).toContain('focusable="false"')
  })

  it('honors the size prop by scaling the glyph', () => {
    const small = svgWidth(renderWordmark('sm'))
    const medium = svgWidth(renderWordmark('md'))
    const large = svgWidth(renderWordmark('lg'))

    expect(small).toBeGreaterThan(0)
    expect(medium).toBeGreaterThan(small ?? 0)
    expect(large).toBeGreaterThan(medium ?? 0)
  })
})
