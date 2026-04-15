const VOLUME_HEADING_PATTERN = /^【第[零一二三四五六七八九十百千万两\d]+卷】(?:\s*\S.*)?$/
const ALT_VOLUME_HEADING_PATTERN = /^(第[零一二三四五六七八九十百千万两\d]+卷)(?:[：:]\s*|\s{1,2})(.+)$/
const OUTLINE_FIELD_PATTERN = /^([\u4e00-\u9fa5A-Za-z0-9]{2,12})[：:]\s*(.+)$/
const OUTLINE_FIELD_LABELS = new Set([
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
])

function isMarkdownControlLine(line: string): boolean {
  return /^(#{1,6}\s|[-*+]\s|>\s|\d+\.\s|---+$|```)/.test(line)
}

function normalizeVolumeHeading(line: string): string | null {
  if (VOLUME_HEADING_PATTERN.test(line)) {
    return `### ${line}`
  }

  const altMatch = line.match(ALT_VOLUME_HEADING_PATTERN)
  if (altMatch?.[1] && altMatch?.[2]) {
    return `### ${altMatch[1]} ${altMatch[2].trim()}`
  }

  return null
}

function normalizeOutlineField(line: string): string | null {
  if (isMarkdownControlLine(line)) {
    return null
  }

  const match = line.match(OUTLINE_FIELD_PATTERN)
  if (!match) {
    return null
  }

  const label = match[1]?.trim()
  const value = match[2]?.trim()
  if (!label || !value || !OUTLINE_FIELD_LABELS.has(label)) {
    return null
  }

  return `- **${label}：** ${value}`
}

export function normalizeMarkdownContent(content: string): string {
  if (!content) {
    return ''
  }

  const normalized = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  const hasVolumeStructure =
    VOLUME_HEADING_PATTERN.test(normalized) || /(^|\n)第[零一二三四五六七八九十百千万两\d]+卷(?:[：:]|\s{1,2})/.test(normalized)
  const hasOutlineFieldLabels = Array.from(OUTLINE_FIELD_LABELS).some((label) =>
    normalized.includes(`${label}：`) || normalized.includes(`${label}:`)
  )

  if (!hasVolumeStructure && !hasOutlineFieldLabels) {
    return normalized.replace(/\n{3,}/g, '\n\n').trim()
  }

  const formattedLines: string[] = []
  let previousWasBlank = true

  for (const rawLine of normalized.split('\n')) {
    const trimmed = rawLine.trim()

    if (!trimmed) {
      if (!previousWasBlank) {
        formattedLines.push('')
        previousWasBlank = true
      }
      continue
    }

    const volumeHeading = normalizeVolumeHeading(trimmed)
    if (volumeHeading) {
      if (!previousWasBlank) {
        formattedLines.push('')
      }
      formattedLines.push(volumeHeading)
      previousWasBlank = false
      continue
    }

    const outlineField = normalizeOutlineField(trimmed)
    if (outlineField) {
      formattedLines.push(outlineField)
      previousWasBlank = false
      continue
    }

    formattedLines.push(trimmed)
    previousWasBlank = false
  }

  return formattedLines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
