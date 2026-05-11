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

export function formatDateTime(value: unknown): string | null {
  if (!value || typeof value !== 'string') return null
  const dt = new Date(value)
  if (!Number.isFinite(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export async function copyText(text: string): Promise<void> {
  const value = String(text || '')
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    window.prompt('复制以下内容：', value)
  }
}

export function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
