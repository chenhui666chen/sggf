import { useEffect, useState } from 'react'
import AddPhotoAlternateOutlinedIcon from '@mui/icons-material/AddPhotoAlternateOutlined'
import BoltOutlinedIcon from '@mui/icons-material/BoltOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  FormHelperText,
  InputLabel as MuiInputLabel,
  MenuItem,
  Select as MuiSelect,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { InputLabelProps, SelectProps, SxProps, Theme } from '@mui/material'
import type { SystemStyleObject } from '@mui/system'

import { apiClient, extractApiErrorMessage } from '@/services/api'

import AssetStudioVisionReviewPanel from './AssetStudioVisionReviewPanel'
import type { AssetStudioVisionReusePayload } from './AssetStudioVisionReviewPanel'
import type { AssetStudioTabId, ModelUseEntry } from './modelEntryData'

interface AssetStudioWorkbenchProps {
  activeTabId: AssetStudioTabId
  entries: ModelUseEntry[]
  onRequestTabChange?: (tabId: AssetStudioTabId) => void
}

interface AssetStudioGenerateResponse {
  kind: string
  mode: string
  model_id: string
  outputs: string[]
  primary_output?: string | null
  metadata?: Record<string, any>
}

const IMAGE_SIZE_OPTIONS: SizeOption[] = [
  { label: '1K 方图', width: 1024, height: 1024, value: '1024x1024' },
  { label: '2K 竖图', width: 1536, height: 2048, value: '1536x2048' },
  { label: '宽屏 16:9', width: 1536, height: 864, value: '1536x864' },
  { label: '竖屏 9:16', width: 864, height: 1536, value: '864x1536' },
]

const VIDEO_SIZE_OPTIONS: SizeOption[] = [
  { label: '1080p · 16:9', width: 1920, height: 1080, value: '1920x1080' },
  { label: '720p · 16:9', width: 1280, height: 720, value: '1280x720' },
  { label: '竖屏 · 9:16', width: 1080, height: 1920, value: '1080x1920' },
  { label: '方屏 · 1:1', width: 1080, height: 1080, value: '1080x1080' },
]

interface ModelOption {
  value: string
  label: string
  helper: string
}

interface DurationOption {
  value: string
  label: string
}

interface SizeOption {
  label: string
  width: number
  height: number
  value: string
}

interface CameraControlOption {
  value: string
  label: string
  helper: string
}

type AudioGenerationType = 'music' | 'sound-effect'
type AssetStudioMediaType = 'image' | 'video' | 'audio'
type AssetCollectKey = 'image' | 'video' | 'motion' | 'audio'

interface CollectFeedback {
  type: 'success' | 'error'
  text: string
}

interface CollectState {
  loading: boolean
  feedback: CollectFeedback | null
}

interface RuntimeCapabilityHints {
  max_reference_images?: number | null
  supports_camera_control?: boolean
  supports_motion_control?: boolean
}

interface RuntimeTaskResolutionSpec {
  value: string
  width: number
  height: number
}

interface RuntimeTaskConstraints {
  duration_values?: number[]
  ratio_values?: string[]
  min_width?: number
  max_width?: number
  min_height?: number
  max_height?: number
  resolution_options?: string[]
  resolution_specs?: RuntimeTaskResolutionSpec[]
}

interface RuntimeRoutingSignal {
  verification_status?: string | null
  blocked?: boolean
  stale?: boolean
  reason?: string | null
  age_hours?: number | null
}

interface CatalogRuntimeEntry {
  model_key: string
  runtime_capability_hints?: RuntimeCapabilityHints | null
  runtime_task_constraints?: RuntimeTaskConstraints | null
  runtime_routing_signal?: RuntimeRoutingSignal | null
}

const WORKBENCH_INPUT_LABEL_SX: SxProps<Theme> = {
  color: 'rgba(255,255,255,0.68)',
  '&.Mui-focused': {
    color: 'rgba(214,224,255,0.92)',
  },
  '&.MuiFormLabel-filled': {
    color: 'rgba(255,255,255,0.72)',
  },
}

const WORKBENCH_SELECT_SX: SxProps<Theme> = {
  color: 'white',
  borderRadius: 2.5,
  backgroundColor: 'rgba(255,255,255,0.045)',
  backdropFilter: 'blur(10px)',
  '& .MuiOutlinedInput-notchedOutline': {
    borderColor: 'rgba(255,255,255,0.12)',
  },
  '&:hover .MuiOutlinedInput-notchedOutline': {
    borderColor: 'rgba(167,186,255,0.3)',
  },
  '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
    borderColor: 'rgba(139,161,255,0.68)',
  },
  '& .MuiSvgIcon-root': {
    color: 'rgba(255,255,255,0.76)',
  },
}

const WORKBENCH_MENU_PAPER_SX: SxProps<Theme> = {
  mt: 1,
  color: 'white',
  borderRadius: 2.5,
  border: '1px solid rgba(255,255,255,0.12)',
  background: 'linear-gradient(180deg, rgba(53,58,92,0.94) 0%, rgba(18,21,33,0.96) 100%)',
  boxShadow: '0 20px 40px rgba(8,10,18,0.42)',
  backdropFilter: 'blur(18px)',
  '& .MuiMenuItem-root': {
    minHeight: 40,
    color: 'rgba(255,255,255,0.92)',
    transition: 'background-color 0.18s ease, color 0.18s ease',
  },
  '& .MuiMenuItem-root:hover': {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  '& .MuiMenuItem-root.Mui-selected': {
    backgroundColor: 'rgba(126,146,255,0.22)',
  },
  '& .MuiMenuItem-root.Mui-selected:hover': {
    backgroundColor: 'rgba(126,146,255,0.28)',
  },
}

const WORKBENCH_MENU_PROPS: SelectProps<string>['MenuProps'] = {
  PaperProps: {
    elevation: 0,
    sx: WORKBENCH_MENU_PAPER_SX,
  },
  MenuListProps: {
    sx: {
      py: 0.5,
    },
  },
}

function mergeSx(base: SxProps<Theme>, sx?: SxProps<Theme>): SxProps<Theme> {
  if (!sx) {
    return base
  }

  const merged = Array.isArray(sx) ? [base, ...sx] : [base, sx]
  return merged as SxProps<Theme>
}

function InputLabel(props: InputLabelProps) {
  return <MuiInputLabel {...props} sx={mergeSx(WORKBENCH_INPUT_LABEL_SX, props.sx)} />
}

function Select<T extends string = string>(props: SelectProps<T>) {
  const { sx, ...restProps } = props

  return <MuiSelect {...restProps} MenuProps={WORKBENCH_MENU_PROPS} sx={mergeSx(WORKBENCH_SELECT_SX, sx)} />
}

const IMAGE_GENERATION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.6-t2i',
    label: 'wan2.6-t2i',
    helper: '统一到实际调用名的主力文生图模型，适合正式出图、封面草图和角色概念图。',
  },
]

const IMAGE_EDIT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'qwen-image-edit-plus',
    label: 'qwen-image-edit-plus',
    helper: '参考图编辑主力，适合根据指令做稳定修改。',
  },
  {
    value: 'qwen-image-edit-max',
    label: 'qwen-image-edit-max',
    helper: '质量更高，适合精修、复杂改图和最终素材处理。',
  },
]

const VIDEO_TEXT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.6-t2v',
    label: 'wan2.6-t2v',
    helper: '质量优先的视频主力模型，支持镜头控制，适合正式生成。',
  },
  {
    value: 'wan2.6-t2v-fast',
    label: 'wan2.6-t2v-fast',
    helper: '快速预览模型，适合 3 秒或 5 秒的早期验证。',
  },
]

const VIDEO_IMAGE_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.6-i2v',
    label: 'wan2.6-i2v',
    helper: '首帧驱动模型，适合基于参考图生成更稳定的人物或场景视频。',
  },
  {
    value: 'wan2.6-r2v',
    label: 'wan2.6-r2v',
    helper: '参考视频+多图驱动，支持首帧/尾帧控制，适合风格一致的镜头续接。',
  },
]

