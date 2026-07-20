const VOLUME_HEADING_PATTERN = /^【第[零一二三四五六七八九十百千万两\d]+卷】(?:\s*\S.*)?$/
const ALT_VOLUME_HEADING_PATTERN = /^(第[零一二三四五六七八九十百千万两\d]+卷)(?:[：:\s]+)(.+)$/

const OUTLINE_FIELD_LABELS = [
  '题材类型',
  '全局主题',
  '故事总纲',
  '核心卖点',
  '核心矛盾',
  '终局方向',
  '覆盖卷段',
  '覆盖章节',
  '阶段目标',
  '阶段主冲突',
  '成长重点',
  '阶段收束标记',
  '规划原则',
  '细化窗口',
  '连续性重点',
  '防漂移规则',
  '人物协同方式',
  '章节规模',
  '卷定位',
  '核心目标',
  '主冲突',
  '人物焦点',
  '伏笔任务',
  '卷末爆点',
  '下卷交接',
]

const CHAPTER_OUTLINE_FIELD_LABELS = [
  '场景目标',
  '冲突设计',
  '关键事件',
  '涉及人物',
  '人物推进',
  '情节作用',
  '信息落地',
  '结尾钩子',
  '爽点类型',
  '伏笔事项',
]

const CHAPTER_OUTLINE_FIELD_LABEL_SET = new Set(CHAPTER_OUTLINE_FIELD_LABELS)
const OUTLINE_FIELD_LABEL_SET = new Set(OUTLINE_FIELD_LABELS)
const CHAPTER_OUTLINE_TABLE_HEADER_PATTERN = /^\|\s*字段\s*\|\s*内容\s*\|?$/i
const MARKDOWN_TABLE_SEPARATOR_PATTERN = /^:?-{3,}:?$/

type ParsedField = {
  label: string
  value: string
  labelOnly: boolean
}

