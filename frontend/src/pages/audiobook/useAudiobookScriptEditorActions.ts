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
  setScriptEditorInitialSegmentIndex: Dispatch<SetStateAction<number | null>>
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
  setScriptEditorInitialSegmentIndex,
  setScriptEditorLoading,
  setSmartChunkPreview,
  setSmartChunkPreviewLoading,
  setTimelineEdits,
  setSnackbar,
}: UseAudiobookScriptEditorActionsParams) => {
  const handleOpenScriptEditor = useCallback(async (
    chapterId: number,
    initialSegmentIndex?: number | null,
  ) => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先创建有声书项目', severity: 'error' })
      return
    }

    setScriptEditorInitialSegmentIndex(initialSegmentIndex ?? null)
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
      setScriptEditorInitialSegmentIndex(null)
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
    setScriptEditorInitialSegmentIndex,
    setScriptEditorLoading,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setTimelineEdits,
    setSnackbar,
  ])

  const handleReloadScriptEditor = useCallback(async () => {
    if (!audiobookProject || !scriptEditorChapter) return

    try {
      resetScriptEditorTransientState()
      setSmartChunkPreview(null)
      setSmartChunkPreviewLoading(false)
      setTimelineEdits({})

      const res = await apiClient.getAudiobookChapterScript(audiobookProject.id, scriptEditorChapter.chapterId)
      setScriptEditorData(normalizeAudiobookChapterScriptData(res.data))
    } catch (err: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(err, '刷新章节剧本失败，请重新打开工作台'),
        severity: 'warning',
      })
    }
  }, [
    audiobookProject,
    resetScriptEditorTransientState,
    scriptEditorChapter,
    setScriptEditorData,
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
    setScriptEditorInitialSegmentIndex(null)
    setSmartChunkPreview(null)
    setSmartChunkPreviewLoading(false)
    setTimelineEdits({})
  }, [
    removeCurrentEditorSyncEntry,
    resetScriptEditorTransientState,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorInitialSegmentIndex,
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

      const response = await apiClient.updateAudiobookChapterScript(
        audiobookProject.id,
        scriptEditorChapter.chapterId,
        buildUpdateChapterScriptPayload(
          scriptEditorData.scriptSegments,
          options.nextStatus,
        ),
      )

      // 保存后同步服务端按签名/时间线派生的整章音频状态，避免本地 stale 标记失真
      const savedData = response?.data && typeof response.data === 'object'
        ? response.data as Record<string, unknown>
        : null

      setScriptEditorData((current) => {
        if (!current) return current
        const next: ScriptEditorStateData = { ...current }
        if (options.nextStatus) {
          next.scriptStatus = options.nextStatus as 'reviewed' | 'approved'
        }
        if (savedData) {
          if (typeof savedData.chapter_audio_available === 'boolean') {
            next.chapterAudioAvailable = savedData.chapter_audio_available
          }
          if (typeof savedData.chapter_audio_stale === 'boolean') {
            next.chapterAudioStale = savedData.chapter_audio_stale
          }
        }
        return next
      })

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
    handleReloadScriptEditor,
    handleCloseScriptEditorDialog,
    handleSaveScript,
    handlePreviewSmartChunking,
  }
}
