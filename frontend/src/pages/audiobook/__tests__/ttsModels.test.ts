import { describe, expect, it } from 'vitest'

import {
  DEFAULT_TTS_MODEL,
  TTS_MODELS,
  createTtsModelRecord,
  getFallbackVoiceId,
  getTtsModelCapabilities,
  modelRequiresCustomVoice,
  modelSupportsCustomVoiceWorkbench,
  modelSupportsVoiceTuning,
  normalizeTtsModelOptions,
  normalizeTtsModelValue,
  normalizeVoiceId,
} from '../ttsModels'

describe('audiobook ttsModels', () => {
  it('normalizes legacy and registry model ids to audiobook model ids', () => {
    expect(normalizeTtsModelValue('qwen3-tts-flash')).toBe(DEFAULT_TTS_MODEL)
    expect(normalizeTtsModelValue('qwen3-tts-plus')).toBe(DEFAULT_TTS_MODEL)
    expect(normalizeTtsModelValue('cosyvoice-v3-plus')).toBe('cosyvoice-v3.5-plus')
    expect(normalizeTtsModelValue('MiniMax/speech-2.8-hd')).toBe('minimax-speech-2.8-hd')
    expect(normalizeTtsModelValue('MiniMax/speech-2.8-turbo')).toBe('minimax-speech-2.8-turbo')
    expect(normalizeTtsModelValue('next-provider-model')).toBe('next-provider-model')
    expect(normalizeTtsModelValue('')).toBeNull()
  })

  it('uses model-specific fallback narrator voices', () => {
    expect(getFallbackVoiceId('qwen3-tts-instruct-flash')).toBe('Neil')
    expect(getFallbackVoiceId('minimax-speech-2.8-hd')).toBe('male-qn-qingse')
    expect(getFallbackVoiceId('minimax-speech-2.8-turbo')).toBe('male-qn-qingse')
    expect(getFallbackVoiceId('cosyvoice-v3.5-plus')).toBe('')
    expect(getFallbackVoiceId('cosyvoice-v3.5-plus', [{ id: 'cosyvoice-v3.5-plus-demo' }])).toBe(
      'cosyvoice-v3.5-plus-demo',
    )
  })

  it('normalizes voice ids only for the matching model family', () => {
    expect(normalizeVoiceId('qwen3-tts-instruct-flash', 'Ryan')).toBe('Neil')
    expect(normalizeVoiceId('qwen3-tts-instruct-flash', 'male_narrator')).toBe('Neil')
    expect(normalizeVoiceId('cosyvoice-v3.5-plus', 'longanzhi_v3')).toBe('')
    expect(normalizeVoiceId('minimax-speech-2.8-hd', 'male-qn-qingse')).toBe('male-qn-qingse')
  })

  it('creates complete records for all supported tts models', () => {
    expect(createTtsModelRecord((model) => model)).toEqual({
      'qwen3-tts-instruct-flash': 'qwen3-tts-instruct-flash',
      'cosyvoice-v3.5-plus': 'cosyvoice-v3.5-plus',
      'minimax-speech-2.8-hd': 'minimax-speech-2.8-hd',
      'minimax-speech-2.8-turbo': 'minimax-speech-2.8-turbo',
    })
    expect(TTS_MODELS).toHaveLength(4)
  })

  it('normalizes backend tts model catalog payloads with static fallback options', () => {
    const normalized = normalizeTtsModelOptions({
      models: [
        {
          id: 'next-provider-model',
          name: 'Next Provider',
          description: 'backend model',
          voice_count: 12,
          price_per_10k: 4,
          features: ['dynamic'],
          cost_level: 'medium',
          quality_level: 'high',
          catalog_note: 'backend capability note',
          catalog_status: 'unavailable',
          catalog_error: 'catalog failed',
          runtime_model_id: 'provider/runtime-model',
          runtime_status: 'unavailable',
          runtime_error: 'runtime failed',
          capabilities: {
            has_system_voices: false,
            requires_custom_voice: true,
            supports_voice_clone: true,
            supports_voice_design: false,
            supports_voice_tuning: true,
          },
        },
      ],
    })

    expect(normalized[0]).toMatchObject({
      id: 'next-provider-model',
      name: 'Next Provider',
      voiceCount: 12,
      pricePer10k: 4,
      features: ['dynamic'],
      costLevel: 'medium',
      qualityLevel: 'high',
      catalogNote: 'backend capability note',
      catalogStatus: 'unavailable',
      catalogError: 'catalog failed',
      runtimeModelId: 'provider/runtime-model',
      runtimeStatus: 'unavailable',
      runtimeError: 'runtime failed',
      capabilities: {
        hasSystemVoices: false,
        requiresCustomVoice: true,
        supportsVoiceClone: true,
        supportsVoiceDesign: false,
        supportsVoiceTuning: true,
      },
      source: 'remote',
    })
    expect(modelRequiresCustomVoice('next-provider-model', normalized)).toBe(true)
    expect(modelSupportsCustomVoiceWorkbench('next-provider-model', normalized)).toBe(true)
    expect(modelSupportsVoiceTuning('next-provider-model', normalized)).toBe(true)
    expect(normalized.map((option) => option.id)).toContain(DEFAULT_TTS_MODEL)
    expect(normalizeTtsModelOptions(null)).toHaveLength(TTS_MODELS.length)
  })

  it('falls back to known model capabilities when backend payload omits them', () => {
    const normalized = normalizeTtsModelOptions({
      models: [{ id: 'cosyvoice-v3.5-plus', name: 'CosyVoice' }],
    })

    expect(getTtsModelCapabilities('cosyvoice-v3.5-plus', normalized)).toMatchObject({
      hasSystemVoices: false,
      requiresCustomVoice: true,
      supportsVoiceClone: true,
      supportsVoiceDesign: true,
      supportsVoiceTuning: true,
    })
    expect(modelRequiresCustomVoice('qwen3-tts-instruct-flash', normalized)).toBe(false)
  })
})
