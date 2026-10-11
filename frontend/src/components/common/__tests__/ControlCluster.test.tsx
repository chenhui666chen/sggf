/**
 * 控件簇的渲染契约：把语言切换与外观切换两个原语分组复用。
 *
 * 簇本身不含新逻辑，验的是"两个原语确实都在、都可点、都带着各自当前状态的
 * aria-label"——顶栏 full 变体与 slim 浮动变体都复用这一簇，缺任何一个都会让
 * 某一处重新退回"登录后切不了语言/外观"的老缺口。
 *
 * 图标期望值从真实图标组件反查 path 指纹，口径与 LanguageSwitcher/ThemeModeToggle
 * 两个测试一致，避免手抄映射表自己漂移。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BrightnessAutoIcon from '@mui/icons-material/BrightnessAuto'
import LanguageIcon from '@mui/icons-material/Language'

import ControlCluster from '../ControlCluster'
import { I18nProvider } from '@/i18n'
import { ThemeModeProvider } from '@/theme'

function iconSignature(markup: string): string {
  return [...markup.matchAll(/<path d="([^"]+)"/g)]
    .map((match) => match[1])
    .join('|')
}

const GLOBE_SIGNATURE = iconSignature(renderToStaticMarkup(<LanguageIcon />))
// Node 里没有 window，ThemeModeProvider 回到 system 档，对应的正是这只自动图标。
const AUTO_SIGNATURE = iconSignature(renderToStaticMarkup(<BrightnessAutoIcon />))

function renderCluster(): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <ControlCluster />
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

describe('ControlCluster', () => {
  it('renders both the language switcher and the theme toggle as buttons', () => {
    const markup = renderCluster()

    expect(markup.match(/<button/g)?.length).toBe(2)
    expect(markup).toContain('切换语言，当前简体中文')
    expect(markup).toContain('切换外观，当前跟随系统')
  })

  it('carries both toggle glyphs', () => {
    const signature = iconSignature(renderCluster())

    expect(signature).toContain(GLOBE_SIGNATURE)
    expect(signature).toContain(AUTO_SIGNATURE)
  })
})
