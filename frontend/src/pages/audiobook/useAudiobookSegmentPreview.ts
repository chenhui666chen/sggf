import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { PlayAudioOptions, SetSnackbar } from './hookTypes'
import type {
  PendingSegmentRegenerationMap,
  PreviewType,
  SegmentPreviewPlaybackOptions,
  ScriptSegment,
  ScriptSegmentTiming,
} from './types'

interface UseAudiobookSegmentPreviewParams {
  audiobookProjectId?: number | null
  chapterId?: number | null
  chapterAudioAvailable?: boolean
  segmentTimings?: readonly ScriptSegmentTiming[]
  pendingSegmentRegenerations: PendingSegmentRegenerationMap
  playingChapter: number | null
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
  playExternalUrl: (url: string, options?: PlayAudioOptions) => Promise<unknown>
  stopManagedPlayback: () => void
  onResetSegmentDetails?: () => void
  setSnackbar: SetSnackbar
}

const PREVIEW_TYPE_LABEL_KEYS: Record<PreviewType, string> = {
  voice: 'audiobook.useAudiobookSegmentPreview.previewVoice',
  sfx: 'audiobook.useAudiobookSegmentPreview.previewSfx',
  bgm: 'audiobook.useAudiobookSegmentPreview.previewBgm',
  mix: 'audiobook.useAudiobookSegmentPreview.previewMix',
}

const resolveSegmentAudioPath = (segment: ScriptSegment, previewType: PreviewType) => {
  if (previewType === 'voice') return segment.audio_path || ''
  if (previewType === 'sfx') return segment.sfx_audio_path || ''
  if (previewType === 'bgm') return segment.bgm_audio_path || ''
  return segment.mix_audio_path || ''
}

const clampSegmentStartRatio = (value: number): number =>
  Math.max(0, Math.min(0.95, value))

export const resolveSegmentTimelineStartTime = (
  segmentTimings: readonly ScriptSegmentTiming[] = [],
  segmentIndex: number,
  startRatio = 0,
): number | null => {
  const timing = segmentTimings.find((item) => Number(item.index) === segmentIndex)
  if (!timing || !Number.isFinite(timing.start) || timing.start < 0) {
    return null
  }

  const end = Number(timing.end)
  const duration = Number(timing.duration)
  const resolvedDuration = Number.isFinite(duration) && duration > 0
    ? duration
    : Number.isFinite(end) && end > timing.start
      ? end - timing.start
      : 0

  return timing.start + resolvedDuration * clampSegmentStartRatio(startRatio)
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
  chapterAudioAvailable = false,
  segmentTimings = [],
  pendingSegmentRegenerations,
  playingChapter,
  setPlayingChapter,
  playExternalUrl,
  stopManagedPlayback,
  onResetSegmentDetails,
  setSnackbar,
}: UseAudiobookSegmentPreviewParams) => {
  const { t } = useTranslation()
  const previewTypeLabel = useCallback((type: PreviewType): string => t(PREVIEW_TYPE_LABEL_KEYS[type]), [t])
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
    options?: SegmentPreviewPlaybackOptions,
  ) => {
    if (!audiobookProjectId || !chapterId) return

    const pendingRegeneration = pendingSegmentRegenerations[index]?.[previewType]
    // options.candidateId 覆盖：候选生成成功后自动播放时，state 尚未更新，避免闭包旧值
    const candidateId = options?.candidateId || pendingRegeneration?.candidateId || ''
    const savedAudioPath = resolveSegmentAudioPath(segment, previewType)
    // 管线生成的音效/配乐没有持久化分轨：无候选且无已存路径时由服务端按时间线实时渲染
    const canPreviewPipelineTimeline = !candidateId
      && !savedAudioPath
      && (previewType === 'sfx' || previewType === 'bgm')
    const shouldUseChapterAudio = !candidateId && !savedAudioPath && previewType === 'mix' && chapterAudioAvailable
    const chapterStartTime = shouldUseChapterAudio
      ? resolveSegmentTimelineStartTime(segmentTimings, index, options?.startRatio ?? 0)
      : null
    if (!candidateId && !savedAudioPath && !shouldUseChapterAudio && !canPreviewPipelineTimeline) {
      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookSegmentPreview.noPreviewAudio', { type: previewTypeLabel(previewType) }),
        severity: 'warning',
      })
      return
    }
    if (shouldUseChapterAudio && chapterStartTime === null) {
      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookSegmentPreview.noChapterTimeline'),
        severity: 'warning',
      })
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

      if (shouldUseChapterAudio) {
        const streamUrl = await apiClient.getAudiobookChapterAudioSignedStreamUrl(
          audiobookProjectId,
          chapterId,
        )
        if (!isCurrentPreviewRequest()) {
          return
        }

        await playExternalUrl(streamUrl, {
          startTime: chapterStartTime ?? 0,
          onEnded: () => {
            if (isCurrentPreviewRequest()) {
              clearPreviewingState()
            }
          },
        })
        if (isCurrentPreviewRequest()) {
          setSnackbar({ open: true, message: t('audiobook.useAudiobookSegmentPreview.chapterMixPlaying'), severity: 'success' })
        }
        return
      }

      const response = await apiClient.getSegmentRegenerationCandidateAudio(
        audiobookProjectId,
        chapterId,
        index,
        candidateId
          ? { candidateId }
          : { audioPath: savedAudioPath, previewType },
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
        startRatio: options?.startRatio,
        onEnded: () => {
          if (isCurrentPreviewRequest()) {
            clearPreviewingState()
          }
        },
      })
      if (isCurrentPreviewRequest()) {
        const versionLabel = candidateId ? t('audiobook.useAudiobookSegmentPreview.candidateVersion') : t('audiobook.useAudiobookSegmentPreview.segmentVersion')
        setSnackbar({ open: true, message: t('audiobook.useAudiobookSegmentPreview.versionAudioPlaying', { version: versionLabel, type: previewTypeLabel(previewType) }), severity: 'success' })
      }
    } catch (error) {
      if (isCurrentPreviewRequest()) {
        setSnackbar({
          open: true,
          message: await extractApiErrorMessage(error) || t('audiobook.useAudiobookSegmentPreview.playbackFailed', { type: previewTypeLabel(previewType) }),
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
    chapterAudioAvailable,
    clearPreviewingState,
    pendingSegmentRegenerations,
    playExternalUrl,
    playingChapter,
    setPlayingChapter,
    setSnackbar,
    t,
    segmentTimings,
    stopManagedPlayback,
  ])

  return {
    segmentPreviewingIndex,
    segmentPreviewingType,
    segmentAudioUrls,
    resetSegmentPreviewState,
    handlePreviewScriptSegmentAudio,
  }
}
