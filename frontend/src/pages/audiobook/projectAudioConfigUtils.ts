import type {
  AudioFxConfig,
  CharacterVoiceSetting,
  ProjectAudioConfig,
  TtsModel,
  VoicePreset,
} from './types'
import {
  getFallbackVoiceId,
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
  voice_clone_data_url?: string | null
  voice_design_prompt?: string | null
  mimo_voice_asset_id?: string | null
  stepaudio_voice_asset_id?: string | null
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
  }
}

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
  if (explicitVoiceId) {
    return explicitVoiceId
  }
  return isNarratorVoiceSetting(voice) ? getFallbackVoiceId(ttsModel, voicePresets) : ''
}

const shouldIncludeVoiceSetting = (voice: CharacterVoiceSetting): boolean =>
  isNarratorVoiceSetting(voice)
  || Boolean(voice.voiceId.trim())
  || Boolean(trimOptionalText(voice.voiceCloneDataUrl))
  || Boolean(trimOptionalText(voice.mimoVoiceAssetId))
  || Boolean(trimOptionalText(voice.stepaudioVoiceAssetId))

const getEffectiveVoiceModel = (voice: CharacterVoiceSetting, fallbackTtsModel: TtsModel): TtsModel =>
  voice.ttsModel || fallbackTtsModel

const getPayloadVoiceCloneDataUrl = (
  voice: CharacterVoiceSetting,
  fallbackTtsModel: TtsModel,
): string | undefined =>
  getEffectiveVoiceModel(voice, fallbackTtsModel) === 'mimo-v2.5-tts-voiceclone'
    && !trimOptionalText(voice.mimoVoiceAssetId)
    ? trimOptionalText(voice.voiceCloneDataUrl)
    : undefined

const getPayloadVoiceDesignPrompt = (): string | undefined => undefined

const getPayloadMimoVoiceAssetId = (
  voice: CharacterVoiceSetting,
  fallbackTtsModel: TtsModel,
): string | undefined => {
  const effectiveModel = getEffectiveVoiceModel(voice, fallbackTtsModel)
  if (effectiveModel !== 'mimo-v2.5-tts-voiceclone' && effectiveModel !== 'mimo-v2.5-tts-voicedesign') {
    return undefined
  }
  return trimOptionalText(voice.mimoVoiceAssetId)
}

const getPayloadStepAudioVoiceAssetId = (
  voice: CharacterVoiceSetting,
  fallbackTtsModel: TtsModel,
): string | undefined => {
  const effectiveModel = getEffectiveVoiceModel(voice, fallbackTtsModel)
  if (effectiveModel !== 'stepaudio-2.5-tts') {
    return undefined
  }
  return trimOptionalText(voice.stepaudioVoiceAssetId)
}

const shouldIncludeVoiceSettingForModel = (
  voice: CharacterVoiceSetting,
  fallbackTtsModel: TtsModel,
): boolean =>
  shouldIncludeVoiceSetting(voice)
  && (
    isNarratorVoiceSetting(voice)
    || Boolean(voice.voiceId.trim())
    || Boolean(getPayloadVoiceCloneDataUrl(voice, fallbackTtsModel))
    || Boolean(getPayloadVoiceDesignPrompt())
    || Boolean(getPayloadMimoVoiceAssetId(voice, fallbackTtsModel))
    || Boolean(getPayloadStepAudioVoiceAssetId(voice, fallbackTtsModel))
  )

export const buildProjectCharacterVoiceSettings = ({
  characters,
  savedCharacters = [],
  ttsModel,
  voicePresets = [],
}: {
  characters: readonly ProjectCharacterSummary[]
  savedCharacters?: readonly SavedCharacterAudioConfig[]
  ttsModel: TtsModel
  voicePresets?: Array<Pick<VoicePreset, 'id'>>
}): CharacterVoiceSetting[] => {
  const validVoiceIds = new Set(voicePresets.map((p) => p.id))
  
  return characters.map((character) => {
    const saved = findSavedCharacterConfig(savedCharacters, character.id)
    const savedTtsModel = normalizeTtsModelValue(saved?.tts_model) || ttsModel
    return {
      characterId: character.id,
      name: character.name,
      gender: character.gender,
      role: character.role,
      voiceId: normalizeVoiceId(savedTtsModel, saved?.voice_id, validVoiceIds),
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
      ...(saved?.source ? { source: saved.source } : {}),
    }
  })
}

