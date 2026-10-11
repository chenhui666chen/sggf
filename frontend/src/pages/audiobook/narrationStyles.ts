import { TTS_MODELS, normalizeTtsModelValue } from './ttsModels'
import { audiobookColors } from './audiobookTheme'
import type { AudiobookTtsModel } from '../../types/audiobook'

export type KnownNarrationStyleId = 'professional' | 'dramatic' | 'relaxing' | 'expressive' | 'custom'
export type NarrationStyleId = string

export interface NarrationStyleOption {
  id: NarrationStyleId
  name: string
  description: string
  color: string
  supported_models?: readonly AudiobookTtsModel[]
}

export const DEFAULT_NARRATION_STYLE: KnownNarrationStyleId = 'professional'

const ALL_NARRATION_TTS_MODELS = TTS_MODELS
// Qwen 快速档（现 qwen-audio-3.1-tts-flash）只暴露 natural_language 控制，
// 情绪混排类风格仍按能力面排除；3.1 写法测评（B3）给出实测结论后再评估是否放通。
const EXPRESSIVE_NARRATION_TTS_MODELS = TTS_MODELS.filter(
  (model) => model !== 'qwen-audio-3.1-tts-flash',
)

const KNOWN_NARRATION_STYLE_IDS: readonly KnownNarrationStyleId[] = [
  'professional',
  'dramatic',
  'relaxing',
  'expressive',
  'custom',
]

const NARRATION_STYLE_COLORS: Record<KnownNarrationStyleId, string> = {
  professional: audiobookColors.brand,
  dramatic: audiobookColors.reviewWarning,
  relaxing: audiobookColors.successMain,
  expressive: audiobookColors.primary,
  custom: audiobookColors.neutral,
}

export const NARRATION_STYLE_OPTIONS: readonly NarrationStyleOption[] = [
  {
    id: 'professional',
    name: '专业播报',
    description: '标准新闻播报风格，适合严肃题材',
    color: NARRATION_STYLE_COLORS.professional,
    supported_models: ALL_NARRATION_TTS_MODELS,
  },
  {
    id: 'dramatic',
    name: '戏剧表演',
    description: '富有表现力的戏剧化朗读，适合情感丰富的故事',
    color: NARRATION_STYLE_COLORS.dramatic,
    supported_models: EXPRESSIVE_NARRATION_TTS_MODELS,
  },
  {
    id: 'relaxing',
    name: '轻松舒缓',
    description: '温柔舒缓的讲述方式，适合治愈系内容',
    color: NARRATION_STYLE_COLORS.relaxing,
    supported_models: ALL_NARRATION_TTS_MODELS,
  },
  {
    id: 'expressive',
    name: '生动表现',
    description: '活泼生动的表达方式，适合儿童或轻喜剧',
    color: NARRATION_STYLE_COLORS.expressive,
    supported_models: EXPRESSIVE_NARRATION_TTS_MODELS,
  },
  {
    id: 'custom',
    name: '自定义',
    description: '使用自定义提示词控制旁白语气',
    color: NARRATION_STYLE_COLORS.custom,
    supported_models: ALL_NARRATION_TTS_MODELS,
  },
] as const

const LEGACY_NARRATION_STYLE_ALIASES: Record<string, KnownNarrationStyleId> = {
  relaxed: 'relaxing',
  vivid: 'expressive',
}

const NARRATION_STYLE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,63}$/

export const isKnownNarrationStyleId = (value: unknown): value is KnownNarrationStyleId =>
  typeof value === 'string' && KNOWN_NARRATION_STYLE_IDS.includes(value as KnownNarrationStyleId)

export const isNarrationStyleId = (value: unknown): value is NarrationStyleId =>
  typeof value === 'string' && NARRATION_STYLE_ID_PATTERN.test(value)

export const normalizeNarrationStyleValue = (value: unknown): NarrationStyleId => {
  if (typeof value !== 'string') {
    return DEFAULT_NARRATION_STYLE
  }

  const normalizedValue = value.trim().toLowerCase()
  return LEGACY_NARRATION_STYLE_ALIASES[normalizedValue]
    || (isNarrationStyleId(normalizedValue) ? normalizedValue : DEFAULT_NARRATION_STYLE)
}

const getFallbackNarrationStyleOption = (id: NarrationStyleId): NarrationStyleOption =>
  NARRATION_STYLE_OPTIONS.find((style) => style.id === id) || {
    id,
    name: id,
    description: '后端叙事风格',
    color: audiobookColors.neutral,
  }

const normalizeSupportedModels = (value: unknown): readonly AudiobookTtsModel[] | undefined => {
  if (!Array.isArray(value)) {
    return undefined
  }
  const supported = value.flatMap((model): AudiobookTtsModel[] => {
    const normalized = normalizeTtsModelValue(model)
    return normalized ? [normalized] : []
  })
  return supported.length ? supported : undefined
}

export const normalizeNarrationStyleOptions = (raw: unknown): readonly NarrationStyleOption[] => {
  if (!Array.isArray(raw)) {
    return NARRATION_STYLE_OPTIONS
  }

  const normalized = raw.flatMap((item): NarrationStyleOption[] => {
    if (!item || typeof item !== 'object') {
      return []
    }

    const rawItem = item as Record<string, unknown>
    const rawId = typeof rawItem.id === 'string' ? rawItem.id.trim().toLowerCase() : ''
    if (!isNarrationStyleId(rawId)) {
      return []
    }

    const fallback = getFallbackNarrationStyleOption(rawId)
    return [{
      id: rawId,
      name: typeof rawItem.name === 'string' && rawItem.name.trim() ? rawItem.name.trim() : fallback.name,
      description: typeof rawItem.description === 'string' && rawItem.description.trim()
        ? rawItem.description.trim()
        : fallback.description,
      color: typeof rawItem.color === 'string' && rawItem.color.trim()
        ? rawItem.color.trim()
        : isKnownNarrationStyleId(rawId)
          ? NARRATION_STYLE_COLORS[rawId]
          : audiobookColors.neutral,
      supported_models: normalizeSupportedModels(rawItem.supported_models) || fallback.supported_models,
    }]
  })

  return normalized.length ? normalized : NARRATION_STYLE_OPTIONS
}
