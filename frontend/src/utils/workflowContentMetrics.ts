const CHINESE_NUMERAL_PATTERN = '[0-9一二三四五六七八九十百千万零两〇]+'
const CHAPTER_HEADING_LABEL_PATTERN = '[章节回幕集话]'
const INLINE_CHAPTER_PATTERN = new RegExp(
  `第\\s*(${CHINESE_NUMERAL_PATTERN})\\s*${CHAPTER_HEADING_LABEL_PATTERN}(?=[：:、.\\-\\s]|$)|chapter\\s+(\\d+)`,
  'giu',
)
const BRACKETED_NAME_FIELD_LINE_PATTERN = /^(?:#+\s*)?(?:\*\*)?【(?:姓名|角色名|人物名)】(?:\*\*)?\s*[：:]\s*(.+?)\s*$/u
const CHARACTER_FIELD_LINE_PATTERN = /^(?:[-*]\s*)?(?:\d+[.)、]\s*)?(?:\*\*)?(姓名|角色名|人物名)(?:\*\*)?\s*[：:]\s*(.+?)\s*$/u
const CHARACTER_CARD_HEADING_PATTERN = /^###\s*(?!【姓名】)(?:\*\*)?(.+?)(?:\*\*)?\s*$/u
const CHARACTER_SUMMARY_PATTERN = /^(?:[-*]\s*)?(.{1,30}?)[；;]\s*(?:定位|身份|角色|特质|能力|背景|动机|关系|故事立场|阵营|年龄|性别|职业|能力\/状态)(?:[=：:]|$)/u
const CHARACTER_ROLE_LINE_PATTERN = /^(?:[-*]\s*)?(.{1,30}?)\s*[：:]\s*(?:主角|反派|配角|盟友|导师|对手|支持角色|中立角色|核心角色|重要角色)(?:\s|$)/u
const MARKDOWN_SECTION_FIELD_PATTERN = /^\s*[-*]\s+(?:\*\*)?[^*：:\n]{1,20}(?:\*\*)?\s*[：:]\s*\S+/u
const CHAPTER_LINE_PATTERNS = [
  new RegExp(
    `^\\s*(?:\\d+[.)、]\\s*)?(?:#{1,6}\\s*)?(?:[一二三四五六七八九十百千万零两〇]+[、.．]\\s*)?第\\s*(${CHINESE_NUMERAL_PATTERN})\\s*(${CHAPTER_HEADING_LABEL_PATTERN})(?=$|大纲|[：:、.\\-\\s])`,
    'iu',
  ),
  /^\s*(?:\d+[.)、]\s*)?(?:#{1,6}\s*)?chapter\s+(\d+)(?:\s|$)/iu,
]

const CHARACTER_CARD_FIELD_LABELS = [
  '年龄/性别',
  '年龄性别',
  '角色定位',
  '故事立场',
  '所属势力',
  '重要性',
  '外貌特征',
  '性格特点',
  '背景故事',
  '背景经历',
  '核心动机',
  '能力/特长',
  '能力特长',
  '能力/状态',
  '弱点/缺陷',
  '弱点缺陷',
  '在情节中的作用',
  '剧情作用',
  '人物成长线',
  '成长线',
  '关键关系',
  '关联线索',
  '定位',
  '动机',
  '特质',
  '关系边',
]

const NON_CHARACTER_HEADING_KEYWORDS = [
  '人物设定',
  '人物关系',
  '角色关系',
  '关系补丁',
  '角色名单',
  '人物名单',
  '主角阵营',
  '对手阵营',
  '支持角色',
  '中立角色',
  '主要人物',
  '主要角色',
  '核心人物',
  '新增角色',
  '协同新增角色',
  '人物卡',
  '角色卡',
  '人物体系',
  '角色体系',
  '关系图谱',
]
const NON_CHARACTER_NAME_KEYWORDS = [
  '姓名',
  '角色名',
  '人物名',
  ...CHARACTER_CARD_FIELD_LABELS,
]

