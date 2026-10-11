import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
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
  Slider,
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
import {
  SMART_DURATION_VALUE,
  buildCatalogDurationOptionsByModel,
  buildCatalogDurationRangesByModel,
  getDurationRange,
  getRuntimeDurationOptions,
  getSliderDurationValue,
  resolveDurationSelection,
} from '@/utils/assetStudioDurationControls'
import type { DurationOption, DurationRange } from '@/utils/assetStudioDurationControls'
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
  { labelKey: 'assetStudio.workbench.sizeImage1kSquare', width: 1024, height: 1024, value: '1024x1024' },
  { labelKey: 'assetStudio.workbench.sizeImage2kPortrait', width: 1536, height: 2048, value: '1536x2048' },
  { labelKey: 'assetStudio.workbench.sizeImageWide169', width: 1536, height: 864, value: '1536x864' },
  { labelKey: 'assetStudio.workbench.sizeImagePortrait916', width: 864, height: 1536, value: '864x1536' },
]

const VIDEO_SIZE_OPTIONS: SizeOption[] = [
  { labelKey: 'assetStudio.workbench.sizeVideo1080p', width: 1920, height: 1080, value: '1920x1080' },
  { labelKey: 'assetStudio.workbench.sizeVideo720p', width: 1280, height: 720, value: '1280x720' },
  { labelKey: 'assetStudio.workbench.sizeVideoPortrait916', width: 1080, height: 1920, value: '1080x1920' },
  { labelKey: 'assetStudio.workbench.sizeVideoSquare11', width: 1080, height: 1080, value: '1080x1080' },
]

interface ModelOption {
  value: string
  label: string
  labelKey?: string
  helper: string
  helperKey?: string
}

interface SizeOption {
  labelKey: string
  width: number
  height: number
  value: string
}

interface CameraControlOption {
  value: string
  label: string
  labelKey?: string
  helper: string
  helperKey?: string
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
    value: 'qwen-image-3.0',
    label: 'Qwen Image 3.0',
    labelKey: 'dreamweaverRun.modelImageQwen30',
    helperKey: 'assetStudio.workbench.helper.qwenImage30',
    helper: '项目默认图像模型，4500 Token 长指令、12 国语言小字清晰渲染，0.20 元/张。限流 20 QPM，批量出图需排队。',
  },
  {
    value: 'qwen-image-3.0-pro',
    label: 'Qwen Image 3.0 Pro',
    labelKey: 'dreamweaverRun.modelImageQwen30Pro',
    helperKey: 'assetStudio.workbench.helper.qwenImage30Pro',
    helper: '旗舰档，专攻报纸/菜单/分镜等密集图文排版与人像级质感，1K 档 0.27 元/张。限流仅 5 QPM。',
  },
  {
    value: 'wan2.7-image-pro',
    label: 'Wan 2.7 Image Pro',
    labelKey: 'dreamweaverRun.modelImageWan27Pro',
    helperKey: 'assetStudio.workbench.helper.wan27ImagePro',
    helper: '万相旗舰，支持 4K 文生图、9 图参考一致性、框选局部编辑与组图输出，0.5 元/张。无反向提示词。',
  },
  {
    value: 'doubao-seedream-5-0',
    label: 'Doubao Seedream 5.0',
    helperKey: 'assetStudio.workbench.helper.seedream50',
    helper: '豆包最新版本，支持超高分辨率和多种图像创作功能。',
  },
  {
    value: 'doubao-seedream-5-0-pro',
    label: 'Doubao Seedream 5.0 Pro',
    helperKey: 'assetStudio.workbench.helper.seedream50Pro',
    helper: '豆包旗舰文生图，取代已下线的 Seedream 4.5，画质与指令遵循更强。',
  },
  {
    value: 'kling/kling-v3-image-generation',
    label: 'Kling V3 图像生成',
    labelKey: 'assetStudio.workbench.model.klingV3Image',
    helperKey: 'assetStudio.workbench.helper.klingV3Image',
    helper: '快手可灵 V3 图像生成，高质量人物和场景。',
  },
  {
    value: 'kling/kling-v3-omni-image-generation',
    label: 'Kling V3 Omni 图像生成',
    labelKey: 'assetStudio.workbench.model.klingV3OmniImage',
    helperKey: 'assetStudio.workbench.helper.klingV3OmniImage',
    helper: '可灵全能版图像生成，支持图生图和风格迁移。',
  },
]

const IMAGE_EDIT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'qwen-image-edit-plus',
    label: 'Qwen Image Edit Plus',
    helperKey: 'assetStudio.workbench.helper.qwenImageEditPlus',
    helper: '参考图编辑主力，适合根据指令做稳定修改。',
  },
  {
    value: 'qwen-image-edit-max',
    label: 'Qwen Image Edit Max',
    helperKey: 'assetStudio.workbench.helper.qwenImageEditMax',
    helper: '质量更高，适合精修、复杂改图和最终素材处理。',
  },
]

const VIDEO_GENERATION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan3.0-video',
    label: 'Wan 3.0 Video',
    labelKey: 'dreamweaverRun.modelVideoWan30',
    helperKey: 'assetStudio.workbench.helper.wan30Video',
    helper: '项目唯一视频主力（all-in-one）：文生视频、首尾帧、多参考一致性、视频编辑与延长共用同一 ID，取代已弃用的 5 个分档模型。默认 720P，0.6 元/秒。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0',
    helperKey: 'assetStudio.workbench.helper.seedance20',
    helper: '支持最多9张参考图+3个参考视频+首尾帧，多模态控制最强。',
  },
  {
    value: 'doubao-seedance-2-0-fast',
    label: 'Doubao Seedance 2.0 Fast',
    helperKey: 'assetStudio.workbench.helper.seedance20Fast',
    helper: '豆包快速版本，适合原型验证和快速迭代。',
  },
  {
    value: 'kling/kling-v3-video-generation',
    label: 'Kling V3 视频生成',
    labelKey: 'assetStudio.workbench.model.klingV3Video',
    helperKey: 'assetStudio.workbench.helper.klingV3Video',
    helper: '快手可灵 V3，支持最多7张参考图+首尾帧+多镜头。',
  },
  {
    value: 'kling/kling-v3-omni-video-generation',
    label: 'Kling V3 Omni 视频生成',
    labelKey: 'assetStudio.workbench.model.klingV3OmniVideo',
    helperKey: 'assetStudio.workbench.helper.klingV3OmniVideo',
    helper: '快手可灵全能版本，支持多模态输入与复杂场景控制。',
  },
  {
    value: 'pixverse-v6-t2v',
    label: 'PixVerse V6',
    helperKey: 'assetStudio.workbench.helper.pixverseV6',
    helper: 'PixVerse V6 文生视频，支持首尾帧+多镜头+特效模板。',
  },
  {
    value: 'vidu-q3-pro-text2video',
    label: 'Vidu Q3 Pro 文生视频',
    labelKey: 'assetStudio.workbench.model.viduQ3Text',
    helperKey: 'assetStudio.workbench.helper.viduQ3Text',
    helper: 'Vidu Q3 Pro 文生视频链路，适合高质量视频创作。',
  },
  {
    value: 'vidu-q3-pro-img2video',
    label: 'Vidu Q3 Pro 图生视频',
    labelKey: 'assetStudio.workbench.model.viduQ3Img',
    helperKey: 'assetStudio.workbench.helper.viduQ3Img',
    helper: 'Vidu Q3 Pro 图生视频链路，支持参考图驱动视频生成。',
  },
  {
    value: 'vidu-q3-pro-start-end2video',
    label: 'Vidu Q3 Pro 首尾帧',
    labelKey: 'assetStudio.workbench.model.viduQ3StartEnd',
    helperKey: 'assetStudio.workbench.helper.viduQ3StartEnd',
    helper: 'Vidu Q3 Pro 首尾帧控制，适合精确控制视频起始和结束画面。',
  },
]

const VIDEO_EDIT_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan3.0-video',
    label: 'Wan 3.0 Video',
    labelKey: 'dreamweaverRun.modelVideoWan30',
    helperKey: 'assetStudio.workbench.helper.wan30Video',
    helper: '万相 all-in-one 视频模型，视频编辑与延长共用同一 ID，支持参考视频输入与多片段融合。',
  },
  {
    value: 'doubao-seedance-2-5',
    label: 'Doubao Seedance 2.5（编辑/延长）',
    helper: '全模态参考 + 视频编辑与延长，与后端 edit_video 白名单一致。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0',
    helperKey: 'assetStudio.workbench.helper.seedance20',
    helper: '支持最多9张参考图+3个参考视频+首尾帧，多模态控制最强。',
  },
  {
    value: 'doubao-seedance-2-0-fast',
    label: 'Doubao Seedance 2.0 Fast',
    helperKey: 'assetStudio.workbench.helper.seedance20Fast',
    helper: '豆包快速版本，适合原型验证和快速迭代。',
  },
]

