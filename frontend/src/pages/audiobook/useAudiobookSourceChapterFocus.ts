import { useEffect, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import { extractApiErrorMessage } from '../../services/api'
import {
  buildAudiobookSourceFocusPlan,
  type UserAssetSourceAudiobookFocusMode,
} from '../../utils/userAssetSourceNavigation'
import type { SetSnackbar } from './hookTypes'

interface UseAudiobookSourceChapterFocusParams {
  selectedProjectId: number | null
  requestedAudiobookProjectId: number | null
  requestedSourceChapterId: number | null
  requestedSourceFocus: UserAssetSourceAudiobookFocusMode | null
  loadedAudiobookProjectId: number | null
  currentAudiobookProjectId: number | null
  handledSourceChapterKeyRef: MutableRefObject<string | null>
  clearActiveGenerationState: () => void
  resetBrowserPlayer: () => void
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<unknown>
  handleOpenScriptEditor: (chapterId: number) => Promise<void>
  setActiveStep: Dispatch<SetStateAction<number>>
  setShowHistory: Dispatch<SetStateAction<boolean>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setSnackbar: SetSnackbar
}

export const useAudiobookSourceChapterFocus = ({
  selectedProjectId,
  requestedAudiobookProjectId,
  requestedSourceChapterId,
  requestedSourceFocus,
  loadedAudiobookProjectId,
  currentAudiobookProjectId,
  handledSourceChapterKeyRef,
  clearActiveGenerationState,
  resetBrowserPlayer,
  refreshAudiobookProjectDetail,
  handleOpenScriptEditor,
  setActiveStep,
  setShowHistory,
  setCurrentAudiobookProjectId,
  setSnackbar,
}: UseAudiobookSourceChapterFocusParams) => {
  useEffect(() => {
    const focusPlan = buildAudiobookSourceFocusPlan({
      selectedProjectId,
      requestedAudiobookProjectId,
      requestedSourceChapterId,
      requestedSourceFocus,
      loadedAudiobookProjectId,
      currentAudiobookProjectId,
      handledFocusKey: handledSourceChapterKeyRef.current,
    })
    if (!focusPlan) return

    let cancelled = false

    const focusSourceChapter = async () => {
      setActiveStep(2)
      setShowHistory(false)
      resetBrowserPlayer()
      clearActiveGenerationState()
      setCurrentAudiobookProjectId(focusPlan.targetAudiobookProjectId)

      if (focusPlan.shouldRefreshProject) {
        try {
          await refreshAudiobookProjectDetail(focusPlan.targetAudiobookProjectId)
        } catch (error: unknown) {
          if (!cancelled) {
            handledSourceChapterKeyRef.current = focusPlan.focusKey
            setSnackbar({
              open: true,
              message: await extractApiErrorMessage(error, '加载有声书项目失败'),
              severity: 'error',
            })
          }
        }
        return
      }

      handledSourceChapterKeyRef.current = focusPlan.focusKey
      await handleOpenScriptEditor(focusPlan.chapterId)
    }

    void focusSourceChapter()

    return () => {
      cancelled = true
    }
  }, [
    clearActiveGenerationState,
    currentAudiobookProjectId,
    handleOpenScriptEditor,
    handledSourceChapterKeyRef,
    loadedAudiobookProjectId,
    refreshAudiobookProjectDetail,
    requestedAudiobookProjectId,
    requestedSourceChapterId,
    requestedSourceFocus,
    resetBrowserPlayer,
    selectedProjectId,
    setActiveStep,
    setCurrentAudiobookProjectId,
    setShowHistory,
    setSnackbar,
  ])
}
