import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import AddPhotoAlternateOutlinedIcon from '@mui/icons-material/AddPhotoAlternateOutlined'
import BoltOutlinedIcon from '@mui/icons-material/BoltOutlined'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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

import {
  apiClient,
  extractApiErrorMessage,
  type AssetStudioGenerateResponse,
  type AssetStudioModelCatalogOption,
  type AssetStudioMediaAsset,
} from '@/services/api'
import { buildAssetStudioCollectedAssetMetadataContract } from '@/contracts/userAssetMetadataBuilders'
import { buildAssetStudioCollectedSourcePayload } from '@/contracts/userAssetSourcePayloadBuilders'
import { useAssetStudioModelCatalog } from '@/hooks/useAssetStudioModelCatalog'
import { modelUsesBasicNumericSpeedControl } from '@/pages/audiobook/ttsModels'
import { extractLocalAssetStorageMetadata } from '@/utils/localAssetVault'
import { saveExplicitLocalUserAsset } from '@/utils/userAssetExplicitLocalCollection'

import AssetStudioVisionReviewPanel from './AssetStudioVisionReviewPanel'
import type { AssetStudioVisionReusePayload } from './AssetStudioVisionReviewPanel'
import type { AssetStudioTabId, ModelUseEntry } from './modelEntryData'

interface AssetStudioWorkbenchProps {
  activeTabId: AssetStudioTabId
  entries: ModelUseEntry[]
  onRequestTabChange?: (tabId: AssetStudioTabId) => void
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

interface SpeechVoicePreset {
  id: string
  speaker: string
  label: string
  category?: string
  description?: string
  customType?: 'clone' | 'design'
  supportsInstruct?: boolean
}

type AudioGenerationType = 'music' | 'sound-effect' | 'scene-audio' | 'speech'
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

function mapCatalogOptionToModelOption(option: AssetStudioModelCatalogOption): ModelOption {
  return {
    value: option.model_id,
    label: option.label,
    helper: option.helper,
  }
}

function mapDurationValuesToOptions(values: number[] | undefined | null): DurationOption[] {
  if (!Array.isArray(values) || values.length === 0) {
    return []
  }

  const normalizedValues = Array.from(
    new Set(
      values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value)),
    ),
  ).sort((left, right) => left - right)

  return normalizedValues.map((value) => {
    const normalized = normalizeDurationValue(value)
    return {
      value: normalized,
      label: `${normalized} 秒`,
    }
  })
}

function buildCatalogDurationOptionsByModel(
  groups: Record<string, AssetStudioModelCatalogOption[]> | undefined,
): Record<string, DurationOption[]> {
  if (!groups) {
    return {}
  }

  const result: Record<string, DurationOption[]> = {}
  const groupKeys = ['video_generation', 'video_edit', 'motion'] as const
  for (const groupKey of groupKeys) {
    for (const option of groups[groupKey] || []) {
      const durationOptions = mapDurationValuesToOptions(option.duration_options)
      if (durationOptions.length > 0) {
        result[option.model_id] = durationOptions
      }
    }
  }
  return result
}

function resolvePreferredModelOption(options: ModelOption[], preferredModelId: string): ModelOption | null {
  return options.find((option) => option.value === preferredModelId) || options[0] || null
}

function getPrimaryResultAsset(result: AssetStudioGenerateResponse | null | undefined): AssetStudioMediaAsset | null {
  if (!result) return null
  return result.primary_asset || result.assets?.[0] || null
}

function resolveResultAssetUrl(asset: AssetStudioMediaAsset | null | undefined): string {
  return asset?.preview_uri || asset?.source_uri || asset?.download_uri || ''
}

function buildPendingGenerateResponse({
  kind,
  mode,
  modelId,
  prompt,
  metadata,
}: {
  kind: string
  mode: string
  modelId: string
  prompt: string
  metadata?: Record<string, unknown>
}): AssetStudioGenerateResponse {
  return {
    kind,
    mode,
    model_id: modelId,
    assets: [],
    primary_asset: null,
    metadata: {
      pending: true,
      pending_message: '请求已提交，正在等待模型返回结果...',
      prompt_preview: prompt.trim().slice(0, 120),
      submitted_at: new Date().toISOString(),
      requested_model_id: modelId,
      ...(metadata || {}),
    },
  }
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

const MODEL_CATALOG_ENTRY_ALIASES: Record<string, string[]> = {
  'kling/kling-v3-image-generation': ['kling-v3-image-generation'],
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

const WORKBENCH_DIALOG_PAPER_SX: SxProps<Theme> = {
  color: 'white',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.12)',
  background: 'linear-gradient(180deg, rgba(26,30,46,0.98) 0%, rgba(12,15,24,0.98) 100%)',
  boxShadow: '0 28px 80px rgba(2,6,16,0.52)',
  backdropFilter: 'blur(18px)',
}

const WORKBENCH_DIALOG_BACKDROP_SX: SxProps<Theme> = {
  backgroundColor: 'rgba(5,8,16,0.76)',
  backdropFilter: 'blur(10px)',
}

const WORKBENCH_DIALOG_TITLE_SX: SxProps<Theme> = {
  px: 3,
  py: 2.25,
  color: 'white',
  fontSize: '1.85rem',
  fontWeight: 700,
  borderBottom: '1px solid rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_CONTENT_SX: SxProps<Theme> = {
  px: 3,
  py: 2.5,
  borderColor: 'rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_ACTIONS_SX: SxProps<Theme> = {
  px: 3,
  py: 2,
  gap: 1,
  borderTop: '1px solid rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_INFO_ALERT_SX: SxProps<Theme> = {
  borderRadius: 2.5,
  color: 'rgba(224,236,255,0.96)',
  backgroundColor: 'rgba(74,115,255,0.14)',
  border: '1px solid rgba(121,149,255,0.24)',
  '& .MuiAlert-icon': {
    color: '#9db4ff',
  },
}

const WORKBENCH_DIALOG_FIELD_SX: SxProps<Theme> = {
  '& .MuiInputLabel-root': {
    color: 'rgba(255,255,255,0.66)',
  },
  '& .MuiInputLabel-root.Mui-focused': {
    color: 'rgba(214,224,255,0.92)',
  },
  '& .MuiOutlinedInput-root': {
    color: 'white',
    borderRadius: 2.5,
    backgroundColor: 'rgba(255,255,255,0.045)',
    '& fieldset': {
      borderColor: 'rgba(255,255,255,0.14)',
    },
    '&:hover fieldset': {
      borderColor: 'rgba(167,186,255,0.3)',
    },
    '&.Mui-focused fieldset': {
      borderColor: 'rgba(139,161,255,0.68)',
    },
  },
}

const WORKBENCH_SUBTLE_ACTION_BUTTON_SX: SxProps<Theme> = {
  minHeight: 38,
  px: 1.25,
  color: 'rgba(235,241,255,0.92)',
  borderColor: 'rgba(255,255,255,0.12)',
  backgroundColor: 'rgba(255,255,255,0.03)',
  whiteSpace: 'nowrap',
  '&:hover': {
    borderColor: 'rgba(138,158,255,0.36)',
    backgroundColor: 'rgba(138,158,255,0.08)',
  },
  '&.Mui-disabled': {
    color: 'rgba(255,255,255,0.28)',
    borderColor: 'rgba(255,255,255,0.08)',
    backgroundColor: 'rgba(255,255,255,0.02)',
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
    label: 'Wan 2.6 T2I',
    helper: '主力文生图模型，适合正式出图、封面草图和角色概念图。',
  },
  {
    value: 'qwen-image-2.0',
    label: 'Qwen Image 2.0',
    helper: '通义千问高质量文生图，适合日常图像创作。',
  },
  {
    value: 'qwen-image-2.0-pro',
    label: 'Qwen Image 2.0 Pro',
    helper: '通义千问旗舰级文生图，画质更精细，适合商业级图像。',
  },
  {
    value: 'wan2.7-image',
    label: 'Wan 2.7 Image',
    helper: '万相最新图像生成模型，支持多种创作功能。',
  },
  {
    value: 'doubao-seedream-4-5',
    label: 'Doubao Seedream 4.5',
    helper: '豆包高质量文生图，适合插画和概念设计。',
  },
  {
    value: 'doubao-seedream-5-0',
    label: 'Doubao Seedream 5.0',
    helper: '豆包最新版本，支持超高分辨率和多种图像创作功能。',
  },
  {
    value: 'kling-v3-image-generation',
    label: 'Kling V3 图像生成',
    helper: '快手可灵 V3 图像生成，高质量人物和场景。',
  },
  {
    value: 'kling-v3-omni-image-generation',
    label: 'Kling V3 Omni 图像生成',
    helper: '可灵全能版图像生成，支持图生图和风格迁移。',
  },
]

const IMAGE_EDIT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'qwen-image-edit-plus',
    label: 'Qwen Image Edit Plus',
    helper: '参考图编辑主力，适合根据指令做稳定修改。',
  },
  {
    value: 'qwen-image-edit-max',
    label: 'Qwen Image Edit Max',
    helper: '质量更高，适合精修、复杂改图和最终素材处理。',
  },
]

