import { useCallback, type Dispatch, type SetStateAction } from 'react'

import {
  apiClient,
  extractApiErrorMessage,
} from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type {
  AudiobookProjectDetail,
  Chapter,
  ScriptEditorChapterRef,
  ScriptEditorStateData,
  SmartChunkPreviewResult,
  TimelineClipEditMap,
} from './types'
import {
  buildScriptEditorChapterRef,
  buildUpdateChapterScriptPayload,
  normalizeAudiobookChapterScriptData,
  normalizeSmartChunkPreviewResponse,
} from './scriptEditorUtils'

interface UseAudiobookScriptEditorActionsParams {
  audiobookProject: AudiobookProjectDetail | null
  chapters: Chapter[]
  scriptEditorChapter: ScriptEditorChapterRef | null
  scriptEditorData: ScriptEditorStateData | null
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<AudiobookProjectDetail>
  resetScriptEditorTransientState: () => void
  resetSegmentPreviewState: () => void
  removeCurrentEditorSyncEntry: () => void
  stopManagedPlayback: () => void
  setScriptEditorDialogOpen: Dispatch<SetStateAction<boolean>>
  setScriptEditorChapter: Dispatch<SetStateAction<ScriptEditorChapterRef | null>>
  setScriptEditorData: Dispatch<SetStateAction<ScriptEditorStateData | null>>
  setScriptEditorLoading: Dispatch<SetStateAction<boolean>>
  setSmartChunkPreview: Dispatch<SetStateAction<SmartChunkPreviewResult | null>>
  setSmartChunkPreviewLoading: Dispatch<SetStateAction<boolean>>
  setTimelineEdits: Dispatch<SetStateAction<TimelineClipEditMap>>
  setSnackbar: SetSnackbar
}

export const useAudiobookScriptEditorActions = ({
  audiobookProject,
  chapters,
  scriptEditorChapter,
  scriptEditorData,
  refreshAudiobookProjectDetail,
  resetScriptEditorTransientState,
  resetSegmentPreviewState,
  removeCurrentEditorSyncEntry,
  stopManagedPlayback,
  setScriptEditorDialogOpen,
  setScriptEditorChapter,
  setScriptEditorData,
  setScriptEditorLoading,
  setSmartChunkPreview,
  setSmartChunkPreviewLoading,
  setTimelineEdits,
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
  }) => {
    if (!audiobookProject || !scriptEditorChapter || !scriptEditorData) return

    try {
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

      if (options.nextStatus) {
        setScriptEditorData((current) => current
          ? { ...current, scriptStatus: options.nextStatus as 'reviewed' | 'approved' }
          : current)
      }

      try {
        await refreshAudiobookProjectDetail(audiobookProject.id)
      } catch {
        setSnackbar({
          open: true,
          message: '剧本已保存，但项目状态刷新失败，请重新打开项目',
          severity: 'warning',
        })
        return
      }
      setSnackbar({
        open: true,
        message: options.nextStatus === 'approved' ? '剧本已批准' : '剧本已保存',
        severity: 'success',
      })
    } catch (err: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(err, '保存失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setScriptEditorLoading(false)
    }
  }, [
    audiobookProject,
    refreshAudiobookProjectDetail,
    resetSegmentPreviewState,
    scriptEditorChapter,
    scriptEditorData,
    setScriptEditorData,
    setScriptEditorLoading,
    setSnackbar,
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
