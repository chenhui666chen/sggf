import type {
  AudioEngineMode,
  AudioFxConfig,
  CharacterVoiceSetting,
  ProjectAudioConfig,
  ProjectCharacterAudioConfig,
  TtsModel,
  VoicePreset,
} from './types'
import {
  getFallbackVoiceId,
  isCloneVoiceId,
  normalizeTtsModelValue,
  normalizeVoiceId,
} from './ttsModels'

export interface ProjectCharacterSummary {
  id: number
  name: string
  gender?: string | null
  role?: string | null
}

type SavedCharacterAudioConfig = ProjectAudioConfig['characters'][number]

export interface AudiobookVoiceConfigPayloadItem {
  character_name: string
  voice_id: string
  tts_model?: TtsModel | null
  reference_source?: 'user_private' | 'public_pool'
  reference_audio_url?: string
  voice_reference_asset_id?: string
  voice_pool_publication_id?: string
}

export interface ProjectVoiceAssignmentResult {
  characterVoices: CharacterVoiceSetting[]
  assignedCount: number
}

const NARRATOR_CHARACTER_ID = 0
const NARRATOR_NAME = '旁白'

export const createDefaultAudioFxConfig = (): AudioFxConfig => ({
  enable_sound_effects: true,
  enable_music: true,
  sound_effect_density: 'medium',
  music_density: 'medium',
  intelligent_balance: true,
  balance_strategy: 'auto',
})

const AUDIO_FX_DENSITIES = new Set<AudioFxConfig['sound_effect_density']>([
  'low',
  'medium',
  'high',
  'off',
])

const normalizeAudioFxDensity = (
  value: unknown,
): AudioFxConfig['sound_effect_density'] =>
  AUDIO_FX_DENSITIES.has(value as AudioFxConfig['sound_effect_density'])
    ? value as AudioFxConfig['sound_effect_density']
    : 'medium'

export const normalizeProjectAudioFxConfig = (
  savedFx?: AudioFxConfig | null,
): AudioFxConfig => {
  const defaults = createDefaultAudioFxConfig()
  if (!savedFx) {
    return defaults
  }

  return {
    enable_sound_effects: savedFx.enable_sound_effects ?? defaults.enable_sound_effects,
    enable_music: savedFx.enable_music ?? defaults.enable_music,
    sound_effect_density: normalizeAudioFxDensity(savedFx.sound_effect_density),
    music_density: normalizeAudioFxDensity(savedFx.music_density),
    intelligent_balance: true,
    balance_strategy: 'auto',
  }
}

/**
 * 构建旁白默认音色配置。
 *
 * 优先级链：用户显式配置的音色 > 克隆音色 > 模型默认音色 > 系统默认音色。
 * 此函数仅提供最后的系统默认回退值（getFallbackVoiceId），
 * 用户配置的克隆音色在 buildInitialProjectVoiceSettings 中优先恢复。
 */
export const buildBaseNarratorVoice = (
  ttsModel: TtsModel,
  voicePresets: Array<Pick<VoicePreset, 'id'>> = [],
): CharacterVoiceSetting => ({
  characterId: NARRATOR_CHARACTER_ID,
  name: NARRATOR_NAME,
  gender: '中性',
  role: NARRATOR_NAME,
  voiceId: getFallbackVoiceId(ttsModel, voicePresets),
  volume: 50,
  speed: 1.0,
  pitch: 50,
})

const findSavedCharacterConfig = (
  savedCharacters: readonly SavedCharacterAudioConfig[],
  characterId: number,
) => savedCharacters.find((saved) => saved.character_id === characterId)

/**
 * 按引擎分支读取角色配置（GUIDE §2.2 解析侧）。
 *
 * 优先级：engines.{mode}.tts_models.{model}.characters（先精确 key，再
 * 遍历分支内任意模型 key 兜底）→ engines.{mode}.characters（旧分支形态）
 * → 顶层 characters（仅 legacy_stems 旧数据回退，保持向后兼容）。
 */
