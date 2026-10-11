/**
 * MUI 内置文案的语言数据。
 *
 * MUI 组件自带一批写死的英文（Alert 的关闭按钮、Autocomplete 的空选项提示、
 * TablePagination 的每页行数），它们不走 i18next，只能作为 createTheme 的
 * deep-merge 参数注入。MUI 5.18 已经没有 LocalizationProvider，所以注入点
 * 是 createAppTheme 现成的 components 出口。
 *
 * 断言全部走渲染结果或 MUI 自己的键表，不手抄一份中文串：抄出来的那份一旦
 * 与 MUI 的数据漂移，测试照样绿，而界面已经错了。
 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Alert, ThemeProvider } from '@mui/material'

import { createAppTheme } from '../createAppTheme'
import { MUI_LOCALES } from '../muiLocale'
import type { AppLanguage } from '@/i18n'

/** Alert 的关闭按钮把 closeText 直接用作 aria-label，是这批内置文案里最好观察的一个。 */
function renderAlertCloseLabel(language: AppLanguage): string {
  const markup = renderToStaticMarkup(
    <ThemeProvider theme={createAppTheme('light', { components: MUI_LOCALES[language] })}>
      <Alert onClose={() => undefined}>content</Alert>
    </ThemeProvider>,
  )

  return markup.match(/aria-label="([^"]*)"/)?.[1] ?? ''
}

describe('MUI_LOCALES', () => {
  it('switches MUI’s own strings to Chinese for zh-CN', () => {
    expect(renderAlertCloseLabel('zh-CN')).toBe('关闭')
  })

  it('leaves en-US on MUI’s built-in English defaults', () => {
    // enUS 在 MUI 里是个空对象：英文本来就是它的内置默认，没有数据可注入。
    // 所以这里断言行为而不是数据——映射值是 undefined 也必须照样出英文，
    // 而不是抛错或退化成裸 key。
    expect(MUI_LOCALES['en-US']).toBeUndefined()
    expect(renderAlertCloseLabel('en-US')).toBe('Close')
  })

  it('lands every component MUI localizes, not just the one under test', () => {
    // 键表取自 MUI 自己的数据：手写一份清单，MUI 升级后多出来的组件就会静默漏掉。
    const localized = MUI_LOCALES['zh-CN']
    expect(localized).toBeDefined()

    const theme = createAppTheme('light', { components: localized })

    for (const name of Object.keys(localized ?? {})) {
      expect(theme.components, name).toHaveProperty(name)
    }
  })

  it('does not clobber the project’s own overrides', () => {
    // locale 与内置 overrides 按组件名两层浅合并。当前两边不重叠（locale 那几项
    // 全是 defaultProps，内置的是 styleOverrides），一旦哪天重了这条会先红——
    // 届时该改的是合并深度，而不是把 locale 丢掉。
    const plain = createAppTheme('light')
    const localized = createAppTheme('light', { components: MUI_LOCALES['zh-CN'] })

    expect(localized.components?.MuiAlert?.styleOverrides).toBeDefined()
    expect(localized.components?.MuiAlert?.styleOverrides).toEqual(
      plain.components?.MuiAlert?.styleOverrides,
    )
  })
})
