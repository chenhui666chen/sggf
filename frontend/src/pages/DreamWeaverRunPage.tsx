import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  ImageList,
  ImageListItem,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import BugReportIcon from '@mui/icons-material/BugReport'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import WarningIcon from '@mui/icons-material/Warning'
import {
  apiClient,
  describeTaskPointsPrecheckErrorDetail,
  extractApiErrorMessage,
  extractTaskPointsPrecheckErrorDetail,
  type TaskPointsPrecheckErrorDetail,
} from '@/services/api'
import { workflowWebSocket } from '@/services/websocket'
import FormattedContent from '@/components/common/FormattedContent'
import TaskPointsPrecheckAlert from '@/components/common/TaskPointsPrecheckAlert'
import {
  CHARACTER_VIEW_ORDER,
  CHARACTER_VIEW_RANK,
  characterViewLabel,
  formatReferenceRoleLabel,
  parseLibraryRole,
  resolveCharacterViewChainPlan,
} from '@/utils/dreamweaverLibraryRole'
import { hasRenderableLibraryImage, resolveLibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'
import {
  DREAMWEAVER_STAGES,
  STYLE_PRESETS,
  STYLE_PRESET_LABELS,
  IMAGE_RATIOS,
  IMAGE_RATIOS_LABELS,
  IMAGE_RESOLUTIONS,
  IMAGE_RESOLUTIONS_LABELS,
} from '@/constants/dreamweaver'
import { TaskHeader } from '@/components/dreamweaver/TaskHeader'
import { useDreamweaverDiagnostics } from '@/hooks/useDreamweaverDiagnostics'
import { useDreamweaverRunPersistence } from '@/hooks/useDreamweaverRunPersistence'
import {
  buildProtectedMergedVideoUrl,
  buildLibraryPlanItemsFromPayload,
  buildResultFromRunSnapshot,
  clearPersistedDreamWeaverRun,
  extractMergedVideoFromContract,
  isPlaceholderEntityName,
  libraryAssetToCssAspectRatio,
  mergeRunResult,
  ratioIsPortrait,
  ratioToCssAspectRatio,
  readPersistedDreamWeaverRun,
  writePersistedDreamWeaverRun,
  stageToPreviewStep,
} from '@/utils/dreamweaver'
import type {
  BulkDeleteProgress,
  BulkDeleteResult,
  Chapter,
  CollectFeedback,
  DreamweaverAssetPlanItem,
  DreamweaverEventRecord,
  DreamweaverDiagnosticShotFrames,
  DreamweaverLibraryPlanItem,
  DreamweaverProjectLockedGenerationConfig,
  DreamweaverRunAsyncResponse,
  DreamweaverDiagnosticShot,
  DreamweaverRunPreflight as DreamweaverRunPreflightData,
  DreamweaverRunSnapshot,
  DreamweaverRunSummary,
  DreamweaverShotAsset,
  DreamweaverShotFrame,
  DreamweaverShotSnapshot,
  DreamweaverShotSchemaMeta,
  DreamweaverScriptEntities,
  DreamweaverTaskArtifacts,
  DreamweaverVideoClipJob,
  DreamweaverVideoProviderShotTrace,
  LibraryAsset,
  LibraryDisplayItem,
  LibraryPayload,
  Project,
  RunResult,
  ScriptGeneration,
  TaskStatus,
  VideoDiagnostics,
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
  PendingLibraryNotice,
  PendingLibraryReadyShell,
  PendingLibraryReviewShell,
  PendingPromptReviewView,
  PendingRunningShell,
  PendingScriptApprovalShell,
  PendingVideoConfirmationView,
} from './dreamweaver-run/pendingViews'
import {
  DreamweaverConfigDialogActions,
  DreamweaverConfigDialogChapterSelectionCard,
  DreamweaverConfigDialogContent,
  DreamweaverConfigDialogProjectSection,
  DreamweaverConfigDialogShell,
  DreamweaverConfigDialogStrategyCard,
  DreamweaverConfigDialogTitle,
  DreamweaverConfigDialogVisualSettingsCard,
} from './dreamweaver-run/configDialog'
import {
  DreamweaverBulkDeleteDialogActions,
  DreamweaverBulkDeleteDialogContent,
  DreamweaverBulkDeleteDialogShell,
  DreamweaverDeleteRunDialogActions,
  DreamweaverDeleteRunDialogContent,
  DreamweaverDeleteRunDialogShell,
} from './dreamweaver-run/deleteDialogs'
import {
  DreamweaverDiagnosticDialogEmptyState,
  DreamweaverDiagnosticDialogHeader,
  DreamweaverDiagnosticDialogShell,
  DreamweaverDiagnosticDialogStatusSection,
  DreamweaverDiagnosticDialogToolbar,
} from './dreamweaver-run/diagnosticDialog'
import {
  DreamweaverHistoryDialogContent,
  DreamweaverHistoryDialogShell,
  DreamweaverHistoryDialogTitle,
  DreamweaverHistoryDialogToolbar,
  DreamweaverHistoryRunItem,
} from './dreamweaver-run/historyDialog'
import {
  DreamweaverPromptEditDialogActions,
  DreamweaverPromptEditDialogContent,
  DreamweaverPromptEditDialogShell,
  DreamweaverRegenerateDialogActions,
  DreamweaverRegenerateDialogContent,
  DreamweaverRegenerateDialogModeControls,
  DreamweaverRegenerateDialogShell,
} from './dreamweaver-run/promptDialogs'
import {
  RunSnapshotAssetPreviewSection,
  RunSnapshotMergedVideoSection,
  RunSnapshotPreviewPane,
  RunSnapshotShotList,
} from './dreamweaver-run/runSnapshotPreviewPane'
import {
  DreamweaverWorkbenchRestartAction,
  DreamweaverWorkbenchRestartMenu,
  DreamweaverWorkbenchStatusActionButton,
  DreamweaverWorkbenchStatusPanel,
  DreamweaverWorkbenchStatusRightActions,
  DreamweaverWorkbenchStepper,
} from './dreamweaver-run/workbenchStatusPanel'
const DREAMWEAVER_PREVIEW_STEPS = ['剧本', '分镜', '素材', '镜头', '合成'] as const
type LibraryGroupSummary = {
  total: number
  generated: number
  processing: number
  planned: number
  approved: number
  pendingReview: number
}

type CharacterLibraryBucket = {
  bucketKey: string
  entityId: number
  name: string
  items: LibraryDisplayItem[]
}

type LibraryDisplayGroup = {
  key: LibraryDisplayItem['group']
  label: string
  items: LibraryDisplayItem[]
  summary: LibraryGroupSummary
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function toDreamweaverScriptEntities(value: unknown): DreamweaverScriptEntities | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const toBucket = (bucket: unknown): DreamweaverScriptEntities['characters'] => {
    if (!Array.isArray(bucket)) return []
    return bucket.filter(
      (item): item is DreamweaverScriptEntities['characters'][number] =>
        Boolean(item) && typeof item === 'object' && !Array.isArray(item),
    )
  }
  return {
    characters: toBucket(record.characters),
    scenes: toBucket(record.scenes),
    props: toBucket(record.props),
  }
}

function summarizeScriptEntities(entities: DreamweaverScriptEntities | null): string {
  if (!entities) return ''
  return `角色 ${entities.characters.length}，场景 ${entities.scenes.length}，道具 ${entities.props.length}`
}

function toDreamweaverShotSnapshots(value: unknown): DreamweaverShotSnapshot[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverShotSnapshot => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

function toDreamweaverVideoClipJobs(value: unknown): DreamweaverVideoClipJob[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverVideoClipJob => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

function toDreamweaverRunSummaries(value: unknown): DreamweaverRunSummary[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverRunSummary => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

function toDreamweaverRunSnapshot(value: unknown): DreamweaverRunSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverRunSnapshot
}

function toDreamweaverTaskStatus(value: unknown): TaskStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as TaskStatus
}

function toDreamweaverRunAsyncResponse(value: unknown): DreamweaverRunAsyncResponse | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverRunAsyncResponse
}

function toDreamweaverProjectLockedGenerationConfig(value: unknown): DreamweaverProjectLockedGenerationConfig | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverProjectLockedGenerationConfig
}

function toDreamweaverEventRecords(value: unknown): DreamweaverEventRecord[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverEventRecord => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

function toChapters(value: unknown): Chapter[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Chapter => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
}

function toLibraryPayload(value: unknown): LibraryPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as LibraryPayload
}

function toDreamweaverQueuedTaskResponse(
  value: unknown,
): { task_id: string; run_id: string; status: string } | null {
  const record = asObject(value)
  if (!record) return null
  const task_id = typeof record.task_id === 'string' ? record.task_id.trim() : ''
  const run_id = typeof record.run_id === 'string' ? record.run_id.trim() : ''
  const status = typeof record.status === 'string' ? record.status.trim() : ''
  if (!task_id || !run_id) return null
  return { task_id, run_id, status }
}