export const resolveBranchSavedCharacters = (
  config: Partial<Pick<ProjectAudioConfig, 'characters' | 'engines'>> | null | undefined,
  engineMode: AudioEngineMode,
  ttsModel: TtsModel,
): ProjectCharacterAudioConfig[] => {
  const branch = config?.engines?.[engineMode]
  const branchTtsModels = branch?.tts_models
  if (branchTtsModels) {
    const exactMatch = branchTtsModels[ttsModel]?.characters
    if (exactMatch?.length) {
      return exactMatch
    }
    for (const modelConfig of Object.values(branchTtsModels)) {
      const characters = modelConfig?.characters
      if (characters?.length) {
        return characters
      }
    }
  }
  if (branch?.characters?.length) {
    return branch.characters
  }
  if (engineMode === 'legacy_stems' && config?.characters?.length) {
    return config.characters
  }
  return []
}

const findSavedNarratorConfig = (
  savedCharacters: readonly SavedCharacterAudioConfig[],
) => savedCharacters.find(
  (saved) => saved.character_id === NARRATOR_CHARACTER_ID || saved.name === NARRATOR_NAME,
)

const buildSavedCharacterConfigMap = (
  savedCharacters: readonly SavedCharacterAudioConfig[],
  ttsModel: TtsModel,
) => {
  const configById = new Map<
    number,
    {
      voiceId: string
      volume?: number | null
      speed?: number
      pitch?: number
      ttsModel?: TtsModel
      voiceType?: string
      personality?: string
      emotionTendency?: string
      voiceCloneDataUrl?: string
      voiceDesignPrompt?: string
      mimoVoiceAssetId?: string
      stepaudioVoiceAssetId?: string
      referenceSource?: 'user_private' | 'public_pool'
      referenceAudioUrl?: string
      voiceReferenceAssetId?: string
      voicePoolPublicationId?: string
      source?: string | null
    }
  >()

  for (const item of savedCharacters) {
    const itemTtsModel = normalizeTtsModelValue(item.tts_model) || ttsModel
    configById.set(item.character_id, {
      voiceId: normalizeVoiceId(itemTtsModel, item.voice_id),
      volume: item.volume,
      speed: item.speed ?? undefined,
      pitch: item.pitch ?? undefined,
      ttsModel: itemTtsModel,
      voiceType: item.voice_type || undefined,
      personality: item.personality || undefined,
      emotionTendency: item.emotion_tendency || undefined,
      voiceCloneDataUrl: trimOptionalText(item.voice_clone_data_url),
      voiceDesignPrompt: trimOptionalText(item.voice_design_prompt),
      mimoVoiceAssetId: trimOptionalText(item.mimo_voice_asset_id),
      stepaudioVoiceAssetId: trimOptionalText(item.stepaudio_voice_asset_id),
      referenceSource: item.reference_source || undefined,
      referenceAudioUrl: trimOptionalText(item.reference_audio_url),
      voiceReferenceAssetId: trimOptionalText(item.voice_reference_asset_id),
      voicePoolPublicationId: trimOptionalText(item.voice_pool_publication_id),
      source: item.source ?? undefined,
    })
  }

  return configById
}

const isNarratorVoiceSetting = (voice: CharacterVoiceSetting): boolean =>
  voice.characterId === NARRATOR_CHARACTER_ID || voice.name.trim() === NARRATOR_NAME

const trimOptionalText = (value?: string | null): string | undefined => {
  const trimmed = typeof value === 'string' ? value.trim() : ''
  return trimmed || undefined
}

const resolvePayloadVoiceId = (
  voice: CharacterVoiceSetting,
  ttsModel: TtsModel,
  voicePresets: Array<Pick<VoicePreset, 'id'>>,
): string => {
  const explicitVoiceId = voice.voiceId.trim()
  // 用户显式配置的音色（包括克隆音色）优先返回，不触达 getFallbackVoiceId 回退逻辑
  if (explicitVoiceId) {
    return explicitVoiceId
  }
  // 旁白没有显式配置音色时，使用模型默认回退值
  return isNarratorVoiceSetting(voice) ? getFallbackVoiceId(ttsModel, voicePresets) : ''
}

const shouldIncludeVoiceSetting = (voice: CharacterVoiceSetting): boolean =>
  isNarratorVoiceSetting(voice)
  || Boolean(voice.voiceId.trim())

const getEffectiveVoiceModel = (voice: CharacterVoiceSetting, fallbackTtsModel: TtsModel): TtsModel =>
  voice.ttsModel || fallbackTtsModel

const shouldIncludeVoiceSettingForModel = (voice: CharacterVoiceSetting): boolean =>
  shouldIncludeVoiceSetting(voice)

