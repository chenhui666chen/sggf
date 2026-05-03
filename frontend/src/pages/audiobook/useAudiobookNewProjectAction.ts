import { useCallback, type Dispatch, type SetStateAction } from 'react'

import type { TaskPointsPrecheckErrorDetail } from '../../services/api'
import type { AudiobookProjectDetail, Project } from './types'

interface UseAudiobookNewProjectActionParams {
  clearActiveGenerationState: () => void
  resetBrowserPlayer: () => void
  stopManagedPlayback: () => void
  setActiveStep: Dispatch<SetStateAction<number>>
  setSelectedProject: Dispatch<SetStateAction<Project | null>>
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
  setTaskPointsPrecheckError: Dispatch<SetStateAction<TaskPointsPrecheckErrorDetail | null>>
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
}

export const useAudiobookNewProjectAction = ({
  clearActiveGenerationState,
  resetBrowserPlayer,
  stopManagedPlayback,
  setActiveStep,
  setSelectedProject,
  setAudiobookProject,
  setTaskPointsPrecheckError,
  setPlayingChapter,
}: UseAudiobookNewProjectActionParams) => {
  const handleCreateNewAudiobookProject = useCallback(() => {
    clearActiveGenerationState()
    setActiveStep(0)
    setSelectedProject(null)
    setAudiobookProject(null)
    setTaskPointsPrecheckError(null)
    resetBrowserPlayer()
    stopManagedPlayback()
    setPlayingChapter(null)
  }, [
    clearActiveGenerationState,
    resetBrowserPlayer,
    setActiveStep,
    setAudiobookProject,
    setPlayingChapter,
    setSelectedProject,
    setTaskPointsPrecheckError,
    stopManagedPlayback,
  ])

  return {
    handleCreateNewAudiobookProject,
  }
}
