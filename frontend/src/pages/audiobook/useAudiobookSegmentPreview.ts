import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { PlayAudioOptions, SetSnackbar } from './hookTypes'
import type {
  PreviewType,
  ScriptSegment,
  TtsModel,
} from './types'

interface UseAudiobookSegmentPreviewParams {
  audiobookProjectId?: number | null
  chapterId?: number | null
  ttsModel: TtsModel
  playingChapter: number | null
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
  playExternalUrl: (url: string, options?: PlayAudioOptions) => Promise<unknown>
  stopManagedPlayback: () => void
  onResetSegmentDetails?: () => void
  setSnackbar: SetSnackbar
}

const revokeObjectUrlMap = (urls: Record<number, string>) => {
  Object.values(urls).forEach((url) => {
    if (url) {
      window.URL.revokeObjectURL(url)
    }
  })
}

export const useAudiobookSegmentPreview = ({
  audiobookProjectId,
  chapterId,
  ttsModel,
  playingChapter,
  setPlayingChapter,
  playExternalUrl,
  stopManagedPlayback,
  onResetSegmentDetails,
  setSnackbar,
}: UseAudiobookSegmentPreviewParams) => {
  const [segmentPreviewingIndex, setSegmentPreviewingIndex] = useState<number | null>(null)
  const [segmentPreviewingType, setSegmentPreviewingType] = useState<PreviewType | null>(null)
  const [segmentAudioUrls, setSegmentAudioUrls] = useState<Record<number, string>>({})
  const segmentAudioUrlsRef = useRef<Record<number, string>>({})
  const previewRequestVersionRef = useRef(0)

  const clearPreviewingState = useCallback(() => {
    setSegmentPreviewingIndex(null)
    setSegmentPreviewingType(null)
  }, [])

  const releaseSegmentAudioUrls = useCallback(() => {
    revokeObjectUrlMap(segmentAudioUrlsRef.current)
    segmentAudioUrlsRef.current = {}
  }, [])

  const resetSegmentPreviewState = useCallback(() => {
    previewRequestVersionRef.current += 1
    releaseSegmentAudioUrls()
    setSegmentAudioUrls({})
    clearPreviewingState()
    onResetSegmentDetails?.()
  }, [clearPreviewingState, onResetSegmentDetails, releaseSegmentAudioUrls])

  useEffect(() => () => {
    previewRequestVersionRef.current += 1
    releaseSegmentAudioUrls()
  }, [releaseSegmentAudioUrls])

  const handlePreviewScriptSegmentAudio = useCallback(async (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
  ) => {
    if (!audiobookProjectId || !chapterId) return
    const textValue = String(segment?.text || '').trim()
    if (!textValue) {
      setSnackbar({ open: true, message: '片段文本为空，无法生成音频', severity: 'warning' })
      return
    }

    const requestVersion = previewRequestVersionRef.current + 1
    previewRequestVersionRef.current = requestVersion
    const isCurrentPreviewRequest = () => previewRequestVersionRef.current === requestVersion

    setSegmentPreviewingIndex(index)
    setSegmentPreviewingType(previewType)
    try {
      if (playingChapter) {
        stopManagedPlayback()
        setPlayingChapter(null)
      }

      const response = await apiClient.previewScriptSegmentAudio(
        audiobookProjectId,
        chapterId,
        { segment, tts_model: ttsModel, preview_type: previewType },
      )
      const url = window.URL.createObjectURL(response.data)

      if (!isCurrentPreviewRequest()) {
        window.URL.revokeObjectURL(url)
        return
      }

      setSegmentAudioUrls((prev) => {
        const existing = prev[index]
        if (existing) {
          window.URL.revokeObjectURL(existing)
        }
        const next = { ...prev, [index]: url }
        segmentAudioUrlsRef.current = next
        return next
      })
      await playExternalUrl(url, {
        onEnded: () => {
          if (isCurrentPreviewRequest()) {
            clearPreviewingState()
          }
        },
      })
      if (isCurrentPreviewRequest()) {
        setSnackbar({ open: true, message: '片段音频已生成并开始播放', severity: 'success' })
      }
    } catch (error) {
      if (isCurrentPreviewRequest()) {
        setSnackbar({
          open: true,
          message: await extractApiErrorMessage(error) || '生成片段音频失败，请重试',
          severity: 'error',
        })
      }
    } finally {
      if (isCurrentPreviewRequest()) {
        clearPreviewingState()
      }
    }
  }, [
    audiobookProjectId,
    chapterId,
    clearPreviewingState,
    playExternalUrl,
    playingChapter,
    setPlayingChapter,
    setSnackbar,
    stopManagedPlayback,
    ttsModel,
  ])

  return {
    segmentPreviewingIndex,
    segmentPreviewingType,
    segmentAudioUrls,
    resetSegmentPreviewState,
    handlePreviewScriptSegmentAudio,
  }
}
