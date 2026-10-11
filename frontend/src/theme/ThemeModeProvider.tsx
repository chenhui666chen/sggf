/**
 * 主题模式的 React 层。
 *
 * 职责：持有用户的模式选择、跟随系统偏好、持久化、把已解析模式写到
 * `<html data-theme>`，并据此产出全站唯一的 MUI theme。
 *
 * 防闪烁（FOUC）由 index.html 的内联脚本负责：它在 React 挂载前就读好
 * localStorage 并写好 data-theme，因此这里的首帧永远不会是错的模式。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
// 走 @mui/material 的 barrel：项目的 muiIconsSource 契约测试禁止组件级运行时深导入。
import { CssBaseline, ThemeProvider as MuiThemeProvider } from '@mui/material'

import { createAppTheme } from './createAppTheme'
import { MUI_LOCALES } from './muiLocale'
import {
  nextThemeMode,
  readStoredThemeMode,
  readSystemPrefersDark,
  resolveThemeMode,
} from './themeMode'
import {
  applyThemeColorMeta,
  applyThemeModeToElement,
  persistThemeMode,
  subscribeToSystemColorScheme,
  THEME_COLOR_META_NAME,
} from './themeModeDom'
import type { ReactNode } from 'react'
import type { AppLanguage } from '@/i18n'
import type { ResolvedThemeMode, ThemeMode } from './themeMode'
import type { DensityMode } from './tokens'

export interface ThemeModeContextValue {
  /** 用户的选择，可能是 'system'。 */
  readonly mode: ThemeMode
  /** 实际生效的模式，只有 light / dark。 */
  readonly resolvedMode: ResolvedThemeMode
  readonly setMode: (mode: ThemeMode) => void
  /** 轮换 light → dark → system，供单个图标按钮使用。 */
  readonly cycleMode: () => void
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null)

export function useThemeMode(): ThemeModeContextValue {
  const value = useContext(ThemeModeContext)

  if (!value) {
    // 静默返回默认值会让"忘了包 Provider"变成难查的视觉 bug，不如直接抛错。
    throw new Error('useThemeMode 必须在 <ThemeModeProvider> 内部调用')
  }

  return value
}

export interface ThemeModeProviderProps {
  children: ReactNode
  /**
   * 密度档位。刻意只暴露原始值而不是整个 createAppTheme 选项对象：
   * 对象字面量每次渲染都是新引用，会让 useMemo 的缓存彻底失效。
   */
  density?: DensityMode
  /**
   * 界面语言，决定 MUI 自带的那批文案（Alert 的关闭按钮、Autocomplete 的空
   * 选项提示等）用哪套 locale。这批字符串不走 i18next，只能由主题注入。
   *
   * 刻意做成可选的普通 prop、而不是在这里读 i18n 的 context：主题层对 i18n
   * 只保留类型级依赖，没有 I18nProvider 也能独立渲染与测试。
   */
  language?: AppLanguage
}

/** Node/SSR 下没有 window，统一取安全默认值，让服务端渲染也能出图。 */
function readInitialMode(): ThemeMode {
  return typeof window === 'undefined' ? 'system' : readStoredThemeMode(window.localStorage)
}

function getLocalStorage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}

function getMatchMedia() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return null
  }

  return window.matchMedia.bind(window)
}

function getDocumentElement(): HTMLElement | null {
  return typeof document === 'undefined' ? null : document.documentElement
}

function getThemeColorMeta(): HTMLElement | null {
  if (typeof document === 'undefined') {
    return null
  }

  return document.querySelector(`meta[name="${THEME_COLOR_META_NAME}"]`)
}

export function ThemeModeProvider({ children, density, language }: ThemeModeProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(readInitialMode)
  const [systemPrefersDark, setSystemPrefersDark] = useState<boolean>(readSystemPrefersDark)

  useEffect(() => {
    // 挂载时重读一次：内联脚本只写了 data-theme，没有把偏好传进 React。
    setSystemPrefersDark(readSystemPrefersDark())

    // 即使用户选了固定模式也保持订阅，这样切回 system 时状态是最新的。
    return subscribeToSystemColorScheme(getMatchMedia(), setSystemPrefersDark)
  }, [])

  const resolvedMode = resolveThemeMode(mode, systemPrefersDark)

  useEffect(() => {
    // 纯 CSS 表面（滚动条、Vditor、ReactFlow）读不到 MUI theme，只认这个属性。
    applyThemeModeToElement(getDocumentElement(), resolvedMode)
    applyThemeColorMeta(getThemeColorMeta(), resolvedMode)
  }, [resolvedMode])

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
    persistThemeMode(getLocalStorage(), next)
  }, [])

  const cycleMode = useCallback(() => {
    setMode(nextThemeMode(mode))
  }, [mode, setMode])

  // 依赖用查表结果而不是 language 本身：en-US 查出来是 undefined（MUI 的内置
  // 默认就是英文，没有数据可注入），这样在两门都无数据的语言之间切换不会
  // 白重建一次主题。
  const localeComponents = language === undefined ? undefined : MUI_LOCALES[language]

  // theme 只在模式、密度或语言变化时重建；重建意味着 Emotion 要重新序列化全部
  // overrides，代价不低，因此这里的依赖数组必须保持最小。
  const theme = useMemo(
    () => createAppTheme(resolvedMode, { density, components: localeComponents }),
    [resolvedMode, density, localeComponents],
  )

  const value = useMemo<ThemeModeContextValue>(
    () => ({ mode, resolvedMode, setMode, cycleMode }),
    [mode, resolvedMode, setMode, cycleMode],
  )

  return (
    <ThemeModeContext.Provider value={value}>
      <MuiThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MuiThemeProvider>
    </ThemeModeContext.Provider>
  )
}
