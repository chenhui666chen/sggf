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
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  ImageList,
  ImageListItem,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  Select,
  Stack,
  Step,
  StepLabel,
  Stepper,
  Switch,
  TextField,
  Typography,
  useMediaQuery,
} from '@mui/material'
import { useTheme } from '@mui/material/styles'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import BugReportIcon from '@mui/icons-material/BugReport'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import WarningIcon from '@mui/icons-material/Warning'
import { apiClient, extractApiErrorMessage } from '@/services/api'

// 织梦映心：生成流程页

const DREAMWEAVER_PREVIEW_STEPS = ['剧本', '分镜', '素材', '镜头', '合成'] as const

const DREAMWEAVER_RUN_STORAGE_PREFIX = 'dreamweaver:lastRun:'

interface PersistedDreamWeaverRun {
  project_id: number
  run_id: string
  task_id?: string | null
  status?: string | null
  quality_mode?: 'quality' | 'cost'
  qc_allow_fail?: boolean
  smart_tuning?: boolean
  video_require_confirmation?: boolean
  style_preset?: string
  image_ratio?: string
  image_resolution?: string
  video_fps?: number // legacy（曾误用为“帧率”，实际需求为分辨率）
  selected_chapter_ids?: number[]
  updated_at: number
}

function dreamweaverRunStorageKey(projectId: number) {
  return `${DREAMWEAVER_RUN_STORAGE_PREFIX}${projectId}`
}

function readPersistedDreamWeaverRun(projectId: number): PersistedDreamWeaverRun | null {
  try {
    const raw = localStorage.getItem(dreamweaverRunStorageKey(projectId))
    if (!raw) return null
    const obj = JSON.parse(raw) as PersistedDreamWeaverRun
    if (!obj || typeof obj !== 'object') return null
    if (typeof obj.run_id !== 'string' || !obj.run_id.trim()) return null
    return obj
  } catch {
    return null
  }
}

function writePersistedDreamWeaverRun(projectId: number, patch: Partial<PersistedDreamWeaverRun>) {
  try {
    const prev = readPersistedDreamWeaverRun(projectId)
    const next: PersistedDreamWeaverRun = {
      project_id: projectId,
      run_id: String(patch.run_id ?? prev?.run_id ?? '').trim(),
      task_id: patch.task_id ?? prev?.task_id ?? null,
      status: patch.status ?? prev?.status ?? null,
      quality_mode: patch.quality_mode ?? prev?.quality_mode,
      qc_allow_fail: patch.qc_allow_fail ?? prev?.qc_allow_fail,
      smart_tuning: patch.smart_tuning ?? prev?.smart_tuning,
      video_require_confirmation: patch.video_require_confirmation ?? prev?.video_require_confirmation,
      style_preset: patch.style_preset ?? prev?.style_preset,
      image_ratio: patch.image_ratio ?? prev?.image_ratio,
      image_resolution: patch.image_resolution ?? prev?.image_resolution,
      video_fps: patch.video_fps ?? prev?.video_fps,
      selected_chapter_ids: patch.selected_chapter_ids ?? prev?.selected_chapter_ids,
      updated_at: Date.now(),
    }
    if (!next.run_id) return
    localStorage.setItem(dreamweaverRunStorageKey(projectId), JSON.stringify(next))
  } catch {
    // ignore
  }
}

function clearPersistedDreamWeaverRun(projectId: number) {
  try {
    localStorage.removeItem(dreamweaverRunStorageKey(projectId))
  } catch {
    // ignore
  }
}

function stageToPreviewStep(stage: string | null | undefined): number {
  const value = (stage || '').trim().toLowerCase()
  if (!value) return 0
  if (value === 'init' || value === 'script' || value === 'waiting_script_approval') return 0
  if (value === 'storyboard') return 1
  if (value === 'asset_library' || value === 'waiting_approval') return 2
  if (value === 'keyframes' || value === 'midframes' || value === 'video' || value === 'waiting_video_confirmation') return 3
  if (value === 'edit' || value === 'review' || value === 'done' || value === 'rework' || value === 'failed') return 4
  return 0
}

function ratioToCssAspectRatio(value: string | null | undefined, fallback = '16 / 9'): string {
  const raw = String(value ?? '').trim()
  if (!raw) return fallback
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (!match) return fallback
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return fallback
  return `${width} / ${height}`
}

function ratioIsPortrait(value: string | null | undefined): boolean {
  const raw = String(value ?? '').trim()
  if (!raw) return false
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$/)
  if (!match) return false
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return false
  return height > width
}

interface Project {
  id: number
  title: string
  description?: string
}

interface Chapter {
  id: number
  chapter_number: number
  title: string
  content: string
}

interface RunResult {
  run_id: string
  state: string
  stage?: string | null
  progress?: number | null
  artifacts?: Record<string, any> | null
  source_chapter_count: number
  plan?: Record<string, any>
  storyboard?: any[]
  camera_tree_generation?: Record<string, any> | null
  camera_tree?: any[] | null
  camera_states?: any[] | null
  camera_scenes?: any[] | null
  keyframes?: any[]
  midframes?: any[]
  video_clips?: any[]
  merged_video?: string | null
  audit?: Record<string, any>
  autoqc?: Record<string, any>
  qc_warning?: Record<string, any>
}

interface TaskStatus {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'waiting'
  progress: number
  run_id?: string | null
  queue?: string | null
  state?: string | null
  stage?: string | null
  artifacts?: Record<string, any> | null
  error_type?: string | null
  result?: RunResult | null
  error?: string | null
}

interface LibraryAsset {
  id: number
  role: string
  uri: string
  meta?: Record<string, any>
}

interface LibraryPayload {
  project_id: number
  spec: Record<string, any>
  review: Record<string, any>
  assets: LibraryAsset[]
}

function extractMergedVideoFromContract(contract: any): string | null {
  const anchorSets = contract?.anchor_sets_ref
  const mergedFromAnchor = anchorSets?.merged_video?.uri
  if (typeof mergedFromAnchor === 'string' && mergedFromAnchor.trim()) return mergedFromAnchor.trim()

  const assets = Array.isArray(contract?.assets) ? contract.assets : []
  for (const item of assets) {
    const role = item && typeof item === 'object' ? String((item as any).role || '') : ''
    if (role !== 'merged_video') continue
    const uri = item && typeof item === 'object' ? (item as any).uri : null
    if (typeof uri === 'string' && uri.trim()) return uri.trim()
  }
  return null
}

function buildResultFromRunSnapshot(data: any, fallbackRunId: string): RunResult | null {
  const contract = data?.contract && typeof data.contract === 'object' ? data.contract : null
  if (!contract) return null

  const runtimeCfg = contract.runtime_config && typeof contract.runtime_config === 'object' ? contract.runtime_config : {}
  const chapterIds = Array.isArray(runtimeCfg.chapter_ids) ? runtimeCfg.chapter_ids : []
  let plan =
    runtimeCfg.plan && typeof runtimeCfg.plan === 'object'
      ? runtimeCfg.plan
      : typeof runtimeCfg.plan_text === 'string' && runtimeCfg.plan_text.trim()
        ? { text: runtimeCfg.plan_text.trim() }
        : undefined
  if (!plan) {
    const scriptText = typeof runtimeCfg.script_text === 'string' ? runtimeCfg.script_text : ''
    if (scriptText.trim()) {
      const lines = scriptText.split(/\r?\n/)
      const start = lines.findIndex((ln: string) => ln.trim() === '## 概要')
      if (start >= 0) {
        const picked: string[] = []
        for (const ln of lines.slice(start + 1)) {
          const s = ln.trim()
          if (!s) continue
          if (s.startsWith('## ')) break
          if (s.startsWith('-')) {
            picked.push(s)
            if (picked.length >= 6) break
          }
        }
        if (picked.length) plan = { text: picked.join('\n') }
      }
      if (!plan) plan = { text: scriptText.trim().slice(0, 280) }
    }
  }

  const storyboard: any[] = []
  const keyframes: any[] = []
  const midframes: any[] = []
  const videoClips: any[] = []

  const episodes = Array.isArray(contract.episodes) ? contract.episodes : []
  for (const ep of episodes) {
    const shots = ep && typeof ep === 'object' && Array.isArray((ep as any).shots) ? (ep as any).shots : []
    for (const shot of shots) {
      const shotSchemaV2 = shot?.shot_schema_v2 && typeof shot.shot_schema_v2 === 'object' ? shot.shot_schema_v2 : {}
      storyboard.push({
        scene_id: shot?.scene_id,
        shot_id: shot?.shot_key,
        desc: shot?.desc,
        duration_s: shot?.duration_s,
        cam_idx: shotSchemaV2?.cam_idx,
        visual_desc: shotSchemaV2?.visual_desc,
        ff_desc: shotSchemaV2?.ff_desc,
        lf_desc: shotSchemaV2?.lf_desc,
        motion_desc: shotSchemaV2?.motion_desc,
        audio_desc: shotSchemaV2?.audio_desc,
        ff_vis_char_ids: shotSchemaV2?.ff_vis_char_ids,
        lf_vis_char_ids: shotSchemaV2?.lf_vis_char_ids,
        head_frame: shot?.head_frame,
        tail_frame: shot?.tail_frame,
      })

      const assets = Array.isArray(shot?.assets) ? shot.assets : []
      for (const asset of assets) {
        const role = asset && typeof asset === 'object' ? String((asset as any).role || '') : ''
        const uri = asset && typeof asset === 'object' ? (asset as any).uri : null
        if (typeof uri !== 'string' || !uri.trim()) continue
        const meta = asset && typeof asset === 'object' && (asset as any).meta && typeof (asset as any).meta === 'object' ? (asset as any).meta : {}

        if (role === 'head_frame' || role === 'tail_frame') {
          keyframes.push({ path: uri, ratio: meta.ratio, spec: meta.spec, meta })
        } else if (role === 'mid_frame') {
          midframes.push({ path: uri, ratio: meta.ratio, spec: meta.spec, meta })
        } else if (role === 'video_clip') {
          videoClips.push({ path: uri, duration: meta.duration, head: meta.head, mid: meta.mid, tail: meta.tail, meta })
        }
      }
    }
  }

  const mergedVideo = extractMergedVideoFromContract(contract)
  const autoqc = contract.autoqc && typeof contract.autoqc === 'object' ? contract.autoqc : undefined

  const cameraTreeGeneration =
    runtimeCfg.camera_tree_generation && typeof runtimeCfg.camera_tree_generation === 'object' ? (runtimeCfg.camera_tree_generation as any) : undefined
  const cameraTree = Array.isArray(runtimeCfg.camera_tree) ? (runtimeCfg.camera_tree as any[]) : undefined
  const cameraStates = Array.isArray(runtimeCfg.camera_states) ? (runtimeCfg.camera_states as any[]) : undefined
  const cameraScenes = Array.isArray(runtimeCfg.camera_scenes) ? (runtimeCfg.camera_scenes as any[]) : undefined

  const runId = typeof data?.run_id === 'string' && data.run_id.trim() ? data.run_id.trim() : fallbackRunId
  const state = typeof data?.state === 'string' && data.state.trim() ? data.state.trim() : 'DONE'
  const stage = data?.stage != null ? String(data.stage) : null
  const progress = typeof data?.progress === 'number' ? data.progress : null

  return {
    run_id: runId,
    state,
    stage,
    progress,
    artifacts: null,
    source_chapter_count: chapterIds.length,
    plan,
    storyboard: storyboard.length ? storyboard : undefined,
    camera_tree_generation: cameraTreeGeneration ?? null,
    camera_tree: cameraTree ?? null,
    camera_states: cameraStates ?? null,
    camera_scenes: cameraScenes ?? null,
    keyframes: keyframes.length ? keyframes : undefined,
    midframes: midframes.length ? midframes : undefined,
    video_clips: videoClips.length ? videoClips : undefined,
    merged_video: mergedVideo,
    autoqc,
  }
}

function mergeRunResult(prev: RunResult | null, next: RunResult | null): RunResult | null {
  if (!prev) return next
  if (!next) return prev
  return {
    ...prev,
    ...next,
    plan: next.plan ?? prev.plan,
    storyboard: next.storyboard ?? prev.storyboard,
    camera_tree_generation: next.camera_tree_generation ?? prev.camera_tree_generation,
    camera_tree: next.camera_tree ?? prev.camera_tree,
    camera_states: next.camera_states ?? prev.camera_states,
    camera_scenes: next.camera_scenes ?? prev.camera_scenes,
    keyframes: next.keyframes ?? prev.keyframes,
    midframes: next.midframes ?? prev.midframes,
    video_clips: next.video_clips ?? prev.video_clips,
    merged_video: next.merged_video ?? prev.merged_video,
    audit: next.audit ?? prev.audit,
    autoqc: next.autoqc ?? prev.autoqc,
    qc_warning: next.qc_warning ?? prev.qc_warning,
  }
}

function libraryAssetToCssAspectRatio(asset: LibraryAsset, fallback: string): string {
  const meta = asset?.meta || {}
  const width = Number((meta as any).width)
  const height = Number((meta as any).height)
  if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
    return `${width} / ${height}`
  }
  const ratio = typeof (meta as any).ratio === 'string' ? String((meta as any).ratio).trim() : ''
  if (ratio) return ratioToCssAspectRatio(ratio, fallback)
  return fallback
}

interface DreamweaverRunSummary {
  run_id: string
  status: string
  state?: string | null
  stage?: string | null
  progress?: number | null
  schema_version?: string | null
  error_type?: string | null
  error_message?: string | null
  created_at?: string | null
  updated_at?: string | null
  camera_tree_mode?: string | null
  camera_count?: number | null
  camera_states_count?: number | null
  camera_scenes_count?: number | null
}

interface DreamweaverProjectLockedGenerationConfig {
  locked: boolean
  style_preset: string
  image_ratio: string
  image_resolution: string
  source_run_id?: string | null
}

