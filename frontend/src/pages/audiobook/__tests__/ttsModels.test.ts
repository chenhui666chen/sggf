import { describe, expect, it } from 'vitest'

import {
  DEFAULT_TTS_MODEL,
  TTS_MODELS,
  createTtsModelRecord,
  getFallbackVoiceId,
  getTtsStyleControlLabels,
  getTtsModelCapabilities,
  modelRequiresCustomVoice,
  modelSupportsCustomVoiceWorkbench,
  modelSupportsInstructStyleControl,
  modelSupportsVoiceTuning,
  modelUsesBasicNumericSpeedControl,
  modelUsesInlineCustomVoiceInput,
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
    expect(normalizeTtsModelValue('MiMo/V2.5-TTS')).toBe('mimo-v2.5-tts')
    expect(normalizeTtsModelValue('mimo-v2.5-tts-voice-design')).toBe('mimo-v2.5-tts-voicedesign')
    expect(normalizeTtsModelValue('mimo-v2.5-tts-voice-clone')).toBe('mimo-v2.5-tts-voiceclone')
    expect(normalizeTtsModelValue('StepFun/StepAudio-2.5-TTS')).toBe('stepaudio-2.5-tts')
    expect(normalizeTtsModelValue('stepaudio_2_5_tts')).toBe('stepaudio-2.5-tts')
    expect(normalizeTtsModelValue('Doubao/Seed-TTS-2.0-Expressive')).toBe('seed-tts-2.0-expressive')
    expect(normalizeTtsModelValue('doubao-tts-2.0-expressive')).toBe('seed-tts-2.0-expressive')
    expect(normalizeTtsModelValue('next-provider-model')).toBe('next-provider-model')
    expect(normalizeTtsModelValue('')).toBeNull()
  })

  it('uses model-specific fallback narrator voices', () => {
    expect(getFallbackVoiceId('qwen3-tts-instruct-flash')).toBe('Neil')
    expect(getFallbackVoiceId('minimax-speech-2.8-hd')).toBe('male-qn-qingse')
    expect(getFallbackVoiceId('minimax-speech-2.8-turbo')).toBe('male-qn-qingse')
    expect(getFallbackVoiceId('mimo-v2.5-tts')).toBe('mimo_default')
    expect(getFallbackVoiceId('mimo-v2.5-tts-voicedesign')).toBe('')
    expect(getFallbackVoiceId('mimo-v2.5-tts-voiceclone')).toBe('')
    expect(getFallbackVoiceId('stepaudio-2.5-tts')).toBe('cixingnansheng')
    expect(getFallbackVoiceId('seed-tts-2.0-expressive')).toBe('zh_female_vv_uranus_bigtts')
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
      'mimo-v2.5-tts': 'mimo-v2.5-tts',
      'mimo-v2.5-tts-voicedesign': 'mimo-v2.5-tts-voicedesign',
      'mimo-v2.5-tts-voiceclone': 'mimo-v2.5-tts-voiceclone',
      'stepaudio-2.5-tts': 'stepaudio-2.5-tts',
      'seed-tts-2.0-expressive': 'seed-tts-2.0-expressive',
    })
    expect(TTS_MODELS).toHaveLength(9)
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
            model_family: 'mimo',
            style_control_modes: ['director', 'audio_tags', 'natural_language'],
            preferred_style_control_mode: 'director',
            supports_voice_description: true,
            supports_director_mode: true,
            supports_audio_tags: true,
            supports_emotion_mixing: true,
            supports_micro_tags: true,
            supports_word_level_control: true,
            instruction_budget: null,
            control_message_roles: {
              director: 'user',
              audio_tags: 'assistant',
              natural_language: 'user',
            },
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
      source: 'remote',
    })
    expect(modelRequiresCustomVoice('next-provider-model', normalized)).toBe(true)
    expect(modelSupportsCustomVoiceWorkbench('next-provider-model', normalized)).toBe(false)
    expect(modelSupportsVoiceTuning('next-provider-model', normalized)).toBe(true)
    expect(modelUsesInlineCustomVoiceInput('next-provider-model', normalized)).toBe(false)
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
      modelFamily: 'cosyvoice',
      styleControlModes: ['natural_language'],
      preferredStyleControlMode: 'natural_language',
      supportsVoiceDescription: true,
      supportsAudioTags: false,
    })
    expect(modelRequiresCustomVoice('qwen3-tts-instruct-flash', normalized)).toBe(false)
    expect(modelSupportsCustomVoiceWorkbench('cosyvoice-v3.5-plus', normalized)).toBe(true)
    expect(modelSupportsCustomVoiceWorkbench('mimo-v2.5-tts-voicedesign')).toBe(false)
    expect(modelSupportsCustomVoiceWorkbench('mimo-v2.5-tts-voiceclone')).toBe(false)
    expect(modelUsesInlineCustomVoiceInput('cosyvoice-v3.5-plus', normalized)).toBe(false)
    expect(modelUsesInlineCustomVoiceInput('mimo-v2.5-tts')).toBe(false)
    expect(modelUsesInlineCustomVoiceInput('mimo-v2.5-tts-voicedesign')).toBe(false)
    expect(modelUsesInlineCustomVoiceInput('mimo-v2.5-tts-voiceclone')).toBe(true)
  })

  it('keeps model-aware style control fallback capabilities', () => {
    expect(getTtsModelCapabilities('qwen3-tts-instruct-flash')).toMatchObject({
      modelFamily: 'qwen',
      styleControlModes: ['natural_language'],
      preferredStyleControlMode: 'natural_language',
      supportsVoiceDescription: true,
      supportsAudioTags: false,
      instructionBudget: 600,
    })

    expect(getTtsModelCapabilities('minimax-speech-2.8-hd')).toMatchObject({
      modelFamily: 'minimax',
      styleControlModes: ['basic'],
      preferredStyleControlMode: 'basic',
      supportsVoiceDescription: false,
      supportsAudioTags: false,
      supportsVoiceClone: true,
    })
    expect(modelSupportsCustomVoiceWorkbench('minimax-speech-2.8-hd')).toBe(true)
    expect(modelSupportsCustomVoiceWorkbench('minimax-speech-2.8-turbo')).toBe(true)

    expect(getTtsModelCapabilities('mimo-v2.5-tts')).toMatchObject({
      hasSystemVoices: true,
      requiresCustomVoice: false,
      supportsVoiceClone: false,
      supportsVoiceDesign: false,
      modelFamily: 'mimo',
      styleControlModes: ['director', 'audio_tags', 'natural_language'],
      preferredStyleControlMode: 'director',
      supportsVoiceDescription: true,
      supportsAudioTags: true,
    })

    expect(getTtsModelCapabilities('mimo-v2.5-tts-voicedesign')).toMatchObject({
      hasSystemVoices: false,
      requiresCustomVoice: true,
      supportsVoiceClone: false,
      supportsVoiceDesign: true,
      modelFamily: 'mimo',
      styleControlModes: ['voice_design', 'natural_language'],
      preferredStyleControlMode: 'voice_design',
      supportsDirectorMode: false,
      supportsAudioTags: false,
      supportsMicroTags: false,
      supportsWordLevelControl: false,
    })

    expect(getTtsModelCapabilities('mimo-v2.5-tts-voiceclone')).toMatchObject({
      hasSystemVoices: false,
      requiresCustomVoice: true,
      supportsVoiceClone: true,
      supportsVoiceDesign: false,
      modelFamily: 'mimo',
      styleControlModes: ['director', 'audio_tags', 'natural_language'],
    })

    expect(getTtsModelCapabilities('stepaudio-2.5-tts')).toMatchObject({
      hasSystemVoices: true,
      requiresCustomVoice: false,
      supportsVoiceClone: true,
      supportsVoiceDesign: false,
      modelFamily: 'stepaudio',
      styleControlModes: ['global_context', 'inline_context', 'natural_language'],
      preferredStyleControlMode: 'global_context',
      supportsVoiceDescription: true,
      supportsEmotionMixing: true,
      supportsMicroTags: true,
      supportsWordLevelControl: true,
      instructionBudget: 200,
      controlMessageRoles: {
        global_context: 'parameters.instruction',
        inline_context: 'input.parentheses',
        natural_language: 'parameters.instruction',
      },
    })

    expect(getTtsModelCapabilities('seed-tts-2.0-expressive')).toMatchObject({
      hasSystemVoices: true,
      requiresCustomVoice: false,
      supportsVoiceClone: true,
      supportsVoiceDesign: false,
      modelFamily: 'doubao',
      styleControlModes: ['query_response', 'audio_tags', 'natural_language'],
      preferredStyleControlMode: 'query_response',
      supportsVoiceDescription: true,
      supportsEmotionMixing: true,
      supportsMicroTags: true,
      supportsWordLevelControl: true,
      controlMessageRoles: {
        query_response: 'req_params.additions.context_texts',
        audio_tags: 'req_params.text + req_params.use_tag_parser',
        natural_language: 'req_params.additions.context_texts',
      },
    })
  })

  it('separates instruction pace models from basic numeric fallback models', () => {
    for (const model of [
      'qwen3-tts-instruct-flash',
      'cosyvoice-v3.5-plus',
      'mimo-v2.5-tts',
      'mimo-v2.5-tts-voicedesign',
      'mimo-v2.5-tts-voiceclone',
      'stepaudio-2.5-tts',
      'seed-tts-2.0-expressive',
    ] as const) {
      expect(modelSupportsInstructStyleControl(model)).toBe(true)
    }

    expect(modelSupportsInstructStyleControl('minimax-speech-2.8-hd')).toBe(false)
    expect(modelSupportsInstructStyleControl('minimax-speech-2.8-turbo')).toBe(false)
    expect(modelSupportsInstructStyleControl(null)).toBe(false)

    expect(modelUsesBasicNumericSpeedControl('minimax-speech-2.8-hd')).toBe(true)
    expect(modelUsesBasicNumericSpeedControl('minimax/speech-2.8-turbo')).toBe(true)
    expect(modelUsesBasicNumericSpeedControl('seed-tts-2.0-expressive')).toBe(false)
    expect(modelUsesBasicNumericSpeedControl('unknown-model')).toBe(false)
    expect(modelUsesBasicNumericSpeedControl(null)).toBe(false)
  })

  it('builds readable style control labels from model capabilities', () => {
    const normalized = normalizeTtsModelOptions({
      models: [
        {
          id: 'mimo-v2.5-tts',
          name: 'MiMo V2.5 TTS',
          capabilities: {
            style_control_modes: ['director', 'audio_tags', 'natural_language'],
            preferred_style_control_mode: 'director',
            supports_voice_description: true,
            supports_audio_tags: true,
          },
        },
      ],
    })

    expect(getTtsStyleControlLabels('qwen3-tts-instruct-flash')).toEqual(['自然语言指令'])
    expect(getTtsStyleControlLabels('minimax-speech-2.8-hd')).toEqual(['基础参数'])
    expect(getTtsStyleControlLabels('mimo-v2.5-tts', normalized)).toEqual([
      '导演模式',
      '音频标签',
      '自然语言指令',
    ])
    expect(getTtsStyleControlLabels('mimo-v2.5-tts-voicedesign')[0]).toBe('音色设计')
  })

  it('exposes StepAudio contextual style labels', () => {
    expect(getTtsStyleControlLabels('stepaudio-2.5-tts')).toEqual([
      '全局语境',
      '文中语境',
      '自然语言指令',
    ])
  })

  it('exposes Doubao Seed-TTS query-response style labels', () => {
    expect(getTtsStyleControlLabels('seed-tts-2.0-expressive')).toEqual([
      '对话式TTS',
      '音频标签',
      '自然语言指令',
    ])
  })
})
