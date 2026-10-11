import { describe, expect, it } from 'vitest'

import {
  THEME_MODE_STORAGE_KEY,
  THEME_MODES,
  isThemeMode,
  nextThemeMode,
  parseThemeMode,
  readStoredThemeMode,
  resolveThemeMode,
} from '../themeMode'

// 创建只在读取时生效的最小 Storage 替身，避免依赖 jsdom。
function createStorageStub(stored: Record<string, string>, options?: { throwOnGetItem?: boolean }) {
  return {
    getItem(key: string) {
      if (options?.throwOnGetItem) {
        throw new Error('storage disabled')
      }
      return Object.prototype.hasOwnProperty.call(stored, key) ? stored[key] : null
    },
  }
}

describe('theme mode parsing', () => {
  it('accepts the three supported modes verbatim', () => {
    expect(isThemeMode('light')).toBe(true)
    expect(isThemeMode('dark')).toBe(true)
    expect(isThemeMode('system')).toBe(true)
  })

  it('rejects values that are not exactly a supported mode', () => {
    expect(isThemeMode('DARK')).toBe(false)
    expect(isThemeMode('')).toBe(false)
    expect(isThemeMode(null)).toBe(false)
    expect(isThemeMode(undefined)).toBe(false)
    expect(isThemeMode(1)).toBe(false)
    expect(isThemeMode({})).toBe(false)
  })

  it('falls back to system for any unusable stored value', () => {
    expect(parseThemeMode('dark')).toBe('dark')
    expect(parseThemeMode('DARK')).toBe('system')
    expect(parseThemeMode('')).toBe('system')
    expect(parseThemeMode(null)).toBe('system')
    expect(parseThemeMode(undefined)).toBe('system')
  })
})

describe('stored theme mode reading', () => {
  it('reads the persisted mode from the documented storage key', () => {
    expect(THEME_MODE_STORAGE_KEY).toBe('sg.theme-mode')
    expect(readStoredThemeMode(createStorageStub({ 'sg.theme-mode': 'dark' }))).toBe('dark')
  })

  it('falls back to system when nothing is persisted', () => {
    expect(readStoredThemeMode(createStorageStub({}))).toBe('system')
  })

  it('falls back to system when storage is unavailable', () => {
    expect(readStoredThemeMode(null)).toBe('system')
    expect(readStoredThemeMode(createStorageStub({}, { throwOnGetItem: true }))).toBe('system')
  })
})

describe('theme mode resolution', () => {
  it('lets an explicit mode win over the system preference', () => {
    expect(resolveThemeMode('light', true)).toBe('light')
    expect(resolveThemeMode('dark', false)).toBe('dark')
  })

  it('follows the system preference only in system mode', () => {
    expect(resolveThemeMode('system', true)).toBe('dark')
    expect(resolveThemeMode('system', false)).toBe('light')
  })
})

describe('theme mode cycling', () => {
  it('exposes the three modes in the order the toggle walks through', () => {
    expect(THEME_MODES).toEqual(['light', 'dark', 'system'])
  })

  it('advances light -> dark -> system -> light so a single icon button can reach all three', () => {
    expect(nextThemeMode('light')).toBe('dark')
    expect(nextThemeMode('dark')).toBe('system')
    expect(nextThemeMode('system')).toBe('light')
  })

  it('is a pure function of its input', () => {
    expect(nextThemeMode('light')).toBe(nextThemeMode('light'))
  })
})
