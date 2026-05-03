import { useCallback, useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import type {
  AudiobookEditorSessionState,
  Chapter,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
} from './types'
import type { SetSnackbar } from './hookTypes'
import {
  buildAudiobookEditorConflictSignature,
  buildSegmentDetailsOpenState,
} from './editorSessionUtils'
import { readStoredAudiobookEditorSession } from './editorSessionStorageUtils'
import { buildScriptEditorChapterRef } from './scriptEditorUtils'

type SegmentReviews = NonNullable<AudiobookEditorSessionState['segmentReviews']>

interface UseAudiobookScriptEditorDraftStateParams {
  editorSessionStorageKey: string
  sessionHydratedRef: MutableRefObject<boolean>
  restoredEditorSessionKeyRef: MutableRefObject<string | null>
  dismissedEditorConflictSignatureRef: MutableRefObject<string | null>
  selectedProjectId: number | null
  audiobookProjectId?: number | null
  chapters: Chapter[]
  scriptEditorDialogOpen: boolean
  editorCrossTabConflict: AudiobookEditorSessionState | null
  setScriptEditorDialogOpen: Dispatch<SetStateAction<boolean>>
  setScriptEditorChapter: Dispatch<SetStateAction<ScriptEditorChapterRef | null>>
  setScriptEditorData: Dispatch<SetStateAction<ScriptEditorStateData | null>>
  setScriptEditorLoading: Dispatch<SetStateAction<boolean>>
  setReviewMode: Dispatch<SetStateAction<boolean>>
  setSegmentReviews: Dispatch<SetStateAction<SegmentReviews>>
  setSegmentDetailsOpen: Dispatch<SetStateAction<Record<number, boolean>>>
  setEditorCrossTabConflict: Dispatch<SetStateAction<AudiobookEditorSessionState | null>>
  setSnackbar: SetSnackbar
}

export const useAudiobookScriptEditorDraftState = ({
  editorSessionStorageKey,
  sessionHydratedRef,
  restoredEditorSessionKeyRef,
  dismissedEditorConflictSignatureRef,
  selectedProjectId,
  audiobookProjectId,
  chapters,
  scriptEditorDialogOpen,
  editorCrossTabConflict,
  setScriptEditorDialogOpen,
  setScriptEditorChapter,
  setScriptEditorData,
  setScriptEditorLoading,
  setReviewMode,
  setSegmentReviews,
  setSegmentDetailsOpen,
  setEditorCrossTabConflict,
  setSnackbar,
}: UseAudiobookScriptEditorDraftStateParams) => {
  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProjectId
    ) {
      return
    }

    const restoreKey = `${selectedProjectId}:${audiobookProjectId}`
    if (restoredEditorSessionKeyRef.current === restoreKey) {
      return
    }
    restoredEditorSessionKeyRef.current = restoreKey

    if (scriptEditorDialogOpen) {
      return
    }

    const storedEntry = readStoredAudiobookEditorSession(sessionStorage, editorSessionStorageKey)
    const savedEditorSession = storedEntry.session
    if (!savedEditorSession) {
      return
    }

    if (
      savedEditorSession.projectId !== selectedProjectId
      || savedEditorSession.audiobookProjectId !== audiobookProjectId
      || !savedEditorSession.chapterId
      || !savedEditorSession.data
    ) {
      return
    }

    setScriptEditorChapter(buildScriptEditorChapterRef(savedEditorSession.chapterId, chapters))
    setScriptEditorData(savedEditorSession.data)
    setReviewMode(Boolean(savedEditorSession.reviewMode))
    setSegmentReviews(savedEditorSession.segmentReviews || {})
    setSegmentDetailsOpen(
      buildSegmentDetailsOpenState(savedEditorSession.openSegmentDetailIndices || []),
    )
    setScriptEditorLoading(false)
    setScriptEditorDialogOpen(true)
  }, [
    audiobookProjectId,
    chapters,
    editorSessionStorageKey,
    restoredEditorSessionKeyRef,
    scriptEditorDialogOpen,
    selectedProjectId,
    sessionHydratedRef,
    setReviewMode,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorDialogOpen,
    setScriptEditorLoading,
    setSegmentDetailsOpen,
    setSegmentReviews,
  ])

  const handleApplyIncomingEditorDraft = useCallback(() => {
    if (!editorCrossTabConflict?.data) {
      return
    }

    setScriptEditorData(editorCrossTabConflict.data)
    setReviewMode(Boolean(editorCrossTabConflict.reviewMode))
    setSegmentReviews(editorCrossTabConflict.segmentReviews || {})
    setSegmentDetailsOpen(
      buildSegmentDetailsOpenState(editorCrossTabConflict.openSegmentDetailIndices || []),
    )
    dismissedEditorConflictSignatureRef.current = null
    setEditorCrossTabConflict(null)
    setSnackbar({
      open: true,
      message: '已载入另一标签页的最新草稿',
      severity: 'info',
    })
  }, [
    dismissedEditorConflictSignatureRef,
    editorCrossTabConflict,
    setEditorCrossTabConflict,
    setReviewMode,
    setScriptEditorData,
    setSegmentDetailsOpen,
    setSegmentReviews,
    setSnackbar,
  ])

  const handleKeepLocalEditorDraft = useCallback(() => {
    const conflictSignature = buildAudiobookEditorConflictSignature(editorCrossTabConflict)
    if (conflictSignature) {
      dismissedEditorConflictSignatureRef.current = conflictSignature
    }
    setEditorCrossTabConflict(null)
    setSnackbar({
      open: true,
      message: '已保留当前标签页草稿；如另一标签页继续修改，会再次提醒',
      severity: 'warning',
    })
  }, [
    dismissedEditorConflictSignatureRef,
    editorCrossTabConflict,
    setEditorCrossTabConflict,
    setSnackbar,
  ])

  return {
    handleApplyIncomingEditorDraft,
    handleKeepLocalEditorDraft,
  }
}
