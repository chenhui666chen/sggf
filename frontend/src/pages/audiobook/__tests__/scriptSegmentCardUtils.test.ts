import { describe, expect, it } from 'vitest'
import * as scriptSegmentCardUtils from '../scriptSegmentCardUtils'

import {
  formatScriptSegmentSummary,
  getInlineTagStrategySummary,
  getMusicCueInputValue,
  getScriptSegmentVoiceParams,
  getScriptSegmentSpeakerLabel,
  getScriptSegmentTypeLabel,
  getSoundEffectsInputValue,
  hasPreviewableMusicCue,
  hasPreviewableSoundEffects,
  parseCommaSeparatedList,
  parseOptionalNumberInput,
  sanitizeScriptSegmentVoiceIdentityControls,
} from '../scriptSegmentCardUtils'

describe('script segment card utils', () => {
  it('builds structured patches for explicit audio library selections', () => {
    const utils = scriptSegmentCardUtils as unknown as {
      buildSoundEffectAssetPatch: (selection: {
        id: string
        type: 'sfx'
        label: string
        name?: string
      }) => unknown
      buildMusicAssetPatch: (selection: {
        id: string
        type: 'music'
        label: string
        style?: string
        mood?: string
      }) => unknown
    }

    expect(typeof utils.buildSoundEffectAssetPatch).toBe('function')
    expect(utils.buildSoundEffectAssetPatch({
      id: 'sfx-door-01',
      type: 'sfx',
      label: 'Heavy door',
      name: 'Heavy door',
    })).toEqual({
      sound_effects: [{ asset_id: 'sfx-door-01', name: 'Heavy door' }],
      sound_effects_simple: [],
    })

    expect(typeof utils.buildMusicAssetPatch).toBe('function')
    expect(utils.buildMusicAssetPatch({
      id: 'music-tense-01',
      type: 'music',
      label: 'Tense strings - tense',
      style: 'Tense strings',
      mood: 'tense',
    })).toEqual({
      music_cue: {
        asset_id: 'music-tense-01',
        style: 'Tense strings',
        name: 'Tense strings - tense',
        mood: 'tense',
      },
      music_cue_simple: null,
    })
  })

  it('appends and deduplicates sound effect assets without dropping existing prompts', () => {
    const utils = scriptSegmentCardUtils as unknown as {
      appendSoundEffectAssetPatch: (
        segment: {
          sound_effects_simple?: string[]
          sound_effects?: Array<string | { asset_id?: string; name?: string }>
        },
        selection: { id: string; type: 'sfx'; label: string; name?: string },
        description?: string,
      ) => unknown
    }

    const first = utils.appendSoundEffectAssetPatch({
      sound_effects_simple: ['风声'],
      sound_effects: [{ asset_id: 'sfx-door', name: '旧木门' }],
    }, {
      id: 'sfx-water',
      type: 'sfx',
      label: '水滴声',
      name: '水滴声',
    }, '持续水滴声，近距离，音量很低')

    expect(first).toEqual({
      sound_effects: [
        { asset_id: 'sfx-door', name: '旧木门' },
        { name: '风声' },
        { asset_id: 'sfx-water', name: '持续水滴声，近距离，音量很低' },
      ],
      sound_effects_simple: [],
    })

    expect(utils.appendSoundEffectAssetPatch({
      sound_effects: (first as { sound_effects: Array<{ asset_id?: string; name: string }> }).sound_effects,
    }, {
      id: 'sfx-water',
      type: 'sfx',
      label: '水滴声',
    }, '更远的水滴声')).toEqual({
      sound_effects: [
        { asset_id: 'sfx-door', name: '旧木门' },
        { name: '风声' },
        { asset_id: 'sfx-water', name: '更远的水滴声' },
      ],
      sound_effects_simple: [],
    })
  })

  it('parses optional numeric input without forcing blank values to zero', () => {
    expect(parseOptionalNumberInput('1.25')).toBe(1.25)
    expect(parseOptionalNumberInput(' 0 ')).toBe(0)
    expect(parseOptionalNumberInput('')).toBeNull()
    expect(parseOptionalNumberInput('abc')).toBeNull()
  })

  it('parses comma separated prompt lists', () => {
    expect(parseCommaSeparatedList(' footsteps, wind ,, rain ')).toEqual([
      'footsteps',
      'wind',
      'rain',
    ])
  })

  it('normalizes voice params safely', () => {
    const params = {
      tts_model: 'seed-tts-2.0-expressive',
      speed: 1.1,
      rate: 1.1,
      character_base_speed: 1.0,
      pitch: 42,
      pitch_ratio: 0.9,
      pitch_semitones: -2,
      character_base_pitch: 50,
    }
    expect(getScriptSegmentVoiceParams({ voice_params: params })).toEqual({
      tts_model: 'seed-tts-2.0-expressive',
    })
    expect(getScriptSegmentVoiceParams({
      voice_params: {
        tts_model: 'minimax-speech-2.8-hd',
        speed: 1.1,
        rate: 1.1,
        character_base_speed: 1.0,
      },
    })).toEqual({
      tts_model: 'minimax-speech-2.8-hd',
      speed: 1.1,
      rate: 1.1,
      character_base_speed: 1.0,
    })
    expect(getScriptSegmentVoiceParams({ voice_params: null })).toEqual({})
  })

  it('removes fixed-voice identity overrides from nested segment payloads', () => {
    const segment = {
      text: 'Line 1',
      pitch: 41,
      voice_description: 'change the speaker identity',
      speed: 1.2,
      voice_params: {
        speaker: 'voice-1',
        tts_model: 'seed-tts-2.0-expressive',
        speed: 0.9,
        rate: 0.9,
        character_base_speed: 1.0,
        pitch: 42,
        voice_description: 'older and hoarse',
        voice_design_prompt: 'design another voice',
        provider_prompt_snapshot: {
          delivery_plan: {
            pace: 'slow',
            pitch_ratio: 0.8,
            character_base_pitch: 50,
          },
        },
      },
    }

    expect(sanitizeScriptSegmentVoiceIdentityControls(segment)).toEqual({
      text: 'Line 1',
      voice_params: {
        speaker: 'voice-1',
        tts_model: 'seed-tts-2.0-expressive',
        provider_prompt_snapshot: {
          delivery_plan: {
            pace: 'slow',
          },
        },
      },
    })
    expect(segment.voice_params.pitch).toBe(42)
  })

  it('summarizes provider prompt inline tag strategy for review display', () => {
    expect(getInlineTagStrategySummary({
      voice_params: {
        provider_prompt_snapshot: {
          provider_prompt: {
            inline_tag_strategy: {
              model_family: 'doubao',
              placement: 'text_prefix',
              style_tags: ['旁白'],
              inline_tags: ['低语', '吸气'],
              use_tag_parser: true,
            },
          },
        },
      },
    })).toEqual({
      modelFamily: 'doubao',
      placement: 'text_prefix',
      tags: ['旁白', '低语', '吸气'],
      useTagParser: true,
    })

    expect(getInlineTagStrategySummary({ voice_params: null })).toBeNull()
  })

  it('formats segment summary labels with robust fallbacks', () => {
    expect(getScriptSegmentTypeLabel({ type: 'dialogue' })).toBe('对白')
    expect(getScriptSegmentTypeLabel({ type: '' })).toBe('旁白')
    expect(getScriptSegmentSpeakerLabel({
      speaker: ' ',
      speaker_name: null,
      character_name: ' Hero ',
      role_name: 'Ignored',
    })).toBe('Hero')
    expect(formatScriptSegmentSummary({
      type: null,
      speaker: '',
      speaker_name: null,
      character_name: null,
      role_name: '',
      emotion: ' calm ',
    }, 2)).toBe('#3 [旁白] 旁白 · 情绪: calm')
  })

  it('prefers simple sound effect prompts and filters empty values', () => {
    expect(getSoundEffectsInputValue({
      sound_effects_simple: [' wind ', '', 'rain'],
      sound_effects: ['ignored'],
    })).toBe('wind,rain')

    expect(getSoundEffectsInputValue({
      sound_effects_simple: [],
      sound_effects: [
        ' footsteps ',
        { name: ' door ' },
        { effect_id: ' bell ' },
        { id: ' creek ' },
        {},
      ],
    })).toBe('footsteps,door,bell,creek')
  })

  it('uses normalized prompt text to decide sound effect preview availability', () => {
    expect(hasPreviewableSoundEffects({ sound_effects_simple: ['  '] })).toBe(false)
    expect(hasPreviewableSoundEffects({ sound_effects: [{}] })).toBe(false)
    expect(hasPreviewableSoundEffects({ sound_effects: [{ name: 'wind' }] })).toBe(true)
  })

  it('normalizes music cue prompts and preview availability', () => {
    expect(getMusicCueInputValue({
      music_cue_simple: ' calm piano ',
      music_cue: { style: 'ignored' },
    })).toBe('calm piano')
    expect(getMusicCueInputValue({
      music_cue_simple: '',
      music_cue: { style: ' suspense ', name: 'ignored' },
    })).toBe('suspense')
    expect(getMusicCueInputValue({
      music_cue_simple: null,
      music_cue: ' ambient ',
    })).toBe('ambient')

    expect(hasPreviewableMusicCue({ music_cue: {} })).toBe(false)
    expect(hasPreviewableMusicCue({ music_cue: { name: 'theme' } })).toBe(true)
  })
})
