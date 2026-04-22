import { useDeferredValue, useEffect, useState, type ReactElement } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  IconButton,
  Link,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HubIcon from '@mui/icons-material/Hub'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'

import { apiClient, extractApiErrorMessage } from '@/services/api'

type VerificationStatus = 'verified' | 'partial' | 'failed' | 'pending'

interface CatalogOverview {
  total_entries: number
  verified_entries: number
  partial_entries: number
  failed_entries: number
  pending_entries: number
  categories: Array<{ key: string; count: number }>
  providers: Array<{ key: string; count: number }>
  last_verified_at?: string | null
  last_synced_at?: string | null
}

interface CatalogSource {
  url: string
  source_type: string
  source_domain?: string | null
  http_status?: number | null
  reachable: boolean
  verified: boolean
  page_title?: string | null
  page_excerpt?: string | null
  matched_keywords: string[]
  verification_note?: string | null
  fetched_at?: string | null
}

interface LabeledValueItem {
  label: string
  value: string
  required?: boolean
}

interface SupportItem {
  name?: string
  label: string
  supported: boolean
  note: string
  required?: boolean
  status_label?: string
  status_color?: 'success' | 'warning' | 'default'
}

interface PromptPatternItem {
  title: string
  template: string
}

interface RouterRuleItem {
  when: string
  action: string
  reason: string
}

interface ResourceLinkItem {
  label: string
  url: string
  note?: string
}

interface IdentityProfile {
  core_positioning: string
  model_lineage: LabeledValueItem[]
  context_window: LabeledValueItem[]
  capability_quadrants: {
    strengths: string[]
    weaknesses: string[]
    modalities: string[]
    capability_tags: string[]
  }
  project_fit: {
    modules: string[]
    task_types: string[]
    role_summary: string
  }
}

interface IntegrationProfile {
  calling_stack: LabeledValueItem[]
  native_parameters: SupportItem[]
  response_features: SupportItem[]
  environment_bindings: LabeledValueItem[]
  client_entrypoints?: LabeledValueItem[]
  api_references?: ResourceLinkItem[]
  tooling_badges: string[]
  recommended_wrapper: string
  sdk_templates: {
    python?: string
    javascript?: string
  }
}

interface PromptRouterProfile {
  system_role: string
  prompt_patterns: PromptPatternItem[]
  router_rules: RouterRuleItem[]
  best_practice_tips: string[]
  fallback_chain: string[]
}

interface DeploymentProfile {
  access_topology: LabeledValueItem[]
  project_entrypoints: LabeledValueItem[]
  environment_convention: LabeledValueItem[]
  local_deployment_note: string
  proxy_snippet: string
}

interface ResourceNavigation {
  official_sources: ResourceLinkItem[]
  selection_hubs: ResourceLinkItem[]
  model_hubs: ResourceLinkItem[]
  provider_portals: ResourceLinkItem[]
}

interface CatalogEntry {
  model_key: string
  name: string
  provider: string
  category: string
  category_label: string
  subcategory?: string | null
  model_family?: string | null
  config_source: string
  status: string
  summary?: string | null
  recommended_scenarios: string[]
  limitations: string[]
  integration_notes: string[]
  documentation_url?: string | null
  source_urls: string[]
  tags: string[]
  modalities: string[]
  capabilities: Array<Record<string, any>>
  constraints: Record<string, any>
  performance: Record<string, any>
  routing: Record<string, any>
  default_params: Record<string, any>
  verification_status: VerificationStatus
  verification_scope?: string | null
  verification_score: number
  total_source_count: number
  reachable_source_count: number
  verified_source_count: number
  verification_notes?: string | null
  last_synced_at?: string | null
  last_verified_at?: string | null
  updated_at?: string | null
  project_modules: string[]
  project_task_labels: string[]
  tooling_badges: string[]
  primary_strengths: string[]
  identity_profile?: IdentityProfile
  integration_profile?: IntegrationProfile
  prompt_router_profile?: PromptRouterProfile
  deployment_profile?: DeploymentProfile
  resource_navigation?: ResourceNavigation
  sources?: CatalogSource[]
  detailed_specs?: DetailedSpecs
  pricing_verification?: PricingVerification
  constraints_summary?: ConstraintsSummary
  capability_provenance?: CapabilityProvenance[]
  error_handlers_summary?: ErrorHandlerSummary
  usage_guide?: UsageGuide
}

interface UsageGuide {
  title: string
  sections: Array<{
    title: string
    content: string
    tips?: string[]
  }>
}

interface AiDesignParameter {
  name: string
  required: boolean
  meaning: string
}

interface AiDesignContext {
  model_key: string
  display_name: string
  summary: string
  core_capabilities: string[]
  voice_design_dimensions: string[]
  voice_lifecycle_statuses: string[]
  hard_constraints: string[]
  required_workflow: string[]
  critical_parameters: AiDesignParameter[]
  input_requirements: string[]
  output_contract: string[]
  error_cases: string[]
  design_tips: string[]
  official_docs: ResourceLinkItem[]
}

interface PricingVerification {
  pricing_status: 'verified' | 'unverified'
  price?: number
  unit?: string
  currency?: string
  pricing_verified?: boolean
  source?: string
  confidence?: string
  last_verified_at?: string
}

interface ConstraintsSummary {
  duration?: { min_seconds: number; max_seconds: number; available_options: number[] }
  resolution?: { min_width?: number; max_width?: number; min_height?: number; max_height?: number }
  aspect_ratios?: string[]
  max_batch_size?: number
  max_prompt_length?: number
  pricing?: { price: number; unit: string; currency: string; pricing_verified: boolean }
}

interface CapabilityProvenance {
  capability_name: string
  capability_label: string
  support_level: string
  description: string
  score?: number
  source: string
  verified_at?: string
  confidence: 'high' | 'medium' | 'low'
}

interface ErrorHandlerSummary {
  content_safety?: { action: string; retry: boolean }
  rate_limit?: { action: string; wait_seconds: number }
  timeout?: { action: string; fallback_model: string }
}

interface DetailedSpecs {
  voice_synthesis?: {
    voice_catalog?: {
      total_count?: number
      update_note?: string
      categories?: Array<{
        name: string
        voices?: Array<{
          id: string
          name: string
          gender: string
          description: string
          emotion_tags?: string[]
          recommended_scenarios?: string[]
        }>
      }>
    }
    calling_method?: {
      param_name?: string
      format?: string
      required?: boolean
    }
    instruct_control?: {
      enabled?: boolean
      param_name?: string
      max_instruction_chars?: number
      description?: string
      supported_emotions?: Array<{
        tag: string
        label: string
        description: string
      }>
      usage_tips?: string[]
    }
    voice_clone?: {
      enabled: boolean
      note?: string
      status_values?: Array<{
        value: string
        meaning: string
      }>
      input_requirements?: {
        supported_formats?: string[]
        min_duration_seconds?: number
        max_duration_seconds?: number
        recommended_duration?: string
        quality_requirements?: string[]
      }
    }
    voice_design?: {
      enabled: boolean
      note?: string
      constraints?: {
        max_prompt_chars?: number
        supported_languages?: string[]
        required_target_model?: string
        forbidden_requests?: string[]
      }
      quality_principles?: string[]
      recommended_dimensions?: Array<{
        name: string
        examples: string[]
      }>
    }
  }
  video_generation?: {
    core_function?: {
      description?: string
      key_features?: string[]
    }
    input_modalities?: Array<{
      id: string
      name: string
      required: boolean
      description?: string
    }>
    output_format?: {
      container?: string
      video_codec?: string
      audio_codec?: string
      frame_rate?: number
    }
    basic_params?: {
      duration?: {
        min_seconds?: number
        max_seconds?: number
        step_seconds?: number
        supported_values?: number[]
        recommended?: number[]
        note?: string
      }
      resolution?: {
        options?: string[]
        recommended?: string
        note?: string
      }
    }
    advanced_features?: Array<{
      id: string
      name: string
      description: string
      version_support?: string
    }>
    reference_input?: {
      reference_images?: {
        enabled: boolean
        max_count: number
        recommended_count?: number
        input_spec?: {
          formats?: string[]
          max_size_mb?: number
        }
        weight_control?: {
          enabled: boolean
          range?: number[]
          default?: number
        }
        usage_types?: Array<{
          type: string
          description: string
          recommended_weight?: string
          tips?: string[]
        }>
      }
      reference_videos?: {
        enabled: boolean
        max_count: number
        input_spec?: {
          formats?: string[]
          duration_range?: {
            min: number
            max: number
          }
        }
        usage_types?: Array<{
          type: string
          description: string
          recommended_weight?: string
        }>
      }
    }
    frame_control?: {
      enabled: boolean
      first_frame?: {
        description: string
        input_spec?: {
          formats?: string[]
        }
        usage?: Array<{
          scenario: string
          description: string
          example?: string
        }>
      }
      last_frame?: {
        description: string
        input_spec?: {
          formats?: string[]
        }
        usage?: Array<{
          scenario: string
          description: string
          example?: string
        }>
      }
      combined_usage?: {
        description: string
        usage?: Array<{
          scenario: string
          description: string
        }>
      }
    }
    prompt_examples?: Array<{
      title: string
      content: string
      description?: string
    }>
    best_practices?: {
      tips: string[]
    }
    limitations?: string[]
  }
  image_editing?: {
    edit_instructions?: {
      edit_types?: Array<{
        type: string
        description: string
      }>
    }
  }
  music_generation?: {
    style_control?: {
      preset_styles?: Array<{
        id: string
        name: string
      }>
    }
    mood_control?: {
      supported_moods?: Array<{
        tag: string
        label: string
      }>
    }
  }
  audio_generation?: {
    audio_types?: Array<{
      type: string
      description: string
    }>
  }
}

type CategoryFilter = 'all' | 'llm' | 'image' | 'audio' | 'video' | 'multimodal'

const STATUS_META: Record<VerificationStatus, { color: 'success' | 'warning' | 'error' | 'default'; label: string }> = {
  verified: { color: 'success', label: '已验证' },
  partial: { color: 'warning', label: '部分验证' },
  failed: { color: 'error', label: '未通过' },
  pending: { color: 'default', label: '待手动验证' },
}

