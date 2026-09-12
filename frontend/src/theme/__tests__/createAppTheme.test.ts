/**
 * createAppTheme 的契约测试。
 *
 * 这里锁的是"设计 token 是单一事实源"这条约束：MUI theme 的每一处颜色、
 * 圆角、投影、缓动都必须能追溯到 tokens.ts，不允许在主题工厂里凭空造色。
 */

import { describe, expect, it } from 'vitest'

import { contrastRatio, parseHexColor, relativeLuminance } from '../contrast'
import { createAppTheme } from '../createAppTheme'
import { motionTokens, shapeTokens, DENSITY_ROW_HEIGHT, darkShadows, darkTokens, lightShadows, lightTokens, resolveShadows, resolveTokens } from '../tokens'
import type { ResolvedThemeMode } from '../themeMode'

const MODES: readonly ResolvedThemeMode[] = ['light', 'dark']

/** MUI 的六个填充色，每个都必须与自身 contrastText 成对校验。 */
const FILLED_INTENTS = ['primary', 'secondary', 'success', 'warning', 'error', 'info'] as const

/**
 * MUI 的 createTheme 在开发环境下会清空 styleOverrides 顶层的状态类键
 * （createTheme.js 的 traverse 里执行 node[key] = {}），而生产环境不清空，
 * 造成"开发无样式、构建后又有样式"的隐蔽不一致。
 * 状态类必须写在 root 内部，用 '&.Mui-disabled' 这类选择器语法。
 * 该列表需与 node_modules/@mui/material/styles/createTheme.js 保持一致。
 */
const MUI_STATE_CLASS_KEYS = [
  'active',
  'checked',
  'completed',
  'disabled',
  'error',
  'expanded',
  'focused',
  'focusVisible',
  'required',
  'selected',
] as const

function luminanceOf(hex: string | undefined): number {
  const rgb = parseHexColor(hex ?? '')

  expect(rgb, `${hex} is not an opaque hex color`).not.toBeNull()

  return relativeLuminance(rgb!)
}

