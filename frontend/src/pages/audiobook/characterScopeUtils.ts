import type { CharacterVoiceSetting } from './types'


export const selectVisibleCharacterVoices = ({
  characterVoices,
  scopedCharacterIds,
  showAll,
}: {
  characterVoices: readonly CharacterVoiceSetting[]
  scopedCharacterIds: readonly number[]
  showAll: boolean
}): CharacterVoiceSetting[] => {
  if (showAll) {
    return [...characterVoices]
  }

  const visibleIds = new Set(scopedCharacterIds)
  visibleIds.add(0)
  return characterVoices.filter((voice) => visibleIds.has(voice.characterId))
}
