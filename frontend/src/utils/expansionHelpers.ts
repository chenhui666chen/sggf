/**
 * 大纲与人物扩展相关的通用辅助函数。
 */

export interface ExpansionHistoryRecord {
  timestamp: number
  content: string
  chapterCount?: number
  characterCount?: number
}

interface ChapterBreakdownCsvRow {
  chapterNumber: string
  title: string
  sceneGoal: string
  conflictDesign: string
  keyEvents: string
  involvedCharacters: string
  characterProgress: string
  plotFunction: string
  informationPayoff: string
  endingHook: string
}

type ChapterBreakdownFieldKey =
  | 'sceneGoal'
  | 'conflictDesign'
  | 'keyEvents'
  | 'involvedCharacters'
  | 'characterProgress'
  | 'plotFunction'
  | 'informationPayoff'
  | 'endingHook'

const CHAPTER_BREAKDOWN_FIELD_MATCHERS: Array<{
  key: ChapterBreakdownFieldKey
  pattern: RegExp
}> = [
  { key: 'sceneGoal', pattern: /^-\s*场景目标[：:]\s*(.+)$/ },
  { key: 'conflictDesign', pattern: /^-\s*冲突设计[：:]\s*(.+)$/ },
  { key: 'keyEvents', pattern: /^-\s*关键事件[：:]\s*(.+)$/ },
  { key: 'involvedCharacters', pattern: /^-\s*涉及人物[：:]\s*(.+)$/ },
  { key: 'characterProgress', pattern: /^-\s*人物推进[：:]\s*(.+)$/ },
  { key: 'plotFunction', pattern: /^-\s*情节作用[：:]\s*(.+)$/ },
  { key: 'informationPayoff', pattern: /^-\s*信息落地[：:]\s*(.+)$/ },
  { key: 'endingHook', pattern: /^-\s*结尾钩子[：:]\s*(.+)$/ },
]

function canUseLocalStorage(): boolean {
  return typeof localStorage !== 'undefined'
}

function createEmptyChapterBreakdownRow(): ChapterBreakdownCsvRow {
  return {
    chapterNumber: '',
    title: '',
    sceneGoal: '',
    conflictDesign: '',
    keyEvents: '',
    involvedCharacters: '',
    characterProgress: '',
    plotFunction: '',
    informationPayoff: '',
    endingHook: '',
  }
}

function isChapterBreakdownRowEmpty(row: ChapterBreakdownCsvRow): boolean {
  return Object.values(row).every((value) => !String(value || '').trim())
}

function toChapterBreakdownCsvLine(row: ChapterBreakdownCsvRow): string {
  return [
    row.chapterNumber,
    row.title,
    row.sceneGoal,
    row.conflictDesign,
    row.keyEvents,
    row.involvedCharacters,
    row.characterProgress,
    row.plotFunction,
    row.informationPayoff,
    row.endingHook,
  ]
    .map((value) => escapeCSV(value))
    .join(',')
}

/**
 * 计算扩展进度百分比。
 */
export function calculateProgress(currentIteration: number, maxIterations: number): number {
  return Math.min(Math.round((currentIteration / maxIterations) * 100), 100)
}

/**
 * 估算剩余时间。
 */
export function estimateRemainingTime(
  startTime: number,
  currentIteration: number,
  totalIterations: number,
): number {
  if (currentIteration === 0) return 0

  const elapsedTime = Date.now() - startTime
  const avgTimePerIteration = elapsedTime / currentIteration
  const remainingIterations = totalIterations - currentIteration

  return Math.round((avgTimePerIteration * remainingIterations) / 1000)
}

/**
 * 格式化剩余时间展示。
 */
export function formatRemainingTime(seconds: number): string {
  if (seconds < 60) {
    return `约 ${seconds} 秒`
  }
  if (seconds < 3600) {
    return `约 ${Math.floor(seconds / 60)} 分钟`
  }

  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `约 ${hours} 小时 ${minutes} 分钟`
}

/**
 * 保存扩展历史记录。
 */