describe('createAppTheme palette', () => {
  it.each(MODES)('mirrors the %s tokens into the palette', (mode) => {
    const theme = createAppTheme(mode)
    const tokens = resolveTokens(mode)

    expect(theme.palette.mode).toBe(mode)
    expect(theme.palette.background.default).toBe(tokens.bgDefault)
    expect(theme.palette.background.paper).toBe(tokens.surface)
    expect(theme.palette.text.primary).toBe(tokens.textPrimary)
    expect(theme.palette.text.secondary).toBe(tokens.textSecondary)
    expect(theme.palette.text.disabled).toBe(tokens.textDisabled)
    expect(theme.palette.divider).toBe(tokens.divider)

    expect(theme.palette.primary.main).toBe(tokens.primary)
    expect(theme.palette.primary.contrastText).toBe(tokens.onPrimary)
    expect(theme.palette.secondary.main).toBe(tokens.secondary)
    expect(theme.palette.success.main).toBe(tokens.success)
    expect(theme.palette.warning.main).toBe(tokens.warning)
    expect(theme.palette.error.main).toBe(tokens.error)
    expect(theme.palette.info.main).toBe(tokens.info)
  })

  it.each(MODES)('maps MUI light/dark onto soft-tint and hover in %s mode', (mode) => {
    const theme = createAppTheme(mode)
    const tokens = resolveTokens(mode)

    // light 承担"柔色底"，dark 承担"悬停态"，而不是字面明暗。
    expect(theme.palette.primary.light).toBe(tokens.primarySoft)
    expect(theme.palette.primary.dark).toBe(tokens.primaryHover)
    expect(theme.palette.secondary.light).toBe(tokens.secondarySoft)
    expect(theme.palette.secondary.dark).toBe(tokens.secondaryHover)
    expect(theme.palette.error.light).toBe(tokens.errorSoft)
    expect(theme.palette.error.dark).toBe(tokens.errorHover)
  })

  it.each(MODES)('keeps every filled intent at WCAG AA against its own label color (%s)', (mode) => {
    const theme = createAppTheme(mode)

    FILLED_INTENTS.forEach((intent) => {
      const color = theme.palette[intent]
      const ratio = contrastRatio(color.contrastText, color.main)

      expect(ratio, `${intent} label on ${intent} fill in ${mode} mode`).toBeGreaterThanOrEqual(4.5)
    })
  })

  it.each(MODES)('keeps every intent legible on the paper surface in %s mode', (mode) => {
    const theme = createAppTheme(mode)
    const paper = theme.palette.background.paper

    FILLED_INTENTS.forEach((intent) => {
      expect(
        contrastRatio(theme.palette[intent].main, paper),
        `${intent}.main on background.paper in ${mode} mode`,
      ).toBeGreaterThanOrEqual(4.5)
    })
  })

  it.each(MODES)('reverses the grey ramp in %s mode so grey[900] stays readable as ink', (mode) => {
    const theme = createAppTheme(mode)
    const light50 = luminanceOf(theme.palette.grey[50])
    const light900 = luminanceOf(theme.palette.grey[900])

    if (mode === 'light') {
      expect(light50).toBeGreaterThan(light900)
    } else {
      expect(light50).toBeLessThan(light900)
    }
  })

  it.each(MODES)('keeps every grey step an opaque six-digit hex in %s mode', (mode) => {
    const theme = createAppTheme(mode)

    Object.entries(theme.palette.grey).forEach(([step, value]) => {
      expect(value, `grey[${step}]`).toMatch(/^#[0-9a-f]{6}$/)
    })
  })

  it.each(MODES)('derives translucent interaction colors instead of hardcoding rgba (%s)', (mode) => {
    const theme = createAppTheme(mode)

    expect(theme.palette.action.hover).toMatch(/^rgba\(\d+, \d+, \d+, 0\.\d+\)$/)
    expect(theme.palette.action.selected).toMatch(/^rgba\(\d+, \d+, \d+, 0\.\d+\)$/)
    expect(theme.palette.action.focus).toMatch(/^rgba\(\d+, \d+, \d+, 0\.\d+\)$/)
  })
})

describe('createAppTheme geometry and motion', () => {
  it.each(MODES)('wires shape, shadows and transitions from the tokens (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const shadows = resolveShadows(mode)

    expect(theme.shape.borderRadius).toBe(shapeTokens.radiusMd)

    // elevation 区间映射：Card(1) → shadow1，AppBar(4) → shadow2，
    // Menu(8) → shadow3，Drawer(16) 与 Dialog(24) → shadow4。
    expect(theme.shadows[0]).toBe('none')
    expect(theme.shadows[1]).toBe(shadows.shadow1)
    expect(theme.shadows[3]).toBe(shadows.shadow1)
    expect(theme.shadows[4]).toBe(shadows.shadow2)
    expect(theme.shadows[8]).toBe(shadows.shadow3)
    expect(theme.shadows[16]).toBe(shadows.shadow4)
    expect(theme.shadows[24]).toBe(shadows.shadow4)

    expect(theme.transitions.duration.shortest).toBe(motionTokens.durationInstant)
    expect(theme.transitions.duration.short).toBe(motionTokens.durationFast)
    expect(theme.transitions.duration.standard).toBe(motionTokens.durationBase)
    expect(theme.transitions.duration.complex).toBe(motionTokens.durationSlow)
    expect(theme.transitions.duration.enteringScreen).toBe(motionTokens.durationBase)
    expect(theme.transitions.duration.leavingScreen).toBe(motionTokens.durationFast)
    expect(theme.transitions.easing.easeInOut).toBe(motionTokens.easeStandard)
    expect(theme.transitions.easing.easeOut).toBe(motionTokens.easeDecelerate)
    expect(theme.transitions.easing.easeIn).toBe(motionTokens.easeAccelerate)
    expect(theme.transitions.easing.sharp).toBe(motionTokens.easeAccelerate)
  })

  it.each(MODES)('invents no transition value outside the motion tokens (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const allowedDurations = new Set<number>(
      Object.values(motionTokens).filter((value): value is number => typeof value === 'number'),
    )
    const allowedEasings = new Set<string>(
      Object.values(motionTokens).filter((value): value is string => typeof value === 'string'),
    )
    // MUI 的 duration/easing 接口没有索引签名，Object.entries 会丢掉值类型。
    const durations = theme.transitions.duration as unknown as Record<string, number>
    const easings = theme.transitions.easing as unknown as Record<string, string>

    Object.entries(durations).forEach(([slot, value]) => {
      expect(allowedDurations.has(value), `transitions.duration.${slot} = ${value}`).toBe(true)
    })

    Object.entries(easings).forEach(([slot, value]) => {
      expect(allowedEasings.has(value), `transitions.easing.${slot} = ${value}`).toBe(true)
    })
  })

  it.each(MODES)('invents no elevation shadow outside the shadow tokens (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const allowed = new Set<string>(['none', ...Object.values(resolveShadows(mode))])
    const elevationShadows = theme.shadows as unknown as readonly string[]

    expect(elevationShadows).toHaveLength(25)
    elevationShadows.forEach((value: string, elevation: number) => {
      expect(allowed.has(value), `shadows[${elevation}] = ${value}`).toBe(true)
    })
  })

  it('resolves the shadow set per mode', () => {
    expect(resolveShadows('light')).toBe(lightShadows)
    expect(resolveShadows('dark')).toBe(darkShadows)
    expect(resolveTokens('light')).toBe(lightTokens)
    expect(resolveTokens('dark')).toBe(darkTokens)
  })
})

