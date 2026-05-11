import { describe, expect, it } from 'vitest'

import {
  buildMusicTogglePatch,
  buildSoundEffectsTogglePatch,
} from '../audioFxConfigPanelUtils'

describe('audio fx config panel utils', () => {
  it('turns sound effect density off when sound effects are disabled', () => {
    expect(buildSoundEffectsTogglePatch(false, 'high')).toEqual({
      enable_sound_effects: false,
      sound_effect_density: 'off',
    })
  })

  it('restores a usable sound effect density when sound effects are enabled from off', () => {
    expect(buildSoundEffectsTogglePatch(true, 'off')).toEqual({
      enable_sound_effects: true,
      sound_effect_density: 'medium',
    })
  })

  it('keeps existing usable sound effect density when sound effects stay enabled', () => {
    expect(buildSoundEffectsTogglePatch(true, 'high')).toEqual({
      enable_sound_effects: true,
      sound_effect_density: 'high',
    })
  })

  it('turns music density off when music is disabled', () => {
    expect(buildMusicTogglePatch(false, 'low')).toEqual({
      enable_music: false,
      music_density: 'off',
    })
  })

  it('restores a usable music density when music is enabled from off', () => {
    expect(buildMusicTogglePatch(true, 'off')).toEqual({
      enable_music: true,
      music_density: 'medium',
    })
  })

  it('keeps existing usable music density when music stays enabled', () => {
    expect(buildMusicTogglePatch(true, 'high')).toEqual({
      enable_music: true,
      music_density: 'high',
    })
  })
})
