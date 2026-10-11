/**
 * 挂在 MUI theme 上的「拾光工坊」扩展槽。
 *
 * 存在的理由：MUI 的 palette 只暴露 main/light/dark/contrastText 四档，
 * 装不下 44 个语义 token（soft、faint、hover、active、borderStrong…）。
 * 与其在业务代码里到处 import tokens 造成第二条事实源，不如把原始 token
 * 挂到 theme.sg 上，让任何拿到 theme 的地方都能读到完整的一套。
 */

import type { ResolvedThemeMode } from './themeMode'
import type {
  ColorTokens,
  DensityMode,
  MotionTokens,
  ShadowTokens,
  ShapeTokens,
} from './tokens'

export interface SgTheme {
  /** 已解析的模式；'system' 在到达这里之前就被解析掉了。 */
  readonly mode: ResolvedThemeMode
  readonly color: Readonly<ColorTokens>
  readonly shape: Readonly<ShapeTokens>
  readonly motion: Readonly<MotionTokens>
  readonly shadow: Readonly<ShadowTokens>
  readonly density: DensityMode
  /** 由 density 派生的表格行高，避免各处重复查 DENSITY_ROW_HEIGHT。 */
  readonly rowHeight: number
}

declare module '@mui/material/styles' {
  interface Theme {
    sg: SgTheme
  }

  interface ThemeOptions {
    sg?: Partial<SgTheme>
  }
}