const resolveLegacyVoiceAssetReference = (
  voice: CharacterVoiceSetting,
  fallbackTtsModel: TtsModel,
): string => {
  if (voice.voiceId.trim()) {
    return voice.voiceId.trim()
  }
  const effectiveModel = getEffectiveVoiceModel(voice, fallbackTtsModel)
  const mimoVoiceAssetId = trimOptionalText(voice.mimoVoiceAssetId)
  if (
    mimoVoiceAssetId
    && (effectiveModel === 'mimo-v2.5-tts-voiceclone' || effectiveModel === 'mimo-v2.5-tts-voicedesign')
  ) {
    return effectiveModel === 'mimo-v2.5-tts-voicedesign'
      ? `mimo_design:${mimoVoiceAssetId}`
      : `mimo_clone:${mimoVoiceAssetId}`
  }
  const stepaudioVoiceAssetId = trimOptionalText(voice.stepaudioVoiceAssetId)
  if (stepaudioVoiceAssetId && effectiveModel === 'stepaudio-3-tts') {
    return `stepaudio_clone:${stepaudioVoiceAssetId}`
  }
  return ''
}

export const buildProjectCharacterVoiceSettings = ({
  characters,
  savedCharacters = [],
  ttsModel,
}: {
  characters: readonly ProjectCharacterSummary[]
  savedCharacters?: readonly SavedCharacterAudioConfig[]
  ttsModel: TtsModel
}): CharacterVoiceSetting[] => {
  // 每个角色可能配置了与全局模型不同的 TTS 模型（跨模型音色），此处若用全局模型的
  // 音色目录做合法性校验，会把合法的跨模型音色误判为无效并清空，导致已保存的音色
  // 配置在加载时丢失（固定化失效）。因此加载时不做目录校验，原样保留已保存音色；
  // 渲染层会按各角色自身模型的音色目录进行展示与处理。
  return characters.map((character) => {
    const saved = findSavedCharacterConfig(savedCharacters, character.id)
    const savedTtsModel = normalizeTtsModelValue(saved?.tts_model) || ttsModel
    const savedVoiceId = normalizeVoiceId(savedTtsModel, saved?.voice_id)
    const legacyAssetVoiceId = resolveLegacyVoiceAssetReference({
      characterId: character.id,
      name: character.name,
      voiceId: '',
      volume: 50,
      ttsModel: savedTtsModel,
      mimoVoiceAssetId: trimOptionalText(saved?.mimo_voice_asset_id),
      stepaudioVoiceAssetId: trimOptionalText(saved?.stepaudio_voice_asset_id),
      referenceSource: saved?.reference_source || undefined,
      referenceAudioUrl: trimOptionalText(saved?.reference_audio_url),
      voiceReferenceAssetId: trimOptionalText(saved?.voice_reference_asset_id),
      voicePoolPublicationId: trimOptionalText(saved?.voice_pool_publication_id),
    }, ttsModel)
    return {
      characterId: character.id,
      name: character.name,
      gender: character.gender,
      role: character.role,
      voiceId: savedVoiceId || legacyAssetVoiceId,
      volume: saved?.volume ?? 50,
      speed: saved?.speed ?? 1.0,
      pitch: saved?.pitch ?? 50,
      ttsModel: savedTtsModel,
      voiceType: saved?.voice_type || undefined,
      personality: saved?.personality || undefined,
      emotionTendency: saved?.emotion_tendency || undefined,
      voiceCloneDataUrl: trimOptionalText(saved?.voice_clone_data_url),
      voiceDesignPrompt: trimOptionalText(saved?.voice_design_prompt),
      mimoVoiceAssetId: trimOptionalText(saved?.mimo_voice_asset_id),
      stepaudioVoiceAssetId: trimOptionalText(saved?.stepaudio_voice_asset_id),
      referenceSource: saved?.reference_source || undefined,
      referenceAudioUrl: trimOptionalText(saved?.reference_audio_url),
      voiceReferenceAssetId: trimOptionalText(saved?.voice_reference_asset_id),
      voicePoolPublicationId: trimOptionalText(saved?.voice_pool_publication_id),
      ...(saved?.source ? { source: saved.source } : {}),
    }
  })
}

