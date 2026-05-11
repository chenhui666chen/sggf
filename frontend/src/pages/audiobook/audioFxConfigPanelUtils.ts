import type { AudioFxConfig } from './types'

const DEFAULT_ENABLED_DENSITY: AudioFxConfig['sound_effect_density'] = 'medium'

export const buildSoundEffectsTogglePatch = (
  checked: boolean,
  currentDensity: AudioFxConfig['sound_effect_density'],
): Pick<AudioFxConfig, 'enable_sound_effects' | 'sound_effect_density'> => ({
  enable_sound_effects: checked,
  sound_effect_density: checked
    ? currentDensity === 'off'
      ? DEFAULT_ENABLED_DENSITY
      : currentDensity
    : 'off',
})

export const buildMusicTogglePatch = (
  checked: boolean,
  currentDensity: AudioFxConfig['music_density'],
): Pick<AudioFxConfig, 'enable_music' | 'music_density'> => ({
  enable_music: checked,
  music_density: checked
    ? currentDensity === 'off'
      ? DEFAULT_ENABLED_DENSITY
      : currentDensity
    : 'off',
})
