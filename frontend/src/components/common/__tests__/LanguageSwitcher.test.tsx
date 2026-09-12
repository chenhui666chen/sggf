/**
 * LanguageSwitcher 的渲染契约。
 *
 * 菜单在静态渲染下是关着的（Popover 走 portal，open=false 时不产出任何标记），
 * 所以菜单内容抽成纯函数 buildLanguageOptions 单独测，组件这边只验按钮本身。
 *
 * 母语原则（菜单里的语言名必须是该语言的自称）不在这里测——它属于语言注册表的
 * 数据契约，已由 i18n/__tests__/language.test.ts 钉住，重复一份只会两处漂移。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LanguageIcon from '@mui/icons-material/Language'

import LanguageSwitcher, { buildLanguageOptions } from '../LanguageSwitcher'
import { I18nProvider, SUPPORTED_LANGUAGES, bootstrapI18n } from '@/i18n'
import type { LanguageDescriptor } from '@/i18n'

/** 一个图标可能由多条 path 组成，全部拼起来才是它的指纹。 */
function iconSignature(markup: string): string {
  return [...markup.matchAll(/<path d="([^"]+)"/g)]
    .map((match) => match[1])
    .join('|')
}

function attribute(markup: string, name: string): string | undefined {
  return markup.match(new RegExp(`${name}="([^"]*)"`))?.[1]
}

const GLOBE_SIGNATURE = iconSignature(renderToStaticMarkup(<LanguageIcon />))

/** 只包 I18nProvider：上面所有用例都跑在这个层级下，顺带证明了它不依赖主题上下文。 */
function renderSwitcher(): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <LanguageSwitcher />
    </I18nProvider>,
  )
}

describe('buildLanguageOptions', () => {
  it('lists every supported language, in registry order', () => {
    // 顺序取自注册表而不是另排一份：注册表里 zh-CN 在前，菜单里就该 zh-CN 在前，
    // 否则加第三门语言时两边会各排各的。
    const options = buildLanguageOptions('zh-CN')

    expect(options.map((option) => option.code)).toEqual(
      SUPPORTED_LANGUAGES.map((entry) => entry.code),
    )
  })

  it('marks exactly the current language as selected', () => {
    for (const entry of SUPPORTED_LANGUAGES) {
      const options = buildLanguageOptions(entry.code)
      const selected = options.filter((option) => option.selected)

      expect(selected, entry.code).toHaveLength(1)
      expect(selected[0]?.code, entry.code).toBe(entry.code)
    }
  })

  it('carries both the endonym and the English name for each entry', () => {
    // englishLabel 是兜底：母语名并非人人都认得（没人认识「简体中文」时），
    // 两行并排才对所有人都可达。
    const options = buildLanguageOptions('zh-CN')

    expect(options.map((option) => option.nativeLabel)).toEqual(
      SUPPORTED_LANGUAGES.map((entry) => entry.nativeLabel),
    )
    expect(options.map((option) => option.englishLabel)).toEqual(
      SUPPORTED_LANGUAGES.map((entry) => entry.englishLabel),
    )
  })

  it('selects nothing rather than crashing when the current language is off-registry', () => {
    // languages 是可注入的，所以这条走得到：给一个不含当前语言的清单，
    // 结果应该是「没有一项被选中」，而不是抛错或随便选一个。
    const partial: readonly LanguageDescriptor[] = SUPPORTED_LANGUAGES.slice(0, 1)

    const options = buildLanguageOptions('en-US', partial)

    expect(options.map((option) => option.code)).toEqual(['zh-CN'])
    expect(options.some((option) => option.selected)).toBe(false)
  })
})

describe('LanguageSwitcher', () => {
  it('renders a real button so it stays reachable by keyboard', () => {
    const markup = renderSwitcher()

    expect(markup).toContain('<button')
    expect(markup).toContain('MuiIconButton-root')
  })

  it('uses the globe icon', () => {
    expect(iconSignature(renderSwitcher())).toBe(GLOBE_SIGNATURE)
  })

  it('names the current language in its own script in the aria-label', () => {
    expect(attribute(renderSwitcher(), 'aria-label')).toBe('切换语言，当前简体中文')
  })

  it('reports a closed menu before any interaction', () => {
    // 静态渲染下菜单必然是关的，但这两个属性还是要在标记里，
    // 否则读屏软件不会把这个按钮播报成「可展开的菜单」。
    const markup = renderSwitcher()

    expect(attribute(markup, 'aria-haspopup')).toBe('menu')
    expect(attribute(markup, 'aria-expanded')).toBe('false')
  })

  it('follows the interface language rather than hard-coding Chinese', async () => {
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <LanguageSwitcher />
      </I18nProvider>,
    )

    expect(attribute(markup, 'aria-label')).toBe('Change language, currently English')
  })
})
