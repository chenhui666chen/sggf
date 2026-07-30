import type { SeedSceneTestReferencePayload } from '@/services/api'

import { normalizeTtsModelValue } from './ttsModels'


const NATIVE_SEED_SPEAKER_MODEL = 'seed-tts-2.0-expressive'

export const isNativeSeedSpeakerModel = (model: string) => (
  normalizeTtsModelValue(model) === NATIVE_SEED_SPEAKER_MODEL
)

export const buildSeedSceneReferencePayload = ({
  slotId,
  model,
  voiceId,
  audioUrl,
  audioDataBase64,
  audioMimeType,
}: {
  slotId: string
  model: string
  voiceId: string
  audioUrl?: string | null
  audioDataBase64?: string | null
  audioMimeType?: string | null
}): SeedSceneTestReferencePayload => {
  const basePayload: SeedSceneTestReferencePayload = {
    slot_id: slotId,
    source_model: model,
    source_voice_id: voiceId,
  }
  if (isNativeSeedSpeakerModel(model)) return basePayload

  if (audioUrl) return { ...basePayload, audio_url: audioUrl }
  if (audioDataBase64) {
    return {
      ...basePayload,
      audio_data_base64: audioDataBase64,
      audio_mime_type: audioMimeType || 'audio/mpeg',
    }
  }
  return basePayload
}
