import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { CharacterVoiceSetting, TtsModel } from './types'
import { DEFAULT_CHARACTER_VOICE_PREVIEW_TEXT } from './voicePreviewText'

interface UseAudiobookCharacterVoicePreviewParams {
  ttsModel: TtsModel
  playingChapter: number | null
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
  playManagedBlob: (blob: Blob) => Promise<unknown>
  playExternalUrl: (url: string) => Promise<unknown>
  setSnackbar: SetSnackbar
}

export const useAudiobookCharacterVoicePreview = ({
  ttsModel,
  playingChapter,
  setPlayingChapter,
  playManagedBlob,
  playExternalUrl,
  setSnackbar,
}: UseAudiobookCharacterVoicePreviewParams) => {
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)

  const handlePreviewCharacterVoice = useCallback(async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId.trim()) {
      setSnackbar({ open: true, message: '请先为该角色选择音色再试听', severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const modelForPreview = cv.ttsModel || ttsModel
      const result = await apiClient.previewTTSCached({
        text: DEFAULT_CHARACTER_VOICE_PREVIEW_TEXT,
        voice_id: cv.voiceId,
        model: modelForPreview,
      })

      if (playingChapter) {
        setPlayingChapter(null)
      }
      if (result.audioUrl) {
        await playExternalUrl(result.audioUrl)
      } else if (result.blob) {
        await playManagedBlob(result.blob)
      }
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '角色音试听失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setPreviewingCharacterId(null)
    }
  }, [playManagedBlob, playExternalUrl, playingChapter, setPlayingChapter, setSnackbar, ttsModel])

  return {
    previewingCharacterId,
    handlePreviewCharacterVoice,
  }
}
