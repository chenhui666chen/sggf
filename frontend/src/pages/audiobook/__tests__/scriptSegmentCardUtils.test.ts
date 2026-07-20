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
    const params = { speed: 1.1, pitch: 42 }
    expect(getScriptSegmentVoiceParams({ voice_params: params })).toBe(params)
    expect(getScriptSegmentVoiceParams({ voice_params: null })).toEqual({})
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
