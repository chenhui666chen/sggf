import type { TtsModel } from './types'

export const DEFAULT_TTS_MODEL: TtsModel = 'qwen3-tts-instruct-flash'

export const TTS_MODELS: readonly TtsModel[] = [
  'qwen3-tts-instruct-flash',
  'cosyvoice-v3.5-plus',
  'minimax-speech-2.8-hd',
  'minimax-speech-2.8-turbo',
  'mimo-v2.5-tts',
  'mimo-v2.5-tts-voicedesign',
  'mimo-v2.5-tts-voiceclone',
  'stepaudio-2.5-tts',
  'seed-tts-2.0-expressive',
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
  modelFamily: string
  styleControlModes: string[]
  preferredStyleControlMode: string
  supportsVoiceDescription: boolean
  supportsDirectorMode: boolean
  supportsAudioTags: boolean
  supportsEmotionMixing: boolean
  supportsMicroTags: boolean
  supportsWordLevelControl: boolean
  instructionBudget?: number | null
  controlMessageRoles: Record<string, string>
}

export const DEFAULT_NARRATOR_BY_MODEL: Record<string, string> = {
  'qwen3-tts-instruct-flash': 'Neil',
  'cosyvoice-v3.5-plus': '',
  'minimax-speech-2.8-hd': 'male-qn-qingse',
  'minimax-speech-2.8-turbo': 'male-qn-qingse',
  'mimo-v2.5-tts': 'mimo_default',
  'mimo-v2.5-tts-voicedesign': '',
  'mimo-v2.5-tts-voiceclone': '',
  'stepaudio-2.5-tts': 'cixingnansheng',
  'seed-tts-2.0-expressive': 'zh_female_vv_uranus_bigtts',
}