const VIDEO_GENERATION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.7-t2v',
    label: 'Wan 2.7 T2V',
    helper: '质量优先的视频主力模型，支持镜头控制，适合正式生成。',
  },
  {
    value: 'wan2.6-t2v-fast',
    label: 'Wan 2.6 T2V Fast',
    helper: '快速预览模型，适合 3 秒或 5 秒的早期验证。',
  },
  {
    value: 'wan2.7-i2v',
    label: 'Wan 2.7 I2V',
    helper: '首帧驱动模型，适合基于参考图生成更稳定的人物或场景视频。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0',
    helper: '支持最多9张参考图+3个参考视频+首尾帧，多模态控制最强。',
  },
  {
    value: 'doubao-seedance-2-0-fast',
    label: 'Doubao Seedance 2.0 Fast',
    helper: '豆包快速版本，适合原型验证和快速迭代。',
  },
  {
    value: 'doubao-seedance-1-5-pro',
    label: 'Doubao Seedance 1.5 Pro',
    helper: '豆包上一代专业版本，稳定可靠。',
  },
  {
    value: 'kling-v3-video-generation',
    label: 'Kling V3 视频生成',
    helper: '快手可灵 V3，支持最多7张参考图+首尾帧+多镜头。',
  },
  {
    value: 'kling-v3-omni-video-generation',
    label: 'Kling V3 Omni 视频生成',
    helper: '快手可灵全能版本，支持多模态输入与复杂场景控制。',
  },
  {
    value: 'pixverse-v6-t2v',
    label: 'PixVerse V6',
    helper: 'PixVerse V6 文生视频，支持首尾帧+多镜头+特效模板。',
  },
  {
    value: 'vidu-q3-pro-text2video',
    label: 'Vidu Q3 Pro 文生视频',
    helper: 'Vidu Q3 Pro 文生视频链路，适合高质量视频创作。',
  },
  {
    value: 'vidu-q3-pro-img2video',
    label: 'Vidu Q3 Pro 图生视频',
    helper: 'Vidu Q3 Pro 图生视频链路，支持参考图驱动视频生成。',
  },
  {
    value: 'vidu-q3-pro-start-end2video',
    label: 'Vidu Q3 Pro 首尾帧',
    helper: 'Vidu Q3 Pro 首尾帧控制，适合精确控制视频起始和结束画面。',
  },
]

const VIDEO_EDIT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.7-videoedit',
    label: 'Wan 2.7 VideoEdit',
    helper: '万相视频编辑模型，支持参考视频输入、多片段融合与风格迁移。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0（编辑）',
    helper: '支持视频编辑与延长，电影级质量。',
  },
  {
    value: 'kling-v3-video-generation',
    label: 'Kling V3（编辑）',
    helper: '可灵视频编辑与融合，适合高质量视频创作。',
  },
]

const MOTION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan2.7-r2v',
    label: 'Wan 2.7 R2V',
    helper: '支持最多5个视频参考+多图+首尾帧，动作控制、主体一致性最强。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0',
    helper: '支持最多9张参考图+3个参考视频+首尾帧，多模态控制最强。',
  },
  {
    value: 'kling-v3-video-generation',
    label: 'Kling V3',
    helper: '支持最多7张参考图+首尾帧+多镜头生成。',
  },
  {
    value: 'kling-v3-omni-video-generation',
    label: 'Kling V3 Omni',
    helper: '可灵全能版，支持多模态输入+首尾帧+多镜头。',
  },
  {
    value: 'pixverse-v6-t2v',
    label: 'PixVerse V6',
    helper: '支持首尾帧+多镜头+特效模板，创意视频首选。',
  },
]

