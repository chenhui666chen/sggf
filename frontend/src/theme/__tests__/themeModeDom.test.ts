/**
 * 主题模式 DOM/存储副作用的守护测试。
 *
 * 项目没有 jsdom，因此这些副作用全部写成"接收依赖的纯函数"，用最小替身覆盖。
 * 这里锁的是三件容易在重构中丢掉的事：属性名与存储键的契约、异常吞噬、
 * 以及取消订阅真的生效。
 */

import { describe, expect, it, vi } from 'vitest'

import { THEME_MODE_DOM_ATTRIBUTE, THEME_MODE_STORAGE_KEY } from '../themeMode'
import {
  BOOT_COLORS,
  SYSTEM_COLOR_SCHEME_QUERY,
  THEME_COLOR_META_NAME,
  applyThemeColorMeta,
  applyThemeModeToElement,
  persistThemeMode,
  subscribeToSystemColorScheme,
} from '../themeModeDom'
import { darkTokens, lightTokens } from '../tokens'
import type { MatchMediaFn } from '../themeModeDom'

/** 记录 setAttribute 调用的最小元素替身。 */
function createElementStub() {
  const calls: Array<{ name: string; value: string }> = []

  return {
    calls,
    setAttribute(name: string, value: string) {
      calls.push({ name, value })
    },
  }
}

/**
 * 可编程的 matchMedia 替身，能手动触发 change 事件。
 *
 * 替身用 `as unknown as MediaQueryList` 断言而不是自定义窄接口：后者在
 * strictFunctionTypes 下无法与真实的 window.matchMedia 互换，会让实现被迫
 * 接受两种签名。
 */
function createMatchMediaStub(options?: { throwOnCall?: boolean }) {
  const listeners = new Set<EventListenerOrEventListenerObject>()
  const queries: string[] = []

  const matchMedia = ((query: string): MediaQueryList => {
    if (options?.throwOnCall) {
      throw new Error('matchMedia unavailable')
    }

    queries.push(query)

    return {
      matches: false,
      addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
        if (type === 'change') {
          listeners.add(listener)
        }
      },
      removeEventListener(type: string, listener: EventListenerOrEventListenerObject) {
        if (type === 'change') {
          listeners.delete(listener)
        }
      },
    } as unknown as MediaQueryList
  }) as MatchMediaFn

  return {
    matchMedia,
    queries,
    /** 模拟系统偏好翻转。 */
    emit(matches: boolean) {
      const event = { matches } as MediaQueryListEvent

      listeners.forEach((listener) => {
        if (typeof listener === 'function') {
          listener(event)
        }
      })
    },
    listenerCount: () => listeners.size,
  }
}

describe('applyThemeModeToElement', () => {
  it('writes the resolved mode onto the documented html attribute', () => {
    const element = createElementStub()

    applyThemeModeToElement(element, 'dark')

    expect(THEME_MODE_DOM_ATTRIBUTE).toBe('data-theme')
    expect(element.calls).toEqual([{ name: 'data-theme', value: 'dark' }])
  })

  it('overwrites the previous mode instead of appending', () => {
    const element = createElementStub()

    applyThemeModeToElement(element, 'dark')
    applyThemeModeToElement(element, 'light')

    expect(element.calls).toHaveLength(2)
    expect(element.calls[1]).toEqual({ name: 'data-theme', value: 'light' })
  })

  it('tolerates a missing element so server rendering does not crash', () => {
    expect(() => applyThemeModeToElement(null, 'light')).not.toThrow()
  })

  it('never writes the unresolved system mode, only light or dark', () => {
    const element = createElementStub()

    applyThemeModeToElement(element, 'light')

    expect(element.calls.every((call) => call.value === 'light' || call.value === 'dark')).toBe(true)
  })
})

