import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { CharacterVoiceSetting, TtsModel } from './types'

interface UseAudiobookCharacterVoicePreviewParams {
  ttsModel: TtsModel
  playingChapter: number | null
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
  playManagedBlob: (blob: Blob) => Promise<unknown>
  setSnackbar: SetSnackbar
}

export const useAudiobookCharacterVoicePreview = ({
  ttsModel,
  playingChapter,
  setPlayingChapter,
  playManagedBlob,
  setSnackbar,
}: UseAudiobookCharacterVoicePreviewParams) => {
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)

  const handlePreviewCharacterVoice = useCallback(async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId) {
      setSnackbar({ open: true, message: '请先为该角色选择音色再试听', severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const modelForPreview = cv.ttsModel || ttsModel
      const response = await apiClient.previewTTS({
        text: '当你真的喜欢一个人的时候就容易说傻话办蠢事。',
        voice_id: cv.voiceId,
        volume: cv.volume,
        speed: cv.speed,
        pitch: cv.pitch,
        model: modelForPreview,
      })

      if (playingChapter) {
        setPlayingChapter(null)
      }
      await playManagedBlob(response.data)
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '角色音试听失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setPreviewingCharacterId(null)
    }
  }, [playManagedBlob, playingChapter, setPlayingChapter, setSnackbar, ttsModel])

  return {
    previewingCharacterId,
    handlePreviewCharacterVoice,
  }
}
