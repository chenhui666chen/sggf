import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LANGUAGE,
  FALLBACK_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  isAppLanguage,
  matchSupportedLanguage,
  readStoredLanguage,
  resolveFallbackChain,
  resolveInitialLanguage,
} from '../language'

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

describe('supported language registry', () => {
  it('ships exactly zh-CN and en-US with zh-CN as the source of truth', () => {
    expect(SUPPORTED_LANGUAGES.map((entry) => entry.code)).toEqual(['zh-CN', 'en-US'])
    expect(DEFAULT_LANGUAGE).toBe('zh-CN')
    expect(FALLBACK_LANGUAGE).toBe('en-US')
    expect(LANGUAGE_STORAGE_KEY).toBe('sg.lang')
  })

  it('carries a native label so the switcher stays readable in any language', () => {
    const zh = SUPPORTED_LANGUAGES.find((entry) => entry.code === 'zh-CN')
    const en = SUPPORTED_LANGUAGES.find((entry) => entry.code === 'en-US')

    expect(zh?.nativeLabel).toBe('简体中文')
    expect(en?.nativeLabel).toBe('English')
    // 每个语言都要有用于 <html lang> 与 Intl 的 BCP-47 标记。
    for (const entry of SUPPORTED_LANGUAGES) {
      expect(entry.bcp47).toBeTruthy()
    }
  })

  it('guards the language literal type', () => {
    expect(isAppLanguage('zh-CN')).toBe(true)
    expect(isAppLanguage('en-US')).toBe(true)
    expect(isAppLanguage('ja-JP')).toBe(false)
    expect(isAppLanguage(null)).toBe(false)
    expect(isAppLanguage(42)).toBe(false)
  })
})

describe('language tag matching', () => {
  it('maps every simplified-Chinese spelling onto zh-CN', () => {
    for (const tag of ['zh', 'zh-CN', 'zh-cn', 'zh_CN', 'zh-Hans', 'zh-Hans-CN', 'zh-SG', 'ZH-hans']) {
      expect(matchSupportedLanguage(tag), tag).toBe('zh-CN')
    }
  })

  it('routes traditional Chinese to zh-CN rather than English while zh-TW is unbuilt', () => {
    for (const tag of ['zh-TW', 'zh-HK', 'zh-Hant', 'zh-MO', 'zh-Hant-TW']) {
      expect(matchSupportedLanguage(tag), tag).toBe('zh-CN')
    }
  })

  it('maps every English spelling onto en-US', () => {
    for (const tag of ['en', 'en-US', 'en-us', 'en_GB', 'en-GB', 'en-AU', 'EN', 'en-IN']) {
      expect(matchSupportedLanguage(tag), tag).toBe('en-US')
    }
  })

  it('returns null for unsupported or malformed tags', () => {
    expect(matchSupportedLanguage('ja-JP')).toBeNull()
    expect(matchSupportedLanguage('fr')).toBeNull()
    expect(matchSupportedLanguage('de-DE')).toBeNull()
    expect(matchSupportedLanguage('')).toBeNull()
    expect(matchSupportedLanguage(null)).toBeNull()
    expect(matchSupportedLanguage(undefined)).toBeNull()
    expect(matchSupportedLanguage(123)).toBeNull()
    expect(matchSupportedLanguage('   ')).toBeNull()
  })

  it('tolerates quality-weighted Accept-Language style values', () => {
    expect(matchSupportedLanguage('en-US;q=0.9')).toBe('en-US')
    expect(matchSupportedLanguage('zh-CN;q=0.8')).toBe('zh-CN')
  })
})

describe('initial language resolution', () => {
  it('takes the first candidate that maps to a supported language', () => {
    expect(resolveInitialLanguage(['ja-JP', 'en-GB'])).toBe('en-US')
    expect(resolveInitialLanguage([null, 'zh-TW'])).toBe('zh-CN')
    expect(resolveInitialLanguage(['en', 'zh-CN'])).toBe('en-US')
  })

  it('prefers the international fallback when a signal exists but is unsupported', () => {
    // 法语/日语浏览器显然不是中文用户，给英文远好于给中文。
    expect(resolveInitialLanguage(['fr'])).toBe('en-US')
    expect(resolveInitialLanguage(['ja-JP', 'ko-KR', null])).toBe('en-US')
  })

  it('uses the default language only when there is no signal at all', () => {
    expect(resolveInitialLanguage([])).toBe('zh-CN')
    expect(resolveInitialLanguage([null, undefined, ''])).toBe('zh-CN')
  })
})

describe('fallback chain', () => {
  it('always ends on the other supported language so no key renders blank', () => {
    expect(resolveFallbackChain('zh-CN')).toEqual(['zh-CN', 'en-US'])
    expect(resolveFallbackChain('en-US')).toEqual(['en-US', 'zh-CN'])
  })
})

describe('stored language reading', () => {
  it('reads a persisted supported language', () => {
    expect(readStoredLanguage(createStorageStub({ 'sg.lang': 'en-US' }))).toBe('en-US')
    expect(readStoredLanguage(createStorageStub({ 'sg.lang': 'zh-CN' }))).toBe('zh-CN')
  })

  it('returns null when nothing usable is persisted', () => {
    expect(readStoredLanguage(createStorageStub({}))).toBeNull()
    expect(readStoredLanguage(createStorageStub({ 'sg.lang': 'ja-JP' }))).toBeNull()
    expect(readStoredLanguage(null)).toBeNull()
    expect(readStoredLanguage(createStorageStub({}, { throwOnGetItem: true }))).toBeNull()
  })
})