// 目录不可用时的兜底动作组，与后端 asset_studio_model_catalog 由 models.yaml modality
// （image_to_video）派生出的 motion 分组同源；档案只有 text_to_video 的档位不得出现在这里
const MOTION_MODEL_OPTIONS: ModelOption[] = [
  {
    value: 'wan3.0-video',
    label: 'Wan 3.0 Video',
    labelKey: 'dreamweaverRun.modelVideoWan30',
    helperKey: 'assetStudio.workbench.helper.wan30Video',
    helper: '万相 all-in-one 视频模型，支持多图参考与首尾帧驱动，主体一致性与动作控制最强。',
  },
  {
    value: 'doubao-seedance-2-5',
    label: 'Doubao Seedance 2.5',
    helper: '全模态参考 + 首尾帧驱动，动作迁移与主体一致性最强。',
  },
  {
    value: 'doubao-seedance-2-0',
    label: 'Doubao Seedance 2.0',
    helperKey: 'assetStudio.workbench.helper.seedance20',
    helper: '支持最多9张参考图+3个参考视频+首尾帧，多模态控制最强。',
  },
  {
    value: 'doubao-seedance-2-0-fast',
    label: 'Doubao Seedance 2.0 Fast',
    helperKey: 'assetStudio.workbench.helper.seedance20Fast',
    helper: '豆包快速版本，适合原型验证和快速迭代。',
  },
  {
    value: 'kling/kling-v3-video-generation',
    label: 'Kling V3',
    helperKey: 'assetStudio.workbench.helper.klingV3',
    helper: '支持最多7张参考图+首尾帧+多镜头生成。',
  },
  {
    value: 'kling/kling-v3-omni-video-generation',
    label: 'Kling V3 Omni',
    helperKey: 'assetStudio.workbench.helper.klingV3Omni',
    helper: '可灵全能版，支持多模态输入+首尾帧+多镜头。',
  },
  {
    value: 'vidu-q3-pro-img2video',
    label: 'Vidu Q3 Pro 图生视频',
    labelKey: 'assetStudio.workbench.model.viduQ3Img',
    helperKey: 'assetStudio.workbench.helper.viduQ3Img',
    helper: 'Vidu Q3 Pro 图生视频链路，支持参考图驱动视频生成。',
  },
  {
    value: 'vidu-q3-pro-start-end2video',
    label: 'Vidu Q3 Pro 首尾帧',
    labelKey: 'assetStudio.workbench.model.viduQ3StartEnd',
    helperKey: 'assetStudio.workbench.helper.viduQ3StartEnd',
    helper: 'Vidu Q3 Pro 首尾帧控制，适合精确控制视频起始和结束画面。',
  },
]

const CAMERA_CONTROL_OPTIONS: CameraControlOption[] = [
  {
    value: '',
    label: '自动',
    labelKey: 'assetStudio.workbench.camera.auto',
    helperKey: 'assetStudio.workbench.camera.autoHelper',
    helper: '不额外指定镜头运动，让模型自行决定。',
  },
  {
    value: '镜头稳定，以主体动作为主',
    label: '固定机位',
    labelKey: 'assetStudio.workbench.camera.fixed',
    helperKey: 'assetStudio.workbench.camera.fixedHelper',
    helper: '更稳，更适合展示人物动作和表情。',
  },
  {
    value: '镜头缓慢推进，聚焦主体',
    label: '缓慢推进',
    labelKey: 'assetStudio.workbench.camera.push',
    helperKey: 'assetStudio.workbench.camera.pushHelper',
    helper: '适合突出人物、物体或情绪焦点。',
  },
  {
    value: '镜头轻微平移，保持节奏稳定',
    label: '轻微平移',
    labelKey: 'assetStudio.workbench.camera.pan',
    helperKey: 'assetStudio.workbench.camera.panHelper',
    helper: '适合展示空间关系和场景横向变化。',
  },
  {
    value: '镜头轻微跟随主体移动，保持构图稳定',
    label: '轻微跟拍',
    labelKey: 'assetStudio.workbench.camera.follow',
    helperKey: 'assetStudio.workbench.camera.followHelper',
    helper: '适合人物走位、奔跑和连续动作。',
  },
  {
    value: '镜头轻微环绕主体，突出空间层次',
    label: '轻微环绕',
    labelKey: 'assetStudio.workbench.camera.orbit',
    helperKey: 'assetStudio.workbench.camera.orbitHelper',
    helper: '适合表现空间感、立体感和展示感。',
  },
]

const MOTION_LEVEL_HELPER_KEYS: Record<string, string> = {
  low: 'assetStudio.workbench.motionLevel.low',
  medium: 'assetStudio.workbench.motionLevel.medium',
  high: 'assetStudio.workbench.motionLevel.high',
}

const AUDIO_GENERATION_TYPE_OPTIONS: Array<{ value: AudioGenerationType; label: string; labelKey: string; helper: string; helperKey: string }> = [
  {
    value: 'music',
    label: '配乐生成',
    labelKey: 'assetStudio.workbench.audioType.music',
    helper: '适合背景音乐、氛围音乐和预告片配乐。',
    helperKey: 'assetStudio.workbench.audioType.musicHelper',
  },
  {
    value: 'sound-effect',
    label: '音效生成',
    labelKey: 'assetStudio.workbench.audioType.soundEffect',
    helper: '适合环境音、动作音和短时音效草案。',
    helperKey: 'assetStudio.workbench.audioType.soundEffectHelper',
  },
  {
    value: 'scene-audio',
    label: '场景音频',
    labelKey: 'assetStudio.workbench.audioType.sceneAudio',
    helper: '在一条导演式提示词中统一生成多角色对白、环境声、动作音效和配乐。',
    helperKey: 'assetStudio.workbench.audioType.sceneAudioHelper',
  },
  {
    value: 'speech',
    label: '语音合成',
    labelKey: 'assetStudio.workbench.audioType.speech',
    helper: '适合旁白、对白和角色试听，可直接选择 TTS 模型与音色。',
    helperKey: 'assetStudio.workbench.audioType.speechHelper',
  },
]

const AUDIO_MODEL_OPTIONS_BY_TYPE: Record<AudioGenerationType, ModelOption[]> = {
  music: [
    {
      value: 'mureka-o1-instrumental',
      label: 'mureka-o1-instrumental',
      helperKey: 'assetStudio.workbench.helper.murekaO1Instrumental',
      helper: '当前资产工作台的纯音乐主力模型，适合配乐和氛围音乐。',
    },
  ],
  'sound-effect': [
    {
      value: 'seed-audio-1.0',
      label: '豆包音频生成模型 1.0',
      labelKey: 'assetStudio.workbench.model.seedAudio10',
      helperKey: 'assetStudio.workbench.helper.seedAudioSoundEffect',
      helper: '音效链路默认模型，按提示词生成短音效与环境音，实际时长由模型决定。',
    },
  ],
  'scene-audio': [
    {
      value: 'seed-audio-1.0',
      label: '豆包音频生成模型 1.0',
      labelKey: 'assetStudio.workbench.model.seedAudio10',
      helperKey: 'assetStudio.workbench.helper.seedAudio10',
      helper: '适合有声剧和影视场景预演，可在一次生成中组合对白、环境、音效与音乐。',
    },
  ],
  speech: [
    {
      value: 'qwen-audio-3.1-tts-flash',
      label: 'Qwen-Audio 3.1 TTS Flash',
      helperKey: 'assetStudio.workbench.helper.qwenAudio31TtsFlash',
      helper: '速度快、出稿稳，适合旁白草稿、对白验证和大批量试听。',
    },
    {
      value: 'cosyvoice-v3.5-plus',
      label: 'CosyVoice v3.5-plus',
      helperKey: 'assetStudio.workbench.helper.cosyvoiceV35',
      helper: '高表现力语音模型，支持 instruction，但必须先选择复刻或设计音色。',
    },
    {
      value: 'minimax-speech-2.8-hd',
      label: 'MiniMax Speech 2.8 HD',
      helperKey: 'assetStudio.workbench.helper.minimaxSpeech28Hd',
      helper: '音质优先，适合高保真语音样稿和更细腻的情感表达。',
    },
    {
      value: 'minimax-speech-2.8-turbo',
      label: 'MiniMax Speech 2.8 Turbo',
      helperKey: 'assetStudio.workbench.helper.minimaxSpeech28Turbo',
      helper: '兼顾速度和质量，适合快速迭代语音草案。',
    },
  ],
}

const AUDIO_DURATION_OPTIONS_BY_TYPE: Record<AudioGenerationType, DurationOption[]> = {
  music: [
    { value: '15' },
    { value: '30' },
    { value: '45' },
    { value: '60' },
  ],
  'sound-effect': [
    { value: '3' },
    { value: '5' },
    { value: '8' },
    { value: '10' },
  ],
  'scene-audio': [],
  speech: [],
}

