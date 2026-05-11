import { useCallback, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { CharacterVoiceSetting, TtsModel, VoicePreset } from './types'

type UpdateCharacterVoicesForCurrentModel = (
  updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[],
) => void

interface UseAudiobookCharacterVoiceSettingsParams {
  voicePresets: VoicePreset[]
  updateCharacterVoicesForCurrentModel: UpdateCharacterVoicesForCurrentModel
  setSnackbar: SetSnackbar
}

export const useAudiobookCharacterVoiceSettings = ({
  voicePresets,
  updateCharacterVoicesForCurrentModel,
  setSnackbar,
}: UseAudiobookCharacterVoiceSettingsParams) => {
  const [recommendingVoiceTypeId, setRecommendingVoiceTypeId] = useState<number | null>(null)

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
      const patch: Partial<CharacterVoiceSetting> = { voiceId, source: 'user' }
      if (!current.voiceId && preset?.default_params) {
        patch.volume = preset.default_params.volume ?? current.volume
        patch.speed = preset.default_params.speed ?? current.speed
        patch.pitch = preset.default_params.pitch ?? current.pitch
      }
      return patch
    })
  }, [patchCharacterVoice, voicePresets])

  const handleVolumeChange = useCallback((characterId: number, volume: number) => {
    patchCharacterVoice(characterId, () => ({ volume, source: 'user' }))
  }, [patchCharacterVoice])

  const handleSpeedChange = useCallback((characterId: number, speed: number) => {
    patchCharacterVoice(characterId, () => ({ speed, source: 'user' }))
  }, [patchCharacterVoice])

  const handlePitchChange = useCallback((characterId: number, pitch: number) => {
    patchCharacterVoice(characterId, () => ({ pitch, source: 'user' }))
  }, [patchCharacterVoice])

  const handleTtsModelChangeForCharacter = useCallback((characterId: number, nextModel: TtsModel | 'inherit') => {
    if (nextModel === 'inherit') {
      patchCharacterVoice(characterId, () => ({ ttsModel: undefined, source: 'user' }))
      return
    }

    patchCharacterVoice(characterId, () => ({ ttsModel: nextModel, source: 'user' }))
  }, [patchCharacterVoice])

  const handleVoiceTypeChange = useCallback((characterId: number, voiceType: string) => {
    patchCharacterVoice(characterId, () => ({ voiceType: voiceType || undefined, source: 'user' }))
  }, [patchCharacterVoice])

  const handlePersonalityChange = useCallback((characterId: number, personality: string) => {
    patchCharacterVoice(characterId, () => ({ personality: personality || undefined, source: 'user' }))
  }, [patchCharacterVoice])

  const handleEmotionTendencyChange = useCallback((characterId: number, emotionTendency: string) => {
    patchCharacterVoice(characterId, () => ({ emotionTendency: emotionTendency || undefined, source: 'user' }))
  }, [patchCharacterVoice])

  const handleRecommendVoiceType = useCallback(async (characterVoice: CharacterVoiceSetting) => {
    if (recommendingVoiceTypeId !== null) {
      return
    }

    setRecommendingVoiceTypeId(characterVoice.characterId)
    try {
      const response = await apiClient.recommendVoiceType(
        characterVoice.personality || undefined,
        characterVoice.gender || undefined,
      )
      const recommendedTypes = Array.isArray(response.data?.recommended_types)
        ? response.data.recommended_types.filter((item: unknown): item is string =>
          typeof item === 'string' && Boolean(item.trim()),
        )
        : []
      const nextVoiceType = recommendedTypes[0]
      if (!nextVoiceType) {
        setSnackbar({
          open: true,
          message: '暂未找到匹配的声音类型推荐',
          severity: 'warning',
        })
        return
      }

      patchCharacterVoice(characterVoice.characterId, () => ({ voiceType: nextVoiceType, source: 'user' }))
      setSnackbar({
        open: true,
        message: `已为 ${characterVoice.name || '角色'} 推荐声音类型，试听和生成会应用该风格。`,
        severity: 'success',
      })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '推荐声音类型失败'),
        severity: 'error',
      })
    } finally {
      setRecommendingVoiceTypeId(null)
    }
  }, [patchCharacterVoice, recommendingVoiceTypeId, setSnackbar])

  return {
    recommendingVoiceTypeId,
    handleVoiceChange,
    handleVolumeChange,
    handleSpeedChange,
    handlePitchChange,
    handleTtsModelChangeForCharacter,
    handleVoiceTypeChange,
    handlePersonalityChange,
    handleEmotionTendencyChange,
    handleRecommendVoiceType,
  }
}
