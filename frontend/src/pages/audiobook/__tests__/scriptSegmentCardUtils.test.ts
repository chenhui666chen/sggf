import { describe, expect, it } from 'vitest'

import {
  formatScriptSegmentSummary,
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