export const TTS_MODEL_LABELS: Record<string, string> = {
  'qwen3-tts-instruct-flash': 'Qwen3-TTS Instruct Flash',
  'cosyvoice-v3.5-plus': 'CosyVoice v3.5-plus',
  'minimax-speech-2.8-hd': 'MiniMax HD',
  'minimax-speech-2.8-turbo': 'MiniMax Turbo',
  'mimo-v2.5-tts': 'MiMo V2.5 TTS',
  'mimo-v2.5-tts-voicedesign': 'MiMo Voice Design',
  'mimo-v2.5-tts-voiceclone': 'MiMo Voice Clone',
  'stepaudio-2.5-tts': 'StepAudio 2.5 TTS',
  'seed-tts-2.0-expressive': 'Doubao Seed-TTS 2.0 Expressive',
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
  'mimo-v2.5-tts': 'mimo-v2.5-tts',
  'mimo/v2.5-tts': 'mimo-v2.5-tts',
  'mimo-v2.5-tts-voicedesign': 'mimo-v2.5-tts-voicedesign',
  'mimo-v2.5-tts-voice-design': 'mimo-v2.5-tts-voicedesign',
  'mimo/v2.5-tts-voicedesign': 'mimo-v2.5-tts-voicedesign',
  'mimo/v2.5-tts-voice-design': 'mimo-v2.5-tts-voicedesign',
  'mimo-v2.5-tts-voiceclone': 'mimo-v2.5-tts-voiceclone',
  'mimo-v2.5-tts-voice-clone': 'mimo-v2.5-tts-voiceclone',
  'mimo/v2.5-tts-voiceclone': 'mimo-v2.5-tts-voiceclone',
  'mimo/v2.5-tts-voice-clone': 'mimo-v2.5-tts-voiceclone',
  'stepaudio-2.5-tts': 'stepaudio-2.5-tts',
  stepaudio_2_5_tts: 'stepaudio-2.5-tts',
  'stepfun/stepaudio-2.5-tts': 'stepaudio-2.5-tts',
  'stepfun/stepaudio_2_5_tts': 'stepaudio-2.5-tts',
  'seed-tts-2.0-expressive': 'seed-tts-2.0-expressive',
  seed_tts_2_0_expressive: 'seed-tts-2.0-expressive',
  'doubao/seed-tts-2.0-expressive': 'seed-tts-2.0-expressive',
  'doubao/seed_tts_2_0_expressive': 'seed-tts-2.0-expressive',
  'doubao-tts-2.0-expressive': 'seed-tts-2.0-expressive',
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
    modelFamily: 'qwen',
    styleControlModes: ['natural_language'],
    preferredStyleControlMode: 'natural_language',
    supportsVoiceDescription: true,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: false,
    supportsMicroTags: false,
    supportsWordLevelControl: false,
    instructionBudget: 600,
    controlMessageRoles: { natural_language: 'parameters.instructions' },
  },
  'cosyvoice-v3.5-plus': {
    hasSystemVoices: false,
    requiresCustomVoice: true,
    supportsVoiceClone: true,
    supportsVoiceDesign: true,
    supportsVoiceTuning: true,
    modelFamily: 'cosyvoice',
    styleControlModes: ['natural_language'],
    preferredStyleControlMode: 'natural_language',
    supportsVoiceDescription: true,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: false,
    supportsMicroTags: false,
    supportsWordLevelControl: false,
    instructionBudget: 100,
    controlMessageRoles: { natural_language: 'parameters.instruction' },
  },
  'minimax-speech-2.8-hd': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: true,
    supportsVoiceDesign: false,
    supportsVoiceTuning: false,
    modelFamily: 'minimax',
    styleControlModes: ['basic'],
    preferredStyleControlMode: 'basic',
    supportsVoiceDescription: false,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: false,
    supportsMicroTags: false,
    supportsWordLevelControl: false,
    instructionBudget: null,
    controlMessageRoles: {},
  },
  'minimax-speech-2.8-turbo': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: true,
    supportsVoiceDesign: false,
    supportsVoiceTuning: false,
    modelFamily: 'minimax',
    styleControlModes: ['basic'],
    preferredStyleControlMode: 'basic',
    supportsVoiceDescription: false,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: false,
    supportsMicroTags: false,
    supportsWordLevelControl: false,
    instructionBudget: null,
    controlMessageRoles: {},
  },
  'mimo-v2.5-tts': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: false,
    supportsVoiceDesign: false,
    supportsVoiceTuning: true,
    modelFamily: 'mimo',
    styleControlModes: ['director', 'audio_tags', 'natural_language'],
    preferredStyleControlMode: 'director',
    supportsVoiceDescription: true,
    supportsDirectorMode: true,
    supportsAudioTags: true,
    supportsEmotionMixing: true,
    supportsMicroTags: true,
    supportsWordLevelControl: true,
    instructionBudget: null,
    controlMessageRoles: {
      director: 'user',
      audio_tags: 'assistant',
      natural_language: 'user',
    },
  },
  'mimo-v2.5-tts-voicedesign': {
    hasSystemVoices: false,
    requiresCustomVoice: true,
    supportsVoiceClone: false,
    supportsVoiceDesign: true,
    supportsVoiceTuning: true,
    modelFamily: 'mimo',
    styleControlModes: ['voice_design', 'natural_language'],
    preferredStyleControlMode: 'voice_design',
    supportsVoiceDescription: true,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: true,
    supportsMicroTags: false,
    supportsWordLevelControl: false,
    instructionBudget: null,
    controlMessageRoles: {
      voice_design: 'user',
      natural_language: 'user',
    },
  },
  'mimo-v2.5-tts-voiceclone': {
    hasSystemVoices: false,
    requiresCustomVoice: true,
    supportsVoiceClone: true,
    supportsVoiceDesign: false,
    supportsVoiceTuning: true,
    modelFamily: 'mimo',
    styleControlModes: ['director', 'audio_tags', 'natural_language'],
    preferredStyleControlMode: 'director',
    supportsVoiceDescription: true,
    supportsDirectorMode: true,
    supportsAudioTags: true,
    supportsEmotionMixing: true,
    supportsMicroTags: true,
    supportsWordLevelControl: true,
    instructionBudget: null,
    controlMessageRoles: {
      director: 'user',
      audio_tags: 'assistant',
      natural_language: 'user',
      voice_clone: 'audio.voice',
    },
  },
  'stepaudio-2.5-tts': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: true,
    supportsVoiceDesign: false,
    supportsVoiceTuning: true,
    modelFamily: 'stepaudio',
    styleControlModes: ['global_context', 'inline_context', 'natural_language'],
    preferredStyleControlMode: 'global_context',
    supportsVoiceDescription: true,
    supportsDirectorMode: false,
    supportsAudioTags: false,
    supportsEmotionMixing: true,
    supportsMicroTags: true,
    supportsWordLevelControl: true,
    instructionBudget: 200,
    controlMessageRoles: {
      global_context: 'parameters.instruction',
      inline_context: 'input.parentheses',
      natural_language: 'parameters.instruction',
    },
  },
  'seed-tts-2.0-expressive': {
    hasSystemVoices: true,
    requiresCustomVoice: false,
    supportsVoiceClone: true,
    supportsVoiceDesign: false,
    supportsVoiceTuning: true,
    modelFamily: 'doubao',
    styleControlModes: ['query_response', 'audio_tags', 'natural_language'],
    preferredStyleControlMode: 'query_response',
    supportsVoiceDescription: true,
    supportsDirectorMode: false,
    supportsAudioTags: true,
    supportsEmotionMixing: true,
    supportsMicroTags: true,
    supportsWordLevelControl: true,
    instructionBudget: null,
    controlMessageRoles: {
      query_response: 'req_params.additions.context_texts',
      audio_tags: 'req_params.text + req_params.use_tag_parser',
      natural_language: 'req_params.additions.context_texts',
    },
  },
}

