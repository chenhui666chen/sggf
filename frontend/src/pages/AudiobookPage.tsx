/**
 * 耳畔星河 - 有声小说生成页面
 * 
 * 功能：
 * 1. 项目选择与章节管理
 * 2. 音色配置
 * 3. 有声书生成
 * 4. 进度监控
 * 5. 音频播放与下载
 */
import { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback, ChangeEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  apiClient,
  describeTaskPointsPrecheckErrorDetail,
  extractApiErrorMessage,
  extractTaskPointsPrecheckErrorDetail,
  type TaskPointsPrecheckErrorDetail,
} from '../services/api'
import { buildAudiobookChapterAudioAssetMetadataContract } from '../contracts/userAssetMetadataBuilders'
import { buildAudiobookChapterAudioSourcePayload } from '../contracts/userAssetSourcePayloadBuilders'
import * as bookParserApi from '../services/bookParserApi'
import BrowserPlayer, { type BrowserPlayerProjectData } from '../components/audiobook/BrowserPlayer'
import TaskPointsPrecheckAlert from '../components/common/TaskPointsPrecheckAlert'
import { extractLocalAssetStorageMetadata, getLocalAssetBlob } from '../utils/localAssetVault'
import {
  buildAudiobookSourceFocusPlan,
  readUserAssetSourceAudiobookRouteRequest,
} from '../utils/userAssetSourceNavigation'
import { saveExplicitLocalUserAsset } from '../utils/userAssetExplicitLocalCollection'
import {
  Box,
  Container,
  Typography,
  Button,
  Grid,
  IconButton,
  Chip,
  LinearProgress,
  Rating,
  List,
  ListItem,
  ListItemText,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  Tooltip,
  Paper,
  Stepper,
  Step,
  StepLabel,
  CircularProgress,
  Divider,
  Checkbox,
  Slider,
  Snackbar,
  FormControlLabel,
  Menu,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AudioIcon from '@mui/icons-material/GraphicEq'
import CheckIcon from '@mui/icons-material/CheckCircle'
import DeleteIcon from '@mui/icons-material/Delete'
import DownloadIcon from '@mui/icons-material/Download'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import HistoryIcon from '@mui/icons-material/History'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import PauseIcon from '@mui/icons-material/Pause'
import PlayIcon from '@mui/icons-material/PlayArrow'
import VoiceIcon from '@mui/icons-material/RecordVoiceOver'
import WarningIcon from '@mui/icons-material/Warning'

// 类型定义
interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

interface Chapter {
  id: number
  chapter_number: number
  title: string
  content: string
}

// 新增：任务状态类型
type StageStatus = 'pending' | 'running' | 'completed' | 'failed'
type PreviewType = 'voice' | 'sfx' | 'bgm' | 'mix'
type TtsModel =
  | 'qwen3-tts-instruct-flash'
  | 'cosyvoice-v3.5-plus'
  | 'minimax-speech-2.8-hd'
  | 'minimax-speech-2.8-turbo'
type AudioOutputFormat = 'mp3' | 'wav' | 'm4b'
type NarrationStyleId = 'professional' | 'dramatic' | 'relaxing' | 'expressive'

interface StageInfo {
  status: StageStatus
  progress: number
  start_time?: string
  end_time?: string
  error_message?: string
  metrics?: Record<string, any>
  message?: string
}

interface TaskStatus {
  task_id: string
  audiobook_project_id: number
  chapter_id?: number | null
  task_type?: string | null
  status: StageStatus
  current_stage?: string | null
  progress: number
  stages: Record<StageKey, StageInfo>
  created_at?: string
  updated_at?: string
  detail?: Record<string, any>
  overall_progress?: number
}

interface CharacterVoiceSetting {
  characterId: number
  name: string
  gender?: string | null
  role?: string | null
  voiceId: string
  volume: number
  speed?: number
  pitch?: number
  ttsModel?: TtsModel  // 🆕 角色使用的TTS模型
  voiceType?: string  // 🆕 声音类型（威严/温柔/活泼等）
  personality?: string  // 🆕 性格类型（内向/外向等）
  emotionTendency?: string  // 🆕 情感倾向（积极/消极/中性/多变）
}

interface AudioFxConfig {
  enable_sound_effects: boolean
  enable_music: boolean
  sound_effect_density: 'low' | 'medium' | 'high' | 'off'
  music_density: 'low' | 'medium' | 'high' | 'off'
}

interface ProjectAudioConfig {
  characters: {
    character_id: number
    name: string
    voice_id: string
    volume: number
    speed?: number | null
    pitch?: number | null
    tts_model?: TtsModel | null  // 🆕 TTS模型
    voice_type?: string | null  // 🆕 声音类型
    personality?: string | null  // 🆕 性格类型
    emotion_tendency?: string | null  // 🆕 情感倾向
  }[]
  audio_fx?: AudioFxConfig | null
}

interface AudiobookSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  taskId?: string | null
  activeTasks?: Array<{
    taskId: string
    audiobookProjectId: number
  }>
  selectedChapterIds?: number[]
  activeStep?: number
  generating?: boolean
  ttsModel?: TtsModel
  updatedAt?: string
  writerTabId?: string
}

interface GenerationCheckpoint {
  chapter_id: number
  total_segments: number
  completed_segments: number
  completed_segment_indices?: number[]
  cached_audio_paths?: Record<string, string>
  can_resume: boolean
  run_id?: number | null
  run_status?: string | null
  current_stage?: string | null
  celery_task_id?: string | null
  checkpoint_source?: string | null
  estimated_remaining_time?: number | null
}

interface ScriptEditorDialogProps {
  open: boolean
  loading: boolean
  chapter: {
    chapterId: number
    title: string
  } | null
  data: {
    scriptStatus: string
    scriptSegments: any[]
    scriptReview: ScriptReviewDetail | null
  } | null
  onClose: () => void
  onChangeSegmentText: (index: number, value: string) => void
  onSaveScript: (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => void
  onPreviewSegmentAudio: (index: number, segment: any, previewType: PreviewType) => void
  onRegenerateSegment: (index: number, segment: any) => void
  onReviewSegment: (index: number, score: number) => void
  segmentReviews: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  segmentPreviewingIndex: number | null
  segmentPreviewingType: PreviewType | null
  segmentAudioUrls: Record<number, string>
  segmentDetailsOpen: Record<number, boolean>
  onToggleSegmentDetails: (index: number) => void
  onUpdateSegment: (index: number, patch: Record<string, any>) => void
  reviewMode: boolean
  onToggleReviewMode: () => void
  regeneratingSegments: Set<number>
  editorConflict: AudiobookEditorSessionState | null
  onApplyIncomingDraft: () => void
  onKeepLocalDraft: () => void
}

interface HistoryDialogProps {
  open: boolean
  loading: boolean
  historyProjects: any[]
  selectedProject: Project | null
  onCloseHistory: () => void
  onViewHistory: (audiobookProjectId: number) => Promise<void>
  onDeleteHistory: (audiobookProjectId: number) => Promise<void>
}

function buildAudiobookChapterDownloadUrl(audiobookProjectId: number, chapterId: number): string {
  return `/api/v1/audiobook/download/${audiobookProjectId}/${chapterId}`
}

function buildAudiobookChapterAssetUuid(audiobookProjectId: number, chapterId: number): string {
  return `audiobook-${audiobookProjectId}-${chapterId}`
}

function extractDownloadFilename(contentDisposition: string | null | undefined, fallback: string): string {
  const header = String(contentDisposition || '').trim()
  if (!header) return fallback

  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const asciiMatch = header.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1]?.trim() || fallback
}

interface VoiceDefaultParams {
  pitch?: number
  speed?: number
  volume?: number
}

interface VoicePreset {
  id: string
  speaker: string
  label: string
  gender?: string
  style?: string
  category?: string
  customType?: 'clone' | 'design'
  languages?: string[]
  description?: string
  recommended?: string[]
  default_params?: VoiceDefaultParams
  supportsInstruct?: boolean
}

interface VoiceCatalogMeta {
  model?: string
  updated_at?: string
  source?: string
  voice_count?: number
}

interface ScriptReviewIssue {
  location?: string
  severity?: string
  category?: string
  description?: string
  suggestion?: string
}

interface ScriptQualityMetrics {
  naturalness_score?: number
  clarity_score?: number
  engagement_score?: number
  total_segments?: number
  average_segment_length?: number
}

interface ScriptAudioBalanceMetrics {
  sound_effects?: string
  music?: string
  voice_differentiation?: string
  total_effects?: number
  total_music_cues?: number
  effects_per_minute?: number
}

interface ScriptPacingMetrics {
  estimated_duration?: string
  pacing_issues?: string[]
  average_segment_duration?: string
  total_segments?: number
}

interface ScriptReviewDetail {
  overall_score?: number
  overall_grade?: string
  issues_count?: number
  script_quality?: ScriptQualityMetrics
  audio_balance?: ScriptAudioBalanceMetrics
  pacing?: ScriptPacingMetrics
  revision_suggestions?: string[]
  issues?: ScriptReviewIssue[]
}

interface ScriptEditorChapterRef {
  chapterId: number
  title: string
}

interface ScriptEditorStateData {
  scriptStatus: string
  scriptSegments: any[]
  scriptReview: ScriptReviewDetail | null
}

interface AudiobookEditorSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  chapterId?: number | null
  reviewMode?: boolean
  openSegmentDetailIndices?: number[]
  segmentReviews?: Record<number, { quality_score?: number; needs_regenerate?: boolean }>
  data?: ScriptEditorStateData | null
  updatedAt?: string
  writerTabId?: string
}

interface EditorConflictFieldDiffPreview {
  key: string
  label: string
  currentValue: string
  incomingValue: string
}

interface EditorConflictSegmentDiffPreview {
  index: number
  speaker: string
  changeType: 'modified' | 'added' | 'removed'
  fieldDiffs: EditorConflictFieldDiffPreview[]
}

interface EditorConflictDiffPreview {
  fieldDiffs: EditorConflictFieldDiffPreview[]
  segmentDiffs: EditorConflictSegmentDiffPreview[]
}

interface AudiobookEditorSyncRegistry {
  entries?: Record<string, AudiobookEditorSessionState>
}

interface DeleteChapterSessionTarget {
  id: number
  chapterNumber: number
  title: string
  contentPreview: string
}

interface AudiobookPageSessionState {
  projectId?: number | null
  audiobookProjectId?: number | null
  browserPlayerOpen?: boolean
  showHistory?: boolean
  scriptOnlyMode?: boolean
  narrationStyle?: NarrationStyleId
  scriptReviewDialogOpen?: boolean
  scriptReviewData?: {
    report: ScriptReviewDetail | null
    segments: any[]
  } | null
  stageMetricsDialogOpen?: boolean
  stageMetricsData?: {
    stageKey: StageKey
    info: StageInfo
  } | null
  deleteChapterDialogOpen?: boolean
  deleteChapterTarget?: DeleteChapterSessionTarget | null
  deleteChapterReason?: string
  deleteChapterFiles?: boolean
  cloneRecordDialogOpen?: boolean
  cloneName?: string
  cloneUrl?: string
  designName?: string
  designPrompt?: string
  designPreviewText?: string
  newProjectDialogOpen?: boolean
  newProjectTitle?: string
  newProjectText?: string
  updatedAt?: string
}

const DEFAULT_NARRATOR_BY_MODEL = {
  'qwen3-tts-instruct-flash': 'Neil',
  'cosyvoice-v3.5-plus': '',
  'minimax-speech-2.8-hd': 'male-qn-jingying',
  'minimax-speech-2.8-turbo': 'male-qn-jingying',
} as const

const DEFAULT_DESIGN_PREVIEW_TEXT = '欢迎收听这段声音设计试听，我们从这里开始塑造角色的独特声线。'
const DEFAULT_NARRATION_STYLE: NarrationStyleId = 'professional'

const NARRATION_STYLE_OPTIONS = [
  { id: 'professional', name: '专业播报', desc: '标准新闻播报风格，适合严肃题材', color: '#9c27b0' },
  { id: 'dramatic', name: '戏剧表演', desc: '富有表现力的戏剧化朗读，适合情感丰富的故事', color: '#f57c00' },
  { id: 'relaxing', name: '轻松舒缓', desc: '温柔舒缓的讲述方式，适合治愈系内容', color: '#4caf50' },
  { id: 'expressive', name: '生动表现', desc: '活泼生动的表达方式，适合儿童或轻喜剧', color: '#2196f3' },
] as const satisfies ReadonlyArray<{
  id: NarrationStyleId
  name: string
  desc: string
  color: string
}>

const TTS_MODEL_LABELS: Record<TtsModel, string> = {
  'qwen3-tts-instruct-flash': 'Qwen3-TTS Instruct Flash',
  'cosyvoice-v3.5-plus': 'CosyVoice v3.5-plus',
  'minimax-speech-2.8-hd': 'MiniMax HD',
  'minimax-speech-2.8-turbo': 'MiniMax Turbo',
}

const isTtsModel = (value: unknown): value is TtsModel =>
  value === 'qwen3-tts-instruct-flash'
  || value === 'cosyvoice-v3.5-plus'
  || value === 'minimax-speech-2.8-hd'
  || value === 'minimax-speech-2.8-turbo'

const isNarrationStyleId = (value: unknown): value is NarrationStyleId =>
  value === 'professional'
  || value === 'dramatic'
  || value === 'relaxing'
  || value === 'expressive'

const normalizeTtsModelValue = (value: unknown): TtsModel | null => {
  if (value === 'cosyvoice-v3-plus') {
    return 'cosyvoice-v3.5-plus'
  }
  return isTtsModel(value) ? value : null
}

const normalizeNarrationStyleValue = (value: unknown): NarrationStyleId => {
  if (value === 'relaxed') {
    return 'relaxing'
  }
  if (value === 'vivid') {
    return 'expressive'
  }
  return isNarrationStyleId(value) ? value : DEFAULT_NARRATION_STYLE
}

const hasCustomDesignPreviewText = (value: unknown): boolean => {
  if (typeof value !== 'string') {
    return false
  }
  const trimmedValue = value.trim()
  return Boolean(trimmedValue) && trimmedValue !== DEFAULT_DESIGN_PREVIEW_TEXT.trim()
}

const resolveDesignPreviewTextDraft = (value: unknown): string =>
  typeof value === 'string' && value.trim()
    ? value
    : DEFAULT_DESIGN_PREVIEW_TEXT

const getTtsModelLabel = (model: TtsModel) => TTS_MODEL_LABELS[model]

const getDefaultNarratorId = (model: TtsModel) =>
  DEFAULT_NARRATOR_BY_MODEL[model] || (model === 'cosyvoice-v3.5-plus' ? '' : 'Neil')

const getFallbackVoiceId = (
  model: TtsModel,
  presets: Array<{ id: string }> = [],
) => {
  if (model === 'cosyvoice-v3.5-plus') {
    return presets.find((preset) => Boolean(preset.id))?.id || ''
  }
  return getDefaultNarratorId(model)
}

const QWEN_FLASH_ONLY_TO_INSTRUCT: Record<string, string> = {
  Aiden: 'Ethan',
  Alek: 'Elias',
  Andre: 'Neil',
  Bodega: 'Ethan',
  Dolce: 'Vincent',
  Dylan: 'Ethan',
  Ebona: 'Bellona',
  Emilien: 'Ethan',
  Eric: 'Nofish',
  Jada: 'Mia',
  Jennifer: 'Bellona',
  Katerina: 'Vivian',
  Kiki: 'Nini',
  Lenn: 'Elias',
  Li: 'Vincent',
  Marcus: 'Vincent',
  'Ono Anna': 'Nini',
  Peter: 'Vincent',
  'Radio Gol': 'Ethan',
  Rocky: 'Kai',
  Roy: 'Vincent',
  Ryan: 'Neil',
  Sohee: 'Serena',
  Sonrisa: 'Stella',
  Sunny: 'Mia',
}

const LEGACY_VOICE_ALIASES: Record<string, string> = {
  male_young_energetic: 'Ethan',
  male_young_gentle: 'Vincent',
  male_adult_calm: 'Neil',
  male_adult_energetic: 'Ethan',
  male_elder_wise: 'Eldric Sage',
  male_warm: 'Vincent',
  male_customer_service: 'Kai',
  male_refreshing: 'Kai',
  male_monkey: 'Nofish',
  male_narrator: 'Neil',
  male_villain_sinister: 'Vincent',
  female_villain_cold: 'Bellona',
  female_villain_cunning: 'Vivian',
  female_young_gentle: 'Cherry',
  female_young_energetic: 'Bunny',
  female_young_cute: 'Momo',
  female_adult_elegant: 'Bella',
  female_adult_intellectual: 'Vivian',
  female_capable: 'Bellona',
  female_elder: 'Chelsie',
  female_intimate: 'Mochi',
  female_lively: 'Mia',
  female_child: 'Momo',
}

const normalizeVoiceId = (
  model: TtsModel,
  voiceId?: string | null,
) => {
  if (!voiceId) return ''
  if (model === 'qwen3-tts-instruct-flash') {
    const normalizedVoiceId = LEGACY_VOICE_ALIASES[voiceId] || voiceId
    return QWEN_FLASH_ONLY_TO_INSTRUCT[normalizedVoiceId] || normalizedVoiceId
  }
  const cosyvoiceV3PlusLegacyAliases: Record<string, string> = {
    longanzhi_v3: 'longanyang',
    longanyun_v3: 'longanyang',
    longyichen_v3: 'longanyang',
    longwanjun_v3: 'longanhuan',
    longanwen_v3: 'longanhuan',
  }
  const normalizedVoiceId = cosyvoiceV3PlusLegacyAliases[voiceId] || voiceId
  const legacyCosyvoiceSystemVoices = new Set(['longanyang', 'longanhuan'])
  return legacyCosyvoiceSystemVoices.has(normalizedVoiceId) ? '' : normalizedVoiceId
}

const STAGE_CONFIG = [
  { key: 'strategy', name: '策略制定', icon: '01', desc: '分析原文，制定改编策略' },
  { key: 'script_adaptation', name: '剧本改编', icon: '02', desc: '将小说改编为有声剧本' },
  { key: 'voice_design', name: '音色设计', icon: '03', desc: '为角色分配音色参数' },
  { key: 'sound_design', name: '音效设计', icon: '04', desc: '设计场景音效和环境音' },
  { key: 'music_composition', name: '音乐编曲', icon: '05', desc: '设计背景音乐方案' },
  { key: 'quality_review', name: '剧本评审', icon: '06', desc: 'TTS前质量检查' },
  { key: 'audio_prompt_review', name: '提示词审阅', icon: '07', desc: '审阅音频提示词并试听' },
  { key: 'tts_synthesis', name: 'TTS合成', icon: '08', desc: '语音合成生成音频' },
  { key: 'audio_mixing', name: '音频混合', icon: '09', desc: '混音与后期处理' },
  { key: 'final_audio_review', name: '最终评审', icon: '10', desc: '最终质量检查' },
] as const

type StageKey = typeof STAGE_CONFIG[number]['key']
type StageConfig = typeof STAGE_CONFIG[number]

const STAGE_KEYS: StageKey[] = STAGE_CONFIG.map((stage) => stage.key)
const STAGE_STATUS_LABELS: Record<StageStatus, string> = {
  pending: '等待中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
}

const createEmptyStageMap = (): Record<StageKey, StageInfo> =>
  STAGE_KEYS.reduce((acc, key) => {
    acc[key] = {
      status: 'pending',
      progress: 0,
      start_time: undefined,
      end_time: undefined,
      error_message: undefined,
      metrics: undefined,
      message: undefined,
    }
    return acc
  }, {} as Record<StageKey, StageInfo>)

const coerceStageStatus = (value: any): StageStatus => {
  if (value === 'running' || value === 'completed' || value === 'failed' || value === 'pending') {
    return value
  }
  return 'pending'
}

const normalizeStageEntry = (raw: any): StageInfo => ({
  status: coerceStageStatus(raw?.status),
  progress: typeof raw?.progress === 'number' ? raw.progress : 0,
  start_time: raw?.start_time,
  end_time: raw?.end_time,
  error_message: raw?.error ?? raw?.error_message,
  metrics: raw?.metrics,
  message: raw?.message,
})

const normalizeTaskStatusResponse = (payload: any): TaskStatus => {
  const detail = payload?.detail ?? {}
  const rawStages = (detail?.stages ?? {}) as Record<string, any>
  const normalizedStages = createEmptyStageMap()

  Object.entries(rawStages).forEach(([key, value]) => {
    const stageKey = key as StageKey
    if (STAGE_KEYS.includes(stageKey)) {
      normalizedStages[stageKey] = normalizeStageEntry(value)
    }
  })

  const currentStage = (payload?.current_stage || detail?.current_stage) as string | undefined
  if (currentStage && normalizedStages[currentStage as StageKey]) {
    const stageInfo = normalizedStages[currentStage as StageKey]
    if (stageInfo.status === 'pending' && payload?.status === 'running') {
      stageInfo.status = 'running'
    }
  }

  const taskId = payload?.celery_task_id || payload?.task_id || String(payload?.id || '')

  return {
    task_id: taskId,
    audiobook_project_id: payload?.audiobook_project_id,
    chapter_id: payload?.chapter_id ?? null,
    task_type: typeof payload?.task_type === 'string' ? payload.task_type : null,
    status: coerceStageStatus(payload?.status),
    current_stage: currentStage,
    progress: typeof payload?.progress === 'number' ? payload.progress : 0,
    stages: normalizedStages,
    created_at: payload?.created_at,
    updated_at: payload?.updated_at,
    detail,
    overall_progress: typeof detail?.overall_progress === 'number' ? detail.overall_progress : undefined,
  }
}

const isActiveAudiobookTask = (task: TaskStatus | null | undefined): task is TaskStatus =>
  Boolean(task && (task.status === 'pending' || task.status === 'running'))

const getTaskSortTimestamp = (task: Pick<TaskStatus, 'updated_at' | 'created_at'>): number => {
  const raw = task.updated_at || task.created_at
  if (!raw) return 0
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

const compareTaskByRecency = (left: TaskStatus, right: TaskStatus): number =>
  getTaskSortTimestamp(right) - getTaskSortTimestamp(left)

const dedupeSessionTaskRefs = (
  taskRefs: AudiobookSessionState['activeTasks'],
): Array<{ taskId: string; audiobookProjectId: number }> => {
  const seen = new Set<string>()
  const normalized: Array<{ taskId: string; audiobookProjectId: number }> = []

  for (const item of taskRefs || []) {
    const taskId = typeof item?.taskId === 'string' ? item.taskId.trim() : ''
    const audiobookProjectId = Number(item?.audiobookProjectId)
    if (!taskId || !Number.isFinite(audiobookProjectId) || audiobookProjectId <= 0) {
      continue
    }
    if (seen.has(taskId)) {
      continue
    }
    seen.add(taskId)
    normalized.push({
      taskId,
      audiobookProjectId,
    })
  }

  return normalized
}

const normalizeSelectedChapterIds = (
  chapterIds: unknown,
  options?: {
    allowedIds?: number[]
    fallbackIds?: number[]
  },
): number[] => {
  const allowedIdSet = Array.isArray(options?.allowedIds)
    ? new Set(
        options.allowedIds
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item) && item > 0),
      )
    : null

  const normalized = Array.isArray(chapterIds)
    ? Array.from(
        new Set(
          chapterIds
            .map((item) => Number(item))
            .filter((item) => Number.isFinite(item) && item > 0)
            .filter((item) => !allowedIdSet || allowedIdSet.has(item)),
        ),
      )
    : []

  if (normalized.length > 0) {
    return normalized
  }

  return Array.isArray(options?.fallbackIds) ? options.fallbackIds : []
}

const buildPendingTaskStatus = ({
  taskId,
  audiobookProjectId,
  taskType,
  chapterId = null,
}: {
  taskId: string
  audiobookProjectId: number
  taskType?: string | null
  chapterId?: number | null
}): TaskStatus => {
  const now = new Date().toISOString()
  return {
    task_id: taskId,
    audiobook_project_id: audiobookProjectId,
    chapter_id: chapterId,
    task_type: taskType || null,
    status: 'pending',
    current_stage: null,
    progress: 0,
    stages: createEmptyStageMap(),
    created_at: now,
    updated_at: now,
    detail: {},
    overall_progress: 0,
  }
}

const AUDIOBOOK_SESSION_STORAGE_KEY = 'audiobook_active_session_v1'
const AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY = 'audiobook_editor_session_v1'
const AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY = 'audiobook_editor_sync_v1'
const AUDIOBOOK_PAGE_SESSION_STORAGE_KEY = 'audiobook_page_session_v1'
const AUDIOBOOK_SESSION_TAB_ID_KEY = 'audiobook_session_tab_id_v1'
const AUDIOBOOK_EDITOR_SYNC_TTL_MS = 10 * 60 * 1000
const AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS = 30 * 1000
const SCRIPT_EDITOR_CONFLICT_SEGMENT_PREVIEW_LIMIT = 6
const SCRIPT_EDITOR_CONFLICT_FIELD_DETAIL_LIMIT = 3
const SCRIPT_EDITOR_CONFLICT_SEGMENT_FIELDS = [
  { key: 'text', label: '文本', maxLength: 96 },
  { key: 'performance_notes', label: '表演提示', maxLength: 72 },
  { key: 'pause_before', label: '前停顿', maxLength: 24 },
  { key: 'pause_after', label: '后停顿', maxLength: 24 },
  { key: 'instruct_emotion', label: '情绪指令', maxLength: 48 },
  { key: 'instruct_scene', label: '场景指令', maxLength: 48 },
  { key: 'instruct_role', label: '角色指令', maxLength: 48 },
  { key: 'instruct_identity', label: '身份指令', maxLength: 48 },
  { key: 'voice_params', label: '音色参数', maxLength: 72 },
  { key: 'sound_effects_simple', label: '简易音效', maxLength: 72 },
  { key: 'sound_effects', label: '详细音效', maxLength: 72 },
  { key: 'music_cue_simple', label: '简易配乐', maxLength: 56 },
  { key: 'music_cue', label: '详细配乐', maxLength: 72 },
] as const
const SCRIPT_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  generated: '已生成',
  reviewed: '已审查',
  approved: '已通过',
}