export default function DreamWeaverRunPage() {
  const navigate = useNavigate()
  const { projectId: projectIdParam } = useParams()
  const theme = useTheme()
  const configDialogFullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const [projects, setProjects] = useState<Project[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [selectedChapterIds, setSelectedChapterIds] = useState<number[]>([])
  const [highQuality, setHighQuality] = useState(true)
  const [qcAllowFail, setQcAllowFail] = useState(false)
  const [smartTuning, setSmartTuning] = useState(true)
  const [videoRequireConfirmation, setVideoRequireConfirmation] = useState(true)
  const [abVariant, setAbVariant] = useState<string>('')
  const [stylePreset, setStylePreset] = useState<string>('cinematic_realistic')
  const [imageRatio, setImageRatio] = useState<string>('16:9')
  const [imageResolution, setImageResolution] = useState<string>('720p')
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [running, setRunning] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskRunId, setTaskRunId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<string | null>(null)
  const [taskQueue, setTaskQueue] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState<number>(0)
  const [taskState, setTaskState] = useState<string | null>(null)
  const [taskStage, setTaskStage] = useState<string | null>(null)
  const [taskArtifacts, setTaskArtifacts] = useState<Record<string, any> | null>(null)
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
  const [scriptEntities, setScriptEntities] = useState<Record<string, any> | null>(null)
  const [scriptGeneration, setScriptGeneration] = useState<{ mode?: string; model?: string | null; error?: string | null } | null>(null)
  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [libraryPreviews, setLibraryPreviews] = useState<Record<number, string>>({})
  const [mergedVideoLoading, setMergedVideoLoading] = useState(false)
  const [mergedVideoError, setMergedVideoError] = useState<string | null>(null)
  const [mergedVideoPreviewUrl, setMergedVideoPreviewUrl] = useState<string | null>(null)
  const [runAssetPreviews, setRunAssetPreviews] = useState<Record<string, string>>({})
  const [runAssetPreviewLoading, setRunAssetPreviewLoading] = useState<Record<string, boolean>>({})
  const [runAssetPreviewErrors, setRunAssetPreviewErrors] = useState<Record<string, string>>({})
  const runAssetPreviewsRef = useRef<Record<string, string>>({})
  const [regenOpen, setRegenOpen] = useState(false)
  const [regenRole, setRegenRole] = useState<string>('')
  const [regenTitle, setRegenTitle] = useState<string>('')
  const [regenPrompt, setRegenPrompt] = useState<string>('')
  const [regenSubmitting, setRegenSubmitting] = useState(false)
  const [regenError, setRegenError] = useState<string | null>(null)
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyRuns, setHistoryRuns] = useState<DreamweaverRunSummary[]>([])
  const [historyStatusFilters, setHistoryStatusFilters] = useState<string[]>([])

  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteSubmitting, setBulkDeleteSubmitting] = useState(false)
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null)
  const [bulkDeleteProgress, setBulkDeleteProgress] = useState<{ current: number; total: number } | null>(null)
  const [bulkDeleteResult, setBulkDeleteResult] = useState<{
    deleted: number
    skipped: number
    failed: number
    errors: string[]
  } | null>(null)

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

  const [runSnapshot, setRunSnapshot] = useState<Record<string, any> | null>(null)
  const [runSnapshotLoading, setRunSnapshotLoading] = useState(false)
  const [runSnapshotError, setRunSnapshotError] = useState<string | null>(null)

  const [previewStep, setPreviewStep] = useState(0)
  const [manualPreviewStep, setManualPreviewStep] = useState(false)

  const libraryPreviewAspectRatio = ratioToCssAspectRatio(imageRatio)
  const generationConfigLocked = Boolean(lockedGenerationConfig?.locked)
  const mergedVideoPreviewPortrait = ratioIsPortrait(
    generationConfigLocked ? lockedGenerationConfig?.image_ratio : imageRatio,
  )

  const videoDiagnostics = useMemo(() => {
    const clips = Array.isArray(result?.video_clips) ? (result?.video_clips as any[]) : []
    const viaSet = new Set<string>()
    let fallbackCount = 0
    let errorCount = 0
    for (const clip of clips) {
      const meta = clip && typeof clip === 'object' && (clip as any).meta && typeof (clip as any).meta === 'object' ? (clip as any).meta : null
      const via = meta && typeof (meta as any).via === 'string' ? String((meta as any).via) : ''
      if (via) viaSet.add(via)
      if (via.includes('fallback')) fallbackCount += 1
      const err = meta && typeof (meta as any).error === 'string' ? String((meta as any).error) : ''
      if (err.trim()) errorCount += 1
    }
    return { clipCount: clips.length, viaSummary: Array.from(viaSet).join(', '), fallbackCount, errorCount }
  }, [result?.video_clips])

  const candidateFrameUris = useMemo(() => {
    const uris: string[] = []
    const pushFromFrames = (frames: any[]) => {
      for (const frame of frames || []) {
        const meta = frame && typeof frame === 'object' && (frame as any).meta && typeof (frame as any).meta === 'object' ? (frame as any).meta : null
        if (!meta) continue
        const candidates = (meta as any).candidates
        if (!Array.isArray(candidates)) continue
        for (const item of candidates) {
          if (typeof item !== 'string') continue
          const uri = item.trim()
          if (!uri) continue
          uris.push(uri)
        }
      }
    }
    pushFromFrames(Array.isArray(result?.keyframes) ? (result?.keyframes as any[]) : [])
    pushFromFrames(Array.isArray(result?.midframes) ? (result?.midframes as any[]) : [])
    return Array.from(new Set(uris))
  }, [result?.keyframes, result?.midframes])

  const [configDialogOpen, setConfigDialogOpen] = useState(false)
  const autoOpenedConfigDialogRef = useRef(false)

  const autoLoadedScriptRunIdRef = useRef<string | null>(null)
  const autoLoadedRunSnapshotRunIdRef = useRef<string | null>(null)
  const restoredProjectIdRef = useRef<number | null>(null)
  const lockedGenerationConfigReqIdRef = useRef(0)

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

  const lockedProjectId = useMemo(() => {
    const parsed = Number(projectIdParam)
    if (!projectIdParam || !Number.isFinite(parsed)) return null
    return parsed
  }, [projectIdParam])

  const selectedProject = useMemo(() => {
    if (!selectedProjectId) return null
    return projects.find((p) => p.id === selectedProjectId) || null
  }, [projects, selectedProjectId])

  const formatPath = (value: any) => {
    if (!value || typeof value !== 'string') return null
    const parts = value.split(/[\\/]+/).filter(Boolean)
    return parts.slice(-2).join('/')
  }

  const formatPaths = (value: any) => {
    if (!Array.isArray(value)) return null
    const formatted = value.map(formatPath).filter(Boolean)
    return formatted.length ? formatted.join('  ') : null
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
          {items.map((uri) => {
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
                    {previewUrl ? (
                      kind === 'image' ? (
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
                      ) : (
                        <Box sx={{ mt: 0.75, bgcolor: '#000', borderRadius: 1, overflow: 'hidden' }}>
                          <Box component="video" src={previewUrl} controls sx={{ width: '100%', maxHeight: 240, display: 'block' }} />
                        </Box>
                      )
                    ) : (
                      <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">
                          未加载预览
                        </Typography>
                      </Box>
                    )}

                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                      <Button size="small" variant="outlined" onClick={() => loadRunAssetPreview(uri)} disabled={!currentRunId || loading}>
                        {loading ? '加载中…' : previewUrl ? '重新加载' : '加载预览'}
                      </Button>
                      <Button size="small" variant="text" onClick={() => downloadRunAsset(uri)} disabled={!currentRunId || loading}>
                        下载
                      </Button>
                      {formatPath(uri) && <Chip size="small" label={formatPath(uri)} variant="outlined" />}
                    </Stack>

                    {err && (
                      <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5, wordBreak: 'break-all' }}>
                        {err}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              </Grid>
            )
          })}
        </Grid>
      </Box>
    )
  }

  const formatDateTime = (value: any) => {
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

  const safeJsonStringify = (value: any) => {
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
      result,
    }

    await copyText(safeJsonStringify(payload))
  }

  const renderDiagnosticJson = (value: any) => {
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
          maxHeight: 320,
          overflow: 'auto',
        }}
      >
        {safeJsonStringify(value)}
      </Box>
    )
  }

  const renderDiagnosticFrame = (title: string, frame: any, kind: 'image' | 'video' = 'image') => {
    if (!frame || typeof frame !== 'object') return null
    const uri = String((frame as any).path || '').trim()
    if (!uri) return null
    const meta = (frame as any).meta && typeof (frame as any).meta === 'object' ? ((frame as any).meta as any) : {}
    const decision = meta.decision && typeof meta.decision === 'object' ? (meta.decision as any) : null
    const via = typeof meta.via === 'string' ? meta.via : ''
    const mode = decision && typeof decision.mode === 'string' ? String(decision.mode) : ''
    const reason = decision && typeof decision.reason === 'string' ? String(decision.reason) : ''
    const selector = typeof meta.selector === 'string' ? meta.selector : ''
    const candidateCount = typeof meta.candidate_count === 'number' ? meta.candidate_count : null
    const selected = typeof meta.selected === 'number' ? meta.selected : null
    const selectedSeed = typeof meta.selected_seed === 'number' ? meta.selected_seed : null
    const candidates = Array.isArray(meta.candidates) ? (meta.candidates as any[]) : []
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
        const runs = Array.isArray(res.data) ? (res.data as DreamweaverRunSummary[]) : []
        setHistoryRuns(runs)
      } catch (e: any) {
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

  const handleViewHistoryRun = (runId: string) => {
    if (!selectedProjectId) return
    const nextRunId = String(runId || '').trim()
    if (!nextRunId) return

    setError(null)
    setResult(null)
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

    setPreviewStep(0)
    setManualPreviewStep(false)

    writePersistedDreamWeaverRun(selectedProjectId, { run_id: nextRunId, task_id: null, status: null })
    void hydrateFromPersistedRun(selectedProjectId, nextRunId, null)
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
        setLockedGenerationConfig((res.data as any) || null)
        setLockedGenerationConfigError(null)
      } catch (e: any) {
        setLockedGenerationConfig(null)
        setLockedGenerationConfigError(await extractApiErrorMessage(e, '加载项目锁定配置失败'))
      }
      setDeleteDialogOpen(false)
      setDeleteRunId(null)
    } catch (e: any) {
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
      } catch (e: any) {
        const msg = await extractApiErrorMessage(e, '删除失败')
        errors.push(`${runId}: ${msg}`)
      } finally {
        setBulkDeleteProgress({ current: i + 1, total: targets.length })
      }
    }

    try {
      await fetchRunHistory(selectedProjectId)
    } catch (e: any) {
      // ignore
    }
    try {
      await refreshLockedGenerationConfig(selectedProjectId)
    } catch (e: any) {
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
  ) => {
    if (!runId) return
    try {
      const res = await apiClient.getDreamweaverRun(runId)
      const data = (res.data as any) || {}
      setRunSnapshot(data)
      setRunSnapshotError(null)

      const status = String(data.status || '').trim()
      const statusLower = status.toLowerCase()
      const stage = data.stage != null ? String(data.stage) : null
      const state = data.state != null ? String(data.state) : null
      const progress = typeof data.progress === 'number' ? data.progress : 0
      const contract = data.contract && typeof data.contract === 'object' ? (data.contract as any) : null

      setTaskStatus(status || null)
      setTaskProgress(progress)
      setTaskStage(stage)
      setTaskState(state)

      const waitingKind = String(stage || state || '').trim().toLowerCase()
      const waiting =
        statusLower === 'waiting' ||
        waitingKind === 'waiting_script_approval' ||
        waitingKind === 'waiting_approval' ||
        waitingKind === 'waiting_video_confirmation'
      setWaitingApproval(waiting)

      const isRunning = statusLower === 'running' || statusLower === 'queued'
      setRunning(isRunning)

      if (statusLower === 'completed' && contract) {
        const nextResult = buildResultFromRunSnapshot(data, runId)
        if (nextResult) setResult((prev) => mergeRunResult(prev, nextResult))
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
    } catch (e: any) {
      if (e?.response?.status === 404) {
        clearPersistedDreamWeaverRun(projectId)
      }
      setRunSnapshotError(await extractApiErrorMessage(e, '恢复运行状态失败'))
    }
  }

  useEffect(() => {
    const loadProjects = async () => {
      try {
        const res = await apiClient.getProjects()
        setProjects(res.data || [])
      } catch (e: any) {
        setError(e?.message || '获取项目列表失败')
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
    if (persisted.image_ratio) setImageRatio(persisted.image_ratio)
    if (persisted.image_resolution) setImageResolution(persisted.image_resolution)

    void hydrateFromPersistedRun(selectedProjectId, persisted.run_id, persisted.task_id ?? null)
  }, [selectedProjectId])

  useEffect(() => {
    if (!selectedProjectId) return
    if (!lockedGenerationConfig?.locked) return
    if (lockedGenerationConfig.style_preset) setStylePreset(lockedGenerationConfig.style_preset)
    if (lockedGenerationConfig.image_ratio) setImageRatio(lockedGenerationConfig.image_ratio)
    if (lockedGenerationConfig.image_resolution) setImageResolution(lockedGenerationConfig.image_resolution)
  }, [lockedGenerationConfig, selectedProjectId])

  useEffect(() => {
    if (!selectedProjectId) return
    const runId = taskRunId || result?.run_id || null
    if (!runId) return
    writePersistedDreamWeaverRun(selectedProjectId, {
      run_id: runId,
      task_id: taskId,
      status: taskStatus,
      quality_mode: highQuality ? 'quality' : 'cost',
      qc_allow_fail: qcAllowFail,
      smart_tuning: smartTuning,
      video_require_confirmation: videoRequireConfirmation,
      style_preset: stylePreset,
      image_ratio: imageRatio,
      image_resolution: imageResolution,
      selected_chapter_ids: selectedChapterIds,
    })
  }, [highQuality, imageRatio, imageResolution, qcAllowFail, smartTuning, videoRequireConfirmation, result?.run_id, selectedChapterIds, selectedProjectId, stylePreset, taskId, taskRunId, taskStatus])

  useEffect(() => {
    if (!taskId) return

    let cancelled = false
    let timer: any = null

    const poll = async () => {
      try {
        const res = await apiClient.getDreamweaverTask(taskId)
        const data = res.data as TaskStatus
        if (cancelled) return
        setError(null)

        if (data.status === 'queued') {
          setRunning(true)
          setTaskStatus('queued')
          setTaskQueue((data.queue as any) || null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts((data.artifacts as any) || null)
          setTaskRunId((prev) => data.run_id || prev)
          setWaitingApproval(false)
          timer = setTimeout(poll, 1000)
          return
        }

        if (data.status === 'running') {
          setTaskStatus('running')
          setTaskQueue((data.queue as any) || null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts((data.artifacts as any) || null)
          setTaskRunId((prev) => data.run_id || prev)
          setWaitingApproval(false)
          timer = setTimeout(poll, 1000)
          return
        }

        if (data.status === 'waiting') {
          setTaskStatus('waiting')
          setTaskQueue((data.queue as any) || null)
          setRunning(false)
          setTaskId(null)
          setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
          setTaskState(data.state || null)
          setTaskStage(data.stage || null)
          setTaskArtifacts((data.artifacts as any) || null)
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
          setResult((prev) => mergeRunResult(prev, (data.result as any) || null))
        } else {
          setError(data.error || '任务执行失败')
        }
      } catch (e: any) {
        if (cancelled) return
        const message = await extractApiErrorMessage(e, '任务状态查询失败')
        const status = typeof e?.response?.status === 'number' ? Number(e.response.status) : null
        const isTimeout = String(e?.message || '').toLowerCase().includes('timeout')
        const isNetworkError = !e?.response

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
      setLockedGenerationConfig((res.data as any) || null)
    } catch (e: any) {
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
    setLoadingChapters(true)
    try {
      const res = await apiClient.getChapters(projectId)
      const data = res.data as Chapter[]
      setChapters(data)
      setSelectedChapterIds(data.map((c) => c.id))
    } catch (e: any) {
      setError(e?.message || '加载章节失败')
      setChapters([])
      setSelectedChapterIds([])
    } finally {
      setLoadingChapters(false)
    }
  }, [clearRunAssetPreviews, refreshLockedGenerationConfig])

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
    setError(null)
    setLibrary(null)
    setLibraryError(null)
    setLibraryPreviews({})
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
    clearRunAssetPreviews()
    try {
      const res = await apiClient.runDreamweaverAsync(selectedProjectId, selectedChapterIds, {
        quality_mode: highQuality ? 'quality' : 'cost',
        qc_allow_fail: qcAllowFail,
        smart_tuning: smartTuning,
        ab_variant: abVariant.trim() ? abVariant.trim() : undefined,
        video_require_confirmation: videoRequireConfirmation,
        style_preset: stylePreset,
        image_ratio: imageRatio,
        image_resolution: imageResolution,
      })
      const data = res.data as { task_id: string; run_id: string; status: string }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
      setTaskStatus(data.status || 'queued')
      void refreshLockedGenerationConfig(selectedProjectId)
      return true
    } catch (e: any) {
      setError(await extractApiErrorMessage(e, '任务提交失败'))
      setRunning(false)
      return false
    } finally {
      // running 状态由轮询结束时关闭
    }
  }

  useEffect(() => {
    return () => {
      Object.values(libraryPreviews).forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
    }
  }, [libraryPreviews])

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

  const scriptDirty = scriptText !== scriptSavedText
  const waitingKind = (taskStage || taskState || '').toString().toLowerCase()
  const waitingScriptApproval = waitingApproval && waitingKind === 'waiting_script_approval'
  const waitingVideoConfirmation = waitingApproval && waitingKind === 'waiting_video_confirmation'
  const persistedRunId = taskRunId || result?.run_id || null
  const currentRunId = persistedRunId
  const libraryApproved = Boolean(library?.review?.approved)
  const snapshotRuntimeCfg =
    runSnapshot?.contract && typeof (runSnapshot as any).contract === 'object' && (runSnapshot as any).contract.runtime_config && typeof (runSnapshot as any).contract.runtime_config === 'object'
      ? ((runSnapshot as any).contract.runtime_config as any)
      : {}
  const videoClipJobs: any[] = Array.isArray(snapshotRuntimeCfg.video_clip_jobs) ? (snapshotRuntimeCfg.video_clip_jobs as any[]) : []
  const canResumeFromScript =
    Boolean(currentRunId) && !scriptLoading && !resumeLoading && !scriptDirty && (!scriptRequiresReview || scriptApproved)
  const canResumeFromLibrary = Boolean(currentRunId) && !libraryLoading && !resumeLoading && libraryApproved

  const loadRunSnapshot = useCallback(async () => {
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.getDreamweaverRun(persistedRunId)
      const data = (res.data as any) || null
      setRunSnapshot(data)
      if (String(data?.status || '').trim().toLowerCase() === 'completed') {
        const nextResult = buildResultFromRunSnapshot(data, persistedRunId)
        if (nextResult) setResult((prev) => mergeRunResult(prev, nextResult))
      }
    } catch (e: any) {
      setRunSnapshotError(await extractApiErrorMessage(e, '加载运行快照失败'))
    } finally {
      setRunSnapshotLoading(false)
    }
  }, [persistedRunId])

  const rebuildVideoJobs = useCallback(async () => {
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.rebuildDreamweaverVideoJobs(persistedRunId)
      const jobs = Array.isArray((res.data as any)?.video_clip_jobs) ? ((res.data as any).video_clip_jobs as any[]) : null
      if (!jobs) {
        await loadRunSnapshot()
        return
      }

      if (!runSnapshot) {
        await loadRunSnapshot()
        return
      }

      setRunSnapshot((prev) => {
        if (!prev || typeof prev !== 'object') return prev
        const prevAny = prev as any
        const contract = prevAny.contract && typeof prevAny.contract === 'object' ? { ...prevAny.contract } : {}
        const runtimeCfg =
          contract.runtime_config && typeof contract.runtime_config === 'object' ? { ...contract.runtime_config } : {}
        runtimeCfg.video_clip_jobs = jobs
        contract.runtime_config = runtimeCfg
        return { ...prevAny, contract }
      })
    } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
      setMergedVideoError(await extractApiErrorMessage(e, '下载合成视频失败'))
    } finally {
      setMergedVideoLoading(false)
    }
  }, [currentRunId, result?.merged_video])

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
      } catch (e: any) {
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
      } catch (e: any) {
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
      const data = res.data as any
      const text = typeof data?.script_text === 'string' ? data.script_text : ''
      setScriptText(text)
      setScriptSavedText(text)
      setScriptApproved(Boolean(data?.script_review?.approved))
      setScriptRequiresReview(Boolean(data?.script_requires_review))
      setScriptEntities((data?.script_entities as any) || null)
      setScriptGeneration((data?.script_generation as any) || null)
    } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
      setScriptError(await extractApiErrorMessage(e, '更新剧本审核状态失败'))
    } finally {
      setScriptLoading(false)
    }
  }

  const loadLibrary = async (): Promise<string | null> => {
    if (!selectedProjectId) return '未选择项目'
    setLibraryLoading(true)
    setLibraryError(null)
    setLibrary(null)
    setLibraryPreviews({})
    try {
      const scopedRunId = typeof currentRunId === 'string' && currentRunId.trim() ? currentRunId.trim() : null
      const res = await apiClient.getDreamweaverLibrary(selectedProjectId, scopedRunId ? { run_id: scopedRunId } : undefined)
      const data = res.data as LibraryPayload
      setLibrary(data)

      const assets = Array.isArray(data.assets) ? data.assets : []
      const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data.review!.missing_roles as string[]) : []
      const missingRoleSet = new Set(missingRoles.map((r) => String(r || '').trim()).filter((r) => r))
      const previewEntries = await Promise.all(
        assets
          .filter((asset) => !missingRoleSet.has(String(asset?.role || '').trim()))
          .map(async (asset) => {
          try {
            const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
            const url = URL.createObjectURL(fileRes.data)
            return [asset.id, url] as const
          } catch {
            return [asset.id, ''] as const
          }
        }),
      )
      const previewMap: Record<number, string> = {}
      for (const [assetId, url] of previewEntries) {
        if (url) previewMap[assetId] = url
      }
      setLibraryPreviews(previewMap)
      return null
    } catch (e: any) {
      const message = await extractApiErrorMessage(e, '加载素材库失败')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }

  const approveLibrary = async (payload: { approve_all?: boolean; roles?: string[]; approved?: boolean }) => {
    if (!selectedProjectId) return
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.approveDreamweaverLibrary(selectedProjectId, payload)
      await loadLibrary()
    } catch (e: any) {
      setLibraryError(await extractApiErrorMessage(e, '更新审核状态失败'))
    } finally {
      setLibraryLoading(false)
    }
  }

  const regenerateLibraryAsset = async (role: string, prompt?: string): Promise<string | null> => {
    if (!selectedProjectId) return '未选择项目'
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.regenerateDreamweaverLibraryAsset(selectedProjectId, { role, ...(prompt ? { prompt } : {}) })
      return await loadLibrary()
    } catch (e: any) {
      const message = await extractApiErrorMessage(e, '重新生成失败')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }

  const openRegenerateDialog = (asset: LibraryAsset) => {
    const role = String(asset.role || '').trim()
    if (!role) return
    const title = String(asset.meta?.entity_name || asset.role || '').trim() || role
    const prompt = String(asset.meta?.prompt || '').trim()
    setRegenRole(role)
    setRegenTitle(title)
    setRegenPrompt(prompt)
    setRegenError(null)
    setRegenOpen(true)
  }

  const submitRegenerateDialog = async () => {
    const role = String(regenRole || '').trim()
    if (!role || !selectedProjectId) return
    setRegenSubmitting(true)
    setRegenError(null)
    try {
      const err = await regenerateLibraryAsset(role, regenPrompt.trim())
      if (err) {
        setRegenError(err)
        return
      }
      setRegenOpen(false)
    } finally {
      setRegenSubmitting(false)
    }
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
      const data = res.data as { task_id: string; run_id: string; status: string }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
      setTaskStatus(data.status || 'queued')
    } catch (e: any) {
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
      const data = (res.data as any) || {}
      const statusRaw = String(data.status || '').trim().toLowerCase()
      const message = data.message != null ? String(data.message || '').trim() : ''
      const jobs = Array.isArray(data.video_clip_jobs) ? (data.video_clip_jobs as any[]) : null

      if (jobs && runSnapshot) {
        setRunSnapshot((prev) => {
          if (!prev || typeof prev !== 'object') return prev
          const prevAny = prev as any
          const contract = prevAny.contract && typeof prevAny.contract === 'object' ? { ...prevAny.contract } : {}
          const runtimeCfg =
            contract.runtime_config && typeof contract.runtime_config === 'object' ? { ...contract.runtime_config } : {}
          runtimeCfg.video_clip_jobs = jobs
          contract.runtime_config = runtimeCfg
          return { ...prevAny, contract }
        })
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
    } catch (e: any) {
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
    clearRunAssetPreviews()

    try {
      const res = await apiClient.restartDreamweaverAsync(currentRunId, {
        start_state: startStateRaw,
        reset_policy: 'downstream',
        qc_allow_fail: qcAllowFail,
        smart_tuning: smartTuning,
        ...(normalizedShotIds.length > 0 ? { shot_ids: normalizedShotIds } : {}),
        ...(normalizedCamIdxs.length > 0 ? { cam_idxs: normalizedCamIdxs } : {}),
      })
      const data = res.data as { task_id: string; run_id: string; status: string }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id || currentRunId)
      setTaskStatus(data.status || 'queued')
    } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
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

  const snapshotShots = useMemo(() => {
    const episodes = (runSnapshot as any)?.contract?.episodes
    if (!Array.isArray(episodes)) return []
    const shots: any[] = []
    for (const ep of episodes) {
      const epShots = (ep as any)?.shots
      if (Array.isArray(epShots)) shots.push(...epShots)
    }
    return shots
  }, [runSnapshot])

  const snapshotAssetCount = useMemo(() => {
    return snapshotShots.reduce((acc, shot) => {
      const assets = (shot as any)?.assets
      return acc + (Array.isArray(assets) ? assets.length : 0)
    }, 0)
  }, [snapshotShots])

  const snapshotContract = useMemo(() => {
    const contract = (runSnapshot as any)?.contract
    return contract && typeof contract === 'object' ? (contract as any) : null
  }, [runSnapshot])

  const snapshotRuntimeConfig = useMemo(() => {
    const runtimeCfg = snapshotContract?.runtime_config
    return runtimeCfg && typeof runtimeCfg === 'object' ? (runtimeCfg as any) : {}
  }, [snapshotContract])

  const snapshotCameraDiagnostics = useMemo(() => {
    const generation = snapshotRuntimeConfig?.camera_tree_generation
    const cameraTree = Array.isArray(snapshotRuntimeConfig?.camera_tree) ? (snapshotRuntimeConfig.camera_tree as any[]) : null
    const cameraStates = Array.isArray(snapshotRuntimeConfig?.camera_states) ? (snapshotRuntimeConfig.camera_states as any[]) : null
    const cameraScenes = Array.isArray(snapshotRuntimeConfig?.camera_scenes) ? (snapshotRuntimeConfig.camera_scenes as any[]) : null
    const sceneUris = (cameraScenes || [])
      .map((item) =>
        item && typeof item === 'object' && typeof (item as any).scene_uri === 'string' ? String((item as any).scene_uri || '').trim() : '',
      )
      .filter(Boolean)
    const mode = generation && typeof generation === 'object' && typeof (generation as any).mode === 'string' ? String((generation as any).mode) : null
    return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
  }, [snapshotRuntimeConfig])

  const snapshotTelemetry = useMemo(() => {
    const telemetry = snapshotRuntimeConfig?.telemetry
    return telemetry && typeof telemetry === 'object' ? (telemetry as any) : null
  }, [snapshotRuntimeConfig])

  const snapshotTelemetrySummary = useMemo(() => {
    if (!snapshotTelemetry) return null

    const startedAt = typeof snapshotTelemetry.run_started_at === 'number' ? Number(snapshotTelemetry.run_started_at) : null
    const finishedAt = typeof snapshotTelemetry.run_finished_at === 'number' ? Number(snapshotTelemetry.run_finished_at) : null
    const totalS = startedAt != null && finishedAt != null && finishedAt >= startedAt ? finishedAt - startedAt : null

    const terminalState = typeof snapshotTelemetry.terminal_state === 'string' ? String(snapshotTelemetry.terminal_state) : null
    const reworkCount = typeof snapshotTelemetry.rework_count === 'number' ? Number(snapshotTelemetry.rework_count) : null
    const reworkByType =
      snapshotTelemetry.rework_by_type && typeof snapshotTelemetry.rework_by_type === 'object' ? (snapshotTelemetry.rework_by_type as any) : null

    const stagesRaw = snapshotTelemetry.stages && typeof snapshotTelemetry.stages === 'object' ? (snapshotTelemetry.stages as any) : {}
    const stageOrder = ['init', 'script', 'storyboard', 'asset_library', 'keyframes', 'midframes', 'video', 'edit', 'review']
    const stageEntries = Object.entries(stagesRaw)
      .map(([stage, value]) => {
        const item = value && typeof value === 'object' ? (value as any) : {}
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
    const raw = snapshotTelemetry?.counters
    if (!raw || typeof raw !== 'object') return []

    const entries: { name: string; value: number }[] = []
    for (const [name, value] of Object.entries(raw as any)) {
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
    const plan = snapshotRuntimeConfig?.plan
    if (plan && typeof plan === 'object' && typeof (plan as any).text === 'string') return String((plan as any).text)
    if (typeof snapshotRuntimeConfig?.plan_text === 'string' && snapshotRuntimeConfig.plan_text.trim()) return snapshotRuntimeConfig.plan_text.trim()
    return ''
  }, [snapshotRuntimeConfig])

  const snapshotScriptText = useMemo(() => {
    return typeof snapshotRuntimeConfig?.script_text === 'string' ? snapshotRuntimeConfig.script_text : ''
  }, [snapshotRuntimeConfig])

  const snapshotScriptApproved = useMemo(() => {
    const review = snapshotRuntimeConfig?.script_review
    return Boolean(review && typeof review === 'object' && Boolean((review as any).approved))
  }, [snapshotRuntimeConfig])

  const snapshotMergedVideo = useMemo(() => {
    return snapshotContract ? extractMergedVideoFromContract(snapshotContract) : null
  }, [snapshotContract])

  const snapshotAssetSummary = useMemo(() => {
    const keyframes: string[] = []
    const midframes: string[] = []
    const videoClips: { path: string; meta: any }[] = []
    for (const shot of snapshotShots) {
      const assets = Array.isArray((shot as any)?.assets) ? ((shot as any).assets as any[]) : []
      for (const asset of assets) {
        const role = asset && typeof asset === 'object' ? String((asset as any).role || '') : ''
        const uri = asset && typeof asset === 'object' ? (asset as any).uri : null
        if (typeof uri !== 'string' || !uri.trim()) continue
        const meta = asset && typeof asset === 'object' && (asset as any).meta && typeof (asset as any).meta === 'object' ? (asset as any).meta : {}

        if (role === 'head_frame' || role === 'tail_frame') keyframes.push(uri)
        else if (role === 'mid_frame') midframes.push(uri)
        else if (role === 'video_clip') videoClips.push({ path: uri, meta })
      }
    }
    return { keyframes, midframes, videoClips }
  }, [snapshotShots])

  const diagnosticResult = useMemo(() => {
    if (result) return result
    if (!runSnapshot) return null
    const fallback =
      persistedRunId || (typeof (runSnapshot as any)?.run_id === 'string' ? String((runSnapshot as any).run_id).trim() : '')
    if (!fallback) return buildResultFromRunSnapshot(runSnapshot, 'unknown')
    return buildResultFromRunSnapshot(runSnapshot, fallback)
  }, [persistedRunId, result, runSnapshot])

  const diagnosticCameraDiagnostics = useMemo(() => {
    const snapshotHasAny =
      Boolean(snapshotCameraDiagnostics.cameraTree && snapshotCameraDiagnostics.cameraTree.length) ||
      Boolean(snapshotCameraDiagnostics.cameraStates && snapshotCameraDiagnostics.cameraStates.length) ||
      Boolean(snapshotCameraDiagnostics.cameraScenes && snapshotCameraDiagnostics.cameraScenes.length) ||
      Boolean(snapshotCameraDiagnostics.generation)
    if (snapshotHasAny) return snapshotCameraDiagnostics

    const res: any = diagnosticResult && typeof diagnosticResult === 'object' ? (diagnosticResult as any) : null
    const generation = res?.camera_tree_generation && typeof res.camera_tree_generation === 'object' ? (res.camera_tree_generation as any) : null
    const cameraTree = Array.isArray(res?.camera_tree) ? (res.camera_tree as any[]) : null
    const cameraStates = Array.isArray(res?.camera_states) ? (res.camera_states as any[]) : null
    const cameraScenes = Array.isArray(res?.camera_scenes) ? (res.camera_scenes as any[]) : null
    const sceneUris = (cameraScenes || [])
      .map((item) =>
        item && typeof item === 'object' && typeof (item as any).scene_uri === 'string' ? String((item as any).scene_uri || '').trim() : '',
      )
      .filter(Boolean)
    const mode = generation && typeof (generation as any).mode === 'string' ? String((generation as any).mode) : null
    const resultHasAny = Boolean(generation) || Boolean(cameraTree && cameraTree.length) || Boolean(cameraStates && cameraStates.length) || Boolean(cameraScenes && cameraScenes.length)
    if (!resultHasAny) return snapshotCameraDiagnostics

    return { generation, cameraTree, cameraStates, cameraScenes, sceneUris, mode }
  }, [diagnosticResult, snapshotCameraDiagnostics])

  const diagnosticShots = useMemo(() => {
    const res = diagnosticResult
    if (!res) return []

    const map = new Map<string, any>()
    const ensure = (shotId: string) => {
      const key = String(shotId || '').trim()
      if (!key) return null
      if (!map.has(key)) map.set(key, { shot_id: key })
      return map.get(key)
    }

    const storyboard = Array.isArray(res.storyboard) ? (res.storyboard as any[]) : []
    for (const item of storyboard) {
      const shotId = item && typeof item === 'object' ? String((item as any).shot_id || '').trim() : ''
      const node = ensure(shotId)
      if (!node) continue
      node.storyboard = item
    }

    const parseFrameUri = (uri: string) => {
      const name = String(uri || '').split(/[\\/]+/).pop() || ''
      if (name.endsWith('_head.png')) return { shot_id: name.slice(0, -'_head.png'.length), role: 'head' as const }
      if (name.endsWith('_tail.png')) return { shot_id: name.slice(0, -'_tail.png'.length), role: 'tail' as const }
      if (name.endsWith('_mid.png')) return { shot_id: name.slice(0, -'_mid.png'.length), role: 'mid' as const }
      return { shot_id: '', role: null as any }
    }

    const parseClipUri = (uri: string) => {
      const name = String(uri || '').split(/[\\/]+/).pop() || ''
      if (!name) return ''
      const parts = name.split('.')
      if (parts.length < 2) return ''
      return parts.slice(0, -1).join('.')
    }

    const keyframes = Array.isArray(res.keyframes) ? (res.keyframes as any[]) : []
    for (const frame of keyframes) {
      const uri = frame && typeof frame === 'object' ? String((frame as any).path || '').trim() : ''
      if (!uri) continue
      const parsed = parseFrameUri(uri)
      if (!parsed.shot_id || !parsed.role) continue
      const node = ensure(parsed.shot_id)
      if (!node) continue
      node.frames = node.frames || {}
      node.frames[parsed.role] = frame
    }

    const midframes = Array.isArray(res.midframes) ? (res.midframes as any[]) : []
    for (const frame of midframes) {
      const uri = frame && typeof frame === 'object' ? String((frame as any).path || '').trim() : ''
      if (!uri) continue
      const parsed = parseFrameUri(uri)
      if (!parsed.shot_id) continue
      const node = ensure(parsed.shot_id)
      if (!node) continue
      node.frames = node.frames || {}
      node.frames.mid = frame
    }

    const clips = Array.isArray(res.video_clips) ? (res.video_clips as any[]) : []
    for (const clip of clips) {
      const uri = clip && typeof clip === 'object' ? String((clip as any).path || '').trim() : ''
      if (!uri) continue
      const shotId = parseClipUri(uri)
      if (!shotId) continue
      const node = ensure(shotId)
      if (!node) continue
      node.video_clip = clip
    }

    const ordered: any[] = []
    const pushed = new Set<string>()
    for (const item of storyboard) {
      const shotId = item && typeof item === 'object' ? String((item as any).shot_id || '').trim() : ''
      if (!shotId || pushed.has(shotId)) continue
      const node = map.get(shotId)
      if (node) {
        ordered.push(node)
        pushed.add(shotId)
      }
    }
    const rest = Array.from(map.values()).filter((n) => n && typeof n === 'object' && !pushed.has(String((n as any).shot_id || '')))
    rest.sort((a, b) => String((a as any).shot_id || '').localeCompare(String((b as any).shot_id || ''), 'zh-CN'))
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

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', py: 4 }}>
      <Container maxWidth="lg">
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

        <Dialog
          open={configDialogOpen}
          onClose={() => setConfigDialogOpen(false)}
          fullScreen={configDialogFullScreen}
          maxWidth="md"
          fullWidth
        >
          <DialogTitle sx={{ pb: 1 }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="h6" sx={{ fontWeight: 800 }}>
                  生成配置
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {(selectedProject?.title || (selectedProjectId ? `项目 #${selectedProjectId}` : '请选择项目')) +
                    (chapters.length ? ` · 已选 ${selectedChapterIds.length}/${chapters.length} 章` : '')}
                </Typography>
              </Box>
              <IconButton onClick={() => setConfigDialogOpen(false)} size="small" aria-label="关闭">
                <CloseIcon fontSize="small" />
              </IconButton>
            </Stack>
          </DialogTitle>
          <DialogContent dividers sx={{ pt: 2 }}>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            <Stack spacing={2}>
              {lockedProjectId ? (
                <Box
                  sx={{
                    p: 1.5,
                    borderRadius: 2,
                    border: '1px solid rgba(0,0,0,0.08)',
                    bgcolor: 'rgba(0,0,0,0.04)',
                  }}
                >
                  <Typography variant="caption" color="text.secondary" display="block">
                    当前项目
                  </Typography>
                  <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                    {selectedProject?.title || `项目 #${lockedProjectId}`}
                  </Typography>
                </Box>
              ) : (
                <Alert
                  severity="info"
                  action={
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => {
                        setConfigDialogOpen(false)
                        navigate('/drama')
                      }}
                    >
                      去项目列表
                    </Button>
                  }
                >
                  请先在项目列表选择一个项目，再进入生成配置。
                </Alert>
              )}

              <Grid container spacing={2}>
                <Grid item xs={12} md={7}>
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                        章节选择
                      </Typography>
                      <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
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
                      </Stack>
                    </Stack>

                    <Box
                      sx={{
                        maxHeight: configDialogFullScreen ? '55vh' : 360,
                        overflow: 'auto',
                        border: '1px solid rgba(0,0,0,0.08)',
                        borderRadius: 2,
                      }}
                    >
                      {loadingChapters ? (
                        <LinearProgress />
                      ) : (
                        <List dense disablePadding>
                          {chapters.map((c) => {
                            const raw = String(c.content || '').replace(/\s+/g, ' ').trim()
                            const snippet = raw ? (raw.length > 64 ? raw.slice(0, 64) + '…' : raw) : '（无正文）'
                            return (
                              <ListItem
                                key={c.id}
                                disablePadding
                                secondaryAction={
                                  <Checkbox
                                    edge="end"
                                    size="small"
                                    disabled={running}
                                    checked={selectedChapterIds.includes(c.id)}
                                    onChange={() => handleToggleChapter(c.id)}
                                  />
                                }
                              >
                                <ListItemButton
                                  onClick={() => handleToggleChapter(c.id)}
                                  disabled={running}
                                  sx={{ pr: 6 }}
                                >
                                  <ListItemText
                                    primary={`${c.chapter_number}. ${c.title || '未命名章节'}`}
                                    secondary={snippet}
                                  />
                                </ListItemButton>
                              </ListItem>
                            )
                          })}
                        </List>
                      )}
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                      至少选择 1 个章节；默认全选可直接开始生成。
                    </Typography>
                  </Paper>
                </Grid>

                <Grid item xs={12} md={5}>
                  <Stack spacing={2}>
                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1 }}>
                        生成策略
                      </Typography>

                      <Stack spacing={1.5}>
                        <Stack spacing={0.5}>
                          <Stack direction="row" alignItems="center" justifyContent="space-between">
                            <Typography variant="body2" sx={{ fontWeight: 700 }}>
                              成本 / 质量
                            </Typography>
                            <FormControlLabel
                              sx={{ mr: 0 }}
                              control={<Switch checked={highQuality} onChange={(e) => setHighQuality(e.target.checked)} disabled={running} />}
                              label={highQuality ? '最高质量' : '低成本'}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            {highQuality ? '多候选 + 语义评选 + 图片编辑 + 语义质检' : '单候选 + 关闭编辑/语义质检'}
                          </Typography>
                        </Stack>

                        <Stack spacing={0.5}>
                          <Stack direction="row" alignItems="center" justifyContent="space-between">
                            <Typography variant="body2" sx={{ fontWeight: 700 }}>
                              智能调参
                            </Typography>
                            <FormControlLabel
                              sx={{ mr: 0 }}
                              control={<Switch checked={smartTuning} onChange={(e) => setSmartTuning(e.target.checked)} disabled={running} />}
                              label={smartTuning ? '智能调参' : '手动调参'}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            质量优先：按镜头规模自动调候选数与语义质检预算。
                          </Typography>
                        </Stack>

                        <Stack spacing={0.5}>
                          <Stack direction="row" alignItems="center" justifyContent="space-between">
                            <Typography variant="body2" sx={{ fontWeight: 700 }}>
                              视频逐段确认
                            </Typography>
                            <FormControlLabel
                              sx={{ mr: 0 }}
                              control={
                                <Switch
                                  checked={videoRequireConfirmation}
                                  onChange={(e) => setVideoRequireConfirmation(e.target.checked)}
                                  disabled={running}
                                />
                              }
                              label={videoRequireConfirmation ? '逐段确认' : '自动生成'}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            VIDEO 阶段先生成任务卡，确认后按镜头生成视频；桥接依赖会自动阻塞提示。
                          </Typography>
                        </Stack>

                        <Stack spacing={0.5}>
	                          <Stack direction="row" alignItems="center" justifyContent="space-between">
	                            <Typography variant="body2" sx={{ fontWeight: 700 }}>
	                              质检失败处理
	                            </Typography>
                            <FormControlLabel
                              sx={{ mr: 0 }}
                              control={<Switch checked={qcAllowFail} onChange={(e) => setQcAllowFail(e.target.checked)} disabled={running} />}
                              label={qcAllowFail ? '仅警告' : '严格拦截'}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
	                            AutoQC 失败可仅警告放行；文件校验（audit）仍会拦截。
	                          </Typography>
	                        </Stack>

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
	                      </Stack>
	                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
	                        性能提示：关键帧镜头级并发由后端环境变量 `DREAMWEAVER_KEYFRAMES_PARALLELISM` 控制，建议先从 `2` 开始，避免把上游 QPS 打满。
	                      </Typography>
	                    </Paper>

                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1 }}>
                        画面设置
                      </Typography>
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
                      <Grid container spacing={1.5}>
                        <Grid item xs={12}>
                          <FormControl fullWidth size="small" disabled={running || lockedGenerationConfigLoading || generationConfigLocked}>
                            <InputLabel id="style-preset-label">风格预设</InputLabel>
                            <Select
                              labelId="style-preset-label"
                              value={stylePreset}
                              label="风格预设"
                              onChange={(e) => setStylePreset(String(e.target.value))}
                            >
                              <MenuItem value="cinematic_realistic">电影写实</MenuItem>
                              <MenuItem value="anime">二次元动画</MenuItem>
                              <MenuItem value="ink_wash">国风水墨</MenuItem>
                              <MenuItem value="cyberpunk">赛博朋克</MenuItem>
                            </Select>
                          </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={6}>
                          <FormControl fullWidth size="small" disabled={running || lockedGenerationConfigLoading || generationConfigLocked}>
                            <InputLabel id="image-ratio-label">画面比例</InputLabel>
                            <Select
                              labelId="image-ratio-label"
                              value={imageRatio}
                              label="画面比例"
                              onChange={(e) => setImageRatio(String(e.target.value))}
                            >
                              <MenuItem value="16:9">横屏 16:9</MenuItem>
                              <MenuItem value="9:16">竖屏 9:16</MenuItem>
                            </Select>
                          </FormControl>
                        </Grid>
                        <Grid item xs={12} sm={6}>
                          <FormControl fullWidth size="small" disabled={running || lockedGenerationConfigLoading || generationConfigLocked}>
                            <InputLabel id="image-resolution-label">分辨率</InputLabel>
                            <Select
                              labelId="image-resolution-label"
                              value={imageResolution}
                              label="分辨率"
                              onChange={(e) => setImageResolution(String(e.target.value))}
                            >
                              <MenuItem value="720p">720p</MenuItem>
                              <MenuItem value="1080p">1080p</MenuItem>
                            </Select>
                          </FormControl>
                        </Grid>
                      </Grid>
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                        比例决定横/竖屏；分辨率影响素材库、关键帧与合成视频输出尺寸。
                      </Typography>
                    </Paper>
                  </Stack>
                </Grid>
              </Grid>
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setConfigDialogOpen(false)}>关闭</Button>
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={async () => {
                const ok = await handleRun()
                if (ok) setConfigDialogOpen(false)
              }}
              disabled={running || lockedGenerationConfigLoading || !selectedProjectId || selectedChapterIds.length === 0}
            >
              开始生成
            </Button>
          </DialogActions>
        </Dialog>

        <Grid container spacing={2.5}>
          <Grid item xs={12} md={12}>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            {result?.qc_warning && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                质检未通过，已按“仅警告”策略完成出片。建议在「合成/质检」查看 AutoQC 详情并视情况覆盖重跑修复。
              </Alert>
            )}

            <Card sx={{ borderRadius: 3 }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" mb={1}>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    短剧工作台
                  </Typography>
                  {running && <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, taskProgress))} sx={{ flex: 1 }} />}
                </Stack>

                <Paper sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.95)', mb: 2 }}>
                  <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="space-between" mb={1}>
                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
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
                        onClick={() => {
                          setDiagnosticActionError(null)
                          setDiagnosticOpen(true)
                        }}
                        disabled={!currentRunId}
                      >
                        诊断面板
                      </Button>
                      <Button
                        size="small"
                        variant="text"
                        startIcon={<HistoryIcon fontSize="small" />}
                        onClick={openHistoryDialog}
                        disabled={!selectedProjectId}
                      >
                        历史记录
                      </Button>
                       <Button size="small" variant="text" onClick={() => setConfigDialogOpen(true)}>
                         配置
                       </Button>
                       <Button
                         size="small"
                         variant="text"
                         startIcon={<RefreshIcon fontSize="small" />}
                         onClick={(e) => setRestartAnchorEl(e.currentTarget)}
                         disabled={!currentRunId || running || restartLoading}
                       >
                         {restartLoading ? '重跑中…' : '重跑'}
                       </Button>
                       <Menu
                         anchorEl={restartAnchorEl}
                         open={Boolean(restartAnchorEl)}
                         onClose={() => setRestartAnchorEl(null)}
                         anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                         transformOrigin={{ vertical: 'top', horizontal: 'left' }}
                       >
                         <MenuItem
                           onClick={() => {
                             setRestartAnchorEl(null)
                             void restartGeneration('EDIT')
                           }}
                           disabled={!currentRunId || running || restartLoading}
                         >
                           重新合成（EDIT）
                         </MenuItem>
                         <MenuItem
                           onClick={() => {
                             setRestartAnchorEl(null)
                             void restartGeneration('VIDEO')
                           }}
                           disabled={!currentRunId || running || restartLoading}
                         >
                           从镜头视频（VIDEO）重跑
                         </MenuItem>
                         <MenuItem
                           onClick={() => {
                             setRestartAnchorEl(null)
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
                           }}
                           disabled={!currentRunId || running || restartLoading}
                         >
                           重跑指定镜头视频（VIDEO）…
                         </MenuItem>
                          <MenuItem
                            onClick={() => {
                              setRestartAnchorEl(null)
                              void restartGeneration('KEYFRAMES')
                            }}
                            disabled={!currentRunId || running || restartLoading}
                          >
                            从关键帧（KEYFRAMES）重跑
                          </MenuItem>
                          <MenuItem
                            onClick={() => {
                              setRestartAnchorEl(null)
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
                            }}
                            disabled={!currentRunId || running || restartLoading}
                          >
                            重跑指定相机关键帧（KEYFRAMES）…
                          </MenuItem>
                          <MenuItem
                            onClick={() => {
                              setRestartAnchorEl(null)
                              void restartGeneration('STORYBOARD')
                           }}
                           disabled={!currentRunId || running || restartLoading}
                         >
                           从分镜（STORYBOARD）重跑
                         </MenuItem>
                         <MenuItem
                           onClick={() => {
                             setRestartAnchorEl(null)
                             void restartGeneration('SCRIPT')
                           }}
                           disabled={!currentRunId || running || restartLoading}
                         >
                           从剧本（SCRIPT）重跑
                         </MenuItem>
                       </Menu>
                     </Stack>
                     <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" justifyContent="flex-end">
                       {manualPreviewStep && previewStep !== progressStep && (
                         <Button size="small" variant="text" onClick={followProgressStep}>
                          跟随进度
                        </Button>
                      )}
                    </Stack>
                  </Stack>

                  <Stepper activeStep={previewStep}>
                    {DREAMWEAVER_PREVIEW_STEPS.map((label, idx) => (
                      <Step key={label} completed={idx < progressStep} sx={{ cursor: 'pointer', px: 0.5 }} onClick={() => handleClickStep(idx)}>
                        <StepLabel
                          sx={{
                            '& .MuiStepLabel-label': {
                              cursor: 'pointer',
                              fontSize: '0.9rem',
                              transition: 'color 0.2s, transform 0.2s',
                              '&:hover': {
                                color: 'primary.main',
                                transform: 'scale(1.03)',
                              },
                            },
                          }}
                        >
                          {label}
                        </StepLabel>
                      </Step>
                    ))}
                  </Stepper>
                </Paper>
                {!result ? (
                  running ? (
                    <Box>
                      {taskStatus === 'queued' && (
                        <Alert severity="info" sx={{ mb: 1 }}>
                          任务已入队排队中{taskQueue ? `（队列：${taskQueue}）` : ''}。若长期无进度，请确认 Celery worker 正在运行并监听该队列。
                        </Alert>
                      )}
                      {previewStep === 0 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          剧本预览：当前为运行中阶段，进入“剧本待审核”后可加载/编辑/通过。
                        </Typography>
                      )}
                      {previewStep === 1 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          分镜预览：将展示镜头数量与分镜阶段信息（后续可升级为镜头列表/分镜卡）。
                        </Typography>
                      )}
                      {previewStep === 2 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          素材预览：素材库在生成后可在此加载并逐项审核。
                        </Typography>
                      )}
                      {previewStep === 3 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          镜头预览：关键帧/中间帧/片段生成将逐步更新计数与产物路径。
                        </Typography>
                      )}
                      {previewStep === 4 && (
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          合成预览：合成视频与质检结果将在后续阶段产出。
                        </Typography>
                      )}

                      {persistedRunId && (
                        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" mb={1}>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={loadRunSnapshot}
                            disabled={!persistedRunId || runSnapshotLoading}
                          >
                            {runSnapshotLoading ? '加载中…' : '刷新运行快照'}
                          </Button>
                          {runSnapshot && runSnapshot.run_id === persistedRunId && (
                            <Chip size="small" label="快照已加载" color="success" />
                          )}
                        </Stack>
                      )}
                      {runSnapshotError && (
                        <Alert severity="error" sx={{ mb: 1 }}>
                          {runSnapshotError}
                        </Alert>
                      )}
                      {runSnapshotLoading && <LinearProgress sx={{ mb: 1 }} />}

                      {previewStep === 0 && !runSnapshotLoading && (
                        <Box sx={{ mb: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            计划 / 剧本提要（快照）
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>
                            {snapshotPlanText.trim() || '暂无计划/提要快照（可能仍在生成或尚未落库）。'}
                          </Typography>

                          {snapshotScriptText.trim() ? (
                            <Accordion>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                    剧本（快照）
                                  </Typography>
                                  <Chip size="small" label={snapshotScriptApproved ? '已通过' : '未通过'} color={snapshotScriptApproved ? 'success' : 'default'} />
                                  <Chip size="small" label={`长度: ${snapshotScriptText.length}`} />
                                </Stack>
                              </AccordionSummary>
                              <AccordionDetails>
                                <Box
                                  sx={{
                                    whiteSpace: 'pre-wrap',
                                    fontFamily: 'monospace',
                                    fontSize: 12,
                                    bgcolor: '#fafafa',
                                    border: '1px solid #eee',
                                    borderRadius: 2,
                                    p: 1.5,
                                    maxHeight: 260,
                                    overflow: 'auto',
                                  }}
                                >
                                  {snapshotScriptText.length > 6000 ? `${snapshotScriptText.slice(0, 6000)}\n…` : snapshotScriptText}
                                </Box>
                              </AccordionDetails>
                            </Accordion>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              尚无可用剧本快照（可能仍在生成，或尚未落库）。
                            </Typography>
                          )}
                        </Box>
                      )}

                      {previewStep === 1 && !runSnapshotLoading && (
                        <Box sx={{ mb: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            镜头列表
                          </Typography>
                          {snapshotShots.length ? (
                            <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                              {snapshotShots.slice(0, 12).map((shot: any) => (
                                <ListItem key={shot.shot_key || shot.shot_index} disablePadding sx={{ px: 1, py: 0.25 }}>
                                  <ListItemText
                                    primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                    secondary={`场景: ${shot.scene_id || '-'}  时长: ${typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s`}
                                  />
                                </ListItem>
                              ))}
                            </List>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              尚无可用分镜快照（可能仍在生成，或尚未落库）。
                            </Typography>
                          )}
                        </Box>
                      )}

                        {previewStep === 3 && !runSnapshotLoading && snapshotShots.length > 0 && (
                          <Box sx={{ mb: 1 }}>
                            <Stack direction="row" spacing={1} flexWrap="wrap" mb={0.5}>
                              <Chip size="small" label={`镜头: ${snapshotShots.length}`} />
                              <Chip size="small" label={`资产: ${snapshotAssetCount}`} />
                              <Chip size="small" label={`KF: ${snapshotAssetSummary.keyframes.length}`} />
                              <Chip size="small" label={`MF: ${snapshotAssetSummary.midframes.length}`} />
                              <Chip size="small" label={`VC: ${snapshotAssetSummary.videoClips.length}`} />
                            </Stack>
                            {(snapshotAssetSummary.keyframes.length > 0 || snapshotAssetSummary.midframes.length > 0 || snapshotAssetSummary.videoClips.length > 0) && (
                              <Typography variant="caption" color="text.secondary" display="block">
                                快照路径：
                                {formatPaths(snapshotAssetSummary.keyframes.slice(-3)) ? `KF ${formatPaths(snapshotAssetSummary.keyframes.slice(-3))}` : ''}
                                {formatPaths(snapshotAssetSummary.midframes.slice(-3)) ? `  MF ${formatPaths(snapshotAssetSummary.midframes.slice(-3))}` : ''}
                                {formatPaths(snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path)) ? `  VC ${formatPaths(snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path))}` : ''}
                              </Typography>
                            )}
                            {renderRunAssetPreviewGrid('关键帧（快照）', snapshotAssetSummary.keyframes.slice(-6), 'image')}
                            {renderRunAssetPreviewGrid('中间帧（快照）', snapshotAssetSummary.midframes.slice(-6), 'image')}
                            {renderRunAssetPreviewGrid(
                              '镜头片段（快照）',
                              snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path),
                              'video',
                            )}
                          </Box>
                        )}

                      {previewStep === 4 && !runSnapshotLoading && (
                        <Box sx={{ mb: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            合成视频（快照）
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {snapshotMergedVideo ? `合成视频：${snapshotMergedVideo}` : '暂无合成视频快照'}
                          </Typography>
                          {snapshotMergedVideo && (
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
                            </Stack>
                          )}
                          {mergedVideoError && (
                            <Alert severity="error" sx={{ mt: 1 }}>
                              {mergedVideoError}
                            </Alert>
                          )}
                          {mergedVideoPreviewUrl && (
                            <Box sx={{ mt: 1, bgcolor: '#000', borderRadius: 2, overflow: 'hidden' }}>
                              <Box component="video" src={mergedVideoPreviewUrl} controls sx={{ width: '100%', display: 'block' }} />
                            </Box>
                          )}
                        </Box>
                      )}
                      <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
                        {taskArtifacts?.storyboard_count != null && (
                          <Chip label={`SB: ${taskArtifacts.storyboard_count}`} size="small" />
                        )}
                        {taskArtifacts?.keyframes_count != null && (
                          <Chip label={`KF: ${taskArtifacts.keyframes_count}`} size="small" />
                        )}
                        {taskArtifacts?.midframes_count != null && (
                          <Chip label={`MF: ${taskArtifacts.midframes_count}`} size="small" />
                        )}
                        {taskArtifacts?.video_clips_count != null && (
                          <Chip label={`VC: ${taskArtifacts.video_clips_count}`} size="small" />
                        )}
                        {taskArtifacts?.stage_artifacts?.camera_tree_mode && (
                          <Chip label={`CamTree: ${taskArtifacts.stage_artifacts.camera_tree_mode}`} size="small" variant="outlined" />
                        )}
                        {taskArtifacts?.stage_artifacts?.camera_count != null && (
                          <Chip label={`Cam: ${taskArtifacts.stage_artifacts.camera_count}`} size="small" />
                        )}
                        {taskArtifacts?.stage_artifacts?.camera_states_count != null && (
                          <Chip label={`CamState: ${taskArtifacts.stage_artifacts.camera_states_count}`} size="small" />
                        )}
                        {taskArtifacts?.stage_artifacts?.camera_scenes_count != null && (
                          <Chip label={`CamScene: ${taskArtifacts.stage_artifacts.camera_scenes_count}`} size="small" />
                        )}
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
                          onClick={() => {
                            setDiagnosticActionError(null)
                            setDiagnosticOpen(true)
                          }}
                          disabled={!currentRunId}
                        >
                          诊断面板
                        </Button>
                      </Stack>
                      {(taskArtifacts?.last_keyframe_path || taskArtifacts?.last_midframe_path || taskArtifacts?.last_video_clip_path) && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Last: {formatPath(taskArtifacts.last_keyframe_path) ? `KF ${formatPath(taskArtifacts.last_keyframe_path)}` : ''}
                          {formatPath(taskArtifacts.last_midframe_path) ? `  MF ${formatPath(taskArtifacts.last_midframe_path)}` : ''}
                          {formatPath(taskArtifacts.last_video_clip_path) ? `  VC ${formatPath(taskArtifacts.last_video_clip_path)}` : ''}
                        </Typography>
                      )}
                      {(taskArtifacts?.keyframes_tail_paths || taskArtifacts?.midframes_tail_paths || taskArtifacts?.video_clips_tail_paths) && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          {formatPaths(taskArtifacts.keyframes_tail_paths) ? `KF: ${formatPaths(taskArtifacts.keyframes_tail_paths)}` : ''}
                          {formatPaths(taskArtifacts.midframes_tail_paths) ? `  MF: ${formatPaths(taskArtifacts.midframes_tail_paths)}` : ''}
                          {formatPaths(taskArtifacts.video_clips_tail_paths) ? `  VC: ${formatPaths(taskArtifacts.video_clips_tail_paths)}` : ''}
                        </Typography>
                      )}
                      {taskArtifacts?.rework_reason && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Rework: {JSON.stringify(taskArtifacts.rework_reason)}
                        </Typography>
                      )}
                      {taskArtifacts?.stage_artifacts && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                          Stage artifacts: {JSON.stringify(taskArtifacts.stage_artifacts)}
                        </Typography>
                      )}
                      <Typography variant="body2" color="text.secondary">
                        任务执行中，完成后将自动展示分镜/首尾帧/视频产物。
                      </Typography>
                      <Accordion sx={{ mt: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            调试面板（Artifacts）
                          </Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Box
                            sx={{
                              whiteSpace: 'pre-wrap',
                              fontFamily: 'monospace',
                              fontSize: 12,
                              bgcolor: '#fafafa',
                              border: '1px solid #eee',
                              borderRadius: 2,
                              p: 1.5,
                            }}
                          >
                            {JSON.stringify(taskArtifacts, null, 2)}
                          </Box>
                        </AccordionDetails>
                      </Accordion>
                    </Box>
                  ) : waitingApproval ? (
                    waitingScriptApproval ? (
                      previewStep === 0 ? (
                      <Box>
                        <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
                          {scriptGenerationLabel && <Chip label={`剧本生成: ${scriptGenerationLabel}`} size="small" />}
                          {scriptDirty && <Chip label="未保存" size="small" color="warning" />}
                        </Stack>

                        {scriptRequiresReview ? (
                          scriptApproved ? (
                            <Alert severity="success" sx={{ mb: 1 }}>
                              剧本已通过：现在可以点击“继续生成”进入分镜与素材库阶段。
                            </Alert>
                          ) : (
                            <Alert severity="warning" sx={{ mb: 1 }}>
                              剧本待审核：请先加载/编辑剧本并点击“通过”，通过后再继续生成分镜与素材库。
                            </Alert>
                          )
                        ) : (
                          <Alert severity="info" sx={{ mb: 1 }}>
                            当前配置无需剧本审核：可直接点击“继续生成”进入分镜与素材库阶段。
                          </Alert>
                        )}
                        {scriptDirty && (
                          <Alert severity="info" sx={{ mb: 1 }}>
                            剧本已修改但未保存：请先点击“保存”，再点击“通过”。
                          </Alert>
                        )}
                        {scriptGeneration?.mode === 'rule_fallback' && scriptGeneration?.error && (
                          <Alert severity="info" sx={{ mb: 1 }}>
                            LLM 调用失败，已回退为规则剧本：{scriptGeneration.error}
                            <br />
                            建议检查 `.env` 的 `DASHSCOPE_API_KEY` / `DASHSCOPE_API_BASE` 以及 `DREAMWEAVER_*_MODEL`（如 `qwen-plus`），并重启后端与 Celery worker。
                          </Alert>
                        )}

                        <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
                          <Button size="small" variant="contained" onClick={loadScript} disabled={!currentRunId || scriptLoading}>
                            加载剧本
                          </Button>
                          <Button
                            size="small"
                            variant="outlined"
                            onClick={saveScript}
                            disabled={!currentRunId || scriptLoading || !scriptDirty || !scriptText.trim()}
                          >
                            保存
                          </Button>
                          <Button
                            size="small"
                            variant="contained"
                            color="success"
                            onClick={() => approveScript(true)}
                            disabled={!currentRunId || scriptLoading || scriptDirty || !scriptText.trim()}
                          >
                            通过
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            onClick={() => approveScript(false)}
                            disabled={!currentRunId || scriptLoading || !scriptApproved}
                          >
                            撤销通过
                          </Button>
                          <Button
                            size="small"
                            variant="contained"
                            color="success"
                            onClick={resumeGeneration}
                            disabled={!canResumeFromScript}
                          >
                            {resumeLoading ? '继续生成中…' : '继续生成'}
                          </Button>
                        </Stack>

                        {scriptError && (
                          <Alert severity="error" sx={{ mb: 1 }}>
                            {scriptError}
                          </Alert>
                        )}

                        {scriptLoading && <LinearProgress sx={{ mb: 1 }} />}

                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                          审核状态：{scriptRequiresReview ? (scriptApproved ? '已通过' : '待审核') : '无需审核'}
                          {scriptGenerationLabel ? `  生成：${scriptGenerationLabel}` : ''}
                          {scriptEntities
                            ? `  实体：角色 ${Array.isArray((scriptEntities as any).characters) ? (scriptEntities as any).characters.length : 0}，场景 ${Array.isArray((scriptEntities as any).scenes) ? (scriptEntities as any).scenes.length : 0}，道具 ${Array.isArray((scriptEntities as any).props) ? (scriptEntities as any).props.length : 0}`
                            : ''}
                        </Typography>

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

                        <Accordion sx={{ mt: 1 }}>
                          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                              调试面板（Artifacts）
                            </Typography>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Box
                              sx={{
                                whiteSpace: 'pre-wrap',
                                fontFamily: 'monospace',
                                fontSize: 12,
                                bgcolor: '#fafafa',
                                border: '1px solid #eee',
                                borderRadius: 2,
                                p: 1.5,
                              }}
                            >
                              {JSON.stringify(taskArtifacts, null, 2)}
                            </Box>
                          </AccordionDetails>
                        </Accordion>
                      </Box>
                    ) : (
                      <Alert
                        severity={scriptRequiresReview && !scriptApproved ? 'info' : 'success'}
                        sx={{ mb: 1 }}
                        action={
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Button size="small" variant="text" onClick={() => handleClickStep(0)}>
                              查看剧本
                            </Button>
                            <Button size="small" variant="contained" color="success" onClick={resumeGeneration} disabled={!canResumeFromScript}>
                              {resumeLoading ? '继续生成中…' : '继续生成'}
                            </Button>
                          </Stack>
                        }
                      >
                        {scriptRequiresReview && !scriptApproved
                          ? '剧本待审核：请先在“剧本”完成审核；审核通过后可继续生成。'
                          : '剧本审核已完成：可继续生成进入分镜与素材库阶段。'}
                      </Alert>
                    )
                  ) : waitingVideoConfirmation ? (
                    previewStep === 3 ? (
                      <Box>
                        <Alert severity="info" sx={{ mb: 1 }}>
                          当前阶段启用“逐镜头确认生成”：点击卡片右侧按钮确认/触发生成；若镜头需要“上一镜头尾帧→本镜头首帧”桥接，依赖未就绪时会保持阻塞。
                        </Alert>

                        {videoJobActionError && (
                          <Alert severity="error" sx={{ mb: 1 }}>
                            {videoJobActionError}
                          </Alert>
                        )}

                        <Stack direction="row" spacing={1} flexWrap="wrap" mb={1}>
                          <Button size="small" variant="outlined" onClick={rebuildVideoJobs} disabled={!persistedRunId || runSnapshotLoading}>
                            {runSnapshotLoading ? '刷新中…' : '刷新任务卡'}
                          </Button>
                        </Stack>

                        {videoClipJobs.length ? (
                          <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                            {videoClipJobs.map((job: any, idx: number) => {
                              const sid = String(job?.shot_id || '').trim()
                              const desc = String(job?.desc || '').trim()
                              const status = String(job?.status || '').trim().toLowerCase()
                              const confirmed = Boolean(job?.confirmed)
                              const requiresBridge = Boolean(job?.requires_bridge)
                              const dep = String(job?.depends_on_shot_id || '').trim()

                              const statusLabel =
                                status === 'done'
                                  ? '已生成'
                                  : status === 'blocked'
                                    ? '依赖未就绪'
                                    : status === 'confirmed'
                                      ? '已确认'
                                      : '待确认'

                              const confirming = videoJobConfirmingShotId === sid
                              const disabled = !sid || running || confirming || status === 'done'
                              const actionLabel =
                                status === 'done'
                                  ? '已生成'
                                  : confirming
                                    ? '处理中…'
                                    : confirmed
                                      ? '开始生成'
                                      : requiresBridge
                                        ? '确认（桥接）'
                                        : '确认生成'

                              return (
                                <ListItem
                                  key={sid || String(idx)}
                                  disableGutters
                                  sx={{ px: 1, py: 0.75, borderBottom: '1px solid #f0f0f0', alignItems: 'flex-start' }}
                                >
                                  <Box sx={{ flex: 1, minWidth: 0 }}>
                                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
                                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                        {sid || '(unknown)'}
                                      </Typography>
                                      <Chip size="small" label={statusLabel} color={status === 'done' ? 'success' : status === 'blocked' ? 'warning' : 'default'} />
                                      {confirmed && status !== 'done' && <Chip size="small" label="已确认" color="primary" />}
                                      {requiresBridge && <Chip size="small" label={`桥接依赖: ${dep || '-'}`} />}
                                    </Stack>
                                    {desc && (
                                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                                        {desc}
                                      </Typography>
                                    )}
                                  </Box>

                                  <Box sx={{ pl: 1 }}>
                                    <Button size="small" variant="contained" onClick={() => confirmVideoJob(sid)} disabled={disabled}>
                                      {actionLabel}
                                    </Button>
                                  </Box>
                                </ListItem>
                              )
                            })}
                          </List>
                        ) : (
                          <Alert severity="warning">未找到视频任务卡（video_clip_jobs）。可点击“刷新任务卡”或重试生成到 VIDEO 阶段。</Alert>
                        )}
                      </Box>
                    ) : (
                      <Alert
                        severity="info"
                        sx={{ mb: 1 }}
                        action={
                          <Button size="small" variant="text" onClick={() => handleClickStep(3)}>
                            查看视频任务卡
                          </Button>
                        }
                      >
                        当前阶段正在等待镜头视频确认：请切换到“镜头/视频”查看并逐段确认生成。
                      </Alert>
                    )
                  ) : (
                    previewStep === 2 ? (
                      <Box>

                      <Alert severity={libraryApproved ? 'success' : 'warning'} sx={{ mb: 1 }}>
                        {libraryApproved
                          ? '素材库已审核通过：可点击“继续生成”进入镜头阶段。'
                          : '素材库待审核：请先审核角色/场景/道具素材库，确认后点击“继续生成”。'}
                      </Alert>
 
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

                      {libraryError && (
                        <Alert severity="error" sx={{ mb: 1 }}>
                          {libraryError}
                        </Alert>
                      )}

                      {libraryLoading && <LinearProgress sx={{ mb: 1 }} />}

                      {library?.review && (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                          审核状态：缺失 {Array.isArray(library.review.missing_roles) ? library.review.missing_roles.length : 0}，未通过{' '}
                          {Array.isArray(library.review.unapproved_roles) ? library.review.unapproved_roles.length : 0}
                        </Typography>
                      )}

                      {library?.assets?.length ? (
                        <ImageList cols={3} gap={8} sx={{ m: 0 }}>
                          {library.assets.map((asset) => {
                            const approved = Boolean(asset.meta?.approved)
                            const title = asset.meta?.entity_name || asset.role
                            const preview = libraryPreviews[asset.id]
                            const aspectRatio = libraryAssetToCssAspectRatio(asset, libraryPreviewAspectRatio)
                            return (
                              <ImageListItem key={asset.id} sx={{ border: '1px solid #eee', borderRadius: 2, overflow: 'hidden' }}>
                                <Box sx={{ width: '100%', aspectRatio, bgcolor: '#f5f5f5', position: 'relative' }}>
                                  {preview && (
                                    <Box
                                      component="img"
                                      src={preview}
                                      alt={title}
                                      loading="lazy"
                                      sx={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                                    />
                                  )}
                                </Box>
                                <Box sx={{ p: 1 }}>
                                  <Typography variant="caption" sx={{ fontWeight: 600 }} display="block">
                                    {title}
                                  </Typography>
                                  <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
                                    <Chip size="small" label={approved ? '已通过' : '待审核'} color={approved ? 'success' : 'default'} />
                                    <Button
                                      size="small"
                                      variant="text"
                                      onClick={() => approveLibrary({ roles: [asset.role], approved: !approved })}
                                      disabled={libraryLoading}
                                    >
                                      {approved ? '撤销' : '通过'}
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="text"
                                      onClick={() => openRegenerateDialog(asset)}
                                      disabled={libraryLoading}
                                    >
                                      重生成
                                    </Button>
                                  </Stack>
                                </Box>
                              </ImageListItem>
                            )
                          })}
                        </ImageList>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          未加载素材库或当前项目暂无可审核素材。
                        </Typography>
                      )}

                      <Accordion sx={{ mt: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            调试面板（Artifacts）
                          </Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Box
                            sx={{
                              whiteSpace: 'pre-wrap',
                              fontFamily: 'monospace',
                              fontSize: 12,
                              bgcolor: '#fafafa',
                              border: '1px solid #eee',
                              borderRadius: 2,
                              p: 1.5,
                            }}
                          >
                            {JSON.stringify(taskArtifacts, null, 2)}
                          </Box>
                        </AccordionDetails>
                      </Accordion>
                    </Box>
                    ) : (
                      <Box>
                        <Alert
                          severity={libraryApproved ? 'success' : 'info'}
                          sx={{ mb: 1 }}
                          action={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Button size="small" variant="text" onClick={() => handleClickStep(2)}>
                                查看素材
                              </Button>
                              <Button size="small" variant="contained" color="success" onClick={resumeGeneration} disabled={!canResumeFromLibrary}>
                                {resumeLoading ? '继续生成中…' : '继续生成'}
                              </Button>
                            </Stack>
                          }
                        >
                          {libraryApproved ? '素材库已审核通过：可继续生成进入镜头阶段。' : '当前阶段正在等待素材库审核：请先在“素材”完成审核后继续。'}
                        </Alert>

                        {persistedRunId && (
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" mb={1}>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={loadRunSnapshot}
                              disabled={!persistedRunId || runSnapshotLoading}
                            >
                              {runSnapshotLoading ? '加载中…' : '刷新运行快照'}
                            </Button>
                            {runSnapshot && runSnapshot.run_id === persistedRunId && (
                              <Chip size="small" label="快照已加载" color="success" />
                            )}
                          </Stack>
                        )}
                        {runSnapshotError && (
                          <Alert severity="error" sx={{ mb: 1 }}>
                            {runSnapshotError}
                          </Alert>
                        )}
                        {runSnapshotLoading && <LinearProgress sx={{ mb: 1 }} />}

                        {previewStep === 0 && !runSnapshotLoading && (
                          <Box sx={{ mb: 1 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              计划 / 剧本提要（快照）
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>
                              {snapshotPlanText.trim() || '暂无计划/提要快照（可能尚未落库）。'}
                            </Typography>

                            {snapshotScriptText.trim() ? (
                              <Accordion>
                                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                      剧本（快照）
                                    </Typography>
                                    <Chip
                                      size="small"
                                      label={snapshotScriptApproved ? '已通过' : '未通过'}
                                      color={snapshotScriptApproved ? 'success' : 'default'}
                                    />
                                    <Chip size="small" label={`长度: ${snapshotScriptText.length}`} />
                                  </Stack>
                                </AccordionSummary>
                                <AccordionDetails>
                                  <Box
                                    sx={{
                                      whiteSpace: 'pre-wrap',
                                      fontFamily: 'monospace',
                                      fontSize: 12,
                                      bgcolor: '#fafafa',
                                      border: '1px solid #eee',
                                      borderRadius: 2,
                                      p: 1.5,
                                      maxHeight: 260,
                                      overflow: 'auto',
                                    }}
                                  >
                                    {snapshotScriptText.length > 6000 ? `${snapshotScriptText.slice(0, 6000)}\n…` : snapshotScriptText}
                                  </Box>
                                </AccordionDetails>
                              </Accordion>
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                尚无可用剧本快照（可能尚未落库）。
                              </Typography>
                            )}
                          </Box>
                        )}

                        {previewStep === 1 && !runSnapshotLoading && (
                          <Box sx={{ mb: 1 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              镜头列表
                            </Typography>
                            {snapshotShots.length ? (
                              <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                                {snapshotShots.slice(0, 12).map((shot: any) => (
                                  <ListItem key={shot.shot_key || shot.shot_index} disablePadding sx={{ px: 1, py: 0.25 }}>
                                    <ListItemText
                                      primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                      secondary={`场景: ${shot.scene_id || '-'}  时长: ${typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s`}
                                    />
                                  </ListItem>
                                ))}
                              </List>
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                尚无可用分镜快照（可能尚未落库）。
                              </Typography>
                            )}
                          </Box>
                        )}

                        {previewStep === 3 && !runSnapshotLoading && snapshotShots.length > 0 && (
                          <Box sx={{ mb: 1 }}>
                            <Stack direction="row" spacing={1} flexWrap="wrap" mb={0.5}>
                              <Chip size="small" label={`镜头: ${snapshotShots.length}`} />
                              <Chip size="small" label={`资产: ${snapshotAssetCount}`} />
                              <Chip size="small" label={`KF: ${snapshotAssetSummary.keyframes.length}`} />
                              <Chip size="small" label={`MF: ${snapshotAssetSummary.midframes.length}`} />
                              <Chip size="small" label={`VC: ${snapshotAssetSummary.videoClips.length}`} />
                            </Stack>
                            {(snapshotAssetSummary.keyframes.length > 0 ||
                              snapshotAssetSummary.midframes.length > 0 ||
                              snapshotAssetSummary.videoClips.length > 0) && (
                              <Typography variant="caption" color="text.secondary" display="block">
                                快照路径：
                                {formatPaths(snapshotAssetSummary.keyframes.slice(-3)) ? `KF ${formatPaths(snapshotAssetSummary.keyframes.slice(-3))}` : ''}
                                {formatPaths(snapshotAssetSummary.midframes.slice(-3)) ? `  MF ${formatPaths(snapshotAssetSummary.midframes.slice(-3))}` : ''}
                                {formatPaths(snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path))
                                  ? `  VC ${formatPaths(snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path))}`
                                  : ''}
                              </Typography>
                            )}
                            {renderRunAssetPreviewGrid('关键帧（快照）', snapshotAssetSummary.keyframes.slice(-6), 'image')}
                            {renderRunAssetPreviewGrid('中间帧（快照）', snapshotAssetSummary.midframes.slice(-6), 'image')}
                            {renderRunAssetPreviewGrid(
                              '镜头片段（快照）',
                              snapshotAssetSummary.videoClips.slice(-3).map((v) => v.path),
                              'video',
                            )}
                          </Box>
                        )}

                        {previewStep === 4 && !runSnapshotLoading && (
                          <Box sx={{ mb: 1 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              合成视频（快照）
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {snapshotMergedVideo ? `合成视频：${snapshotMergedVideo}` : '暂无合成视频快照'}
                            </Typography>
                            {snapshotMergedVideo && (
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
                              </Stack>
                            )}
                            {mergedVideoError && (
                              <Alert severity="error" sx={{ mt: 1 }}>
                                {mergedVideoError}
                              </Alert>
                            )}
                            {mergedVideoPreviewUrl && (
                              <Box sx={{ mt: 1, bgcolor: '#000', borderRadius: 2, overflow: 'hidden' }}>
                                <Box component="video" src={mergedVideoPreviewUrl} controls sx={{ width: '100%', display: 'block' }} />
                              </Box>
                            )}
                          </Box>
                        )}
                      </Box>
                    )
                    )
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      点击“开始生成”后，这里会展示「{DREAMWEAVER_PREVIEW_STEPS[previewStep]}」相关产物与进度。
                    </Typography>
                  )
                ) : (
                  <Box>
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

                    <Accordion sx={{ mb: 1.5 }}>
                      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          调试面板（Result）
                        </Typography>
                      </AccordionSummary>
                      <AccordionDetails>
                        <Box
                          sx={{
                            whiteSpace: 'pre-wrap',
                            fontFamily: 'monospace',
                            fontSize: 12,
                            bgcolor: '#fafafa',
                            border: '1px solid #eee',
                            borderRadius: 2,
                            p: 1.5,
                          }}
                        >
                          {JSON.stringify(result, null, 2)}
                        </Box>
                      </AccordionDetails>
                    </Accordion>

                    <Divider sx={{ my: 1.5 }} />

                    {(previewStep === 0 || previewStep === 4) && (
                      <>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                          计划 / 剧本提要
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          {result.plan?.text || '未返回文本'}
                        </Typography>
                      </>
                    )}

                    {(previewStep === 1 || previewStep === 4) && (
                      <>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                          分镜（storyboard）
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {result.storyboard ? `${result.storyboard.length} 个镜头` : '暂无'}
                        </Typography>
                        {previewStep === 1 && (
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={loadRunSnapshot}
                              disabled={!persistedRunId || runSnapshotLoading}
                            >
                              {runSnapshotLoading ? '加载中…' : '加载运行快照'}
                            </Button>
                            {runSnapshot && runSnapshot.run_id === persistedRunId && (
                              <Chip size="small" label="快照已加载" color="success" />
                            )}
                          </Stack>
                        )}
                        {previewStep === 1 && runSnapshotError && (
                          <Alert severity="error" sx={{ mt: 1 }}>
                            {runSnapshotError}
                          </Alert>
                        )}
                        {previewStep === 1 && runSnapshotLoading && <LinearProgress sx={{ mt: 1 }} />}
                        {previewStep === 1 && !runSnapshotLoading && snapshotShots.length > 0 && (
                          <List dense sx={{ mt: 1, bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                            {snapshotShots.slice(0, 12).map((shot: any) => (
                              <ListItem key={shot.shot_key || shot.shot_index} disablePadding sx={{ px: 1, py: 0.25 }}>
                                <ListItemText
                                  primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                  secondary={`场景: ${shot.scene_id || '-'}  时长: ${typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s`}
                                />
                              </ListItem>
                            ))}
                          </List>
                        )}
                      </>
                    )}

                    {previewStep === 2 && (
                      <Alert severity="info" sx={{ mb: 1 }}>
                        素材库为项目维度产物，可切换到“素材”并点击“加载素材库”查看/审核。
                      </Alert>
                    )}

                    {(previewStep === 3 || previewStep === 4) && (
                      <>
                        {renderRunAssetPreviewGrid(
                          '关键帧',
                          (Array.isArray(result.keyframes) ? result.keyframes.map((k: any) => (k ? (k as any).path : '')) : []).slice(-6),
                          'image',
                        )}
                        {renderRunAssetPreviewGrid(
                          '中间帧',
                          (Array.isArray(result.midframes) ? result.midframes.map((m: any) => (m ? (m as any).path : '')) : []).slice(-6),
                          'image',
                        )}
                        {candidateFrameUris.length > 0 &&
                          renderRunAssetPreviewGrid('候选帧（keep_candidates）', candidateFrameUris.slice(-12), 'image')}
                        {renderRunAssetPreviewGrid(
                          '镜头片段',
                          (Array.isArray(result.video_clips) ? result.video_clips.map((v: any) => (v ? (v as any).path : '')) : []).slice(-3),
                          'video',
                        )}
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
                          视频产物
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {result.merged_video ? `合成视频：${result.merged_video}` : '无合成视频记录'}
                        </Typography>
                        {videoDiagnostics.viaSummary && (
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            生成方式：{videoDiagnostics.viaSummary}
                            {videoDiagnostics.fallbackCount > 0 ? `（降级: ${videoDiagnostics.fallbackCount}/${videoDiagnostics.clipCount}）` : ''}
                          </Typography>
                        )}
                        {videoDiagnostics.fallbackCount > 0 && (
                          <Alert severity="warning" sx={{ mt: 1 }}>
                            检测到镜头视频生成失败并降级为幻灯片合成，建议检查 WAN_I2V_* 配置/网络，并适当增大 WAN_I2V_TIMEOUT。
                          </Alert>
                        )}
                        {Array.isArray(result.video_clips) && result.video_clips.length > 0 && (
                          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                            {result.video_clips
                              .map((v, idx) => (v.path ? `${idx + 1}. ${v.path}` : ''))
                              .filter(Boolean)
                              .join('  ')}
                          </Typography>
                        )}
                        {result.merged_video && (
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
                          </Stack>
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
                              mx: 'auto',
                              width: '100%',
                              maxWidth: mergedVideoPreviewPortrait ? 360 : 720,
                            }}
                          >
                            <Box component="video" src={mergedVideoPreviewUrl} controls sx={{ width: '100%', display: 'block' }} />
                          </Box>
                        )}
                        {previewStep === 3 && (
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={loadRunSnapshot}
                              disabled={!persistedRunId || runSnapshotLoading}
                            >
                              {runSnapshotLoading ? '加载中…' : '加载运行快照'}
                            </Button>
                            {runSnapshot && runSnapshot.run_id === persistedRunId && (
                              <Chip size="small" label="快照已加载" color="success" />
                            )}
                            {snapshotShots.length > 0 && (
                              <Chip size="small" label={`镜头: ${snapshotShots.length}`} />
                            )}
                            {snapshotAssetCount > 0 && <Chip size="small" label={`资产: ${snapshotAssetCount}`} />}
                          </Stack>
                        )}
                        {previewStep === 3 && runSnapshotError && (
                          <Alert severity="error" sx={{ mt: 1 }}>
                            {runSnapshotError}
                          </Alert>
                        )}
                        {previewStep === 3 && runSnapshotLoading && <LinearProgress sx={{ mt: 1 }} />}
                      </>
                    )}

                    {previewStep === 4 && (
                      <>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
                          质检
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {result.audit ? JSON.stringify(result.audit) : '未返回审核信息'}
                        </Typography>
                      </>
                    )}
                  </Box>
                )}

                <Dialog open={diagnosticOpen} onClose={() => setDiagnosticOpen(false)} maxWidth="lg" fullWidth>
                  <DialogTitle>
                    <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                        <BugReportIcon color="primary" />
                        <Typography variant="h6">诊断面板</Typography>
                        {currentRunId && (
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {currentRunId}
                          </Typography>
                        )}
                        {diagnosticResult?.state && <Chip size="small" label={`state: ${diagnosticResult.state}`} />}
                        {diagnosticResult?.stage && <Chip size="small" label={`stage: ${diagnosticResult.stage}`} />}
                      </Stack>
                      <IconButton onClick={() => setDiagnosticOpen(false)}>
                        <CloseIcon />
                      </IconButton>
                    </Stack>
                  </DialogTitle>
                  <DialogContent dividers>
                    {!currentRunId && (
                      <Alert severity="info" sx={{ mb: 1 }}>
                        暂无 run_id，无法加载产物预览与诊断信息。
                      </Alert>
                    )}
                    {currentRunId && !diagnosticResult && (
                      <Alert severity="info" sx={{ mb: 1 }}>
                        暂无可用的契约快照/镜头信息。可尝试点击“刷新运行快照”，或等待任务落库后再查看。
                      </Alert>
                    )}
                    {diagnosticActionError && (
                      <Alert severity="error" sx={{ mb: 1 }}>
                        {diagnosticActionError}
                      </Alert>
                    )}
                    {diagnosticActionLoading && <LinearProgress sx={{ mb: 1 }} />}

                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
                      <Chip size="small" label={`镜头: ${diagnosticShots.length}`} />
                      {Array.isArray(diagnosticResult?.keyframes) && <Chip size="small" label={`KF: ${diagnosticResult?.keyframes?.length || 0}`} />}
                      {Array.isArray(diagnosticResult?.midframes) && <Chip size="small" label={`MF: ${diagnosticResult?.midframes?.length || 0}`} />}
                      {Array.isArray(diagnosticResult?.video_clips) && <Chip size="small" label={`VC: ${diagnosticResult?.video_clips?.length || 0}`} />}
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<RefreshIcon fontSize="small" />}
                        onClick={loadRunSnapshot}
                        disabled={!persistedRunId || runSnapshotLoading}
                      >
                        {runSnapshotLoading ? '刷新中…' : '刷新运行快照'}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={<ContentCopyIcon fontSize="small" />}
                        onClick={() =>
                          copyText(
                            safeJsonStringify({
                              page: 'DreamWeaverRunDiagnostics',
                              run_id: currentRunId,
                              status: taskStatus,
                              state: taskState,
                              stage: taskStage,
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
                            }),
                          )
                        }
                        disabled={!diagnosticResult}
                      >
                        复制 Run 诊断
                      </Button>
                    </Stack>

                    <Divider sx={{ mb: 1 }} />

                    {snapshotTelemetrySummary && (
                      <Accordion defaultExpanded sx={{ mb: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            运行耗时（Telemetry）
                          </Typography>
                        </AccordionSummary>
                        <AccordionDetails>
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

                          {snapshotTelemetrySummary.stageEntries.length > 0 && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
                              {snapshotTelemetrySummary.stageEntries.map((it) => (
                                <Chip
                                  key={`tele:${it.stage}`}
                                  size="small"
                                  variant="outlined"
                                  label={`${it.stage}: ${Number(it.totalS).toFixed(1)}s (${it.calls}${it.failure ? `, fail:${it.failure}` : ''})`}
                                />
                              ))}
                            </Stack>
                          )}

                          {snapshotTelemetrySummary.reworkByType && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                              {Object.entries(snapshotTelemetrySummary.reworkByType).map(([k, v]) => (
                                <Chip key={`rework:${k}`} size="small" variant="outlined" label={`rework.${k}: ${v}`} />
                              ))}
                            </Stack>
                          )}

                          {snapshotTelemetryCounters.length > 0 && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                              {snapshotTelemetryCounters.map((it) => (
                                <Chip key={`telemetry-counter:${it.name}`} size="small" variant="outlined" label={`${it.name}: ${it.value}`} />
                              ))}
                            </Stack>
                          )}

                          {snapshotTelemetry && (
                            <Accordion sx={{ mt: 1 }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                  Telemetry JSON
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>{renderDiagnosticJson(snapshotTelemetry)}</AccordionDetails>
                            </Accordion>
                          )}
                        </AccordionDetails>
                      </Accordion>
                    )}

                    {(diagnosticCameraDiagnostics.cameraTree ||
                      diagnosticCameraDiagnostics.cameraStates ||
                      diagnosticCameraDiagnostics.cameraScenes ||
                      diagnosticCameraDiagnostics.generation) && (
                      <Accordion sx={{ mb: 1 }}>
                        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                            <PhotoCameraIcon color="primary" fontSize="small" />
                            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                              相机依赖（Camera Tree）
                            </Typography>
                            {diagnosticCameraDiagnostics.mode && (
                              <Chip size="small" label={`mode: ${diagnosticCameraDiagnostics.mode}`} variant="outlined" />
                            )}
                            {Array.isArray(diagnosticCameraDiagnostics.cameraTree) && (
                              <Chip size="small" label={`cameras: ${diagnosticCameraDiagnostics.cameraTree.length}`} />
                            )}
                            {Array.isArray(diagnosticCameraDiagnostics.cameraScenes) && (
                              <Chip size="small" label={`scenes: ${diagnosticCameraDiagnostics.cameraScenes.length}`} />
                            )}
                          </Stack>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<ContentCopyIcon fontSize="small" />}
                              onClick={() =>
                                copyText(
                                  safeJsonStringify({
                                    camera_tree_generation: diagnosticCameraDiagnostics.generation || null,
                                    camera_tree: diagnosticCameraDiagnostics.cameraTree || null,
                                    camera_states: diagnosticCameraDiagnostics.cameraStates || null,
                                    camera_scenes: diagnosticCameraDiagnostics.cameraScenes || null,
                                  }),
                                )
                              }
                            >
                              复制 Camera 诊断
                            </Button>
                          </Stack>

                          {diagnosticCameraDiagnostics.sceneUris.length > 0 &&
                            renderRunAssetPreviewGrid(
                              '相机场景（每个相机首镜头 head）',
                              diagnosticCameraDiagnostics.sceneUris.slice(0, 12),
                              'image',
                            )}

                          {diagnosticCameraDiagnostics.generation && (
                            <Accordion sx={{ mt: 1 }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                  camera_tree_generation
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>{renderDiagnosticJson(diagnosticCameraDiagnostics.generation)}</AccordionDetails>
                            </Accordion>
                          )}

                          {diagnosticCameraDiagnostics.cameraTree && (
                            <Accordion sx={{ mt: 1 }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                  camera_tree
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>{renderDiagnosticJson(diagnosticCameraDiagnostics.cameraTree)}</AccordionDetails>
                            </Accordion>
                          )}

                          {diagnosticCameraDiagnostics.cameraStates && (
                            <Accordion sx={{ mt: 1 }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                  camera_states
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>{renderDiagnosticJson(diagnosticCameraDiagnostics.cameraStates)}</AccordionDetails>
                            </Accordion>
                          )}

                          {diagnosticCameraDiagnostics.cameraScenes && (
                            <Accordion sx={{ mt: 1 }}>
                              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                  camera_scenes
                                </Typography>
                              </AccordionSummary>
                              <AccordionDetails>{renderDiagnosticJson(diagnosticCameraDiagnostics.cameraScenes)}</AccordionDetails>
                            </Accordion>
                          )}
                        </AccordionDetails>
                      </Accordion>
                    )}

                    {!diagnosticResult && (
                      <Typography variant="body2" color="text.secondary">
                        无可展示内容
                      </Typography>
                    )}

                    {diagnosticResult && diagnosticShots.length === 0 && (
                      <Typography variant="body2" color="text.secondary">
                        暂无镜头数据（storyboard 未落库或尚未生成）。
                      </Typography>
                    )}

                    {diagnosticResult &&
                      diagnosticShots.length > 0 &&
                      diagnosticShots.map((shot) => {
                        const shotId = String((shot as any).shot_id || '').trim()
                        const frames = (shot as any).frames && typeof (shot as any).frames === 'object' ? ((shot as any).frames as any) : {}
                        const sb = (shot as any).storyboard && typeof (shot as any).storyboard === 'object' ? ((shot as any).storyboard as any) : null
                        const desc = sb && typeof sb.desc === 'string' ? sb.desc : ''
                        const duration =
                          sb && typeof sb.duration_s === 'number' ? Number(sb.duration_s) : typeof sb?.duration_s === 'string' ? Number(sb.duration_s) : null
                        const autoqcShots = (diagnosticResult?.autoqc as any)?.shots
                        const shotAutoQC = autoqcShots && typeof autoqcShots === 'object' ? (autoqcShots as any)[shotId] : null
                        const shotAutoQCPass = shotAutoQC && typeof shotAutoQC === 'object' ? Boolean((shotAutoQC as any).pass) : null
                        const shotAutoQCScore =
                          shotAutoQC && typeof shotAutoQC === 'object' && (shotAutoQC as any).scores && typeof (shotAutoQC as any).scores === 'object'
                            ? (shotAutoQC as any).scores.overall
                            : null

                        return (
                          <Accordion key={`diag:${shotId}`} sx={{ mb: 1 }}>
                            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
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
                                {(shot as any).video_clip && <Chip size="small" label="clip" color="info" variant="outlined" />}
                                {shotAutoQCPass != null && (
                                  <Chip
                                    size="small"
                                    label={`AutoQC: ${shotAutoQCPass ? 'pass' : 'fail'}${typeof shotAutoQCScore === 'number' ? ` (${shotAutoQCScore.toFixed(2)})` : ''}`}
                                    color={shotAutoQCPass ? 'success' : 'warning'}
                                  />
                                )}
                              </Stack>
                            </AccordionSummary>
                            <AccordionDetails>
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
                                        video_clip: (shot as any).video_clip || null,
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
                                {shotId && (
                                  <>
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      component="label"
                                      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
                                    >
                                      上传首帧
                                      <input
                                        hidden
                                        type="file"
                                        accept="image/png"
                                        onChange={(e) => {
                                          const f = e.target.files && e.target.files[0]
                                          e.target.value = ''
                                          if (!f) return
                                          void uploadShotAsset(shotId, 'head_frame', f)
                                        }}
                                      />
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      component="label"
                                      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
                                    >
                                      上传尾帧
                                      <input
                                        hidden
                                        type="file"
                                        accept="image/png"
                                        onChange={(e) => {
                                          const f = e.target.files && e.target.files[0]
                                          e.target.value = ''
                                          if (!f) return
                                          void uploadShotAsset(shotId, 'tail_frame', f)
                                        }}
                                      />
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      component="label"
                                      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
                                    >
                                      上传中间帧
                                      <input
                                        hidden
                                        type="file"
                                        accept="image/png"
                                        onChange={(e) => {
                                          const f = e.target.files && e.target.files[0]
                                          e.target.value = ''
                                          if (!f) return
                                          void uploadShotAsset(shotId, 'mid_frame', f)
                                        }}
                                      />
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="outlined"
                                      component="label"
                                      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
                                    >
                                      上传镜头视频
                                      <input
                                        hidden
                                        type="file"
                                        accept="video/mp4"
                                        onChange={(e) => {
                                          const f = e.target.files && e.target.files[0]
                                          e.target.value = ''
                                          if (!f) return
                                          void uploadShotAsset(shotId, 'video_clip', f)
                                        }}
                                      />
                                    </Button>
                                    <Button
                                      size="small"
                                      variant="contained"
                                      onClick={() =>
                                        void promptAndRegenerateKeyframe(
                                          shotId,
                                          'head',
                                          String((sb as any)?.head_frame?.prompt || (sb as any)?.visual_desc || (sb as any)?.desc || ''),
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
                                          String((sb as any)?.tail_frame?.prompt || (sb as any)?.visual_desc || (sb as any)?.desc || ''),
                                        )
                                      }
                                      disabled={!currentRunId || running || restartLoading || diagnosticActionLoading}
                                    >
                                      改尾帧提示词并重跑
                                    </Button>
                                  </>
                                )}
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

                              {sb && (
                                <Accordion>
                                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                      分镜（storyboard）
                                    </Typography>
                                  </AccordionSummary>
                                  <AccordionDetails>{renderDiagnosticJson(sb)}</AccordionDetails>
                                </Accordion>
                              )}

                              {shotAutoQC && (
                                <Accordion sx={{ mt: 1 }}>
                                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                      AutoQC
                                    </Typography>
                                  </AccordionSummary>
                                  <AccordionDetails>{renderDiagnosticJson(shotAutoQC)}</AccordionDetails>
                                </Accordion>
                              )}

                              {renderDiagnosticFrame('首帧（head）', frames.head, 'image')}
                              {renderDiagnosticFrame('尾帧（tail）', frames.tail, 'image')}
                              {renderDiagnosticFrame('中间帧（mid）', frames.mid, 'image')}
                              {renderDiagnosticFrame('镜头片段（video_clip）', (shot as any).video_clip, 'video')}
                            </AccordionDetails>
                          </Accordion>
                        )
                      })}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setDiagnosticOpen(false)}>关闭</Button>
                  </DialogActions>
                </Dialog>

                <Dialog
                  open={regenOpen}
                  onClose={() => {
                    if (regenSubmitting) return
                    setRegenOpen(false)
                  }}
                  fullWidth
                  maxWidth="md"
                >
                  <DialogTitle>重生成素材：{regenTitle || regenRole}</DialogTitle>
                  <DialogContent dividers>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                      可在下方编辑该素材的提示词，确认后将覆盖重生成（生成后会变为“待审核”）。
                    </Typography>
                    <TextField
                      label="提示词"
                      fullWidth
                      multiline
                      minRows={8}
                      value={regenPrompt}
                      onChange={(e) => setRegenPrompt(e.target.value)}
                      disabled={regenSubmitting}
                    />
                    {regenError && (
                      <Alert severity="error" sx={{ mt: 1 }}>
                        {regenError}
                      </Alert>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button
                      onClick={() => setRegenOpen(false)}
                      disabled={regenSubmitting}
                    >
                      取消
                    </Button>
                    <Button
                      variant="contained"
                      onClick={submitRegenerateDialog}
                      disabled={regenSubmitting || !regenRole}
                    >
                      {regenSubmitting ? '重生成中…' : '确认重生成'}
                    </Button>
                  </DialogActions>
                </Dialog>

                <Dialog open={historyOpen} onClose={closeHistoryDialog} maxWidth="md" fullWidth>
                  <DialogTitle>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <HistoryIcon color="primary" />
                      <Typography variant="h6">历史记录</Typography>
                      {selectedProject?.title && (
                        <Typography variant="body2" color="text.secondary">
                          {selectedProject.title}
                        </Typography>
                      )}
                    </Stack>
                  </DialogTitle>
                  <DialogContent dividers>
                    {historyError && (
                      <Alert severity="error" sx={{ mb: 1 }}>
                        {historyError}
                      </Alert>
                    )}
                    {historyLoading && <LinearProgress sx={{ mb: 1 }} />}

                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 1 }}>
                      <Chip
                        size="small"
                        label={`全部 (${historyRuns.length})`}
                        color="default"
                        variant={historyStatusFilters.length === 0 ? 'filled' : 'outlined'}
                        onClick={() => setHistoryStatusFilters([])}
                      />
                      {(['running', 'queued', 'waiting', 'failed', 'timeout', 'completed'] as const).map((status) => {
                        const enabled = historyStatusFilters.includes(status)
                        const count = historyStatusCounts[status] || 0
                        const label =
                          status === 'completed'
                            ? '已完成'
                            : status === 'waiting'
                            ? '待审核'
                            : status === 'failed'
                            ? '失败'
                            : status === 'timeout'
                            ? '超时'
                            : status === 'running'
                            ? '运行中'
                            : status === 'queued'
                            ? '排队中'
                            : status
                        const color: 'default' | 'success' | 'error' | 'warning' | 'info' =
                          status === 'completed'
                            ? 'success'
                            : status === 'failed'
                            ? 'error'
                            : status === 'waiting' || status === 'timeout'
                            ? 'warning'
                            : status === 'running' || status === 'queued'
                            ? 'info'
                            : 'default'

                        return (
                          <Chip
                            key={status}
                            size="small"
                            label={`${label} (${count})`}
                            color={color}
                            variant={enabled ? 'filled' : 'outlined'}
                            onClick={() =>
                              setHistoryStatusFilters((prev) =>
                                prev.includes(status) ? prev.filter((s) => s !== status) : [...prev, status],
                              )
                            }
                          />
                        )
                      })}

                      <Box sx={{ flex: 1 }} />

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
                    </Stack>

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

                    {!historyLoading && filteredHistoryRuns.length > 0 && (
                      <List>
                        {filteredHistoryRuns.map((run) => {
                          const statusRaw = String(run.status || '').trim().toLowerCase()
                          const statusLabel =
                            statusRaw === 'completed'
                              ? '已完成'
                              : statusRaw === 'waiting'
                              ? '待审核'
                              : statusRaw === 'failed'
                              ? '失败'
                              : statusRaw === 'timeout'
                              ? '超时'
                              : statusRaw === 'running'
                              ? '运行中'
                              : statusRaw === 'queued'
                              ? '排队中'
                              : statusRaw || '未知'
                          const statusColor: 'default' | 'success' | 'error' | 'warning' | 'info' =
                            statusRaw === 'completed'
                              ? 'success'
                              : statusRaw === 'failed'
                              ? 'error'
                              : statusRaw === 'waiting'
                              ? 'warning'
                              : statusRaw === 'timeout'
                              ? 'warning'
                              : statusRaw === 'running' || statusRaw === 'queued'
                              ? 'info'
                              : 'default'
                          const timeText = formatDateTime(run.updated_at || run.created_at)
                          const progressValue =
                            typeof run.progress === 'number' ? Math.max(0, Math.min(100, Math.round(run.progress))) : null

                          return (
                            <ListItem key={run.run_id} sx={{ border: '1px solid #eee', borderRadius: 2, mb: 1 }}>
                              <Box sx={{ flex: 1, minWidth: 0 }}>
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
                                {timeText && (
                                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                                    {timeText}
                                  </Typography>
                                )}
                                {run.error_message && (
                                  <Typography variant="caption" color="error" display="block" sx={{ mt: 0.5 }}>
                                    {run.error_message}
                                  </Typography>
                                )}
                              </Box>
                              <Stack direction="row" spacing={1} alignItems="center">
                                <Button
                                  size="small"
                                  variant="text"
                                  startIcon={<PlayArrowIcon fontSize="small" />}
                                  onClick={() => handleViewHistoryRun(run.run_id)}
                                >
                                  查看
                                </Button>
                                <Button
                                  size="small"
                                  variant="text"
                                  color="error"
                                  startIcon={<DeleteIcon fontSize="small" />}
                                  onClick={() => openDeleteRunDialog(run.run_id)}
                                >
                                  删除
                                </Button>
                              </Stack>
                            </ListItem>
                          )
                        })}
                      </List>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={closeHistoryDialog}>关闭</Button>
                  </DialogActions>
                </Dialog>

                <Dialog open={bulkDeleteDialogOpen} onClose={closeBulkDeleteDialog} fullWidth maxWidth="sm">
                  <DialogTitle>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <WarningIcon sx={{ color: '#f44336' }} />
                      <Typography variant="h6">确认批量删除</Typography>
                    </Stack>
                  </DialogTitle>
                  <DialogContent dividers>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      此操作将级联删除筛选出的 runs 的数据库记录与 runs/{'{run_id}'} 产物文件（不可恢复）；不会删除项目公共素材库（可复用）。运行中/排队中的 run 将自动跳过。
                    </Alert>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      本次将删除：{bulkDeleteTargets.length} 个 run；跳过：{bulkDeleteSkippedCount} 个（运行中/排队中）。
                    </Typography>

                    {bulkDeleteProgress && (
                      <Stack spacing={1} sx={{ mb: 1 }}>
                        <LinearProgress
                          variant={bulkDeleteProgress.total > 0 ? 'determinate' : 'indeterminate'}
                          value={
                            bulkDeleteProgress.total > 0
                              ? Math.round((bulkDeleteProgress.current / bulkDeleteProgress.total) * 100)
                              : undefined
                          }
                        />
                        <Typography variant="caption" color="text.secondary">
                          进度：{bulkDeleteProgress.current}/{bulkDeleteProgress.total}
                        </Typography>
                      </Stack>
                    )}

                    {bulkDeleteError && (
                      <Alert severity="error" sx={{ mt: 1 }}>
                        {bulkDeleteError}
                      </Alert>
                    )}

                    {bulkDeleteResult && (
                      <Alert severity={bulkDeleteResult.failed ? 'warning' : 'success'} sx={{ mt: 1 }}>
                        已删除：{bulkDeleteResult.deleted}；跳过：{bulkDeleteResult.skipped}；失败：{bulkDeleteResult.failed}
                        {bulkDeleteResult.errors.length > 0 && (
                          <Box sx={{ mt: 1 }}>
                            {bulkDeleteResult.errors.slice(0, 6).map((msg) => (
                              <Typography key={msg} variant="caption" display="block" sx={{ fontFamily: 'monospace' }}>
                                {msg}
                              </Typography>
                            ))}
                            {bulkDeleteResult.errors.length > 6 && (
                              <Typography variant="caption" display="block" color="text.secondary">
                                …还有 {bulkDeleteResult.errors.length - 6} 条错误
                              </Typography>
                            )}
                          </Box>
                        )}
                      </Alert>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={closeBulkDeleteDialog} disabled={bulkDeleteSubmitting}>
                      {bulkDeleteResult ? '关闭' : '取消'}
                    </Button>
                    {!bulkDeleteResult && (
                      <Button
                        variant="contained"
                        color="error"
                        onClick={confirmBulkDeleteRuns}
                        disabled={bulkDeleteSubmitting || bulkDeleteTargets.length === 0}
                      >
                        {bulkDeleteSubmitting ? '删除中…' : '确认批量删除'}
                      </Button>
                    )}
                  </DialogActions>
                </Dialog>

                <Dialog open={deleteDialogOpen} onClose={closeDeleteRunDialog} fullWidth maxWidth="sm">
                  <DialogTitle>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <WarningIcon sx={{ color: '#f44336' }} />
                      <Typography variant="h6">确认删除</Typography>
                    </Stack>
                  </DialogTitle>
                  <DialogContent dividers>
                    <Alert severity="warning" sx={{ mb: 2 }}>
                      此操作将级联删除该次 run 的数据库记录与 runs/{'{run_id}'} 产物文件（不可恢复）；不会删除项目公共素材库（可复用）。
                    </Alert>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
                      RunID: {deleteRunId || '-'}
                    </Typography>
                    {deleteDialogError && (
                      <Alert severity="error" sx={{ mt: 1 }}>
                        {deleteDialogError}
                      </Alert>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={closeDeleteRunDialog} disabled={deleteSubmitting}>
                      取消
                    </Button>
                    <Button
                      variant="contained"
                      color="error"
                      onClick={confirmDeleteRun}
                      disabled={deleteSubmitting || !deleteRunId}
                    >
                      {deleteSubmitting ? '删除中…' : '确认删除'}
                    </Button>
                  </DialogActions>
                </Dialog>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>
    </Box>
  )
}
