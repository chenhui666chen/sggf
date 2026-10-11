/**
 * :root CSS 变量与全局基础样式。
 *
 * MUI 的 theme 只能影响 MUI 组件。代码库里有两个自带样式表、且样式表里写死
 * 浅色的第三方表面（vditor/dist/index.css、reactflow/dist/style.css），还有
 * 滚动条、::selection、原生表单控件也不吃 theme。贯通它们的唯一通道是
 * :root 上的 CSS 变量，因此这里的输出就是"深色模式能否覆盖全站"的判据。
 */

import { withAlpha } from './contrast'
import { fontFamilies } from './typography'
import type { CSSObject, Theme } from '@mui/material/styles'
import type { SgTheme } from './types'

/** 所有变量统一前缀，避免与第三方样式表的自定义属性撞名。 */
export const CSS_VARIABLE_PREFIX = '--sg-'

/**
 * 自带样式表且不吃 MUI theme 的第三方表面。
 *
 * 刻意不包含：
 * - react-markdown：MarkdownRenderer 把每个元素都映射成了 MUI 组件，已跟随主题；
 * - <audio>：项目里没有该标签，播放全部走 new Audio() 编程式接口；
 * - @uiw/react-md-editor：虽在 package.json 中，但 src 内零引用。
 */
export const THIRD_PARTY_SURFACE_SELECTORS = ['.vditor', '.react-flow'] as const

/** 读取挂在 theme 上的 token；单独成函数也让 './types' 的模块增强在本文件内确定生效。 */
function sg(theme: Theme): SgTheme {
  return theme.sg
}

/**
 * 把 token 摊平成 :root 的自定义属性。
 *
 * 命名约定：
 * - `--sg-accent*` 对应 palette 的 primary，用"accent"是因为第三方样式表里
 *   primary 一词常已被占用；
 * - 颜色一律原样输出不透明十六进制，透明度在消费处用 color-mix 或 rgba 派生。
 */
export function buildCssVariables(theme: Theme): Record<string, string> {
  const { color, shadow, shape, motion, mode } = sg(theme)

  return {
    '--sg-color-scheme': mode,

    '--sg-bg': color.bgDefault,
    '--sg-bg-paper': color.bgPaper,
    '--sg-bg-subtle': color.bgSubtle,
    '--sg-surface': color.surface,
    '--sg-surface-raised': color.surfaceRaised,
    '--sg-surface-sunken': color.surfaceSunken,
    '--sg-scrim': color.scrim,

    '--sg-text': color.textPrimary,
    '--sg-text-secondary': color.textSecondary,
    '--sg-text-disabled': color.textDisabled,
    '--sg-text-inverse': color.textInverse,

    '--sg-border': color.border,
    '--sg-border-strong': color.borderStrong,
    '--sg-divider': color.divider,
    '--sg-divider-strong': color.dividerStrong,

    '--sg-accent': color.primary,
    '--sg-accent-hover': color.primaryHover,
    '--sg-accent-active': color.primaryActive,
    '--sg-accent-soft': color.primarySoft,
    '--sg-accent-faint': color.primaryFaint,
    '--sg-on-accent': color.onPrimary,

    '--sg-secondary': color.secondary,
    '--sg-secondary-soft': color.secondarySoft,
    '--sg-on-secondary': color.onSecondary,

    '--sg-success': color.success,
    '--sg-success-soft': color.successSoft,
    '--sg-on-success': color.onSuccess,
    '--sg-warning': color.warning,
    '--sg-warning-soft': color.warningSoft,
    '--sg-on-warning': color.onWarning,
    '--sg-error': color.error,
    '--sg-error-soft': color.errorSoft,
    '--sg-on-error': color.onError,
    '--sg-info': color.info,
    '--sg-info-soft': color.infoSoft,
    '--sg-on-info': color.onInfo,

    '--sg-focus-ring': color.focusRing,

    '--sg-radius-xs': `${shape.radiusXs}px`,
    '--sg-radius-sm': `${shape.radiusSm}px`,
    '--sg-radius': `${shape.radiusMd}px`,
    '--sg-radius-lg': `${shape.radiusLg}px`,
    '--sg-radius-xl': `${shape.radiusXl}px`,
    '--sg-radius-pill': `${shape.radiusPill}px`,

    '--sg-shadow-1': shadow.shadow1,
    '--sg-shadow-2': shadow.shadow2,
    '--sg-shadow-3': shadow.shadow3,
    '--sg-shadow-4': shadow.shadow4,
    '--sg-shadow-inset': shadow.shadowInset,

    '--sg-duration-fast': `${motion.durationFast}ms`,
    '--sg-duration-base': `${motion.durationBase}ms`,
    '--sg-duration-slow': `${motion.durationSlow}ms`,
    '--sg-ease-standard': motion.easeStandard,

    '--sg-font-sans': fontFamilies.sans,
    '--sg-font-display': fontFamilies.display,
    '--sg-font-mono': fontFamilies.mono,
  }
}

/**
 * Vditor 的表层覆盖。
 *
 * 只做容器级（背景、边框、文字色）的兜底：VditorEditor.tsx 的 Box sx 已经用
 * theme palette 管了 .vditor 与 .vditor-toolbar，特异性高于这里的全局规则，
 * 所以本函数兜的是 sx 覆盖不到的编辑区与 Vditor 自身样式表写死的部分。
 * 代码高亮（hljs github 主题）与工具栏图标色留待带视觉验证时再处理。
 */
