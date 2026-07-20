import { describe, expect, it } from 'vitest'

import { selectVisibleCharacterVoices } from '../characterScopeUtils'
import type { CharacterVoiceSetting } from '../types'


const characterVoices: CharacterVoiceSetting[] = [
  {
    characterId: 0,
    name: '旁白',
    voiceId: 'Neil',
    volume: 50,
    speed: 1,
    pitch: 50,
  },
  {
    characterId: 1,
    name: '裴世清',
    voiceId: 'voice-1',
    volume: 50,
    speed: 1,
    pitch: 50,
  },
  {
    characterId: 2,
    name: '苏念慈',
    voiceId: 'voice-2',
    volume: 50,
    speed: 1,
    pitch: 50,
  },
]


describe('audiobook character scope utils', () => {
  it('keeps narrator and selected chapter characters without mutating the full list', () => {
    const visible = selectVisibleCharacterVoices({
      characterVoices,
      scopedCharacterIds: [2],
      showAll: false,
    })

    expect(visible.map((voice) => voice.characterId)).toEqual([0, 2])
    expect(characterVoices.map((voice) => voice.characterId)).toEqual([0, 1, 2])
  })

  it('returns every project voice when show all is enabled', () => {
    const visible = selectVisibleCharacterVoices({
      characterVoices,
      scopedCharacterIds: [2],
      showAll: true,
    })

    expect(visible).toEqual(characterVoices)
  })
})