const MOTION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.6-r2v',
    label: 'wan2.6-r2v',
    helper: '动作控制首选，支持参考视频+多图（最多5张），首尾帧控制，主体一致性最强。',
  },
  {
    value: 'wan2.6-i2v',
    label: 'wan2.6-i2v',
    helper: '单图驱动动画化，适合从静态图生成运动画面。',
  },
  {
    value: 'wan2.6-t2v',
    label: 'wan2.6-t2v',
    helper: '纯提示词驱动，镜头语言更强的运动片段。',
  },
]

const VIDEO_DURATION_OPTIONS_BY_MODEL: Record<string, DurationOption[]> = {
  'wan2.6-t2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
    { value: '15', label: '15 秒' },
  ],
  'wan2.6-t2v-fast': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
  ],
  'wan2.6-i2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'wan2.6-r2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
    { value: '15', label: '15 秒' },
  ],
}

const CAMERA_CONTROL_OPTIONS: CameraControlOption[] = [
  {
    value: '',
    label: '自动',
    helper: '不额外指定镜头运动，让模型自行决定。',
  },
  {
    value: '镜头稳定，以主体动作为主',
    label: '固定机位',
    helper: '更稳，更适合展示人物动作和表情。',
  },
  {
    value: '镜头缓慢推进，聚焦主体',
    label: '缓慢推进',
    helper: '适合突出人物、物体或情绪焦点。',
  },
  {
    value: '镜头轻微平移，保持节奏稳定',
    label: '轻微平移',
    helper: '适合展示空间关系和场景横向变化。',
  },
  {
    value: '镜头轻微跟随主体移动，保持构图稳定',
    label: '轻微跟拍',
    helper: '适合人物走位、奔跑和连续动作。',
  },
  {
    value: '镜头轻微环绕主体，突出空间层次',
    label: '轻微环绕',
    helper: '适合表现空间感、立体感和展示感。',
  },
]

const MOTION_LEVEL_HELPERS: Record<string, string> = {
  low: '更稳，适合微动作、微表情和轻运动。',
  medium: '平衡动作强度和画面稳定性，适合大多数镜头。',
  high: '动作更明显，但对构图和稳定性要求更高。',
}

const AUDIO_GENERATION_TYPE_OPTIONS: Array<{ value: AudioGenerationType; label: string; helper: string }> = [
  {
    value: 'music',
    label: '配乐生成',
    helper: '适合背景音乐、氛围音乐和预告片配乐。',
  },
  {
    value: 'sound-effect',
    label: '音效生成',
    helper: '适合环境音、动作音和短时音效草案。',
  },
]

const AUDIO_MODEL_OPTIONS_BY_TYPE: Record<AudioGenerationType, ModelOption[]> = {
  music: [
    {
      value: 'mureka-o1-instrumental',
      label: 'mureka-o1-instrumental',
      helper: '当前资产工作台的纯音乐主力模型，适合配乐和氛围音乐。',
    },
  ],
  'sound-effect': [
    {
      value: 'kling-v1-text-to-audio',
      label: 'kling-v1-text-to-audio',
      helper: '优先用于短音效和环境音生成；若未配置密钥，后端会自动回退。',
    },
    {
      value: 'mureka-o1-instrumental',
      label: 'mureka-o1-instrumental',
      helper: '作为环境音和轻配乐回退链路，可在无可灵密钥时继续出结果。',
    },
  ],
}

const AUDIO_DURATION_OPTIONS_BY_TYPE: Record<AudioGenerationType, DurationOption[]> = {
  music: [
    { value: '15', label: '15 秒' },
    { value: '30', label: '30 秒' },
    { value: '45', label: '45 秒' },
    { value: '60', label: '60 秒' },
  ],
  'sound-effect': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '8', label: '8 秒' },
    { value: '10', label: '10 秒' },
  ],
}

const AUDIO_STYLE_OPTIONS = [
  { value: '氛围', label: '氛围' },
  { value: '流行', label: '流行' },
  { value: '电子', label: '电子' },
  { value: '钢琴', label: '钢琴' },
  { value: '悬疑', label: '悬疑' },
  { value: '史诗', label: '史诗' },
  { value: '影视配乐', label: '影视配乐' },
]

const AUDIO_MOOD_OPTIONS = [
  { value: 'calm', label: '平静' },
  { value: 'tense', label: '紧张' },
  { value: 'exciting', label: '激昂' },
  { value: 'mysterious', label: '神秘' },
  { value: 'sad', label: '忧郁' },
]

const AUDIO_TEMPO_OPTIONS = [
  { value: 'slow', label: '慢速' },
  { value: 'medium', label: '中速' },
  { value: 'fast', label: '快速' },
]

function getFallbackDurationOptions(modelId: string): DurationOption[] {
  return VIDEO_DURATION_OPTIONS_BY_MODEL[modelId] || VIDEO_DURATION_OPTIONS_BY_MODEL['wan2.6-t2v']
}

function getRecommendedDuration(options: DurationOption[]): string {
  return options.find((option) => option.value === '5')?.value || options[0]?.value || '5'
}

function getGreatestCommonDivisor(a: number, b: number): number {
  let left = Math.abs(a)
  let right = Math.abs(b)
  while (right !== 0) {
    const remainder = left % right
    left = right
    right = remainder
  }
  return left || 1
}

function getAspectRatio(width: number, height: number): string {
  const divisor = getGreatestCommonDivisor(width, height)
  return `${Math.round(width / divisor)}:${Math.round(height / divisor)}`
}

function normalizeDurationValue(value: number): string {
  return Number.isInteger(value) ? String(Math.trunc(value)) : String(value).replace(/\.0+$/, '').replace(/(\.\d*?[1-9])0+$/, '$1')
}

function getRuntimeDurationOptions(
  modelId: string,
  runtimeTaskConstraints?: RuntimeTaskConstraints | null,
): DurationOption[] {
  const durationValues = Array.isArray(runtimeTaskConstraints?.duration_values)
    ? runtimeTaskConstraints.duration_values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value))
    : []

  if (!durationValues.length) {
    return getFallbackDurationOptions(modelId)
  }

  const uniqueSortedValues = Array.from(new Set(durationValues)).sort((left, right) => left - right)
  return uniqueSortedValues.map((value) => {
    const normalized = normalizeDurationValue(value)
    return {
      value: normalized,
      label: `${normalized} 秒`,
    }
  })
}

function filterSizeOptions(
  options: SizeOption[],
  runtimeTaskConstraints?: RuntimeTaskConstraints | null,
): SizeOption[] {
  if (!runtimeTaskConstraints) {
    return options
  }

  const ratioValues = Array.isArray(runtimeTaskConstraints.ratio_values)
    ? runtimeTaskConstraints.ratio_values.filter((value) => typeof value === 'string' && value.trim())
    : []
  const minWidth = typeof runtimeTaskConstraints.min_width === 'number' ? runtimeTaskConstraints.min_width : null
  const maxWidth = typeof runtimeTaskConstraints.max_width === 'number' ? runtimeTaskConstraints.max_width : null
  const minHeight = typeof runtimeTaskConstraints.min_height === 'number' ? runtimeTaskConstraints.min_height : null
  const maxHeight = typeof runtimeTaskConstraints.max_height === 'number' ? runtimeTaskConstraints.max_height : null

  const filtered = options.filter((option) => {
    if (minWidth !== null && option.width < minWidth) return false
    if (maxWidth !== null && option.width > maxWidth) return false
    if (minHeight !== null && option.height < minHeight) return false
    if (maxHeight !== null && option.height > maxHeight) return false
    if (ratioValues.length && !ratioValues.includes(getAspectRatio(option.width, option.height))) return false
    return true
  })

  return filtered.length ? filtered : options
}

function getSupportsCameraControl(
  modelId: string,
  runtimeCapabilityHints?: RuntimeCapabilityHints | null,
): boolean {
  if (typeof runtimeCapabilityHints?.supports_camera_control === 'boolean') {
    return runtimeCapabilityHints.supports_camera_control
  }
  return modelId === 'wan2.6-t2v'
}

function getMaxReferenceImages(
  runtimeCapabilityHints?: RuntimeCapabilityHints | null,
  fallback = 4,
): number {
  const maxReferenceImages = runtimeCapabilityHints?.max_reference_images
  if (typeof maxReferenceImages === 'number' && maxReferenceImages > 0) {
    return maxReferenceImages
  }
  return fallback
}