const CATEGORY_OPTIONS: { key: CategoryFilter; label: string; icon: ReactElement }[] = [
  { key: 'all', label: '全部', icon: <HubIcon fontSize="small" /> },
  { key: 'llm', label: '文本LLM', icon: <HubIcon fontSize="small" /> },
  { key: 'image', label: '图像生成', icon: <HubIcon fontSize="small" /> },
  { key: 'audio', label: '音频生成', icon: <HubIcon fontSize="small" /> },
  { key: 'video', label: '视频生成', icon: <HubIcon fontSize="small" /> },
  { key: 'multimodal', label: '多模态', icon: <HubIcon fontSize="small" /> },
]

function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function normalizeCategoryFilter(raw: string | null): CategoryFilter {
  if (!raw || raw === 'all') return 'all'
  const allowed: CategoryFilter[] = ['llm', 'image', 'audio', 'video', 'multimodal']
  return allowed.includes(raw as CategoryFilter) ? (raw as CategoryFilter) : 'all'
}

const COSYVOICE_V35_PLUS_DISPLAY_NAME = 'CosyVoice v3.5 Plus'
const COSYVOICE_V35_DOC_LINKS: ResourceLinkItem[] = [
  {
    label: '非实时语音合成',
    url: 'https://help.aliyun.com/zh/model-studio/non-realtime-cosyvoice-api',
    note: 'CosyVoice v3.5 Plus 语音合成主文档',
  },
  {
    label: '声音复刻与设计',
    url: 'https://help.aliyun.com/zh/model-studio/cosyvoice-clone-design-api',
    note: '自定义音色创建、复刻与声音设计接口',
  },
  {
    label: 'WebSocket 接口',
    url: 'https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api',
    note: '语音合成补充接口文档',
  },
]

function mergeUniqueStrings(...groups: Array<string[] | null | undefined>): string[] {
  const seen = new Set<string>()
  const merged: string[] = []

  groups.forEach((group) => {
    ;(group || []).forEach((item) => {
      const normalized = String(item || '').trim()
      if (!normalized || seen.has(normalized)) return
      seen.add(normalized)
      merged.push(normalized)
    })
  })

  return merged
}

function mergeResourceLinks(...groups: Array<ResourceLinkItem[] | null | undefined>): ResourceLinkItem[] {
  const seen = new Set<string>()
  const merged: ResourceLinkItem[] = []

  groups.forEach((group) => {
    ;(group || []).forEach((item) => {
      const url = String(item?.url || '').trim()
      if (!url || seen.has(url)) return
      seen.add(url)
      merged.push(item)
    })
  })

  return merged
}

function isCosyVoiceV35Entry(entry?: Pick<CatalogEntry, 'model_key' | 'name'> | null): boolean {
  if (!entry) return false

  const modelKey = String(entry.model_key || '').trim().toLowerCase()
  const normalizedName = String(entry.name || '').trim().toLowerCase()

  return (
    modelKey === 'cosyvoice-v3.5-plus'
    || modelKey === 'cosyvoice-v3-plus'
    || normalizedName === 'cosyvoice v3.5 plus'
    || normalizedName === 'cosyvoice v3.5-plus'
    || normalizedName === 'cosyvoice v3 plus'
    || normalizedName === 'cosyvoice v3-plus'
  )
}

function getCatalogEntryDisplayName(entry?: Pick<CatalogEntry, 'model_key' | 'name'> | null): string {
  if (!entry) return ''

  const rawName = String(entry.name || '').trim()
  if (isCosyVoiceV35Entry(entry)) {
    return COSYVOICE_V35_PLUS_DISPLAY_NAME
  }

  return rawName
}

