import { useMemo } from 'react'

import { useTranslation } from 'react-i18next'

import { useFormats } from '@/i18n'

import {
  buildAudiobookEditorConflictPreview,
  extractOpenSegmentDetailIndices,
} from './editorSessionUtils'
import type {
  AudiobookEditorSessionState,
  ScriptEditorStateData,
  TimelineClipEditMap,
} from './types'

const SCRIPT_EDITOR_CONFLICT_SEGMENT_PREVIEW_LIMIT = 6

type SegmentReviews = NonNullable<AudiobookEditorSessionState['segmentReviews']>

interface UseAudiobookEditorConflictPreviewParams {
  chapterId?: number | null
  reviewMode: boolean
  segmentDetailsOpen: Record<number, boolean>
  segmentReviews: SegmentReviews
  timelineEdits: TimelineClipEditMap
  scriptEditorData: ScriptEditorStateData | null
  editorCrossTabConflict: AudiobookEditorSessionState | null
}

export const useAudiobookEditorConflictPreview = ({
  chapterId,
  reviewMode,
  segmentDetailsOpen,
  segmentReviews,
  timelineEdits,
  scriptEditorData,
  editorCrossTabConflict,
}: UseAudiobookEditorConflictPreviewParams) => {
  const { t } = useTranslation()
  const { formatMonthDayTimeWithSeconds } = useFormats()

  // 跨标签冲突的时刻要看到秒：两个标签页往往就在同一分钟内先后写入，
  // 少了秒分不出哪一份更新。无效时间继续给 null，不给空串。
  const editorConflictTimeLabel = editorCrossTabConflict?.updatedAt
    ? formatMonthDayTimeWithSeconds(editorCrossTabConflict.updatedAt) || null
    : null

  const editorConflictPreview = useMemo(
    () => buildAudiobookEditorConflictPreview(
      {
        chapterId,
        reviewMode,
        openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
        segmentReviews,
        timelineEdits,
        data: scriptEditorData,
      },
      editorCrossTabConflict,
      t,
    ),
    [
      chapterId,
      reviewMode,
      segmentDetailsOpen,
      segmentReviews,
      timelineEdits,
      scriptEditorData,
      editorCrossTabConflict,
    ],
  )

  const visibleEditorConflictSegmentDiffs = editorConflictPreview?.segmentDiffs.slice(
    0,
    SCRIPT_EDITOR_CONFLICT_SEGMENT_PREVIEW_LIMIT,
  ) || []

  const hiddenEditorConflictSegmentDiffCount = Math.max(
    0,
    (editorConflictPreview?.segmentDiffs.length || 0) - visibleEditorConflictSegmentDiffs.length,
  )

  return {
    editorConflictTimeLabel,
    editorConflictPreview,
    visibleEditorConflictSegmentDiffs,
    hiddenEditorConflictSegmentDiffCount,
  }
}