const getFallbackTtsModelCapabilities = (model: TtsModel): TtsModelCapabilities => ({
  hasSystemVoices: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.hasSystemVoices ?? true,
  requiresCustomVoice: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.requiresCustomVoice ?? false,
  supportsVoiceClone: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceClone ?? false,
  supportsVoiceDesign: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceDesign ?? false,
  supportsVoiceTuning: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceTuning ?? false,
  modelFamily: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.modelFamily ?? 'generic',
  styleControlModes: [...(FALLBACK_TTS_MODEL_CAPABILITIES[model]?.styleControlModes ?? ['natural_language'])],
  preferredStyleControlMode:
    FALLBACK_TTS_MODEL_CAPABILITIES[model]?.preferredStyleControlMode ?? 'natural_language',
  supportsVoiceDescription: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsVoiceDescription ?? true,
  supportsDirectorMode: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsDirectorMode ?? false,
  supportsAudioTags: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsAudioTags ?? false,
  supportsEmotionMixing: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsEmotionMixing ?? false,
  supportsMicroTags: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsMicroTags ?? false,
  supportsWordLevelControl: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.supportsWordLevelControl ?? false,
  instructionBudget: FALLBACK_TTS_MODEL_CAPABILITIES[model]?.instructionBudget ?? null,
  controlMessageRoles: { ...(FALLBACK_TTS_MODEL_CAPABILITIES[model]?.controlMessageRoles ?? {}) },
})

const normalizeStringArray = (value: unknown, fallback: string[]): string[] => {
  if (!Array.isArray(value)) {
    return [...fallback]
  }
  const seen = new Set<string>()
  return value.flatMap((item): string[] => {
    if (typeof item !== 'string') {
      return []
    }
    const normalized = item.trim()
    if (!normalized || seen.has(normalized)) {
      return []
    }
    seen.add(normalized)
    return [normalized]
  })
}