const createEphemeralSessionId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `tab_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

const getOrCreateAudiobookSessionTabId = (): string => {
  if (typeof window === 'undefined' || typeof sessionStorage === 'undefined') {
    return createEphemeralSessionId()
  }

  try {
    const existing = sessionStorage.getItem(AUDIOBOOK_SESSION_TAB_ID_KEY)
    if (existing) {
      return existing
    }

    const nextId = createEphemeralSessionId()
    sessionStorage.setItem(AUDIOBOOK_SESSION_TAB_ID_KEY, nextId)
    return nextId
  } catch {
    return createEphemeralSessionId()
  }
}

const parseSessionTimestamp = (value: unknown): number => {
  if (typeof value !== 'string' || !value.trim()) {
    return 0
  }
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const pruneAudiobookEditorSyncEntries = (
  entries: Record<string, AudiobookEditorSessionState>,
  nowMs: number = Date.now(),
): Record<string, AudiobookEditorSessionState> => {
  const nextEntries: Record<string, AudiobookEditorSessionState> = {}

  for (const [entryKey, entry] of Object.entries(entries)) {
    const updatedAtMs = parseSessionTimestamp(entry.updatedAt)
    if (updatedAtMs <= 0) {
      continue
    }
    if (nowMs - updatedAtMs > AUDIOBOOK_EDITOR_SYNC_TTL_MS) {
      continue
    }
    nextEntries[entryKey] = entry
  }

  return nextEntries
}

const normalizePositiveId = (value: unknown): number | null => {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

const normalizeSegmentDetailIndices = (value: unknown): number[] =>
  Array.isArray(value)
    ? Array.from(
        new Set(
          value
            .map((item) => Number(item))
            .filter((item) => Number.isFinite(item) && item >= 0),
        ),
      ).sort((left, right) => left - right)
    : []

const buildSegmentDetailsOpenState = (indices: number[]): Record<number, boolean> => {
  const nextState: Record<number, boolean> = {}
  for (const index of indices) {
    nextState[index] = true
  }
  return nextState
}

const extractOpenSegmentDetailIndices = (segmentDetailsOpen: Record<number, boolean>): number[] =>
  Object.entries(segmentDetailsOpen)
    .filter(([, open]) => Boolean(open))
    .map(([index]) => Number(index))
    .filter((index) => Number.isFinite(index) && index >= 0)
    .sort((left, right) => left - right)

const normalizeSegmentReviews = (
  reviews: unknown,
): Record<number, { quality_score?: number; needs_regenerate?: boolean }> => {
  if (!reviews || typeof reviews !== 'object') {
    return {}
  }

  const normalized: Record<number, { quality_score?: number; needs_regenerate?: boolean }> = {}
  for (const [rawIndex, rawReview] of Object.entries(reviews as Record<string, unknown>)) {
    const index = Number(rawIndex)
    if (!Number.isFinite(index) || index < 0 || !rawReview || typeof rawReview !== 'object') {
      continue
    }

    const review = rawReview as Record<string, unknown>
    const nextReview: { quality_score?: number; needs_regenerate?: boolean } = {}

    if (typeof review.quality_score === 'number' && !Number.isNaN(review.quality_score)) {
      nextReview.quality_score = review.quality_score
    }
    if (typeof review.needs_regenerate === 'boolean') {
      nextReview.needs_regenerate = review.needs_regenerate
    }

    if (Object.keys(nextReview).length > 0) {
      normalized[index] = nextReview
    }
  }

  return normalized
}

const buildComparableAudiobookSessionPayload = (
  session: Partial<AudiobookSessionState> | null | undefined,
) => ({
  projectId: normalizePositiveId(session?.projectId),
  audiobookProjectId: normalizePositiveId(session?.audiobookProjectId),
  taskId: typeof session?.taskId === 'string' && session.taskId.trim() ? session.taskId.trim() : null,
  activeTasks: dedupeSessionTaskRefs(session?.activeTasks),
  selectedChapterIds: normalizeSelectedChapterIds(session?.selectedChapterIds),
  activeStep: typeof session?.activeStep === 'number' ? session.activeStep : undefined,
  generating: Boolean(session?.generating),
  ttsModel: normalizeTtsModelValue(session?.ttsModel) || undefined,
})

type NavigationType = PerformanceNavigationTiming['type'] | 'navigate' | 'reload' | 'back_forward'

const detectNavigationType = (): NavigationType => {
  if (typeof window === 'undefined' || typeof performance === 'undefined') {
    return 'navigate'
  }
  try {
    if (typeof performance.getEntriesByType === 'function') {
      const entries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[]
      if (entries && entries.length > 0) {
        return entries[0].type
      }
    }
    const legacyNav = (performance as any).navigation
    if (legacyNav) {
      switch (legacyNav.type) {
        case legacyNav.TYPE_RELOAD:
          return 'reload'
        case legacyNav.TYPE_BACK_FORWARD:
          return 'back_forward'
        default:
          return 'navigate'
      }
    }
  } catch {
    // 无法检测导航类型
  }
  return 'navigate'
}

const ISSUE_DISPLAY_LIMIT = 20

const isSamePathReferrer = () => {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return false
  }
  try {
    if (!document.referrer) return false
    const refUrl = new URL(document.referrer)
    return refUrl.origin === window.location.origin && refUrl.pathname === window.location.pathname
  } catch {
    return false
  }
}

const severityColorMap: Record<string, 'default' | 'error' | 'warning' | 'info'> = {
  critical: 'error',
  major: 'warning',
  minor: 'info',
}

const severityLabelMap: Record<string, string> = {
  critical: '严重',
  major: '重要',
  minor: '提示',
}

const categoryLabelMap: Record<string, string> = {
  script: '剧本',
  audio: '音频',
  pacing: '节奏',
}

const normalizeScriptReview = (raw: any): ScriptReviewDetail | null => {
  if (!raw || typeof raw !== 'object') return null
  const safeIssues = Array.isArray(raw.issues) ? raw.issues : []
  return {
    overall_score: typeof raw.overall_score === 'number' ? raw.overall_score : undefined,
    overall_grade: raw.overall_grade,
    issues_count:
      typeof raw.issues_count === 'number'
        ? raw.issues_count
        : safeIssues.length,
    script_quality: raw.script_quality,
    audio_balance: raw.audio_balance,
    pacing: raw.pacing,
    revision_suggestions: Array.isArray(raw.revision_suggestions) ? raw.revision_suggestions : [],
    issues: safeIssues,
  }
}

const normalizeScriptEditorStateData = (raw: unknown): ScriptEditorStateData | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const data = raw as Partial<ScriptEditorStateData>
  return {
    scriptStatus:
      typeof data.scriptStatus === 'string' && data.scriptStatus.trim()
        ? data.scriptStatus
        : 'pending',
    scriptSegments: Array.isArray(data.scriptSegments) ? data.scriptSegments : [],
    scriptReview: normalizeScriptReview(data.scriptReview),
  }
}

const normalizeAudiobookEditorSessionState = (raw: unknown): AudiobookEditorSessionState | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const session = raw as AudiobookEditorSessionState
  return {
    projectId: normalizePositiveId(session.projectId),
    audiobookProjectId: normalizePositiveId(session.audiobookProjectId),
    chapterId: normalizePositiveId(session.chapterId),
    reviewMode: Boolean(session.reviewMode),
    openSegmentDetailIndices: normalizeSegmentDetailIndices(session.openSegmentDetailIndices),
    segmentReviews: normalizeSegmentReviews(session.segmentReviews),
    data: normalizeScriptEditorStateData(session.data),
    updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : undefined,
    writerTabId: typeof session.writerTabId === 'string' && session.writerTabId.trim()
      ? session.writerTabId.trim()
      : undefined,
  }
}

const normalizeAudiobookEditorSyncRegistry = (
  raw: unknown,
): Record<string, AudiobookEditorSessionState> => {
  if (!raw || typeof raw !== 'object') {
    return {}
  }

  const registry = raw as AudiobookEditorSyncRegistry
  const rawEntries = registry.entries
  if (!rawEntries || typeof rawEntries !== 'object') {
    return {}
  }

  const normalizedEntries: Record<string, AudiobookEditorSessionState> = {}
  for (const [entryKey, entryValue] of Object.entries(rawEntries)) {
    if (!entryKey.trim()) {
      continue
    }
    const normalizedEntry = normalizeAudiobookEditorSessionState(entryValue)
    if (!normalizedEntry?.writerTabId) {
      continue
    }
    normalizedEntries[entryKey] = normalizedEntry
  }

  return normalizedEntries
}

const normalizeDeleteChapterSessionTarget = (raw: unknown): DeleteChapterSessionTarget | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const target = raw as Partial<DeleteChapterSessionTarget>
  const targetId = normalizePositiveId(target.id)
  if (!targetId) {
    return null
  }

  return {
    id: targetId,
    chapterNumber:
      typeof target.chapterNumber === 'number' && Number.isFinite(target.chapterNumber)
        ? Math.max(0, Math.trunc(target.chapterNumber))
        : 0,
    title: typeof target.title === 'string' ? target.title : '',
    contentPreview: typeof target.contentPreview === 'string' ? target.contentPreview : '',
  }
}

const buildDeleteChapterSessionTarget = (
  chapter: Chapter | null | undefined,
): DeleteChapterSessionTarget | null => {
  if (!chapter?.id) {
    return null
  }

  return {
    id: chapter.id,
    chapterNumber: chapter.chapter_number,
    title: chapter.title || '',
    contentPreview: chapter.content ? chapter.content.slice(0, 100) : '',
  }
}

const normalizeAudiobookPageSessionState = (raw: unknown): AudiobookPageSessionState | null => {
  if (!raw || typeof raw !== 'object') {
    return null
  }

  const session = raw as AudiobookPageSessionState
  const normalizedDeleteChapterTarget = normalizeDeleteChapterSessionTarget(session.deleteChapterTarget)
  const normalizedScriptReviewData =
    session.scriptReviewData && typeof session.scriptReviewData === 'object'
      ? {
          report: normalizeScriptReview(session.scriptReviewData.report),
          segments: Array.isArray(session.scriptReviewData.segments)
            ? session.scriptReviewData.segments
            : [],
        }
      : null

  const rawStageMetricsData = session.stageMetricsData
  const normalizedStageMetricsData =
    rawStageMetricsData
    && typeof rawStageMetricsData === 'object'
    && typeof rawStageMetricsData.stageKey === 'string'
    && STAGE_KEYS.includes(rawStageMetricsData.stageKey as StageKey)
      ? {
          stageKey: rawStageMetricsData.stageKey as StageKey,
          info: normalizeStageEntry(rawStageMetricsData.info),
        }
      : null

  return {
    projectId: normalizePositiveId(session.projectId),
    audiobookProjectId: normalizePositiveId(session.audiobookProjectId),
    browserPlayerOpen: Boolean(session.browserPlayerOpen),
    showHistory: Boolean(session.showHistory),
    scriptOnlyMode: Boolean(session.scriptOnlyMode),
    narrationStyle: normalizeNarrationStyleValue(session.narrationStyle),
    scriptReviewDialogOpen: Boolean(session.scriptReviewDialogOpen),
    scriptReviewData: normalizedScriptReviewData,
    stageMetricsDialogOpen: Boolean(session.stageMetricsDialogOpen),
    stageMetricsData: normalizedStageMetricsData,
    deleteChapterDialogOpen: Boolean(session.deleteChapterDialogOpen),
    deleteChapterTarget: normalizedDeleteChapterTarget,
    deleteChapterReason: typeof session.deleteChapterReason === 'string' ? session.deleteChapterReason : '',
    deleteChapterFiles: Boolean(session.deleteChapterFiles),
    cloneRecordDialogOpen: Boolean(session.cloneRecordDialogOpen),
    cloneName: typeof session.cloneName === 'string' ? session.cloneName : '',
    cloneUrl: typeof session.cloneUrl === 'string' ? session.cloneUrl : '',
    designName: typeof session.designName === 'string' ? session.designName : '',
    designPrompt: typeof session.designPrompt === 'string' ? session.designPrompt : '',
    designPreviewText: typeof session.designPreviewText === 'string' ? session.designPreviewText : '',
    newProjectDialogOpen: Boolean(session.newProjectDialogOpen),
    newProjectTitle: typeof session.newProjectTitle === 'string' ? session.newProjectTitle : '',
    newProjectText: typeof session.newProjectText === 'string' ? session.newProjectText : '',
    updatedAt: typeof session.updatedAt === 'string' ? session.updatedAt : undefined,
  }
}

const buildComparableAudiobookEditorSessionPayload = (
  session: Partial<AudiobookEditorSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookEditorSessionState(session)

  return {
    projectId: normalizedSession?.projectId ?? null,
    audiobookProjectId: normalizedSession?.audiobookProjectId ?? null,
    chapterId: normalizedSession?.chapterId ?? null,
    reviewMode: normalizedSession?.reviewMode ?? false,
    openSegmentDetailIndices: normalizedSession?.openSegmentDetailIndices ?? [],
    segmentReviews: normalizedSession?.segmentReviews ?? {},
    data: normalizedSession?.data ?? null,
  }
}

const buildAudiobookEditorConflictSignature = (
  session: Partial<AudiobookEditorSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookEditorSessionState(session)
  if (!normalizedSession?.writerTabId) {
    return null
  }
  return `${normalizedSession.writerTabId}:${normalizedSession.updatedAt || ''}`
}

const normalizeEditorDiffComparableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeEditorDiffComparableValue(item))
  }

  if (value && typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>)
      .sort((left, right) => left.localeCompare(right))
      .reduce<Record<string, unknown>>((acc, key) => {
        const normalizedValue = normalizeEditorDiffComparableValue(
          (value as Record<string, unknown>)[key],
        )
        if (typeof normalizedValue !== 'undefined') {
          acc[key] = normalizedValue
        }
        return acc
      }, {})
  }

  if (typeof value === 'undefined') {
    return null
  }

  return value
}

const isDiffValueEqual = (left: unknown, right: unknown): boolean =>
  JSON.stringify(normalizeEditorDiffComparableValue(left))
  === JSON.stringify(normalizeEditorDiffComparableValue(right))

const hasMeaningfulDiffValue = (value: unknown): boolean => {
  if (value === null || typeof value === 'undefined') {
    return false
  }

  if (typeof value === 'string') {
    return value.trim().length > 0
  }

  if (Array.isArray(value)) {
    return value.length > 0
  }

  if (typeof value === 'object') {
    return Object.keys(value as Record<string, unknown>).length > 0
  }

  return true
}

const formatDiffPreviewText = (value: unknown, maxLength: number = 72): string => {
  if (value === null || typeof value === 'undefined') {
    return '—'
  }

  let text = ''
  if (typeof value === 'string') {
    text = value
  } else if (typeof value === 'number' || typeof value === 'boolean') {
    text = String(value)
  } else {
    try {
      text = JSON.stringify(value)
    } catch {
      text = String(value)
    }
  }

  const normalizedText = text.replace(/\s+/g, ' ').trim()
  if (!normalizedText) {
    return '—'
  }

  return normalizedText.length > maxLength
    ? `${normalizedText.slice(0, maxLength).trimEnd()}...`
    : normalizedText
}

const buildEditorConflictFieldDiffPreview = ({
  key,
  label,
  currentValue,
  incomingValue,
  maxLength = 72,
}: {
  key: string
  label: string
  currentValue: unknown
  incomingValue: unknown
  maxLength?: number
}): EditorConflictFieldDiffPreview => ({
  key,
  label,
  currentValue: formatDiffPreviewText(currentValue, maxLength),
  incomingValue: formatDiffPreviewText(incomingValue, maxLength),
})

const formatScriptStatusPreviewText = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) {
    return '—'
  }

  return SCRIPT_STATUS_LABELS[value.trim()] || value.trim()
}

const formatReviewModePreviewText = (value: unknown): string =>
  value ? '审查模式' : '普通编辑'

const formatOpenSegmentDetailIndicesSummary = (value: unknown): string => {
  const indices = normalizeSegmentDetailIndices(value)
  if (indices.length === 0) {
    return '无展开详情'
  }

  const preview = indices.slice(0, 4).map((index) => `#${index + 1}`).join('、')
  return indices.length > 4
    ? `${preview} 等 ${indices.length} 个片段已展开`
    : `${preview} 已展开`
}

const formatSegmentReviewSummary = (
  reviews: unknown,
): string => {
  const normalizedReviews = normalizeSegmentReviews(reviews)
  const entries = Object.entries(normalizedReviews)
    .map(([rawIndex, review]) => ({
      index: Number(rawIndex),
      review,
    }))
    .sort((left, right) => left.index - right.index)

  if (entries.length === 0) {
    return '无审查结果'
  }

  const ratedCount = entries.filter(({ review }) => typeof review.quality_score === 'number').length
  const regenerateCount = entries.filter(({ review }) => review.needs_regenerate).length
  const previewIndices = entries.slice(0, 4).map(({ index }) => `#${index + 1}`).join('、')

  return entries.length > 4
    ? `评分 ${ratedCount} 条，待重生成 ${regenerateCount} 条，涉及 ${previewIndices} 等 ${entries.length} 个片段`
    : `评分 ${ratedCount} 条，待重生成 ${regenerateCount} 条，涉及 ${previewIndices}`
}

const resolveScriptSegmentSpeaker = (segment: any): string => {
  const speaker =
    segment?.speaker
    || segment?.speaker_name
    || segment?.character_name
    || segment?.role_name

  return typeof speaker === 'string' && speaker.trim() ? speaker.trim() : '旁白'
}

const buildAudiobookEditorConflictPreview = (
  localSession: Partial<AudiobookEditorSessionState> | null | undefined,
  incomingSession: Partial<AudiobookEditorSessionState> | null | undefined,
): EditorConflictDiffPreview | null => {
  const normalizedLocalSession = normalizeAudiobookEditorSessionState(localSession)
  const normalizedIncomingSession = normalizeAudiobookEditorSessionState(incomingSession)

  if (!normalizedLocalSession?.data || !normalizedIncomingSession?.data) {
    return null
  }

  const fieldDiffs: EditorConflictFieldDiffPreview[] = []
  if (!isDiffValueEqual(normalizedLocalSession.data.scriptStatus, normalizedIncomingSession.data.scriptStatus)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'scriptStatus',
        label: '剧本状态',
        currentValue: formatScriptStatusPreviewText(normalizedLocalSession.data.scriptStatus),
        incomingValue: formatScriptStatusPreviewText(normalizedIncomingSession.data.scriptStatus),
        maxLength: 32,
      }),
    )
  }
  if (!isDiffValueEqual(normalizedLocalSession.reviewMode, normalizedIncomingSession.reviewMode)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'reviewMode',
        label: '编辑模式',
        currentValue: formatReviewModePreviewText(normalizedLocalSession.reviewMode),
        incomingValue: formatReviewModePreviewText(normalizedIncomingSession.reviewMode),
        maxLength: 24,
      }),
    )
  }
  if (
    !isDiffValueEqual(
      normalizedLocalSession.openSegmentDetailIndices,
      normalizedIncomingSession.openSegmentDetailIndices,
    )
  ) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'openSegmentDetailIndices',
        label: '详情展开',
        currentValue: formatOpenSegmentDetailIndicesSummary(normalizedLocalSession.openSegmentDetailIndices),
        incomingValue: formatOpenSegmentDetailIndicesSummary(normalizedIncomingSession.openSegmentDetailIndices),
        maxLength: 56,
      }),
    )
  }
  if (!isDiffValueEqual(normalizedLocalSession.segmentReviews, normalizedIncomingSession.segmentReviews)) {
    fieldDiffs.push(
      buildEditorConflictFieldDiffPreview({
        key: 'segmentReviews',
        label: '片段审查',
        currentValue: formatSegmentReviewSummary(normalizedLocalSession.segmentReviews),
        incomingValue: formatSegmentReviewSummary(normalizedIncomingSession.segmentReviews),
        maxLength: 80,
      }),
    )
  }

  const localSegments = Array.isArray(normalizedLocalSession.data.scriptSegments)
    ? normalizedLocalSession.data.scriptSegments
    : []
  const incomingSegments = Array.isArray(normalizedIncomingSession.data.scriptSegments)
    ? normalizedIncomingSession.data.scriptSegments
    : []

  const segmentDiffs: EditorConflictSegmentDiffPreview[] = []
  const totalSegments = Math.max(localSegments.length, incomingSegments.length)

  for (let index = 0; index < totalSegments; index += 1) {
    const localSegment = localSegments[index]
    const incomingSegment = incomingSegments[index]

    if (!localSegment && !incomingSegment) {
      continue
    }

    const changeType: EditorConflictSegmentDiffPreview['changeType'] =
      !localSegment
        ? 'added'
        : !incomingSegment
          ? 'removed'
          : 'modified'

    const segmentFieldDiffs = SCRIPT_EDITOR_CONFLICT_SEGMENT_FIELDS.reduce<EditorConflictFieldDiffPreview[]>(
      (acc, field) => {
        const currentValue = localSegment?.[field.key]
        const nextValue = incomingSegment?.[field.key]

        if (changeType === 'modified' && isDiffValueEqual(currentValue, nextValue)) {
          return acc
        }

        if (changeType === 'added' && !hasMeaningfulDiffValue(nextValue)) {
          return acc
        }

        if (changeType === 'removed' && !hasMeaningfulDiffValue(currentValue)) {
          return acc
        }

        acc.push(
          buildEditorConflictFieldDiffPreview({
            key: field.key,
            label: field.label,
            currentValue,
            incomingValue: nextValue,
            maxLength: field.maxLength,
          }),
        )
        return acc
      },
      [],
    )

    if (segmentFieldDiffs.length === 0) {
      if (changeType === 'modified') {
        continue
      }

      segmentFieldDiffs.push(
        buildEditorConflictFieldDiffPreview({
          key: 'segment_presence',
          label: '片段存在状态',
          currentValue: localSegment ? '本页存在' : '本页缺失',
          incomingValue: incomingSegment ? '对方存在' : '对方缺失',
          maxLength: 24,
        }),
      )
    }

    segmentDiffs.push({
      index,
      speaker: resolveScriptSegmentSpeaker(incomingSegment || localSegment),
      changeType,
      fieldDiffs: segmentFieldDiffs,
    })
  }

  if (fieldDiffs.length === 0 && segmentDiffs.length === 0) {
    return null
  }

  return {
    fieldDiffs,
    segmentDiffs,
  }
}

const buildComparableAudiobookPageSessionPayload = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  const normalizedDeleteChapterTarget = normalizedSession?.deleteChapterTarget ?? null
  const hasDeleteChapterDialogState = Boolean(
    normalizedSession?.deleteChapterDialogOpen && normalizedDeleteChapterTarget,
  )
  const hasVoiceWorkbenchDraftState = Boolean(
    normalizedSession?.cloneRecordDialogOpen
      || normalizedSession?.cloneName
      || normalizedSession?.cloneUrl
      || normalizedSession?.designName
      || normalizedSession?.designPrompt
      || hasCustomDesignPreviewText(normalizedSession?.designPreviewText),
  )

  return {
    projectId: normalizedSession?.projectId ?? null,
    audiobookProjectId: normalizedSession?.audiobookProjectId ?? null,
    browserPlayerOpen: normalizedSession?.browserPlayerOpen ?? false,
    showHistory: normalizedSession?.showHistory ?? false,
    scriptOnlyMode: normalizedSession?.scriptOnlyMode ?? false,
    narrationStyle: normalizedSession?.narrationStyle ?? DEFAULT_NARRATION_STYLE,
    scriptReviewDialogOpen:
      Boolean(normalizedSession?.scriptReviewDialogOpen && normalizedSession?.scriptReviewData),
    scriptReviewData:
      normalizedSession?.scriptReviewDialogOpen && normalizedSession?.scriptReviewData
        ? normalizedSession.scriptReviewData
        : null,
    stageMetricsDialogOpen:
      Boolean(normalizedSession?.stageMetricsDialogOpen && normalizedSession?.stageMetricsData),
    stageMetricsData:
      normalizedSession?.stageMetricsDialogOpen && normalizedSession?.stageMetricsData
        ? normalizedSession.stageMetricsData
        : null,
    deleteChapterDialogOpen: hasDeleteChapterDialogState,
    deleteChapterTarget: hasDeleteChapterDialogState ? normalizedDeleteChapterTarget : null,
    deleteChapterReason: hasDeleteChapterDialogState ? normalizedSession?.deleteChapterReason ?? '' : '',
    deleteChapterFiles: Boolean(hasDeleteChapterDialogState && normalizedSession?.deleteChapterFiles),
    cloneRecordDialogOpen: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneRecordDialogOpen ?? false : false,
    cloneName: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneName ?? '' : '',
    cloneUrl: hasVoiceWorkbenchDraftState ? normalizedSession?.cloneUrl ?? '' : '',
    designName: hasVoiceWorkbenchDraftState ? normalizedSession?.designName ?? '' : '',
    designPrompt: hasVoiceWorkbenchDraftState ? normalizedSession?.designPrompt ?? '' : '',
    designPreviewText: hasVoiceWorkbenchDraftState
      ? resolveDesignPreviewTextDraft(normalizedSession?.designPreviewText)
      : '',
    newProjectDialogOpen: normalizedSession?.newProjectDialogOpen ?? false,
    newProjectTitle: normalizedSession?.newProjectTitle ?? '',
    newProjectText: normalizedSession?.newProjectText ?? '',
  }
}

const hasPersistableAudiobookPageSession = (
  session: Partial<AudiobookPageSessionState> | null | undefined,
) => {
  const normalizedSession = normalizeAudiobookPageSessionState(session)
  if (!normalizedSession) {
    return false
  }

  return Boolean(
    normalizedSession.browserPlayerOpen
      || normalizedSession.showHistory
      || normalizedSession.scriptOnlyMode
      || normalizedSession.narrationStyle !== DEFAULT_NARRATION_STYLE
      || (normalizedSession.scriptReviewDialogOpen && normalizedSession.scriptReviewData)
      || (normalizedSession.stageMetricsDialogOpen && normalizedSession.stageMetricsData)
      || (normalizedSession.deleteChapterDialogOpen && normalizedSession.deleteChapterTarget)
      || normalizedSession.cloneRecordDialogOpen
      || normalizedSession.cloneName
      || normalizedSession.cloneUrl
      || normalizedSession.designName
      || normalizedSession.designPrompt
      || hasCustomDesignPreviewText(normalizedSession.designPreviewText)
      || normalizedSession.newProjectDialogOpen
      || normalizedSession.newProjectTitle
      || normalizedSession.newProjectText,
  )
}

const formatTenScale = (value?: number) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(1)
}

const formatOneDecimal = (value?: number) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(1)
}

const ScriptReviewReport = ({ review }: { review: ScriptReviewDetail | null }) => {
  if (!review) return null
  const scriptQuality = review.script_quality || {}
  const audioBalance = review.audio_balance || {}
  const pacing = review.pacing || {}
  const issues = review.issues || []
  const suggestions = review.revision_suggestions || []
  const extraIssues =
    (review.issues_count || issues.length || 0) > ISSUE_DISPLAY_LIMIT
      ? (review.issues_count || issues.length || 0) - ISSUE_DISPLAY_LIMIT
      : 0

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
          总体评分
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 70,
              height: 70,
              borderRadius: '50%',
              backgroundColor:
                (review.overall_score || 0) >= 8
                  ? 'rgba(76, 175, 80, 0.15)'
                  : (review.overall_score || 0) >= 6
                  ? 'rgba(255, 152, 0, 0.15)'
                  : 'rgba(244, 67, 54, 0.15)',
            }}
          >
            <Typography
              variant="h5"
              sx={{
                fontWeight: 600,
                color:
                  (review.overall_score || 0) >= 8
                    ? '#2e7d32'
                    : (review.overall_score || 0) >= 6
                    ? '#f57c00'
                    : '#c62828',
              }}
            >
              {typeof review.overall_score === 'number'
                ? review.overall_score.toFixed(1)
                : '—'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>
              等级：{review.overall_grade || 'N/A'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              问题数：{review.issues_count ?? issues.length ?? 0}
            </Typography>
          </Box>
        </Box>
        {suggestions.length > 0 && (
          <Alert severity="info" sx={{ mb: 1 }}>
            {suggestions[0]}
            {suggestions.length > 1 && (
              <Typography variant="caption" component="div">
                其余建议在下方详列
              </Typography>
            )}
          </Alert>
        )}
      </Box>

      <Divider textAlign="left">剧本质量</Divider>
      <Grid container spacing={1}>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            自然流畅度
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.naturalness_score)}/10</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            信息清晰度
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.clarity_score)}/10</Typography>
        </Grid>
        <Grid item xs={4}>
          <Typography variant="caption" color="text.secondary">
            听觉张力
          </Typography>
          <Typography variant="subtitle2">{formatTenScale(scriptQuality.engagement_score)}/10</Typography>
        </Grid>
      </Grid>
      <Typography variant="caption" color="text.secondary">
        片段数：{scriptQuality.total_segments ?? '—'} · 平均片段长度：
        {typeof scriptQuality.average_segment_length === 'number'
          ? `${formatOneDecimal(scriptQuality.average_segment_length)} 字`
          : '—'}
      </Typography>

      <Divider textAlign="left">音频平衡</Divider>
      <List dense>
        <ListItem disableGutters>
          <ListItemText
            primary="音效密度"
            secondary={
              audioBalance.sound_effects
                ? `${audioBalance.sound_effects}（≈ ${formatOneDecimal(audioBalance.effects_per_minute)} / 分钟）`
                : '—'
            }
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="配乐覆盖"
            secondary={
              audioBalance.music
                ? `${audioBalance.music}（共 ${audioBalance.total_music_cues ?? 0} 个提示）`
                : '—'
            }
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="角色音色区分"
            secondary={audioBalance.voice_differentiation || '—'}
          />
        </ListItem>
      </List>

      <Divider textAlign="left">节奏评估</Divider>
      <List dense>
        <ListItem disableGutters>
          <ListItemText
            primary="预计成品时长"
            secondary={pacing.estimated_duration || '—'}
          />
        </ListItem>
        <ListItem disableGutters>
          <ListItemText
            primary="平均片段朗读时长"
            secondary={pacing.average_segment_duration || '—'}
          />
        </ListItem>
        {pacing.pacing_issues?.length ? (
          pacing.pacing_issues.map((issue, idx) => (
            <ListItem key={idx} disableGutters>
              <ListItemText
                primaryTypographyProps={{ variant: 'body2' }}
                primary={`节奏提示 ${idx + 1}`}
                secondary={issue}
              />
            </ListItem>
          ))
        ) : (
          <ListItem disableGutters>
            <ListItemText secondary="节奏稳定，未发现明显问题" />
          </ListItem>
        )}
      </List>

      <Divider textAlign="left">问题清单</Divider>
      {issues.length > 0 ? (
        <List dense>
          {issues.slice(0, ISSUE_DISPLAY_LIMIT).map((issue, idx) => {
            const severityKey = (issue.severity || '').toLowerCase()
            const color = severityColorMap[severityKey] || 'default'
            const categoryLabel = categoryLabelMap[(issue.category || '').toLowerCase()] || issue.category || '其他'
            const severityLabel = severityLabelMap[severityKey] || issue.severity || '未分级'
            return (
              <ListItem key={`${issue.location || idx}-${idx}`} alignItems="flex-start" sx={{ mb: 1 }}>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Chip label={severityLabel} size="small" color={color} />
                      <Chip label={categoryLabel} size="small" variant="outlined" />
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {issue.description || '未提供描述'}
                      </Typography>
                    </Box>
                  }
                  secondary={
                    issue.suggestion ? (
                      <Typography variant="body2" color="text.secondary">
                        建议：{issue.suggestion}
                      </Typography>
                    ) : undefined
                  }
                />
              </ListItem>
            )
          })}
        </List>
      ) : (
        <Typography variant="body2" color="text.secondary">
          未找到具体问题，整体表现稳定。
        </Typography>
      )}
      {extraIssues > 0 && (
        <Typography variant="caption" color="text.secondary">
          另有 {extraIssues} 条问题记录，可在导出报告或后台数据库中查看全部明细。
        </Typography>
      )}

      {suggestions.length > 1 && (
        <>
          <Divider textAlign="left">修订建议</Divider>
          <List dense>
            {suggestions.map((s, idx) => (
              <ListItem key={idx} disableGutters>
                <ListItemText primary={`建议 ${idx + 1}`} secondary={s} />
              </ListItem>
            ))}
          </List>
        </>
      )}
    </Box>
  )
}


