import { useCallback, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  describeTaskPointsPrecheckErrorDetail,
  extractApiErrorMessage,
  extractTaskPointsPrecheckErrorDetail,
  type TaskPointsPrecheckErrorDetail,
} from '../../services/api'
import type { ActivateQueuedAudiobookTask, SetSnackbar } from './hookTypes'
import type { NarrationStyleId } from './narrationStyles'
import {
  buildCreateAudiobookProjectPayload,
  extractQueuedAudiobookProjectTask,
  markResumeCheckpointQueued,
  resolveAudiobookGenerationMode,
  resolveProjectIdForAudiobookGeneration,
  resolveResumeGenerationMode,
} from './generationActionUtils'
import {
  buildAudiobookVoiceConfigPayload,
  buildProjectAudioConfigPayload,
} from './projectAudioConfigUtils'
import {
  buildGenerateAudioFromScriptPayload,
  extractQueuedAudiobookJobId,
} from './scriptEditorUtils'
import type {
  AudioEngineMode,
  AudioFxConfig,
  AudioOutputFormat,
  AudiobookProjectDetail,
  CharacterVoiceSetting,
  GenerationCheckpoint,
  TtsModel,
  VoicePreset,
} from './types'

interface UseAudiobookGenerationActionsParams {
  audiobookProject: AudiobookProjectDetail | null
  generating: boolean
  selectedChapters: number[]
  selectedProjectId: number | null
  routeProjectId: number | null
  characterVoices: CharacterVoiceSetting[]
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
  ttsModel: TtsModel
  currentVoicePresets: VoicePreset[]
  scriptOnlyMode: boolean
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
  ensureCurrentTtsModelReady: () => boolean
  activateQueuedAudiobookTask: ActivateQueuedAudiobookTask
  setGenerating: Dispatch<SetStateAction<boolean>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setLastGenerationMode: Dispatch<SetStateAction<'full' | 'script_only'>>
  setTaskPointsPrecheckError: Dispatch<SetStateAction<TaskPointsPrecheckErrorDetail | null>>
  setResumeCheckpoints: Dispatch<SetStateAction<Record<number, GenerationCheckpoint>>>
  setResumingChapterId: Dispatch<SetStateAction<number | null>>
  setSnackbar: SetSnackbar
}

