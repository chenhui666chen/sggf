﻿import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppLanguage } from '@/i18n'
import { useDreamweaverTaskPolling } from '@/hooks/useDreamweaverTaskPolling'
import { useDreamweaverEventSyncLifecycle } from '@/hooks/useDreamweaverEventSyncLifecycle'
import { useDreamweaverRunHydration } from '@/hooks/useDreamweaverRunHydration'
import { useDreamweaverDerivedState } from '@/hooks/useDreamweaverDerivedState'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import {
  type TaskPointsPrecheckErrorDetail,
} from '@/services/api'
import TaskPointsPrecheckAlert from '@/components/common/TaskPointsPrecheckAlert'
import { useAssetStudioModelCatalog } from '@/hooks/useAssetStudioModelCatalog'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import {
  DREAMWEAVER_STAGES,
  IMAGE_MODEL_OPTIONS,
  SAFETY_FAIL_POLICY_OPTIONS,
  VIDEO_MODEL_OPTIONS,
  VIDEO_EDIT_MODEL_OPTIONS,
  VISION_MODEL_OPTIONS,
} from '@/constants/dreamweaver'
import { useDreamweaverDiagnostics } from '@/hooks/useDreamweaverDiagnostics'
import { useDreamweaverRunTaskState } from '@/hooks/useDreamweaverRunTaskState'
import { useDreamweaverScriptApproval } from '@/hooks/useDreamweaverScriptApproval'
import { useDreamweaverAssetPreviews } from '@/hooks/useDreamweaverAssetPreviews'
import { useDreamweaverDiagnosticDialog } from '@/hooks/useDreamweaverDiagnosticDialog'
import { useDreamweaverDeleteRun } from '@/hooks/useDreamweaverDeleteRun'
import { useDreamweaverMergedVideo } from '@/hooks/useDreamweaverMergedVideo'
import { useDreamweaverLockedConfig } from '@/hooks/useDreamweaverLockedConfig'
import { useDreamweaverBulkDelete } from '@/hooks/useDreamweaverBulkDelete'
import { useDreamweaverRunConfig } from '@/hooks/useDreamweaverRunConfig'
import { useDreamweaverRunAssetPreviews } from '@/hooks/useDreamweaverRunAssetPreviews'
import { useDreamweaverRunHistory } from '@/hooks/useDreamweaverRunHistory'
import { useDreamweaverSnapshotDerived } from '@/hooks/useDreamweaverSnapshotDerived'
import { useDreamweaverRegenDialog } from '@/hooks/useDreamweaverRegenDialog'
import { useDreamweaverPromptEditDialog } from '@/hooks/useDreamweaverPromptEditDialog'
import { useDreamweaverRunPersistence } from '@/hooks/useDreamweaverRunPersistence'
import { useDreamweaverRunSnapshot } from '@/hooks/useDreamweaverRunSnapshot'
import { useDreamweaverEventSync } from '@/hooks/useDreamweaverEventSync'
import { useDreamweaverRunActions } from '@/hooks/useDreamweaverRunActions'
import {
  clearPersistedDreamWeaverRun,
  ratioIsPortrait,
  ratioToCssAspectRatio,
  readPersistedDreamWeaverRun,
  writePersistedDreamWeaverRun,
} from '@/utils/dreamweaver'
import {
  readUserAssetSourceRunId,
} from '@/utils/userAssetSourceNavigation'
import type {
  Chapter,
  DreamweaverRunPreflight as DreamweaverRunPreflightData,
  DreamweaverRunSnapshot,
  DreamweaverRunSummary,
  LibraryAsset,
  LibraryPayload,
  Project,
  RunResult,
} from '@/types/dreamweaver'
import { createRunPageSnapshotRenderer } from './dreamweaver-run/createRunPageSnapshotRenderer'
import { createRunPagePendingRenderer } from './dreamweaver-run/createRunPagePendingRenderer'
import { createRunPageResultRenderer } from './dreamweaver-run/createRunPageResultRenderer'
import { createRunPageDialogRenderer } from './dreamweaver-run/createRunPageDialogRenderer'
import { createRunPageDiagnosticRenderer } from './dreamweaver-run/createRunPageDiagnosticRenderer'
import { createRunPageLibraryRenderer } from './dreamweaver-run/useRunPageLibraryRenderer'
import { createRunPageWorkbenchRenderer } from './dreamweaver-run/createRunPageWorkbenchRenderer'
import { createRunPagePreviewRenderers } from './dreamweaver-run/createRunPagePreviewRenderers'
import { useRunPageProjectActions } from './dreamweaver-run/useRunPageProjectActions'
import {
  getDiagnosticStoryboardPrompt,
  isNotFoundError,
  formatPath,
  copyText,
  safeJsonStringify,
  collectBulkDeleteTargets,
  computeResultDerivedState,
  resolveWaitingKind,
  resolveTaskStateKind,
  resolveCanResumeFromScript,
  resolveCanResumeFromLibrary,
  computeSafetyAuditAlertState,
  buildMissingRoleSet,
  buildLibraryAssetsByRole,
  shouldTreatRunNotFoundAsPending as _shouldTreatRunNotFoundAsPending,
  buildDebugInfoPayload,
  buildConfigDialogSubtitle,
  resolveConfigRunDisabled,
  isRestartDisabled,
  applyGenerationConfig,
  resolveModelOptions,
  applyModelOptionSync,
} from './dreamweaver-run/runPageHelpers'
import {
  DreamweaverRunPageScaffold,
} from './dreamweaver-run/runPageShell'
import { DebugAccordion } from './dreamweaver-run/diagnosticSections'
const DREAMWEAVER_PREVIEW_STEPS = ['dreamweaverRun.previewStepScript', 'dreamweaverRun.previewStepStoryboard', 'dreamweaverRun.previewStepAssets', 'dreamweaverRun.previewStepShots', 'dreamweaverRun.previewStepMerged'] as const