function getRoutingStatusLabel(signal?: RuntimeRoutingSignal | null): string {
  if (signal?.blocked) {
    return '近期失败'
  }
  if (signal?.stale) {
    return '信号过期'
  }

  switch (signal?.verification_status) {
    case 'verified':
      return '已校验'
    case 'partial':
      return '部分校验'
    case 'failed':
      return '校验失败'
    case 'pending':
      return '待校验'
    default:
      return '未校验'
  }
}

function getRoutingStatusHelper(signal?: RuntimeRoutingSignal | null): string | null {
  if (signal?.blocked) {
    return '该模型最近一次联网校验失败，运行时会优先自动改选其他可用模型。'
  }
  if (signal?.stale) {
    return '该模型的联网校验信号已过期，当前约束可能不是最新官方状态。'
  }

  switch (signal?.verification_status) {
    case 'verified':
      return '最近一次联网校验通过，当前模型状态和能力约束可信度更高。'
    case 'partial':
      return '仅完成部分联网校验，建议结合实际生成结果继续确认。'
    case 'failed':
      return '最近一次联网校验失败，但已超出阻断窗口，运行时仍可能尝试回退使用。'
    case 'pending':
      return '该模型尚未完成联网校验，当前主要依赖本地模型档案。'
    default:
      return null
  }
}

function formatRoutingAge(ageHours?: number | null): string | null {
  if (typeof ageHours !== 'number' || !Number.isFinite(ageHours) || ageHours < 0) {
    return null
  }
  if (ageHours < 1) {
    return '1 小时内'
  }
  if (ageHours < 24) {
    return `${Math.round(ageHours)} 小时前`
  }
  return `${Math.round(ageHours / 24)} 天前`
}

function getRoutingStatusMetaLine(signal?: RuntimeRoutingSignal | null): string | null {
  const parts: string[] = []
  const ageLabel = formatRoutingAge(signal?.age_hours)
  if (ageLabel) {
    parts.push(`最近校验：${ageLabel}`)
  }

  if (typeof signal?.reason === 'string') {
    const reason = signal.reason.trim()
    if (reason) {
      parts.push(`原因：${reason.length > 64 ? `${reason.slice(0, 64)}...` : reason}`)
    }
  }

  return parts.length ? parts.join(' · ') : null
}

function getRoutingPriority(signal?: RuntimeRoutingSignal | null): number {
  if (signal?.blocked) {
    return 6
  }
  if (signal?.stale) {
    return 5
  }

  switch (signal?.verification_status) {
    case 'verified':
      return 0
    case 'partial':
      return 1
    case 'pending':
      return 2
    case 'failed':
      return 4
    default:
      return 3
  }
}

function getRoutingAgePriority(signal?: RuntimeRoutingSignal | null): number {
  return typeof signal?.age_hours === 'number' && Number.isFinite(signal.age_hours) ? signal.age_hours : Number.POSITIVE_INFINITY
}

function sortModelOptionsByRoutingSignal(
  options: ModelOption[],
  runtimeEntries: Record<string, CatalogRuntimeEntry>,
): ModelOption[] {
  return options
    .map((option, index) => ({
      option,
      index,
      signal: runtimeEntries[option.value]?.runtime_routing_signal,
    }))
    .sort((left, right) => {
      const priorityDiff = getRoutingPriority(left.signal) - getRoutingPriority(right.signal)
      if (priorityDiff !== 0) {
        return priorityDiff
      }

      const ageDiff = getRoutingAgePriority(left.signal) - getRoutingAgePriority(right.signal)
      if (ageDiff !== 0) {
        return ageDiff
      }

      return left.index - right.index
    })
    .map((item) => item.option)
}

function shouldRecommendAlternativeModel(
  selectedModelId: string,
  recommendedOption: ModelOption | null,
  runtimeEntries: Record<string, CatalogRuntimeEntry>,
): boolean {
  if (!recommendedOption || recommendedOption.value === selectedModelId) {
    return false
  }

  const selectedSignal = runtimeEntries[selectedModelId]?.runtime_routing_signal
  const recommendedSignal = runtimeEntries[recommendedOption.value]?.runtime_routing_signal
  const selectedPriority = getRoutingPriority(selectedSignal)
  const recommendedPriority = getRoutingPriority(recommendedSignal)

  if (recommendedPriority !== selectedPriority) {
    return recommendedPriority < selectedPriority
  }

  return getRoutingAgePriority(recommendedSignal) < getRoutingAgePriority(selectedSignal)
}

function getRoutingStatusChipSx(signal?: RuntimeRoutingSignal | null): SystemStyleObject<Theme> {
  if (signal?.blocked) {
    return {
      color: '#ffb4ab',
      borderColor: 'rgba(255,120,102,0.4)',
      backgroundColor: 'rgba(255,120,102,0.12)',
    }
  }
  if (signal?.stale) {
    return {
      color: '#ffd38a',
      borderColor: 'rgba(255,190,92,0.36)',
      backgroundColor: 'rgba(255,190,92,0.12)',
    }
  }
  if (signal?.verification_status === 'verified') {
    return {
      color: '#9cff7a',
      borderColor: 'rgba(118,255,84,0.36)',
      backgroundColor: 'rgba(118,255,84,0.12)',
    }
  }
  if (signal?.verification_status === 'partial') {
    return {
      color: '#bcd6ff',
      borderColor: 'rgba(128,170,255,0.32)',
      backgroundColor: 'rgba(128,170,255,0.12)',
    }
  }
  return {
    color: 'rgba(255,255,255,0.72)',
    borderColor: 'rgba(255,255,255,0.16)',
    backgroundColor: 'rgba(255,255,255,0.06)',
  }
}

function renderModelOptionMenuItem(option: ModelOption, signal?: RuntimeRoutingSignal | null) {
  return (
    <MenuItem key={option.value} value={option.value}>
      <Box
        sx={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1.25,
        }}
      >
        <Typography
          sx={{
            minWidth: 0,
            color: 'inherit',
            fontSize: '0.92rem',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {option.label}
        </Typography>
        <Chip
          size="small"
          label={getRoutingStatusLabel(signal)}
          variant="outlined"
          sx={{
            ...getRoutingStatusChipSx(signal),
            flexShrink: 0,
            height: 22,
            '& .MuiChip-label': {
              px: 1,
              fontSize: '0.7rem',
              fontWeight: 600,
            },
          }}
        />
      </Box>
    </MenuItem>
  )
}

function renderRoutingStatusMeta(signal?: RuntimeRoutingSignal | null) {
  const helper = getRoutingStatusHelper(signal)
  const metaLine = getRoutingStatusMetaLine(signal)
  if (!helper && !metaLine) {
    return null
  }

  return (
    <Stack spacing={1} sx={{ mt: 1.25 }}>
      {helper ? (
        <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
          {helper}
        </Typography>
      ) : null}
      {metaLine ? (
        <Typography sx={{ color: 'rgba(188,214,255,0.7)', fontSize: '0.78rem', lineHeight: 1.6 }}>
          {metaLine}
        </Typography>
      ) : null}
      {signal?.blocked ? (
        <Alert
          severity="warning"
          sx={{
            py: 0,
            border: '1px solid rgba(255,180,171,0.24)',
            backgroundColor: 'rgba(255,120,102,0.1)',
            color: '#ffe6e2',
            '& .MuiAlert-icon': {
              color: '#ffb4ab',
            },
          }}
        >
          当前模型近期联网校验失败，运行时会优先自动改选其他可用模型。
        </Alert>
      ) : null}
    </Stack>
  )
}

function renderRecommendedModelAction(
  selectedModelId: string,
  recommendedOption: ModelOption | null,
  runtimeEntries: Record<string, CatalogRuntimeEntry>,
  onApply: () => void,
) {
  if (!shouldRecommendAlternativeModel(selectedModelId, recommendedOption, runtimeEntries) || !recommendedOption) {
    return null
  }

  const recommendedSignal = runtimeEntries[recommendedOption.value]?.runtime_routing_signal

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1}
      alignItems={{ xs: 'stretch', sm: 'center' }}
      sx={{
        mt: 1.25,
        p: 1.2,
        borderRadius: 2.5,
        border: '1px solid rgba(118,255,84,0.16)',
        backgroundColor: 'rgba(118,255,84,0.06)',
      }}
    >
      <Typography sx={{ flex: 1, color: 'rgba(226,255,214,0.88)', fontSize: '0.82rem', lineHeight: 1.7 }}>
        推荐改用 {recommendedOption.label}，当前联网校验状态更优（{getRoutingStatusLabel(recommendedSignal)}）。
      </Typography>
      <Button
        size="small"
        variant="outlined"
        onClick={onApply}
        sx={{
          flexShrink: 0,
          color: '#d9ffcc',
          borderColor: 'rgba(118,255,84,0.28)',
          '&:hover': {
            borderColor: 'rgba(118,255,84,0.42)',
            backgroundColor: 'rgba(118,255,84,0.08)',
          },
        }}
      >
        改用推荐模型
      </Button>
    </Stack>
  )
}

