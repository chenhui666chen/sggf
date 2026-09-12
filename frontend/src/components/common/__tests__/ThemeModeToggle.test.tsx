/**
 * ThemeModeToggle 的渲染契约。
 *
 * 项目没有 jsdom，点击轮换这个行为本身由 theme/__tests__/themeMode.test.ts 的
 * nextThemeMode 覆盖；这里验的是静态渲染能验的另一半：图标跟着模式走、
 * aria-label 用**当前界面语言**说出**用户选的那一档**、以及它是个真正的 button。
 *
 * 图标的期望值从真实图标组件反查 path 指纹，而不是手抄一份映射表——手抄的那份
 * 自己就会漂移，口径与 theme/__tests__/fonts.test.ts 一致。
 */
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BrightnessAutoIcon from '@mui/icons-material/BrightnessAuto'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'

import ThemeModeToggle from '../ThemeModeToggle'
import { I18nProvider, bootstrapI18n } from '@/i18n'
import { THEME_MODE_STORAGE_KEY, ThemeModeProvider } from '@/theme'

/** 一个图标可能由多条 path 组成，全部拼起来才是它的指纹。 */
function iconSignature(markup: string): string {
  return [...markup.matchAll(/<path d="([^"]+)"/g)]
    .map((match) => match[1])
    .join('|')
}

function attribute(markup: string, name: string): string | undefined {
  return markup.match(new RegExp(`${name}="([^"]*)"`))?.[1]
}

const ICON_SIGNATURES = {
  light: iconSignature(renderToStaticMarkup(<LightModeIcon />)),
  dark: iconSignature(renderToStaticMarkup(<DarkModeIcon />)),
  system: iconSignature(renderToStaticMarkup(<BrightnessAutoIcon />)),
} as const

interface StubOptions {
  readonly systemPrefersDark?: boolean
}

/**
 * 让 ThemeModeProvider 读到指定的持久化模式。
 *
 * Provider 在完全没有 window 时一律回到 system，想验 light / dark 两档就得给它
 * 一个 window。matchMedia 也一并补上：不补的话 resolvedMode 永远是 light，
 * 就验不出"按钮说的是选中的档位而不是解析后的档位"这件事。
 */
function withStoredMode<T>(mode: string, run: () => T, options: StubOptions = {}): T {
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => (key === THEME_MODE_STORAGE_KEY ? mode : null),
      setItem: () => {},
    },
    matchMedia: (query: string) => ({
      media: query,
      matches: options.systemPrefersDark ?? false,
      addEventListener: () => {},
      removeEventListener: () => {},
    }),
  })

  try {
    return run()
  } finally {
    vi.unstubAllGlobals()
  }
}

/** 层级与 main.tsx 一致：I18nProvider 在外，ThemeModeProvider 在内。 */
function renderToggle(): string {
  return renderToStaticMarkup(
    <I18nProvider>
      <ThemeModeProvider>
        <ThemeModeToggle />
      </ThemeModeProvider>
    </I18nProvider>,
  )
}

describe('ThemeModeToggle', () => {
  it('renders a real button so it stays reachable by keyboard', () => {
    const markup = renderToggle()

    expect(markup).toContain('<button')
    expect(markup).toContain('MuiIconButton-root')
  })

  it('starts in system mode and shows the auto icon', () => {
    // Node 里没有 window，Provider 回到 system——这也正是首次访问者的状态。
    expect(iconSignature(renderToggle())).toBe(ICON_SIGNATURES.system)
  })

  it('shows a distinct icon for each of the three modes', () => {
    // 三档共用一个图标的话，用户点下去得不到任何反馈，轮换就成了盲操作。
    const signatures = (['light', 'dark', 'system'] as const).map((mode) =>
      withStoredMode(mode, () => iconSignature(renderToggle())),
    )

    expect(signatures).toEqual([
      ICON_SIGNATURES.light,
      ICON_SIGNATURES.dark,
      ICON_SIGNATURES.system,
    ])
    expect(new Set(signatures).size).toBe(3)
  })

  it('names the current mode in the aria-label, in the interface language', () => {
    expect(attribute(renderToggle(), 'aria-label')).toBe('切换外观，当前跟随系统')
  })

  it('names the chosen mode rather than the resolved one', () => {
    // 选了 system 而系统是深色时，按钮要说"跟随系统"而不是"深色"：
    // 说成深色的话用户会以为这个按钮决定当前明暗，点下去却跳到了浅色。
    const markup = withStoredMode('system', () => renderToggle(), { systemPrefersDark: true })

    expect(attribute(markup, 'aria-label')).toBe('切换外观，当前跟随系统')
    expect(attribute(markup, 'aria-label')).not.toContain('深色')
  })

  it('follows the interface language rather than hard-coding Chinese', async () => {
    // 走 bootstrapI18n 而不是直接建实例：那才是 main.tsx 的真实路径，
    // 顺带验到 en-US 的懒加载资源确实可用。
    const instance = await bootstrapI18n('en-US')
    const markup = renderToStaticMarkup(
      <I18nProvider instance={instance}>
        <ThemeModeProvider>
          <ThemeModeToggle />
        </ThemeModeProvider>
      </I18nProvider>,
    )

    expect(attribute(markup, 'aria-label')).toBe('Change appearance, currently System')
  })
})
