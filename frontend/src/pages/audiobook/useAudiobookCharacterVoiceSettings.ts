import { useCallback } from 'react'

import type { CharacterVoiceSetting, TtsModel, VoicePreset } from './types'

const parseMimoVoiceAssetId = (voiceId: string): string | undefined => {
  const trimmed = voiceId.trim()
  if (trimmed.startsWith('mimo_clone:')) {
    return trimmed.slice('mimo_clone:'.length).trim() || undefined
  }
  if (trimmed.startsWith('mimo_design:')) {
    return trimmed.slice('mimo_design:'.length).trim() || undefined
  }
  return undefined
}

const parseStepAudioVoiceAssetId = (voiceId: string): string | undefined => {
  const trimmed = voiceId.trim()
  if (trimmed.startsWith('stepaudio_clone:')) {
    return trimmed.slice('stepaudio_clone:'.length).trim() || undefined
  }
  return undefined
}

type UpdateCharacterVoicesForCurrentModel = (
  updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[],
) => void

interface UseAudiobookCharacterVoiceSettingsParams {
  voicePresets: VoicePreset[]
  updateCharacterVoicesForCurrentModel: UpdateCharacterVoicesForCurrentModel
}

export const useAudiobookCharacterVoiceSettings = ({
  voicePresets,
  updateCharacterVoicesForCurrentModel,
}: UseAudiobookCharacterVoiceSettingsParams) => {
  const patchCharacterVoice = useCallback((
    characterId: number,
    buildPatch: (current: CharacterVoiceSetting) => Partial<CharacterVoiceSetting>,
  ) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) =>
        item.characterId === characterId
          ? { ...item, ...buildPatch(item) }
          : item,
      ),
    )
  }, [updateCharacterVoicesForCurrentModel])

  const handleVoiceChange = useCallback((characterId: number, voiceId: string) => {
    const preset = voicePresets.find((item) => item.id === voiceId)
    patchCharacterVoice(characterId, (current) => {
      const mimoVoiceAssetId = parseMimoVoiceAssetId(voiceId)
      const stepaudioVoiceAssetId = parseStepAudioVoiceAssetId(voiceId)
      const patch: Partial<CharacterVoiceSetting> = {
        voiceId,
        source: 'user',
        mimoVoiceAssetId,
        stepaudioVoiceAssetId,
        ...(mimoVoiceAssetId ? { voiceCloneDataUrl: undefined, voiceDesignPrompt: undefined } : {}),
      }
      if (!current.voiceId && preset?.default_params) {
        patch.volume = preset.default_params.volume ?? current.volume
        patch.speed = preset.default_params.speed ?? current.speed
        patch.pitch = preset.default_params.pitch ?? current.pitch
      }
      return patch
    })
  }, [patchCharacterVoice, voicePresets])

  const handleTtsModelChangeForCharacter = useCallback((characterId: number, nextModel: TtsModel | 'inherit') => {
    if (nextModel === 'inherit') {
      patchCharacterVoice(characterId, () => ({ ttsModel: undefined, source: 'user' }))
      return
    }

    patchCharacterVoice(characterId, () => ({ ttsModel: nextModel, source: 'user' }))
  }, [patchCharacterVoice])

  const handleVoiceCloneDataUrlChange = useCallback((characterId: number, voiceCloneDataUrl: string) => {
    patchCharacterVoice(characterId, () => ({ voiceCloneDataUrl: voiceCloneDataUrl || undefined, source: 'user' }))
  }, [patchCharacterVoice])

  return {
    handleVoiceChange,
    handleTtsModelChangeForCharacter,
    handleVoiceCloneDataUrlChange,
  }
}