function parseSizeValue(
  value: string,
  options: SizeOption[],
): { width: number; height: number } {
  const matched = options.find((item) => item.value === value)
  return matched ? { width: matched.width, height: matched.height } : { width: options[0].width, height: options[0].height }
}

function buildAssetTitle(prompt: string, fallback: string): string {
  const normalized = String(prompt || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return fallback
  return normalized.length > 28 ? `${normalized.slice(0, 28)}...` : normalized
}

function UploadCard({
  title,
  subtitle,
  multiple = false,
  accept,
  fileCount,
  fileLabel,
  onChange,
}: {
  title: string
  subtitle: string
  multiple?: boolean
  accept?: string
  fileCount: number
  fileLabel: string
  onChange: (files: FileList | null) => void
}) {
  return (
    <Box
      component="label"
      sx={{
        minHeight: 138,
        borderRadius: 3,
        border: '1px dashed rgba(255,255,255,0.18)',
        backgroundColor: 'rgba(255,255,255,0.05)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 2,
        textAlign: 'center',
        cursor: 'pointer',
        transition: 'all 0.24s ease',
        '&:hover': {
          borderColor: 'rgba(142, 255, 74, 0.45)',
          backgroundColor: 'rgba(255,255,255,0.08)',
        },
      }}
    >
      <AddPhotoAlternateOutlinedIcon sx={{ color: 'rgba(255,255,255,0.8)', fontSize: 28, mb: 1 }} />
      <Typography sx={{ color: 'white', fontSize: '0.95rem', fontWeight: 700 }}>{title}</Typography>
      <Typography sx={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.82rem', mt: 0.6 }}>{subtitle}</Typography>
      <Chip
        size="small"
        label={fileCount > 0 ? fileLabel : multiple ? '点击上传多张' : '点击上传'}
        sx={{
          mt: 1.35,
          color: 'white',
          borderColor: 'rgba(255,255,255,0.18)',
          backgroundColor: fileCount > 0 ? 'rgba(142,255,74,0.16)' : 'rgba(255,255,255,0.08)',
        }}
        variant="outlined"
      />
      <input
        hidden
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={(event) => onChange(event.target.files)}
      />
    </Box>
  )
}

function ResultCard({
  title,
  result,
  loading,
  error,
  mediaType = 'image',
  onCollect,
  collecting = false,
  collectFeedback = null,
}: {
  title: string
  result: AssetStudioGenerateResponse | null
  loading: boolean
  error: string | null
  mediaType?: AssetStudioMediaType
  onCollect?: (() => void) | null
  collecting?: boolean
  collectFeedback?: CollectFeedback | null
}) {
  const primaryOutput = result?.primary_output || result?.outputs?.[0] || ''

  return (
    <Box
      sx={{
        borderRadius: 3,
        p: 2,
        minHeight: 220,
        border: '1px solid rgba(255,255,255,0.1)',
        backgroundColor: 'rgba(255,255,255,0.04)',
      }}
    >
      <Typography sx={{ color: 'white', fontSize: '0.92rem', fontWeight: 700, mb: 1.2 }}>{title}</Typography>

      {loading ? (
        <Stack spacing={1.2} alignItems="center" justifyContent="center" sx={{ minHeight: 160 }}>
          <CircularProgress size={28} sx={{ color: '#8eff4a' }} />
          <Typography sx={{ color: 'rgba(255,255,255,0.74)', fontSize: '0.9rem' }}>正在调用模型生成资产...</Typography>
        </Stack>
      ) : error ? (
        <Alert severity="error" sx={{ borderRadius: 2 }}>
          {error}
        </Alert>
      ) : primaryOutput ? (
        <Stack spacing={1.2}>
          <Box
            sx={{
              borderRadius: 2.5,
              overflow: 'hidden',
              backgroundColor: '#101317',
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            {mediaType === 'video' ? (
              <Box
                component="video"
                src={primaryOutput}
                controls
                sx={{ width: '100%', display: 'block', maxHeight: 320, backgroundColor: 'black' }}
              />
            ) : mediaType === 'audio' ? (
              <Box sx={{ p: 2 }}>
                <Box component="audio" src={primaryOutput} controls sx={{ width: '100%', display: 'block' }} />
              </Box>
            ) : (
              <Box
                component="img"
                src={primaryOutput}
                alt="generated asset"
                sx={{ width: '100%', display: 'block', maxHeight: 320, objectFit: 'contain', backgroundColor: 'black' }}
              />
            )}
          </Box>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`模式：${result?.mode || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
            <Chip size="small" label={`模型：${result?.model_id || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
          </Stack>
          {result?.metadata?.fallback_reason ? (
            <Alert severity="info" sx={{ borderRadius: 2 }}>
              {String(result.metadata.fallback_reason)}
            </Alert>
          ) : null}
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button
              variant="outlined"
              onClick={onCollect || undefined}
              disabled={!onCollect || collecting}
              sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.18)' }}
            >
              {collecting ? '收录中...' : '收录到用户资产'}
            </Button>
            <Button
              component="a"
              href={primaryOutput}
              target="_blank"
              rel="noreferrer"
              variant="outlined"
              sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.18)' }}
            >
              查看原文件
            </Button>
          </Stack>
          {collectFeedback ? (
            <Alert severity={collectFeedback.type} sx={{ borderRadius: 2 }}>
              {collectFeedback.text}
            </Alert>
          ) : null}
        </Stack>
      ) : (
        <Stack spacing={1} justifyContent="center" sx={{ minHeight: 160 }}>
          <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.9rem', lineHeight: 1.8 }}>
            这里会展示最新一次生成结果。当前支持直接调用资产生成 API，不经过项目工作流。
          </Typography>
        </Stack>
      )}
    </Box>
  )
}

function FooterAction({
  loading,
  label,
  onClick,
  disabled,
}: {
  loading: boolean
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <Button
      variant="contained"
      onClick={onClick}
      disabled={Boolean(disabled) || loading}
      sx={{
        minWidth: 180,
        minHeight: 56,
        borderRadius: 3,
        background: 'linear-gradient(135deg, #31d12d 0%, #8fff37 100%)',
        color: '#081507',
        fontWeight: 800,
        fontSize: '1.1rem',
        boxShadow: '0 18px 36px rgba(95, 255, 74, 0.22)',
        '&:hover': {
          background: 'linear-gradient(135deg, #31d12d 0%, #8fff37 100%)',
          filter: 'brightness(0.97)',
        },
      }}
    >
      {loading ? '生成中...' : label}
    </Button>
  )
}

export default function AssetStudioWorkbench({ activeTabId, entries, onRequestTabChange }: AssetStudioWorkbenchProps) {
  const activeEntry = entries.find((entry) => entry.id === activeTabId) || entries[0]
  const ActiveIcon = activeEntry.icon
  const [catalogRuntimeEntries, setCatalogRuntimeEntries] = useState<Record<string, CatalogRuntimeEntry>>({})

  const [imagePrompt, setImagePrompt] = useState('')
  const [imageNegativePrompt, setImageNegativePrompt] = useState('')
  const [imageModelId, setImageModelId] = useState('wan2.6-t2i')
  const [imageSize, setImageSize] = useState(IMAGE_SIZE_OPTIONS[0].value)
  const [imageReferenceFiles, setImageReferenceFiles] = useState<File[]>([])
  const [imageLoading, setImageLoading] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)
  const [imageResult, setImageResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [videoPrompt, setVideoPrompt] = useState('')
  const [videoModelId, setVideoModelId] = useState('wan2.6-t2v')
  const [videoDuration, setVideoDuration] = useState('5')
  const [videoSize, setVideoSize] = useState(VIDEO_SIZE_OPTIONS[1].value)
  const [videoCameraControl, setVideoCameraControl] = useState('')
  const [videoReferenceFile, setVideoReferenceFile] = useState<File | null>(null)
  const [videoLoading, setVideoLoading] = useState(false)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [videoResult, setVideoResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [motionPrompt, setMotionPrompt] = useState('')
  const [motionModelId, setMotionModelId] = useState('wan2.6-i2v')
  const [motionDuration, setMotionDuration] = useState('5')
  const [motionSize, setMotionSize] = useState(VIDEO_SIZE_OPTIONS[1].value)
  const [motionLevel, setMotionLevel] = useState('medium')
  const [motionCameraControl, setMotionCameraControl] = useState('')
  const [motionReferenceFile, setMotionReferenceFile] = useState<File | null>(null)
  const [motionLoading, setMotionLoading] = useState(false)
  const [motionError, setMotionError] = useState<string | null>(null)
  const [motionResult, setMotionResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [audioGenerationType, setAudioGenerationType] = useState<AudioGenerationType>('music')
  const [audioPrompt, setAudioPrompt] = useState('')
  const [audioModelId, setAudioModelId] = useState('mureka-o1-instrumental')
  const [audioDuration, setAudioDuration] = useState('30')
  const [audioStyle, setAudioStyle] = useState('氛围')
  const [audioMood, setAudioMood] = useState('calm')
  const [audioTempo, setAudioTempo] = useState('medium')
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [audioResult, setAudioResult] = useState<AssetStudioGenerateResponse | null>(null)
  const [collectStates, setCollectStates] = useState<Record<AssetCollectKey, CollectState>>({
    image: { loading: false, feedback: null },
    video: { loading: false, feedback: null },
    motion: { loading: false, feedback: null },
    audio: { loading: false, feedback: null },
  })

  const imageUsesReferenceMode = imageReferenceFiles.length > 0
  const imageModelOptions = imageUsesReferenceMode ? IMAGE_EDIT_MODEL_OPTIONS : IMAGE_GENERATION_MODEL_OPTIONS
  const sortedImageModelOptions = sortModelOptionsByRoutingSignal(imageModelOptions, catalogRuntimeEntries)
  const recommendedImageModel = sortedImageModelOptions[0] || imageModelOptions[0] || null
  const selectedImageCatalogEntry = catalogRuntimeEntries[imageModelId]
  const selectedImageRoutingSignal = selectedImageCatalogEntry?.runtime_routing_signal
  const imageSizeOptions = filterSizeOptions(IMAGE_SIZE_OPTIONS, selectedImageCatalogEntry?.runtime_task_constraints)
  const imageReferenceLimit = getMaxReferenceImages(selectedImageCatalogEntry?.runtime_capability_hints, 4)
  const selectedImageModel = sortedImageModelOptions.find((option) => option.value === imageModelId) || sortedImageModelOptions[0]

  const videoUsesReferenceMode = Boolean(videoReferenceFile)
  const videoModelOptions = videoUsesReferenceMode ? VIDEO_IMAGE_MODEL_OPTIONS : VIDEO_TEXT_MODEL_OPTIONS
  const sortedVideoModelOptions = sortModelOptionsByRoutingSignal(videoModelOptions, catalogRuntimeEntries)
  const recommendedVideoModel = sortedVideoModelOptions[0] || videoModelOptions[0] || null
  const selectedVideoCatalogEntry = catalogRuntimeEntries[videoModelId]
  const selectedVideoRoutingSignal = selectedVideoCatalogEntry?.runtime_routing_signal
  const selectedVideoModel = sortedVideoModelOptions.find((option) => option.value === videoModelId) || sortedVideoModelOptions[0]
  const videoDurationOptions = getRuntimeDurationOptions(videoModelId, selectedVideoCatalogEntry?.runtime_task_constraints)
  const videoSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedVideoCatalogEntry?.runtime_task_constraints)
  const videoSupportsCameraControl = getSupportsCameraControl(videoModelId, selectedVideoCatalogEntry?.runtime_capability_hints)
  const selectedVideoCameraControl = CAMERA_CONTROL_OPTIONS.find((option) => option.value === videoCameraControl) || CAMERA_CONTROL_OPTIONS[0]

  const sortedMotionModelOptions = sortModelOptionsByRoutingSignal(MOTION_MODEL_OPTIONS, catalogRuntimeEntries)
  const recommendedMotionModel = sortedMotionModelOptions[0] || MOTION_MODEL_OPTIONS[0] || null
  const selectedMotionCatalogEntry = catalogRuntimeEntries[motionModelId]
  const selectedMotionRoutingSignal = selectedMotionCatalogEntry?.runtime_routing_signal
  const selectedMotionModel = sortedMotionModelOptions.find((option) => option.value === motionModelId) || sortedMotionModelOptions[0]
  const motionDurationOptions = getRuntimeDurationOptions(motionModelId, selectedMotionCatalogEntry?.runtime_task_constraints)
  const motionSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedMotionCatalogEntry?.runtime_task_constraints)
  const motionSupportsCameraControl = getSupportsCameraControl(motionModelId, selectedMotionCatalogEntry?.runtime_capability_hints)
  const selectedMotionCameraControl = CAMERA_CONTROL_OPTIONS.find((option) => option.value === motionCameraControl) || CAMERA_CONTROL_OPTIONS[0]

  const audioModelOptions = AUDIO_MODEL_OPTIONS_BY_TYPE[audioGenerationType]
  const selectedAudioModel = audioModelOptions.find((option) => option.value === audioModelId) || audioModelOptions[0]
  const selectedAudioGenerationType =
    AUDIO_GENERATION_TYPE_OPTIONS.find((option) => option.value === audioGenerationType) || AUDIO_GENERATION_TYPE_OPTIONS[0]
  const audioDurationOptions = AUDIO_DURATION_OPTIONS_BY_TYPE[audioGenerationType]

  const updateCollectState = (
    key: AssetCollectKey,
    patch: Partial<CollectState>,
  ) => {
    setCollectStates((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        ...patch,
      },
    }))
  }

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const response = await apiClient.getModelCatalogEntries()
        const items = Array.isArray(response.data?.items) ? response.data.items : []
        if (cancelled) {
          return
        }

        const nextEntries: Record<string, CatalogRuntimeEntry> = {}
        for (const item of items) {
          if (!item || typeof item !== 'object') {
            continue
          }

          const modelKey = typeof (item as CatalogRuntimeEntry).model_key === 'string'
            ? (item as CatalogRuntimeEntry).model_key
            : ''
          if (!modelKey) {
            continue
          }

          nextEntries[modelKey] = {
            model_key: modelKey,
            runtime_capability_hints:
              typeof (item as CatalogRuntimeEntry).runtime_capability_hints === 'object'
                ? (item as CatalogRuntimeEntry).runtime_capability_hints
                : null,
            runtime_task_constraints:
              typeof (item as CatalogRuntimeEntry).runtime_task_constraints === 'object'
                ? (item as CatalogRuntimeEntry).runtime_task_constraints
                : null,
            runtime_routing_signal:
              typeof (item as CatalogRuntimeEntry).runtime_routing_signal === 'object'
                ? (item as CatalogRuntimeEntry).runtime_routing_signal
                : null,
          }
        }
        setCatalogRuntimeEntries(nextEntries)
      } catch {
        if (!cancelled) {
          setCatalogRuntimeEntries({})
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  const collectAssetResult = async (
    key: AssetCollectKey,
    options: {
      result: AssetStudioGenerateResponse | null
      assetKind: 'image' | 'video' | 'audio'
      prompt: string
      fallbackTitle: string
      tags?: string[]
    },
  ) => {
    const primaryOutput = options.result?.primary_output || options.result?.outputs?.[0] || ''
    if (!options.result || !primaryOutput) return

    updateCollectState(key, { loading: true, feedback: null })

    try {
      await apiClient.createUserAsset({
        source_module: 'asset_studio',
        asset_kind: options.assetKind,
        asset_class: 'reusable',
        title: buildAssetTitle(options.prompt, options.fallbackTitle),
        description: options.prompt.trim() || null,
        file_url: primaryOutput,
        preview_url: primaryOutput,
        model_id: options.result.model_id || null,
        generation_mode: options.result.mode || null,
        tags: options.tags || [],
        metadata_json: options.result.metadata || {},
        source_payload_json: {
          kind: options.result.kind,
          mode: options.result.mode,
          model_id: options.result.model_id,
          outputs: options.result.outputs || [],
          metadata: options.result.metadata || {},
        },
      })
      updateCollectState(key, {
        loading: false,
        feedback: { type: 'success', text: '已收录到用户资产' },
      })
    } catch (error) {
      updateCollectState(key, {
        loading: false,
        feedback: {
          type: 'error',
          text: await extractApiErrorMessage(error, '收录到用户资产失败'),
        },
      })
    }
  }

  useEffect(() => {
    if (activeTabId !== 'image') return
    if (imageUsesReferenceMode && !imageModelId.startsWith('qwen-image-edit')) {
      setImageModelId(recommendedImageModel?.value || 'qwen-image-edit-plus')
      return
    }
    if (!imageUsesReferenceMode && imageModelId.startsWith('qwen-image-edit')) {
      setImageModelId(recommendedImageModel?.value || 'wan2.6-t2i')
    }
  }, [activeTabId, imageModelId, imageUsesReferenceMode, recommendedImageModel])

  useEffect(() => {
    if (activeTabId !== 'video') return
    if (videoUsesReferenceMode && videoModelId !== 'wan2.6-i2v') {
      setVideoModelId(recommendedVideoModel?.value || 'wan2.6-i2v')
      return
    }
    if (!videoUsesReferenceMode && videoModelId === 'wan2.6-i2v') {
      setVideoModelId(recommendedVideoModel?.value || 'wan2.6-t2v')
    }
  }, [activeTabId, recommendedVideoModel, videoModelId, videoUsesReferenceMode])

  useEffect(() => {
    if (imageReferenceFiles.length > imageReferenceLimit) {
      setImageReferenceFiles((prev) => prev.slice(0, imageReferenceLimit))
    }
  }, [imageReferenceFiles, imageReferenceLimit])

  useEffect(() => {
    const allowedValues = new Set(imageSizeOptions.map((option) => option.value))
    if (!allowedValues.has(imageSize)) {
      setImageSize(imageSizeOptions[0]?.value || IMAGE_SIZE_OPTIONS[0].value)
    }
  }, [imageSize, imageSizeOptions])

  useEffect(() => {
    const allowedValues = new Set(videoDurationOptions.map((option) => option.value))
    if (!allowedValues.has(videoDuration)) {
      setVideoDuration(getRecommendedDuration(videoDurationOptions))
    }
  }, [videoDuration, videoDurationOptions])

  useEffect(() => {
    const allowedValues = new Set(videoSizeOptions.map((option) => option.value))
    if (!allowedValues.has(videoSize)) {
      setVideoSize(videoSizeOptions[0]?.value || VIDEO_SIZE_OPTIONS[0].value)
    }
  }, [videoSize, videoSizeOptions])

  useEffect(() => {
    const allowedValues = new Set(motionDurationOptions.map((option) => option.value))
    if (!allowedValues.has(motionDuration)) {
      setMotionDuration(getRecommendedDuration(motionDurationOptions))
    }
  }, [motionDuration, motionDurationOptions])

  useEffect(() => {
    const allowedValues = new Set(motionSizeOptions.map((option) => option.value))
    if (!allowedValues.has(motionSize)) {
      setMotionSize(motionSizeOptions[0]?.value || VIDEO_SIZE_OPTIONS[0].value)
    }
  }, [motionSize, motionSizeOptions])

  useEffect(() => {
    if (!videoSupportsCameraControl && videoCameraControl) {
      setVideoCameraControl('')
    }
  }, [videoCameraControl, videoSupportsCameraControl])

  useEffect(() => {
    if (!motionSupportsCameraControl && motionCameraControl) {
      setMotionCameraControl('')
    }
  }, [motionCameraControl, motionSupportsCameraControl])

  useEffect(() => {
    if (!audioModelOptions.some((option) => option.value === audioModelId)) {
      setAudioModelId(audioModelOptions[0]?.value || 'mureka-o1-instrumental')
    }
  }, [audioGenerationType, audioModelId, audioModelOptions])

  useEffect(() => {
    if (!audioDurationOptions.some((option) => option.value === audioDuration)) {
      setAudioDuration(audioDurationOptions[0]?.value || '30')
    }
  }, [audioDuration, audioDurationOptions])

  const handleGenerateImage = async () => {
    if (!imagePrompt.trim()) {
      setImageError('请先填写图片提示词')
      return
    }

    setImageLoading(true)
    setImageError(null)
    try {
      const formData = new FormData()
      const { width, height } = parseSizeValue(imageSize, imageSizeOptions)
      formData.append('prompt', imagePrompt.trim())
      formData.append('negative_prompt', imageNegativePrompt.trim())
      formData.append('model_id', imageModelId)
      formData.append('width', String(width))
      formData.append('height', String(height))
      imageReferenceFiles.forEach((file) => formData.append('reference_images', file))

      const response = await apiClient.generateAssetStudioImage(formData)
      setImageResult(response.data as AssetStudioGenerateResponse)
    } catch (error) {
      setImageError(await extractApiErrorMessage(error, '图片生成失败'))
    } finally {
      setImageLoading(false)
    }
  }

  const handleGenerateVideo = async () => {
    if (!videoPrompt.trim()) {
      setVideoError('请先填写视频提示词')
      return
    }

    setVideoLoading(true)
    setVideoError(null)
    try {
      const formData = new FormData()
      const { width, height } = parseSizeValue(videoSize, videoSizeOptions)
      formData.append('prompt', videoPrompt.trim())
      formData.append('model_id', videoModelId)
      formData.append('width', String(width))
      formData.append('height', String(height))
      formData.append('duration', videoDuration)
      if (videoSupportsCameraControl && videoCameraControl) {
        formData.append('camera_control', videoCameraControl)
      }
      if (videoReferenceFile) {
        formData.append('reference_image', videoReferenceFile)
      }

      const response = await apiClient.generateAssetStudioVideo(formData)
      setVideoResult(response.data as AssetStudioGenerateResponse)
    } catch (error) {
      setVideoError(await extractApiErrorMessage(error, '视频生成失败'))
    } finally {
      setVideoLoading(false)
    }
  }

  const handleGenerateMotion = async () => {
    if (!motionPrompt.trim()) {
      setMotionError('请先填写动作描述')
      return
    }
    if (!motionReferenceFile) {
      setMotionError('动作控制至少需要一张参考图')
      return
    }

    setMotionLoading(true)
    setMotionError(null)
    try {
      const formData = new FormData()
      const { width, height } = parseSizeValue(motionSize, motionSizeOptions)
      formData.append('prompt', motionPrompt.trim())
      formData.append('model_id', motionModelId)
      formData.append('width', String(width))
      formData.append('height', String(height))
      formData.append('duration', motionDuration)
      formData.append('motion_control', motionLevel)
      if (motionSupportsCameraControl && motionCameraControl) {
        formData.append('camera_control', motionCameraControl)
      }
      formData.append('reference_image', motionReferenceFile)

      const response = await apiClient.generateAssetStudioMotion(formData)
      setMotionResult(response.data as AssetStudioGenerateResponse)
    } catch (error) {
      setMotionError(await extractApiErrorMessage(error, '动作控制生成失败'))
    } finally {
      setMotionLoading(false)
    }
  }

  const handleGenerateAudio = async () => {
    if (!audioPrompt.trim()) {
      setAudioError(audioGenerationType === 'music' ? '请先填写配乐提示词' : '请先填写音效提示词')
      return
    }

    setAudioLoading(true)
    setAudioError(null)
    try {
      const formData = new FormData()
      formData.append('prompt', audioPrompt.trim())
      formData.append('generation_type', audioGenerationType)
      formData.append('model_id', audioModelId)
      formData.append('duration', audioDuration)
      formData.append('mood', audioMood)
      formData.append('tempo', audioTempo)
      if (audioGenerationType === 'music') {
        formData.append('style', audioStyle)
      }

      const response = await apiClient.generateAssetStudioAudio(formData)
      setAudioResult(response.data as AssetStudioGenerateResponse)
    } catch (error) {
      setAudioError(await extractApiErrorMessage(error, '音频生成失败'))
    } finally {
      setAudioLoading(false)
    }
  }

  const handleUseReviewedResult = ({ target, prompt, mode, referenceFile }: AssetStudioVisionReusePayload) => {
    const cleanedPrompt = prompt.trim()
    if (!cleanedPrompt) {
      return
    }

    if (target === 'image') {
      setImagePrompt(cleanedPrompt)
      setImageError(null)
      setImageResult(null)
      if (mode === 'reference' && referenceFile) {
        setImageReferenceFiles([referenceFile])
      } else {
        setImageReferenceFiles([])
      }
      onRequestTabChange?.('image')
      return
    }

    setVideoPrompt(cleanedPrompt)
    setVideoError(null)
    setVideoResult(null)
    if (mode === 'reference' && referenceFile) {
      setVideoReferenceFile(referenceFile)
    } else {
      setVideoReferenceFile(null)
    }
    onRequestTabChange?.('video')
  }

  return (
    <Box
      sx={{
        borderRadius: 4,
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,0.1)',
        background: 'linear-gradient(180deg, rgba(16,18,22,0.98), rgba(10,11,15,0.98))',
        boxShadow: '0 28px 60px rgba(2,6,16,0.28)',
      }}
    >
      <Box
        sx={{
          px: { xs: 1.5, sm: 2.5 },
          py: 1.2,
          borderBottom: '1px solid rgba(255,255,255,0.08)',
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <ActiveIcon sx={{ fontSize: 20, color: activeEntry.color }} />
        <Typography sx={{ color: 'white', fontWeight: 700 }}>{activeEntry.title}</Typography>
        <Chip
          size="small"
          label={activeEntry.status === 'ready' ? 'API 可用' : '待接入'}
          sx={{
            color: activeEntry.status === 'ready' ? '#9cff7a' : 'rgba(255,255,255,0.7)',
            backgroundColor: activeEntry.status === 'ready' ? 'rgba(118,255,84,0.14)' : 'rgba(255,255,255,0.08)',
          }}
        />
      </Box>

      {activeTabId === 'image' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>图片模型</InputLabel>
                  <Select value={imageModelId} label="图片模型" onChange={(event) => setImageModelId(event.target.value)} sx={{ color: 'white' }}>
                    {sortedImageModelOptions.map((option) => renderModelOptionMenuItem(option, catalogRuntimeEntries[option.value]?.runtime_routing_signal))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedImageModel?.helper}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedImageRoutingSignal)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedImageRoutingSignal)}
                  />
                  <Chip size="small" label={imageUsesReferenceMode ? '参考图编辑模式' : '纯提示词生成'} variant="outlined" sx={{ color: 'white' }} />
                  <Chip
                    size="small"
                    label={imageModelId === 'qwen-image-edit-max' ? '质量优先' : '推荐主力'}
                    variant="outlined"
                    sx={{ color: 'white' }}
                  />
                </Stack>
                {renderRoutingStatusMeta(selectedImageRoutingSignal)}
                {renderRecommendedModelAction(imageModelId, recommendedImageModel, catalogRuntimeEntries, () => {
                  if (recommendedImageModel?.value) {
                    setImageModelId(recommendedImageModel.value)
                  }
                })}
              </Box>

              <UploadCard
                title="参考生图（可选）"
                subtitle={`上传 1 到 ${imageReferenceLimit} 张参考图后，会自动切到参考图生成链路`}
                multiple
                accept="image/*"
                fileCount={imageReferenceFiles.length}
                fileLabel={`已选 ${imageReferenceFiles.length} 张`}
                onChange={(files) => setImageReferenceFiles(files ? Array.from(files).slice(0, imageReferenceLimit) : [])}
              />
              <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                当前运行时模型约束允许最多 {imageReferenceLimit} 张参考图，超出部分会自动截断。
              </Typography>

              <TextField
                multiline
                minRows={8}
                label="图片提示词"
                value={imagePrompt}
                onChange={(event) => setImagePrompt(event.target.value)}
                placeholder="可以直接描述想生成的图片内容，也可以配合参考图做一致性生成。"
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              <TextField
                multiline
                minRows={2}
                label="反向提示词（可选）"
                value={imageNegativePrompt}
                onChange={(event) => setImageNegativePrompt(event.target.value)}
                placeholder="例如：低质量、模糊、畸形、文字、水印"
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />
            </Stack>

            <ResultCard
              title="生成结果"
              result={imageResult}
              loading={imageLoading}
              error={imageError}
              onCollect={() =>
                void collectAssetResult('image', {
                  result: imageResult,
                  assetKind: 'image',
                  prompt: imagePrompt,
                  fallbackTitle: '图片资产',
                  tags: ['asset_studio', 'image'],
                })
              }
              collecting={collectStates.image.loading}
              collectFeedback={collectStates.image.feedback}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>尺寸</InputLabel>
                <Select value={imageSize} label="尺寸" onChange={(event) => setImageSize(event.target.value)} sx={{ color: 'white' }}>
                  {imageSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
              </Select>
            </FormControl>
            <FooterAction loading={imageLoading} label="生成" onClick={handleGenerateImage} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'video' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>视频模型</InputLabel>
                  <Select value={videoModelId} label="视频模型" onChange={(event) => setVideoModelId(event.target.value)} sx={{ color: 'white' }}>
                    {sortedVideoModelOptions.map((option) => renderModelOptionMenuItem(option, catalogRuntimeEntries[option.value]?.runtime_routing_signal))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedVideoModel?.helper}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedVideoRoutingSignal)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedVideoRoutingSignal)}
                  />
                  <Chip size="small" label={videoUsesReferenceMode ? '首帧驱动模式' : '纯文本视频模式'} variant="outlined" sx={{ color: 'white' }} />
                  <Chip
                    size="small"
                    label={videoModelId === 'wan2.6-t2v-fast' ? '快速预览' : videoModelId === 'wan2.6-i2v' ? '稳定主体' : '正式生成'}
                    variant="outlined"
                    sx={{ color: 'white' }}
                  />
                </Stack>
                {renderRoutingStatusMeta(selectedVideoRoutingSignal)}
                {renderRecommendedModelAction(videoModelId, recommendedVideoModel, catalogRuntimeEntries, () => {
                  if (recommendedVideoModel?.value) {
                    setVideoModelId(recommendedVideoModel.value)
                  }
                })}
              </Box>

              <UploadCard
                title="添加首帧参考图（可选）"
                subtitle="上传后会优先走图生视频链路"
                accept="image/*"
                fileCount={videoReferenceFile ? 1 : 0}
                fileLabel={videoReferenceFile ? videoReferenceFile.name : ''}
                onChange={(files) => setVideoReferenceFile(files?.[0] || null)}
              />

              <TextField
                multiline
                minRows={8}
                label="视频提示词"
                value={videoPrompt}
                onChange={(event) => setVideoPrompt(event.target.value)}
                placeholder="描述镜头、主体、动作和节奏，例如：少女站在雨夜霓虹街头，镜头缓慢推进，发丝与衣摆被风吹动。"
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {videoSupportsCameraControl ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>镜头控制</InputLabel>
                  <Select value={videoCameraControl} label="镜头控制" onChange={(event) => setVideoCameraControl(event.target.value)} sx={{ color: 'white' }}>
                    {CAMERA_CONTROL_OPTIONS.map((option) => (
                      <MenuItem key={option.value || 'auto'} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedVideoCameraControl.helper}
                  </FormHelperText>
                </FormControl>
              ) : (
                <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                  当前模型优先做首帧驱动或快速预览，当前工作台不额外暴露镜头控制参数。
                </Typography>
              )}
            </Stack>

            <ResultCard
              title="视频结果"
              result={videoResult}
              loading={videoLoading}
              error={videoError}
              mediaType="video"
              onCollect={() =>
                void collectAssetResult('video', {
                  result: videoResult,
                  assetKind: 'video',
                  prompt: videoPrompt,
                  fallbackTitle: '视频资产',
                  tags: ['asset_studio', 'video'],
                })
              }
              collecting={collectStates.video.loading}
              collectFeedback={collectStates.video.feedback}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>尺寸</InputLabel>
                <Select value={videoSize} label="尺寸" onChange={(event) => setVideoSize(event.target.value)} sx={{ color: 'white' }}>
                  {videoSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>时长</InputLabel>
                <Select value={videoDuration} label="时长" onChange={(event) => setVideoDuration(event.target.value)} sx={{ color: 'white' }}>
                  {videoDurationOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            <FooterAction loading={videoLoading} label="生成" onClick={handleGenerateVideo} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'motion' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>动作模型</InputLabel>
                  <Select value={motionModelId} label="动作模型" onChange={(event) => setMotionModelId(event.target.value)} sx={{ color: 'white' }}>
                    {sortedMotionModelOptions.map((option) => renderModelOptionMenuItem(option, catalogRuntimeEntries[option.value]?.runtime_routing_signal))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedMotionModel?.helper}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedMotionRoutingSignal)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedMotionRoutingSignal)}
                  />
                  <Chip size="small" label={motionModelId === 'wan2.6-i2v' ? '参考图驱动' : '镜头语言增强'} variant="outlined" sx={{ color: 'white' }} />
                  <Chip size="small" label="动作控制" variant="outlined" sx={{ color: 'white' }} />
                </Stack>
                {renderRoutingStatusMeta(selectedMotionRoutingSignal)}
                {renderRecommendedModelAction(motionModelId, recommendedMotionModel, catalogRuntimeEntries, () => {
                  if (recommendedMotionModel?.value) {
                    setMotionModelId(recommendedMotionModel.value)
                  }
                })}
              </Box>

              <UploadCard
                title="动作参考图"
                subtitle="动作控制必须上传一张主体参考图"
                accept="image/*"
                fileCount={motionReferenceFile ? 1 : 0}
                fileLabel={motionReferenceFile ? motionReferenceFile.name : ''}
                onChange={(files) => setMotionReferenceFile(files?.[0] || null)}
              />

              <TextField
                multiline
                minRows={8}
                label="动作描述"
                value={motionPrompt}
                onChange={(event) => setMotionPrompt(event.target.value)}
                placeholder="例如：角色向前迈步并抬头，右手轻挥，镜头轻微跟拍。"
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {motionSupportsCameraControl ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>镜头控制</InputLabel>
                  <Select value={motionCameraControl} label="镜头控制" onChange={(event) => setMotionCameraControl(event.target.value)} sx={{ color: 'white' }}>
                    {CAMERA_CONTROL_OPTIONS.map((option) => (
                      <MenuItem key={option.value || 'auto'} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedMotionCameraControl.helper}
                  </FormHelperText>
                </FormControl>
              ) : (
                <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                  当前模型优先保证主体一致性和动作稳定性，当前工作台不额外暴露镜头控制参数。
                </Typography>
              )}
            </Stack>

            <ResultCard
              title="动作结果"
              result={motionResult}
              loading={motionLoading}
              error={motionError}
              mediaType="video"
              onCollect={() =>
                void collectAssetResult('motion', {
                  result: motionResult,
                  assetKind: 'video',
                  prompt: motionPrompt,
                  fallbackTitle: '动作视频资产',
                  tags: ['asset_studio', 'motion'],
                })
              }
              collecting={collectStates.motion.loading}
              collectFeedback={collectStates.motion.feedback}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>尺寸</InputLabel>
                <Select value={motionSize} label="尺寸" onChange={(event) => setMotionSize(event.target.value)} sx={{ color: 'white' }}>
                  {motionSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>时长</InputLabel>
                <Select value={motionDuration} label="时长" onChange={(event) => setMotionDuration(event.target.value)} sx={{ color: 'white' }}>
                  {motionDurationOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>动作强度</InputLabel>
                <Select value={motionLevel} label="动作强度" onChange={(event) => setMotionLevel(event.target.value)} sx={{ color: 'white' }}>
                  <MenuItem value="low">低</MenuItem>
                  <MenuItem value="medium">中</MenuItem>
                  <MenuItem value="high">高</MenuItem>
                </Select>
                <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                  {MOTION_LEVEL_HELPERS[motionLevel] || MOTION_LEVEL_HELPERS.medium}
                </FormHelperText>
              </FormControl>
            </Stack>
            <FooterAction loading={motionLoading} label="生成" onClick={handleGenerateMotion} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'audio' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>生成类型</InputLabel>
                  <Select
                    value={audioGenerationType}
                    label="生成类型"
                    onChange={(event) => setAudioGenerationType(event.target.value as AudioGenerationType)}
                    sx={{ color: 'white' }}
                  >
                    {AUDIO_GENERATION_TYPE_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedAudioGenerationType.helper}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip size="small" label={audioGenerationType === 'music' ? '配乐主链路' : '音效主链路'} variant="outlined" sx={{ color: 'white' }} />
                  <Chip size="small" label={audioGenerationType === 'music' ? 'Mureka 生成' : 'Kling 优先 / Mureka 回退'} variant="outlined" sx={{ color: 'white' }} />
                </Stack>
              </Box>

              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>音频模型</InputLabel>
                  <Select value={audioModelId} label="音频模型" onChange={(event) => setAudioModelId(event.target.value)} sx={{ color: 'white' }}>
                    {audioModelOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedAudioModel?.helper}
                  </FormHelperText>
                </FormControl>
              </Box>

              {audioGenerationType === 'sound-effect' ? (
                <Alert severity="info" sx={{ borderRadius: 3 }}>
                  当前音效链路优先使用 `kling-v1-text-to-audio`。若本地未配置可灵密钥，后端会自动回退到
                  `mureka-o1-instrumental` 生成环境音草案。
                </Alert>
              ) : null}

              <TextField
                multiline
                minRows={8}
                label={audioGenerationType === 'music' ? '配乐提示词' : '音效提示词'}
                value={audioPrompt}
                onChange={(event) => setAudioPrompt(event.target.value)}
                placeholder={
                  audioGenerationType === 'music'
                    ? '例如：夜色都市，低频铺底，缓慢推进，悬疑感钢琴与合成器氛围配乐。'
                    : '例如：雨夜巷口的脚步声与湿润地面回响，近景、短促、带一点紧张气氛。'
                }
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>时长</InputLabel>
                  <Select value={audioDuration} label="时长" onChange={(event) => setAudioDuration(event.target.value)} sx={{ color: 'white' }}>
                    {audioDurationOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>情绪</InputLabel>
                  <Select value={audioMood} label="情绪" onChange={(event) => setAudioMood(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_MOOD_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>节奏</InputLabel>
                  <Select value={audioTempo} label="节奏" onChange={(event) => setAudioTempo(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_TEMPO_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Stack>

              {audioGenerationType === 'music' ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>风格</InputLabel>
                  <Select value={audioStyle} label="风格" onChange={(event) => setAudioStyle(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_STYLE_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : null}
            </Stack>

            <ResultCard
              title="音频结果"
              result={audioResult}
              loading={audioLoading}
              error={audioError}
              mediaType="audio"
              onCollect={() =>
                void collectAssetResult('audio', {
                  result: audioResult,
                  assetKind: 'audio',
                  prompt: audioPrompt,
                  fallbackTitle: audioGenerationType === 'music' ? '配乐资产' : '音效资产',
                  tags: ['asset_studio', audioGenerationType === 'music' ? 'music' : 'sound-effect'],
                })
              }
              collecting={collectStates.audio.loading}
              collectFeedback={collectStates.audio.feedback}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.84rem', lineHeight: 1.7 }}>
              {audioGenerationType === 'music'
                ? '配乐模式会把风格、情绪和节奏一并传给后端音频服务。'
                : '音效模式优先尝试 Kling 文生音频，如不可用则自动降级到 Mureka 环境音链路。'}
            </Typography>
            <FooterAction loading={audioLoading} label="生成音频" onClick={handleGenerateAudio} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'vision-review' ? <AssetStudioVisionReviewPanel onUseResult={handleUseReviewedResult} /> : null}

      <Box sx={{ px: { xs: 1.5, sm: 2.5 }, py: 1.2, borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', gap: 1, color: 'rgba(255,255,255,0.42)' }}>
        <BoltOutlinedIcon sx={{ fontSize: 16 }} />
        <Typography sx={{ fontSize: '0.82rem' }}>
          当前工作台为直连资产生成区，优先调用轻量 API，不走项目章节或长流程状态机。
        </Typography>
      </Box>
    </Box>
  )
}
