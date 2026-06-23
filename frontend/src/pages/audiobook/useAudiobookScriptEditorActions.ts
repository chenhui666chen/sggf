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
import type {
  AudiobookProjectDetail,
  AudioOutputFormat,
  Chapter,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
  SmartChunkPreviewResult,
  TimelineClipEditMap,
  TtsModel,
} from './types'
import {
  buildGenerateAudioFromScriptPayload,
  buildScriptEditorChapterRef,
  buildUpdateChapterScriptPayload,
  extractQueuedAudiobookJobId,
  normalizeAudiobookChapterScriptData,
  normalizeSmartChunkPreviewResponse,
} from './scriptEditorUtils'

interface UseAudiobookScriptEditorActionsParams {
  audiobookProject: AudiobookProjectDetail | null
  chapters: Chapter[]
  scriptEditorChapter: ScriptEditorChapterRef | null
  scriptEditorData: ScriptEditorStateData | null
  timelineEdits: TimelineClipEditMap
  ttsModel: TtsModel
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  ensureCurrentTtsModelReady: () => boolean
  resetScriptEditorTransientState: () => void
  resetSegmentPreviewState: () => void
  removeCurrentEditorSyncEntry: () => void
  stopManagedPlayback: () => void
  activateQueuedAudiobookTask: ActivateQueuedAudiobookTask
  setScriptEditorDialogOpen: Dispatch<SetStateAction<boolean>>
  setScriptEditorChapter: Dispatch<SetStateAction<ScriptEditorChapterRef | null>>
  setScriptEditorData: Dispatch<SetStateAction<ScriptEditorStateData | null>>
  setScriptEditorLoading: Dispatch<SetStateAction<boolean>>
  setSmartChunkPreview: Dispatch<SetStateAction<SmartChunkPreviewResult | null>>
  setSmartChunkPreviewLoading: Dispatch<SetStateAction<boolean>>
  setTimelineEdits: Dispatch<SetStateAction<TimelineClipEditMap>>
  setTaskPointsPrecheckError: Dispatch<SetStateAction<TaskPointsPrecheckErrorDetail | null>>
  setSnackbar: SetSnackbar
}

