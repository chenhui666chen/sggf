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
  if (stepaudioVoiceAssetId && effectiveModel === 'stepaudio-2.5-tts') {
    return `stepaudio_clone:${stepaudioVoiceAssetId}`
  }
  return ''
}

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
    const savedVoiceId = normalizeVoiceId(savedTtsModel, saved?.voice_id, validVoiceIds)
    const legacyAssetVoiceId = resolveLegacyVoiceAssetReference({
      characterId: character.id,
      name: character.name,
      voiceId: '',
      volume: 50,
      ttsModel: savedTtsModel,
      mimoVoiceAssetId: trimOptionalText(saved?.mimo_voice_asset_id),
      stepaudioVoiceAssetId: trimOptionalText(saved?.stepaudio_voice_asset_id),
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
    voiceId: normalizeVoiceId(ttsModel, narratorSaved?.voice_id, new Set(voicePresets.map((p) => p.id)))
      || resolveLegacyVoiceAssetReference({
        characterId: NARRATOR_CHARACTER_ID,
        name: NARRATOR_NAME,
        voiceId: '',
        volume: baseNarratorVoice.volume,
        ttsModel,
        mimoVoiceAssetId: trimOptionalText(narratorSaved?.mimo_voice_asset_id),
        stepaudioVoiceAssetId: trimOptionalText(narratorSaved?.stepaudio_voice_asset_id),
      }, ttsModel)
      || baseNarratorVoice.voiceId,
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
    const legacyAssetVoiceId = resolveLegacyVoiceAssetReference({
      ...voice,
      voiceId: '',
      ttsModel: config.ttsModel ?? voice.ttsModel,
      mimoVoiceAssetId: config.mimoVoiceAssetId ?? voice.mimoVoiceAssetId,
      stepaudioVoiceAssetId: config.stepaudioVoiceAssetId ?? voice.stepaudioVoiceAssetId,
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
  ttsModel,
  voicePresets,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  ttsModel: TtsModel
  voicePresets: Array<Pick<VoicePreset, 'id'>>
}): ProjectAudioConfig => ({
  characters: characterVoices
    .filter(shouldIncludeVoiceSettingForModel)
    .map((voice) => {
      return {
        character_id: voice.characterId,
        name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
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
    .filter(shouldIncludeVoiceSettingForModel)
    .map((voice) => {
      return {
        character_name: voice.name,
        voice_id: resolvePayloadVoiceId(voice, ttsModel, voicePresets),
        tts_model: voice.ttsModel || ttsModel,
      }
    })
