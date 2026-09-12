/**
 * 主题模式的纯逻辑：解析、持久化读取、与系统偏好合成。
 *
 * 这里只放不依赖 React 与 DOM 的部分，方便在 Node 环境下直接测试；
 * Provider 与副作用在 ThemeModeProvider 中。
 */

import type { ReadableStorage } from '@/utils/domContracts'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedThemeMode = 'light' | 'dark'

/** localStorage 键名，index.html 的防闪烁脚本必须与此保持一致。 */
export const THEME_MODE_STORAGE_KEY = 'sg.theme-mode'

/** 写到 <html data-theme> 上的属性名，供纯 CSS 表面（滚动条、第三方组件）选择。 */
export const THEME_MODE_DOM_ATTRIBUTE = 'data-theme'

/** 系统深浅色偏好的媒体查询；读取与订阅必须用同一个串，否则会出现两者不同步。 */
export const SYSTEM_COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)'

/** 轮换顺序：单个图标按钮依次走过这三档。 */
export const THEME_MODES: readonly ThemeMode[] = ['light', 'dark', 'system']

/** 无法判断时一律回到 system，让用户跟随操作系统。 */
const FALLBACK_MODE: ThemeMode = 'system'

export function isThemeMode(value: unknown): value is ThemeMode {
  return typeof value === 'string' && (THEME_MODES as readonly string[]).includes(value)
}

export function parseThemeMode(value: unknown): ThemeMode {
  return isThemeMode(value) ? value : FALLBACK_MODE
}

/** Safari 隐私模式下访问 localStorage 会抛异常，必须吞掉并回退。 */
export function readStoredThemeMode(storage: ReadableStorage | null): ThemeMode {
  if (!storage) {
    return FALLBACK_MODE
  }

  try {
    return parseThemeMode(storage.getItem(THEME_MODE_STORAGE_KEY))
  } catch {
    return FALLBACK_MODE
  }
}

export function resolveThemeMode(mode: ThemeMode, systemPrefersDark: boolean): ResolvedThemeMode {
  if (mode === 'system') {
    return systemPrefersDark ? 'dark' : 'light'
  }

  return mode
}

/**
 * 轮换到下一个模式：light → dark → system → light。
 *
 * 让一个图标按钮就能覆盖三档，不必再为"跟随系统"单开一个下拉菜单。
 */
export function nextThemeMode(mode: ThemeMode): ThemeMode {
  const index = THEME_MODES.indexOf(mode)

  // 不在列表里的输入会让 indexOf 返回 -1，+1 取模后落到 0（light），是安全兜底。
  return THEME_MODES[(index + 1) % THEME_MODES.length]
}

/** 读取系统偏好；无 matchMedia 的环境（旧浏览器、Node）按浅色处理。 */
export function readSystemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }

  try {
    return window.matchMedia(SYSTEM_COLOR_SCHEME_QUERY).matches
  } catch {
    return false
  }
}