export default function DreamWeaverRunPage() {
  // 历史弹窗的时间文案由 createRunPageDialogRenderer 里的一串纯函数算出来，
  // 那里拿不到 hook，因此把当前语言当 deps 递下去。
  const { t } = useTranslation()
  const { language } = useAppLanguage()
  const navigate = useNavigate()
  const { projectId: projectIdParam } = useParams()
  const [searchParams] = useSearchParams()
  const theme = useTheme()
  const smDown = useMediaQuery(theme.breakpoints.down('sm'))
  const mdDown = useMediaQuery(theme.breakpoints.down('md'))
  const { catalog: assetStudioModelCatalog } = useAssetStudioModelCatalog()
  const configDialogFullScreen = smDown
  const libraryGridCols = smDown ? 1 : mdDown ? 2 : 3
  const dreamweaverImageDefaultModelId = assetStudioModelCatalog?.defaults.dreamweaver_image || 'qwen-image-2.0-pro'
  const dreamweaverVideoDefaultModelId = assetStudioModelCatalog?.defaults.dreamweaver_video || 'wan2.7-t2v'
  const dreamweaverVideoEditDefaultModelId = assetStudioModelCatalog?.defaults.dreamweaver_video_edit || 'wan2.7-videoedit'
  const dreamweaverVisionDefaultModelId = assetStudioModelCatalog?.defaults.dreamweaver_vision || 'qwen3-vl-plus'
  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [selectedChapterIds, setSelectedChapterIds] = useState<number[]>([])
  const [loadingChapters, setLoadingChapters] = useState(false)
  const {
    highQuality, setHighQuality,
    qcAllowFail, setQcAllowFail,
    smartTuning, setSmartTuning,
    videoRequireConfirmation, setVideoRequireConfirmation,
    promptReviewRequired, setPromptReviewRequired,
    abVariant, setAbVariant,
    stylePreset, setStylePreset,
    imageRatio, setImageRatio,
    imageResolution, setImageResolution,
    imageModel, setImageModel,
    videoModel, setVideoModel,
    videoEditModel, setVideoEditModel,
    visionModel, setVisionModel,
    enableVideoEdit, setEnableVideoEdit,
    enableVisionReview, setEnableVisionReview,
    enableSafetyAudit, setEnableSafetyAudit,
    safetyFailPolicy, setSafetyFailPolicy,
  } = useDreamweaverRunConfig()
  const generationConfigSetters = useMemo(() => ({
    setStylePreset,
    setHighQuality,
    setQcAllowFail,
    setSmartTuning,
    setVideoRequireConfirmation,
    setPromptReviewRequired,
    setImageRatio,
    setImageResolution,
    setImageModel,
    setVideoModel,
    setVideoEditModel,
    setVisionModel,
    setEnableVideoEdit,
    setEnableVisionReview,
    setEnableSafetyAudit,
    setSafetyFailPolicy,
  }), [setStylePreset, setHighQuality, setQcAllowFail, setSmartTuning, setVideoRequireConfirmation, setPromptReviewRequired, setImageRatio, setImageResolution, setImageModel, setVideoModel, setVideoEditModel, setVisionModel, setEnableVideoEdit, setEnableVisionReview, setEnableSafetyAudit, setSafetyFailPolicy])
  const {
    running, taskId, taskRunId, taskStatus, taskQueue, taskProgress,
    taskState, taskStage, taskArtifacts, waitingApproval,
    videoJobActionError, videoJobConfirmingShotId,
    setRunning, setTaskId, setTaskRunId, setTaskStatus, setTaskQueue,
    setTaskProgress, setTaskState, setTaskStage, setTaskArtifacts,
    setWaitingApproval, setVideoJobActionError, setVideoJobConfirmingShotId,
    resetTaskState, applyQueuedStatus, applyRunningStatus, applyWaitingStatus,
    applyTerminalStatus, applyCompletedStatus, applyFailedStatus,
  } = useDreamweaverRunTaskState()
  const [resumeLoading, setResumeLoading] = useState(false)
  const [restartLoading, setRestartLoading] = useState(false)
  const [restartAnchorEl, setRestartAnchorEl] = useState<HTMLElement | null>(null)
  const {
    scriptLoading, scriptError, scriptText, scriptApproved,
    scriptRequiresReview, scriptEntities, scriptGeneration,
    scriptDirty, setScriptText, resetScriptState,
    loadScript, saveScript, approveScript, autoLoadIfNeeded,
  } = useDreamweaverScriptApproval()
  const [promptReviewLoading, setPromptReviewLoading] = useState(false)
  const [promptReviewError, setPromptReviewError] = useState<string | null>(null)
  const [safetyAuditApproveLoading, setSafetyAuditApproveLoading] = useState(false)
  const [safetyAuditApproveError, setSafetyAuditApproveError] = useState<string | null>(null)
  const [promptReviewShowAll, setPromptReviewShowAll] = useState(false)
  const promptEditCurrentRunIdRef = useRef<string | null>(null)
  const promptEditLoadRunSnapshotRef = useRef<() => Promise<void>>(async () => {})
  const {
    promptEditOpen,
    promptEditShot,
    promptEditHead,
    promptEditTail,
    promptEditVideo,
    promptEditSaving,
    promptEditError,
    promptEditGenerated,
    setPromptEditHead,
    setPromptEditTail,
    setPromptEditVideo,
    openPromptEditDialog,
    closePromptEditDialog,
    savePromptEdit,
    resetPromptEditState,
  } = useDreamweaverPromptEditDialog({
    currentRunId: promptEditCurrentRunIdRef.current,
    loadRunSnapshot: promptEditLoadRunSnapshotRef.current,
  })
  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const {
    libraryPreviews, libraryPreviewLoading, libraryPreviewErrors,
    setLibraryPreviews, setLibraryPreviewErrors,
    clearLibraryPreviews, resetLibraryPreviews, loadLibraryPreview,
  } = useDreamweaverAssetPreviews()
  const mergedVideoCurrentRunIdRef = useRef<string | null>(null)
  const mergedVideoResultRef = useRef<RunResult | null>(null)
  const mergedVideoRunSnapshotRef = useRef<DreamweaverRunSnapshot | null>(null)
  const mergedVideoProjectIdRef = useRef<number | null>(null)
  const mergedVideoProjectTitleRef = useRef<string | null>(null)
  const {
    mergedVideoLoading,
    mergedVideoError,
    mergedVideoPreviewUrl,
    mergedVideoCollecting,
    mergedVideoCollectFeedback,
    loadMergedVideoPreview,
    downloadMergedVideo,
    collectMergedVideo,
    resetMergedVideoState,
  } = useDreamweaverMergedVideo({
    getCurrentRunId: () => mergedVideoCurrentRunIdRef.current,
    getMergedVideoPath: () => mergedVideoResultRef.current?.merged_video || null,
    getRunSnapshot: () => mergedVideoRunSnapshotRef.current,
    getProjectId: () => mergedVideoProjectIdRef.current,
    getProjectTitle: () => mergedVideoProjectTitleRef.current,
  })
  const runAssetPreviewCurrentRunIdRef = useRef<string | null>(null)
  const {
    runAssetPreviews,
    runAssetPreviewLoading,
    runAssetPreviewErrors,
    loadRunAssetPreview,
    downloadRunAsset,
    clearRunAssetPreviews,
  } = useDreamweaverRunAssetPreviews({
    getCurrentRunId: () => runAssetPreviewCurrentRunIdRef.current,
  })

  const applyStageSignalRef = useRef<(stage: string | null, payload: Record<string, unknown>) => void>(() => {})
  const resetMissingRunStateRef2 = useRef<(projectId: number | null) => void>(() => {})
  const setErrorRef = useRef<(v: string | null) => void>(() => {})

  const {
    eventCursor,
    eventSyncing,
    eventSyncError,
    wsError,
    streamTextByKey,
    streamMetaByKey,
    assetPlanItems,
    libraryPlanItems,
    setLibraryPlanItems,
    setWsError,
    resetDreamweaverEvents,
    applyDreamweaverEvent,
    syncDreamweaverEvents,
  } = useDreamweaverEventSync({
    onApplyStageSignal: (stage, payload) => applyStageSignalRef.current(stage, payload),
    onSetError: (v) => setErrorRef.current(v),
    onSetTaskStatus: setTaskStatus,
    onSetRunning: setRunning,
    onSetWaitingApproval: setWaitingApproval,
    onResetMissingRunState: (projectId) => resetMissingRunStateRef2.current(projectId),
    getSelectedProjectId: () => selectedProjectId,
    getTaskId: () => taskId,
    getTaskStatus: () => taskStatus,
  })

  const {
    dreamweaverImageModelOptions,
    dreamweaverVideoModelOptions,
    dreamweaverVideoEditModelOptions,
    dreamweaverVisionModelOptions,
  } = useMemo(() => ({
    dreamweaverImageModelOptions: resolveModelOptions(assetStudioModelCatalog?.groups.dreamweaver_image, IMAGE_MODEL_OPTIONS),
    dreamweaverVideoModelOptions: resolveModelOptions(assetStudioModelCatalog?.groups.dreamweaver_video, VIDEO_MODEL_OPTIONS),
    dreamweaverVideoEditModelOptions: resolveModelOptions(assetStudioModelCatalog?.groups.dreamweaver_video_edit, VIDEO_EDIT_MODEL_OPTIONS),
    dreamweaverVisionModelOptions: resolveModelOptions(assetStudioModelCatalog?.groups.dreamweaver_vision, VISION_MODEL_OPTIONS),
  }), [assetStudioModelCatalog])

  useEffect(() => {
    const imageNext = applyModelOptionSync(imageModel, dreamweaverImageModelOptions, dreamweaverImageDefaultModelId)
    if (imageNext) setImageModel(imageNext)
    const videoNext = applyModelOptionSync(videoModel, dreamweaverVideoModelOptions, dreamweaverVideoDefaultModelId)
    if (videoNext) setVideoModel(videoNext)
    const videoEditNext = applyModelOptionSync(videoEditModel, dreamweaverVideoEditModelOptions, dreamweaverVideoEditDefaultModelId)
    if (videoEditNext) setVideoEditModel(videoEditNext)
    const visionNext = applyModelOptionSync(visionModel, dreamweaverVisionModelOptions, dreamweaverVisionDefaultModelId)
    if (visionNext) setVisionModel(visionNext)
  }, [dreamweaverImageDefaultModelId, dreamweaverImageModelOptions, imageModel, dreamweaverVideoDefaultModelId, dreamweaverVideoModelOptions, videoModel, dreamweaverVideoEditDefaultModelId, dreamweaverVideoEditModelOptions, videoEditModel, dreamweaverVisionDefaultModelId, dreamweaverVisionModelOptions, visionModel])

  const [result, setResult] = useState<RunResult | null>(null)
  const [runPreflight, setRunPreflight] = useState<DreamweaverRunPreflightData | null>(null)
  const [error, setError] = useState<string | null>(null)
  setErrorRef.current = setError
  const [taskPointsPrecheckError, setTaskPointsPrecheckError] = useState<TaskPointsPrecheckErrorDetail | null>(null)

  const {
    historyOpen,
    setHistoryOpen,
    historyLoading,
    historyError,
    historyRuns,
    historyStatusFilters,
    setHistoryStatusFilters,
    historyStatusCounts,
    filteredHistoryRuns,
    fetchRunHistory,
    openHistoryDialog,
    closeHistoryDialog,
  } = useDreamweaverRunHistory()

  const bulkDeleteTargetsRef = useRef<DreamweaverRunSummary[]>([])
  const filteredHistoryRunsRef = useRef<DreamweaverRunSummary[]>([])
  const fetchRunHistoryRef = useRef<(projectId: number) => Promise<void>>(async () => {})
  const refreshLockedConfigRef = useRef<(projectId: number) => Promise<void>>(async () => {})
  const {
    bulkDeleteDialogOpen,
    bulkDeleteSubmitting,
    bulkDeleteError,
    bulkDeleteProgress,
    bulkDeleteResult,
    openBulkDeleteDialog,
    closeBulkDeleteDialog,
    confirmBulkDeleteRuns,
  } = useDreamweaverBulkDelete({
    getProjectId: () => selectedProjectId,
    getBulkDeleteTargets: () => bulkDeleteTargetsRef.current,
    getFilteredHistoryCount: () => filteredHistoryRunsRef.current.length,
    getPersistedRunId: () => persistedRunIdRef.current,
    onResetCurrentRunState: () => {
      resetForNewRun({ resetPreview: false })
    },
    onClearPersistedRunIfMatch: (projectId, runId) => {
      const persisted = readPersistedDreamWeaverRun(projectId)
      if (persisted?.run_id === runId) {
        clearPersistedDreamWeaverRun(projectId)
      }
    },
    onFetchRunHistory: (projectId) => fetchRunHistoryRef.current(projectId),
    onRefreshLockedGenerationConfig: (projectId) => refreshLockedConfigRef.current(projectId),
  })

  const {
    lockedGenerationConfig,
    lockedGenerationConfigLoading,
    lockedGenerationConfigError,
    refreshLockedGenerationConfig,
    resetLockedConfig,
  } = useDreamweaverLockedConfig()

  refreshLockedConfigRef.current = refreshLockedGenerationConfig

  const {
    diagnosticOpen,
    diagnosticActionLoading,
    diagnosticActionError,
    setDiagnosticActionLoading,
    setDiagnosticActionError,
    openDiagnosticDialog,
    closeDiagnosticDialog,
  } = useDreamweaverDiagnosticDialog()

  const resetMissingRunStateRef = useRef<(projectId: number | null) => void>(() => {})

  const {
    runSnapshot,
    runSnapshotLoading,
    runSnapshotError,
    setRunSnapshot,
    setRunSnapshotError,
    loadRunSnapshot,
    rebuildVideoJobs,
    resetSnapshotState,
  } = useDreamweaverRunSnapshot({
    getPersistedRunId: () => persistedRunId,
    getTaskId: () => taskId,
    getTaskStatus: () => taskStatus,
    getSelectedProjectId: () => selectedProjectId,
    onResetMissingRunState: (projectId) => resetMissingRunStateRef.current(projectId),
    onSetResult: setResult,
    onSetRunPreflight: setRunPreflight,
  })

  const [previewStep, setPreviewStep] = useState(0)
  const [manualPreviewStep, setManualPreviewStep] = useState(false)

  const libraryPreviewAspectRatio = ratioToCssAspectRatio(imageRatio)
  const generationConfigLocked = Boolean(lockedGenerationConfig?.locked)
  const visualFieldsDisabled = running || lockedGenerationConfigLoading || generationConfigLocked
  const missingRoleSet = useMemo(() => buildMissingRoleSet(library), [library?.review])
  const libraryAssetsByRole = useMemo(() => buildLibraryAssetsByRole(library), [library?.assets])

  const mergedVideoPreviewPortrait = ratioIsPortrait(
    generationConfigLocked ? lockedGenerationConfig?.image_ratio : imageRatio,
  )

  const {
    videoDiagnostics,
    planText: resultPlanText,
    videoClipPaths: resultVideoClipPaths,
    candidateFrameUris,
    keyframePaths: resultKeyframePaths,
    midframePaths: resultMidframePaths,
    chapterCount: resultChapterCount,
    keyframeCount: resultKeyframeCount,
    midframeCount: resultMidframeCount,
    videoClipCount: resultVideoClipCount,
  } = useMemo(
    () => computeResultDerivedState(result as Record<string, unknown> | null),
    [result],
  )

  const [configDialogOpen, setConfigDialogOpen] = useState(false)

  const autoLoadedRunSnapshotRunIdRef = useRef<string | null>(null)
  const autoLoadedLibraryRef = useRef(false)

  const resetForNewRun = useCallback(
    (options?: { resetPreview?: boolean; resetApprovalState?: boolean; resetRunSpecificState?: boolean }) => {
      const { resetPreview = true, resetApprovalState = false, resetRunSpecificState = false } = options || {}

      setError(null)
      setResult(null)
      setRunPreflight(null)
      resetTaskState()
      resetSnapshotState()
      resetScriptState()
      setLibrary(null)
      setLibraryError(null)
      resetLibraryPreviews()
      resetMergedVideoState()
      clearRunAssetPreviews()
      resetDreamweaverEvents()

      if (resetPreview) {
        autoLoadedRunSnapshotRunIdRef.current = null
        setPreviewStep(0)
        setManualPreviewStep(false)
      }

      if (resetApprovalState) {
        setSafetyAuditApproveError(null)
      }

      if (resetRunSpecificState) {
        setPromptReviewError(null)
        setPromptReviewShowAll(false)
        resetPromptEditState()
        setTaskPointsPrecheckError(null)
      }
    },
    [clearRunAssetPreviews, resetDreamweaverEvents, resetSnapshotState],
  )

  const resetMissingRunState = useCallback(
    (projectId: number | null) => {
      if (projectId) {
        clearPersistedDreamWeaverRun(projectId)
      }

      resetForNewRun()
    },
    [resetForNewRun],
  )
  resetMissingRunStateRef.current = resetMissingRunState
  resetMissingRunStateRef2.current = resetMissingRunState

  const lockedProjectId = useMemo(() => {
    const parsed = Number(projectIdParam)
    if (!projectIdParam || !Number.isFinite(parsed)) return null
    return parsed
  }, [projectIdParam])
  const requestedRunId = useMemo(() => readUserAssetSourceRunId(searchParams), [searchParams])

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) return null
    return projects.find((p) => p.id === selectedProjectId) || null
  }, [projects, selectedProjectId])

  const copyDebugInfo = async () => {
    const payload = buildDebugInfoPayload({
      selectedProjectId,
      selectedChapterIds,
      highQuality,
      stylePreset,
      imageRatio,
      imageResolution,
      running,
      task: {
        taskId,
        status: taskStatus,
        queue: taskQueue,
        runId: taskRunId,
        progress: taskProgress,
        state: taskState,
        stage: taskStage,
        artifacts: taskArtifacts,
      },
      error,
      preflight: diagnosticPreflight,
      video_provider_trace: diagnosticProviderTrace,
      result,
    })
    await copyText(safeJsonStringify({ page: 'DreamWeaverRunPage', ...payload }), t)
  }

  fetchRunHistoryRef.current = fetchRunHistory

  const bulkDeleteTargets = useMemo(() => collectBulkDeleteTargets(filteredHistoryRuns), [filteredHistoryRuns])
  const bulkDeleteTargetCount = bulkDeleteTargets.length

  const bulkDeleteSkippedCount = Math.max(0, filteredHistoryRuns.length - bulkDeleteTargets.length)

  bulkDeleteTargetsRef.current = bulkDeleteTargets
  filteredHistoryRunsRef.current = filteredHistoryRuns

  const handleViewHistoryRun = (runId: string) => {
    if (!selectedProjectId) return
    const nextRunId = String(runId || '').trim()
    if (!nextRunId) return

    resetForNewRun()
    setTaskRunId(nextRunId)

    writePersistedDreamWeaverRun(selectedProjectId, { run_id: nextRunId, task_id: null, status: null })
    void hydrateFromPersistedRun(selectedProjectId, nextRunId, null, null)
    setHistoryOpen(false)
  }

  const { hydrateFromPersistedRun } = useDreamweaverRunHydration({
    selectedProjectId,
    lockedGenerationConfig,
    generationConfigSetters,
    isNotFoundError,
    shouldTreatRunNotFoundAsPending: _shouldTreatRunNotFoundAsPending,
    resetMissingRunState,
    setProjects,
    setTaskRunId,
    setTaskStatus,
    setTaskProgress,
    setTaskStage,
    setTaskState,
    setTaskId,
    setRunning,
    setWaitingApproval,
    setError,
    setRunSnapshot,
    setRunSnapshotError,
    setRunPreflight,
    setResult,
    applyGenerationConfig,
  })

  useDreamweaverTaskPolling({
    taskId,
    setError,
    setResult,
    setRunPreflight,
    applyQueuedStatus,
    applyRunningStatus,
    applyWaitingStatus,
    applyTerminalStatus,
    applyCompletedStatus,
    applyFailedStatus,
  })

  const persistedRunIdRef = useRef<string | null>(null)

  const {
    deleteRunId,
    deleteDialogOpen,
    deleteSubmitting,
    deleteDialogError,
    openDeleteRunDialog,
    closeDeleteRunDialog,
    confirmDeleteRun,
  } = useDreamweaverDeleteRun({
    getPersistedRunId: () => persistedRunIdRef.current,
    onResetCurrentRunState: () => {
      resetForNewRun()
    },
    onClearPersistedRunIfMatch: (projectId, runId) => {
      const persisted = readPersistedDreamWeaverRun(projectId)
      if (persisted?.run_id === runId) {
        clearPersistedDreamWeaverRun(projectId)
      }
    },
    onFetchRunHistory: fetchRunHistory,
    onRefreshLockedGenerationConfig: refreshLockedGenerationConfig,
    onResetMissingRunState: resetMissingRunState,
    isNotFoundError,
  })

  const {
    handleSelectProject,
    handleToggleChapter,
    handleSelectAll,
    handleRun,
  } = useRunPageProjectActions({
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
  })

  const applyStageSignal = useCallback((stage: string | null, payload: Record<string, unknown>) => {
    if (stage) setTaskStage(stage)
    const stateRaw = typeof payload.state === 'string' ? String(payload.state) : null
    if (stateRaw) setTaskState(stateRaw)
    const progressRaw = typeof payload.progress === 'number' ? payload.progress : null
    if (typeof progressRaw === 'number') setTaskProgress(progressRaw)
    if (stateRaw) {
      const kind = resolveTaskStateKind(stateRaw)
      if (kind === 'waiting') applyWaitingStatus({ queue: null, progress: progressRaw ?? 0, state: stateRaw, stage, run_id: taskRunId, artifacts: null })
      else if (kind === 'done') applyCompletedStatus({ progress: progressRaw ?? 100, state: stateRaw, stage })
      else if (kind === 'failed') applyFailedStatus({ progress: progressRaw ?? 100, state: stateRaw, stage })
      else applyRunningStatus({ queue: null, progress: progressRaw ?? 0, state: stateRaw, stage, run_id: taskRunId, artifacts: null })
    }
  }, [applyWaitingStatus, applyCompletedStatus, applyFailedStatus, applyRunningStatus, taskRunId])
  applyStageSignalRef.current = applyStageSignal

  const waitingKind = resolveWaitingKind(taskStage, taskState)
  const waitingScriptApproval = waitingApproval && waitingKind === DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL
  const waitingVideoConfirmation = waitingApproval && waitingKind === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION
  const runConfig = useMemo(() => ({
    highQuality,
    setHighQuality,
    qcAllowFail,
    setQcAllowFail,
    smartTuning,
    setSmartTuning,
    videoRequireConfirmation,
    setVideoRequireConfirmation,
    promptReviewRequired,
    setPromptReviewRequired,
    abVariant,
    setAbVariant,
    stylePreset,
    setStylePreset,
    imageRatio,
    setImageRatio,
    imageResolution,
    setImageResolution,
    imageModel,
    setImageModel,
    videoModel,
    setVideoModel,
    videoEditModel,
    setVideoEditModel,
    visionModel,
    setVisionModel,
    enableVideoEdit,
    setEnableVideoEdit,
    enableVisionReview,
    setEnableVisionReview,
    enableSafetyAudit,
    setEnableSafetyAudit,
    safetyFailPolicy,
    setSafetyFailPolicy,
    resetConfig: () => {},
  }), [
    highQuality, qcAllowFail, smartTuning, videoRequireConfirmation,
    promptReviewRequired, abVariant, stylePreset, imageRatio, imageResolution,
    imageModel, videoModel, videoEditModel, visionModel, enableVideoEdit,
    enableVisionReview, enableSafetyAudit, safetyFailPolicy,
  ])

  const { persistedRunId, currentRunId } = useDreamweaverRunPersistence({
    selectedProjectId,
    taskRunId,
    resultRunId: result?.run_id || null,
    taskId,
    taskStatus,
    config: runConfig,
    selectedChapterIds,
  })

  persistedRunIdRef.current = persistedRunId

  const diagnosticUploadDisabled = !currentRunId || running || restartLoading || diagnosticActionLoading

  promptEditCurrentRunIdRef.current = currentRunId
  mergedVideoCurrentRunIdRef.current = currentRunId
  mergedVideoResultRef.current = result
  mergedVideoRunSnapshotRef.current = runSnapshot
  mergedVideoProjectIdRef.current = selectedProjectId
  mergedVideoProjectTitleRef.current = projects.find((p) => p.id === selectedProjectId)?.title || null
  runAssetPreviewCurrentRunIdRef.current = currentRunId

  const sharedAssetGridProps = {
    previewsByUri: runAssetPreviews,
    loadingByUri: runAssetPreviewLoading,
    errorsByUri: runAssetPreviewErrors,
    canInteract: !!currentRunId,
    onLoadPreview: loadRunAssetPreview,
    onDownload: downloadRunAsset,
    formatPath,
  }

  const {
    regenOpen, regenRole, regenTitle, regenPrompt, regenPromptInitial,
    regenImageEditAutoCleared,
    regenSuggesting, regenSuggestError,
    regenSubmitting, regenError,
    regenForceImageEdit,
    regenHasImageBase, regenImageEditActive,
    regenAlertBaseLabel,
    regenAlertReadyReferenceLabel, regenAlertMissingReferenceLabel,
    regenAlertReadyReferenceCount, regenPromptInputLabel,
    setRegenPrompt, setRegenPromptDirty,
    openRegenerateDialog, openRegenerateDialogForRole,
    submitRegenerateDialog, toggleRegenImageEditPreference,
    closeRegenDialog, requestSmartRegeneratePrompt,
  } = useDreamweaverRegenDialog({
    libraryAssetsByRole, missingRoleSet, selectedProjectId, currentRunId,
  })
  const {
    snapshotContract,
    snapshotRuntimeConfig,
    diagnosticResult,
    diagnosticPreflight,
    diagnosticProviderTrace,
    diagnosticSmartDispatchTrace,
    diagnosticProviderTraceByShotId,
    diagnosticProviderTraceSummary,
    diagnosticSmartDispatchTraceSummary,
  } = useDreamweaverDiagnostics({
    persistedRunId,
    result,
    runSnapshot,
    runPreflight,
  })
  const {
    snapshotCameraDiagnostics,
    snapshotTelemetry,
    snapshotTelemetrySummary,
    snapshotTelemetryCounters,
    snapshotPlanText,
    snapshotScriptText,
    snapshotScriptApproved,
    snapshotScriptEntities,
    snapshotScriptGeneration,
    snapshotCharacterProfiles,
    snapshotAudioMarkers,
    snapshotMergedVideo,
    videoClipJobs,
    promptReviewRequiredSnapshot,
    promptReviewApproved,
  } = useDreamweaverSnapshotDerived({ snapshotRuntimeConfig, snapshotContract })
  const libraryApproved = Boolean(library?.review?.approved)

  useEffect(() => {
    autoLoadedLibraryRef.current = false
    setSafetyAuditApproveError(null)
  }, [currentRunId])
  const promptReviewReady = !promptReviewRequiredSnapshot || promptReviewApproved
  const safetyAuditAlertState = useMemo(
    () => computeSafetyAuditAlertState({ result, snapshotRuntimeConfig, runSnapshot, taskStatus, error, currentRunId, running }, t),
    [currentRunId, error, result, runSnapshot, running, snapshotRuntimeConfig, taskStatus, t],
  )
  const canResumeFromScript = resolveCanResumeFromScript({
    currentRunId,
    scriptLoading,
    resumeLoading,
    scriptDirty,
    scriptRequiresReview,
    scriptApproved,
  })
  const canResumeFromLibrary = resolveCanResumeFromLibrary({
    currentRunId,
    libraryLoading,
    resumeLoading,
    libraryApproved,
    promptReviewReady,
  })

  const mergedVideoPanelProps = useMemo(() => ({
    currentRunId,
    mergedVideoLoading,
    mergedVideoError,
    mergedVideoPreviewUrl,
    mergedVideoPreviewPortrait,
    mergedVideoCollecting,
    mergedVideoCollectFeedback,
    onLoadPreview: loadMergedVideoPreview,
    onDownload: downloadMergedVideo,
    onCollect: () => void collectMergedVideo(),
  }), [
    currentRunId,
    mergedVideoLoading,
    mergedVideoError,
    mergedVideoPreviewUrl,
    mergedVideoPreviewPortrait,
    mergedVideoCollecting,
    mergedVideoCollectFeedback,
    loadMergedVideoPreview,
    downloadMergedVideo,
    collectMergedVideo,
  ])

  useDreamweaverEventSyncLifecycle({
    selectedProjectId,
    currentRunId,
    running,
    syncDreamweaverEvents,
    resetDreamweaverEvents,
    applyDreamweaverEvent,
    setWsError,
  })

  promptEditLoadRunSnapshotRef.current = loadRunSnapshot

  useEffect(() => {
    if (!persistedRunId) return
    if (taskStatus !== 'failed') return
    void loadRunSnapshot()
  }, [loadRunSnapshot, persistedRunId, taskStatus])

  const loadScriptWrapper = useCallback(async () => {
    if (!currentRunId) return
    await loadScript(currentRunId)
  }, [currentRunId, loadScript])

  useEffect(() => {
    if (!waitingScriptApproval) return
    if (!currentRunId) return
    if (scriptLoading) return
    if (scriptText.trim()) return
    autoLoadIfNeeded(currentRunId, waitingScriptApproval)
  }, [currentRunId, autoLoadIfNeeded, scriptLoading, scriptText, waitingScriptApproval])

  useEffect(() => {
    if (!persistedRunId) return
    if (runSnapshotLoading) return
    if (runSnapshot && runSnapshot.run_id === persistedRunId) return
    if (autoLoadedRunSnapshotRunIdRef.current === persistedRunId) return
    autoLoadedRunSnapshotRunIdRef.current = persistedRunId
    void loadRunSnapshot()
  }, [loadRunSnapshot, persistedRunId, runSnapshot, runSnapshotLoading])

  const autoLoadedRunSnapshotStageKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (!persistedRunId) return
    if (!running) return
    const key = `${persistedRunId}|${String(taskStage || '').trim().toLowerCase()}|${String(taskState || '').trim().toLowerCase()}`
    if (autoLoadedRunSnapshotStageKeyRef.current === key) return
    autoLoadedRunSnapshotStageKeyRef.current = key
    if (runSnapshotLoading) return
    void loadRunSnapshot()
  }, [loadRunSnapshot, persistedRunId, runSnapshotLoading, running, taskStage, taskState])

  const saveScriptWrapper = async () => {
    if (!currentRunId) return
    await saveScript(currentRunId)
  }

  const approveScriptWrapper = async (approved: boolean) => {
    if (!currentRunId) return
    await approveScript(currentRunId, approved)
  }

  const loadLibraryPreviewWrapper = useCallback(async (asset: LibraryAsset, options?: { force?: boolean }): Promise<void> => {
    const hasRenderableImage = hasRenderableLibraryImage(asset, { missingRoleSet })
    await loadLibraryPreview(asset, { ...options, hasRenderableImage })
  }, [loadLibraryPreview, missingRoleSet])

  const {
    loadLibrary,
    approveLibrary,
    resumeGeneration,
    confirmVideoJob,
    restartGeneration,
    uploadShotAsset,
    promptAndRegenerateKeyframe,
    approvePromptReview,
    approveSafetyAudit,
  } = useDreamweaverRunActions({
    selectedProjectId,
    currentRunId,
    running,
    qcAllowFail,
    smartTuning,
    library,
    setError,
    setRunning,
    setTaskId,
    setTaskRunId,
    setTaskStatus,
    setTaskQueue,
    setTaskProgress,
    setTaskState,
    setTaskStage,
    setTaskArtifacts,
    setWaitingApproval,
    setResumeLoading,
    setRestartLoading,
    setRestartAnchorEl,
    setLibrary,
    setLibraryLoading,
    setLibraryError,
    setLibraryPlanItems,
    clearLibraryPreviews,
    setLibraryPreviews,
    setLibraryPreviewErrors,
    setVideoJobActionError,
    setVideoJobConfirmingShotId,
    setDiagnosticActionLoading,
    setDiagnosticActionError,
    setPromptReviewLoading,
    setPromptReviewError,
    setSafetyAuditApproveLoading,
    setSafetyAuditApproveError,
    setRunSnapshot,
    resetForNewRun,
    applyTerminalStatus,
    loadRunSnapshot,
    hydrateFromPersistedRun,
  })

  const {
    streamSnapshots,
    scriptGenerationLabel,
    activeStreamKeys,
    snapshotShots,
    safetyBlockedShots,
    snapshotShotById,
    promptReviewShots,
    snapshotAssetCount,
    snapshotAssetSummary,
    libraryPromptReviewMessage,
    assetPlanSummary,
    mergedVideoPlan,
    nonMergedVideoAssets,
    hasNonMergedVideoAssets,
    hasMergedVideoPlan,
    librarySummary,
    libraryGroups,
    hasLibraryItems,
    diagnosticCameraDiagnostics,
    diagnosticCameraSceneUris,
    hasDiagnosticCameraSceneUris,
    diagnosticShots,
    runId,
    stageLabel,
    stateLabel,
    taskStatusLabel,
    taskStatusColor,
    artifactChips,
    artifactLines,
    hasArtifactLines,
    progressLabel,
    progressStep,
  } = useDreamweaverDerivedState({
    scriptGeneration,
    streamTextByKey,
    streamMetaByKey,
    runSnapshot,
    promptReviewShowAll,
    libraryApproved,
    promptReviewReady,
    promptReviewRequiredSnapshot,
    assetPlanItems,
    library,
    libraryPlanItems,
    libraryPreviews,
    libraryPreviewAspectRatio,
    missingRoleSet,
    snapshotCameraDiagnostics,
    diagnosticResult,
    taskRunId,
    result,
    taskStage,
    taskState,
    taskStatus,
    taskArtifacts,
    running,
    waitingApproval,
    taskProgress,
  })

  const openSafetyBlockedShot = useCallback(
    (shotId: string) => {
      const key = String(shotId || '').trim()
      if (!key) return
      const shot = snapshotShotById.get(key)
      if (!shot) return
      openPromptEditDialog(shot)
    },
    [openPromptEditDialog, snapshotShotById],
  )

  const previewRenderers = createRunPagePreviewRenderers({
    sharedAssetGridProps,
    missingRoleSet,
    libraryPreviewLoading,
    libraryPreviewErrors,
    libraryLoading,
    approveLibrary,
    loadLibraryPreviewWrapper,
    openRegenerateDialog,
    openRegenerateDialogForRole,
    streamSnapshots,
    activeStreamKeys,
    libraryPlanItems,
    assetPlanItems,
    assetPlanSummary,
    mergedVideoPlan,
    hasNonMergedVideoAssets,
    hasMergedVideoPlan,
    nonMergedVideoAssets,
    snapshotPlanText,
    snapshotScriptText,
    snapshotScriptApproved,
    snapshotCharacterProfiles,
    snapshotAudioMarkers,
    snapshotScriptEntities,
    snapshotScriptGeneration,
    safetyBlockedShots,
    openSafetyBlockedShot,
    t,
  })
  const renderRunAssetPreviewGrid = previewRenderers.renderRunAssetPreviewGrid
  const renderLibraryDisplayCard = previewRenderers.renderLibraryDisplayCard
  const renderStreamingPreview = previewRenderers.renderStreamingPreview
  const renderScriptStageSnapshot = previewRenderers.renderScriptStageSnapshot
  const renderSafetyBlockedAlert = previewRenderers.renderSafetyBlockedAlert

  useEffect(() => {
    if (manualPreviewStep) return
    setPreviewStep(progressStep)
  }, [manualPreviewStep, progressStep])

  const handleClickStep = (step: number) => {
    setPreviewStep(step)
    setManualPreviewStep(true)
  }

  const followProgressStep = () => {
    setManualPreviewStep(false)
    setPreviewStep(progressStep)
  }

  const isScriptPreviewStep = previewStep === 0
  const isStoryboardPreviewStep = previewStep === 1
  const isAuditPreviewStep = previewStep === 4

  const snapshotRenderer = createRunPageSnapshotRenderer({
    previewStep,
    isScriptPreviewStep,
    isStoryboardPreviewStep,
    isAuditPreviewStep,
    runSnapshotLoading,
    snapshotShots,
    snapshotAssetCount,
    snapshotAssetSummary,
    snapshotMergedVideo: snapshotMergedVideo as string | null,
    snapshotScriptStageSnapshot: renderScriptStageSnapshot(),
    wsError,
    persistedRunId,
    runSnapshot,
    runSnapshotError,
    mergedVideoPanelProps,
    renderRunAssetPreviewGrid,
    renderSafetyBlockedAlert,
    renderStreamingPreview,
    loadRunSnapshot,
    setWsError,
    t,
  })

  const renderRunSnapshotPreviewPane = snapshotRenderer.renderRunSnapshotPreviewPane
  const snapshotStatusBaseProps = snapshotRenderer.snapshotStatusBaseProps
  const snapshotStatusPropsWithChips = snapshotRenderer.snapshotStatusPropsWithChips
  const snapshotRefreshDisabled = snapshotRenderer.snapshotRefreshDisabled
  const runSnapshotLoaded = snapshotRenderer.runSnapshotLoaded

  const restartActionDisabled = isRestartDisabled(currentRunId, running, restartLoading)

  const renderDebugAccordion = ({
    title,
    value,
    marginTop = 0,
    marginBottom = 0,
  }: {
    title: string
    value: unknown
    marginTop?: number
    marginBottom?: number
  }) => (
    <DebugAccordion title={title} value={value} marginTop={marginTop} marginBottom={marginBottom} safeJsonStringify={safeJsonStringify} />
  )

  const renderArtifactsDebugPanel = () =>
    renderDebugAccordion({ title: t('dreamweaverRun.debugPanelArtifacts'), value: taskArtifacts, marginTop: 1 })

  const libraryRenderer = createRunPageLibraryRenderer({
    libraryLoading,
    libraryError,
    library,
    libraryApproved,
    libraryGridCols,
    librarySummary,
    libraryGroups,
    hasLibraryItems,
    libraryPromptReviewMessage,
    promptReviewReady,
    promptReviewRequiredSnapshot,
    selectedProjectId,
    canResumeFromLibrary,
    resumeLoading,
    loadLibrary,
    approveLibrary,
    resumeGeneration,
    handleClickStep,
    renderArtifactsDebugPanel,
    renderRunSnapshotPreviewPane,
    renderLibraryDisplayCard,
    t,
  })

  const pendingRenderer = createRunPagePendingRenderer({
    taskStatus,
    taskQueue,
    previewStep,
    previewStepLabel: t(DREAMWEAVER_PREVIEW_STEPS[previewStep]),
    running,
    currentRunId,
    persistedRunId,
    runSnapshotLoading,
    scriptText,
    scriptLoading,
    scriptError,
    scriptRequiresReview,
    scriptApproved,
    scriptDirty,
    canResumeFromScript,
    resumeLoading,
    scriptGenerationLabel,
    scriptGeneration,
    scriptEntities,
    videoClipJobs,
    videoJobConfirmingShotId,
    videoJobActionError,
    promptReviewApproved,
    promptReviewLoading,
    promptReviewError,
    promptReviewShots,
    promptReviewShowAll,
    promptReviewRequiredSnapshot,
    libraryApproved,
    canResumeFromLibrary,
    snapshotShots,
    snapshotShotById,
    artifactLines,
    hasArtifactLines,
    artifactChips,
    waitingScriptApproval,
    waitingVideoConfirmation,
    loadScriptWrapper,
    saveScriptWrapper,
    approveScriptWrapper,
    resumeGeneration,
    confirmVideoJob,
    openPromptEditDialog,
    approvePromptReview,
    loadRunSnapshot,
    rebuildVideoJobs,
    setScriptText,
    setPromptReviewShowAll,
    renderArtifactsDebugPanel,
    renderRunSnapshotPreviewPane,
    copyDebugInfo,
    openDiagnosticDialog,
    renderPendingLibraryReviewView: libraryRenderer.renderPendingLibraryReviewView,
    renderPendingLibraryReadyView: libraryRenderer.renderPendingLibraryReadyView,
    t,
  })

  const renderPendingView = pendingRenderer.renderPendingView

  const resultRenderer = createRunPageResultRenderer({
    safeJsonStringify,
    taskArtifacts,
    result,
    resultChapterCount,
    resultKeyframeCount,
    resultMidframeCount,
    resultVideoClipCount,
    resultKeyframePaths,
    resultMidframePaths,
    resultVideoClipPaths,
    candidateFrameUris,
    renderRunAssetPreviewGrid,
    isStoryboardPreviewStep,
    isScriptPreviewStep,
    isAuditPreviewStep,
    runSnapshotLoading,
    snapshotShots,
    snapshotStatusBaseProps,
    videoDiagnostics,
    snapshotStatusPropsWithChips,
    mergedVideoPanelProps,
    resultPlanText,
    currentRunId,
    eventSyncing,
    eventCursor,
    runSnapshotError,
    eventSyncError,
    loadRunSnapshot,
    syncDreamweaverEvents,
    renderStreamingPreview,
    previewStep,
    snapshotRefreshDisabled,
    runSnapshotLoaded,
    t,
  })

  const renderResultView = resultRenderer.renderResultView

  const diagnosticRenderer = createRunPageDiagnosticRenderer({
    safeJsonStringify,
    copyText: (text: string) => copyText(text, t),
    renderRunAssetPreviewGrid,
    currentRunId,
    diagnosticOpen,
    closeDiagnosticDialog,
    diagnosticResult,
    diagnosticActionError,
    diagnosticActionLoading,
    diagnosticShots,
    persistedRunId,
    runSnapshotLoading,
    diagnosticPreflight,
    diagnosticProviderTrace,
    diagnosticSmartDispatchTrace,
    diagnosticProviderTraceByShotId,
    diagnosticProviderTraceSummary,
    diagnosticSmartDispatchTraceSummary,
    snapshotRuntimeConfig,
    snapshotTelemetrySummary,
    snapshotTelemetryCounters,
    snapshotTelemetry,
    diagnosticCameraDiagnostics,
    hasDiagnosticCameraSceneUris,
    diagnosticCameraSceneUris,
    diagnosticUploadDisabled,
    uploadShotAsset,
    promptAndRegenerateKeyframe,
    getDiagnosticStoryboardPrompt,
    restartGeneration,
    restartActionDisabled,
    loadRunSnapshot,
    taskStatus,
    taskState,
    taskStage,
    hasDiagnosticShots: diagnosticShots.length > 0,
    telemetryAbVariant: typeof snapshotRuntimeConfig?.ab_variant === 'string' ? snapshotRuntimeConfig.ab_variant : undefined,
    t,
  })

  const renderDiagnosticDialog = diagnosticRenderer.renderDiagnosticDialog

  const dialogRenderer = createRunPageDialogRenderer({
    language,
    promptEditOpen, closePromptEditDialog,
    promptEditShot, promptEditGenerated,
    promptEditHead, promptEditTail,
    promptEditVideo, promptEditSaving,
    promptEditError, setPromptEditHead,
    setPromptEditTail, setPromptEditVideo,
    savePromptEdit, regenOpen,
    closeRegenDialog, regenTitle,
    regenRole, regenSuggesting,
    regenSubmitting, regenForceImageEdit,
    regenImageEditActive, regenHasImageBase,
    regenAlertBaseLabel, regenAlertReadyReferenceLabel,
    regenAlertReadyReferenceCount, regenAlertMissingReferenceLabel,
    regenSuggestError, regenImageEditAutoCleared,
    regenPromptInputLabel, regenPrompt,
    regenPromptInitial, regenError,
    submitRegenerateDialog, toggleRegenImageEditPreference,
    requestSmartRegeneratePrompt, setRegenPrompt,
    setRegenPromptDirty, historyOpen,
    closeHistoryDialog,
    selectedProjectTitle: selectedProject?.title,
    historyError, historyLoading,
    historyRunCount: historyRuns.length, historyStatusFilters,
    historyStatusCounts,
    clearHistoryStatusFilters: () => setHistoryStatusFilters([]),
    toggleHistoryStatusFilter: (status: string) => {
      setHistoryStatusFilters((prev: string[]) =>
        prev.includes(status) ? prev.filter((item) => item !== status) : [...prev, status],
      )
    },
    refreshHistory: () => { if (selectedProjectId) fetchRunHistory(selectedProjectId) },
    historyRefreshDisabled: historyLoading || !selectedProjectId,
    openBulkDeleteDialog,
    historyBulkDeleteDisabled: historyLoading || bulkDeleteTargetCount === 0,
    bulkDeleteTargetCount, filteredHistoryRuns,
    handleViewHistoryRun, openDeleteRunDialog,
    historyEmpty: !historyLoading && !historyError && historyRuns.length === 0,
    historyFilterEmpty: !historyLoading && !historyError && historyRuns.length > 0 && filteredHistoryRuns.length === 0,
    bulkDeleteDialogOpen, closeBulkDeleteDialog,
    bulkDeleteSkippedCount, bulkDeleteProgress,
    bulkDeleteError, bulkDeleteResult,
    bulkDeleteSubmitting, confirmBulkDeleteRuns,
    deleteDialogOpen, closeDeleteRunDialog,
    deleteRunId, deleteDialogError,
    deleteSubmitting,
    confirmDeleteCurrentRun: () => confirmDeleteRun(selectedProjectId),
    configDialogOpen,
    closeConfigDialog: () => setConfigDialogOpen(false),
    configDialogFullScreen,
    configSubtitle: buildConfigDialogSubtitle(selectedProject?.title, selectedProjectId, selectedChapterIds.length, chapters.length, t),
    configDialogErrorNotice: taskPointsPrecheckError
      ? <TaskPointsPrecheckAlert detail={taskPointsPrecheckError} onClose={() => { setTaskPointsPrecheckError(null); setError(null) }} sx={{ mb: 2 }} />
      : error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null,
    lockedProjectId,
    onOpenProjectList: () => { setConfigDialogOpen(false); navigate('/drama') },
    selectedChapterIds, chapters,
    loadingChapters, running,
    handleSelectAll,
    onRefreshChapters: () => { if (selectedProjectId) void handleSelectProject(selectedProjectId) },
    chapterRefreshDisabled: loadingChapters || !selectedProjectId || running,
    handleToggleChapter, highQuality,
    setHighQuality, smartTuning,
    setSmartTuning, videoRequireConfirmation,
    setVideoRequireConfirmation, promptReviewRequired,
    setPromptReviewRequired, qcAllowFail,
    setQcAllowFail, abVariant,
    setAbVariant, lockedGenerationConfigError,
    generationConfigLocked,
    lockedGenerationConfigSourceRunId: lockedGenerationConfig?.source_run_id,
    stylePreset, setStylePreset,
    imageRatio, setImageRatio,
    imageResolution, setImageResolution,
    visualFieldsDisabled, imageModel,
    setImageModel, dreamweaverImageModelOptions,
    videoModel, setVideoModel,
    dreamweaverVideoModelOptions, videoEditModel,
    setVideoEditModel, dreamweaverVideoEditModelOptions,
    visionModel, setVisionModel,
    dreamweaverVisionModelOptions, enableVideoEdit,
    setEnableVideoEdit, enableVisionReview,
    setEnableVisionReview, enableSafetyAudit,
    setEnableSafetyAudit, safetyFailPolicy,
    setSafetyFailPolicy, SAFETY_FAIL_POLICY_OPTIONS,
    onRunFromConfigDialog: async () => { const ok = await handleRun(); if (ok) setConfigDialogOpen(false) },
    configRunDisabled: resolveConfigRunDisabled({
      running, lockedGenerationConfigLoading,
      selectedProjectId,
      selectedChapterIdsLength: selectedChapterIds.length,
    }),
    renderDiagnosticDialog, taskPointsPrecheckError,
    onClearTaskPointsPrecheckError: () => { setTaskPointsPrecheckError(null); setError(null) },
    safetyAuditAlertState, safetyAuditApproveLoading,
    safetyAuditApproveError,
    onApproveSafetyAudit: () => void approveSafetyAudit(),
    error,
    hasQcWarning: Boolean(result?.qc_warning),
    diagnosticPreflight,
    t,
  })

  const renderConfigDialog = dialogRenderer.renderConfigDialog
  const renderWorkbenchDialogs = dialogRenderer.renderWorkbenchDialogs
  const renderRunPageAlerts = dialogRenderer.renderRunPageAlerts

  const workbenchRenderer = createRunPageWorkbenchRenderer({
    runId,
    progressLabel,
    stateLabel,
    stageLabel,
    taskStatusLabel,
    taskQueue,
    taskStatusColor,
    currentRunId,
    running,
    restartLoading,
    manualPreviewStep,
    previewStep,
    progressStep,
    selectedProjectId,
    taskStage,
    taskState,
    taskProgress,
    taskStatus,
    waitingApproval,
    result,
    restartAnchorEl,
    setRestartAnchorEl,
    copyDebugInfo,
    openDiagnosticDialog,
    openHistoryDialog,
    openConfigDialog: () => setConfigDialogOpen(true),
    restartGeneration,
    followProgressStep,
    handleClickStep,
    setError,
    renderPendingView,
    renderResultView,
    renderWorkbenchDialogs,
    stepLabels: DREAMWEAVER_PREVIEW_STEPS.map((stepKey) => t(stepKey)),
    t,
  })
  const renderWorkbenchCard = workbenchRenderer.renderWorkbenchCard

  const navigateBack = () => navigate('/drama')

  return (
    <DreamweaverRunPageScaffold
      onBack={navigateBack}
      heroTitle={t('dreamweaverRun.heroTitle')}
      heroDescription={t('dreamweaverRun.heroDescription')}
      configDialog={renderConfigDialog()}
      alerts={renderRunPageAlerts()}
      workbenchCard={renderWorkbenchCard()}
    />
  )
}
