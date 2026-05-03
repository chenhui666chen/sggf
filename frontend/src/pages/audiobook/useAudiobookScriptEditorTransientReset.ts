import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import type { AudiobookEditorSessionState } from './types'

interface UseAudiobookScriptEditorTransientResetParams {
  resetSegmentPreviewState: () => void
  resetSegmentReviewState: () => void
  setEditorCrossTabConflict: Dispatch<SetStateAction<AudiobookEditorSessionState | null>>
  dismissedEditorConflictSignatureRef: MutableRefObject<string | null>
}

export const useAudiobookScriptEditorTransientReset = ({
  resetSegmentPreviewState,
  resetSegmentReviewState,
  setEditorCrossTabConflict,
  dismissedEditorConflictSignatureRef,
}: UseAudiobookScriptEditorTransientResetParams) => {
  const resetScriptEditorTransientState = useCallback(() => {
    resetSegmentPreviewState()
    setEditorCrossTabConflict(null)
    dismissedEditorConflictSignatureRef.current = null
    resetSegmentReviewState()
  }, [
    dismissedEditorConflictSignatureRef,
    resetSegmentPreviewState,
    resetSegmentReviewState,
    setEditorCrossTabConflict,
  ])

  return {
    resetScriptEditorTransientState,
  }
}
