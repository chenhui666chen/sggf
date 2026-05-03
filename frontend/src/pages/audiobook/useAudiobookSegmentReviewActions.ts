import { useCallback, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type {
  AudiobookEditorSessionState,
  ScriptSegment,
  TtsModel,
} from './types'

type SegmentReviews = NonNullable<AudiobookEditorSessionState['segmentReviews']>

interface UseAudiobookSegmentReviewActionsParams {
  audiobookProjectId?: number | null
  chapterId?: number | null
  ttsModel: TtsModel
  setSnackbar: SetSnackbar
}

export const useAudiobookSegmentReviewActions = ({
  audiobookProjectId,
  chapterId,
  ttsModel,
  setSnackbar,
}: UseAudiobookSegmentReviewActionsParams) => {
  const [reviewMode, setReviewMode] = useState(false)
  const [segmentReviews, setSegmentReviews] = useState<SegmentReviews>({})
  const [regeneratingSegments, setRegeneratingSegments] = useState<Set<number>>(() => new Set())

  const resetSegmentReviewState = useCallback(() => {
    setReviewMode(false)
    setSegmentReviews({})
    setRegeneratingSegments(new Set())
  }, [])

  const handleToggleReviewMode = useCallback(() => {
    setReviewMode((prev) => !prev)
  }, [])

  const handleReviewSegment = useCallback(async (index: number, score: number) => {
    if (!audiobookProjectId || !chapterId) return
    try {
      await apiClient.reviewSegment(audiobookProjectId, chapterId, index, { quality_score: score })
      setSegmentReviews((prev) => ({ ...prev, [index]: { quality_score: score } }))
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '保存评分失败')
      setSnackbar({ open: true, message, severity: 'error' })
    }
  }, [audiobookProjectId, chapterId, setSnackbar])

  const handleRegenerateSegment = useCallback(async (index: number, segment: ScriptSegment) => {
    if (!audiobookProjectId || !chapterId) return
    setRegeneratingSegments((prev) => new Set([...prev, index]))
    try {
      const voiceParams = segment.voice_params || {}
      await apiClient.regenerateSegment(audiobookProjectId, chapterId, index, {
        reason: '质量不满意',
        tts_model: ttsModel,
        voice_id: voiceParams.speaker ?? undefined,
        emotion: voiceParams.emotion ?? undefined,
      })
      setSnackbar({ open: true, message: `片段 #${index + 1} 重新生成成功`, severity: 'success' })
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '请稍后重试')
      setSnackbar({ open: true, message: `重新生成失败: ${message}`, severity: 'error' })
    } finally {
      setRegeneratingSegments((prev) => {
        const next = new Set(prev)
        next.delete(index)
        return next
      })
    }
  }, [audiobookProjectId, chapterId, setSnackbar, ttsModel])

  return {
    reviewMode,
    setReviewMode,
    segmentReviews,
    setSegmentReviews,
    regeneratingSegments,
    resetSegmentReviewState,
    handleToggleReviewMode,
    handleReviewSegment,
    handleRegenerateSegment,
  }
}