export function saveHistory(
  type: 'outline' | 'character',
  content: string,
  count: number,
): ExpansionHistoryRecord {
  const record: ExpansionHistoryRecord = {
    timestamp: Date.now(),
    content,
    ...(type === 'outline' ? { chapterCount: count } : { characterCount: count }),
  }

  if (!canUseLocalStorage()) {
    return record
  }

  const storageKey = `expansion_history_${type}`
  const history = getHistory(type)
  history.push(record)

  if (history.length > 20) {
    history.shift()
  }

  localStorage.setItem(storageKey, JSON.stringify(history))
  return record
}

/**
 * 获取扩展历史记录。
 */
export function getHistory(type: 'outline' | 'character'): ExpansionHistoryRecord[] {
  if (!canUseLocalStorage()) {
    return []
  }

  const storageKey = `expansion_history_${type}`
  const stored = localStorage.getItem(storageKey)
  if (!stored) {
    return []
  }

  try {
    const parsed = JSON.parse(stored) as unknown
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed.filter((item): item is ExpansionHistoryRecord =>
      Boolean(item)
      && typeof item === 'object'
      && typeof (item as ExpansionHistoryRecord).timestamp === 'number'
      && typeof (item as ExpansionHistoryRecord).content === 'string',
    )
  } catch {
    return []
  }
}

/**
 * 清除历史记录。
 */
export function clearHistory(type: 'outline' | 'character'): void {
  if (!canUseLocalStorage()) {
    return
  }

  localStorage.removeItem(`expansion_history_${type}`)
}

/**
 * 导出为 Markdown 格式。
 */
export function exportToMarkdown(
  content: string,
  title: string,
  metadata?: Record<string, unknown>,
): string {
  let markdown = `# ${title}\n\n`

  if (metadata && Object.keys(metadata).length > 0) {
    markdown += '## 元信息\n\n'
    Object.entries(metadata).forEach(([key, value]) => {
      markdown += `- **${key}**: ${String(value)}\n`
    })
    markdown += '\n'
  }

  markdown += `## 内容\n\n${content}\n`
  return markdown
}

/**
 * 下载文本文件。
 */
export function downloadFile(
  content: string,
  filename: string,
  mimeType = 'text/plain',
): void {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * 将章节细纲导出为 CSV。
 * 当前按统一细纲字段导出：场景目标、冲突设计、关键事件、涉及人物、人物推进、情节作用、信息落地、结尾钩子。
 */
export function exportChapterBreakdownToCSV(chapterBreakdown: string): string {
  const lines = chapterBreakdown.split('\n')
  const csvLines = [
    '章节编号,标题,场景目标,冲突设计,关键事件,涉及人物,人物推进,情节作用,信息落地,结尾钩子',
  ]

  let currentRow = createEmptyChapterBreakdownRow()

  const flushCurrentRow = () => {
    if (isChapterBreakdownRowEmpty(currentRow)) {
      return
    }
    csvLines.push(toChapterBreakdownCsvLine(currentRow))
    currentRow = createEmptyChapterBreakdownRow()
  }

  lines.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) {
      return
    }

    const chapterMatch = trimmed.match(/^第(\d+)章[：:]\s*(.+)$/)
    if (chapterMatch) {
      flushCurrentRow()
      currentRow.chapterNumber = chapterMatch[1]
      currentRow.title = chapterMatch[2]
      return
    }

    for (const matcher of CHAPTER_BREAKDOWN_FIELD_MATCHERS) {
      const match = trimmed.match(matcher.pattern)
      if (!match) {
        continue
      }
      currentRow[matcher.key] = match[1]
      return
    }

    if (trimmed.match(/^\d+[.、]\s+/)) {
      currentRow.keyEvents = currentRow.keyEvents
        ? `${currentRow.keyEvents} / ${trimmed}`
        : trimmed
    }
  })

  flushCurrentRow()
  return csvLines.join('\n')
}

/**
 * CSV 转义函数。
 */
function escapeCSV(str: string): string {
  if (!str) return ''
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}