function toDreamweaverShotFrames(value: unknown): DreamweaverShotFrame[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverShotFrame => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

function getShotAssets(shot: DreamweaverShotSnapshot | null | undefined): DreamweaverShotAsset[] {
  return Array.isArray(shot?.assets) ? shot.assets : []
}

function getShotId(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(shot?.shot_key || shot?.shot_id || '').trim()
}

function getShotDesc(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(shot?.desc || '').trim()
}

function getShotFramePrompt(frame: DreamweaverShotFrame | null | undefined): string {
  return String(frame?.prompt || '').trim()
}

function getShotFramePath(frame: DreamweaverShotFrame | null | undefined): string {
  return String(frame?.path || '').trim()
}

function getShotFrameCandidateUris(frame: DreamweaverShotFrame | null | undefined): string[] {
  const candidates = asObject(frame?.meta)?.candidates
  if (!Array.isArray(candidates)) return []
  return candidates
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}

function getShotSchemaMeta(shot: DreamweaverShotSnapshot | null | undefined): DreamweaverShotSchemaMeta | null {
  const meta = shot?.shot_schema_v2?.meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  return meta
}

function getShotVideoPromptOverride(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(getShotSchemaMeta(shot)?.video_prompt_override || '').trim()
}

function getShotVideoPromptGenerated(shot: DreamweaverShotSnapshot | null | undefined): string {
  return String(getShotSchemaMeta(shot)?.video_prompt_generated || '').trim()
}

function getResultVideoClipPath(clip: unknown): string {
  const path = asObject(clip)?.path
  return typeof path === 'string' ? path.trim() : ''
}

function getResultVideoClipMeta(clip: unknown): Record<string, unknown> | null {
  return asObject(asObject(clip)?.meta)
}

function getDiagnosticStoryboardPrompt(
  storyboard: Record<string, unknown> | null | undefined,
  frameKey: 'head_frame' | 'tail_frame',
): string {
  const framePrompt = asObject(storyboard?.[frameKey])?.prompt
  if (typeof framePrompt === 'string' && framePrompt.trim()) return framePrompt.trim()
  const visualDesc = storyboard?.visual_desc
  if (typeof visualDesc === 'string' && visualDesc.trim()) return visualDesc.trim()
  const desc = storyboard?.desc
  return typeof desc === 'string' ? desc.trim() : ''
}

function withRunSnapshotVideoJobs(
  snapshot: DreamweaverRunSnapshot | null,
  jobs: DreamweaverVideoClipJob[],
): DreamweaverRunSnapshot | null {
  if (!snapshot) return snapshot
  const contract = asObject(snapshot.contract) || {}
  const runtimeConfig = asObject(contract.runtime_config) || {}
  return {
    ...snapshot,
    contract: {
      ...contract,
      runtime_config: {
        ...runtimeConfig,
        video_clip_jobs: jobs,
      },
    },
  }
}

function getThrownErrorResponse(error: unknown): Record<string, unknown> | null {
  return asObject(asObject(error)?.response)
}

function getThrownErrorStatus(error: unknown): number | null {
  const status = getThrownErrorResponse(error)?.status
  return typeof status === 'number' ? Number(status) : null
}

function getThrownErrorMessage(error: unknown): string {
  const message = asObject(error)?.message
  return typeof message === 'string' ? message : ''
}

function isNotFoundError(error: unknown): boolean {
  return getThrownErrorStatus(error) === 404
}

function isTimeoutErrorLike(error: unknown): boolean {
  return getThrownErrorMessage(error).toLowerCase().includes('timeout')
}

function isNetworkErrorLike(error: unknown): boolean {
  return !getThrownErrorResponse(error)
}

export default function DreamWeaverRunPage() {
  const navigate = useNavigate()
  const { projectId: projectIdParam } = useParams()
  const theme = useTheme()
  const smDown = useMediaQuery(theme.breakpoints.down('sm'))
  const mdDown = useMediaQuery(theme.breakpoints.down('md'))
  const configDialogFullScreen = smDown
  const libraryGridCols = smDown ? 1 : mdDown ? 2 : 3
  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [selectedChapterIds, setSelectedChapterIds] = useState<number[]>([])
  const [highQuality, setHighQuality] = useState(true)
  const [qcAllowFail, setQcAllowFail] = useState(false)
  const [smartTuning, setSmartTuning] = useState(true)
  const [videoRequireConfirmation, setVideoRequireConfirmation] = useState(true)
  const [promptReviewRequired, setPromptReviewRequired] = useState(true)
  const [abVariant, setAbVariant] = useState<string>('')
  const [stylePreset, setStylePreset] = useState<string>(STYLE_PRESETS.CINEMATIC_REALISTIC)
  const [imageRatio, setImageRatio] = useState<string>(IMAGE_RATIOS.LANDSCAPE_16_9)
  const [imageResolution, setImageResolution] = useState<string>(IMAGE_RESOLUTIONS.HD_720P)
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [running, setRunning] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskRunId, setTaskRunId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<string | null>(null)
  const [taskQueue, setTaskQueue] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState<number>(0)
  const [taskState, setTaskState] = useState<string | null>(null)
  const [taskStage, setTaskStage] = useState<string | null>(null)
  const [taskArtifacts, setTaskArtifacts] = useState<DreamweaverTaskArtifacts | null>(null)
  const [waitingApproval, setWaitingApproval] = useState(false)
  const [videoJobActionError, setVideoJobActionError] = useState<string | null>(null)
  const [videoJobConfirmingShotId, setVideoJobConfirmingShotId] = useState<string | null>(null)
  const [resumeLoading, setResumeLoading] = useState(false)
  const [restartLoading, setRestartLoading] = useState(false)
  const [restartAnchorEl, setRestartAnchorEl] = useState<HTMLElement | null>(null)
  const [scriptLoading, setScriptLoading] = useState(false)
  const [scriptError, setScriptError] = useState<string | null>(null)
  const [scriptText, setScriptText] = useState<string>('')
  const [scriptSavedText, setScriptSavedText] = useState<string>('')
  const [scriptApproved, setScriptApproved] = useState(false)
  const [scriptRequiresReview, setScriptRequiresReview] = useState(true)
  const [scriptEntities, setScriptEntities] = useState<DreamweaverScriptEntities | null>(null)
  const [scriptGeneration, setScriptGeneration] = useState<ScriptGeneration | null>(null)
  const [promptReviewLoading, setPromptReviewLoading] = useState(false)
  const [promptReviewError, setPromptReviewError] = useState<string | null>(null)
  const [promptReviewShowAll, setPromptReviewShowAll] = useState(false)
  const [shotPromptExpanded, setShotPromptExpanded] = useState<Record<string, boolean>>({})
  const [promptEditOpen, setPromptEditOpen] = useState(false)
  const [promptEditShot, setPromptEditShot] = useState<DreamweaverShotSnapshot | null>(null)
  const [promptEditHead, setPromptEditHead] = useState<string>('')
  const [promptEditTail, setPromptEditTail] = useState<string>('')
  const [promptEditVideo, setPromptEditVideo] = useState<string>('')
  const [promptEditSaving, setPromptEditSaving] = useState(false)
  const [promptEditError, setPromptEditError] = useState<string | null>(null)
  const promptEditGenerated = useMemo(() => {
    return getShotVideoPromptGenerated(promptEditShot)
  }, [promptEditShot])
  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [libraryPreviews, setLibraryPreviews] = useState<Record<number, string>>({})
  const [libraryPreviewLoading, setLibraryPreviewLoading] = useState<Record<number, boolean>>({})
  const [libraryPreviewErrors, setLibraryPreviewErrors] = useState<Record<number, string>>({})
  const libraryPreviewsRef = useRef<Record<number, string>>({})
  const [mergedVideoLoading, setMergedVideoLoading] = useState(false)
  const [mergedVideoError, setMergedVideoError] = useState<string | null>(null)
  const [mergedVideoPreviewUrl, setMergedVideoPreviewUrl] = useState<string | null>(null)
  const [mergedVideoCollecting, setMergedVideoCollecting] = useState(false)
  const [mergedVideoCollectFeedback, setMergedVideoCollectFeedback] = useState<CollectFeedback | null>(null)
  const [runAssetPreviews, setRunAssetPreviews] = useState<Record<string, string>>({})
  const [runAssetPreviewLoading, setRunAssetPreviewLoading] = useState<Record<string, boolean>>({})
  const [runAssetPreviewErrors, setRunAssetPreviewErrors] = useState<Record<string, string>>({})
  const runAssetPreviewsRef = useRef<Record<string, string>>({})
  const activeRunIdRef = useRef<string | null>(null)
  const eventCursorRef = useRef(0)
  const eventSyncingRef = useRef(false)
  const [regenOpen, setRegenOpen] = useState(false)
  const [regenRole, setRegenRole] = useState<string>('')
  const [regenTitle, setRegenTitle] = useState<string>('')
  const [regenPrompt, setRegenPrompt] = useState<string>('')
  const [regenPromptInitial, setRegenPromptInitial] = useState<string>('')
  const [regenPromptTemplateSnapshot, setRegenPromptTemplateSnapshot] = useState<string>('')
  const [regenImageEditAutoCleared, setRegenImageEditAutoCleared] = useState(false)
  const [regenPromptDirty, setRegenPromptDirty] = useState(false)
  const [regenPreferImageEdit, setRegenPreferImageEdit] = useState(false)
  const [regenSuggesting, setRegenSuggesting] = useState(false)
  const [regenSuggestError, setRegenSuggestError] = useState<string | null>(null)
  const [regenSmartPromptTriggered, setRegenSmartPromptTriggered] = useState(false)
  const [regenSubmitting, setRegenSubmitting] = useState(false)
  const [regenError, setRegenError] = useState<string | null>(null)
  const [result, setResult] = useState<RunResult | null>(null)
  const [runPreflight, setRunPreflight] = useState<DreamweaverRunPreflightData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taskPointsPrecheckError, setTaskPointsPrecheckError] = useState<TaskPointsPrecheckErrorDetail | null>(null)
  const [eventCursor, setEventCursor] = useState(0)
  const [eventSyncing, setEventSyncing] = useState(false)
  const [eventSyncError, setEventSyncError] = useState<string | null>(null)
  const [wsError, setWsError] = useState<string | null>(null)
  const [streamTextByKey, setStreamTextByKey] = useState<Record<string, string>>({})
  const [streamMetaByKey, setStreamMetaByKey] = useState<Record<string, { stage?: string | null; done?: boolean }>>({})
  const [assetPlanItems, setAssetPlanItems] = useState<DreamweaverAssetPlanItem[]>([])
  const [libraryPlanItems, setLibraryPlanItems] = useState<DreamweaverLibraryPlanItem[]>([])

  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyRuns, setHistoryRuns] = useState<DreamweaverRunSummary[]>([])
  const [historyStatusFilters, setHistoryStatusFilters] = useState<string[]>([])

  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteSubmitting, setBulkDeleteSubmitting] = useState(false)
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null)
  const [bulkDeleteProgress, setBulkDeleteProgress] = useState<BulkDeleteProgress | null>(null)
  const [bulkDeleteResult, setBulkDeleteResult] = useState<BulkDeleteResult | null>(null)

  const [lockedGenerationConfig, setLockedGenerationConfig] = useState<DreamweaverProjectLockedGenerationConfig | null>(null)
  const [lockedGenerationConfigLoading, setLockedGenerationConfigLoading] = useState(false)
  const [lockedGenerationConfigError, setLockedGenerationConfigError] = useState<string | null>(null)

  const [diagnosticOpen, setDiagnosticOpen] = useState(false)
  const [diagnosticActionLoading, setDiagnosticActionLoading] = useState(false)
  const [diagnosticActionError, setDiagnosticActionError] = useState<string | null>(null)

  const [deleteRunId, setDeleteRunId] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteSubmitting, setDeleteSubmitting] = useState(false)
  const [deleteDialogError, setDeleteDialogError] = useState<string | null>(null)

  const [runSnapshot, setRunSnapshot] = useState<DreamweaverRunSnapshot | null>(null)
  const [runSnapshotLoading, setRunSnapshotLoading] = useState(false)
  const [runSnapshotError, setRunSnapshotError] = useState<string | null>(null)

  const [previewStep, setPreviewStep] = useState(0)
  const [manualPreviewStep, setManualPreviewStep] = useState(false)

  const libraryPreviewAspectRatio = ratioToCssAspectRatio(imageRatio)
  const generationConfigLocked = Boolean(lockedGenerationConfig?.locked)
  const missingRoleSet = useMemo(() => {
    const missingRoles = Array.isArray(library?.review?.missing_roles) ? (library.review!.missing_roles as string[]) : []
    return new Set(missingRoles.map((role) => String(role || '').trim()).filter(Boolean))
  }, [library?.review])
  const libraryAssetsByRole = useMemo(() => {
    const map = new Map<string, LibraryAsset>()
    const assets = Array.isArray(library?.assets) ? (library.assets as LibraryAsset[]) : []
    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role) continue
      map.set(role, asset)
    }
    return map
  }, [library?.assets])
  const regenRoleAsset = useMemo(() => {
    const role = String(regenRole || '').trim()
    if (!role) return null
    return libraryAssetsByRole.get(role) || null
  }, [libraryAssetsByRole, regenRole])
  const regenRoleInfo = useMemo(() => parseLibraryRole(regenRole), [regenRole])
  const regenIsDerivedCharacterView = useMemo(
    () => regenRoleInfo.entityType === 'character' && Boolean(regenRoleInfo.view) && regenRoleInfo.view !== 'front',
    [regenRoleInfo],
  )
  const regenHasCurrentImage = useMemo(
    () => hasRenderableLibraryImage(regenRoleAsset, { missingRoleSet }),
    [missingRoleSet, regenRoleAsset],
  )
  const regenViewChainPlan = useMemo(() => resolveCharacterViewChainPlan(regenRole), [regenRole])
  const regenForceImageEdit = regenViewChainPlan.forceImageEdit
  const regenImageBaseRole = regenViewChainPlan.baseRole
  const regenImageBaseAsset = useMemo(() => {
    if (!regenImageBaseRole) return null
    return libraryAssetsByRole.get(regenImageBaseRole) || null
  }, [libraryAssetsByRole, regenImageBaseRole])
  const regenHasRenderableBaseImage = useMemo(
    () => hasRenderableLibraryImage(regenImageBaseAsset, { missingRoleSet }),
    [missingRoleSet, regenImageBaseAsset],
  )
  const regenReferenceRoles = useMemo(() => {
    return (Array.isArray(regenViewChainPlan.referenceRoles) ? regenViewChainPlan.referenceRoles : [])
      .map((item) => String(item || '').trim())
      .filter(Boolean)
  }, [regenViewChainPlan.referenceRoles])
  const regenReadyReferenceRoles = useMemo(() => {
    return regenReferenceRoles.filter((role) => hasRenderableLibraryImage(libraryAssetsByRole.get(role) || null, { missingRoleSet }))
  }, [libraryAssetsByRole, missingRoleSet, regenReferenceRoles])
  const regenMissingReferenceRoles = useMemo(() => {
    return regenReferenceRoles.filter((role) => !hasRenderableLibraryImage(libraryAssetsByRole.get(role) || null, { missingRoleSet }))
  }, [libraryAssetsByRole, missingRoleSet, regenReferenceRoles])
  const regenHasImageBase = useMemo(() => {
    if (regenForceImageEdit) return regenHasRenderableBaseImage
    return regenHasCurrentImage
  }, [regenForceImageEdit, regenHasCurrentImage, regenHasRenderableBaseImage])
  const regenImageEditActive = regenForceImageEdit || (regenPreferImageEdit && regenHasImageBase)
  const regenImageBaseRoleLabel = useMemo(() => {
    return regenImageBaseRole ? formatReferenceRoleLabel(regenImageBaseRole) : '前序视角'
  }, [regenImageBaseRole])
  const regenForceViewChainEditBase = regenForceImageEdit && regenIsDerivedCharacterView && regenSmartPromptTriggered
  const regenAlertBaseLabel = useMemo(() => {
    if (!regenForceImageEdit) return ''
    if (regenForceViewChainEditBase) return regenImageBaseRoleLabel
    if (regenHasCurrentImage) return '当前图'
    return regenImageBaseRoleLabel
  }, [regenForceImageEdit, regenForceViewChainEditBase, regenHasCurrentImage, regenImageBaseRoleLabel])
  const regenAlertReadyReferenceLabel = useMemo(() => {
    const labels: string[] = []
    const push = (value: string) => {
      const text = String(value || '').trim()
      if (!text) return
      if (!labels.includes(text)) labels.push(text)
    }

    if (!regenForceImageEdit) return ''

    if (regenForceViewChainEditBase) {
      if (regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    } else if (regenHasCurrentImage) {
      push('当前图')
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    } else {
      if (regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenReadyReferenceRoles) push(formatReferenceRoleLabel(role))
    }

    return labels.join('、')
  }, [
    regenForceImageEdit,
    regenForceViewChainEditBase,
    regenHasCurrentImage,
    regenHasRenderableBaseImage,
    regenImageBaseRoleLabel,
    regenReadyReferenceRoles,
  ])
  const regenAlertMissingReferenceLabel = useMemo(() => {
    const labels: string[] = []
    const push = (value: string) => {
      const text = String(value || '').trim()
      if (!text) return
      if (!labels.includes(text)) labels.push(text)
    }

    if (!regenForceImageEdit) return ''

    if (regenForceViewChainEditBase) {
      if (!regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    } else if (regenHasCurrentImage) {
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    } else {
      if (!regenHasRenderableBaseImage) push(regenImageBaseRoleLabel)
      for (const role of regenMissingReferenceRoles) push(formatReferenceRoleLabel(role))
    }

    return labels.join('、')
  }, [
    regenForceImageEdit,
    regenForceViewChainEditBase,
    regenHasCurrentImage,
    regenHasRenderableBaseImage,
    regenImageBaseRoleLabel,
    regenMissingReferenceRoles,
  ])
  const regenAlertReadyReferenceCount = useMemo(() => {
    const text = String(regenAlertReadyReferenceLabel || '').trim()
    if (!text) return 0
    return text.split('、').map((s) => s.trim()).filter(Boolean).length
  }, [regenAlertReadyReferenceLabel])
  const regenPromptInputLabel = useMemo(() => {
    if (!(regenImageEditActive && regenImageEditAutoCleared)) return '提示词'
    if (regenForceViewChainEditBase) return '修改要求（基于参考图）'
    if (regenHasCurrentImage) return '修改要求（基于当前图）'
    return '修改要求（基于参考图）'
  }, [regenForceViewChainEditBase, regenHasCurrentImage, regenImageEditActive, regenImageEditAutoCleared])
  const mergedVideoPreviewPortrait = ratioIsPortrait(
    generationConfigLocked ? lockedGenerationConfig?.image_ratio : imageRatio,
  )

  const videoDiagnostics = useMemo<VideoDiagnostics>(() => {
    const clips = Array.isArray(result?.video_clips) ? result.video_clips : []
    const viaSet = new Set<string>()
    let fallbackCount = 0
    let errorCount = 0
    for (const clip of clips) {
      const meta = getResultVideoClipMeta(clip)
      const via = typeof meta?.via === 'string' ? String(meta.via).trim() : ''
      if (via) viaSet.add(via)
      if (via.includes('fallback')) fallbackCount += 1
      const err = typeof meta?.error === 'string' ? String(meta.error).trim() : ''
      if (err) errorCount += 1
    }
    return { clipCount: clips.length, viaSummary: Array.from(viaSet).join(', '), fallbackCount, errorCount }
  }, [result?.video_clips])

  const resultPlanText = useMemo(() => {
    const plan = result?.plan
    if (!plan || typeof plan !== 'object') return ''
    const text = (plan as { text?: unknown }).text
    return typeof text === 'string' ? text : ''
  }, [result?.plan])

  const resultVideoClipPaths = useMemo(() => {
    const clips = Array.isArray(result?.video_clips) ? result.video_clips : []
    return clips.map((clip) => getResultVideoClipPath(clip)).filter(Boolean)
  }, [result?.video_clips])

  const candidateFrameUris = useMemo(() => {
    const uris: string[] = []
    const pushFromFrames = (frames: DreamweaverShotFrame[]) => {
      for (const frame of frames) {
        uris.push(...getShotFrameCandidateUris(frame))
      }
    }
    pushFromFrames(toDreamweaverShotFrames(result?.keyframes))
    pushFromFrames(toDreamweaverShotFrames(result?.midframes))
    return Array.from(new Set(uris))
  }, [result?.keyframes, result?.midframes])

  const resultKeyframePaths = useMemo(() => {
    return toDreamweaverShotFrames(result?.keyframes).map((frame) => getShotFramePath(frame)).filter(Boolean)
  }, [result?.keyframes])

  const resultMidframePaths = useMemo(() => {
    return toDreamweaverShotFrames(result?.midframes).map((frame) => getShotFramePath(frame)).filter(Boolean)
  }, [result?.midframes])

  const [configDialogOpen, setConfigDialogOpen] = useState(false)
  const autoOpenedConfigDialogRef = useRef(false)

  const autoLoadedScriptRunIdRef = useRef<string | null>(null)
  const autoLoadedRunSnapshotRunIdRef = useRef<string | null>(null)
  const autoLoadedLibraryRef = useRef(false)
  const restoredProjectIdRef = useRef<number | null>(null)
  const lockedGenerationConfigReqIdRef = useRef(0)

  useEffect(() => {
    libraryPreviewsRef.current = libraryPreviews
  }, [libraryPreviews])

  useEffect(() => {
    return () => {
      Object.values(libraryPreviewsRef.current).forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
    }
  }, [])

  useEffect(() => {
    runAssetPreviewsRef.current = runAssetPreviews
  }, [runAssetPreviews])

  useEffect(() => {
    return () => {
      Object.values(runAssetPreviewsRef.current).forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
    }
  }, [])

  const clearRunAssetPreviews = useCallback(() => {
    Object.values(runAssetPreviewsRef.current).forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore
      }
    })
    runAssetPreviewsRef.current = {}
    setRunAssetPreviews({})
    setRunAssetPreviewLoading({})
    setRunAssetPreviewErrors({})
  }, [])

  const clearLibraryPreviews = useCallback(() => {
    Object.values(libraryPreviewsRef.current).forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore
      }
    })
    libraryPreviewsRef.current = {}
    setLibraryPreviews({})
    setLibraryPreviewLoading({})
    setLibraryPreviewErrors({})
  }, [])

  const resetDreamweaverEvents = useCallback(() => {
    eventCursorRef.current = 0
    setEventCursor(0)
    setEventSyncError(null)
    setStreamTextByKey({})
    setStreamMetaByKey({})
    setAssetPlanItems([])
    setLibraryPlanItems([])
  }, [])

  const shouldTreatRunNotFoundAsPending = useCallback((taskIdValue?: string | null, statusValue?: string | null) => {
    const status = String(statusValue || '').trim().toLowerCase()
    if (status === 'queued' || status === 'running' || status === 'waiting') return true
    return Boolean(taskIdValue)
  }, [])

  const resetMissingRunState = useCallback(
    (projectId: number | null) => {
      if (projectId) {
        clearPersistedDreamWeaverRun(projectId)
      }

      setTaskId(null)
      setTaskRunId(null)
      setTaskStatus(null)
      setTaskQueue(null)
      setTaskProgress(0)
      setTaskState(null)
      setTaskStage(null)
      setTaskArtifacts(null)
      setRunning(false)
      setWaitingApproval(false)

      setResult(null)
      setRunPreflight(null)
      setRunSnapshot(null)

      setScriptError(null)
      setScriptText('')
      setScriptSavedText('')
      setScriptApproved(false)
      setScriptRequiresReview(true)
      setScriptEntities(null)
      setScriptGeneration(null)

      setLibrary(null)
      setLibraryError(null)
      setLibraryPreviews({})
      setMergedVideoLoading(false)
      setMergedVideoError(null)
      setMergedVideoPreviewUrl(null)
      clearRunAssetPreviews()
      resetDreamweaverEvents()

      autoLoadedRunSnapshotRunIdRef.current = null
      autoLoadedScriptRunIdRef.current = null
      setPreviewStep(0)
      setManualPreviewStep(false)
    },
    [clearRunAssetPreviews, resetDreamweaverEvents],
  )

  const lockedProjectId = useMemo(() => {
    const parsed = Number(projectIdParam)
    if (!projectIdParam || !Number.isFinite(parsed)) return null
    return parsed
  }, [projectIdParam])

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) return null
    return projects.find((p) => p.id === selectedProjectId) || null
  }, [projects, selectedProjectId])

  const formatPath = (value: unknown) => {
    if (!value || typeof value !== 'string') return null
    const parts = value.split(/[\\/]+/).filter(Boolean)
    return parts.slice(-2).join('/')
  }

  const formatPaths = (value: unknown) => {
    if (!Array.isArray(value)) return null
    const formatted = value.map(formatPath).filter((item): item is string => Boolean(item))
    return formatted.length ? formatted.join('  ') : null
  }

  const renderRunAssetPreviewCardMedia = (previewUrl: string, kind: 'image' | 'video') => {
    if (!previewUrl) {
      return (
        <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
          <Typography variant="caption" color="text.secondary">
            未加载预览
          </Typography>
        </Box>
      )
    }

    if (kind === 'image') {
      return (
        <Box
          sx={{
            mt: 0.75,
            bgcolor: '#000',
            borderRadius: 1,
            overflow: 'hidden',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            p: 0.5,
          }}
        >
          <Box component="img" src={previewUrl} sx={{ maxWidth: '100%', maxHeight: 220, display: 'block', objectFit: 'contain' }} />
        </Box>
      )
    }

    return (
      <Box sx={{ mt: 0.75, bgcolor: '#000', borderRadius: 1, overflow: 'hidden' }}>
        <Box component="video" src={previewUrl} controls sx={{ width: '100%', maxHeight: 240, display: 'block' }} />
      </Box>
    )
  }

  const renderRunAssetPreviewCardActions = ({
    uri,
    previewUrl,
    loading,
  }: {
    uri: string
    previewUrl: string
    loading: boolean
  }) => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
      <Button size="small" variant="outlined" onClick={() => loadRunAssetPreview(uri)} disabled={!currentRunId || loading}>
        {loading ? '加载中…' : previewUrl ? '重新加载' : '加载预览'}
      </Button>
      <Button size="small" variant="text" onClick={() => downloadRunAsset(uri)} disabled={!currentRunId || loading}>
        下载
      </Button>
      {formatPath(uri) && <Chip size="small" label={formatPath(uri)} variant="outlined" />}
    </Stack>
  )

  const renderRunAssetPreviewCard = ({
    title,
    uri,
    kind,
  }: {
    title: string
    uri: string
    kind: 'image' | 'video'
  }) => {
    const previewUrl = runAssetPreviews[uri]
    const loading = Boolean(runAssetPreviewLoading[uri])
    const err = runAssetPreviewErrors[uri]
    const filename = uri.split(/[\\/]+/).pop() || uri

    return (
      <Grid item xs={12} sm={6} md={4} key={`${title}:${uri}`}>
        <Card variant="outlined">
          <CardContent sx={{ p: 1.25 }}>
            <Typography variant="caption" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
              {filename}
            </Typography>
            {renderRunAssetPreviewCardMedia(previewUrl, kind)}
            {renderRunAssetPreviewCardActions({ uri, previewUrl, loading })}

            {err && (
              <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
                {err}
              </Typography>
            )}
          </CardContent>
        </Card>
      </Grid>
    )
  }

  const renderRunAssetPreviewGrid = (title: string, uris: string[], kind: 'image' | 'video') => {
    const items = Array.from(new Set((uris || []).map((u) => String(u || '').trim()).filter(Boolean)))
    if (items.length === 0) return null
    return (
      <Box sx={{ mt: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
          {title}
        </Typography>
        <Grid container spacing={1}>
          {items.map((uri) => renderRunAssetPreviewCard({ title, uri, kind }))}
        </Grid>
      </Box>
    )
  }

  const renderAssetPlanCardPlaceholder = (uri: string) => (
    <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
      <Typography variant="caption" color="text.secondary">
        {uri ? '已生成，待加载预览' : '生成中，等待素材'}
      </Typography>
    </Box>
  )

  const renderAssetPlanCardLocation = (item: DreamweaverAssetPlanItem) => {
    if (!item.shot_id && !item.scene_id) return null

    return (
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
        {item.shot_id ? `Shot: ${item.shot_id}` : ''}
        {item.scene_id ? `  Scene: ${item.scene_id}` : ''}
      </Typography>
    )
  }

  const renderAssetPlanCard = (item: DreamweaverAssetPlanItem) => {
    const uri = item.uri ? String(item.uri).trim() : ''
    const previewUrl = uri ? runAssetPreviews[uri] : ''
    const loading = uri ? Boolean(runAssetPreviewLoading[uri]) : false
    const err = uri ? runAssetPreviewErrors[uri] : null
    const status = item.status === 'done' || uri ? 'done' : item.status === 'processing' ? 'processing' : 'planned'
    const statusLabel = status === 'done' ? '已生成' : status === 'processing' ? '生成中' : '待生成'
    const statusColor: 'default' | 'success' | 'info' = status === 'done' ? 'success' : status === 'processing' ? 'info' : 'default'
    const label = String(item.label || item.id || '').trim() || item.id
    const kind = item.kind === 'video' ? 'video' : 'image'

    return (
      <Grid item xs={12} sm={6} md={4} key={`plan:${item.id}`}>
        <Card variant="outlined">
          <CardContent sx={{ p: 1.25 }}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                {label}
              </Typography>
              <Chip size="small" label={statusLabel} color={statusColor} />
              {item.optional && <Chip size="small" label="可选" variant="outlined" />}
            </Stack>

            {previewUrl ? renderRunAssetPreviewCardMedia(previewUrl, kind) : renderAssetPlanCardPlaceholder(uri)}

            {uri && renderRunAssetPreviewCardActions({ uri, previewUrl, loading })}
            {renderAssetPlanCardLocation(item)}

            {err && (
              <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
                {err}
              </Typography>
            )}
          </CardContent>
        </Card>
      </Grid>
    )
  }

  const renderAssetPlanGrid = (title: string, items: DreamweaverAssetPlanItem[]) => {
    const list = Array.isArray(items) ? items : []
    if (!list.length) return null
    return (
      <Box sx={{ mt: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
          {title}
        </Typography>
        <Grid container spacing={1}>
          {list.map(renderAssetPlanCard)}
        </Grid>
      </Box>
    )
  }

  const resolveLibraryDisplayCardState = (item: LibraryDisplayItem) => {
    const asset = item.asset
    const imageState = item.imageState || resolveLibraryAssetImageState(asset || null, { missingRoleSet })
    const hasRenderableImage = Boolean(item.hasRenderableImage ?? imageState.hasRenderableImage)
    const missing = Boolean(item.missing || imageState.markedMissing)
    const placeholder = Boolean(item.placeholder || (asset && imageState.placeholder && !missing && !imageState.safetyBlocked))
    const approved = hasRenderableImage && (asset ? Boolean(asset.meta?.approved) : Boolean(item.approved))
    const safetyBlocked = Boolean(item.safety_blocked || imageState.safetyBlocked || asset?.meta?.safety_blocked)
    const safetyError = item.safety_error || (asset?.meta?.safety_error as string | undefined) || null
    const statusLabel = missing
      ? '缺失'
      : safetyBlocked
        ? '安全拦截'
        : placeholder
          ? '占位'
          : asset
            ? approved
              ? '已通过'
              : '待审核'
            : item.status === 'done'
              ? '已生成'
              : item.status === 'planned'
                ? '待生成'
                : '生成中'
    const statusColor: 'default' | 'success' | 'info' | 'error' | 'warning' = missing
      ? 'error'
      : safetyBlocked
        ? 'error'
        : placeholder
          ? 'warning'
          : asset
            ? approved
              ? 'success'
              : 'default'
            : item.status === 'done'
              ? 'success'
              : item.status === 'planned'
                ? 'default'
                : 'info'
    const preview = asset && hasRenderableImage ? item.preview : ''
    const placeholderText = missing
      ? '素材缺失'
      : safetyBlocked
        ? '安全拦截'
        : placeholder
          ? '占位图'
          : asset
            ? '待加载预览'
            : item.status === 'done'
              ? '已生成，等待入库'
              : item.status === 'planned'
                ? '待生成'
                : '生成中'
    const previewLoading = asset ? Boolean(libraryPreviewLoading[asset.id]) : false
    const previewError = asset ? libraryPreviewErrors[asset.id] : null
    const canGenerate = !asset && (missing || item.status === 'done')
    const roleLabel = item.group === 'other' && item.role ? `role: ${item.role}` : ''
    const backgroundColor = safetyBlocked || missing ? '#fff5f5' : placeholder ? '#fffaf0' : '#f5f5f5'
    const placeholderColor = safetyBlocked || missing ? 'error.main' : placeholder ? 'warning.main' : 'text.secondary'
    const placeholderBackgroundImage = safetyBlocked || missing
      ? 'repeating-linear-gradient(45deg, rgba(211,47,47,0.05) 0, rgba(211,47,47,0.05) 8px, rgba(211,47,47,0.1) 8px, rgba(211,47,47,0.1) 16px)'
      : placeholder
        ? 'repeating-linear-gradient(45deg, rgba(245,124,0,0.05) 0, rgba(245,124,0,0.05) 8px, rgba(245,124,0,0.1) 8px, rgba(245,124,0,0.1) 16px)'
        : 'repeating-linear-gradient(45deg, rgba(0,0,0,0.02) 0, rgba(0,0,0,0.02) 8px, rgba(0,0,0,0.04) 8px, rgba(0,0,0,0.04) 16px)'

    return {
      asset,
      hasRenderableImage,
      missing,
      placeholder,
      approved,
      safetyBlocked,
      safetyError,
      statusLabel,
      statusColor,
      preview,
      placeholderText,
      previewLoading,
      previewError,
      canGenerate,
      roleLabel,
      backgroundColor,
      placeholderColor,
      placeholderBackgroundImage,
    }
  }

  type LibraryDisplayCardState = ReturnType<typeof resolveLibraryDisplayCardState>

  const renderLibraryDisplayCardPreviewArea = (item: LibraryDisplayItem, state: LibraryDisplayCardState) => (
    <Box
      sx={{
        width: '100%',
        aspectRatio: item.aspectRatio,
        bgcolor: state.backgroundColor,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {state.preview && !state.safetyBlocked ? (
        <Box
          component="img"
          src={state.preview}
          alt={item.title}
          loading="lazy"
          sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : (
        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: state.placeholderColor,
            fontSize: 12,
            backgroundImage: state.placeholderBackgroundImage,
          }}
        >
          {state.safetyBlocked && <Box sx={{ fontSize: 24, mb: 0.5 }}>⛔️</Box>}
          <Box>{state.placeholderText}</Box>
          {state.safetyBlocked && (
            <Box sx={{ fontSize: 10, mt: 0.5, px: 1, textAlign: 'center', opacity: 0.8 }}>
              点击重新生成
            </Box>
          )}
        </Box>
      )}
      <Box sx={{ position: 'absolute', top: 8, left: 8 }}>
        <Chip size="small" label={state.statusLabel} color={state.statusColor} />
      </Box>
      {state.placeholder && (
        <Box sx={{ position: 'absolute', top: 8, right: 8 }}>
          <Chip size="small" label="占位" variant="outlined" color="warning" />
        </Box>
      )}
    </Box>
  )

  const renderLibraryDisplayCardErrors = (state: LibraryDisplayCardState) => (
    <>
      {state.safetyError && (
        <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
          {state.safetyError.slice(0, 100)}{state.safetyError.length > 100 ? '...' : ''}
        </Typography>
      )}
      {state.previewError && (
        <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
          {state.previewError.slice(0, 100)}{state.previewError.length > 100 ? '...' : ''}
        </Typography>
      )}
    </>
  )

  const renderLibraryDisplayCardActions = (item: LibraryDisplayItem, state: LibraryDisplayCardState) => (
    <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
      {state.asset ? (
        <>
          {!state.safetyBlocked && state.hasRenderableImage && (
            <Button
              size="small"
              variant="text"
              onClick={() => approveLibrary({ roles: [state.asset!.role], approved: !state.approved })}
              disabled={libraryLoading}
            >
              {state.approved ? '撤销' : '通过'}
            </Button>
          )}
          {!state.safetyBlocked && state.hasRenderableImage && (!state.preview || state.previewError) && (
            <Button
              size="small"
              variant="text"
              onClick={() => loadLibraryPreview(state.asset!, { force: true })}
              disabled={libraryLoading || state.previewLoading}
            >
              {state.previewLoading ? '加载中…' : state.preview ? '重新加载预览' : '加载预览'}
            </Button>
          )}
          <Button
            size="small"
            variant={state.safetyBlocked ? 'contained' : 'text'}
            color={state.safetyBlocked ? 'warning' : 'primary'}
            onClick={() => openRegenerateDialog(state.asset!)}
            disabled={libraryLoading}
          >
            {state.hasRenderableImage ? '重新生成' : '生成素材'}
          </Button>
        </>
      ) : state.canGenerate ? (
        <Button size="small" variant="text" onClick={() => openRegenerateDialogForRole(item.role, item.title)} disabled={libraryLoading}>
          生成素材
        </Button>
      ) : (
        <Chip size="small" label="等待生成" variant="outlined" />
      )}
    </Stack>
  )

  const renderLibraryDisplayCard = (item: LibraryDisplayItem) => {
    const state = resolveLibraryDisplayCardState(item)

    return (
      <ImageListItem key={item.key} sx={{ border: '1px solid #eee', borderRadius: 2, overflow: 'hidden' }}>
        {renderLibraryDisplayCardPreviewArea(item, state)}
        <Box sx={{ p: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 600 }} display="block">
            {item.title}
          </Typography>
          {state.roleLabel && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
              {state.roleLabel}
            </Typography>
          )}
          {renderLibraryDisplayCardErrors(state)}
          {renderLibraryDisplayCardActions(item, state)}
        </Box>
      </ImageListItem>
    )
  }

  const renderStreamingTextBlock = (
    title: string,
    text: string,
    options?: { maxHeight?: number; monospace?: boolean; streaming?: boolean },
  ) => {
    if (!text) return null
    const maxHeight = typeof options?.maxHeight === 'number' ? options?.maxHeight : 220
    const isStreaming = options?.streaming ?? false
    const fontFamily = options?.monospace
      ? 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'
      : undefined

    return (
      <Box sx={{ mb: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
          {title}
          {isStreaming && (
            <Box
              component="span"
              sx={{
                display: 'inline-block',
                width: 6,
                height: 14,
                bgcolor: 'primary.main',
                animation: 'blink 1s step-end infinite',
                verticalAlign: 'middle',
                ml: 0.5,
                borderRadius: 0.5,
                '@keyframes blink': {
                  '50%': { opacity: 0 },
                },
              }}
            />
          )}
        </Typography>
        <Box sx={{ maxHeight, overflow: 'auto', bgcolor: '#fafafa', border: '1px solid #eee', borderRadius: 1, p: 1.5 }}>
          {options?.monospace ? (
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ whiteSpace: 'pre-wrap', fontFamily, fontSize: '0.85rem', lineHeight: 1.6 }}
            >
              {text}
            </Typography>
          ) : (
            <FormattedContent
              content={text}
              sx={{
                fontSize: '0.9rem',
                lineHeight: 1.7,
                '& p': { margin: '8px 0' },
                '& h1, & h2, & h3': { marginTop: '12px', marginBottom: '8px' },
              }}
            />
          )}
        </Box>
      </Box>
    )
  }

  const renderStreamingPreviewHeader = () => (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        流式预览
      </Typography>
      {activeStreamKeys.length > 0 && <Chip size="small" label={`实时输出: ${activeStreamKeys.join(', ')}`} />}
    </Stack>
  )

  const renderStreamingPreviewStepZero = (planText: string, scriptText: string, profileText: string, audioText: string) => {
    if (!planText && !scriptText && !profileText && !audioText) return null
    return (
      <Box sx={{ mb: 1 }}>
        {renderStreamingPreviewHeader()}
        {renderStreamingTextBlock('计划/脚本提要（流式）', planText, { maxHeight: 200 })}
        {renderStreamingTextBlock('剧本（流式）', scriptText, { maxHeight: 400 })}
        {renderStreamingTextBlock('角色小传（流式）', profileText, { maxHeight: 200 })}
        {renderStreamingTextBlock('音频标记（流式）', audioText, { maxHeight: 200, monospace: true })}
      </Box>
    )
  }

  const renderStreamingPreviewStepOne = (storyboardText: string, cameraTreeText: string) => {
    if (!storyboardText && !cameraTreeText) return null
    return (
      <Box sx={{ mb: 1 }}>
        {renderStreamingPreviewHeader()}
        {renderStreamingTextBlock('分镜（流式）', storyboardText, { maxHeight: 400 })}
        {renderStreamingTextBlock('镜头树（流式）', cameraTreeText, { maxHeight: 260 })}
      </Box>
    )
  }

  const renderStreamingLibraryPlanCardMedia = (item: DreamweaverLibraryPlanItem) => {
    if (item.status === 'processing') {
      return (
        <Box
          sx={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
          }}
        >
          <Box
            sx={{
              width: 24,
              height: 24,
              border: '2px solid',
              borderColor: 'primary.main',
              borderTopColor: 'transparent',
              borderRadius: '50%',
              animation: 'spin 1s linear infinite',
              '@keyframes spin': {
                '0%': { transform: 'rotate(0deg)' },
                '100%': { transform: 'rotate(360deg)' },
              },
            }}
          />
        </Box>
      )
    }

    return (
      <Box
        sx={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
        }}
      >
        <PhotoCameraIcon sx={{ fontSize: 32, color: 'grey.400' }} />
      </Box>
    )
  }

  const renderStreamingLibraryPlanCardStatusBadge = (item: DreamweaverLibraryPlanItem) => {
    if (item.status !== 'processing' && item.status !== 'done') return null

    const label = item.status === 'processing' ? '生成中' : '完成'
    const backgroundColor = item.status === 'processing' ? 'warning.main' : 'success.main'

    return (
      <Box
        sx={{
          position: 'absolute',
          top: 4,
          right: 4,
          bgcolor: backgroundColor,
          color: 'white',
          fontSize: '0.65rem',
          px: 0.5,
          py: 0.25,
          borderRadius: 0.5,
        }}
      >
        {label}
      </Box>
    )
  }

  const renderStreamingLibraryPlanCard = (item: DreamweaverLibraryPlanItem) => {
    const statusLabel = item.status === 'done' ? '已生成' : item.status === 'processing' ? '生成中...' : '待生成'
    const label = item.label || item.entity_name || item.role

    return (
      <Grid item key={item.id} xs={6} sm={4} md={3} lg={2}>
        <Card
          sx={{
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            border: item.status === 'processing' ? '2px solid' : '1px solid',
            borderColor: item.status === 'processing' ? 'warning.main' : 'divider',
            opacity: item.status === 'planned' ? 0.7 : 1,
          }}
        >
          <Box
            sx={{
              position: 'relative',
              paddingTop: '100%',
              bgcolor: 'grey.100',
              overflow: 'hidden',
            }}
          >
            {renderStreamingLibraryPlanCardMedia(item)}
            {renderStreamingLibraryPlanCardStatusBadge(item)}
          </Box>
          <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
            <Typography variant="caption" sx={{ fontWeight: 500, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {label}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
              {statusLabel}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
    )
  }

  const renderStreamingPreviewStepTwo = () => {
    if (!libraryPlanItems.length) return null

    const plannedCount = libraryPlanItems.filter((item) => item.status === 'planned').length
    const doneCount = libraryPlanItems.filter((item) => item.status === 'done').length
    const processingCount = libraryPlanItems.filter((item) => item.status === 'processing').length

    return (
      <Box sx={{ mb: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            素材库生成
          </Typography>
          <Chip size="small" label={`总计: ${libraryPlanItems.length}`} />
          <Chip size="small" label={`已生成: ${doneCount}`} color={doneCount > 0 ? 'success' : 'default'} />
          <Chip size="small" label={`生成中: ${processingCount}`} color={processingCount > 0 ? 'warning' : 'default'} />
          <Chip size="small" label={`待生成: ${plannedCount}`} />
        </Stack>
        <Grid container spacing={1.5}>
          {libraryPlanItems.slice(0, 12).map(renderStreamingLibraryPlanCard)}
          {libraryPlanItems.length > 12 && (
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">
                还有 {libraryPlanItems.length - 12} 个素材...
              </Typography>
            </Grid>
          )}
        </Grid>
      </Box>
    )
  }

  const renderStreamingPreviewStepThree = () => {
    const assets = assetPlanItems.filter((item) => item.id !== 'merged_video')
    if (!assets.length) return null

    return (
      <Box sx={{ mb: 1 }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" mb={0.5}>
          <Chip size="small" label={`占位: ${assetPlanSummary.total}`} />
          <Chip size="small" label={`已生成: ${assetPlanSummary.done}`} color={assetPlanSummary.done > 0 ? 'success' : 'default'} />
          <Chip size="small" label={`待生成: ${assetPlanSummary.planned}`} />
          <Chip size="small" label={`图像: ${assetPlanSummary.images}`} />
          <Chip size="small" label={`视频: ${assetPlanSummary.videos}`} />
        </Stack>
        {renderAssetPlanGrid('素材占位卡', assets)}
      </Box>
    )
  }

  const renderStreamingPreviewStepFour = () => {
    if (!mergedVideoPlan) return null

    return (
      <Box sx={{ mb: 1 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            流式预览
          </Typography>
          <Chip size="small" label={mergedVideoPlan.uri ? '已生成' : '待生成'} color={mergedVideoPlan.uri ? 'success' : 'default'} />
        </Stack>
        {renderAssetPlanGrid('合成视频占位', [mergedVideoPlan])}
      </Box>
    )
  }

  const renderStreamingPreview = (step: number) => {
    const planText = String(streamSnapshots.plan || '').trim()
    const scriptText = String(streamSnapshots.script || streamSnapshots.scriptEnhance || '').trim()
    const profileText = String(streamSnapshots.characterProfiles || '').trim()
    const audioText = String(streamSnapshots.audioMarkers || '').trim()
    const storyboardText = String(streamSnapshots.storyboard || '').trim()
    const cameraTreeText = String(streamSnapshots.cameraTree || '').trim()

    if (step === 0) {
      return renderStreamingPreviewStepZero(planText, scriptText, profileText, audioText)
    }

    if (step === 1) {
      return renderStreamingPreviewStepOne(storyboardText, cameraTreeText)
    }

    if (step === 2) {
      return renderStreamingPreviewStepTwo()
    }

    if (step === 3) {
      return renderStreamingPreviewStepThree()
    }

    if (step === 4) {
      return renderStreamingPreviewStepFour()
    }

    return null
  }

  const renderScriptStageSnapshot = () => {
    const planText = snapshotPlanText.trim()
    const scriptText = snapshotScriptText.trim()
    const profilesCount = snapshotCharacterProfiles.length
    const markersCount = snapshotAudioMarkers.length
    const entitySummary = summarizeScriptEntities(snapshotScriptEntities)
    const hasGeneration = Boolean(snapshotScriptGeneration && Object.keys(snapshotScriptGeneration).length > 0)

    const renderSnapshotMonospaceBox = (content: string, maxHeight = 240) => (
      <Box
        sx={{
          whiteSpace: 'pre-wrap',
          fontFamily: 'monospace',
          fontSize: 12,
          bgcolor: '#fafafa',
          border: '1px solid #eee',
          borderRadius: 2,
          p: 1.5,
          maxHeight,
          overflow: 'auto',
        }}
      >
        {content}
      </Box>
    )

    const renderJsonBlock = (value: unknown, emptyText: string, maxHeight = 240) => {
      const isEmpty =
        value == null ||
        (Array.isArray(value) ? value.length === 0 : typeof value === 'object' && Object.keys(value).length === 0)
      if (isEmpty) {
        return (
          <Typography variant="body2" color="text.secondary">
            {emptyText}
          </Typography>
        )
      }
      return renderSnapshotMonospaceBox(JSON.stringify(value, null, 2), maxHeight)
    }

    const renderSnapshotAccordionHeader = (title: string, extra?: JSX.Element | null) => (
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        {extra}
      </Stack>
    )

    const renderSnapshotJsonAccordion = (
      title: string,
      value: unknown,
      emptyText: string,
      extra?: JSX.Element | null,
    ) => (
      <Accordion>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>{renderSnapshotAccordionHeader(title, extra)}</AccordionSummary>
        <AccordionDetails>{renderJsonBlock(value, emptyText)}</AccordionDetails>
      </Accordion>
    )

    const renderSnapshotTextAccordion = ({
      title,
      text,
      emptyText,
      defaultExpanded = false,
      extra,
    }: {
      title: string
      text: string
      emptyText: string
      defaultExpanded?: boolean
      extra?: JSX.Element | null
    }) => (
      <Accordion defaultExpanded={defaultExpanded}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>{renderSnapshotAccordionHeader(title, extra)}</AccordionSummary>
        <AccordionDetails>
          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
            {text || emptyText}
          </Typography>
        </AccordionDetails>
      </Accordion>
    )

    const renderSnapshotScriptAccordion = () => (
      <Accordion defaultExpanded>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderSnapshotAccordionHeader(
            '剧本（快照）',
            <>
              <Chip size="small" label={snapshotScriptApproved ? '已通过' : '未通过'} color={snapshotScriptApproved ? 'success' : 'default'} />
              <Chip size="small" label={`长度: ${scriptText.length}`} />
            </>,
          )}
        </AccordionSummary>
        <AccordionDetails>
          {scriptText ? (
            renderSnapshotMonospaceBox(scriptText.length > 6000 ? `${scriptText.slice(0, 6000)}\n…` : scriptText, 320)
          ) : (
            <Typography variant="body2" color="text.secondary">
              尚无可用剧本快照（可能仍在生成或尚未落库）。
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>
    )

    return (
      <Box sx={{ mb: 1 }}>
        {renderSnapshotTextAccordion({
          title: '计划 / 剧本提要（快照）',
          text: planText,
          emptyText: '暂无计划/提要快照（可能仍在生成或尚未落库）。',
          defaultExpanded: true,
        })}

        {renderSnapshotScriptAccordion()}

        {renderSnapshotJsonAccordion(
          '角色小传（快照）',
          snapshotCharacterProfiles,
          '暂无角色小传（可能尚未生成或未落库）。',
          profilesCount > 0 ? <Chip size="small" label={`${profilesCount} 条`} /> : null,
        )}

        {renderSnapshotJsonAccordion(
          '音频标记（快照）',
          snapshotAudioMarkers,
          '暂无音频标记（可能尚未生成或未落库）。',
          markersCount > 0 ? <Chip size="small" label={`${markersCount} 条`} /> : null,
        )}

        {renderSnapshotJsonAccordion(
          '实体抽取（快照）',
          snapshotScriptEntities,
          '暂无实体抽取数据（可能尚未生成或未落库）。',
          entitySummary ? <Chip size="small" label={entitySummary} /> : null,
        )}

        {renderSnapshotJsonAccordion(
          '剧本生成信息（快照）',
          snapshotScriptGeneration,
          '暂无剧本生成信息（可能尚未生成或未落库）。',
          hasGeneration ? <Chip size="small" label="已记录" /> : null,
        )}
      </Box>
    )
  }

  const renderSafetyBlockedAlert = () => {
    if (!safetyBlockedShots.length) return null
    return (
      <Alert severity="warning" sx={{ mb: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          检测到内容安全拦截：部分镜头产物被安全过滤
        </Typography>
        <Typography variant="body2" color="text.secondary">
          请点击下方镜头编号查看/修改提示词后重试生成。
        </Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
          {safetyBlockedShots.map(renderSafetyBlockedShotAction)}
        </Stack>
        {safetyBlockedShots[0]?.errorSample && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            示例错误：{safetyBlockedShots[0].errorSample}
          </Typography>
        )}
      </Alert>
      )
  }

  const renderSafetyBlockedShotAction = (item: {
    shotId: string
    shotIndex?: number
    roles: string[]
    errorSample: string
  }) => {
    const label = item.shotIndex != null ? `#${item.shotIndex} ${item.shotId}` : item.shotId

    return (
      <Button key={item.shotId} size="small" variant="outlined" onClick={() => openSafetyBlockedShot(item.shotId)}>
        {label}
      </Button>
    )
  }

  const formatDateTime = (value: unknown) => {
    if (!value || typeof value !== 'string') return null
    const dt = new Date(value)
    if (!Number.isFinite(dt.getTime())) return value
    return dt.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const copyText = async (text: string) => {
    const value = String(text || '')
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      window.prompt('复制以下内容：', value)
    }
  }

  const safeJsonStringify = (value: unknown) => {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }

  const copyDebugInfo = async () => {
    const payload = {
      page: 'DreamWeaverRunPage',
      selectedProjectId,
      selectedChapterIds,
      qualityMode: highQuality ? 'quality' : 'cost',
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
    }

    await copyText(safeJsonStringify(payload))
  }

  const renderDebugJsonBox = (value: unknown, maxHeight?: number) => {
    return (
      <Box
        sx={{
          whiteSpace: 'pre-wrap',
          fontFamily: 'monospace',
          fontSize: 12,
          bgcolor: '#fafafa',
          border: '1px solid #eee',
          borderRadius: 2,
          p: 1.5,
          ...(typeof maxHeight === 'number'
            ? {
                maxHeight,
                overflow: 'auto',
              }
            : {}),
        }}
      >
        {safeJsonStringify(value)}
      </Box>
    )
  }

  const renderDiagnosticJson = (value: unknown) => {
    return renderDebugJsonBox(value, 320)
  }

  const renderTitledDiagnosticJsonAccordion = ({
    title,
    value,
    marginTop = 1,
  }: {
    title: string
    value: unknown
    marginTop?: number
  }) => {
    if (!value) return null
    return (
      <Accordion sx={marginTop > 0 ? { mt: marginTop } : undefined}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
        </AccordionSummary>
        <AccordionDetails>{renderDiagnosticJson(value)}</AccordionDetails>
      </Accordion>
    )
  }

  const renderDiagnosticUploadButton = ({
    label,
    accept,
    shotId,
    assetRole,
  }: {
    label: string
    accept: string
    shotId: string
    assetRole: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip'
  }) => (
    <Button
      size="small"
      variant="outlined"
      component="label"
      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
    >
      {label}
      <input
        hidden
        type="file"
        accept={accept}
        onChange={(e) => {
          const f = e.target.files && e.target.files[0]
          e.target.value = ''
          if (!f) return
          void uploadShotAsset(shotId, assetRole, f)
        }}
      />
    </Button>
  )

  const renderDiagnosticFrame = (title: string, frame: unknown, kind: 'image' | 'video' = 'image') => {
    if (!frame || typeof frame !== 'object') return null
    const frameRecord = frame as Record<string, unknown>
    const uri = String(frameRecord.path || '').trim()
    if (!uri) return null
    const meta =
      frameRecord.meta && typeof frameRecord.meta === 'object' && !Array.isArray(frameRecord.meta)
        ? (frameRecord.meta as Record<string, unknown>)
        : {}
    const decision =
      meta.decision && typeof meta.decision === 'object' && !Array.isArray(meta.decision)
        ? (meta.decision as Record<string, unknown>)
        : null
    const via = typeof meta.via === 'string' ? meta.via : ''
    const mode = decision && typeof decision.mode === 'string' ? String(decision.mode) : ''
    const reason = decision && typeof decision.reason === 'string' ? String(decision.reason) : ''
    const selector = typeof meta.selector === 'string' ? meta.selector : ''
    const candidateCount = typeof meta.candidate_count === 'number' ? meta.candidate_count : null
    const selected = typeof meta.selected === 'number' ? meta.selected : null
    const selectedSeed = typeof meta.selected_seed === 'number' ? meta.selected_seed : null
    const candidates = Array.isArray(meta.candidates) ? meta.candidates : []
    const hasCandidates = candidates.some((c) => typeof c === 'string' && String(c).trim())

    return (
      <Accordion sx={{ mt: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ width: '100%' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
              {title}
            </Typography>
            {via && <Chip size="small" label={`via: ${via}`} />}
            {mode && <Chip size="small" label={`mode: ${mode}`} />}
            {reason && (
              <Chip size="small" label={`reason: ${reason}`} variant="outlined" sx={{ maxWidth: 420 }} />
            )}
            {selector && <Chip size="small" label={`selector: ${selector}`} />}
            {candidateCount != null && <Chip size="small" label={`cands: ${candidateCount}`} />}
            {selected != null && <Chip size="small" label={`selected: ${selected}`} color="primary" />}
            {selectedSeed != null && <Chip size="small" label={`seed: ${selectedSeed}`} />}
            {hasCandidates && <Chip size="small" label="keep_candidates" color="success" variant="outlined" />}
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
            <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={() => copyText(safeJsonStringify(meta))}>
              复制 meta
            </Button>
            <Button size="small" variant="text" onClick={() => copyText(uri)}>
              复制路径
            </Button>
          </Stack>

          {renderRunAssetPreviewGrid('预览', [uri], kind)}

          {hasCandidates &&
            renderRunAssetPreviewGrid(
              '候选图（keep_candidates）',
              candidates
                .map((c) => (typeof c === 'string' ? c.trim() : ''))
                .filter(Boolean)
                .slice(0, 12),
              'image',
            )}

          <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
            meta
          </Typography>
          {renderDiagnosticJson(meta)}
        </AccordionDetails>
      </Accordion>
    )
  }

  const fetchRunHistory = useCallback(
    async (projectId: number) => {
      setHistoryLoading(true)
      setHistoryError(null)
      try {
        const res = await apiClient.listDreamweaverRuns(projectId, 100)
        const runs = toDreamweaverRunSummaries(res.data)
        setHistoryRuns(runs)
      } catch (e: unknown) {
        setHistoryError(await extractApiErrorMessage(e, '加载历史任务失败'))
      } finally {
        setHistoryLoading(false)
      }
    },
    [setHistoryRuns]
  )

  const historyStatusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const run of historyRuns) {
      const statusRaw = String(run.status || '').trim().toLowerCase() || 'unknown'
      counts[statusRaw] = (counts[statusRaw] || 0) + 1
    }
    return counts
  }, [historyRuns])

  const filteredHistoryRuns = useMemo(() => {
    if (!historyStatusFilters.length) return historyRuns
    const enabled = new Set(historyStatusFilters.map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))
    if (!enabled.size) return historyRuns
    return historyRuns.filter((run) => enabled.has(String(run.status || '').trim().toLowerCase() || 'unknown'))
  }, [historyRuns, historyStatusFilters])

  const bulkDeleteTargets = useMemo(() => {
    return filteredHistoryRuns.filter((run) => {
      const statusRaw = String(run.status || '').trim().toLowerCase()
      return statusRaw !== 'running' && statusRaw !== 'queued'
    })
  }, [filteredHistoryRuns])

  const bulkDeleteSkippedCount = Math.max(0, filteredHistoryRuns.length - bulkDeleteTargets.length)

  const openHistoryDialog = () => {
    if (!selectedProjectId) return
    setHistoryOpen(true)
    void fetchRunHistory(selectedProjectId)
  }

  const closeHistoryDialog = () => {
    setHistoryOpen(false)
    setHistoryError(null)
    setHistoryStatusFilters([])
  }

  const getHistoryStatusMeta = (
    status: string,
  ): { label: string; color: 'default' | 'success' | 'error' | 'warning' | 'info' } => {
    const normalized = String(status || '').trim().toLowerCase()
    if (normalized === 'completed') return { label: '已完成', color: 'success' }
    if (normalized === 'waiting') return { label: '待审核', color: 'warning' }
    if (normalized === 'failed') return { label: '失败', color: 'error' }
    if (normalized === 'timeout') return { label: '超时', color: 'warning' }
    if (normalized === 'running') return { label: '运行中', color: 'info' }
    if (normalized === 'queued') return { label: '排队中', color: 'info' }
    return { label: normalized || '未知', color: 'default' }
  }

  const handleViewHistoryRun = (runId: string) => {
    if (!selectedProjectId) return
    const nextRunId = String(runId || '').trim()
    if (!nextRunId) return

    setError(null)
    setResult(null)
    setRunPreflight(null)
    setTaskId(null)
    setRunning(false)
    setWaitingApproval(false)
    setTaskRunId(nextRunId)
    setTaskStatus(null)
    setTaskQueue(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)

    setRunSnapshot(null)
    setRunSnapshotError(null)

    setScriptError(null)
    setScriptText('')
    setScriptSavedText('')
    setScriptApproved(false)
    setScriptRequiresReview(true)
    setScriptEntities(null)
    setScriptGeneration(null)

    setLibrary(null)
    setLibraryError(null)
    setLibraryPreviews({})
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
    clearRunAssetPreviews()
    resetDreamweaverEvents()

    setPreviewStep(0)
    setManualPreviewStep(false)

    writePersistedDreamWeaverRun(selectedProjectId, { run_id: nextRunId, task_id: null, status: null })
    void hydrateFromPersistedRun(selectedProjectId, nextRunId, null, null)
    setHistoryOpen(false)
  }

  const openDeleteRunDialog = (runId: string) => {
    const nextRunId = String(runId || '').trim()
    if (!nextRunId) return
    setDeleteDialogError(null)
    setDeleteRunId(nextRunId)
    setDeleteDialogOpen(true)
  }

  const closeDeleteRunDialog = () => {
    if (deleteSubmitting) return
    setDeleteDialogOpen(false)
    setDeleteRunId(null)
    setDeleteDialogError(null)
  }

  const confirmDeleteRun = async () => {
    if (!deleteRunId || !selectedProjectId) return
    setDeleteSubmitting(true)
    setDeleteDialogError(null)
    try {
      await apiClient.deleteDreamweaverRun(deleteRunId, true)

      const persisted = readPersistedDreamWeaverRun(selectedProjectId)
      if (persisted?.run_id === deleteRunId) {
        clearPersistedDreamWeaverRun(selectedProjectId)
      }

      if (persistedRunId === deleteRunId) {
        setError(null)
        setResult(null)
        setRunPreflight(null)
        setTaskId(null)
        setTaskRunId(null)
        setRunning(false)
        setWaitingApproval(false)
        setTaskStatus(null)
        setTaskQueue(null)
        setTaskProgress(0)
        setTaskState(null)
        setTaskStage(null)
        setTaskArtifacts(null)
        setRunSnapshot(null)
        setRunSnapshotError(null)
        setScriptError(null)
        setScriptText('')
        setScriptSavedText('')
        setScriptApproved(false)
        setScriptRequiresReview(true)
        setScriptEntities(null)
        setScriptGeneration(null)
        setLibrary(null)
        setLibraryError(null)
        setLibraryPreviews({})
        setMergedVideoLoading(false)
        setMergedVideoError(null)
        setMergedVideoPreviewUrl(null)
      }

      await fetchRunHistory(selectedProjectId)
      try {
        const res = await apiClient.getDreamweaverProjectLockedConfig(selectedProjectId)
        setLockedGenerationConfig(toDreamweaverProjectLockedGenerationConfig(res.data))
        setLockedGenerationConfigError(null)
      } catch (e: unknown) {
        setLockedGenerationConfig(null)
        setLockedGenerationConfigError(await extractApiErrorMessage(e, '加载项目锁定配置失败'))
      }
      setDeleteDialogOpen(false)
      setDeleteRunId(null)
    } catch (e: unknown) {
      if (isNotFoundError(e)) {
        resetMissingRunState(selectedProjectId)
      }
      setDeleteDialogError(await extractApiErrorMessage(e, '删除失败'))
    } finally {
      setDeleteSubmitting(false)
    }
  }

  const openBulkDeleteDialog = () => {
    if (!selectedProjectId) return
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress(null)
    setBulkDeleteDialogOpen(true)
  }

  const closeBulkDeleteDialog = () => {
    if (bulkDeleteSubmitting) return
    setBulkDeleteDialogOpen(false)
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress(null)
  }

  const confirmBulkDeleteRuns = async () => {
    if (!selectedProjectId) return

    const targets = [...bulkDeleteTargets]
    if (!targets.length) return

    setBulkDeleteSubmitting(true)
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress({ current: 0, total: targets.length })

    const errors: string[] = []
    let deleted = 0

    for (let i = 0; i < targets.length; i += 1) {
      const run = targets[i]
      const runId = String(run.run_id || '').trim()
      if (!runId) continue

      try {
        await apiClient.deleteDreamweaverRun(runId, true)
        deleted += 1

        const persisted = readPersistedDreamWeaverRun(selectedProjectId)
        if (persisted?.run_id === runId) {
          clearPersistedDreamWeaverRun(selectedProjectId)
        }

        if (persistedRunId === runId) {
          setError(null)
          setResult(null)
          setRunPreflight(null)
          setTaskId(null)
          setTaskRunId(null)
          setRunning(false)
          setWaitingApproval(false)
          setTaskStatus(null)
          setTaskQueue(null)
          setTaskProgress(0)
          setTaskState(null)
          setTaskStage(null)
          setTaskArtifacts(null)
          setRunSnapshot(null)
          setRunSnapshotError(null)
          setScriptError(null)
          setScriptText('')
          setScriptSavedText('')
          setScriptApproved(false)
          setScriptRequiresReview(true)
          setScriptEntities(null)
          setScriptGeneration(null)
          setLibrary(null)
          setLibraryError(null)
          setLibraryPreviews({})
          setMergedVideoLoading(false)
          setMergedVideoError(null)
          setMergedVideoPreviewUrl(null)
          clearRunAssetPreviews()
          resetDreamweaverEvents()
        }
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '删除失败')
        errors.push(`${runId}: ${msg}`)
      } finally {
        setBulkDeleteProgress({ current: i + 1, total: targets.length })
      }
    }

    try {
      await fetchRunHistory(selectedProjectId)
    } catch (e: unknown) {
      // ignore
    }
    try {
      await refreshLockedGenerationConfig(selectedProjectId)
    } catch (e: unknown) {
      // ignore
    }

    setBulkDeleteResult({
      deleted,
      skipped: Math.max(0, filteredHistoryRuns.length - targets.length),
      failed: errors.length,
      errors,
    })
    setBulkDeleteSubmitting(false)
  }

  const hydrateFromPersistedRun = async (
    projectId: number,
    runId: string,
    persistedTaskId: string | null,
    persistedStatus: string | null,
  ) => {
    if (!runId) return
    try {
      const res = await apiClient.getDreamweaverRun(runId)
      const data = toDreamweaverRunSnapshot(res.data)
      setRunSnapshot(data)
      setRunSnapshotError(null)

      const status = String(data?.status || '').trim()
      const statusLower = status.toLowerCase()
      const stage = data?.stage != null ? String(data.stage) : null
      const state = data?.state != null ? String(data.state) : null
      const progress = typeof data?.progress === 'number' ? data.progress : 0
      const contract = asObject(data?.contract)

      setTaskStatus(status || null)
      setTaskProgress(progress)
      setTaskStage(stage)
      setTaskState(state)

      const waitingKind = String(stage || state || '').trim().toLowerCase()
      const waiting =
        statusLower === 'waiting' ||
        waitingKind === DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL ||
        waitingKind === DREAMWEAVER_STAGES.WAITING_APPROVAL ||
        waitingKind === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION
      setWaitingApproval(waiting)

      const isRunning = statusLower === 'running' || statusLower === 'queued'
      setRunning(isRunning)

      if (statusLower === 'completed' && contract) {
        const nextResult = buildResultFromRunSnapshot(data, runId)
        if (nextResult) {
          setResult((prev) => mergeRunResult(prev, nextResult))
          if (nextResult.preflight) {
            setRunPreflight(nextResult.preflight)
          }
        }
      }

      if (waiting) {
        setTaskId(null)
        return
      }
      if (isRunning && persistedTaskId) {
        setTaskId(persistedTaskId)
      } else if (!isRunning) {
        setTaskId(null)
      }
    } catch (e: unknown) {
      if (isNotFoundError(e)) {
        if (shouldTreatRunNotFoundAsPending(persistedTaskId, persistedStatus)) {
          setRunSnapshotError('运行数据尚未落库，稍后自动重试')
          return
        }
        resetMissingRunState(projectId)
      }
      setRunSnapshotError(await extractApiErrorMessage(e, '恢复运行状态失败'))
    }
  }

  useEffect(() => {
    const loadProjects = async () => {
      try {
        const res = await apiClient.getProjects()
        setProjects(res.data || [])
      } catch (e: unknown) {
        setError(getThrownErrorMessage(e) || '获取项目列表失败')
      }
    }
    loadProjects()
  }, [])

  useEffect(() => {
    if (!selectedProjectId) return
    if (restoredProjectIdRef.current === selectedProjectId) return
    restoredProjectIdRef.current = selectedProjectId

    const persisted = readPersistedDreamWeaverRun(selectedProjectId)
    if (!persisted) return

    setTaskRunId(persisted.run_id)
    setTaskStatus(persisted.status || null)
    if (persisted.style_preset) setStylePreset(persisted.style_preset)
    if (persisted.quality_mode) setHighQuality(persisted.quality_mode === 'quality')
    if (typeof persisted.qc_allow_fail === 'boolean') setQcAllowFail(persisted.qc_allow_fail)
    if (typeof persisted.smart_tuning === 'boolean') setSmartTuning(persisted.smart_tuning)
    if (typeof persisted.video_require_confirmation === 'boolean')
      setVideoRequireConfirmation(persisted.video_require_confirmation)
    if (typeof persisted.prompt_review_required === 'boolean')
      setPromptReviewRequired(persisted.prompt_review_required)
    if (persisted.image_ratio) setImageRatio(persisted.image_ratio)
    if (persisted.image_resolution) setImageResolution(persisted.image_resolution)

    void hydrateFromPersistedRun(selectedProjectId, persisted.run_id, persisted.task_id ?? null, persisted.status ?? null)
  }, [selectedProjectId])

  useEffect(() => {
    if (!selectedProjectId) return
    if (!lockedGenerationConfig?.locked) return
    if (lockedGenerationConfig.style_preset) setStylePreset(lockedGenerationConfig.style_preset)
    if (lockedGenerationConfig.image_ratio) setImageRatio(lockedGenerationConfig.image_ratio)
    if (lockedGenerationConfig.image_resolution) setImageResolution(lockedGenerationConfig.image_resolution)
  }, [lockedGenerationConfig, selectedProjectId])

  useEffect(() => {
    if (!taskId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      try {
        const res = await apiClient.getDreamweaverTask(taskId)
        const data = toDreamweaverTaskStatus(res.data)
        if (cancelled) return
        if (!data) {
          setError('任务状态响应格式无效')
          setRunning(false)
          setTaskId(null)
          return
        }
        setError(null)

        if (data.status === 'queued') {
          setRunning(true)
          setTaskStatus('queued')
          setTaskQueue(data.queue || null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts(data.artifacts || null)
          setTaskRunId((prev) => data.run_id || prev)
          setWaitingApproval(false)
          timer = setTimeout(poll, 1000)
          return
        }

        if (data.status === 'running') {
          setTaskStatus('running')
          setTaskQueue(data.queue || null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts(data.artifacts || null)
          setTaskRunId((prev) => data.run_id || prev)
          setWaitingApproval(false)
          timer = setTimeout(poll, 1000)
          return
        }

        if (data.status === 'waiting') {
          setTaskStatus('waiting')
          setTaskQueue(data.queue || null)
          setRunning(false)
          setTaskId(null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts(data.artifacts || null)
          setTaskRunId((prev) => data.run_id || prev)
          setWaitingApproval(true)
          return
        }

        setRunning(false)
        setTaskId(null)
        setTaskRunId((prev) => data.run_id || prev)
        setTaskStatus(null)
        setTaskQueue(null)
        setTaskProgress(0)
        setTaskState(null)
        setTaskStage(null)
        setTaskArtifacts(null)
        setWaitingApproval(false)

        if (data.status === 'completed') {
          setResult((prev) => mergeRunResult(prev, data.result || null))
          if (data.result?.preflight) {
            setRunPreflight(data.result.preflight)
          }
        } else {
          setError(data.error || '任务执行失败')
        }
      } catch (e: unknown) {
        if (cancelled) return
        const message = await extractApiErrorMessage(e, '任务状态查询失败')
        const status = getThrownErrorStatus(e)
        const isTimeout = isTimeoutErrorLike(e)
        const isNetworkError = isNetworkErrorLike(e)

        // 轮询属于“弱一致”场景：偶发超时/网络抖动不应中断任务执行。
        if (isTimeout || isNetworkError || (status !== null && status >= 500)) {
          setError(message)
          timer = setTimeout(poll, 2000)
          return
        }

        setRunning(false)
        setTaskId(null)
        setTaskStatus(null)
        setTaskQueue(null)
        setWaitingApproval(false)
        setError(message)
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [taskId])

  const refreshLockedGenerationConfig = useCallback(async (projectId: number) => {
    const reqId = lockedGenerationConfigReqIdRef.current + 1
    lockedGenerationConfigReqIdRef.current = reqId
    setLockedGenerationConfigLoading(true)
    setLockedGenerationConfigError(null)
    try {
      const res = await apiClient.getDreamweaverProjectLockedConfig(projectId)
      if (lockedGenerationConfigReqIdRef.current !== reqId) return
      setLockedGenerationConfig(toDreamweaverProjectLockedGenerationConfig(res.data))
    } catch (e: unknown) {
      if (lockedGenerationConfigReqIdRef.current !== reqId) return
      setLockedGenerationConfig(null)
      setLockedGenerationConfigError(await extractApiErrorMessage(e, '加载项目锁定配置失败'))
    } finally {
      if (lockedGenerationConfigReqIdRef.current !== reqId) return
      setLockedGenerationConfigLoading(false)
    }
  }, [])

  const handleSelectProject = useCallback(async (projectId: number) => {
    setSelectedProjectId(projectId)
    setLockedGenerationConfig(null)
    setLockedGenerationConfigError(null)
    void refreshLockedGenerationConfig(projectId)
    setResult(null)
    setRunPreflight(null)
    setError(null)
    setWaitingApproval(false)
    setRunning(false)
    setTaskId(null)
    setTaskRunId(null)
    setTaskStatus(null)
    setTaskQueue(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)
    setRunSnapshot(null)
    setRunSnapshotError(null)
    autoLoadedRunSnapshotRunIdRef.current = null
    setPreviewStep(0)
    setManualPreviewStep(false)
    setScriptError(null)
    setScriptText('')
    setScriptSavedText('')
    setScriptApproved(false)
    setScriptRequiresReview(true)
    setScriptEntities(null)
    setScriptGeneration(null)
    setLibrary(null)
    setLibraryError(null)
    setLibraryPreviews({})
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
    clearRunAssetPreviews()
    resetDreamweaverEvents()
    setLoadingChapters(true)
    try {
      const res = await apiClient.getChapters(projectId)
      const data = toChapters(res.data)
      setChapters(data)
      setSelectedChapterIds(data.map((c) => c.id))
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
    setRunning(true)
    setWaitingApproval(false)
    setRunSnapshot(null)
    setRunSnapshotError(null)
    autoLoadedRunSnapshotRunIdRef.current = null
    setPreviewStep(0)
    setManualPreviewStep(false)
    setScriptError(null)
    setScriptText('')
    setScriptSavedText('')
    setScriptApproved(false)
    setScriptRequiresReview(true)
    setScriptEntities(null)
    setScriptGeneration(null)
    setPromptReviewError(null)
    setPromptReviewShowAll(false)
    setPromptEditOpen(false)
    setPromptEditShot(null)
    setPromptEditHead('')
    setPromptEditTail('')
    setPromptEditVideo('')
    setPromptEditError(null)
    setTaskId(null)
    setTaskRunId(null)
    setTaskStatus(null)
    setTaskQueue(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)
    setVideoJobActionError(null)
    setVideoJobConfirmingShotId(null)
    setResult(null)
    setRunPreflight(null)
    setError(null)
    setTaskPointsPrecheckError(null)
    setLibrary(null)
    setLibraryError(null)
    setLibraryPreviews({})
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
    clearRunAssetPreviews()
    resetDreamweaverEvents()
    try {
      const res = await apiClient.runDreamweaverAsync(selectedProjectId, selectedChapterIds, {
        quality_mode: highQuality ? 'quality' : 'cost',
        qc_allow_fail: qcAllowFail,
        smart_tuning: smartTuning,
        ab_variant: abVariant.trim() ? abVariant.trim() : undefined,
        video_require_confirmation: videoRequireConfirmation,
        prompt_review_required: promptReviewRequired,
        style_preset: stylePreset,
        image_ratio: imageRatio,
        image_resolution: imageResolution,
      })
      const data = toDreamweaverRunAsyncResponse(res.data)
      if (!data) {
        setError('启动响应格式无效')
        return false
      }
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
    } finally {
      // running 状态由轮询结束时关闭
    }
  }

  useEffect(() => {
    return () => {
      if (!mergedVideoPreviewUrl) return
      try {
        URL.revokeObjectURL(mergedVideoPreviewUrl)
      } catch {
        // ignore
      }
    }
  }, [mergedVideoPreviewUrl])

  const applyStageSignal = useCallback((stage: string | null, payload: Record<string, unknown>) => {
    if (stage) setTaskStage(stage)
    const stateRaw = typeof payload.state === 'string' ? String(payload.state) : null
    if (stateRaw) setTaskState(stateRaw)
    const progressRaw = typeof payload.progress === 'number' ? payload.progress : null
    if (typeof progressRaw === 'number') setTaskProgress(progressRaw)

    if (stateRaw) {
      const upper = stateRaw.toUpperCase()
      if (upper.startsWith('WAITING')) {
        setTaskStatus('waiting')
        setWaitingApproval(true)
        setRunning(false)
      } else if (upper === 'DONE') {
        setTaskStatus('completed')
        setWaitingApproval(false)
        setRunning(false)
      } else if (upper === 'FAILED') {
        setTaskStatus('failed')
        setWaitingApproval(false)
        setRunning(false)
      } else {
        setTaskStatus('running')
        setWaitingApproval(false)
        setRunning(true)
      }
    }
  }, [])

  const normalizeAssetPlanItems = useCallback((items: unknown): DreamweaverAssetPlanItem[] => {
    if (!Array.isArray(items)) return []
    return items
      .map((raw) => {
        const item = asObject(raw)
        if (!item) return null
        const id = String(item.id || '').trim()
        if (!id) return null
        const kindRaw = String(item.kind || '').trim().toLowerCase()
        const roleRaw = String(item.role || '').trim()
        const statusRaw = String(item.status || '').trim().toLowerCase()
        const kind = kindRaw === 'video' ? 'video' : kindRaw === 'image' ? 'image' : roleRaw === 'video_clip' || roleRaw === 'merged_video' ? 'video' : 'image'
        const status = statusRaw === 'done' ? 'done' : statusRaw === 'processing' ? 'processing' : 'planned'
        const uri = typeof item.uri === 'string' ? String(item.uri || '').trim() : ''
        const camIdx = typeof item.cam_idx === 'number' ? item.cam_idx : null
        return {
          id,
          shot_id: item.shot_id != null ? String(item.shot_id) : null,
          scene_id: item.scene_id != null ? String(item.scene_id) : null,
          cam_idx: camIdx,
          role: roleRaw || null,
          kind,
          label: typeof item.label === 'string' ? String(item.label || '') : id,
          status,
          optional: Boolean(item.optional),
          uri: uri || null,
        } as DreamweaverAssetPlanItem
      })
      .filter(Boolean) as DreamweaverAssetPlanItem[]
  }, [])

  const normalizeLibraryPlanItems = useCallback((items: unknown): DreamweaverLibraryPlanItem[] => {
    if (!Array.isArray(items)) return []
    return items
      .map((raw) => {
        const item = asObject(raw)
        if (!item) return null
        const role = String(item.role || '').trim()
        const id = String(item.id || role || '').trim()
        if (!id || !role) return null
        const statusRaw = String(item.status || '').trim().toLowerCase()
        const status = statusRaw === 'done' ? 'done' : statusRaw === 'planned' ? 'planned' : 'processing'
        const entityType = item.entity_type != null ? String(item.entity_type) : null
        const entityId = typeof item.entity_id === 'number' ? item.entity_id : Number(item.entity_id || 0) || null
        const entityName = typeof item.entity_name === 'string' ? String(item.entity_name || '').trim() : null
        const label = typeof item.label === 'string' ? String(item.label || '').trim() : ''
        const view = typeof item.view === 'string' ? String(item.view || '').trim() : null
        const uri = typeof item.uri === 'string' ? String(item.uri || '').trim() : ''
        const assetId = typeof item.asset_id === 'number' ? item.asset_id : Number(item.asset_id || 0) || null
        const approved = typeof item.approved === 'boolean' ? Boolean(item.approved) : null
        return {
          id,
          role,
          entity_type: entityType,
          entity_id: entityId,
          entity_name: entityName,
          label: label || role,
          view,
          status,
          kind: 'image',
          uri: uri || null,
          asset_id: assetId,
          approved,
        } as DreamweaverLibraryPlanItem
      })
      .filter(Boolean) as DreamweaverLibraryPlanItem[]
  }, [])

  const applyDreamweaverEvent = useCallback(
    (event: DreamweaverEventRecord) => {
      if (!event || !event.run_id) return
      const activeRunId = activeRunIdRef.current
      if (!activeRunId || event.run_id !== activeRunId) return

      const eventId = typeof event.event_id === 'number' ? event.event_id : Number(event.event_id || 0)
      if (eventId && eventId <= eventCursorRef.current) return
      if (eventId) {
        eventCursorRef.current = eventId
        setEventCursor(eventId)
      }

      const eventType = String(event.event_type || '').trim()
      const stage = event.stage != null ? String(event.stage) : null
      const payload = event.payload || {}

      if (eventType === 'text_stream_start' || eventType === 'text_stream_delta' || eventType === 'text_stream_end') {
        const streamKeyRaw = typeof payload.stream_key === 'string' ? String(payload.stream_key || '').trim() : ''
        const streamKey = streamKeyRaw || stage || 'default'

        if (eventType === 'text_stream_start') {
          setStreamTextByKey((prev) => ({ ...prev, [streamKey]: '' }))
          setStreamMetaByKey((prev) => ({ ...prev, [streamKey]: { stage, done: false } }))
          return
        }

        if (eventType === 'text_stream_delta') {
          const chunk = typeof payload.chunk === 'string' ? String(payload.chunk || '') : ''
          if (chunk) {
            setStreamTextByKey((prev) => ({ ...prev, [streamKey]: (prev[streamKey] || '') + chunk }))
          }
          if (stage) {
            setStreamMetaByKey((prev) => ({ ...prev, [streamKey]: { stage, done: prev[streamKey]?.done } }))
          }
          return
        }

        if (eventType === 'text_stream_end') {
          setStreamMetaByKey((prev) => ({ ...prev, [streamKey]: { stage, done: true } }))
          return
        }
      }

      if (eventType === 'asset_library_plan') {
        const items = normalizeLibraryPlanItems(payload.items)
        if (items.length) {
          setLibraryPlanItems((prev) => {
            const map = new Map(prev.map((item) => [item.id, item]))
            for (const item of items) {
              const existing = map.get(item.id)
              if (existing) {
                map.set(item.id, {
                  ...existing,
                  ...item,
                  status: existing.status === 'done' ? 'done' : item.status,
                  uri: existing.uri || item.uri,
                })
              } else {
                map.set(item.id, item)
              }
            }
            return Array.from(map.values())
          })
        }
        return
      }

      if (eventType === 'asset_plan') {
        const items = normalizeAssetPlanItems(payload.items)
        if (items.length) {
          setAssetPlanItems((prev) => {
            const map = new Map(prev.map((item) => [item.id, item]))
            for (const item of items) {
              const existing = map.get(item.id)
              if (existing) {
                map.set(item.id, {
                  ...item,
                  status: existing.status === 'done' ? 'done' : item.status,
                  uri: existing.uri || item.uri,
                })
              } else {
                map.set(item.id, item)
              }
            }
            return Array.from(map.values())
          })
        }
        return
      }

      if (eventType === 'asset_ready') {
        const assetId = typeof payload.id === 'string' ? String(payload.id || '').trim() : ''
        if (!assetId) return
        const uri = typeof payload.uri === 'string' ? String(payload.uri || '').trim() : ''
        const role = typeof payload.role === 'string' ? String(payload.role || '').trim() : ''
        const kindRaw = typeof payload.kind === 'string' ? String(payload.kind || '').trim().toLowerCase() : ''
        const kind = kindRaw === 'video' ? 'video' : kindRaw === 'image' ? 'image' : role === 'video_clip' || role === 'merged_video' ? 'video' : 'image'

        setAssetPlanItems((prev) => {
          const map = new Map(prev.map((item) => [item.id, item]))
          const existing = map.get(assetId)
          const next: DreamweaverAssetPlanItem = {
            id: assetId,
            shot_id: payload.shot_id != null ? String(payload.shot_id) : existing?.shot_id ?? null,
            role: role || existing?.role || null,
            kind,
            label: existing?.label || assetId,
            status: 'done',
            uri: uri || existing?.uri || null,
          }
          map.set(assetId, { ...existing, ...next })
          return Array.from(map.values())
        })
        return
      }

      if (eventType === 'stage_start' || eventType === 'stage_progress' || eventType === 'stage_end') {
        applyStageSignal(stage, payload)
        return
      }

      if (eventType === 'run_error') {
        const err = typeof payload.error === 'string' ? String(payload.error || '').trim() : ''
        if (err) setError(err)
        setTaskStatus('failed')
        setRunning(false)
        setWaitingApproval(false)
      }
    },
    [applyStageSignal, normalizeAssetPlanItems, normalizeLibraryPlanItems],
  )

  const syncDreamweaverEvents = useCallback(
    async (runId: string) => {
      if (!runId) return
      if (eventSyncingRef.current) return
      eventSyncingRef.current = true
      setEventSyncing(true)
      setEventSyncError(null)

      try {
        let afterId = eventCursorRef.current
        let guard = 0
        while (guard < 6) {
          if (activeRunIdRef.current && activeRunIdRef.current !== runId) break
          const res = await apiClient.getDreamweaverRunEvents(runId, { after_id: afterId, limit: 200 })
          const rows = toDreamweaverEventRecords(res.data)
          if (!rows.length) break
          for (const row of rows) {
            applyDreamweaverEvent(row)
          }
          const maxId = rows.reduce((acc, item) => {
            const id = typeof item.event_id === 'number' ? item.event_id : Number(item.event_id || 0)
            return id > acc ? id : acc
          }, afterId)
          if (maxId > afterId) {
            afterId = maxId
            eventCursorRef.current = maxId
            setEventCursor(maxId)
          }
          if (rows.length < 200) break
          guard += 1
        }
      } catch (e: unknown) {
        if (isNotFoundError(e)) {
          if (shouldTreatRunNotFoundAsPending(taskId, taskStatus)) {
            setEventSyncError('事件尚未落库，稍后再试')
            return
          }
          resetMissingRunState(selectedProjectId)
        }
        setEventSyncError(await extractApiErrorMessage(e, '同步事件失败'))
      } finally {
        eventSyncingRef.current = false
        setEventSyncing(false)
      }
    },
    [applyDreamweaverEvent, resetMissingRunState, selectedProjectId, shouldTreatRunNotFoundAsPending, taskId, taskStatus],
  )

  const scriptDirty = scriptText !== scriptSavedText
  const waitingKind = (taskStage || taskState || '').toString().toLowerCase()
  const waitingScriptApproval = waitingApproval && waitingKind === DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL
  const waitingVideoConfirmation = waitingApproval && waitingKind === DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION
  const { persistedRunId, currentRunId } = useDreamweaverRunPersistence({
    selectedProjectId,
    taskRunId,
    resultRunId: result?.run_id || null,
    taskId,
    taskStatus,
    qualityMode: highQuality ? 'quality' : 'cost',
    qcAllowFail,
    smartTuning,
    videoRequireConfirmation,
    promptReviewRequired,
    stylePreset,
    imageRatio,
    imageResolution,
    selectedChapterIds,
  })
  const {
    snapshotContract,
    snapshotRuntimeConfig,
    diagnosticResult,
    diagnosticPreflight,
    diagnosticProviderTrace,
    diagnosticProviderTraceByShotId,
    diagnosticProviderTraceSummary,
  } = useDreamweaverDiagnostics({
    persistedRunId,
    result,
    runSnapshot,
    runPreflight,
  })
  const libraryApproved = Boolean(library?.review?.approved)

  useEffect(() => {
    autoLoadedLibraryRef.current = false
  }, [currentRunId])
  const videoClipJobs = useMemo(() => {
    return toDreamweaverVideoClipJobs(snapshotRuntimeConfig.video_clip_jobs)
  }, [snapshotRuntimeConfig.video_clip_jobs])
  const promptReviewRequiredSnapshot = Boolean(snapshotRuntimeConfig?.prompt_review_required)
  const promptReviewApproved = Boolean(
    (snapshotRuntimeConfig.prompt_review as Record<string, unknown> | null | undefined)?.approved,
  )
  const promptReviewReady = !promptReviewRequiredSnapshot || promptReviewApproved
  const canResumeFromScript =
    Boolean(currentRunId) && !scriptLoading && !resumeLoading && !scriptDirty && (!scriptRequiresReview || scriptApproved)
  const canResumeFromLibrary =
    Boolean(currentRunId) && !libraryLoading && !resumeLoading && libraryApproved && promptReviewReady

  useEffect(() => {
    if (!currentRunId) {
      activeRunIdRef.current = null
      resetDreamweaverEvents()
      return
    }
    if (activeRunIdRef.current === currentRunId) return
    activeRunIdRef.current = currentRunId
    resetDreamweaverEvents()
    void syncDreamweaverEvents(currentRunId)
  }, [currentRunId, resetDreamweaverEvents, syncDreamweaverEvents])

  useEffect(() => {
    if (!currentRunId) return
    if (!running) return
    const timer = window.setInterval(() => {
      if (eventSyncingRef.current) return
      void syncDreamweaverEvents(currentRunId)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [currentRunId, running, syncDreamweaverEvents])

  useEffect(() => {
    if (!selectedProjectId) return
    let active = true

    workflowWebSocket.setOnRoomJoined((joinedProjectId) => {
      if (!active) return
      if (joinedProjectId !== selectedProjectId) return
      if (activeRunIdRef.current) {
        void syncDreamweaverEvents(activeRunIdRef.current)
      }
    })

    workflowWebSocket.connect().then(() => {
      if (!active) return
      workflowWebSocket.joinProject(selectedProjectId)
    }).catch((error) => {
      setWsError(`WebSocket 连接失败: ${error instanceof Error ? error.message : String(error)}`)
    })

    workflowWebSocket.onDreamweaverEvent((data) => {
      applyDreamweaverEvent(data as DreamweaverEventRecord)
    })

    return () => {
      active = false
      workflowWebSocket.setOnRoomJoined(() => {})
      workflowWebSocket.removeEventListeners()
    }
  }, [applyDreamweaverEvent, selectedProjectId, syncDreamweaverEvents])

  const loadRunSnapshot = useCallback(async () => {
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.getDreamweaverRun(persistedRunId)
      const data = toDreamweaverRunSnapshot(res.data)
      setRunSnapshot(data)
      if (String(data?.status || '').trim().toLowerCase() === 'completed') {
        const nextResult = buildResultFromRunSnapshot(data, persistedRunId)
        if (nextResult) {
          setResult((prev) => mergeRunResult(prev, nextResult))
          if (nextResult.preflight) {
            setRunPreflight(nextResult.preflight)
          }
        }
      }
    } catch (e: unknown) {
      if (isNotFoundError(e)) {
        if (shouldTreatRunNotFoundAsPending(taskId, taskStatus)) {
          setRunSnapshotError('运行数据尚未落库，稍后自动重试')
          return
        }
        resetMissingRunState(selectedProjectId)
      }
      setRunSnapshotError(await extractApiErrorMessage(e, '加载运行快照失败'))
    } finally {
      setRunSnapshotLoading(false)
    }
  }, [persistedRunId, resetMissingRunState, selectedProjectId, shouldTreatRunNotFoundAsPending, taskId, taskStatus])

  const rebuildVideoJobs = useCallback(async () => {
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.rebuildDreamweaverVideoJobs(persistedRunId)
      const data = asObject(res.data)
      const jobs = Array.isArray(data?.video_clip_jobs) ? toDreamweaverVideoClipJobs(data.video_clip_jobs) : null
      if (!jobs) {
        await loadRunSnapshot()
        return
      }

      if (!runSnapshot) {
        await loadRunSnapshot()
        return
      }

      setRunSnapshot((prev) => withRunSnapshotVideoJobs(prev, jobs))
    } catch (e: unknown) {
      setRunSnapshotError(await extractApiErrorMessage(e, '刷新任务卡失败'))
    } finally {
      setRunSnapshotLoading(false)
    }
  }, [persistedRunId, loadRunSnapshot, runSnapshot])

  const loadMergedVideoPreview = useCallback(async () => {
    if (!currentRunId) {
      setMergedVideoError('缺少 run_id，无法加载合成视频')
      return
    }
    setMergedVideoLoading(true)
    setMergedVideoError(null)
    try {
      const res = await apiClient.getDreamweaverMergedVideoFile(currentRunId)
      const url = URL.createObjectURL(res.data)
      setMergedVideoPreviewUrl(url)
    } catch (e: unknown) {
      setMergedVideoError(await extractApiErrorMessage(e, '加载合成视频失败'))
    } finally {
      setMergedVideoLoading(false)
    }
  }, [currentRunId])

  const downloadMergedVideo = useCallback(async () => {
    if (!currentRunId) {
      setMergedVideoError('缺少 run_id，无法下载合成视频')
      return
    }
    setMergedVideoLoading(true)
    setMergedVideoError(null)
    try {
      const res = await apiClient.getDreamweaverMergedVideoFile(currentRunId)
      const url = URL.createObjectURL(res.data)
      const filename =
        (result?.merged_video ? String(result.merged_video).split(/[\\/]+/).pop() : '') ||
        `merged_${currentRunId}.mp4`
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      }, 0)
    } catch (e: unknown) {
      setMergedVideoError(await extractApiErrorMessage(e, '下载合成视频失败'))
    } finally {
      setMergedVideoLoading(false)
    }
  }, [currentRunId, result?.merged_video])

  const collectMergedVideo = useCallback(async () => {
    if (!currentRunId) {
      setMergedVideoCollectFeedback({ type: 'error', text: '缺少 run_id，无法归档合成视频' })
      return
    }

    const mergedPath =
      result?.merged_video ||
      (runSnapshot?.contract && typeof runSnapshot.contract === 'object'
        ? extractMergedVideoFromContract(runSnapshot.contract as Record<string, unknown>)
        : null)

    setMergedVideoCollecting(true)
    setMergedVideoCollectFeedback(null)

    try {
      await apiClient.createUserAsset({
        project_id: selectedProjectId,
        source_module: 'dreamweaver_run',
        asset_kind: 'video',
        asset_class: 'deliverable',
        title: `${selectedProject?.title || '短剧项目'} 合成视频`,
        description: 'DreamWeaver 最终合成成片归档',
        file_url: buildProtectedMergedVideoUrl(currentRunId),
        preview_url: buildProtectedMergedVideoUrl(currentRunId),
        generation_mode: 'merged_video',
        tags: ['dreamweaver', 'deliverable', 'merged-video'],
        metadata_json: {
          run_id: currentRunId,
          project_id: selectedProjectId,
          project_title: selectedProject?.title || null,
          merged_video_path: mergedPath,
        },
        source_payload_json: {
          run_id: currentRunId,
          project_id: selectedProjectId,
          type: 'merged_video',
          path: mergedPath,
        },
      })
      setMergedVideoCollectFeedback({ type: 'success', text: '合成视频已归档到用户中心' })
    } catch (collectError) {
      setMergedVideoCollectFeedback({
        type: 'error',
        text: await extractApiErrorMessage(collectError, '归档合成视频失败'),
      })
    } finally {
      setMergedVideoCollecting(false)
    }
  }, [currentRunId, result?.merged_video, runSnapshot, selectedProject?.title, selectedProjectId])

  const renderMergedVideoPanel = useCallback(
    (options?: { centeredPreview?: boolean }) => (
      <>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
          <Button
            size="small"
            variant="outlined"
            onClick={loadMergedVideoPreview}
            disabled={!currentRunId || mergedVideoLoading}
          >
            {mergedVideoLoading ? '加载中…' : mergedVideoPreviewUrl ? '重新加载合成视频' : '加载合成视频预览'}
          </Button>
          <Button
            size="small"
            variant="contained"
            onClick={downloadMergedVideo}
            disabled={!currentRunId || mergedVideoLoading}
          >
            下载合成视频
          </Button>
          <Button
            size="small"
            variant="outlined"
            onClick={() => void collectMergedVideo()}
            disabled={!currentRunId || mergedVideoCollecting}
          >
            {mergedVideoCollecting ? '归档中…' : '归档到用户中心'}
          </Button>
        </Stack>
        {mergedVideoCollectFeedback && (
          <Alert severity={mergedVideoCollectFeedback.type} sx={{ mt: 1 }}>
            {mergedVideoCollectFeedback.text}
          </Alert>
        )}
        {mergedVideoError && (
          <Alert severity="error" sx={{ mt: 1 }}>
            {mergedVideoError}
          </Alert>
        )}
        {mergedVideoPreviewUrl && (
          <Box
            sx={{
              mt: 1,
              bgcolor: '#000',
              borderRadius: 2,
              overflow: 'hidden',
              ...(options?.centeredPreview
                ? {
                    mx: 'auto',
                    width: '100%',
                    maxWidth: mergedVideoPreviewPortrait ? 360 : 720,
                  }
                : {}),
            }}
          >
            <Box component="video" src={mergedVideoPreviewUrl} controls sx={{ width: '100%', display: 'block' }} />
          </Box>
        )}
      </>
    ),
    [
      collectMergedVideo,
      currentRunId,
      downloadMergedVideo,
      loadMergedVideoPreview,
      mergedVideoCollectFeedback,
      mergedVideoCollecting,
      mergedVideoError,
      mergedVideoLoading,
      mergedVideoPreviewPortrait,
      mergedVideoPreviewUrl,
    ],
  )

  const loadRunAssetPreview = useCallback(
    async (uri: string) => {
      const targetUri = String(uri || '').trim()
      if (!targetUri) return
      if (!currentRunId) {
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: '缺少 run_id，无法加载产物预览' }))
        return
      }

      setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: true }))
      setRunAssetPreviewErrors((prev) => {
        const next = { ...prev }
        delete next[targetUri]
        return next
      })
      try {
        const res = await apiClient.getDreamweaverRunAssetFile(currentRunId, targetUri)
        const url = URL.createObjectURL(res.data)
        setRunAssetPreviews((prev) => {
          const existed = prev[targetUri]
          if (existed) {
            try {
              URL.revokeObjectURL(existed)
            } catch {
              // ignore
            }
          }
          return { ...prev, [targetUri]: url }
        })
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '加载产物预览失败')
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: msg }))
      } finally {
        setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: false }))
      }
    },
    [currentRunId],
  )

  const downloadRunAsset = useCallback(
    async (uri: string) => {
      const targetUri = String(uri || '').trim()
      if (!targetUri) return
      if (!currentRunId) {
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: '缺少 run_id，无法下载产物' }))
        return
      }

      setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: true }))
      try {
        const res = await apiClient.getDreamweaverRunAssetFile(currentRunId, targetUri)
        const url = URL.createObjectURL(res.data)
        const filename = targetUri.split(/[\\/]+/).pop() || `asset_${currentRunId}`
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => {
          try {
            URL.revokeObjectURL(url)
          } catch {
            // ignore
          }
        }, 0)
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '下载产物失败')
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: msg }))
      } finally {
        setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: false }))
      }
    },
    [currentRunId],
  )

  const loadScript = useCallback(async () => {
    if (!currentRunId) return
    setScriptLoading(true)
    setScriptError(null)
    try {
      const res = await apiClient.getDreamweaverRunScript(currentRunId)
      const data = asObject(res.data) || {}
      const text = typeof data?.script_text === 'string' ? data.script_text : ''
      const scriptReview = asObject(data?.script_review)
      const scriptGeneration =
        data?.script_generation && typeof data.script_generation === 'object' && !Array.isArray(data.script_generation)
          ? (data.script_generation as ScriptGeneration)
          : null
      setScriptText(text)
      setScriptSavedText(text)
      setScriptApproved(Boolean(scriptReview?.approved))
      setScriptRequiresReview(Boolean(data?.script_requires_review))
      setScriptEntities(toDreamweaverScriptEntities(data?.script_entities))
      setScriptGeneration(scriptGeneration)
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, '加载剧本失败'))
    } finally {
      setScriptLoading(false)
    }
  }, [currentRunId])

  useEffect(() => {
    if (!waitingScriptApproval) return
    if (!currentRunId) return
    if (scriptLoading) return
    if (scriptText.trim()) return
    if (autoLoadedScriptRunIdRef.current === currentRunId) return
    autoLoadedScriptRunIdRef.current = currentRunId
    void loadScript()
  }, [currentRunId, loadScript, scriptLoading, scriptText, waitingScriptApproval])

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

  const saveScript = async () => {
    if (!currentRunId) return
    if (!scriptText.trim()) {
      setScriptError('剧本不能为空')
      return
    }
    setScriptLoading(true)
    setScriptError(null)
    try {
      await apiClient.updateDreamweaverRunScript(currentRunId, { script_text: scriptText })
      await loadScript()
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, '保存剧本失败'))
    } finally {
      setScriptLoading(false)
    }
  }

  const approveScript = async (approved: boolean) => {
    if (!currentRunId) return
    setScriptLoading(true)
    setScriptError(null)
    try {
      await apiClient.approveDreamweaverRunScript(currentRunId, { approved })
      await loadScript()
    } catch (e: unknown) {
      setScriptError(await extractApiErrorMessage(e, '更新剧本审核状态失败'))
    } finally {
      setScriptLoading(false)
    }
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

  const openPromptEditDialog = (shot: DreamweaverShotSnapshot) => {
    const head = getShotFramePrompt(shot.head_frame)
    const tail = getShotFramePrompt(shot.tail_frame)
    const videoOverride = getShotVideoPromptOverride(shot)
    setPromptEditShot(shot)
    setPromptEditHead(head)
    setPromptEditTail(tail)
    setPromptEditVideo(videoOverride)
    setPromptEditError(null)
    setPromptEditOpen(true)
  }

  const savePromptEdit = async () => {
    if (!currentRunId || !promptEditShot) return
    const shotId = getShotId(promptEditShot)
    if (!shotId) {
      setPromptEditError('缺少 shot_id，无法保存')
      return
    }
    const head = promptEditHead.trim()
    const tail = promptEditTail.trim()
    if (!head || !tail) {
      setPromptEditError('首帧/尾帧提示词不能为空')
      return
    }

    const originHead = getShotFramePrompt(promptEditShot.head_frame)
    const originTail = getShotFramePrompt(promptEditShot.tail_frame)
    const originVideo = getShotVideoPromptOverride(promptEditShot)
    const nextVideo = promptEditVideo.trim()

    const tasks: Promise<any>[] = []
    if (head !== originHead) {
      tasks.push(apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, shotId, 'head', head))
    }
    if (tail !== originTail) {
      tasks.push(apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, shotId, 'tail', tail))
    }
    if (nextVideo !== originVideo) {
      tasks.push(apiClient.updateDreamweaverRunShotVideoPrompt(currentRunId, shotId, nextVideo))
    }
    if (!tasks.length) {
      setPromptEditOpen(false)
      return
    }

    setPromptEditSaving(true)
    setPromptEditError(null)
    try {
      await Promise.all(tasks)
      await loadRunSnapshot()
      setPromptEditOpen(false)
    } catch (e: unknown) {
      setPromptEditError(await extractApiErrorMessage(e, '提示词保存失败'))
    } finally {
      setPromptEditSaving(false)
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
      const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data.review.missing_roles as string[]) : []
      const scopedMissingRoleSet = new Set(missingRoles.map((role) => String(role || '').trim()).filter(Boolean))
      const previewEntries = await Promise.all(
        assets
          .filter((asset) => hasRenderableLibraryImage(asset, { missingRoleSet: scopedMissingRoleSet }))
          .map(async (asset) => {
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
      const previewMap: Record<number, string> = {}
      const previewErrorMap: Record<number, string> = {}
      for (const entry of previewEntries) {
        if (entry.url) previewMap[entry.id] = entry.url
        if (entry.error) previewErrorMap[entry.id] = entry.error
      }
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

  const regenerateLibraryAsset = async (options: {
    role: string
    prompt?: string
    run_id?: string
    prefer_image_edit?: boolean
    prefer_view_chain_edit_base?: boolean
  }): Promise<string | null> => {
    const role = String(options.role || '').trim()
    if (!role) return 'missing asset role'
    if (!selectedProjectId) return 'project not selected'
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.regenerateDreamweaverLibraryAsset(selectedProjectId, {
        role,
        ...(options.run_id ? { run_id: options.run_id } : {}),
        ...(options.prompt ? { prompt: options.prompt } : {}),
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
  }

  const loadLibraryPreview = async (asset: LibraryAsset, options?: { force?: boolean }): Promise<void> => {
    if (!asset?.id) return
    if (!hasRenderableLibraryImage(asset, { missingRoleSet })) {
      setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: '素材为占位/缺失，暂无可预览图片' }))
      return
    }
    if (!options?.force && libraryPreviews[asset.id]) return
    setLibraryPreviewLoading((prev) => ({ ...prev, [asset.id]: true }))
    setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: '' }))
    try {
      const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
      const url = URL.createObjectURL(fileRes.data)
      setLibraryPreviews((prev) => ({ ...prev, [asset.id]: url }))
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, '加载预览失败')
      setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: message }))
    } finally {
      setLibraryPreviewLoading((prev) => ({ ...prev, [asset.id]: false }))
    }
  }

  const suggestRegeneratePrompt = useCallback(
    async (options: {
      role: string
      prompt?: string
      mode?: 'template' | 'ai'
      source?: 'auto' | 'manual'
      preferViewChainSeed?: boolean
    }): Promise<string | null> => {
      const role = String(options.role || '').trim()
      if (!selectedProjectId || !role) return null
      setRegenSuggesting(true)
      setRegenSuggestError(null)
      try {
        const res = await apiClient.suggestDreamweaverLibraryPrompt(selectedProjectId, {
          role,
          ...(currentRunId ? { run_id: currentRunId } : {}),
          ...(options.prompt ? { prompt: options.prompt } : {}),
          ...(options.preferViewChainSeed ? { prefer_view_chain_seed: true } : {}),
          mode: options.mode || 'template',
        })
        const nextPrompt = String(res.data?.prompt || '').trim()
        if (nextPrompt) {
          setRegenPrompt(nextPrompt)
          if (options.preferViewChainSeed) setRegenSmartPromptTriggered(true)
          if ((options.source || 'manual') === 'auto') {
            setRegenPromptInitial(nextPrompt)
            setRegenPromptDirty(false)
          } else {
            setRegenPromptDirty(nextPrompt.trim() !== regenPromptInitial.trim())
          }
          return nextPrompt
        }
        return null
      } catch (e: unknown) {
        const message = await extractApiErrorMessage(e, '生成提示词失败')
        setRegenSuggestError(message)
        return null
      } finally {
        setRegenSuggesting(false)
      }
    },
    [currentRunId, regenPromptInitial, selectedProjectId],
  )

  const requestSmartRegeneratePrompt = useCallback(
    (options?: { role?: string; source?: 'auto' | 'manual' }) => {
      const role = String(options?.role || regenRole || '').trim()
      if (!role) return
      const parsed = parseLibraryRole(role)
      const preferViewChainSeed = parsed.entityType === 'character' && Boolean(parsed.view) && parsed.view !== 'front'
      if (preferViewChainSeed) setRegenSmartPromptTriggered(true)
      void suggestRegeneratePrompt({
        role,
        mode: 'template',
        source: options?.source || 'manual',
        preferViewChainSeed,
      })
    },
    [regenRole, suggestRegeneratePrompt],
  )

  const openRegenerateDialogForRole = (roleInput: string, titleInput?: string, promptInput?: string) => {
    const role = String(roleInput || '').trim()
    if (!role) return
    const roleAsset = libraryAssetsByRole.get(role) || null
    const title = String(titleInput || role).trim() || role
    const prompt = String(promptInput || roleAsset?.meta?.prompt || roleAsset?.meta?.suggested_prompt || '').trim()
    const viewChainPlan = resolveCharacterViewChainPlan(role)
    const hasCurrentImage = hasRenderableLibraryImage(roleAsset, { missingRoleSet })
    const imageEditPref = Boolean(viewChainPlan.forceImageEdit)
    const shouldAutoClearForImageEdit = imageEditPref && hasCurrentImage
    const initialPrompt = shouldAutoClearForImageEdit ? '' : prompt
    setRegenRole(role)
    setRegenTitle(title)
    setRegenPrompt(initialPrompt)
    setRegenPromptInitial(initialPrompt)
    setRegenPromptTemplateSnapshot(prompt)
    setRegenImageEditAutoCleared(shouldAutoClearForImageEdit)
    setRegenPromptDirty(false)
    setRegenPreferImageEdit(imageEditPref)
    setRegenSmartPromptTriggered(false)
    setRegenSuggesting(false)
    setRegenSuggestError(null)
    setRegenError(null)
    setRegenOpen(true)
    if (!hasCurrentImage) {
      requestSmartRegeneratePrompt({ role, source: 'auto' })
    }
  }

  const openRegenerateDialog = (asset: LibraryAsset) => {
    const role = String(asset.role || '').trim()
    if (!role) return
    const title = String(asset.meta?.entity_name || asset.role || '').trim() || role
    const prompt = String(asset.meta?.prompt || '').trim()
    openRegenerateDialogForRole(role, title, prompt)
  }

  const submitRegenerateDialog = async () => {
    const role = String(regenRole || '').trim()
    if (!role || !selectedProjectId) return
    setRegenSubmitting(true)
    setRegenError(null)
    try {
      const promptText = regenPrompt.trim()
      if (regenImageEditActive && regenImageEditAutoCleared && !promptText) {
        setRegenError('图像编辑模式下请填写“修改要求”（基于参考原图需要修改的内容）')
        return
      }
      const shouldSendPrompt = regenImageEditActive ? true : Boolean(regenPromptDirty && promptText)
      const err = await regenerateLibraryAsset({
        role,
        ...(shouldSendPrompt ? { prompt: promptText } : {}),
        run_id: currentRunId || undefined,
        prefer_image_edit: regenForceImageEdit || (regenPreferImageEdit && regenHasImageBase),
        ...(regenForceViewChainEditBase ? { prefer_view_chain_edit_base: true } : {}),
      })
      if (err) {
        setRegenError(err)
        return
      }
      setRegenOpen(false)
    } finally {
      setRegenSubmitting(false)
    }
  }

  const toggleRegenImageEditPreference = () => {
    if (regenForceImageEdit || !regenHasImageBase) return
    if (regenPreferImageEdit) {
      const restore = String(regenPromptTemplateSnapshot || '').trim()
      setRegenPreferImageEdit(false)
      setRegenImageEditAutoCleared(false)
      setRegenPrompt(restore)
      setRegenPromptInitial(restore)
      setRegenPromptDirty(false)
      return
    }
    const snapshot = String(regenPrompt || regenPromptInitial || regenPromptTemplateSnapshot || '').trim()
    setRegenPromptTemplateSnapshot(snapshot)
    setRegenPreferImageEdit(true)
    if (regenHasCurrentImage) {
      setRegenImageEditAutoCleared(true)
      setRegenPrompt('')
      setRegenPromptInitial('')
    } else {
      // 首次生成（当前无图）保留模板提示词，避免被强制清空。
      setRegenImageEditAutoCleared(false)
    }
    setRegenPromptDirty(false)
  }

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

    const normalizedShotIds = Array.isArray(shotIds)
      ? shotIds
          .map((s) => String(s || '').trim())
          .filter((s) => s)
          .filter((s, idx, arr) => arr.indexOf(s) === idx)
          .slice(0, 200)
      : []

    const normalizedCamIdxs = Array.isArray(camIdxs)
      ? camIdxs
          .map((n) => Number(n))
          .filter((n) => Number.isFinite(n))
          .map((n) => Math.trunc(n))
          .filter((n, idx, arr) => arr.indexOf(n) === idx)
          .slice(0, 200)
      : []

    if (normalizedShotIds.length > 0 && normalizedCamIdxs.length > 0) {
      setError('shot_id 与 cam_idx 不能同时使用')
      return
    }

    if (
      (normalizedShotIds.length > 0 || normalizedCamIdxs.length > 0) &&
      !['KEYFRAMES', 'MIDFRAMES', 'VIDEO'].includes(startStateRaw)
    ) {
      setError('镜头/相机级局部重跑仅支持 KEYFRAMES/MIDFRAMES/VIDEO 阶段')
      return
    }

    const partialHint =
      normalizedShotIds.length > 0
        ? `\n\n镜头：${normalizedShotIds.slice(0, 6).join(', ')}${normalizedShotIds.length > 6 ? '…' : ''}\n（仅重跑这些镜头，其余镜头将复用历史产物；仍会重新合成下游成片）`
        : normalizedCamIdxs.length > 0
          ? `\n\n相机：${normalizedCamIdxs.join(', ')}\n（仅重跑这些相机的镜头，其余镜头将复用历史产物；仍会重新合成下游成片）`
          : ''

    const ok = window.confirm(
      `将从 ${startStateRaw} 开始重跑，并清理该阶段及其下游产物（覆盖式重跑，可能产生额外调用/成本）。${partialHint}\n\n确认继续？`,
    )
    if (!ok) return

    setError(null)
    setLibraryError(null)
    setRestartLoading(true)
    setRestartAnchorEl(null)
    setTaskQueue(null)
    setRunning(true)
    setWaitingApproval(false)
    setTaskStatus('queued')
    setTaskProgress(0)
    setTaskState(startStateRaw)
    setTaskStage(null)
    setTaskArtifacts(null)
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
    setLibrary(null)
    clearLibraryPreviews()
    setLibraryPlanItems([])
    clearRunAssetPreviews()

    try {
      const missingRoleCount = Array.isArray(library?.review?.missing_roles) ? library.review.missing_roles.length : 0
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
      setRunning(false)
      setTaskStatus(null)
      setWaitingApproval(false)
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

  const scriptGenerationLabel = useMemo(() => {
    const mode = (scriptGeneration?.mode || '').toString()
    const model = scriptGeneration?.model ? String(scriptGeneration.model) : ''
    if (!mode) return null
    if (mode === 'llm') return model ? `LLM（${model}）` : 'LLM'
    if (mode === 'rule_fallback') return '规则回退'
    if (mode === 'rule') return '规则'
    if (mode === 'manual') return '手动编辑'
    return mode
  }, [scriptGeneration?.mode, scriptGeneration?.model])

  const streamSnapshots = useMemo(() => {
    return {
      plan: streamTextByKey.plan || '',
      script: streamTextByKey.script || '',
      scriptEnhance: streamTextByKey.script_enhance || '',
      characterProfiles: streamTextByKey.character_profiles || '',
      audioMarkers: streamTextByKey.audio_markers || '',
      storyboard: streamTextByKey.storyboard || '',
      cameraTree: streamTextByKey.camera_tree || '',
    }
  }, [streamTextByKey])

  const activeStreamKeys = useMemo(() => {
    return Object.entries(streamMetaByKey)
      .filter(([, meta]) => meta && !meta.done)
      .map(([key]) => key)
  }, [streamMetaByKey])

  const snapshotShots = useMemo(() => {
    const episodes = runSnapshot?.contract?.episodes
    if (!Array.isArray(episodes)) return []
    const shots: DreamweaverShotSnapshot[] = []
    for (const ep of episodes) {
      if (!ep || typeof ep !== 'object' || Array.isArray(ep)) continue
      const epShots = (ep as Record<string, unknown>).shots
      shots.push(...toDreamweaverShotSnapshots(epShots))
    }
    return shots
  }, [runSnapshot])

  const safetyBlockedShots = useMemo(() => {
    const results: Array<{ shotId: string; shotIndex?: number; roles: string[]; errorSample: string }> = []
    const pattern = /datainspectionfailed|inappropriate content|content check failed/i
    for (const shot of snapshotShots) {
      const shotId = getShotId(shot)
      if (!shotId) continue
      const roles = new Set<string>()
      let errorSample = ''
      const assets = getShotAssets(shot)
      for (const asset of assets) {
        const meta = asset.meta && typeof asset.meta === 'object' && !Array.isArray(asset.meta) ? asset.meta : {}
        const safetyError = typeof meta.safety_error === 'string' ? meta.safety_error : ''
        const errorText = typeof meta.error === 'string' ? meta.error : ''
        const messageText = typeof meta.message === 'string' ? meta.message : ''
        const combined = [safetyError, errorText, messageText].filter((v) => v && v.trim()).join(' | ')
        const isBlocked = Boolean(meta.safety_blocked) || (combined && pattern.test(combined))
        if (!isBlocked) continue
        const role = String(asset.role || '').trim()
        if (role) roles.add(role)
        if (!errorSample && combined) errorSample = combined
      }
      if (!roles.size) continue
      results.push({
        shotId,
        shotIndex: typeof shot.shot_index === 'number' ? shot.shot_index : undefined,
        roles: Array.from(roles),
        errorSample,
      })
    }
    return results
  }, [snapshotShots])

  const snapshotShotById = useMemo(() => {
    const map = new Map<string, DreamweaverShotSnapshot>()
    for (const shot of snapshotShots) {
      const id = getShotId(shot)
      if (!id) continue
      map.set(id, shot)
    }
    return map
  }, [snapshotShots])

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

  const promptReviewShots = useMemo(() => {
    return promptReviewShowAll ? snapshotShots : snapshotShots.slice(0, 12)
  }, [promptReviewShowAll, snapshotShots])

  const snapshotAssetCount = useMemo(() => {
    return snapshotShots.reduce((acc, shot) => {
      return acc + getShotAssets(shot).length
    }, 0)
  }, [snapshotShots])

  const libraryPromptReviewMessage = libraryApproved
    ? promptReviewReady
      ? '素材库已通过，提示词已确认：可继续生成进入镜头阶段。'
      : '素材库已通过，但提示词待确认：请先完成提示词审核。'
    : promptReviewRequiredSnapshot
      ? '素材库待审核：通过后还需确认提示词，才能继续生成。'
      : '素材库待审核：通过后可继续生成。'

  const snapshotCameraDiagnostics = useMemo<{
    generation: Record<string, unknown> | null
    cameraTree: unknown[] | null
    cameraStates: unknown[] | null
    cameraScenes: unknown[] | null
    sceneUris: string[]
    mode: string | null
  }>(() => {
    const generation = asObject(snapshotRuntimeConfig?.camera_tree_generation)
    const cameraTree = Array.isArray(snapshotRuntimeConfig?.camera_tree) ? snapshotRuntimeConfig.camera_tree : null
    const cameraStates = Array.isArray(snapshotRuntimeConfig?.camera_states) ? snapshotRuntimeConfig.camera_states : null
    const cameraScenes = Array.isArray(snapshotRuntimeConfig?.camera_scenes) ? snapshotRuntimeConfig.camera_scenes : null
    const sceneUris = (cameraScenes || [])
      .map((item) => {
        const record = asObject(item)
        return typeof record?.scene_uri === 'string' ? String(record.scene_uri || '').trim() : ''
      })
      .filter((item): item is string => Boolean(item))
    const mode = typeof generation?.mode === 'string' ? String(generation.mode) : null
    return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
  }, [snapshotRuntimeConfig])

  const snapshotTelemetry = useMemo(() => {
    return asObject(snapshotRuntimeConfig?.telemetry)
  }, [snapshotRuntimeConfig])

  const snapshotTelemetrySummary = useMemo(() => {
    if (!snapshotTelemetry) return null

    const startedAt = typeof snapshotTelemetry.run_started_at === 'number' ? Number(snapshotTelemetry.run_started_at) : null
    const finishedAt = typeof snapshotTelemetry.run_finished_at === 'number' ? Number(snapshotTelemetry.run_finished_at) : null
    const totalS = startedAt != null && finishedAt != null && finishedAt >= startedAt ? finishedAt - startedAt : null

    const terminalState = typeof snapshotTelemetry.terminal_state === 'string' ? String(snapshotTelemetry.terminal_state) : null
    const reworkCount = typeof snapshotTelemetry.rework_count === 'number' ? Number(snapshotTelemetry.rework_count) : null
    const reworkByType = asObject(snapshotTelemetry.rework_by_type)
    const stagesRaw = asObject(snapshotTelemetry.stages) || {}
    const stageOrder = ['init', 'script', 'storyboard', 'asset_library', 'keyframes', 'midframes', 'video', 'edit', 'review']
    const stageEntries = Object.entries(stagesRaw)
      .map(([stage, value]) => {
        const item = asObject(value) || {}
        const total = typeof item.total_s === 'number' ? Number(item.total_s) : null
        const calls = typeof item.calls === 'number' ? Number(item.calls) : 0
        const failure = typeof item.failure === 'number' ? Number(item.failure) : 0
        return { stage: String(stage), totalS: total, calls, failure }
      })
      .filter((it) => typeof it.totalS === 'number' && Number.isFinite(it.totalS) && it.totalS >= 0)
      .sort((a, b) => {
        const ia = stageOrder.indexOf(a.stage)
        const ib = stageOrder.indexOf(b.stage)
        if (ia === -1 && ib === -1) return a.stage.localeCompare(b.stage)
        if (ia === -1) return 1
        if (ib === -1) return -1
        return ia - ib
      })

    return {
      startedAt,
      finishedAt,
      totalS,
      terminalState,
      reworkCount,
      reworkByType,
      stageEntries,
    }
  }, [snapshotTelemetry])

  const snapshotTelemetryCounters = useMemo(() => {
    const raw = asObject(snapshotTelemetry?.counters)
    if (!raw) return []

    const entries: { name: string; value: number }[] = []
    for (const [name, value] of Object.entries(raw)) {
      const key = String(name || '').trim()
      if (!key) continue
      if (typeof value === 'number' && Number.isFinite(value)) {
        entries.push({ name: key, value: Number(value) })
      } else if (typeof value === 'string' && value.trim()) {
        const parsed = Number(value)
        if (Number.isFinite(parsed)) entries.push({ name: key, value: parsed })
      }
      if (entries.length >= 200) break
    }

    const valueByName = new Map(entries.map((it) => [it.name, it.value]))
    const vlmTotalCalls =
      Number(valueByName.get('vlm_text_prefilter_calls') || 0) +
      Number(valueByName.get('vlm_rewrite_t2i_calls') || 0) +
      Number(valueByName.get('vlm_edit_prompt_calls') || 0) +
      Number(valueByName.get('vlm_analyze_image_calls') || 0) +
      Number(valueByName.get('vlm_semantic_selector_calls') || 0)
    if (vlmTotalCalls > 0 && !valueByName.has('vlm_total_calls')) entries.push({ name: 'vlm_total_calls', value: vlmTotalCalls })

    const preferredOrder = [
      'vlm_total_calls',
      'vlm_text_prefilter_calls',
      'vlm_rewrite_t2i_calls',
      'vlm_edit_prompt_calls',
      'vlm_analyze_image_calls',
      'vlm_analyze_image_images',
      'vlm_semantic_selector_calls',
      'vlm_semantic_selector_images',
      'vlm_edit_prompt_calls_head',
      'vlm_edit_prompt_calls_tail',
      'vlm_edit_prompt_calls_mid',
      'vlm_edit_prompt_images',
      'vlm_rewrite_t2i_ref_images',
      'semantic_retrieval_queries',
      'semantic_retrieval_hits',
      't2i_generate_calls',
      't2i_cache_hits',
      't2i_cache_misses',
      'image_edit_generate_calls',
      'image_edit_cache_hits',
      'image_edit_cache_misses',
      'multiperson_fusion_attempts',
      'multiperson_fusion_success',
      'multiperson_fusion_failed',
      'multiperson_fusion_skipped',
      'multiperson_fusion_steps',
    ]
    const rank = new Map(preferredOrder.map((k, idx) => [k, idx]))
    entries.sort((a, b) => {
      const ra = rank.has(a.name) ? Number(rank.get(a.name)) : preferredOrder.length
      const rb = rank.has(b.name) ? Number(rank.get(b.name)) : preferredOrder.length
      if (ra !== rb) return ra - rb
      if (a.name === b.name) return 0
      return a.name.localeCompare(b.name)
    })
    return entries
  }, [snapshotTelemetry])

  const snapshotPlanText = useMemo(() => {
    const plan = asObject(snapshotRuntimeConfig?.plan)
    if (typeof plan?.text === 'string') return String(plan.text)
    if (typeof snapshotRuntimeConfig?.plan_text === 'string' && snapshotRuntimeConfig.plan_text.trim()) return snapshotRuntimeConfig.plan_text.trim()
    return ''
  }, [snapshotRuntimeConfig])

  const snapshotScriptText = useMemo(() => {
    return typeof snapshotRuntimeConfig?.script_text === 'string' ? snapshotRuntimeConfig.script_text : ''
  }, [snapshotRuntimeConfig])

  const snapshotScriptApproved = useMemo(() => {
    const review = asObject(snapshotRuntimeConfig?.script_review)
    return Boolean(review?.approved)
  }, [snapshotRuntimeConfig])

  const snapshotScriptEntities = useMemo(() => {
    return toDreamweaverScriptEntities(snapshotRuntimeConfig?.script_entities)
  }, [snapshotRuntimeConfig])

  const snapshotScriptGeneration = useMemo(() => {
    const generation = snapshotRuntimeConfig?.script_generation
    return generation && typeof generation === 'object' && !Array.isArray(generation) ? (generation as ScriptGeneration) : null
  }, [snapshotRuntimeConfig])

  const snapshotCharacterProfiles = useMemo(() => {
    const profiles = snapshotRuntimeConfig?.character_profiles
    return Array.isArray(profiles) ? profiles : []
  }, [snapshotRuntimeConfig])

  const snapshotAudioMarkers = useMemo(() => {
    const markers = snapshotRuntimeConfig?.audio_markers
    return Array.isArray(markers) ? markers : []
  }, [snapshotRuntimeConfig])

  const snapshotMergedVideo = useMemo(() => {
    return snapshotContract ? extractMergedVideoFromContract(snapshotContract) : null
  }, [snapshotContract])

  const snapshotAssetSummary = useMemo(() => {
    const keyframes: string[] = []
    const midframes: string[] = []
    const videoClips: Array<{ path: string; meta: Record<string, unknown> }> = []
    for (const shot of snapshotShots) {
      const assets = getShotAssets(shot)
      for (const asset of assets) {
        const role = String(asset.role || '')
        const uri = asset.uri
        if (typeof uri !== 'string' || !uri.trim()) continue
        const meta = asObject(asset.meta) || {}

        if (role === 'head_frame' || role === 'tail_frame') keyframes.push(uri)
        else if (role === 'mid_frame') midframes.push(uri)
        else if (role === 'video_clip') videoClips.push({ path: uri, meta })
      }
    }
    return { keyframes, midframes, videoClips }
  }, [snapshotShots])

  const assetPlanSummary = useMemo(() => {
    const total = assetPlanItems.length
    let done = 0
    let planned = 0
    let images = 0
    let videos = 0
    for (const item of assetPlanItems) {
      if (item.kind === 'video') videos += 1
      else images += 1
      if (item.status === 'done' || item.uri) done += 1
      else planned += 1
    }
    return { total, done, planned, images, videos }
  }, [assetPlanItems])

  const mergedVideoPlan = useMemo(() => {
    return assetPlanItems.find((item) => item.id === 'merged_video') || null
  }, [assetPlanItems])

  const libraryDisplayItems = useMemo<LibraryDisplayItem[]>(() => {
    const assets = Array.isArray(library?.assets) ? (library?.assets as LibraryAsset[]) : []
    const normalizedMissingRoles = Array.from(missingRoleSet.values())
    const characterNameById = new Map<number, string>()
    const rememberCharacterName = (entityIdRaw: unknown, nameRaw: unknown) => {
      const entityId = Number.parseInt(String(entityIdRaw ?? ''), 10)
      const name = String(nameRaw || '').trim()
      if (!Number.isFinite(entityId) || entityId <= 0 || isPlaceholderEntityName(name)) return
      const prev = characterNameById.get(entityId)
      if (!prev || isPlaceholderEntityName(prev)) {
        characterNameById.set(entityId, name)
      }
    }
    const specCharacters = Array.isArray(library?.spec?.characters) ? library.spec.characters : []
    for (const rawItem of specCharacters) {
      const item = asObject(rawItem)
      if (!item) continue
      rememberCharacterName(item.entity_id, item.name)
    }
    for (const plan of libraryPlanItems) {
      if (String(plan?.entity_type || '').trim().toLowerCase() !== 'character') continue
      rememberCharacterName(plan?.entity_id, plan?.entity_name)
    }
    const assetsByRole = new Map<string, LibraryAsset>()
    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role) continue
      assetsByRole.set(role, asset)
      const parsed = parseLibraryRole(role)
      if (parsed.entityType === 'character' && parsed.entityId) {
        rememberCharacterName(parsed.entityId, asset?.meta?.entity_name)
      }
    }

    const normalizeRole = (rawRole: string) => {
      const role = String(rawRole || '').trim()
      const parsed = parseLibraryRole(role)
      let group: LibraryDisplayItem['group'] = 'other'
      let view: LibraryDisplayItem['view'] = null
      if (parsed.entityType === 'character') {
        group = 'character'
        view = parsed.view || null
      } else if (parsed.entityType === 'scene') {
        group = 'scene'
      } else if (parsed.entityType === 'prop') {
        group = 'prop'
      }
      const viewRank = view ? CHARACTER_VIEW_RANK[view] : 99
      const viewLabel = view ? characterViewLabel(view) : ''
      return { role, group, view, viewRank, viewLabel }
    }

    const formatTitle = (rawTitle: string, role: string, viewLabel: string) => {
      const parsed = parseLibraryRole(role)
      const raw = String(rawTitle || '').trim()
      let base = raw || role
      if (parsed.entityType === 'character' && parsed.entityId) {
        const mapped = characterNameById.get(parsed.entityId) || ''
        const fallbackCharacterName = mapped || `角色#${parsed.entityId}`
        if (raw === role || isPlaceholderEntityName(raw)) {
          base = fallbackCharacterName
        }
        if (!String(base || '').trim()) base = fallbackCharacterName
      }
      if (viewLabel && !base.includes(viewLabel)) return `${base} ${viewLabel}`
      return base
    }

    const makeAssetItem = (asset: LibraryAsset, key: string) => {
      const { role, group, view, viewRank, viewLabel } = normalizeRole(String(asset?.role || '').trim() || key)
      const rawTitle = String(asset?.meta?.entity_name || asset?.role || '').trim()
      const title = formatTitle(rawTitle, role, viewLabel)
      const imageState = resolveLibraryAssetImageState(asset, { missingRoleSet })
      const hasRenderableImage = imageState.hasRenderableImage
      const preview = hasRenderableImage ? libraryPreviews[asset.id] || '' : ''
      const aspectRatio = libraryAssetToCssAspectRatio(asset, libraryPreviewAspectRatio)
      const approved = hasRenderableImage && Boolean(asset.meta?.approved)
      const safety_blocked = Boolean(imageState.safetyBlocked || asset.meta?.safety_blocked)
      const safety_error = typeof asset.meta?.safety_error === 'string' ? asset.meta.safety_error : null
      const placeholder = Boolean(imageState.placeholder && !imageState.markedMissing && !imageState.safetyBlocked)
      return {
        key,
        role,
        title,
        preview,
        aspectRatio,
        approved,
        status: 'done' as const,
        group,
        view,
        viewRank,
        asset,
        missing: imageState.markedMissing,
        placeholder,
        hasRenderableImage,
        imageState,
        safety_blocked,
        safety_error,
      }
    }

    const items: LibraryDisplayItem[] = []
    const usedRoles = new Set<string>()

    const pushMissingItem = (rawRole: string) => {
      const role = String(rawRole || '').trim()
      if (!role || usedRoles.has(role)) return
      const { group, view, viewRank, viewLabel } = normalizeRole(role)
      const title = formatTitle(role, role, viewLabel)
      items.push({
        key: `missing:${role}`,
        role,
        title,
        preview: '',
        aspectRatio: libraryPreviewAspectRatio,
        approved: false,
        status: 'planned',
        group,
        view,
        viewRank,
        missing: true,
        placeholder: false,
        hasRenderableImage: false,
        imageState: null,
      })
      usedRoles.add(role)
    }

    if (libraryPlanItems.length) {
      for (const plan of libraryPlanItems) {
        const role = String(plan.role || '').trim()
        if (!role) continue
        usedRoles.add(role)
        const asset = assetsByRole.get(role)
        if (asset) {
          items.push(makeAssetItem(asset, `plan:${role}`))
          continue
        }
        const { group, view, viewRank, viewLabel } = normalizeRole(role)
        const rawTitle = String(plan.label || plan.entity_name || role).trim()
        const title = formatTitle(rawTitle, role, viewLabel)
        items.push({
          key: `plan:${role}`,
          role,
          title,
          preview: '',
          aspectRatio: libraryPreviewAspectRatio,
          approved: Boolean(plan.approved),
          status: plan.status === 'done' ? 'done' : plan.status === 'planned' ? 'planned' : 'processing',
          group,
          view,
          viewRank,
          missing: !asset && missingRoleSet.has(role),
          placeholder: false,
          hasRenderableImage: false,
          imageState: null,
        })
      }
      for (const asset of assets) {
        const role = String(asset?.role || '').trim()
        if (!role || usedRoles.has(role)) continue
        usedRoles.add(role)
        items.push(makeAssetItem(asset, `asset:${asset.id}`))
      }
      for (const role of normalizedMissingRoles) {
        pushMissingItem(role)
      }
      return items
    }

    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (role) usedRoles.add(role)
      items.push(makeAssetItem(asset, `asset:${asset.id}`))
    }
    for (const role of normalizedMissingRoles) {
      pushMissingItem(role)
    }
    return items
  }, [library?.assets, library?.spec, libraryPlanItems, libraryPreviews, libraryPreviewAspectRatio, missingRoleSet])

  const librarySummary = useMemo(() => {
    const total = libraryDisplayItems.length
    let generated = 0
    let processing = 0
    let planned = 0
    let approved = 0
    let pendingReview = 0
    for (const item of libraryDisplayItems) {
      if (item.hasRenderableImage) {
        generated += 1
      } else if (!item.asset && item.status === 'processing') {
        processing += 1
      } else {
        planned += 1
      }
      if (item.asset && item.hasRenderableImage) {
        if (item.approved) approved += 1
        else pendingReview += 1
      }
    }
    return { total, generated, processing, planned, approved, pendingReview }
  }, [libraryDisplayItems])

  const libraryGroups = useMemo(() => {
    const order: Array<LibraryDisplayItem['group']> = ['character', 'scene', 'prop', 'other']
    const labels: Record<LibraryDisplayItem['group'], string> = {
      character: '角色',
      scene: '场景',
      prop: '道具',
      other: '其他',
    }
    const groups = new Map<LibraryDisplayItem['group'], LibraryDisplayItem[]>()
    for (const item of libraryDisplayItems) {
      const key = item.group || 'other'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(item)
    }
    const result: LibraryDisplayGroup[] = []
    for (const key of order) {
      const items = groups.get(key) || []
      if (!items.length) continue
      const viewSuffixes = CHARACTER_VIEW_ORDER.map((view) => characterViewLabel(view)).sort((a, b) => b.length - a.length)
      const stripView = (value: string) => {
        const text = String(value || '').trim()
        for (const suffix of viewSuffixes) {
          const candidate = ` ${suffix}`
          if (text.endsWith(candidate)) return text.slice(0, -candidate.length)
        }
        return text
      }
      const sorted = [...items].sort((a, b) => {
        const nameA = stripView(String(a.title || ''))
        const nameB = stripView(String(b.title || ''))
        if (nameA !== nameB) return nameA.localeCompare(nameB, 'zh-CN')
        if (a.viewRank !== b.viewRank) return a.viewRank - b.viewRank
        return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
      })
      const summary = {
        total: sorted.length,
        generated: sorted.filter((i) => i.hasRenderableImage).length,
        processing: sorted.filter((i) => !i.asset && i.status === 'processing').length,
        planned: sorted.filter((i) => !i.hasRenderableImage && (i.asset || i.status === 'planned' || i.status === 'done')).length,
        approved: sorted.filter((i) => i.asset && i.hasRenderableImage && i.approved).length,
        pendingReview: sorted.filter((i) => i.asset && i.hasRenderableImage && !i.approved).length,
      }
      result.push({ key, label: labels[key], items: sorted, summary })
    }
    return result
  }, [libraryDisplayItems])

  const diagnosticCameraDiagnostics = useMemo(() => {
    const snapshotHasAny =
      Boolean(snapshotCameraDiagnostics.cameraTree && snapshotCameraDiagnostics.cameraTree.length) ||
      Boolean(snapshotCameraDiagnostics.cameraStates && snapshotCameraDiagnostics.cameraStates.length) ||
      Boolean(snapshotCameraDiagnostics.cameraScenes && snapshotCameraDiagnostics.cameraScenes.length) ||
      Boolean(snapshotCameraDiagnostics.generation)
    if (snapshotHasAny) return snapshotCameraDiagnostics

    const generation = asObject(diagnosticResult?.camera_tree_generation)
    const cameraTree = Array.isArray(diagnosticResult?.camera_tree) ? diagnosticResult.camera_tree : null
    const cameraStates = Array.isArray(diagnosticResult?.camera_states) ? diagnosticResult.camera_states : null
    const cameraScenes = Array.isArray(diagnosticResult?.camera_scenes) ? diagnosticResult.camera_scenes : null
    const sceneUris = (cameraScenes || [])
      .map((item) => {
        const record = asObject(item)
        return typeof record?.scene_uri === 'string' ? String(record.scene_uri || '').trim() : ''
      })
      .filter((item): item is string => Boolean(item))
    const mode = typeof generation?.mode === 'string' ? String(generation.mode) : null
    const resultHasAny = Boolean(generation) || Boolean(cameraTree && cameraTree.length) || Boolean(cameraStates && cameraStates.length) || Boolean(cameraScenes && cameraScenes.length)
    if (!resultHasAny) return snapshotCameraDiagnostics

    return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
  }, [diagnosticResult, snapshotCameraDiagnostics])

  const diagnosticShots = useMemo<DreamweaverDiagnosticShot[]>(() => {
    const res = diagnosticResult
    if (!res) return []

    const map = new Map<string, DreamweaverDiagnosticShot>()
    const ensure = (shotId: string): DreamweaverDiagnosticShot | null => {
      const key = String(shotId || '').trim()
      if (!key) return null
      if (!map.has(key)) map.set(key, { shot_id: key })
      return map.get(key) || null
    }

    const storyboard = Array.isArray(res.storyboard) ? res.storyboard : []
    for (const item of storyboard) {
      const itemRecord = asObject(item)
      const shotId = String(itemRecord?.shot_id || '').trim()
      const node = ensure(shotId)
      if (!node) continue
      node.storyboard = itemRecord
    }

    const parseFrameUri = (uri: string) => {
      const name = String(uri || '').split(/[\\/]+/).pop() || ''
      if (name.endsWith('_head.png')) return { shot_id: name.slice(0, -'_head.png'.length), role: 'head' as const }
      if (name.endsWith('_tail.png')) return { shot_id: name.slice(0, -'_tail.png'.length), role: 'tail' as const }
      if (name.endsWith('_mid.png')) return { shot_id: name.slice(0, -'_mid.png'.length), role: 'mid' as const }
      return { shot_id: '', role: null }
    }

    const parseClipUri = (uri: string) => {
      const name = String(uri || '').split(/[\\/]+/).pop() || ''
      if (!name) return ''
      const parts = name.split('.')
      if (parts.length < 2) return ''
      return parts.slice(0, -1).join('.')
    }

    const keyframes = Array.isArray(res.keyframes) ? res.keyframes : []
    for (const frame of keyframes) {
      const frameRecord = asObject(frame)
      const uri = typeof frameRecord?.path === 'string' ? String(frameRecord.path || '').trim() : ''
      if (!uri) continue
      const parsed = parseFrameUri(uri)
      if (!parsed.shot_id || !parsed.role) continue
      const node = ensure(parsed.shot_id)
      if (!node) continue
      node.frames = node.frames || {}
      node.frames[parsed.role] = frameRecord
    }

    const midframes = Array.isArray(res.midframes) ? res.midframes : []
    for (const frame of midframes) {
      const frameRecord = asObject(frame)
      const uri = typeof frameRecord?.path === 'string' ? String(frameRecord.path || '').trim() : ''
      if (!uri) continue
      const parsed = parseFrameUri(uri)
      if (!parsed.shot_id) continue
      const node = ensure(parsed.shot_id)
      if (!node) continue
      node.frames = node.frames || {}
      node.frames.mid = frameRecord
    }

    const clips = Array.isArray(res.video_clips) ? res.video_clips : []
    for (const clip of clips) {
      const clipRecord = asObject(clip)
      const uri = typeof clipRecord?.path === 'string' ? String(clipRecord.path || '').trim() : ''
      if (!uri) continue
      const shotId = parseClipUri(uri)
      if (!shotId) continue
      const node = ensure(shotId)
      if (!node) continue
      node.video_clip = clipRecord
    }

    const ordered: DreamweaverDiagnosticShot[] = []
    const pushed = new Set<string>()
    for (const item of storyboard) {
      const shotId = String(asObject(item)?.shot_id || '').trim()
      if (!shotId || pushed.has(shotId)) continue
      const node = map.get(shotId)
      if (node) {
        ordered.push(node)
        pushed.add(shotId)
      }
    }
    const rest = Array.from(map.values()).filter((node) => !pushed.has(String(node.shot_id || '')))
    rest.sort((a, b) => String(a.shot_id || '').localeCompare(String(b.shot_id || ''), 'zh-CN'))
    ordered.push(...rest)
    return ordered
  }, [diagnosticResult])

  const runId = useMemo(() => taskRunId || result?.run_id || null, [result?.run_id, taskRunId])
  const stageLabel = useMemo(() => taskStage || result?.stage || null, [result?.stage, taskStage])
  const stateLabel = useMemo(() => taskState || result?.state || null, [result?.state, taskState])
  const taskStatusLabel = useMemo(() => {
    const value = (taskStatus || '').trim().toLowerCase()
    if (!value) return null
    if (value === 'queued') return '排队中'
    if (value === 'running') return '运行中'
    if (value === 'waiting') return '等待中'
    if (value === 'completed') return '已完成'
    if (value === 'failed') return '失败'
    return taskStatus
  }, [taskStatus])
  const taskStatusColor = useMemo<'default' | 'info' | 'warning' | 'success' | 'error'>(() => {
    const value = (taskStatus || '').trim().toLowerCase()
    if (value === 'queued') return 'warning'
    if (value === 'waiting') return 'warning'
    if (value === 'running') return 'info'
    if (value === 'completed') return 'success'
    if (value === 'failed') return 'error'
    return 'default'
  }, [taskStatus])
  const progressLabel = useMemo(() => {
    if (running || waitingApproval) return taskProgress
    if (typeof result?.progress === 'number') return result.progress
    return taskProgress
  }, [result?.progress, running, taskProgress, waitingApproval])

  const progressStep = useMemo(() => stageToPreviewStep(stageLabel), [stageLabel])

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

  const toggleShotPromptExpanded = useCallback((key: string) => {
    const safeKey = String(key || '').trim()
    if (!safeKey) return
    setShotPromptExpanded((prev) => ({ ...prev, [safeKey]: !prev[safeKey] }))
  }, [])

  const renderShotPromptSnapshotItems = () =>
    snapshotShots.slice(0, 12).map((shot, idx) => {
      const shotKey = String(getShotId(shot) || shot.shot_index || idx).trim()
      const expanded = Boolean(shotPromptExpanded[shotKey])
      const headPrompt = getShotFramePrompt(shot.head_frame)
      const tailPrompt = getShotFramePrompt(shot.tail_frame)
      const overridePrompt = getShotVideoPromptOverride(shot)
      const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
      const promptLines: string[] = []
      const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}...`)
      if (headPrompt) promptLines.push(`首帧: ${formatPrompt(headPrompt)}`)
      if (tailPrompt) promptLines.push(`尾帧: ${formatPrompt(tailPrompt)}`)
      if (overridePrompt) promptLines.push(`视频覆盖: ${formatPrompt(overridePrompt)}`)
      const promptText = hasPrompt ? promptLines.join('\n') : '暂无提示词快照'
      const durationText = typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'
      return (
        <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
          <ListItemText
            primary={`#${shot.shot_index ?? idx + 1} ${getShotDesc(shot)}`.trim()}
            secondary={
              <>
                <Typography variant="caption" color="text.secondary" display="block">
                  场景: {shot.scene_id != null ? String(shot.scene_id) : '-'}  时长: {durationText}s
                </Typography>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
                  {promptText}
                </Typography>
                <Button
                  size="small"
                  variant="text"
                  onClick={() => toggleShotPromptExpanded(shotKey)}
                  disabled={!hasPrompt}
                  sx={{ px: 0, mt: 0.25 }}
                >
                  {expanded ? '收起提示词' : '展开提示词'}
                </Button>
              </>
            }
          />
        </ListItem>
      )
    })

  const renderRunSnapshotRefreshControls = (label = '刷新运行快照') => {
    if (!persistedRunId) return null
    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" mb={1}>
        {renderRunSnapshotRefreshButton(label)}
        {renderRunSnapshotLoadedChip()}
      </Stack>
    )
  }

  const buildSnapshotAssetPreviewPathSummary = (tailVideoClipPaths: string[]) => {
    const keyframePaths = formatPaths(snapshotAssetSummary.keyframes.slice(-3))
    const midframePaths = formatPaths(snapshotAssetSummary.midframes.slice(-3))
    const videoClipPaths = formatPaths(tailVideoClipPaths)

    if (!keyframePaths && !midframePaths && !videoClipPaths) return null

    return `快照路径：${keyframePaths ? `KF ${keyframePaths}` : ''}${midframePaths ? `  MF ${midframePaths}` : ''}${
      videoClipPaths ? `  VC ${videoClipPaths}` : ''
    }`
  }

  const renderSnapshotShotList = (emptyText: string) => {
    return (
      <RunSnapshotShotList
        visible={previewStep === 1 && !runSnapshotLoading}
        title="镜头列表"
        emptyText={emptyText}
        hasShots={snapshotShots.length > 0}
        shotItems={<List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>{renderShotPromptSnapshotItems()}</List>}
      />
    )
  }

  const renderSnapshotAssetPreviewSection = () => {
    const tailVideoClipPaths = snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path)

    return (
      <RunSnapshotAssetPreviewSection
        visible={previewStep === 3 && !runSnapshotLoading && snapshotShots.length > 0}
        shotCount={snapshotShots.length}
        assetCount={snapshotAssetCount}
        keyframeCount={snapshotAssetSummary.keyframes.length}
        midframeCount={snapshotAssetSummary.midframes.length}
        videoClipCount={snapshotAssetSummary.videoClips.length}
        pathSummary={buildSnapshotAssetPreviewPathSummary(tailVideoClipPaths)}
        keyframeGrid={renderRunAssetPreviewGrid('关键帧（快照）', snapshotAssetSummary.keyframes.slice(-6), 'image')}
        midframeGrid={renderRunAssetPreviewGrid('中间帧（快照）', snapshotAssetSummary.midframes.slice(-6), 'image')}
        videoClipGrid={renderRunAssetPreviewGrid('镜头片段（快照）', tailVideoClipPaths, 'video')}
      />
    )
  }

  const renderSnapshotMergedVideoSection = () => {
    return (
      <RunSnapshotMergedVideoSection
        visible={previewStep === 4 && !runSnapshotLoading}
        title="合成视频（快照）"
        description={snapshotMergedVideo ? `合成视频：${snapshotMergedVideo}` : '暂无合成视频快照'}
        panel={snapshotMergedVideo ? renderMergedVideoPanel() : null}
      />
    )
  }

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
  }) => (
    <RunSnapshotPreviewPane
      refreshControls={renderRunSnapshotRefreshControls(refreshLabel)}
      errorAlert={renderRunSnapshotErrorAlert('mb', 1)}
      wsWarning={
        includeWsError && wsError ? (
          <Alert severity="warning" sx={{ mb: 1 }} onClose={() => setWsError(null)}>
            {wsError}
          </Alert>
        ) : null
      }
      loadingBar={renderRunSnapshotLoadingBar('mb', 1)}
      safetyBlockedAlert={renderSafetyBlockedAlert()}
      streamingPreview={includeStreamingPreview ? renderStreamingPreview(previewStep) : null}
      scriptStageSnapshot={previewStep === 0 && !runSnapshotLoading ? renderScriptStageSnapshot() : null}
      shotList={renderSnapshotShotList(shotEmptyText)}
      assetPreview={renderSnapshotAssetPreviewSection()}
      mergedVideo={renderSnapshotMergedVideoSection()}
    />
  )

  const renderRunSnapshotRefreshButton = (label = '刷新运行快照') => (
    <Button
      size="small"
      variant="outlined"
      onClick={loadRunSnapshot}
      disabled={!persistedRunId || runSnapshotLoading}
    >
      {runSnapshotLoading ? '加载中…' : label}
    </Button>
  )

  const renderRunSnapshotLoadedChip = () => {
    if (!runSnapshot || runSnapshot.run_id !== persistedRunId) return null
    return <Chip size="small" label="快照已加载" color="success" />
  }

  const renderRunSnapshotErrorAlert = (spacingKey: 'mb' | 'mt', spacingValue = 1) => {
    if (!runSnapshotError) return null

    return (
      <Alert severity="error" sx={{ [spacingKey]: spacingValue }}>
        {runSnapshotError}
      </Alert>
    )
  }

  const renderRunSnapshotLoadingBar = (spacingKey: 'mb' | 'mt', spacingValue = 1) => {
    if (!runSnapshotLoading) return null
    return <LinearProgress sx={{ [spacingKey]: spacingValue }} />
  }

  const renderRunSnapshotSectionStatus = ({
    label = '加载运行快照',
    marginTop = 1,
    chips = [],
  }: {
    label?: string
    marginTop?: number
    chips?: Array<{ key: string; label: string }>
  }) => (
    <>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: marginTop }}>
        {renderRunSnapshotRefreshButton(label)}
        {renderRunSnapshotLoadedChip()}
        {chips.map((chip) => (
          <Chip key={chip.key} size="small" label={chip.label} />
        ))}
      </Stack>
      {renderRunSnapshotErrorAlert('mt', marginTop)}
      {renderRunSnapshotLoadingBar('mt', marginTop)}
    </>
  )

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
    <Accordion
      sx={{
        ...(marginTop > 0 ? { mt: marginTop } : {}),
        ...(marginBottom > 0 ? { mb: marginBottom } : {}),
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>{renderDebugJsonBox(value)}</AccordionDetails>
    </Accordion>
  )

  const renderResultVideoSummarySection = () => (
    <>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
        视频产物
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {result?.merged_video ? `合成视频：${result.merged_video}` : '无合成视频记录'}
      </Typography>
      {videoDiagnostics.viaSummary && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          生成方式：{videoDiagnostics.viaSummary}
          {videoDiagnostics.fallbackCount > 0 ? `（降级: ${videoDiagnostics.fallbackCount}/${videoDiagnostics.clipCount}）` : ''}
        </Typography>
      )}
    </>
  )

  const renderResultVideoFallbackAlert = () => {
    if (videoDiagnostics.fallbackCount <= 0) return null

    return (
      <Alert severity="warning" sx={{ mt: 1 }}>
        检测到镜头视频生成失败并降级为幻灯片合成，建议检查 WAN_I2V_* 配置/网络，并适当增大 WAN_I2V_TIMEOUT。
      </Alert>
    )
  }

  const renderResultVideoClipPathSummary = () => {
    if (!Array.isArray(result?.video_clips) || result.video_clips.length === 0) return null

    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        {resultVideoClipPaths
          .map((path, idx) => `${idx + 1}. ${path}`)
          .filter(Boolean)
          .join('  ')}
      </Typography>
    )
  }

  const renderResultVideoSnapshotStatus = () => {
    if (previewStep !== 3) return null

    return renderRunSnapshotSectionStatus({
      label: '加载运行快照',
      chips: [
        ...(snapshotShots.length > 0 ? [{ key: 'shots', label: `镜头: ${snapshotShots.length}` }] : []),
        ...(snapshotAssetCount > 0 ? [{ key: 'assets', label: `资产: ${snapshotAssetCount}` }] : []),
      ],
    })
  }

  const renderResultTextStageSection = ({
    title,
    text,
    emptyText,
    marginTop = 0,
    marginBottom = 1,
  }: {
    title: string
    text?: string | null
    emptyText: string
    marginTop?: number
    marginBottom?: number
  }) => (
    <>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, ...(marginTop > 0 ? { mt: marginTop } : {}), mb: 0.5 }}>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={marginBottom > 0 ? { mb: marginBottom } : undefined}>
        {text || emptyText}
      </Typography>
    </>
  )

  const renderResultVideoAssetPreviewSections = () => (
    <>
      {renderRunAssetPreviewGrid('关键帧', resultKeyframePaths.slice(-6), 'image')}
      {renderRunAssetPreviewGrid('中间帧', resultMidframePaths.slice(-6), 'image')}
      {candidateFrameUris.length > 0 &&
        renderRunAssetPreviewGrid('候选帧（keep_candidates）', candidateFrameUris.slice(-12), 'image')}
      {renderRunAssetPreviewGrid('镜头片段', resultVideoClipPaths.slice(-3), 'video')}
    </>
  )

  const renderResultStoryboardSnapshotSection = () => {
    if (previewStep !== 1) return null

    return (
      <>
        {renderRunSnapshotSectionStatus({ label: '加载运行快照' })}
        {!runSnapshotLoading && snapshotShots.length > 0 && (
          <List dense sx={{ mt: 1, bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
            {renderShotPromptSnapshotItems()}
          </List>
        )}
      </>
    )
  }

  const renderResultVideoStageView = () => (
    <>
      {renderResultVideoAssetPreviewSections()}
      {renderResultVideoSummarySection()}
      {renderResultVideoFallbackAlert()}
      {renderResultVideoClipPathSummary()}
      {result?.merged_video && renderMergedVideoPanel({ centeredPreview: true })}
      {renderResultVideoSnapshotStatus()}
    </>
  )

  const renderResultPlanStageView = () => (
    renderResultTextStageSection({
      title: '计划 / 剧本提要',
      text: resultPlanText,
      emptyText: '未返回文本',
    })
  )

  const renderResultStoryboardStageView = () => (
    <>
      {renderResultTextStageSection({
        title: '分镜（storyboard）',
        text: result?.storyboard ? `${result.storyboard.length} 个镜头` : '暂无',
        emptyText: '暂无',
        marginBottom: 0,
      })}
      {renderResultStoryboardSnapshotSection()}
    </>
  )

  const renderResultLibraryHintView = () => (
    <Alert severity="info" sx={{ mb: 1 }}>
      素材库为项目维度产物，可切换到“素材”并点击“加载素材库”查看/审核。
    </Alert>
  )

  const renderResultAuditStageView = () => (
    renderResultTextStageSection({
      title: '质检',
      text: result?.audit ? JSON.stringify(result.audit) : '',
      emptyText: '未返回审核信息',
      marginTop: 1,
      marginBottom: 0,
    })
  )

  const renderResultSummaryChips = () => {
    if (!result) return null

    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1.5} alignItems="center">
        <Chip label={`章节: ${result.source_chapter_count}`} size="small" />
        {Array.isArray(result.keyframes) && result.keyframes.length > 0 && (
          <Chip label={`关键帧: ${result.keyframes.length}`} size="small" />
        )}
        {Array.isArray(result.midframes) && result.midframes.length > 0 && (
          <Chip label={`中间帧: ${result.midframes.length}`} size="small" />
        )}
        {result.video_clips && <Chip label={`片段: ${result.video_clips.length}`} size="small" color="primary" />}
      </Stack>
    )
  }

  const renderResultSyncActions = () => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      {renderRunSnapshotRefreshButton('刷新运行快照')}
      <Button
        size="small"
        variant="outlined"
        onClick={() => currentRunId && syncDreamweaverEvents(currentRunId)}
        disabled={!currentRunId || eventSyncing}
      >
        {eventSyncing ? '同步中…' : '同步事件'}
      </Button>
      {renderRunSnapshotLoadedChip()}
      {eventCursor > 0 && <Chip size="small" label={`事件#${eventCursor}`} variant="outlined" />}
    </Stack>
  )

  const renderResultSyncStatus = () => (
    <>
      {renderRunSnapshotErrorAlert('mb', 1)}
      {eventSyncError && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {eventSyncError}
        </Alert>
      )}
      {renderRunSnapshotLoadingBar('mb', 1)}
    </>
  )

  const renderResultSyncSection = () => (
    <>
      {renderResultSyncActions()}
      {renderResultSyncStatus()}
    </>
  )

  const renderResultStageContent = () => (
    <>
      {(previewStep === 0 || previewStep === 4) && renderResultPlanStageView()}
      {(previewStep === 1 || previewStep === 4) && renderResultStoryboardStageView()}
      {previewStep === 2 && renderResultLibraryHintView()}
      {(previewStep === 3 || previewStep === 4) && renderResultVideoStageView()}
      {previewStep === 4 && renderResultAuditStageView()}
    </>
  )

  const renderResultView = () => {
    if (!result) return null

    return (
      <Box>
        {renderResultSummaryChips()}

        {renderDebugAccordion({
          title: '调试面板（Result）',
          value: result,
          marginBottom: 1.5,
        })}

        <Divider sx={{ my: 1.5 }} />

        {renderResultSyncSection()}

        {renderStreamingPreview(previewStep)}
        {renderResultStageContent()}
      </Box>
    )
  }

  const renderShotDiagnosticSummary = ({
    shotId,
    desc,
    duration,
    frames,
    hasVideoClip,
    shotProviderTrace,
    shotAutoQCPass,
    shotAutoQCScore,
  }: {
    shotId: string
    desc: string
    duration: number | null
    frames: DreamweaverDiagnosticShotFrames
    hasVideoClip: boolean
    shotProviderTrace: DreamweaverVideoProviderShotTrace | null
    shotAutoQCPass: boolean | null
    shotAutoQCScore: number | null
  }) => (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ width: '100%' }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
        {shotId || '-'}
      </Typography>
      {desc && (
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 520, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {desc}
        </Typography>
      )}
      {typeof duration === 'number' && Number.isFinite(duration) && <Chip size="small" label={`${duration.toFixed(1)}s`} />}
      {frames.head && <Chip size="small" label="head" color="success" variant="outlined" />}
      {frames.tail && <Chip size="small" label="tail" color="success" variant="outlined" />}
      {frames.mid && <Chip size="small" label="mid" color="success" variant="outlined" />}
      {hasVideoClip && <Chip size="small" label="clip" color="info" variant="outlined" />}
      {shotProviderTrace?.route && <Chip size="small" variant="outlined" color="info" label={`route: ${shotProviderTrace.route}`} />}
      {shotProviderTrace?.applied_provider && <Chip size="small" variant="outlined" label={`applied: ${shotProviderTrace.applied_provider}`} />}
      {shotProviderTrace?.shadowed && <Chip size="small" color="warning" label="shadow" />}
      {shotAutoQCPass != null && (
        <Chip
          size="small"
          label={`AutoQC: ${shotAutoQCPass ? 'pass' : 'fail'}${typeof shotAutoQCScore === 'number' ? ` (${shotAutoQCScore.toFixed(2)})` : ''}`}
          color={shotAutoQCPass ? 'success' : 'warning'}
        />
      )}
    </Stack>
  )

  const resolveShotDiagnosticAccordionState = (shot: DreamweaverDiagnosticShot) => {
    const shotId = String(shot.shot_id || '').trim()
    const frames = shot.frames || {}
    const sb = shot.storyboard || null
    const desc = typeof sb?.desc === 'string' ? sb.desc : ''
    const duration =
      typeof sb?.duration_s === 'number' ? Number(sb.duration_s) : typeof sb?.duration_s === 'string' ? Number(sb.duration_s) : null
    const autoqcShots = asObject(asObject(diagnosticResult?.autoqc)?.shots)
    const shotAutoQC = asObject(autoqcShots?.[shotId])
    const shotAutoQCPass = shotAutoQC ? Boolean(shotAutoQC.pass) : null
    const shotAutoQCScore =
      typeof asObject(shotAutoQC?.scores)?.overall === 'number' ? Number(asObject(shotAutoQC?.scores)?.overall) : null
    const shotProviderTrace = diagnosticProviderTraceByShotId.get(shotId) || null

    return {
      shotId,
      frames,
      sb,
      desc,
      duration,
      shotAutoQC,
      shotAutoQCPass,
      shotAutoQCScore,
      shotProviderTrace,
      videoClip: shot.video_clip,
      hasVideoClip: Boolean(shot.video_clip),
    }
  }

  const renderShotDiagnosticUploadActions = (shotId: string) => {
    if (!shotId) return null

    return (
      <>
        {renderDiagnosticUploadButton({
          label: '上传首帧',
          accept: 'image/png',
          shotId,
          assetRole: 'head_frame',
        })}
        {renderDiagnosticUploadButton({
          label: '上传尾帧',
          accept: 'image/png',
          shotId,
          assetRole: 'tail_frame',
        })}
        {renderDiagnosticUploadButton({
          label: '上传中间帧',
          accept: 'image/png',
          shotId,
          assetRole: 'mid_frame',
        })}
        {renderDiagnosticUploadButton({
          label: '上传镜头视频',
          accept: 'video/mp4',
          shotId,
          assetRole: 'video_clip',
        })}
      </>
    )
  }

  const renderShotDiagnosticPromptRegenerateActions = (shotId: string, sb: Record<string, unknown> | null) => {
    if (!shotId) return null

    return (
      <>
        <Button
          size="small"
          variant="contained"
          onClick={() =>
            void promptAndRegenerateKeyframe(
              shotId,
              'head',
              getDiagnosticStoryboardPrompt(sb, 'head_frame'),
            )
          }
          disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
        >
          改首帧提示词并重跑
        </Button>
        <Button
          size="small"
          variant="contained"
          onClick={() =>
            void promptAndRegenerateKeyframe(
              shotId,
              'tail',
              getDiagnosticStoryboardPrompt(sb, 'tail_frame'),
            )
          }
          disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
        >
          改尾帧提示词并重跑
        </Button>
      </>
    )
  }

  const renderShotDiagnosticActions = ({
    shotId,
    sb,
    frames,
    videoClip,
    shotProviderTrace,
    shotAutoQC,
  }: {
    shotId: string
    sb: Record<string, unknown> | null
    frames: DreamweaverDiagnosticShotFrames
    videoClip: Record<string, unknown> | null | undefined
    shotProviderTrace: DreamweaverVideoProviderShotTrace | null
    shotAutoQC: Record<string, unknown> | null
  }) => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Button
        size="small"
        variant="outlined"
        startIcon={<ContentCopyIcon fontSize="small" />}
        onClick={() =>
          copyText(
            safeJsonStringify({
              shot_id: shotId,
              storyboard: sb,
              frames: frames,
              video_clip: videoClip || null,
              provider_trace: shotProviderTrace,
              autoqc: shotAutoQC,
            }),
          )
        }
      >
        复制镜头诊断
      </Button>
      {sb && (
        <Button size="small" variant="text" onClick={() => copyText(safeJsonStringify(sb))}>
          复制分镜
        </Button>
      )}
      {renderShotDiagnosticUploadActions(shotId)}
      {renderShotDiagnosticPromptRegenerateActions(shotId, sb)}
      {shotId && (
        <Button
          size="small"
          variant="contained"
          startIcon={<RefreshIcon fontSize="small" />}
          onClick={() => void restartGeneration('VIDEO', [shotId])}
          disabled={!currentRunId || running || restartLoading}
        >
          重跑该镜头视频
        </Button>
      )}
    </Stack>
  )

  const renderShotProviderTraceSection = (shotProviderTrace: DreamweaverVideoProviderShotTrace | null) => {
    if (!shotProviderTrace) return null

    return (
      <Accordion sx={{ mt: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              Provider 路由
            </Typography>
            {shotProviderTrace.reason && <Chip size="small" variant="outlined" label={`reason: ${shotProviderTrace.reason}`} />}
          </Stack>
        </AccordionSummary>
        <AccordionDetails>
          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
            {shotProviderTrace.requested_provider_mode && (
              <Chip size="small" variant="outlined" label={`requested: ${shotProviderTrace.requested_provider_mode}`} />
            )}
            {shotProviderTrace.recommended_provider && (
              <Chip size="small" variant="outlined" label={`recommended: ${shotProviderTrace.recommended_provider}`} />
            )}
            {shotProviderTrace.applied_provider && (
              <Chip size="small" variant="outlined" label={`applied: ${shotProviderTrace.applied_provider}`} />
            )}
            {shotProviderTrace.selector_mode && <Chip size="small" variant="outlined" label={`selector: ${shotProviderTrace.selector_mode}`} />}
          </Stack>
          {shotProviderTrace.metadata && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              metadata: {safeJsonStringify(shotProviderTrace.metadata)}
            </Typography>
          )}
          {renderDiagnosticJson(shotProviderTrace)}
        </AccordionDetails>
      </Accordion>
    )
  }

  const renderShotDiagnosticDetails = ({
    sb,
    shotProviderTrace,
    shotAutoQC,
    frames,
    videoClip,
  }: {
    sb: Record<string, unknown> | null
    shotProviderTrace: DreamweaverVideoProviderShotTrace | null
    shotAutoQC: Record<string, unknown> | null
    frames: DreamweaverDiagnosticShotFrames
    videoClip: Record<string, unknown> | null | undefined
  }) => (
    <>
      {renderTitledDiagnosticJsonAccordion({
        title: '分镜（storyboard）',
        value: sb,
        marginTop: 0,
      })}

      {renderShotProviderTraceSection(shotProviderTrace)}

      {renderTitledDiagnosticJsonAccordion({
        title: 'AutoQC',
        value: shotAutoQC,
      })}

      {renderDiagnosticFrame('首帧（head）', frames.head, 'image')}
      {renderDiagnosticFrame('尾帧（tail）', frames.tail, 'image')}
      {renderDiagnosticFrame('中间帧（mid）', frames.mid, 'image')}
      {renderDiagnosticFrame('镜头片段（video_clip）', videoClip, 'video')}
    </>
  )

  const renderShotDiagnosticAccordion = (shot: DreamweaverDiagnosticShot) => {
    const {
      shotId,
      frames,
      sb,
      desc,
      duration,
      shotAutoQC,
      shotAutoQCPass,
      shotAutoQCScore,
      shotProviderTrace,
      videoClip,
      hasVideoClip,
    } = resolveShotDiagnosticAccordionState(shot)

    return (
      <Accordion key={`diag:${shotId}`} sx={{ mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderShotDiagnosticSummary({
            shotId,
            desc,
            duration,
            frames,
            hasVideoClip,
            shotProviderTrace,
            shotAutoQCPass,
            shotAutoQCScore,
          })}
        </AccordionSummary>
        <AccordionDetails>
          {renderShotDiagnosticActions({
            shotId,
            sb,
            frames,
            videoClip,
            shotProviderTrace,
            shotAutoQC,
          })}

          {renderShotDiagnosticDetails({
            sb,
            shotProviderTrace,
            shotAutoQC,
            frames,
            videoClip,
          })}
        </AccordionDetails>
      </Accordion>
    )
  }

  const renderDiagnosticRouteFeatureChips = ({
    allowKlingOmni,
    enableKlingVideoProvider,
    allowSubjectBridge,
  }: {
    allowKlingOmni?: boolean | null
    enableKlingVideoProvider?: boolean | null
    allowSubjectBridge?: boolean | null
  }) => (
    <>
      {typeof allowKlingOmni === 'boolean' && (
        <Chip size="small" variant="outlined" label={`allow_kling_omni: ${allowKlingOmni ? 'on' : 'off'}`} />
      )}
      {typeof enableKlingVideoProvider === 'boolean' && (
        <Chip size="small" variant="outlined" label={`kling_executor: ${enableKlingVideoProvider ? 'on' : 'off'}`} />
      )}
      {typeof allowSubjectBridge === 'boolean' && (
        <Chip size="small" variant="outlined" label={`subject_bridge: ${allowSubjectBridge ? 'on' : 'off'}`} />
      )}
    </>
  )

  const renderDiagnosticIssueAlerts = ({
    issues,
    severity,
    keyPrefix,
  }: {
    issues: DreamweaverRunPreflightData['errors']
    severity: 'error' | 'warning'
    keyPrefix: string
  }) =>
    issues.map((issue) => (
      <Alert key={`${keyPrefix}:${issue.code}`} severity={severity} sx={{ mb: 1 }}>
        {issue.code}: {issue.message}
      </Alert>
    ))

  const renderDiagnosticPreflightSummary = (preflight: DreamweaverRunPreflightData) => {
    const resolvedVideoConfig = preflight.resolved_video_config || {}

    return (
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <WarningIcon color={preflight.allowed ? 'warning' : 'error'} fontSize="small" />
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          运行预检
        </Typography>
        <Chip
          size="small"
          color={preflight.allowed ? 'success' : 'error'}
          label={preflight.allowed ? 'allowed' : 'blocked'}
        />
        <Chip size="small" label={`errors: ${preflight.errors.length}`} />
        <Chip size="small" label={`warnings: ${preflight.warnings.length}`} />
        {typeof resolvedVideoConfig['provider_mode'] === 'string' && (
          <Chip size="small" variant="outlined" label={`provider: ${String(resolvedVideoConfig['provider_mode'])}`} />
        )}
        {typeof resolvedVideoConfig['selector_mode'] === 'string' && (
          <Chip size="small" variant="outlined" label={`selector: ${String(resolvedVideoConfig['selector_mode'])}`} />
        )}
      </Stack>
    )
  }

  const renderDiagnosticPreflightActions = (preflight: DreamweaverRunPreflightData) => {
    const resolvedVideoConfig = preflight.resolved_video_config || {}

    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<ContentCopyIcon fontSize="small" />}
          onClick={() => copyText(safeJsonStringify(preflight))}
        >
          复制 Preflight
        </Button>
        {renderDiagnosticRouteFeatureChips({
          allowKlingOmni:
            typeof resolvedVideoConfig['allow_kling_omni'] === 'boolean' ? resolvedVideoConfig['allow_kling_omni'] : null,
          enableKlingVideoProvider:
            typeof resolvedVideoConfig['enable_kling_video_provider'] === 'boolean'
              ? resolvedVideoConfig['enable_kling_video_provider']
              : null,
          allowSubjectBridge:
            typeof resolvedVideoConfig['allow_subject_bridge'] === 'boolean' ? resolvedVideoConfig['allow_subject_bridge'] : null,
        })}
      </Stack>
    )
  }

  const renderDiagnosticPreflightDetails = (preflight: DreamweaverRunPreflightData) => (
    <>
      {renderDiagnosticPreflightActions(preflight)}
      {renderDiagnosticIssueAlerts({
        issues: preflight.errors,
        severity: 'error',
        keyPrefix: 'preflight:error',
      })}
      {renderDiagnosticIssueAlerts({
        issues: preflight.warnings,
        severity: 'warning',
        keyPrefix: 'preflight:warning',
      })}

      {renderTitledDiagnosticJsonAccordion({
        title: 'preflight',
        value: preflight,
      })}
    </>
  )

  const renderDiagnosticPreflightSection = () => {
    if (!diagnosticPreflight) return null
    return (
      <Accordion defaultExpanded={!diagnosticPreflight.allowed} sx={{ mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderDiagnosticPreflightSummary(diagnosticPreflight)}
        </AccordionSummary>
        <AccordionDetails>{renderDiagnosticPreflightDetails(diagnosticPreflight)}</AccordionDetails>
      </Accordion>
    )
  }

  const renderDiagnosticProviderTraceSummary = () => (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
      <BugReportIcon color="primary" fontSize="small" />
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        Provider 路由
      </Typography>
      {diagnosticProviderTrace?.provider_mode && (
        <Chip size="small" variant="outlined" label={`provider_mode: ${diagnosticProviderTrace.provider_mode}`} />
      )}
      {diagnosticProviderTrace?.selector_mode && (
        <Chip size="small" variant="outlined" label={`selector_mode: ${diagnosticProviderTrace.selector_mode}`} />
      )}
      {diagnosticProviderTraceSummary && <Chip size="small" label={`shots: ${diagnosticProviderTraceSummary.totalShots}`} />}
      {diagnosticProviderTraceSummary && (
        <Chip size="small" label={`recommend_kling: ${diagnosticProviderTraceSummary.recommendedKling}`} />
      )}
      {diagnosticProviderTraceSummary && (
        <Chip size="small" label={`apply_kling: ${diagnosticProviderTraceSummary.appliedKling}`} />
      )}
      {diagnosticProviderTraceSummary && diagnosticProviderTraceSummary.shadowed > 0 && (
        <Chip size="small" color="warning" label={`shadow: ${diagnosticProviderTraceSummary.shadowed}`} />
      )}
    </Stack>
  )

  const renderDiagnosticProviderTraceActions = () => {
    if (!diagnosticProviderTrace) return null

    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<ContentCopyIcon fontSize="small" />}
          onClick={() => copyText(safeJsonStringify(diagnosticProviderTrace))}
        >
          复制 Provider Trace
        </Button>
        {renderDiagnosticRouteFeatureChips({
          allowKlingOmni: diagnosticProviderTrace.allow_kling_omni,
          enableKlingVideoProvider: diagnosticProviderTrace.enable_kling_video_provider,
          allowSubjectBridge: diagnosticProviderTrace.allow_subject_bridge,
        })}
      </Stack>
    )
  }

  const renderDiagnosticProviderTraceDetails = () => {
    if (!diagnosticProviderTrace) return null

    return (
      <>
        {renderDiagnosticProviderTraceActions()}

        {renderTitledDiagnosticJsonAccordion({
          title: 'video_provider_trace',
          value: diagnosticProviderTrace,
        })}
      </>
    )
  }

  const renderDiagnosticProviderTraceSection = () => {
    if (!diagnosticProviderTrace) return null
    return (
      <Accordion defaultExpanded sx={{ mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderDiagnosticProviderTraceSummary()}
        </AccordionSummary>
        <AccordionDetails>{renderDiagnosticProviderTraceDetails()}</AccordionDetails>
      </Accordion>
    )
  }

  const renderDiagnosticOutlinedChipStack = (
    items: Array<{ key: string; label: string }>,
    marginTop = 0,
  ) => {
    if (items.length === 0) return null

    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={marginTop > 0 ? { mt: marginTop } : undefined}>
        {items.map((item) => (
          <Chip key={item.key} size="small" variant="outlined" label={item.label} />
        ))}
      </Stack>
    )
  }

  const renderDiagnosticTelemetrySummary = () => {
    if (!snapshotTelemetrySummary) return null

    return (
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
        {typeof snapshotTelemetrySummary.totalS === 'number' && (
          <Chip size="small" label={`总耗时: ${snapshotTelemetrySummary.totalS.toFixed(1)}s`} />
        )}
        {snapshotTelemetrySummary.terminalState && (
          <Chip size="small" label={`terminal: ${snapshotTelemetrySummary.terminalState}`} variant="outlined" />
        )}
        {typeof snapshotTelemetrySummary.reworkCount === 'number' && (
          <Chip size="small" label={`返工: ${snapshotTelemetrySummary.reworkCount}`} variant="outlined" />
        )}
        {typeof snapshotRuntimeConfig?.ab_variant === 'string' && snapshotRuntimeConfig.ab_variant.trim() && (
          <Chip size="small" label={`variant: ${snapshotRuntimeConfig.ab_variant.trim()}`} variant="outlined" />
        )}
      </Stack>
    )
  }

  const renderDiagnosticTelemetryStageEntries = () => {
    if (!snapshotTelemetrySummary || snapshotTelemetrySummary.stageEntries.length === 0) return null

    return renderDiagnosticOutlinedChipStack(
      snapshotTelemetrySummary.stageEntries.map((item) => ({
        key: `tele:${item.stage}`,
        label: `${item.stage}: ${Number(item.totalS).toFixed(1)}s (${item.calls}${item.failure ? `, fail:${item.failure}` : ''})`,
      })),
    )
  }

  const renderDiagnosticTelemetryReworkChips = () => {
    if (!snapshotTelemetrySummary?.reworkByType) return null

    return renderDiagnosticOutlinedChipStack(
      Object.entries(snapshotTelemetrySummary.reworkByType).map(([key, value]) => ({
        key: `rework:${key}`,
        label: `rework.${key}: ${value}`,
      })),
      1,
    )
  }

  const renderDiagnosticTelemetryCounterChips = () => {
    if (snapshotTelemetryCounters.length === 0) return null

    return renderDiagnosticOutlinedChipStack(
      snapshotTelemetryCounters.map((item) => ({
        key: `telemetry-counter:${item.name}`,
        label: `${item.name}: ${item.value}`,
      })),
      1,
    )
  }

  const renderDiagnosticTelemetrySection = () => {
    if (!snapshotTelemetrySummary) return null
    return (
      <Accordion defaultExpanded sx={{ mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            运行耗时（Telemetry）
          </Typography>
        </AccordionSummary>
        <AccordionDetails>
          {renderDiagnosticTelemetrySummary()}
          {renderDiagnosticTelemetryStageEntries()}
          {renderDiagnosticTelemetryReworkChips()}
          {renderDiagnosticTelemetryCounterChips()}

          {renderTitledDiagnosticJsonAccordion({
            title: 'Telemetry JSON',
            value: snapshotTelemetry,
          })}
        </AccordionDetails>
      </Accordion>
    )
  }

  const buildCameraDiagnosticPayload = () => ({
    camera_tree_generation: diagnosticCameraDiagnostics.generation || null,
    camera_tree: diagnosticCameraDiagnostics.cameraTree || null,
    camera_states: diagnosticCameraDiagnostics.cameraStates || null,
    camera_scenes: diagnosticCameraDiagnostics.cameraScenes || null,
  })

  const renderDiagnosticCameraDiagnosticsSummary = () => (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
      <PhotoCameraIcon color="primary" fontSize="small" />
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        相机依赖（Camera Tree）
      </Typography>
      {diagnosticCameraDiagnostics.mode && <Chip size="small" label={`mode: ${diagnosticCameraDiagnostics.mode}`} variant="outlined" />}
      {Array.isArray(diagnosticCameraDiagnostics.cameraTree) && (
        <Chip size="small" label={`cameras: ${diagnosticCameraDiagnostics.cameraTree.length}`} />
      )}
      {Array.isArray(diagnosticCameraDiagnostics.cameraScenes) && (
        <Chip size="small" label={`scenes: ${diagnosticCameraDiagnostics.cameraScenes.length}`} />
      )}
    </Stack>
  )

  const renderDiagnosticCameraDiagnosticsActions = () => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Button
        size="small"
        variant="outlined"
        startIcon={<ContentCopyIcon fontSize="small" />}
        onClick={() => copyText(safeJsonStringify(buildCameraDiagnosticPayload()))}
      >
        复制 Camera 诊断
      </Button>
    </Stack>
  )

  const renderDiagnosticCameraDiagnosticsDetails = () => (
    <>
      {diagnosticCameraDiagnostics.sceneUris.length > 0 &&
        renderRunAssetPreviewGrid(
          '相机场景（每个相机首镜头 head）',
          diagnosticCameraDiagnostics.sceneUris.slice(0, 12),
          'image',
        )}

      {renderTitledDiagnosticJsonAccordion({
        title: 'camera_tree_generation',
        value: diagnosticCameraDiagnostics.generation,
      })}

      {renderTitledDiagnosticJsonAccordion({
        title: 'camera_tree',
        value: diagnosticCameraDiagnostics.cameraTree,
      })}

      {renderTitledDiagnosticJsonAccordion({
        title: 'camera_states',
        value: diagnosticCameraDiagnostics.cameraStates,
      })}

      {renderTitledDiagnosticJsonAccordion({
        title: 'camera_scenes',
        value: diagnosticCameraDiagnostics.cameraScenes,
      })}
    </>
  )

  const renderDiagnosticCameraDiagnosticsSection = () => {
    if (
      !diagnosticCameraDiagnostics.cameraTree &&
      !diagnosticCameraDiagnostics.cameraStates &&
      !diagnosticCameraDiagnostics.cameraScenes &&
      !diagnosticCameraDiagnostics.generation
    ) {
      return null
    }
    return (
      <Accordion sx={{ mb: 1 }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          {renderDiagnosticCameraDiagnosticsSummary()}
        </AccordionSummary>
        <AccordionDetails>
          {renderDiagnosticCameraDiagnosticsActions()}
          {renderDiagnosticCameraDiagnosticsDetails()}
        </AccordionDetails>
      </Accordion>
    )
  }

  const openDiagnosticDialog = () => {
    setDiagnosticActionError(null)
    setDiagnosticOpen(true)
  }

  const renderPendingRunningStageHint = () => {
    const stageHintMap: Record<number, string> = {
      0: '剧本预览：当前为运行中阶段，进入“剧本待审核”后可加载/编辑/通过。',
      1: '分镜预览：将展示镜头数量与分镜阶段信息（后续可升级为镜头列表/分镜卡）。',
      2: '素材预览：素材库在生成后可在此加载并逐项审核。',
      3: '镜头预览：关键帧/中间帧/片段生成将逐步更新计数与产物路径。',
      4: '合成预览：合成视频与质检结果将在后续阶段产出。',
    }
    const hint = stageHintMap[previewStep]
    if (!hint) return null

    return (
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {hint}
      </Typography>
    )
  }

  const renderPendingRunningArtifactChip = (
    label: string,
    value: string | number | null | undefined,
    variant: 'filled' | 'outlined' = 'filled',
  ) => {
    if (value == null || value === '') return null
    return <Chip label={`${label}: ${value}`} size="small" variant={variant} />
  }

  const renderPendingRunningArtifactLine = (label: string | null, parts: Array<string | null | undefined | false>) => {
    const content = parts.filter(Boolean).join('  ')
    if (!content) return null

    return (
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
        {label ? `${label}: ${content}` : content}
      </Typography>
    )
  }

  const renderPendingRunningArtifactsSummary = () => (
    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
      {renderPendingRunningArtifactChip('SB', taskArtifacts?.storyboard_count)}
      {renderPendingRunningArtifactChip('KF', taskArtifacts?.keyframes_count)}
      {renderPendingRunningArtifactChip('MF', taskArtifacts?.midframes_count)}
      {renderPendingRunningArtifactChip('VC', taskArtifacts?.video_clips_count)}
      {renderPendingRunningArtifactChip('CamTree', taskArtifacts?.stage_artifacts?.camera_tree_mode, 'outlined')}
      {renderPendingRunningArtifactChip('Cam', taskArtifacts?.stage_artifacts?.camera_count)}
      {renderPendingRunningArtifactChip('CamState', taskArtifacts?.stage_artifacts?.camera_states_count)}
      {renderPendingRunningArtifactChip('CamScene', taskArtifacts?.stage_artifacts?.camera_scenes_count)}
      <Button
        size="small"
        variant="text"
        startIcon={<ContentCopyIcon fontSize="small" />}
        onClick={copyDebugInfo}
      >
        复制调试信息
      </Button>
      <Button
        size="small"
        variant="text"
        startIcon={<BugReportIcon fontSize="small" />}
        onClick={openDiagnosticDialog}
        disabled={!currentRunId}
      >
        诊断面板
      </Button>
    </Stack>
  )

  const renderPendingRunningArtifactDetails = () => (
    <>
      {renderPendingRunningArtifactLine('Last', [
        formatPath(taskArtifacts?.last_keyframe_path) ? `KF ${formatPath(taskArtifacts?.last_keyframe_path)}` : '',
        formatPath(taskArtifacts?.last_midframe_path) ? `MF ${formatPath(taskArtifacts?.last_midframe_path)}` : '',
        formatPath(taskArtifacts?.last_video_clip_path) ? `VC ${formatPath(taskArtifacts?.last_video_clip_path)}` : '',
      ])}
      {renderPendingRunningArtifactLine(null, [
        formatPaths(taskArtifacts?.keyframes_tail_paths) ? `KF: ${formatPaths(taskArtifacts?.keyframes_tail_paths)}` : '',
        formatPaths(taskArtifacts?.midframes_tail_paths) ? `MF: ${formatPaths(taskArtifacts?.midframes_tail_paths)}` : '',
        formatPaths(taskArtifacts?.video_clips_tail_paths) ? `VC: ${formatPaths(taskArtifacts?.video_clips_tail_paths)}` : '',
      ])}
      {renderPendingRunningArtifactLine('Rework', [
        taskArtifacts?.rework_reason ? JSON.stringify(taskArtifacts.rework_reason) : '',
      ])}
      {renderPendingRunningArtifactLine('Stage artifacts', [
        taskArtifacts?.stage_artifacts ? JSON.stringify(taskArtifacts.stage_artifacts) : '',
      ])}
    </>
  )

  const renderPendingRunningView = () => {
    const state = resolvePendingRunningState({
      taskStatus,
      taskQueue,
    })

    return (
      <PendingRunningShell
        state={state}
        stageHint={renderPendingRunningStageHint()}
        snapshotPreview={renderRunSnapshotPreviewPane({
          shotEmptyText: state.snapshotShotEmptyText,
          includeStreamingPreview: true,
          includeWsError: true,
        })}
        artifactsSummary={renderPendingRunningArtifactsSummary()}
        artifactDetails={renderPendingRunningArtifactDetails()}
        debugPanel={renderDebugAccordion({
          title: '调试面板（Artifacts）',
          value: taskArtifacts,
          marginTop: 1,
        })}
      />
    )
  }

  const renderPendingScriptApprovalEditor = () => (
    <TextField
      label="剧本（可编辑）"
      value={scriptText}
      onChange={(e) => setScriptText(e.target.value)}
      fullWidth
      multiline
      minRows={10}
      maxRows={22}
      disabled={scriptLoading}
      sx={{ bgcolor: '#fff' }}
    />
  )

  const renderPendingScriptApprovalView = () => {
    const state = resolvePendingScriptApprovalState({
      scriptText,
      scriptGenerationLabel: scriptGenerationLabel || '',
      scriptGenerationMode: scriptGeneration?.mode,
      scriptGenerationError: scriptGeneration?.error,
      scriptRequiresReview,
      scriptApproved,
      scriptDirty,
      currentRunId,
      scriptLoading,
      canResumeFromScript,
      resumeLoading,
      scriptError,
      entitySummary: scriptEntities ? summarizeScriptEntities(scriptEntities) : '',
    })

    return (
      <PendingScriptApprovalShell
        state={state}
        onLoadScript={loadScript}
        onSaveScript={saveScript}
        onApproveScript={() => approveScript(true)}
        onRevokeScript={() => approveScript(false)}
        onResume={resumeGeneration}
        editor={renderPendingScriptApprovalEditor()}
        debugPanel={renderDebugAccordion({
          title: '调试面板（Artifacts）',
          value: taskArtifacts,
          marginTop: 1,
        })}
      />
    )
  }

  const renderPendingVideoConfirmationJobItem = (job: DreamweaverVideoClipJob, idx: number) => {
    const sid = String(job.shot_id || '').trim()
    const desc = String(job.desc || '').trim()
    const dep = String(job.depends_on_shot_id || '').trim()
    const shot = sid ? snapshotShotById.get(sid) ?? null : null
    const headPrompt = getShotFramePrompt(shot?.head_frame)
    const tailPrompt = getShotFramePrompt(shot?.tail_frame)
    const overridePrompt = getShotVideoPromptOverride(shot)
    const state = resolvePendingVideoConfirmationJobState({
      shotId: sid,
      desc,
      status: String(job.status || '').trim(),
      confirmed: Boolean(job.confirmed),
      requiresBridge: Boolean(job.requires_bridge),
      bridgeDependency: dep,
      hasPrompt: Boolean(headPrompt || tailPrompt || overridePrompt),
      headPrompt,
      tailPrompt,
      overridePrompt,
      running,
      videoJobConfirmingShotId,
      hasShot: Boolean(shot),
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
    const state = resolvePendingPromptReviewShotState({
      shotId,
      title: getShotDesc(shot),
      shotIndex: shot.shot_index ?? idx + 1,
      headPrompt: getShotFramePrompt(shot.head_frame),
      tailPrompt: getShotFramePrompt(shot.tail_frame),
      overridePrompt: getShotVideoPromptOverride(shot),
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

  const renderPendingVideoConfirmationView = () => {
    const state = resolvePendingVideoConfirmationState({
      videoJobActionError,
      persistedRunId,
      runSnapshotLoading,
      videoClipJobCount: videoClipJobs.length,
    })

    return (
      <PendingVideoConfirmationView
        state={state}
        jobItems={videoClipJobs.map(renderPendingVideoConfirmationJobItem)}
        onRefresh={rebuildVideoJobs}
      />
    )
  }

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
      promptReviewShotCount: promptReviewShots.length,
      snapshotShotCount: snapshotShots.length,
      promptReviewShowAll,
    })

    return (
      <PendingPromptReviewView
        state={state}
        shotItems={promptReviewShots.map(renderPendingPromptReviewShotItem)}
        revokeLabel="撤销确认"
        onRefresh={loadRunSnapshot}
        onApprove={() => approvePromptReview(true)}
        onRevoke={() => approvePromptReview(false)}
        onResume={resumeGeneration}
        onToggleShowAll={() => setPromptReviewShowAll((prev) => !prev)}
      />
    )
  }

  const renderCharacterLibraryBucketSection = (bucket: CharacterLibraryBucket) => {
    const generatedCount = bucket.items.filter((item) => item.hasRenderableImage).length

    return (
      <Box key={bucket.bucketKey} sx={{ border: '1px solid #eee', borderRadius: 2, p: 1, bgcolor: '#fcfcfc' }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 0.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {bucket.name}
          </Typography>
          <Chip size="small" label={`视角 ${bucket.items.length}`} variant="outlined" />
          <Chip size="small" label={`已生成 ${generatedCount}`} color={generatedCount ? 'success' : 'default'} />
        </Stack>
        <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
          {bucket.items.map(renderLibraryDisplayCard)}
        </ImageList>
      </Box>
    )
  }

  const renderLibrarySummaryChips = (summary: LibraryGroupSummary, totalLabel: string) => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Chip size="small" label={`${totalLabel} ${summary.total}`} />
      <Chip size="small" label={`已生成 ${summary.generated}`} color={summary.generated ? 'success' : 'default'} />
      <Chip size="small" label={`生成中 ${summary.processing}`} color={summary.processing ? 'info' : 'default'} />
      <Chip size="small" label={`待生成 ${summary.planned}`} />
      {summary.approved > 0 && <Chip size="small" label={`已通过 ${summary.approved}`} color="success" />}
      {summary.pendingReview > 0 && <Chip size="small" label={`待审核 ${summary.pendingReview}`} color="warning" />}
    </Stack>
  )

  const renderCharacterLibraryGroupGrid = (items: LibraryDisplayItem[]) => {
    const viewSuffixes = CHARACTER_VIEW_ORDER.map((view) => characterViewLabel(view)).sort((a, b) => b.length - a.length)
    const stripViewSuffix = (value: string) => {
      const text = String(value || '').trim()
      for (const suffix of viewSuffixes) {
        const candidate = ` ${suffix}`
        if (text.endsWith(candidate)) return text.slice(0, -candidate.length).trim()
      }
      return text
    }

    const buckets = new Map<string, CharacterLibraryBucket>()
    for (const item of items) {
      const parsed = parseLibraryRole(item.role)
      const parsedEntityId = typeof parsed.entityId === 'number' ? parsed.entityId : 0
      const entityId = parsed.entityType === 'character' && parsedEntityId > 0 ? parsedEntityId : 0
      const fallbackName = entityId > 0 ? `角色#${entityId}` : '未命名角色'
      const strippedTitle = stripViewSuffix(item.title)
      const baseName = isPlaceholderEntityName(strippedTitle) || strippedTitle === item.role ? fallbackName : strippedTitle
      const bucketKey = entityId > 0 ? `character:${entityId}` : `character:${baseName}`
      if (!buckets.has(bucketKey)) {
        buckets.set(bucketKey, { bucketKey, entityId, name: baseName, items: [] })
      }
      buckets.get(bucketKey)!.items.push(item)
    }

    const orderedBuckets = Array.from(buckets.values())
      .map((bucket) => ({
        ...bucket,
        items: [...bucket.items].sort((a, b) => {
          if (a.viewRank !== b.viewRank) return a.viewRank - b.viewRank
          return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
        }),
      }))
      .sort((a, b) => {
        if (a.entityId > 0 && b.entityId > 0) return a.entityId - b.entityId
        if (a.entityId > 0) return -1
        if (b.entityId > 0) return 1
        return a.name.localeCompare(b.name, 'zh-CN')
      })

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
    <Box key={group.key} sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {group.label}
        </Typography>
      </Stack>
      {renderLibrarySummaryChips(group.summary, '总计')}
      {renderLibraryGroupGrid(group)}
    </Box>
  )

  const renderPendingLibraryControls = () => (
    <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
      <Button
        size="small"
        variant="contained"
        onClick={loadLibrary}
        disabled={!selectedProjectId || libraryLoading}
      >
        加载素材库
      </Button>
      <Button
        size="small"
        variant="outlined"
        onClick={() => approveLibrary({ approve_all: true, approved: true })}
        disabled={!selectedProjectId || libraryLoading}
      >
        全部通过
      </Button>
      <Button
        size="small"
        variant="contained"
        color="success"
        onClick={resumeGeneration}
        disabled={!canResumeFromLibrary}
      >
        {resumeLoading ? '继续生成中…' : '继续生成'}
      </Button>
    </Stack>
  )

  const renderPendingLibraryReviewStatus = () => {
    if (!library?.review) return null

    return (
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        审核状态：缺失 {Array.isArray(library.review.missing_roles) ? library.review.missing_roles.length : 0}，未通过{' '}
        {Array.isArray(library.review.unapproved_roles) ? library.review.unapproved_roles.length : 0}
      </Typography>
    )
  }

  const renderPendingLibrarySummaryChips = () => renderLibrarySummaryChips(librarySummary, '占位')

  const renderPendingLibraryReadyActions = () => (
    <Stack direction="row" spacing={1} alignItems="center">
      <Button size="small" variant="text" onClick={() => handleClickStep(2)}>
        查看素材库
      </Button>
      {promptReviewRequiredSnapshot && (
        <Button size="small" variant="text" onClick={() => handleClickStep(1)}>
          查看提示词
        </Button>
      )}
      <Button size="small" variant="contained" color="success" onClick={resumeGeneration} disabled={!canResumeFromLibrary}>
        {resumeLoading ? '继续生成中…' : '继续生成'}
      </Button>
    </Stack>
  )

  const renderPendingLibrarySummarySection = () => {
    if (!libraryDisplayItems.length) {
      return <Typography variant="body2" color="text.secondary">{'未加载素材库或当前项目暂无可审核素材。'}</Typography>
    }

    return (
      <Box>
        {renderPendingLibrarySummaryChips()}
        {libraryGroups.map(renderLibraryGroupSection)}
      </Box>
    )
  }

  const renderPendingLibraryReviewView = () => (
    <PendingLibraryReviewShell
      notice={
        <PendingLibraryNotice
          severity={libraryApproved && promptReviewReady ? 'success' : 'warning'}
          message={libraryPromptReviewMessage}
        />
      }
      controls={renderPendingLibraryControls()}
      runtimeStatus={
        <>
          {libraryError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {libraryError}
            </Alert>
          )}
          {libraryLoading && <LinearProgress sx={{ mb: 1 }} />}
          {renderPendingLibraryReviewStatus()}
        </>
      }
      summarySection={renderPendingLibrarySummarySection()}
      debugPanel={renderDebugAccordion({
        title: '调试面板（Artifacts）',
        value: taskArtifacts,
        marginTop: 1,
      })}
    />
  )

  const renderPendingLibraryReadyView = () => (
    <PendingLibraryReadyShell
      notice={
        <PendingLibraryNotice
          severity={libraryApproved && promptReviewReady ? 'success' : 'info'}
          message={libraryPromptReviewMessage}
          action={renderPendingLibraryReadyActions()}
        />
      }
      snapshotPreview={renderRunSnapshotPreviewPane({
        shotEmptyText: '尚无可用分镜快照（可能尚未落库）。',
      })}
    />
  )

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

  const closeDiagnosticDialog = () => {
    setDiagnosticOpen(false)
  }

  const buildRunDiagnosticPayload = () => ({
    page: 'DreamWeaverRunDiagnostics',
    run_id: currentRunId,
    status: taskStatus,
    state: taskState,
    stage: taskStage,
    preflight: diagnosticPreflight,
    video_provider_trace: diagnosticProviderTrace,
    runtime_config: snapshotRuntimeConfig,
    camera_tree_generation: diagnosticCameraDiagnostics.generation || null,
    camera_tree: diagnosticCameraDiagnostics.cameraTree || null,
    camera_states: diagnosticCameraDiagnostics.cameraStates || null,
    camera_scenes: diagnosticCameraDiagnostics.cameraScenes || null,
    autoqc: diagnosticResult?.autoqc || null,
    storyboard: diagnosticResult?.storyboard || null,
    keyframes: diagnosticResult?.keyframes || null,
    midframes: diagnosticResult?.midframes || null,
    video_clips: diagnosticResult?.video_clips || null,
    merged_video: diagnosticResult?.merged_video || null,
  })

  const renderDiagnosticDialog = () => (
    <DreamweaverDiagnosticDialogShell
      open={diagnosticOpen}
      onClose={closeDiagnosticDialog}
      header={
        <DreamweaverDiagnosticDialogHeader
          runId={currentRunId}
          state={diagnosticResult?.state}
          stage={diagnosticResult?.stage}
          onClose={closeDiagnosticDialog}
        />
      }
      statusSection={
        <DreamweaverDiagnosticDialogStatusSection
          hasRunId={Boolean(currentRunId)}
          hasDiagnosticResult={Boolean(diagnosticResult)}
          error={diagnosticActionError}
          loading={diagnosticActionLoading}
        />
      }
      toolbar={
        <DreamweaverDiagnosticDialogToolbar
          shotCount={diagnosticShots.length}
          keyframeCount={Array.isArray(diagnosticResult?.keyframes) ? diagnosticResult.keyframes.length : null}
          midframeCount={Array.isArray(diagnosticResult?.midframes) ? diagnosticResult.midframes.length : null}
          videoClipCount={Array.isArray(diagnosticResult?.video_clips) ? diagnosticResult.video_clips.length : null}
          refreshLabel={runSnapshotLoading ? '刷新中...' : '刷新运行快照'}
          refreshDisabled={!persistedRunId || runSnapshotLoading}
          copyDisabled={!(diagnosticResult || diagnosticPreflight || diagnosticProviderTrace)}
          onRefresh={loadRunSnapshot}
          onCopy={() => copyText(safeJsonStringify(buildRunDiagnosticPayload()))}
        />
      }
      sections={
        <>
          {renderDiagnosticPreflightSection()}
          {renderDiagnosticProviderTraceSection()}
          {renderDiagnosticTelemetrySection()}
          {renderDiagnosticCameraDiagnosticsSection()}
        </>
      }
      emptyState={
        <DreamweaverDiagnosticDialogEmptyState
          hasDiagnosticResult={Boolean(diagnosticResult)}
          shotCount={diagnosticShots.length}
        />
      }
      shotAccordions={diagnosticResult && diagnosticShots.length > 0 ? diagnosticShots.map(renderShotDiagnosticAccordion) : null}
    />
  )

  const closePromptEditDialog = () => {
    if (promptEditSaving) return
    setPromptEditOpen(false)
  }

  const renderPromptEditDialogContent = () => (
    <DreamweaverPromptEditDialogContent
      shotDescription={promptEditShot ? getShotDesc(promptEditShot) : null}
      headPrompt={promptEditHead}
      tailPrompt={promptEditTail}
      generatedPrompt={promptEditGenerated || '暂无自动提示词（可能尚未生成或未落库）'}
      videoPrompt={promptEditVideo}
      saving={promptEditSaving}
      error={promptEditError}
      onChangeHead={setPromptEditHead}
      onChangeTail={setPromptEditTail}
      onChangeVideo={setPromptEditVideo}
    />
  )

  const renderPromptEditDialogActions = () => (
    <DreamweaverPromptEditDialogActions
      saving={promptEditSaving}
      onClose={closePromptEditDialog}
      onSave={savePromptEdit}
    />
  )

  const renderPromptEditDialog = () => (
    <DreamweaverPromptEditDialogShell
      open={promptEditOpen}
      onClose={closePromptEditDialog}
      title={`提示词审核：${getShotId(promptEditShot) || '未选中'}`}
      content={renderPromptEditDialogContent()}
      actions={renderPromptEditDialogActions()}
    />
  )

  const closeRegenerateDialog = () => {
    if (regenSubmitting) return
    setRegenOpen(false)
  }

  const renderRegenerateDialogModeControls = () => (
    <DreamweaverRegenerateDialogModeControls
      suggesting={regenSuggesting}
      submitting={regenSubmitting}
      hasRole={Boolean(regenRole)}
      forceImageEdit={regenForceImageEdit}
      imageEditActive={regenImageEditActive}
      hasImageBase={regenHasImageBase}
      onSmartGenerate={() => requestSmartRegeneratePrompt({ source: 'manual' })}
      onToggleImageEdit={toggleRegenImageEditPreference}
    />
  )

  const renderRegenerateDialogStatusHints = () => (
    <>
      {regenForceImageEdit && (
        <Alert severity={regenHasImageBase ? 'info' : 'error'} sx={{ mb: 1 }}>
          <Typography variant="body2">
            {regenHasImageBase
              ? `参考基底：${regenAlertBaseLabel}。${
                  regenAlertReadyReferenceLabel
                    ? `参考图已就绪：${regenAlertReadyReferenceLabel}${
                        regenAlertReadyReferenceCount > 1
                          ? '（生成时将自动上传；额外参考图在模型支持多参考时生效）。'
                          : '（生成时将自动上传）。'
                      }`
                    : '参考图已就绪。'
                }`
              : `缺少参考图：${regenAlertMissingReferenceLabel || '前序视角'}。请先生成前序视角。`}
          </Typography>
        </Alert>
      )}
      {!regenForceImageEdit && !regenHasImageBase && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          当前素材没有可编辑底图，将回退到文生图模式。
        </Typography>
      )}
      {regenSuggestError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {regenSuggestError}
        </Alert>
      )}
      {regenImageEditActive && regenImageEditAutoCleared && (
        <Typography variant="caption" color="text.disabled" display="block" sx={{ mb: 1 }}>
          已清空原提示词，请填写本次需要修改的内容。
        </Typography>
      )}
    </>
  )

  const renderRegenerateDialogContent = () => (
    <DreamweaverRegenerateDialogContent
      modeHint={
        regenImageEditActive
          ? '图像编辑模式：将基于参考图生成，提交后状态变为“待审核”。'
          : '可在下方编辑提示词并重生成素材，生成后将变为待审核状态。'
      }
      modeControls={renderRegenerateDialogModeControls()}
      statusHints={renderRegenerateDialogStatusHints()}
      promptInputLabel={regenPromptInputLabel}
      prompt={regenPrompt}
      promptPlaceholder={
        regenImageEditActive && regenImageEditAutoCleared
          ? '示例：保持角色身份锚点不变，改为侧面全身，左肩数据接口更亮，背景保持纯灰色。'
          : undefined
      }
      submitting={regenSubmitting}
      suggesting={regenSuggesting}
      error={regenError}
      onChangePrompt={(value) => {
        setRegenPrompt(value)
        setRegenPromptDirty(value.trim() !== regenPromptInitial.trim())
      }}
    />
  )

  const renderRegenerateDialogActions = () => (
    <DreamweaverRegenerateDialogActions
      submitting={regenSubmitting}
      submitLabel={regenSubmitting ? '生成中...' : regenImageEditActive ? '开始生成（图像编辑）' : '开始生成（提示词）'}
      submitDisabled={regenSubmitting || regenSuggesting || !regenRole || (regenForceImageEdit && !regenHasImageBase)}
      onClose={closeRegenerateDialog}
      onSubmit={submitRegenerateDialog}
    />
  )

  const renderRegenerateDialog = () => (
    <DreamweaverRegenerateDialogShell
      open={regenOpen}
      onClose={closeRegenerateDialog}
      title={`重生成素材：${regenTitle || regenRole}`}
      content={renderRegenerateDialogContent()}
      actions={renderRegenerateDialogActions()}
    />
  )

  const HISTORY_FILTER_STATUSES = ['running', 'queued', 'waiting', 'failed', 'timeout', 'completed'] as const

  const renderHistoryDialogTitle = () => <DreamweaverHistoryDialogTitle projectTitle={selectedProject?.title} />

  const toggleHistoryStatusFilter = (status: string) => {
    setHistoryStatusFilters((prev) =>
      prev.includes(status) ? prev.filter((item) => item !== status) : [...prev, status],
    )
  }

  const renderHistoryAllFilterChip = () => (
    <Chip
      size="small"
      label={`全部 (${historyRuns.length})`}
      color="default"
      variant={historyStatusFilters.length === 0 ? 'filled' : 'outlined'}
      onClick={() => setHistoryStatusFilters([])}
    />
  )

  const renderHistoryStatusFilterChip = (status: string) => {
    const enabled = historyStatusFilters.includes(status)
    const count = historyStatusCounts[status] || 0
    const { label, color } = getHistoryStatusMeta(status)

    return (
      <Chip
        key={status}
        size="small"
        label={`${label} (${count})`}
        color={color}
        variant={enabled ? 'filled' : 'outlined'}
        onClick={() => toggleHistoryStatusFilter(status)}
      />
    )
  }

  const renderHistoryFilterChips = () => (
    <>
      {renderHistoryAllFilterChip()}
      {HISTORY_FILTER_STATUSES.map(renderHistoryStatusFilterChip)}
    </>
  )

  const renderHistoryDialogToolbarActions = () => (
    <>
      <Button
        size="small"
        variant="outlined"
        disabled={historyLoading || !selectedProjectId}
        onClick={() => selectedProjectId && fetchRunHistory(selectedProjectId)}
      >
        刷新
      </Button>
      <Button
        size="small"
        variant="contained"
        color="error"
        disabled={historyLoading || bulkDeleteTargets.length === 0}
        onClick={openBulkDeleteDialog}
      >
        批量删除筛选结果 ({bulkDeleteTargets.length})
      </Button>
    </>
  )

  const renderHistoryDialogToolbar = () => (
    <DreamweaverHistoryDialogToolbar
      filters={renderHistoryFilterChips()}
      actions={renderHistoryDialogToolbarActions()}
    />
  )

  const renderHistoryRunItemSummaryChips = (run: DreamweaverRunSummary, progressValue: number | null) => {
    const statusRaw = String(run.status || '').trim().toLowerCase()
    const { label: statusLabel, color: statusColor } = getHistoryStatusMeta(statusRaw)

    return (
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <Chip size="small" label={statusLabel} color={statusColor} />
        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
          {run.run_id}
        </Typography>
        {typeof progressValue === 'number' && <Chip size="small" label={`进度: ${progressValue}%`} />}
        {run.stage && <Chip size="small" label={`阶段: ${run.stage}`} />}
        {run.camera_tree_mode && <Chip size="small" label={`CamTree: ${run.camera_tree_mode}`} variant="outlined" />}
        {typeof run.camera_count === 'number' && <Chip size="small" label={`Cam: ${run.camera_count}`} />}
        {typeof run.camera_states_count === 'number' && <Chip size="small" label={`CamState: ${run.camera_states_count}`} />}
        {typeof run.camera_scenes_count === 'number' && <Chip size="small" label={`CamScene: ${run.camera_scenes_count}`} />}
      </Stack>
    )
  }

  const renderHistoryRunItemActions = (runId: string) => (
    <Stack direction="row" spacing={1} alignItems="center">
      <Button
        size="small"
        variant="text"
        startIcon={<PlayArrowIcon fontSize="small" />}
        onClick={() => handleViewHistoryRun(runId)}
      >
        查看
      </Button>
      <Button
        size="small"
        variant="text"
        color="error"
        startIcon={<DeleteIcon fontSize="small" />}
        onClick={() => openDeleteRunDialog(runId)}
      >
        删除
      </Button>
    </Stack>
  )

  const renderHistoryRunItem = (run: DreamweaverRunSummary) => {
    const timeText = formatDateTime(run.updated_at || run.created_at)
    const progressValue =
      typeof run.progress === 'number' ? Math.max(0, Math.min(100, Math.round(run.progress))) : null

    return (
      <DreamweaverHistoryRunItem
        key={run.run_id}
        summary={renderHistoryRunItemSummaryChips(run, progressValue)}
        timeText={timeText}
        errorMessage={run.error_message}
        actions={renderHistoryRunItemActions(run.run_id)}
      />
    )
  }

  const renderHistoryDialogContent = () => (
    <DreamweaverHistoryDialogContent
      error={historyError}
      loading={historyLoading}
      toolbar={renderHistoryDialogToolbar()}
      emptyState={
        <>
          {!historyLoading && !historyError && historyRuns.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              暂无历史任务
            </Typography>
          )}

          {!historyLoading && !historyError && historyRuns.length > 0 && filteredHistoryRuns.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              筛选结果为空
            </Typography>
          )}
        </>
      }
      runList={!historyLoading && filteredHistoryRuns.length > 0 ? <List>{filteredHistoryRuns.map(renderHistoryRunItem)}</List> : null}
    />
  )

  const renderHistoryDialog = () => (
    <DreamweaverHistoryDialogShell
      open={historyOpen}
      onClose={closeHistoryDialog}
      title={renderHistoryDialogTitle()}
      content={renderHistoryDialogContent()}
    />
  )

  const renderBulkDeleteDialogContent = () => (
    <DreamweaverBulkDeleteDialogContent
      targetCount={bulkDeleteTargets.length}
      skippedCount={bulkDeleteSkippedCount}
      progress={bulkDeleteProgress}
      error={bulkDeleteError}
      result={bulkDeleteResult}
    />
  )

  const renderBulkDeleteDialogActions = () => (
    <DreamweaverBulkDeleteDialogActions
      submitting={bulkDeleteSubmitting}
      hasResult={Boolean(bulkDeleteResult)}
      hasTargets={bulkDeleteTargets.length > 0}
      onClose={closeBulkDeleteDialog}
      onConfirm={confirmBulkDeleteRuns}
    />
  )

  const renderBulkDeleteDialog = () => (
    <DreamweaverBulkDeleteDialogShell
      open={bulkDeleteDialogOpen}
      onClose={closeBulkDeleteDialog}
      content={renderBulkDeleteDialogContent()}
      actions={renderBulkDeleteDialogActions()}
    />
  )

  const renderDeleteRunDialogContent = () => (
    <DreamweaverDeleteRunDialogContent runId={deleteRunId} error={deleteDialogError} />
  )

  const renderDeleteRunDialogActions = () => (
    <DreamweaverDeleteRunDialogActions
      submitting={deleteSubmitting}
      hasRunId={Boolean(deleteRunId)}
      onClose={closeDeleteRunDialog}
      onConfirm={confirmDeleteRun}
    />
  )

  const renderDeleteRunDialog = () => (
    <DreamweaverDeleteRunDialogShell
      open={deleteDialogOpen}
      onClose={closeDeleteRunDialog}
      content={renderDeleteRunDialogContent()}
      actions={renderDeleteRunDialogActions()}
    />
  )

  const closeConfigDialog = () => setConfigDialogOpen(false)

  const clearTaskPointsPrecheckError = () => {
    setTaskPointsPrecheckError(null)
    setError(null)
  }

  const renderConfigDialogTitle = () => (
    <DreamweaverConfigDialogTitle
      title="生成配置"
      subtitle={
        (selectedProject?.title || (selectedProjectId ? `项目 #${selectedProjectId}` : '请选择项目')) +
        (chapters.length ? ` · 已选 ${selectedChapterIds.length}/${chapters.length} 章` : '')
      }
      onClose={closeConfigDialog}
    />
  )

  const renderConfigDialogErrorNotice = () => {
    if (taskPointsPrecheckError) {
      return (
        <TaskPointsPrecheckAlert
          detail={taskPointsPrecheckError}
          onClose={clearTaskPointsPrecheckError}
          sx={{ mb: 2 }}
        />
      )
    }

    if (error) {
      return (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )
    }

    return null
  }

  const renderConfigDialogProjectSection = () => (
    <DreamweaverConfigDialogProjectSection
      lockedProjectId={lockedProjectId}
      projectTitle={selectedProject?.title}
      action={renderConfigDialogProjectAlertAction()}
    />
  )

  const renderConfigDialogProjectAlertAction = () => (
    <Button
      size="small"
      variant="outlined"
      onClick={() => {
        closeConfigDialog()
        navigate('/drama')
      }}
    >
      去项目列表
    </Button>
  )

  const renderConfigDialogChapterItem = (chapter: Chapter) => {
    const raw = String(chapter.content || '').replace(/\s+/g, ' ').trim()
    const snippet = raw ? (raw.length > 64 ? raw.slice(0, 64) + '…' : raw) : '（无正文）'

    return (
      <ListItem
        key={chapter.id}
        disablePadding
        secondaryAction={
          <Checkbox
            edge="end"
            size="small"
            disabled={running}
            checked={selectedChapterIds.includes(chapter.id)}
            onChange={() => handleToggleChapter(chapter.id)}
          />
        }
      >
        <ListItemButton
          onClick={() => handleToggleChapter(chapter.id)}
          disabled={running}
          sx={{ pr: 6 }}
        >
          <ListItemText
            primary={`${chapter.chapter_number}. ${chapter.title || '未命名章节'}`}
            secondary={snippet}
          />
        </ListItemButton>
      </ListItem>
    )
  }

  const renderConfigDialogChapterSelectionCard = () => (
    <DreamweaverConfigDialogChapterSelectionCard
      toolbarActions={
        <>
          <Button size="small" onClick={handleSelectAll} disabled={loadingChapters || !chapters.length || running}>
            {selectedChapterIds.length === chapters.length ? '清空' : '全选'}
          </Button>
          <Button
            size="small"
            startIcon={<RefreshIcon fontSize="small" />}
            onClick={() => {
              if (selectedProjectId) void handleSelectProject(selectedProjectId)
            }}
            disabled={loadingChapters || !selectedProjectId || running}
          >
            刷新
          </Button>
        </>
      }
      listContent={loadingChapters ? <LinearProgress /> : <List dense disablePadding>{chapters.map(renderConfigDialogChapterItem)}</List>}
      helperText="至少选择 1 个章节；默认全选可直接开始生成。"
      maxHeight={configDialogFullScreen ? '55vh' : 360}
    />
  )

  const renderConfigStrategyToggleField = ({
    fieldKey,
    title,
    checked,
    onChange,
    enabledLabel,
    disabledLabel,
    description,
  }: {
    fieldKey?: string
    title: string
    checked: boolean
    onChange: (checked: boolean) => void
    enabledLabel: string
    disabledLabel: string
    description: string
  }) => (
    <Stack key={fieldKey} spacing={0.5}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <FormControlLabel
          sx={{ mr: 0 }}
          control={<Switch checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={running} />}
          label={checked ? enabledLabel : disabledLabel}
        />
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {description}
      </Typography>
    </Stack>
  )

  const renderConfigDialogStrategyFields = () => {
    const fields = [
      {
        fieldKey: 'quality-mode',
        title: '成本 / 质量',
        checked: highQuality,
        onChange: setHighQuality,
        enabledLabel: '最高质量',
        disabledLabel: '低成本',
        description: highQuality ? '多候选 + 语义评选 + 图片编辑 + 语义质检' : '单候选 + 关闭编辑/语义质检',
      },
      {
        fieldKey: 'smart-tuning',
        title: '智能调参',
        checked: smartTuning,
        onChange: setSmartTuning,
        enabledLabel: '智能调参',
        disabledLabel: '手动调参',
        description: '质量优先：按镜头规模自动调候选数与语义质检预算。',
      },
      {
        fieldKey: 'video-confirmation',
        title: '视频逐段确认',
        checked: videoRequireConfirmation,
        onChange: setVideoRequireConfirmation,
        enabledLabel: '逐段确认',
        disabledLabel: '自动生成',
        description: 'VIDEO 阶段先生成任务卡，确认后按镜头生成视频；桥接依赖会自动阻塞提示。',
      },
      {
        fieldKey: 'prompt-review',
        title: '提示词审核',
        checked: promptReviewRequired,
        onChange: setPromptReviewRequired,
        enabledLabel: '先审提示词',
        disabledLabel: '直接生成',
        description: '生成关键帧/视频前先停在提示词审核，可修改后再提交生成任务。',
      },
      {
        fieldKey: 'qc-allow-fail',
        title: '质检失败处理',
        checked: qcAllowFail,
        onChange: setQcAllowFail,
        enabledLabel: '仅警告',
        disabledLabel: '严格拦截',
        description: 'AutoQC 失败可仅警告放行；文件校验（audit）仍会拦截。',
      },
    ]

    return fields.map((field) => renderConfigStrategyToggleField(field))
  }

  const renderConfigDialogExperimentField = () => (
    <Stack spacing={0.5}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>
        实验标签（可选）
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={abVariant}
        onChange={(e) => setAbVariant(e.target.value)}
        disabled={running}
        placeholder="例如 A / B / control / treatment"
        inputProps={{ maxLength: 32 }}
      />
      <Typography variant="caption" color="text.secondary">
        仅用于标记并对比不同策略效果，不会自动改变生成逻辑。
      </Typography>
    </Stack>
  )

  const renderConfigDialogSelectField = ({
    labelId,
    label,
    value,
    onChange,
    options,
  }: {
    labelId: string
    label: string
    value: string
    onChange: (value: string) => void
    options: Array<{ value: string; label: string }>
  }) => (
    <FormControl fullWidth size="small" disabled={running || lockedGenerationConfigLoading || generationConfigLocked}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select
        labelId={labelId}
        value={value}
        label={label}
        onChange={(e) => onChange(String(e.target.value))}
      >
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )

  const renderConfigDialogStrategyCard = () => (
    <DreamweaverConfigDialogStrategyCard
      content={
        <>
          {renderConfigDialogStrategyFields()}
          {renderConfigDialogExperimentField()}
        </>
      }
      helperText="性能提示：关键帧镜头级并发由后端环境变量 `DREAMWEAVER_KEYFRAMES_PARALLELISM` 控制，建议先从 `2` 开始，避免把上游 QPS 打满。"
    />
  )

  const renderConfigDialogVisualSettingsCard = () => (
    <DreamweaverConfigDialogVisualSettingsCard
      notices={
        <>
          {lockedGenerationConfigError && (
            <Alert severity="warning" sx={{ mb: 1 }}>
              {lockedGenerationConfigError}
            </Alert>
          )}
          {generationConfigLocked && (
            <Alert severity="info" sx={{ mb: 1 }}>
              当前项目的风格/比例/分辨率已锁定，生成过程中不允许切换；如需变更请新建项目或先清理该项目的 DreamWeaver runs。
              {lockedGenerationConfig?.source_run_id ? `（锁定来源：${lockedGenerationConfig.source_run_id}）` : ''}
            </Alert>
          )}
        </>
      }
      fields={
        <Grid container spacing={1.5}>
          <Grid item xs={12}>
            {renderConfigDialogSelectField({
              labelId: 'style-preset-label',
              label: '风格预设',
              value: stylePreset,
              onChange: setStylePreset,
              options: Object.values(STYLE_PRESETS).map((optionValue) => ({
                value: optionValue,
                label: STYLE_PRESET_LABELS[optionValue] || optionValue,
              })),
            })}
          </Grid>
          <Grid item xs={12} sm={6}>
            {renderConfigDialogSelectField({
              labelId: 'image-ratio-label',
              label: '画面比例',
              value: imageRatio,
              onChange: setImageRatio,
              options: Object.values(IMAGE_RATIOS).map((optionValue) => ({
                value: optionValue,
                label: IMAGE_RATIOS_LABELS[optionValue] || optionValue,
              })),
            })}
          </Grid>
          <Grid item xs={12} sm={6}>
            {renderConfigDialogSelectField({
              labelId: 'image-resolution-label',
              label: '分辨率',
              value: imageResolution,
              onChange: setImageResolution,
              options: Object.values(IMAGE_RESOLUTIONS).map((optionValue) => ({
                value: optionValue,
                label: IMAGE_RESOLUTIONS_LABELS[optionValue] || optionValue,
              })),
            })}
          </Grid>
        </Grid>
      }
      helperText="比例决定横/竖屏；分辨率影响素材库、关键帧与合成视频输出尺寸。"
    />
  )

  const runFromConfigDialog = async () => {
    const ok = await handleRun()
    if (ok) closeConfigDialog()
  }

  const renderConfigDialogMainGrid = () => (
    <Grid container spacing={2}>
      <Grid item xs={12} md={7}>
        {renderConfigDialogChapterSelectionCard()}
      </Grid>

      <Grid item xs={12} md={5}>
        <Stack spacing={2}>
          {renderConfigDialogStrategyCard()}
          {renderConfigDialogVisualSettingsCard()}
        </Stack>
      </Grid>
    </Grid>
  )

  const renderConfigDialogContent = () => (
    <DreamweaverConfigDialogContent
      errorNotice={renderConfigDialogErrorNotice()}
      projectSection={renderConfigDialogProjectSection()}
      mainGrid={renderConfigDialogMainGrid()}
    />
  )

  const renderConfigDialogActions = () => (
    <DreamweaverConfigDialogActions
      onClose={closeConfigDialog}
      onRun={runFromConfigDialog}
      runDisabled={running || lockedGenerationConfigLoading || !selectedProjectId || selectedChapterIds.length === 0}
    />
  )

  const renderConfigDialog = () => (
    <DreamweaverConfigDialogShell
      open={configDialogOpen}
      onClose={closeConfigDialog}
      fullScreen={configDialogFullScreen}
      title={renderConfigDialogTitle()}
      content={renderConfigDialogContent()}
      actions={renderConfigDialogActions()}
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
    if (raw == null) return
    const ids = raw
      .split(/[\s,，;；\n]+/g)
      .map((s) => s.trim())
      .filter((s) => s)
    if (ids.length === 0) {
      setError('未输入有效 shot_id')
      return
    }
    void restartGeneration('VIDEO', ids)
  }

  const requestRestartKeyframeCameras = () => {
    closeRestartMenu()
    const raw = window.prompt('请输入需要重跑的相机 cam_idx（多个用逗号分隔）', '')
    if (raw == null) return
    const ids = raw
      .split(/[\s,，;；\n]+/g)
      .map((s) => s.trim())
      .filter((s) => s)
      .map((s) => Number(s))
      .filter((n) => Number.isFinite(n))
      .map((n) => Math.trunc(n))
    const unique = ids.filter((n, idx, arr) => arr.indexOf(n) === idx)
    if (unique.length === 0) {
      setError('未输入有效 cam_idx')
      return
    }
    void restartGeneration('KEYFRAMES', undefined, unique)
  }

  const renderWorkbenchRestartMenuItem = ({
    itemKey,
    label,
    onClick,
  }: {
    itemKey: string
    label: string
    onClick: () => void
  }) => (
    <MenuItem key={itemKey} onClick={onClick} disabled={!currentRunId || running || restartLoading}>
      {label}
    </MenuItem>
  )

  const renderWorkbenchRestartMenuItems = () => {
    const items = [
      { itemKey: 'edit', label: '重新合成（EDIT）', onClick: () => triggerRestartFromStage('EDIT') },
      { itemKey: 'video', label: '从镜头视频（VIDEO）重跑', onClick: () => triggerRestartFromStage('VIDEO') },
      { itemKey: 'video-shots', label: '重跑指定镜头视频（VIDEO）…', onClick: requestRestartVideoShots },
      { itemKey: 'keyframes', label: '从关键帧（KEYFRAMES）重跑', onClick: () => triggerRestartFromStage('KEYFRAMES') },
      { itemKey: 'keyframe-cameras', label: '重跑指定相机关键帧（KEYFRAMES）…', onClick: requestRestartKeyframeCameras },
      { itemKey: 'storyboard', label: '从分镜（STORYBOARD）重跑', onClick: () => triggerRestartFromStage('STORYBOARD') },
      { itemKey: 'script', label: '从剧本（SCRIPT）重跑', onClick: () => triggerRestartFromStage('SCRIPT') },
    ]

    return items.map(renderWorkbenchRestartMenuItem)
  }

  const renderWorkbenchStatusChips = () => (
    <>
      {runId && <Chip label={`RunID: ${runId}`} size="small" />}
      <Chip label={`进度: ${progressLabel}%`} size="small" color="primary" />
      {stateLabel && <Chip label={`状态: ${stateLabel}`} size="small" />}
      {stageLabel && <Chip label={`阶段: ${stageLabel}`} size="small" />}
      {taskStatusLabel && (
        <Chip
          label={`任务: ${taskStatusLabel}${taskQueue ? `（${taskQueue}）` : ''}`}
          size="small"
          color={taskStatusColor}
        />
      )}
    </>
  )

  const renderWorkbenchStatusActionButton = ({
    label,
    onClick,
    disabled,
    startIcon,
  }: {
    label: string
    onClick: () => void
    disabled?: boolean
    startIcon?: JSX.Element
  }) => (
    <DreamweaverWorkbenchStatusActionButton
      label={label}
      onClick={onClick}
      disabled={disabled}
      startIcon={startIcon}
    />
  )

  const renderWorkbenchStatusPrimaryActions = () => {
    const items = [
      {
        label: '复制调试信息',
        onClick: copyDebugInfo,
        startIcon: <ContentCopyIcon fontSize="small" />,
      },
      {
        label: '诊断面板',
        onClick: openDiagnosticDialog,
        disabled: !currentRunId,
        startIcon: <BugReportIcon fontSize="small" />,
      },
      {
        label: '历史记录',
        onClick: openHistoryDialog,
        disabled: !selectedProjectId,
        startIcon: <HistoryIcon fontSize="small" />,
      },
      {
        label: '配置',
        onClick: openConfigDialog,
      },
    ]

    return items.map(renderWorkbenchStatusActionButton)
  }

  const renderWorkbenchStatusRestartAction = () => (
    <DreamweaverWorkbenchRestartAction
      label={restartLoading ? '重跑中…' : '重跑'}
      startIcon={<RefreshIcon fontSize="small" />}
      onClick={(e) => setRestartAnchorEl(e.currentTarget)}
      disabled={!currentRunId || running || restartLoading}
    />
  )

  const renderWorkbenchStatusActions = () => (
    <>
      {renderWorkbenchStatusPrimaryActions()}
      {renderWorkbenchStatusRestartAction()}
    </>
  )

  const renderWorkbenchRestartMenu = () => (
    <DreamweaverWorkbenchRestartMenu
      anchorEl={restartAnchorEl}
      open={Boolean(restartAnchorEl)}
      onClose={closeRestartMenu}
      items={renderWorkbenchRestartMenuItems()}
    />
  )

  const renderWorkbenchStatusRightActions = () => (
    <DreamweaverWorkbenchStatusRightActions
      followVisible={manualPreviewStep && previewStep !== progressStep}
      onFollow={followProgressStep}
    />
  )

  const renderWorkbenchStepper = () => (
    <DreamweaverWorkbenchStepper
      labels={DREAMWEAVER_PREVIEW_STEPS}
      activeStep={previewStep}
      progressStep={progressStep}
      onStepClick={handleClickStep}
    />
  )

  const renderWorkbenchStatusPanelPrimarySection = () => (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
      {renderWorkbenchStatusChips()}
      {renderWorkbenchStatusActions()}
      {renderWorkbenchRestartMenu()}
    </Stack>
  )

  const renderWorkbenchStatusPanel = () => (
    <DreamweaverWorkbenchStatusPanel
      primarySection={renderWorkbenchStatusPanelPrimarySection()}
      rightActions={renderWorkbenchStatusRightActions()}
      stepper={renderWorkbenchStepper()}
    />
  )

  const renderRunPageErrorAlert = () => {
    if (taskPointsPrecheckError) {
      return (
        <TaskPointsPrecheckAlert
          detail={taskPointsPrecheckError}
          onClose={clearTaskPointsPrecheckError}
          sx={{ mb: 2 }}
        />
      )
    }

    if (error) {
      return (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )
    }

    return null
  }

  const renderRunPageQcWarningAlert = () => {
    if (!result?.qc_warning) return null

    return (
      <Alert severity="warning" sx={{ mb: 2 }}>
        质检未通过，已按“仅警告”策略完成出片。建议在「合成/质检」查看 AutoQC 详情并视情况覆盖重跑修复。
      </Alert>
    )
  }

  const renderRunPagePreflightAlertMessage = () => {
    if (!diagnosticPreflight) return null

    return diagnosticPreflight.allowed
      ? `运行预检给出了 ${diagnosticPreflight.warnings.length} 条提示，建议在“诊断面板”查看路由与参数建议。`
      : `运行预检包含 ${diagnosticPreflight.errors.length} 条错误，当前配置存在阻断项，请先修正。`
  }

  const renderRunPagePreflightAlert = () => {
    if (!diagnosticPreflight || (diagnosticPreflight.allowed && diagnosticPreflight.warnings.length === 0)) {
      return null
    }

    return (
      <Alert severity={diagnosticPreflight.allowed ? 'warning' : 'error'} sx={{ mb: 2 }}>
        {renderRunPagePreflightAlertMessage()}
      </Alert>
    )
  }

  const renderRunPageHero = () => (
    <>
      <Button
        variant="text"
        startIcon={<ArrowBackIcon />}
        sx={{ color: 'white', mb: 2 }}
        onClick={() => navigate('/drama')}
      >
        返回项目列表
      </Button>

      <Typography variant="h4" sx={{ color: 'white', fontWeight: 700, mb: 0.5 }}>
        织梦映心 · 生成流程
      </Typography>
      <Typography variant="body1" sx={{ color: 'rgba(255,255,255,0.85)', mb: 3 }}>
        读取项目章节内容，生成分镜、首尾帧、分镜片段并合成成片；支持进度轮询与产物预览。
      </Typography>
    </>
  )

  const renderRunPageAlerts = () => (
    <>
      {renderRunPageErrorAlert()}
      {renderRunPageQcWarningAlert()}
      {renderRunPagePreflightAlert()}
    </>
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

  const renderWorkbenchCardHeader = () => (
    <Stack direction="row" spacing={1} alignItems="center" mb={1}>
      <Typography variant="h6" sx={{ fontWeight: 700 }}>
        短剧工作台
      </Typography>
      {running && <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, taskProgress))} sx={{ flex: 1 }} />}
    </Stack>
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

  const renderWorkbenchCardSections = () => (
    <>
      {renderWorkbenchCardHeader()}
      {renderWorkbenchStatusPanel()}
      {renderWorkbenchTaskHeader()}
      {renderWorkbenchMainContent()}
      {renderWorkbenchDialogs()}
    </>
  )

  const renderWorkbenchCard = () => (
    <Card sx={{ borderRadius: 3 }}>
      <CardContent>{renderWorkbenchCardSections()}</CardContent>
    </Card>
  )

  const renderRunWorkbenchMainColumn = () => (
    <Grid item xs={12} md={12}>
      {renderRunPageAlerts()}
      {renderWorkbenchCard()}
    </Grid>
  )

  const renderRunWorkbenchSection = () => (
    <Grid container spacing={2.5}>
      {renderRunWorkbenchMainColumn()}
    </Grid>
  )

  const renderRunPageContent = () => (
    <>
      {renderConfigDialog()}
      {renderRunWorkbenchSection()}
    </>
  )

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', py: 4 }}>
      <Container maxWidth="lg">
        {renderRunPageHero()}
        {renderRunPageContent()}
      </Container>
    </Box>
  )
}
