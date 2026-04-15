export interface CharacterRelationItem {
  target: string
  type: string
  description?: string
  detail?: string
}

export interface CharacterRelationsPayload {
  version: number
  text: string
  current_summary: string
  items: CharacterRelationItem[]
}

const PAYLOAD_KEYS = new Set(['version', 'text', 'current_summary', 'items'])

const normalizeText = (value: unknown): string => {
  if (typeof value !== 'string') {
    return ''
  }
  return value.trim()
}

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
)

const relationDetailToType = (detail: string, fallbackType = ''): string => {
  const text = normalizeText(detail)
  if (!text) {
    return normalizeText(fallbackType)
  }
  const match = text.split(/[\/／|｜]/, 1)[0]?.trim()
  return match || normalizeText(fallbackType) || text
}

const buildRelationDetail = (item: Partial<CharacterRelationItem>): string => {
  const detail = normalizeText(item.detail)
  if (detail) {
    return detail
  }
  const type = normalizeText(item.type)
  const description = normalizeText(item.description)
  if (type && description) {
    return `${type}/${description}`
  }
  return type || description
}

const parseRawRelationText = (value: string): CharacterRelationItem[] => {
  const items: CharacterRelationItem[] = []
  value
    .split(/[；;\n]+/)
    .map((segment) => segment.trim())
    .filter(Boolean)
    .forEach((segment) => {
      const separator = segment.includes('：') ? '：' : ':'
      const [rawTarget, rawDetail] = segment.includes(separator)
        ? segment.split(separator, 2)
        : ['', segment]
      const target = rawTarget.trim()
      const detail = rawDetail.trim()
      const type = relationDetailToType(detail)
      if (target && type) {
        items.push({ target, type, detail })
      }
    })
  return items
}

export const parseCharacterRelations = (value: unknown): CharacterRelationItem[] => {
  if (value == null || value === '') {
    return []
  }

  if (typeof value === 'string') {
    try {
      return parseCharacterRelations(JSON.parse(value))
    } catch {
      return parseRawRelationText(value)
    }
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => parseCharacterRelations(item))
      .flat()
  }

  if (!isRecord(value)) {
    return []
  }

  if (
    (typeof value.target === 'string' || typeof value.name === 'string') &&
    (typeof value.type === 'string' || typeof value.detail === 'string' || typeof value.description === 'string')
  ) {
    const target = normalizeText(value.target) || normalizeText(value.name)
    const type = normalizeText(value.type) || relationDetailToType(normalizeText(value.detail))
    const description = normalizeText(value.description)
    const detail = buildRelationDetail({ type, description, detail: normalizeText(value.detail) })
    return target && (type || detail)
      ? [{ target, type: type || relationDetailToType(detail), description: description || undefined, detail: detail || undefined }]
      : []
  }

  if ([...PAYLOAD_KEYS].some((key) => key in value)) {
    const items = Array.isArray(value.items) ? parseCharacterRelations(value.items) : []
    if (items.length > 0) {
      return items
    }
    const text = normalizeText(value.text)
    return text ? parseRawRelationText(text) : []
  }

  const items: CharacterRelationItem[] = []
  Object.entries(value).forEach(([target, rawRelation]) => {
    if (isRecord(rawRelation)) {
      const type = normalizeText(rawRelation.type) || normalizeText(rawRelation.relation_type)
      const description = normalizeText(rawRelation.description) || normalizeText(rawRelation.detail)
      const detail = buildRelationDetail({ type, description })
      if (target && (type || detail)) {
        items.push({
          target,
          type: type || relationDetailToType(detail),
          description: description || undefined,
          detail: detail || undefined,
        })
      }
      return
    }

    const detail = normalizeText(rawRelation)
    const type = relationDetailToType(detail)
    if (target && type) {
      items.push({ target, type, detail })
    }
  })
  return items
}

export const buildCharacterRelationsPayload = (
  items: CharacterRelationItem[],
): CharacterRelationsPayload | null => {
  const normalizedItems: CharacterRelationItem[] = []
  items.forEach((item) => {
    const target = normalizeText(item.target)
    const type = normalizeText(item.type)
    const description = normalizeText(item.description)
    const detail = buildRelationDetail(item)
    if (!target || !(type || detail)) {
      return
    }
    normalizedItems.push({
      target,
      type: type || relationDetailToType(detail),
      description: description || undefined,
      detail: detail || undefined,
    })
  })

  if (normalizedItems.length === 0) {
    return null
  }

  const text = normalizedItems
    .map((item) => `${item.target}：${item.detail || item.type}`)
    .join('；')
  const currentSummary = normalizedItems
    .slice(0, 5)
    .map((item) => `${item.target}：${item.type}`)
    .join('；')

  return {
    version: 2,
    text,
    current_summary: currentSummary,
    items: normalizedItems,
  }
}