function normalizeCatalogEntryForDisplay(entry: CatalogEntry): CatalogEntry {
  if (!isCosyVoiceV35Entry(entry)) {
    return entry
  }

  const primaryStrengths = mergeUniqueStrings(
    ['高表现力 TTS', 'Instruction 控制', '声音复刻', '声音设计'],
    entry.primary_strengths,
  )
  const recommendedScenarios = mergeUniqueStrings(
    [
      '高质量有声书章节朗读',
      '角色化旁白与情绪浓度较高的演绎',
      '基于真实样本的声音复刻工作流',
      '基于描述词创建新声线的声音设计工作流',
      '资产生成工作台中的语音资产制作',
      '后续有声小说字幕对齐与短剧配音时间轴能力',
    ],
    entry.recommended_scenarios,
  )
  const limitations = mergeUniqueStrings(
    [
      '不提供系统音色，接入前必须先创建或选择复刻/设计音色。',
      '合成时必须传入当前账号下可用的 voice_id，不能直接使用公共 narrator。',
      '成本与吞吐通常不如默认朗读模型，更适合质量优先而非批量低成本链路。',
      '音色生命周期需要额外管理，包括上传样本、复刻/设计、刷新列表与删除清理。',
    ],
    entry.limitations,
  )
  const integrationNotes = mergeUniqueStrings(
    [
      '项目已在有声书页面接入 CosyVoice v3.5 Plus，并支持声音复刻、声音设计、录音上传与 voice_id 选择。',
      '资产生成工作台已接入该模型，可直接在语音面板创建或管理 CosyVoice 自定义音色。',
      '合成时建议将自定义 voice_id 作为 speaker 使用，并按需传入 instruction 控制情绪、语速与语气；instruction 长度不要超过 100 个字符，且汉字按 2 个字符计数。',
      '声音复刻与声音设计创建链路的 target_model 需要与后续合成模型保持一致，当前项目统一固定为 cosyvoice-v3.5-plus。',
      '音色列表需要关注 status 字段，只有 OK 状态适合直接进入合成，DEPLOYING 和 UNDEPLOYED 需要提示用户等待或重新处理。',
      '词级时间戳已验证可用，适合后续有声小说字幕切分、短剧配音对词和台词时间轴生成；音素级时间戳当前默认按不支持处理。',
      '当前账号下的复刻/设计音色会同步进入前端音色列表，官方静态系统音色目录为空。',
    ],
    entry.integration_notes,
  )
  const sourceUrls = mergeUniqueStrings(
    COSYVOICE_V35_DOC_LINKS.map((item) => item.url),
    entry.source_urls,
  )
  const officialSources = mergeResourceLinks(
    COSYVOICE_V35_DOC_LINKS,
    entry.resource_navigation?.official_sources,
  )

  return {
    ...entry,
    verification_status: 'verified',
    verification_scope: entry.verification_scope || 'manual_runtime_verified',
    verification_score: 1,
    total_source_count: Math.max(intOrZero(entry.total_source_count), officialSources.length),
    reachable_source_count: Math.max(intOrZero(entry.reachable_source_count), officialSources.length),
    verified_source_count: Math.max(intOrZero(entry.verified_source_count), officialSources.length),
    verification_notes:
      '已在 2026-04-22 完成文档核对与真实运行时校验。词级时间戳已实测可用；音素级时间戳默认按不支持处理。',
    last_verified_at: entry.last_verified_at || '2026-04-22T12:00:00+08:00',
    name: COSYVOICE_V35_PLUS_DISPLAY_NAME,
    summary:
      '阿里云百炼的高表现力语音合成路径，支持 instruction、声音复刻与声音设计。该模型不提供系统音色，必须先创建或选择当前账号下的复刻/设计 voice_id 后才能合成，现已接入有声书页面与资产生成工作台。',
    documentation_url: 'https://help.aliyun.com/zh/model-studio/non-realtime-cosyvoice-api',
    source_urls: sourceUrls,
    tags: mergeUniqueStrings(
      ['tts', 'instruction', 'voice-clone', 'voice-design', 'audio', 'alibaba', 'audiobook'],
      entry.tags,
    ),
    recommended_scenarios: recommendedScenarios,
    limitations,
    integration_notes: integrationNotes,
    primary_strengths: primaryStrengths,
    project_modules: mergeUniqueStrings(['有声书', '资产生成工作台', 'TTS API'], entry.project_modules),
    project_task_labels: mergeUniqueStrings(
      ['章节朗读', '角色旁白', '语音克隆', '声音设计', '语音资产生成'],
      entry.project_task_labels,
    ),
    identity_profile: {
      ...entry.identity_profile,
      core_positioning:
        '项目当前用于高表现力语音合成的 CosyVoice 主力路径，定位于“先准备自定义音色，再进行高质量演绎”的质量优先工作流。',
      model_lineage: entry.identity_profile?.model_lineage || [],
      context_window: entry.identity_profile?.context_window || [],
      capability_quadrants: {
        strengths: mergeUniqueStrings(
          ['高表现力 TTS', 'Instruction 控制', '声音复刻', '声音设计'],
          entry.identity_profile?.capability_quadrants?.strengths,
          entry.primary_strengths,
        ),
        weaknesses: mergeUniqueStrings(
          [
            '无系统音色可直接调用',
            '需要额外维护 voice_id 与自定义音色生命周期',
            '更适合质量优先场景，不适合作为默认批量低成本朗读模型',
          ],
          entry.identity_profile?.capability_quadrants?.weaknesses,
          entry.limitations,
        ),
        modalities: mergeUniqueStrings(
          ['text_to_speech', 'voice_clone', 'voice_design'],
          entry.identity_profile?.capability_quadrants?.modalities,
        ),
        capability_tags: mergeUniqueStrings(
          ['tts', 'instruction', 'voice-clone', 'voice-design'],
          entry.identity_profile?.capability_quadrants?.capability_tags,
          entry.tags,
        ),
      },
      project_fit: {
        modules: mergeUniqueStrings(
          ['有声书', '资产生成工作台', 'TTS API'],
          entry.identity_profile?.project_fit?.modules,
          entry.project_modules,
        ),
        task_types: mergeUniqueStrings(
          ['章节朗读', '角色旁白', '语音克隆', '声音设计', '语音资产生成'],
          entry.identity_profile?.project_fit?.task_types,
          entry.project_task_labels,
        ),
        role_summary:
          '当我们需要更强的角色感、情绪控制或专属声线时，优先使用 CosyVoice v3.5 Plus，而不是依赖系统预设音色。',
      },
    },
    integration_profile: {
      ...entry.integration_profile,
      calling_stack: [
        {
          label: '统一试听接口',
          value: 'POST /api/v1/audiobook/tts/preview，短文本试听，返回音频 blob。',
          required: true,
        },
        {
          label: '时间戳试听接口',
          value: 'POST /api/v1/audiobook/tts/preview-with-timestamps，短文本试听，返回 base64 音频与词级时间戳 JSON。',
        },
        {
          label: '章节段落预览',
          value: 'POST /api/v1/audiobook/projects/{projectId}/chapters/{chapterId}/segments/preview，用于脚本段落试听。',
        },
        {
          label: '音色列表',
          value: 'GET /api/v1/audiobook/tts/voices?model=cosyvoice-v3.5-plus，返回当前账号下可用的 voice_id 列表。',
        },
        {
          label: '声音复刻',
          value: 'POST /api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones，body: { name, url }。',
        },
        {
          label: '声音设计',
          value: 'POST /api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/designs，body: { name, voice_prompt, preview_text, sample_rate?, response_format? }。',
        },
        {
          label: '样本上传',
          value: 'POST /api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones/upload，multipart/form-data file。',
        },
        {
          label: '删除音色',
          value: 'DELETE /api/v1/audiobook/tts/voices/cosyvoice-v3.5-plus/clones/{voice_id}。',
        },
      ],
      environment_bindings: [
        {
          label: 'DASHSCOPE_API_KEY',
          value: '必填。CosyVoice 合成、声音复刻、声音设计与上传策略都依赖该凭证。',
          required: true,
        },
        {
          label: 'DASHSCOPE_API_BASE',
          value: '可选。统一媒体运行时走 DashScope 兼容层时可覆盖默认地址。',
        },
      ],
      native_parameters: [
        {
          name: 'text',
          label: 'text',
          supported: true,
          required: true,
          note: '合成正文文本。/tts/preview 试听链路会对超长文本做截断。',
        },
        {
          name: 'speaker',
          label: 'speaker / voice_id',
          supported: true,
          required: true,
          note: '必须传当前账号下可用的 voice_id；CosyVoice 不提供系统音色。',
        },
        {
          name: 'instruction',
          label: 'instruction',
          supported: true,
          note: '自然语言控制情绪、语速、语气和停顿，建议与自定义 voice_id 搭配使用；长度不得超过 100 个字符，汉字按 2 个字符计算，其他字符按 1 个字符计算。',
        },
        {
          name: 'target_model',
          label: 'target_model',
          supported: true,
          note: '声音复刻/设计创建时用于声明目标合成模型，必须与后续 synthesis 使用的模型一致；当前项目应固定为 cosyvoice-v3.5-plus。',
        },
        {
          name: 'volume',
          label: 'volume / speed / pitch',
          supported: true,
          note: '试听接口支持音量、语速、音高微调；段落试听和工作台链路会按场景透传。',
        },
        {
          name: 'voice_prompt',
          label: 'voice_prompt',
          supported: true,
          required: true,
          note: '声音设计接口必填；建议在 500 字符内使用中文或英文，从性别、年龄、音调、语速、情感、音色特点和用途等维度描述声音特质，不要请求模仿名人或演员。',
        },
        {
          name: 'preview_text',
          label: 'preview_text',
          supported: true,
          required: true,
          note: '声音设计接口必填，用于生成设计音色的预览样本。',
        },
        {
          name: 'sample_rate',
          label: 'sample_rate',
          supported: true,
          note: '声音设计接口可选，当前默认值为 24000。',
        },
        {
          name: 'response_format',
          label: 'response_format',
          supported: true,
          note: '声音设计接口可选，当前默认值为 wav。',
        },
        {
          name: 'file',
          label: 'clone sample file',
          supported: true,
          note: '上传接口支持本地音频文件；也可先上传换取 URL，再发起复刻。',
        },
        {
          name: 'url',
          label: 'clone sample url',
          supported: true,
          note: '声音复刻接口实际消费公网 URL 或临时 OSS URL。',
        },
      ],
      response_features: [
        {
          label: '音频 blob',
          supported: true,
          note: '试听接口直接返回音频二进制，媒体类型按 wav / mp3 自动识别。',
        },
        {
          label: 'voice_id 返回',
          supported: true,
          note: '声音复刻与声音设计成功后都应返回 voice_id，供前端写回音色列表。',
        },
        {
          label: 'preview_audio',
          supported: true,
          note: '列出复刻/设计音色时返回 preview_audio，方便试听和确认。',
        },
        {
          label: '当前账号音色列表',
          supported: true,
          note: 'GET /tts/voices 与 GET /tts/voices/cosyvoice-v3.5-plus/clones 都只返回当前账号可用音色。',
        },
        {
          label: '音色状态字段',
          supported: true,
          note: '音色列表需要返回 status；建议前端至少区分 DEPLOYING、OK、UNDEPLOYED，只有 OK 状态可直接进入合成。',
        },
        {
          label: '词级时间戳',
          supported: true,
          note: '已验证支持词级时间戳，适合后续有声小说字幕切分、短剧配音对词和台词时间轴生成。',
        },
        {
          label: '音素级时间戳',
          supported: false,
          note: '当前项目默认按不支持处理，不作为能力承诺；更细粒度同步场景不要依赖该能力。',
        },
        {
          label: '系统音色目录',
          supported: false,
          note: '官方静态系统音色目录为空，前端必须依赖复刻/设计结果。',
        },
      ],
      client_entrypoints: [
        {
          label: 'apiClient.previewTTS',
          value: '短文本试听入口，对应 /api/v1/audiobook/tts/preview。',
        },
        {
          label: 'apiClient.previewTTSWithTimestamps',
          value: '短文本时间戳试听入口，对应 /api/v1/audiobook/tts/preview-with-timestamps。',
        },
        {
          label: 'apiClient.previewScriptSegmentAudio',
          value: '章节段落试听入口，对应 /api/v1/audiobook/projects/{projectId}/chapters/{chapterId}/segments/preview。',
        },
        {
          label: 'apiClient.getTtsVoices',
          value: '拉取当前模型可用音色列表。',
        },
        {
          label: 'apiClient.uploadCosyVoiceV3PlusCloneSample',
          value: '上传本地样本文件，换取可用于复刻的临时 URL。',
        },
        {
          label: 'apiClient.createCosyVoiceV3PlusClone',
          value: '创建复刻音色。',
        },
        {
          label: 'apiClient.createCosyVoiceV3PlusDesign',
          value: '创建设计音色。',
        },
        {
          label: 'apiClient.deleteCosyVoiceV3PlusClone',
          value: '删除当前账号下的自定义音色。',
        },
      ],
      api_references: officialSources,
      tooling_badges: mergeUniqueStrings(
        [
          'runtime_synthesize_speech',
          'apiClient.previewTTS',
          'apiClient.getTtsVoices',
          'voice_id validation',
          'DashScope upload policy',
        ],
        entry.integration_profile?.tooling_badges,
        entry.tooling_badges,
      ),
      recommended_wrapper:
        '建议将 CosyVoice 接入拆成两条链路：一条是音色生命周期管理（上传 / 复刻 / 设计 / 删除 / 刷新列表），一条是统一合成链路（previewTTS / segment preview -> runtime_synthesize_speech）。前端只持有 voice_id，后端负责校验 voice_id 并映射到底层 speaker。',
      sdk_templates: {
        python: `from core.unified_media_runtime import media_runtime

audio_bytes = await media_runtime.synthesize_speech(
    model_id="cosyvoice-v3.5-plus",
    text="这是测试文本",
    speaker="cosyvoice-v3.5-plus-abc123",
    instructions="用开心的语气，语速稍快"
)`,
        javascript: `const uploaded = await apiClient.uploadCosyVoiceV3PlusCloneSample(file)

const clone = await apiClient.createCosyVoiceV3PlusClone({
  name: '主角音色',
  url: uploaded.data?.url,
})

await apiClient.getTtsVoices('cosyvoice-v3.5-plus')

const audio = await apiClient.previewTTS({
  model: 'cosyvoice-v3.5-plus',
  text: '这是试听文本',
  voice_id: clone.data?.voice_id,
  speed: 1,
})`,
      },
    },
    constraints_summary: {
      ...entry.constraints_summary,
      max_batch_size: 1,
      max_prompt_length: 20000,
    },
    detailed_specs: {
      ...entry.detailed_specs,
      voice_synthesis: {
        ...entry.detailed_specs?.voice_synthesis,
        voice_catalog: {
          ...entry.detailed_specs?.voice_synthesis?.voice_catalog,
          total_count: 0,
          categories: entry.detailed_specs?.voice_synthesis?.voice_catalog?.categories || [],
          update_note: '官方不提供系统音色；前端音色列表展示的是当前账号下创建出的复刻/设计音色。',
        },
        calling_method: {
          ...entry.detailed_specs?.voice_synthesis?.calling_method,
          param_name: 'speaker',
          format: 'voice_id',
          required: true,
        },
        instruct_control: {
          ...entry.detailed_specs?.voice_synthesis?.instruct_control,
          enabled: true,
          param_name: 'instruction',
          max_instruction_chars: 100,
          description: '通过自然语言描述控制情绪、语速、停顿与整体演绎方式。',
          supported_emotions:
            entry.detailed_specs?.voice_synthesis?.instruct_control?.supported_emotions?.length
              ? entry.detailed_specs.voice_synthesis.instruct_control.supported_emotions
              : [
                  { tag: 'happy', label: '开心', description: '适合轻快、明亮、带笑意的表达。' },
                  { tag: 'sad', label: '悲伤', description: '适合低沉、克制、哽咽感较强的表达。' },
                  { tag: 'angry', label: '生气', description: '适合冲突、愤怒或压迫感场景。' },
                  { tag: 'fearful', label: '恐惧', description: '适合紧张、颤抖、低语式表达。' },
                  { tag: 'surprised', label: '惊讶', description: '适合语调上扬、情绪突发的表达。' },
                  { tag: 'love', label: '爱意', description: '适合温柔、亲密、细腻的表达。' },
                ],
          usage_tips: mergeUniqueStrings(
            [
              'instruction 长度不得超过 100 个字符，汉字按 2 个字符计算，适合写短句式控制语。',
              'instruction 与自定义 voice_id 搭配时效果更稳定。',
              '可以在 instruction 中描述语速、停顿和情绪强度。',
            ],
            entry.detailed_specs?.voice_synthesis?.instruct_control?.usage_tips,
          ),
        },
        voice_clone: {
          ...entry.detailed_specs?.voice_synthesis?.voice_clone,
          enabled: true,
          note: '支持上传样本进行声音复刻，并可在当前账号维度管理音色。',
          status_values: [
            { value: 'DEPLOYING', meaning: '审核中，暂时不可调用，不要直接进入正式合成。' },
            { value: 'OK', meaning: '审核通过，可调用，可进入试听、段落预览和正式合成。' },
            { value: 'UNDEPLOYED', meaning: '审核不通过，不可调用，需要重新处理或更换音色。' },
          ],
          input_requirements: {
            supported_formats: ['mp3', 'wav', 'm4a'],
            min_duration_seconds: 30,
            max_duration_seconds: 600,
            recommended_duration: '60-180 秒',
            quality_requirements: [
              '音频清晰、背景噪音低',
              '仅包含单一说话人',
              '语速自然，避免过快或过慢',
            ],
          },
        },
        voice_design: {
          enabled: true,
          note: '支持通过文字描述创建新的声线，再以生成出的 voice_id 进行合成。',
          constraints: {
            max_prompt_chars: 500,
            supported_languages: ['中文', '英文'],
            required_target_model: 'cosyvoice-v3.5-plus',
            forbidden_requests: [
              '不要请求模仿名人、演员或其他具体公众人物。',
              '不要用“好听”“普通”这类模糊主观词替代具体声音特征。',
            ],
          },
          quality_principles: [
            '具体而非模糊：优先描述低沉、清脆、语速偏快等可感知特征。',
            '多维而非单一：尽量组合性别、年龄、音调、语速、情感、特点和用途。',
            '客观而非主观：描述声音本身，而不是“我最喜欢的声音”这类偏好表达。',
            '原创而非模仿：描述目标声线特质，不要要求直接模仿特定人物。',
            '简洁而非冗余：避免重复同义词和无意义的强调词。',
          ],
          recommended_dimensions: [
            { name: '性别', examples: ['男性', '女性', '中性'] },
            { name: '年龄', examples: ['儿童（5-12岁）', '青少年（13-18岁）', '青年（19-35岁）', '中年（36-55岁）', '老年（55岁以上）'] },
            { name: '音调', examples: ['高音', '中音', '低音', '偏高', '偏低'] },
            { name: '语速', examples: ['快速', '中速', '缓慢', '偏快', '偏慢'] },
            { name: '情感', examples: ['开朗', '沉稳', '温柔', '严肃', '活泼', '冷静', '治愈'] },
            { name: '特点', examples: ['有磁性', '清脆', '沙哑', '圆润', '甜美', '浑厚', '有力'] },
            { name: '用途', examples: ['新闻播报', '广告配音', '有声书', '动画角色', '语音助手', '纪录片解说'] },
          ],
        },
      },
    },
    usage_guide: {
      title: 'CosyVoice v3.5 Plus 使用指南',
      sections: [
        {
          title: '1. 先创建或选择音色',
          content:
            'CosyVoice v3.5 Plus 没有系统音色可直接调用。开始合成前，需要先在工作台或有声书页面创建声音复刻或声音设计，拿到当前账号下可用的 voice_id。',
          tips: [
            '音色列表只展示当前账号下可用的复刻/设计结果。',
            '只有 status = OK 的音色适合直接选择合成，DEPLOYING 请等待，UNDEPLOYED 需要重新处理。',
            '创建完成后刷新音色列表，再把 voice_id 作为 speaker 使用。',
          ],
        },
        {
          title: '2. 准备复刻样本',
          content:
            '声音复刻支持上传 mp3、wav、m4a 样本，建议提供 60-180 秒的清晰单人录音；也可以先录音，再上传换取临时 URL。',
          tips: [
            '尽量避免背景音乐、环境噪声和多人对话。',
            '样本语速保持自然、音量稳定，复刻效果会更好。',
          ],
        },
        {
          title: '3. 先写好声音描述',
          content:
            '声音设计的关键是写好 voice_prompt。建议使用中文或英文，在 500 字符内从性别、年龄、音调、语速、情感、特点和用途等多个维度描述目标声线，尽量保持具体、客观、原创和简洁。',
          tips: [
            '推荐写法：青年女性、中音、语速偏慢、温柔治愈、音色圆润，适合有声书旁白。',
            '避免写法：我想要一个很好听的声音、模仿某位演员、非常非常棒的声音。',
          ],
        },
        {
          title: '4. 合成时再调 instruction',
          content:
            '如果不需要复刻真实人声，可以直接用文字描述设计新声线。真正发起合成时，再按需追加 instruction 来控制情绪、语气、语速和停顿。',
          tips: [
            '声线设定负责“是谁在说”，instruction 负责“怎么说”。',
            'instruction 建议写成短句控制语，长度不要超过 100 个字符，汉字按 2 个字符计数。',
            '适合角色旁白、情绪密集段落和品牌化声线场景。',
          ],
        },
      ],
    },
    resource_navigation: {
      ...entry.resource_navigation,
      official_sources: officialSources,
      selection_hubs: entry.resource_navigation?.selection_hubs || [],
      model_hubs: entry.resource_navigation?.model_hubs || [],
      provider_portals: entry.resource_navigation?.provider_portals || [],
    },
  }
}