export const useAudiobookGenerationActions = ({
  audiobookProject,
  generating,
  selectedChapters,
  selectedProjectId,
  routeProjectId,
  characterVoices,
  audioFxConfig,
  audioEngineMode,
  ttsModel,
  currentVoicePresets,
  scriptOnlyMode,
  narrationStyle,
  narrationStylePrompt,
  outputFormat,
  ensureCurrentTtsModelReady,
  activateQueuedAudiobookTask,
  setGenerating,
  setActiveStep,
  setLastGenerationMode,
  setTaskPointsPrecheckError,
  setResumeCheckpoints,
  setResumingChapterId,
  setSnackbar,
}: UseAudiobookGenerationActionsParams) => {
  const { t } = useTranslation()
  const showGenerationError = useCallback(async (error: unknown, fallbackMessage: string) => {
    const precheckDetail = await extractTaskPointsPrecheckErrorDetail(error)
    setTaskPointsPrecheckError(precheckDetail)
    const message = precheckDetail
      ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
      : await extractApiErrorMessage(error, fallbackMessage)
    setSnackbar({
      open: true,
      message: message || fallbackMessage,
      severity: 'error',
    })
  }, [setSnackbar, setTaskPointsPrecheckError])

  const handleGenerateAudioForApprovedChapters = useCallback(async () => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookGenerationActions.completeScriptFirst'), severity: 'error' })
      return
    }
    if (generating) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookGenerationActions.taskInProgress'), severity: 'warning' })
      return
    }
    if (!ensureCurrentTtsModelReady()) return

    try {
      setTaskPointsPrecheckError(null)
      const response = await apiClient.generateAudioFromScripts(
        audiobookProject.id,
        buildGenerateAudioFromScriptPayload({
          ttsModel,
          narrationStyle,
          narrationStylePrompt,
          outputFormat,
        }),
      )

      const jobId = extractQueuedAudiobookJobId(response.data)
      if (!jobId) {
        throw new Error(t('audiobook.useAudiobookGenerationActions.triggerAudioGenerationFailed'))
      }

      await activateQueuedAudiobookTask(audiobookProject.id, jobId, {
        generationMode: 'full',
        successMessage: t('audiobook.useAudiobookGenerationActions.approvedChaptersQueued'),
      })
    } catch (error: unknown) {
      await showGenerationError(error, t('audiobook.useAudiobookGenerationActions.batchGenerationFailed'))
    }
  }, [
    activateQueuedAudiobookTask,
    audiobookProject,
    ensureCurrentTtsModelReady,
    generating,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    setSnackbar,
    setTaskPointsPrecheckError,
    showGenerationError,
    ttsModel,
  ])

  const generateChapters = useCallback(async (chapterIds: number[]) => {
    if (generating) return
    if (!ensureCurrentTtsModelReady()) return

    if (chapterIds.length === 0) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookGenerationActions.selectGeneratableChapter'), severity: 'error' })
      return
    }

    const generationMode = resolveAudiobookGenerationMode(scriptOnlyMode)
    const projectIdForRequest = resolveProjectIdForAudiobookGeneration({
      selectedProjectId,
      routeProjectId,
    })
    if (!projectIdForRequest) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookGenerationActions.projectNotLoaded'), severity: 'error' })
      return
    }

    setTaskPointsPrecheckError(null)
    setGenerating(true)
    setActiveStep(1)
    setLastGenerationMode(generationMode)

    try {
      const projectAudioConfigBody = buildProjectAudioConfigPayload({
        characterVoices,
        audioFxConfig,
        audioEngineMode,
        ttsModel,
        voicePresets: currentVoicePresets,
      })

      let audioConfigWarning: string | null = null
      try {
        await apiClient.updateProjectAudioConfig(projectIdForRequest, projectAudioConfigBody, ttsModel)
      } catch (configError: unknown) {
        const configErrorMessage = await extractApiErrorMessage(
          configError,
          t('audiobook.useAudiobookGenerationActions.audioConfigSaveWarning'),
        )
        audioConfigWarning = configErrorMessage || t('audiobook.useAudiobookGenerationActions.audioConfigSaveWarning')
      }

      const voiceConfigPayload = buildAudiobookVoiceConfigPayload({
        characterVoices,
        ttsModel,
        voicePresets: currentVoicePresets,
      })

      const response = await apiClient.createAudiobookProject(
        buildCreateAudiobookProjectPayload({
          projectId: projectIdForRequest,
          chapterIds,
          voiceConfig: voiceConfigPayload,
          ttsModel,
          generationMode,
          narrationStyle,
          narrationStylePrompt,
          outputFormat,
        }),
      )

      const data = response.data || {}
      const { audiobookProjectId, jobId } = extractQueuedAudiobookProjectTask(data)
      if (!audiobookProjectId || !jobId) {
        throw new Error(t('audiobook.useAudiobookGenerationActions.createAudiobookTaskFailed'))
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        generationMode,
      })
      if (audioConfigWarning) {
        setSnackbar({
          open: true,
          message: t('audiobook.useAudiobookGenerationActions.taskQueuedWithWarning', { warning: audioConfigWarning }),
          severity: 'warning',
        })
      }
    } catch (error: unknown) {
      await showGenerationError(error, t('audiobook.useAudiobookGenerationActions.generationFailed'))
      setGenerating(false)
      setActiveStep(0)
    }
  }, [
    activateQueuedAudiobookTask,
    audioFxConfig,
    audioEngineMode,
    characterVoices,
    currentVoicePresets,
    ensureCurrentTtsModelReady,
    generating,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    routeProjectId,
    scriptOnlyMode,
    selectedProjectId,
    setActiveStep,
    setGenerating,
    setLastGenerationMode,
    setSnackbar,
    setTaskPointsPrecheckError,
    showGenerationError,
    ttsModel,
  ])

  const handleGenerate = useCallback(
    () => generateChapters(selectedChapters),
    [generateChapters, selectedChapters],
  )

  const handleRegenerateChapter = useCallback(
    (chapterId: number) => generateChapters([chapterId]),
    [generateChapters],
  )

  const handleResumeChapterGeneration = useCallback(async (chapterId: number) => {
    if (!audiobookProject?.id) {
      return
    }
    if (generating) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookGenerationActions.taskInProgress'), severity: 'warning' })
      return
    }

    try {
      setTaskPointsPrecheckError(null)
      setResumingChapterId(chapterId)

      const response = await apiClient.resumeChapterGeneration(audiobookProject.id, chapterId)
      const data = response.data || {}
      const jobId = extractQueuedAudiobookJobId(data)
      if (!jobId) {
        throw new Error(t('audiobook.useAudiobookGenerationActions.resumeJobIdMissing'))
      }

      setResumeCheckpoints((prev) =>
        markResumeCheckpointQueued({
          checkpoints: prev,
          chapterId,
          jobId,
        }),
      )

      await activateQueuedAudiobookTask(audiobookProject.id, jobId, {
        generationMode: resolveResumeGenerationMode(data),
        successMessage: t('audiobook.useAudiobookGenerationActions.resumeQueued'),
      })
    } catch (error: unknown) {
      await showGenerationError(error, t('audiobook.useAudiobookGenerationActions.resumeGenerationFailed'))
    } finally {
      setResumingChapterId(null)
    }
  }, [
    activateQueuedAudiobookTask,
    audiobookProject?.id,
    generating,
    setResumeCheckpoints,
    setResumingChapterId,
    setSnackbar,
    setTaskPointsPrecheckError,
    showGenerationError,
  ])

  return {
    handleGenerateAudioForApprovedChapters,
    handleGenerate,
    handleRegenerateChapter,
    handleResumeChapterGeneration,
  }
}