const normalizeStringRecord = (value: unknown, fallback: Record<string, string>): Record<string, string> => {
  if (!value || typeof value !== 'object') {
    return { ...fallback }
  }
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => {
    if (typeof item !== 'string' || !key.trim() || !item.trim()) {
      return []
    }
    return [[key.trim(), item.trim()]]
  }))
}

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
    modelFamily: typeof raw.model_family === 'string' && raw.model_family.trim()
      ? raw.model_family.trim()
      : fallback.modelFamily,
    styleControlModes: normalizeStringArray(raw.style_control_modes, fallback.styleControlModes),
    preferredStyleControlMode:
      typeof raw.preferred_style_control_mode === 'string' && raw.preferred_style_control_mode.trim()
        ? raw.preferred_style_control_mode.trim()
        : fallback.preferredStyleControlMode,
    supportsVoiceDescription: typeof raw.supports_voice_description === 'boolean'
      ? raw.supports_voice_description
      : fallback.supportsVoiceDescription,
    supportsDirectorMode: typeof raw.supports_director_mode === 'boolean'
      ? raw.supports_director_mode
      : fallback.supportsDirectorMode,
    supportsAudioTags: typeof raw.supports_audio_tags === 'boolean'
      ? raw.supports_audio_tags
      : fallback.supportsAudioTags,
    supportsEmotionMixing: typeof raw.supports_emotion_mixing === 'boolean'
      ? raw.supports_emotion_mixing
      : fallback.supportsEmotionMixing,
    supportsMicroTags: typeof raw.supports_micro_tags === 'boolean'
      ? raw.supports_micro_tags
      : fallback.supportsMicroTags,
    supportsWordLevelControl: typeof raw.supports_word_level_control === 'boolean'
      ? raw.supports_word_level_control
      : fallback.supportsWordLevelControl,
    instructionBudget: typeof raw.instruction_budget === 'number' && Number.isFinite(raw.instruction_budget)
      ? raw.instruction_budget
      : raw.instruction_budget === null
        ? null
        : fallback.instructionBudget,
    controlMessageRoles: normalizeStringRecord(raw.control_message_roles, fallback.controlMessageRoles),
  }
}

export const getDefaultNarratorId = (model: TtsModel): string =>
  DEFAULT_NARRATOR_BY_MODEL[model] || (
    model === 'cosyvoice-v3.5-plus'
    || model === 'mimo-v2.5-tts-voicedesign'
    || model === 'mimo-v2.5-tts-voiceclone'
      ? ''
      : 'Neil'
  )

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

const INSTRUCT_STYLE_CONTROL_MODES = new Set([
  'audio_tags',
  'director',
  'global_context',
  'inline_context',
  'natural_language',
  'query_response',
  'voice_design',
])

const BASIC_NUMERIC_SPEED_MODELS = new Set<TtsModel>([
  'minimax-speech-2.8-hd',
  'minimax-speech-2.8-turbo',
])

export const modelSupportsInstructStyleControl = (
  model: unknown,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => {
  const normalized = normalizeTtsModelValue(model)
  if (!normalized) {
    return false
  }
  const remoteCapabilities = findTtsModelOption(normalized, modelOptions)?.capabilities
  const fallbackCapabilities = FALLBACK_TTS_MODEL_CAPABILITIES[normalized]
  const modes = remoteCapabilities?.styleControlModes || fallbackCapabilities?.styleControlModes || []
  return modes.some((mode) => INSTRUCT_STYLE_CONTROL_MODES.has(mode))
}

export const modelUsesBasicNumericSpeedControl = (model: unknown): boolean => {
  const normalized = normalizeTtsModelValue(model)
  return Boolean(normalized && BASIC_NUMERIC_SPEED_MODELS.has(normalized))
}

export const modelRequiresCustomVoice = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => getTtsModelCapabilities(model, modelOptions).requiresCustomVoice

export const modelSupportsCustomVoiceWorkbench = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => {
  const capabilities = getTtsModelCapabilities(model, modelOptions)
  const supportedWorkbenchModel = model === 'cosyvoice-v3.5-plus'
    || model === 'minimax-speech-2.8-hd'
    || model === 'minimax-speech-2.8-turbo'
  return supportedWorkbenchModel
    && (capabilities.supportsVoiceClone || capabilities.supportsVoiceDesign)
}

export const modelUsesInlineCustomVoiceInput = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => {
  const capabilities = getTtsModelCapabilities(model, modelOptions)
  return capabilities.modelFamily === 'mimo'
    && model === 'mimo-v2.5-tts-voiceclone'
}

export const modelSupportsVoiceTuning = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): boolean => getTtsModelCapabilities(model, modelOptions).supportsVoiceTuning