export const buildInitialProjectVoiceSettings = ({
  characters,
  projectAudioConfig,
  ttsModel,
  voicePresets,
  engineMode,
}: {
  characters: readonly ProjectCharacterSummary[]
  projectAudioConfig?: ProjectAudioConfig | null
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
  // 指定时按引擎分支读取已保存绑定（GUIDE §2.2）；缺省回退顶层 characters
  engineMode?: AudioEngineMode
}): CharacterVoiceSetting[] => {
  const savedCharacters = engineMode
    ? resolveBranchSavedCharacters(projectAudioConfig, engineMode, ttsModel)
    : (projectAudioConfig?.characters || [])
  const baseNarratorVoice = buildBaseNarratorVoice(ttsModel, voicePresets)
  const narratorSaved = findSavedNarratorConfig(savedCharacters)
  // 旁白同样可能配置了与全局模型不同的 TTS 模型（跨模型音色）。此前这里漏掉了
  // 恢复已保存的 tts_model，旁白 ttsModel 为空后重新保存会被全局模型覆盖
  // （buildProjectAudioConfigPayload 的 voice.ttsModel || ttsModel），造成 voice_id
  // 与 tts_model 错配（如 minimax/SeedTTS 音色被按全局模型解析），生成时旁白音色
  // 无法解析而被跳过（固定化失效）。此处与普通角色一致，恢复已保存的 tts_model。
  const narratorSavedTtsModel = normalizeTtsModelValue(narratorSaved?.tts_model) || ttsModel
  // 克隆音色（voice_clone_ / mmx_ 等前缀）是用户专门创建的，应被视为最高优先级。
  // normalizeVoiceId 已对克隆音色跳过目录校验，确保原样保留。
  const savedNarratorVoiceId = normalizeVoiceId(narratorSavedTtsModel, narratorSaved?.voice_id)
  // 额外防御：如果 normalizeVoiceId 返回空但原始值确为克隆音色，直接使用原始值
  const rawSavedVoiceId = typeof narratorSaved?.voice_id === 'string'
    ? narratorSaved.voice_id.trim()
    : ''
  const cloneVoiceFallback = rawSavedVoiceId && isCloneVoiceId(rawSavedVoiceId) ? rawSavedVoiceId : ''
  const narratorVoice: CharacterVoiceSetting = {
    ...baseNarratorVoice,
    ttsModel: narratorSavedTtsModel,
    // 优先级：用户保存的音色（含克隆） > 克隆音色原始值 > 遗留资产引用 > 系统默认回退值
    voiceId: savedNarratorVoiceId
      || cloneVoiceFallback
      || resolveLegacyVoiceAssetReference({
        characterId: NARRATOR_CHARACTER_ID,
        name: NARRATOR_NAME,
        voiceId: '',
        volume: baseNarratorVoice.volume,
        ttsModel: narratorSavedTtsModel,
        mimoVoiceAssetId: trimOptionalText(narratorSaved?.mimo_voice_asset_id),
        stepaudioVoiceAssetId: trimOptionalText(narratorSaved?.stepaudio_voice_asset_id),
      }, ttsModel)
      || baseNarratorVoice.voiceId,
    volume: narratorSaved?.volume ?? baseNarratorVoice.volume,
    speed: narratorSaved?.speed ?? baseNarratorVoice.speed,
    pitch: narratorSaved?.pitch ?? baseNarratorVoice.pitch,
    referenceSource: narratorSaved?.reference_source || undefined,
    referenceAudioUrl: trimOptionalText(narratorSaved?.reference_audio_url),
    voiceReferenceAssetId: trimOptionalText(narratorSaved?.voice_reference_asset_id),
    voicePoolPublicationId: trimOptionalText(narratorSaved?.voice_pool_publication_id),
  }

  return [
    narratorVoice,
    ...buildProjectCharacterVoiceSettings({
      characters,
      savedCharacters,
      ttsModel,
    }),
  ]
}

