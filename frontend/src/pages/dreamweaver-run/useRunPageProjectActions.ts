import { useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage, extractTaskPointsPrecheckErrorDetail, describeTaskPointsPrecheckErrorDetail, type TaskPointsPrecheckErrorDetail } from '@/services/api'
import type { Chapter, DreamweaverRunPreflight as DreamweaverRunPreflightData } from '@/types/dreamweaver'
import {
  readPersistedDreamWeaverRun,
} from '@/utils/dreamweaver'
import { buildDreamweaverRunSourceNavigationPlan } from '@/utils/userAssetSourceNavigation'
import { toChapters, toDreamweaverRunAsyncResponse, buildDreamweaverRunConfig, getThrownErrorMessage } from './runPageHelpers'

interface UseRunPageProjectActionsDeps {
  selectedProjectId: number | null
  lockedProjectId: number | null
  running: boolean
  requestedRunId: string | null
  selectedChapterIds: number[]
  chapters: { id: number }[]
  highQuality: boolean
  qcAllowFail: boolean
  smartTuning: boolean
  abVariant: string
  videoRequireConfirmation: boolean
  promptReviewRequired: boolean
  stylePreset: string
  imageRatio: string
  imageResolution: string
  imageModel: string
  videoModel: string
  videoEditModel: string
  visionModel: string
  enableVideoEdit: boolean
  enableVisionReview: boolean
  enableSafetyAudit: boolean
  safetyFailPolicy: string
  setSelectedProjectId: (id: number | null) => void
  setSelectedChapterIds: (ids: number[] | ((prev: number[]) => number[])) => void
  setChapters: (chapters: Chapter[]) => void
  setLoadingChapters: (loading: boolean) => void
  setError: (error: string | null) => void
  setRunning: (running: boolean) => void
  setTaskId: (id: string | null) => void
  setTaskRunId: (id: string | null) => void
  setTaskStatus: (status: string | null) => void
  setRunPreflight: (preflight: DreamweaverRunPreflightData | null) => void
  setConfigDialogOpen: (open: boolean) => void
  setTaskPointsPrecheckError: (err: TaskPointsPrecheckErrorDetail | null) => void
  resetForNewRun: (options?: { resetPreview?: boolean; resetApprovalState?: boolean; resetRunSpecificState?: boolean }) => void
  resetLockedConfig: () => void
  refreshLockedGenerationConfig: (projectId: number) => Promise<void>
  clearRunAssetPreviews: () => void
  resetDreamweaverEvents: () => void
  handleViewHistoryRun: (runId: string) => void
}

