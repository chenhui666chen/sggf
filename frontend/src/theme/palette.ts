/**
 * 设计 token → MUI palette 的映射。
 *
 * 一条贯穿全项目的约定：**颜色只在 tokens.ts 里定义一次**，本文件只做搬运，
 * 不允许出现新的十六进制字面量（grey 斜坡除外，它由两端 token 插值而来，
 * 见下方注释）。
 */

import { withAlpha } from './contrast'
import type { PaletteOptions } from '@mui/material/styles'
import type { ResolvedThemeMode } from './themeMode'
import type { ColorTokens } from './tokens'

/**
 * MUI 的 `light` / `dark` 在本主题里分别承担"柔色底"与"悬停态"的角色，
 * 而不是字面意义的明暗。
 *
 * 这样所有现存 `color="primary.light"` 或 `bgcolor: 'primary.dark'` 的写法
 * 都会落到设计意图内的柔和色/悬停色上，而不是 MUI 自动 lighten/darken
 * 出来的脏色。
 */
function intent(
  main: string,
  hover: string,
  soft: string,
  contrastText: string,
): PaletteOptions['primary'] {
  return { main, light: soft, dark: hover, contrastText }
}

/**
 * 暖灰斜坡。
 *
 * 浅色下 50 → 900 由暖白走向墨；深色下方向反转，这是 MUI 的官方约定，
 * 目的是让 `grey[900]` 在两种模式下都表示"最强的墨色前景"。
 * 两端取自 tokens（bgPaper/surfaceRaised 与 textPrimary/surfaceSunken），
 * 中间档位按视觉节奏手工定档而非机械插值。
 */
function createGreyRamp(mode: ResolvedThemeMode, tokens: ColorTokens): PaletteOptions['grey'] {
  if (mode === 'dark') {
    return {
      50: tokens.surfaceSunken,
      100: tokens.bgSubtle,
      200: '#16191d',
      300: tokens.surfaceRaised,
      400: tokens.border,
      500: tokens.borderStrong,
      600: tokens.textDisabled,
      700: '#8d8981',
      800: tokens.textSecondary,
      900: tokens.textPrimary,
    }
  }

  return {
    50: tokens.surfaceRaised,
    100: tokens.bgSubtle,
    200: '#ede8de',
    300: tokens.divider,
    400: tokens.borderStrong,
    500: '#a89f8d',
    600: tokens.textDisabled,
    700: tokens.textSecondary,
    800: '#3d382e',
    900: tokens.textPrimary,
  }
}

/**
 * 半透明交互色。
 *
 * 深色模式下同样的 alpha 在暗底上几乎不可见，因此深色统一用更高的一档，
 * 这是双模式视觉一致性的必要补偿，不是随意取值。
 */
function createAction(tokens: ColorTokens, mode: ResolvedThemeMode): PaletteOptions['action'] {
  const isDark = mode === 'dark'
  const hoverAlpha = isDark ? 0.08 : 0.04
  const selectedAlpha = isDark ? 0.14 : 0.08
  const focusAlpha = isDark ? 0.12 : 0.06

  return {
    active: tokens.textSecondary,
    hover: withAlpha(tokens.textPrimary, hoverAlpha),
    hoverOpacity: hoverAlpha,
    selected: withAlpha(tokens.textPrimary, selectedAlpha),
    selectedOpacity: selectedAlpha,
    disabled: withAlpha(tokens.textPrimary, isDark ? 0.3 : 0.26),
    disabledOpacity: isDark ? 0.5 : 0.38,
    disabledBackground: withAlpha(tokens.textPrimary, isDark ? 0.16 : 0.12),
    activatedOpacity: selectedAlpha,
    focus: withAlpha(tokens.textPrimary, focusAlpha),
    focusOpacity: focusAlpha,
  }
}

export function createPalette(tokens: ColorTokens, mode: ResolvedThemeMode): PaletteOptions {
  return {
    mode,
    common: { black: '#000000', white: '#ffffff' },

    primary: intent(tokens.primary, tokens.primaryHover, tokens.primarySoft, tokens.onPrimary),
    secondary: intent(tokens.secondary, tokens.secondaryHover, tokens.secondarySoft, tokens.onSecondary),
    success: intent(tokens.success, tokens.successHover, tokens.successSoft, tokens.onSuccess),
    warning: intent(tokens.warning, tokens.warningHover, tokens.warningSoft, tokens.onWarning),
    error: intent(tokens.error, tokens.errorHover, tokens.errorSoft, tokens.onError),
    info: intent(tokens.info, tokens.infoHover, tokens.infoSoft, tokens.onInfo),

    grey: createGreyRamp(mode, tokens),

    text: {
      primary: tokens.textPrimary,
      secondary: tokens.textSecondary,
      disabled: tokens.textDisabled,
    },

    divider: tokens.divider,

    background: {
      default: tokens.bgDefault,
      paper: tokens.surface,
    },

    action: createAction(tokens, mode),
  }
}