const AUDIO_STYLE_OPTIONS = [
  { value: '氛围', labelKey: 'assetStudio.workbench.audioStyle.ambient' },
  { value: '流行', labelKey: 'assetStudio.workbench.audioStyle.pop' },
  { value: '电子', labelKey: 'assetStudio.workbench.audioStyle.electronic' },
  { value: '钢琴', labelKey: 'assetStudio.workbench.audioStyle.piano' },
  { value: '悬疑', labelKey: 'assetStudio.workbench.audioStyle.suspense' },
  { value: '史诗', labelKey: 'assetStudio.workbench.audioStyle.epic' },
  { value: '影视配乐', labelKey: 'assetStudio.workbench.audioStyle.filmScore' },
]

const AUDIO_MOOD_OPTIONS = [
  { value: 'calm', labelKey: 'assetStudio.workbench.audioMood.calm' },
  { value: 'tense', labelKey: 'assetStudio.workbench.audioMood.tense' },
  { value: 'exciting', labelKey: 'assetStudio.workbench.audioMood.exciting' },
  { value: 'mysterious', labelKey: 'assetStudio.workbench.audioMood.mysterious' },
  { value: 'sad', labelKey: 'assetStudio.workbench.audioMood.sad' },
]

const AUDIO_TEMPO_OPTIONS = [
  { value: 'slow', labelKey: 'assetStudio.workbench.audioTempo.slow' },
  { value: 'medium', labelKey: 'assetStudio.workbench.audioTempo.medium' },
  { value: 'fast', labelKey: 'assetStudio.workbench.audioTempo.fast' },
]

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
  runtimeCapabilityHints?: RuntimeCapabilityHints | null,
): boolean {
  // 在售的 wan3.0-video 上游不支持 camera_control，只有运行时能力提示显式给出 true 才放开
  return runtimeCapabilityHints?.supports_camera_control === true
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

function getRoutingStatusLabel(signal?: RuntimeRoutingSignal | null, t?: TFunction): string {
  if (signal?.blocked) {
    return t ? t('assetStudio.workbench.routing.statusBlocked') : '近期失败'
  }
  if (signal?.stale) {
    return t ? t('assetStudio.workbench.routing.statusStale') : '信号过期'
  }

  switch (signal?.verification_status) {
    case 'verified':
      return t ? t('assetStudio.workbench.routing.statusVerified') : '已校验'
    case 'partial':
      return t ? t('assetStudio.workbench.routing.statusPartial') : '部分校验'
    case 'failed':
      return t ? t('assetStudio.workbench.routing.statusFailed') : '校验失败'
    case 'pending':
      return t ? t('assetStudio.workbench.routing.statusPending') : '待校验'
    default:
      return t ? t('assetStudio.workbench.routing.statusUnverified') : '未校验'
  }
}

function getRoutingStatusHelper(signal?: RuntimeRoutingSignal | null, t?: TFunction): string | null {
  if (signal?.blocked) {
    return t ? t('assetStudio.workbench.routing.helperBlocked') : '该模型最近一次联网校验失败，运行时会优先自动改选其他可用模型。'
  }
  if (signal?.stale) {
    return t ? t('assetStudio.workbench.routing.helperStale') : '该模型的联网校验信号已过期，当前约束可能不是最新官方状态。'
  }

  switch (signal?.verification_status) {
    case 'verified':
      return t ? t('assetStudio.workbench.routing.helperVerified') : '最近一次联网校验通过，当前模型状态和能力约束可信度更高。'
    case 'partial':
      return t ? t('assetStudio.workbench.routing.helperPartial') : '仅完成部分联网校验，建议结合实际生成结果继续确认。'
    case 'failed':
      return t ? t('assetStudio.workbench.routing.helperFailed') : '最近一次联网校验失败，但已超出阻断窗口，运行时仍可能尝试回退使用。'
    case 'pending':
      return t ? t('assetStudio.workbench.routing.helperPending') : '该模型尚未完成联网校验，当前主要依赖本地模型档案。'
    default:
      return null
  }
}

function formatRoutingAge(ageHours?: number | null, t?: TFunction): string | null {
  if (typeof ageHours !== 'number' || !Number.isFinite(ageHours) || ageHours < 0) {
    return null
  }
  if (ageHours < 1) {
    return t ? t('assetStudio.workbench.routing.ageWithinHour') : '1 小时内'
  }
  if (ageHours < 24) {
    const hours = Math.round(ageHours)
    return t ? t('assetStudio.workbench.routing.ageHours', { count: hours }) : `${hours} 小时前`
  }
  const days = Math.round(ageHours / 24)
  return t ? t('assetStudio.workbench.routing.ageDays', { count: days }) : `${days} 天前`
}

function getRoutingStatusMetaLine(signal?: RuntimeRoutingSignal | null, t?: TFunction): string | null {
  const parts: string[] = []
  const ageLabel = formatRoutingAge(signal?.age_hours, t)
  if (ageLabel) {
    parts.push(t ? t('assetStudio.workbench.routing.metaCheckedAt', { label: ageLabel }) : `最近校验：${ageLabel}`)
  }

  if (typeof signal?.reason === 'string') {
    const reason = signal.reason.trim()
    if (reason) {
      const preview = reason.length > 64 ? `${reason.slice(0, 64)}...` : reason
      parts.push(t ? t('assetStudio.workbench.routing.metaReason', { reason: preview }) : `原因：${preview}`)
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

function renderModelOptionMenuItem(option: ModelOption, signal?: RuntimeRoutingSignal | null, t?: TFunction) {
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
          {option.labelKey ? t?.(option.labelKey) : option.label}
        </Typography>
        <Chip
          size="small"
          label={getRoutingStatusLabel(signal, t)}
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

function renderRoutingStatusMeta(signal?: RuntimeRoutingSignal | null, t?: TFunction) {
  const helper = getRoutingStatusHelper(signal, t)
  const metaLine = getRoutingStatusMetaLine(signal, t)
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
          {t ? t('assetStudio.workbench.routing.blockedAlert') : '当前模型近期联网校验失败，运行时会优先自动改选其他可用模型。'}
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
  t?: TFunction,
) {
  if (!shouldRecommendAlternativeModel(selectedModelId, recommendedOption, runtimeEntries) || !recommendedOption) {
    return null
  }

  const recommendedSignal = runtimeEntries[recommendedOption.value]?.runtime_routing_signal
  const recommendedLabel = recommendedOption.labelKey ? t?.(recommendedOption.labelKey) : recommendedOption.label

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
        {t ? t('assetStudio.workbench.routing.recommendSwitch', { model: recommendedLabel, status: getRoutingStatusLabel(recommendedSignal, t) }) : `推荐改用 ${recommendedLabel}，当前联网校验状态更优（${getRoutingStatusLabel(recommendedSignal, t)}）。`}
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
        {t ? t('assetStudio.workbench.routing.switchRecommended') : '改用推荐模型'}
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

function renderOptionHelperText(
  option: { helperKey?: string; helper?: string } | null | undefined,
  t?: TFunction,
): string | undefined {
  if (!option) {
    return undefined
  }
  if (option.helperKey) {
    return t ? t(option.helperKey) : option.helper
  }
  return option.helper
}

function UploadCard({
  title,
  subtitle,
  multiple = false,
  accept,
  fileCount,
  fileLabel,
  onChange,
  t,
}: {
  title: string
  subtitle: string
  multiple?: boolean
  accept?: string
  fileCount: number
  fileLabel: string
  onChange: (files: FileList | null) => void
  t?: TFunction
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
        label={fileCount > 0 ? fileLabel : multiple ? (t ? t('assetStudio.workbench.upload.clickMulti') : '点击上传多张') : (t ? t('assetStudio.workbench.upload.click') : '点击上传')}
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
  t,
}: {
  title: string
  result: AssetStudioGenerateResponse | null
  loading: boolean
  error: string | null
  mediaType?: AssetStudioMediaType
  onCollect?: (() => void) | null
  collecting?: boolean
  collectFeedback?: CollectFeedback | null
  t?: TFunction
}) {
  const primaryOutput = resolveResultAssetUrl(getPrimaryResultAsset(result))
  const requestedModelId = typeof result?.metadata?.requested_model_id === 'string'
    ? String(result.metadata.requested_model_id).trim()
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
                <Chip size="small" label={t ? t('assetStudio.workbench.result.modeChip', { value: result.mode || 'unknown' }) : `模式：${result.mode || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
                <Chip size="small" label={t ? t('assetStudio.workbench.result.modelChip', { value: result.model_id || 'unknown' }) : `模型：${result.model_id || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
                {hasRequestedModelMismatch ? (
                  <Chip size="small" label={t ? t('assetStudio.workbench.result.requestedModelChip', { value: requestedModelId }) : `请求模型：${requestedModelId}`} sx={{ color: 'white' }} variant="outlined" />
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
          <Typography sx={{ color: 'rgba(255,255,255,0.74)', fontSize: '0.9rem' }}>{t ? t('assetStudio.workbench.result.generating') : '正在调用模型生成资产...'}</Typography>
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
            <Chip size="small" label={t ? t('assetStudio.workbench.result.modeChip', { value: result?.mode || 'unknown' }) : `模式：${result?.mode || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
            <Chip size="small" label={t ? t('assetStudio.workbench.result.modelChip', { value: result?.model_id || 'unknown' }) : `模型：${result?.model_id || 'unknown'}`} sx={{ color: 'white' }} variant="outlined" />
            {hasRequestedModelMismatch ? (
              <Chip size="small" label={t ? t('assetStudio.workbench.result.requestedModelChip', { value: requestedModelId }) : `请求模型：${requestedModelId}`} sx={{ color: 'white' }} variant="outlined" />
            ) : null}
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
              {collecting
                ? (t ? t('assetStudio.workbench.result.collecting') : '收录中...')
                : (t ? t('assetStudio.workbench.result.collect') : '收录到用户资产')}
            </Button>
            <Button
              component="a"
              href={primaryOutput}
              target="_blank"
              rel="noreferrer"
              variant="outlined"
              sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.18)' }}
            >
              {t ? t('assetStudio.workbench.result.viewOriginal') : '查看原文件'}
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
            {t ? t('assetStudio.workbench.result.emptyHint') : '这里会展示最新一次生成结果。当前支持直接调用资产生成 API，不经过项目工作流。'}
          </Typography>
        </Stack>
      )}
    </Box>
  )
}

function DurationRangeControl({
  label,
  value,
  range,
  onChange,
  t,
}: {
  label: string
  value: string
  range: DurationRange
  onChange: (value: string) => void
  t: TFunction
}) {
  const smartDuration = range.supportsAuto && value === SMART_DURATION_VALUE
  const sliderValue = getSliderDurationValue(value, range)
  const [draftText, setDraftText] = useState(String(sliderValue))

  useEffect(() => {
    setDraftText(String(sliderValue))
  }, [sliderValue])

  const commitDraft = function() {
    onChange(String(getSliderDurationValue(draftText, range)))
  }

  return (
    <Box sx={{ minWidth: 232 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.25 }}>
        <Typography sx={{ color: 'rgba(255,255,255,0.68)', fontSize: '0.78rem' }}>{label}</Typography>
        {range.supportsAuto ? (
          <Button
            size="small"
            onClick={() => onChange(smartDuration ? String(range.defaultValue) : SMART_DURATION_VALUE)}
            sx={{
              borderRadius: 2,
              px: 1.25,
              py: 0.25,
              fontSize: '0.72rem',
              fontWeight: 700,
              backgroundColor: smartDuration ? 'rgba(139,161,255,0.86)' : 'transparent',
              border: smartDuration ? '1px solid transparent' : '1px solid rgba(255,255,255,0.24)',
              color: smartDuration ? '#0d1226' : 'rgba(255,255,255,0.82)',
            }}
          >
            {t('assetStudio.workbench.durationSmart')}
          </Button>
        ) : null}
      </Stack>
      <Slider
        value={sliderValue}
        min={range.min}
        max={range.max}
        step={range.step}
        disabled={smartDuration}
        valueLabelDisplay="auto"
        getAriaLabel={() => label}
        onChange={(_event, next) => onChange(String(Array.isArray(next) ? next[0] : next))}
        sx={{ color: 'rgba(167,186,255,0.85)', mx: 0.5 }}
      />
      <Stack direction="row" alignItems="center" spacing={1}>
        <TextField
          size="small"
          type="number"
          value={draftText}
          disabled={smartDuration}
          onChange={(event) => setDraftText(event.target.value)}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              commitDraft()
            }
          }}
          inputProps={{ min: range.min, max: range.max, step: range.step }}
          sx={{
            width: 104,
            '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' },
          }}
        />
        <Typography sx={{ color: 'rgba(255,255,255,0.56)', fontSize: '0.76rem' }}>
          {smartDuration
            ? t('assetStudio.workbench.durationSmartHint')
            : t('assetStudio.workbench.durationRangeHint', { min: range.min, max: range.max })}
        </Typography>
      </Stack>
    </Box>
  )
}

function FooterAction({
  loading,
  label,
  onClick,
  disabled,
  t,
}: {
  loading: boolean
  label: string
  onClick: () => void
  disabled?: boolean
  t?: TFunction
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
      {loading ? (t ? t('assetStudio.workbench.action.generating') : '生成中...') : label}
    </Button>
  )
}

export default function AssetStudioWorkbench({ activeTabId, entries, onRequestTabChange }: AssetStudioWorkbenchProps) {
  const { t } = useTranslation()
  const activeEntry = entries.find((entry) => entry.id === activeTabId) || entries[0]
  const ActiveIcon = activeEntry.icon
  const [catalogRuntimeEntries, setCatalogRuntimeEntries] = useState<Record<string, CatalogRuntimeEntry>>({})
  const { catalog: assetStudioModelCatalog } = useAssetStudioModelCatalog()

  const assetStudioImageGenerationDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_image_generation || 'qwen-image-3.0'
  const assetStudioImageEditDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_image_edit || 'qwen-image-edit-plus'
  const assetStudioVideoGenerationDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_video_generation || 'wan3.0-video'
  const assetStudioMotionDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_motion || 'wan3.0-video'
  const assetStudioAudioMusicDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_music || 'mureka-o1-instrumental'
  const assetStudioAudioSoundEffectDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_sound_effect || 'seed-audio-1.0'
  const assetStudioAudioSceneDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_scene || 'seed-audio-1.0'
  const assetStudioAudioSpeechDefaultModelId =
    assetStudioModelCatalog?.defaults.asset_studio_audio_speech || 'qwen-audio-3.1-tts-flash'

  const [imagePrompt, setImagePrompt] = useState('')
  const [imageNegativePrompt, setImageNegativePrompt] = useState('')
  const [imageModelId, setImageModelId] = useState('qwen-image-3.0')
  const [imageSize, setImageSize] = useState(IMAGE_SIZE_OPTIONS[0].value)
  const [imageReferenceFiles, setImageReferenceFiles] = useState<File[]>([])
  const [imageLoading, setImageLoading] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)
  const [imageResult, setImageResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [videoPrompt, setVideoPrompt] = useState('')
  const [videoModelId, setVideoModelId] = useState('wan3.0-video')
  const [videoDuration, setVideoDuration] = useState('5')
  const [videoSize, setVideoSize] = useState(VIDEO_SIZE_OPTIONS[1].value)
  const [videoCameraControl, setVideoCameraControl] = useState('')
  const [videoReferenceFile, setVideoReferenceFile] = useState<File | null>(null)
  const [videoLoading, setVideoLoading] = useState(false)
  const [videoError, setVideoError] = useState<string | null>(null)
  const [videoResult, setVideoResult] = useState<AssetStudioGenerateResponse | null>(null)

  const [motionPrompt, setMotionPrompt] = useState('')
  const [motionModelId, setMotionModelId] = useState('wan3.0-video')
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
  const [audioDesignPreviewText, setAudioDesignPreviewText] = useState(() => t('assetStudio.workbench.voice.designPreviewDefault'))
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
  const catalogDurationRangesByModel = buildCatalogDurationRangesByModel(assetStudioModelCatalog?.groups)
  const imageGenerationModelOptions =
    assetStudioModelCatalog?.groups.image_generation?.map(mapCatalogOptionToModelOption) || IMAGE_GENERATION_MODEL_OPTIONS
  const imageEditModelOptions =
    assetStudioModelCatalog?.groups.image_edit?.map(mapCatalogOptionToModelOption) || IMAGE_EDIT_MODEL_OPTIONS
  const imageModelOptions =
    imageEditModelOptions.length > 0
      ? [...imageGenerationModelOptions, { value: '---divider---' as const, label: t('assetStudio.workbench.model.imageEditDivider') }, ...imageEditModelOptions]
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
      ? [...videoGenerationModelOptions, { value: '---divider---' as const, label: t('assetStudio.workbench.model.videoEditDivider') }, ...videoEditModelOptions]
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
  const videoDurationRange = getDurationRange(videoModelId, catalogDurationRangesByModel)
  const videoSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedVideoCatalogEntry?.runtime_task_constraints)
  const videoSupportsCameraControl = getSupportsCameraControl(selectedVideoCatalogEntry?.runtime_capability_hints)
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
  const motionDurationRange = getDurationRange(motionModelId, catalogDurationRangesByModel)
  const motionSizeOptions = filterSizeOptions(VIDEO_SIZE_OPTIONS, selectedMotionCatalogEntry?.runtime_task_constraints)
  const motionSupportsCameraControl = getSupportsCameraControl(selectedMotionCatalogEntry?.runtime_capability_hints)
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
        throw new Error(t('assetStudio.workbench.error.missingTempUrl'))
      }
      setAudioCloneUrl(url)
      setAudioCloneFeedback({ type: 'success', text: t('assetStudio.workbench.voice.sampleUploaded') })
    } catch (error) {
      const message = await extractApiErrorMessage(error, t('assetStudio.workbench.error.uploadCloneSampleFailed'))
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
        throw new Error(t('assetStudio.workbench.error.missingTempUrl'))
      }
      setAudioCloneUrl(url)
      setAudioCloneRecordDialogOpen(false)
      setAudioCloneFeedback({ type: 'success', text: t('assetStudio.workbench.voice.recordingUploaded') })
    } catch (error) {
      const message = await extractApiErrorMessage(error, t('assetStudio.workbench.error.uploadRecordingFailed'))
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
      setAudioCloneFeedback({ type: 'error', text: t('assetStudio.workbench.voice.recordingUnsupported') })
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
          setAudioCloneFeedback({ type: 'error', text: t('assetStudio.workbench.voice.noRecordingData') })
          return
        }
        const blob = new Blob(chunks, { type: chunks[0]?.type || 'audio/webm' })
        void uploadRecordedAudioClone(blob)
      }
      recorder.onerror = () => {
        audioCloneRecorderRef.current = null
        setAudioCloneRecording(false)
        stopAudioCloneRecordingStream()
        setAudioCloneFeedback({ type: 'error', text: t('assetStudio.workbench.voice.recordingFailed') })
      }
      recorder.start()
      setAudioCloneRecording(true)
    } catch (error) {
      stopAudioCloneRecordingStream()
      setAudioCloneRecording(false)
      const message = await extractApiErrorMessage(error, t('assetStudio.workbench.error.micAccessDenied'))
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
        text: voiceId
          ? t('assetStudio.workbench.voice.cloneSubmittedWithId', { voiceId })
          : t('assetStudio.workbench.voice.cloneSubmitted'),
      })
    } catch (error) {
      const message = await extractApiErrorMessage(error, t('assetStudio.workbench.error.createCloneFailed'))
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
      setAudioDesignPreviewText(t('assetStudio.workbench.voice.designPreviewDefault'))
      setAudioDesignDialogOpen(false)
      setAudioVoiceActionFeedback({
        type: 'success',
        text: voiceId
          ? t('assetStudio.workbench.voice.designSubmittedWithId', { voiceId })
          : t('assetStudio.workbench.voice.designSubmitted'),
      })
    } catch (error) {
      const message = await extractApiErrorMessage(error, t('assetStudio.workbench.error.createDesignFailed'))
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
        ? t('assetStudio.workbench.collect.fallbackSaved')
        : t('assetStudio.workbench.collect.saved')
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
            localSaved ? t('assetStudio.workbench.collect.localSavedApiFailed') : t('assetStudio.workbench.collect.saveLocalFailed'),
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
    const resolvedDuration = resolveDurationSelection(videoDuration, videoDurationRange, videoDurationOptions)
    if (resolvedDuration !== videoDuration) {
      setVideoDuration(resolvedDuration)
    }
  }, [videoDuration, videoDurationRange, videoDurationOptions])

  useEffect(() => {
    const allowedValues = new Set(videoSizeOptions.map((option) => option.value))
    if (!allowedValues.has(videoSize)) {
      setVideoSize(videoSizeOptions[0]?.value || VIDEO_SIZE_OPTIONS[0].value)
    }
  }, [videoSize, videoSizeOptions])

  useEffect(() => {
    const resolvedDuration = resolveDurationSelection(motionDuration, motionDurationRange, motionDurationOptions)
    if (resolvedDuration !== motionDuration) {
      setMotionDuration(resolvedDuration)
    }
  }, [motionDuration, motionDurationRange, motionDurationOptions])

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
      setImageError(t('assetStudio.workbench.error.imagePromptRequired'))
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
      setImageError(await extractApiErrorMessage(error, t('assetStudio.workbench.error.imageGenerateFailed')))
    } finally {
      setImageLoading(false)
    }
  }

  const handleGenerateVideo = async () => {
    if (!videoPrompt.trim()) {
      setVideoError(t('assetStudio.workbench.error.videoPromptRequired'))
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
      setVideoError(await extractApiErrorMessage(error, t('assetStudio.workbench.error.videoGenerateFailed')))
    } finally {
      setVideoLoading(false)
    }
  }

  const handleGenerateMotion = async () => {
    if (!motionPrompt.trim()) {
      setMotionError(t('assetStudio.workbench.error.motionPromptRequired'))
      return
    }
    if (!motionReferenceFile) {
      setMotionError(t('assetStudio.workbench.error.motionReferenceRequired'))
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
      setMotionError(await extractApiErrorMessage(error, t('assetStudio.workbench.error.motionGenerateFailed')))
    } finally {
      setMotionLoading(false)
    }
  }

  const handleGenerateAudio = async () => {
    if (audioGenerationType === 'speech') {
      if (!audioPrompt.trim()) {
        setAudioError(t('assetStudio.workbench.error.voicePromptRequired'))
        return
      }
      if (!audioVoiceId) {
        setAudioError(
          audioModelId === 'cosyvoice-v3.5-plus'
            ? t('assetStudio.workbench.error.voiceIdRequiredCosy')
            : t('assetStudio.workbench.error.voiceIdRequired'),
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
        formData.append('voice_id', audioVoiceId)
        formData.append('instruction', audioInstruction.trim())
        if (showAudioNumericSpeedControl) {
          formData.append('rate', audioRate)
        }
        formData.append('volume', audioVolume)

        const response = await apiClient.generateAssetStudioAudio(formData)
        setAudioResult(response.data as AssetStudioGenerateResponse)
      } catch (error) {
        setAudioError(await extractApiErrorMessage(error, t('assetStudio.workbench.error.voiceGenerateFailed')))
      } finally {
        setAudioLoading(false)
      }
      return
    }
    if (!audioPrompt.trim()) {
      setAudioError(
        audioGenerationType === 'music'
          ? t('assetStudio.workbench.error.musicPromptRequired')
          : audioGenerationType === 'scene-audio'
            ? t('assetStudio.workbench.error.sceneAudioPromptRequired')
            : t('assetStudio.workbench.error.soundEffectPromptRequired'),
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
      setAudioError(await extractApiErrorMessage(error, t('assetStudio.workbench.error.audioGenerateFailed')))
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
        <Typography sx={{ color: 'white', fontWeight: 700 }}>{t(activeEntry.titleKey)}</Typography>
        <Chip
          size="small"
          label={activeEntry.status === 'ready' ? t('assetStudio.workbench.status.apiReady') : t('assetStudio.workbench.status.pendingIntegration')}
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
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.imageModel')}</InputLabel>
                  <Select value={imageModelId} label={t('assetStudio.workbench.label.imageModel')} onChange={(event) => setImageModelId(event.target.value)} sx={{ color: 'white' }}>
                    {imageModelOptions.map((option) =>
                      option.value === '---divider---' ? (
                        <MenuItem key={option.value} value={option.value} disabled sx={{ color: 'rgba(255,255,255,0.3)', fontWeight: 600, textAlign: 'center' }}>
                          {option.label}
                        </MenuItem>
                      ) : (
                        renderModelOptionMenuItem(option as ModelOption, catalogRuntimeEntries[option.value]?.runtime_routing_signal, t)
                      )
                    )}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedImageModel, t)}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25, display: audioGenerationType === 'speech' ? 'none' : 'flex' }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedImageRoutingSignal, t)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedImageRoutingSignal)}
                  />
                  <Chip size="small" label={imageUsesReferenceMode ? t('assetStudio.workbench.chip.referenceEditMode') : t('assetStudio.workbench.chip.purePromptMode')} variant="outlined" sx={{ color: 'white' }} />
                  <Chip
                    size="small"
                    label={imageModelId === 'qwen-image-edit-max' ? t('assetStudio.workbench.chip.qualityFirst') : t('assetStudio.workbench.chip.recommendedMain')}
                    variant="outlined"
                    sx={{ color: 'white' }}
                  />
                </Stack>
                {renderRoutingStatusMeta(selectedImageRoutingSignal, t)}
                {renderRecommendedModelAction(imageModelId, recommendedImageModel, catalogRuntimeEntries, () => {
                  if (recommendedImageModel?.value) {
                    setImageModelId(recommendedImageModel.value)
                  }
                }, t)}
              </Box>

              <UploadCard
                title={t('assetStudio.workbench.upload.imageReferenceTitle')}
                subtitle={t('assetStudio.workbench.upload.imageReferenceSubtitle', { count: imageReferenceLimit })}
                multiple
                accept="image/*"
                fileCount={imageReferenceFiles.length}
                fileLabel={t('assetStudio.workbench.upload.imageReferenceSelected', { count: imageReferenceFiles.length })}
                onChange={(files) => setImageReferenceFiles(files ? Array.from(files).slice(0, imageReferenceLimit) : [])}
                t={t}
              />
              <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                {t('assetStudio.workbench.dataHint.imageReferenceLimit', { count: imageReferenceLimit })}
              </Typography>

              {audioGenerationType === 'speech' ? (
                <Alert severity={audioModelId === 'cosyvoice-v3.5-plus' && sortedAudioVoicePresets.length === 0 ? 'warning' : 'info'} sx={{ borderRadius: 3 }}>
                  {audioModelId === 'cosyvoice-v3.5-plus'
                    ? sortedAudioVoicePresets.length > 0
                      ? t('assetStudio.workbench.alert.cosyVoiceReady')
                      : t('assetStudio.workbench.alert.cosyVoiceNoSystem')
                    : t('assetStudio.workbench.alert.unifiedTts')}
                </Alert>
              ) : null}

              {audioGenerationType === 'speech' ? (
                <TextField
                  multiline
                  minRows={8}
                  label={t('assetStudio.workbench.label.voiceText')}
                  value={audioPrompt}
                  onChange={(event) => setAudioPrompt(event.target.value)}
                  placeholder={t('assetStudio.workbench.placeholder.voiceText')}
                  InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                  sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                />
              ) : null}

              <TextField
                multiline
                minRows={8}
                label={t('assetStudio.workbench.label.imagePrompt')}
                value={imagePrompt}
                onChange={(event) => setImagePrompt(event.target.value)}
                placeholder={t('assetStudio.workbench.placeholder.imagePrompt')}
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ display: audioGenerationType === 'speech' ? 'none' : 'block', '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              <TextField
                multiline
                minRows={2}
                label={t('assetStudio.workbench.label.imageNegativePrompt')}
                value={imageNegativePrompt}
                onChange={(event) => setImageNegativePrompt(event.target.value)}
                placeholder={t('assetStudio.workbench.placeholder.imageNegativePrompt')}
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />
            </Stack>

            <ResultCard
              title={t('assetStudio.workbench.result.imageTitle')}
              result={imageResult}
              loading={imageLoading}
              error={imageError}
              onCollect={() =>
                void collectAssetResult('image', {
                  result: imageResult,
                  assetKind: 'image',
                  prompt: imagePrompt,
                  fallbackTitle: t('assetStudio.workbench.assetTitle.image'),
                  tags: ['asset_studio', 'image'],
                })
              }
              collecting={collectStates.image.loading}
              collectFeedback={collectStates.image.feedback}
              t={t}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.size')}</InputLabel>
                <Select value={imageSize} label={t('assetStudio.workbench.label.size')} onChange={(event) => setImageSize(event.target.value)} sx={{ color: 'white' }}>
                  {imageSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </MenuItem>
                  ))}
              </Select>
            </FormControl>
            <FooterAction loading={imageLoading} label={t('assetStudio.workbench.action.generate')} onClick={handleGenerateImage} t={t} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'video' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.videoModel')}</InputLabel>
                  <Select value={videoModelId} label={t('assetStudio.workbench.label.videoModel')} onChange={(event) => setVideoModelId(event.target.value)} sx={{ color: 'white' }}>
                    {videoModelOptions.map((option) =>
                      option.value === '---divider---' ? (
                        <MenuItem key={option.value} value={option.value} disabled sx={{ color: 'rgba(255,255,255,0.3)', fontWeight: 600, textAlign: 'center' }}>
                          {option.label}
                        </MenuItem>
                      ) : (
                        renderModelOptionMenuItem(option as ModelOption, catalogRuntimeEntries[option.value]?.runtime_routing_signal, t)
                      )
                    )}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedVideoModel, t)}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedVideoRoutingSignal, t)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedVideoRoutingSignal)}
                  />
                  <Chip size="small" label={videoUsesReferenceMode ? t('assetStudio.workbench.chip.firstFrameMode') : t('assetStudio.workbench.chip.pureTextMode')} variant="outlined" sx={{ color: 'white' }} />
                </Stack>
                {renderRoutingStatusMeta(selectedVideoRoutingSignal, t)}
                {renderRecommendedModelAction(videoModelId, recommendedVideoModel, catalogRuntimeEntries, () => {
                  if (recommendedVideoModel?.value) {
                    setVideoModelId(recommendedVideoModel.value)
                  }
                }, t)}
              </Box>

              <UploadCard
                title={t('assetStudio.workbench.upload.videoFirstFrameTitle')}
                subtitle={t('assetStudio.workbench.upload.videoFirstFrameSubtitle')}
                accept="image/*"
                fileCount={videoReferenceFile ? 1 : 0}
                fileLabel={videoReferenceFile ? videoReferenceFile.name : ''}
                onChange={(files) => setVideoReferenceFile(files?.[0] || null)}
                t={t}
              />

              <TextField
                multiline
                minRows={8}
                label={t('assetStudio.workbench.label.videoPrompt')}
                value={videoPrompt}
                onChange={(event) => setVideoPrompt(event.target.value)}
                placeholder={t('assetStudio.workbench.placeholder.videoPrompt')}
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {videoSupportsCameraControl ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.cameraControl')}</InputLabel>
                  <Select value={videoCameraControl} label={t('assetStudio.workbench.label.cameraControl')} onChange={(event) => setVideoCameraControl(event.target.value)} sx={{ color: 'white' }}>
                    {CAMERA_CONTROL_OPTIONS.map((option) => (
                      <MenuItem key={option.value || 'auto'} value={option.value}>
                        {option.labelKey ? t(option.labelKey) : option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedVideoCameraControl, t)}
                  </FormHelperText>
                </FormControl>
              ) : (
                <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                  {t('assetStudio.workbench.dataHint.cameraNotExposedVideo')}
                </Typography>
              )}
            </Stack>

            <ResultCard
              title={t('assetStudio.workbench.result.videoTitle')}
              result={displayedVideoResult}
              loading={videoLoading}
              error={videoError}
              mediaType="video"
              onCollect={() =>
                void collectAssetResult('video', {
                  result: videoResult,
                  assetKind: 'video',
                  prompt: videoPrompt,
                  fallbackTitle: t('assetStudio.workbench.assetTitle.video'),
                  tags: ['asset_studio', 'video'],
                })
              }
              collecting={collectStates.video.loading}
              collectFeedback={collectStates.video.feedback}
              t={t}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.size')}</InputLabel>
                <Select value={videoSize} label={t('assetStudio.workbench.label.size')} onChange={(event) => setVideoSize(event.target.value)} sx={{ color: 'white' }}>
                  {videoSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {videoDurationRange ? (
                <DurationRangeControl
                  label={t('assetStudio.workbench.label.duration')}
                  value={videoDuration}
                  range={videoDurationRange}
                  onChange={setVideoDuration}
                  t={t}
                />
              ) : (
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.duration')}</InputLabel>
                  <Select value={videoDuration} label={t('assetStudio.workbench.label.duration')} onChange={(event) => setVideoDuration(event.target.value)} sx={{ color: 'white' }}>
                    {videoDurationOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t('assetStudio.workbench.durationSeconds', { count: option.value })}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
            </Stack>
            <FooterAction loading={videoLoading} label={t('assetStudio.workbench.action.generate')} onClick={handleGenerateVideo} t={t} />
          </Stack>
        </Box>
      ) : null}

      {activeTabId === 'motion' ? (
        <Box sx={{ p: { xs: 1.5, sm: 2.5 } }}>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', xl: '1.1fr 0.9fr' } }}>
            <Stack spacing={2}>
              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.motionModel')}</InputLabel>
                  <Select value={motionModelId} label={t('assetStudio.workbench.label.motionModel')} onChange={(event) => setMotionModelId(event.target.value)} sx={{ color: 'white' }}>
                    {sortedMotionModelOptions.map((option) => renderModelOptionMenuItem(option, catalogRuntimeEntries[option.value]?.runtime_routing_signal, t))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedMotionModel, t)}
                  </FormHelperText>
                </FormControl>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.25 }}>
                  <Chip
                    size="small"
                    label={getRoutingStatusLabel(selectedMotionRoutingSignal, t)}
                    variant="outlined"
                    sx={getRoutingStatusChipSx(selectedMotionRoutingSignal)}
                  />
                  <Chip size="small" label={motionReferenceFile ? t('assetStudio.workbench.chip.referenceDriven') : t('assetStudio.workbench.chip.pureTextMode')} variant="outlined" sx={{ color: 'white' }} />
                  <Chip size="small" label={t('assetStudio.workbench.chip.motionControl')} variant="outlined" sx={{ color: 'white' }} />
                </Stack>
                {renderRoutingStatusMeta(selectedMotionRoutingSignal, t)}
                {renderRecommendedModelAction(motionModelId, recommendedMotionModel, catalogRuntimeEntries, () => {
                  if (recommendedMotionModel?.value) {
                    setMotionModelId(recommendedMotionModel.value)
                  }
                }, t)}
              </Box>

              <UploadCard
                title={t('assetStudio.workbench.upload.motionRefTitle')}
                subtitle={t('assetStudio.workbench.upload.motionRefSubtitle')}
                accept="image/*"
                fileCount={motionReferenceFile ? 1 : 0}
                fileLabel={motionReferenceFile ? motionReferenceFile.name : ''}
                onChange={(files) => setMotionReferenceFile(files?.[0] || null)}
                t={t}
              />

              <TextField
                multiline
                minRows={8}
                label={t('assetStudio.workbench.label.motionPrompt')}
                value={motionPrompt}
                onChange={(event) => setMotionPrompt(event.target.value)}
                placeholder={t('assetStudio.workbench.placeholder.motionPrompt')}
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {motionSupportsCameraControl ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.cameraControl')}</InputLabel>
                  <Select value={motionCameraControl} label={t('assetStudio.workbench.label.cameraControl')} onChange={(event) => setMotionCameraControl(event.target.value)} sx={{ color: 'white' }}>
                    {CAMERA_CONTROL_OPTIONS.map((option) => (
                      <MenuItem key={option.value || 'auto'} value={option.value}>
                        {option.labelKey ? t(option.labelKey) : option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedMotionCameraControl, t)}
                  </FormHelperText>
                </FormControl>
              ) : (
                <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.82rem', lineHeight: 1.7 }}>
                  {t('assetStudio.workbench.dataHint.cameraNotExposedMotion')}
                </Typography>
              )}
            </Stack>

            <ResultCard
              title={t('assetStudio.workbench.result.motionTitle')}
              result={motionResult}
              loading={motionLoading}
              error={motionError}
              mediaType="video"
              onCollect={() =>
                void collectAssetResult('motion', {
                  result: motionResult,
                  assetKind: 'video',
                  prompt: motionPrompt,
                  fallbackTitle: t('assetStudio.workbench.assetTitle.motion'),
                  tags: ['asset_studio', 'motion'],
                })
              }
              collecting={collectStates.motion.loading}
              collectFeedback={collectStates.motion.feedback}
              t={t}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.size')}</InputLabel>
                <Select value={motionSize} label={t('assetStudio.workbench.label.size')} onChange={(event) => setMotionSize(event.target.value)} sx={{ color: 'white' }}>
                  {motionSizeOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {motionDurationRange ? (
                <DurationRangeControl
                  label={t('assetStudio.workbench.label.duration')}
                  value={motionDuration}
                  range={motionDurationRange}
                  onChange={setMotionDuration}
                  t={t}
                />
              ) : (
                <FormControl size="small" sx={{ minWidth: 120 }}>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.duration')}</InputLabel>
                  <Select value={motionDuration} label={t('assetStudio.workbench.label.duration')} onChange={(event) => setMotionDuration(event.target.value)} sx={{ color: 'white' }}>
                    {motionDurationOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t('assetStudio.workbench.durationSeconds', { count: option.value })}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.motionLevel')}</InputLabel>
                <Select value={motionLevel} label={t('assetStudio.workbench.label.motionLevel')} onChange={(event) => setMotionLevel(event.target.value)} sx={{ color: 'white' }}>
                  <MenuItem value="low">{t('assetStudio.workbench.chip.motionLow')}</MenuItem>
                  <MenuItem value="medium">{t('assetStudio.workbench.chip.motionMedium')}</MenuItem>
                  <MenuItem value="high">{t('assetStudio.workbench.chip.motionHigh')}</MenuItem>
                </Select>
                <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                  {t(MOTION_LEVEL_HELPER_KEYS[motionLevel] || MOTION_LEVEL_HELPER_KEYS.medium)}
                </FormHelperText>
              </FormControl>
            </Stack>
            <FooterAction loading={motionLoading} label={t('assetStudio.workbench.action.generate')} onClick={handleGenerateMotion} t={t} />
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
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.generationType')}</InputLabel>
                  <Select
                    value={audioGenerationType}
                    label={t('assetStudio.workbench.label.generationType')}
                    onChange={(event) => setAudioGenerationType(event.target.value as AudioGenerationType)}
                    sx={{ color: 'white' }}
                  >
                    {AUDIO_GENERATION_TYPE_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedAudioGenerationType, t)}
                  </FormHelperText>
                </FormControl>
              </Box>

              <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
                <FormControl fullWidth size="small">
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.audioModel')}</InputLabel>
                  <Select value={audioModelId} label={t('assetStudio.workbench.label.audioModel')} onChange={(event) => setAudioModelId(event.target.value)} sx={{ color: 'white' }}>
                    {audioModelOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.labelKey ? t(option.labelKey) : option.label}
                      </MenuItem>
                    ))}
                  </Select>
                  <FormHelperText sx={{ color: 'rgba(255,255,255,0.6)', mx: 0, mt: 1 }}>
                    {renderOptionHelperText(selectedAudioModel, t)}
                  </FormHelperText>
                </FormControl>
              </Box>

              </Box>

              {audioGenerationType === 'sound-effect' ? (
                <Alert severity="info" sx={{ borderRadius: 3 }}>
                  {t('assetStudio.workbench.audioAlert.soundEffect')}
                </Alert>
              ) : null}

              {audioGenerationType === 'scene-audio' ? (
                <>
                  <Alert severity="info" sx={{ borderRadius: 3 }}>
                    {t('assetStudio.workbench.audioAlert.sceneAudio')}
                  </Alert>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    {[
                      { labelKey: 'assetStudio.workbench.voice.sceneSampleDialogue', prompt: '安静的室内，窗外持续下雨。男子1用低沉严肃的语气说：“你终于来了。”女子1短暂停顿后平静回答：“有些答案，只能当面告诉你。”远处一声闷雷，低音弦乐缓慢进入。' },
                      { labelKey: 'assetStudio.workbench.voice.sceneSampleChase', prompt: '夜晚地下停车场，急促脚步声由远及近，汽车警报突然响起。男子1喘息着低声说：“别回头，继续跑。”随后传来轮胎摩擦地面的声音，紧张的电子打击乐逐渐增强。' },
                      { labelKey: 'assetStudio.workbench.voice.sceneSampleAmbient', prompt: '清晨海边，海浪和海鸥声持续。旁白温和地讲述：“天亮以后，小镇又恢复了往日的平静。”木吉他与柔和钢琴缓慢铺开，最后只留下海浪声。' },
                    ].map((sample) => (
                      <Button key={sample.labelKey} size="small" variant="outlined" onClick={() => setAudioPrompt(sample.prompt)} sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}>
                        {t(sample.labelKey)}
                      </Button>
                    ))}
                  </Stack>
                </>
              ) : null}

              <TextField
                multiline
                minRows={8}
                label={audioGenerationType === 'music' ? t('assetStudio.workbench.label.musicPrompt') : audioGenerationType === 'scene-audio' ? t('assetStudio.workbench.label.sceneAudioPrompt') : t('assetStudio.workbench.label.soundEffectPrompt')}
                value={audioPrompt}
                onChange={(event) => setAudioPrompt(event.target.value)}
                placeholder={
                  audioGenerationType === 'music'
                    ? t('assetStudio.workbench.placeholder.musicPrompt')
                    : audioGenerationType === 'scene-audio'
                      ? t('assetStudio.workbench.placeholder.sceneAudioPrompt')
                      : t('assetStudio.workbench.placeholder.soundEffectPrompt')
                }
                InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
              />

              {audioGenerationType === 'scene-audio' ? (
                <TextField
                  size="small"
                  fullWidth
                  label={t('assetStudio.workbench.label.speakerId')}
                  value={audioSpeakerIds}
                  onChange={(event) => setAudioSpeakerIds(event.target.value)}
                  placeholder={t('assetStudio.workbench.placeholder.speakerId')}
                  helperText={t('assetStudio.workbench.helperText.speakerId')}
                  InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                  FormHelperTextProps={{ sx: { color: 'rgba(255,255,255,0.56)', mx: 0 } }}
                  sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                />
              ) : null}

              {audioGenerationType === 'speech' ? (
                <Stack spacing={1.5}>
                  <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', md: isCosyVoiceSpeechMode ? 'repeat(2, minmax(0, 1fr))' : '1fr' } }}>
                    <FormControl size="small" fullWidth>
                      <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.voice')}</InputLabel>
                      <Select
                        value={audioVoiceId}
                        label={t('assetStudio.workbench.label.voice')}
                        onChange={(event) => setAudioVoiceId(event.target.value)}
                        sx={{ color: 'white' }}
                        disabled={audioVoiceLoading || sortedAudioVoicePresets.length === 0}
                      >
                        {audioVoiceLoading ? (
                          <MenuItem value="" disabled>
                            {t('assetStudio.workbench.voice.voiceLoading')}
                          </MenuItem>
                        ) : null}
                        {!audioVoiceLoading && sortedAudioVoicePresets.length === 0 ? (
                          <MenuItem value="" disabled>
                            {t('assetStudio.workbench.voice.voiceEmpty')}
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
                          || (audioModelId === 'cosyvoice-v3.5-plus' ? t('assetStudio.workbench.voice.cosyOnlyHint') : t('assetStudio.workbench.voice.pickOneHint'))}
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
                            {t('assetStudio.workbench.voice.clone')}
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
                            {t('assetStudio.workbench.voice.design')}
                          </Button>
                          <Button
                            variant="outlined"
                            sx={WORKBENCH_SUBTLE_ACTION_BUTTON_SX}
                            onClick={() => {
                              void refreshAudioVoiceCatalog('cosyvoice-v3.5-plus').catch(async (error) => {
                                const message = await extractApiErrorMessage(error, t('assetStudio.workbench.voice.refreshFailed'))
                                setAudioVoiceActionFeedback({ type: 'error', text: message })
                              })
                            }}
                            disabled={audioVoiceLoading || audioCloneLoading || audioCloneUploading || audioDesignLoading}
                          >
                            {audioVoiceLoading ? t('assetStudio.workbench.voice.syncInProgress') : t('assetStudio.workbench.voice.refresh')}
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
                    label={t('assetStudio.workbench.label.instruction')}
                    value={audioInstruction}
                    onChange={(event) => setAudioInstruction(event.target.value)}
                    placeholder={t('assetStudio.workbench.placeholder.instruction')}
                    InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                    sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                  />

                  <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                    {showAudioNumericSpeedControl ? (
                      <TextField
                        size="small"
                        fullWidth
                        label={t('assetStudio.workbench.label.speechRate')}
                        value={audioRate}
                        onChange={(event) => setAudioRate(event.target.value)}
                        InputLabelProps={{ sx: { color: 'rgba(255,255,255,0.62)' } }}
                        sx={{ '& .MuiOutlinedInput-root': { color: 'white', backgroundColor: 'rgba(255,255,255,0.03)' } }}
                      />
                    ) : null}
                    <TextField
                      size="small"
                      fullWidth
                      label={t('assetStudio.workbench.label.volume')}
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
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.duration')}</InputLabel>
                  <Select value={audioDuration} label={t('assetStudio.workbench.label.duration')} onChange={(event) => setAudioDuration(event.target.value)} sx={{ color: 'white' }}>
                    {audioDurationOptions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t('assetStudio.workbench.durationSeconds', { count: option.value })}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.mood')}</InputLabel>
                  <Select value={audioMood} label={t('assetStudio.workbench.label.mood')} onChange={(event) => setAudioMood(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_MOOD_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.tempo')}</InputLabel>
                  <Select value={audioTempo} label={t('assetStudio.workbench.label.tempo')} onChange={(event) => setAudioTempo(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_TEMPO_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Stack>

              {audioGenerationType === 'music' ? (
                <FormControl size="small" fullWidth>
                  <InputLabel sx={{ color: 'rgba(255,255,255,0.68)' }}>{t('assetStudio.workbench.label.style')}</InputLabel>
                  <Select value={audioStyle} label={t('assetStudio.workbench.label.style')} onChange={(event) => setAudioStyle(event.target.value)} sx={{ color: 'white' }}>
                    {AUDIO_STYLE_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              ) : null}
            </Stack>

            <ResultCard
              title={t('assetStudio.workbench.result.audioTitle')}
              result={audioResult}
              loading={audioLoading}
              error={audioError}
              mediaType="audio"
              onCollect={() =>
                void collectAssetResult('audio', {
                  result: audioResult,
                  assetKind: 'audio',
                  prompt: audioPrompt,
                  fallbackTitle:
                    audioGenerationType === 'music'
                      ? t('assetStudio.workbench.assetTitle.music')
                      : audioGenerationType === 'sound-effect'
                        ? t('assetStudio.workbench.assetTitle.soundEffect')
                        : audioGenerationType === 'scene-audio'
                          ? t('assetStudio.workbench.assetTitle.sceneAudio')
                          : t('assetStudio.workbench.assetTitle.speech'),
                  tags: ['asset_studio', audioGenerationType === 'music' ? 'music' : audioGenerationType === 'sound-effect' ? 'sound-effect' : audioGenerationType === 'scene-audio' ? 'scene-audio' : 'speech'],
                })
              }
              collecting={collectStates.audio.loading}
              collectFeedback={collectStates.audio.feedback}
              t={t}
            />
          </Box>

          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', md: 'center' }} spacing={1.5} sx={{ mt: 2 }}>
            <Typography sx={{ color: 'rgba(255,255,255,0.58)', fontSize: '0.84rem', lineHeight: 1.7 }}>
              {audioGenerationType === 'music'
                ? t('assetStudio.workbench.dataHint.modeHintMusic')
                : audioGenerationType === 'sound-effect'
                ? t('assetStudio.workbench.dataHint.modeHintSoundEffect')
                : audioGenerationType === 'scene-audio'
                ? t('assetStudio.workbench.dataHint.modeHintSceneAudio')
                : t('assetStudio.workbench.dataHint.modeHintSpeech')}
            </Typography>
            <FooterAction loading={audioLoading} label={t('assetStudio.workbench.action.generateAudio')} onClick={handleGenerateAudio} t={t} />
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
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>{t('assetStudio.workbench.voice.clone')}</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              {t('assetStudio.workbench.voice.cloneAlert')}
            </Alert>
            <TextField
              size="small"
              fullWidth
              label={t('assetStudio.workbench.label.cloneName')}
              value={audioCloneName}
              onChange={(event) => setAudioCloneName(event.target.value)}
              disabled={audioCloneLoading || audioCloneUploading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <TextField
              size="small"
              fullWidth
              label={t('assetStudio.workbench.label.cloneUrl')}
              placeholder={t('assetStudio.workbench.placeholder.cloneUrl')}
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
                {audioCloneUploading ? t('assetStudio.workbench.voice.cloneUploading') : t('assetStudio.workbench.voice.cloneUploadUrl')}
                <input hidden type="file" accept="audio/*" onChange={handleUploadAudioCloneSample} />
              </Button>
              <Button
                variant="outlined"
                onClick={handleOpenAudioCloneRecordDialog}
                disabled={audioCloneLoading || audioCloneUploading || audioCloneRecording}
                sx={{ alignSelf: 'flex-start', borderColor: 'rgba(138,158,255,0.42)', color: '#d7e1ff' }}
              >
                {audioCloneRecording ? t('assetStudio.workbench.voice.recordUploading') : t('assetStudio.workbench.voice.recordUploadUrl')}
              </Button>
              <Typography sx={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.78rem', lineHeight: 1.6 }}>
                {t('assetStudio.workbench.voice.urlBackfillHint')}
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
            {t('assetStudio.workbench.voice.cancel')}
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
            {audioCloneLoading ? t('assetStudio.workbench.voice.submitting') : t('assetStudio.workbench.voice.startClone')}
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
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>{t('assetStudio.workbench.voice.recordTitle')}</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.25}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              {t('assetStudio.workbench.voice.recordAlert')}
            </Alert>
            <Box sx={{ p: 2, borderRadius: 3, border: '1px solid rgba(255,255,255,0.1)', backgroundColor: 'rgba(255,255,255,0.03)' }}>
              <Typography sx={{ color: 'white', fontSize: '0.95rem', lineHeight: 1.8 }}>
                {t('assetStudio.workbench.voice.recordSample')}
              </Typography>
              <Typography sx={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.78rem', mt: 1 }}>
                {t('assetStudio.workbench.voice.recordAnyText')}
              </Typography>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions sx={WORKBENCH_DIALOG_ACTIONS_SX}>
          <Button onClick={handleCloseAudioCloneRecordDialog} disabled={audioCloneRecording || audioCloneUploading} sx={{ color: 'rgba(214,224,255,0.9)' }}>
            {t('assetStudio.workbench.voice.close')}
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
            {audioCloneRecording ? t('assetStudio.workbench.voice.stopAndUpload') : t('assetStudio.workbench.voice.startRecording')}
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
        <DialogTitle sx={WORKBENCH_DIALOG_TITLE_SX}>{t('assetStudio.workbench.voice.design')}</DialogTitle>
        <DialogContent dividers sx={WORKBENCH_DIALOG_CONTENT_SX}>
          <Stack spacing={1.5} sx={{ pt: 0.5 }}>
            <Alert severity="info" sx={WORKBENCH_DIALOG_INFO_ALERT_SX}>
              {t('assetStudio.workbench.voice.designAlert')}
            </Alert>
            <TextField
              size="small"
              fullWidth
              label={t('assetStudio.workbench.label.designName')}
              value={audioDesignName}
              onChange={(event) => setAudioDesignName(event.target.value)}
              disabled={audioDesignLoading}
              sx={WORKBENCH_DIALOG_FIELD_SX}
            />
            <TextField
              size="small"
              fullWidth
              label={t('assetStudio.workbench.label.designPrompt')}
              placeholder={t('assetStudio.workbench.placeholder.designPrompt')}
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
              label={t('assetStudio.workbench.label.designPreviewText')}
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
            {t('assetStudio.workbench.voice.cancel')}
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
            {audioDesignLoading ? t('assetStudio.workbench.voice.submitting') : t('assetStudio.workbench.voice.startDesign')}
          </Button>
        </DialogActions>
      </Dialog>

      {activeTabId === 'vision-review' ? <AssetStudioVisionReviewPanel onUseResult={handleUseReviewedResult} /> : null}

      <Box sx={{ px: { xs: 1.5, sm: 2.5 }, py: 1.2, borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', alignItems: 'center', gap: 1, color: 'rgba(255,255,255,0.42)' }}>
        <BoltOutlinedIcon sx={{ fontSize: 16 }} />
        <Typography sx={{ fontSize: '0.82rem' }}>
          {t('assetStudio.workbench.dataHint.footerNote')}
        </Typography>
      </Box>
    </Box>
  )
}