export function useRunPageProjectActions(deps: UseRunPageProjectActionsDeps) {
  const {
    selectedProjectId,
    lockedProjectId,
    running,
    requestedRunId,
    selectedChapterIds,
    chapters,
    highQuality, qcAllowFail, smartTuning, abVariant,
    videoRequireConfirmation, promptReviewRequired, stylePreset,
    imageRatio, imageResolution, imageModel, videoModel,
    videoEditModel, visionModel, enableVideoEdit, enableVisionReview,
    enableSafetyAudit, safetyFailPolicy,
    setSelectedProjectId,
    setSelectedChapterIds,
    setChapters,
    setLoadingChapters,
    setError,
    setRunning,
    setTaskId,
    setTaskRunId,
    setTaskStatus,
    setRunPreflight,
    setConfigDialogOpen,
    setTaskPointsPrecheckError,
    resetForNewRun,
    resetLockedConfig,
    refreshLockedGenerationConfig,
    clearRunAssetPreviews,
    resetDreamweaverEvents,
    handleViewHistoryRun,
  } = deps
  const { t } = useTranslation()

  const autoOpenedConfigDialogRef = useRef(false)
  const handledSourceRunKeyRef = useRef<string | null>(null)

  const handleSelectProject = useCallback(async (projectId: number) => {
    setSelectedProjectId(projectId)
    resetLockedConfig()
    void refreshLockedGenerationConfig(projectId)
    resetForNewRun({ resetPreview: true, resetApprovalState: true })
    setLoadingChapters(true)
    try {
      const res = await apiClient.getChapters(projectId)
      const data = toChapters(res.data)
      setChapters(data)
      setSelectedChapterIds(data.map((c: { id: number }) => c.id))
    } catch (e: unknown) {
      setError(getThrownErrorMessage(e) || t('dreamweaverRun.loadChaptersFailed'))
      setChapters([])
      setSelectedChapterIds([])
    } finally {
      setLoadingChapters(false)
    }
  }, [clearRunAssetPreviews, refreshLockedGenerationConfig, resetDreamweaverEvents, t])

  useEffect(() => {
    if (!lockedProjectId) return
    if (selectedProjectId === lockedProjectId) return
    void handleSelectProject(lockedProjectId)
  }, [handleSelectProject, lockedProjectId, selectedProjectId])

  useEffect(() => {
    const restorePlan = buildDreamweaverRunSourceNavigationPlan({
      selectedProjectId,
      requestedRunId,
      handledRestoreKey: handledSourceRunKeyRef.current,
    })
    if (!restorePlan) return
    handledSourceRunKeyRef.current = restorePlan.restoreKey
    handleViewHistoryRun(restorePlan.runId)
  }, [requestedRunId, selectedProjectId])

  useEffect(() => {
    if (!lockedProjectId) return
    if (autoOpenedConfigDialogRef.current) return
    if (running) return
    const persisted = readPersistedDreamWeaverRun(lockedProjectId)
    if (persisted?.run_id) {
      autoOpenedConfigDialogRef.current = true
      return
    }
    setConfigDialogOpen(true)
    autoOpenedConfigDialogRef.current = true
  }, [lockedProjectId, running])

  const handleToggleChapter = (chapterId: number) => {
    setSelectedChapterIds((prev) =>
      prev.includes(chapterId) ? prev.filter((id) => id !== chapterId) : [...prev, chapterId],
    )
  }

  const handleSelectAll = () => {
    if (selectedChapterIds.length === chapters.length) {
      setSelectedChapterIds([])
    } else {
      setSelectedChapterIds(chapters.map((c) => c.id))
    }
  }

  const handleRun = async (): Promise<boolean> => {
    if (!selectedProjectId || selectedChapterIds.length === 0) {
      setError(t('dreamweaverRun.projectOrChapterRequired'))
      return false
    }
    resetForNewRun({ resetPreview: true, resetApprovalState: true, resetRunSpecificState: true })
    setRunning(true)
    try {
      const config = buildDreamweaverRunConfig({
        highQuality, qcAllowFail, smartTuning, abVariant,
        videoRequireConfirmation, promptReviewRequired, stylePreset,
        imageRatio, imageResolution, imageModel, videoModel,
        videoEditModel, visionModel, enableVideoEdit, enableVisionReview,
        enableSafetyAudit, safetyFailPolicy,
      })
      const res = await apiClient.runDreamweaverAsync(selectedProjectId, selectedChapterIds, config)
      const data = toDreamweaverRunAsyncResponse(res.data)
      if (!data) { setError(t('dreamweaverRun.startResponseInvalid')); return false }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
      setTaskStatus(data.status || 'queued')
      setRunPreflight(data.preflight || null)
      void refreshLockedGenerationConfig(selectedProjectId)
      return true
    } catch (e: unknown) {
      const precheckDetail = await extractTaskPointsPrecheckErrorDetail(e)
      setTaskPointsPrecheckError(precheckDetail)
      setError(
        precheckDetail
          ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
          : ((await extractApiErrorMessage(e, t('dreamweaverRun.submitTaskFailed'))) || t('dreamweaverRun.submitTaskFailed'))
      )
      setRunning(false)
      return false
    }
  }

  return {
    handleSelectProject,
    handleToggleChapter,
    handleSelectAll,
    handleRun,
    autoOpenedConfigDialogRef,
    handledSourceRunKeyRef,
  }
}
