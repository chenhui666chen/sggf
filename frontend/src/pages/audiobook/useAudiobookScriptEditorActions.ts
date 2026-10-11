import { useCallback, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  extractApiErrorMessage,
} from '../../services/api'
import type { AudiobookProjectSummary } from '../../types/audiobook'
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
  novelProjectId: number | null
  chapters: Chapter[]
  scriptEditorChapter: ScriptEditorChapterRef | null
  scriptEditorData: ScriptEditorStateData | null
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<AudiobookProjectDetail>
  resetScriptEditorTransientState: () => void
  resetSegmentPreviewState: () => void
  removeCurrentEditorSyncEntry: () => void
  stopManagedPlayback: () => void
  setScriptEditorDialogOpen: Dispatch<SetStateAction<boolean>>
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
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
  novelProjectId,
  chapters,
  scriptEditorChapter,
  scriptEditorData,
  refreshAudiobookProjectDetail,
  resetScriptEditorTransientState,
  resetSegmentPreviewState,
  removeCurrentEditorSyncEntry,
  stopManagedPlayback,
  setScriptEditorDialogOpen,
  setAudiobookProject,
  setCurrentAudiobookProjectId,
  setScriptEditorChapter,
  setScriptEditorData,
  setScriptEditorInitialSegmentIndex,
  setScriptEditorLoading,
  setSmartChunkPreview,
  setSmartChunkPreviewLoading,
  setTimelineEdits,
  setSnackbar,
}: UseAudiobookScriptEditorActionsParams) => {
  const { t } = useTranslation()
  const handleOpenScriptEditor = useCallback(async (
    chapterId: number,
    initialSegmentIndex?: number | null,
  ) => {
    let targetProject = audiobookProject
    if (!targetProject && novelProjectId) {
      // 与历史记录入口对齐：detail 缺失时按小说项目查最新已完成的有声书项目补齐，
      // 避免首次进入路由（无会话恢复）时打开工作台报“请先创建有声书项目”
      try {
        const listRes = await apiClient.getAudiobookProjectsByProject(novelProjectId)
        const summaries: AudiobookProjectSummary[] = Array.isArray(listRes.data)
          ? (listRes.data as AudiobookProjectSummary[])
          : []
        const completedSorted = summaries
          .filter((item) => item?.status === 'completed')
          .sort((a, b) => {
            const ta = a?.created_at ? Date.parse(a.created_at) : 0
            const tb = b?.created_at ? Date.parse(b.created_at) : 0
            if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return tb - ta
            const ia = typeof a?.id === 'number' ? a.id : 0
            const ib = typeof b?.id === 'number' ? b.id : 0
            return ib - ia
          })
        const latestCompleted = completedSorted[0]
        if (latestCompleted) {
          const detailRes = await apiClient.getAudiobookProject(latestCompleted.id)
          targetProject = detailRes.data as AudiobookProjectDetail
          setAudiobookProject(targetProject)
          setCurrentAudiobookProjectId(targetProject.id)
        }
      } catch {
        // 自动补齐失败时维持原错误提示，由下方守卫接管
      }
    }
    if (!targetProject) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookScriptEditorActions.createProjectFirst'), severity: 'error' })
      return
    }

    setScriptEditorInitialSegmentIndex(initialSegmentIndex ?? null)
    setScriptEditorChapter(buildScriptEditorChapterRef(chapterId, chapters, t))

    try {
      resetScriptEditorTransientState()
      setSmartChunkPreview(null)
      setSmartChunkPreviewLoading(false)
      setTimelineEdits({})
      setScriptEditorLoading(true)

      const res = await apiClient.getAudiobookChapterScript(targetProject.id, chapterId)
      setScriptEditorData(normalizeAudiobookChapterScriptData(res.data))
      setScriptEditorDialogOpen(true)
    } catch (err: unknown) {
      setScriptEditorInitialSegmentIndex(null)
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(err, t('audiobook.useAudiobookScriptEditorActions.fetchScriptFailed')),
        severity: 'error',
      })
    } finally {
      setScriptEditorLoading(false)
    }
  }, [
    audiobookProject,
    novelProjectId,
    chapters,
    resetScriptEditorTransientState,
    setAudiobookProject,
    setCurrentAudiobookProjectId,
    setScriptEditorChapter,
    setScriptEditorData,
    setScriptEditorDialogOpen,
    setScriptEditorInitialSegmentIndex,
    setScriptEditorLoading,
    setSmartChunkPreview,
    setSmartChunkPreviewLoading,
    setTimelineEdits,
    setSnackbar,
    t,
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
        message: await extractApiErrorMessage(err, t('audiobook.useAudiobookScriptEditorActions.refreshScriptFailed')),
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
    t,
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
  }): Promise<boolean> => {
    if (!audiobookProject || !scriptEditorChapter || !scriptEditorData) return false

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
          message: t('audiobook.useAudiobookScriptEditorActions.savedButRefreshFailed'),
          severity: 'warning',
        })
        // 保存/审批已落库，后续动作（如生成音频）仍可基于服务端状态继续
        return true
      }
      setSnackbar({
        open: true,
        message: options.nextStatus === 'approved' ? t('audiobook.useAudiobookScriptEditorActions.scriptApproved') : t('audiobook.useAudiobookScriptEditorActions.scriptSaved'),
        severity: 'success',
      })
      return true
    } catch (err: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(err, t('audiobook.useAudiobookScriptEditorActions.saveFailed')),
        severity: 'error',
      })
      return false
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
    t,
  ])

  const handlePreviewSmartChunking = useCallback(async () => {
    if (!scriptEditorData?.scriptSegments.length) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookScriptEditorActions.noDiagnosableSegments'), severity: 'warning' })
      return
    }

    try {
      setSmartChunkPreviewLoading(true)
      const response = await apiClient.previewSmartChunking(scriptEditorData.scriptSegments)
      setSmartChunkPreview(normalizeSmartChunkPreviewResponse(response.data))
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookScriptEditorActions.chunkDiagnoseFailed')),
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
    t,
  ])

  return {
    handleOpenScriptEditor,
    handleReloadScriptEditor,
    handleCloseScriptEditorDialog,
    handleSaveScript,
    handlePreviewSmartChunking,
  }
}
