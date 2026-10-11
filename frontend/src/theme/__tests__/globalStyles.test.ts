/**
 * --sg-* CSS 变量的守护测试。
 *
 * MUI 的 theme 只作用于 MUI 组件；Vditor 与 ReactFlow 各自带一份硬编码浅色
 * 的样式表，滚动条与原生控件也不吃 theme。唯一能贯通它们的通道是 :root 上
 * 的 CSS 变量，所以这里的断言就是"第三方表面能不能跟随深浅色"的判据。
 */

import { describe, expect, it } from 'vitest'

import { createAppTheme } from '../createAppTheme'
import { buildCssVariables, CSS_VARIABLE_PREFIX, THIRD_PARTY_SURFACE_SELECTORS } from '../globalStyles'
import { fontFamilies } from '../typography'
import { shapeTokens, resolveTokens } from '../tokens'
import type { ResolvedThemeMode } from '../themeMode'

const MODES: readonly ResolvedThemeMode[] = ['light', 'dark']

describe('buildCssVariables', () => {
  it.each(MODES)('prefixes every variable with --sg- (%s)', (mode) => {
    const variables = buildCssVariables(createAppTheme(mode))

    expect(CSS_VARIABLE_PREFIX).toBe('--sg-')
    expect(Object.keys(variables).length).toBeGreaterThan(20)

    Object.keys(variables).forEach((key) => {
      expect(key.startsWith(CSS_VARIABLE_PREFIX), key).toBe(true)
    })
  })

  it.each(MODES)('emits the tokens third-party surfaces cannot read from the palette (%s)', (mode) => {
    const tokens = resolveTokens(mode)
    const variables = buildCssVariables(createAppTheme(mode))

    expect(variables['--sg-color-scheme']).toBe(mode)
    expect(variables['--sg-bg']).toBe(tokens.bgDefault)
    expect(variables['--sg-bg-paper']).toBe(tokens.bgPaper)
    expect(variables['--sg-bg-subtle']).toBe(tokens.bgSubtle)
    expect(variables['--sg-surface']).toBe(tokens.surface)
    expect(variables['--sg-surface-raised']).toBe(tokens.surfaceRaised)
    expect(variables['--sg-surface-sunken']).toBe(tokens.surfaceSunken)
    expect(variables['--sg-text']).toBe(tokens.textPrimary)
    expect(variables['--sg-text-secondary']).toBe(tokens.textSecondary)
    expect(variables['--sg-text-disabled']).toBe(tokens.textDisabled)
    expect(variables['--sg-text-inverse']).toBe(tokens.textInverse)
    expect(variables['--sg-border']).toBe(tokens.border)
    expect(variables['--sg-border-strong']).toBe(tokens.borderStrong)
    expect(variables['--sg-divider']).toBe(tokens.divider)
    expect(variables['--sg-accent']).toBe(tokens.primary)
    expect(variables['--sg-accent-hover']).toBe(tokens.primaryHover)
    expect(variables['--sg-accent-soft']).toBe(tokens.primarySoft)
    expect(variables['--sg-on-accent']).toBe(tokens.onPrimary)
    expect(variables['--sg-focus-ring']).toBe(tokens.focusRing)
  })

  it.each(MODES)('emits status colors so third-party badges can match the app (%s)', (mode) => {
    const tokens = resolveTokens(mode)
    const variables = buildCssVariables(createAppTheme(mode))

    expect(variables['--sg-success']).toBe(tokens.success)
    expect(variables['--sg-success-soft']).toBe(tokens.successSoft)
    expect(variables['--sg-warning']).toBe(tokens.warning)
    expect(variables['--sg-warning-soft']).toBe(tokens.warningSoft)
    expect(variables['--sg-error']).toBe(tokens.error)
    expect(variables['--sg-error-soft']).toBe(tokens.errorSoft)
    expect(variables['--sg-info']).toBe(tokens.info)
    expect(variables['--sg-info-soft']).toBe(tokens.infoSoft)
  })

  it.each(MODES)('serializes geometry and type into css-ready values (%s)', (mode) => {
    const variables = buildCssVariables(createAppTheme(mode))

    expect(variables['--sg-radius-sm']).toBe(`${shapeTokens.radiusSm}px`)
    expect(variables['--sg-radius']).toBe(`${shapeTokens.radiusMd}px`)
    expect(variables['--sg-radius-lg']).toBe(`${shapeTokens.radiusLg}px`)
    expect(variables['--sg-font-sans']).toBe(fontFamilies.sans)
    expect(variables['--sg-font-display']).toBe(fontFamilies.display)
    expect(variables['--sg-font-mono']).toBe(fontFamilies.mono)
    // 阴影里含逗号，作为 CSS 值原样可用；不能是 undefined 或对象。
    expect(typeof variables['--sg-shadow-2']).toBe('string')
    expect(variables['--sg-shadow-2']).toContain('rgba')
  })

  it('flips color-scheme with the mode so native widgets follow', () => {
    expect(buildCssVariables(createAppTheme('light'))['--sg-color-scheme']).toBe('light')
    expect(buildCssVariables(createAppTheme('dark'))['--sg-color-scheme']).toBe('dark')
  })

  it('produces different values per mode rather than a shared neutral set', () => {
    const light = buildCssVariables(createAppTheme('light'))
    const dark = buildCssVariables(createAppTheme('dark'))

    expect(light['--sg-bg']).not.toBe(dark['--sg-bg'])
    expect(light['--sg-text']).not.toBe(dark['--sg-text'])
    expect(light['--sg-accent']).not.toBe(dark['--sg-accent'])
    // 几何与字体是模式无关的。
    expect(light['--sg-radius']).toBe(dark['--sg-radius'])
    expect(light['--sg-font-sans']).toBe(dark['--sg-font-sans'])
  })
})

describe('THIRD_PARTY_SURFACE_SELECTORS', () => {
  it('names exactly the surfaces whose own stylesheet ships hardcoded light colors', () => {
    // vditor/dist/index.css 与 reactflow/dist/style.css 是代码库里仅有的两个
    // 自带样式表且不吃 MUI theme 的第三方表面。
    // react-markdown 不在其中：MarkdownRenderer 把每个元素都映射成了 MUI 组件，
    // 因此它已经跟随主题。项目里也没有 <audio> 标签，播放全部走 new Audio()。
    expect(THIRD_PARTY_SURFACE_SELECTORS).toEqual(['.vditor', '.react-flow'])
  })

  it('lists each selector exactly once', () => {
    const unique = new Set(THIRD_PARTY_SURFACE_SELECTORS)

    expect(unique.size).toBe(THIRD_PARTY_SURFACE_SELECTORS.length)
  })
})
