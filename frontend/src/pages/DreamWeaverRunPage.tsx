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
import { workflowWebSocket } from '@/services/websocket'
import FormattedContent from '@/components/common/FormattedContent'
import {
  CHARACTER_VIEW_ORDER,
  CHARACTER_VIEW_RANK,
  characterViewLabel,
  formatReferenceRoleLabel,
  parseLibraryRole,
  resolveCharacterViewChainPlan,
  type CharacterView,
} from '@/utils/dreamweaverLibraryRole'
import { hasRenderableLibraryImage, resolveLibraryAssetImageState, type LibraryAssetImageState } from '@/utils/dreamweaverLibraryAssetState'

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
  prompt_review_required?: boolean
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
      prompt_review_required: patch.prompt_review_required ?? prev?.prompt_review_required,
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

function isPlaceholderEntityName(value: unknown): boolean {
  const text = String(value ?? '').trim()
  if (!text) return true
  const lowered = text.toLowerCase()
  if (lowered === 'unknown' || lowered === 'n/a' || lowered === 'na') return true
  if (lowered.startsWith('lib_character_portrait')) return true
  if (lowered.startsWith('lib_scene_card:')) return true
  if (lowered.startsWith('lib_prop_card:')) return true
  return false
}

interface Project {
  id: number
  display_no?: number
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

interface CollectFeedback {
  type: 'success' | 'error'
  text: string
}

function buildProtectedMergedVideoUrl(runId: string): string {
  return `protected://dreamweaver-run-merged/${encodeURIComponent(runId)}`
}

interface DreamweaverEventRecord {
  event_id: number
  run_id: string
  project_id: number
  stage?: string | null
  event_type: string
  payload?: Record<string, any>
  created_at?: string | null
}

interface DreamweaverAssetPlanItem {
  id: string
  shot_id?: string | null
  scene_id?: string | null
  cam_idx?: number | null
  role?: string | null
  kind?: 'image' | 'video'
  label?: string
  status?: 'planned' | 'done' | 'processing'
  optional?: boolean
  uri?: string | null
}

interface DreamweaverLibraryPlanItem {
  id: string
  role: string
  entity_type?: string | null
  entity_id?: number | null
  entity_name?: string | null
  label?: string
  view?: string | null
  status?: 'planned' | 'done' | 'processing'
  kind?: 'image'
  uri?: string | null
  asset_id?: number | null
  approved?: boolean | null
}

interface LibraryDisplayItem {
  key: string
  role: string
  title: string
  preview: string
  aspectRatio: string
  approved: boolean
  status: 'planned' | 'processing' | 'done'
  group: 'character' | 'scene' | 'prop' | 'other'
  view?: CharacterView | null
  viewRank: number
  asset?: LibraryAsset
  missing?: boolean
  placeholder?: boolean
  hasRenderableImage?: boolean
  imageState?: LibraryAssetImageState | null
  safety_blocked?: boolean
  safety_error?: string | null
}

function buildLibraryPlanItemsFromPayload(data: LibraryPayload | null | undefined): DreamweaverLibraryPlanItem[] {
  if (!data || typeof data !== 'object') return []

  const assets = Array.isArray(data.assets) ? data.assets : []
  const assetsByRole = new Map<string, LibraryAsset>()
  for (const asset of assets) {
    const role = String(asset?.role || '').trim()
    if (!role) continue
    assetsByRole.set(role, asset)
  }

  const entityNameByKey = new Map<string, string>()
  const spec = data.spec && typeof data.spec === 'object' ? data.spec : {}
  const sections: Array<{ key: string; entityType: 'character' | 'scene' | 'prop' }> = [
    { key: 'characters', entityType: 'character' },
    { key: 'scenes', entityType: 'scene' },
    { key: 'props', entityType: 'prop' },
  ]
  for (const section of sections) {
    const items = Array.isArray((spec as any)?.[section.key]) ? ((spec as any)[section.key] as any[]) : []
    for (const item of items) {
      if (!item || typeof item !== 'object') continue
      const entityId = Number.parseInt(String((item as any).entity_id ?? ''), 10)
      if (!Number.isFinite(entityId) || entityId <= 0) continue
      const name = String((item as any).name || '').trim()
      if (!name) continue
      entityNameByKey.set(`${section.entityType}:${entityId}`, name)
    }
  }

  const requiredRolesRaw = Array.isArray((data.review as any)?.required_roles) ? (((data.review as any).required_roles as any[]) ?? []) : []
  const requiredRoles = requiredRolesRaw
    .map((raw) => String(raw || '').trim())
    .filter((role) => role)

  const orderedRoles = requiredRoles.length
    ? requiredRoles
    : Array.from(assetsByRole.keys()).sort((a, b) => a.localeCompare(b, 'zh-CN'))

  const seen = new Set<string>()
  const items: DreamweaverLibraryPlanItem[] = []
  for (const role of orderedRoles) {
    if (seen.has(role)) continue
    seen.add(role)
    const parsed = parseLibraryRole(role)
    const asset = assetsByRole.get(role) || null
    const entityType = parsed.entityType === 'unknown' ? null : parsed.entityType
    const entityId = typeof parsed.entityId === 'number' && parsed.entityId > 0 ? parsed.entityId : null
    const nameFromSpec = entityType && entityId ? entityNameByKey.get(`${entityType}:${entityId}`) || '' : ''
    const nameFromAsset = String(asset?.meta?.entity_name || '').trim()
    const entityName = nameFromSpec || (!isPlaceholderEntityName(nameFromAsset) ? nameFromAsset : '') || null
    const hasUri = Boolean(asset && String(asset.uri || '').trim())
    const status: DreamweaverLibraryPlanItem['status'] = hasUri ? 'done' : 'planned'
    const viewLabel = parsed.entityType === 'character' && parsed.view ? characterViewLabel(parsed.view) : ''
    const baseLabel = entityName || role
    const label = viewLabel && !baseLabel.includes(viewLabel) ? `${baseLabel} ${viewLabel}` : baseLabel

    items.push({
      id: role,
      role,
      entity_type: entityType,
      entity_id: entityId,
      entity_name: entityName,
      label,
      view: parsed.entityType === 'character' && parsed.view ? parsed.view : null,
      status,
      kind: 'image',
      uri: hasUri ? String(asset!.uri || '').trim() : null,
      asset_id: asset?.id ?? null,
      approved: typeof asset?.meta?.approved === 'boolean' ? Boolean(asset?.meta?.approved) : null,
    })
  }
  return items
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
  const [promptReviewLoading, setPromptReviewLoading] = useState(false)
  const [promptReviewError, setPromptReviewError] = useState<string | null>(null)
  const [promptReviewShowAll, setPromptReviewShowAll] = useState(false)
  const [shotPromptExpanded, setShotPromptExpanded] = useState<Record<string, boolean>>({})
  const [promptEditOpen, setPromptEditOpen] = useState(false)
  const [promptEditShot, setPromptEditShot] = useState<any | null>(null)
  const [promptEditHead, setPromptEditHead] = useState<string>('')
  const [promptEditTail, setPromptEditTail] = useState<string>('')
  const [promptEditVideo, setPromptEditVideo] = useState<string>('')
  const [promptEditSaving, setPromptEditSaving] = useState(false)
  const [promptEditError, setPromptEditError] = useState<string | null>(null)
  const promptEditGenerated = useMemo(() => {
    return String(promptEditShot?.shot_schema_v2?.meta?.video_prompt_generated || '').trim()
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
  const [error, setError] = useState<string | null>(null)
  const [eventCursor, setEventCursor] = useState(0)
  const [eventSyncing, setEventSyncing] = useState(false)
  const [eventSyncError, setEventSyncError] = useState<string | null>(null)
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

  const renderAssetPlanGrid = (title: string, items: DreamweaverAssetPlanItem[]) => {
    const list = Array.isArray(items) ? items : []
    if (!list.length) return null
    return (
      <Box sx={{ mt: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
          {title}
        </Typography>
        <Grid container spacing={1}>
          {list.map((item) => {
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

                    {previewUrl ? (
                      kind === 'video' ? (
                        <Box sx={{ mt: 0.75, bgcolor: '#000', borderRadius: 1, overflow: 'hidden' }}>
                          <Box component="video" src={previewUrl} controls sx={{ width: '100%', maxHeight: 240, display: 'block' }} />
                        </Box>
                      ) : (
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
                    ) : (
                      <Box sx={{ mt: 0.75, bgcolor: '#fafafa', border: '1px dashed #ddd', borderRadius: 1, p: 1, textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">
                          {uri ? '已生成，待加载预览' : '生成中，等待素材'}
                        </Typography>
                      </Box>
                    )}

                    {uri && (
                      <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                        <Button size="small" variant="outlined" onClick={() => loadRunAssetPreview(uri)} disabled={!currentRunId || loading}>
                          {loading ? '加载中…' : previewUrl ? '重新加载' : '加载预览'}
                        </Button>
                        <Button size="small" variant="text" onClick={() => downloadRunAsset(uri)} disabled={!currentRunId || loading}>
                          下载
                        </Button>
                        {formatPath(uri) && <Chip size="small" label={formatPath(uri)} variant="outlined" />}
                      </Stack>
                    )}

                    {(item.shot_id || item.scene_id) && (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                        {item.shot_id ? `Shot: ${item.shot_id}` : ''}
                        {item.scene_id ? `  Scene: ${item.scene_id}` : ''}
                      </Typography>
                    )}

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

  const renderStageOverview = () => null
  const renderLibraryDisplayCard = (item: LibraryDisplayItem) => {
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
          ? (approved ? 'success' : 'default')
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

    return (
      <ImageListItem key={item.key} sx={{ border: '1px solid #eee', borderRadius: 2, overflow: 'hidden' }}>
        <Box
          sx={{
            width: '100%',
            aspectRatio: item.aspectRatio,
            bgcolor: safetyBlocked || missing ? '#fff5f5' : placeholder ? '#fffaf0' : '#f5f5f5',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          {preview && !safetyBlocked ? (
            <Box
              component="img"
              src={preview}
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
                color: safetyBlocked || missing ? 'error.main' : placeholder ? 'warning.main' : 'text.secondary',
                fontSize: 12,
                backgroundImage: safetyBlocked || missing
                  ? 'repeating-linear-gradient(45deg, rgba(211,47,47,0.05) 0, rgba(211,47,47,0.05) 8px, rgba(211,47,47,0.1) 8px, rgba(211,47,47,0.1) 16px)'
                  : placeholder
                    ? 'repeating-linear-gradient(45deg, rgba(245,124,0,0.05) 0, rgba(245,124,0,0.05) 8px, rgba(245,124,0,0.1) 8px, rgba(245,124,0,0.1) 16px)'
                    : 'repeating-linear-gradient(45deg, rgba(0,0,0,0.02) 0, rgba(0,0,0,0.02) 8px, rgba(0,0,0,0.04) 8px, rgba(0,0,0,0.04) 16px)',
              }}
            >
              {safetyBlocked && (
                <Box sx={{ fontSize: 24, mb: 0.5 }}>⛔️</Box>
              )}
              <Box>{placeholderText}</Box>
              {safetyBlocked && (
                <Box sx={{ fontSize: 10, mt: 0.5, px: 1, textAlign: 'center', opacity: 0.8 }}>
                  点击重新生成
                </Box>
              )}
            </Box>
          )}
          <Box sx={{ position: 'absolute', top: 8, left: 8 }}>
            <Chip size="small" label={statusLabel} color={statusColor} />
          </Box>
          {placeholder && (
            <Box sx={{ position: 'absolute', top: 8, right: 8 }}>
              <Chip size="small" label="占位" variant="outlined" color="warning" />
            </Box>
          )}
        </Box>
        <Box sx={{ p: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 600 }} display="block">
            {item.title}
          </Typography>
          {roleLabel && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
              {roleLabel}
            </Typography>
          )}
          {safetyError && (
            <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
              {safetyError.slice(0, 100)}{safetyError.length > 100 ? '...' : ''}
            </Typography>
          )}
          {previewError && (
            <Typography variant="caption" color="error" display="block" sx={{ mb: 0.5, fontSize: '0.7rem', wordBreak: 'break-all' }}>
              {previewError.slice(0, 100)}{previewError.length > 100 ? '...' : ''}
            </Typography>
          )}
          <Stack direction="row" spacing={1} alignItems="center" mt={0.5} flexWrap="wrap">
            {asset ? (
              <>
                {!safetyBlocked && hasRenderableImage && (
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => approveLibrary({ roles: [asset.role], approved: !approved })}
                    disabled={libraryLoading}
                  >
                    {approved ? '撤销' : '通过'}
                  </Button>
                )}
                {!safetyBlocked && hasRenderableImage && (!preview || previewError) && (
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => loadLibraryPreview(asset, { force: true })}
                    disabled={libraryLoading || previewLoading}
                  >
                    {previewLoading ? '加载中…' : preview ? '重新加载预览' : '加载预览'}
                  </Button>
                )}
                <Button
                  size="small"
                  variant={safetyBlocked ? 'contained' : 'text'}
                  color={safetyBlocked ? 'warning' : 'primary'}
                  onClick={() => openRegenerateDialog(asset)}
                  disabled={libraryLoading}
                >
                  {hasRenderableImage ? '重新生成' : '生成素材'}
                </Button>
              </>
            ) : canGenerate ? (
              <Button size="small" variant="text" onClick={() => openRegenerateDialogForRole(item.role, item.title)} disabled={libraryLoading}>
                生成素材
              </Button>
            ) : (
              <Chip size="small" label="等待生成" variant="outlined" />
            )}
          </Stack>
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

  const renderStreamingPreview = (step: number) => {
    const planText = String(streamSnapshots.plan || '').trim()
    const scriptText = String(streamSnapshots.script || streamSnapshots.scriptEnhance || '').trim()
    const profileText = String(streamSnapshots.characterProfiles || '').trim()
    const audioText = String(streamSnapshots.audioMarkers || '').trim()
    const storyboardText = String(streamSnapshots.storyboard || '').trim()
    const cameraTreeText = String(streamSnapshots.cameraTree || '').trim()

    if (step === 0) {
      if (!planText && !scriptText && !profileText && !audioText) return null
      return (
        <Box sx={{ mb: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              流式预览
            </Typography>
            {activeStreamKeys.length > 0 && <Chip size="small" label={`实时输出: ${activeStreamKeys.join(', ')}`} />}
          </Stack>
          {renderStreamingTextBlock('计划/脚本提要（流式）', planText, { maxHeight: 200 })}
          {renderStreamingTextBlock('剧本（流式）', scriptText, { maxHeight: 400 })}
          {renderStreamingTextBlock('角色小传（流式）', profileText, { maxHeight: 200 })}
          {renderStreamingTextBlock('音频标记（流式）', audioText, { maxHeight: 200, monospace: true })}
        </Box>
      )
    }

    if (step === 1) {
      if (!storyboardText && !cameraTreeText) return null
      return (
        <Box sx={{ mb: 1 }}>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mb: 0.5 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              流式预览
            </Typography>
            {activeStreamKeys.length > 0 && <Chip size="small" label={`实时输出: ${activeStreamKeys.join(', ')}`} />}
          </Stack>
          {renderStreamingTextBlock('分镜（流式）', storyboardText, { maxHeight: 400 })}
          {renderStreamingTextBlock('镜头树（流式）', cameraTreeText, { maxHeight: 260 })}
        </Box>
      )
    }

    if (step === 2) {
      if (!libraryPlanItems.length) return null
      const plannedCount = libraryPlanItems.filter((i) => i.status === 'planned').length
      const doneCount = libraryPlanItems.filter((i) => i.status === 'done').length
      const processingCount = libraryPlanItems.filter((i) => i.status === 'processing').length
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
            {libraryPlanItems.slice(0, 12).map((item) => (
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
                    {item.status === 'processing' ? (
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
                    ) : (
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
                    )}
                    {item.status === 'processing' && (
                      <Box
                        sx={{
                          position: 'absolute',
                          top: 4,
                          right: 4,
                          bgcolor: 'warning.main',
                          color: 'white',
                          fontSize: '0.65rem',
                          px: 0.5,
                          py: 0.25,
                          borderRadius: 0.5,
                        }}
                      >
                        生成中
                      </Box>
                    )}
                    {item.status === 'done' && (
                      <Box
                        sx={{
                          position: 'absolute',
                          top: 4,
                          right: 4,
                          bgcolor: 'success.main',
                          color: 'white',
                          fontSize: '0.65rem',
                          px: 0.5,
                          py: 0.25,
                          borderRadius: 0.5,
                        }}
                      >
                        完成
                      </Box>
                    )}
                  </Box>
                  <CardContent sx={{ p: 1, '&:last-child': { pb: 1 } }}>
                    <Typography variant="caption" sx={{ fontWeight: 500, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.label || item.entity_name || item.role}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                      {item.status === 'done' ? '已生成' : item.status === 'processing' ? '生成中...' : '待生成'}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            ))}
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

    if (step === 3) {
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

    if (step === 4) {
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

    return null
  }

  const renderScriptStageSnapshot = () => {
    const planText = snapshotPlanText.trim()
    const scriptText = snapshotScriptText.trim()
    const profilesCount = snapshotCharacterProfiles.length
    const markersCount = snapshotAudioMarkers.length
    const entityCount = (key: string) => {
      if (!snapshotScriptEntities || typeof snapshotScriptEntities !== 'object') return 0
      const list = (snapshotScriptEntities as any)[key]
      return Array.isArray(list) ? list.length : 0
    }
    const entitySummary = snapshotScriptEntities
      ? `角色 ${entityCount('characters')}，场景 ${entityCount('scenes')}，道具 ${entityCount('props')}`
      : ''
    const hasGeneration = Boolean(snapshotScriptGeneration && Object.keys(snapshotScriptGeneration).length > 0)

    const renderJsonBlock = (value: any, emptyText: string, maxHeight = 240) => {
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
            maxHeight,
            overflow: 'auto',
          }}
        >
          {JSON.stringify(value, null, 2)}
        </Box>
      )
    }

    return (
      <Box sx={{ mb: 1 }}>
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              计划 / 剧本提要（快照）
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
              {planText || '暂无计划/提要快照（可能仍在生成或尚未落库）。'}
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                剧本（快照）
              </Typography>
              <Chip size="small" label={snapshotScriptApproved ? '已通过' : '未通过'} color={snapshotScriptApproved ? 'success' : 'default'} />
              <Chip size="small" label={`长度: ${scriptText.length}`} />
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
            {scriptText ? (
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
                {scriptText.length > 6000 ? `${scriptText.slice(0, 6000)}\n…` : scriptText}
              </Box>
            ) : (
              <Typography variant="body2" color="text.secondary">
                尚无可用剧本快照（可能仍在生成或尚未落库）。
              </Typography>
            )}
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                角色小传（快照）
              </Typography>
              {profilesCount > 0 && <Chip size="small" label={`${profilesCount} 条`} />}
            </Stack>
          </AccordionSummary>
          <AccordionDetails>{renderJsonBlock(snapshotCharacterProfiles, '暂无角色小传（可能尚未生成或未落库）。')}</AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                音频标记（快照）
              </Typography>
              {markersCount > 0 && <Chip size="small" label={`${markersCount} 条`} />}
            </Stack>
          </AccordionSummary>
          <AccordionDetails>{renderJsonBlock(snapshotAudioMarkers, '暂无音频标记（可能尚未生成或未落库）。')}</AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                实体抽取（快照）
              </Typography>
              {entitySummary && <Chip size="small" label={entitySummary} />}
            </Stack>
          </AccordionSummary>
          <AccordionDetails>{renderJsonBlock(snapshotScriptEntities, '暂无实体抽取数据（可能尚未生成或未落库）。')}</AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                剧本生成信息（快照）
              </Typography>
              {hasGeneration && <Chip size="small" label="已记录" />}
            </Stack>
          </AccordionSummary>
          <AccordionDetails>{renderJsonBlock(snapshotScriptGeneration, '暂无剧本生成信息（可能尚未生成或未落库）。')}</AccordionDetails>
        </Accordion>
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
          {safetyBlockedShots.map((item) => {
            const label = item.shotIndex != null ? `#${item.shotIndex} ${item.shotId}` : item.shotId
            return (
              <Button key={item.shotId} size="small" variant="outlined" onClick={() => openSafetyBlockedShot(item.shotId)}>
                {label}
              </Button>
            )
          })}
        </Stack>
        {safetyBlockedShots[0]?.errorSample && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
            示例错误：{safetyBlockedShots[0].errorSample}
          </Typography>
        )}
      </Alert>
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
      if (e?.response?.status === 404) {
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
    persistedStatus: string | null,
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
      prompt_review_required: promptReviewRequired,
      style_preset: stylePreset,
      image_ratio: imageRatio,
      image_resolution: imageResolution,
      selected_chapter_ids: selectedChapterIds,
    })
  }, [
    highQuality,
    imageRatio,
    imageResolution,
    qcAllowFail,
    smartTuning,
    videoRequireConfirmation,
    promptReviewRequired,
    result?.run_id,
    selectedChapterIds,
    selectedProjectId,
    stylePreset,
    taskId,
    taskRunId,
    taskStatus,
  ])

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
    resetDreamweaverEvents()
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
    setError(null)
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
      if (!mergedVideoPreviewUrl) return
      try {
        URL.revokeObjectURL(mergedVideoPreviewUrl)
      } catch {
        // ignore
      }
    }
  }, [mergedVideoPreviewUrl])

  const applyStageSignal = useCallback((stage: string | null, payload: any) => {
    if (stage) setTaskStage(stage)
    const stateRaw = payload && typeof payload.state === 'string' ? String(payload.state) : null
    if (stateRaw) setTaskState(stateRaw)
    const progressRaw = payload && typeof payload.progress === 'number' ? payload.progress : null
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

  const normalizeAssetPlanItems = useCallback((items: any[]): DreamweaverAssetPlanItem[] => {
    if (!Array.isArray(items)) return []
    return items
      .map((raw) => {
        if (!raw || typeof raw !== 'object') return null
        const id = String((raw as any).id || '').trim()
        if (!id) return null
        const kindRaw = String((raw as any).kind || '').trim().toLowerCase()
        const roleRaw = String((raw as any).role || '').trim()
        const statusRaw = String((raw as any).status || '').trim().toLowerCase()
        const kind = kindRaw === 'video' ? 'video' : kindRaw === 'image' ? 'image' : roleRaw === 'video_clip' || roleRaw === 'merged_video' ? 'video' : 'image'
        const status = statusRaw === 'done' ? 'done' : statusRaw === 'processing' ? 'processing' : 'planned'
        const uri = typeof (raw as any).uri === 'string' ? String((raw as any).uri || '').trim() : ''
        return {
          id,
          shot_id: (raw as any).shot_id != null ? String((raw as any).shot_id) : null,
          scene_id: (raw as any).scene_id != null ? String((raw as any).scene_id) : null,
          cam_idx: typeof (raw as any).cam_idx === 'number' ? (raw as any).cam_idx : null,
          role: roleRaw || null,
          kind,
          label: typeof (raw as any).label === 'string' ? String((raw as any).label || '') : id,
          status,
          optional: Boolean((raw as any).optional),
          uri: uri || null,
        } as DreamweaverAssetPlanItem
      })
      .filter(Boolean) as DreamweaverAssetPlanItem[]
  }, [])

  const normalizeLibraryPlanItems = useCallback((items: any[]): DreamweaverLibraryPlanItem[] => {
    if (!Array.isArray(items)) return []
    return items
      .map((raw) => {
        if (!raw || typeof raw !== 'object') return null
        const role = String((raw as any).role || '').trim()
        const id = String((raw as any).id || role || '').trim()
        if (!id || !role) return null
        const statusRaw = String((raw as any).status || '').trim().toLowerCase()
        const status = statusRaw === 'done' ? 'done' : statusRaw === 'planned' ? 'planned' : 'processing'
        const entityType = (raw as any).entity_type != null ? String((raw as any).entity_type) : null
        const entityId = typeof (raw as any).entity_id === 'number' ? (raw as any).entity_id : Number((raw as any).entity_id || 0) || null
        const entityName = typeof (raw as any).entity_name === 'string' ? String((raw as any).entity_name || '').trim() : null
        const label = typeof (raw as any).label === 'string' ? String((raw as any).label || '').trim() : ''
        const view = typeof (raw as any).view === 'string' ? String((raw as any).view || '').trim() : null
        const uri = typeof (raw as any).uri === 'string' ? String((raw as any).uri || '').trim() : ''
        const assetId = typeof (raw as any).asset_id === 'number' ? (raw as any).asset_id : Number((raw as any).asset_id || 0) || null
        const approved = typeof (raw as any).approved === 'boolean' ? Boolean((raw as any).approved) : null
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
        const streamKeyRaw = payload && typeof (payload as any).stream_key === 'string' ? String((payload as any).stream_key || '').trim() : ''
        const streamKey = streamKeyRaw || stage || 'default'

        if (eventType === 'text_stream_start') {
          setStreamTextByKey((prev) => ({ ...prev, [streamKey]: '' }))
          setStreamMetaByKey((prev) => ({ ...prev, [streamKey]: { stage, done: false } }))
          return
        }

        if (eventType === 'text_stream_delta') {
          const chunk = payload && typeof (payload as any).chunk === 'string' ? String((payload as any).chunk || '') : ''
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
        const items = normalizeLibraryPlanItems((payload as any)?.items)
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
        const items = normalizeAssetPlanItems((payload as any)?.items)
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
        const assetId = typeof (payload as any)?.id === 'string' ? String((payload as any).id || '').trim() : ''
        if (!assetId) return
        const uri = typeof (payload as any)?.uri === 'string' ? String((payload as any).uri || '').trim() : ''
        const role = typeof (payload as any)?.role === 'string' ? String((payload as any).role || '').trim() : ''
        const kindRaw = typeof (payload as any)?.kind === 'string' ? String((payload as any).kind || '').trim().toLowerCase() : ''
        const kind = kindRaw === 'video' ? 'video' : kindRaw === 'image' ? 'image' : role === 'video_clip' || role === 'merged_video' ? 'video' : 'image'

        setAssetPlanItems((prev) => {
          const map = new Map(prev.map((item) => [item.id, item]))
          const existing = map.get(assetId)
          const next: DreamweaverAssetPlanItem = {
            id: assetId,
            shot_id: (payload as any)?.shot_id != null ? String((payload as any).shot_id) : existing?.shot_id ?? null,
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
        const err = typeof (payload as any)?.error === 'string' ? String((payload as any).error || '').trim() : ''
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
          const rows = Array.isArray(res.data) ? (res.data as DreamweaverEventRecord[]) : []
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
      } catch (e: any) {
        if (e?.response?.status === 404) {
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
  const waitingScriptApproval = waitingApproval && waitingKind === 'waiting_script_approval'
  const waitingVideoConfirmation = waitingApproval && waitingKind === 'waiting_video_confirmation'
  const persistedRunId = taskRunId || result?.run_id || null
  const currentRunId = persistedRunId
  const libraryApproved = Boolean(library?.review?.approved)

  useEffect(() => {
    autoLoadedLibraryRef.current = false
  }, [currentRunId])
  const snapshotRuntimeCfg =
    runSnapshot?.contract && typeof (runSnapshot as any).contract === 'object' && (runSnapshot as any).contract.runtime_config && typeof (runSnapshot as any).contract.runtime_config === 'object'
      ? ((runSnapshot as any).contract.runtime_config as any)
      : {}
  const videoClipJobs: any[] = Array.isArray(snapshotRuntimeCfg.video_clip_jobs) ? (snapshotRuntimeCfg.video_clip_jobs as any[]) : []
  const promptReviewRequiredSnapshot = Boolean(snapshotRuntimeCfg?.prompt_review_required)
  const promptReviewApproved = Boolean(snapshotRuntimeCfg?.prompt_review?.approved)
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
      console.error('WebSocket 连接失败:', error)
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
      const data = (res.data as any) || null
      setRunSnapshot(data)
      if (String(data?.status || '').trim().toLowerCase() === 'completed') {
        const nextResult = buildResultFromRunSnapshot(data, persistedRunId)
        if (nextResult) setResult((prev) => mergeRunResult(prev, nextResult))
      }
    } catch (e: any) {
      if (e?.response?.status === 404) {
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

  const collectMergedVideo = useCallback(async () => {
    if (!currentRunId) {
      setMergedVideoCollectFeedback({ type: 'error', text: '缺少 run_id，无法归档合成视频' })
      return
    }

    const mergedPath =
      result?.merged_video ||
      (runSnapshot?.contract && typeof runSnapshot.contract === 'object'
        ? extractMergedVideoFromContract(runSnapshot.contract as Record<string, any>)
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
  const approvePromptReview = async (approved: boolean) => {
    if (!currentRunId) return
    setPromptReviewLoading(true)
    setPromptReviewError(null)
    try {
      await apiClient.approveDreamweaverPromptReview(currentRunId, { approved })
      await loadRunSnapshot()
    } catch (e: any) {
      setPromptReviewError(await extractApiErrorMessage(e, '更新提示词审核状态失败'))
    } finally {
      setPromptReviewLoading(false)
    }
  }

  const openPromptEditDialog = (shot: any) => {
    const head = String(shot?.head_frame?.prompt || '').trim()
    const tail = String(shot?.tail_frame?.prompt || '').trim()
    const meta = shot?.shot_schema_v2?.meta && typeof shot.shot_schema_v2.meta === 'object' ? shot.shot_schema_v2.meta : {}
    const videoOverride = String(meta?.video_prompt_override || '').trim()
    setPromptEditShot(shot)
    setPromptEditHead(head)
    setPromptEditTail(tail)
    setPromptEditVideo(videoOverride)
    setPromptEditError(null)
    setPromptEditOpen(true)
  }

  const savePromptEdit = async () => {
    if (!currentRunId || !promptEditShot) return
    const shotId = String(promptEditShot?.shot_key || promptEditShot?.shot_id || '').trim()
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

    const originHead = String(promptEditShot?.head_frame?.prompt || '').trim()
    const originTail = String(promptEditShot?.tail_frame?.prompt || '').trim()
    const originVideo = String(promptEditShot?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
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
    } catch (e: any) {
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
      const data = res.data as LibraryPayload
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
          } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
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
    } catch (e: any) {
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
      } catch (e: any) {
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
    const episodes = (runSnapshot as any)?.contract?.episodes
    if (!Array.isArray(episodes)) return []
    const shots: any[] = []
    for (const ep of episodes) {
      const epShots = (ep as any)?.shots
      if (Array.isArray(epShots)) shots.push(...epShots)
    }
    return shots
  }, [runSnapshot])

  const safetyBlockedShots = useMemo(() => {
    const results: Array<{ shotId: string; shotIndex?: number; roles: string[]; errorSample: string }> = []
    const pattern = /datainspectionfailed|inappropriate content|content check failed/i
    for (const shot of snapshotShots) {
      const shotId = String((shot as any)?.shot_key || (shot as any)?.shot_id || '').trim()
      if (!shotId) continue
      const roles = new Set<string>()
      let errorSample = ''
      const assets = Array.isArray((shot as any)?.assets) ? ((shot as any).assets as any[]) : []
      for (const asset of assets) {
        if (!asset || typeof asset !== 'object') continue
        const meta = asset.meta && typeof asset.meta === 'object' ? asset.meta : {}
        const safetyError = typeof meta.safety_error === 'string' ? meta.safety_error : ''
        const errorText = typeof meta.error === 'string' ? meta.error : ''
        const messageText = typeof meta.message === 'string' ? meta.message : ''
        const combined = [safetyError, errorText, messageText].filter((v) => v && v.trim()).join(' | ')
        const isBlocked = Boolean(meta.safety_blocked) || (combined && pattern.test(combined))
        if (!isBlocked) continue
        const role = String((asset as any).role || '').trim()
        if (role) roles.add(role)
        if (!errorSample && combined) errorSample = combined
      }
      if (!roles.size) continue
      results.push({
        shotId,
        shotIndex: typeof (shot as any)?.shot_index === 'number' ? (shot as any).shot_index : undefined,
        roles: Array.from(roles),
        errorSample,
      })
    }
    return results
  }, [snapshotShots])

  const snapshotShotById = useMemo(() => {
    const map = new Map<string, any>()
    for (const shot of snapshotShots) {
      const id = String((shot as any)?.shot_key || (shot as any)?.shot_id || '').trim()
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

  const libraryPromptReviewMessage = libraryApproved
    ? promptReviewReady
      ? '素材库已通过，提示词已确认：可继续生成进入镜头阶段。'
      : '素材库已通过，但提示词待确认：请先完成提示词审核。'
    : promptReviewRequiredSnapshot
      ? '素材库待审核：通过后还需确认提示词，才能继续生成。'
      : '素材库待审核：通过后可继续生成。'

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

  const snapshotScriptEntities = useMemo(() => {
    const entities = snapshotRuntimeConfig?.script_entities
    return entities && typeof entities === 'object' ? (entities as any) : null
  }, [snapshotRuntimeConfig])

  const snapshotScriptGeneration = useMemo(() => {
    const generation = snapshotRuntimeConfig?.script_generation
    return generation && typeof generation === 'object' ? (generation as any) : null
  }, [snapshotRuntimeConfig])

  const snapshotCharacterProfiles = useMemo(() => {
    const profiles = snapshotRuntimeConfig?.character_profiles
    return Array.isArray(profiles) ? (profiles as any[]) : []
  }, [snapshotRuntimeConfig])

  const snapshotAudioMarkers = useMemo(() => {
    const markers = snapshotRuntimeConfig?.audio_markers
    return Array.isArray(markers) ? (markers as any[]) : []
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
    const specCharacters = Array.isArray(library?.spec?.characters) ? (library!.spec!.characters as any[]) : []
    for (const item of specCharacters) {
      rememberCharacterName(item?.entity_id, item?.name)
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
    const result: Array<{
      key: LibraryDisplayItem['group']
      label: string
      items: LibraryDisplayItem[]
      summary: { total: number; generated: number; processing: number; planned: number; approved: number; pendingReview: number }
    }> = []
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

  const toggleShotPromptExpanded = useCallback((key: string) => {
    const safeKey = String(key || '').trim()
    if (!safeKey) return
    setShotPromptExpanded((prev) => ({ ...prev, [safeKey]: !prev[safeKey] }))
  }, [])

  const renderPendingView = () => (
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
                      {renderSafetyBlockedAlert()}

                      {renderStreamingPreview(previewStep)}

                      {previewStep === 0 && !runSnapshotLoading && renderScriptStageSnapshot()}

                      {previewStep === 1 && !runSnapshotLoading && (
                        <Box sx={{ mb: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                            镜头列表
                          </Typography>
                          {snapshotShots.length ? (
                            <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                              {snapshotShots.slice(0, 12).map((shot: any, idx: number) => {
                                const shotKey = String(shot?.shot_key || shot?.shot_id || shot?.shot_index || idx).trim()
                                const expanded = Boolean(shotPromptExpanded[shotKey])
                                const headPrompt = String(shot?.head_frame?.prompt || '').trim()
                                const tailPrompt = String(shot?.tail_frame?.prompt || '').trim()
                                const overridePrompt = String(shot?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
                                const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
                                const promptLines: string[] = []
                                const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}…`)
                                if (headPrompt) promptLines.push(`首帧: ${formatPrompt(headPrompt)}`)
                                if (tailPrompt) promptLines.push(`尾帧: ${formatPrompt(tailPrompt)}`)
                                if (overridePrompt) {
                                  promptLines.push(`视频覆盖: ${formatPrompt(overridePrompt)}`)
                                }
                                const promptText = hasPrompt ? promptLines.join('\n') : '暂无提示词快照'
                                return (
                                  <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
                                    <ListItemText
                                      primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                      secondary={
                                        <>
                                          <Typography variant="caption" color="text.secondary" display="block">
                                            场景: {shot.scene_id || '-'}  时长: {typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s
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
                              })}
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
                          {snapshotMergedVideo && renderMergedVideoPanel()}
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
                  ) : waitingScriptApproval && previewStep === 0 ? (
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
                  ) : waitingVideoConfirmation && previewStep === 3 ? (
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
                              const shot = sid ? snapshotShotById.get(sid) : null
                              const headPrompt = String((shot as any)?.head_frame?.prompt || '').trim()
                              const tailPrompt = String((shot as any)?.tail_frame?.prompt || '').trim()
                              const overridePrompt = String((shot as any)?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
                              const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)

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
                                    {hasPrompt ? (
                                      <Box sx={{ mt: 0.5 }}>
                                        <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
                                          首帧: {headPrompt ? (headPrompt.length > 120 ? `${headPrompt.slice(0, 120)}…` : headPrompt) : '-'}
                                        </Typography>
                                        <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
                                          尾帧: {tailPrompt ? (tailPrompt.length > 120 ? `${tailPrompt.slice(0, 120)}…` : tailPrompt) : '-'}
                                        </Typography>
                                        {overridePrompt && (
                                          <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
                                            视频覆盖: {overridePrompt.length > 120 ? `${overridePrompt.slice(0, 120)}…` : overridePrompt}
                                          </Typography>
                                        )}
                                      </Box>
                                    ) : (
                                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                                        暂无提示词快照
                                      </Typography>
                                    )}
                                  </Box>

                                  <Box sx={{ pl: 1 }}>
                                    <Stack spacing={0.5} alignItems="flex-end">
                                      <Button size="small" variant="contained" onClick={() => confirmVideoJob(sid)} disabled={disabled}>
                                        {actionLabel}
                                      </Button>
                                      <Button size="small" variant="outlined" onClick={() => shot && openPromptEditDialog(shot)} disabled={!shot}>
                                        查看提示词
                                      </Button>
                                    </Stack>
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
                    promptReviewRequiredSnapshot && previewStep === 1 ? (
                      <Box>
                        <Alert severity={promptReviewApproved ? 'success' : 'warning'} sx={{ mb: 1 }}>
                          {promptReviewApproved
                            ? libraryApproved
                              ? '提示词已确认、素材库已通过：可继续生成进入镜头阶段。'
                              : '提示词已确认，但素材库仍待审核。'
                            : '提示词待确认：请逐镜检查并修改，确认后再继续生成。'}
                        </Alert>

                        <Stack direction="row" spacing={1} flexWrap="wrap" mb={1} alignItems="center">
                          <Button size="small" variant="outlined" onClick={loadRunSnapshot} disabled={!persistedRunId || runSnapshotLoading}>
                            {runSnapshotLoading ? '刷新中…' : '刷新快照'}
                          </Button>
                          <Button
                            size="small"
                            variant="contained"
                            color="success"
                            onClick={() => approvePromptReview(true)}
                            disabled={!currentRunId || promptReviewLoading}
                          >
                            {promptReviewLoading ? '确认中…' : '确认提示词'}
                          </Button>
                          <Button
                            size="small"
                            variant="text"
                            onClick={() => approvePromptReview(false)}
                            disabled={!currentRunId || promptReviewLoading || !promptReviewApproved}
                          >
                            撤销确认
                          </Button>
                          <Button size="small" variant="contained" color="success" onClick={resumeGeneration} disabled={!canResumeFromLibrary}>
                            {resumeLoading ? '继续生成中…' : '继续生成'}
                          </Button>
                        </Stack>

                        {promptReviewError && (
                          <Alert severity="error" sx={{ mb: 1 }}>
                            {promptReviewError}
                          </Alert>
                        )}

                        {promptReviewShots.length ? (
                          <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                            {promptReviewShots.map((shot: any, idx: number) => {
                              const shotId = String(shot?.shot_key || shot?.shot_id || '').trim()
                              const headPrompt = String(shot?.head_frame?.prompt || '').trim()
                              const tailPrompt = String(shot?.tail_frame?.prompt || '').trim()
                              const overridePrompt = String(shot?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
                              const title = String(shot?.desc || '').trim()
                              return (
                                <ListItem
                                  key={shotId || String(idx)}
                                  disableGutters
                                  sx={{ px: 1, py: 0.75, borderBottom: '1px solid #f0f0f0', alignItems: 'flex-start' }}
                                >
                                  <Box sx={{ flex: 1, minWidth: 0 }}>
                                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
                                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                        #{shot?.shot_index || idx + 1} {title}
                                      </Typography>
                                      {shotId && <Chip size="small" label={shotId} variant="outlined" />}
                                      {overridePrompt && <Chip size="small" label="视频已覆盖" color="info" />}
                                    </Stack>
                                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                                      首帧: {headPrompt ? (headPrompt.length > 120 ? `${headPrompt.slice(0, 120)}…` : headPrompt) : '-'}
                                    </Typography>
                                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.25, whiteSpace: 'pre-wrap' }}>
                                      尾帧: {tailPrompt ? (tailPrompt.length > 120 ? `${tailPrompt.slice(0, 120)}…` : tailPrompt) : '-'}
                                    </Typography>
                                  </Box>
                                  <Box sx={{ pl: 1 }}>
                                    <Button size="small" variant="outlined" onClick={() => openPromptEditDialog(shot)}>
                                      编辑提示词
                                    </Button>
                                  </Box>
                                </ListItem>
                              )
                            })}
                          </List>
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            暂无可用镜头提示词快照（可能仍在生成或尚未落库）。
                          </Typography>
                        )}

                        {snapshotShots.length > 12 && (
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mt: 1 }}>
                            <Button size="small" variant="text" onClick={() => setPromptReviewShowAll((prev) => !prev)}>
                              {promptReviewShowAll ? '收起列表' : `显示全部(${snapshotShots.length})`}
                            </Button>
                          </Stack>
                        )}
                      </Box>
                    ) : currentRunId ? (
                      previewStep === 2 ? (
                        <Box>

                      <Alert severity={libraryApproved && promptReviewReady ? 'success' : 'warning'} sx={{ mb: 1 }}>
                        {libraryPromptReviewMessage}
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

                      {libraryDisplayItems.length ? (
                        <Box>
                          <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
                            <Chip size="small" label={`占位 ${librarySummary.total}`} />
                            <Chip size="small" label={`已生成 ${librarySummary.generated}`} color={librarySummary.generated ? 'success' : 'default'} />
                            <Chip size="small" label={`生成中 ${librarySummary.processing}`} color={librarySummary.processing ? 'info' : 'default'} />
                            <Chip size="small" label={`待生成 ${librarySummary.planned}`} />
                            {librarySummary.approved > 0 && (
                              <Chip size="small" label={`已通过 ${librarySummary.approved}`} color="success" />
                            )}
                            {librarySummary.pendingReview > 0 && (
                              <Chip size="small" label={`待审核 ${librarySummary.pendingReview}`} color="warning" />
                            )}
                          </Stack>

                          {libraryGroups.map((group) => {
                            const renderGroupGrid = () => {
                              if (group.key !== 'character') {
                                return (
                                  <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
                                    {group.items.map(renderLibraryDisplayCard)}
                                  </ImageList>
                                )
                              }

                              const viewSuffixes = CHARACTER_VIEW_ORDER.map((view) => characterViewLabel(view)).sort((a, b) => b.length - a.length)
                              const stripViewSuffix = (value: string) => {
                                const text = String(value || '').trim()
                                for (const suffix of viewSuffixes) {
                                  const candidate = ` ${suffix}`
                                  if (text.endsWith(candidate)) return text.slice(0, -candidate.length).trim()
                                }
                                return text
                              }

                              const buckets = new Map<
                                string,
                                { bucketKey: string; entityId: number; name: string; items: LibraryDisplayItem[] }
                              >()
                              for (const item of group.items) {
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
                                  {orderedBuckets.map((bucket) => {
                                    const generatedCount = bucket.items.filter((it) => it.hasRenderableImage).length
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
                                  })}
                                </Stack>
                              )
                            }

                            return (
                              <Box key={group.key} sx={{ mb: 2 }}>
                                <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 0.5 }}>
                                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                    {group.label}
                                  </Typography>
                                  <Chip size="small" label={`总计 ${group.summary.total}`} />
                                  <Chip size="small" label={`已生成 ${group.summary.generated}`} color={group.summary.generated ? 'success' : 'default'} />
                                  <Chip size="small" label={`生成中 ${group.summary.processing}`} color={group.summary.processing ? 'info' : 'default'} />
                                  <Chip size="small" label={`待生成 ${group.summary.planned}`} />
                                  {group.summary.approved > 0 && <Chip size="small" label={`已通过 ${group.summary.approved}`} color="success" />}
                                  {group.summary.pendingReview > 0 && <Chip size="small" label={`待审核 ${group.summary.pendingReview}`} color="warning" />}
                                </Stack>
                                {renderGroupGrid()}
                              </Box>
                            )
                          })}
                        </Box>
                      ) : (
                        <Typography variant="body2" color="text.secondary">{'未加载素材库或当前项目暂无可审核素材。'}</Typography>
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
                          severity={libraryApproved && promptReviewReady ? 'success' : 'info'}
                          sx={{ mb: 1 }}
                          action={
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
                          }
                        >
                          {libraryPromptReviewMessage}
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
                      {renderSafetyBlockedAlert()}

                      {previewStep === 0 && !runSnapshotLoading && renderScriptStageSnapshot()}

                        {previewStep === 1 && !runSnapshotLoading && (
                          <Box sx={{ mb: 1 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                              镜头列表
                            </Typography>
                            {snapshotShots.length ? (
                              <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
                                {snapshotShots.slice(0, 12).map((shot: any, idx: number) => {
                                  const shotKey = String(shot?.shot_key || shot?.shot_id || shot?.shot_index || idx).trim()
                                  const expanded = Boolean(shotPromptExpanded[shotKey])
                                  const headPrompt = String(shot?.head_frame?.prompt || '').trim()
                                  const tailPrompt = String(shot?.tail_frame?.prompt || '').trim()
                                  const overridePrompt = String(shot?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
                                  const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
                                  const promptLines: string[] = []
                                  const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}…`)
                                  if (headPrompt) promptLines.push(`首帧: ${formatPrompt(headPrompt)}`)
                                  if (tailPrompt) promptLines.push(`尾帧: ${formatPrompt(tailPrompt)}`)
                                  if (overridePrompt) {
                                    promptLines.push(`视频覆盖: ${formatPrompt(overridePrompt)}`)
                                  }
                                  const promptText = hasPrompt ? promptLines.join('\n') : '暂无提示词快照'
                                  return (
                                    <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
                                      <ListItemText
                                        primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                        secondary={
                                          <>
                                            <Typography variant="caption" color="text.secondary" display="block">
                                              场景: {shot.scene_id || '-'}  时长: {typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s
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
                                })}
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
                            {snapshotMergedVideo && renderMergedVideoPanel()}
                          </Box>
                        )}
                      </Box>
                    )
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      点击“开始生成”后，这里会展示「{DREAMWEAVER_PREVIEW_STEPS[previewStep]}」相关产物与进度。
                    </Typography>
                  )
  ))

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
                              提示词审核
                            </Typography>
                            <FormControlLabel
                              sx={{ mr: 0 }}
                              control={
                                <Switch
                                  checked={promptReviewRequired}
                                  onChange={(e) => setPromptReviewRequired(e.target.checked)}
                                  disabled={running}
                                />
                              }
                              label={promptReviewRequired ? '先审提示词' : '直接生成'}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            生成关键帧/视频前先停在提示词审核，可修改后再提交生成任务。
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
                {renderStageOverview()}
                {!result ? (
                  renderPendingView()
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

                    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={loadRunSnapshot}
                        disabled={!persistedRunId || runSnapshotLoading}
                      >
                        {runSnapshotLoading ? '加载中…' : '刷新运行快照'}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => currentRunId && syncDreamweaverEvents(currentRunId)}
                        disabled={!currentRunId || eventSyncing}
                      >
                        {eventSyncing ? '同步中…' : '同步事件'}
                      </Button>
                      {runSnapshot && runSnapshot.run_id === persistedRunId && (
                        <Chip size="small" label="快照已加载" color="success" />
                      )}
                      {eventCursor > 0 && <Chip size="small" label={`事件#${eventCursor}`} variant="outlined" />}
                    </Stack>
                    {runSnapshotError && (
                      <Alert severity="error" sx={{ mb: 1 }}>
                        {runSnapshotError}
                      </Alert>
                    )}
                    {eventSyncError && (
                      <Alert severity="warning" sx={{ mb: 1 }}>
                        {eventSyncError}
                      </Alert>
                    )}
                    {runSnapshotLoading && <LinearProgress sx={{ mb: 1 }} />}

                    {renderStreamingPreview(previewStep)}

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
                            {snapshotShots.slice(0, 12).map((shot: any, idx: number) => {
                              const shotKey = String(shot?.shot_key || shot?.shot_id || shot?.shot_index || idx).trim()
                              const expanded = Boolean(shotPromptExpanded[shotKey])
                              const headPrompt = String(shot?.head_frame?.prompt || '').trim()
                              const tailPrompt = String(shot?.tail_frame?.prompt || '').trim()
                              const overridePrompt = String(shot?.shot_schema_v2?.meta?.video_prompt_override || '').trim()
                              const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
                              const promptLines: string[] = []
                              const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}…`)
                              if (headPrompt) promptLines.push(`首帧: ${formatPrompt(headPrompt)}`)
                              if (tailPrompt) promptLines.push(`尾帧: ${formatPrompt(tailPrompt)}`)
                              if (overridePrompt) {
                                promptLines.push(`视频覆盖: ${formatPrompt(overridePrompt)}`)
                              }
                              const promptText = hasPrompt ? promptLines.join('\n') : '暂无提示词快照'
                              return (
                                <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
                                  <ListItemText
                                    primary={`#${shot.shot_index} ${shot.desc || ''}`.trim()}
                                    secondary={
                                      <>
                                        <Typography variant="caption" color="text.secondary" display="block">
                                          场景: {shot.scene_id || '-'}  时长: {typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'}s
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
                            })}
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
                          renderMergedVideoPanel({ centeredPreview: true })
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
                      {regenImageEditActive
                        ? '图像编辑模式：将基于参考图生成，提交后状态变为“待审核”。'
                        : '可在下方编辑提示词并重生成素材，生成后将变为待审核状态。'}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }} flexWrap="wrap">
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => requestSmartRegeneratePrompt({ source: 'manual' })}
                        disabled={regenSubmitting || regenSuggesting || !regenRole}
                      >
                        {regenSuggesting ? '提示词生成中…' : '智能生成提示词'}
                      </Button>
                      {regenForceImageEdit ? (
                        <Chip size="small" color="secondary" variant="outlined" label="图像编辑：强制" />
                      ) : (
                        <Button
                          size="small"
                          variant={regenImageEditActive ? 'contained' : 'outlined'}
                          color={regenImageEditActive ? 'secondary' : 'primary'}
                          aria-pressed={regenImageEditActive}
                          onClick={toggleRegenImageEditPreference}
                          disabled={regenSubmitting || regenSuggesting || !regenHasImageBase}
                        >
                          {regenImageEditActive ? '图像编辑：开启' : '使用图像编辑'}
                        </Button>
                      )}
                    </Stack>
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
                    <TextField
                      label={regenPromptInputLabel}
                      fullWidth
                      multiline
                      minRows={8}
                      value={regenPrompt}
                      placeholder={
                        regenImageEditActive && regenImageEditAutoCleared
                          ? '示例：保持角色身份锚点不变，改为侧面全身，左肩数据接口更亮，背景保持纯灰色。'
                          : undefined
                      }
                      onChange={(e) => {
                        setRegenPrompt(e.target.value)
                        setRegenPromptDirty(e.target.value.trim() !== regenPromptInitial.trim())
                      }}
                      disabled={regenSubmitting || regenSuggesting}
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
                      disabled={regenSubmitting || regenSuggesting || !regenRole || (regenForceImageEdit && !regenHasImageBase)}
                    >
                      {regenSubmitting
                        ? '生成中…'
                        : regenImageEditActive
                          ? '开始生成（图像编辑）'
                          : '开始生成（提示词）'}
                    </Button>
                  </DialogActions>
                </Dialog>

                <Dialog
                  open={promptEditOpen}
                  onClose={() => {
                    if (promptEditSaving) return
                    setPromptEditOpen(false)
                  }}
                  fullWidth
                  maxWidth="md"
                >
                  <DialogTitle>
                    提示词审核：{String(promptEditShot?.shot_key || promptEditShot?.shot_id || '').trim() || '未选中'}
                  </DialogTitle>
                  <DialogContent dividers>
                    {promptEditShot && (
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                        镜头描述：{String(promptEditShot?.desc || '').trim() || '-'}
                      </Typography>
                    )}
                    <Stack spacing={1.5}>
                      <TextField
                        label="首帧提示词"
                        fullWidth
                        multiline
                        minRows={3}
                        value={promptEditHead}
                        onChange={(e) => setPromptEditHead(e.target.value)}
                        disabled={promptEditSaving}
                      />
                      <TextField
                        label="尾帧提示词"
                        fullWidth
                        multiline
                        minRows={3}
                        value={promptEditTail}
                        onChange={(e) => setPromptEditTail(e.target.value)}
                        disabled={promptEditSaving}
                      />
                      <TextField
                        label="视频提示词（自动）"
                        fullWidth
                        multiline
                        minRows={3}
                        value={promptEditGenerated || '暂无自动提示词（可能尚未生成或未落库）'}
                        InputProps={{ readOnly: true }}
                      />
                      <TextField
                        label="视频提示词覆盖（可选）"
                        fullWidth
                        multiline
                        minRows={3}
                        value={promptEditVideo}
                        onChange={(e) => setPromptEditVideo(e.target.value)}
                        disabled={promptEditSaving}
                        placeholder="留空则使用系统拼接的默认视频提示词"
                      />
                    </Stack>
                    {promptEditError && (
                      <Alert severity="error" sx={{ mt: 1 }}>
                        {promptEditError}
                      </Alert>
                    )}
                  </DialogContent>
                  <DialogActions>
                    <Button onClick={() => setPromptEditOpen(false)} disabled={promptEditSaving}>
                      取消
                    </Button>
                    <Button variant="contained" onClick={savePromptEdit} disabled={promptEditSaving}>
                      {promptEditSaving ? '保存中…' : '保存'}
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
