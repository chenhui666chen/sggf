import type { TtsModel } from './types'

export const DEFAULT_TTS_MODEL: TtsModel = 'qwen3-tts-instruct-flash'

export const TTS_MODELS: readonly TtsModel[] = [
  'qwen3-tts-instruct-flash',
  'cosyvoice-v3.5-plus',
  'minimax-speech-2.8-hd',
  'minimax-speech-2.8-turbo',
] as const

export interface TtsModelOption {
  id: TtsModel
  name: string
  description?: string
  voiceCount?: number
  pricePer10k?: number
  features: string[]
  costLevel?: string
  qualityLevel?: string
  catalogNote?: string
  catalogStatus?: string
  catalogError?: string
  runtimeModelId?: string
  runtimeStatus?: string
  runtimeError?: string
  capabilities: TtsModelCapabilities
  source: 'remote' | 'fallback'
}

export interface TtsModelCapabilities {
  hasSystemVoices: boolean
  requiresCustomVoice: boolean
  supportsVoiceClone: boolean
  supportsVoiceDesign: boolean
  supportsVoiceTuning: boolean
}

export const DEFAULT_NARRATOR_BY_MODEL: Record<string, string> = {
  'qwen3-tts-instruct-flash': 'Neil',
  'cosyvoice-v3.5-plus': '',
  'minimax-speech-2.8-hd': 'male-qn-qingse',
  'minimax-speech-2.8-turbo': 'male-qn-qingse',
}

export const TTS_MODEL_LABELS: Record<string, string> = {
  'qwen3-tts-instruct-flash': 'Qwen3-TTS Instruct Flash',
  'cosyvoice-v3.5-plus': 'CosyVoice v3.5-plus',
  'minimax-speech-2.8-hd': 'MiniMax HD',
  'minimax-speech-2.8-turbo': 'MiniMax Turbo',
}

const TTS_MODEL_ALIASES: Record<string, TtsModel> = {
  qwen3_tts: 'qwen3-tts-instruct-flash',
  'qwen3-tts': 'qwen3-tts-instruct-flash',
  'qwen3-tts-flash': 'qwen3-tts-instruct-flash',
  'qwen3-tts-instruct': 'qwen3-tts-instruct-flash',
  'qwen3-tts-instruct-flash': 'qwen3-tts-instruct-flash',
  'qwen3-tts-plus': 'qwen3-tts-instruct-flash',
  'cosyvoice-v3-plus': 'cosyvoice-v3.5-plus',
  cosyvoice_v3_plus: 'cosyvoice-v3.5-plus',
  'cosyvoice-v3.5-plus': 'cosyvoice-v3.5-plus',
  'minimax-speech-2.8': 'minimax-speech-2.8-hd',
  'minimax-speech-2.8-hd': 'minimax-speech-2.8-hd',
  'minimax-speech-2.8-turbo': 'minimax-speech-2.8-turbo',
  'minimax/speech-2.8': 'minimax-speech-2.8-hd',
  'minimax/speech-2.8-hd': 'minimax-speech-2.8-hd',
  'minimax/speech-2.8-turbo': 'minimax-speech-2.8-turbo',
}

export const isTtsModel = (value: unknown): value is TtsModel =>
  typeof value === 'string' && Boolean(value.trim())

export const normalizeTtsModelValue = (value: unknown): TtsModel | null => {
  if (typeof value !== 'string') {
    return null
  }
  const normalized = value.trim().toLowerCase()
  if (!normalized) {
    return null
  }
  return TTS_MODEL_ALIASES[normalized] || normalized
}

export const getTtsModelLabel = (model: TtsModel) => TTS_MODEL_LABELS[model] || model