const STYLE_CONTROL_MODE_LABELS: Record<string, string> = {
  natural_language: '自然语言指令',
  voice_design: '音色设计',
  director: '导演模式',
  audio_tags: '音频标签',
  global_context: '全局语境',
  inline_context: '文中语境',
  query_response: '对话式TTS',
  basic: '基础参数',
}

export const getTtsStyleControlLabels = (
  model: TtsModel,
  modelOptions: readonly TtsModelOption[] = [],
): string[] => {
  const capabilities = getTtsModelCapabilities(model, modelOptions)
  const seen = new Set<string>()
  return capabilities.styleControlModes.flatMap((mode): string[] => {
    const label = STYLE_CONTROL_MODE_LABELS[mode] || mode
    if (!label || seen.has(label)) {
      return []
    }
    seen.add(label)
    return [label]
  })
}

const QWEN_FLASH_ONLY_TO_INSTRUCT: Record<string, string> = {
  Aiden: 'Ethan',
  Alek: 'Elias',
  Andre: 'Neil',
  Bodega: 'Ethan',
  Dolce: 'Vincent',
  Dylan: 'Ethan',
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

// 克隆/自定义音色前缀：这些音色由用户专门创建，不在任何预设列表中，
// 不应被 validVoiceIds 校验或 getFallbackVoiceId 覆盖为硬编码默认值。
const CLONE_VOICE_PREFIXES = [
  'voice_clone_',
  'mmx_',
  'mimo_design:',
  'mimo_clone:',
  'stepaudio_clone:',
  'cosyvoice-v3.5-plus-',
  'cosyvoice-v3-plus-',
] as const

export const isCloneVoiceId = (voiceId?: string | null): boolean => {
  const value = typeof voiceId === 'string' ? voiceId.trim() : ''
  return value !== '' && CLONE_VOICE_PREFIXES.some((prefix) => value.startsWith(prefix))
}

export const normalizeVoiceId = (
  model: TtsModel,
  voiceId?: string | null,
  validVoiceIds?: readonly string[] | Set<string>,
): string => {
  if (!voiceId) return ''

  let normalizedVoiceId = voiceId

  if (model === 'qwen3-tts-instruct-flash') {
    normalizedVoiceId = LEGACY_VOICE_ALIASES[voiceId] || voiceId
    normalizedVoiceId = QWEN_FLASH_ONLY_TO_INSTRUCT[normalizedVoiceId] || normalizedVoiceId
  } else if (model === 'cosyvoice-v3.5-plus') {
    normalizedVoiceId = COSYVOICE_V3_PLUS_LEGACY_ALIASES[voiceId] || voiceId
    if (LEGACY_COSYVOICE_SYSTEM_VOICES.has(normalizedVoiceId)) {
      return ''
    }
  }

  // 克隆/自定义音色由用户专门创建，不在任何预设列表中，跳过目录校验
  if (validVoiceIds && !isCloneVoiceId(normalizedVoiceId)) {
    const validVoiceIdSet: Set<string> =
      validVoiceIds instanceof Set ? validVoiceIds : new Set(validVoiceIds)
    const isValid = validVoiceIdSet.has(normalizedVoiceId)

    if (!isValid) {
      // 音色不在有效列表中,返回空字符串让前端使用默认值
      console.warn(
        `[ttsModels] Voice ID "${normalizedVoiceId}" is not valid for model "${model}". ` +
        `Resetting to default.`
      )
      return ''
    }
  }

  return normalizedVoiceId
}