function ScriptEditorDialog({
  open,
  loading,
  chapter,
  data,
  onClose,
  onChangeSegmentText,
  onSaveScript,
  onPreviewSegmentAudio,
  onRegenerateSegment,
  onReviewSegment,
  segmentReviews,
  segmentPreviewingIndex,
  segmentPreviewingType,
  segmentAudioUrls,
  segmentDetailsOpen,
  onToggleSegmentDetails,
  onUpdateSegment,
  reviewMode,
  onToggleReviewMode,
  regeneratingSegments,
  editorConflict,
  onApplyIncomingDraft,
  onKeepLocalDraft,
}: ScriptEditorDialogProps) {
  const parseFloatValue = (value: string) => {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }

  const parseCommaList = (value: string) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)

  const editorConflictTimeLabel =
    editorConflict?.updatedAt
      ? new Date(editorConflict.updatedAt).toLocaleString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      : null

  const editorConflictPreview = useMemo(
    () => buildAudiobookEditorConflictPreview(
      {
        chapterId: chapter?.chapterId,
        reviewMode,
        openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
        segmentReviews,
        data,
      },
      editorConflict,
    ),
    [chapter?.chapterId, data, editorConflict, reviewMode, segmentDetailsOpen, segmentReviews],
  )

  const visibleEditorConflictSegmentDiffs = editorConflictPreview?.segmentDiffs.slice(
    0,
    SCRIPT_EDITOR_CONFLICT_SEGMENT_PREVIEW_LIMIT,
  ) || []
  const hiddenEditorConflictSegmentDiffCount = Math.max(
    0,
    (editorConflictPreview?.segmentDiffs.length || 0) - visibleEditorConflictSegmentDiffs.length,
  )

  const updateVoiceParams = (index: number, patch: Record<string, any>) => {
    if (!data) return
    const current = data.scriptSegments[index]
    const currentParams = current?.voice_params && typeof current.voice_params === 'object'
      ? current.voice_params
      : {}
    onUpdateSegment(index, { voice_params: { ...currentParams, ...patch } })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        {chapter ? `编辑剧本与音频提示词 - ${chapter.title}` : '编辑章节剧本与音频提示词'}
      </DialogTitle>
      <DialogContent dividers sx={{ minHeight: 400 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : !data ? (
          <Typography variant="body2" color="text.secondary">
            暂无剧本数据，请先生成剧本。
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {editorConflict && (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                <Alert
                  severity="warning"
                  action={(
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Button size="small" color="inherit" onClick={onApplyIncomingDraft}>
                        载入对方草稿
                      </Button>
                      <Button size="small" color="inherit" onClick={onKeepLocalDraft}>
                        保留本页草稿
                      </Button>
                    </Box>
                  )}
                >
                  检测到另一个标签页刚刚更新了同一章节的未保存草稿
                  {editorConflictTimeLabel ? `（${editorConflictTimeLabel}）` : ''}。
                  你可以先查看字段级差异，再决定载入对方草稿，或继续保留当前标签页的内容。
                </Alert>
                {editorConflictPreview && (
                  <Paper
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      borderColor: 'warning.light',
                      backgroundColor: 'rgba(255, 248, 225, 0.6)',
                    }}
                  >
                    <Box
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: 1,
                        flexWrap: 'wrap',
                        mb: 1,
                      }}
                    >
                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                        字段级差异预览
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        顶层 {editorConflictPreview.fieldDiffs.length} 项 · 片段 {editorConflictPreview.segmentDiffs.length} 个
                      </Typography>
                    </Box>

                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                        <Typography variant="caption" color="text.secondary">
                          顶层状态
                        </Typography>
                        {editorConflictPreview.fieldDiffs.length > 0 ? (
                          editorConflictPreview.fieldDiffs.map((fieldDiff) => (
                            <Box
                              key={fieldDiff.key}
                              sx={{
                                p: 1,
                                borderRadius: 1,
                                backgroundColor: 'rgba(255,255,255,0.75)',
                                border: '1px solid rgba(0,0,0,0.08)',
                              }}
                            >
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {fieldDiff.label}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" component="div">
                                当前：{fieldDiff.currentValue}
                              </Typography>
                              <Typography variant="caption" color="text.secondary" component="div">
                                对方：{fieldDiff.incomingValue}
                              </Typography>
                            </Box>
                          ))
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            顶层字段无差异，当前冲突主要集中在片段内容。
                          </Typography>
                        )}
                      </Box>

                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                        <Typography variant="caption" color="text.secondary">
                          片段差异
                        </Typography>
                        {visibleEditorConflictSegmentDiffs.length > 0 ? (
                          visibleEditorConflictSegmentDiffs.map((segmentDiff) => {
                            const visibleFieldDiffs = segmentDiff.fieldDiffs.slice(
                              0,
                              SCRIPT_EDITOR_CONFLICT_FIELD_DETAIL_LIMIT,
                            )
                            const hiddenFieldDiffCount = Math.max(
                              0,
                              segmentDiff.fieldDiffs.length - visibleFieldDiffs.length,
                            )

                            return (
                              <Box
                                key={`${segmentDiff.index}-${segmentDiff.changeType}`}
                                sx={{
                                  p: 1,
                                  borderRadius: 1,
                                  backgroundColor: 'rgba(255,255,255,0.75)',
                                  border: '1px dashed rgba(0,0,0,0.18)',
                                }}
                              >
                                <Box
                                  sx={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 0.75,
                                    flexWrap: 'wrap',
                                    mb: 0.75,
                                  }}
                                >
                                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                    片段 #{segmentDiff.index + 1} · {segmentDiff.speaker}
                                  </Typography>
                                  <Chip
                                    size="small"
                                    variant="outlined"
                                    color={
                                      segmentDiff.changeType === 'added'
                                        ? 'success'
                                        : segmentDiff.changeType === 'removed'
                                          ? 'info'
                                          : 'warning'
                                    }
                                    label={
                                      segmentDiff.changeType === 'added'
                                        ? '对方新增'
                                        : segmentDiff.changeType === 'removed'
                                          ? '对方已删除'
                                          : '字段变更'
                                    }
                                  />
                                  {segmentDiff.fieldDiffs.slice(0, 4).map((fieldDiff) => (
                                    <Chip
                                      key={`${segmentDiff.index}-${fieldDiff.key}`}
                                      size="small"
                                      label={fieldDiff.label}
                                      variant="outlined"
                                    />
                                  ))}
                                  {segmentDiff.fieldDiffs.length > 4 && (
                                    <Typography variant="caption" color="text.secondary">
                                      等 {segmentDiff.fieldDiffs.length} 项
                                    </Typography>
                                  )}
                                </Box>

                                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                                  {visibleFieldDiffs.map((fieldDiff) => (
                                    <Box key={`${segmentDiff.index}-${fieldDiff.key}-detail`}>
                                      <Typography variant="caption" sx={{ fontWeight: 600 }}>
                                        {fieldDiff.label}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary" component="div">
                                        当前：{fieldDiff.currentValue}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary" component="div">
                                        对方：{fieldDiff.incomingValue}
                                      </Typography>
                                    </Box>
                                  ))}
                                  {hiddenFieldDiffCount > 0 && (
                                    <Typography variant="caption" color="text.secondary">
                                      其余 {hiddenFieldDiffCount} 个字段差异已折叠。
                                    </Typography>
                                  )}
                                </Box>
                              </Box>
                            )
                          })
                        ) : (
                          <Typography variant="body2" color="text.secondary">
                            片段内容无差异，当前冲突主要集中在顶层状态。
                          </Typography>
                        )}
                        {hiddenEditorConflictSegmentDiffCount > 0 && (
                          <Typography variant="caption" color="text.secondary">
                            其余 {hiddenEditorConflictSegmentDiffCount} 个片段差异已折叠，避免在确认前把弹窗拉得过长。
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  </Paper>
                )}
              </Box>
            )}
            <Box sx={{ display: 'flex', gap: 2 }}>
            {/* 左侧：剧本可编辑列表 */}
            <Box sx={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                剧本片段（支持文本与音频提示词调整）
              </Typography>
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1, gap: 1, alignItems: 'center' }}>
                {reviewMode && (
                  <Box sx={{ flex: 1, mr: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        审查进度
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {Object.keys(segmentReviews).length} / {data?.scriptSegments?.length || 0}
                      </Typography>
                    </Box>
                    <LinearProgress 
                      variant="determinate" 
                      value={data?.scriptSegments?.length ? (Object.keys(segmentReviews).length / data.scriptSegments.length) * 100 : 0} 
                      sx={{ height: 6, borderRadius: 1 }}
                    />
                  </Box>
                )}
                <Button
                  size="small"
                  variant={reviewMode ? 'contained' : 'outlined'}
                  color={reviewMode ? 'primary' : 'inherit'}
                  onClick={onToggleReviewMode}
                  startIcon={
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                    </svg>
                  }
                >
                  {reviewMode ? '退出审查模式' : '进入审查模式'}
                </Button>
              </Box>
              <Paper
                variant="outlined"
                sx={{ maxHeight: 520, overflow: 'auto', p: 1 }}
              >
                <List dense>
                  {data.scriptSegments.map((seg: any, idx: number) => {
                    const hasSoundEffects =
                      (Array.isArray(seg.sound_effects) && seg.sound_effects.length > 0) ||
                      (Array.isArray(seg.sound_effects_simple) && seg.sound_effects_simple.length > 0)
                    const hasMusicCue = Boolean(seg.music_cue) || Boolean(seg.music_cue_simple)
                    const isBusy = segmentPreviewingIndex === idx
                    const isPreviewing = (type: PreviewType) =>
                      isBusy && segmentPreviewingType === type
                    const voiceParams =
                      seg.voice_params && typeof seg.voice_params === 'object' ? seg.voice_params : {}
                    const soundEffectsSimple = Array.isArray(seg.sound_effects_simple)
                      ? seg.sound_effects_simple
                      : []
                    const soundEffectsFromDetail = Array.isArray(seg.sound_effects)
                      ? seg.sound_effects
                          .map((item: any) => item?.name || item?.effect_id || item?.id || item)
                          .filter((item: any) => typeof item === 'string' && item.length > 0)
                      : []
                    const soundEffectsValue =
                      soundEffectsSimple.length > 0
                        ? soundEffectsSimple.join(',')
                        : soundEffectsFromDetail.join(',')
                    const musicCueValue =
                      seg.music_cue_simple ||
                      (seg.music_cue && (seg.music_cue.style || seg.music_cue.name)) ||
                      ''

                    return (
                      <ListItem key={idx} alignItems="flex-start" sx={{ mb: 1 }}>
                        <Box sx={{ width: '100%' }}>
                          <Typography variant="caption" color="text.secondary">
                            #{idx + 1} [{seg.type === 'dialogue' ? '对白' : seg.type}] {seg.speaker || '旁白'}{' '}
                            {seg.emotion ? `· 情绪: ${seg.emotion}` : ''}
                          </Typography>
                          <TextField
                            fullWidth
                            multiline
                            minRows={2}
                            margin="dense"
                            value={seg.text || ''}
                            onChange={(e) => onChangeSegmentText(idx, e.target.value)}
                          />
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                            <Button
                              size="small"
                              variant="text"
                              onClick={() => onToggleSegmentDetails(idx)}
                            >
                              {segmentDetailsOpen[idx] ? '收起详情' : '查看详情'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'voice')}
                              disabled={isBusy || !seg.text?.trim()}
                              startIcon={isPreviewing('voice') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('voice') ? '生成中...' : '人声试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'sfx')}
                              disabled={isBusy || !seg.text?.trim() || !hasSoundEffects}
                              startIcon={isPreviewing('sfx') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('sfx') ? '生成中...' : '音效试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'bgm')}
                              disabled={isBusy || !seg.text?.trim() || !hasMusicCue}
                              startIcon={isPreviewing('bgm') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('bgm') ? '生成中...' : '配乐试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="contained"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'mix')}
                              disabled={isBusy || !seg.text?.trim()}
                              startIcon={isPreviewing('mix') ? <CircularProgress size={14} /> : undefined}
                              sx={{
                                backgroundColor: '#9c27b0',
                                '&:hover': { backgroundColor: '#7b1fa2' },
                              }}
                            >
                              {isPreviewing('mix') ? '生成中...' : '融合试听'}
                            </Button>
                            {reviewMode && (
                              <>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
                                  <Typography variant="caption" color="text.secondary">评分：</Typography>
                                  <Rating
                                    size="small"
                                    value={segmentReviews[idx]?.quality_score || 0}
                                    onChange={(_, newValue) => {
                                      if (newValue) onReviewSegment(idx, newValue)
                                    }}
                                  />
                                </Box>
                                <Button
                                  size="small"
                                  variant="outlined"
                                  color="warning"
                                  onClick={() => onRegenerateSegment(idx, seg)}
                                  disabled={regeneratingSegments.has(idx) || !seg.text?.trim()}
                                  startIcon={regeneratingSegments.has(idx) ? <CircularProgress size={14} /> : undefined}
                                >
                                  {regeneratingSegments.has(idx) ? '重新生成中...' : '重新生成'}
                                </Button>
                              </>
                            )}
                          </Box>
                          {segmentDetailsOpen[idx] && (
                            <Paper
                              variant="outlined"
                              sx={{
                                mt: 1,
                                p: 1,
                                backgroundColor: 'rgba(0,0,0,0.02)',
                                borderStyle: 'dashed',
                              }}
                            >
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                                详细信息
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                表演提示：{seg.performance_notes || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                原文：{seg.original_text || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                改编原因：{seg.adaptation_reason || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                停顿：前 {seg.pause_before ?? '—'}s / 后 {seg.pause_after ?? '—'}s
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                Instruct：{seg.instruct_emotion || '—'} / {seg.instruct_scene || '—'} / {seg.instruct_role || '—'} / {seg.instruct_identity || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                音色参数：{seg.voice_params ? JSON.stringify(seg.voice_params) : '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                音效：{seg.sound_effects ? JSON.stringify(seg.sound_effects) : (seg.sound_effects_simple ? JSON.stringify(seg.sound_effects_simple) : '—')}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                配乐：{seg.music_cue ? JSON.stringify(seg.music_cue) : (seg.music_cue_simple || '—')}
                              </Typography>
                              <Divider sx={{ my: 1 }} />
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                                音频提示词（可编辑）
                              </Typography>
                              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 1 }}>
                                <TextField
                                  size="small"
                                  label="停顿-前(s)"
                                  type="number"
                                  value={seg.pause_before ?? ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { pause_before: parseFloatValue(e.target.value) })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="停顿-后(s)"
                                  type="number"
                                  value={seg.pause_after ?? ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { pause_after: parseFloatValue(e.target.value) })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 情感"
                                  value={seg.instruct_emotion || ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { instruct_emotion: e.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 场景"
                                  value={seg.instruct_scene || ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { instruct_scene: e.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 角色"
                                  value={seg.instruct_role || ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { instruct_role: e.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 身份"
                                  value={seg.instruct_identity || ''}
                                  onChange={(e) =>
                                    onUpdateSegment(idx, { instruct_identity: e.target.value })
                                  }
                                />
                              </Box>
                              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, mt: 1 }}>
                                <TextField
                                  size="small"
                                  label="语速 rate"
                                  type="number"
                                  value={voiceParams.rate ?? voiceParams.speed ?? ''}
                                  onChange={(e) => updateVoiceParams(idx, { rate: parseFloatValue(e.target.value) })}
                                />
                                <TextField
                                  size="small"
                                  label="音高 pitch"
                                  type="number"
                                  value={voiceParams.pitch ?? ''}
                                  onChange={(e) => updateVoiceParams(idx, { pitch: parseFloatValue(e.target.value) })}
                                />
                                <TextField
                                  size="small"
                                  label="音量 volume"
                                  type="number"
                                  value={voiceParams.volume ?? ''}
                                  onChange={(e) => updateVoiceParams(idx, { volume: parseFloatValue(e.target.value) })}
                                />
                              </Box>
                              <TextField
                                fullWidth
                                size="small"
                                label="音效提示（逗号分隔）"
                                value={soundEffectsValue}
                                onChange={(e) =>
                                  onUpdateSegment(idx, {
                                    sound_effects_simple: parseCommaList(e.target.value),
                                    sound_effects: [],
                                  })
                                }
                                sx={{ mt: 1 }}
                              />
                              <TextField
                                fullWidth
                                size="small"
                                label="配乐提示"
                                value={musicCueValue}
                                onChange={(e) =>
                                  onUpdateSegment(idx, {
                                    music_cue_simple: e.target.value,
                                    music_cue: null,
                                  })
                                }
                                sx={{ mt: 1 }}
                              />
                            </Paper>
                          )}
                          {segmentAudioUrls[idx] && (
                            <Box sx={{ mt: 1 }}>
                              <audio controls src={segmentAudioUrls[idx]} />
                            </Box>
                          )}
                        </Box>
                      </ListItem>
                    )
                  })}
                </List>
              </Paper>
            </Box>

            {/* 右侧：评审报告摘要 */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                评审报告
              </Typography>
              {data.scriptReview ? (
                <Paper variant="outlined" sx={{ p: 2, maxHeight: 520, overflow: 'auto' }}>
                  <ScriptReviewReport review={data.scriptReview} />
                </Paper>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  暂无评审数据。
                </Typography>
              )}

              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
                修改剧本后，建议重新生成该章节音频以保证文本与音频一致。
              </Typography>
            </Box>
          </Box>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          关闭
        </Button>
        <Button
          onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
          disabled={loading || !data}
        >
          仅保存剧本
        </Button>
        <Button
          onClick={() => onSaveScript({ nextStatus: 'approved', generateAudio: true })}
          disabled={loading || !data}
          variant="contained"
          sx={{
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          保存并生成该章节音频
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function HistoryDialog({
  open,
  loading,
  historyProjects,
  selectedProject,
  onCloseHistory,
  onViewHistory,
  onDeleteHistory,
}: HistoryDialogProps) {
  const [deleteProjectId, setDeleteProjectId] = useState<number | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  
  const handleOpenDeleteDialog = (projectId: number) => {
    setDeleteProjectId(projectId)
    setDeleteDialogOpen(true)
  }
  
  const handleCloseDeleteDialog = () => {
    setDeleteDialogOpen(false)
    setDeleteProjectId(null)
  }
  
  const handleConfirmDelete = async () => {
    if (deleteProjectId) {
      await onDeleteHistory(deleteProjectId)
      handleCloseDeleteDialog()
    }
  }
  
  return (
    <>
    <Dialog open={open} onClose={onCloseHistory} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <HistoryIcon sx={{ color: '#9c27b0' }} />
          <Typography variant="h6">
            {selectedProject?.title} - 历史生成记录
          </Typography>
        </Box>
      </DialogTitle>
      <DialogContent>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : historyProjects.length === 0 ? (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography variant="body2" color="text.secondary">
              还没有生成过有声书
            </Typography>
          </Box>
        ) : (
          <List>
            {historyProjects.map((project) => (
              <ListItem
                key={project.id}
                sx={{
                  border: '1px solid #e0e0e0',
                  borderRadius: 2,
                  mb: 2,
                  '&:hover': {
                    backgroundColor: 'rgba(156, 39, 176, 0.05)',
                    cursor: 'pointer',
                  },
                }}
                onClick={() => onViewHistory(project.id)}
              >
                <Box sx={{ flex: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Chip
                      label={
                        project.status === 'completed'
                          ? '已完成'
                          : project.status === 'processing'
                          ? '生成中'
                          : project.status === 'failed'
                          ? '失败'
                          : '等待中'
                      }
                      size="small"
                      sx={{
                        backgroundColor:
                          project.status === 'completed'
                            ? '#4caf50'
                            : project.status === 'processing'
                            ? '#ff9800'
                            : project.status === 'failed'
                            ? '#f44336'
                            : '#9e9e9e',
                        color: 'white',
                      }}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {new Date(project.created_at).toLocaleString('zh-CN', {
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <Typography variant="body2">
                      章节：{project.completed_chapters}/{project.total_chapters}
                    </Typography>
                    {project.status === 'completed' && (
                      <Typography variant="body2" color="text.secondary">
                        时长：{((project.total_duration || 0) / 60).toFixed(1)}分钟
                      </Typography>
                    )}
                  </Box>
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      onViewHistory(project.id)
                    }}
                    sx={{ color: '#9c27b0' }}
                  >
                    <PlayIcon />
                  </IconButton>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleOpenDeleteDialog(project.id)
                    }}
                    sx={{ color: '#f44336' }}
                  >
                    <DeleteIcon />
                  </IconButton>
                </Box>
              </ListItem>
            ))}
          </List>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onCloseHistory}>关闭</Button>
      </DialogActions>
    </Dialog>
    
	    {/* 删除确认对话框 */}
	    <Dialog open={deleteDialogOpen} onClose={handleCloseDeleteDialog}>
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <WarningIcon sx={{ color: '#f44336' }} />
          <Typography variant="h6">确认删除</Typography>
        </Box>
      </DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 2 }}>
          此操作将永久删除该有声书项目！
        </Alert>
        <Typography variant="body1" sx={{ mb: 2 }}>
          确定要删除这个有声书项目吗？
        </Typography>
	        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
	          项目ID: {deleteProjectId}
	        </Typography>
	        <Alert severity="info" sx={{ mb: 2 }}>
	          将默认同时删除音频文件（不可恢复）。
	        </Alert>
	      </DialogContent>
	      <DialogActions>
	        <Button onClick={handleCloseDeleteDialog}>取消</Button>
	        <Button 
	          onClick={handleConfirmDelete} 
	          variant="contained" 
	          sx={{
	            backgroundColor: '#f44336',
	            '&:hover': { backgroundColor: '#d32f2f' },
	          }}
	        >
	          确认删除
	        </Button>
	      </DialogActions>
	    </Dialog>
    </>
  )
}

const steps = ['配置音色', '生成有声书', '完成']

const AudiobookPage = () => {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams] = useSearchParams()
  const routeProjectId = useMemo(() => {
    const id = Number(projectId)
    return Number.isFinite(id) ? id : null
  }, [projectId])
  const sourceRouteRequest = useMemo(
    () => readUserAssetSourceAudiobookRouteRequest(searchParams),
    [searchParams],
  )
  const requestedAudiobookProjectId = sourceRouteRequest.audiobookProjectId
  const requestedSourceChapterId = sourceRouteRequest.chapterId
  const requestedSourceFocus = sourceRouteRequest.focus

  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [characterVoices, setCharacterVoices] = useState<CharacterVoiceSetting[]>([])
  const [audioFxConfig, setAudioFxConfig] = useState<AudioFxConfig>({
    enable_sound_effects: true,
    enable_music: true,
    sound_effect_density: 'medium',
    music_density: 'medium',
  })
  const [audiobookProject, setAudiobookProject] = useState<any>(null)
  const [browserPlayerOpen, setBrowserPlayerOpen] = useState(false)
  const [browserPlayerLoading, setBrowserPlayerLoading] = useState(false)
  const [browserPlayerData, setBrowserPlayerData] = useState<BrowserPlayerProjectData | null>(null)
  const [loadingCharacters, setLoadingCharacters] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyProjects, setHistoryProjects] = useState<any[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [scriptReviewDialogOpen, setScriptReviewDialogOpen] = useState(false)
  const [scriptReviewData, setScriptReviewData] = useState<{ report: ScriptReviewDetail | null; segments: any[] } | null>(null)
  const [stageMetricsDialogOpen, setStageMetricsDialogOpen] = useState(false)
  const [stageMetricsData, setStageMetricsData] = useState<{
    stage: StageConfig
    info: StageInfo
  } | null>(null)
  const [scriptEditorDialogOpen, setScriptEditorDialogOpen] = useState(false)
  const [scriptEditorChapter, setScriptEditorChapter] = useState<ScriptEditorChapterRef | null>(null)
  const [scriptEditorData, setScriptEditorData] = useState<ScriptEditorStateData | null>(null)
  const [scriptEditorLoading, setScriptEditorLoading] = useState(false)
  const [editorCrossTabConflict, setEditorCrossTabConflict] = useState<AudiobookEditorSessionState | null>(null)
  const [segmentPreviewingIndex, setSegmentPreviewingIndex] = useState<number | null>(null)
  const [segmentPreviewingType, setSegmentPreviewingType] = useState<PreviewType | null>(null)
  const [segmentAudioUrls, setSegmentAudioUrls] = useState<Record<number, string>>({})
  const [segmentDetailsOpen, setSegmentDetailsOpen] = useState<Record<number, boolean>>({})
  const [reviewMode, setReviewMode] = useState(false)
  const [segmentReviews, setSegmentReviews] = useState<Record<number, { quality_score?: number; needs_regenerate?: boolean }>>({})
  const [regeneratingSegments, setRegeneratingSegments] = useState<Set<number>>(new Set())
  const [scriptOnlyMode, setScriptOnlyMode] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [collectingChapterId, setCollectingChapterId] = useState<number | null>(null)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [currentAudiobookProjectId, setCurrentAudiobookProjectId] = useState<number | null>(null)
  const [resumeCheckpoints, setResumeCheckpoints] = useState<Record<number, GenerationCheckpoint>>({})
  const [resumeCheckpointLoading, setResumeCheckpointLoading] = useState(false)
  const [resumingChapterId, setResumingChapterId] = useState<number | null>(null)
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newProjectText, setNewProjectText] = useState('')
  const [snackbar, setSnackbar] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'info' | 'warning' | 'error'
  }>({
    open: false,
    message: '',
    severity: 'info',
  })
  const [taskPointsPrecheckError, setTaskPointsPrecheckError] = useState<TaskPointsPrecheckErrorDetail | null>(null)
  const [voicePresets, setVoicePresets] = useState<VoicePreset[]>([])
  const [voiceCatalogMeta, setVoiceCatalogMeta] = useState<VoiceCatalogMeta | null>(null)
  const [voiceLoading, setVoiceLoading] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [voicePresetsByModel, setVoicePresetsByModel] = useState<Record<TtsModel, VoicePreset[]>>({
    'qwen3-tts-instruct-flash': [],
    'cosyvoice-v3.5-plus': [],
    'minimax-speech-2.8-hd': [],
    'minimax-speech-2.8-turbo': [],
  })
  const [voiceCatalogMetaByModel, setVoiceCatalogMetaByModel] = useState<Record<TtsModel, VoiceCatalogMeta | null>>({
    'qwen3-tts-instruct-flash': null,
    'cosyvoice-v3.5-plus': null,
    'minimax-speech-2.8-hd': null,
    'minimax-speech-2.8-turbo': null,
  })

  const [cloneName, setCloneName] = useState('')
  const [cloneUrl, setCloneUrl] = useState('')
  const [cloneLoading, setCloneLoading] = useState(false)
  const [cloneUploading, setCloneUploading] = useState(false)
  const [cloneRecording, setCloneRecording] = useState(false)
  const [cloneRecordDialogOpen, setCloneRecordDialogOpen] = useState(false)
  const [cloneDeletingId, setCloneDeletingId] = useState<string | null>(null)
  const [cloneError, setCloneError] = useState<string | null>(null)
  const [cloneSuccess, setCloneSuccess] = useState<string | null>(null)
  const [designName, setDesignName] = useState('')
  const [designPrompt, setDesignPrompt] = useState('')
  const [designPreviewText, setDesignPreviewText] = useState(DEFAULT_DESIGN_PREVIEW_TEXT)
  const [designLoading, setDesignLoading] = useState(false)
  const [designError, setDesignError] = useState<string | null>(null)
  const [designSuccess, setDesignSuccess] = useState<string | null>(null)
  const [autoAssigningVoices, setAutoAssigningVoices] = useState(false)
  const [creatingFromBook, setCreatingFromBook] = useState(false)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only'>('full')
  const [activeStep, setActiveStep] = useState(0)
  const [ttsModel, setTtsModel] = useState<TtsModel>('qwen3-tts-instruct-flash')
  const outputFormat: AudioOutputFormat = 'mp3'
  const supportsTtsTuning = ttsModel === 'cosyvoice-v3.5-plus'
  const [narrationStyle, setNarrationStyle] = useState<NarrationStyleId>(DEFAULT_NARRATION_STYLE)
  const [chapterMenuAnchor, setChapterMenuAnchor] = useState<null | HTMLElement>(null)
  const [selectedChapterForMenu, setSelectedChapterForMenu] = useState<Chapter | null>(null)
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [deleteChapterReason, setDeleteChapterReason] = useState('')
  const [deleteChapterFiles, setDeleteChapterFiles] = useState(false)
  const [deletingChapter, setDeletingChapter] = useState(false)

  const audioRef = useMemo(() => new Audio(), [])
  const playingAudioUrlRef = useRef<string | null>(null)
  const sessionHydratedRef = useRef(false)
  const sessionTabIdRef = useRef<string>(getOrCreateAudiobookSessionTabId())
  const lastSessionTimestampRef = useRef(0)
  const restoredEditorSessionKeyRef = useRef<string | null>(null)
  const restoredPageSessionProjectRef = useRef<number | null>(null)
  const restoredProjectBoundPageSessionKeyRef = useRef<string | null>(null)
  const handledSourceChapterKeyRef = useRef<string | null>(null)
  const skipNextPageSessionPersistRef = useRef(false)
  const dismissedEditorConflictSignatureRef = useRef<string | null>(null)
  const ttsModelRef = useRef<TtsModel>(ttsModel)
  const handleSelectProjectRef = useRef<(project: Project, options?: SelectProjectOptions) => Promise<void>>(
    async () => {},
  )
  const cloneRecorderRef = useRef<MediaRecorder | null>(null)
  const cloneStreamRef = useRef<MediaStream | null>(null)
  const cloneChunksRef = useRef<Blob[]>([])
  const navigationTypeRef = useRef<NavigationType>(typeof window === 'undefined' ? null : detectNavigationType())
  const selectedProjectId = selectedProject?.id ?? null

  useEffect(() => {
    return () => {
      if (playingAudioUrlRef.current) {
        window.URL.revokeObjectURL(playingAudioUrlRef.current)
        playingAudioUrlRef.current = null
      }
    }
  }, [])

  const fetchChapterAudioFile = useCallback(
    async (chapterId: number) => {
      if (!audiobookProject) {
        throw new Error('缺少有声书项目')
      }

      const response = await apiClient.getAudiobookChapterAudioFile(audiobookProject.id, chapterId)
      const blob = response.data as Blob
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `chapter_${chapterId}.${outputFormat}`,
      )

      return {
        blob,
        filename,
        downloadUrl: buildAudiobookChapterDownloadUrl(audiobookProject.id, chapterId),
      }
    },
    [audiobookProject, outputFormat],
  )

  const trackedAudiobookProjectIds = useMemo(() => {
    const ids = new Set<number>()

    for (const project of historyProjects) {
      const projectId = Number(project?.id)
      if (Number.isFinite(projectId) && projectId > 0) {
        ids.add(projectId)
      }
    }

    const currentIds = [audiobookProject?.id, currentAudiobookProjectId]
    for (const candidate of currentIds) {
      const projectId = Number(candidate)
      if (Number.isFinite(projectId) && projectId > 0) {
        ids.add(projectId)
      }
    }

    return Array.from(ids)
  }, [historyProjects, audiobookProject?.id, currentAudiobookProjectId])

  const trackedAudiobookProjectIdKey = useMemo(
    () => trackedAudiobookProjectIds.slice().sort((left, right) => left - right).join(','),
    [trackedAudiobookProjectIds],
  )

  const activeProjectTasks = useMemo(() => {
    const trackedIds = new Set(trackedAudiobookProjectIds)
    return Object.values(taskStatuses)
      .filter((task) => trackedIds.size === 0 || trackedIds.has(task.audiobook_project_id))
      .filter((task) => isActiveAudiobookTask(task))
      .sort(compareTaskByRecency)
  }, [taskStatuses, trackedAudiobookProjectIds])

  const persistedActiveTaskRefs = useMemo(
    () =>
      activeProjectTasks.map((task) => ({
        taskId: task.task_id,
        audiobookProjectId: task.audiobook_project_id,
      })),
    [activeProjectTasks],
  )

  const activeTaskStatus = useMemo(() => {
    if (currentTaskId && taskStatuses[currentTaskId]) {
      return taskStatuses[currentTaskId]
    }
    if (activeProjectTasks.length > 0) {
      return activeProjectTasks[0]
    }
    const first = Object.values(taskStatuses).sort(compareTaskByRecency)[0]
    return first || null
  }, [currentTaskId, taskStatuses, activeProjectTasks])

  const setCharacterVoicesForCurrentModel = useCallback(
    (next: CharacterVoiceSetting[]) => {
      setCharacterVoices(next)
    },
    [],
  )

  const clearActiveGenerationState = useCallback(() => {
    setCurrentAudiobookProjectId(null)
    setCurrentTaskId(null)
    setTaskStatuses({})
    setGenerating(false)
  }, [])

  const formatActiveTaskLabel = useCallback(
    (task: TaskStatus) => {
      const chapter = task.chapter_id
        ? chapters.find((item) => item.id === task.chapter_id)
        : null
      const chapterLabel = chapter
        ? `第${chapter.chapter_number}章`
        : task.chapter_id
        ? `章节${task.chapter_id}`
        : '批量任务'

      switch (task.task_type) {
        case 'script_only':
          return `${chapterLabel} 剧本`
        case 'audio_from_scripts':
          return `${chapterLabel} 音频`
        case 'full':
          return `${chapterLabel} 全流程`
        default:
          return chapterLabel
      }
    },
    [chapters],
  )

  const updateCharacterVoicesForCurrentModel = (
    updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[],
  ) => {
    setCharacterVoices((prev) => {
      return updater(prev)
    })
  }

  const currentVoicePresets = useMemo(() => {
    if (voicePresets.length === 0) {
      return []
    }

    const sorted = [...voicePresets].sort((a, b) => {
      const catA = a.category || 'general'
      const catB = b.category || 'general'
      if (catA !== catB) {
        return catA.localeCompare(catB, 'zh-CN')
      }
      const labelA = a.label || a.id
      const labelB = b.label || b.id
      return labelA.localeCompare(labelB, 'zh-CN')
    })

    return sorted
  }, [voicePresets, ttsModel])

  const customVoicePresets = useMemo(() => {
    if (ttsModel !== 'cosyvoice-v3.5-plus') {
      return []
    }
    return currentVoicePresets.filter((preset) => preset.category === 'custom')
  }, [currentVoicePresets, ttsModel])

  const cosyvoiceHasUsableVoice = useMemo(() => {
    if (ttsModel !== 'cosyvoice-v3.5-plus') {
      return true
    }
    return currentVoicePresets.length > 0 || characterVoices.some((item) => Boolean(item.voiceId))
  }, [characterVoices, currentVoicePresets, ttsModel])

  const ensureCurrentTtsModelReady = useCallback(() => {
    if (ttsModel !== 'cosyvoice-v3.5-plus' || cosyvoiceHasUsableVoice) {
      return true
    }
    setSnackbar({
      open: true,
      message: 'CosyVoice v3.5-plus 没有系统音色，请先创建至少一个自定义音色再生成。',
      severity: 'error',
    })
    return false
  }, [cosyvoiceHasUsableVoice, ttsModel])

  const refreshAudiobookProjectDetail = useCallback(async (audiobookProjectId: number) => {
    const response = await apiClient.getAudiobookProject(audiobookProjectId)
    const data = response.data
    setAudiobookProject(data)
    return data
  }, [])

  const focusAudiobookTask = useCallback(
    async (
      task: TaskStatus,
      options?: {
        loadProjectDetail?: boolean
        forceGenerating?: boolean
        activateProgressView?: boolean
      },
    ) => {
      setCurrentTaskId(task.task_id)
      setCurrentAudiobookProjectId(task.audiobook_project_id)

      if (options?.forceGenerating ?? isActiveAudiobookTask(task)) {
        setGenerating(true)
      }

      if (options?.activateProgressView) {
        setActiveStep(1)
      } else if (options?.forceGenerating ?? isActiveAudiobookTask(task)) {
        setActiveStep((prev) => (prev === 0 ? 1 : prev))
      }

      if (
        options?.loadProjectDetail !== false
        && task.audiobook_project_id
        && audiobookProject?.id !== task.audiobook_project_id
      ) {
        try {
          await refreshAudiobookProjectDetail(task.audiobook_project_id)
        } catch {
          // 切换任务焦点时刷新有声书项目详情失败
        }
      }
    },
    [audiobookProject?.id, refreshAudiobookProjectDetail],
  )

  const activateQueuedAudiobookTask = useCallback(
    async (
      audiobookProjectId: number,
      jobId: string,
      options?: {
        generationMode?: 'full' | 'script_only'
        successMessage?: string
      },
    ) => {
      const nextTaskType = options?.generationMode || 'full'
      setTaskStatuses((prev) => ({
        ...prev,
        [jobId]: buildPendingTaskStatus({
          taskId: jobId,
          audiobookProjectId,
          taskType: nextTaskType,
        }),
      }))
      setLastGenerationMode(nextTaskType)

      await focusAudiobookTask(
        buildPendingTaskStatus({
          taskId: jobId,
          audiobookProjectId,
          taskType: nextTaskType,
        }),
        {
          forceGenerating: true,
          activateProgressView: true,
        },
      )

      if (options?.successMessage) {
        setSnackbar({
          open: true,
          message: options.successMessage,
          severity: 'success',
        })
      }
    },
    [focusAudiobookTask],
  )

  const resumableChapterEntries = useMemo(() => {
    const chapterAudios = Array.isArray(audiobookProject?.chapter_audios) ? audiobookProject.chapter_audios : []
    return chapterAudios
      .map((chapterAudio: any) => {
        const checkpoint = resumeCheckpoints[chapterAudio.chapter_id]
        const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
        return {
          chapterAudio,
          checkpoint,
          chapter,
        }
      })
      .filter((entry: { checkpoint?: GenerationCheckpoint }) => Boolean(entry.checkpoint?.can_resume))
  }, [audiobookProject, chapters, resumeCheckpoints])

  // 从 URL 参数加载项目，并在刷新/回退时按顺序恢复会话
  useEffect(() => {
    let cancelled = false

    const loadProjectFromUrl = async () => {
      sessionHydratedRef.current = false
      restoredEditorSessionKeyRef.current = null
      restoredPageSessionProjectRef.current = null
      restoredProjectBoundPageSessionKeyRef.current = null
      lastSessionTimestampRef.current = 0

      if (!routeProjectId) {
        setSnackbar({ open: true, message: '缺少项目ID参数', severity: 'error' })
        navigate('/audiobook-dashboard')
        return
      }

      const navType = navigationTypeRef.current
      const shouldRestore = navType === 'reload' || navType === 'back_forward' || isSamePathReferrer()
      let savedSession: AudiobookSessionState | null = null

      if (shouldRestore) {
        const raw = localStorage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)
        if (raw) {
          try {
            const saved = JSON.parse(raw) as AudiobookSessionState
            if (saved.projectId === routeProjectId) {
              savedSession = saved
            } else {
              localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
            }
          } catch {
            localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
          }
        }

        const editorRaw = sessionStorage.getItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
        if (editorRaw) {
          try {
            const savedEditorSession = JSON.parse(editorRaw) as AudiobookEditorSessionState
            if (savedEditorSession.projectId !== routeProjectId) {
              sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
            }
          } catch {
            sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
          }
        }

        const pageRaw = sessionStorage.getItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
        if (pageRaw) {
          try {
            const savedPageSession = JSON.parse(pageRaw) as AudiobookPageSessionState
            if (savedPageSession.projectId !== routeProjectId) {
              sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
            }
          } catch {
            sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
          }
        }
      } else {
        localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
        sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
        sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
      }

      const restoredTtsModel = normalizeTtsModelValue(savedSession?.ttsModel) || ttsModelRef.current
      const restoredActiveTasks = dedupeSessionTaskRefs(savedSession?.activeTasks)
      const restoredSelectedChapterIds = normalizeSelectedChapterIds(savedSession?.selectedChapterIds)
      const restoredTaskId = savedSession?.taskId
        || restoredActiveTasks[0]?.taskId
        || null
      const restoredAudiobookProjectId = savedSession?.audiobookProjectId
        || restoredActiveTasks.find((item) => item.taskId === restoredTaskId)?.audiobookProjectId
        || restoredActiveTasks[0]?.audiobookProjectId
        || null

      lastSessionTimestampRef.current = parseSessionTimestamp(savedSession?.updatedAt)

      if (savedSession && restoredTtsModel !== ttsModelRef.current) {
        setTtsModel(restoredTtsModel)
      }

      try {
        const projectRes = await apiClient.getProject(routeProjectId)
        if (cancelled) return

        const project = projectRes.data as Project
        await handleSelectProjectRef.current(project, {
          skipStepReset: true,
          preserveSessionState: Boolean(savedSession),
          ttsModelOverride: restoredTtsModel,
          selectedChapterIds: restoredSelectedChapterIds,
        })

        if (cancelled || !savedSession) {
          return
        }

        if (typeof savedSession.activeStep === 'number') {
          setActiveStep(savedSession.activeStep)
        }

        if (restoredActiveTasks.length > 0) {
          setTaskStatuses((prev) => {
            const next = { ...prev }
            for (const taskRef of restoredActiveTasks) {
              if (!next[taskRef.taskId]) {
                next[taskRef.taskId] = buildPendingTaskStatus({
                  taskId: taskRef.taskId,
                  audiobookProjectId: taskRef.audiobookProjectId,
                })
              }
            }
            return next
          })
        }

        if (restoredAudiobookProjectId) {
          setCurrentAudiobookProjectId(restoredAudiobookProjectId)
          try {
            const detailRes = await apiClient.getAudiobookProject(restoredAudiobookProjectId)
            if (!cancelled) {
              setAudiobookProject(detailRes.data)
            }
          } catch {
            // 恢复有声书项目失败
          }
        }

        if (!cancelled) {
          setCurrentTaskId(restoredTaskId)
          setGenerating(
            restoredTaskId || restoredActiveTasks.length > 0
              ? (savedSession.generating ?? true)
              : false,
          )
        }
      } catch (error: any) {
        const msg = await extractApiErrorMessage(error, '加载项目失败')
        if (!cancelled) {
          setSnackbar({ open: true, message: msg, severity: 'error' })
          navigate('/audiobook-dashboard')
        }
      } finally {
        if (!cancelled) {
          sessionHydratedRef.current = true
        }
      }
    }

    loadProjectFromUrl()

    return () => {
      cancelled = true
    }
  }, [routeProjectId, navigate])

  // 页面初始化时加载所有模型的音色目录（并行加载）
  useEffect(() => {
    const models: TtsModel[] = ['qwen3-tts-instruct-flash', 'cosyvoice-v3.5-plus', 'minimax-speech-2.8-hd', 'minimax-speech-2.8-turbo']

    const loadAllVoiceCatalogs = async () => {
      setVoiceLoading(true)
      try {
        const results = await Promise.all(
          models.map(async (model) => {
            const res = await apiClient.getTtsVoices(model)
            const data = res.data || {}
            const voicesFromApi = (data.voices || []) as VoicePreset[]
            const normalized = voicesFromApi.map((voice) => ({
              ...voice,
              supportsInstruct: Boolean(voice.supportsInstruct),
            }))
            return { model, voices: normalized, meta: {
              model: data.model,
              updated_at: data.updated_at,
              source: data.source,
              voice_count: data.voice_count || normalized.length,
            }}
          })
        )

        const newPresetsByModel: Record<TtsModel, VoicePreset[]> = {
          'qwen3-tts-instruct-flash': [],
          'cosyvoice-v3.5-plus': [],
          'minimax-speech-2.8-hd': [],
          'minimax-speech-2.8-turbo': [],
        }
        const newMetaByModel: Record<TtsModel, VoiceCatalogMeta | null> = {
          'qwen3-tts-instruct-flash': null,
          'cosyvoice-v3.5-plus': null,
          'minimax-speech-2.8-hd': null,
          'minimax-speech-2.8-turbo': null,
        }

        for (const result of results) {
          newPresetsByModel[result.model] = result.voices
          newMetaByModel[result.model] = result.meta as VoiceCatalogMeta
        }

        setVoicePresetsByModel(newPresetsByModel)
        setVoiceCatalogMetaByModel(newMetaByModel)
        setVoicePresets(newPresetsByModel['cosyvoice-v3.5-plus'] || [])
        setVoiceCatalogMeta(newMetaByModel['cosyvoice-v3.5-plus'] || null)
        setVoiceError(null)
      } catch (error: any) {
        const message = await extractApiErrorMessage(error, '加载音色库失败')
        setVoiceError(message)
      } finally {
        setVoiceLoading(false)
      }
    }

    loadAllVoiceCatalogs()
  }, [])

  // 根据角色级模型选择更新音色列表显示
  useEffect(() => {
    if (voicePresetsByModel[ttsModel]) {
      setVoicePresets(voicePresetsByModel[ttsModel])
      setVoiceCatalogMeta(voiceCatalogMetaByModel[ttsModel])
    }
  }, [ttsModel, voicePresetsByModel, voiceCatalogMetaByModel])

  // 刷新某个模型的音色（用于克隆音色创建后刷新）
  const refreshVoiceCatalog = async (model: TtsModel) => {
    try {
      const res = await apiClient.getTtsVoices(model)
      const data = res.data || {}
      const voicesFromApi = (data.voices || []) as VoicePreset[]
      const normalized = voicesFromApi.map((voice) => ({
        ...voice,
        supportsInstruct: Boolean(voice.supportsInstruct),
      }))
      setVoicePresetsByModel((prev) => ({ ...prev, [model]: normalized }))
      setVoiceCatalogMetaByModel((prev) => ({ ...prev, [model]: data as VoiceCatalogMeta }))
      if (model === ttsModel) {
        setVoicePresets(normalized)
        setVoiceCatalogMeta(data as VoiceCatalogMeta)
      }
    } catch (error) {
      console.error(`刷新 ${model} 音色库失败:`, error)
    }
  }

  const fetchVoiceCatalog = async () => {
    await refreshVoiceCatalog(ttsModel)
  }

  const handleCreateCloneVoice = async () => {
    setCloneLoading(true)
    setCloneError(null)
    setCloneSuccess(null)
    setDesignError(null)
    setDesignSuccess(null)
    try {
      const name = cloneName.trim()
      const url = cloneUrl.trim()
      const res = await apiClient.createCosyVoiceV3PlusClone({ name, url })
      const voiceId = (res.data?.voice_id as string) || ''
      setCloneSuccess(voiceId ? `已提交复刻任务：${voiceId}` : '已提交复刻任务')
      setCloneName('')
      setCloneUrl('')
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '创建复刻音色失败')
      setCloneError(message)
    } finally {
      setCloneLoading(false)
    }
  }

  const handleCreateDesignVoice = async () => {
    setDesignLoading(true)
    setDesignError(null)
    setDesignSuccess(null)
    setCloneError(null)
    setCloneSuccess(null)
    try {
      const name = designName.trim()
      const voicePrompt = designPrompt.trim()
      const previewText = designPreviewText.trim()
      const res = await apiClient.createCosyVoiceV3PlusDesign({
        name,
        voice_prompt: voicePrompt,
        preview_text: previewText,
      })
      const voiceId = (res.data?.voice_id as string) || ''
      setDesignSuccess(voiceId ? `已提交声音设计任务：${voiceId}` : '已提交声音设计任务')
      setDesignName('')
      setDesignPrompt('')
      setDesignPreviewText(DEFAULT_DESIGN_PREVIEW_TEXT)
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '创建设计音色失败')
      setDesignError(message)
    } finally {
      setDesignLoading(false)
    }
  }

  const handleDeleteCustomVoice = async (voiceId: string, label?: string) => {
    if (!voiceId || cloneDeletingId) return
    const displayName = label || voiceId
    if (!confirm(`确定要删除自定义音色「${displayName}」吗？\n\n该操作会从当前账号移除该音色，无法恢复。`)) {
      return
    }
    setCloneDeletingId(voiceId)
    setCloneError(null)
    setCloneSuccess(null)
    setDesignError(null)
    setDesignSuccess(null)
    try {
      await apiClient.deleteCosyVoiceV3PlusClone(voiceId)
      updateCharacterVoicesForCurrentModel((prev) =>
        prev.map((item) => (item.voiceId === voiceId ? { ...item, voiceId: '' } : item)),
      )
      setCloneSuccess(`已删除自定义音色：${displayName}`)
      await refreshVoiceCatalog('cosyvoice-v3.5-plus')
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '删除自定义音色失败')
      setCloneError(message)
    } finally {
      setCloneDeletingId(null)
    }
  }

  const handleUploadCloneAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setCloneUploading(true)
    setCloneError(null)
    setCloneSuccess(null)
    try {
      const res = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
      const url = (res.data?.url as string) || ''
      if (!url) {
        throw new Error('未返回临时URL')
      }
      setCloneUrl(url)
      setCloneSuccess('已上传音频并生成临时URL（48小时有效）')
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '上传音频失败')
      setCloneError(message)
    } finally {
      setCloneUploading(false)
    }
  }

  const stopCloneRecordingStream = () => {
    if (cloneStreamRef.current) {
      cloneStreamRef.current.getTracks().forEach((track) => track.stop())
      cloneStreamRef.current = null
    }
  }

  const uploadRecordedCloneAudio = async (blob: Blob) => {
    setCloneUploading(true)
    setCloneError(null)
    setCloneSuccess(null)
    try {
      const filename = `recording_${Date.now()}.webm`
      const file = new File([blob], filename, { type: blob.type || 'audio/webm' })
      const res = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
      const url = (res.data?.url as string) || ''
      if (!url) {
        throw new Error('未返回临时URL')
      }
      setCloneUrl(url)
      setCloneSuccess('录音已上传并生成临时URL（48小时有效）')
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '上传录音失败')
      setCloneError(message)
    } finally {
      setCloneUploading(false)
    }
  }

  const handleStartCloneRecording = async () => {
    if (cloneLoading || cloneUploading || cloneRecording) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setCloneError('当前浏览器不支持录音，请改用上传音频')
      return
    }
    setCloneError(null)
    setCloneSuccess(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      cloneStreamRef.current = stream
      cloneChunksRef.current = []
      const recorder = new MediaRecorder(stream)
      cloneRecorderRef.current = recorder
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          cloneChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        const chunks = cloneChunksRef.current
        cloneChunksRef.current = []
        cloneRecorderRef.current = null
        setCloneRecording(false)
        stopCloneRecordingStream()
        if (chunks.length === 0) {
          setCloneError('未获取到录音数据，请重试')
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void uploadRecordedCloneAudio(blob)
      }
      recorder.onerror = () => {
        cloneRecorderRef.current = null
        setCloneRecording(false)
        stopCloneRecordingStream()
        setCloneError('录音失败，请重试')
      }
      recorder.start()
      setCloneRecording(true)
    } catch (error: any) {
      stopCloneRecordingStream()
      setCloneRecording(false)
      const message = await extractApiErrorMessage(error, '无法访问麦克风，请检查权限')
      setCloneError(message)
    }
  }

  const handleStopCloneRecording = () => {
    const recorder = cloneRecorderRef.current
    if (!recorder) return
    if (recorder.state === 'inactive') {
      cloneRecorderRef.current = null
      setCloneRecording(false)
      stopCloneRecordingStream()
      return
    }
    recorder.stop()
  }

  const handleOpenCloneRecordDialog = () => {
    setCloneRecordDialogOpen(true)
  }

  const handleCloseCloneRecordDialog = () => {
    if (cloneRecording) return
    setCloneRecordDialogOpen(false)
  }

  // 新增：获取历史记录
  const fetchHistory = useCallback(
    async (options?: { projectId?: number | null; showLoading?: boolean }) => {
      const targetProjectId = options?.projectId ?? selectedProjectId
      if (!targetProjectId) {
        setHistoryProjects([])
        return []
      }

      const shouldShowLoading = options?.showLoading ?? true
      if (shouldShowLoading) {
        setLoadingHistory(true)
      }

      try {
        const res = await apiClient.getAudiobookProjectsByProject(targetProjectId)
        const nextProjects = Array.isArray(res.data) ? res.data : []
        setHistoryProjects(nextProjects)
        return nextProjects
      } catch {
        return []
      } finally {
        if (shouldShowLoading) {
          setLoadingHistory(false)
        }
      }
    },
    [selectedProjectId],
  )

  useEffect(() => {
    if (!selectedProjectId) {
      setHistoryProjects([])
      return
    }

    void fetchHistory({ projectId: selectedProjectId, showLoading: false })
  }, [selectedProjectId, fetchHistory])
  
  // 新增：查看历史项目详情
  const handleViewHistory = async (audiobookProjectId: number) => {
    try {
      const res = await apiClient.getAudiobookProject(audiobookProjectId)
      const data = res.data
      clearActiveGenerationState()
      setAudiobookProject(data)
      setBrowserPlayerData(null)
      setBrowserPlayerOpen(false)
      setCurrentAudiobookProjectId(data.id)
      setActiveStep(2) // 跳转到完成页面
      setShowHistory(false)
    } catch {
      setSnackbar({ open: true, message: '加载失败', severity: 'error' })
    }
  }
  
  // 新增：删除历史项目
  const handleDeleteHistory = async (audiobookProjectId: number) => {
    try {
      await apiClient.deleteAudiobookProject(audiobookProjectId, { delete_files: true })
      setSnackbar({ open: true, message: '项目已删除', severity: 'success' })
      // 重新获取历史记录以更新列表
      await fetchHistory({ showLoading: false })
    } catch (error: any) {
      const errorMessage = error?.response?.status === 404 
        ? '项目不存在或已被删除' 
        : await extractApiErrorMessage(error, '删除失败，请重试')
      setSnackbar({ open: true, message: errorMessage, severity: 'error' })
    }
  }

  const handleCreateProjectFromText = async () => {
    const rawText = newProjectText.trim()
    if (!rawText) {
      setSnackbar({ open: true, message: '请先粘贴文本内容', severity: 'error' })
      return
    }

    const title = newProjectTitle.trim() || '从整本书导入的项目'

    const waitForStatus = async (bookId: number, targetStatuses: string[]) => {
      // 简单轮询拆书/分析状态
      // 这里不使用全局 pollStatus，避免和两阶段状态混淆
      // targetStatuses 一般为 ['chapters_done'] 或 ['completed']
      while (true) {
        const status = await bookParserApi.getParseStatus(bookId)
        if (targetStatuses.includes(status.status)) {
          return status
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '拆书任务失败')
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
      }
    }

    setCreatingFromBook(true)
    try {
      // 1. 上传整本书文本
      const book = await bookParserApi.uploadText({
        title,
        content: rawText,
      })

      const bookId = book.id

      // 2. 执行章节切分
      await bookParserApi.parseBook(bookId)
      await waitForStatus(bookId, ['chapters_done'])

      // 3. 执行AI分析（人物/世界观/情节等），便于后续创作
      await bookParserApi.analyzeBook(bookId)
      await waitForStatus(bookId, ['completed'])

      // 4. 导入为灵感方舟项目（包含章节内容）
      const importResult = await bookParserApi.importToProject(bookId, {
        project_title: title,
        import_settings: true,
        import_characters: true,
        import_chapters: true,
      })

      // 5. 选中新建项目，直接进入音色配置
      try {
        const projectRes = await apiClient.getProject(importResult.project_id)
        const project = projectRes.data as Project
        await handleSelectProject(project, { skipStepReset: true })
      } catch (e) {
        // 回退：如果获取单个项目失败，至少构造一个最小的项目对象
        const fallbackProject: Project = {
          id: importResult.project_id,
          title: importResult.project_title || title,
          description: undefined,
          genre: undefined,
        }
        await handleSelectProject(fallbackProject, { skipStepReset: true })
      }

      setActiveStep(0)
      setNewProjectDialogOpen(false)
      setNewProjectTitle('')
      setNewProjectText('')

      setSnackbar({
        open: true,
        message: '已从文本创建项目，请配置音色后生成有声书',
        severity: 'success',
      })
    } catch (error: any) {
      const msg = await extractApiErrorMessage(error, '从文本创建项目失败，请稍后重试')
      setSnackbar({
        open: true,
        message: msg,
        severity: 'error',
      })
    } finally {
      setCreatingFromBook(false)
    }
  }

  // 选择项目
  type SelectProjectOptions = {
    skipStepReset?: boolean
    preserveSessionState?: boolean
    ttsModelOverride?: TtsModel
    selectedChapterIds?: number[]
  }

  const handleSelectProject = useCallback(async (project: Project, options?: SelectProjectOptions) => {
    const resolvedTtsModel = options?.ttsModelOverride ?? ttsModel
    setSelectedProject(project)
    setTaskPointsPrecheckError(null)
    setCharacterVoices([])
    setBrowserPlayerData(null)
    setBrowserPlayerOpen(false)
    setChapterMenuAnchor(null)
    setSelectedChapterForMenu(null)
    setDeleteChapterDialogOpen(false)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)

    if (!options?.preserveSessionState) {
      clearActiveGenerationState()
      setAudiobookProject(null)
    }

    const baseNarratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: getFallbackVoiceId(resolvedTtsModel, voicePresetsByModel[resolvedTtsModel] || []),
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }
    
    try {
      // 获取章节列表
      const chaptersRes = await apiClient.getChapters(project.id)
      const chaptersData = chaptersRes.data
      setChapters(chaptersData)
      setSelectedChapters(
        normalizeSelectedChapterIds(options?.selectedChapterIds, {
          allowedIds: chaptersData.map((c: Chapter) => c.id),
          fallbackIds: chaptersData.map((c: Chapter) => c.id),
        }),
      )

      // 获取角色列表（用于音频配置）
      setLoadingCharacters(true)
      try {
        const charactersRes = await apiClient.getCharacters(project.id)
        const charactersData = charactersRes.data
      
        // 尝试读取项目级音频配置（角色音 + 音效/BGM）
        let projectAudioConfig: ProjectAudioConfig | null = null
        try {
          const audioConfigRes = await apiClient.getProjectAudioConfig(project.id, resolvedTtsModel)
          projectAudioConfig = audioConfigRes.data
        } catch {
          // 获取项目音频配置失败
        }
      
        const savedCharacters = projectAudioConfig?.characters || []
        const savedFx = projectAudioConfig?.audio_fx || null
      
        // 根据已保存的角色音配置初始化角色音
        const characterVoicesFromApi: CharacterVoiceSetting[] = charactersData.map((c: any) => {
          const saved = savedCharacters.find((sc) => sc.character_id === c.id)
          return {
            characterId: c.id,
            name: c.name,
            gender: c.gender,
            role: c.role,
            voiceId: normalizeVoiceId(resolvedTtsModel, saved?.voice_id),
            volume: saved?.volume ?? 50,
            speed: saved?.speed ?? 1.0,
            pitch: saved?.pitch ?? 50,
            ttsModel: normalizeTtsModelValue(saved?.tts_model) || resolvedTtsModel,  // 🆕 从保存的配置中获取tts_model
            voiceType: saved?.voice_type || undefined,  // 🆕 从保存的配置中获取声音类型
            personality: saved?.personality || undefined,  // 🆕 从保存的配置中获取性格类型
            emotionTendency: saved?.emotion_tendency || undefined,  // 🆕 从保存的配置中获取情感倾向
          }
        })
      
        // 旁白使用 character_id 为 0 或 name 为"旁白"的配置（如有）
        const narratorSaved = savedCharacters.find(
          (sc) => sc.character_id === 0 || sc.name === '旁白'
        )
        const narratorVoice: CharacterVoiceSetting = {
          ...baseNarratorVoice,
          voiceId: normalizeVoiceId(resolvedTtsModel, narratorSaved?.voice_id) || baseNarratorVoice.voiceId,
          volume: narratorSaved?.volume ?? baseNarratorVoice.volume,
          speed: narratorSaved?.speed ?? baseNarratorVoice.speed,
          pitch: narratorSaved?.pitch ?? baseNarratorVoice.pitch,
        }
      
        const initialVoices: CharacterVoiceSetting[] = [
          narratorVoice,
          ...characterVoicesFromApi,
        ]
        setCharacterVoicesForCurrentModel(initialVoices)
      
        // 初始化项目级音效/BGM 配置
        if (savedFx) {
          setAudioFxConfig({
            enable_sound_effects: savedFx.enable_sound_effects ?? true,
            enable_music: savedFx.enable_music ?? true,
            sound_effect_density: (savedFx.sound_effect_density as AudioFxConfig['sound_effect_density']) || 'medium',
            music_density: (savedFx.music_density as AudioFxConfig['music_density']) || 'medium',
          })
        } else {
          setAudioFxConfig({
            enable_sound_effects: true,
            enable_music: true,
            sound_effect_density: 'medium',
            music_density: 'medium',
          })
        }
      } catch {
        setCharacterVoices([baseNarratorVoice])
      } finally {
        setLoadingCharacters(false)
      }

      if (!options?.skipStepReset) {
        setActiveStep(0)
      }
    } catch {
      setSnackbar({ open: true, message: '网络错误，请重试', severity: 'error' })
    }
  }, [clearActiveGenerationState, setCharacterVoicesForCurrentModel, ttsModel, voicePresetsByModel])

  const handleOpenBrowserPlayer = useCallback(async () => {
    if (!audiobookProject?.id) {
      setSnackbar({ open: true, message: '请先生成或加载有声书项目', severity: 'warning' })
      return
    }

    setBrowserPlayerLoading(true)
    try {
      const response = await apiClient.getBrowserPlayerData(audiobookProject.id)
      const data = response.data as BrowserPlayerProjectData

      if (!data?.chapters?.length) {
        setSnackbar({ open: true, message: '当前项目暂无可播放章节', severity: 'warning' })
        return
      }

      setBrowserPlayerData(data)
      setBrowserPlayerOpen(true)
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '加载浏览器播放器失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setBrowserPlayerLoading(false)
    }
  }, [audiobookProject?.id])

  const handleCloseBrowserPlayer = useCallback(() => {
    setBrowserPlayerOpen(false)
  }, [])

  useEffect(() => {
    ttsModelRef.current = ttsModel
  }, [ttsModel])

  useLayoutEffect(() => {
    handleSelectProjectRef.current = handleSelectProject
  }, [handleSelectProject])

  const writeEditorSyncEntries = useCallback((
    entries: Record<string, AudiobookEditorSessionState>,
  ) => {
    if (typeof window === 'undefined') {
      return
    }

    const nextEntries = pruneAudiobookEditorSyncEntries(entries)
    if (Object.keys(nextEntries).length === 0) {
      localStorage.removeItem(AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY)
      return
    }

    localStorage.setItem(
      AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY,
      JSON.stringify({ entries: nextEntries } satisfies AudiobookEditorSyncRegistry),
    )
  }, [])

  const readEditorSyncEntries = useCallback((rawRegistry?: string | null) => {
    if (typeof window === 'undefined') {
      return {}
    }

    const serializedRegistry = rawRegistry ?? localStorage.getItem(AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY)
    if (!serializedRegistry) {
      return {}
    }

    const currentEntries = normalizeAudiobookEditorSyncRegistry(
      JSON.parse(serializedRegistry) as AudiobookEditorSyncRegistry,
    )
    const nextEntries = pruneAudiobookEditorSyncEntries(currentEntries)

    if (Object.keys(nextEntries).length !== Object.keys(currentEntries).length) {
      writeEditorSyncEntries(nextEntries)
    }

    return nextEntries
  }, [writeEditorSyncEntries])

  const buildCurrentEditorSyncEntry = useCallback((updatedAt: string) => {
    if (
      !selectedProjectId
      || !audiobookProject?.id
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      return null
    }

    return {
      projectId: selectedProjectId,
      audiobookProjectId: audiobookProject.id,
      chapterId: scriptEditorChapter.chapterId,
      reviewMode,
      openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
      segmentReviews,
      data: scriptEditorData,
      updatedAt,
      writerTabId: sessionTabIdRef.current,
    } satisfies AudiobookEditorSessionState
  }, [
    selectedProjectId,
    audiobookProject?.id,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
  ])

  const upsertCurrentEditorSyncEntry = useCallback((options?: { forceTouch?: boolean }) => {
    if (typeof window === 'undefined') {
      return
    }

    const writerTabId = sessionTabIdRef.current
    const updatedAt = new Date().toISOString()
    const nextEntry = buildCurrentEditorSyncEntry(updatedAt)
    if (!nextEntry) {
      return
    }

    try {
      const currentEntries = readEditorSyncEntries()
      const currentSelfEntry = currentEntries[writerTabId]
      const currentSelfComparablePayload = currentSelfEntry
        ? JSON.stringify(buildComparableAudiobookEditorSessionPayload(currentSelfEntry))
        : null
      const nextComparablePayload = JSON.stringify(
        buildComparableAudiobookEditorSessionPayload(nextEntry),
      )
      const currentSelfUpdatedAtMs = parseSessionTimestamp(currentSelfEntry?.updatedAt)
      const shouldRefreshHeartbeat = Boolean(
        options?.forceTouch
        || !currentSelfEntry
        || currentSelfUpdatedAtMs <= 0
        || Date.now() - currentSelfUpdatedAtMs >= AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS,
      )

      if (
        currentSelfComparablePayload === nextComparablePayload
        && !shouldRefreshHeartbeat
      ) {
        return
      }

      writeEditorSyncEntries({
        ...currentEntries,
        [writerTabId]: nextEntry,
      })
    } catch {
      // localStorage 不可用或容量不足时忽略跨标签页草稿同步元数据
    }
  }, [buildCurrentEditorSyncEntry, readEditorSyncEntries, writeEditorSyncEntries])

  const removeCurrentEditorSyncEntry = useCallback(() => {
    if (typeof window === 'undefined') {
      return
    }

    const writerTabId = sessionTabIdRef.current
    try {
      const currentEntries = readEditorSyncEntries()
      if (!currentEntries[writerTabId]) {
        return
      }

      const nextEntries = { ...currentEntries }
      delete nextEntries[writerTabId]
      writeEditorSyncEntries(nextEntries)
    } catch {
      // 忽略跨标签页草稿同步元数据清理失败
    }
  }, [readEditorSyncEntries, writeEditorSyncEntries])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }

    const handleBeforeUnload = () => {
      removeCurrentEditorSyncEntry()
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      removeCurrentEditorSyncEntry()
    }
  }, [removeCurrentEditorSyncEntry])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !scriptEditorDialogOpen
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      return
    }

    const intervalId = window.setInterval(() => {
      upsertCurrentEditorSyncEntry({ forceTouch: true })
    }, AUDIOBOOK_EDITOR_SYNC_HEARTBEAT_MS)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    upsertCurrentEditorSyncEntry,
  ])

  useEffect(() => {
    let cancelled = false

    const loadResumeCheckpoints = async () => {
      const targetAudiobookProjectId = audiobookProject?.id
      const chapterAudios = Array.isArray(audiobookProject?.chapter_audios) ? audiobookProject.chapter_audios : []

      if (!targetAudiobookProjectId || chapterAudios.length === 0) {
        setResumeCheckpoints({})
        setResumeCheckpointLoading(false)
        return
      }

      const candidateChapterIds: number[] = Array.from(
        new Set<number>(
          chapterAudios
            .filter((chapterAudio: any) => !chapterAudio?.audio_path)
            .map((chapterAudio: any) => Number(chapterAudio.chapter_id))
            .filter((chapterId: number) => Number.isFinite(chapterId) && chapterId > 0),
        ),
      )

      if (candidateChapterIds.length === 0) {
        setResumeCheckpoints({})
        setResumeCheckpointLoading(false)
        return
      }

      setResumeCheckpointLoading(true)

      try {
        const checkpointEntries = await Promise.all(
          candidateChapterIds.map(async (chapterId) => {
            try {
              const response = await apiClient.getGenerationCheckpoint(targetAudiobookProjectId, chapterId)
              const checkpoint = response.data as GenerationCheckpoint
              if (!checkpoint || typeof checkpoint.chapter_id !== 'number') {
                return null
              }
              return [chapterId, checkpoint] as const
            } catch {
              return null
            }
          }),
        )

        if (cancelled) return

        const nextCheckpoints = checkpointEntries.reduce((acc, entry: readonly [number, GenerationCheckpoint] | null) => {
          if (entry) {
            acc[entry[0]] = entry[1]
          }
          return acc
        }, {} as Record<number, GenerationCheckpoint>)

        setResumeCheckpoints(nextCheckpoints)
      } finally {
        if (!cancelled) {
          setResumeCheckpointLoading(false)
        }
      }
    }

    loadResumeCheckpoints()

    return () => {
      cancelled = true
    }
  }, [audiobookProject])

  // 章节菜单相关处理函数
  const handleOpenChapterMenu = (event: React.MouseEvent<HTMLElement>, chapter: Chapter) => {
    event.stopPropagation()
    setChapterMenuAnchor(event.currentTarget)
    setSelectedChapterForMenu(chapter)
  }

  const handleCloseChapterMenu = () => {
    setChapterMenuAnchor(null)
    setSelectedChapterForMenu(null)
  }

  const handleOpenDeleteChapterDialog = () => {
    if (!selectedChapterForMenu) {
      setChapterMenuAnchor(null)
      return
    }
    setChapterMenuAnchor(null)
    setDeleteChapterDialogOpen(true)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
  }

  const handleCloseDeleteChapterDialog = () => {
    setDeleteChapterDialogOpen(false)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
    setSelectedChapterForMenu(null)
  }

  const handleDeleteChapter = async () => {
    if (!selectedChapterForMenu) return

    setDeletingChapter(true)
    try {
      await apiClient.deleteChapter(selectedChapterForMenu.id, {
        delete_reason: deleteChapterReason || undefined,
        delete_files: deleteChapterFiles,
      })

      // 从章节列表中移除已删除的章节
      setChapters((prev) => prev.filter((c) => c.id !== selectedChapterForMenu.id))
      setSelectedChapters((prev) => prev.filter((id) => id !== selectedChapterForMenu.id))

      setSnackbar({
        open: true,
        message: '章节已删除',
        severity: 'success',
      })
      handleCloseDeleteChapterDialog()
    } catch (error: any) {
      const msg = await extractApiErrorMessage(error, '删除章节失败')
      setSnackbar({
        open: true,
        message: msg,
        severity: 'error',
      })
    } finally {
      setDeletingChapter(false)
    }
  }

  useEffect(() => {
    if (!sessionHydratedRef.current) {
      return
    }

    if (!selectedProjectId && !currentAudiobookProjectId && !currentTaskId) {
      localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
      lastSessionTimestampRef.current = 0
      return
    }

    const comparablePayload = buildComparableAudiobookSessionPayload({
      projectId: selectedProjectId,
      audiobookProjectId: currentAudiobookProjectId,
      taskId: currentTaskId,
      activeTasks: persistedActiveTaskRefs,
      selectedChapterIds: selectedChapters,
      activeStep,
      generating,
      ttsModel,
    })
    let comparableStoredPayload: string | null = null
    const currentStoredPayload = localStorage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)

    if (currentStoredPayload) {
      try {
        comparableStoredPayload = JSON.stringify(
          buildComparableAudiobookSessionPayload(JSON.parse(currentStoredPayload) as AudiobookSessionState),
        )
      } catch {
        comparableStoredPayload = null
      }
    }

    const serializedComparablePayload = JSON.stringify(comparablePayload)
    if (comparableStoredPayload === serializedComparablePayload) {
      return
    }

    const updatedAt = new Date().toISOString()
    const payload: AudiobookSessionState = {
      ...comparablePayload,
      updatedAt,
      writerTabId: sessionTabIdRef.current,
    }

    localStorage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, JSON.stringify(payload))
    lastSessionTimestampRef.current = parseSessionTimestamp(updatedAt)
  }, [
    selectedProjectId,
    currentAudiobookProjectId,
    currentTaskId,
    persistedActiveTaskRefs,
    selectedChapters,
    activeStep,
    generating,
    ttsModel,
  ])

  useEffect(() => {
    if (typeof window === 'undefined' || !sessionHydratedRef.current || !selectedProjectId) {
      return
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== AUDIOBOOK_SESSION_STORAGE_KEY || !event.newValue) {
        return
      }

      try {
        const incomingSession = JSON.parse(event.newValue) as AudiobookSessionState
        if (incomingSession.projectId !== selectedProjectId) {
          return
        }
        if (incomingSession.writerTabId && incomingSession.writerTabId === sessionTabIdRef.current) {
          return
        }

        const incomingSessionTimestamp = parseSessionTimestamp(incomingSession.updatedAt)
        if (incomingSessionTimestamp > 0 && incomingSessionTimestamp < lastSessionTimestampRef.current) {
          return
        }

        const incomingActiveTasks = dedupeSessionTaskRefs(incomingSession.activeTasks)
        const incomingTaskId = incomingSession.taskId
          || incomingActiveTasks[0]?.taskId
          || null
        const incomingAudiobookProjectId = incomingSession.audiobookProjectId
          || incomingActiveTasks.find((item) => item.taskId === incomingTaskId)?.audiobookProjectId
          || incomingActiveTasks[0]?.audiobookProjectId
          || null
        const normalizedChapterIds = normalizeSelectedChapterIds(incomingSession.selectedChapterIds, {
          allowedIds: chapters.map((chapter) => chapter.id),
          fallbackIds: chapters.map((chapter) => chapter.id),
        })
        const incomingTtsModel = normalizeTtsModelValue(incomingSession.ttsModel)

        if (incomingTtsModel && incomingTtsModel !== ttsModelRef.current) {
          setTtsModel(incomingTtsModel)
        }

        if (Array.isArray(incomingSession.selectedChapterIds)) {
          setSelectedChapters((prev) => {
            const sameLength = prev.length === normalizedChapterIds.length
            const sameItems = sameLength && prev.every((chapterId, index) => chapterId === normalizedChapterIds[index])
            return sameItems ? prev : normalizedChapterIds
          })
        }

        if (typeof incomingSession.activeStep === 'number') {
          setActiveStep(incomingSession.activeStep)
        }

        if (incomingActiveTasks.length > 0) {
          setTaskStatuses((prev) => {
            const next = { ...prev }
            for (const taskRef of incomingActiveTasks) {
              if (!next[taskRef.taskId]) {
                next[taskRef.taskId] = buildPendingTaskStatus({
                  taskId: taskRef.taskId,
                  audiobookProjectId: taskRef.audiobookProjectId,
                })
              }
            }
            return next
          })
        }

        setCurrentTaskId((prev) => prev === incomingTaskId ? prev : incomingTaskId)
        setCurrentAudiobookProjectId((prev) =>
          prev === incomingAudiobookProjectId ? prev : incomingAudiobookProjectId
        )
        setGenerating(
          incomingTaskId || incomingActiveTasks.length > 0
            ? (incomingSession.generating ?? true)
            : false,
        )
        if (incomingSessionTimestamp > 0) {
          lastSessionTimestampRef.current = incomingSessionTimestamp
        }

        if (
          incomingAudiobookProjectId
          && incomingAudiobookProjectId !== audiobookProject?.id
        ) {
          void refreshAudiobookProjectDetail(incomingAudiobookProjectId)
        }
      } catch {
        // 忽略其它标签页同步的无效会话数据
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener('storage', handleStorage)
    }
  }, [selectedProjectId, chapters, audiobookProject?.id, refreshAudiobookProjectDetail])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
    ) {
      return
    }

    if (restoredPageSessionProjectRef.current === routeProjectId) {
      return
    }

    const raw = sessionStorage.getItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
    if (!raw) {
      restoredPageSessionProjectRef.current = routeProjectId
      return
    }

    let savedPageSession: AudiobookPageSessionState | null = null
    try {
      savedPageSession = normalizeAudiobookPageSessionState(
        JSON.parse(raw) as AudiobookPageSessionState,
      )
    } catch {
      sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
      restoredPageSessionProjectRef.current = routeProjectId
      return
    }

    if (!savedPageSession || savedPageSession.projectId !== routeProjectId) {
      sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
      restoredPageSessionProjectRef.current = routeProjectId
      return
    }

    const shouldRestoreRouteScopedPageSession = Boolean(
      savedPageSession.showHistory
      || savedPageSession.scriptOnlyMode
      || savedPageSession.narrationStyle !== DEFAULT_NARRATION_STYLE
      || savedPageSession.cloneRecordDialogOpen
      || savedPageSession.cloneName
      || savedPageSession.cloneUrl
      || savedPageSession.designName
      || savedPageSession.designPrompt
      || hasCustomDesignPreviewText(savedPageSession.designPreviewText)
      || savedPageSession.newProjectDialogOpen
      || savedPageSession.newProjectTitle
      || savedPageSession.newProjectText,
    )
    if (shouldRestoreRouteScopedPageSession) {
      skipNextPageSessionPersistRef.current = true
    }

    setShowHistory(Boolean(savedPageSession.showHistory))
    setScriptOnlyMode(Boolean(savedPageSession.scriptOnlyMode))
    setNarrationStyle(normalizeNarrationStyleValue(savedPageSession.narrationStyle))
    setCloneRecordDialogOpen(Boolean(savedPageSession.cloneRecordDialogOpen))
    setCloneName(savedPageSession.cloneName || '')
    setCloneUrl(savedPageSession.cloneUrl || '')
    setDesignName(savedPageSession.designName || '')
    setDesignPrompt(savedPageSession.designPrompt || '')
    setDesignPreviewText(resolveDesignPreviewTextDraft(savedPageSession.designPreviewText))
    setNewProjectDialogOpen(Boolean(savedPageSession.newProjectDialogOpen))
    setNewProjectTitle(savedPageSession.newProjectTitle || '')
    setNewProjectText(savedPageSession.newProjectText || '')
    restoredPageSessionProjectRef.current = routeProjectId
  }, [routeProjectId, selectedProjectId])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
      || !audiobookProject?.id
    ) {
      return
    }

    const restoreKey = `${routeProjectId}:${audiobookProject.id}`
    if (restoredProjectBoundPageSessionKeyRef.current === restoreKey) {
      return
    }

    const raw = sessionStorage.getItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
    if (!raw) {
      restoredProjectBoundPageSessionKeyRef.current = restoreKey
      return
    }

    let savedPageSession: AudiobookPageSessionState | null = null
    try {
      savedPageSession = normalizeAudiobookPageSessionState(
        JSON.parse(raw) as AudiobookPageSessionState,
      )
    } catch {
      sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
      restoredProjectBoundPageSessionKeyRef.current = restoreKey
      return
    }

    if (
      !savedPageSession
      || savedPageSession.projectId !== routeProjectId
      || (
        savedPageSession.audiobookProjectId
        && savedPageSession.audiobookProjectId !== audiobookProject.id
      )
    ) {
      restoredProjectBoundPageSessionKeyRef.current = restoreKey
      return
    }

    const shouldRestoreDeleteChapterDialog = Boolean(
      savedPageSession.deleteChapterDialogOpen && savedPageSession.deleteChapterTarget,
    )
    const shouldRestoreProjectBoundPageSession = Boolean(
      (savedPageSession.scriptReviewDialogOpen && savedPageSession.scriptReviewData)
      || (savedPageSession.stageMetricsDialogOpen && savedPageSession.stageMetricsData)
      || savedPageSession.browserPlayerOpen
      || shouldRestoreDeleteChapterDialog,
    )
    if (shouldRestoreProjectBoundPageSession) {
      skipNextPageSessionPersistRef.current = true
    }

    if (savedPageSession.scriptReviewDialogOpen && savedPageSession.scriptReviewData) {
      setScriptReviewData(savedPageSession.scriptReviewData)
      setScriptReviewDialogOpen(true)
    }

    if (savedPageSession.stageMetricsDialogOpen && savedPageSession.stageMetricsData) {
      const stage = STAGE_CONFIG.find((item) => item.key === savedPageSession.stageMetricsData?.stageKey)
      if (stage) {
        setStageMetricsData({
          stage,
          info: savedPageSession.stageMetricsData.info,
        })
        setStageMetricsDialogOpen(true)
      }
    }

    if (savedPageSession.browserPlayerOpen && !browserPlayerOpen) {
      void handleOpenBrowserPlayer()
    }

    if (shouldRestoreDeleteChapterDialog && savedPageSession.deleteChapterTarget) {
      const targetChapter = chapters.find((chapter) => chapter.id === savedPageSession.deleteChapterTarget?.id)
      setSelectedChapterForMenu(
        targetChapter ?? {
          id: savedPageSession.deleteChapterTarget.id,
          chapter_number: savedPageSession.deleteChapterTarget.chapterNumber,
          title: savedPageSession.deleteChapterTarget.title,
          content: savedPageSession.deleteChapterTarget.contentPreview,
        },
      )
      setDeleteChapterReason(savedPageSession.deleteChapterReason || '')
      setDeleteChapterFiles(Boolean(savedPageSession.deleteChapterFiles))
      setDeleteChapterDialogOpen(true)
    }

    restoredProjectBoundPageSessionKeyRef.current = restoreKey
  }, [routeProjectId, audiobookProject?.id, chapters, browserPlayerOpen, handleOpenBrowserPlayer])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProject?.id
    ) {
      return
    }

    const restoreKey = `${selectedProjectId}:${audiobookProject.id}`
    if (restoredEditorSessionKeyRef.current === restoreKey) {
      return
    }
    restoredEditorSessionKeyRef.current = restoreKey

    if (scriptEditorDialogOpen) {
      return
    }

    const raw = sessionStorage.getItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
    if (!raw) {
      return
    }

    let savedEditorSession: AudiobookEditorSessionState | null = null
    try {
      savedEditorSession = normalizeAudiobookEditorSessionState(
        JSON.parse(raw) as AudiobookEditorSessionState,
      )
    } catch {
      sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
      return
    }

    if (!savedEditorSession) {
      sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
      return
    }

    if (
      savedEditorSession.projectId !== selectedProjectId
      || savedEditorSession.audiobookProjectId !== audiobookProject.id
      || !savedEditorSession.chapterId
      || !savedEditorSession.data
    ) {
      return
    }

    const chapter = chapters.find((item) => item.id === savedEditorSession?.chapterId)
    setScriptEditorChapter(
      chapter
        ? {
            chapterId: savedEditorSession.chapterId,
            title: `第${chapter.chapter_number}章 - ${chapter.title}`,
          }
        : {
            chapterId: savedEditorSession.chapterId,
            title: `章节 ${savedEditorSession.chapterId}`,
          },
    )
    setScriptEditorData(savedEditorSession.data)
    setReviewMode(Boolean(savedEditorSession.reviewMode))
    setSegmentReviews(savedEditorSession.segmentReviews || {})
    setSegmentDetailsOpen(
      buildSegmentDetailsOpenState(savedEditorSession.openSegmentDetailIndices || []),
    )
    setScriptEditorLoading(false)
    setScriptEditorDialogOpen(true)
  }, [selectedProjectId, audiobookProject?.id, chapters, scriptEditorDialogOpen])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !routeProjectId
    ) {
      return
    }

    if (skipNextPageSessionPersistRef.current) {
      skipNextPageSessionPersistRef.current = false
      return
    }

    const comparablePayload = buildComparableAudiobookPageSessionPayload({
      projectId: routeProjectId,
      audiobookProjectId: currentAudiobookProjectId ?? audiobookProject?.id,
      browserPlayerOpen,
      showHistory,
      scriptOnlyMode,
      narrationStyle,
      scriptReviewDialogOpen,
      scriptReviewData,
      stageMetricsDialogOpen,
      stageMetricsData: stageMetricsData
        ? {
            stageKey: stageMetricsData.stage.key,
            info: stageMetricsData.info,
          }
        : null,
      deleteChapterDialogOpen,
      deleteChapterTarget: buildDeleteChapterSessionTarget(selectedChapterForMenu),
      deleteChapterReason,
      deleteChapterFiles,
      cloneRecordDialogOpen,
      cloneName,
      cloneUrl,
      designName,
      designPrompt,
      designPreviewText,
      newProjectDialogOpen,
      newProjectTitle,
      newProjectText,
    })

    if (!hasPersistableAudiobookPageSession(comparablePayload)) {
      sessionStorage.removeItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
      return
    }

    let comparableStoredPayload: string | null = null
    const currentStoredPayload = sessionStorage.getItem(AUDIOBOOK_PAGE_SESSION_STORAGE_KEY)
    if (currentStoredPayload) {
      try {
        comparableStoredPayload = JSON.stringify(
          buildComparableAudiobookPageSessionPayload(
            JSON.parse(currentStoredPayload) as AudiobookPageSessionState,
          ),
        )
      } catch {
        comparableStoredPayload = null
      }
    }

    const serializedComparablePayload = JSON.stringify(comparablePayload)
    if (comparableStoredPayload === serializedComparablePayload) {
      return
    }

    try {
      sessionStorage.setItem(
        AUDIOBOOK_PAGE_SESSION_STORAGE_KEY,
        JSON.stringify({
          ...comparablePayload,
          updatedAt: new Date().toISOString(),
        } satisfies AudiobookPageSessionState),
      )
    } catch {
      // sessionStorage 不可用或容量不足时忽略页面级 UI 状态持久化
    }
  }, [
    routeProjectId,
    currentAudiobookProjectId,
    audiobookProject?.id,
    browserPlayerOpen,
    showHistory,
    scriptOnlyMode,
    narrationStyle,
    scriptReviewDialogOpen,
    scriptReviewData,
    stageMetricsDialogOpen,
    stageMetricsData,
    deleteChapterDialogOpen,
    selectedChapterForMenu,
    deleteChapterReason,
    deleteChapterFiles,
    cloneRecordDialogOpen,
    cloneName,
    cloneUrl,
    designName,
    designPrompt,
    designPreviewText,
    newProjectDialogOpen,
    newProjectTitle,
    newProjectText,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProject?.id
    ) {
      return
    }

    const restoreKey = `${selectedProjectId}:${audiobookProject.id}`
    if (restoredEditorSessionKeyRef.current !== restoreKey) {
      return
    }

    if (!scriptEditorDialogOpen || !scriptEditorChapter || !scriptEditorData) {
      sessionStorage.removeItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
      removeCurrentEditorSyncEntry()
      return
    }

    const comparablePayload = buildComparableAudiobookEditorSessionPayload({
      projectId: selectedProjectId,
      audiobookProjectId: audiobookProject.id,
      chapterId: scriptEditorChapter.chapterId,
      reviewMode,
      openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
      segmentReviews,
      data: scriptEditorData,
    })

    let comparableStoredPayload: string | null = null
    const currentStoredPayload = sessionStorage.getItem(AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY)
    if (currentStoredPayload) {
      try {
        comparableStoredPayload = JSON.stringify(
          buildComparableAudiobookEditorSessionPayload(
            JSON.parse(currentStoredPayload) as AudiobookEditorSessionState,
          ),
        )
      } catch {
        comparableStoredPayload = null
      }
    }

    const serializedComparablePayload = JSON.stringify(comparablePayload)
    const updatedAt = new Date().toISOString()

    if (comparableStoredPayload !== serializedComparablePayload) {
      try {
        sessionStorage.setItem(
          AUDIOBOOK_EDITOR_SESSION_STORAGE_KEY,
          JSON.stringify({
            ...comparablePayload,
            updatedAt,
          } satisfies AudiobookEditorSessionState),
        )
      } catch {
        // sessionStorage 不可用或容量不足时忽略编辑器草稿持久化
      }
    }

    upsertCurrentEditorSyncEntry()
  }, [
    selectedProjectId,
    audiobookProject?.id,
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    removeCurrentEditorSyncEntry,
    upsertCurrentEditorSyncEntry,
  ])

  useEffect(() => {
    if (
      typeof window === 'undefined'
      || !sessionHydratedRef.current
      || !selectedProjectId
      || !audiobookProject?.id
      || !scriptEditorDialogOpen
      || !scriptEditorChapter
      || !scriptEditorData
    ) {
      setEditorCrossTabConflict(null)
      dismissedEditorConflictSignatureRef.current = null
      return
    }

    const evaluateIncomingEditorDraft = (rawRegistry: string | null) => {
      const currentEntries = readEditorSyncEntries(rawRegistry)
      const incomingEntry = Object.values(currentEntries)
        .filter((entry) => entry.writerTabId && entry.writerTabId !== sessionTabIdRef.current)
        .filter((entry) => entry.projectId === selectedProjectId)
        .filter((entry) => entry.audiobookProjectId === audiobookProject.id)
        .filter((entry) => entry.chapterId === scriptEditorChapter.chapterId)
        .sort((left, right) => parseSessionTimestamp(right.updatedAt) - parseSessionTimestamp(left.updatedAt))[0] || null

      if (!incomingEntry) {
        setEditorCrossTabConflict(null)
        dismissedEditorConflictSignatureRef.current = null
        return
      }

      const localComparablePayload = buildComparableAudiobookEditorSessionPayload({
        projectId: selectedProjectId,
        audiobookProjectId: audiobookProject.id,
        chapterId: scriptEditorChapter.chapterId,
        reviewMode,
        openSegmentDetailIndices: extractOpenSegmentDetailIndices(segmentDetailsOpen),
        segmentReviews,
        data: scriptEditorData,
      })
      const incomingComparablePayload = buildComparableAudiobookEditorSessionPayload(incomingEntry)

      if (JSON.stringify(localComparablePayload) === JSON.stringify(incomingComparablePayload)) {
        setEditorCrossTabConflict(null)
        dismissedEditorConflictSignatureRef.current = null
        return
      }

      const incomingSignature = buildAudiobookEditorConflictSignature(incomingEntry)
      if (incomingSignature && dismissedEditorConflictSignatureRef.current === incomingSignature) {
        return
      }

      setEditorCrossTabConflict(incomingEntry)
    }

    try {
      evaluateIncomingEditorDraft(localStorage.getItem(AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY))
    } catch {
      setEditorCrossTabConflict(null)
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== AUDIOBOOK_EDITOR_SYNC_STORAGE_KEY) {
        return
      }
      try {
        evaluateIncomingEditorDraft(event.newValue)
      } catch {
        // 忽略其它标签页广播的无效编辑器草稿同步数据
      }
    }

    window.addEventListener('storage', handleStorage)
    return () => {
      window.removeEventListener('storage', handleStorage)
    }
  }, [
    selectedProjectId,
    audiobookProject?.id,
    scriptEditorDialogOpen,
    scriptEditorChapter,
    scriptEditorData,
    reviewMode,
    segmentDetailsOpen,
    segmentReviews,
    readEditorSyncEntries,
  ])

  // 切换章节选择
  const handleToggleChapter = (chapterId: number) => {
    setSelectedChapters(prev => 
      prev.includes(chapterId) 
        ? prev.filter(id => id !== chapterId)
        : [...prev, chapterId]
    )
  }

  // 全选/取消全选
  const handleToggleAll = () => {
    if (selectedChapters.length === chapters.length) {
      setSelectedChapters([])
    } else {
      setSelectedChapters(chapters.map(c => c.id))
    }
  }
  
  const handleVoiceChange = (characterId: number, voiceId: string) => {
    const preset = voicePresets.find((p) => p.id === voiceId)
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => {
        if (item.characterId !== characterId) return item
        const next = { ...item, voiceId }
        if (!item.voiceId && preset?.default_params) {
          next.volume = preset.default_params.volume ?? next.volume
          next.speed = preset.default_params.speed ?? next.speed
          next.pitch = preset.default_params.pitch ?? next.pitch
        }
        return next
      }),
    )
  }

  const handleVolumeChange = (characterId: number, volume: number) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, volume } : item)),
    )
  }

  const handleSpeedChange = (characterId: number, speed: number) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, speed } : item)),
    )
  }

  const handlePitchChange = (characterId: number, pitch: number) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, pitch } : item)),
    )
  }

  const handleTtsModelChangeForCharacter = (characterId: number, nextModel: TtsModel | 'inherit') => {
    if (nextModel === 'inherit') {
      updateCharacterVoicesForCurrentModel((prev) =>
        prev.map((item) =>
          item.characterId === characterId
            ? { ...item, ttsModel: undefined }
            : item,
        ),
      )
      return
    }

    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) =>
        item.characterId === characterId
          ? { ...item, ttsModel: nextModel }
          : item,
      ),
    )
    setTtsModel(nextModel)
  }

  const handleVoiceTypeChange = (characterId: number, voiceType: string) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, voiceType: voiceType || undefined } : item)),
    )
  }

  const handlePersonalityChange = (characterId: number, personality: string) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, personality: personality || undefined } : item)),
    )
  }

  const handleEmotionTendencyChange = (characterId: number, emotionTendency: string) => {
    updateCharacterVoicesForCurrentModel((prev) =>
      prev.map((item) => (item.characterId === characterId ? { ...item, emotionTendency: emotionTendency || undefined } : item)),
    )
  }

  // 基于人物卡自动推荐声线
  const handleAutoAssignVoices = async () => {
    if (!selectedProject) return

    try {
      setAutoAssigningVoices(true)
      const res = await apiClient.autoAssignProjectAudioVoices(selectedProject.id, ttsModel)
      const configData = (res.data || { characters: [] }) as {
        characters?: {
          character_id: number
          name: string
          voice_id: string
          volume: number
          speed?: number | null
          pitch?: number | null
        }[]
      }

      const configById = new Map<
        number,
        { voice_id: string; volume: number; speed?: number | null; pitch?: number | null }
      >()
      for (const item of configData.characters || []) {
        configById.set(item.character_id, {
          voice_id: normalizeVoiceId(ttsModel, item.voice_id),
          volume: item.volume,
          speed: item.speed ?? undefined,
          pitch: item.pitch ?? undefined,
        })
      }

      updateCharacterVoicesForCurrentModel((prev) =>
        prev.map((cv) => {
          const conf = configById.get(cv.characterId)
          if (!conf) return cv
          return {
            ...cv,
            voiceId: conf.voice_id || '',
            volume: conf.volume ?? cv.volume,
            speed: conf.speed ?? cv.speed,
            pitch: conf.pitch ?? cv.pitch,
          }
        }),
      )

      const assignedCount = configById.size
      if (assignedCount > 0) {
        setSnackbar({
          open: true,
          message: `? 已为 ${assignedCount} 个角色智能推荐声线！请检查推荐结果，如需调整可手动修改。`,
          severity: 'success',
        })
      } else {
        setSnackbar({
          open: true,
          message: '当前项目还没有角色档案，请先在「项目详情 → 人物设定」中创建角色。',
          severity: 'warning',
        })
      }
    } catch {
      setSnackbar({
        open: true,
        message: '自动推荐声线失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setAutoAssigningVoices(false)
    }
  }

  const handlePreviewCharacterVoice = async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId) {
      setSnackbar({ open: true, message: '请先为该角色选择音色再试听', severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const text = '当你真的喜欢一个人的时候就容易说傻话办蠢事。'

      // 优先使用角色选择的模型，否则使用全局模型
      const modelForPreview = cv.ttsModel || ttsModel

      const res = await apiClient.previewTTS({
        text,
        voice_id: cv.voiceId,
        volume: cv.volume,
        speed: cv.speed,
        pitch: cv.pitch,
        model: modelForPreview,
      })

      const blob = res.data as Blob
      const url = window.URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.play()
      audio.onended = () => {
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      setSnackbar({ open: true, message: await extractApiErrorMessage(error, '角色音试听失败，请稍后重试'), severity: 'error' })
    } finally {
      setPreviewingCharacterId(null)
    }
  }

  // 新增：下载音频
  const handleDownloadAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      const { blob, filename } = await fetchChapterAudioFile(chapterId)
      
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)

      setSnackbar({ open: true, message: '音频下载成功', severity: 'success' })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '下载失败，请重试'),
        severity: 'error',
      })
    }
  }

  const handleCollectChapterAudio = async (chapterAudio: {
    id: number
    chapter_id: number
    chapter_number?: number | null
    audio_path?: string | null
  }) => {
    if (!audiobookProject) return

    setCollectingChapterId(chapterAudio.chapter_id)

    try {
      const { blob, filename, downloadUrl } = await fetchChapterAudioFile(chapterAudio.chapter_id)
      const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
      const rawProjectId = selectedProject?.id ?? audiobookProject.project_id ?? routeProjectId
      const projectId = Number(rawProjectId)
      const normalizedProjectId = Number.isFinite(projectId) && projectId > 0 ? projectId : null
      const chapterNumber = chapter?.chapter_number ?? chapterAudio.chapter_number ?? null
      const chapterTitle = chapter?.title?.trim() || null
      const projectTitle = selectedProject?.title?.trim() || null
      const assetUuid = buildAudiobookChapterAssetUuid(audiobookProject.id, chapterAudio.chapter_id)
      const title = chapterNumber
        ? `第${chapterNumber}章${chapterTitle ? ` - ${chapterTitle}` : ''} 有声书音频`
        : `${chapterTitle || `章节 ${chapterAudio.chapter_id}`} 有声书音频`
      const mimeType = blob.type || 'audio/mpeg'
      const assetMetadata = {
        audiobook_project_id: audiobookProject.id,
        chapter_id: chapterAudio.chapter_id,
        chapter_audio_id: chapterAudio.id,
        project_id: normalizedProjectId,
        project_title: projectTitle,
        chapter_title: chapterTitle,
        chapter_number: chapterNumber,
        filename,
        audio_path: chapterAudio.audio_path || null,
      }

      const {
        localAssetRecord,
        didFallbackToBrowserStorage,
      } = await saveExplicitLocalUserAsset({
        assetUuid,
        mediaKind: 'audio',
        blob,
        mimeType,
        fileSize: blob.size,
        sourceModule: 'audiobook',
        title,
        sourceUri: downloadUrl,
        previewUri: downloadUrl,
        downloadUri: downloadUrl,
        metadata: assetMetadata,
      })

      await apiClient.createUserAsset({
        project_id: normalizedProjectId,
        source_module: 'audiobook',
        asset_kind: 'audio',
        asset_class: 'deliverable',
        asset_uuid: assetUuid,
        storage_mode: 'local_mirror',
        title,
        description: 'Audiobook 章节成品音频',
        source_uri: downloadUrl,
        preview_uri: downloadUrl,
        download_uri: downloadUrl,
        mime_type: mimeType,
        file_size: blob.size,
        generation_mode: 'chapter_audio',
        tags: ['audiobook', 'deliverable', 'chapter-audio'],
        metadata_json: buildAudiobookChapterAudioAssetMetadataContract(
          assetMetadata,
          extractLocalAssetStorageMetadata(localAssetRecord),
        ),
        source_payload_json: buildAudiobookChapterAudioSourcePayload(assetMetadata),
      })

      setSnackbar({
        open: true,
        message: didFallbackToBrowserStorage
          ? '章节音频已收录到用户资产，但用户目录当前不可用，文件已回退保存到浏览器本地存储'
          : '章节音频已收录到用户资产',
        severity: 'success',
      })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '收录章节音频失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setCollectingChapterId(null)
    }
  }
  
  // 新增：在线播放音频
  const handlePlayAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      // 如果当前正在播放同一章节，则暂停
      if (playingChapter === chapterId) {
        audioRef.pause()
        setPlayingChapter(null)
        return
      }
      
      // 暂停当前播放
      audioRef.pause()

      if (playingAudioUrlRef.current) {
        window.URL.revokeObjectURL(playingAudioUrlRef.current)
        playingAudioUrlRef.current = null
      }

      const assetUuid = buildAudiobookChapterAssetUuid(audiobookProject.id, chapterId)
      const localBlob = await getLocalAssetBlob(assetUuid)
      const blob = localBlob || (await fetchChapterAudioFile(chapterId)).blob
      const blobUrl = window.URL.createObjectURL(blob)
      playingAudioUrlRef.current = blobUrl
      
      // 设置新的音频源
      audioRef.src = blobUrl
      
      // 播放
      await audioRef.play()
      setPlayingChapter(chapterId)
      
      // 播放结束后重置状态并释放 Blob URL
      audioRef.onended = () => {
        setPlayingChapter(null)
        if (playingAudioUrlRef.current) {
          window.URL.revokeObjectURL(playingAudioUrlRef.current)
          playingAudioUrlRef.current = null
        }
      }
      
        setSnackbar({ open: true, message: '开始播放', severity: 'success' })
    } catch {
      setSnackbar({ open: true, message: '播放失败，请重试', severity: 'error' })
      setPlayingChapter(null)
    }
  }

  const handleOpenScriptReviewDialog = () => {
    const taskStatus = activeTaskStatus
    if (!taskStatus) {
      setSnackbar({ open: true, message: '暂未获取到任务状态', severity: 'error' })
      return
    }
    const stage = taskStatus.stages['quality_review']
    if (!stage || !stage.metrics) {
      setSnackbar({ open: true, message: '暂未获取到剧本评审结果', severity: 'error' })
      return
    }
    const metrics = stage.metrics
    const report = normalizeScriptReview({
      overall_score: metrics.overall_score,
      overall_grade: metrics.overall_grade,
      issues_count: metrics.issues_count,
      script_quality: metrics.script_quality,
      audio_balance: metrics.audio_balance,
      pacing: metrics.pacing,
      revision_suggestions: metrics.revision_suggestions,
      issues: metrics.issues,
    })
    if (!report) {
      setSnackbar({ open: true, message: '暂未获取到完整的评审详情', severity: 'error' })
      return
    }
    const segments = metrics.sample_segments || []
    setScriptReviewData({ report, segments })
    setScriptReviewDialogOpen(true)
  }

  const handleCloseScriptReviewDialog = () => {
    setScriptReviewDialogOpen(false)
    setScriptReviewData(null)
  }

  const handleOpenStageMetricsDialog = (stage: StageConfig, stageInfo: StageInfo) => {
    const metrics = stageInfo.metrics
    if (!metrics || Object.keys(metrics).length === 0) {
      setSnackbar({ open: true, message: '该阶段暂无可查看的结果数据', severity: 'info' })
      return
    }
    setStageMetricsData({ stage, info: stageInfo })
    setStageMetricsDialogOpen(true)
  }

  const handleCloseStageMetricsDialog = () => {
    setStageMetricsDialogOpen(false)
    setStageMetricsData(null)
  }

  const resetSegmentPreviewState = useCallback(() => {
    Object.values(segmentAudioUrls).forEach((url) => {
      if (url) {
        window.URL.revokeObjectURL(url)
      }
    })
    setSegmentAudioUrls({})
    setSegmentPreviewingIndex(null)
    setSegmentPreviewingType(null)
    setSegmentDetailsOpen({})
  }, [segmentAudioUrls])

  const handleToggleSegmentDetails = (index: number) => {
    setSegmentDetailsOpen((prev) => ({ ...prev, [index]: !prev[index] }))
  }

  const handlePreviewScriptSegmentAudio = async (
    index: number,
    segment: any,
    previewType: PreviewType,
  ) => {
    if (!audiobookProject || !scriptEditorChapter) return
    const textValue = String(segment?.text || '').trim()
    if (!textValue) {
      setSnackbar({ open: true, message: '片段文本为空，无法生成音频', severity: 'warning' })
      return
    }

    setSegmentPreviewingIndex(index)
    setSegmentPreviewingType(previewType)
    try {
      if (playingChapter) {
        audioRef.pause()
        setPlayingChapter(null)
      }

      const response = await apiClient.previewScriptSegmentAudio(
        audiobookProject.id,
        scriptEditorChapter.chapterId,
        { segment, tts_model: ttsModel, preview_type: previewType }
      )
      const blob = response.data as Blob
      const url = window.URL.createObjectURL(blob)
      setSegmentAudioUrls((prev) => {
        const existing = prev[index]
        if (existing) {
          window.URL.revokeObjectURL(existing)
        }
        return { ...prev, [index]: url }
      })
      audioRef.src = url
      await audioRef.play()
      audioRef.onended = () => {
        setSegmentPreviewingIndex(null)
        setSegmentPreviewingType(null)
      }
      setSnackbar({ open: true, message: '片段音频已生成并开始播放', severity: 'success' })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error) || '生成片段音频失败，请重试',
        severity: 'error',
      })
    } finally {
      setSegmentPreviewingIndex(null)
      setSegmentPreviewingType(null)
    }
  }

  const handleToggleReviewMode = () => {
    setReviewMode(prev => !prev)
  }

  const handleReviewSegment = async (index: number, score: number) => {
    if (!audiobookProject || !scriptEditorChapter) return
    try {
      await apiClient.reviewSegment(audiobookProject.id, scriptEditorChapter.chapterId, index, { quality_score: score })
      setSegmentReviews(prev => ({ ...prev, [index]: { quality_score: score } }))
    } catch (error: any) {
      setSnackbar({ open: true, message: '保存评分失败', severity: 'error' })
    }
  }

  const handleRegenerateSegment = async (index: number, segment: any) => {
    if (!audiobookProject || !scriptEditorChapter) return
    setRegeneratingSegments(prev => new Set([...prev, index]))
    try {
      const voiceParams = segment.voice_params || {}
      await apiClient.regenerateSegment(audiobookProject.id, scriptEditorChapter.chapterId, index, {
        reason: '质量不满意',
        tts_model: ttsModel,
        voice_id: voiceParams.speaker,
        emotion: voiceParams.emotion,
      })
      setSnackbar({ open: true, message: `片段 #${index + 1} 重新生成成功`, severity: 'success' })
    } catch (error: any) {
      const msg = await extractApiErrorMessage(error)
      setSnackbar({ open: true, message: `重新生成失败: ${msg}`, severity: 'error' })
    } finally {
      setRegeneratingSegments(prev => { const next = new Set(prev); next.delete(index); return next })
    }
  }

  // 打开章节剧本编辑器
  const handleOpenScriptEditor = useCallback(async (chapterId: number) => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先创建有声书项目', severity: 'error' })
      return
    }

    const chapter = chapters.find((c) => c.id === chapterId)
    setScriptEditorChapter(
      chapter
        ? { chapterId, title: `第${chapter.chapter_number}章 - ${chapter.title}` }
        : { chapterId, title: `章节 ${chapterId}` }
    )

    try {
      resetSegmentPreviewState()
      setEditorCrossTabConflict(null)
      dismissedEditorConflictSignatureRef.current = null
      setReviewMode(false)
      setSegmentReviews({})
      setSegmentDetailsOpen({})
      setRegeneratingSegments(new Set())
      setScriptEditorLoading(true)

      const res = await apiClient.getAudiobookChapterScript(audiobookProject.id, chapterId)
      const data = res.data

      setScriptEditorData({
        scriptStatus: data.script_status || 'pending',
        scriptSegments: data.script_segments || [],
        scriptReview: normalizeScriptReview(data.script_review),
      })
      setScriptEditorDialogOpen(true)
    } catch (err: any) {
      setSnackbar({ open: true, message: err.message || '获取章节剧本失败', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }, [audiobookProject, chapters, resetSegmentPreviewState])

  useEffect(() => {
    const focusPlan = buildAudiobookSourceFocusPlan({
      selectedProjectId,
      requestedAudiobookProjectId,
      requestedSourceChapterId,
      requestedSourceFocus,
      loadedAudiobookProjectId: audiobookProject?.id ?? null,
      currentAudiobookProjectId,
      handledFocusKey: handledSourceChapterKeyRef.current,
    })
    if (!focusPlan) return

    let cancelled = false

    const focusSourceChapter = async () => {
      setActiveStep(2)
      setShowHistory(false)
      setBrowserPlayerOpen(false)
      setBrowserPlayerData(null)
      clearActiveGenerationState()
      setCurrentAudiobookProjectId(focusPlan.targetAudiobookProjectId)

      if (focusPlan.shouldRefreshProject) {
        try {
          await refreshAudiobookProjectDetail(focusPlan.targetAudiobookProjectId)
        } catch (error: unknown) {
          if (!cancelled) {
            handledSourceChapterKeyRef.current = focusPlan.focusKey
            setSnackbar({
              open: true,
              message: await extractApiErrorMessage(error, '加载有声书项目失败'),
              severity: 'error',
            })
          }
        }
        return
      }

      handledSourceChapterKeyRef.current = focusPlan.focusKey
      await handleOpenScriptEditor(focusPlan.chapterId)
    }

    void focusSourceChapter()

    return () => {
      cancelled = true
    }
  }, [
    audiobookProject?.id,
    clearActiveGenerationState,
    currentAudiobookProjectId,
    handleOpenScriptEditor,
    refreshAudiobookProjectDetail,
    requestedAudiobookProjectId,
    requestedSourceChapterId,
    requestedSourceFocus,
    selectedProjectId,
  ])

  const handleCloseScriptEditorDialog = () => {
    resetSegmentPreviewState()
    audioRef.pause()
    removeCurrentEditorSyncEntry()
    setScriptEditorDialogOpen(false)
    setScriptEditorData(null)
    setScriptEditorChapter(null)
    setEditorCrossTabConflict(null)
    dismissedEditorConflictSignatureRef.current = null
    setReviewMode(false)
    setSegmentReviews({})
    setSegmentDetailsOpen({})
    setRegeneratingSegments(new Set())
  }

  const handleApplyIncomingEditorDraft = () => {
    if (!editorCrossTabConflict?.data) {
      return
    }

    setScriptEditorData(editorCrossTabConflict.data)
    setReviewMode(Boolean(editorCrossTabConflict.reviewMode))
    setSegmentReviews(editorCrossTabConflict.segmentReviews || {})
    setSegmentDetailsOpen(
      buildSegmentDetailsOpenState(editorCrossTabConflict.openSegmentDetailIndices || []),
    )
    dismissedEditorConflictSignatureRef.current = null
    setEditorCrossTabConflict(null)
    setSnackbar({
      open: true,
      message: '已载入另一标签页的最新草稿',
      severity: 'info',
    })
  }

  const handleKeepLocalEditorDraft = () => {
    const conflictSignature = buildAudiobookEditorConflictSignature(editorCrossTabConflict)
    if (conflictSignature) {
      dismissedEditorConflictSignatureRef.current = conflictSignature
    }
    setEditorCrossTabConflict(null)
    setSnackbar({
      open: true,
      message: '已保留当前标签页草稿；如另一标签页继续修改，会再次提醒',
      severity: 'warning',
    })
  }

  const handleChangeScriptSegmentText = (index: number, value: string) => {
    setScriptEditorData((prev) => {
      if (!prev) return prev
      const segments = [...prev.scriptSegments]
      segments[index] = { ...segments[index], text: value }
      return { ...prev, scriptSegments: segments }
    })
  }

  const handleUpdateScriptSegment = (index: number, patch: Record<string, any>) => {
    setScriptEditorData((prev) => {
      if (!prev) return prev
      const segments = [...prev.scriptSegments]
      segments[index] = { ...segments[index], ...patch }
      return { ...prev, scriptSegments: segments }
    })
  }

  const handleSaveScript = async (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => {
    if (!audiobookProject || !scriptEditorChapter || !scriptEditorData) return
    if (options.generateAudio && !ensureCurrentTtsModelReady()) return

    try {
      setTaskPointsPrecheckError(null)
      resetSegmentPreviewState()
      setScriptEditorLoading(true)

      const payload: any = {
        script_segments: scriptEditorData.scriptSegments,
      }
      if (options.nextStatus) {
        payload.script_status = options.nextStatus
      }

      await apiClient.updateAudiobookChapterScript(
        audiobookProject.id,
        scriptEditorChapter.chapterId,
        payload
      )

      if (options.generateAudio) {
        const queueResponse = await apiClient.generateAudioFromScripts(audiobookProject.id, {
          chapter_ids: [scriptEditorChapter.chapterId],
          tts_model: ttsModel,
          narration_style: narrationStyle,
        })

        const queueData = queueResponse.data || {}
        if (!queueData?.job_id) {
          throw new Error('音频生成任务未返回 job_id')
        }

        await activateQueuedAudiobookTask(audiobookProject.id, queueData.job_id, {
          generationMode: 'full',
          successMessage: '剧本已保存，并已触发该章节音频生成',
        })
      } else {
        setSnackbar({ open: true, message: '剧本已保存', severity: 'success' })
      }

      // 保存后不自动关闭，方便继续修改；如需可在此关闭
      // handleCloseScriptEditorDialog()
    } catch (err: any) {
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
  }

  const handleGenerateAudioForApprovedChapters = async () => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先完成剧本生成', severity: 'error' })
      return
    }
    if (generating) {
      setSnackbar({ open: true, message: '当前已有任务在执行，请稍候', severity: 'warning' })
      return
    }
    if (!ensureCurrentTtsModelReady()) return

    try {
      setTaskPointsPrecheckError(null)
      const res = await apiClient.generateAudioFromScripts(audiobookProject.id, {
        tts_model: ttsModel,
        narration_style: narrationStyle,
      })

      const data = res.data || {}
      if (!data?.job_id) {
        throw new Error('触发音频生成失败')
      }

      await activateQueuedAudiobookTask(audiobookProject.id, data.job_id, {
        generationMode: 'full',
        successMessage: '已将已审批章节加入音频生成队列',
      })
    } catch (err: any) {
      const precheckDetail = await extractTaskPointsPrecheckErrorDetail(err)
      setTaskPointsPrecheckError(precheckDetail)
      const message = precheckDetail
        ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
        : await extractApiErrorMessage(err, '批量生成音频失败，请稍后重试')
      setSnackbar({
        open: true,
        message: message || '批量生成音频失败，请稍后重试',
        severity: 'error',
      })
    }
  }

  // 开始生成
  const handleGenerate = async () => {
    if (generating) return
    if (!ensureCurrentTtsModelReady()) return

    if (selectedChapters.length === 0) {
      setSnackbar({ open: true, message: '请至少选择一个章节', severity: 'error' })
      return
    }

    const projectIdForRequest = selectedProject?.id ?? routeProjectId
    if (!projectIdForRequest) {
      setSnackbar({ open: true, message: '项目尚未加载完成，请稍后重试', severity: 'error' })
      return
    }
    
    setTaskPointsPrecheckError(null)
    setGenerating(true)
    setActiveStep(1)
    setLastGenerationMode(scriptOnlyMode ? 'script_only' : 'full')

    try {
      // 调用生成API
      // 先保存本次的项目级音频配置（角色音 + 音效/BGM），用于下次自动带出
      if (projectIdForRequest) {
        const projectAudioConfigBody: ProjectAudioConfig = {
          characters: characterVoices
            .filter((cv) => cv.voiceId || cv.name === '旁白')  // 修复：旁白即使 voiceId 为空也保留，让后端使用默认音色
            .map((cv) => ({
              character_id: cv.characterId,
              name: cv.name,
              voice_id: cv.voiceId || getFallbackVoiceId(ttsModel, currentVoicePresets),
              volume: cv.volume,
              speed: cv.speed,
              pitch: cv.pitch,
              tts_model: cv.ttsModel || ttsModel,  // 🆕 保存tts_model
              voice_type: cv.voiceType || undefined,  // 🆕 保存声音类型
              personality: cv.personality || undefined,  // 🆕 保存性格类型
              emotion_tendency: cv.emotionTendency || undefined,  // 🆕 保存情感倾向
            })),
          audio_fx: audioFxConfig,
        }

        try {
          await apiClient.updateProjectAudioConfig(projectIdForRequest, projectAudioConfigBody, ttsModel)
        } catch {
          // 保存项目音频配置失败
        }
      }

      const voiceConfigPayload =
        characterVoices
          .filter((cv) => cv.voiceId || cv.name === '旁白')  // 修复：旁白即使 voiceId 为空也保留
          .map((cv) => ({
            character_name: cv.name,
            voice_id: cv.voiceId || getFallbackVoiceId(ttsModel, currentVoicePresets),
            volume: cv.volume,
            speed: cv.speed,
            pitch: cv.pitch,
          }))

      const response = await apiClient.createAudiobookProject({
        project_id: projectIdForRequest,
        chapter_ids: selectedChapters,
        tts_provider: 'aliyun',
        enable_cache: true,
        voice_config: voiceConfigPayload,
        tts_model: ttsModel,
        generation_mode: scriptOnlyMode ? 'script_only' : 'full',
        narration_style: narrationStyle,
      })

      const data = response.data
      if (data?.audiobook_project_id) {
        setCurrentAudiobookProjectId(data.audiobook_project_id)
      }
      if (data?.job_id) {
        setCurrentTaskId(data.job_id)
        if (data?.audiobook_project_id) {
          setTaskStatuses((prev) => ({
            ...prev,
            [data.job_id]: buildPendingTaskStatus({
              taskId: data.job_id,
              audiobookProjectId: data.audiobook_project_id,
              taskType: scriptOnlyMode ? 'script_only' : 'full',
            }),
          }))
        }
      }
      // 不立即设置audiobookProject，因为createAudiobookProject返回的数据不包含chapter_audios
      // 等待轮询获取完整数据后再设置
      // setAudiobookProject(data)

      // 轮询查询项目进度
      const projectId = data.audiobook_project_id
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await apiClient.getAudiobookProject(projectId)
          const statusData = statusResponse.data

          // 首次获取到完整数据时设置audiobookProject
          if (!audiobookProject && statusData) {
            setAudiobookProject(statusData)
          }

          if (statusData.status === 'completed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setActiveStep(2)
            setAudiobookProject(statusData)
            setSnackbar({ open: true, message: '生成完成！', severity: 'success' })
          } else if (statusData.status === 'failed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setSnackbar({ open: true, message: '生成失败，请重试', severity: 'error' })
            setActiveStep(0)
          }
        } catch {
          // 轮询有声书项目状态失败
        }
      }, 2000) // 每2秒查询一次
    } catch (error: any) {
      const precheckDetail = await extractTaskPointsPrecheckErrorDetail(error)
      setTaskPointsPrecheckError(precheckDetail)
      const message = precheckDetail
        ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
        : await extractApiErrorMessage(error, '生成失败，请重试')
      setSnackbar({ 
        open: true, 
        message: message || '生成失败，请重试', 
        severity: 'error' 
      })
      setGenerating(false)
      setActiveStep(0)
    }
  }
  
  const handleResumeChapterGeneration = async (chapterId: number) => {
    if (!audiobookProject?.id) {
      return
    }
    if (generating) {
      setSnackbar({ open: true, message: '当前已有任务在执行，请稍候', severity: 'warning' })
      return
    }

    try {
      setTaskPointsPrecheckError(null)
      setResumingChapterId(chapterId)

      const response = await apiClient.resumeChapterGeneration(audiobookProject.id, chapterId)
      const data = response.data || {}
      if (!data?.job_id) {
        throw new Error('恢复任务未返回 job_id')
      }

      setResumeCheckpoints((prev) => {
        const current = prev[chapterId]
        if (!current) {
          return prev
        }
        return {
          ...prev,
          [chapterId]: {
            ...current,
            can_resume: false,
            run_status: 'queued',
            celery_task_id: data.job_id,
          },
        }
      })

      await activateQueuedAudiobookTask(audiobookProject.id, data.job_id, {
        generationMode: data.task_type === 'script_only' ? 'script_only' : 'full',
        successMessage: '继续生成任务已进入队列',
      })
    } catch (error: any) {
      const precheckDetail = await extractTaskPointsPrecheckErrorDetail(error)
      setTaskPointsPrecheckError(precheckDetail)
      const message = precheckDetail
        ? describeTaskPointsPrecheckErrorDetail(precheckDetail)
        : await extractApiErrorMessage(error, '继续生成失败，请稍后重试')
      setSnackbar({
        open: true,
        message: message || '继续生成失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setResumingChapterId(null)
    }
  }

  // 轮询当前项目下的任务列表，支持刷新后自动恢复多个活跃任务
  useEffect(() => {
    if (!selectedProjectId) {
      return
    }

    let cancelled = false

    const pollTaskList = async () => {
      try {
        const response = await apiClient.listAudiobookTasks()

        if (response.status < 200 || response.status >= 300) {
          return
        }

        const trackedIds = new Set(trackedAudiobookProjectIds)
        if (trackedIds.size === 0) {
          return
        }

        const rawTasks = Array.isArray(response.data) ? response.data : []
        const normalizedTasks: TaskStatus[] = rawTasks
          .map((task: any) => normalizeTaskStatusResponse(task))
          .filter((task) => trackedIds.has(task.audiobook_project_id))

        if (cancelled) {
          return
        }

        if (normalizedTasks.length > 0) {
          const nextTaskMap = normalizedTasks.reduce((acc, task) => {
            acc[task.task_id] = task
            return acc
          }, {} as Record<string, TaskStatus>)

          setTaskStatuses((prev) => ({
            ...prev,
            ...nextTaskMap,
          }))
        }

        const activeTasks = normalizedTasks
          .filter((task) => isActiveAudiobookTask(task))
          .sort(compareTaskByRecency)

        if (activeTasks.length > 0) {
          const shouldAutofocusActiveTask =
            Boolean(currentTaskId)
            || generating
            || activeStep === 0
            || activeStep === 1

          if (shouldAutofocusActiveTask) {
            const preferredTask = activeTasks.find((task) => task.task_id === currentTaskId) || activeTasks[0]

            if (
              preferredTask.task_id !== currentTaskId
              || preferredTask.audiobook_project_id !== currentAudiobookProjectId
              || audiobookProject?.id !== preferredTask.audiobook_project_id
            ) {
              await focusAudiobookTask(preferredTask, {
                forceGenerating: true,
                activateProgressView: true,
                loadProjectDetail: audiobookProject?.id !== preferredTask.audiobook_project_id,
              })
            } else {
              setGenerating(true)
              setActiveStep((prev) => (prev === 0 ? 1 : prev))
            }
          }
        }
      } catch {
        // 查询任务列表异常
      }
    }

    void pollTaskList()
    const intervalId = setInterval(() => {
      void pollTaskList()
    }, 2000)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [
    selectedProjectId,
    trackedAudiobookProjectIdKey,
    currentTaskId,
    currentAudiobookProjectId,
    generating,
    activeStep,
    audiobookProject?.id,
    focusAudiobookTask,
  ])
  
  // 新增：轮询单个任务状态（用于实时显示8个阶段）
  useEffect(() => {
    if (!currentTaskId) {
      return
    }

    let cancelled = false

    const pollTaskStatus = async () => {
      try {
        const response = await apiClient.getAudiobookTaskStatus(currentTaskId)

        if (response.status >= 200 && response.status < 300) {
          const raw = response.data
          const normalized = normalizeTaskStatusResponse(raw)
          if (cancelled) return
          setTaskStatuses((prev) => ({
            ...prev,
            [normalized.task_id]: normalized,
          }))
          if (!currentAudiobookProjectId && normalized.audiobook_project_id) {
            setCurrentAudiobookProjectId(normalized.audiobook_project_id)
          }
          const resolvedAudiobookProjectId = currentAudiobookProjectId || normalized.audiobook_project_id || null
          const mergedTaskStatuses = {
            ...taskStatuses,
            [normalized.task_id]: normalized,
          }
          const nextActiveTask = Object.values(mergedTaskStatuses)
            .filter((task) => task.task_id !== normalized.task_id)
            .filter((task) => isActiveAudiobookTask(task))
            .sort(compareTaskByRecency)[0]

          if (normalized.status === 'completed') {
            if (nextActiveTask) {
              await focusAudiobookTask(nextActiveTask, {
                forceGenerating: true,
                activateProgressView: true,
              })
              return
            }

            setGenerating(false)
            setActiveStep(2)
            if (resolvedAudiobookProjectId) {
              try {
                await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
              } catch {
                // 刷新有声书项目详情失败
              }
            }
            setSnackbar({ open: true, message: '生成完成！', severity: 'success' })
            setCurrentTaskId(null)
          } else if (normalized.status === 'failed') {
            if (nextActiveTask) {
              await focusAudiobookTask(nextActiveTask, {
                forceGenerating: true,
                activateProgressView: true,
              })
              return
            }

            setGenerating(false)
            setActiveStep(0)
            if (resolvedAudiobookProjectId) {
              try {
                await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
              } catch {
                // 刷新有声书项目详情失败
              }
            }
            setSnackbar({ open: true, message: '生成失败，请重试', severity: 'error' })
            setCurrentTaskId(null)
          } else {
            setGenerating(true)
          }
        } else if (response.status === 404) {
          const nextActiveTask = Object.values(taskStatuses)
            .filter((task) => task.task_id !== currentTaskId)
            .filter((task) => isActiveAudiobookTask(task))
            .sort(compareTaskByRecency)[0]

          if (nextActiveTask) {
            await focusAudiobookTask(nextActiveTask, {
              forceGenerating: true,
              activateProgressView: true,
            })
            return
          }

          setGenerating(false)
          setCurrentTaskId(null)
        }
      } catch {
        // 查询任务状态异常
      }
    }

    pollTaskStatus()
    const intervalId = setInterval(pollTaskStatus, 2000)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [
    currentTaskId,
    currentAudiobookProjectId,
    refreshAudiobookProjectDetail,
    focusAudiobookTask,
    taskStatuses,
  ])
  
  // 新增：渲染阶段详情
  const renderStageDetails = (taskStatus: TaskStatus) => {
    const stageConfig = STAGE_CONFIG

    const statusColors = {
      pending: { bg: '#f5f5f5', border: '#e0e0e0', text: '#9e9e9e' },
      running: { bg: 'rgba(156, 39, 176, 0.08)', border: '#9c27b0', text: '#9c27b0' },
      completed: { bg: 'rgba(76, 175, 80, 0.08)', border: '#4caf50', text: '#4caf50' },
      failed: { bg: 'rgba(244, 67, 54, 0.08)', border: '#f44336', text: '#f44336' }
    }
    
    const stageValues = Object.values(taskStatus.stages || {})
    const hasLiveProgress = stageValues.some((stage) => stage?.status && stage.status !== 'pending')

    return (
      <Box>
        {!hasLiveProgress && (
          <Alert severity="info" sx={{ mb: 2 }}>
            正在等待后台任务启动，阶段详情准备就绪后会自动更新。如需查看以往结果，可打开右上角「历史记录」。
          </Alert>
        )}
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 2 }}>
        {stageConfig.map((stage) => {
          const stageInfo = taskStatus.stages[stage.key as StageKey] || { status: 'pending', progress: 0 }
          
          const colors = statusColors[stageInfo.status as keyof typeof statusColors] || statusColors.pending
          const isActive = stageInfo.status === 'running'
          const isDone = stageInfo.status === 'completed'
          const hasMetrics = Boolean(stageInfo.metrics && Object.keys(stageInfo.metrics).length > 0)
          const canOpen = isDone && hasMetrics
          
          return (
            <Paper 
              key={stage.key}
              elevation={isActive ? 4 : 1}
              onClick={canOpen ? () => handleOpenStageMetricsDialog(stage, stageInfo) : undefined}
              sx={{ 
                p: 2,
                border: `2px solid ${colors.border}`,
                backgroundColor: colors.bg,
                transition: 'all 0.3s ease',
                transform: isActive ? 'scale(1.02)' : 'scale(1)',
                position: 'relative',
                overflow: 'hidden',
                cursor: canOpen ? 'pointer' : 'default',
                '&::before': isActive ? {
                  content: '""',
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  background: `linear-gradient(135deg, transparent 0%, ${colors.border}15 100%)`,
                  pointerEvents: 'none'
                } : {}
              }}
            >
              {/* 头部：图标+名称+状态 */}
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="h6" sx={{ fontSize: '1.5rem' }}>
                    {stage.icon}
                  </Typography>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: colors.text }}>
                      {stage.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                      {stage.desc}
                    </Typography>
                  </Box>
                </Box>
                {isDone && (
                  <Box
                    sx={{
                      width: 24,
                      height: 24,
                      borderRadius: '50%',
                      backgroundColor: '#4caf50',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'white',
                      fontSize: '0.9rem',
                    }}
                  >
                    ✓
                  </Box>
                )}
              </Box>
              
              {/* 进度条 */}
              <LinearProgress 
                variant="determinate" 
                value={stageInfo.progress * 100} 
                sx={{ 
                  height: 4, 
                  borderRadius: 2,
                  backgroundColor: 'rgba(0, 0, 0, 0.08)',
                  '& .MuiLinearProgress-bar': {
                    backgroundColor: colors.border,
                    borderRadius: 2
                  }
                }}
              />
              
              {/* 状态文字 */}
              <Typography 
                variant="caption" 
                sx={{ 
                  display: 'block',
                  mt: 0.5,
                  textAlign: 'right',
                  color: colors.text,
                  fontWeight: 500,
                  fontSize: '0.7rem'
                }}
              >
                {isActive ? `进行中 ${Math.round(stageInfo.progress * 100)}%` : 
                 isDone ? '已完成' : 
                 stageInfo.status === 'failed' ? '失败' : '等待中'}
              </Typography>
              
              {/* 关键指标 */}
              {stageInfo.metrics && Object.keys(stageInfo.metrics).length > 0 && (
                <Box sx={{ mt: 1, pt: 1, borderTop: '1px dashed rgba(0,0,0,0.1)' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem', lineHeight: 1.3 }}>
                    {Object.entries(stageInfo.metrics).slice(0, 2).map(([key, value]) => (
                      <Box key={key} component="span" sx={{ display: 'block' }}>
                        {key}: {typeof value === 'object' ? JSON.stringify(value).slice(0, 20) : String(value).slice(0, 20)}
                      </Box>
                    ))}
                  </Typography>
                </Box>
              )}
            </Paper>
          )
        })}
        </Box>
      </Box>
    )
  }

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
      {/* 顶部导航 */}
      <Box
        sx={{
          p: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          backgroundColor: 'rgba(255,255,255,0.95)',
          backdropFilter: 'blur(10px)',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        }}
      >
        <IconButton onClick={() => navigate('/home')}>
          <ArrowBackIcon />
        </IconButton>
        <Box sx={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 1 }}>
          <HeadphonesIcon sx={{ fontSize: 32, color: '#9c27b0' }} />
          <Typography variant="h5" sx={{ fontWeight: 600 }}>
            耳畔星河
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
            有声小说生成工具
          </Typography>
        </Box>

        <Button
          variant="contained"
          onClick={() => setNewProjectDialogOpen(true)}
          sx={{
            mr: selectedProject ? 1 : 0,
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          新建项目
        </Button>
        
        {/* 新增：历史记录按钮 */}
        {selectedProject && (
          <Tooltip title="查看历史生成记录">
            <Button
              variant="outlined"
              startIcon={<HistoryIcon />}
              onClick={() => {
                setShowHistory(true)
                fetchHistory()
              }}
              sx={{
                borderColor: '#9c27b0',
                color: '#9c27b0',
                '&:hover': {
                  borderColor: '#7b1fa2',
                  backgroundColor: 'rgba(156, 39, 176, 0.08)',
                },
              }}
            >
              历史记录
            </Button>
          </Tooltip>
        )}
      </Box>

      <Container maxWidth="xl" sx={{ py: 4 }}>
        {/* 步骤指示器 */}
        <Paper sx={{ p: 3, mb: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
          <Stepper activeStep={activeStep}>
            {steps.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>
        </Paper>

        {taskPointsPrecheckError && (
          <TaskPointsPrecheckAlert
            detail={taskPointsPrecheckError}
            onClose={() => setTaskPointsPrecheckError(null)}
            sx={{ mb: 3 }}
          />
        )}

        {activeProjectTasks.length > 0 && activeStep !== 1 && (
          <Alert severity="info" sx={{ mb: 3, alignItems: 'flex-start' }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  当前项目下有 {activeProjectTasks.length} 个任务仍在后台运行
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  刷新后这些任务会继续被自动发现与轮询。你可以随时切回进度页查看任一任务。
                </Typography>
              </Box>

              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {activeProjectTasks.map((task) => (
                  <Button
                    key={task.task_id}
                    variant="outlined"
                    size="small"
                    onClick={() => {
                      void focusAudiobookTask(task, {
                        forceGenerating: true,
                        activateProgressView: true,
                      })
                    }}
                    sx={{
                      borderColor: '#1976d2',
                      color: '#1565c0',
                      '&:hover': {
                        borderColor: '#1565c0',
                        backgroundColor: 'rgba(25, 118, 210, 0.08)',
                      },
                    }}
                  >
                    {formatActiveTaskLabel(task)}
                  </Button>
                ))}
              </Box>
            </Box>
          </Alert>
        )}

        {!generating && resumableChapterEntries.length > 0 && (
          <Alert
            severity="warning"
            icon={<WarningIcon fontSize="inherit" />}
            sx={{ mb: 3, alignItems: 'flex-start' }}
          >
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  检测到 {resumableChapterEntries.length} 个章节存在可继续生成的进度
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  页面只负责发现入口，是否可恢复与如何入队由服务端 checkpoint 规则判定。
                </Typography>
              </Box>

              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {resumableChapterEntries.slice(0, 3).map((entry: any) => {
                  const chapterLabel = entry.chapter
                    ? `继续第${entry.chapter.chapter_number}章`
                    : `继续章节${entry.chapterAudio.chapter_id}`

                  return (
                    <Button
                      key={entry.chapterAudio.chapter_id}
                      variant="outlined"
                      size="small"
                      onClick={() => handleResumeChapterGeneration(entry.chapterAudio.chapter_id)}
                      disabled={resumingChapterId !== null}
                      startIcon={
                        resumingChapterId === entry.chapterAudio.chapter_id
                          ? <CircularProgress size={14} color="inherit" />
                          : undefined
                      }
                      sx={{
                        borderColor: '#ef6c00',
                        color: '#e65100',
                        '&:hover': {
                          borderColor: '#e65100',
                          backgroundColor: 'rgba(239, 108, 0, 0.08)',
                        },
                      }}
                    >
                      {resumingChapterId === entry.chapterAudio.chapter_id ? '提交中...' : chapterLabel}
                    </Button>
                  )
                })}

                {resumableChapterEntries.length > 3 && (
                  <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                    其余章节可在下方结果区继续生成
                  </Typography>
                )}

                {resumeCheckpointLoading && (
                  <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                    正在同步最新断点信息...
                  </Typography>
                )}
              </Box>
            </Box>
          </Alert>
        )}

        {/* 步骤1: 配置音色（章节选择 + 角色音频设置） */}
        {activeStep === 0 && (
          <Paper sx={{ p: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center' }}>
              <VoiceIcon sx={{ mr: 1, color: '#9c27b0' }} />
              配置章节与角色音
            </Typography>
                    
            <Alert severity="info" sx={{ mb: 2 }}>
              已选择 {selectedChapters.length}/{chapters.length} 个章节。未配置的角色将由 AI 自动分配音色和音量。
            </Alert>

            {/* TTS 模型选择已移除 - 现在仅通过角色级模型选择器选择 */}
            <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={scriptOnlyMode}
                    onChange={(_, checked) => setScriptOnlyMode(checked)}
                    sx={{
                      color: '#9c27b0',
                      '&.Mui-checked': {
                        color: '#9c27b0',
                      },
                    }}
                  />
                }
                label="仅生成剧本和评审（稍后再生成音频）"
              />
            </Box>

            <Box sx={{ flex: 1, minWidth: 260 }}>
              {voiceCatalogMeta && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  {ttsModel === 'cosyvoice-v3.5-plus'
                    ? `${voiceCatalogMeta.model || 'CosyVoice v3.5-plus'}：官方无系统音色，当前展示 ${currentVoicePresets.length} 个可用自定义音色，最近同步 ${voiceCatalogMeta.updated_at || '—'}。`
                    : `${voiceCatalogMeta.model || 'Qwen3-TTS Instruct Flash'}：官方 ${voiceCatalogMeta.voice_count ?? currentVoicePresets.length} 种音色，最近更新 ${voiceCatalogMeta.updated_at || '—'}，覆盖普通话/多语种/方言。`}
                </Typography>
              )}
              <Alert severity="success" sx={{ mb: 1 }}>
                Qwen3-TTS Instruct Flash 适合整本批量生成；CosyVoice v3.5-plus 适合精品章节，但需要先准备复刻或设计音色。
              </Alert>
              {ttsModel === 'cosyvoice-v3.5-plus' && (
                <>
                  <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                      自定义音色管理（CosyVoice v3.5-plus）
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                      CosyVoice v3.5-plus 不提供系统音色。你可以通过“声音复刻”导入真实样本，也可以通过“声音设计”用文字描述生成新声线；创建完成后会出现在下方音色列表中。
                    </Typography>
                    <Grid container spacing={1.5}>
                      <Grid item xs={12} lg={6}>
                        <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                            声音复刻
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                            支持 http/https 或 oss:// 临时 URL（有效期 48 小时）；系统会自动生成合规 prefix，并用你的“命名”在列表中展示。
                          </Typography>
                          <Grid container spacing={1}>
                            <Grid item xs={12} md={4}>
                              <TextField
                                size="small"
                                fullWidth
                                label="声音名称"
                                value={cloneName}
                                onChange={(e) => setCloneName(e.target.value)}
                                disabled={cloneLoading || cloneUploading || cloneRecording || designLoading}
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                size="small"
                                fullWidth
                                label="音频 URL（http/https 或 oss://）"
                                value={cloneUrl}
                                onChange={(e) => setCloneUrl(e.target.value)}
                                disabled={cloneLoading || cloneUploading || cloneRecording || designLoading}
                              />
                            </Grid>
                            <Grid item xs={12} md={2}>
                              <Button
                                fullWidth
                                variant="contained"
                                onClick={handleCreateCloneVoice}
                                disabled={cloneLoading || cloneUploading || cloneRecording || designLoading || !cloneName.trim() || !cloneUrl.trim()}
                                sx={{ height: '100%' }}
                              >
                                {cloneLoading ? '提交中...' : '开始复刻'}
                              </Button>
                            </Grid>
                            <Grid item xs={12}>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                                <Button
                                  variant="outlined"
                                  onClick={handleOpenCloneRecordDialog}
                                  disabled={cloneLoading || cloneUploading || cloneRecording || designLoading}
                                >
                                  录音
                                </Button>
                                <Button
                                  variant="outlined"
                                  component="label"
                                  disabled={cloneLoading || cloneUploading || cloneRecording || designLoading}
                                >
                                  {cloneUploading ? '上传中...' : '上传音频获取临时URL'}
                                  <input
                                    type="file"
                                    hidden
                                    accept="audio/*"
                                    onChange={handleUploadCloneAudio}
                                  />
                                </Button>
                                <Typography variant="caption" color="text.secondary">
                                  录音或上传都会生成临时 URL（oss://），有效期 48 小时。点击“录音”可查看示例文本，也可以随机朗读其他内容。
                                </Typography>
                              </Box>
                            </Grid>
                          </Grid>
                          {cloneError && (
                            <Alert severity="warning" sx={{ mt: 1 }}>
                              {cloneError}
                            </Alert>
                          )}
                          {cloneSuccess && (
                            <Alert severity="success" sx={{ mt: 1 }}>
                              {cloneSuccess}
                            </Alert>
                          )}
                        </Paper>
                      </Grid>
                      <Grid item xs={12} lg={6}>
                        <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
                          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                            声音设计
                          </Typography>
                          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                            用自然语言描述声线、年龄感、气质和情绪，再提供一段试听文本，即可生成新的设计音色。
                          </Typography>
                          <Grid container spacing={1}>
                            <Grid item xs={12} md={4}>
                              <TextField
                                size="small"
                                fullWidth
                                label="设计名称"
                                value={designName}
                                onChange={(e) => setDesignName(e.target.value)}
                                disabled={designLoading || cloneLoading || cloneUploading || cloneRecording}
                              />
                            </Grid>
                            <Grid item xs={12} md={8}>
                              <TextField
                                size="small"
                                fullWidth
                                label="声音描述"
                                placeholder="例如：青年女性，声线清透，带一点冷静与克制，适合悬疑旁白。"
                                value={designPrompt}
                                onChange={(e) => setDesignPrompt(e.target.value)}
                                disabled={designLoading || cloneLoading || cloneUploading || cloneRecording}
                              />
                            </Grid>
                            <Grid item xs={12} md={9}>
                              <TextField
                                size="small"
                                fullWidth
                                multiline
                                minRows={2}
                                label="试听文本"
                                value={designPreviewText}
                                onChange={(e) => setDesignPreviewText(e.target.value)}
                                disabled={designLoading || cloneLoading || cloneUploading || cloneRecording}
                              />
                            </Grid>
                            <Grid item xs={12} md={3}>
                              <Button
                                fullWidth
                                variant="contained"
                                onClick={handleCreateDesignVoice}
                                disabled={designLoading || cloneLoading || cloneUploading || cloneRecording || !designName.trim() || !designPrompt.trim() || !designPreviewText.trim()}
                                sx={{ height: '100%' }}
                              >
                                {designLoading ? '设计中...' : '开始设计'}
                              </Button>
                            </Grid>
                          </Grid>
                          {designError && (
                            <Alert severity="warning" sx={{ mt: 1 }}>
                              {designError}
                            </Alert>
                          )}
                          {designSuccess && (
                            <Alert severity="success" sx={{ mt: 1 }}>
                              {designSuccess}
                            </Alert>
                          )}
                        </Paper>
                      </Grid>
                    </Grid>
                    {customVoicePresets.length > 0 && (
                      <Box sx={{ mt: 1.5 }}>
                        <Divider sx={{ mb: 1 }} />
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                          已创建自定义音色（可删除）
                        </Typography>
                        <List dense>
                          {customVoicePresets.map((preset) => {
                            const isDesign = preset.customType === 'design'
                            return (
                              <ListItem
                                key={preset.id}
                                secondaryAction={
                                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Tooltip title={isDesign ? '音色设计：通过文字描述生成新的声线' : '音色克隆：基于音频样本创建的专属音色'}>
                                      <Chip
                                        label={isDesign ? '设计' : '克隆'}
                                        size="small"
                                        color={isDesign ? 'warning' : 'success'}
                                        sx={{ height: 18, fontSize: '0.65rem' }}
                                      />
                                    </Tooltip>
                                    <Button
                                      color="error"
                                      size="small"
                                      disabled={cloneDeletingId === preset.id || cloneLoading || cloneUploading || designLoading}
                                      onClick={() => handleDeleteCustomVoice(preset.id, preset.label)}
                                    >
                                      {cloneDeletingId === preset.id ? '删除中...' : '删除'}
                                    </Button>
                                  </Box>
                                }
                              >
                                <ListItemText
                                  primary={preset.label || preset.id}
                                  secondary={preset.description || preset.id}
                                />
                              </ListItem>
                            )
                          })}
                        </List>
                      </Box>
                    )}
                  </Paper>
                  <Dialog
                    open={cloneRecordDialogOpen}
                    onClose={() => handleCloseCloneRecordDialog()}
                    fullWidth
                    maxWidth="sm"
                    disableEscapeKeyDown={cloneRecording}
                  >
                    <DialogTitle>录音朗读提示</DialogTitle>
                    <DialogContent dividers>
                      <Typography variant="body2" sx={{ mb: 1 }}>
                        朗读示例（约10秒）：“时间会缓和所有的悲伤，当你的悲伤被安抚以后，你就会因为认识过我而感到满足。”
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        也可以随机读其他内容。
                      </Typography>
                    </DialogContent>
                    <DialogActions>
                      <Button onClick={handleCloseCloneRecordDialog} disabled={cloneRecording}>
                        关闭
                      </Button>
                      <Button
                        variant="contained"
                        color={cloneRecording ? 'error' : 'primary'}
                        onClick={cloneRecording ? handleStopCloneRecording : handleStartCloneRecording}
                        disabled={cloneLoading || cloneUploading}
                      >
                        {cloneRecording ? '结束录音并上传' : '开始录音'}
                      </Button>
                    </DialogActions>
                  </Dialog>
                </>
              )}
              {voiceError && (
                <Alert severity="warning" action={
                  <Button size="small" onClick={fetchVoiceCatalog} disabled={voiceLoading}>
                    {voiceLoading ? '同步中...' : '重新同步'}
                  </Button>
                } sx={{ mb: 1 }}>
                  {voiceError}
                </Alert>
              )}
            </Box>

            {/* 叙事风格选择 */}
            <Paper
              variant="outlined"
              sx={{
                mb: 2,
                p: 2,
                backgroundColor: 'rgba(156, 39, 176, 0.02)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                叙事风格
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                选择旁白的朗读风格，影响AI的情感表达和语调
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {NARRATION_STYLE_OPTIONS.map((style) => (
                  <Tooltip key={style.id} title={style.desc} arrow>
                    <Box
                      onClick={() => setNarrationStyle(style.id)}
                      sx={{
                        flex: '1 1 140px',
                        minWidth: 140,
                        p: 1.5,
                        borderRadius: 1,
                        border: `1px solid ${narrationStyle === style.id ? style.color : 'divider'}`,
                        borderWidth: narrationStyle === style.id ? 2 : 1,
                        backgroundColor: narrationStyle === style.id ? style.color + '10' : 'transparent',
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                        '&:hover': {
                          borderColor: style.color,
                          backgroundColor: style.color + '10',
                        },
                      }}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 600, color: narrationStyle === style.id ? style.color : 'text.primary' }}>
                        {style.name}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                        {style.desc}
                      </Typography>
                    </Box>
                  </Tooltip>
                ))}
              </Box>
              {narrationStyle !== DEFAULT_NARRATION_STYLE && (
                <Chip
                  label={`已选择: ${NARRATION_STYLE_OPTIONS.find((style) => style.id === narrationStyle)?.name || '自定义风格'}`}
                  size="small"
                  color="primary"
                  variant="outlined"
                  sx={{ mt: 1 }}
                />
              )}
            </Paper>

            {/* 项目级音效与配乐配置 */}
            <Paper
              variant="outlined"
              sx={{
                mb: 2,
                p: 2,
                backgroundColor: 'rgba(156, 39, 176, 0.02)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                音效与背景音乐
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                这里的设置会作为项目级默认配置保存，下次进入该项目会自动带出，并影响音效/配乐是否启用及大致密度。
              </Typography>
              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={audioFxConfig.enable_sound_effects}
                        onChange={(_, checked) =>
                          setAudioFxConfig((prev) => ({
                            ...prev,
                            enable_sound_effects: checked,
                          }))
                        }
                        sx={{
                          color: '#9c27b0',
                          '&.Mui-checked': {
                            color: '#9c27b0',
                          },
                        }}
                      />
                    }
                    label="开启音效（环境音 + 关键动作音）"
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_sound_effects}>
                    <InputLabel>音效密度</InputLabel>
                    <Select
                      label="音效密度"
                      value={audioFxConfig.sound_effect_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          sound_effect_density: e.target.value as AudioFxConfig['sound_effect_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">关闭（不使用音效）</MenuItem>
                      <MenuItem value="low">稀疏（仅关键场景）</MenuItem>
                      <MenuItem value="medium">适中（推荐）</MenuItem>
                      <MenuItem value="high">丰富（沉浸感更强）</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} md={6}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={audioFxConfig.enable_music}
                        onChange={(_, checked) =>
                          setAudioFxConfig((prev) => ({
                            ...prev,
                            enable_music: checked,
                          }))
                        }
                        sx={{
                          color: '#9c27b0',
                          '&.Mui-checked': {
                            color: '#9c27b0',
                          },
                        }}
                      />
                    }
                    label="开启背景音乐（AI 配乐）"
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_music}>
                    <InputLabel>配乐密度</InputLabel>
                    <Select
                      label="配乐密度"
                      value={audioFxConfig.music_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          music_density: e.target.value as AudioFxConfig['music_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">关闭（不使用配乐）</MenuItem>
                      <MenuItem value="low">稀疏（仅片头/片尾）</MenuItem>
                      <MenuItem value="medium">适中（推荐）</MenuItem>
                      <MenuItem value="high">丰富（几乎全程有配乐）</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
              </Grid>
              
              {/* 🆕 LLM智能场景检测信息 */}
              {audioFxConfig.enable_sound_effects && (
                <Box sx={{ mt: 2, p: 1.5, backgroundColor: 'rgba(33, 150, 243, 0.05)', borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    ℹ️ 音效将由AI根据章节内容智能匹配，支持大雨、街道、森林等场景识别
                  </Typography>
                </Box>
              )}
            </Paper>
        
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1 }}>
                  章节选择
                </Typography>
        
                {/* 全选按钮 */}
                <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
                  <Button 
                    variant="outlined" 
                    size="small"
                    onClick={handleToggleAll}
                  >
                    {selectedChapters.length === chapters.length ? '取消全选' : '全选'}
                  </Button>
                </Box>
        
                {/* 章节列表 */}
                <Paper 
                  variant="outlined" 
                  sx={{ 
                    maxHeight: 400, 
                    overflow: 'auto',
                  }}
                >
                  <List>
                    {chapters.map((chapter) => (
                      <ListItem 
                        key={chapter.id}
                        component="div"
                        onClick={() => handleToggleChapter(chapter.id)}
                        secondaryAction={
                          <IconButton
                            edge="end"
                            size="small"
                            onClick={(e) => handleOpenChapterMenu(e, chapter)}
                            sx={{ color: '#757575' }}
                          >
                            <MoreVertIcon fontSize="small" />
                          </IconButton>
                        }
                        sx={{
                          cursor: 'pointer',
                          '&:hover': {
                            backgroundColor: 'rgba(156, 39, 176, 0.08)'
                          }
                        }}
                      >
                        <Checkbox
                          edge="start"
                          checked={selectedChapters.includes(chapter.id)}
                          tabIndex={-1}
                          disableRipple
                          sx={{
                            color: '#9c27b0',
                            '&.Mui-checked': {
                              color: '#9c27b0',
                            },
                          }}
                        />
                        <ListItemText
                          primary={`第${chapter.chapter_number}章 - ${chapter.title}`}
                          secondary={chapter.content ? `${chapter.content.slice(0, 50)}...` : '暂无内容'}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              </Grid>
        
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AudioIcon fontSize="small" />
                  {supportsTtsTuning ? '角色音与音量配置' : '角色音配置'}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  {supportsTtsTuning
                    ? '不修改时使用 AI 默认音色；为角色选择音色或调整音量/语速/音高后，本次有声书生成将优先使用你的配置。'
                    : '不修改时使用 AI 默认音色；为角色选择音色后，本次有声书生成将优先使用你的配置。'}
                </Typography>
        
                {loadingCharacters && (
                  <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
                    <CircularProgress size={24} />
                  </Box>
                )}
        
                {!loadingCharacters && characterVoices.length === 0 && (
                  <Box sx={{ py: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      当前项目还没有结构化角色档案，可在「项目详情 → 角色管理」中添加角色后再配置音色。
                    </Typography>
                  </Box>
                )}
        
                {!loadingCharacters && characterVoices.length > 0 && (
                  <Paper
                    variant="outlined"
                    sx={{
                      maxHeight: 400,
                      overflow: 'auto',
                      p: 1,
                    }}
                  >
                    <List>
                      {characterVoices.map((cv) => (
                        <ListItem
                          key={cv.characterId}
                          alignItems="flex-start"
                          sx={{
                            alignItems: 'stretch',
                            '&:hover': {
                              backgroundColor: 'rgba(156, 39, 176, 0.03)',
                            },
                          }}
                        >
                          <Box sx={{ width: '100%' }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                              <Box>
                                <Typography variant="subtitle2">{cv.name}</Typography>
                                {(cv.role || cv.gender) && (
                                  <Typography variant="caption" color="text.secondary">
                                    {cv.role || '角色'} · {cv.gender || '性别未设定'}
                                  </Typography>
                                )}
                              </Box>
                              <Box sx={{ display: 'flex', gap: 0.5 }}>
                                {cv.ttsModel && cv.ttsModel !== ttsModel && (
                                  <Chip
                                    label={getTtsModelLabel(cv.ttsModel)}
                                    size="small"
                                    color={cv.ttsModel === 'cosyvoice-v3.5-plus' ? 'warning' : cv.ttsModel.startsWith('minimax-') ? 'info' : 'default'}
                                    sx={{ height: 18, fontSize: '0.65rem' }}
                                  />
                                )}
                                {cv.voiceId && (
                                  <Chip
                                    label="已配置"
                                    size="small"
                                    color="success"
                                    sx={{ height: 18 }}
                                  />
                                )}
                              </Box>
                            </Box>
        
                            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                              <FormControl size="small" fullWidth>
                                <InputLabel>角色音</InputLabel>
                                <Select
                                  label="角色音"
                                  value={cv.voiceId}
                                  onChange={(e) => handleVoiceChange(cv.characterId, e.target.value as string)}
                                  disabled={voiceLoading && currentVoicePresets.length === 0}
                                >
                                  <MenuItem value="">
                                    <em>自动（AI 选择）</em>
                                  </MenuItem>
                                  {voiceLoading && currentVoicePresets.length === 0 && (
                                    <MenuItem disabled value="__loading">
                                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <CircularProgress size={14} />
                                        <Typography variant="caption">同步官方音色...</Typography>
                                      </Box>
                                    </MenuItem>
                                  )}
                                  {!voiceLoading && currentVoicePresets.length === 0 && (
                                    <MenuItem disabled value="__empty">
                                      {ttsModel === 'cosyvoice-v3.5-plus' ? '暂无可用自定义音色，请先创建' : '暂无官方音色，请稍后重试'}
                                    </MenuItem>
                                  )}
                                  {currentVoicePresets.map((preset) => (
                                    <MenuItem key={preset.id} value={preset.id}>
                                      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.25 }}>
                                        <Typography variant="body2" fontWeight={600}>
                                          {preset.label || preset.id}
                                        </Typography>
                                        {preset.description && (
                                          <Typography variant="caption" color="text.secondary">
                                            {preset.description}
                                          </Typography>
                                        )}
                                        <Typography variant="caption" color="text.secondary">
                                          {(preset.languages?.join('/') || '中英')} · {preset.style || '通用'}
                                        </Typography>
                                      </Box>
                                      {ttsModel === 'cosyvoice-v3.5-plus' && preset.supportsInstruct && (
                                        <Tooltip title="该音色支持 instruction/SSML（CosyVoice v3.5-plus）。情绪/语气可通过 Instruct 参数控制。">
                                          <Chip
                                            label="Instruct"
                                            size="small"
                                            color="primary"
                                            sx={{ height: 18, fontSize: '0.65rem', ml: 1 }}
                                          />
                                        </Tooltip>
                                      )}
                                    </MenuItem>
                                  ))}
                                </Select>
                              </FormControl>
                              
                              <FormControl size="small" sx={{ minWidth: 140 }}>
                                <InputLabel>模型</InputLabel>
                                <Select
                                  label="模型"
                                  value={cv.ttsModel || 'inherit'}
                                  onChange={(e) => handleTtsModelChangeForCharacter(cv.characterId, e.target.value as TtsModel)}
                                >
                                  <MenuItem value="inherit">
                                    <em>跟随项目 ({getTtsModelLabel(ttsModel)})</em>
                                  </MenuItem>
                                  <Divider sx={{ my: 0.5 }} />
                                  <MenuItem value="qwen3-tts-instruct-flash">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                      <span>Qwen3-TTS Instruct Flash</span>
                                      <Chip label="低价" size="small" color="success" sx={{ height: 16, fontSize: '0.6rem' }} />
                                    </Box>
                                  </MenuItem>
                                  <MenuItem value="cosyvoice-v3.5-plus">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                      <span>CosyVoice v3.5-plus</span>
                                      <Chip label="高音质" size="small" color="warning" sx={{ height: 16, fontSize: '0.6rem' }} />
                                    </Box>
                                  </MenuItem>
                                  <MenuItem value="minimax-speech-2.8-turbo">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                      <span>MiniMax Turbo</span>
                                      <Chip label="低成本" size="small" color="info" sx={{ height: 16, fontSize: '0.6rem' }} />
                                    </Box>
                                  </MenuItem>
                                  <MenuItem value="minimax-speech-2.8-hd">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                      <span>MiniMax HD</span>
                                      <Chip label="高清" size="small" color="error" sx={{ height: 16, fontSize: '0.6rem' }} />
                                    </Box>
                                  </MenuItem>
                                </Select>
                              </FormControl>
                            </Box>
        
                            {/* 🆕 声音类型选择 */}
                            <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
                              <FormControl size="small" sx={{ minWidth: 100 }}>
                                <InputLabel>声音类型</InputLabel>
                                <Select
                                  label="声音类型"
                                  value={cv.voiceType || ''}
                                  onChange={(e) => handleVoiceTypeChange(cv.characterId, e.target.value as string)}
                                >
                                  <MenuItem value=""><em>自动</em></MenuItem>
                                  <MenuItem value="gentle">温柔</MenuItem>
                                  <MenuItem value="energetic">活泼</MenuItem>
                                  <MenuItem value="calm">平静</MenuItem>
                                  <MenuItem value="serious">严肃</MenuItem>
                                  <MenuItem value="mysterious">神秘</MenuItem>
                                  <MenuItem value="powerful">力量</MenuItem>
                                  <MenuItem value="scholarly">书卷气</MenuItem>
                                  <MenuItem value="playful">俏皮</MenuItem>
                                  <MenuItem value="cold">清冷</MenuItem>
                                </Select>
                              </FormControl>
                              <FormControl size="small" sx={{ minWidth: 100 }}>
                                <InputLabel>性格</InputLabel>
                                <Select
                                  label="性格"
                                  value={cv.personality || ''}
                                  onChange={(e) => handlePersonalityChange(cv.characterId, e.target.value as string)}
                                >
                                  <MenuItem value=""><em>自动</em></MenuItem>
                                  <MenuItem value="introvert">内向</MenuItem>
                                  <MenuItem value="extrovert">外向</MenuItem>
                                  <MenuItem value="ambitious">野心</MenuItem>
                                  <MenuItem value="calm">冷静</MenuItem>
                                  <MenuItem value="emotional">感性</MenuItem>
                                  <MenuItem value="rational">理性</MenuItem>
                                  <MenuItem value="rebellious">叛逆</MenuItem>
                                  <MenuItem value="loyal">忠诚</MenuItem>
                                </Select>
                              </FormControl>
                              <FormControl size="small" sx={{ minWidth: 100 }}>
                                <InputLabel>情感倾向</InputLabel>
                                <Select
                                  label="情感倾向"
                                  value={cv.emotionTendency || ''}
                                  onChange={(e) => handleEmotionTendencyChange(cv.characterId, e.target.value as string)}
                                >
                                  <MenuItem value=""><em>自动</em></MenuItem>
                                  <MenuItem value="positive">积极</MenuItem>
                                  <MenuItem value="negative">消极</MenuItem>
                                  <MenuItem value="neutral">中性</MenuItem>
                                  <MenuItem value="variable">多变</MenuItem>
                                </Select>
                              </FormControl>
                            </Box>
        
                            {supportsTtsTuning && (
                              <>
                                <Box sx={{ mt: 1 }}>
                                  <Typography variant="caption" color="text.secondary">
                                    音量：{cv.volume}
                                  </Typography>
                                  <Slider
                                    size="small"
                                    min={0}
                                    max={100}
                                    step={5}
                                    value={cv.volume}
                                    onChange={(_, value) => handleVolumeChange(cv.characterId, value as number)}
                                    sx={{ mt: 0.5 }}
                                  />
                                </Box>

                                <Box sx={{ mt: 1 }}>
                                  <Typography variant="caption" color="text.secondary">
                                    语速：{cv.speed ?? 1.0}
                                  </Typography>
                                  <Slider
                                    size="small"
                                    min={0.5}
                                    max={2.0}
                                    step={0.1}
                                    value={cv.speed ?? 1.0}
                                    onChange={(_, value) => handleSpeedChange(cv.characterId, value as number)}
                                    sx={{ mt: 0.5 }}
                                  />
                                </Box>

                                <Box sx={{ mt: 1 }}>
                                  <Typography variant="caption" color="text.secondary">
                                    音高：{cv.pitch ?? 50}
                                  </Typography>
                                  <Slider
                                    size="small"
                                    min={0}
                                    max={100}
                                    step={5}
                                    value={cv.pitch ?? 50}
                                    onChange={(_, value) => handlePitchChange(cv.characterId, value as number)}
                                    sx={{ mt: 0.5 }}
                                  />
                                </Box>
                              </>
                            )}

                            <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end' }}>
                              <Tooltip title="云端精确试听效果，请稍作等待...">
                                <span>
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    onClick={() => handlePreviewCharacterVoice(cv)}
                                    disabled={!cv.voiceId || previewingCharacterId === cv.characterId}
                                  >
                                    {previewingCharacterId === cv.characterId ? '试听中...' : '试听'}
                                  </Button>
                                </span>
                              </Tooltip>
                            </Box>
                          </Box>
                        </ListItem>
                      ))}
                    </List>
                  </Paper>
                )}

                {/* 自动推荐声线按钮 */}
                {!loadingCharacters && (
                  <Box sx={{ mt: 2, display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={handleAutoAssignVoices}
                      disabled={autoAssigningVoices}
                      sx={{
                        borderColor: '#9c27b0',
                        color: '#9c27b0',
                        '&:hover': {
                          borderColor: '#7b1fa2',
                          backgroundColor: 'rgba(156, 39, 176, 0.04)',
                        },
                      }}
                    >
                    {autoAssigningVoices ? '智能推荐中...' : '基于人物卡自动推荐声线'}
                    </Button>
                  </Box>
                )}
              </Grid>
            </Grid>
        
            <Box sx={{ mt: 3, display: 'flex', gap: 2, justifyContent: 'center' }}>
              {activeStep > 0 && (
                <Button variant="outlined" onClick={() => setActiveStep(activeStep - 1)}>
                  上一步
                </Button>
              )}
              <Button
                variant="contained"
                onClick={handleGenerate}
                disabled={selectedChapters.length === 0 || generating || !(selectedProject?.id ?? routeProjectId)}
                sx={{
                  backgroundColor: '#9c27b0',
                  '&:hover': { backgroundColor: '#7b1fa2' },
                }}
              >
                开始生成 ({selectedChapters.length}章)
              </Button>
            </Box>
          </Paper>
        )}

        {/* 步骤2: 生成有声书 */}
        {activeStep === 1 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            {/* 顶部整体进度条和文字已移除，改为仅展示阶段卡片状态 */}

            {activeProjectTasks.length > 0 && (
              <Alert severity="info" sx={{ mb: 3, alignItems: 'flex-start' }}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      已恢复 {activeProjectTasks.length} 个进行中的任务
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      当前展示的是焦点任务，你可以在这里切换查看不同章节或不同批次任务的阶段进度。
                    </Typography>
                  </Box>

                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {activeProjectTasks.map((task) => {
                      const isFocused = task.task_id === activeTaskStatus?.task_id
                      return (
                        <Button
                          key={task.task_id}
                          size="small"
                          variant={isFocused ? 'contained' : 'outlined'}
                          onClick={() => {
                            void focusAudiobookTask(task, {
                              forceGenerating: true,
                              activateProgressView: true,
                            })
                          }}
                          sx={
                            isFocused
                              ? {
                                  backgroundColor: '#9c27b0',
                                  '&:hover': { backgroundColor: '#7b1fa2' },
                                }
                              : {
                                  borderColor: '#9c27b0',
                                  color: '#9c27b0',
                                  '&:hover': {
                                    borderColor: '#7b1fa2',
                                    backgroundColor: 'rgba(156, 39, 176, 0.08)',
                                  },
                                }
                          }
                        >
                          {formatActiveTaskLabel(task)}
                        </Button>
                      )
                    })}
                  </Box>
                </Box>
              </Alert>
            )}
            
            {/* 新增：8个阶段详细展示 */}
            {(() => {
              let taskStatus = activeTaskStatus
              
              if (!taskStatus) {
                taskStatus = {
                  task_id: 'pending',
                  audiobook_project_id: currentAudiobookProjectId || 0,
                  chapter_id: null,
                  status: 'pending',
                  current_stage: null,
                  progress: 0,
                  stages: createEmptyStageMap(),
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                  detail: {},
                }
              }
              
              return (
                <Box sx={{ mt: 3 }}>
                  <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#333' }}>
                    当前阶段进度
                  </Typography>
                  {renderStageDetails(taskStatus)}
                  {taskStatus.stages?.quality_review?.status === 'completed' && (
                    <Box sx={{ mt: 3, textAlign: 'center' }}>
                      <Button
                        variant="outlined"
                        size="medium"
                        onClick={handleOpenScriptReviewDialog}
                        sx={{ 
                          borderColor: '#9c27b0',
                          color: '#9c27b0',
                          '&:hover': {
                            borderColor: '#7b1fa2',
                            backgroundColor: 'rgba(156, 39, 176, 0.04)'
                          }
                        }}
                      >
                        查看剧本评审详情
                      </Button>
                    </Box>
                  )}
                </Box>
              )
            })()}
            
            {/* 底部整体进度条已移除，仅保留文字提示 */}
            <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mt: 1, color: 'text.secondary' }}>
              请耐心等待，生成中请勿关闭页面...
            </Typography>
          </Paper>
        )}

        {/* 步骤3: 完成 */}
        {activeStep === 2 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Box sx={{ textAlign: 'center', mb: 3 }}>
              <CheckIcon sx={{ fontSize: 80, color: '#4caf50', mb: 2 }} />
              <Typography variant="h5" sx={{ mb: 2 }}>
                生成完成！
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                {lastGenerationMode === 'script_only'
                  ? '剧本与评审已生成，接下来可以逐章审稿、修改剧本，再生成音频'
                  : '您的有声书已经准备好了'}
              </Typography>
            </Box>
            
            {/* 统计信息 */}
            {audiobookProject && (
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center', 
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(102, 126, 234, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      {audiobookProject.completed_chapters}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      完成章节
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center',
                      background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(240, 147, 251, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      {((audiobookProject.total_duration || 0) / 60).toFixed(1)}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      总时长(分钟)
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center',
                      background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(79, 172, 254, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      ￥{(audiobookProject.total_cost || 0).toFixed(2)}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      总成本
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>
            )}
            
            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap' }}>
              {audiobookProject && audiobookProject.chapter_audios && audiobookProject.chapter_audios.length > 0 && (
                <Button
                  variant="contained"
                  startIcon={browserPlayerLoading ? <CircularProgress size={18} color="inherit" /> : <HeadphonesIcon />}
                  onClick={handleOpenBrowserPlayer}
                  disabled={browserPlayerLoading}
                  sx={{
                    background: 'linear-gradient(135deg, #3949ab 0%, #1e88e5 100%)',
                    boxShadow: '0 6px 16px rgba(30, 136, 229, 0.28)',
                    '&:hover': {
                      background: 'linear-gradient(135deg, #303f9f 0%, #1976d2 100%)',
                    },
                  }}
                >
                  {browserPlayerLoading ? '加载播放器...' : '打开浏览器播放器'}
                </Button>
              )}

              {/* 下载按钮 - 支持分章节下载 */}
              {audiobookProject && audiobookProject.chapter_audios && audiobookProject.chapter_audios.length > 0 && (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center', width: '100%', mb: 2 }}>
                  {audiobookProject.chapter_audios.map((chapterAudio: any) => {
                    const chapter = chapters.find(c => c.id === chapterAudio.chapter_id)
                    const isPlaying = playingChapter === chapterAudio.chapter_id
                    const isCollecting = collectingChapterId === chapterAudio.chapter_id
                    const resumeCheckpoint = resumeCheckpoints[chapterAudio.chapter_id]
                    const canResume = Boolean(resumeCheckpoint?.can_resume)
                    
                    return (
                      <Box key={chapterAudio.id} sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          {/* 在线播放按钮 */}
                          <Tooltip title={isPlaying ? '暂停播放' : '在线播放'}>
                            <Button
                              variant="outlined"
                              size="small"
                              startIcon={isPlaying ? <PauseIcon /> : <PlayIcon />}
                              onClick={() => handlePlayAudio(chapterAudio.chapter_id)}
                              sx={{
                                borderColor: isPlaying ? '#f50057' : '#9c27b0',
                                color: isPlaying ? '#f50057' : '#9c27b0',
                                '&:hover': {
                                  borderColor: isPlaying ? '#c51162' : '#7b1fa2',
                                  backgroundColor: isPlaying ? 'rgba(245, 0, 87, 0.08)' : 'rgba(156, 39, 176, 0.08)',
                                },
                              }}
                            >
                              {chapter ? `第${chapter.chapter_number}章` : `章节${chapterAudio.chapter_id}`}
                            </Button>
                          </Tooltip>
                          
                          {/* 下载按钮 */}
                          <Tooltip title="下载音频">
                            <IconButton
                              size="small"
                              onClick={() => handleDownloadAudio(chapterAudio.chapter_id)}
                              sx={{
                                color: '#9c27b0',
                                '&:hover': {
                                  backgroundColor: 'rgba(156, 39, 176, 0.08)',
                                },
                              }}
                            >
                              <DownloadIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>

                          <Tooltip title="收录到用户资产">
                            <Button
                              variant="outlined"
                              size="small"
                              onClick={() => handleCollectChapterAudio(chapterAudio)}
                              disabled={collectingChapterId !== null}
                              startIcon={isCollecting ? <CircularProgress size={14} color="inherit" /> : undefined}
                              sx={{
                                borderColor: '#00897b',
                                color: '#00897b',
                                minWidth: 96,
                                '&:hover': {
                                  borderColor: '#00695c',
                                  backgroundColor: 'rgba(0, 137, 123, 0.08)',
                                },
                              }}
                            >
                              {isCollecting ? '收录中' : '收录资产'}
                            </Button>
                          </Tooltip>
  
                          {/* 编辑剧本按钮（如果有脚本可用，用户可以直接尝试打开） */}
                          <Tooltip title="编辑本章节剧本与音频提示词">
                            <Button
                              variant="outlined"
                              size="small"
                              onClick={() => handleOpenScriptEditor(chapterAudio.chapter_id)}
                              sx={{
                                borderColor: '#607d8b',
                                color: '#607d8b',
                                '&:hover': {
                                  borderColor: '#455a64',
                                  backgroundColor: 'rgba(96, 125, 139, 0.08)',
                                },
                              }}
                            >
                              编辑剧本/提示词
                            </Button>
                          </Tooltip>

                          {canResume && (
                            <Tooltip title="按服务端断点信息重新排队当前章节">
                              <Button
                                variant="outlined"
                                size="small"
                                onClick={() => handleResumeChapterGeneration(chapterAudio.chapter_id)}
                                disabled={generating || resumingChapterId !== null}
                                startIcon={
                                  resumingChapterId === chapterAudio.chapter_id
                                    ? <CircularProgress size={14} color="inherit" />
                                    : undefined
                                }
                                sx={{
                                  borderColor: '#ef6c00',
                                  color: '#e65100',
                                  '&:hover': {
                                    borderColor: '#e65100',
                                    backgroundColor: 'rgba(239, 108, 0, 0.08)',
                                  },
                                }}
                              >
                                {resumingChapterId === chapterAudio.chapter_id ? '提交中...' : '继续生成'}
                              </Button>
                            </Tooltip>
                          )}
                        </Box>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
                          {(() => {
                            const status = chapterAudio.script_status || 'pending'
                            const scriptHasContent = chapterAudio.has_script
                            let label = '剧本：未生成'
                            let bg = 'rgba(158, 158, 158, 0.12)'
                            let color = '#616161'

                            if (status === 'approved') {
                              label = '剧本：已审批'
                              bg = 'rgba(76, 175, 80, 0.15)'
                              color = '#2e7d32'
                            } else if (status === 'reviewed') {
                              label = '剧本：已修改'
                              bg = 'rgba(33, 150, 243, 0.12)'
                              color = '#1565c0'
                            } else if (scriptHasContent) {
                              label = '剧本：已生成'
                              bg = 'rgba(156, 39, 176, 0.10)'
                              color = '#7b1fa2'
                            } else if (status) {
                              label = '剧本：待处理'
                            }

                            return (
                              <Chip
                                label={label}
                                size="small"
                                sx={{
                                  backgroundColor: bg,
                                  color,
                                  fontSize: '0.75rem',
                                  height: 22,
                                }}
                              />
                            )
                          })()}
                          {canResume && (
                            <Chip
                              label={
                                resumeCheckpoint && resumeCheckpoint.total_segments > 0
                                  ? `断点：${resumeCheckpoint.completed_segments}/${resumeCheckpoint.total_segments}`
                                  : '断点：可继续生成'
                              }
                              size="small"
                              sx={{
                                backgroundColor: 'rgba(239, 108, 0, 0.12)',
                                color: '#e65100',
                                fontSize: '0.75rem',
                                height: 22,
                              }}
                            />
                          )}
                          <Chip
                            label={chapterAudio.audio_path ? '音频：已生成' : '音频：未生成'}
                            size="small"
                            sx={{
                              backgroundColor: chapterAudio.audio_path
                                ? 'rgba(156, 39, 176, 0.12)'
                                : 'rgba(189, 189, 189, 0.18)',
                              color: chapterAudio.audio_path ? '#6a1b9a' : '#616161',
                              fontSize: '0.75rem',
                              height: 22,
                            }}
                          />
                        </Box>
                      </Box>
                    )
                  })}
                </Box>
              )}
              
              {activeTaskStatus?.stages?.quality_review && (
                <Button
                  variant="outlined"
                  onClick={handleOpenScriptReviewDialog}
                  sx={{
                    borderColor: '#9c27b0',
                    color: '#9c27b0',
                    '&:hover': {
                      borderColor: '#7b1fa2',
                      backgroundColor: 'rgba(156, 39, 176, 0.08)',
                    },
                  }}
                >
                  查看剧本评审
                </Button>
              )}

              {audiobookProject && (
                <Button
                  variant="outlined"
                  onClick={handleGenerateAudioForApprovedChapters}
                  sx={{
                    borderColor: '#4caf50',
                    color: '#2e7d32',
                    '&:hover': {
                      borderColor: '#2e7d32',
                      backgroundColor: 'rgba(76, 175, 80, 0.08)',
                    },
                  }}
                >
                  对已审批章节生成音频
                </Button>
              )}
              
              <Button
                variant="contained"
                onClick={() => {
                  clearActiveGenerationState()
                  setActiveStep(0)
                  setSelectedProject(null)
                  setAudiobookProject(null)
                  setTaskPointsPrecheckError(null)
                  setBrowserPlayerData(null)
                  setBrowserPlayerOpen(false)
                  audioRef.pause() // 清理播放状态
                  setPlayingChapter(null)
                }}
                sx={{
                  backgroundColor: '#9c27b0',
                  '&:hover': { backgroundColor: '#7b1fa2' },
                }}
              >
                生成新项目
              </Button>
            </Box>
          </Paper>
        )}
      </Container>

      {/* 通知消息 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert 
          onClose={() => setSnackbar({ ...snackbar, open: false })} 
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* 从文本创建项目对话框 */}
      <Dialog
        open={newProjectDialogOpen}
        onClose={() => {
          if (!creatingFromBook) {
            setNewProjectDialogOpen(false)
          }
        }}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>从文本创建新项目</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            粘贴整本书或长篇文本，系统会自动拆分章节并创建项目，随后可以在本页生成有声书。
          </Alert>
          <TextField
            fullWidth
            label="项目名称"
            value={newProjectTitle}
            onChange={(e) => setNewProjectTitle(e.target.value)}
            placeholder="例如：某某小说 有声化项目"
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            multiline
            rows={12}
            label="书籍全文或长篇文本"
            placeholder="将整本书的文本粘贴到这里..."
            value={newProjectText}
            onChange={(e) => setNewProjectText(e.target.value)}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            当前长度：{newProjectText.trim().length.toLocaleString()} 字；系统会自动拆分章节并创建项目。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => !creatingFromBook && setNewProjectDialogOpen(false)} disabled={creatingFromBook}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={handleCreateProjectFromText}
            disabled={creatingFromBook}
            sx={{
              backgroundColor: '#9c27b0',
              '&:hover': { backgroundColor: '#7b1fa2' },
            }}
          >
            {creatingFromBook ? <CircularProgress size={20} color="inherit" /> : '创建并开始配置音色'}
          </Button>
        </DialogActions>
      </Dialog>
      
      {/* 剧本质量评审弹窗 */}
      <Dialog
        open={scriptReviewDialogOpen}
        onClose={handleCloseScriptReviewDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>剧本质量评审</DialogTitle>
        <DialogContent dividers>
          {!scriptReviewData ? (
            <Typography variant="body2" color="text.secondary">
              暂无评审数据
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <ScriptReviewReport review={scriptReviewData.report} />

              <Divider />
              <Divider />

              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                  剧本片段预览（前 {scriptReviewData.segments.length} 段）
                </Typography>
                <Paper
                  variant="outlined"
                  sx={{ maxHeight: 400, overflow: 'auto', p: 1 }}
                >
                  <List dense>
                    {scriptReviewData.segments.map((seg: any) => (
                      <ListItem key={seg.index} alignItems="flex-start" sx={{ mb: 0.5 }}>
                        <ListItemText
                          primary={
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              #{seg.index + 1} [{seg.type === 'dialogue' ? '对白' : seg.type}] {seg.speaker || '旁白'}
                            </Typography>
                          }
                          secondary={
                            <Typography variant="body2" color="text.secondary">
                              {seg.text}
                            </Typography>
                          }
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ mt: 1, display: 'block' }}
                >
                  当前弹窗展示的是自动改编后的有声剧本片段，仅用于人工审核；后续版本会支持直接在此编辑并回写。
                </Typography>
              </Box>
            </Box>
          )}
        </DialogContent>
      <DialogActions>
        <Button onClick={handleCloseScriptReviewDialog}>关闭</Button>
      </DialogActions>
    </Dialog>

      {/* 阶段结果弹窗 */}
      <Dialog
        open={stageMetricsDialogOpen}
        onClose={handleCloseStageMetricsDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {stageMetricsData ? `阶段结果：${stageMetricsData.stage.name}` : '阶段结果'}
        </DialogTitle>
        <DialogContent dividers>
          {!stageMetricsData ? (
            <Typography variant="body2" color="text.secondary">
              暂无阶段数据
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
              <Typography variant="body2" color="text.secondary">
                状态：{STAGE_STATUS_LABELS[stageMetricsData.info.status]}
              </Typography>
              {stageMetricsData.info.message && (
                <Typography variant="body2">提示：{stageMetricsData.info.message}</Typography>
              )}
              {stageMetricsData.info.start_time && (
                <Typography variant="body2" color="text.secondary">
                  开始时间：{stageMetricsData.info.start_time}
                </Typography>
              )}
              {stageMetricsData.info.end_time && (
                <Typography variant="body2" color="text.secondary">
                  结束时间：{stageMetricsData.info.end_time}
                </Typography>
              )}
              {stageMetricsData.info.error_message && (
                <Alert severity="error">{stageMetricsData.info.error_message}</Alert>
              )}
              <Paper
                variant="outlined"
                sx={{ p: 1, backgroundColor: 'rgba(0,0,0,0.02)' }}
              >
                <Box
                  component="pre"
                  sx={{ m: 0, fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}
                >
                  {JSON.stringify(stageMetricsData.info.metrics, null, 2)}
                </Box>
              </Paper>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseStageMetricsDialog}>关闭</Button>
        </DialogActions>
      </Dialog>

      {/* 章节剧本编辑弹窗 */}
      <ScriptEditorDialog
        open={scriptEditorDialogOpen}
        loading={scriptEditorLoading}
        chapter={scriptEditorChapter}
        data={scriptEditorData}
        onClose={handleCloseScriptEditorDialog}
        onChangeSegmentText={handleChangeScriptSegmentText}
        onSaveScript={handleSaveScript}
        onPreviewSegmentAudio={handlePreviewScriptSegmentAudio}
        onRegenerateSegment={handleRegenerateSegment}
        onReviewSegment={handleReviewSegment}
        segmentReviews={segmentReviews}
        segmentPreviewingIndex={segmentPreviewingIndex}
        segmentPreviewingType={segmentPreviewingType}
        segmentAudioUrls={segmentAudioUrls}
        segmentDetailsOpen={segmentDetailsOpen}
        onToggleSegmentDetails={handleToggleSegmentDetails}
        onUpdateSegment={handleUpdateScriptSegment}
        reviewMode={reviewMode}
        onToggleReviewMode={handleToggleReviewMode}
        regeneratingSegments={regeneratingSegments}
        editorConflict={editorCrossTabConflict}
        onApplyIncomingDraft={handleApplyIncomingEditorDraft}
        onKeepLocalDraft={handleKeepLocalEditorDraft}
      />
      
      {/* 新增：历史记录对话框 */}
      <HistoryDialog
            open={showHistory}
            loading={loadingHistory}
            historyProjects={historyProjects}
            selectedProject={selectedProject}
            onCloseHistory={() => setShowHistory(false)}
            onViewHistory={handleViewHistory}
            onDeleteHistory={handleDeleteHistory}
          />

      {browserPlayerData && (
        <BrowserPlayer
          projectData={browserPlayerData}
          open={browserPlayerOpen}
          onClose={handleCloseBrowserPlayer}
        />
      )}

      {/* 章节菜单 */}
      <Menu
        anchorEl={chapterMenuAnchor}
        open={Boolean(chapterMenuAnchor)}
        onClose={handleCloseChapterMenu}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
      >
        <MenuItem onClick={handleOpenDeleteChapterDialog} sx={{ color: '#f44336' }}>
          <DeleteIcon fontSize="small" sx={{ mr: 1 }} />
          删除章节
        </MenuItem>
      </Menu>

      {/* 章节删除确认对话框 */}
      <Dialog
        open={deleteChapterDialogOpen}
        onClose={handleCloseDeleteChapterDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <WarningIcon sx={{ color: '#f44336' }} />
            <Typography variant="h6">确认删除章节</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            此操作将删除章节及其相关数据，请谨慎操作！
          </Alert>
          
          <Typography variant="body1" sx={{ mb: 2 }}>
            确定要删除以下章节吗？
          </Typography>
          
          <Paper variant="outlined" sx={{ p: 2, mb: 2, backgroundColor: 'rgba(244, 67, 54, 0.05)' }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
              {selectedChapterForMenu && `第${selectedChapterForMenu.chapter_number}章 - ${selectedChapterForMenu.title}`}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {selectedChapterForMenu?.content ? `${selectedChapterForMenu.content.slice(0, 100)}...` : '暂无内容'}
            </Typography>
          </Paper>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            删除后将影响以下内容：
          </Typography>
          
          <List dense>
            <ListItem>
              <ListItemText primary="章节内容" secondary="章节的文本内容将被删除" />
            </ListItem>
            <ListItem>
              <ListItemText primary="有声剧本" secondary="已生成的有声剧本将被删除" />
            </ListItem>
            <ListItem>
              <ListItemText primary="音频文件" secondary="已生成的音频文件将被删除（可选）" />
            </ListItem>
            <ListItem>
              <ListItemText primary="章节关联" secondary="章节与角色、设定的关联将被移除" />
            </ListItem>
          </List>

          <TextField
            fullWidth
            multiline
            rows={3}
            label="删除原因（可选）"
            placeholder="请说明删除此章节的原因..."
            value={deleteChapterReason}
            onChange={(e) => setDeleteChapterReason(e.target.value)}
            sx={{ mb: 2 }}
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={deleteChapterFiles}
                onChange={(e) => setDeleteChapterFiles(e.target.checked)}
                sx={{
                  color: '#f44336',
                  '&.Mui-checked': {
                    color: '#f44336',
                  },
                }}
              />
            }
            label="同时删除音频文件（不可恢复）"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteChapterDialog} disabled={deletingChapter}>
            取消
          </Button>
          <Button
            onClick={handleDeleteChapter}
            disabled={deletingChapter}
            variant="contained"
            sx={{
              backgroundColor: '#f44336',
              '&:hover': { backgroundColor: '#d32f2f' },
            }}
          >
            {deletingChapter ? <CircularProgress size={20} color="inherit" /> : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default AudiobookPage
