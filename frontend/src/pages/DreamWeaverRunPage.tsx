import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDreamweaverTaskPolling } from '@/hooks/useDreamweaverTaskPolling'
import { useDreamweaverEventSyncLifecycle } from '@/hooks/useDreamweaverEventSyncLifecycle'
import { useDreamweaverRunHydration } from '@/hooks/useDreamweaverRunHydration'
import { useDreamweaverDerivedState } from '@/hooks/useDreamweaverDerivedState'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Divider,
  ImageList,
  Stack,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import HistoryIcon from '@mui/icons-material/History'
import RefreshIcon from '@mui/icons-material/Refresh'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import BugReportIcon from '@mui/icons-material/BugReport'
import {
  apiClient,
  describeTaskPointsPrecheckErrorDetail,
  extractApiErrorMessage,
  extractTaskPointsPrecheckErrorDetail,
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
import { TaskHeader } from '@/components/dreamweaver/TaskHeader'
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
import {
  buildLibraryPlanItemsFromPayload,
  clearPersistedDreamWeaverRun,
  ratioIsPortrait,
  ratioToCssAspectRatio,
  readPersistedDreamWeaverRun,
  writePersistedDreamWeaverRun,
} from '@/utils/dreamweaver'
import {
  buildDreamweaverRunSourceNavigationPlan,
  readUserAssetSourceRunId,
} from '@/utils/userAssetSourceNavigation'
import type {
  Chapter,
  DreamweaverAssetPlanItem,
  DreamweaverDiagnosticShot,
  DreamweaverRunPreflight as DreamweaverRunPreflightData,
  DreamweaverRunSnapshot,
  DreamweaverRunSummary,
  DreamweaverShotSnapshot,
  DreamweaverVideoClipJob,
  DreamweaverVideoProviderShotTrace,
  LibraryAsset,
  LibraryDisplayItem,
  LibraryPayload,
  Project,
  RunResult,
} from '@/types/dreamweaver'
import {
  resolvePendingPromptReviewShotState,
  resolvePendingPromptReviewState,
  resolvePendingRunningState,
  resolvePendingScriptApprovalState,
  resolvePendingVideoConfirmationJobState,
  resolvePendingVideoConfirmationState,
  resolvePendingViewMode,
} from './dreamweaver-run/pendingViewState'
import { PendingPromptReviewShotItem, PendingVideoConfirmationJobItem } from './dreamweaver-run/pendingListItems'
import {
  PendingEmptyState,
  PendingArtifactDetails,
  PendingLibraryNotice,
  PendingLibraryControls,
  PendingLibraryReadyShell,
  PendingLibraryReadyActions,
  PendingLibraryReviewShell,
  PendingLibraryRuntimeStatus,
  PendingLibrarySummarySection,
  PendingPromptReviewView,
  PendingRunningArtifactsSummary,
  PendingRunningShell,
  PendingRunningStageHint,
  PendingScriptApprovalEditor,
  PendingScriptApprovalShell,
  PendingVideoConfirmationView,
} from './dreamweaver-run/pendingViews'
import {
  DreamweaverRunConfigDialog,
} from './dreamweaver-run/configDialog'
import {
  DreamweaverBulkDeleteDialog,
  DreamweaverDeleteRunDialog,
} from './dreamweaver-run/deleteDialogs'
import {
  DreamweaverRunDiagnosticDialog,
} from './dreamweaver-run/diagnosticDialog'
import {
  DreamweaverDiagnosticCameraDiagnosticsSection,
  DreamweaverDiagnosticPreflightSection,
  DreamweaverDiagnosticProviderTraceSection,
  DreamweaverDiagnosticSmartDispatchSection,
  DreamweaverDiagnosticTelemetrySection,
} from './dreamweaver-run/diagnosticSections'
import {
  DreamweaverDiagnosticShotAccordion,
  DreamweaverDiagnosticShotActions,
  DreamweaverDiagnosticShotDetails,
  DreamweaverDiagnosticShotSummary,
} from './dreamweaver-run/diagnosticShotViews'
import {
  DreamweaverHistoryDialog,
  DreamweaverHistoryRunListItem,
} from './dreamweaver-run/historyDialog'
import {
  DreamweaverCharacterLibraryBucketSection,
  DreamweaverLibraryDisplayCard,
  DreamweaverLibraryGroupSection,
  DreamweaverLibrarySummaryChips,
} from './dreamweaver-run/libraryViews'
import {
  DreamweaverPromptEditDialog,
  DreamweaverRegenerateDialog,
} from './dreamweaver-run/promptDialogs'
import {
  DreamweaverAssetPlanGrid,
  DreamweaverRunAssetPreviewGrid,
  DreamweaverScriptStageSnapshotView,
  DreamweaverStreamingPreview,
} from './dreamweaver-run/previewSections'
import {
  DreamweaverResultLibraryHint,
  DreamweaverResultStoryboardStageView,
  DreamweaverRunResultView,
  DreamweaverResultSyncActionsBar,
  DreamweaverResultSyncStatusPanel,
  DreamweaverResultTextStageSection,
  DreamweaverResultVideoClipPathSummary,
  DreamweaverResultVideoFallbackAlert,
  DreamweaverResultVideoStageView,
  DreamweaverResultVideoSummarySection,
} from './dreamweaver-run/resultView'
import {
  RunSnapshotAssetPreviewSection,
  RunSnapshotErrorAlert,
  RunSnapshotLoadedChip,
  RunSnapshotLoadingBar,
  RunSnapshotMergedVideoSection,
  RunSnapshotPreviewPane,
  RunSnapshotRefreshButton,
  RunSnapshotRefreshControls,
  RunSnapshotSectionStatus,
  RunSnapshotShotList,
} from './dreamweaver-run/runSnapshotPreviewPane'
import {
  DreamweaverWorkbenchCard,
  DreamweaverWorkbenchStatusScaffold,
} from './dreamweaver-run/workbenchStatusPanel'
import {
  asObject,
  buildCharacterLibraryBuckets,
  CharacterLibraryBucket,
  getDiagnosticStoryboardPrompt,
  getShotDesc,
  getShotFramePrompt,
  getShotId,
  getShotVideoPromptOverride,
  getThrownErrorMessage,
  isNotFoundError,
  LibraryDisplayGroup,
  LibraryGroupSummary,
  resolveLibraryDisplayCardState,
  resolveShotDiagnosticAccordionState,
  summarizeScriptEntities,
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
  toChapters,
  toDreamweaverQueuedTaskResponse,
  toDreamweaverRunAsyncResponse,
  toDreamweaverVideoClipJobs,
  toLibraryPayload,
  withRunSnapshotVideoJobs,
  parsePromptedIds,
  parsePromptedCameraIndices,
  mapHistoryRunsToItems,
  PENDING_STAGE_HINTS,
  buildModelFieldProps,
  buildCameraAccordionProps,
  buildVideoSummarySectionProps,
  buildToggleFieldProps,
  buildVisualFieldProps,
  buildStrategyFields,
  buildDebugInfoPayload,
  buildRunDiagnosticPayload as buildRunDiagnosticPayloadHelper,
  buildCameraDiagnosticPayload as buildCameraDiagnosticPayloadHelper,
  buildHistoryFilterItems,
  buildRestartMenuItems,
  resolvePreflightVideoConfig,
  resolveSmartDispatchTraceDetails,
  resolveProviderTraceFeatureFlags,
  hasCameraDiagnosticsData,
  resolveCameraCounts,
  arrayLength,
  buildConfigDialogSubtitle,
  buildShotDiagnosticCopyPayload,
  buildSnapshotStatusProps,
  resolveStreamingTexts,
  resolveSmartDispatchSummaryProps,
  resolveProviderTraceSummaryProps,
  resolveTelemetrySectionProps,
  buildWorkbenchActionItems,
  resolveRegenerateDialogLabels,
  resolveRegenerateSubmitDisabled,
  resolveConfigRunDisabled,
  isSnapshotRefreshDisabled,
  isRestartDisabled,
  buildSnapshotAssetPreviewSectionProps,
  resolvePendingLibraryNoticeSeverity,
  buildPendingLibraryControlsProps,
  buildPendingLibraryRuntimeStatusProps,
  buildDiagnosticDialogProps,
  buildDreamweaverRunConfig,
  normalizeShotIds,
  normalizeCameraIndices,
  buildRestartPartialHint,
  validateRestartParams,
  applyGenerationConfig,
  collectLibraryPreviewMaps,
  extractMissingRoleSet,
  resolveModelOptions,
  applyModelOptionSync,
  STYLE_PRESET_OPTIONS,
  IMAGE_RATIO_OPTIONS,
  IMAGE_RESOLUTION_OPTIONS,
} from './dreamweaver-run/runPageHelpers'
import {
  DreamweaverRunPageScaffold,
} from './dreamweaver-run/runPageShell'
import { MergedVideoPanel } from './dreamweaver-run/MergedVideoPanel'
import { DiagnosticFrameAccordion, DiagnosticJson, TitledDiagnosticJsonAccordion, ShotDiagnosticUploadActions, ShotDiagnosticPromptRegenerateActions, ShotProviderTraceSection, SafetyBlockedAlert, DebugAccordion } from './dreamweaver-run/diagnosticSections'
import { ShotPromptSnapshotList } from './dreamweaver-run/ShotPromptSnapshotList'
import { RunPageAlertsSection } from './dreamweaver-run/RunPageAlertsSection'
const DREAMWEAVER_PREVIEW_STEPS = ['剧本', '分镜', '素材', '镜头', '合成'] as const

export default function DreamWeaverRunPage() {
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
  const autoOpenedConfigDialogRef = useRef(false)

  const autoLoadedRunSnapshotRunIdRef = useRef<string | null>(null)
  const autoLoadedLibraryRef = useRef(false)
  const handledSourceRunKeyRef = useRef<string | null>(null)

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

  const renderRunAssetPreviewGrid = (title: string, uris: string[], kind: 'image' | 'video') => (
    <DreamweaverRunAssetPreviewGrid
      title={title}
      uris={uris}
      kind={kind}
      {...sharedAssetGridProps}
    />
  )

  const renderAssetPlanGrid = (title: string, items: DreamweaverAssetPlanItem[]) => (
    <DreamweaverAssetPlanGrid
      title={title}
      items={items}
      {...sharedAssetGridProps}
    />
  )

  const resolveLibraryDisplayCardStateLocal = (item: LibraryDisplayItem) =>
    resolveLibraryDisplayCardState(item, missingRoleSet, libraryPreviewLoading, libraryPreviewErrors)

  const renderLibraryDisplayCard = (item: LibraryDisplayItem) => {
    const state = resolveLibraryDisplayCardStateLocal(item)
    const cardAsset = state.asset

    return (
      <DreamweaverLibraryDisplayCard
        itemKey={item.key}
        title={item.title}
        aspectRatio={String(item.aspectRatio)}
        state={state}
        libraryLoading={libraryLoading}
        onToggleApprove={
          cardAsset ? () => approveLibrary({ roles: [cardAsset!.role], approved: !state.approved }) : undefined
        }
        onLoadPreview={
          cardAsset ? () => loadLibraryPreviewWrapper(cardAsset!, { force: true }) : undefined
        }
        onOpenRegenerate={
          cardAsset ? () => openRegenerateDialog(cardAsset!) : () => openRegenerateDialogForRole(item.role, item.title)
        }
      />
    )
  }

  const renderStreamingPreview = (step: number) => {
    const streamingTexts = resolveStreamingTexts(streamSnapshots)

    return (
      <DreamweaverStreamingPreview
        step={step}
        activeStreamKeys={activeStreamKeys}
        {...streamingTexts}
        libraryPlanItems={libraryPlanItems}
        assetPlanItems={assetPlanItems}
        assetPlanSummary={assetPlanSummary}
        mergedVideoPlan={mergedVideoPlan ?? null}
        assetPlanGrid={hasNonMergedVideoAssets ? renderAssetPlanGrid('素材占位卡', nonMergedVideoAssets) : null}
        mergedVideoPlanGrid={hasMergedVideoPlan ? renderAssetPlanGrid('合成视频占位', [mergedVideoPlan!]) : null}
      />
    )
  }

  const renderScriptStageSnapshot = () => (
    <DreamweaverScriptStageSnapshotView
      planText={snapshotPlanText.trim()}
      scriptText={snapshotScriptText.trim()}
      scriptApproved={snapshotScriptApproved}
      characterProfiles={snapshotCharacterProfiles}
      audioMarkers={snapshotAudioMarkers}
      scriptEntities={snapshotScriptEntities}
      scriptGeneration={snapshotScriptGeneration}
      entitySummary={summarizeScriptEntities(snapshotScriptEntities)}
    />
  )

  const renderSafetyBlockedAlert = () => (
    <SafetyBlockedAlert shots={safetyBlockedShots} onOpenShot={openSafetyBlockedShot} />
  )

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
    await copyText(safeJsonStringify({ page: 'DreamWeaverRunPage', ...payload }))
  }

  const renderDiagnosticJson = (value: unknown) => (
    <DiagnosticJson value={value} safeJsonStringify={safeJsonStringify} />
  )

  const renderTitledDiagnosticJsonAccordion = ({
    title,
    value,
    marginTop = 1,
  }: {
    title: string
    value: unknown
    marginTop?: number
  }) => (
    <TitledDiagnosticJsonAccordion title={title} value={value} marginTop={marginTop} safeJsonStringify={safeJsonStringify} />
  )

  const renderDiagnosticFrame = (title: string, frame: unknown, kind: 'image' | 'video' = 'image') => (
    <DiagnosticFrameAccordion
      title={title}
      frame={frame}
      kind={kind}
      renderPreviewGrid={renderRunAssetPreviewGrid}
      renderDiagnosticJson={renderDiagnosticJson}
      copyText={copyText}
      safeJsonStringify={safeJsonStringify}
    />
  )

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
      setError(getThrownErrorMessage(e) || '加载章节失败')
      setChapters([])
      setSelectedChapterIds([])
    } finally {
      setLoadingChapters(false)
    }
  }, [clearRunAssetPreviews, refreshLockedGenerationConfig, resetDreamweaverEvents])

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
    openConfigDialog()
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
      setError('请选择项目与至少一个章节后再开始体验')
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
      if (!data) { setError('启动响应格式无效'); return false }
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
          : ((await extractApiErrorMessage(e, '任务提交失败')) || '任务提交失败')
      )
      setRunning(false)
      return false
    }
  }

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
    setRegenPrompt, setRegenPromptDirty, setRegenerateLibraryAsset,
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
    () => computeSafetyAuditAlertState({ result, snapshotRuntimeConfig, runSnapshot, taskStatus, error, currentRunId, running }),
    [currentRunId, error, result, runSnapshot, running, snapshotRuntimeConfig, taskStatus],
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
  const approvePromptReview = async (approved: boolean) => {
    if (!currentRunId) return
    setPromptReviewLoading(true)
    setPromptReviewError(null)
    try {
      await apiClient.approveDreamweaverPromptReview(currentRunId, { approved })
      await loadRunSnapshot()
    } catch (e: unknown) {
      setPromptReviewError(await extractApiErrorMessage(e, '更新提示词审核状态失败'))
    } finally {
      setPromptReviewLoading(false)
    }
  }

  const approveSafetyAudit = async () => {
    if (!currentRunId || !selectedProjectId) return
    setSafetyAuditApproveLoading(true)
    setSafetyAuditApproveError(null)
    try {
      await apiClient.approveDreamweaverSafetyAudit(currentRunId)
      setError(null)
      applyTerminalStatus({ run_id: currentRunId })
      await hydrateFromPersistedRun(selectedProjectId, currentRunId, null, 'completed')
    } catch (e: unknown) {
      setSafetyAuditApproveError(await extractApiErrorMessage(e, '人工放行安全审核失败'))
    } finally {
      setSafetyAuditApproveLoading(false)
    }
  }

  const loadLibrary = async (): Promise<string | null> => {
    if (!selectedProjectId) return '未选择项目'
    setLibraryLoading(true)
    setLibraryError(null)
    setLibrary(null)
    clearLibraryPreviews()
    try {
      const scopedRunId = typeof currentRunId === 'string' && currentRunId.trim() ? currentRunId.trim() : null
      const res = await apiClient.getDreamweaverLibrary(selectedProjectId, scopedRunId ? { run_id: scopedRunId } : undefined)
      const data = toLibraryPayload(res.data)
      if (!data) {
        setLibraryError('素材库响应格式无效')
        return '素材库响应格式无效'
      }
      setLibrary(data)
      setLibraryPlanItems(buildLibraryPlanItemsFromPayload(data))

      const assets = Array.isArray(data.assets) ? data.assets : []
      const scopedMissingRoleSet = extractMissingRoleSet(data)
      const previewEntries = await Promise.all(
        assets
          .filter((asset: LibraryAsset) => hasRenderableLibraryImage(asset, { missingRoleSet: scopedMissingRoleSet }))
          .map(async (asset: LibraryAsset) => {
          try {
            const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
            const url = URL.createObjectURL(fileRes.data)
            return { id: asset.id, url, error: '' }
          } catch (e: unknown) {
            const message = await extractApiErrorMessage(e, '加载预览失败')
            return { id: asset.id, url: '', error: message }
          }
          }),
      )
      const { previewMap, previewErrorMap } = collectLibraryPreviewMaps(previewEntries)
      setLibraryPreviews(previewMap)
      setLibraryPreviewErrors(previewErrorMap)
      return null
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, '加载素材库失败')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }

  useEffect(() => {
    if (!selectedProjectId) return
    if (libraryLoading) return
    if (library || libraryPlanItems.length === 0) return
    if (autoLoadedLibraryRef.current) return
    autoLoadedLibraryRef.current = true
    void loadLibrary()
  }, [library, libraryLoading, libraryPlanItems.length, loadLibrary, selectedProjectId])

  const approveLibrary = async (payload: { approve_all?: boolean; roles?: string[]; approved?: boolean }) => {
    if (!selectedProjectId) return
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.approveDreamweaverLibrary(selectedProjectId, payload)
      await loadLibrary()
    } catch (e: unknown) {
      setLibraryError(await extractApiErrorMessage(e, '更新审核状态失败'))
    } finally {
      setLibraryLoading(false)
    }
  }

  const regenerateLibraryAssetFn = useCallback(async (options: Record<string, unknown>): Promise<string | null> => {
    const role = String(options.role || '').trim()
    if (!role) return 'missing asset role'
    if (!selectedProjectId) return 'project not selected'
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.regenerateDreamweaverLibraryAsset(selectedProjectId, {
        role,
        ...(options.run_id ? { run_id: String(options.run_id) } : {}),
        ...(options.prompt ? { prompt: String(options.prompt) } : {}),
        ...(options.prefer_image_edit ? { prefer_image_edit: true } : {}),
        ...(options.prefer_view_chain_edit_base ? { prefer_view_chain_edit_base: true } : {}),
      })
      return await loadLibrary()
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, 'regenerate failed')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }, [selectedProjectId, loadLibrary])

  useEffect(() => {
    setRegenerateLibraryAsset(regenerateLibraryAssetFn)
  }, [regenerateLibraryAssetFn, setRegenerateLibraryAsset])

  const loadLibraryPreviewWrapper = useCallback(async (asset: LibraryAsset, options?: { force?: boolean }): Promise<void> => {
    const hasRenderableImage = hasRenderableLibraryImage(asset, { missingRoleSet })
    await loadLibraryPreview(asset, { ...options, hasRenderableImage })
  }, [loadLibraryPreview, missingRoleSet])

  const resumeGeneration = async () => {
    if (!currentRunId) {
      setError('缺少 run_id，无法继续生成（请复制调试信息排查）')
      return
    }
    setError(null)
    setLibraryError(null)
    setResumeLoading(true)
    setTaskQueue(null)
    setRunning(true)
    setWaitingApproval(false)
    setTaskStatus('queued')
    try {
      const res = await apiClient.resumeDreamweaverAsync(currentRunId)
      const data = toDreamweaverQueuedTaskResponse(res.data)
      if (!data) {
        throw new Error('继续生成响应格式无效')
      }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
      setTaskStatus(data.status || 'queued')
    } catch (e: unknown) {
      setError(await extractApiErrorMessage(e, '继续生成失败'))
      // 保持停留在等待页，避免“看起来没反应”
      setRunning(false)
      setWaitingApproval(true)
      setTaskStatus('waiting')
    } finally {
      setResumeLoading(false)
    }
  }

  const confirmVideoJob = async (shotId: string) => {
    const sid = String(shotId || '').trim()
    if (!sid) return
    if (!currentRunId) {
      setVideoJobActionError('缺少 run_id，无法确认视频片段生成')
      return
    }
    if (running) {
      setVideoJobActionError('当前 run 正在运行中，请等待结束后再确认')
      return
    }
    setVideoJobActionError(null)
    setVideoJobConfirmingShotId(sid)
    setTaskQueue(null)
    try {
      const res = await apiClient.confirmDreamweaverVideoJobAsync(currentRunId, sid)
      const data = asObject(res.data) || {}
      const statusRaw = String(data.status || '').trim().toLowerCase()
      const message = data.message != null ? String(data.message || '').trim() : ''
      const jobs = Array.isArray(data.video_clip_jobs) ? toDreamweaverVideoClipJobs(data.video_clip_jobs) : null

      if (jobs && runSnapshot) {
        setRunSnapshot((prev) => withRunSnapshotVideoJobs(prev, jobs))
      }

      if (statusRaw === 'queued' && data.task_id) {
        setRunning(true)
        setWaitingApproval(false)
        setTaskId(String(data.task_id))
        setTaskRunId(currentRunId)
        setTaskStatus('queued')
        setTaskState('VIDEO')
        setTaskStage('video')
        setTaskProgress(0)
        if (message) setError(message)
        return
      }

      if (message) setVideoJobActionError(message)
      if (!jobs) await loadRunSnapshot()
    } catch (e: unknown) {
      setVideoJobActionError(await extractApiErrorMessage(e, '确认视频片段生成失败'))
    } finally {
      setVideoJobConfirmingShotId(null)
    }
  }

  const restartGeneration = async (startState: string, shotIds?: string[], camIdxs?: number[]) => {
    const startStateRaw = String(startState || '').trim().toUpperCase()
    if (!startStateRaw) return
    if (!currentRunId) {
      setError('缺少 run_id，无法重跑（请复制调试信息排查）')
      return
    }
    if (running) {
      setError('当前 run 正在运行中，无法重跑')
      return
    }

    const normalizedShotIds = normalizeShotIds(shotIds)
    const normalizedCamIdxs = normalizeCameraIndices(camIdxs)

    const validation = validateRestartParams(startStateRaw, normalizedShotIds, normalizedCamIdxs)
    if (!validation.valid) {
      setError(validation.error || '参数验证失败')
      return
    }

    const partialHint = buildRestartPartialHint(normalizedShotIds, normalizedCamIdxs)
    const ok = window.confirm(
      `将从 ${startStateRaw} 开始重跑，并清理该阶段及其下游产物（覆盖式重跑，可能产生额外调用/成本）。${partialHint}\n\n确认继续？`,
    )
    if (!ok) return

    resetForNewRun({ resetPreview: false, resetApprovalState: false, resetRunSpecificState: false })
    setRestartLoading(true)
    setRestartAnchorEl(null)
    setRunning(true)
    setWaitingApproval(false)
    setTaskStatus('queued')
    setTaskProgress(0)
    setTaskState(startStateRaw)
    setTaskStage(null)
    setTaskArtifacts(null)
    setLibraryPlanItems([])

    try {
      const missingRoleCount = arrayLength(library?.review?.missing_roles, 0) ?? 0
      const autoAssetRolesFromMissingViews =
        startStateRaw === 'ASSET_LIBRARY' &&
        normalizedShotIds.length === 0 &&
        normalizedCamIdxs.length === 0 &&
        missingRoleCount > 0
      const res = await apiClient.restartDreamweaverAsync(currentRunId, {
        start_state: startStateRaw,
        reset_policy: 'downstream',
        qc_allow_fail: qcAllowFail,
        smart_tuning: smartTuning,
        ...(normalizedShotIds.length > 0 ? { shot_ids: normalizedShotIds } : {}),
        ...(normalizedCamIdxs.length > 0 ? { cam_idxs: normalizedCamIdxs } : {}),
        ...(autoAssetRolesFromMissingViews ? { auto_asset_roles_from_missing_views: true } : {}),
      })
      const data = toDreamweaverQueuedTaskResponse(res.data)
      if (!data) {
        throw new Error('重跑响应格式无效')
      }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id || currentRunId)
      setTaskStatus(data.status || 'queued')
    } catch (e: unknown) {
      setError(await extractApiErrorMessage(e, '重跑失败'))
      applyTerminalStatus({ run_id: currentRunId })
    } finally {
      setRestartLoading(false)
    }
  }

  const uploadShotAsset = async (shotId: string, role: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip', file: File) => {
    const safeShotId = String(shotId || '').trim()
    if (!currentRunId) {
      setDiagnosticActionError('缺少 run_id，无法上传')
      return
    }
    if (!safeShotId) {
      setDiagnosticActionError('缺少 shot_id，无法上传')
      return
    }
    if (running) {
      setDiagnosticActionError('run 正在运行中，无法上传')
      return
    }
    if (!file) return

    const isVideo = role === 'video_clip'
    const filename = String(file.name || '').toLowerCase()
    if (!isVideo && !filename.endsWith('.png')) {
      setDiagnosticActionError('仅支持 PNG 替换 head/tail/mid')
      return
    }
    if (isVideo && !filename.endsWith('.mp4')) {
      setDiagnosticActionError('仅支持 MP4 替换 video_clip')
      return
    }
    const maxMb = isVideo ? 200 : 10
    if (typeof file.size === 'number' && file.size > maxMb * 1024 * 1024) {
      setDiagnosticActionError(`文件过大（>${maxMb}MB），请压缩后再上传`)
      return
    }

    setDiagnosticActionLoading(true)
    setDiagnosticActionError(null)
    try {
      await apiClient.uploadDreamweaverRunShotAssetFile(currentRunId, safeShotId, role, file)
      await loadRunSnapshot()
    } catch (e: unknown) {
      setDiagnosticActionError(await extractApiErrorMessage(e, '上传失败'))
    } finally {
      setDiagnosticActionLoading(false)
    }
  }

  const promptAndRegenerateKeyframe = async (shotId: string, frame: 'head' | 'tail', defaultPrompt: string) => {
    const safeShotId = String(shotId || '').trim()
    if (!currentRunId) {
      setDiagnosticActionError('缺少 run_id，无法重生成')
      return
    }
    if (!safeShotId) {
      setDiagnosticActionError('缺少 shot_id，无法重生成')
      return
    }
    if (running) {
      setDiagnosticActionError('run 正在运行中，无法重生成')
      return
    }

    const initial = String(defaultPrompt || '').trim()
    const nextPrompt = window.prompt(`请输入要用于 ${safeShotId} 的 ${frame === 'head' ? '首帧' : '尾帧'} 提示词（将写入契约并用于 KEYFRAMES 重跑）`, initial)
    if (nextPrompt == null) return
    const value = String(nextPrompt || '').trim()
    if (!value) {
      setDiagnosticActionError('提示词不能为空')
      return
    }
    if (value.length > 2000) {
      setDiagnosticActionError('提示词过长（>2000）')
      return
    }

    setDiagnosticActionLoading(true)
    setDiagnosticActionError(null)
    try {
      await apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, safeShotId, frame, value)
      await loadRunSnapshot()
    } catch (e: unknown) {
      setDiagnosticActionError(await extractApiErrorMessage(e, '更新提示词失败'))
      return
    } finally {
      setDiagnosticActionLoading(false)
    }

    await restartGeneration('KEYFRAMES', [safeShotId])
  }

  const {
    scriptGenerationLabel,
    streamSnapshots,
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
  const showSnapshotShotList = isStoryboardPreviewStep && !runSnapshotLoading

  const hasSnapshotShots = snapshotShots.length > 0

  const renderSnapshotShotList = (emptyText: string) => {
    return (
      <RunSnapshotShotList
        visible={showSnapshotShotList}
        title="镜头列表"
        emptyText={emptyText}
        hasShots={hasSnapshotShots}
        shotItems={<ShotPromptSnapshotList shots={snapshotShots} />}
      />
    )
  }

  const renderSnapshotAssetPreviewSection = () => {
    const props = buildSnapshotAssetPreviewSectionProps({
      previewStep,
      runSnapshotLoading,
      snapshotShotsLength: snapshotShots.length,
      snapshotAssetCount,
      snapshotAssetSummary,
    })

    return (
      <RunSnapshotAssetPreviewSection
        {...props}
        keyframeGrid={renderRunAssetPreviewGrid('关键帧（快照）', snapshotAssetSummary.keyframes.slice(-6), 'image')}
        midframeGrid={renderRunAssetPreviewGrid('中间帧（快照）', snapshotAssetSummary.midframes.slice(-6), 'image')}
        videoClipGrid={renderRunAssetPreviewGrid('镜头片段（快照）', props.tailVideoClipPaths, 'video')}
      />
    )
  }

  const isAuditPreviewStep = previewStep === 4
  const showSnapshotMergedVideo = isAuditPreviewStep && !runSnapshotLoading
  const hasSnapshotMergedVideo = Boolean(snapshotMergedVideo)

  const renderSnapshotMergedVideoSection = () => (
    <RunSnapshotMergedVideoSection
      visible={showSnapshotMergedVideo}
      title="合成视频（快照）"
      description={hasSnapshotMergedVideo ? `合成视频：${snapshotMergedVideo}` : '暂无合成视频快照'}
      panel={hasSnapshotMergedVideo ? <MergedVideoPanel {...mergedVideoPanelProps} /> : null}
    />
  )

  const showScriptStageSnapshot = isScriptPreviewStep && !runSnapshotLoading
  const scriptStageSnapshotElement = showScriptStageSnapshot ? renderScriptStageSnapshot() : null

  const clearWsError = () => setWsError(null)

  const wsWarningAlert = wsError ? (
    <Alert severity="warning" sx={{ mb: 1 }} onClose={clearWsError}>
      {wsError}
    </Alert>
  ) : null

  const renderRunSnapshotPreviewPane = ({
    refreshLabel = '刷新运行快照',
    shotEmptyText,
    includeStreamingPreview = false,
    includeWsError = false,
  }: {
    refreshLabel?: string
    shotEmptyText: string
    includeStreamingPreview?: boolean
    includeWsError?: boolean
  }) => {
    return (
      <RunSnapshotPreviewPane
        refreshControls={
          <RunSnapshotRefreshControls
            visible={!!persistedRunId}
            label={refreshLabel}
            onRefresh={loadRunSnapshot}
            refreshDisabled={snapshotRefreshDisabled}
            refreshLoading={runSnapshotLoading}
            loaded={runSnapshotLoaded}
          />
        }
        errorAlert={<RunSnapshotErrorAlert message={runSnapshotError} spacingKey="mb" spacingValue={1} />}
        wsWarning={includeWsError ? wsWarningAlert : null}
      loadingBar={<RunSnapshotLoadingBar visible={runSnapshotLoading} spacingKey="mb" spacingValue={1} />}
      safetyBlockedAlert={renderSafetyBlockedAlert()}
      streamingPreview={includeStreamingPreview ? renderStreamingPreview(previewStep) : null}
      scriptStageSnapshot={scriptStageSnapshotElement}
      shotList={renderSnapshotShotList(shotEmptyText)}
      assetPreview={renderSnapshotAssetPreviewSection()}
      mergedVideo={renderSnapshotMergedVideoSection()}
    />
  )
  }

  const snapshotStatusSharedParams = {
    persistedRunId,
    runSnapshotLoading,
    runSnapshot,
    runSnapshotError,
    snapshotShots,
    snapshotAssetCount,
    loadRunSnapshot,
  }
  const snapshotStatusBaseProps = buildSnapshotStatusProps({ ...snapshotStatusSharedParams, includeChips: false })
  const snapshotStatusPropsWithChips = buildSnapshotStatusProps({ ...snapshotStatusSharedParams, includeChips: true })

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
    renderDebugAccordion({ title: '调试面板（Artifacts）', value: taskArtifacts, marginTop: 1 })

  const hasCandidateFrames = candidateFrameUris.length > 0

  const renderResultVideoAssetPreviewSections = () => (
    <>
      {renderRunAssetPreviewGrid('关键帧', resultKeyframePaths.slice(-6), 'image')}
      {renderRunAssetPreviewGrid('中间帧', resultMidframePaths.slice(-6), 'image')}
      {hasCandidateFrames &&
        renderRunAssetPreviewGrid('候选帧（keep_candidates）', candidateFrameUris.slice(-12), 'image')}
      {renderRunAssetPreviewGrid('镜头片段', resultVideoClipPaths.slice(-3), 'video')}
    </>
  )

  const showResultStoryboardShots = !runSnapshotLoading && snapshotShots.length > 0

  const renderResultStoryboardSnapshotSection = () => {
    if (!isStoryboardPreviewStep) return null

    return (
      <>
        <RunSnapshotSectionStatus {...snapshotStatusBaseProps} />
        {showResultStoryboardShots && (
          <Box sx={{ mt: 1 }}>
            <ShotPromptSnapshotList shots={snapshotShots} />
          </Box>
        )}
      </>
    )
  }

  const videoFallbackAlert = videoDiagnostics.fallbackCount > 0 ? <DreamweaverResultVideoFallbackAlert /> : null
  const videoClipPathSummary = resultVideoClipPaths.length > 0 ? <DreamweaverResultVideoClipPathSummary paths={resultVideoClipPaths} /> : null

  const isVideoPreviewStep = previewStep === 3
  const isLibraryPreviewStep = previewStep === 2
  const showVideoSnapshotStatus = isVideoPreviewStep
  const videoSnapshotStatus = showVideoSnapshotStatus ? <RunSnapshotSectionStatus {...snapshotStatusPropsWithChips} /> : null

  const videoSummarySectionProps = buildVideoSummarySectionProps(result?.merged_video, videoDiagnostics)

  const hasMergedVideo = Boolean(result?.merged_video)
  const mergedVideoPanel = hasMergedVideo ? <MergedVideoPanel {...mergedVideoPanelProps} centeredPreview /> : null

  const renderResultVideoStageView = () => !result ? null : (
    <DreamweaverResultVideoStageView
      assetPreviewSections={renderResultVideoAssetPreviewSections()}
      videoSummarySection={
        <DreamweaverResultVideoSummarySection
          {...videoSummarySectionProps}
        />
      }
      fallbackAlert={videoFallbackAlert}
      clipPathSummary={videoClipPathSummary}
      mergedVideoPanel={mergedVideoPanel}
      snapshotStatus={videoSnapshotStatus}
    />
  )

  const renderResultPlanStageView = () => (
    <DreamweaverResultTextStageSection
      title="计划 / 剧本提要"
      text={resultPlanText}
      emptyText="未返回文本"
    />
  )

  const storyboardSummaryText = result?.storyboard ? `${result.storyboard.length} 个镜头` : '暂无'

  const renderResultStoryboardStageView = () => (
    <DreamweaverResultStoryboardStageView
      storyboardSummary={storyboardSummaryText}
      snapshotSection={renderResultStoryboardSnapshotSection()}
    />
  )

  const renderResultLibraryHintView = () => (
    <DreamweaverResultLibraryHint message="素材库为项目维度产物，可切换到“素材”并点击“加载素材库”查看/审核。" />
  )

  const auditText = result?.audit ? JSON.stringify(result.audit) : ''

  const renderResultAuditStageView = () => (
    <DreamweaverResultTextStageSection
      title="质检"
      text={auditText}
      emptyText="未返回审核信息"
      marginTop={1}
      marginBottom={0}
    />
  )

  const runSnapshotLoaded = Boolean(runSnapshot && runSnapshot.run_id === persistedRunId)

  const handleSyncEvents = currentRunId ? () => syncDreamweaverEvents(currentRunId) : null

  const eventSyncDisabled = !currentRunId || eventSyncing

  const snapshotRefreshDisabled = isSnapshotRefreshDisabled(persistedRunId, runSnapshotLoading)

  const renderResultSyncActions = () => (
    <DreamweaverResultSyncActionsBar
      refreshButton={
        <RunSnapshotRefreshButton
          label="刷新运行快照"
          onClick={loadRunSnapshot}
          disabled={snapshotRefreshDisabled}
          loading={runSnapshotLoading}
        />
      }
      onSync={handleSyncEvents}
      syncInProgress={eventSyncing}
      syncDisabled={eventSyncDisabled}
      loadedChip={<RunSnapshotLoadedChip visible={runSnapshotLoaded} />}
      eventCursor={eventCursor}
    />
  )

  const snapshotErrorAlert = <RunSnapshotErrorAlert message={runSnapshotError} spacingKey="mb" spacingValue={1} />
  const snapshotLoadingBar = <RunSnapshotLoadingBar visible={runSnapshotLoading} spacingKey="mb" spacingValue={1} />

  const renderResultSyncStatus = () => (
    <DreamweaverResultSyncStatusPanel
      snapshotErrorAlert={snapshotErrorAlert}
      eventSyncError={eventSyncError}
      snapshotLoadingBar={snapshotLoadingBar}
    />
  )

  const renderResultDebugPanel = () => (
    <>
      {renderDebugAccordion({
        title: '调试面板（Result）',
        value: result,
        marginBottom: 1.5,
      })}
      <Divider sx={{ my: 1.5 }} />
    </>
  )

  const showResultPlanStage = isScriptPreviewStep || isAuditPreviewStep
  const showResultStoryboardStage = isStoryboardPreviewStep || isAuditPreviewStep
  const showResultLibraryStage = isLibraryPreviewStep
  const showResultVideoStage = isVideoPreviewStep || isAuditPreviewStep
  const showResultAuditStage = isAuditPreviewStep

  const renderResultView = () => !result ? null : (
    <DreamweaverRunResultView
      chapterCount={resultChapterCount}
      keyframeCount={resultKeyframeCount}
      midframeCount={resultMidframeCount}
      videoClipCount={resultVideoClipCount}
      debugPanel={renderResultDebugPanel()}
      syncActions={renderResultSyncActions()}
      syncStatus={renderResultSyncStatus()}
      streamingPreview={renderStreamingPreview(previewStep)}
      planStage={showResultPlanStage ? renderResultPlanStageView() : null}
      storyboardStage={showResultStoryboardStage ? renderResultStoryboardStageView() : null}
      libraryStage={showResultLibraryStage ? renderResultLibraryHintView() : null}
      videoStage={showResultVideoStage ? renderResultVideoStageView() : null}
      auditStage={showResultAuditStage ? renderResultAuditStageView() : null}
    />
  )

  const resolveShotDiagnosticAccordionStateLocal = (shot: DreamweaverDiagnosticShot) =>
    resolveShotDiagnosticAccordionState(shot, diagnosticResult, diagnosticProviderTraceByShotId)

  const renderShotDiagnosticUploadActions = (shotId: string) => (
    <ShotDiagnosticUploadActions shotId={shotId} uploadDisabled={diagnosticUploadDisabled} onUpload={uploadShotAsset} />
  )

  const renderShotDiagnosticPromptRegenerateActions = (shotId: string, sb: Record<string, unknown> | null) => (
    <ShotDiagnosticPromptRegenerateActions
      shotId={shotId}
      sb={sb}
      actionDisabled={diagnosticUploadDisabled}
      onPromptAndRegenerateKeyframe={promptAndRegenerateKeyframe}
      getDiagnosticStoryboardPrompt={getDiagnosticStoryboardPrompt}
    />
  )

  const renderShotProviderTraceSection = (shotProviderTrace: DreamweaverVideoProviderShotTrace | null) => (
    <ShotProviderTraceSection shotProviderTrace={shotProviderTrace} safeJsonStringify={safeJsonStringify} renderDiagnosticJson={renderDiagnosticJson} />
  )

  const renderShotDiagnosticAccordion = (shot: DreamweaverDiagnosticShot) => {
    const {
      shotId,
      frames: rawFrames,
      sb,
      desc,
      duration,
      shotAutoQC,
      shotAutoQCPass,
      shotAutoQCScore,
      shotProviderTrace,
      videoClip,
      hasVideoClip,
    } = resolveShotDiagnosticAccordionStateLocal(shot)
    const frames = rawFrames ?? { head: null, tail: null, mid: null }
    const hasHeadFrame = Boolean(frames.head)
    const hasTailFrame = Boolean(frames.tail)
    const hasMidFrame = Boolean(frames.mid)
    const isShadowed = Boolean(shotProviderTrace?.shadowed)
    const shotCopyPayload = buildShotDiagnosticCopyPayload({
      shotId,
      sb,
      frames,
      videoClip,
      shotProviderTrace,
      shotAutoQC,
    })

    return (
      <DreamweaverDiagnosticShotAccordion
        accordionKey={`diag:${shotId}`}
        summary={
          <DreamweaverDiagnosticShotSummary
            shotId={shotId}
            desc={desc}
            duration={duration}
            hasHeadFrame={hasHeadFrame}
            hasTailFrame={hasTailFrame}
            hasMidFrame={hasMidFrame}
            hasVideoClip={hasVideoClip}
            route={shotProviderTrace?.route}
            appliedProvider={shotProviderTrace?.applied_provider}
            shadowed={isShadowed}
            autoQCPass={shotAutoQCPass}
            autoQCScore={shotAutoQCScore}
          />
        }
        actions={
          <DreamweaverDiagnosticShotActions
            onCopy={() => copyText(safeJsonStringify(shotCopyPayload))}
            onCopyStoryboard={sb ? () => copyText(safeJsonStringify(sb)) : null}
            uploadActions={renderShotDiagnosticUploadActions(shotId)}
            promptRegenerateActions={renderShotDiagnosticPromptRegenerateActions(shotId, sb)}
            onRestartVideo={shotId ? () => void restartGeneration('VIDEO', [shotId]) : null}
            restartDisabled={restartActionDisabled}
          />
        }
        details={
          <DreamweaverDiagnosticShotDetails
            storyboardAccordion={renderTitledDiagnosticJsonAccordion({
              title: '分镜（storyboard）',
              value: sb,
              marginTop: 0,
            })}
            providerTraceSection={renderShotProviderTraceSection(shotProviderTrace)}
            autoqcAccordion={renderTitledDiagnosticJsonAccordion({
              title: 'AutoQC',
              value: shotAutoQC,
            })}
            headFrame={renderDiagnosticFrame('首帧（head）', frames.head, 'image')}
            tailFrame={renderDiagnosticFrame('尾帧（tail）', frames.tail, 'image')}
            midFrame={renderDiagnosticFrame('中间帧（mid）', frames.mid, 'image')}
            videoFrame={renderDiagnosticFrame('镜头片段（video_clip）', videoClip, 'video')}
          />
        }
      />
    )
  }

  const renderDiagnosticPreflightSection = () => {
    if (!diagnosticPreflight) return null

    const videoConfig = resolvePreflightVideoConfig(diagnosticPreflight)
    const preflightErrorCount = diagnosticPreflight.errors.length
    const preflightWarningCount = diagnosticPreflight.warnings.length

    return (
      <DreamweaverDiagnosticPreflightSection
        allowed={diagnosticPreflight.allowed}
        errorCount={preflightErrorCount}
        warningCount={preflightWarningCount}
        {...videoConfig}
        errors={diagnosticPreflight.errors}
        warnings={diagnosticPreflight.warnings}
        onCopy={() => copyText(safeJsonStringify(diagnosticPreflight))}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({ title: 'preflight', value: diagnosticPreflight })}
      />
    )
  }

  const renderDiagnosticProviderTraceSection = () => {
    if (!diagnosticProviderTrace) return null

    const traceSummary = resolveProviderTraceSummaryProps(diagnosticProviderTraceSummary)
    const providerFeatureFlags = resolveProviderTraceFeatureFlags(diagnosticProviderTrace)

    return (
      <DreamweaverDiagnosticProviderTraceSection
        providerMode={diagnosticProviderTrace.provider_mode}
        selectorMode={diagnosticProviderTrace.selector_mode}
        {...traceSummary}
        featureFlags={providerFeatureFlags}
        onCopy={() => copyText(safeJsonStringify(diagnosticProviderTrace))}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'video_provider_trace',
          value: diagnosticProviderTrace,
        })}
      />
    )
  }

  const renderDiagnosticSmartDispatchSection = () => {
    if (!diagnosticSmartDispatchTrace) return null

    const { routing, prompt, attemptedModels } = resolveSmartDispatchTraceDetails(diagnosticSmartDispatchTrace)
    const summaryProps = resolveSmartDispatchSummaryProps(diagnosticSmartDispatchTraceSummary)
    const promptAccordion = prompt
      ? renderTitledDiagnosticJsonAccordion({ title: 'prompt_trace', value: prompt })
      : null
    const routingAccordion = routing
      ? renderTitledDiagnosticJsonAccordion({ title: 'routing_trace', value: routing })
      : null

    return (
      <DreamweaverDiagnosticSmartDispatchSection
        {...summaryProps}
        attemptedModels={attemptedModels}
        onCopy={() => copyText(safeJsonStringify(diagnosticSmartDispatchTrace))}
        promptAccordion={promptAccordion}
        routingAccordion={routingAccordion}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'smart_dispatch_trace',
          value: diagnosticSmartDispatchTrace,
        })}
      />
    )
  }

  const telemetryAbVariant = typeof snapshotRuntimeConfig?.ab_variant === 'string' ? snapshotRuntimeConfig.ab_variant : undefined

  const renderDiagnosticTelemetrySection = () => {
    if (!snapshotTelemetrySummary) return null

    const telProps = resolveTelemetrySectionProps({
      summary: snapshotTelemetrySummary,
      abVariant: telemetryAbVariant,
      counters: snapshotTelemetryCounters,
    })

    return (
      <DreamweaverDiagnosticTelemetrySection
        {...telProps}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'Telemetry JSON',
          value: snapshotTelemetry,
        })}
      />
    )
  }

  const buildCameraDiagnosticPayload = () =>
    buildCameraDiagnosticPayloadHelper(diagnosticCameraDiagnostics)

  const renderDiagnosticCameraDiagnosticsSection = () => {
    if (!hasCameraDiagnosticsData(diagnosticCameraDiagnostics)) {
      return null
    }
    const { cameraCount, sceneCount } = resolveCameraCounts(diagnosticCameraDiagnostics)
    const scenePreview = hasDiagnosticCameraSceneUris
      ? renderRunAssetPreviewGrid(
          '相机场景（每个相机首镜头 head）',
          diagnosticCameraSceneUris.slice(0, 12),
          'image',
        )
      : null

    return (
      <DreamweaverDiagnosticCameraDiagnosticsSection
        mode={diagnosticCameraDiagnostics.mode}
        cameraCount={cameraCount}
        sceneCount={sceneCount}
        onCopy={() => copyText(safeJsonStringify(buildCameraDiagnosticPayload()))}
        scenePreview={scenePreview}
        {...buildCameraAccordionProps(diagnosticCameraDiagnostics, (title: string, value: unknown) =>
          renderTitledDiagnosticJsonAccordion({ title, value }),
        )}
      />
    )
  }

  const renderPendingRunningView = () => {
    const state = resolvePendingRunningState({
      taskStatus,
      taskQueue,
    })
    const stageHint = PENDING_STAGE_HINTS[previewStep] || ''
    const stageHintElement = stageHint ? <PendingRunningStageHint message={stageHint} /> : null
    const artifactDetails = hasArtifactLines ? <PendingArtifactDetails lines={artifactLines} /> : null

    return (
      <PendingRunningShell
        state={state}
        stageHint={stageHintElement}
        snapshotPreview={renderRunSnapshotPreviewPane({
          shotEmptyText: state.snapshotShotEmptyText,
          includeStreamingPreview: true,
          includeWsError: true,
        })}
        artifactsSummary={
          <PendingRunningArtifactsSummary
            chips={artifactChips}
            onCopyDebug={copyDebugInfo}
            onOpenDiagnostic={openDiagnosticDialog}
            diagnosticDisabled={!currentRunId}
          />
        }
        artifactDetails={artifactDetails}
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const scriptEntitySummary = scriptEntities ? summarizeScriptEntities(scriptEntities) : ''

  const confirmScriptApproval = () => approveScriptWrapper(true)
  const revokeScriptApproval = () => approveScriptWrapper(false)

  const scriptGenMode = scriptGeneration?.mode
  const scriptGenError = scriptGeneration?.error

  const scriptGenLabel = scriptGenerationLabel || ''

  const scriptEditorDisabled = scriptLoading

  const renderPendingScriptApprovalView = () => {
    const state = resolvePendingScriptApprovalState({
      scriptText,
      scriptGenerationLabel: scriptGenLabel,
      scriptGenerationMode: scriptGenMode,
      scriptGenerationError: scriptGenError,
      scriptRequiresReview,
      scriptApproved,
      scriptDirty,
      currentRunId,
      scriptLoading,
      canResumeFromScript,
      resumeLoading,
      scriptError,
      entitySummary: scriptEntitySummary,
    })

    return (
      <PendingScriptApprovalShell
        state={state}
        onLoadScript={loadScriptWrapper}
        onSaveScript={saveScriptWrapper}
        onApproveScript={confirmScriptApproval}
        onRevokeScript={revokeScriptApproval}
        onResume={resumeGeneration}
        editor={<PendingScriptApprovalEditor value={scriptText} onChange={setScriptText} disabled={scriptEditorDisabled} />}
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const shotFramePromptGetter = getShotFramePrompt as (frame: unknown) => string
  const shotVideoPromptOverrideGetter = getShotVideoPromptOverride as (shot: unknown) => string

  const renderPendingVideoConfirmationJobItem = (job: DreamweaverVideoClipJob, idx: number) => {
    const sid = String(job.shot_id || '').trim()
    const shot = sid ? snapshotShotById.get(sid) ?? null : null
    const state = resolvePendingVideoConfirmationJobState({
      job,
      shot,
      running,
      videoJobConfirmingShotId,
      getShotFramePrompt: shotFramePromptGetter,
      getShotVideoPromptOverride: shotVideoPromptOverrideGetter,
      snapshotShotById,
    })

    return (
      <PendingVideoConfirmationJobItem
        itemKey={sid || String(idx)}
        shot={shot}
        state={state}
        onConfirm={confirmVideoJob}
        onEditPrompt={openPromptEditDialog}
      />
    )
  }

  const renderPendingPromptReviewShotItem = (shot: DreamweaverShotSnapshot, idx: number) => {
    const shotId = getShotId(shot)
    const shotDesc = getShotDesc(shot)
    const headPrompt = getShotFramePrompt(shot.head_frame)
    const tailPrompt = getShotFramePrompt(shot.tail_frame)
    const overridePrompt = getShotVideoPromptOverride(shot)
    const state = resolvePendingPromptReviewShotState({
      shotId,
      title: shotDesc,
      shotIndex: shot.shot_index ?? idx + 1,
      headPrompt,
      tailPrompt,
      overridePrompt,
    })

    return (
      <PendingPromptReviewShotItem
        itemKey={shotId || String(idx)}
        shot={shot}
        state={state}
        onEditPrompt={openPromptEditDialog}
      />
    )
  }

  const videoClipJobCount = videoClipJobs.length

  const renderPendingVideoConfirmationView = () => {
    const state = resolvePendingVideoConfirmationState({
      videoJobActionError,
      persistedRunId,
      runSnapshotLoading,
      videoClipJobCount,
    })

    return (
      <PendingVideoConfirmationView
        state={state}
        jobItems={videoClipJobs.map(renderPendingVideoConfirmationJobItem)}
        onRefresh={rebuildVideoJobs}
      />
    )
  }

  const confirmPromptReview = () => approvePromptReview(true)
  const revokePromptReview = () => approvePromptReview(false)
  const togglePromptReviewShowAll = () => setPromptReviewShowAll((prev) => !prev)

  const promptReviewShotCount = promptReviewShots.length

  const renderPendingPromptReviewView = () => {
    const state = resolvePendingPromptReviewState({
      promptReviewApproved,
      libraryApproved,
      persistedRunId,
      runSnapshotLoading,
      currentRunId,
      promptReviewLoading,
      canResumeFromLibrary,
      resumeLoading,
      promptReviewError,
      promptReviewShotCount,
      snapshotShotCount: snapshotShots.length,
      promptReviewShowAll,
    })

    return (
      <PendingPromptReviewView
        state={state}
        shotItems={promptReviewShots.map(renderPendingPromptReviewShotItem)}
        revokeLabel="撤销确认"
        onRefresh={loadRunSnapshot}
        onApprove={confirmPromptReview}
        onRevoke={revokePromptReview}
        onResume={resumeGeneration}
        onToggleShowAll={togglePromptReviewShowAll}
      />
    )
  }

  const renderCharacterLibraryBucketSection = (bucket: CharacterLibraryBucket) => {
    const bucketItemCount = bucket.items.length
    const generatedCount = bucket.items.filter((item) => Boolean(item.hasRenderableImage)).length

    return (
      <DreamweaverCharacterLibraryBucketSection
        bucketKey={bucket.bucketKey}
        name={bucket.name}
        viewCount={bucketItemCount}
        generatedCount={generatedCount}
        content={
          <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
            {bucket.items.map(renderLibraryDisplayCard)}
          </ImageList>
        }
      />
    )
  }

  const renderLibrarySummaryChips = (summary: LibraryGroupSummary, totalLabel: string) => (
    <DreamweaverLibrarySummaryChips totalLabel={totalLabel} summary={summary} />
  )

  const renderCharacterLibraryGroupGrid = (items: LibraryDisplayItem[]) => {
    const orderedBuckets = buildCharacterLibraryBuckets(items)

    return (
      <Stack spacing={1}>
        {orderedBuckets.map(renderCharacterLibraryBucketSection)}
      </Stack>
    )
  }

  const renderLibraryGroupGrid = (group: LibraryDisplayGroup) => {
    if (group.key !== 'character') {
      return (
        <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
          {group.items.map(renderLibraryDisplayCard)}
        </ImageList>
      )
    }

    return renderCharacterLibraryGroupGrid(group.items)
  }

  const renderLibraryGroupSection = (group: LibraryDisplayGroup) => (
    <DreamweaverLibraryGroupSection
      groupKey={group.key}
      label={group.label}
      summaryChips={renderLibrarySummaryChips(group.summary, '总计')}
      content={renderLibraryGroupGrid(group)}
    />
  )

  const renderPendingLibrarySummaryChips = () => renderLibrarySummaryChips(librarySummary, '占位')

  const approveAllLibrary = () => approveLibrary({ approve_all: true, approved: true })

  const renderPendingLibraryReviewView = () => {
    const noticeSeverity = resolvePendingLibraryNoticeSeverity(libraryApproved, promptReviewReady, false)
    const controlsProps = buildPendingLibraryControlsProps({
      selectedProjectId,
      libraryLoading,
      canResumeFromLibrary,
      resumeLoading,
    })
    const runtimeStatusProps = buildPendingLibraryRuntimeStatusProps({
      libraryError,
      libraryLoading,
      library,
    })

    const librarySummaryChips = hasLibraryItems ? renderPendingLibrarySummaryChips() : null
    const libraryGroupSections = hasLibraryItems ? <>{libraryGroups.map(renderLibraryGroupSection)}</> : null

    return (
      <PendingLibraryReviewShell
        notice={
          <PendingLibraryNotice
            severity={noticeSeverity}
            message={libraryPromptReviewMessage}
          />
        }
        controls={
          <PendingLibraryControls
            onLoadLibrary={loadLibrary}
            onApproveAll={approveAllLibrary}
            {...controlsProps}
            onResume={resumeGeneration}
          />
        }
        runtimeStatus={
          <PendingLibraryRuntimeStatus {...runtimeStatusProps} />
        }
        summarySection={
          <PendingLibrarySummarySection
            emptyText="未加载素材库或当前项目暂无可审核素材。"
            summaryChips={librarySummaryChips}
            groups={libraryGroupSections}
          />
        }
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const viewLibraryStep = () => handleClickStep(2)
  const viewPromptReviewStep = () => handleClickStep(1)

  const libraryResumeDisabled = !canResumeFromLibrary

  const renderPendingLibraryReadyView = () => {
    const noticeSeverity = resolvePendingLibraryNoticeSeverity(libraryApproved, promptReviewReady, true)

    return (
      <PendingLibraryReadyShell
        notice={
          <PendingLibraryNotice
            severity={noticeSeverity}
            message={libraryPromptReviewMessage}
            action={
              <PendingLibraryReadyActions
                onViewLibrary={viewLibraryStep}
                showPromptReviewAction={promptReviewRequiredSnapshot}
                onViewPromptReview={viewPromptReviewStep}
                onResume={resumeGeneration}
                resumeDisabled={libraryResumeDisabled}
                resumeLoading={resumeLoading}
              />
            }
          />
        }
        snapshotPreview={renderRunSnapshotPreviewPane({
          shotEmptyText: '尚无可用分镜快照（可能尚未落库）。',
        })}
      />
    )
  }

  const renderPendingEmptyState = () => (
    <PendingEmptyState description={`点击“开始生成”后，这里会展示「${DREAMWEAVER_PREVIEW_STEPS[previewStep]}」相关产物与进度。`} />
  )

  const renderPendingView = () => {
    const mode = resolvePendingViewMode({
      running,
      waitingScriptApproval,
      waitingVideoConfirmation,
      promptReviewRequiredSnapshot,
      previewStep,
      currentRunId,
    })

    switch (mode) {
      case 'running':
        return renderPendingRunningView()
      case 'script_approval':
        return renderPendingScriptApprovalView()
      case 'video_confirmation':
        return renderPendingVideoConfirmationView()
      case 'prompt_review':
        return renderPendingPromptReviewView()
      case 'library_review':
        return renderPendingLibraryReviewView()
      case 'library_ready':
        return renderPendingLibraryReadyView()
      case 'empty':
      default:
        return renderPendingEmptyState()
    }
  }

  const buildRunDiagnosticPayload = () =>
    buildRunDiagnosticPayloadHelper({
      currentRunId,
      taskStatus,
      taskState,
      taskStage,
      diagnosticPreflight,
      diagnosticProviderTrace,
      diagnosticSmartDispatchTrace,
      snapshotRuntimeConfig,
      cameraDiagnosticsGeneration: diagnosticCameraDiagnostics.generation,
      cameraDiagnosticsCameraTree: diagnosticCameraDiagnostics.cameraTree,
      cameraDiagnosticsCameraStates: diagnosticCameraDiagnostics.cameraStates,
      cameraDiagnosticsCameraScenes: diagnosticCameraDiagnostics.cameraScenes,
      diagnosticResult,
    })

  const hasDiagnosticShots = diagnosticResult && diagnosticShots.length > 0

  const copyRunDiagnosticPayload = () => copyText(safeJsonStringify(buildRunDiagnosticPayload()))

  const renderDiagnosticDialog = () => {
    const dialogProps = buildDiagnosticDialogProps({
      currentRunId,
      diagnosticResult,
      diagnosticActionError,
      diagnosticActionLoading,
      diagnosticShots,
      persistedRunId,
      runSnapshotLoading,
      diagnosticPreflight,
      diagnosticProviderTrace,
      diagnosticSmartDispatchTrace,
    })

    const diagnosticShotAccordions = hasDiagnosticShots ? diagnosticShots.map(renderShotDiagnosticAccordion) : null

    return (
      <DreamweaverRunDiagnosticDialog
        open={diagnosticOpen}
        onClose={closeDiagnosticDialog}
        {...dialogProps}
        onRefresh={loadRunSnapshot}
        onCopy={copyRunDiagnosticPayload}
        sections={
          <>
            {renderDiagnosticPreflightSection()}
            {renderDiagnosticProviderTraceSection()}
            {renderDiagnosticSmartDispatchSection()}
            {renderDiagnosticTelemetrySection()}
            {renderDiagnosticCameraDiagnosticsSection()}
          </>
        }
        shotAccordions={diagnosticShotAccordions}
      />
    )
  }

  const promptEditShotTitle = getShotId(promptEditShot) || '未选中'
  const promptEditShotDesc = promptEditShot ? getShotDesc(promptEditShot) : null
  const promptEditGeneratedText = promptEditGenerated || '暂无自动提示词（可能尚未生成或未落库）'

  const renderPromptEditDialog = () => (
    <DreamweaverPromptEditDialog
      open={promptEditOpen}
      onClose={closePromptEditDialog}
      shotTitle={promptEditShotTitle}
      shotDescription={promptEditShotDesc}
      headPrompt={promptEditHead}
      tailPrompt={promptEditTail}
      generatedPrompt={promptEditGeneratedText}
      videoPrompt={promptEditVideo}
      saving={promptEditSaving}
      error={promptEditError}
      onChangeHead={setPromptEditHead}
      onChangeTail={setPromptEditTail}
      onChangeVideo={setPromptEditVideo}
      onSave={savePromptEdit}
    />
  )

  const handleRegenPromptChange = (value: string) => {
    setRegenPrompt(value)
    setRegenPromptDirty(value.trim() !== regenPromptInitial.trim())
  }

  const hasRegenRole = Boolean(regenRole)

  const regenMissingRefLabel = regenAlertMissingReferenceLabel || ''

  const regenDialogTitle = regenTitle || regenRole

  const requestSmartRegeneratePromptManual = () => requestSmartRegeneratePrompt({ source: 'manual' })

  const renderRegenerateDialog = () => {
    const labels = resolveRegenerateDialogLabels({
      imageEditActive: regenImageEditActive,
      imageEditAutoCleared: regenImageEditAutoCleared,
      submitting: regenSubmitting,
    })

    return (
      <DreamweaverRegenerateDialog
        open={regenOpen}
        onClose={closeRegenDialog}
        title={`重生成素材：${regenDialogTitle}`}
        modeHint={labels.modeHint}
      suggesting={regenSuggesting}
      submitting={regenSubmitting}
      hasRole={hasRegenRole}
      forceImageEdit={regenForceImageEdit}
      imageEditActive={regenImageEditActive}
      hasImageBase={regenHasImageBase}
      alertBaseLabel={regenAlertBaseLabel}
      alertReadyReferenceLabel={regenAlertReadyReferenceLabel}
      alertReadyReferenceCount={regenAlertReadyReferenceCount}
      alertMissingReferenceLabel={regenMissingRefLabel}
      suggestError={regenSuggestError}
      imageEditAutoCleared={regenImageEditAutoCleared}
      promptInputLabel={regenPromptInputLabel}
      prompt={regenPrompt}
      promptPlaceholder={labels.promptPlaceholder}
      error={regenError}
      submitLabel={labels.submitLabel}
        submitDisabled={resolveRegenerateSubmitDisabled({
          submitting: regenSubmitting,
          suggesting: regenSuggesting,
          hasRole: hasRegenRole,
          forceImageEdit: regenForceImageEdit,
          hasImageBase: regenHasImageBase,
        })}
      onSmartGenerate={requestSmartRegeneratePromptManual}
      onToggleImageEdit={toggleRegenImageEditPreference}
      onChangePrompt={handleRegenPromptChange}
      onSubmit={submitRegenerateDialog}
      />
    )
  }

  const historyRefreshDisabled = historyLoading || !selectedProjectId
  const historyBulkDeleteDisabled = historyLoading || bulkDeleteTargetCount === 0

  const historyRunCount = historyRuns.length
  const historyNoLoadingOrError = !historyLoading && !historyError
  const historyEmpty = historyNoLoadingOrError && historyRunCount === 0
  const historyFilterEmpty = historyNoLoadingOrError && historyRunCount > 0 && filteredHistoryRuns.length === 0

  const clearHistoryStatusFilters = () => setHistoryStatusFilters([])
  const refreshHistory = () => { if (selectedProjectId) fetchRunHistory(selectedProjectId) }

  const toggleHistoryStatusFilter = (status: string) => {
    setHistoryStatusFilters((prev) =>
      prev.includes(status) ? prev.filter((item) => item !== status) : [...prev, status],
    )
  }

  const selectedProjectTitle = selectedProject?.title

  const historyRunItems = mapHistoryRunsToItems(filteredHistoryRuns).map((item) => ({
    ...item,
    onView: () => handleViewHistoryRun(item.runId),
    onDelete: () => openDeleteRunDialog(item.runId),
  })) as DreamweaverHistoryRunListItem[]

  const renderHistoryDialog = () => (
    <DreamweaverHistoryDialog
      open={historyOpen}
      onClose={closeHistoryDialog}
      projectTitle={selectedProjectTitle}
      error={historyError}
      loading={historyLoading}
      filterItems={buildHistoryFilterItems({
        totalRuns: historyRunCount,
        statusFilters: historyStatusFilters,
        statusCounts: historyStatusCounts,
        onClearFilters: clearHistoryStatusFilters,
        onToggleFilter: toggleHistoryStatusFilter,
      })}
      onRefresh={refreshHistory}
      refreshDisabled={historyRefreshDisabled}
      onBulkDelete={openBulkDeleteDialog}
      bulkDeleteDisabled={historyBulkDeleteDisabled}
      bulkDeleteLabel={`批量删除筛选结果 (${bulkDeleteTargetCount})`}
      runs={historyRunItems}
      showEmptyHistory={historyEmpty}
      showEmptyFilter={historyFilterEmpty}
    />
  )

  const renderBulkDeleteDialog = () => (
    <DreamweaverBulkDeleteDialog
      open={bulkDeleteDialogOpen}
      onClose={closeBulkDeleteDialog}
      targetCount={bulkDeleteTargetCount}
      skippedCount={bulkDeleteSkippedCount}
      progress={bulkDeleteProgress}
      error={bulkDeleteError}
      result={bulkDeleteResult}
      submitting={bulkDeleteSubmitting}
      onConfirm={confirmBulkDeleteRuns}
    />
  )

  const confirmDeleteCurrentRun = () => confirmDeleteRun(selectedProjectId)

  const renderDeleteRunDialog = () => (
    <DreamweaverDeleteRunDialog
      open={deleteDialogOpen}
      onClose={closeDeleteRunDialog}
      runId={deleteRunId}
      error={deleteDialogError}
      submitting={deleteSubmitting}
      onConfirm={confirmDeleteCurrentRun}
    />
  )

  const closeConfigDialog = () => setConfigDialogOpen(false)

  const refreshChapters = () => {
    if (selectedProjectId) void handleSelectProject(selectedProjectId)
  }

  const openProjectList = () => {
    closeConfigDialog()
    navigate('/drama')
  }

  const clearTaskPointsPrecheckError = () => {
    setTaskPointsPrecheckError(null)
    setError(null)
  }

  const runFromConfigDialog = async () => {
    const ok = await handleRun()
    if (ok) closeConfigDialog()
  }

  const configDialogErrorNotice = taskPointsPrecheckError
    ? <TaskPointsPrecheckAlert detail={taskPointsPrecheckError} onClose={clearTaskPointsPrecheckError} sx={{ mb: 2 }} />
    : error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null

  const chapterRefreshDisabled = loadingChapters || !selectedProjectId || running
  const selectedChapterCount = selectedChapterIds.length

  const configSubtitle = buildConfigDialogSubtitle(selectedProjectTitle, selectedProjectId, selectedChapterCount, chapters.length)

  const renderConfigDialog = () => (
    <DreamweaverRunConfigDialog
      open={configDialogOpen}
      onClose={closeConfigDialog}
      fullScreen={configDialogFullScreen}
      subtitle={configSubtitle}
      errorNotice={configDialogErrorNotice}
      lockedProjectId={lockedProjectId}
      projectTitle={selectedProjectTitle}
      onOpenProjectList={openProjectList}
      selectedChapterIds={selectedChapterIds}
      chapters={chapters}
      loadingChapters={loadingChapters}
      running={running}
      onToggleAll={handleSelectAll}
      onRefreshChapters={refreshChapters}
      refreshDisabled={chapterRefreshDisabled}
      onToggleChapter={handleToggleChapter}
      strategyFields={buildStrategyFields({
        highQuality,
        setHighQuality,
        smartTuning,
        setSmartTuning,
        videoRequireConfirmation,
        setVideoRequireConfirmation,
        promptReviewRequired,
        setPromptReviewRequired,
        qcAllowFail,
        setQcAllowFail,
      })}
      abVariant={abVariant}
      onChangeAbVariant={setAbVariant}
      lockedGenerationConfigError={lockedGenerationConfigError}
      generationConfigLocked={generationConfigLocked}
      lockedGenerationConfigSourceRunId={lockedGenerationConfig?.source_run_id}
      {...buildVisualFieldProps({
        stylePreset, setStylePreset, stylePresetOptions: STYLE_PRESET_OPTIONS,
        imageRatio, setImageRatio, imageRatioOptions: IMAGE_RATIO_OPTIONS,
        imageResolution, setImageResolution, imageResolutionOptions: IMAGE_RESOLUTION_OPTIONS,
      })}
      visualFieldsDisabled={visualFieldsDisabled}
      {...buildModelFieldProps({
        imageModel, setImageModel, imageModelOptions: dreamweaverImageModelOptions,
        videoModel, setVideoModel, videoModelOptions: dreamweaverVideoModelOptions,
        videoEditModel, setVideoEditModel, videoEditModelOptions: dreamweaverVideoEditModelOptions,
        visionModel, setVisionModel, visionModelOptions: dreamweaverVisionModelOptions,
      })}
      {...buildToggleFieldProps({
        enableVideoEdit, setEnableVideoEdit,
        enableVisionReview, setEnableVisionReview,
        enableSafetyAudit, setEnableSafetyAudit,
        safetyFailPolicy, setSafetyFailPolicy,
        safetyFailPolicyOptions: SAFETY_FAIL_POLICY_OPTIONS,
      })}
      onRun={runFromConfigDialog}
      runDisabled={resolveConfigRunDisabled({
        running,
        lockedGenerationConfigLoading,
        selectedProjectId,
        selectedChapterIdsLength: selectedChapterCount,
      })}
    />
  )

  const openConfigDialog = () => setConfigDialogOpen(true)

  const closeRestartMenu = () => setRestartAnchorEl(null)

  const triggerRestartFromStage = (startState: string) => {
    closeRestartMenu()
    void restartGeneration(startState)
  }

  const requestRestartVideoShots = () => {
    closeRestartMenu()
    const raw = window.prompt('请输入需要重跑的镜头 shot_id（多个用逗号分隔）', '')
    const ids = parsePromptedIds(raw)
    if (ids.length === 0) {
      setError('未输入有效 shot_id')
      return
    }
    void restartGeneration('VIDEO', ids)
  }

  const requestRestartKeyframeCameras = () => {
    closeRestartMenu()
    const raw = window.prompt('请输入需要重跑的相机 cam_idx（多个用逗号分隔）', '')
    const unique = parsePromptedCameraIndices(raw)
    if (unique.length === 0) {
      setError('未输入有效 cam_idx')
      return
    }
    void restartGeneration('KEYFRAMES', undefined, unique)
  }

  const openRestartMenu = (e: React.MouseEvent<HTMLElement>) => setRestartAnchorEl(e.currentTarget)

  const copyDebugIcon = <ContentCopyIcon fontSize="small" />
  const diagnosticsIcon = <BugReportIcon fontSize="small" />
  const historyIcon = <HistoryIcon fontSize="small" />
  const restartIcon = <RefreshIcon fontSize="small" />

  const restartActionLabel = restartLoading ? '重跑中…' : '重跑'
  const restartActionDisabled = isRestartDisabled(currentRunId, running, restartLoading)
  const restartOpen = !!restartAnchorEl

  const followStepVisible = manualPreviewStep && previewStep !== progressStep

  const renderWorkbenchStatusPanel = () => (
    <DreamweaverWorkbenchStatusScaffold
      runId={runId}
      progressLabel={progressLabel}
      stateLabel={stateLabel}
      stageLabel={stageLabel}
      taskStatusLabel={taskStatusLabel}
      taskQueue={taskQueue}
      taskStatusColor={taskStatusColor}
      actionItems={buildWorkbenchActionItems({
        copyDebugInfo,
        openDiagnosticDialog,
        currentRunId,
        openHistoryDialog,
        selectedProjectId,
        openConfigDialog,
        copyDebugIcon,
        diagnosticsIcon,
        historyIcon,
      })}
      restartActionLabel={restartActionLabel}
      restartActionDisabled={restartActionDisabled}
      restartActionStartIcon={restartIcon}
      onOpenRestartMenu={openRestartMenu}
      restartAnchorEl={restartAnchorEl}
      restartOpen={restartOpen}
      onCloseRestartMenu={closeRestartMenu}
      restartMenuItems={buildRestartMenuItems({
        currentRunId,
        running,
        restartLoading,
        requestRestartVideoShots,
        requestRestartKeyframeCameras,
        triggerRestartFromStage,
      })}
      followVisible={followStepVisible}
      onFollow={followProgressStep}
      stepLabels={DREAMWEAVER_PREVIEW_STEPS}
      activeStep={previewStep}
      progressStep={progressStep}
      onStepClick={handleClickStep}
    />
  )

  const hasQcWarning = Boolean(result?.qc_warning)

  const handleApproveSafetyAudit = () => void approveSafetyAudit()

  const renderRunPageAlerts = () => (
    <RunPageAlertsSection
      taskPointsPrecheckError={taskPointsPrecheckError}
      onClearTaskPointsPrecheckError={clearTaskPointsPrecheckError}
      safetyAuditAlertState={safetyAuditAlertState}
      safetyAuditApproveLoading={safetyAuditApproveLoading}
      safetyAuditApproveError={safetyAuditApproveError}
      onApproveSafetyAudit={handleApproveSafetyAudit}
      error={error}
      qcWarning={hasQcWarning}
      diagnosticPreflight={diagnosticPreflight}
    />
  )


  const renderWorkbenchTaskHeader = () => (
    <TaskHeader
      runId={runId}
      taskStage={taskStage}
      taskState={taskState}
      taskProgress={taskProgress}
      taskStatus={taskStatus}
      waitingApproval={waitingApproval}
    />
  )

  const renderWorkbenchMainContent = () => (!result ? renderPendingView() : renderResultView())

  const renderWorkbenchDialogs = () => (
    <>
      {renderDiagnosticDialog()}
      {renderRegenerateDialog()}
      {renderPromptEditDialog()}
      {renderHistoryDialog()}
      {renderBulkDeleteDialog()}
      {renderDeleteRunDialog()}
    </>
  )

  const renderWorkbenchCard = () => (
    <DreamweaverWorkbenchCard
      running={running}
      taskProgress={taskProgress}
      statusPanel={renderWorkbenchStatusPanel()}
      taskHeader={renderWorkbenchTaskHeader()}
      mainContent={renderWorkbenchMainContent()}
      dialogs={renderWorkbenchDialogs()}
    />
  )

  const navigateBack = () => navigate('/drama')

  return (
    <DreamweaverRunPageScaffold
      onBack={navigateBack}
      heroTitle="织梦映心 · 生成流程"
      heroDescription="读取项目章节内容，生成分镜、首尾帧、分镜片段并合成成片；支持进度轮询与产物预览。"
      configDialog={renderConfigDialog()}
      alerts={renderRunPageAlerts()}
      workbenchCard={renderWorkbenchCard()}
    />
  )
}