describe('persistThemeMode', () => {
  it('writes the chosen mode under the documented storage key', () => {
    const setItem = vi.fn()

    persistThemeMode({ setItem }, 'dark')

    expect(THEME_MODE_STORAGE_KEY).toBe('sg.theme-mode')
    expect(setItem).toHaveBeenCalledWith('sg.theme-mode', 'dark')
  })

  it('persists system as a first-class choice rather than dropping it', () => {
    const setItem = vi.fn()

    persistThemeMode({ setItem }, 'system')

    expect(setItem).toHaveBeenCalledWith('sg.theme-mode', 'system')
  })

  it('swallows storage failures so a private-mode browser cannot break the app', () => {
    const setItem = () => {
      throw new Error('quota exceeded')
    }

    expect(() => persistThemeMode({ setItem }, 'dark')).not.toThrow()
  })

  it('tolerates absent storage', () => {
    expect(() => persistThemeMode(null, 'dark')).not.toThrow()
  })
})

describe('applyThemeColorMeta', () => {
  it('tints the mobile browser chrome with the mode background', () => {
    const meta = createElementStub()

    applyThemeColorMeta(meta, 'dark')

    expect(THEME_COLOR_META_NAME).toBe('theme-color')
    expect(meta.calls).toEqual([{ name: 'content', value: darkTokens.bgDefault }])
  })

  it('tracks the light background too', () => {
    const meta = createElementStub()

    applyThemeColorMeta(meta, 'light')

    expect(meta.calls[0]).toEqual({ name: 'content', value: lightTokens.bgDefault })
  })

  it('tolerates a document without the meta tag', () => {
    expect(() => applyThemeColorMeta(null, 'light')).not.toThrow()
  })

  it('takes both boot colors straight from the tokens so the first frame cannot drift', () => {
    expect(BOOT_COLORS.light).toEqual({
      background: lightTokens.bgDefault,
      text: lightTokens.textPrimary,
    })
    expect(BOOT_COLORS.dark).toEqual({
      background: darkTokens.bgDefault,
      text: darkTokens.textPrimary,
    })
  })
})

describe('subscribeToSystemColorScheme', () => {
  it('queries the dark preference media feature', () => {
    const stub = createMatchMediaStub()

    subscribeToSystemColorScheme(stub.matchMedia, () => {})

    expect(SYSTEM_COLOR_SCHEME_QUERY).toBe('(prefers-color-scheme: dark)')
    expect(stub.queries).toEqual(['(prefers-color-scheme: dark)'])
  })

  it('forwards system preference changes to the callback', () => {
    const stub = createMatchMediaStub()
    const onChange = vi.fn()

    subscribeToSystemColorScheme(stub.matchMedia, onChange)
    stub.emit(true)
    stub.emit(false)

    expect(onChange).toHaveBeenNthCalledWith(1, true)
    expect(onChange).toHaveBeenNthCalledWith(2, false)
  })

  it('stops forwarding after the returned unsubscribe runs', () => {
    const stub = createMatchMediaStub()
    const onChange = vi.fn()

    const unsubscribe = subscribeToSystemColorScheme(stub.matchMedia, onChange)

    stub.emit(true)
    unsubscribe()
    stub.emit(false)

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(stub.listenerCount()).toBe(0)
  })

  it('returns a callable unsubscribe when matchMedia is unavailable', () => {
    const unsubscribe = subscribeToSystemColorScheme(null, () => {})

    expect(() => unsubscribe()).not.toThrow()
  })

  it('returns a callable unsubscribe when matchMedia throws', () => {
    const stub = createMatchMediaStub({ throwOnCall: true })

    const unsubscribe = subscribeToSystemColorScheme(stub.matchMedia, () => {})

    expect(() => unsubscribe()).not.toThrow()
  })

  it('subscribes exactly once per call', () => {
    const stub = createMatchMediaStub()

    subscribeToSystemColorScheme(stub.matchMedia, () => {})

    expect(stub.listenerCount()).toBe(1)
  })
})
