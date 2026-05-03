import type { TtsModel, VoiceCatalogMeta, VoicePreset } from './types'

interface VoiceCatalogPayload {
  model?: unknown
  updated_at?: unknown
  source?: unknown
  voice_count?: unknown
  voices?: unknown
}

export interface NormalizedVoiceCatalog {
  model: TtsModel
  voices: VoicePreset[]
  meta: VoiceCatalogMeta
}

type RawVoicePreset = Partial<VoicePreset> & { id: string }

const isVoicePresetLike = (voice: unknown): voice is RawVoicePreset =>
  typeof voice === 'object'
  && voice !== null
  && typeof (voice as { id?: unknown }).id === 'string'
  && Boolean((voice as { id: string }).id.trim())

const normalizeVoicePreset = (voice: RawVoicePreset): VoicePreset => {
  const speaker = typeof voice.speaker === 'string' && voice.speaker.trim()
    ? voice.speaker
    : voice.id
  const label = typeof voice.label === 'string' && voice.label.trim()
    ? voice.label
    : speaker

  return {
    ...voice,
    speaker,
    label,
    supportsInstruct: Boolean(voice.supportsInstruct),
  }
}

export const normalizeVoiceCatalogPayload = (
  model: TtsModel,
  payload?: VoiceCatalogPayload | null,
): NormalizedVoiceCatalog => {
  const rawVoices = Array.isArray(payload?.voices) ? payload.voices : []
  const voices = rawVoices.filter(isVoicePresetLike).map(normalizeVoicePreset)
  const voiceCount = typeof payload?.voice_count === 'number'
    ? payload.voice_count
    : voices.length

  return {
    model,
    voices,
    meta: {
      model: typeof payload?.model === 'string' ? payload.model : model,
      updated_at: typeof payload?.updated_at === 'string' ? payload.updated_at : undefined,
      source: typeof payload?.source === 'string' ? payload.source : undefined,
      voice_count: voiceCount,
    },
  }
}