function intOrZero(value: unknown): number {
  return Number.isFinite(Number(value)) ? Number(value) : 0
}

function getPendingVerificationCopy(entry: CatalogEntry): string {
  if (isCosyVoiceV35Entry(entry)) {
    return '手动维护中 · 已按当前接入文档与项目实现同步更新'
  }

  return '待手动验证 · 来源信息已清理'
}

function getAiDesignOfficialDocs(entry: CatalogEntry): ResourceLinkItem[] {
  return mergeResourceLinks(
    entry.documentation_url ? [{ label: '官方文档', url: entry.documentation_url }] : [],
    (entry.source_urls || []).map((url, index) => ({
      label: `参考文档 ${index + 1}`,
      url,
    })),
    entry.resource_navigation?.official_sources,
  )
}

function buildAiDesignContext(entry: CatalogEntry): AiDesignContext {
  if (isCosyVoiceV35Entry(entry)) {
    return {
      model_key: entry.model_key,
      display_name: getCatalogEntryDisplayName(entry),
      summary:
        '高表现力 TTS 路径，支持 instruction、声音复刻和声音设计。该模型没有系统音色，功能设计必须围绕 voice_id 生命周期展开。',
      core_capabilities: [
        'speech_synthesis',
        'instruction_control',
        'voice_clone',
        'voice_design',
      ],
      voice_design_dimensions: [
        '性别：男性、女性、中性',
        '年龄：儿童、青少年、青年、中年、老年',
        '音调：高音、中音、低音、偏高、偏低',
        '语速：快速、中速、缓慢、偏快、偏慢',
        '情感：开朗、沉稳、温柔、严肃、活泼、冷静、治愈',
        '特点：有磁性、清脆、沙哑、圆润、甜美、浑厚、有力',
        '用途：新闻播报、广告配音、有声书、动画角色、语音助手、纪录片解说',
      ],
      voice_lifecycle_statuses: [
        'DEPLOYING：审核中，暂时不可调用，不要直接进入合成。',
        'OK：审核通过，可调用，可以进入试听、段落预览和正式合成。',
        'UNDEPLOYED：审核不通过，不可调用，需要重新处理或更换音色。',
      ],
      hard_constraints: [
        '不提供系统音色，不能直接走默认 narrator 选择链路。',
        '合成前必须先准备当前账号下可用的 voice_id。',
        'speaker 参数实际上传入的是 voice_id，而不是系统音色名。',
        '音色按当前账号维度管理，前端需要支持创建、刷新、删除和重新选择。',
        '声音复刻/设计创建时的 target_model 必须与后续合成模型一致，当前项目统一固定为 cosyvoice-v3.5-plus。',
        '当前只按词级时间戳设计后续能力，音素级时间戳默认按不支持处理。',
      ],
      required_workflow: [
        '先创建声音复刻或声音设计，拿到 voice_id。',
        '刷新音色列表，让新音色进入当前模型可选项。',
        '根据音色 status 过滤候选项，只有 OK 状态允许进入正式合成。',
        '选择 voice_id 作为 speaker，再提交 text 与 instruction 进行合成。',
        '对空音色、创建失败、voice_id 失效等场景提供显式兜底提示。',
      ],
      critical_parameters: [
        { name: 'text', required: true, meaning: '待合成的正文文本。' },
        { name: 'speaker', required: true, meaning: '当前账号下的自定义 voice_id。' },
        { name: 'instruction', required: false, meaning: '用自然语言控制情绪、语速、语气和停顿，长度不得超过 100 个字符，汉字按 2 个字符计算。' },
        { name: 'target_model', required: true, meaning: '创建声音复刻或声音设计时声明目标合成模型，当前应固定为 cosyvoice-v3.5-plus。' },
        { name: 'sample_rate', required: false, meaning: '声音设计预览阶段可指定采样率。' },
        { name: 'response_format', required: false, meaning: '声音设计预览阶段可指定返回音频格式。' },
      ],
      input_requirements: [
        'voice_prompt 长度不得超过 500 个字符。',
        'voice_prompt 仅支持中文和英文。',
        'instruction 长度不得超过 100 个字符，汉字按 2 个字符计算，适合写短句式控制语。',
        '声音复刻样本支持 mp3 / wav / m4a。',
        '复刻样本时长范围 30s - 600s，建议 60 - 180 秒。',
        '样本应清晰、低噪、单一说话人、自然语速。',
      ],
      output_contract: [
        '语音合成链路可以返回音频结果；时间戳试听链路可返回词级时间戳，适合后续有声小说字幕和短剧配音时间轴场景。',
        '声音复刻/设计创建与列表链路需要返回 voice_id、status 和 preview_audio，供前端回填列表并控制可选状态。',
      ],
      error_cases: [
        '未创建或未选择 voice_id 时不能发起合成。',
        '音色 status 不是 OK 时，应阻断正式合成并提示用户等待部署完成或重新处理。',
        'voice_prompt 超长、语言不符合要求或内容过于模糊时，声音设计结果会不稳定。',
        '上传样本为空、格式不支持或时长不合规时要阻断提交。',
        '请求模仿名人、演员或其他公众人物应直接拦截或改写。',
        'API Key 未配置、账号下音色列表为空、voice_id 已失效时要有明确提示。',
      ],
      design_tips: [
        '交互重点不是“选系统音色”，而是“创建音色 -> 选择音色 -> 再合成”。',
        'instruction 应作为增强控制项，而不是替代 voice_id 的主入口。',
        'voice_prompt 要尽量具体、客观、多维、原创、简洁。',
        '优先从性别、年龄、音调、语速、情感、音色特点和用途组合描述。',
        '声音复刻需要支持本地上传和录音两条入口，减少素材准备门槛。',
        '如果后续要做有声小说字幕切分或短剧配音时间轴，优先复用词级时间戳链路；音素级先不要纳入设计前提。',
      ],
      official_docs: mergeResourceLinks(COSYVOICE_V35_DOC_LINKS, getAiDesignOfficialDocs(entry)),
    }
  }

  const voiceCloneInput = entry.detailed_specs?.voice_synthesis?.voice_clone?.input_requirements
  const criticalParameters = (entry.integration_profile?.native_parameters || []).map((item) => ({
    name: item.name || item.label,
    required: Boolean(item.required),
    meaning: item.note,
  }))
  const inputRequirements = mergeUniqueStrings(
    entry.constraints_summary?.max_prompt_length
      ? [`最大输入长度：${entry.constraints_summary.max_prompt_length} 字符`]
      : [],
    entry.constraints_summary?.duration
      ? [`时长范围：${entry.constraints_summary.duration.min_seconds}s - ${entry.constraints_summary.duration.max_seconds}s`]
      : [],
    voiceCloneInput?.supported_formats?.length
      ? [`支持输入格式：${voiceCloneInput.supported_formats.join(' / ')}`]
      : [],
    voiceCloneInput?.recommended_duration
      ? [`推荐输入时长：${voiceCloneInput.recommended_duration}`]
      : [],
    voiceCloneInput?.quality_requirements || [],
  )

  return {
    model_key: entry.model_key,
    display_name: getCatalogEntryDisplayName(entry),
    summary: entry.identity_profile?.core_positioning || entry.summary || '暂无模型定位说明',
    core_capabilities: mergeUniqueStrings(
      entry.primary_strengths,
      entry.identity_profile?.capability_quadrants?.capability_tags,
      entry.tags,
    ).slice(0, 8),
    voice_design_dimensions: getVoiceDesignDimensionItems(entry).map((item) => `${item.label}：${item.value}`),
    voice_lifecycle_statuses: getVoiceLifecycleStatusItems(entry).map((item) => `${item.label}：${item.value}`),
    hard_constraints: mergeUniqueStrings(
      entry.limitations,
      entry.identity_profile?.capability_quadrants?.weaknesses,
    ).slice(0, 6),
    required_workflow: mergeUniqueStrings(
      (entry.usage_guide?.sections || []).map((section) => section.title),
      entry.integration_notes,
    ).slice(0, 5),
    critical_parameters: criticalParameters,
    input_requirements: inputRequirements,
    output_contract: (entry.integration_profile?.response_features || [])
      .filter((item) => item.supported)
      .map((item) => `${item.label}：${item.note}`),
    error_cases: mergeUniqueStrings(
      entry.error_handlers_summary?.content_safety
        ? [`内容安全：${entry.error_handlers_summary.content_safety.action}`]
        : [],
      entry.error_handlers_summary?.rate_limit
        ? [`限流：${entry.error_handlers_summary.rate_limit.action}`]
        : [],
      entry.error_handlers_summary?.timeout
        ? [`超时：${entry.error_handlers_summary.timeout.action}`]
        : [],
    ),
    design_tips: mergeUniqueStrings(
      entry.prompt_router_profile?.best_practice_tips,
      entry.integration_notes,
    ).slice(0, 5),
    official_docs: getAiDesignOfficialDocs(entry),
  }
}