function normalizeText(value: string): string {
  return value.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function pickPreferredNameSegment(value: string): string {
  const segments = value
    .split(/\/|｜|\|/u)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => item.replace(/\s*[（(][^（）()]{1,20}[)）]\s*$/u, '').trim())
    .map((item) => item.replace(/编号\s*\d+/u, '').trim())
    .map((item) => item.replace(/^[“"'‘’]+|[”"'’]+$/gu, '').trim())

  for (let index = segments.length - 1; index >= 0; index -= 1) {
    const item = segments[index]
    if (item && !['未知', '不详', '匿名', '？？？', '???'].includes(item)) {
      return item
    }
  }

  return segments[0] || value
}

function normalizeCharacterName(name: string): string {
  let value = pickPreferredNameSegment(String(name || '').trim())
  value = value.replace(/^#+\s*/, '')
  value = value.replace(/^\*+|\*+$/g, '').trim()
  value = value.replace(/^(?:姓名|角色名|人物名)\s*[：:]\s*/u, '')
  value = value.replace(/[：:]\s*(?:主角|反派|配角|盟友|导师|对手|支持角色|中立角色|核心角色|重要角色).*$/u, '')
  value = value.replace(/\s*[（(][^（）()]{1,20}[)）]\s*$/u, '')
  value = value.replace(/[【】[\]<>]/g, '')
  value = value.replace(/^[“"'‘’]+|[”"'’]+$/gu, '')
  value = value.replace(/\s+/g, '')
  return value.trim()
}

function isLikelyCharacterName(name: string): boolean {
  if (!name || name.length > 30) {
    return false
  }

  if (/^\d+$/u.test(name)) {
    return false
  }

  if (/[↔⇄→←=]/u.test(name)) {
    return false
  }

  if (/^第[0-9一二三四五六七八九十百千万零两〇]+[章节回幕集话]$/u.test(name)) {
    return false
  }

  if (NON_CHARACTER_HEADING_KEYWORDS.some((keyword) => name.includes(keyword))) {
    return false
  }

  return !NON_CHARACTER_NAME_KEYWORDS.some((keyword) => name === keyword)
}

function hasCharacterCardField(lines: string[], startIndex: number): boolean {
  const nextLines = lines
    .slice(startIndex + 1)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 4)

  return nextLines.some((line) => {
    if (BRACKETED_NAME_FIELD_LINE_PATTERN.test(line)) {
      return true
    }

    if (CHARACTER_FIELD_LINE_PATTERN.test(line)) {
      return true
    }

    if (MARKDOWN_SECTION_FIELD_PATTERN.test(line)) {
      return true
    }

    return CHARACTER_CARD_FIELD_LABELS.some((label) => (
      new RegExp(`^(?:[-*]\\s*)?(?:\\d+[.)、]\\s*)?(?:\\*\\*)?${escapeRegExp(label)}(?:\\*\\*)?\\s*[：:]`, 'u')
    ).test(line))
  })
}

function appendCharacterName(
  candidate: string,
  seen: Set<string>,
  names: string[],
) {
  const normalized = normalizeCharacterName(candidate)
  if (!isLikelyCharacterName(normalized) || seen.has(normalized)) {
    return
  }

  seen.add(normalized)
  names.push(normalized)
}

export function extractCharacterNames(text: string): string[] {
  if (!text.trim()) {
    return []
  }

  const lines = normalizeText(text).split('\n')
  const names: string[] = []
  const seen = new Set<string>()

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (!trimmed) {
      return
    }

    const fieldMatch = trimmed.match(CHARACTER_FIELD_LINE_PATTERN)
    if (fieldMatch?.[2]) {
      appendCharacterName(fieldMatch[2], seen, names)
      return
    }

    const bracketedFieldMatch = trimmed.match(BRACKETED_NAME_FIELD_LINE_PATTERN)
    if (bracketedFieldMatch?.[1]) {
      appendCharacterName(bracketedFieldMatch[1], seen, names)
      return
    }

    const summaryMatch = trimmed.match(CHARACTER_SUMMARY_PATTERN)
    if (summaryMatch?.[1]) {
      appendCharacterName(summaryMatch[1], seen, names)
      return
    }

    const roleMatch = trimmed.match(CHARACTER_ROLE_LINE_PATTERN)
    if (roleMatch?.[1]) {
      appendCharacterName(roleMatch[1], seen, names)
      return
    }

    const headingMatch = trimmed.match(CHARACTER_CARD_HEADING_PATTERN)
    if (headingMatch?.[1] && hasCharacterCardField(lines, index)) {
      appendCharacterName(headingMatch[1], seen, names)
    }
  })

  return names
}

function countLineBasedChapters(lines: string[]): number {
  const chapterKeys = new Set<string>()

  lines.forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) {
      return
    }

    for (const pattern of CHAPTER_LINE_PATTERNS) {
      const match = trimmed.match(pattern)
      if (!match) {
        continue
      }

      const chapterNumber = match[1]?.trim()
      const chapterLabel = match[2]?.trim() || 'chapter'
      if (chapterNumber) {
        chapterKeys.add(`${chapterLabel}-${normalizeChapterNumber(chapterNumber)}`)
      }
      return
    }
  })

  return chapterKeys.size
}

function countInlineChapters(text: string): number {
  const chapterKeys = new Set<string>()

  for (const match of text.matchAll(INLINE_CHAPTER_PATTERN)) {
    const chapterNumber = (match[1] || match[2] || '').trim()
    if (!chapterNumber) {
      continue
    }

    const chapterLabel = match[1] ? 'cn' : 'chapter'
    chapterKeys.add(`${chapterLabel}-${normalizeChapterNumber(chapterNumber)}`)
  }

  return chapterKeys.size
}

export function estimateCharacterCount(text: string): number {
  return extractCharacterNames(text || '').length
}

export function estimateChapterCount(text: string): number {
  const normalized = normalizeText(text || '').trim()
  if (!normalized) {
    return 0
  }

  const lines = normalized.split('\n')
  const lineBasedCount = countLineBasedChapters(lines)
  if (lines.length === 1) {
    return Math.max(lineBasedCount, countInlineChapters(normalized))
  }

  if (lineBasedCount > 0) {
    return lineBasedCount
  }

  return 0
}

function normalizeChapterNumber(token: string): string {
  const value = token.trim()
  if (/^\d+$/u.test(value)) {
    return value
  }

  const digits = new Map<string, number>([
    ['零', 0],
    ['〇', 0],
    ['一', 1],
    ['二', 2],
    ['两', 2],
    ['三', 3],
    ['四', 4],
    ['五', 5],
    ['六', 6],
    ['七', 7],
    ['八', 8],
    ['九', 9],
  ])
  const units = new Map<string, number>([
    ['十', 10],
    ['百', 100],
    ['千', 1000],
    ['万', 10000],
  ])

  let total = 0
  let section = 0
  let number = 0

  for (const char of value) {
    const digit = digits.get(char)
    if (digit != null) {
      number = digit
      continue
    }

    const unit = units.get(char)
    if (unit == null) {
      return value
    }

    if (unit === 10000) {
      section = (section + (number || 0)) * unit
      total += section
      section = 0
      number = 0
      continue
    }

    section += (number || 1) * unit
    number = 0
  }

  const resolved = total + section + number
  return resolved > 0 || value === '零' || value === '〇' ? String(resolved) : value
}
