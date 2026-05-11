import { describe, expect, it } from 'vitest'

import {
  applyProjectVoiceAssignments,
  buildAudiobookVoiceConfigPayload,
  buildBaseNarratorVoice,
  buildInitialProjectVoiceSettings,
  buildProjectAudioConfigPayload,
  buildProjectCharacterVoiceSettings,
  createDefaultAudioFxConfig,
  normalizeProjectAudioFxConfig,
} from '../projectAudioConfigUtils'

describe('audiobook project audio config utils', () => {
  it('creates default audio fx config', () => {
    expect(createDefaultAudioFxConfig()).toEqual({
      enable_sound_effects: true,
      enable_music: true,
      sound_effect_density: 'medium',
      music_density: 'medium',
    })
  })

  it('normalizes partial or invalid audio fx config', () => {
    expect(normalizeProjectAudioFxConfig(null)).toEqual(createDefaultAudioFxConfig())
    expect(normalizeProjectAudioFxConfig({
      enable_sound_effects: false,
      enable_music: true,
      sound_effect_density: 'high',
      music_density: 'invalid' as unknown as 'medium',
    })).toEqual({
      enable_sound_effects: false,
      enable_music: true,
      sound_effect_density: 'high',
      music_density: 'medium',
    })
  })

  it('builds narrator voice with model fallback voice', () => {
    expect(buildBaseNarratorVoice('qwen3-tts-instruct-flash')).toMatchObject({
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: 'Neil',
      volume: 50,
      speed: 1,
      pitch: 50,
    })

    expect(buildBaseNarratorVoice('cosyvoice-v3.5-plus', [{ id: 'custom-voice' }]).voiceId)
      .toBe('custom-voice')
  })

  it('builds character voice settings from saved project config', () => {
    const voices = buildProjectCharacterVoiceSettings({
      ttsModel: 'qwen3-tts-instruct-flash',
      characters: [
        { id: 1, name: 'Alice', gender: 'female', role: 'lead' },
        { id: 2, name: 'Bob' },
      ],
      savedCharacters: [
        {
          character_id: 1,
          name: 'Alice',
          voice_id: 'female-shaonv',
          volume: 66,
          speed: 1.2,
          pitch: 44,
          tts_model: 'minimax-speech-2.8-hd',
          voice_type: 'bright',
          personality: 'calm',
          emotion_tendency: 'warm',
        },
      ],
    })

    expect(voices).toEqual([
      {
        characterId: 1,
        name: 'Alice',
        gender: 'female',
        role: 'lead',
        voiceId: 'female-shaonv',
        volume: 66,
        speed: 1.2,
        pitch: 44,
        ttsModel: 'minimax-speech-2.8-hd',
        voiceType: 'bright',
        personality: 'calm',
        emotionTendency: 'warm',
      },
      {
        characterId: 2,
        name: 'Bob',
        gender: undefined,
        role: undefined,
        voiceId: '',
        volume: 50,
        speed: 1,
        pitch: 50,
        ttsModel: 'qwen3-tts-instruct-flash',
        voiceType: undefined,
        personality: undefined,
        emotionTendency: undefined,
      },
    ])
  })

  it('builds initial voices with saved narrator first', () => {
    const voices = buildInitialProjectVoiceSettings({
      ttsModel: 'minimax-speech-2.8-hd',
      voicePresets: [{ id: 'male-qn-qingse' }],
      characters: [{ id: 7, name: 'Hero' }],
      projectAudioConfig: {
        characters: [
          {
            character_id: 0,
            name: '旁白',
            voice_id: 'narrator-saved',
            volume: 70,
            speed: 0.9,
            pitch: 40,
          },
          {
            character_id: 7,
            name: 'Hero',
            voice_id: 'hero-saved',
            volume: 55,
          },
        ],
      },
    })

    expect(voices[0]).toMatchObject({
      characterId: 0,
      name: '旁白',
      voiceId: 'narrator-saved',
      volume: 70,
      speed: 0.9,
      pitch: 40,
    })
    expect(voices[1]).toMatchObject({
      characterId: 7,
      name: 'Hero',
      voiceId: 'hero-saved',
      volume: 55,
    })
  })

  it('applies voice assignments to existing character voice settings', () => {
    expect(applyProjectVoiceAssignments({
      ttsModel: 'qwen3-tts-instruct-flash',
      characterVoices: [
        {
          characterId: 1,
          name: 'Lead',
          voiceId: '',
          volume: 50,
          speed: 1,
          pitch: 50,
        },
        {
          characterId: 2,
          name: 'Untouched',
          voiceId: '',
          volume: 45,
          speed: 0.9,
          pitch: 48,
        },
      ],
      savedCharacters: [
        {
          character_id: 1,
          name: 'Lead',
          voice_id: 'male-qn-qingse',
          volume: 64,
          speed: null,
          pitch: 42,
          tts_model: 'minimax-speech-2.8-hd',
          voice_type: 'powerful',
          personality: 'ambitious',
          emotion_tendency: 'positive',
        },
        {
          character_id: 999,
          name: 'Missing',
          voice_id: 'Neil',
          volume: 60,
        },
      ],
    })).toEqual({
      assignedCount: 1,
      characterVoices: [
        {
          characterId: 1,
          name: 'Lead',
          voiceId: 'male-qn-qingse',
          volume: 64,
          speed: 1,
          pitch: 42,
          ttsModel: 'minimax-speech-2.8-hd',
          voiceType: 'powerful',
          personality: 'ambitious',
          emotionTendency: 'positive',
        },
        {
          characterId: 2,
          name: 'Untouched',
          voiceId: '',
          volume: 45,
          speed: 0.9,
          pitch: 48,
        },
      ],
    })
  })

  it('builds persisted project audio config from selected voices', () => {
    const audioFxConfig = createDefaultAudioFxConfig()

    expect(buildProjectAudioConfigPayload({
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
      audioFxConfig,
      characterVoices: [
        {
          characterId: 0,
          name: '旁白',
          voiceId: '',
          volume: 50,
          speed: 1,
          pitch: 50,
          voiceType: '  steady ',
          personality: '',
          emotionTendency: ' warm ',
        },
        {
          characterId: 1,
          name: 'NoVoice',
          voiceId: '   ',
          volume: 50,
        },
        {
          characterId: 2,
          name: 'Hero',
          voiceId: ' hero-voice ',
          volume: 63,
          ttsModel: 'minimax-speech-2.8-turbo',
        },
      ],
    })).toEqual({
      characters: [
        {
          character_id: 0,
          name: '旁白',
          voice_id: 'Neil',
          volume: 50,
          speed: 1,
          pitch: 50,
          tts_model: 'qwen3-tts-instruct-flash',
          voice_type: 'steady',
          personality: undefined,
          emotion_tendency: 'warm',
        },
        {
          character_id: 2,
          name: 'Hero',
          voice_id: 'hero-voice',
          volume: 63,
          speed: undefined,
          pitch: undefined,
          tts_model: 'minimax-speech-2.8-turbo',
          voice_type: undefined,
          personality: undefined,
          emotion_tendency: undefined,
        },
      ],
      audio_fx: audioFxConfig,
    })
  })

  it('builds audiobook generation voice config with the same inclusion rules', () => {
    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'cosyvoice-v3.5-plus',
      voicePresets: [{ id: 'cosy-narrator' }],
      characterVoices: [
        {
          characterId: 0,
          name: 'Narrator Alias',
          voiceId: '',
          volume: 52,
          speed: 0.98,
          pitch: 51,
        },
        {
          characterId: 3,
          name: 'Skipped',
          voiceId: '',
          volume: 50,
        },
        {
          characterId: 4,
          name: 'Villain',
          voiceId: 'villain-voice',
          volume: 58,
          speed: 1.05,
          voiceType: 'cold',
          personality: 'rational',
          emotionTendency: 'negative',
        },
      ],
    })).toEqual([
      {
        character_name: 'Narrator Alias',
        voice_id: 'cosy-narrator',
        volume: 52,
        speed: 0.98,
        pitch: 51,
        tts_model: 'cosyvoice-v3.5-plus',
        voice_type: undefined,
        personality: undefined,
        emotion_tendency: undefined,
      },
      {
        character_name: 'Villain',
        voice_id: 'villain-voice',
        volume: 58,
        speed: 1.05,
        pitch: undefined,
        tts_model: 'cosyvoice-v3.5-plus',
        voice_type: 'cold',
        personality: 'rational',
        emotion_tendency: 'negative',
      },
    ])
  })
})
