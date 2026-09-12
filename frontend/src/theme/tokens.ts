/**
 * 「墨与光 / Ink & Light」设计 token。
 *
 * 浅色 = 暖纸（纸白底、墨黑字、黄铜主色）；深色 = 冷墨（墨底、暖白字、亮黄铜主色）。
 *
 * 约束（由 __tests__/tokens.test.ts 强制）：
 * 1. 所有颜色 token 必须是不透明六位十六进制，透明度在使用处用 withAlpha 派生，
 *    这样对比度才能被精确计算；
 * 2. 浅色与深色的键集合必须完全一致，避免暗色下出现未定义颜色；
 * 3. 正文文字对纸面达 WCAG AAA，次级文字与语义色达 AA，填充按钮的标签达 AA。
 */

import type { ResolvedThemeMode } from './themeMode'

export interface ColorTokens {
  /** 最外层画布：MUI background.default */
  bgDefault: string
  /** 页面主体层 */
  bgPaper: string
  /** 次级区块：表头、斑马纹、禁用底 */
  bgSubtle: string
  /** 卡片：MUI background.paper */
  surface: string
  /** 浮层：对话框、菜单、Tooltip */
  surfaceRaised: string
  /** 内凹：输入框、代码块、嵌入区 */
  surfaceSunken: string
  /** 遮罩基色，透明度用 withAlpha 派生 */
  scrim: string

  textPrimary: string
  textSecondary: string
  textDisabled: string
  /** 深色填充上的文字 */
  textInverse: string

  divider: string
  dividerStrong: string
  border: string
  borderStrong: string

  /** 主色：黄铜 */
  primary: string
  primaryHover: string
  primaryActive: string
  primarySoft: string
  primaryFaint: string
  onPrimary: string

  /** 次色：墨青 */
  secondary: string
  secondaryHover: string
  secondarySoft: string
  onSecondary: string

  success: string
  successHover: string
  successSoft: string
  onSuccess: string

  warning: string
  warningHover: string
  warningSoft: string
  onWarning: string

  error: string
  errorHover: string
  errorSoft: string
  onError: string

  info: string
  infoHover: string
  infoSoft: string
  onInfo: string

  /** 焦点环：与主色区分，保证在任何填充上都可见 */
  focusRing: string
}

/**
 * 浅色：纸。
 * 底色红通道高于蓝通道，形成暖纸感而不是冷白。
 */
export const lightTokens: ColorTokens = {
  bgDefault: '#f2eee6',
  bgPaper: '#faf8f4',
  bgSubtle: '#f6f3ed',
  surface: '#fefdfb',
  surfaceRaised: '#ffffff',
  surfaceSunken: '#efeae1',
  scrim: '#1a1815',

  textPrimary: '#1a1815',
  textSecondary: '#57534a',
  textDisabled: '#8c877c',
  textInverse: '#faf8f4',

  divider: '#e3ddd1',
  dividerStrong: '#d3cabb',
  border: '#dcd5c8',
  borderStrong: '#c4baa8',

  primary: '#8c6a1f',
  primaryHover: '#7a5c17',
  primaryActive: '#69500f',
  primarySoft: '#f1e8d3',
  primaryFaint: '#f8f3e7',
  onPrimary: '#fefdfb',

  secondary: '#1f5f5b',
  secondaryHover: '#194f4c',
  secondarySoft: '#dceae8',
  onSecondary: '#fefdfb',

  success: '#2f6f4e',
  successHover: '#276041',
  successSoft: '#e0ede5',
  onSuccess: '#fefdfb',

  warning: '#a8541a',
  warningHover: '#934814',
  warningSoft: '#faebe0',
  onWarning: '#fefdfb',

  error: '#a33a2e',
  errorHover: '#8f3127',
  errorSoft: '#f6e2df',
  onError: '#fefdfb',

  info: '#33566e',
  infoHover: '#2b4a5e',
  infoSoft: '#e1e8ee',
  onInfo: '#fefdfb',

  focusRing: '#33566e',
}

/**
 * 深色：墨。
 * 底色蓝通道不低于红通道，形成冷墨感；表面按海拔逐层提亮。
 */