const VIDEO_DURATION_OPTIONS_BY_MODEL: Record<string, DurationOption[]> = {
  'wan2.7-t2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
    { value: '15', label: '15 秒' },
  ],
  'wan2.6-t2v-fast': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
  ],
  'wan2.7-i2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'wan2.7-r2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
    { value: '15', label: '15 秒' },
  ],
  'wan2.7-videoedit': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'doubao-seedance-2-0': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
    { value: '30', label: '30 秒' },
  ],
  'doubao-seedance-2-0-fast': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'doubao-seedance-1-5-pro': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'kling-v3-video-generation': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'kling-v3-omni-video-generation': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'pixverse-v6-t2v': [
    { value: '3', label: '3 秒' },
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'vidu-q3-pro-text2video': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'vidu-q3-pro-img2video': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
  ],
  'vidu-q3-pro-start-end2video': [
    { value: '5', label: '5 秒' },
    { value: '10', label: '10 秒' },
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
  {
    value: 'scene-audio',
    label: '场景音频',
    helper: '在一条导演式提示词中统一生成多角色对白、环境声、动作音效和配乐。',
  },
  {
    value: 'speech',
    label: '语音合成',
    helper: '适合旁白、对白和角色试听，可直接选择 TTS 模型与音色。',
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
      value: 'vidu-timing2audio',
      label: 'Vidu Timing2Audio',
      helper: '可控文生音效，支持通过时间轴控制多个音效事件，适合视频音效和有声小说音效。',
    },
  ],
  'scene-audio': [
    {
      value: 'seed-audio-1.0',
      label: '豆包音频生成模型 1.0',
      helper: '适合有声剧和影视场景预演，可在一次生成中组合对白、环境、音效与音乐。',
    },
  ],
  speech: [
    {
      value: 'qwen3-tts-instruct-flash',
      label: 'Qwen3-TTS Instruct Flash',
      helper: '速度快、出稿稳，适合旁白草稿、对白验证和大批量试听。',
    },
    {
      value: 'cosyvoice-v3.5-plus',
      label: 'CosyVoice v3.5-plus',
      helper: '高表现力语音模型，支持 instruction，但必须先选择复刻或设计音色。',
    },
    {
      value: 'minimax-speech-2.8-hd',
      label: 'MiniMax Speech 2.8 HD',
      helper: '音质优先，适合高保真语音样稿和更细腻的情感表达。',
    },
    {
      value: 'minimax-speech-2.8-turbo',
      label: 'MiniMax Speech 2.8 Turbo',
      helper: '兼顾速度和质量，适合快速迭代语音草案。',
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
  'scene-audio': [],
  speech: [],
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

const getFallbackDurationOptions = function(
  modelId: string,
  catalogDurationOptionsByModel?: Record<string, DurationOption[]>,
): DurationOption[] {
  const catalogOptions = catalogDurationOptionsByModel?.[modelId]
  if (catalogOptions && catalogOptions.length > 0) {
    return catalogOptions
  }
  return VIDEO_DURATION_OPTIONS_BY_MODEL[modelId] || VIDEO_DURATION_OPTIONS_BY_MODEL['wan2.7-t2v']
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
  catalogDurationOptionsByModel?: Record<string, DurationOption[]>,
): DurationOption[] {
  const durationValues = Array.isArray(runtimeTaskConstraints?.duration_values)
    ? runtimeTaskConstraints.duration_values
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value))
    : []

  if (!durationValues.length) {
    return getFallbackDurationOptions(modelId, catalogDurationOptionsByModel)
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
  return modelId === 'wan2.7-t2v'
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
  const primaryOutput = resolveResultAssetUrl(getPrimaryResultAsset(result))
  const requestedModelId = typeof result?.metadata?.requested_model_id === 'string'
    ? String(result.metadata.requested_model_id).trim()
    : ''
  const routingMessage = typeof result?.metadata?.routing_message === 'string'
    ? String(result.metadata.routing_message).trim()
    : ''
  const hasRequestedModelMismatch = Boolean(
    requestedModelId
    && result?.model_id
    && requestedModelId !== result.model_id,
  )

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
          {result ? (
            <>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="center">
                <Chip size="small" label={`模式：${result.mode || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
                <Chip size="small" label={`模型：${result.model_id || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
                {hasRequestedModelMismatch ? (
                  <Chip size="small" label={`请求模型：${requestedModelId}`} sx={{ color: 'white' }} variant="outlined" />
                ) : null}
              </Stack>
              {typeof result.metadata?.prompt_preview === 'string' && result.metadata.prompt_preview ? (
                <Typography
                  sx={{
                    color: 'rgba(255,255,255,0.6)',
                    fontSize: '0.82rem',
                    lineHeight: 1.7,
                    textAlign: 'center',
                  }}
                >
                  {String(result.metadata.prompt_preview)}
                </Typography>
              ) : null}
            </>
          ) : null}
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
            {hasRequestedModelMismatch ? (
              <Chip size="small" label={`请求模型：${requestedModelId}`} sx={{ color: 'white' }} variant="outlined" />
            ) : null}
          </Stack>
          {routingMessage ? (
            <Alert severity="info" sx={{ borderRadius: 2 }}>
              {routingMessage}
            </Alert>
          ) : null}
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
  const { catalog: assetStudioModelCatalog } = useAssetStudioModelCatalog()

  const assetStudioImageGenerationDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_image_generation || 'wan2.7-image'
  const assetStudioImageEditDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_image_edit || 'qwen-image-edit-plus'
  const assetStudioVideoGenerationDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_video_generation || 'wan2.7-t2v'
  const assetStudioMotionDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_motion || 'wan2.7-i2v'
  const assetStudioAudioMusicDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_music || 'mureka-o1-instrumental'
  const assetStudioAudioSoundEffectDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_sound_effect || 'vidu-timing2audio'
  const assetStudioAudioSceneDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_scene || 'seed-audio-1.0'
  const assetStudioAudioSpeechDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_speech || 'qwen3-tts-instruct-flash'

  const [imagePrompt, setImagePrompt] = useState('')
  const [imageNegativePrompt, setImageNegativePrompt] = useState('')
  const [imageModelId, setImageModelId] = useState('wan2.7-image')
  const [imageSize, setImageSize] = useState(IMAGE_SIZE_OPTIONS[0].value)
  const [imageReferenceFiles, setImageReferenceFiles] = useState<File[]>([])
  const [imageLoading, setImageLoading] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)
  const [imageResult, setImageResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [videoPrompt, setVideoPrompt] = useState('')
  const [videoModelId, setVideoModelId] = useState('wan2.7-t2v')
  const [videoDuration, setVideoDuration] = useState('5')
  const [videoSize, setVideoSize] = useState(VIDEO_SIZE_OPTIONS[1].value)
  const [videoCameraControl, setVideoCameraControl] = useState('')
  const [videoReferenceFile, setVideoReferenceFile] = useState<File | null>(null)
  const [videoLoading, setVideoLoading] = useState(false)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [videoResult, setVideoResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [motionPrompt, setMotionPrompt] = useState('')
  const [motionModelId, setMotionModelId] = useState('wan2.7-i2v')
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
  const [audioVoiceId, setAudioVoiceId] = useState('')
  const [audioInstruction, setAudioInstruction] = useState('')
  const [audioSpeakerIds, setAudioSpeakerIds] = useState('')
  const [audioRate, setAudioRate] = useState('1.0')
  const [audioVolume, setAudioVolume] = useState('50')
  const [audioVoicePresets, setAudioVoicePresets] = useState<SpeechVoicePreset[]>([])
  const [audioVoiceLoading, setAudioVoiceLoading] = useState(false)
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [audioResult, setAudioResult] = useState<AssetStudioGenerateResponse | null>(null)
  const [audioCloneDialogOpen, setAudioCloneDialogOpen] = useState(false)
  const [audioCloneName, setAudioCloneName] = useState('')
  const [audioCloneUrl, setAudioCloneUrl] = useState('')
  const [audioCloneLoading, setAudioCloneLoading] = useState(false)
  const [audioCloneUploading, setAudioCloneUploading] = useState(false)
  const [audioCloneRecording, setAudioCloneRecording] = useState(false)
  const [audioCloneRecordDialogOpen, setAudioCloneRecordDialogOpen] = useState(false)
  const [audioCloneFeedback, setAudioCloneFeedback] = useState<CollectFeedback | null>(null)
  const [audioDesignDialogOpen, setAudioDesignDialogOpen] = useState(false)
  const [audioDesignName, setAudioDesignName] = useState('')
  const [audioDesignPrompt, setAudioDesignPrompt] = useState('')
  const [audioDesignPreviewText, setAudioDesignPreviewText] = useState('欢迎收听这段声音设计试听，我们从这里开始塑造角色的独特声线。')
  const [audioDesignLoading, setAudioDesignLoading] = useState(false)
  const [audioDesignFeedback, setAudioDesignFeedback] = useState<CollectFeedback | null>(null)
  const [audioVoiceActionFeedback, setAudioVoiceActionFeedback] = useState<CollectFeedback | null>(null)
  const audioCloneRecorderRef = useRef<MediaRecorder | null>(null)
  const audioCloneStreamRef = useRef<MediaStream | null>(null)
  const audioCloneChunksRef = useRef<Blob[]>([])

  const [collectStates, setCollectStates] = useState<Record<AssetCollectKey, CollectState>>({
    image: { loading: false, feedback: null },
    video: { loading: false, feedback: null },
    motion: { loading: false, feedback: null },
    audio: { loading: false, feedback: null },
  })

  const imageUsesReferenceMode = imageReferenceFiles.length > 0
  const catalogDurationOptionsByModel = buildCatalogDurationOptionsByModel(assetStudioModelCatalog?.groups)
  const imageGenerationModelOptions =
    assetStudioModelCatalog?.groups.image_generation?.map(mapCatalogOptionToModelOption) || IMAGE_GENERATION_MODEL_OPTIONS
  const imageEditModelOptions =
    assetStudioModelCatalog?.groups.image_edit?.map(mapCatalogOptionToModelOption) || IMAGE_EDIT_MODEL_OPTIONS
  const imageModelOptions =
    imageEditModelOptions.length > 0
      ? [...imageGenerationModelOptions, { value: '---divider---' as const, label: '── 图像编辑 ──' }, ...imageEditModelOptions]
      : imageGenerationModelOptions
  const imageRealModelOptions = imageModelOptions.filter((opt): opt is ModelOption => opt.value !== '---divider---')
  const sortedImageModelOptions = sortModelOptionsByRoutingSignal(imageRealModelOptions, catalogRuntimeEntries)
  const recommendedImageModel = sortedImageModelOptions[0] || imageRealModelOptions[0] || null
  const preferredImageGenerationModel = resolvePreferredModelOption(
    imageGenerationModelOptions,
    assetStudioImageGenerationDefaultModelId,
  )
  const preferredImageEditModel = resolvePreferredModelOption(imageEditModelOptions, assetStudioImageEditDefaultModelId)
  const imageEditModelIds = new Set(imageEditModelOptions.map((option) => option.value))
  const selectedImageCatalogEntry = catalogRuntimeEntries[imageModelId]
  const selectedImageRoutingSignal = selectedImageCatalogEntry?.runtime_routing_signal
  const imageSizeOptions = filterSizeOptions(IMAGE_SIZE_OPTIONS, selectedImageCatalogEntry?.runtime_task_constraints)
  const imageReferenceLimit = getMaxReferenceImages(selectedImageCatalogEntry?.runtime_capability_hints, 4)
  const selectedImageModel = sortedImageModelOptions.find((option) => option.value === imageModelId) || sortedImageModelOptions[0]

  const videoUsesReferenceMode = Boolean(videoReferenceFile)
  const videoGenerationModelOptions =
    assetStudioModelCatalog?.groups.video_generation?.map(mapCatalogOptionToModelOption) || VIDEO_GENERATION_MODEL_OPTIONS
  const videoEditModelOptions =
    assetStudioModelCatalog?.groups.video_edit?.map(mapCatalogOptionToModelOption) || VIDEO_EDIT_MODEL_OPTIONS
  const videoModelOptions =
    videoEditModelOptions.length > 0
      ? [...videoGenerationModelOptions, { value: '---divider---' as const, label: '── 视频编辑 ──' }, ...videoEditModelOptions]
      : videoGenerationModelOptions
  const videoRealModelOptions = videoModelOptions.filter((opt): opt is ModelOption => opt.value !== '---divider---')
  const sortedVideoModelOptions = sortModelOptionsByRoutingSignal(videoRealModelOptions, catalogRuntimeEntries)
  const recommendedVideoModel = sortedVideoModelOptions[0] || videoRealModelOptions[0] || null
  const preferredVideoGenerationModel = resolvePreferredModelOption(
    videoGenerationModelOptions,
    assetStudioVideoGenerationDefaultModelId,
  )
  const preferredVideoReferenceModel = resolvePreferredModelOption(
    videoGenerationModelOptions,
    assetStudioMotionDefaultModelId,
  )
  const selectedVideoCatalogEntry = catalogRuntimeEntries[videoModelId]
  const selectedVideoRoutingSignal = selectedVideoCatalogEntry?.runtime_routing_signal
  const selectedVideoModel = sortedVideoModelOptions.find((option) => option.value === videoModelId) || sortedVideoModelOptions[0]
  const videoDurationOptions = getRuntimeDurationOptions(
    videoModelId,
    selectedVideoCatalogEntry?.runtime_task_constraints,
    catalogDurationOptionsByModel,
  )
  const videoSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedVideoCatalogEntry?.runtime_task_constraints)
  const videoSupportsCameraControl = getSupportsCameraControl(videoModelId, selectedVideoCatalogEntry?.runtime_capability_hints)
  const selectedVideoCameraControl = CAMERA_CONTROL_OPTIONS.find((option) => option.value === videoCameraControl) || CAMERA_CONTROL_OPTIONS[0]
  const pendingVideoResult = videoLoading
    ? buildPendingGenerateResponse({
        kind: 'video',
        mode: videoUsesReferenceMode ? 'image_to_video' : 'text_to_video',
        modelId: videoModelId,
        prompt: videoPrompt,
        metadata: {
          has_reference_image: videoUsesReferenceMode,
          camera_control: videoSupportsCameraControl && videoCameraControl ? videoCameraControl : null,
          requested_duration: videoDuration,
        },
      })
    : null
  const displayedVideoResult = videoLoading ? pendingVideoResult : videoResult

  const motionModelOptions =
    assetStudioModelCatalog?.groups.motion?.map(mapCatalogOptionToModelOption) || MOTION_MODEL_OPTIONS
  const sortedMotionModelOptions = sortModelOptionsByRoutingSignal(motionModelOptions, catalogRuntimeEntries)
  const recommendedMotionModel = sortedMotionModelOptions[0] || motionModelOptions[0] || null
  const preferredMotionModel = resolvePreferredModelOption(motionModelOptions, assetStudioMotionDefaultModelId)
  const selectedMotionCatalogEntry = catalogRuntimeEntries[motionModelId]
  const selectedMotionRoutingSignal = selectedMotionCatalogEntry?.runtime_routing_signal
  const selectedMotionModel = sortedMotionModelOptions.find((option) => option.value === motionModelId) || sortedMotionModelOptions[0]
  const motionDurationOptions = getRuntimeDurationOptions(
    motionModelId,
    selectedMotionCatalogEntry?.runtime_task_constraints,
    catalogDurationOptionsByModel,
  )
  const motionSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedMotionCatalogEntry?.runtime_task_constraints)
  const motionSupportsCameraControl = getSupportsCameraControl(motionModelId, selectedMotionCatalogEntry?.runtime_capability_hints)
  const selectedMotionCameraControl = CAMERA_CONTROL_OPTIONS.find((option) => option.value === motionCameraControl) || CAMERA_CONTROL_OPTIONS[0]

  const audioModelOptionsByType: Record<AudioGenerationType, ModelOption[]> = {
    music: assetStudioModelCatalog?.groups.audio_music?.map(mapCatalogOptionToModelOption) || AUDIO_MODEL_OPTIONS_BY_TYPE.music,
    'sound-effect':
      assetStudioModelCatalog?.groups.audio_sound_effect?.map(mapCatalogOptionToModelOption) ||
      AUDIO_MODEL_OPTIONS_BY_TYPE['sound-effect'],
    'scene-audio':
      assetStudioModelCatalog?.groups.audio_scene?.map(mapCatalogOptionToModelOption) ||
      AUDIO_MODEL_OPTIONS_BY_TYPE['scene-audio'],
    speech: assetStudioModelCatalog?.groups.audio_speech?.map(mapCatalogOptionToModelOption) || AUDIO_MODEL_OPTIONS_BY_TYPE.speech,
  }
  const audioModelOptions = audioModelOptionsByType[audioGenerationType]
  const selectedAudioModel = audioModelOptions.find((option) => option.value === audioModelId) || audioModelOptions[0]
  const selectedAudioGenerationType =
    AUDIO_GENERATION_TYPE_OPTIONS.find((option) => option.value === audioGenerationType) || AUDIO_GENERATION_TYPE_OPTIONS[0]
  const audioDurationOptions = AUDIO_DURATION_OPTIONS_BY_TYPE[audioGenerationType]
  const sortedAudioVoicePresets = [...audioVoicePresets].sort((left, right) => {
    const leftCategory = left.category || 'general'
    const rightCategory = right.category || 'general'
    if (leftCategory !== rightCategory) {
      return leftCategory.localeCompare(rightCategory, 'zh-CN')
    }
    return (left.label || left.id).localeCompare(right.label || right.id, 'zh-CN')
  })
  const isCosyVoiceSpeechMode = audioGenerationType === 'speech' && audioModelId === 'cosyvoice-v3.5-plus'
  const showAudioNumericSpeedControl =
    audioGenerationType === 'speech' && modelUsesBasicNumericSpeedControl(audioModelId)

  const applyAudioVoicePresets = (voices: SpeechVoicePreset[], preferredVoiceId?: string) => {
    setAudioVoicePresets(voices)
    setAudioVoiceId((current) => {
      if (preferredVoiceId && voices.some((voice) => voice.id === preferredVoiceId)) {
        return preferredVoiceId
      }
      if (voices.some((voice) => voice.id === current)) {
        return current
      }
      return voices[0]?.id || ''
    })
  }

  const refreshAudioVoiceCatalog = async (modelId: string = audioModelId, preferredVoiceId?: string) => {
    setAudioVoiceLoading(true)
    try {
      const response = await apiClient.getTtsVoices(modelId)
      const voices = Array.isArray(response.data?.voices)
        ? (response.data?.voices as SpeechVoicePreset[])
        : []
      applyAudioVoicePresets(voices, preferredVoiceId)
      return voices
    } catch (error) {
      setAudioVoicePresets([])
      setAudioVoiceId('')
      throw error
    } finally {
      setAudioVoiceLoading(false)
    }
  }

  const handleUploadAudioCloneSample = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) {
      return
    }

    setAudioCloneUploading(true)
    setAudioCloneFeedback(null)
    setAudioVoiceActionFeedback(null)
    try {
      const response = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
      const url = String(response.data?.url || '').trim()
      if (!url) {
        throw new Error('未返回临时 URL')
      }
      setAudioCloneUrl(url)
      setAudioCloneFeedback({ type: 'success', text: '已上传音频并生成临时 URL（48 小时有效）。' })
    } catch (error) {
      const message = await extractApiErrorMessage(error, '上传复刻样本失败')
      setAudioCloneFeedback({ type: 'error', text: message })
    } finally {
      setAudioCloneUploading(false)
    }
  }

  const stopAudioCloneRecordingStream = () => {
    if (audioCloneStreamRef.current) {
      audioCloneStreamRef.current.getTracks().forEach((track) => track.stop())
      audioCloneStreamRef.current = null
    }
  }

  const discardAudioCloneRecording = () => {
    const recorder = audioCloneRecorderRef.current
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      try {
        if (recorder.state !== 'inactive') {
          recorder.stop()
        }
      } catch {
        // 忽略录音清理失败
      }
    }
    audioCloneRecorderRef.current = null
    audioCloneChunksRef.current = []
    setAudioCloneRecording(false)
    stopAudioCloneRecordingStream()
  }

  const uploadRecordedAudioClone = async (blob: Blob) => {
    setAudioCloneUploading(true)
    setAudioCloneFeedback(null)
    setAudioVoiceActionFeedback(null)
    try {
      const filename = `recording_${Date.now()}.webm`
      const file = new File([blob], filename, { type: blob.type || 'audio/webm' })
      const response = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)
      const url = String(response.data?.url || '').trim()
      if (!url) {
        throw new Error('未返回临时 URL')
      }
      setAudioCloneUrl(url)
      setAudioCloneRecordDialogOpen(false)
      setAudioCloneFeedback({ type: 'success', text: '录音已上传并生成临时 URL（48 小时有效）。' })
    } catch (error) {
      const message = await extractApiErrorMessage(error, '上传录音失败')
      setAudioCloneFeedback({ type: 'error', text: message })
    } finally {
      setAudioCloneUploading(false)
    }
  }

  const handleStartAudioCloneRecording = async () => {
    if (audioCloneLoading || audioCloneUploading || audioCloneRecording) {
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setAudioCloneFeedback({ type: 'error', text: '当前浏览器不支持录音，请改用上传音频。' })
      return
    }

    setAudioCloneFeedback(null)
    setAudioVoiceActionFeedback(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioCloneStreamRef.current = stream
      audioCloneChunksRef.current = []
      const recorder = new MediaRecorder(stream)
      audioCloneRecorderRef.current = recorder
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data && event.data.size > 0) {
          audioCloneChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = () => {
        const chunks = audioCloneChunksRef.current
        audioCloneChunksRef.current = []
        audioCloneRecorderRef.current = null
        setAudioCloneRecording(false)
        stopAudioCloneRecordingStream()
        if (chunks.length === 0) {
          setAudioCloneFeedback({ type: 'error', text: '未获取到录音数据，请重试。' })
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void uploadRecordedAudioClone(blob)
      }
      recorder.onerror = () => {
        audioCloneRecorderRef.current = null
        setAudioCloneRecording(false)
        stopAudioCloneRecordingStream()
        setAudioCloneFeedback({ type: 'error', text: '录音失败，请重试。' })
      }
      recorder.start()
      setAudioCloneRecording(true)
    } catch (error) {
      stopAudioCloneRecordingStream()
      setAudioCloneRecording(false)
      const message = await extractApiErrorMessage(error, '无法访问麦克风，请检查权限')
      setAudioCloneFeedback({ type: 'error', text: message })
    }
  }

  const handleStopAudioCloneRecording = () => {
    const recorder = audioCloneRecorderRef.current
    if (!recorder) {
      return
    }
    if (recorder.state === 'inactive') {
      audioCloneRecorderRef.current = null
      setAudioCloneRecording(false)
      stopAudioCloneRecordingStream()
      return
    }
    recorder.stop()
  }

  const handleOpenAudioCloneRecordDialog = () => {
    setAudioCloneFeedback(null)
    setAudioCloneRecordDialogOpen(true)
  }

  const handleCloseAudioCloneRecordDialog = () => {
    if (audioCloneRecording) {
      return
    }
    setAudioCloneRecordDialogOpen(false)
  }

  const handleCreateAudioClone = async () => {
    setAudioCloneLoading(true)
    setAudioCloneFeedback(null)
    setAudioVoiceActionFeedback(null)
    try {
      const response = await apiClient.createCosyVoiceV3PlusClone({
        name: audioCloneName.trim(),
        url: audioCloneUrl.trim(),
      })
      const voiceId = String(response.data?.voice_id || '').trim()
      await refreshAudioVoiceCatalog('cosyvoice-v3.5-plus', voiceId || undefined)
      setAudioCloneName('')
      setAudioCloneUrl('')
      setAudioCloneDialogOpen(false)
      setAudioVoiceActionFeedback({
        type: 'success',
        text: voiceId ? `已提交声音复刻任务：${voiceId}` : '已提交声音复刻任务，请稍后刷新音色列表。',
      })
    } catch (error) {
      const message = await extractApiErrorMessage(error, '创建复刻音色失败')
      setAudioCloneFeedback({ type: 'error', text: message })
    } finally {
      setAudioCloneLoading(false)
    }
  }

  const handleCreateAudioDesign = async () => {
    setAudioDesignLoading(true)
    setAudioDesignFeedback(null)
    setAudioVoiceActionFeedback(null)
    try {
      const response = await apiClient.createCosyVoiceV3PlusDesign({
        name: audioDesignName.trim(),
        voice_prompt: audioDesignPrompt.trim(),
        preview_text: audioDesignPreviewText.trim(),
      })
      const voiceId = String(response.data?.voice_id || '').trim()
      await refreshAudioVoiceCatalog('cosyvoice-v3.5-plus', voiceId || undefined)
      setAudioDesignName('')
      setAudioDesignPrompt('')
      setAudioDesignPreviewText('欢迎收听这段声音设计试听，我们从这里开始塑造角色的独特声线。')
      setAudioDesignDialogOpen(false)
      setAudioVoiceActionFeedback({
        type: 'success',
        text: voiceId ? `已提交声音设计任务：${voiceId}` : '已提交声音设计任务，请稍后刷新音色列表。',
      })
    } catch (error) {
      const message = await extractApiErrorMessage(error, '创建设计音色失败')
      setAudioDesignFeedback({ type: 'error', text: message })
    } finally {
      setAudioDesignLoading(false)
    }
  }

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

          const runtimeEntry: CatalogRuntimeEntry = {
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

          nextEntries[modelKey] = runtimeEntry
          for (const aliasKey of MODEL_CATALOG_ENTRY_ALIASES[modelKey] || []) {
            nextEntries[aliasKey] = runtimeEntry
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
    const primaryAsset = getPrimaryResultAsset(options.result)
    const primaryOutput = resolveResultAssetUrl(primaryAsset)
    if (!options.result || !primaryAsset || !primaryOutput) return

    updateCollectState(key, { loading: true, feedback: null })

    let localSaved = false
    try {
      const assetResponse = await apiClient.get(primaryOutput, { responseType: 'blob' })
      const assetBlob = assetResponse.data as Blob
      const resolvedMimeType = primaryAsset.mime_type || assetBlob.type || null
      const resolvedFileSize = primaryAsset.file_size ?? assetBlob.size ?? null
      const assetTitle = buildAssetTitle(options.prompt, options.fallbackTitle)
      const {
        localAssetRecord,
        didFallbackToBrowserStorage,
      } = await saveExplicitLocalUserAsset({
        assetUuid: primaryAsset.asset_uuid,
        mediaKind: primaryAsset.media_kind,
        blob: assetBlob,
        mimeType: resolvedMimeType,
        fileSize: resolvedFileSize,
        sourceModule: 'asset_studio',
        title: assetTitle,
        sourceUri: primaryAsset.source_uri,
        previewUri: primaryAsset.preview_uri,
        downloadUri: primaryAsset.download_uri,
        metadata: {
          kind: options.result.kind,
          mode: options.result.mode,
          model_id: options.result.model_id,
          metadata: options.result.metadata || {},
        },
      })
      localSaved = true

      await apiClient.createUserAsset({
        source_module: 'asset_studio',
        asset_kind: options.assetKind,
        asset_class: 'reusable',
        asset_uuid: primaryAsset.asset_uuid,
        storage_mode: 'local_mirror',
        title: assetTitle,
        description: options.prompt.trim() || null,
        source_uri: primaryAsset.source_uri || primaryOutput,
        preview_uri: primaryAsset.preview_uri || primaryOutput,
        download_uri: primaryAsset.download_uri || primaryOutput,
        mime_type: resolvedMimeType,
        file_size: resolvedFileSize,
        expires_at: primaryAsset.expires_at || null,
        model_id: options.result.model_id || null,
        generation_mode: options.result.mode || null,
        tags: options.tags || [],
        metadata_json: buildAssetStudioCollectedAssetMetadataContract(
          options.result.metadata,
          extractLocalAssetStorageMetadata(localAssetRecord),
        ),
        source_payload_json: buildAssetStudioCollectedSourcePayload({
          kind: options.result.kind,
          mode: options.result.mode,
          modelId: options.result.model_id,
          assets: options.result.assets || [],
          primaryAsset: options.result.primary_asset || null,
          metadata: options.result.metadata || {},
        }),
      })
      const successText = didFallbackToBrowserStorage
        ? '已收录到用户资产，但用户目录当前不可用，文件已回退保存到浏览器本地存储'
        : '已保存到本地并收录到用户资产'
      updateCollectState(key, {
        loading: false,
        feedback: { type: 'success', text: successText },
      })
    } catch (error) {
      updateCollectState(key, {
        loading: false,
        feedback: {
          type: 'error',
          text: await extractApiErrorMessage(
            error,
            localSaved ? '本地保存成功，但收录到用户资产失败' : '保存到本地资产库失败',
          ),
        },
      })
    }
  }

  useEffect(() => {
    if (activeTabId !== 'image') return
    if (imageUsesReferenceMode && !imageEditModelIds.has(imageModelId)) {
      setImageModelId(preferredImageEditModel?.value || assetStudioImageEditDefaultModelId)
      return
    }
    if (!imageUsesReferenceMode && imageEditModelIds.has(imageModelId)) {
      setImageModelId(preferredImageGenerationModel?.value || assetStudioImageGenerationDefaultModelId)
    }
  }, [
    activeTabId,
    assetStudioImageEditDefaultModelId,
    assetStudioImageGenerationDefaultModelId,
    imageEditModelIds,
    imageModelId,
    imageUsesReferenceMode,
    preferredImageEditModel,
    preferredImageGenerationModel,
  ])

  useEffect(() => {
    if (!imageRealModelOptions.some((option) => option.value === imageModelId)) {
      setImageModelId(
        imageUsesReferenceMode
          ? preferredImageEditModel?.value || assetStudioImageEditDefaultModelId
          : preferredImageGenerationModel?.value || assetStudioImageGenerationDefaultModelId,
      )
    }
  }, [
    assetStudioImageEditDefaultModelId,
    assetStudioImageGenerationDefaultModelId,
    imageModelId,
    imageRealModelOptions,
    imageUsesReferenceMode,
    preferredImageEditModel,
    preferredImageGenerationModel,
  ])

  useEffect(() => {
    if (activeTabId !== 'video') return
    if (videoUsesReferenceMode && videoModelId !== assetStudioMotionDefaultModelId) {
      setVideoModelId(preferredVideoReferenceModel?.value || assetStudioMotionDefaultModelId)
      return
    }
    if (!videoUsesReferenceMode && videoModelId === assetStudioMotionDefaultModelId) {
      setVideoModelId(preferredVideoGenerationModel?.value || assetStudioVideoGenerationDefaultModelId)
    }
  }, [
    activeTabId,
    assetStudioMotionDefaultModelId,
    assetStudioVideoGenerationDefaultModelId,
    preferredVideoGenerationModel,
    preferredVideoReferenceModel,
    videoModelId,
    videoUsesReferenceMode,
  ])

  useEffect(() => {
    if (!videoRealModelOptions.some((option) => option.value === videoModelId)) {
      setVideoModelId(
        videoUsesReferenceMode
          ? preferredVideoReferenceModel?.value || assetStudioMotionDefaultModelId
          : preferredVideoGenerationModel?.value || assetStudioVideoGenerationDefaultModelId,
      )
    }
  }, [
    assetStudioMotionDefaultModelId,
    assetStudioVideoGenerationDefaultModelId,
    preferredVideoGenerationModel,
    preferredVideoReferenceModel,
    videoModelId,
    videoRealModelOptions,
    videoUsesReferenceMode,
  ])

  useEffect(() => {
    if (!motionModelOptions.some((option) => option.value === motionModelId)) {
      setMotionModelId(preferredMotionModel?.value || assetStudioMotionDefaultModelId)
    }
  }, [assetStudioMotionDefaultModelId, motionModelId, motionModelOptions, preferredMotionModel])

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
      const preferredAudioModelId =
        audioGenerationType === 'music'
          ? assetStudioAudioMusicDefaultModelId
          : audioGenerationType === 'sound-effect'
            ? assetStudioAudioSoundEffectDefaultModelId
            : audioGenerationType === 'scene-audio'
              ? assetStudioAudioSceneDefaultModelId
              : assetStudioAudioSpeechDefaultModelId
      setAudioModelId(
        audioModelOptions.find((option) => option.value === preferredAudioModelId)?.value ||
          audioModelOptions[0]?.value ||
          preferredAudioModelId,
      )
    }
  }, [
    assetStudioAudioMusicDefaultModelId,
    assetStudioAudioSoundEffectDefaultModelId,
    assetStudioAudioSceneDefaultModelId,
    assetStudioAudioSpeechDefaultModelId,
    audioGenerationType,
    audioModelId,
    audioModelOptions,
  ])

  useEffect(() => {
    if (!audioDurationOptions.some((option) => option.value === audioDuration)) {
      setAudioDuration(audioDurationOptions[0]?.value || '30')
    }
  }, [audioDuration, audioDurationOptions])

  useEffect(() => {
    if (audioGenerationType === 'speech') {
      return
    }
    setAudioVoicePresets([])
    setAudioVoiceId('')
    setAudioVoiceLoading(false)
    setAudioCloneDialogOpen(false)
    setAudioCloneRecordDialogOpen(false)
    setAudioDesignDialogOpen(false)
    setAudioCloneRecording(false)
    discardAudioCloneRecording()
  }, [audioGenerationType])

  useEffect(() => {
    let cancelled = false

    if (audioGenerationType !== 'speech') {
      return () => {
        cancelled = true
      }
    }

    void (async () => {
      setAudioVoiceLoading(true)
      try {
        const response = await apiClient.getTtsVoices(audioModelId)
        const voices = Array.isArray(response.data?.voices)
          ? (response.data?.voices as SpeechVoicePreset[])
          : []
        if (cancelled) {
          return
        }
        applyAudioVoicePresets(voices)
      } catch {
        if (!cancelled) {
          setAudioVoicePresets([])
          setAudioVoiceId('')
        }
      } finally {
        if (!cancelled) {
          setAudioVoiceLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [audioGenerationType, audioModelId])

  useEffect(() => {
    if (audioModelId === 'cosyvoice-v3.5-plus') {
      return
    }
    setAudioCloneDialogOpen(false)
    setAudioCloneRecordDialogOpen(false)
    setAudioDesignDialogOpen(false)
    setAudioCloneFeedback(null)
    setAudioDesignFeedback(null)
    setAudioVoiceActionFeedback(null)
    setAudioCloneRecording(false)
    discardAudioCloneRecording()
  }, [audioModelId])

  useEffect(() => {
    return () => {
      discardAudioCloneRecording()
    }
  }, [])

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
    if (audioGenerationType === 'speech') {
      if (!audioPrompt.trim()) {
        setAudioError('请先填写语音文本')
        return
      }
      if (!audioVoiceId) {
        setAudioError(audioModelId === 'cosyvoice-v3.5-plus' ? '请先选择音色；CosyVoice 需要先创建复刻或设计音色。' : '请先选择音色')
        return
      }

      setAudioLoading(true)
      setAudioError(null)
      try {
        const formData = new FormData()
        formData.append('prompt', audioPrompt.trim())
        formData.append('generation_type', audioGenerationType)
        formData.append('model_id', audioModelId)
        formData.append('voice_id', audioVoiceId)
        formData.append('instruction', audioInstruction.trim())
        if (showAudioNumericSpeedControl) {
          formData.append('rate', audioRate)
        }
        formData.append('volume', audioVolume)

        const response = await apiClient.generateAssetStudioAudio(formData)
        setAudioResult(response.data as AssetStudioGenerateResponse)
      } catch (error) {
        setAudioError(await extractApiErrorMessage(error, '语音合成失败'))
      } finally {
        setAudioLoading(false)
      }
      return
    }
    if (!audioPrompt.trim()) {
      setAudioError(
        audioGenerationType === 'music'
          ? '请先填写配乐提示词'
          : audioGenerationType === 'scene-audio'
            ? '请先填写场景音频提示词'
            : '请先填写音效提示词',
      )
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
      if (audioGenerationType === 'scene-audio') {
        formData.append('speaker_ids', audioSpeakerIds.trim())
      }
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
                    {imageModelOptions.map((option) =>
                      option.value === '---divider---' ? (
                        <MenuItem key={option.value} value={option.value} disabled sx={{ color: 'rgba(255,255,255,0.3)', fontWeight: 600, textAlign: 'center' }}>
                          {option.label}
                        </MenuItem>
                      ) : (
                        renderModelOptionMenuItem(option as ModelOption, catalogRuntimeEntries[option.value]?.runtime_routing_signal)
                      )
                    )}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {selectedImageModel?.helper}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25, display: audioGenerationType === 'speech' ? 'none' : 'flex' }}>
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

              {audioGenerationType === 'speech' ? (
                <Alert severity={audioModelId === 'cosyvoice-v3.5-plus' && sortedAudioVoicePresets.length === 0 ? 'warning' : 'info'} sx={{ borderRadius: 3 }}>
                  {audioModelId === 'cosyvoice-v3.5-plus'
                    ? sortedAudioVoicePresets.length > 0
                      ? 'CosyVoice v3.5-plus 已接入语音合成模式，可直接使用你在耳畔星河中创建的复刻/设计音色。'
                      : 'CosyVoice v3.5-plus 没有系统音色，请先在耳畔星河中创建复刻或设计音色，再回到这里合成。'
                    : '语音合成会复用统一 TTS 运行时，可直接切换模型、音色与基础说话参数。'}
                </Alert>
              ) : null}

              {audioGenerationType === 'speech' ? (
                <TextField
                  multiline
                  minRows={8}
                  label="语音文本"
                  value={audioPrompt}
                  onChange={(event) => setAudioPrompt(event.target.value)}
                  placeholder="例如：欢迎来到深夜电台，今晚我们继续讲述这座城市里那些沉默但温柔的瞬间。"
                  InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                  sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                />
              ) : null}

              <TextField
                multiline
                minRows={8}
                label="图片提示词"
                value={imagePrompt}
                onChange={(event) => setImagePrompt(event.target.value)}
                placeholder="可以直接描述想生成的图片内容，也可以配合参考图做一致性生成。"
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ display: audioGenerationType === 'speech' ? 'none' : 'block', '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
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
                    {videoModelOptions.map((option) =>
                      option.value === '---divider---' ? (
                        <MenuItem key={option.value} value={option.value} disabled sx={{ color: 'rgba(255,255,255,0.3)', fontWeight: 600, textAlign: 'center' }}>
                          {option.label}
                        </MenuItem>
                      ) : (
                        renderModelOptionMenuItem(option as ModelOption, catalogRuntimeEntries[option.value]?.runtime_routing_signal)
                      )
                    )}
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
                    label={videoModelId === 'wan2.6-t2v-fast' ? '快速预览' : videoModelId === 'wan2.7-i2v' ? '稳定主体' : '正式生成'}
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
              result={displayedVideoResult}
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
                  <Chip size="small" label={motionModelId === 'wan2.7-i2v' ? '参考图驱动' : '镜头语言增强'} variant="outlined" sx={{ color: 'white' }} />
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
              <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' } }}>
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

              </Box>

              {audioGenerationType === 'sound-effect' ? (
                <Alert severity="info" sx={{ borderRadius: 3 }}>
                  当前音效链路使用 `Vidu Timing2Audio` 进行可控文生音效生成，支持通过时间轴编排多个音效事件，
                  适合动作、环境和叙事节点的精细化音效设计。
                </Alert>
              ) : null}

              {audioGenerationType === 'scene-audio' ? (
                <>
                  <Alert severity="info" sx={{ borderRadius: 3 }}>
                    豆包 Seed Audio 会按提示词顺序统一编排对白、环境声、动作音效和配乐。输出为 MP3 / 48 kHz，并自动保存到资产工作台。
                  </Alert>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    {[
                      ['对白场景', '安静的室内，窗外持续下雨。男子1用低沉严肃的语气说：“你终于来了。”女子1短暂停顿后平静回答：“有些答案，只能当面告诉你。”远处一声闷雷，低音弦乐缓慢进入。'],
                      ['悬疑追逐', '夜晚地下停车场，急促脚步声由远及近，汽车警报突然响起。男子1喘息着低声说：“别回头，继续跑。”随后传来轮胎摩擦地面的声音，紧张的电子打击乐逐渐增强。'],
                      ['氛围叙事', '清晨海边，海浪和海鸥声持续。旁白温和地讲述：“天亮以后，小镇又恢复了往日的平静。”木吉他与柔和钢琴缓慢铺开，最后只留下海浪声。'],
                    ].map(([label, prompt]) => (
                      <Button key={label} size="small" variant="outlined" onClick={() => setAudioPrompt(prompt)} sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}>
                        {label}
                      </Button>
                    ))}
                  </Stack>
                </>
              ) : null}

              <TextField
                multiline
                minRows={8}
                label={audioGenerationType === 'music' ? '配乐提示词' : audioGenerationType === 'scene-audio' ? '场景音频提示词' : '音效提示词'}
                value={audioPrompt}
                onChange={(event) => setAudioPrompt(event.target.value)}
                placeholder={
                  audioGenerationType === 'music'
                    ? '例如：夜色都市，低频铺底，缓慢推进，悬疑感钢琴与合成器氛围配乐。'
                    : audioGenerationType === 'scene-audio'
                      ? '按时间顺序描述环境、角色身份与语气、台词、动作音效、配乐及收尾。'
                      : '例如：雨夜巷口的脚步声与湿润地面回响，近景、短促、带一点紧张气氛。'
                }
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {audioGenerationType === 'scene-audio' ? (
                <TextField
                  size="small"
                  fullWidth
                  label="参考说话人 ID（可选）"
                  value={audioSpeakerIds}
                  onChange={(event) => setAudioSpeakerIds(event.target.value)}
                  placeholder="多个 speaker_id 使用逗号或换行分隔"
                  helperText="按角色出现顺序填写；留空时由模型根据角色描述生成声音。"
                  InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                  FormHelperTextProps={{ sx: { color: 'rgba(255,255,255,0.56)', mx: 0 } }}
                  sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                />
              ) : null}

              {audioGenerationType === 'speech' ? (
                <Stack spacing={1.5}>
                  <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: isCosyVoiceSpeechMode ? 'repeat(2, minmax(0, 1fr))' : '1fr' } }}>
                    <FormControl size="small" fullWidth>
                      <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>音色</InputLabel>
                      <Select
                        value={audioVoiceId}
                        label="音色"
                        onChange={(event) => setAudioVoiceId(event.target.value)}
                        sx={{ color: 'white' }}
                        disabled={audioVoiceLoading || sortedAudioVoicePresets.length === 0}
                      >
                        {audioVoiceLoading ? (
                          <MenuItem value="" disabled>
                            正在加载音色...
                          </MenuItem>
                        ) : null}
                        {!audioVoiceLoading && sortedAudioVoicePresets.length === 0 ? (
                          <MenuItem value="" disabled>
                            暂无可用音色
                          </MenuItem>
                        ) : null}
                        {sortedAudioVoicePresets.map((voice) => (
                          <MenuItem key={voice.id} value={voice.id}>
                            {voice.label}
                          </MenuItem>
                        ))}
                      </Select>
                      <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                        {sortedAudioVoicePresets.find((voice) => voice.id === audioVoiceId)?.description
                          || (audioModelId === 'cosyvoice-v3.5-plus' ? 'CosyVoice 只展示你当前账号下可用的复刻/设计音色。' : '选择一个音色后即可直接合成。')}
                      </FormHelperText>
                    </FormControl>

                    {isCosyVoiceSpeechMode ? (
                      <Box sx={{ p: 1.5, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                        <Box sx={{ display: 'grid', gap: 1, gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                          <Button
                            variant="outlined"
                            sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                            onClick={() => {
                              setAudioCloneFeedback(null)
                              setAudioCloneDialogOpen(true)
                            }}
                            disabled={audioCloneLoading || audioCloneUploading || audioDesignLoading}
                          >
                            声音复刻
                          </Button>
                          <Button
                            variant="outlined"
                            sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                            onClick={() => {
                              setAudioDesignFeedback(null)
                              setAudioDesignDialogOpen(true)
                            }}
                            disabled={audioCloneLoading || audioCloneUploading || audioDesignLoading}
                          >
                            声音设计
                          </Button>
                          <Button
                            variant="outlined"
                            sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                            onClick={() => {
                              void refreshAudioVoiceCatalog('cosyvoice-v3.5-plus').catch(async (error) => {
                                const message = await extractApiErrorMessage(error, '刷新音色失败')
                                setAudioVoiceActionFeedback({ type: 'error', text: message })
                              })
                            }}
                            disabled={audioVoiceLoading || audioCloneLoading || audioCloneUploading || audioDesignLoading}
                          >
                            {audioVoiceLoading ? '同步中...' : '刷新音色'}
                          </Button>
                        </Box>
                        {audioVoiceActionFeedback ? (
                          <Alert severity={audioVoiceActionFeedback.type} sx={{ mt: 1.25, borderRadius: 2 }}>
                            {audioVoiceActionFeedback.text}
                          </Alert>
                        ) : null}
                      </Box>
                    ) : null}
                  </Box>

                  <TextField
                    size="small"
                    fullWidth
                    label="语气指令（可选）"
                    value={audioInstruction}
                    onChange={(event) => setAudioInstruction(event.target.value)}
                    placeholder="例如：沉稳克制，吐字清晰，句尾轻收，像深夜电台主持人。"
                    InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                    sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                  />

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                    {showAudioNumericSpeedControl ? (
                      <TextField
                        size="small"
                        fullWidth
                        label="语速"
                        value={audioRate}
                        onChange={(event) => setAudioRate(event.target.value)}
                        InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                        sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                      />
                    ) : null}
                    <TextField
                      size="small"
                      fullWidth
                      label="音量"
                      value={audioVolume}
                      onChange={(event) => setAudioVolume(event.target.value)}
                      InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                      sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                    />
                  </Stack>
                </Stack>
              ) : null}

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ display: audioGenerationType === 'speech' || audioGenerationType === 'scene-audio' ? 'none' : 'flex' }}>
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
                  fallbackTitle: audioGenerationType === 'music' ? '配乐资产' : audioGenerationType === 'sound-effect' ? '音效资产' : audioGenerationType === 'scene-audio' ? '场景音频资产' : '语音资产',
                  tags: ['asset_studio', audioGenerationType === 'music' ? 'music' : audioGenerationType === 'sound-effect' ? 'sound-effect' : audioGenerationType === 'scene-audio' ? 'scene-audio' : 'speech'],
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
                : audioGenerationType === 'sound-effect'
                ? '音效模式使用 Vidu Timing2Audio 进行时间轴可控的音效生成。'
                : audioGenerationType === 'scene-audio'
                ? '场景音频模式使用豆包 Seed Audio 1.0，一次生成对白、环境声、音效与配乐，并持久化临时结果地址。'
                : '语音模式会调用统一 TTS 运行时，按所选模型、音色和说话参数直接输出语音资产。'}
            </Typography>
            <FooterAction loading={audioLoading} label="生成音频" onClick={handleGenerateAudio} />
          </Stack>
        </Box>
      ) : null}

      <Dialog
        open={audioCloneDialogOpen}
        onClose={() => {
          if (!audioCloneLoading && !audioCloneUploading && !audioCloneRecording && !audioCloneRecordDialogOpen) {
            setAudioCloneDialogOpen(false)
          }
        }}
        fullWidth
        maxWidth="sm"
        PaperProps={{ sx: WORKBENCH_DIALOG_PAPER_SX }}
        BackdropProps={{ sx: WORKBENCH_DIALOG_BACKDROP_SX }}
      >
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>声音复刻</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              支持 `http/https` 或上传样本后获得的临时 URL；创建完成后会自动刷新当前 CosyVoice 音色列表。
            </Alert>
            <TextField
              size="small"
              fullWidth
              label="声音名称"
              value={audioCloneName}
              onChange={(event) => setAudioCloneName(event.target.value)}
              disabled={audioCloneLoading || audioCloneUploading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <TextField
              size="small"
              fullWidth
              label="音频 URL"
              placeholder="支持 http/https 或 oss:// 临时地址"
              value={audioCloneUrl}
              onChange={(event) => setAudioCloneUrl(event.target.value)}
              disabled={audioCloneLoading || audioCloneUploading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <Button
                variant="outlined"
                component="label"
                disabled={audioCloneLoading || audioCloneUploading}
                sx={{ alignSelf: 'flex-start', borderColor: 'rgba(138,158,255,0.42)', color: '#d7e1ff' }}
              >
                {audioCloneUploading ? '上传中...' : '上传音频获取临时 URL'}
                <input hidden type="file" accept="audio/*" onChange={handleUploadAudioCloneSample} />
              </Button>
              <Button
                variant="outlined"
                onClick={handleOpenAudioCloneRecordDialog}
                disabled={audioCloneLoading || audioCloneUploading || audioCloneRecording}
                sx={{ alignSelf: 'flex-start', borderColor: 'rgba(138,158,255,0.42)', color: '#d7e1ff' }}
              >
                {audioCloneRecording ? '录音中...' : '录音获取临时 URL'}
              </Button>
              <Typography sx={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.78rem', lineHeight: 1.6 }}>
                上传或录音后会自动把临时 URL 回填到上方输入框。
              </Typography>
            </Stack>
            {audioCloneFeedback ? (
              <Alert severity={audioCloneFeedback.type} sx={{ borderRadius: 2.5 }}>
                {audioCloneFeedback.text}
              </Alert>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={WORKBENCH_DIALOG_ACTIONS_SX}>
          <Button
            onClick={() => setAudioCloneDialogOpen(false)}
            disabled={audioCloneLoading || audioCloneUploading || audioCloneRecording}
            sx={{ color: 'rgba(214,224,255,0.9)' }}
          >
            取消
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              void handleCreateAudioClone()
            }}
            disabled={audioCloneLoading || audioCloneUploading || !audioCloneName.trim() || !audioCloneUrl.trim()}
            sx={{
              minWidth: 132,
              borderRadius: 2.5,
              background: 'linear-gradient(135deg, #6f86ff 0%, #4c66ff 100%)',
              boxShadow: '0 12px 28px rgba(76,102,255,0.28)',
            }}
          >
            {audioCloneLoading ? '提交中...' : '开始复刻'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={audioCloneRecordDialogOpen}
        onClose={handleCloseAudioCloneRecordDialog}
        fullWidth
        maxWidth="xs"
        disableEscapeKeyDown={audioCloneRecording}
        PaperProps={{ sx: WORKBENCH_DIALOG_PAPER_SX }}
        BackdropProps={{ sx: WORKBENCH_DIALOG_BACKDROP_SX }}
      >
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>录音朗读提示</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.25}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              建议朗读约 10 秒，保持环境安静、音量稳定。录音完成后会自动上传并生成临时 URL。
            </Alert>
            <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
              <Typography sx={{ color: 'white', fontSize: '0.95rem', lineHeight: 1.8 }}>
                示例朗读：“时间会缓和所有的悲伤，当你的悲伤被安抚以后，你就会因为认识过我而感到满足。”
              </Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.78rem', mt: 1 }}>
                也可以随机朗读其他内容，只要音质清晰、长度足够即可。
              </Typography>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions sx={WORKBENCH_DIALOG_ACTIONS_SX}>
          <Button onClick={handleCloseAudioCloneRecordDialog} disabled={audioCloneRecording || audioCloneUploading} sx={{ color: 'rgba(214,224,255,0.9)' }}>
            关闭
          </Button>
          <Button
            variant="contained"
            color={audioCloneRecording ? 'error' : 'primary'}
            onClick={audioCloneRecording ? handleStopAudioCloneRecording : () => void handleStartAudioCloneRecording()}
            disabled={audioCloneLoading || audioCloneUploading}
            sx={{
              minWidth: 148,
              borderRadius: 2.5,
              background: audioCloneRecording
                ? 'linear-gradient(135deg, #ff7b7b 0%, #ef4444 100%)'
                : 'linear-gradient(135deg, #6f86ff 0%, #4c66ff 100%)',
              boxShadow: audioCloneRecording
                ? '0 12px 28px rgba(239,68,68,0.26)'
                : '0 12px 28px rgba(76,102,255,0.28)',
            }}
          >
            {audioCloneRecording ? '结束录音并上传' : '开始录音'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={audioDesignDialogOpen}
        onClose={() => {
          if (!audioDesignLoading) {
            setAudioDesignDialogOpen(false)
          }
        }}
        fullWidth
        maxWidth="sm"
        PaperProps={{ sx: WORKBENCH_DIALOG_PAPER_SX }}
        BackdropProps={{ sx: WORKBENCH_DIALOG_BACKDROP_SX }}
      >
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>声音设计</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              用自然语言描述声线、年龄感、气质和情绪，再提供一段试听文本，即可生成新的设计音色。
            </Alert>
            <TextField
              size="small"
              fullWidth
              label="设计名称"
              value={audioDesignName}
              onChange={(event) => setAudioDesignName(event.target.value)}
              disabled={audioDesignLoading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <TextField
              size="small"
              fullWidth
              label="声音描述"
              placeholder="例如：青年女性，声线清透冷静，带一点克制感，适合悬疑旁白。"
              value={audioDesignPrompt}
              onChange={(event) => setAudioDesignPrompt(event.target.value)}
              disabled={audioDesignLoading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <TextField
              size="small"
              fullWidth
              multiline
              minRows={3}
              label="试听文本"
              value={audioDesignPreviewText}
              onChange={(event) => setAudioDesignPreviewText(event.target.value)}
              disabled={audioDesignLoading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            {audioDesignFeedback ? (
              <Alert severity={audioDesignFeedback.type} sx={{ borderRadius: 2.5 }}>
                {audioDesignFeedback.text}
              </Alert>
            ) : null}
          </Stack>
        </DialogContent>
        <DialogActions sx={WORKBENCH_DIALOG_ACTIONS_SX}>
          <Button onClick={() => setAudioDesignDialogOpen(false)} disabled={audioDesignLoading} sx={{ color: 'rgba(214,224,255,0.9)' }}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              void handleCreateAudioDesign()
            }}
            disabled={audioDesignLoading || !audioDesignName.trim() || !audioDesignPrompt.trim() || !audioDesignPreviewText.trim()}
            sx={{
              minWidth: 132,
              borderRadius: 2.5,
              background: 'linear-gradient(135deg, #6f86ff 0%, #4c66ff 100%)',
              boxShadow: '0 12px 28px rgba(76,102,255,0.28)',
            }}
          >
            {audioDesignLoading ? '提交中...' : '开始设计'}
          </Button>
        </DialogActions>
      </Dialog>

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