const FALLBACK_TTS_MODEL_CAPABILITIES: Record<string, TtsModelCapabilities> = {
  'qwen3-tts-instruct-flash': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: false,
    supportsVoiceDesign: false,
    supportsVoiceTuning: false,
  },
  'cosyvoice-v3.5-plus': {
    hasSystemVoices: false,
    requiresCustomVoice: true,
    supportsVoiceClone: true,
    supportsVoiceDesign: true,
    supportsVoiceTuning: true,
  },
  'minimax-speech-2.8-hd': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: false,
    supportsVoiceDesign: false,
    supportsVoiceTuning: false,
  },
  'minimax-speech-2.8-turbo': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: false,
    supportsVoiceDesign: false,
    supportsVoiceTuning: false,
  },
}

const getFallbackTtsModelCapabilities = (model: TtsModel): TtsModelCapabilities => ({
  hasSystemVoices: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.hasSystemVoices ?? true,
  requiresCustomVoice: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.requiresCustomVoice ?? false,
  supportsVoiceClone: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceClone ?? false,
  supportsVoiceDesign: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceDesign ?? false,
  supportsVoiceTuning: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceTuning ?? false,
})

const normalizeTtsModelCapabilities = (
  model: TtsModel,
  value: unknown,
): TtsModelCapabilities => {
  const fallback = getFallbackTtsModelCapabilities(model)
  if (!value || typeof value !== 'object') {
    return fallback
  }

  const raw = value as Record<string, unknown>
  return {
    hasSystemVoices: typeof raw.has_system_voices === 'boolean'
      ? raw.has_system_voices
      : fallback.hasSystemVoices,
    requiresCustomVoice: typeof raw.requires_custom_voice === 'boolean'
      ? raw.requires_custom_voice
      : fallback.requiresCustomVoice,
    supportsVoiceClone: typeof raw.supports_voice_clone === 'boolean'
      ? raw.supports_voice_clone
      : fallback.supportsVoiceClone,
    supportsVoiceDesign: typeof raw.supports_voice_design === 'boolean'
      ? raw.supports_voice_design
      : fallback.supportsVoiceDesign,
    supportsVoiceTuning: typeof raw.supports_voice_tuning === 'boolean'
      ? raw.supports_voice_tuning
      : fallback.supportsVoiceTuning,
  }
}

export const getDefaultNarratorId = (model: TtsModel): string =>
  DEFAULT_NARRATOR_BY_MODEL[model] || (model === 'cosyvoice-v3.5-plus' ? '' : 'Neil')

export const getFallbackVoiceId = (
  model: TtsModel,
  presets: Array<{ id: string }> = [],
): string => {
  if (model === 'cosyvoice-v3.5-plus') {
    return presets.find((preset) => Boolean(preset.id))?.id || ''
  }
  const defaultNarratorId = getDefaultNarratorId(model)
  if (presets.some((preset) => preset.id === defaultNarratorId)) {
    return defaultNarratorId
  }
  return presets.find((preset) => Boolean(preset.id))?.id || defaultNarratorId
}

export const createTtsModelRecord = <T>(createValue: (model: TtsModel) => T): Record<TtsModel, T> =>
  TTS_MODELS.reduce((acc, model) => {
    acc[model] = createValue(model)
    return acc
  }, {} as Record<TtsModel, T>)

export const FALLBACK_TTS_MODEL_OPTIONS: readonly TtsModelOption[] = TTS_MODELS.map((model) => ({
  id: model,
  name: getTtsModelLabel(model),
  description: '',
  features: [],
  capabilities: getFallbackTtsModelCapabilities(model),
  source: 'fallback',
}))