export const useAudiobookScriptEditorActions = ({
  audiobookProject,
  chapters,
  scriptEditorChapter,
  scriptEditorData,
  timelineEdits,
  ttsModel,
  narrationStyle,
  narrationStylePrompt,
  outputFormat,
  generateSubtitle,
  ensureCurrentTtsModelReady,
  resetScriptEditorTransientState,
  resetSegmentPreviewState,
  removeCurrentEditorSyncEntry,
  stopManagedPlayback,
  activateQueuedAudiobookTask,
  setScriptEditorDialogOpen,
  setScriptEditorChapter,
  setScriptEditorData,
  setScriptEditorLoading,
  setSmartChunkPreview,
  setSmartChunkPreviewLoading,
  setTimelineEdits,
  setTaskPointsPrecheckError,
  setSnackbar,
}: UseAudiobookScriptEditorActionsParams) => {
  const handleOpenScriptEditor = useCallback(async (chapterId: number) => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先创建有声书项目', severity: 'error' })
      return
    }

    setScriptEditorChapter(buildScriptEditorChapterRef(chapterId, chapters))

    try {
      resetScriptEditorTransientState()
      setSmartChunkPreview(null)
      setSmartChunkPreviewLoading(false)
      setTimelineEdits({})
      setScriptEditorLoading(true)

      const res = await apiClient.getAudiobookChapterScript(audiobookProject.id, chapterId)
      setScriptEditorData(normalizeAudiobookChapterScriptData(res.data))
      setScriptEditorDialogOpen(true)
    } catch (err: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(err, '获取章节剧本失败'),
        severity: 'error',
      })
    } finally {
      setScriptEditorLoading(false)
    }
  }, [
    audiobookProject,
    chapters,
    resetScriptEditorTransientState,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorDialogOpen,
    setScriptEditorLoading,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setTimelineEdits,
    setSnackbar,
  ])

  const handleCloseScriptEditorDialog = useCallback(() => {
    stopManagedPlayback()
    resetScriptEditorTransientState()
    removeCurrentEditorSyncEntry()
    setScriptEditorDialogOpen(false)
    setScriptEditorData(null)
    setScriptEditorChapter(null)
    setSmartChunkPreview(null)
    setSmartChunkPreviewLoading(false)
    setTimelineEdits({})
  }, [
    removeCurrentEditorSyncEntry,
    resetScriptEditorTransientState,
    setScriptEditorChapter,
    setScriptEditorData,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setTimelineEdits,
    setScriptEditorDialogOpen,
    stopManagedPlayback,
  ])

  const handleSaveScript = useCallback(async (options: {
    nextStatus?: 'reviewed' | 'approved'
    generateAudio?: boolean
  }) => {
    if (!audiobookProject || !scriptEditorChapter || !scriptEditorData) return
    if (options.generateAudio && !ensureCurrentTtsModelReady()) return

    try {
      setTaskPointsPrecheckError(null)
      resetSegmentPreviewState()
      setScriptEditorLoading(true)

      await apiClient.updateAudiobookChapterScript(
        audiobookProject.id,
        scriptEditorChapter.chapterId,
        buildUpdateChapterScriptPayload(
          scriptEditorData.scriptSegments,
          options.nextStatus,
        ),
      )

      if (options.generateAudio) {
        const queueResponse = await apiClient.generateAudioFromScripts(
          audiobookProject.id,
          buildGenerateAudioFromScriptPayload({
            chapterId: scriptEditorChapter.chapterId,
            ttsModel,
            narrationStyle,
            narrationStylePrompt,
            outputFormat,
            generateSubtitle,
            timelineEdits,
          }),
        )

        const jobId = extractQueuedAudiobookJobId(queueResponse.data)
        if (!jobId) {
          throw new Error('音频生成任务未返回 job_id')
        }

        await activateQueuedAudiobookTask(audiobookProject.id, jobId, {
          generationMode: 'full',
          successMessage: '剧本已保存，并已触发该章节音频生成',
        })
      } else {
        setSnackbar({ open: true, message: '剧本已保存', severity: 'success' })
      }
    } catch (err: unknown) {
      const precheckDetail = await extractTaskPointsPrecheckErrorDetail(err)
      setTaskPointsPrecheckError(precheckDetail)
      const message = precheckDetail
        ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
        : await extractApiErrorMessage(err, '保存失败，请稍后重试')
      setSnackbar({
        open: true,
        message: message || '保存失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setScriptEditorLoading(false)
    }
  }, [
    activateQueuedAudiobookTask,
    audiobookProject,
    ensureCurrentTtsModelReady,
    generateSubtitle,
    narrationStyle,
    narrationStylePrompt,
    outputFormat,
    resetSegmentPreviewState,
    scriptEditorChapter,
    scriptEditorData,
    timelineEdits,
    setScriptEditorLoading,
    setSnackbar,
    setTaskPointsPrecheckError,
    ttsModel,
  ])

  const handlePreviewSmartChunking = useCallback(async () => {
    if (!scriptEditorData?.scriptSegments.length) {
      setSnackbar({ open: true, message: '当前章节没有可诊断的剧本片段', severity: 'warning' })
      return
    }

    try {
      setSmartChunkPreviewLoading(true)
      const response = await apiClient.previewSmartChunking(scriptEditorData.scriptSegments)
      setSmartChunkPreview(normalizeSmartChunkPreviewResponse(response.data))
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '分块诊断失败'),
        severity: 'error',
      })
    } finally {
      setSmartChunkPreviewLoading(false)
    }
  }, [
    scriptEditorData,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setSnackbar,
  ])

  return {
    handleOpenScriptEditor,
    handleCloseScriptEditorDialog,
    handleSaveScript,
    handlePreviewSmartChunking,
  }
}