function createVditorStyles(theme: Theme): CSSObject {
  const { color } = sg(theme)

  return {
    '.vditor': {
      backgroundColor: color.surface,
      borderColor: color.border,
      color: color.textPrimary,
      borderRadius: `${theme.shape.borderRadius}px`,
    },
    '.vditor-toolbar': {
      backgroundColor: color.bgSubtle,
      borderBottomColor: color.divider,
    },
    '.vditor-toolbar__item .vditor-tooltipped': {
      color: color.textSecondary,
    },
    '.vditor-content, .vditor-ir .vditor-reset, .vditor-sv .vditor-reset': {
      backgroundColor: color.surface,
      color: color.textPrimary,
      caretColor: color.primary,
    },
    '.vditor-reset::placeholder, .vditor-ir__marker--pre': {
      color: color.textDisabled,
    },
  }
}

/**
 * ReactFlow 的表层覆盖。
 *
 * 只动背景、控件与连线颜色，不动 attribution 的可见性 —— ReactFlow 的 MIT
 * 许可要求保留署名，这里仅让它跟随主题配色。
 */
function createReactFlowStyles(theme: Theme): CSSObject {
  const { color } = sg(theme)

  return {
    '.react-flow': {
      backgroundColor: color.bgDefault,
      '--xy-background-pattern-dots-color-default': color.borderStrong,
      '--xy-edge-stroke-default': color.borderStrong,
      '--xy-node-color-default': color.textPrimary,
    },
    '.react-flow__controls-button': {
      backgroundColor: color.surface,
      borderBottomColor: color.divider,
      color: color.textSecondary,
      fill: color.textSecondary,
    },
    '.react-flow__controls-button:hover': {
      backgroundColor: color.bgSubtle,
      color: color.textPrimary,
      fill: color.textPrimary,
    },
    '.react-flow__edge-path': {
      stroke: color.borderStrong,
    },
    '.react-flow__edge.selected .react-flow__edge-path': {
      stroke: color.primary,
    },
    '.react-flow__handle': {
      backgroundColor: color.surfaceRaised,
      borderColor: color.borderStrong,
    },
    '.react-flow__attribution': {
      backgroundColor: color.surface,
      color: color.textDisabled,
    },
    '.react-flow__attribution a': {
      color: color.textSecondary,
    },
  }
}

/**
 * 供 MuiCssBaseline.styleOverrides 直接消费的全局样式。
 *
 * MUI 的 CssBaseline 把 styleOverrides 的顶层键当作全局选择器，因此这里
 * 不需要也不应该再包一层 @global。
 */
export function createGlobalStyles(theme: Theme): CSSObject {
  const { color, motion } = sg(theme)
  const isDark = theme.palette.mode === 'dark'

  return {
    ':root': {
      ...buildCssVariables(theme),
      // 让原生控件（滚动条、下拉、日期选择器）跟随模式。
      colorScheme: theme.palette.mode,
    },

    html: {
      WebkitFontSmoothing: 'antialiased',
      MozOsxFontSmoothing: 'grayscale',
      textRendering: 'optimizeLegibility',
    },

    // Firefox 与新版 Chromium 走标准属性，webkit 伪元素只管老 Chromium/Safari。
    '*': {
      scrollbarWidth: 'thin',
      scrollbarColor: `${color.borderStrong} transparent`,
    },

    '::-webkit-scrollbar': {
      width: 10,
      height: 10,
    },
    '::-webkit-scrollbar-track': {
      backgroundColor: 'transparent',
    },
    '::-webkit-scrollbar-corner': {
      backgroundColor: 'transparent',
    },
    '::-webkit-scrollbar-thumb': {
      // border + padding-box 让滑块四周留出透明边，比实底细条更轻。
      backgroundColor: withAlpha(color.textPrimary, isDark ? 0.28 : 0.22),
      borderRadius: `${theme.sg.shape.radiusPill}px`,
      border: '3px solid transparent',
      backgroundClip: 'padding-box',
    },
    '::-webkit-scrollbar-thumb:hover': {
      backgroundColor: withAlpha(color.textPrimary, isDark ? 0.44 : 0.34),
    },

    '::selection': {
      backgroundColor: withAlpha(color.primary, isDark ? 0.42 : 0.24),
      color: color.textPrimary,
    },

    // 键盘焦点必须始终可见；鼠标点击不显示 outline（:focus-visible 的语义）。
    ':focus-visible': {
      outline: `2px solid ${color.focusRing}`,
      outlineOffset: 2,
      borderRadius: `${theme.sg.shape.radiusXs}px`,
    },
    ':focus:not(:focus-visible)': {
      outline: 'none',
    },

    // 用户显式要求减少动效时，关掉全站过渡。
    '@media (prefers-reduced-motion: reduce)': {
      '*, *::before, *::after': {
        animationDuration: '0.01ms !important',
        animationIterationCount: '1 !important',
        transitionDuration: `${motion.durationInstant}ms !important`,
        scrollBehavior: 'auto !important',
      },
    },

    ...createVditorStyles(theme),
    ...createReactFlowStyles(theme),
  } as CSSObject
}