export const darkTokens: ColorTokens = {
  bgDefault: '#0d0e10',
  bgPaper: '#131518',
  bgSubtle: '#101215',
  surface: '#191c20',
  surfaceRaised: '#22262b',
  surfaceSunken: '#0a0b0d',
  scrim: '#000000',

  textPrimary: '#edebe6',
  textSecondary: '#a8a49c',
  textDisabled: '#6e6b65',
  textInverse: '#131518',

  divider: '#262a30',
  dividerStrong: '#343a42',
  border: '#2c3138',
  borderStrong: '#3d444d',

  primary: '#d9b45a',
  primaryHover: '#e3c171',
  primaryActive: '#c9a44c',
  primarySoft: '#3a3220',
  primaryFaint: '#241f14',
  onPrimary: '#1a1610',

  secondary: '#5fb3a9',
  secondaryHover: '#72c2b8',
  secondarySoft: '#1b3330',
  onSecondary: '#0c1a18',

  success: '#66bb8a',
  successHover: '#7ac99b',
  successSoft: '#16281e',
  onSuccess: '#0a1710',

  warning: '#e3a14d',
  warningHover: '#edb264',
  warningSoft: '#2a1f10',
  onWarning: '#1a1206',

  error: '#e0796b',
  errorHover: '#e98d80',
  errorSoft: '#2a1512',
  onError: '#1f0e0b',

  info: '#82aec9',
  infoHover: '#96bed6',
  infoSoft: '#152430',
  onInfo: '#0b1620',

  focusRing: '#82aec9',
}

export function resolveTokens(mode: ResolvedThemeMode): ColorTokens {
  return mode === 'dark' ? darkTokens : lightTokens
}

export interface ShapeTokens {
  radiusXs: number
  radiusSm: number
  radiusMd: number
  radiusLg: number
  radiusXl: number
  radiusPill: number
}

/** 克制的三档主圆角 + 两端极值，避免 MUI 默认 4px 一刀切。 */
export const shapeTokens: ShapeTokens = {
  radiusXs: 3,
  radiusSm: 6,
  radiusMd: 10,
  radiusLg: 14,
  radiusXl: 20,
  radiusPill: 999,
}

export interface MotionTokens {
  durationInstant: number
  durationFast: number
  durationBase: number
  durationSlow: number
  durationDeliberate: number
  easeStandard: string
  easeEmphasized: string
  easeDecelerate: string
  easeAccelerate: string
}

export const motionTokens: MotionTokens = {
  durationInstant: 80,
  durationFast: 140,
  durationBase: 220,
  durationSlow: 340,
  durationDeliberate: 520,
  easeStandard: 'cubic-bezier(0.2, 0, 0, 1)',
  easeEmphasized: 'cubic-bezier(0.2, 0, 0, 1.1)',
  easeDecelerate: 'cubic-bezier(0, 0, 0, 1)',
  easeAccelerate: 'cubic-bezier(0.3, 0, 0.8, 0.15)',
}

export interface ShadowTokens {
  /** 发丝投影：卡片默认 */
  shadow1: string
  /** 悬浮：hover 后的卡片 */
  shadow2: string
  /** 浮层：菜单、下拉 */
  shadow3: string
  /** 模态：对话框 */
  shadow4: string
  /** 内凹：输入框聚焦外的凹陷感 */
  shadowInset: string
}

/**
 * 投影带暖调而不是纯黑，浅色下极轻、深色下靠"提亮表面"而非重投影表达海拔。
 */
export const lightShadows: ShadowTokens = {
  shadow1: '0 1px 2px rgba(26, 24, 21, 0.05), 0 1px 3px rgba(26, 24, 21, 0.04)',
  shadow2: '0 2px 6px rgba(26, 24, 21, 0.07), 0 6px 16px rgba(26, 24, 21, 0.05)',
  shadow3: '0 6px 16px rgba(26, 24, 21, 0.09), 0 16px 40px rgba(26, 24, 21, 0.08)',
  shadow4: '0 12px 32px rgba(26, 24, 21, 0.12), 0 32px 72px rgba(26, 24, 21, 0.14)',
  shadowInset: 'inset 0 1px 2px rgba(26, 24, 21, 0.06)',
}

export const darkShadows: ShadowTokens = {
  shadow1: '0 1px 2px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.3)',
  shadow2: '0 2px 6px rgba(0, 0, 0, 0.45), 0 6px 16px rgba(0, 0, 0, 0.35)',
  shadow3: '0 6px 16px rgba(0, 0, 0, 0.5), 0 16px 40px rgba(0, 0, 0, 0.45)',
  shadow4: '0 12px 32px rgba(0, 0, 0, 0.55), 0 32px 72px rgba(0, 0, 0, 0.6)',
  shadowInset: 'inset 0 1px 2px rgba(0, 0, 0, 0.5)',
}

export function resolveShadows(mode: ResolvedThemeMode): ShadowTokens {
  return mode === 'dark' ? darkShadows : lightShadows
}

/** 密度档位：生产工作台用 comfortable/compact，入口页用 relaxed。 */
export type DensityMode = 'relaxed' | 'comfortable' | 'compact'

export const DENSITY_ROW_HEIGHT: Record<DensityMode, number> = {
  relaxed: 64,
  comfortable: 48,
  compact: 36,
}