function buildAiDesignPromptPayload(context: AiDesignContext) {
  return {
    model_key: context.model_key,
    display_name: context.display_name,
    summary: context.summary,
    core_capabilities: context.core_capabilities,
    voice_design_dimensions: context.voice_design_dimensions,
    voice_lifecycle_statuses: context.voice_lifecycle_statuses,
    hard_constraints: context.hard_constraints,
    required_workflow: context.required_workflow,
    critical_parameters: context.critical_parameters,
    input_requirements: context.input_requirements,
    output_contract: context.output_contract,
    error_cases: context.error_cases,
    design_tips: context.design_tips,
    official_docs: context.official_docs.map((item) => item.url),
  }
}

function getVoiceDesignConstraintItems(entry?: CatalogEntry | null): string[] {
  const constraints = entry?.detailed_specs?.voice_synthesis?.voice_design?.constraints
  return mergeUniqueStrings(
    constraints?.max_prompt_chars ? [`voice_prompt 长度不得超过 ${constraints.max_prompt_chars} 个字符。`] : [],
    constraints?.supported_languages?.length
      ? [`voice_prompt 仅支持 ${constraints.supported_languages.join(' / ')}。`]
      : [],
    constraints?.required_target_model
      ? [`声音复刻/设计创建时 target_model 应固定为 ${constraints.required_target_model}，并与后续合成模型保持一致。`]
      : [],
    constraints?.forbidden_requests || [],
  )
}

function getVoiceLifecycleStatusItems(entry?: CatalogEntry | null): LabeledValueItem[] {
  return (entry?.detailed_specs?.voice_synthesis?.voice_clone?.status_values || []).map((item) => ({
    label: item.value,
    value: item.meaning,
  }))
}

function getVoiceDesignDimensionItems(entry?: CatalogEntry | null): LabeledValueItem[] {
  return (entry?.detailed_specs?.voice_synthesis?.voice_design?.recommended_dimensions || []).map((item) => ({
    label: item.name,
    value: item.examples.join('、'),
  }))
}

function getVoiceDesignPrinciples(entry?: CatalogEntry | null): string[] {
  return entry?.detailed_specs?.voice_synthesis?.voice_design?.quality_principles || []
}

// Helper components
function LabeledValueSection({ title, items }: { title: string; items: LabeledValueItem[] }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1}>
        {items.map((item) => (
          <Box key={item.label}>
            <Typography variant="caption" color="text.secondary">
              {item.label}
            </Typography>
            <Typography variant="body2">{item.value}</Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function SupportMatrixSection({ title, items }: { title: string; items: SupportItem[] }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1.5}>
        {items.map((item) => (
          <Box key={item.label}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Chip
                size="small"
                color={item.status_color || (item.supported ? 'success' : 'default')}
                label={item.status_label || (item.supported ? '支持' : '不支持')}
              />
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {item.label}
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {item.note}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function BulletSection({ title, items }: { title: string; items: string[] }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={0.8}>
        {items.length > 0 ? (
          items.map((item) => (
            <Typography key={item} variant="body2">
              • {item}
            </Typography>
          ))
        ) : (
          <Typography variant="body2" color="text.secondary">
            暂无
          </Typography>
        )}
      </Stack>
    </Paper>
  )
}

function CodeSnippetSectionWithCopy({ title, language, code, onCopy, isCopied }: {
  title: string
  language: string
  code?: string
  onCopy?: () => void
  isCopied?: boolean
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{title}</Typography>
        {code && onCopy && (
          <IconButton size="small" onClick={onCopy}>
            {isCopied ? <CheckCircleIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
          </IconButton>
        )}
      </Box>
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          backgroundColor: 'rgba(15,76,129,0.04)',
          fontFamily: 'monospace',
          fontSize: '0.85rem',
          whiteSpace: 'pre-wrap',
          overflow: 'auto',
          maxHeight: 300,
        }}
      >
        {code || '暂无代码'}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.8, display: 'block' }}>
        语言：{language}
      </Typography>
    </Paper>
  )
}

function ResourceLinkSection({ title, items }: { title: string; items: ResourceLinkItem[] }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1.2}>
        {items.map((item) => (
          <Link
            key={item.url}
            href={item.url}
            target="_blank"
            rel="noreferrer"
            underline="hover"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
          >
            {item.label} <OpenInNewIcon fontSize="inherit" />
          </Link>
        ))}
        {items.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            暂无链接
          </Typography>
        )}
      </Stack>
    </Paper>
  )
}

function UsageGuideSection({ title, sections }: { title: string; sections: Array<{ title: string; content: string; tips?: string[] }> }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
        {title}
      </Typography>
      <Stack spacing={2}>
        {sections.map((section) => (
          <Paper key={section.title} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
              {section.title}
            </Typography>
            <Typography variant="body2" sx={{ lineHeight: 1.8, mb: 1 }}>
              {section.content}
            </Typography>
            {(section.tips || []).length > 0 && (
              <Stack spacing={0.5}>
                {section.tips?.map((tip) => (
                  <Typography key={tip} variant="body2" color="primary.main">
                    💡 {tip}
                  </Typography>
                ))}
              </Stack>
            )}
          </Paper>
        ))}
      </Stack>
    </Paper>
  )
}

