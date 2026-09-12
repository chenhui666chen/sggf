import type { AppLanguage } from '@/i18n'
import { formatDateTime as formatDateTimeInLocale } from '@/i18n/format'
import type { TranslateFn } from '@/pages/audiobook/audioLibraryDisplay'

export function formatPath(value: unknown): string | null {
  if (!value || typeof value !== 'string') return null
  const parts = value.split(/[\\/]+/).filter(Boolean)
  return parts.slice(-2).join('/')
}

export function formatPaths(value: unknown): string | null {
  if (!Array.isArray(value)) return null
  const formatted = value.map(formatPath).filter((item): item is string => Boolean(item))
  return formatted.length ? formatted.join('  ') : null
}

export function formatDateTime(value: unknown, locale?: AppLanguage): string | null {
  if (!value || typeof value !== 'string') return null
  const dt = new Date(value)
  if (!Number.isFinite(dt.getTime())) return value
  // 本函数的名字与 i18n 层的同名，因此导入时取了别名。
  // 三态返回刻意保留：非字符串给 null，解析不出来就把原串还回去。
  return formatDateTimeInLocale(dt, { locale }) || value
}

export async function copyText(text: string, t?: TranslateFn): Promise<void> {
  const value = String(text || '')
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    window.prompt(t ? t('dreamweaverRun.copyTextPrompt') : '复制以下内容：', value)
  }
}

export function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
