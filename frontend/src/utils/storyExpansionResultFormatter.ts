import { hasMarkdownFormat } from './formatContent'

export type StoryExpansionContentKind =
  | 'outline'
  | 'character'
  | 'delta'
  | 'relationship'
  | 'generic'

const CHAPTER_HEADING_PATTERN = /^(第[零一二三四五六七八九十百千万两\d]+[章卷回幕篇]|卷[零一二三四五六七八九十百千万两\d]+|chapter\s+\d+)/i
const PERSON_NAME_PATTERNS = [
  /^【姓名】[:：]?\s*(.+)$/,
  /^姓名[:：]?\s*(.+)$/,
  /^角色名[:：]?\s*(.+)$/,
  /^角色[:：]?\s*(.+)$/,
]
const STRUCTURED_FIELD_PATTERN = /^【?([\u4e00-\u9fa5A-Za-z0-9_/\-\s]{1,24})】?[:：]\s*(.+)$/
const BULLET_PATTERN = /^[-*•●]\s*(.+)$/
const ORDERED_PATTERN = /^(\d+)[.、]\s*(.+)$/
const SHORT_HEADING_PATTERN = /^[^\s]{2,20}[：:]$/
const SECTION_LABELS = new Set([
  '协同摘要',
  '协同建议',
  '执行轮次',
  '停止原因',
  '章节操作',
  '人物关系',
  '关系补丁',
  '章节增量',
  '人物增量',
  '更新后大纲',
  '更新后人物',
])
const PERSON_NAME_LABELS = new Set(['姓名', '角色', '角色名'])

function normalizeText(content: string): string {
  return content.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
}

function collapseBlankLines(text: string): string {
  return text.replace(/\n{3,}/g, '\n\n').trim()
}

function formatStandaloneHeading(line: string): string | null {
  const trimmed = line.trim()
  if (!trimmed) {
    return null
  }

  if (CHAPTER_HEADING_PATTERN.test(trimmed)) {
    return `## ${trimmed}`
  }

  if (SECTION_LABELS.has(trimmed)) {
    return `## ${trimmed}`
  }

  if (SHORT_HEADING_PATTERN.test(trimmed)) {
    return `### ${trimmed.replace(/[：:]$/, '')}`
  }

  for (const pattern of PERSON_NAME_PATTERNS) {
    const match = trimmed.match(pattern)
    if (match?.[1]?.trim()) {
      return `### ${match[1].trim()}`
    }
  }

  return null
}

function formatListItem(line: string): string | null {
  const bulletMatch = line.match(BULLET_PATTERN)
  if (bulletMatch?.[1]?.trim()) {
    return `- ${bulletMatch[1].trim()}`
  }

  const orderedMatch = line.match(ORDERED_PATTERN)
  if (orderedMatch?.[1] && orderedMatch?.[2]?.trim()) {
    return `${orderedMatch[1]}. ${orderedMatch[2].trim()}`
  }

  return null
}

function formatStructuredField(line: string): string | null {
  const match = line.match(STRUCTURED_FIELD_PATTERN)
  if (!match) {
    return null
  }

  const rawLabel = match[1]?.trim()
  const rawValue = match[2]?.trim()
  if (!rawLabel) {
    return null
  }

  if (!rawValue) {
    return `### ${rawLabel}`
  }

  if (PERSON_NAME_LABELS.has(rawLabel)) {
    return `### ${rawValue}`
  }

  return `- **${rawLabel}：** ${rawValue}`
}

function formatGenericLine(line: string, kind: StoryExpansionContentKind): string {
  if (kind === 'relationship' && /(→|->)/.test(line)) {
    return `- ${line}`
  }

  if (kind === 'delta' && line.length <= 36) {
    return `### ${line}`
  }

  return line
}

export function formatStoryExpansionDocument(
  content: string,
  kind: StoryExpansionContentKind = 'generic',
): string {
  const normalized = normalizeText(content)
  if (!normalized) {
    return ''
  }

  if (hasMarkdownFormat(normalized)) {
    return normalized
  }

  const formattedLines: string[] = []
  for (const rawLine of normalized.split('\n')) {
    const line = rawLine.trim()
    if (!line) {
      formattedLines.push('')
      continue
    }

    const headingLine = formatStandaloneHeading(line)
    if (headingLine) {
      formattedLines.push(headingLine)
      continue
    }

    const listLine = formatListItem(line)
    if (listLine) {
      formattedLines.push(listLine)
      continue
    }

    const structuredField = formatStructuredField(line)
    if (structuredField) {
      formattedLines.push(structuredField)
      continue
    }

    formattedLines.push(formatGenericLine(line, kind))
  }

  return collapseBlankLines(formattedLines.join('\n'))
}