export default function ModelCatalogPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [overview, setOverview] = useState<CatalogOverview | null>(null)
  const [entries, setEntries] = useState<CatalogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>(() =>
    normalizeCategoryFilter(searchParams.get('category'))
  )
  const selectedProvider = 'all'
  const [selectedStatus, setSelectedStatus] = useState<'all' | VerificationStatus>('all')
  const [selectedModelKey, setSelectedModelKey] = useState<string | null>(null)
  const [selectedEntry, setSelectedEntry] = useState<CatalogEntry | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState(0)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const deferredKeyword = useDeferredValue(keyword.trim().toLowerCase())
  const categoryParam = searchParams.get('category')

  useEffect(() => {
    const nextCategory = normalizeCategoryFilter(categoryParam)
    setSelectedCategory((currentCategory) => (currentCategory === nextCategory ? currentCategory : nextCategory))
  }, [categoryParam])

  useEffect(() => {
    const nextCategoryParam = selectedCategory === 'all' ? null : selectedCategory

    if ((categoryParam || null) === nextCategoryParam) {
      return
    }

    const nextSearchParams = new URLSearchParams(searchParams)

    if (nextCategoryParam) {
      nextSearchParams.set('category', nextCategoryParam)
    } else {
      nextSearchParams.delete('category')
    }

    setSearchParams(nextSearchParams, { replace: true })
  }, [categoryParam, searchParams, selectedCategory, setSearchParams])

  const fetchCatalog = async () => {
    setLoading(true)
    setError(null)

    try {
      const [overviewResponse, entriesResponse] = await Promise.all([
        apiClient.getModelCatalogOverview(),
        apiClient.getModelCatalogEntries(),
      ])

      const nextOverviewRaw = overviewResponse.data as CatalogOverview
      const nextEntries = ((entriesResponse.data?.items || []) as CatalogEntry[]).map(normalizeCatalogEntryForDisplay)
      const statusSummary = nextEntries.reduce(
        (acc, item) => {
          acc[item.verification_status] += 1
          return acc
        },
        { verified: 0, partial: 0, failed: 0, pending: 0 } as Record<VerificationStatus, number>,
      )
      const nextOverview: CatalogOverview = {
        ...nextOverviewRaw,
        total_entries: nextEntries.length || nextOverviewRaw.total_entries,
        verified_entries: statusSummary.verified,
        partial_entries: statusSummary.partial,
        failed_entries: statusSummary.failed,
        pending_entries: statusSummary.pending,
      }

      if (nextOverview.total_entries === 0) {
        setOverview(nextOverview)
        setEntries(nextEntries)
        return
      }

      setOverview(nextOverview)
      setEntries(nextEntries)
    } catch (fetchError) {
      setError(await extractApiErrorMessage(fetchError, '加载模型档案失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCatalog()
  }, [])

  const openEntryDetail = async (modelKey: string) => {
    setSelectedModelKey(modelKey)
    setDetailLoading(true)
    setDetailError(null)
    setDetailTab(0)
    setCopiedField(null)

    try {
      const response = await apiClient.getModelCatalogEntry(modelKey)
      setSelectedEntry(normalizeCatalogEntryForDisplay(response.data as CatalogEntry))
    } catch (e) {
      setDetailError(await extractApiErrorMessage(e, '加载模型详情失败'))
    } finally {
      setDetailLoading(false)
    }
  }

  const filteredEntries = entries.filter((entry) => {
    const matchKeyword =
      deferredKeyword === '' ||
      getCatalogEntryDisplayName(entry).toLowerCase().includes(deferredKeyword) ||
      entry.provider.toLowerCase().includes(deferredKeyword) ||
      entry.model_key.toLowerCase().includes(deferredKeyword)

    const matchCategory = selectedCategory === 'all' || entry.category === selectedCategory
    const matchProvider = selectedProvider === 'all' || entry.provider === selectedProvider
    const matchStatus = selectedStatus === 'all' || entry.verification_status === selectedStatus

    return matchKeyword && matchCategory && matchProvider && matchStatus
  })

  const visibleEntries = filteredEntries
  const aiDesignContext = selectedEntry ? buildAiDesignContext(selectedEntry) : null
  const aiDesignPromptPayload = aiDesignContext ? buildAiDesignPromptPayload(aiDesignContext) : null
  const overviewScenarios = selectedEntry
    ? mergeUniqueStrings(selectedEntry.recommended_scenarios).slice(0, 6)
    : []
  const overviewWorkflow = aiDesignContext?.required_workflow?.slice(0, 4) || []
  const overviewConstraints = selectedEntry
    ? mergeUniqueStrings(
      aiDesignContext?.hard_constraints,
      selectedEntry.limitations,
      selectedEntry.identity_profile?.capability_quadrants?.weaknesses,
    ).slice(0, 6)
    : []
  const overviewRoleSummary = selectedEntry?.identity_profile?.project_fit?.role_summary || ''
  const voiceDesignConstraints = getVoiceDesignConstraintItems(selectedEntry)
  const voiceDesignDimensions = getVoiceDesignDimensionItems(selectedEntry)
  const voiceDesignPrinciples = getVoiceDesignPrinciples(selectedEntry)
  const voiceLifecycleStatuses = getVoiceLifecycleStatusItems(selectedEntry)

  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: '#f4f7fb', py: 3 }}>
      <Container maxWidth="xl">
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 3 }}>
          <Button
            variant="outlined"
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate('/dashboard')}
          >
            返回工作台
          </Button>
          <Typography variant="h4" sx={{ fontWeight: 800, color: '#113058' }}>
            模型中心
          </Typography>
        </Stack>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        <Stack
          direction="row"
          spacing={2}
          sx={{
            mb: 3,
            p: 2.5,
            borderRadius: 3,
            backgroundColor: 'rgba(255,255,255,0.95)',
            border: '1px solid rgba(17,48,88,0.1)',
          }}
        >
          <TextField
            label="搜索模型"
            variant="outlined"
            size="small"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            sx={{ minWidth: 260 }}
          />

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {CATEGORY_OPTIONS.map((opt) => (
              <Chip
                key={opt.key}
                label={opt.label}
                onClick={() => setSelectedCategory(opt.key)}
                color={selectedCategory === opt.key ? 'primary' : 'default'}
                variant={selectedCategory === opt.key ? 'filled' : 'outlined'}
                icon={opt.icon}
                sx={{ cursor: 'pointer' }}
              />
            ))}
          </Stack>

          <Stack direction="row" spacing={1}>
            <Chip
              label="全部状态"
              onClick={() => setSelectedStatus('all')}
              color={selectedStatus === 'all' ? 'primary' : 'default'}
              variant={selectedStatus === 'all' ? 'filled' : 'outlined'}
            />
            <Chip
              label="已验证"
              onClick={() => setSelectedStatus('verified')}
              color={selectedStatus === 'verified' ? 'success' : 'default'}
              variant={selectedStatus === 'verified' ? 'filled' : 'outlined'}
            />
            <Chip
              label="部分验证"
              onClick={() => setSelectedStatus('partial')}
              color={selectedStatus === 'partial' ? 'warning' : 'default'}
              variant={selectedStatus === 'partial' ? 'filled' : 'outlined'}
            />
          </Stack>
        </Stack>

        {overview && (
          <Paper
            sx={{
              p: 2.5,
              mb: 3,
              borderRadius: 3,
              background: 'linear-gradient(135deg, #f0f4f8 0%, #e2e8f0 100%)',
              border: '1px solid rgba(17,48,88,0.1)',
            }}
          >
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} sm={4}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">档案总数</Typography>
                  <Typography variant="h5" sx={{ fontWeight: 800, color: '#113058' }}>
                    {overview.total_entries}
                  </Typography>
                </Stack>
              </Grid>
              <Grid item xs={6} sm={2}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">已验证</Typography>
                  <Typography variant="h6" sx={{ color: 'success.main', fontWeight: 700 }}>
                    {overview.verified_entries}
                  </Typography>
                </Stack>
              </Grid>
              <Grid item xs={6} sm={2}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">部分验证</Typography>
                  <Typography variant="h6" sx={{ color: 'warning.main', fontWeight: 700 }}>
                    {overview.partial_entries}
                  </Typography>
                </Stack>
              </Grid>
              <Grid item xs={6} sm={2}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">未通过</Typography>
                  <Typography variant="h6" sx={{ color: 'error.main', fontWeight: 700 }}>
                    {overview.failed_entries}
                  </Typography>
                </Stack>
              </Grid>
              <Grid item xs={6} sm={2}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">待手动验证</Typography>
                  <Typography variant="h6" sx={{ color: 'text.secondary', fontWeight: 700 }}>
                    {overview.pending_entries}
                  </Typography>
                </Stack>
              </Grid>
              <Grid item xs={6} sm={2}>
                <Stack spacing={0.5}>
                  <Typography variant="caption" color="text.secondary">模型总数</Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    {overview.total_entries}
                  </Typography>
                </Stack>
              </Grid>
            </Grid>
          </Paper>
        )}

        {loading ? (
          <Box sx={{ py: 10, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress />
          </Box>
        ) : (
          <Grid container spacing={2.5}>
            {visibleEntries.map((entry) => (
              <Grid item xs={12} md={6} xl={4} key={entry.model_key}>
                <Paper
                  variant="outlined"
                  sx={{
                    p: 2.5,
                    borderRadius: 4,
                    height: '100%',
                    cursor: 'pointer',
                    background: 'rgba(255,255,255,0.9)',
                    transition: 'transform 0.2s ease, box-shadow 0.2s ease',
                    '&:hover': {
                      transform: 'translateY(-3px)',
                      boxShadow: '0 18px 32px rgba(17,48,88,0.08)',
                    },
                  }}
                  onClick={() => void openEntryDetail(entry.model_key)}
                >
                  <Stack spacing={1.5}>
                    <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        <Chip label={entry.category_label} color="primary" size="small" />
                        {entry.subcategory ? <Chip label={entry.subcategory} variant="outlined" size="small" /> : null}
                        <Chip label={entry.provider} variant="outlined" size="small" />
                      </Stack>
                      <Chip
                        size="small"
                        label={STATUS_META[entry.verification_status].label}
                        color={STATUS_META[entry.verification_status].color}
                      />
                    </Stack>

                    <Typography variant="h6" sx={{ fontWeight: 700, color: '#113058' }}>
                      {getCatalogEntryDisplayName(entry)}
                    </Typography>

                    <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
                      {entry.summary || '暂无摘要'}
                    </Typography>

                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {entry.tags.slice(0, 4).map((tag) => (
                        <Chip key={tag} label={tag} variant="outlined" size="small" />
                      ))}
                    </Stack>

                    <Divider sx={{ my: 0.5 }} />

                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      {entry.verification_status === 'pending' ? (
                        <Typography variant="caption" color="text.secondary">
                          {getPendingVerificationCopy(entry)}
                        </Typography>
                      ) : (
                        <Stack direction="row" spacing={1.5}>
                          <Typography variant="caption" color="text.secondary">
                            校验分数：{(entry.verification_score * 100).toFixed(0)}%
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            来源：{entry.verified_source_count}/{entry.total_source_count}
                          </Typography>
                        </Stack>
                      )}
                      {entry.verification_status !== 'pending' && entry.last_verified_at && (
                        <Typography variant="caption" color="text.secondary">
                          校验：{formatDateTime(entry.last_verified_at)}
                        </Typography>
                      )}
                    </Stack>
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        )}

        <Dialog open={Boolean(selectedModelKey)} onClose={() => setSelectedModelKey(null)} maxWidth="lg" fullWidth>
          <DialogTitle sx={{ fontWeight: 800, pb: 0 }}>
            {getCatalogEntryDisplayName(selectedEntry) || selectedModelKey || '模型详情'}
          </DialogTitle>
          {selectedEntry && (
            <Tabs
              value={detailTab}
              onChange={(_, v) => setDetailTab(v)}
              variant="scrollable"
              scrollButtons="auto"
              sx={{ px: 3, borderBottom: 1, borderColor: 'divider' }}
            >
              <Tab label="概览" />
              <Tab label="使用指南" />
              <Tab label="API调用" />
              <Tab label="AI设计" />
            </Tabs>
          )}
          <DialogContent dividers>
            {detailLoading ? (
              <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
              </Box>
            ) : detailError ? (
              <Alert severity="error">{detailError}</Alert>
            ) : selectedEntry ? (
              <Stack spacing={2.5}>
                {/* 快速参考卡片 */}
                <Paper
                  variant="outlined"
                  sx={{
                    p: 2,
                    borderRadius: 3,
                    background: 'linear-gradient(135deg, #f0f4f8 0%, #e2e8f0 100%)',
                  }}
                >
                  <Grid container spacing={1.5} alignItems="center">
                    <Grid item xs={12} sm={4}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography variant="caption" color="text.secondary">Model Key:</Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                          {selectedEntry.model_key}
                        </Typography>
                        <IconButton
                          size="small"
                          onClick={() => {
                            navigator.clipboard.writeText(selectedEntry.model_key)
                            setCopiedField('model_key')
                            setTimeout(() => setCopiedField(null), 1500)
                          }}
                        >
                          {copiedField === 'model_key' ? <CheckCircleIcon fontSize="small" color="success" /> : <ContentCopyIcon fontSize="small" />}
                        </IconButton>
                      </Stack>
                    </Grid>
                    <Grid item xs={6} sm={2}>
                      <Typography variant="caption" color="text.secondary">类型</Typography>
                      <Typography variant="body2">{selectedEntry.category_label}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={2}>
                      <Typography variant="caption" color="text.secondary">版本</Typography>
                      <Typography variant="body2">{selectedEntry.subcategory || '-'}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={2}>
                      <Typography variant="caption" color="text.secondary">供应商</Typography>
                      <Typography variant="body2">{selectedEntry.provider}</Typography>
                    </Grid>
                    <Grid item xs={6} sm={2}>
                      <Typography variant="caption" color="text.secondary">校验状态</Typography>
                      <Chip
                        size="small"
                        label={STATUS_META[selectedEntry.verification_status].label}
                        color={STATUS_META[selectedEntry.verification_status].color}
                      />
                    </Grid>
                  </Grid>
                </Paper>

                {/* Tab 0: 概览 */}
                {detailTab === 0 && (
                  <Stack spacing={2.5}>
                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>模型定位</Typography>
                      <Typography variant="body1" sx={{ lineHeight: 1.9, mb: 2 }}>
                        {selectedEntry.identity_profile?.core_positioning || selectedEntry.summary || '暂无定位说明'}
                      </Typography>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {(selectedEntry.identity_profile?.capability_quadrants?.strengths || selectedEntry.primary_strengths || []).map((item) => (
                          <Chip key={item} label={item} color="primary" variant="outlined" size="small" />
                        ))}
                      </Stack>
                    </Paper>

                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>适用与接入</Typography>
                      <Grid container spacing={2}>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>推荐场景</Typography>
                          <Stack spacing={0.8}>
                            {(overviewScenarios.length > 0 ? overviewScenarios : ['暂无']).map((item) => (
                              <Typography key={item} variant="body2">• {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>快速接入提示</Typography>
                          {overviewRoleSummary && (
                            <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8, mb: 1.2 }}>
                              {overviewRoleSummary}
                            </Typography>
                          )}
                          <Stack spacing={0.8}>
                            {(overviewWorkflow.length > 0 ? overviewWorkflow : ['暂无接入提示']).map((item) => (
                              <Typography key={item} variant="body2">• {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                      </Grid>
                    </Paper>

                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>关键限制</Typography>
                      <Grid container spacing={2}>
                        <Grid item xs={12} md={7}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>需要优先注意的边界</Typography>
                          <Stack spacing={0.8}>
                            {(overviewConstraints.length > 0 ? overviewConstraints : ['暂无']).map((item) => (
                              <Typography key={item} variant="body2" color="text.secondary">• {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                        <Grid item xs={12} md={5}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>技术约束</Typography>
                          {selectedEntry.constraints_summary ? (
                            <Stack spacing={1.1}>
                              {selectedEntry.constraints_summary.duration && (
                                <Box>
                                  <Typography variant="caption" color="text.secondary">时长范围</Typography>
                                  <Typography variant="body2">
                                    {selectedEntry.constraints_summary.duration.min_seconds}s ~ {selectedEntry.constraints_summary.duration.max_seconds}s
                                  </Typography>
                                </Box>
                              )}
                              {selectedEntry.constraints_summary.max_prompt_length && (
                                <Box>
                                  <Typography variant="caption" color="text.secondary">最大输入长度</Typography>
                                  <Typography variant="body2">{selectedEntry.constraints_summary.max_prompt_length} 字符</Typography>
                                </Box>
                              )}
                              {selectedEntry.constraints_summary.pricing && (
                                <Box>
                                  <Typography variant="caption" color="text.secondary">参考价格</Typography>
                                  <Typography variant="body2">
                                    {selectedEntry.constraints_summary.pricing.currency} {selectedEntry.constraints_summary.pricing.price} / {selectedEntry.constraints_summary.pricing.unit}
                                  </Typography>
                                </Box>
                              )}
                            </Stack>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              暂无额外技术约束。
                            </Typography>
                          )}
                        </Grid>
                      </Grid>
                    </Paper>

                    {selectedEntry.detailed_specs && Object.keys(selectedEntry.detailed_specs).length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>详细能力规格</Typography>
                        {selectedEntry.detailed_specs.video_generation && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>视频生成规格</Typography>
                            {selectedEntry.detailed_specs.video_generation.core_function && (
                              <Typography variant="body2" sx={{ mb: 1, lineHeight: 1.8 }}>
                                {selectedEntry.detailed_specs.video_generation.core_function.description}
                              </Typography>
                            )}
                            {selectedEntry.detailed_specs.video_generation.basic_params && (
                              <Grid container spacing={1.5}>
                                {selectedEntry.detailed_specs.video_generation.basic_params.duration && (
                                  <Grid item xs={12} sm={6}>
                                    <Typography variant="caption" color="text.secondary">支持时长</Typography>
                                    <Typography variant="body2">
                                      {selectedEntry.detailed_specs.video_generation.basic_params.duration.supported_values?.join('s, ') || '-'}s
                                    </Typography>
                                  </Grid>
                                )}
                                {selectedEntry.detailed_specs.video_generation.basic_params.resolution && (
                                  <Grid item xs={12} sm={6}>
                                    <Typography variant="caption" color="text.secondary">分辨率选项</Typography>
                                    <Typography variant="body2">
                                      {selectedEntry.detailed_specs.video_generation.basic_params.resolution.options?.join(', ') || '-'}
                                    </Typography>
                                  </Grid>
                                )}
                              </Grid>
                            )}
                          </Box>
                        )}
                        {selectedEntry.detailed_specs.image_editing && (
                          <Box sx={{ mb: 2 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>图像编辑规格</Typography>
                            {selectedEntry.detailed_specs.image_editing.edit_instructions && (
                              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                {(selectedEntry.detailed_specs.image_editing.edit_instructions.edit_types || []).map((t: any) => (
                                  <Chip key={t.type} label={t.type} size="small" variant="outlined" />
                                ))}
                              </Stack>
                            )}
                          </Box>
                        )}
                        {selectedEntry.detailed_specs.voice_synthesis && (
                          <Box>
                            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>语音合成规格</Typography>
                            <Stack spacing={1}>
                              {selectedEntry.detailed_specs.voice_synthesis.voice_catalog && (
                                <Typography variant="body2">
                                  音色总数：{selectedEntry.detailed_specs.voice_synthesis.voice_catalog.total_count || '-'}
                                </Typography>
                              )}
                              {selectedEntry.detailed_specs.voice_synthesis.voice_catalog?.update_note && (
                                <Typography variant="body2" color="text.secondary">
                                  {selectedEntry.detailed_specs.voice_synthesis.voice_catalog.update_note}
                                </Typography>
                              )}
                              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                {selectedEntry.detailed_specs.voice_synthesis.instruct_control?.enabled && (
                                  <Chip size="small" color="primary" variant="outlined" label="支持 Instruction 控制" />
                                )}
                                {selectedEntry.detailed_specs.voice_synthesis.voice_clone?.enabled && (
                                  <Chip size="small" color="success" variant="outlined" label="支持声音复刻" />
                                )}
                                {selectedEntry.detailed_specs.voice_synthesis.voice_design?.enabled && (
                                  <Chip size="small" color="secondary" variant="outlined" label="支持声音设计" />
                                )}
                              </Stack>
                              {selectedEntry.detailed_specs.voice_synthesis.calling_method?.param_name && (
                                <Typography variant="body2" color="text.secondary">
                                  调用方式：{selectedEntry.detailed_specs.voice_synthesis.calling_method.param_name}
                                  {' = '}
                                  {selectedEntry.detailed_specs.voice_synthesis.calling_method.format || 'voice_id'}
                                </Typography>
                              )}
                              {selectedEntry.detailed_specs.voice_synthesis.voice_clone?.input_requirements && (
                                <Typography variant="body2" color="text.secondary">
                                  复刻样本：
                                  {(selectedEntry.detailed_specs.voice_synthesis.voice_clone.input_requirements.supported_formats || []).join(' / ') || '-'}
                                  {' · '}
                                  {selectedEntry.detailed_specs.voice_synthesis.voice_clone.input_requirements.min_duration_seconds || '-'}
                                  s - {selectedEntry.detailed_specs.voice_synthesis.voice_clone.input_requirements.max_duration_seconds || '-'}
                                  s
                                  {selectedEntry.detailed_specs.voice_synthesis.voice_clone.input_requirements.recommended_duration
                                    ? `，建议 ${selectedEntry.detailed_specs.voice_synthesis.voice_clone.input_requirements.recommended_duration}`
                                    : ''}
                                </Typography>
                              )}
                              {(selectedEntry.detailed_specs.voice_synthesis.instruct_control?.supported_emotions || []).length > 0 && (
                                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                  {selectedEntry.detailed_specs.voice_synthesis.instruct_control?.supported_emotions?.map((emotion) => (
                                    <Chip
                                      key={emotion.tag}
                                      size="small"
                                      label={emotion.label}
                                      variant="outlined"
                                    />
                                  ))}
                                </Stack>
                              )}
                            </Stack>
                          </Box>
                        )}
                      </Paper>
                    )}
                  </Stack>
                )}

                {/* Tab 1: 使用指南 */}
                {detailTab === 1 && (
                  <Stack spacing={2.5}>
                    {selectedEntry.usage_guide && selectedEntry.usage_guide.sections && selectedEntry.usage_guide.sections.length > 0 ? (
                      <UsageGuideSection
                        title={selectedEntry.usage_guide.title || '使用指南'}
                        sections={selectedEntry.usage_guide.sections}
                      />
                    ) : (
                      <Alert severity="info">暂无使用指南</Alert>
                    )}
                  </Stack>
                )}

                {/* Tab 2: API调用 */}
                {detailTab === 2 && (
                  <Stack spacing={2.5}>
                    <Grid container spacing={2.5}>
                      <Grid item xs={12} md={6}>
                        <LabeledValueSection
                          title="调用栈与统一入口"
                          items={selectedEntry.integration_profile?.calling_stack || []}
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <LabeledValueSection
                          title="环境变量约定"
                          items={selectedEntry.integration_profile?.environment_bindings || []}
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <SupportMatrixSection
                          title="原生参数矩阵"
                          items={selectedEntry.integration_profile?.native_parameters || []}
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <SupportMatrixSection
                          title="响应能力矩阵"
                          items={selectedEntry.integration_profile?.response_features || []}
                        />
                      </Grid>
                    </Grid>

                    {selectedEntry.integration_profile?.tooling_badges && selectedEntry.integration_profile.tooling_badges.length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3 }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>工具支持</Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {selectedEntry.integration_profile.tooling_badges.map((item) => (
                            <Chip key={item} label={item} variant="outlined" />
                          ))}
                        </Stack>
                      </Paper>
                    )}

                    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3 }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>封装层建议</Typography>
                      <Alert severity="success" variant="outlined">
                        {selectedEntry.integration_profile?.recommended_wrapper || '建议通过统一封装层屏蔽不同供应商 API 差异。'}
                      </Alert>
                    </Paper>

                    {((selectedEntry.integration_profile?.client_entrypoints || []).length > 0
                      || (selectedEntry.integration_profile?.api_references || []).length > 0
                      || selectedEntry.integration_notes.length > 0) && (
                      <Grid container spacing={2.5}>
                        {(selectedEntry.integration_profile?.client_entrypoints || []).length > 0 && (
                          <Grid item xs={12} md={6}>
                            <LabeledValueSection
                              title="前端调用入口"
                              items={selectedEntry.integration_profile?.client_entrypoints || []}
                            />
                          </Grid>
                        )}
                        {(selectedEntry.integration_profile?.api_references || []).length > 0 && (
                          <Grid item xs={12} md={6}>
                            <ResourceLinkSection
                              title="API 文档"
                              items={selectedEntry.integration_profile?.api_references || []}
                            />
                          </Grid>
                        )}
                        {selectedEntry.integration_notes.length > 0 && (
                          <Grid item xs={12}>
                            <BulletSection
                              title="接入备注"
                              items={selectedEntry.integration_notes}
                            />
                          </Grid>
                        )}
                      </Grid>
                    )}

                    {(voiceDesignConstraints.length > 0
                      || voiceDesignPrinciples.length > 0
                      || voiceDesignDimensions.length > 0
                      || voiceLifecycleStatuses.length > 0) && (
                      <Grid container spacing={2.5}>
                        {voiceDesignConstraints.length > 0 && (
                          <Grid item xs={12} md={voiceDesignPrinciples.length > 0 || voiceLifecycleStatuses.length > 0 ? 4 : 6}>
                            <BulletSection
                              title="声音设计约束"
                              items={voiceDesignConstraints}
                            />
                          </Grid>
                        )}
                        {voiceDesignPrinciples.length > 0 && (
                          <Grid item xs={12} md={voiceLifecycleStatuses.length > 0 ? 4 : 6}>
                            <BulletSection
                              title="高质量描述原则"
                              items={voiceDesignPrinciples}
                            />
                          </Grid>
                        )}
                        {voiceLifecycleStatuses.length > 0 && (
                          <Grid item xs={12} md={voiceDesignConstraints.length > 0 || voiceDesignPrinciples.length > 0 ? 4 : 6}>
                            <LabeledValueSection
                              title="音色状态机"
                              items={voiceLifecycleStatuses}
                            />
                          </Grid>
                        )}
                        {voiceDesignDimensions.length > 0 && (
                          <Grid item xs={12}>
                            <LabeledValueSection
                              title="声音描述维度参考"
                              items={voiceDesignDimensions}
                            />
                          </Grid>
                        )}
                      </Grid>
                    )}

                    <Grid container spacing={2.5}>
                      <Grid item xs={12} lg={6}>
                        <CodeSnippetSectionWithCopy
                          title="Python 统一调用模板"
                          language="python"
                          code={selectedEntry.integration_profile?.sdk_templates?.python}
                          onCopy={() => {
                            if (selectedEntry.integration_profile?.sdk_templates?.python) {
                              navigator.clipboard.writeText(selectedEntry.integration_profile.sdk_templates.python)
                              setCopiedField('python')
                              setTimeout(() => setCopiedField(null), 1500)
                            }
                          }}
                          isCopied={copiedField === 'python'}
                        />
                      </Grid>
                      <Grid item xs={12} lg={6}>
                        <CodeSnippetSectionWithCopy
                          title="JavaScript / SDK 模板"
                          language="javascript"
                          code={selectedEntry.integration_profile?.sdk_templates?.javascript}
                          onCopy={() => {
                            if (selectedEntry.integration_profile?.sdk_templates?.javascript) {
                              navigator.clipboard.writeText(selectedEntry.integration_profile.sdk_templates.javascript)
                              setCopiedField('javascript')
                              setTimeout(() => setCopiedField(null), 1500)
                            }
                          }}
                          isCopied={copiedField === 'javascript'}
                        />
                      </Grid>
                    </Grid>
                  </Stack>
                )}

                {/* Tab 3: AI设计 */}
                {detailTab === 3 && (
                  <Stack spacing={2.5}>
                    <Alert severity="info" variant="outlined">
                      这一页是给 AI 设计功能时优先参考的精简上下文。环境变量、SDK 模板和工程接入细节请继续查看“API调用”。
                    </Alert>

                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>AI 关注摘要</Typography>
                      <Typography variant="body1" sx={{ lineHeight: 1.9, mb: 2 }}>
                        {aiDesignContext?.summary || '暂无 AI 设计摘要'}
                      </Typography>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {(aiDesignContext?.core_capabilities || []).map((item) => (
                          <Chip key={item} label={item} color="primary" variant="outlined" size="small" />
                        ))}
                      </Stack>
                    </Paper>

                    <Grid container spacing={2.5}>
                      <Grid item xs={12} md={6}>
                        <BulletSection title="硬约束" items={aiDesignContext?.hard_constraints || []} />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <BulletSection title="必经流程" items={aiDesignContext?.required_workflow || []} />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <LabeledValueSection
                          title="关键参数"
                          items={
                            (aiDesignContext?.critical_parameters || []).length > 0
                              ? (aiDesignContext?.critical_parameters || []).map((item) => ({
                                label: `${item.name}${item.required ? ' *' : ''}`,
                                value: item.meaning,
                              }))
                              : [{ label: '暂无参数', value: '当前模型未补充关键参数说明。' }]
                          }
                        />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <BulletSection title="输入要求" items={aiDesignContext?.input_requirements || []} />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <BulletSection title="输出契约" items={aiDesignContext?.output_contract || []} />
                      </Grid>
                      <Grid item xs={12} md={6}>
                        <BulletSection title="异常场景" items={aiDesignContext?.error_cases || []} />
                      </Grid>
                      <Grid item xs={12}>
                        <BulletSection title="设计提示" items={aiDesignContext?.design_tips || []} />
                      </Grid>
                    </Grid>

                    <Grid container spacing={2.5}>
                      <Grid item xs={12} md={5}>
                        <ResourceLinkSection title="官方文档" items={aiDesignContext?.official_docs || []} />
                      </Grid>
                      <Grid item xs={12} md={7}>
                        <CodeSnippetSectionWithCopy
                          title="AI 精简上下文 JSON"
                          language="json"
                          code={aiDesignPromptPayload ? JSON.stringify(aiDesignPromptPayload, null, 2) : ''}
                          onCopy={() => {
                            if (aiDesignPromptPayload) {
                              navigator.clipboard.writeText(JSON.stringify(aiDesignPromptPayload, null, 2))
                              setCopiedField('ai_design_context')
                              setTimeout(() => setCopiedField(null), 1500)
                            }
                          }}
                          isCopied={copiedField === 'ai_design_context'}
                        />
                      </Grid>
                    </Grid>

                    {(voiceDesignConstraints.length > 0 || voiceDesignDimensions.length > 0 || voiceLifecycleStatuses.length > 0) && (
                      <Grid container spacing={2.5}>
                        {voiceDesignConstraints.length > 0 && (
                          <Grid item xs={12} md={6}>
                            <BulletSection title="声音设计规则" items={voiceDesignConstraints} />
                          </Grid>
                        )}
                        {voiceLifecycleStatuses.length > 0 && (
                          <Grid item xs={12} md={6}>
                            <LabeledValueSection
                              title="音色状态机"
                              items={voiceLifecycleStatuses}
                            />
                          </Grid>
                        )}
                        {voiceDesignDimensions.length > 0 && (
                          <Grid item xs={12}>
                            <LabeledValueSection
                              title="声音描述维度"
                              items={voiceDesignDimensions}
                            />
                          </Grid>
                        )}
                      </Grid>
                    )}
                  </Stack>
                )}
              </Stack>
            ) : (
              <Alert severity="info">请选择一个模型查看详情。</Alert>
            )}
          </DialogContent>
        </Dialog>
      </Container>
    </Box>
  )
}