export const buildInitialProjectVoiceSettings = ({
  characters,
  projectAudioConfig,
  ttsModel,
  voicePresets,
}: {
  characters: readonly ProjectCharacterSummary[]
  projectAudioConfig?: ProjectAudioConfig | null
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): CharacterVoiceSetting[] => {
  const savedCharacters = projectAudioConfig?.characters || []
  const baseNarratorVoice = buildBaseNarratorVoice(ttsModel, voicePresets)
  const narratorSaved = findSavedNarratorConfig(savedCharacters)
  const narratorVoice: CharacterVoiceSetting = {
    ...baseNarratorVoice,
    voiceId: normalizeVoiceId(ttsModel, narratorSaved?.voice_id, new Set(voicePresets.map((p) => p.id))) || baseNarratorVoice.voiceId,
    volume: narratorSaved?.volume ?? baseNarratorVoice.volume,
    speed: narratorSaved?.speed ?? baseNarratorVoice.speed,
    pitch: narratorSaved?.pitch ?? baseNarratorVoice.pitch,
  }

  return [
    narratorVoice,
    ...buildProjectCharacterVoiceSettings({
      characters,
      savedCharacters,
      ttsModel,
      voicePresets,
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
    return {
      ...voice,
      voiceId: config.voiceId,
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
  ttsModel,
  voicePresets,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): ProjectAudioConfig => ({
  characters: characterVoices
    .filter((voice) => shouldIncludeVoiceSettingForModel(voice, ttsModel))
    .map((voice) => {
      const voiceCloneDataUrl = getPayloadVoiceCloneDataUrl(voice, ttsModel)
      const voiceDesignPrompt = getPayloadVoiceDesignPrompt()
      const mimoVoiceAssetId = getPayloadMimoVoiceAssetId(voice, ttsModel)
      const stepaudioVoiceAssetId = getPayloadStepAudioVoiceAssetId(voice, ttsModel)
      return {
        character_id: voice.characterId,
        name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
        ...(voiceCloneDataUrl ? { voice_clone_data_url: voiceCloneDataUrl } : {}),
        ...(voiceDesignPrompt ? { voice_design_prompt: voiceDesignPrompt } : {}),
        ...(mimoVoiceAssetId ? { mimo_voice_asset_id: mimoVoiceAssetId } : {}),
        ...(stepaudioVoiceAssetId ? { stepaudio_voice_asset_id: stepaudioVoiceAssetId } : {}),
        ...(trimOptionalText(voice.source) ? { source: trimOptionalText(voice.source) } : {}),
      }
    }),
  audio_fx: audioFxConfig,
})

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
    .filter((voice) => shouldIncludeVoiceSettingForModel(voice, ttsModel))
    .map((voice) => {
      const voiceCloneDataUrl = getPayloadVoiceCloneDataUrl(voice, ttsModel)
      const voiceDesignPrompt = getPayloadVoiceDesignPrompt()
      const mimoVoiceAssetId = getPayloadMimoVoiceAssetId(voice, ttsModel)
      const stepaudioVoiceAssetId = getPayloadStepAudioVoiceAssetId(voice, ttsModel)
      return {
        character_name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
        ...(voiceCloneDataUrl ? { voice_clone_data_url: voiceCloneDataUrl } : {}),
        ...(voiceDesignPrompt ? { voice_design_prompt: voiceDesignPrompt } : {}),
        ...(mimoVoiceAssetId ? { mimo_voice_asset_id: mimoVoiceAssetId } : {}),
        ...(stepaudioVoiceAssetId ? { stepaudio_voice_asset_id: stepaudioVoiceAssetId } : {}),
      }
    })
