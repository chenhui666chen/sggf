import { describe, expect, it } from 'vitest'

import { buildSeedSceneReferencePayload } from '../seedSceneReferenceUtils'


describe('Seed scene reference assignment', () => {
  it('binds Seed-TTS 2.0 voices as native speaker IDs without preview audio', () => {
    expect(buildSeedSceneReferencePayload({
      slotId: 'narrator',
      model: 'seed-tts-2.0-expressive',
      voiceId: 'zh_male_taocheng_uranus_bigtts',
      audioUrl: 'https://audio.example.test/preview.mp3',
      audioDataBase64: 'IGNORED_AUDIO',
      audioMimeType: 'audio/mpeg',
    })).toEqual({
      slot_id: 'narrator',
      source_model: 'seed-tts-2.0-expressive',
      source_voice_id: 'zh_male_taocheng_uranus_bigtts',
    })
  })

  it('keeps Doubao cloned voices as speaker IDs even when preview audio exists', () => {
    expect(buildSeedSceneReferencePayload({
      slotId: 'femaleLead',
      model: 'doubao/seed-tts-2.0-expressive',
      voiceId: 'S_account_voice_clone_001',
      audioUrl: 'https://audio.example.test/clone-preview.mp3',
      audioDataBase64: 'IGNORED_AUDIO',
      audioMimeType: 'audio/mpeg',
    })).toEqual({
      slot_id: 'femaleLead',
      source_model: 'doubao/seed-tts-2.0-expressive',
      source_voice_id: 'S_account_voice_clone_001',
    })
  })

  it('keeps other providers bound to their preview audio', () => {
    expect(buildSeedSceneReferencePayload({
      slotId: 'femaleLead',
      model: 'qwen3-tts-instruct-flash',
      voiceId: 'Cherry',
      audioUrl: 'https://audio.example.test/cherry.wav',
    })).toEqual({
      slot_id: 'femaleLead',
      source_model: 'qwen3-tts-instruct-flash',
      source_voice_id: 'Cherry',
      audio_url: 'https://audio.example.test/cherry.wav',
    })
  })
})
