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
import { useState, useEffect, useMemo, useRef, useCallback, ChangeEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { apiClient, extractApiErrorMessage } from '../services/api'
import * as bookParserApi from '../services/bookParserApi'
import {
  Box,
  Container,
  Typography,
  Button,
  Grid,
  IconButton,
  Chip,
  LinearProgress,
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
import {
  ArrowBack as ArrowBackIcon,
  Headphones as HeadphonesIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Download as DownloadIcon,
  RecordVoiceOver as VoiceIcon,
  GraphicEq as AudioIcon,
  CheckCircle as CheckIcon,
  History as HistoryIcon,
  Delete as DeleteIcon,
  Warning as WarningIcon,
  MoreVert as MoreVertIcon,
} from '@mui/icons-material'

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
  }[]
  audio_fx?: AudioFxConfig | null
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
  segmentPreviewingIndex: number | null
  segmentPreviewingType: PreviewType | null
  segmentAudioUrls: Record<number, string>
  segmentDetailsOpen: Record<number, boolean>
  onToggleSegmentDetails: (index: number) => void
  onUpdateSegment: (index: number, patch: Record<string, any>) => void
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

const DEFAULT_NARRATOR_BY_MODEL = {
  'qwen3-tts-flash': 'Ryan',
  'cosyvoice-v3-plus': 'longanyang',
} as const

const getDefaultNarratorId = (model: 'qwen3-tts-flash' | 'cosyvoice-v3-plus') =>
  DEFAULT_NARRATOR_BY_MODEL[model] || 'Ryan'

const LEGACY_VOICE_ALIASES: Record<string, string> = {
  male_young_energetic: 'Ethan',
  male_young_gentle: 'Vincent',
  male_adult_calm: 'Ryan',
  male_adult_energetic: 'Aiden',
  male_elder_wise: 'Eldric Sage',
  male_warm: 'Vincent',
  male_customer_service: 'Kai',
  male_refreshing: 'Kai',
  male_monkey: 'Nofish',
  male_narrator: 'Ryan',
  male_villain_sinister: 'Aiden',
  female_villain_cold: 'Jennifer',
  female_villain_cunning: 'Katerina',
  female_young_gentle: 'Cherry',
  female_young_energetic: 'Bunny',
  female_young_cute: 'Momo',
  female_adult_elegant: 'Bella',
  female_adult_intellectual: 'Vivian',
  female_capable: 'Jennifer',
  female_elder: 'Chelsie',
  female_intimate: 'Mochi',
  female_lively: 'Mia',
  female_child: 'Momo',
}

const normalizeVoiceId = (
  model: 'qwen3-tts-flash' | 'cosyvoice-v3-plus',
  voiceId?: string | null,
) => {
  if (!voiceId) return ''
  if (model === 'qwen3-tts-flash') {
    return LEGACY_VOICE_ALIASES[voiceId] || voiceId
  }
  const cosyvoiceV3PlusLegacyAliases: Record<string, string> = {
    longanzhi_v3: 'longanyang',
    longanyun_v3: 'longanyang',
    longyichen_v3: 'longanyang',
    longwanjun_v3: 'longanhuan',
    longanwen_v3: 'longanhuan',
  }
  return cosyvoiceV3PlusLegacyAliases[voiceId] || voiceId
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

const AUDIOBOOK_SESSION_STORAGE_KEY = 'audiobook_active_session_v1'

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
  } catch (error) {
    console.warn('无法检测导航类型:', error)
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
  segmentPreviewingIndex,
  segmentPreviewingType,
  segmentAudioUrls,
  segmentDetailsOpen,
  onToggleSegmentDetails,
  onUpdateSegment,
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
          <Box sx={{ display: 'flex', gap: 2 }}>
            {/* 左侧：剧本可编辑列表 */}
            <Box sx={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                剧本片段（支持文本与音频提示词调整）
              </Typography>
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
  const routeProjectId = useMemo(() => {
    const id = Number(projectId)
    return Number.isFinite(id) ? id : null
  }, [projectId])

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
  const [loadingCharacters, setLoadingCharacters] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyProjects, setHistoryProjects] = useState<any[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [scriptReviewDialogOpen, setScriptReviewDialogOpen] = useState(false)
  const [scriptReviewData, setScriptReviewData] = useState<{ report: ScriptReviewDetail; segments: any[] } | null>(null)
  const [stageMetricsDialogOpen, setStageMetricsDialogOpen] = useState(false)
  const [stageMetricsData, setStageMetricsData] = useState<{
    stage: StageConfig
    info: StageInfo
  } | null>(null)
  const [scriptEditorDialogOpen, setScriptEditorDialogOpen] = useState(false)
  const [scriptEditorChapter, setScriptEditorChapter] = useState<{ chapterId: number; title: string } | null>(null)
  const [scriptEditorData, setScriptEditorData] = useState<{
    scriptStatus: string
    scriptSegments: any[]
    scriptReview: any | null
  } | null>(null)
  const [scriptEditorLoading, setScriptEditorLoading] = useState(false)
  const [segmentPreviewingIndex, setSegmentPreviewingIndex] = useState<number | null>(null)
  const [segmentPreviewingType, setSegmentPreviewingType] = useState<PreviewType | null>(null)
  const [segmentAudioUrls, setSegmentAudioUrls] = useState<Record<number, string>>({})
  const [segmentDetailsOpen, setSegmentDetailsOpen] = useState<Record<number, boolean>>({})
  const [scriptOnlyMode, setScriptOnlyMode] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [currentAudiobookProjectId, setCurrentAudiobookProjectId] = useState<number | null>(null)
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
  const [voicePresets, setVoicePresets] = useState<VoicePreset[]>([])
  const [voiceCatalogMeta, setVoiceCatalogMeta] = useState<VoiceCatalogMeta | null>(null)
  const [voiceLoading, setVoiceLoading] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)

  const [cloneName, setCloneName] = useState('')
  const [cloneUrl, setCloneUrl] = useState('')
  const [cloneLoading, setCloneLoading] = useState(false)
  const [cloneUploading, setCloneUploading] = useState(false)
  const [cloneRecording, setCloneRecording] = useState(false)
  const [cloneRecordDialogOpen, setCloneRecordDialogOpen] = useState(false)
  const [cloneDeletingId, setCloneDeletingId] = useState<string | null>(null)
  const [cloneError, setCloneError] = useState<string | null>(null)
  const [cloneSuccess, setCloneSuccess] = useState<string | null>(null)
  const [autoAssigningVoices, setAutoAssigningVoices] = useState(false)
  const [creatingFromBook, setCreatingFromBook] = useState(false)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only'>('full')
  const [activeStep, setActiveStep] = useState(0)
  const [ttsModel, setTtsModel] = useState<'qwen3-tts-flash' | 'cosyvoice-v3-plus'>('qwen3-tts-flash')
  const supportsTtsTuning = ttsModel === 'cosyvoice-v3-plus'
  const [voiceDraftsByModel, setVoiceDraftsByModel] = useState<Record<string, CharacterVoiceSetting[]>>({})
  const [chapterMenuAnchor, setChapterMenuAnchor] = useState<null | HTMLElement>(null)
  const [selectedChapterForMenu, setSelectedChapterForMenu] = useState<Chapter | null>(null)
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [deleteChapterReason, setDeleteChapterReason] = useState('')
  const [deleteChapterFiles, setDeleteChapterFiles] = useState(false)
  const [deletingChapter, setDeletingChapter] = useState(false)

  const audioRef = useMemo(() => new Audio(), [])
  const sessionHydratedRef = useRef(false)
  const cloneRecorderRef = useRef<MediaRecorder | null>(null)
  const cloneStreamRef = useRef<MediaStream | null>(null)
  const cloneChunksRef = useRef<Blob[]>([])
  const navigationTypeRef = useRef<NavigationType>(typeof window === 'undefined' ? null : detectNavigationType())
  const selectedProjectId = selectedProject?.id ?? null
  const activeTaskStatus = useMemo(() => {
    if (currentTaskId && taskStatuses[currentTaskId]) {
      return taskStatuses[currentTaskId]
    }
    const first = Object.values(taskStatuses)[0]
    return first || null
  }, [currentTaskId, taskStatuses])

  const setCharacterVoicesForModel = (
    model: 'qwen3-tts-flash' | 'cosyvoice-v3-plus',
    next: CharacterVoiceSetting[],
  ) => {
    setCharacterVoices(next)
    setVoiceDraftsByModel((prev) => ({ ...prev, [model]: next }))
  }

  const setCharacterVoicesForCurrentModel = useCallback(
    (next: CharacterVoiceSetting[]) => {
      setCharacterVoicesForModel(ttsModel, next)
    },
    [ttsModel],
  )

  const updateCharacterVoicesForCurrentModel = (
    updater: (prev: CharacterVoiceSetting[]) => CharacterVoiceSetting[],
  ) => {
    setCharacterVoices((prev) => {
      const next = updater(prev)
      setVoiceDraftsByModel((drafts) => ({ ...drafts, [ttsModel]: next }))
      return next
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

  const cloneVoicePresets = useMemo(() => {
    if (ttsModel !== 'cosyvoice-v3-plus') {
      return []
    }
    return currentVoicePresets.filter((preset) => preset.category === 'custom')
  }, [currentVoicePresets, ttsModel])

  // 从URL参数加载项目（优先级最高，但会尝试保留会话状态）
  useEffect(() => {
    const loadProjectFromUrl = async () => {
      if (!projectId) {
        setSnackbar({ open: true, message: '缺少项目ID参数', severity: 'error' })
        navigate('/audiobook-dashboard')
        return
      }

      // 检查是否需要清除会话缓存
      const savedSession = localStorage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)
      if (savedSession) {
        try {
          const saved = JSON.parse(savedSession)
          // 如果URL中的projectId与保存的projectId相同，则不清除会话缓存
          if (saved.projectId === parseInt(projectId)) {
            console.log('项目ID匹配，保留会话状态')
            // 恢复会话状态中的activeStep
            if (typeof saved.activeStep === 'number') {
              console.log('恢复activeStep:', saved.activeStep)
              setActiveStep(saved.activeStep)
            }
            if (saved.taskId) {
              setCurrentTaskId(saved.taskId)
              setGenerating(saved.generating ?? true)
            }
            if (saved.ttsModel) {
              setTtsModel(saved.ttsModel)
            }
            // 恢复audiobookProject（如果存在）
            if (saved.audiobookProjectId) {
              setCurrentAudiobookProjectId(saved.audiobookProjectId)
              // 异步加载audiobookProject
              apiClient.getAudiobookProject(saved.audiobookProjectId)
                .then(detailRes => {
                  setAudiobookProject(detailRes.data)
                  console.log('恢复audiobookProject:', detailRes.data)
                })
                .catch(error => {
                  console.warn('恢复有声书项目失败:', error)
                })
            }
            // 设置标志，防止restoreSession effect重复执行
            sessionHydratedRef.current = true
          } else {
            console.log('项目ID不匹配，清除旧会话缓存')
            localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
            sessionHydratedRef.current = true
          }
        } catch (e) {
          console.warn('解析会话数据失败，清除缓存:', e)
          localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
          sessionHydratedRef.current = true
        }
      } else {
        sessionHydratedRef.current = true
      }

      try {
        const projectRes = await apiClient.getProject(parseInt(projectId))
        const project = projectRes.data as Project
        setSelectedProject(project)
        await handleSelectProject(project, { skipStepReset: true })
      } catch (error: any) {
        console.error('加载项目失败:', error)
        const msg = await extractApiErrorMessage(error, '加载项目失败')
        setSnackbar({ open: true, message: msg, severity: 'error' })
        navigate('/audiobook-dashboard')
      }
    }

    loadProjectFromUrl()
  }, [projectId])

  // 同步当前 TTS 模型的音色目录
  useEffect(() => {
    fetchVoiceCatalog()
  }, [ttsModel])

  const fetchVoiceCatalog = async () => {
    setVoiceLoading(true)
    try {
      const res = await apiClient.getTtsVoices(ttsModel)
      const data = res.data || {}
      const voicesFromApi = (data.voices || []) as VoicePreset[]
      const normalized = voicesFromApi.map((voice) => ({
        ...voice,
        supportsInstruct: Boolean(voice.supportsInstruct),
      }))
      setVoicePresets(normalized)
      setVoiceCatalogMeta({
        model: data.model,
        updated_at: data.updated_at,
        source: data.source,
        voice_count: data.voice_count || normalized.length,
      })
      setVoiceError(null)
    } catch (error: any) {
      console.error('加载音色库失败:', error)
      const message = await extractApiErrorMessage(error, '加载音色库失败')
      setVoiceError(message)
    } finally {
      setVoiceLoading(false)
    }
  }

  const handleCreateCloneVoice = async () => {
    setCloneLoading(true)
    setCloneError(null)
    setCloneSuccess(null)
    try {
      const name = cloneName.trim()
      const url = cloneUrl.trim()
      const res = await apiClient.createCosyVoiceV3PlusClone({ name, url })
      const voiceId = (res.data?.voice_id as string) || ''
      setCloneSuccess(voiceId ? `已提交复刻任务：${voiceId}` : '已提交复刻任务')
      setCloneName('')
      setCloneUrl('')
      await fetchVoiceCatalog()
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '创建复刻音色失败')
      setCloneError(message)
    } finally {
      setCloneLoading(false)
    }
  }

  const handleDeleteCloneVoice = async (voiceId: string, label?: string) => {
    if (!voiceId || cloneDeletingId) return
    const displayName = label || voiceId
    if (!confirm(`确定要删除复刻音色「${displayName}」吗？\n\n该操作会从当前账号移除该复刻音色，无法恢复。`)) {
      return
    }
    setCloneDeletingId(voiceId)
    setCloneError(null)
    setCloneSuccess(null)
    try {
      await apiClient.deleteCosyVoiceV3PlusClone(voiceId)
      updateCharacterVoicesForCurrentModel((prev) =>
        prev.map((item) => (item.voiceId === voiceId ? { ...item, voiceId: '' } : item)),
      )
      setCloneSuccess(`已删除复刻音色：${displayName}`)
      await fetchVoiceCatalog()
    } catch (error: any) {
      const message = await extractApiErrorMessage(error, '删除复刻音色失败')
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

  const loadProjectVoiceConfig = async (
    projectId: number,
    model: 'qwen3-tts-flash' | 'cosyvoice-v3-plus',
  ) => {
    const baseNarratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: getDefaultNarratorId(model),
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }

    setLoadingCharacters(true)
    try {
      const [charactersRes, audioConfigRes] = await Promise.all([
        apiClient.getCharacters(projectId),
        apiClient.getProjectAudioConfig(projectId, model),
      ])

      const charactersData = charactersRes.data || []
      const projectAudioConfig = (audioConfigRes.data || { characters: [] }) as ProjectAudioConfig
      const savedCharacters = projectAudioConfig?.characters || []
      const savedFx = projectAudioConfig?.audio_fx || null

      const characterVoicesFromApi: CharacterVoiceSetting[] = charactersData.map((c: any) => {
        const saved = savedCharacters.find((sc) => sc.character_id === c.id)
        return {
          characterId: c.id,
          name: c.name,
          gender: c.gender,
          role: c.role,
          voiceId: normalizeVoiceId(model, saved?.voice_id),
          volume: saved?.volume ?? 50,
          speed: saved?.speed ?? 1.0,
          pitch: saved?.pitch ?? 50,
        }
      })

      const narratorSaved = savedCharacters.find((sc) => sc.character_id === 0 || sc.name === '旁白')
      const narratorVoice: CharacterVoiceSetting = {
        ...baseNarratorVoice,
        voiceId: normalizeVoiceId(model, narratorSaved?.voice_id) || baseNarratorVoice.voiceId,
        volume: narratorSaved?.volume ?? baseNarratorVoice.volume,
        speed: narratorSaved?.speed ?? baseNarratorVoice.speed,
        pitch: narratorSaved?.pitch ?? baseNarratorVoice.pitch,
      }

      const initialVoices: CharacterVoiceSetting[] = [narratorVoice, ...characterVoicesFromApi]
      setCharacterVoicesForModel(model, initialVoices)

      if (savedFx) {
        setAudioFxConfig({
          enable_sound_effects: savedFx.enable_sound_effects ?? true,
          enable_music: savedFx.enable_music ?? true,
          sound_effect_density: (savedFx.sound_effect_density as AudioFxConfig['sound_effect_density']) || 'medium',
          music_density: (savedFx.music_density as AudioFxConfig['music_density']) || 'medium',
        })
      }
    } catch (error) {
      console.error('加载项目音色配置失败:', error)
      setCharacterVoicesForModel(model, [baseNarratorVoice])
    } finally {
      setLoadingCharacters(false)
    }
  }

  const handleTtsModelChange = async (nextModel: 'qwen3-tts-flash' | 'cosyvoice-v3-plus') => {
    if (nextModel === ttsModel) return

    // 保留当前模型的未保存草稿
    setVoiceDraftsByModel((prev) => ({ ...prev, [ttsModel]: characterVoices }))

    setTtsModel(nextModel)

    if (!selectedProject) return

    const cached = voiceDraftsByModel[nextModel]
    if (cached && cached.length > 0) {
      setCharacterVoicesForModel(nextModel, cached)
      return
    }

    await loadProjectVoiceConfig(selectedProject.id, nextModel)
  }

  // 新增：获取历史记录
  const fetchHistory = async () => {
    if (!selectedProject) return

    setLoadingHistory(true)
    try {
      const res = await apiClient.getAudiobookProjectsByProject(selectedProject.id)
      setHistoryProjects(res.data)
    } catch (error) {
      console.error('获取历史记录失败:', error)
    } finally {
      setLoadingHistory(false)
    }
  }
  
  // 新增：查看历史项目详情
  const handleViewHistory = async (audiobookProjectId: number) => {
    try {
      const res = await apiClient.getAudiobookProject(audiobookProjectId)
      const data = res.data
      setAudiobookProject(data)
      setCurrentAudiobookProjectId(data.id)
      setActiveStep(2) // 跳转到完成页面
      setShowHistory(false)
    } catch (error) {
      console.error('查看历史失败:', error)
      setSnackbar({ open: true, message: '加载失败', severity: 'error' })
    }
  }
  
  // 新增：删除历史项目
  const handleDeleteHistory = async (audiobookProjectId: number) => {
    try {
      await apiClient.deleteAudiobookProject(audiobookProjectId, { delete_files: true })
      setSnackbar({ open: true, message: '项目已删除', severity: 'success' })
      // 重新获取历史记录以更新列表
      await fetchHistory()
    } catch (error: any) {
      console.error('删除历史失败:', error)
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

    // 如果一次输入过多，则跳转到拆书页面，由拆书工具完成后续流程
    const TOO_LONG_THRESHOLD = 10000
    if (rawText.length > TOO_LONG_THRESHOLD) {
      setNewProjectDialogOpen(false)
      navigate('/book-parser', {
        state: {
          openUpload: true,
          prefillTitle: title,
          prefillContent: rawText,
        },
      })
      return
    }

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
        setSelectedProject(project)
      } catch (e) {
        // 回退：如果获取单个项目失败，至少构造一个最小的项目对象
        const fallbackProject: Project = {
          id: importResult.project_id,
          title: importResult.project_title || title,
          description: undefined,
          genre: undefined,
        }
        setSelectedProject(fallbackProject)
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
      console.error('从文本创建项目失败:', error)
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
  type SelectProjectOptions = { skipStepReset?: boolean }

  const handleSelectProject = useCallback(async (project: Project, options?: SelectProjectOptions) => {
    setSelectedProject(project)
    setCurrentAudiobookProjectId(null)
    setCurrentTaskId(null)
    setTaskStatuses({})
    setCharacterVoices([])
    setVoiceDraftsByModel({})

    const baseNarratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: getDefaultNarratorId(ttsModel),
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }
    
    try {
      // 获取章节列表
      const chaptersRes = await apiClient.getChapters(project.id)
      const chaptersData = chaptersRes.data
      setChapters(chaptersData)
      setSelectedChapters(chaptersData.map((c: Chapter) => c.id))  // 默认全选

      // 获取角色列表（用于音频配置）
      setLoadingCharacters(true)
      try {
        const charactersRes = await apiClient.getCharacters(project.id)
        const charactersData = charactersRes.data
      
        // 尝试读取项目级音频配置（角色音 + 音效/BGM）
        let projectAudioConfig: ProjectAudioConfig | null = null
        try {
          const audioConfigRes = await apiClient.getProjectAudioConfig(project.id, ttsModel)
          projectAudioConfig = audioConfigRes.data
        } catch (e) {
          console.warn('获取项目音频配置失败:', e)
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
            voiceId: normalizeVoiceId(ttsModel, saved?.voice_id),
            volume: saved?.volume ?? 50,
            speed: saved?.speed ?? 1.0,
            pitch: saved?.pitch ?? 50,
          }
        })
      
        // 旁白使用 character_id 为 0 或 name 为"旁白"的配置（如有）
        const narratorSaved = savedCharacters.find(
          (sc) => sc.character_id === 0 || sc.name === '旁白'
        )
        const narratorVoice: CharacterVoiceSetting = {
          ...baseNarratorVoice,
          voiceId: normalizeVoiceId(ttsModel, narratorSaved?.voice_id) || baseNarratorVoice.voiceId,
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
      } catch (error) {
        console.error('获取角色列表失败:', error)
        setCharacterVoices([baseNarratorVoice])
      } finally {
        setLoadingCharacters(false)
      }

      if (!options?.skipStepReset) {
        setActiveStep(0)
      }
    } catch (error) {
      console.error('获取章节失败:', error)
      setSnackbar({ open: true, message: '网络错误，请重试', severity: 'error' })
    }
  }, [ttsModel, setCharacterVoicesForCurrentModel])

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
    handleCloseChapterMenu()
    setDeleteChapterDialogOpen(true)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
  }

  const handleCloseDeleteChapterDialog = () => {
    setDeleteChapterDialogOpen(false)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
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
      console.error('删除章节失败:', error)
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
      return
    }

    const payload = {
      projectId: selectedProjectId,
      audiobookProjectId: currentAudiobookProjectId,
      taskId: currentTaskId,
      activeStep,
      generating,
      ttsModel,
    }
    localStorage.setItem(AUDIOBOOK_SESSION_STORAGE_KEY, JSON.stringify(payload))
  }, [selectedProjectId, currentAudiobookProjectId, currentTaskId, activeStep, generating, ttsModel])

  useEffect(() => {
    if (sessionHydratedRef.current) {
      return
    }

    const navType = navigationTypeRef.current
    const shouldRestore = navType === 'reload' || navType === 'back_forward' || isSamePathReferrer()
    if (!shouldRestore) {
      localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
      sessionHydratedRef.current = true
      return
    }

    let cancelled = false

    const restoreSession = async () => {
      const raw = localStorage.getItem(AUDIOBOOK_SESSION_STORAGE_KEY)
      if (!raw) {
        sessionHydratedRef.current = true
        return
      }

      try {
        const saved = JSON.parse(raw)

        if (saved.ttsModel && saved.ttsModel !== ttsModel) {
          setTtsModel(saved.ttsModel)
        }

        if (saved.projectId && !cancelled) {
          try {
            const projectRes = await apiClient.getProject(saved.projectId)
            if (!cancelled) {
              await handleSelectProject(projectRes.data, { skipStepReset: true })
            }
          } catch (error) {
            console.warn('恢复项目失败:', error)
          }
        }

        if (saved.audiobookProjectId && !cancelled) {
          setCurrentAudiobookProjectId(saved.audiobookProjectId)
          try {
            const detailRes = await apiClient.getAudiobookProject(saved.audiobookProjectId)
            if (!cancelled) {
              setAudiobookProject(detailRes.data)
            }
          } catch (error) {
            console.warn('恢复有声书项目失败:', error)
          }
        }

        if (saved.taskId && !cancelled) {
          setCurrentTaskId(saved.taskId)
          setGenerating(saved.generating ?? true)
          setActiveStep(saved.activeStep ?? 0)
        } else if (typeof saved.activeStep === 'number' && !cancelled) {
          setActiveStep(saved.activeStep)
        }
      } catch (error) {
        console.warn('恢复会话失败:', error)
        localStorage.removeItem(AUDIOBOOK_SESSION_STORAGE_KEY)
      } finally {
        if (!cancelled) {
          sessionHydratedRef.current = true
        }
      }
    }

    restoreSession()

    return () => {
      cancelled = true
    }
  }, [handleSelectProject, ttsModel])

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
    } catch (err) {
      console.error('? 自动推荐声线失败:', err)
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

      const res = await apiClient.previewTTS({
        text,
        voice_id: cv.voiceId,
        volume: cv.volume,
        speed: cv.speed,
        pitch: cv.pitch,
        model: ttsModel,
      })

      const blob = res.data as Blob
      const url = window.URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.play()
      audio.onended = () => {
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('角色音试听失败:', error)
      setSnackbar({ open: true, message: await extractApiErrorMessage(error, '角色音试听失败，请稍后重试'), severity: 'error' })
    } finally {
      setPreviewingCharacterId(null)
    }
  }

  // 新增：下载音频
  const handleDownloadAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(
        `/api/v1/audiobook/download/${audiobookProject.id}/${chapterId}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        }
      )
      
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        
        // 从 Content-Disposition 获取文件名
        const contentDisposition = response.headers.get('Content-Disposition')
        let filename = `chapter_${chapterId}.mp3`
        if (contentDisposition) {
          const match = contentDisposition.match(/filename\*=UTF-8''(.+)/)
          if (match) {
            filename = decodeURIComponent(match[1])
          }
        }
        
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        
        setSnackbar({ open: true, message: '音频下载成功', severity: 'success' })
      } else {
        throw new Error('下载失败')
      }
    } catch (error) {
      console.error('下载音频失败:', error)
      setSnackbar({ open: true, message: '? 下载失败，请重试', severity: 'error' })
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
      
      // 通过 fetch 获取音频数据（带 Authorization header）
      const token = localStorage.getItem('access_token')
      const response = await fetch(
        `/api/v1/audiobook/stream/${audiobookProject.id}/${chapterId}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        }
      )
      
      if (!response.ok) {
        throw new Error('加载音频失败')
      }
      
      // 创建 Blob URL
      const blob = await response.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      
      // 设置新的音频源
      audioRef.src = blobUrl
      
      // 播放
      await audioRef.play()
      setPlayingChapter(chapterId)
      
      // 播放结束后重置状态并释放 Blob URL
      audioRef.onended = () => {
        setPlayingChapter(null)
        window.URL.revokeObjectURL(blobUrl)
      }
      
        setSnackbar({ open: true, message: '开始播放', severity: 'success' })
    } catch (error) {
      console.error('播放音频失败:', error)
      setSnackbar({ open: true, message: '? 播放失败，请重试', severity: 'error' })
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
      console.error('生成片段音频失败:', error)
      setSnackbar({
        open: true,
        message: extractApiErrorMessage(error) || '生成片段音频失败，请重试',
        severity: 'error',
      })
    } finally {
      setSegmentPreviewingIndex(null)
      setSegmentPreviewingType(null)
    }
  }

  // 打开章节剧本编辑器
  const handleOpenScriptEditor = async (chapterId: number) => {
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
      console.error('获取章节剧本失败:', err)
      setSnackbar({ open: true, message: err.message || '获取章节剧本失败', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }

  const handleCloseScriptEditorDialog = () => {
    resetSegmentPreviewState()
    audioRef.pause()
    setScriptEditorDialogOpen(false)
    setScriptEditorData(null)
    setScriptEditorChapter(null)
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

    try {
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

      setSnackbar({ open: true, message: '剧本已保存', severity: 'success' })

      // 可选：保存并生成该章节音频
      if (options.generateAudio) {
        await apiClient.generateAudioFromScripts(audiobookProject.id, {
          chapter_ids: [scriptEditorChapter.chapterId],
          tts_model: ttsModel,
        })
        setSnackbar({ open: true, message: '已触发该章节音频生成', severity: 'success' })
      }

      // 保存后不自动关闭，方便继续修改；如需可在此关闭
      // handleCloseScriptEditorDialog()
    } catch (err: any) {
      console.error('保存/生成失败:', err)
      setSnackbar({ open: true, message: err.message || '保存失败', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }

  const handleGenerateAudioForApprovedChapters = async () => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先完成剧本生成', severity: 'error' })
      return
    }

    try {
      const res = await apiClient.generateAudioFromScripts(audiobookProject.id, {
        tts_model: ttsModel,
      })

      if (res.status !== 200) {
        throw new Error('触发音频生成失败')
      }

      setSnackbar({
        open: true,
        message: '已触发所有已审批章节的音频生成，请稍候在历史记录或本页刷新查看结果',
        severity: 'success',
      })
    } catch (err: any) {
      console.error('批量生成音频失败:', err)
      setSnackbar({
        open: true,
        message: err.message || '批量生成音频失败，请稍后重试',
        severity: 'error',
      })
    }
  }

  // 开始生成
  const handleGenerate = async () => {
    if (generating) return

    if (selectedChapters.length === 0) {
      setSnackbar({ open: true, message: '请至少选择一个章节', severity: 'error' })
      return
    }

    const projectIdForRequest = selectedProject?.id ?? routeProjectId
    if (!projectIdForRequest) {
      setSnackbar({ open: true, message: '项目尚未加载完成，请稍后重试', severity: 'error' })
      return
    }
    
    setGenerating(true)
    setActiveStep(1)
    setLastGenerationMode(scriptOnlyMode ? 'script_only' : 'full')
    setTaskStatuses({})  // 清空之前的状态

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
              voice_id: cv.voiceId || getDefaultNarratorId(ttsModel),
              volume: cv.volume,
              speed: cv.speed,
              pitch: cv.pitch,
            })),
          audio_fx: audioFxConfig,
        }

        try {
          await apiClient.updateProjectAudioConfig(projectIdForRequest, projectAudioConfigBody, ttsModel)
        } catch (err) {
          console.warn('保存项目音频配置失败:', err)
        }
      }

      const voiceConfigPayload =
        characterVoices
          .filter((cv) => cv.voiceId || cv.name === '旁白')  // 修复：旁白即使 voiceId 为空也保留
          .map((cv) => ({
            character_name: cv.name,
            voice_id: cv.voiceId || getDefaultNarratorId(ttsModel),
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
      })

      const data = response.data
      if (data?.audiobook_project_id) {
        setCurrentAudiobookProjectId(data.audiobook_project_id)
      }
      if (data?.job_id) {
        setCurrentTaskId(data.job_id)
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
          console.log('轮询项目状态:', statusData)

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
        } catch (err) {
          console.error('轮询有声书项目状态失败:', err)
        }
      }, 2000) // 每2秒查询一次
    } catch (error: any) {
      console.error('生成失败:', error)
      setSnackbar({ 
        open: true, 
        message: error.message || '生成失败，请重试', 
        severity: 'error' 
      })
      setGenerating(false)
      setActiveStep(0)
    }
  }
  
  // 新增：轮询任务列表以获取当前任务ID（避免依赖 chapter_audios）
  useEffect(() => {
    if (currentTaskId || !currentAudiobookProjectId || !generating) {
      return
    }

    let cancelled = false

    const pollTaskList = async () => {
      try {
        const response = await fetch('/api/v1/audiobook/tasks', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (!response.ok) {
          console.error('查询任务列表失败:', response.status, response.statusText)
          return
        }

        const rawTasks = await response.json()
        const normalizedTasks: TaskStatus[] = rawTasks.map((task: any) => normalizeTaskStatusResponse(task))
        const matched = normalizedTasks.find(
          (task) =>
            task.audiobook_project_id === currentAudiobookProjectId &&
            (task.status === 'running' || task.status === 'pending')
        )

        if (matched && !cancelled) {
          setTaskStatuses((prev) => ({
            ...prev,
            [matched.task_id]: matched,
          }))
          setCurrentTaskId(matched.task_id)
        }
      } catch (error) {
        console.error('查询任务列表异常:', error)
      }
    }

    pollTaskList()
    const intervalId = setInterval(pollTaskList, 2000)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [generating, currentTaskId, currentAudiobookProjectId])
  
  // 新增：轮询单个任务状态（用于实时显示8个阶段）
  useEffect(() => {
    if (!currentTaskId) {
      return
    }

    if (activeTaskStatus && (activeTaskStatus.status === 'completed' || activeTaskStatus.status === 'failed')) {
      return
    }

    let cancelled = false

    const pollTaskStatus = async () => {
      try {
        const response = await fetch(`/api/v1/audiobook/tasks/${currentTaskId}/status`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (response.ok) {
          const raw = await response.json()
          const normalized = normalizeTaskStatusResponse(raw)
          if (cancelled) return
          setTaskStatuses((prev) => ({
            ...prev,
            [normalized.task_id]: normalized,
          }))
          if (!currentAudiobookProjectId && normalized.audiobook_project_id) {
            setCurrentAudiobookProjectId(normalized.audiobook_project_id)
          }
          if (normalized.status === 'completed') {
            setGenerating(false)
            setActiveStep(2)
            setSnackbar({ open: true, message: '生成完成！', severity: 'success' })
            setCurrentTaskId(null)
          } else if (normalized.status === 'failed') {
            setGenerating(false)
            setActiveStep(0)
            setSnackbar({ open: true, message: '生成失败，请重试', severity: 'error' })
            setCurrentTaskId(null)
          } else {
            setGenerating(true)
          }
        } else if (response.status === 404) {
          console.warn('任务不存在，停止轮询')
          setGenerating(false)
          setCurrentTaskId(null)
        } else {
          console.error('查询任务状态失败:', response.status, response.statusText)
        }
      } catch (error) {
        console.error('查询任务状态异常:', error)
      }
    }

    pollTaskStatus()
    const intervalId = setInterval(pollTaskStatus, 2000)

    return () => {
      cancelled = true
      clearInterval(intervalId)
    }
  }, [currentTaskId, activeTaskStatus?.status, currentAudiobookProjectId])
  
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

            {/* TTS 模型选择 */}
            <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <FormControl size="small" sx={{ minWidth: 260 }}>
                <InputLabel>TTS 模型</InputLabel>
                <Select
                  label="TTS 模型"
                  value={ttsModel}
                  onChange={(e) =>
                    handleTtsModelChange(e.target.value as 'qwen3-tts-flash' | 'cosyvoice-v3-plus')
                  }
                >
                  <MenuItem value="qwen3-tts-flash">
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <span>Qwen3-TTS Flash</span>
                      <Tooltip title="高性价比，速度快，适合大规模章节生成，价格较低">
                        <Chip
                          label="价格：低"
                          size="small"
                          color="success"
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                      </Tooltip>
                    </Box>
                  </MenuItem>
                  <MenuItem value="cosyvoice-v3-plus">
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <span>CosyVoice v3-plus</span>
                      <Tooltip title="音质更好，支持零样本声音复刻，更适合重要章节和精细角色，价格较高">
                        <Chip
                          label="价格：高"
                          size="small"
                          color="error"
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                      </Tooltip>
                    </Box>
                  </MenuItem>
                </Select>
              </FormControl>

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
                  {(voiceCatalogMeta.model || 'Qwen3-TTS Flash')}：官方 {voiceCatalogMeta.voice_count ?? currentVoicePresets.length} 种音色，最近更新 {voiceCatalogMeta.updated_at || '—'}，覆盖普通话/多语种/方言。
                </Typography>
              )}
              <Alert severity="success" sx={{ mb: 1 }}>
                Qwen3-TTS Flash 支持快速批量合成、指令式情感（Ethan/Sunny）与多语种/方言音色，适合整本生成；CosyVoice 保留为精品章节备用。
              </Alert>
              {ttsModel === 'cosyvoice-v3-plus' && (
                <>
                  <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
                    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                      声音复刻（CosyVoice v3-plus）
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      支持 http/https 或 oss:// 临时 URL（有效期 48 小时）；系统会自动生成合规 prefix（最长 10 个字符），并用你的“命名”在列表里展示为 “复刻-命名”（状态 OK 后可用于合成）。
                    </Typography>
                    <Grid container spacing={1}>
                      <Grid item xs={12} md={4}>
                        <TextField
                          size="small"
                          fullWidth
                          label="声音名称"
                          value={cloneName}
                          onChange={(e) => setCloneName(e.target.value)}
                          disabled={cloneLoading || cloneUploading || cloneRecording}
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <TextField
                          size="small"
                          fullWidth
                          label="音频 URL（http/https 或 oss://）"
                          value={cloneUrl}
                          onChange={(e) => setCloneUrl(e.target.value)}
                          disabled={cloneLoading || cloneUploading || cloneRecording}
                        />
                      </Grid>
                      <Grid item xs={12} md={2}>
                        <Button
                          fullWidth
                          variant="contained"
                          onClick={handleCreateCloneVoice}
                          disabled={cloneLoading || cloneUploading || cloneRecording || !cloneName.trim() || !cloneUrl.trim()}
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
                            disabled={cloneLoading || cloneUploading || cloneRecording}
                          >
                            录音
                          </Button>
                          <Button
                            variant="outlined"
                            component="label"
                            disabled={cloneLoading || cloneUploading || cloneRecording}
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
                    {cloneVoicePresets.length > 0 && (
                      <Box sx={{ mt: 1 }}>
                        <Divider sx={{ mb: 1 }} />
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                          已复刻音色（可删除）
                        </Typography>
                        <List dense>
                          {cloneVoicePresets.map((preset) => (
                            <ListItem
                              key={preset.id}
                              secondaryAction={
                                <Button
                                  color="error"
                                  size="small"
                                  disabled={cloneDeletingId === preset.id || cloneLoading || cloneUploading}
                                  onClick={() => handleDeleteCloneVoice(preset.id, preset.label)}
                                >
                                  {cloneDeletingId === preset.id ? '删除中...' : '删除'}
                                </Button>
                              }
                            >
                              <ListItemText
                                primary={preset.label || preset.id}
                                secondary={preset.description || preset.id}
                              />
                            </ListItem>
                          ))}
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
                              {cv.voiceId && (
                                <Chip
                                  label="已配置"
                                  size="small"
                                  color="success"
                                  sx={{ height: 20 }}
                                />
                              )}
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
                                    <MenuItem disabled value="__empty">暂无官方音色，请稍后重试</MenuItem>
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
                                      {ttsModel === 'cosyvoice-v3-plus' && preset.supportsInstruct && (
                                        <Tooltip title="该音色支持 Instruct/SSML（CosyVoice v3-plus）。情绪/语气可通过 Instruct 参数控制。">
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
              {/* 下载按钮 - 支持分章节下载 */}
              {audiobookProject && audiobookProject.chapter_audios && audiobookProject.chapter_audios.length > 0 && (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center', width: '100%', mb: 2 }}>
                  {audiobookProject.chapter_audios.map((chapterAudio: any) => {
                    const chapter = chapters.find(c => c.id === chapterAudio.chapter_id)
                    const isPlaying = playingChapter === chapterAudio.chapter_id
                    
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
                  setActiveStep(0)
                  setSelectedProject(null)
                  setAudiobookProject(null)
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
            当前长度：{newProjectText.trim().length.toLocaleString()} 字；超过 10,000 字时，点击「创建并开始配置音色」会自动跳转到拆书工具。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => !creatingFromBook && setNewProjectDialogOpen(false)} disabled={creatingFromBook}>
            取消
          </Button>
          <Button
            onClick={() => {
              const text = newProjectText.trim()
              const title = newProjectTitle.trim() || '从耳畔星河导入的书籍'
              setNewProjectDialogOpen(false)
              navigate('/book-parser', {
                state: {
                  openUpload: true,
                  prefillTitle: title,
                  prefillContent: text,
                  from: 'audiobook',
                },
              })
            }}
            disabled={creatingFromBook}
          >
            导入整本书到拆书工具
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
        segmentPreviewingIndex={segmentPreviewingIndex}
        segmentPreviewingType={segmentPreviewingType}
        segmentAudioUrls={segmentAudioUrls}
        segmentDetailsOpen={segmentDetailsOpen}
        onToggleSegmentDetails={handleToggleSegmentDetails}
        onUpdateSegment={handleUpdateScriptSegment}
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