export const applyProjectVoiceAssignments = ({
  characterVoices,
  savedCharacters,
  ttsModel,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  savedCharacters: readonly SavedCharacterAudioConfig[]
  ttsModel: TtsModel
}): ProjectVoiceAssignmentResult => {
  const configById = buildSavedCharacterConfigMap(savedCharacters, ttsModel)
  let assignedCount = 0
  const nextCharacterVoices = characterVoices.map((voice) => {
    const config = configById.get(voice.characterId)
    if (!config) {
      return voice
    }
    assignedCount += 1
    const legacyAssetVoiceId = resolveLegacyVoiceAssetReference({
      ...voice,
      voiceId: '',
      ttsModel: config.ttsModel ?? voice.ttsModel,
      mimoVoiceAssetId: config.mimoVoiceAssetId ?? voice.mimoVoiceAssetId,
      stepaudioVoiceAssetId: config.stepaudioVoiceAssetId ?? voice.stepaudioVoiceAssetId,
      referenceSource: config.referenceSource ?? voice.referenceSource,
      referenceAudioUrl: config.referenceAudioUrl ?? voice.referenceAudioUrl,
      voiceReferenceAssetId: config.voiceReferenceAssetId ?? voice.voiceReferenceAssetId,
      voicePoolPublicationId: config.voicePoolPublicationId ?? voice.voicePoolPublicationId,
    }, ttsModel)
    return {
      ...voice,
      voiceId: config.voiceId || legacyAssetVoiceId,
      volume: config.volume ?? voice.volume,
      speed: config.speed ?? voice.speed,
      pitch: config.pitch ?? voice.pitch,
      ttsModel: config.ttsModel ?? voice.ttsModel,
      voiceType: config.voiceType ?? voice.voiceType,
      personality: config.personality ?? voice.personality,
      emotionTendency: config.emotionTendency ?? voice.emotionTendency,
      voiceCloneDataUrl: config.voiceCloneDataUrl ?? voice.voiceCloneDataUrl,
      voiceDesignPrompt: config.voiceDesignPrompt ?? voice.voiceDesignPrompt,
      mimoVoiceAssetId: config.mimoVoiceAssetId ?? voice.mimoVoiceAssetId,
      stepaudioVoiceAssetId: config.stepaudioVoiceAssetId ?? voice.stepaudioVoiceAssetId,
      ...((config.source ?? voice.source) ? { source: config.source ?? voice.source } : {}),
    }
  })

  return {
    assignedCount,
    characterVoices: nextCharacterVoices,
  }
}

export const buildProjectAudioConfigPayload = ({
  characterVoices,
  audioFxConfig,
  audioEngineMode,
  ttsModel,
  voicePresets,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  audioEngineMode?: AudioEngineMode
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): ProjectAudioConfig => {
  const characters = characterVoices
    .filter(shouldIncludeVoiceSettingForModel)
    .map((voice) => {
      return {
        character_id: voice.characterId,
        name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
        ...(voice.referenceSource ? { reference_source: voice.referenceSource } : {}),
        ...(voice.referenceAudioUrl ? { reference_audio_url: voice.referenceAudioUrl } : {}),
        ...(voice.voiceReferenceAssetId
          ? { voice_reference_asset_id: voice.voiceReferenceAssetId }
          : {}),
        ...(voice.voicePoolPublicationId
          ? { voice_pool_publication_id: voice.voicePoolPublicationId }
          : {}),
      }
    })
  return {
    // 顶层字段保留用于向后兼容；后端 PUT 在 engines 非空时只落分支（GUIDE §2.2）
    characters,
    audio_fx: audioFxConfig,
    ...(audioEngineMode ? { audio_engine_mode: audioEngineMode } : {}),
    ...(audioEngineMode
      ? {
          engines: {
            [audioEngineMode]: {
              tts_models: {
                [ttsModel]: { characters },
              },
            },
          },
        }
      : {}),
  }
}

export const buildAudiobookVoiceConfigPayload = ({
  characterVoices,
  ttsModel,
  voicePresets,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): AudiobookVoiceConfigPayloadItem[] =>
  characterVoices
    .filter(shouldIncludeVoiceSettingForModel)
    .map((voice) => {
      return {
        character_name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
        ...(voice.referenceSource ? { reference_source: voice.referenceSource } : {}),
        ...(voice.referenceAudioUrl ? { reference_audio_url: voice.referenceAudioUrl } : {}),
        ...(voice.voiceReferenceAssetId
          ? { voice_reference_asset_id: voice.voiceReferenceAssetId }
          : {}),
        ...(voice.voicePoolPublicationId
          ? { voice_pool_publication_id: voice.voicePoolPublicationId }
          : {}),
      }
    })
