import { useCallback, useState } from 'react'

import type { CharacterVoiceSetting } from './types'

export const useAudiobookCharacterVoiceState = () => {
  const [characterVoices, setCharacterVoices] = useState<CharacterVoiceSetting[]>([])

  const setCharacterVoicesForCurrentModel = useCallback(
    (next: CharacterVoiceSetting[]) => {
      setCharacterVoices(next)
    },
    [],
  )

  const updateCharacterVoicesForCurrentModel = useCallback(
    (updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[]) => {
      setCharacterVoices((prev) => updater(prev))
    },
    [],
  )

  return {
    characterVoices,
    setCharacterVoicesForCurrentModel,
    updateCharacterVoicesForCurrentModel,
  }
}
