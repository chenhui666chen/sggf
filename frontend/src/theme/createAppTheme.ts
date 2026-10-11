/**
 * 主题工厂 —— 全站唯一的 createTheme 调用点。
 *
 * 任何页面或组件都不应该再自己 createTheme，否则设计 token 就会出现第二条
 * 事实源，深色模式必然出现漏网的白块。
 */

import { createTheme } from '@mui/material/styles'
import { createComponentOverrides } from './componentOverrides'
import { createPalette } from './palette'
import { createTypography } from './typography'
import {
  DENSITY_ROW_HEIGHT,
  motionTokens,
  resolveShadows,
  resolveTokens,
  shapeTokens,
} from './tokens'
import type { Theme, ThemeOptions } from '@mui/material/styles'
import type { ResolvedThemeMode } from './themeMode'
import type { DensityMode, ShadowTokens } from './tokens'
import type { SgTheme } from './types'

export interface CreateAppThemeOptions {
  /** 密度档位：生产工作台用 comfortable/compact，入口页用 relaxed。 */
  density?: DensityMode
  /**
   * 追加或覆盖组件级样式。
   *
   * 与内置 overrides 按"组件名"两层合并，因此调用方只写自己想改的那部分即可，
   * 不会把内置的一整套冲掉。
   */
  components?: ThemeOptions['components']
}

const DEFAULT_DENSITY: DensityMode = 'comfortable'

/**
 * elevation 0-24 与四档投影 token 的映射区间。
 *
 * 区间边界取自 MUI 各组件的默认 elevation：Card = 1，AppBar = 4，
 * Menu/Popover = 8，Drawer = 16，Dialog = 24。这样每个组件拿到的投影
 * 都符合它在视觉层级里的实际角色。
 */
const SHADOW_BANDS: readonly { from: number; to: number; key: keyof ShadowTokens }[] = [
  { from: 1, to: 3, key: 'shadow1' },
  { from: 4, to: 7, key: 'shadow2' },
  { from: 8, to: 15, key: 'shadow3' },
  { from: 16, to: 24, key: 'shadow4' },
]

function createShadows(tokens: ShadowTokens): NonNullable<ThemeOptions['shadows']> {
  const shadows: string[] = new Array(25).fill('none')

  SHADOW_BANDS.forEach(({ from, to, key }) => {
    for (let elevation = from; elevation <= to; elevation += 1) {
      shadows[elevation] = tokens[key]
    }
  })

  return shadows as NonNullable<ThemeOptions['shadows']>
}

/**
 * MUI 有 7 个 duration 槽位而 token 只有 5 档，因此 shorter 与 short 共用
 * durationFast。刻意复用而不是发明第六个时长值，这样 transitions 里出现的
 * 每个数字都能追溯到 motionTokens（由测试强制）。
 */
function createTransitions(): NonNullable<ThemeOptions['transitions']> {
  return {
    duration: {
      shortest: motionTokens.durationInstant,
      shorter: motionTokens.durationFast,
      short: motionTokens.durationFast,
      standard: motionTokens.durationBase,
      complex: motionTokens.durationSlow,
      enteringScreen: motionTokens.durationBase,
      leavingScreen: motionTokens.durationFast,
    },
    easing: {
      easeInOut: motionTokens.easeStandard,
      easeOut: motionTokens.easeDecelerate,
      easeIn: motionTokens.easeAccelerate,
      sharp: motionTokens.easeAccelerate,
    },
  }
}

/**
 * 按组件名做两层浅合并。
 *
 * 只合到 `{ MuiX: { defaultProps, styleOverrides } }` 这一层就够用了：
 * 再深一层（合并 styleOverrides 内部的 class key）会让调用方无法覆盖内置规则，
 * 反而失去 escape hatch 的作用。
 */
function mergeComponents(
  base: NonNullable<ThemeOptions['components']>,
  extra: ThemeOptions['components'],
): NonNullable<ThemeOptions['components']> {
  if (!extra) {
    return base
  }

  const merged = { ...base } as Record<string, Record<string, unknown>>

  Object.entries(extra).forEach(([name, definition]) => {
    merged[name] = { ...merged[name], ...(definition as Record<string, unknown>) }
  })

  return merged as NonNullable<ThemeOptions['components']>
}

export function createAppTheme(
  mode: ResolvedThemeMode,
  options: CreateAppThemeOptions = {},
): Theme {
  const density = options.density ?? DEFAULT_DENSITY

  const sg: SgTheme = {
    mode,
    color: resolveTokens(mode),
    shape: shapeTokens,
    motion: motionTokens,
    shadow: resolveShadows(mode),
    density,
    rowHeight: DENSITY_ROW_HEIGHT[density],
  }

  // sg 刻意不放进 createTheme 的 options：MUI 会对未知顶层键做 deepmerge，
  // 那会把 token 复制成一份与 lightTokens/darkTokens 脱钩的副本，既丢掉
  // Object.is 恒等，也让 SgTheme 上的 readonly 保护形同虚设。改为构造完
  // theme 后直接把原始引用挂上去。
  const shared: ThemeOptions = {
    palette: createPalette(sg.color, mode),
    typography: createTypography(),
    shape: { borderRadius: sg.shape.radiusMd },
    shadows: createShadows(sg.shadow),
    transitions: createTransitions(),
  }

  // 组件 overrides 需要读一个完整 theme（palette、shape、typography、sg），
  // 而 theme 又是由带 components 的 createTheme 产生的，属于先有鸡还是先有蛋。
  // 解法是先造一个不含 components 的基底供 overrides 读取，再造最终 theme。
  // 主题只在切换模式时构造，两次 createTheme 的开销可以忽略。
  const baseTheme = createTheme(shared)

  baseTheme.sg = sg

  const theme = createTheme({
    ...shared,
    components: mergeComponents(createComponentOverrides(baseTheme), options.components),
  })

  theme.sg = sg

  return theme
}
