import { useCallback, type Dispatch, type SetStateAction } from 'react'

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
      setSnackbar({ open: true, message: '请先完成剧本生成', severity: 'error' })
      return
    }
    if (generating) {
      setSnackbar({ open: true, message: '当前已有任务在执行，请稍候', severity: 'warning' })
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
        throw new Error('触发音频生成失败')
      }

      await activateQueuedAudiobookTask(audiobookProject.id, jobId, {
        generationMode: 'full',
        successMessage: '已将已审批章节加入音频生成队列',
      })
    } catch (error: unknown) {
      await showGenerationError(error, '批量生成音频失败，请稍后重试')
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
      setSnackbar({ open: true, message: '请选择一个可生成章节', severity: 'error' })
      return
    }

    const generationMode = resolveAudiobookGenerationMode(scriptOnlyMode)
    const projectIdForRequest = resolveProjectIdForAudiobookGeneration({
      selectedProjectId,
      routeProjectId,
    })
    if (!projectIdForRequest) {
      setSnackbar({ open: true, message: '项目尚未加载完成，请稍后重试', severity: 'error' })
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
          '项目音效/BGM 配置保存失败，本次生成可能不会应用最新音频配置。',
        )
        audioConfigWarning = configErrorMessage || '项目音效/BGM 配置保存失败，本次生成可能不会应用最新音频配置。'
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
        throw new Error('创建有声书任务失败')
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        generationMode,
      })
      if (audioConfigWarning) {
        setSnackbar({
          open: true,
          message: `任务已入队，但${audioConfigWarning}`,
          severity: 'warning',
        })
      }
    } catch (error: unknown) {
      await showGenerationError(error, '生成失败，请重试')
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
      setSnackbar({ open: true, message: '当前已有任务在执行，请稍候', severity: 'warning' })
      return
    }

    try {
      setTaskPointsPrecheckError(null)
      setResumingChapterId(chapterId)

      const response = await apiClient.resumeChapterGeneration(audiobookProject.id, chapterId)
      const data = response.data || {}
      const jobId = extractQueuedAudiobookJobId(data)
      if (!jobId) {
        throw new Error('恢复任务未返回 job_id')
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
        successMessage: '继续生成任务已进入队列',
      })
    } catch (error: unknown) {
      await showGenerationError(error, '继续生成失败，请稍后重试')
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