const normalizeTtsModelOption = (item: unknown): TtsModelOption | null => {
  if (!item || typeof item !== 'object') {
    return null
  }

  const rawItem = item as Record<string, unknown>
  const id = normalizeTtsModelValue(rawItem.id)
  if (!id) {
    return null
  }

  const rawFeatures = Array.isArray(rawItem.features) ? rawItem.features : []
  const voiceCount = typeof rawItem.voice_count === 'number' && Number.isFinite(rawItem.voice_count)
    ? rawItem.voice_count
    : undefined
  const pricePer10k = typeof rawItem.price_per_10k === 'number' && Number.isFinite(rawItem.price_per_10k)
    ? rawItem.price_per_10k
    : undefined
  const costLevel = typeof rawItem.cost_level === 'string' && rawItem.cost_level.trim()
    ? rawItem.cost_level.trim()
    : undefined
  const qualityLevel = typeof rawItem.quality_level === 'string' && rawItem.quality_level.trim()
    ? rawItem.quality_level.trim()
    : undefined
  const catalogNote = typeof rawItem.catalog_note === 'string' && rawItem.catalog_note.trim()
    ? rawItem.catalog_note.trim()
    : undefined
  const catalogStatus = typeof rawItem.catalog_status === 'string' && rawItem.catalog_status.trim()
    ? rawItem.catalog_status.trim()
    : undefined
  const catalogError = typeof rawItem.catalog_error === 'string' && rawItem.catalog_error.trim()
    ? rawItem.catalog_error.trim()
    : undefined
  const runtimeModelId = typeof rawItem.runtime_model_id === 'string' && rawItem.runtime_model_id.trim()
    ? rawItem.runtime_model_id.trim()
    : undefined
  const runtimeStatus = typeof rawItem.runtime_status === 'string' && rawItem.runtime_status.trim()
    ? rawItem.runtime_status.trim()
    : undefined
  const runtimeError = typeof rawItem.runtime_error === 'string' && rawItem.runtime_error.trim()
    ? rawItem.runtime_error.trim()
    : undefined

  return {
    id,
    name: typeof rawItem.name === 'string' && rawItem.name.trim()
      ? rawItem.name.trim()
      : getTtsModelLabel(id),
    description: typeof rawItem.description === 'string' && rawItem.description.trim()
      ? rawItem.description.trim()
      : undefined,
    voiceCount,
    pricePer10k,
    features: rawFeatures.filter((feature): feature is string =>
      typeof feature === 'string' && Boolean(feature.trim()),
    ),
    costLevel,
    qualityLevel,
    catalogNote,
    catalogStatus,
    catalogError,
    runtimeModelId,
    runtimeStatus,
    runtimeError,
    capabilities: normalizeTtsModelCapabilities(id, rawItem.capabilities),
    source: 'remote',
  }
}

export const mergeTtsModelOptions = (
  modelOptions: readonly TtsModelOption[],
  extraModels: readonly TtsModel[] = [],
): TtsModelOption[] => {
  const optionMap = new Map<TtsModel, TtsModelOption>()

  for (const option of [...modelOptions, ...FALLBACK_TTS_MODEL_OPTIONS]) {
    if (!optionMap.has(option.id)) {
      optionMap.set(option.id, option)
    }
  }

  for (const model of extraModels) {
    const normalized = normalizeTtsModelValue(model)
    if (normalized && !optionMap.has(normalized)) {
      optionMap.set(normalized, {
        id: normalized,
        name: getTtsModelLabel(normalized),
        description: '',
        features: [],
        capabilities: getFallbackTtsModelCapabilities(normalized),
        source: 'fallback',
      })
    }
  }

  return Array.from(optionMap.values())
}

export const normalizeTtsModelOptions = (payload: unknown): readonly TtsModelOption[] => {
  const rawModels = payload && typeof payload === 'object'
    ? (payload as { models?: unknown }).models
    : null
  if (!Array.isArray(rawModels)) {
    return FALLBACK_TTS_MODEL_OPTIONS
  }

  const normalized = rawModels.flatMap((item): TtsModelOption[] => {
    const option = normalizeTtsModelOption(item)
    return option ? [option] : []
  })

  return normalized.length ? mergeTtsModelOptions(normalized) : FALLBACK_TTS_MODEL_OPTIONS
}

export const findTtsModelOption = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): TtsModelOption | null => modelOptions.find((option) => option.id === model) || null

