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
      intelligent_balance: true,
      balance_strategy: 'auto',
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
      intelligent_balance: true,
      balance_strategy: 'auto',
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
          voice_clone_data_url: 'data:audio/wav;base64,AAAA',
          voice_design_prompt: '青年女性，中音，语速中等，温柔但疲惫',
        },
      ],
      // 提供有效的音色列表,让 female-shaonv 被视为无效(因为不在列表中)
      voicePresets: [{ id: 'valid-voice-1' }, { id: 'valid-voice-2' }],
    })

    expect(voices).toEqual([
      {
        characterId: 1,
        name: 'Alice',
        gender: 'female',
        role: 'lead',
        voiceId: '', // female-shaonv 对 minimax 模型无效,被重置为空
        volume: 66,
        speed: 1.2,
        pitch: 44,
        ttsModel: 'minimax-speech-2.8-hd',
        voiceType: 'bright',
        personality: 'calm',
        emotionTendency: 'warm',
        voiceCloneDataUrl: 'data:audio/wav;base64,AAAA',
        voiceDesignPrompt: '青年女性，中音，语速中等，温柔但疲惫',
        mimoVoiceAssetId: undefined,
        stepaudioVoiceAssetId: undefined,
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
        mimoVoiceAssetId: undefined,
        stepaudioVoiceAssetId: undefined,
        voiceCloneDataUrl: undefined,
        voiceDesignPrompt: undefined,
      },
    ])
  })

  it('hydrates legacy asset ids into voice id references', () => {
    const voices = buildProjectCharacterVoiceSettings({
      ttsModel: 'mimo-v2.5-tts-voiceclone',
      characters: [
        { id: 1, name: 'CloneHero' },
        { id: 2, name: 'DesignHero' },
        { id: 3, name: 'StepHero' },
      ],
      savedCharacters: [
        {
          character_id: 1,
          name: 'CloneHero',
          voice_id: '',
          tts_model: 'mimo-v2.5-tts-voiceclone',
          mimo_voice_asset_id: 'mimo_clone_unit',
        },
        {
          character_id: 2,
          name: 'DesignHero',
          voice_id: '',
          tts_model: 'mimo-v2.5-tts-voicedesign',
          mimo_voice_asset_id: 'mimo_design_unit',
        },
        {
          character_id: 3,
          name: 'StepHero',
          voice_id: '',
          tts_model: 'stepaudio-2.5-tts',
          stepaudio_voice_asset_id: 'stepaudio_clone_unit',
        },
      ],
    })

    expect(voices.map((voice) => voice.voiceId)).toEqual([
      'mimo_clone:mimo_clone_unit',
      'mimo_design:mimo_design_unit',
      'stepaudio_clone:stepaudio_clone_unit',
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
      voiceId: 'male-qn-qingse', // narrator-saved 无效,回退到 baseNarratorVoice
      volume: 70,
      speed: 0.9,
      pitch: 40,
    })
    expect(voices[1]).toMatchObject({
      characterId: 7,
      name: 'Hero',
      voiceId: '', // hero-saved 对 minimax 模型无效,被重置为空
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
          voice_clone_data_url: 'data:audio/mpeg;base64,BBBB',
          voice_design_prompt: '中年男性，低音，语速偏慢，沉稳有磁性',
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
          voiceCloneDataUrl: 'data:audio/mpeg;base64,BBBB',
          voiceDesignPrompt: '中年男性，低音，语速偏慢，沉稳有磁性',
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
          tts_model: 'qwen3-tts-instruct-flash',
        },
        {
          character_id: 2,
          name: 'Hero',
          voice_id: 'hero-voice',
          tts_model: 'minimax-speech-2.8-turbo',
        },
      ],
      audio_fx: audioFxConfig,
    })
  })

  it('ignores inline clone and design inputs because voice assets are managed separately', () => {
    const audioFxConfig = createDefaultAudioFxConfig()

    expect(buildProjectAudioConfigPayload({
      ttsModel: 'mimo-v2.5-tts-voiceclone',
      voicePresets: [],
      audioFxConfig,
      characterVoices: [
        {
          characterId: 5,
          name: 'CloneHero',
          voiceId: '',
          volume: 60,
          speed: 1.05,
          pitch: 50,
          ttsModel: 'mimo-v2.5-tts-voiceclone',
          voiceCloneDataUrl: ' data:audio/wav;base64,AAAA ',
        },
        {
          characterId: 6,
          name: 'DesignHero',
          voiceId: '',
          volume: 55,
          ttsModel: 'mimo-v2.5-tts-voicedesign',
          voiceDesignPrompt: ' 青年女性，中音，语速中等，清亮但克制，适合有声书对白 ',
        },
      ],
    })).toEqual({
      characters: [],
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
        tts_model: 'cosyvoice-v3.5-plus',
      },
      {
        character_name: 'Villain',
        voice_id: 'villain-voice',
        tts_model: 'cosyvoice-v3.5-plus',
      },
    ])
  })

  it('omits role-level voice profiling and tuning from persisted and generation payloads', () => {
    const audioFxConfig = createDefaultAudioFxConfig()

    expect(buildProjectAudioConfigPayload({
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
      audioFxConfig,
      characterVoices: [
        {
          characterId: 16,
          name: 'RuntimeDirectedRole',
          voiceId: 'Neil',
          volume: 72,
          speed: 1.4,
          pitch: 35,
          voiceType: 'cold',
          personality: 'rational',
          emotionTendency: 'negative',
        },
      ],
    }).characters[0]).toEqual({
      character_id: 16,
      name: 'RuntimeDirectedRole',
      voice_id: 'Neil',
      tts_model: 'qwen3-tts-instruct-flash',
    })

    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
      characterVoices: [
        {
          characterId: 17,
          name: 'RuntimeGeneratedPromptRole',
          voiceId: 'Cherry',
          volume: 40,
          speed: 0.8,
          pitch: 70,
          voiceType: 'warm',
          personality: 'calm',
          emotionTendency: 'positive',
        },
      ],
    })[0]).toEqual({
      character_name: 'RuntimeGeneratedPromptRole',
      voice_id: 'Cherry',
      tts_model: 'qwen3-tts-instruct-flash',
    })
  })

  it('excludes inline clone and design inputs from generation voice config', () => {
    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'mimo-v2.5-tts-voicedesign',
      voicePresets: [],
      characterVoices: [
        {
          characterId: 7,
          name: 'CloneRole',
          voiceId: '',
          volume: 64,
          ttsModel: 'mimo-v2.5-tts-voiceclone',
          voiceCloneDataUrl: 'data:audio/mpeg;base64,BBBB',
        },
        {
          characterId: 8,
          name: 'DesignRole',
          voiceId: '',
          volume: 58,
          ttsModel: 'mimo-v2.5-tts-voicedesign',
          voiceDesignPrompt: '少年男性，偏高音，语速偏快，紧张但勇敢',
        },
      ],
    })).toEqual([])
  })

  it('ignores stale MiMo inline inputs when the effective model no longer uses them', () => {
    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'qwen3-tts-instruct-flash',
      voicePresets: [],
      characterVoices: [
        {
          characterId: 9,
          name: 'StaleInlineRole',
          voiceId: 'Neil',
          volume: 50,
          voiceCloneDataUrl: 'data:audio/wav;base64,STALE',
          voiceDesignPrompt: '不应进入非 MiMo inline 模型',
        },
      ],
    })).toEqual([
      {
        character_name: 'StaleInlineRole',
        voice_id: 'Neil',
        tts_model: 'qwen3-tts-instruct-flash',
      },
    ])
  })

  it('persists reusable voice assets as voice_id references only', () => {
    const audioFxConfig = createDefaultAudioFxConfig()

    expect(buildProjectAudioConfigPayload({
      ttsModel: 'mimo-v2.5-tts-voicedesign',
      voicePresets: [],
      audioFxConfig,
      characterVoices: [
        {
          characterId: 12,
          name: 'ReusableDesign',
          voiceId: 'mimo_design:mimo_design_unit',
          volume: 57,
          ttsModel: 'mimo-v2.5-tts-voicedesign',
          mimoVoiceAssetId: 'mimo_design_unit',
          voiceDesignPrompt: 'stale inline prompt should not be saved when asset id exists',
        },
      ],
    })).toEqual({
      characters: [
        {
          character_id: 12,
          name: 'ReusableDesign',
          voice_id: 'mimo_design:mimo_design_unit',
          tts_model: 'mimo-v2.5-tts-voicedesign',
        },
      ],
      audio_fx: audioFxConfig,
    })

    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'mimo-v2.5-tts-voiceclone',
      voicePresets: [],
      characterVoices: [
        {
          characterId: 13,
          name: 'ReusableClone',
          voiceId: 'mimo_clone:mimo_clone_unit',
          volume: 61,
          ttsModel: 'mimo-v2.5-tts-voiceclone',
          mimoVoiceAssetId: 'mimo_clone_unit',
          voiceCloneDataUrl: 'data:audio/wav;base64,STALE',
        },
      ],
    })).toEqual([
      {
        character_name: 'ReusableClone',
        voice_id: 'mimo_clone:mimo_clone_unit',
        tts_model: 'mimo-v2.5-tts-voiceclone',
      },
    ])

    expect(buildAudiobookVoiceConfigPayload({
      ttsModel: 'stepaudio-2.5-tts',
      voicePresets: [],
      characterVoices: [
        {
          characterId: 14,
          name: 'ReusableStepAudioClone',
          voiceId: 'stepaudio_clone:stepaudio_clone_unit',
          volume: 62,
          ttsModel: 'stepaudio-2.5-tts',
          stepaudioVoiceAssetId: 'stepaudio_clone_unit',
        },
      ],
    })).toEqual([
      {
        character_name: 'ReusableStepAudioClone',
        voice_id: 'stepaudio_clone:stepaudio_clone_unit',
        tts_model: 'stepaudio-2.5-tts',
      },
    ])
  })
})