describe('createAppTheme sg extension', () => {
  it.each(MODES)('exposes the raw tokens on theme.sg for surfaces that cannot read the palette (%s)', (mode) => {
    const theme = createAppTheme(mode)

    expect(theme.sg.mode).toBe(mode)
    expect(theme.sg.color).toBe(resolveTokens(mode))
    expect(theme.sg.shape).toBe(shapeTokens)
    expect(theme.sg.motion).toBe(motionTokens)
    expect(theme.sg.shadow).toBe(resolveShadows(mode))
  })

  it('defaults to comfortable density', () => {
    const theme = createAppTheme('light')

    expect(theme.sg.density).toBe('comfortable')
    expect(theme.sg.rowHeight).toBe(DENSITY_ROW_HEIGHT.comfortable)
  })

  it.each(['relaxed', 'comfortable', 'compact'] as const)('honors an explicit %s density', (density) => {
    const theme = createAppTheme('light', { density })

    expect(theme.sg.density).toBe(density)
    expect(theme.sg.rowHeight).toBe(DENSITY_ROW_HEIGHT[density])
  })
})

describe('createAppTheme component overrides', () => {
  it.each(MODES)('disables uppercase on buttons so Chinese labels survive (%s)', (mode) => {
    const theme = createAppTheme(mode)

    expect(theme.typography.button.textTransform).toBe('none')

    const root = theme.components?.MuiButton?.styleOverrides?.root as unknown as Record<string, unknown>

    expect(root.textTransform).toBe('none')
  })

  it('ships overrides for the surfaces the app actually renders', () => {
    const theme = createAppTheme('light')
    const components = theme.components as unknown as Record<string, unknown> | undefined
    const required = [
      'MuiCssBaseline',
      'MuiButton',
      'MuiIconButton',
      'MuiPaper',
      'MuiCard',
      'MuiAppBar',
      'MuiDrawer',
      'MuiDialog',
      'MuiDialogTitle',
      'MuiTextField',
      'MuiOutlinedInput',
      'MuiInputLabel',
      'MuiChip',
      'MuiTabs',
      'MuiTab',
      'MuiTableCell',
      'MuiTooltip',
      'MuiAlert',
      'MuiSnackbar',
      'MuiDivider',
      'MuiMenuItem',
      'MuiLink',
      'MuiBackdrop',
      'MuiSwitch',
      'MuiSelect',
      'MuiAvatar',
      'MuiSkeleton',
      'MuiAccordion',
      'MuiBreadcrumbs',
      'MuiLinearProgress',
    ]

    required.forEach((name) => {
      expect(components?.[name], `${name} override is missing`).toBeDefined()
    })
  })

  it.each(MODES)('paints CssBaseline from the tokens rather than from literals (%s)', (mode) => {
    const theme = createAppTheme(mode)
    // MUI 的 CssBaseline 把 styleOverrides 的顶层键直接当全局选择器用。
    const styleOverrides = theme.components?.MuiCssBaseline?.styleOverrides as unknown as
      | Record<string, Record<string, unknown>>
      | undefined
    const root = styleOverrides?.[':root']

    expect(root, ':root CSS variables are missing').toBeDefined()
    expect(root?.['--sg-color-scheme']).toBe(mode)
    expect(root?.['--sg-bg']).toBe(resolveTokens(mode).bgDefault)
  })

  it.each(MODES)('themes the scrollbar and focus ring globally, not just inside MUI (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const styleOverrides = theme.components?.MuiCssBaseline?.styleOverrides as unknown as
      | Record<string, Record<string, unknown>>
      | undefined

    expect(styleOverrides?.['::-webkit-scrollbar-thumb'], 'scrollbar thumb').toBeDefined()
    expect(styleOverrides?.[':focus-visible'], 'focus-visible outline').toBeDefined()
    // Firefox 走标准属性，不能只写 webkit 伪元素。
    expect(styleOverrides?.['*'], 'standard scrollbar-color').toBeDefined()
  })

  it('merges caller overrides on top of the built-in ones without dropping either', () => {
    const theme = createAppTheme('light', {
      components: { MuiButton: { defaultProps: { disableRipple: true } } },
    })

    expect(theme.components?.MuiButton?.defaultProps?.disableRipple).toBe(true)
    expect(theme.components?.MuiButton?.styleOverrides?.root).toBeDefined()
  })

  it.each(MODES)('never uses a bare state class as a top-level styleOverrides key (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const components = theme.components as unknown as Record<
      string,
      { styleOverrides?: Record<string, unknown> } | undefined
    >

    Object.entries(components).forEach(([component, definition]) => {
      Object.keys(definition?.styleOverrides ?? {}).forEach((key) => {
        expect(
          MUI_STATE_CLASS_KEYS.includes(key as (typeof MUI_STATE_CLASS_KEYS)[number]),
          `${component}.styleOverrides.${key} is dropped by MUI; move it under root as '&.Mui-${key}'`,
        ).toBe(false)
      })
    })
  })

  it.each(MODES)('leaves no empty styleOverrides entry (%s)', (mode) => {
    const theme = createAppTheme(mode)
    const components = theme.components as unknown as Record<
      string,
      { styleOverrides?: Record<string, unknown> } | undefined
    >

    // 空对象正是 MUI 丢弃状态类键后留下的痕迹；这条检查不依赖手抄的黑名单，
    // 即使 MUI 将来扩充状态类列表也依然有效。
    Object.entries(components).forEach(([component, definition]) => {
      Object.entries(definition?.styleOverrides ?? {}).forEach(([key, value]) => {
        if (typeof value === 'object' && value !== null) {
          expect(
            Object.keys(value).length,
            `${component}.styleOverrides.${key} is empty`,
          ).toBeGreaterThan(0)
        }
      })
    })
  })

  it('produces independent themes for the two modes', () => {
    const light = createAppTheme('light')
    const dark = createAppTheme('dark')

    expect(light.palette.background.default).not.toBe(dark.palette.background.default)
    expect(light.shadows[1]).not.toBe(dark.shadows[1])
    // 几何与动效是模式无关的，不该被复制出两份不同的值。
    expect(light.shape.borderRadius).toBe(dark.shape.borderRadius)
    expect(light.transitions.duration.standard).toBe(dark.transitions.duration.standard)
  })
})