export const getTtsModelCapabilities = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): TtsModelCapabilities => findTtsModelOption(model, modelOptions)?.capabilities
  || getFallbackTtsModelCapabilities(model)

export const modelRequiresCustomVoice = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => getTtsModelCapabilities(model, modelOptions).requiresCustomVoice

export const modelSupportsCustomVoiceWorkbench = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => {
  const capabilities = getTtsModelCapabilities(model, modelOptions)
  return capabilities.supportsVoiceClone || capabilities.supportsVoiceDesign
}

export const modelSupportsVoiceTuning = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => getTtsModelCapabilities(model, modelOptions).supportsVoiceTuning

const QWEN_FLASH_ONLY_TO_INSTRUCT: Record<string, string> = {
  Aiden: 'Ethan',
  Alek: 'Elias',
  Andre: 'Neil',
  Bodega: 'Ethan',
  Dolce: 'Vincent',
  Dylan: 'Ethan',
  Ebona: 'Bellona',
  Emilien: 'Ethan',
  Eric: 'Nofish',
  Jada: 'Mia',
  Jennifer: 'Bellona',
  Katerina: 'Vivian',
  Kiki: 'Nini',
  Lenn: 'Elias',
  Li: 'Vincent',
  Marcus: 'Vincent',
  'Ono Anna': 'Nini',
  Peter: 'Vincent',
  'Radio Gol': 'Ethan',
  Rocky: 'Kai',
  Roy: 'Vincent',
  Ryan: 'Neil',
  Sohee: 'Serena',
  Sonrisa: 'Stella',
  Sunny: 'Mia',
}

const LEGACY_VOICE_ALIASES: Record<string, string> = {
  male_young_energetic: 'Ethan',
  male_young_gentle: 'Vincent',
  male_adult_calm: 'Neil',
  male_adult_energetic: 'Ethan',
  male_elder_wise: 'Eldric Sage',
  male_warm: 'Vincent',
  male_customer_service: 'Kai',
  male_refreshing: 'Kai',
  male_monkey: 'Nofish',
  male_narrator: 'Neil',
  female_villain_sinister: 'Vivian',
  female_villain_cold: 'Bellona',
  female_villain_cunning: 'Vivian',
  female_young_gentle: 'Cherry',
  female_young_energetic: 'Bunny',
  female_young_cute: 'Momo',
  female_adult_elegant: 'Bella',
  female_adult_intellectual: 'Vivian',
  female_capable: 'Bellona',
  female_elder: 'Chelsie',
  female_intimate: 'Mochi',
  female_lively: 'Mia',
  female_child: 'Momo',
}

const COSYVOICE_V3_PLUS_LEGACY_ALIASES: Record<string, string> = {
  longanzhi_v3: 'longanyang',
  longanyun_v3: 'longanyang',
  longyichen_v3: 'longanyang',
  longwanjun_v3: 'longanhuan',
  longanwen_v3: 'longanhuan',
}

const LEGACY_COSYVOICE_SYSTEM_VOICES = new Set(['longanyang', 'longanhuan'])

export const normalizeVoiceId = (
  model: TtsModel,
  voiceId?: string | null,
): string => {
  if (!voiceId) return ''

  if (model === 'qwen3-tts-instruct-flash') {
    const normalizedVoiceId = LEGACY_VOICE_ALIASES[voiceId] || voiceId
    return QWEN_FLASH_ONLY_TO_INSTRUCT[normalizedVoiceId] || normalizedVoiceId
  }

  if (model === 'cosyvoice-v3.5-plus') {
    const normalizedVoiceId = COSYVOICE_V3_PLUS_LEGACY_ALIASES[voiceId] || voiceId
    return LEGACY_COSYVOICE_SYSTEM_VOICES.has(normalizedVoiceId) ? '' : normalizedVoiceId
  }

  return voiceId
}
