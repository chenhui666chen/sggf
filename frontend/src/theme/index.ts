/**
 * 主题模块的统一出口。
 *
 * 业务代码只应从这里导入，不要直接深入 tokens / palette / componentOverrides，
 * 这样将来调整内部拆分时不必改动调用点。
 */

export {
  WCAG_THRESHOLDS,
  contrastRatio,
  meetsWcag,
  parseHexColor,
  relativeLuminance,
  withAlpha,
} from './contrast'
export type { Rgb, WcagLevel } from './contrast'

export { createAppTheme } from './createAppTheme'
export type { CreateAppThemeOptions } from './createAppTheme'

export {
  CSS_VARIABLE_PREFIX,
  THIRD_PARTY_SURFACE_SELECTORS,
  buildCssVariables,
  createGlobalStyles,
} from './globalStyles'

export { createPalette } from './palette'

export { ThemeModeProvider, useThemeMode } from './ThemeModeProvider'
export type { ThemeModeContextValue, ThemeModeProviderProps } from './ThemeModeProvider'

export {
  SYSTEM_COLOR_SCHEME_QUERY,
  THEME_MODES,
  THEME_MODE_DOM_ATTRIBUTE,
  THEME_MODE_STORAGE_KEY,
  isThemeMode,
  nextThemeMode,
  parseThemeMode,
  readStoredThemeMode,
  readSystemPrefersDark,
  resolveThemeMode,
} from './themeMode'
export type { ResolvedThemeMode, ThemeMode } from './themeMode'

export {
  BOOT_COLORS,
  THEME_COLOR_META_NAME,
  applyThemeColorMeta,
  applyThemeModeToElement,
  persistThemeMode,
  subscribeToSystemColorScheme,
} from './themeModeDom'
export type { AttributeTarget, MatchMediaFn, WritableStorage } from './themeModeDom'

export {
  DENSITY_ROW_HEIGHT,
  darkShadows,
  darkTokens,
  lightShadows,
  lightTokens,
  motionTokens,
  resolveShadows,
  resolveTokens,
  shapeTokens,
} from './tokens'
export type {
  ColorTokens,
  DensityMode,
  MotionTokens,
  ShadowTokens,
  ShapeTokens,
} from './tokens'

export { createTypography, fontFamilies, typeScaleTokens } from './typography'
export type { FontFamilies, TypeScaleTokens } from './typography'

export type { SgTheme } from './types'
