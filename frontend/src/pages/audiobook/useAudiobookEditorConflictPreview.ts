import { useMemo } from 'react'

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
  const editorConflictTimeLabel =
    editorCrossTabConflict?.updatedAt
      ? new Date(editorCrossTabConflict.updatedAt).toLocaleString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
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
