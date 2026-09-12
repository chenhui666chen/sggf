/**
 * ThemeModeProvider 的渲染契约测试。
 *
 * 项目用 renderToStaticMarkup 而非 jsdom，因此 useEffect 不会执行。这里能验证的
 * 是同样重要的另一半：Provider 在没有 window/document 时不崩、初始模式解析正确、
 * MUI theme 真的接上了 token、以及 hook 在 Provider 外会 fail fast。
 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Alert, Button } from '@mui/material'
import { useTheme } from '@mui/material/styles'

import { ThemeModeProvider, useThemeMode } from '../ThemeModeProvider'
import { lightTokens, DENSITY_ROW_HEIGHT } from '../tokens'

function ModeProbe() {
  const { mode, resolvedMode } = useThemeMode()

  return (
    <span data-mode={mode} data-resolved={resolvedMode}>
      probe
    </span>
  )
}

function ThemeProbe() {
  const theme = useTheme()

  return (
    <span
      data-background={theme.palette.background.default}
      data-sg-mode={theme.sg.mode}
      data-row-height={theme.sg.rowHeight}
    >
      theme
    </span>
  )
}

describe('ThemeModeProvider', () => {
  it('renders its children', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <span>child content</span>
      </ThemeModeProvider>,
    )

    expect(markup).toContain('child content')
  })

  it('starts in system mode and resolves to light when no browser preference is readable', () => {
    // Node 环境没有 window，readSystemPrefersDark 按浅色处理。
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <ModeProbe />
      </ThemeModeProvider>,
    )

    expect(markup).toContain('data-mode="system"')
    expect(markup).toContain('data-resolved="light"')
  })

  it('never leaks the unresolved system value into the theme', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <ThemeProbe />
      </ThemeModeProvider>,
    )

    expect(markup).toContain('data-sg-mode="light"')
    expect(markup).not.toContain('data-sg-mode="system"')
  })

  it('wires the palette from the design tokens rather than from MUI defaults', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <ThemeProbe />
      </ThemeModeProvider>,
    )

    // MUI 默认的 background.default 是 #fff，出现 token 值才说明工厂真的接上了。
    expect(markup).toContain(`data-background="${lightTokens.bgDefault}"`)
    expect(markup).not.toContain('data-background="#fff"')
  })

  it('defaults to comfortable density', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <ThemeProbe />
      </ThemeModeProvider>,
    )

    expect(markup).toContain(`data-row-height="${DENSITY_ROW_HEIGHT.comfortable}"`)
  })

  it('honors an explicit density for compact production workbenches', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider density="compact">
        <ThemeProbe />
      </ThemeModeProvider>,
    )

    expect(markup).toContain(`data-row-height="${DENSITY_ROW_HEIGHT.compact}"`)
  })

  it('localizes MUI’s own strings when told the interface language', () => {
    // MUI 组件自带一批写死的英文，它们不走 i18next，只能由主题注入。
    // Alert 的关闭按钮把 closeText 直接用作 aria-label，是最好观察的一个。
    const markup = renderToStaticMarkup(
      <ThemeModeProvider language="zh-CN">
        <Alert onClose={() => undefined}>content</Alert>
      </ThemeModeProvider>,
    )

    expect(markup).toContain('aria-label="关闭"')
  })

  it('stays on MUI’s English defaults when no language is given', () => {
    // language 是可选的：没有 I18nProvider 的调用方（包括本文件其余用例）
    // 得照常渲染，而不是抛错。
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <Alert onClose={() => undefined}>content</Alert>
      </ThemeModeProvider>,
    )

    expect(markup).toContain('aria-label="Close"')
  })

  it('provides a working MUI theme to nested material components', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <Button variant="contained">保存草稿</Button>
      </ThemeModeProvider>,
    )

    expect(markup).toContain('MuiButton-root')
    expect(markup).toContain('MuiButton-contained')
    expect(markup).toContain('保存草稿')
  })

  it('fails fast when useThemeMode is called outside the provider', () => {
    // 静默返回默认值会让"忘了包 Provider"变成难查的视觉 bug，不如直接抛错。
    expect(() => renderToStaticMarkup(<ModeProbe />)).toThrow('ThemeModeProvider')
  })

  it('supports nesting so a workbench can override density locally', () => {
    const markup = renderToStaticMarkup(
      <ThemeModeProvider>
        <ThemeModeProvider density="relaxed">
          <ThemeProbe />
        </ThemeModeProvider>
      </ThemeModeProvider>,
    )

    expect(markup).toContain(`data-row-height="${DENSITY_ROW_HEIGHT.relaxed}"`)
  })
})
