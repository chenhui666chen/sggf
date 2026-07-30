import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import type { TaskPointsPrecheckErrorDetail } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import { loadAudiobookProjectSelectionData } from './projectSelectionLoader'
import type {
  AudioEngineMode,
  AudioFxConfig,
  AudiobookProjectDetail,
  Chapter,
  CharacterVoiceSetting,
  Project,
  TtsModel,
  VoicePreset,
} from './types'

export type AudiobookSelectProjectOptions = {
  skipStepReset?: boolean
  preserveSessionState?: boolean
  ttsModelOverride?: TtsModel
  selectedChapterIds?: number[]
}

interface UseAudiobookProjectSelectionActionsParams {
  ttsModel: TtsModel
  voicePresetsByModel: Partial<Record<TtsModel, VoicePreset[]>>
  clearActiveGenerationState: () => void
  resetBrowserPlayer: () => void
  resetChapterDeleteState: () => void
  setSelectedProject: Dispatch<SetStateAction<Project | null>>
  setTaskPointsPrecheckError: Dispatch<SetStateAction<TaskPointsPrecheckErrorDetail | null>>
  setCharacterVoicesForCurrentModel: (next: CharacterVoiceSetting[]) => void
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
  setChapters: Dispatch<SetStateAction<Chapter[]>>
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
  setAudioFxConfig: Dispatch<SetStateAction<AudioFxConfig>>
  setAudioEngineMode: Dispatch<SetStateAction<AudioEngineMode>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setSnackbar: SetSnackbar
}

export const useAudiobookProjectSelectionActions = ({
  ttsModel,
  voicePresetsByModel,
  clearActiveGenerationState,
  resetBrowserPlayer,
  resetChapterDeleteState,
  setSelectedProject,
  setTaskPointsPrecheckError,
  setCharacterVoicesForCurrentModel,
  setAudiobookProject,
  setChapters,
  setSelectedChapters,
  setAudioFxConfig,
  setAudioEngineMode,
  setActiveStep,
  setSnackbar,
}: UseAudiobookProjectSelectionActionsParams) => {
  const [loadingCharacters, setLoadingCharacters] = useState(false)

  const handleSelectProject = useCallback(async (project: Project, options?: AudiobookSelectProjectOptions) => {
    const resolvedTtsModel = options?.ttsModelOverride ?? ttsModel
    setSelectedProject(project)
    setTaskPointsPrecheckError(null)
    setCharacterVoicesForCurrentModel([])
    resetBrowserPlayer()
    resetChapterDeleteState()

    if (!options?.preserveSessionState) {
      clearActiveGenerationState()
      setAudiobookProject(null)
    }

    try {
      setLoadingCharacters(true)
      const projectSelectionData = await loadAudiobookProjectSelectionData({
        projectId: project.id,
        selectedChapterIds: options?.selectedChapterIds,
        ttsModel: resolvedTtsModel,
        voicePresets: voicePresetsByModel[resolvedTtsModel] || [],
      })

      setChapters(projectSelectionData.chapters)
      setSelectedChapters(projectSelectionData.selectedChapterIds)
      setCharacterVoicesForCurrentModel(projectSelectionData.characterVoices)
      setAudioFxConfig(projectSelectionData.audioFxConfig)
      setAudioEngineMode(projectSelectionData.audioEngineMode)

      if (!options?.skipStepReset) {
        setActiveStep(0)
      }
    } catch {
      setSnackbar({ open: true, message: '网络错误，请重试', severity: 'error' })
    } finally {
      setLoadingCharacters(false)
    }
  }, [
    clearActiveGenerationState,
    resetBrowserPlayer,
    resetChapterDeleteState,
    setActiveStep,
    setAudioFxConfig,
    setAudioEngineMode,
    setAudiobookProject,
    setCharacterVoicesForCurrentModel,
    setChapters,
    setSelectedChapters,
    setSelectedProject,
    setSnackbar,
    setTaskPointsPrecheckError,
    ttsModel,
    voicePresetsByModel,
  ])

  return {
    loadingCharacters,
    handleSelectProject,
  }
}