function isMarkdownControlLine(line: string): boolean {
  return /^(#{1,6}\s|[-*+]\s|>\s|\d+\.\s|---+$|```)/.test(line)
}

function normalizeFieldValue(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function buildField(label: string, value: string): string {
  const normalizedValue = normalizeFieldValue(value)
  return normalizedValue ? `- **${label}：** ${normalizedValue}` : `- **${label}：**`
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function stripFieldLabelDecoratorPrefix(value: string): { stripped: boolean; value: string } {
  const match = value.match(/^(?<marker>\*{1,3}|_{1,3})(?=(?:[：:】\]\s]|$))/)
  if (!match?.groups?.marker) {
    return { stripped: false, value }
  }

  return {
    stripped: true,
    value: value.slice(match.groups.marker.length),
  }
}

function hasCanonicalEmphasizedMarkdownField(line: string, labels: string[]): boolean {
  const trimmed = line.trim()
  return labels.some((label) =>
    new RegExp(`^[-*+]\\s+\\*\\*${escapeRegExp(label)}[：:]\\*\\*(?:\\s+|$)`).test(trimmed),
  )
}

function stripFieldPrefix(line: string, allowMarkdownList: boolean): string {
  let value = line.trim()
  if (allowMarkdownList) {
    value = value.replace(/^[-*+]\s*/, '')
  }

  value = value.replace(/^\*+/, '').trimStart()
  value = value.replace(/^[【[]\s*/, '')
  return value
}

function parseField(line: string, labels: string[], options?: { allowMarkdownList?: boolean }): ParsedField | null {
  const allowMarkdownList = options?.allowMarkdownList ?? false
  if (!allowMarkdownList && isMarkdownControlLine(line)) {
    return null
  }

  const source = stripFieldPrefix(line, allowMarkdownList)
  const orderedLabels = [...labels].sort((left, right) => right.length - left.length)

  for (const label of orderedLabels) {
    if (!source.startsWith(label)) {
      continue
    }

    let rest = source.slice(label.length)
    const hadWhitespaceSeparator = /^\s+/.test(rest)
    let consumedDelimiter = false
    let strippedDecorator = false

    const stripDecorator = () => {
      const result = stripFieldLabelDecoratorPrefix(rest)
      rest = result.value
      strippedDecorator = strippedDecorator || result.stripped
    }

    stripDecorator()

    while (true) {
      if (/^[】\]]/.test(rest)) {
        rest = rest.slice(1)
        consumedDelimiter = true
        stripDecorator()
        continue
      }
      if (/^[：:]/.test(rest)) {
        rest = rest.slice(1)
        consumedDelimiter = true
        stripDecorator()
        continue
      }
      break
    }

    stripDecorator()
    const value = rest.trim()
    if (!value) {
      if (consumedDelimiter || strippedDecorator || !rest.length) {
        return { label, value: '', labelOnly: true }
      }
      continue
    }

    if (consumedDelimiter || hadWhitespaceSeparator || strippedDecorator) {
      return { label, value, labelOnly: false }
    }
  }

  return null
}

function splitMarkdownTableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map((cell) => cell.trim())
}

function isMarkdownTableSeparatorRow(line: string): boolean {
  const cells = splitMarkdownTableCells(line)
  return Boolean(cells.length) && cells.every((cell) => cell && MARKDOWN_TABLE_SEPARATOR_PATTERN.test(cell))
}

function parseChapterOutlineTableRow(line: string): string | null {
  if (!line.trim().startsWith('|')) {
    return null
  }

  const cells = splitMarkdownTableCells(line)
  const visibleCells = cells.filter((cell) => cell)
  if (!visibleCells.length || visibleCells.every((cell) => MARKDOWN_TABLE_SEPARATOR_PATTERN.test(cell))) {
    return null
  }

  const firstCell = cells[0] || ''
  const secondCell = cells.slice(1).join(' | ').trim()
  const parsedFirstCell = parseField(firstCell, CHAPTER_OUTLINE_FIELD_LABELS, { allowMarkdownList: true })

  if (parsedFirstCell) {
    const value = parsedFirstCell.labelOnly ? secondCell : parsedFirstCell.value
    return buildField(parsedFirstCell.label, value)
  }

  const combinedRow = visibleCells.join(' ')
  const parsedCombinedRow = parseField(combinedRow, CHAPTER_OUTLINE_FIELD_LABELS, { allowMarkdownList: true })
  if (parsedCombinedRow && !parsedCombinedRow.labelOnly) {
    return buildField(parsedCombinedRow.label, parsedCombinedRow.value)
  }

  return null
}

function normalizeVolumeHeading(line: string): string | null {
  if (VOLUME_HEADING_PATTERN.test(line)) {
    return `### ${line}`
  }

  const match = line.match(ALT_VOLUME_HEADING_PATTERN)
  if (match?.[1] && match?.[2]) {
    return `### ${match[1]} ${match[2].trim()}`
  }

  return null
}

function parseOutlineField(line: string): string | null {
  const parsed = parseField(line, OUTLINE_FIELD_LABELS)
  if (!parsed || parsed.labelOnly || !OUTLINE_FIELD_LABEL_SET.has(parsed.label)) {
    return null
  }
  return buildField(parsed.label, parsed.value)
}

function parseChapterOutlineField(line: string): string | null {
  if (hasCanonicalEmphasizedMarkdownField(line, CHAPTER_OUTLINE_FIELD_LABELS)) {
    return line.trim()
  }

  const parsed = parseField(line, CHAPTER_OUTLINE_FIELD_LABELS, { allowMarkdownList: true })
  if (!parsed || parsed.labelOnly || !CHAPTER_OUTLINE_FIELD_LABEL_SET.has(parsed.label)) {
    return null
  }
  return buildField(parsed.label, parsed.value)
}

function parseChapterOutlineFieldLabel(line: string): string | null {
  if (hasCanonicalEmphasizedMarkdownField(line, CHAPTER_OUTLINE_FIELD_LABELS)) {
    return null
  }

  const parsed = parseField(line, CHAPTER_OUTLINE_FIELD_LABELS, { allowMarkdownList: true })
  if (!parsed || !parsed.labelOnly) {
    return null
  }
  return parsed.label
}

export function normalizeMarkdownContent(content: string): string {
  if (!content) {
    return ''
  }

  const normalized = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const formattedLines: string[] = []
  let previousWasBlank = true
  let inChapterOutlineTable = false
  let pendingChapterFieldLabel: string | null = null
  let pendingChapterFieldValues: string[] = []

  const flushPendingChapterField = () => {
    if (!pendingChapterFieldLabel) {
      return
    }

    formattedLines.push(buildField(pendingChapterFieldLabel, pendingChapterFieldValues.join(' ')))
    pendingChapterFieldLabel = null
    pendingChapterFieldValues = []
    previousWasBlank = false
  }

  for (const rawLine of normalized.split('\n')) {
    const trimmed = rawLine.trim()

    if (!trimmed) {
      flushPendingChapterField()
      if (!previousWasBlank) {
        formattedLines.push('')
        previousWasBlank = true
      }
      inChapterOutlineTable = false
      continue
    }

    const volumeHeading = normalizeVolumeHeading(trimmed)
    const outlineField = parseOutlineField(trimmed)
    const chapterField = parseChapterOutlineField(trimmed)
    const chapterFieldLabel = parseChapterOutlineFieldLabel(trimmed)

    if (pendingChapterFieldLabel) {
      if (
        CHAPTER_OUTLINE_TABLE_HEADER_PATTERN.test(trimmed) ||
        volumeHeading ||
        outlineField ||
        chapterField ||
        chapterFieldLabel
      ) {
        flushPendingChapterField()
      } else {
        pendingChapterFieldValues.push(trimmed)
        previousWasBlank = false
        continue
      }
    }

    if (CHAPTER_OUTLINE_TABLE_HEADER_PATTERN.test(trimmed)) {
      inChapterOutlineTable = true
      continue
    }

    if (inChapterOutlineTable && isMarkdownTableSeparatorRow(trimmed)) {
      continue
    }

    if (inChapterOutlineTable) {
      const tableField = parseChapterOutlineTableRow(trimmed)
      if (tableField) {
        formattedLines.push(tableField)
        previousWasBlank = false
        continue
      }
      inChapterOutlineTable = false
    }

    if (chapterField) {
      formattedLines.push(chapterField)
      previousWasBlank = false
      continue
    }

    if (chapterFieldLabel) {
      pendingChapterFieldLabel = chapterFieldLabel
      pendingChapterFieldValues = []
      previousWasBlank = false
      continue
    }

    if (volumeHeading) {
      if (!previousWasBlank) {
        formattedLines.push('')
      }
      formattedLines.push(volumeHeading)
      previousWasBlank = false
      continue
    }

    if (outlineField) {
      formattedLines.push(outlineField)
      previousWasBlank = false
      continue
    }

    formattedLines.push(trimmed)
    previousWasBlank = false
  }

  flushPendingChapterField()

  return formattedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
