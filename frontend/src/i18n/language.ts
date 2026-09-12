/**
 * 语言注册表与语言标记匹配。
 *
 * 设计取舍：
 * - zh-CN 是事实源（所有文案先有中文），en-US 是国际兜底；
 * - 有语言信号但不被支持（法语、日语浏览器）→ 走 en-US，绝不给中文；
 * - 完全没有信号 → 走 zh-CN；
 * - 繁体中文在 zh-TW 资源建成前一律路由到 zh-CN，比给英文更接近用户预期。
 */

import type { ReadableStorage } from '@/utils/domContracts'

export type AppLanguage = 'zh-CN' | 'en-US'

export interface LanguageDescriptor {
  /** 应用内部语言码，同时作为 i18next 的 lng 值与资源目录名 */
  code: AppLanguage
  /** 传给 Intl 与写入 <html lang> 的 BCP-47 标记 */
  bcp47: string
  /** 该语言的自称，切换菜单里永远用母语展示 */
  nativeLabel: string
  /** 英文名，供语言自身不可读时兜底 */
  englishLabel: string
}

export const SUPPORTED_LANGUAGES: readonly LanguageDescriptor[] = [
  {
    code: 'zh-CN',
    bcp47: 'zh-CN',
    nativeLabel: '简体中文',
    englishLabel: 'Simplified Chinese',
  },
  {
    code: 'en-US',
    bcp47: 'en-US',
    nativeLabel: 'English',
    englishLabel: 'English',
  },
]

export const SUPPORTED_LANGUAGE_CODES: readonly AppLanguage[] = SUPPORTED_LANGUAGES.map(
  (entry) => entry.code,
)

/** 事实源语言：i18next 的最终 fallback，保证任何 key 都不会渲染成空白。 */
export const DEFAULT_LANGUAGE: AppLanguage = 'zh-CN'

/** 国际兜底语言：识别到语言但不支持时使用。 */
export const FALLBACK_LANGUAGE: AppLanguage = 'en-US'

/** localStorage 键名。 */
export const LANGUAGE_STORAGE_KEY = 'sg.lang'

/** 语言候选来源，按优先级从高到低。 */
export const LANGUAGE_CANDIDATE_SOURCES = ['localStorage', 'navigator'] as const

export function isAppLanguage(value: unknown): value is AppLanguage {
  return typeof value === 'string' && (SUPPORTED_LANGUAGE_CODES as readonly string[]).includes(value)
}

export function getLanguageDescriptor(code: AppLanguage): LanguageDescriptor {
  return (
    SUPPORTED_LANGUAGES.find((entry) => entry.code === code) ??
    // 数组第一项即 DEFAULT_LANGUAGE，理论上取不到，仅为满足类型收窄。
    (SUPPORTED_LANGUAGES[0] as LanguageDescriptor)
  )
}

/**
 * 把任意 BCP-47（含下划线写法、大小写混写、Accept-Language 的 q 权重）
 * 归一到受支持语言；无法匹配返回 null。
 */
export function matchSupportedLanguage(tag: unknown): AppLanguage | null {
  if (typeof tag !== 'string') {
    return null
  }

  // 'en-US;q=0.9' → 'en-US'
  const primarySubtag = tag
    .split(';')[0]
    ?.trim()
    .split('-')[0]
    ?.split('_')[0]
    ?.toLowerCase()

  if (!primarySubtag) {
    return null
  }

  if (primarySubtag === 'zh') {
    return 'zh-CN'
  }

  if (primarySubtag === 'en') {
    return 'en-US'
  }

  return null
}

/**
 * 从候选列表中定出初始语言。
 *
 * 候选按优先级传入（已持久化的选择 > 浏览器语言）。
 * 区分"没有信号"与"有信号但不支持"，两者的兜底语言不同。
 */
export function resolveInitialLanguage(
  candidates: readonly (string | null | undefined)[],
): AppLanguage {
  for (const candidate of candidates) {
    const matched = matchSupportedLanguage(candidate)

    if (matched) {
      return matched
    }
  }

  const hasAnySignal = candidates.some(
    (candidate) => typeof candidate === 'string' && candidate.trim() !== '',
  )

  return hasAnySignal ? FALLBACK_LANGUAGE : DEFAULT_LANGUAGE
}

/**
 * i18next 的语言链：以自身开头，以另一种受支持语言收尾，
 * 保证任何 key 都不会渲染成空白。
 */
export function resolveFallbackChain(language: AppLanguage): AppLanguage[] {
  const others = SUPPORTED_LANGUAGE_CODES.filter((code) => code !== language)

  return [language, ...others]
}

/** 读取已持久化的语言；无存储、异常或存了不支持的语言都返回 null（表示"无信号"）。 */
export function readStoredLanguage(storage: ReadableStorage | null): AppLanguage | null {
  if (!storage) {
    return null
  }

  try {
    return matchSupportedLanguage(storage.getItem(LANGUAGE_STORAGE_KEY))
  } catch {
    return null
  }
}
