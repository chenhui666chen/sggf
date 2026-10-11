/**
 * 主题模式的 DOM 与存储副作用。
 *
 * 全部写成"接收依赖的纯函数"而不是直接摸 window / document / localStorage：
 * 项目没有 jsdom，只有这样才能被单元测试覆盖，Provider 也才能保持薄。
 */

import {
  SYSTEM_COLOR_SCHEME_QUERY,
  THEME_MODE_DOM_ATTRIBUTE,
  THEME_MODE_STORAGE_KEY,
} from './themeMode'
import { darkTokens, lightTokens } from './tokens'
import type { AttributeTarget, WritableStorage } from '@/utils/domContracts'
import type { ResolvedThemeMode, ThemeMode } from './themeMode'

// 订阅与读取必须共用同一个媒体查询串，这里从 themeMode 转出，
// 让调用方只依赖本模块即可。DOM 契约同理，统一由 utils/domContracts 定义。
export { SYSTEM_COLOR_SCHEME_QUERY } from './themeMode'
export type { AttributeTarget, WritableStorage }

/** index.html 里驱动移动端地址栏颜色的 meta 名。 */
export const THEME_COLOR_META_NAME = 'theme-color'

/**
 * 首帧与运行时共用的底色。
 *
 * index.html 的内联启动脚本必须写同样的值，否则 Emotion 注入前会闪一下
 * 错色。indexHtml.test.ts 会比对两边，防止改 token 时漏改 HTML。
 */
export const BOOT_COLORS: Readonly<Record<ResolvedThemeMode, Readonly<{ background: string; text: string }>>> = {
  light: { background: lightTokens.bgDefault, text: lightTokens.textPrimary },
  dark: { background: darkTokens.bgDefault, text: darkTokens.textPrimary },
}

/**
 * 把已解析的模式写到 <html data-theme>。
 *
 * 纯 CSS 表面（滚动条伪元素、第三方组件样式表、index.html 的防闪烁脚本）
 * 读不到 MUI theme，只能靠这个属性写选择器。
 */
export function applyThemeModeToElement(
  element: AttributeTarget | null,
  resolvedMode: ResolvedThemeMode,
): void {
  element?.setAttribute(THEME_MODE_DOM_ATTRIBUTE, resolvedMode)
}

/**
 * 让移动端浏览器的地址栏颜色跟随主题。
 *
 * `meta[name=theme-color]` 无法用 CSS 的 data-theme 选择器驱动，只能由 JS 写；
 * 不写的话深色模式下地址栏会一直是白的，是首屏最容易被看见的割裂。
 * meta 不存在时静默跳过——index.html 的契约由 indexHtml.test.ts 守。
 */
export function applyThemeColorMeta(
  meta: AttributeTarget | null,
  resolvedMode: ResolvedThemeMode,
): void {
  meta?.setAttribute('content', BOOT_COLORS[resolvedMode].background)
}

/**
 * 持久化用户的模式选择。
 *
 * Safari 隐私模式与配额耗尽都会抛异常；存不下偏好不该让整个应用崩掉，
 * 代价只是下次加载回到系统偏好。
 */
export function persistThemeMode(storage: WritableStorage | null, mode: ThemeMode): void {
  try {
    storage?.setItem(THEME_MODE_STORAGE_KEY, mode)
  } catch {
    // 忽略：下次加载回退到系统偏好。
  }
}

/**
 * 直接用 DOM 的 MediaQueryList 而不是自定义结构：后者的 addEventListener 参数更窄，
 * 在 strictFunctionTypes 下无法与 window.matchMedia 互相赋值。
 * 测试里用显式断言造替身，边界反而更清楚。
 */
export type MatchMediaFn = (query: string) => MediaQueryList

function noop(): void {
  // 无 matchMedia 时不需要取消订阅。
}

/**
 * 订阅系统深浅色偏好变化，返回取消订阅函数。
 *
 * 即使用户当前选了固定模式也应保持订阅，这样切回 system 时状态是最新的。
 * 没有 matchMedia 的环境（Node、极旧浏览器）返回 no-op，调用方按浅色处理。
 */
export function subscribeToSystemColorScheme(
  matchMedia: MatchMediaFn | null | undefined,
  onChange: (prefersDark: boolean) => void,
): () => void {
  if (typeof matchMedia !== 'function') {
    return noop
  }

  let list: MediaQueryList | null = null

  try {
    list = matchMedia(SYSTEM_COLOR_SCHEME_QUERY)
  } catch {
    return noop
  }

  const listener = (event: MediaQueryListEvent) => {
    onChange(event.matches)
  }

  list.addEventListener('change', listener)

  return () => {
    list?.removeEventListener('change', listener)
  }
}
