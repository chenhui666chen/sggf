import { startTransition, useDeferredValue, useEffect, useState } from 'react'
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
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import SyncIcon from '@mui/icons-material/Sync'
import HubIcon from '@mui/icons-material/Hub'
import VerifiedIcon from '@mui/icons-material/Verified'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'

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

interface CatalogSyncResult {
  processed: number
  verified: number
  partial: number
  failed: number
  skipped: number
  skipped_up_to_date?: number
  cache_hits?: number
  network_requests?: number
  cached_response_count?: number
  updated_at?: string
  model_keys?: string[]
  config_validation?: ConfigValidationResult
}

interface ConfigValidationResult {
  check_status: string
  errors: string[]
  warnings: string[]
  fixes: string[]
  is_consistent: boolean
  error_count: number
  warning_count: number
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
    instruct_control?: {
      supported_emotions?: Array<{
        tag: string
        label: string
        description: string
      }>
    }
    voice_clone?: {
      enabled: boolean
      input_requirements?: Record<string, any>
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
        scenario: string
        description: string
        constraints?: string[]
        example?: string
      }
    }
    camera_control?: {
      enabled: boolean
      preset_movements?: Array<{
        id: string
        name: string
        description: string
        prompt_keyword?: string
      }>
    }
    prompt_examples?: Array<{
      title: string
      description?: string
      content: string
    }>
    best_practices?: {
      tips?: string[]
    }
    limitations?: string[]
    usage_examples?: {
      python?: Array<{
        name: string
        code: string
      }>
    }
  }
  image_editing?: {
    edit_instructions?: {
      edit_types?: Array<{
        type: string
        description: string
        prompt_format?: string
        examples?: string[]
      }>
    }
  }
  music_generation?: {
    style_control?: {
      preset_styles?: Array<{
        id: string
        name: string
        description?: string
        keywords?: string[]
      }>
    }
    mood_control?: {
      supported_moods?: Array<{
        tag: string
        label: string
        description?: string
      }>
    }
  }
  audio_generation?: {
    audio_types?: Array<{
      type: string
      description: string
      prompt_examples?: string[]
    }>
  }
}

const STATUS_META: Record<
  VerificationStatus,
  { label: string; color: 'success' | 'warning' | 'error' | 'default' }
> = {
  verified: { label: '已验证', color: 'success' },
  partial: { label: '部分验证', color: 'warning' },
  failed: { label: '验证失败', color: 'error' },
  pending: { label: '待验证', color: 'default' },
}

const CATEGORY_LABELS: Record<string, string> = {
  all: '全部',
  llm: '文本模型',
  image: '图像模型',
  video: '视频模型',
  audio: '音频模型',
  multimodal: '多模态模型',
  embedding: '向量模型',
}

const CATEGORY_FILTERS = ['all', 'llm', 'image', 'video', 'audio', 'multimodal', 'embedding'] as const

type CategoryFilter = (typeof CATEGORY_FILTERS)[number]

function normalizeCategoryFilter(value: string | null): CategoryFilter {
  if (!value) {
    return 'all'
  }

  return CATEGORY_FILTERS.includes(value as CategoryFilter) ? (value as CategoryFilter) : 'all'
}

const EXTERNAL_HUBS = [
  {
    label: 'Arena AI',
    url: 'https://arena.ai',
    description: '看对话、多模态与综合榜单，适合做主观效果对比。',
  },
  {
    label: 'Artificial Analysis',
    url: 'https://artificialanalysis.ai',
    description: '看速度、成本、智能和延迟，适合做工程选型。',
  },
  {
    label: 'Hugging Face Hub',
    url: 'https://huggingface.co',
    description: '查模型卡、版本、推理入口与开源生态。',
  },
  {
    label: 'ModelScope 魔搭',
    url: 'https://www.modelscope.cn',
    description: '查国产模型、部署与微调资料。',
  },
]

function formatDateTime(value?: string | null): string {
  if (!value) return '暂无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatSyncSummary(result: CatalogSyncResult): string {
  const segments = [
    `本次处理 ${result.processed} 个模型`,
    `跳过 ${result.skipped} 个配置未变化的模型`,
  ]

  if ((result.skipped_up_to_date || 0) > 0) {
    segments.push(`其中 ${result.skipped_up_to_date} 个已校验且未更新`)
  }

  if (typeof result.network_requests === 'number') {
    segments.push(`实际联网请求 ${result.network_requests} 次`)
  }

  if (typeof result.cache_hits === 'number') {
    segments.push(`缓存命中 ${result.cache_hits} 次`)
  }

  if (typeof result.cached_response_count === 'number' && result.cached_response_count > 0) {
    segments.push(`缓存池累计 ${result.cached_response_count} 条响应`)
  }

  return `${segments.join('，')}。`
}

function renderValue(value: unknown): string {
  if (value == null || value === '') return '暂无'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value, null, 2)
}

function DetailKvSection({ title, data }: { title: string; data: Record<string, any> }) {
  const items = Object.entries(data || {})
  if (items.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3, background: 'rgba(255,255,255,0.92)' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1}>
        {items.map(([key, value]) => (
          <Box key={key}>
            <Typography variant="caption" color="text.secondary">
              {key}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontFamily: typeof value === 'object' && value != null ? 'Consolas, monospace' : 'inherit',
              }}
            >
              {renderValue(value)}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  )
}

function LabeledValueSection({ title, items }: { title: string; items: LabeledValueItem[] }) {
  if (!items || items.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1.1}>
        {items.map((item) => (
          <Box key={`${title}-${item.label}`}>
            <Typography variant="caption" color="text.secondary">
              {item.label}
              {item.required === false ? '（可选）' : ''}
            </Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {item.value || '暂无'}
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
      <Stack spacing={1}>
        {items && items.length > 0 ? (
          items.map((item) => (
            <Typography key={`${title}-${item}`} variant="body2">
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

function SupportMatrixSection({ title, items }: { title: string; items: SupportItem[] }) {
  if (!items || items.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1.2}>
        {items.map((item) => (
          <Paper
            key={`${title}-${item.label}`}
            variant="outlined"
            sx={{
              p: 1.4,
              borderRadius: 2,
              background: item.supported ? 'rgba(236,253,245,0.7)' : 'rgba(248,250,252,0.9)',
            }}
          >
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                {item.label}
              </Typography>
              <Chip
                size="small"
                color={item.supported ? 'success' : 'default'}
                label={item.supported ? '支持' : '未启用'}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {item.note}
            </Typography>
          </Paper>
        ))}
      </Stack>
    </Paper>
  )
}

function CodeSnippetSection({ title, code, language }: { title: string; code?: string; language: string }) {
  if (!code) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <Chip size="small" variant="outlined" label={language} />
      </Stack>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.5,
          borderRadius: 2,
          overflowX: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          background: 'rgba(15,23,42,0.92)',
          color: '#e2e8f0',
          fontSize: 13,
          fontFamily: 'Consolas, Monaco, monospace',
        }}
      >
        {code}
      </Box>
    </Paper>
  )
}

function ResourceLinkSection({ title, items }: { title: string; items: ResourceLinkItem[] }) {
  if (!items || items.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
      <Stack spacing={1.2}>
        {items.map((item) => (
          <Paper key={`${title}-${item.url}`} variant="outlined" sx={{ p: 1.4, borderRadius: 2 }}>
            <Link
              href={item.url}
              target="_blank"
              rel="noreferrer"
              underline="hover"
              sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontWeight: 700 }}
            >
              {item.label} <OpenInNewIcon fontSize="inherit" />
            </Link>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {item.note || '外部参考链接'}
            </Typography>
          </Paper>
        ))}
      </Stack>
    </Paper>
  )
}

function UsageGuideSection({ title, sections }: { title: string; sections: Array<{ title: string; content: string; tips?: string[] }> }) {
  if (!sections || sections.length === 0) return null

  return (
    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
      <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
        {title}
      </Typography>
      <Stack spacing={2}>
        {sections.map((section, idx) => (
          <Box key={idx}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1, color: 'primary.main' }}>
              {section.title}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                lineHeight: 1.8,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontFamily: 'inherit',
              }}
            >
              {section.content}
            </Typography>
            {section.tips && section.tips.length > 0 && (
              <Paper
                variant="outlined"
                sx={{
                  mt: 1.5,
                  p: 1.5,
                  borderRadius: 2,
                  backgroundColor: 'rgba(236,253,245,0.7)',
                  borderColor: 'rgba(34,197,94,0.26)',
                }}
              >
                <Typography variant="caption" sx={{ fontWeight: 700, color: 'success.main', mb: 0.75, display: 'block' }}>
                  💡 使用技巧
                </Typography>
                <Stack spacing={0.5}>
                  {section.tips.map((tip, tipIdx) => (
                    <Typography key={tipIdx} variant="body2" color="text.secondary">
                      • {tip}
                    </Typography>
                  ))}
                </Stack>
              </Paper>
            )}
          </Box>
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
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncSummary, setSyncSummary] = useState<string | null>(null)
  const [keyword, setKeyword] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>(() =>
    normalizeCategoryFilter(searchParams.get('category'))
  )
  const [selectedProvider, setSelectedProvider] = useState('all')
  const [selectedStatus, setSelectedStatus] = useState<'all' | VerificationStatus>('all')
  const [autoSyncAttempted, setAutoSyncAttempted] = useState(false)
  const [selectedModelKey, setSelectedModelKey] = useState<string | null>(null)
  const [selectedEntry, setSelectedEntry] = useState<CatalogEntry | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

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

  const fetchCatalog = async (allowAutoSync = true) => {
    setLoading(true)
    setError(null)

    try {
      const [overviewResponse, entriesResponse] = await Promise.all([
        apiClient.getModelCatalogOverview(),
        apiClient.getModelCatalogEntries(),
      ])

      const nextOverview = overviewResponse.data as CatalogOverview
      const nextEntries = (entriesResponse.data?.items || []) as CatalogEntry[]

      if (allowAutoSync && !autoSyncAttempted && nextOverview.total_entries === 0) {
        setAutoSyncAttempted(true)
        await performSync({ manual: false, forceRefresh: true })
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

  const performSync = async ({
    manual = true,
    forceRefresh = false,
  }: {
    manual?: boolean
    forceRefresh?: boolean
  } = {}) => {
    setSyncing(true)
    setSyncSummary(null)
    if (manual) {
      setError(null)
    }

    try {
      // Step 1: Submit sync task (returns immediately with task_id)
      const response = await apiClient.syncModelCatalog({
        force_refresh: forceRefresh,
      })
      const { task_id, message } = response.data
      console.log(`Sync task submitted: ${task_id}, ${message}`)

      // Step 2: Poll for completion
      let pollCount = 0
      const maxPolls = 300 // 5 minutes max (5000ms * 300)
      const pollInterval = 5000 // 5 seconds

      while (pollCount < maxPolls) {
        await new Promise((resolve) => setTimeout(resolve, pollInterval))
        const statusResponse = await apiClient.getSyncTaskStatus(task_id)
        const { status, result } = statusResponse.data

        if (status === 'completed' && result) {
          setSyncSummary(formatSyncSummary(result as CatalogSyncResult))
          await fetchCatalog(false)
          break
        } else if (status === 'failed') {
          setError(`校验失败: ${result?.error || '未知错误'}`)
          break
        }
        // status === 'running' or 'pending', continue polling
        pollCount++
      }

      if (pollCount >= maxPolls) {
        setError('校验任务超时，请稍后刷新页面查看结果。')
      }
    } catch (syncError) {
      setError(await extractApiErrorMessage(syncError, '联网同步模型档案失败'))
    } finally {
      setSyncing(false)
    }
  }

  const openEntryDetail = async (modelKey: string) => {
    startTransition(() => {
      setSelectedModelKey(modelKey)
      setSelectedEntry(null)
      setDetailError(null)
    })
    setDetailLoading(true)

    try {
      const response = await apiClient.getModelCatalogEntry(modelKey)
      setSelectedEntry(response.data as CatalogEntry)
    } catch (entryError) {
      setDetailError(await extractApiErrorMessage(entryError, '加载模型详情失败'))
    } finally {
      setDetailLoading(false)
    }
  }

  useEffect(() => {
    void fetchCatalog()
  }, [])

  const visibleEntries = entries.filter((entry) => {
    if (selectedCategory !== 'all' && entry.category !== selectedCategory) {
      return false
    }
    if (selectedProvider !== 'all' && entry.provider !== selectedProvider) {
      return false
    }
    if (selectedStatus !== 'all' && entry.verification_status !== selectedStatus) {
      return false
    }
    if (!deferredKeyword) {
      return true
    }

    const searchable = [
      entry.name,
      entry.model_key,
      entry.provider,
      entry.category_label,
      entry.subcategory || '',
      entry.summary || '',
      ...(entry.tags || []),
      ...(entry.modalities || []),
    ]
      .join(' ')
      .toLowerCase()

    return searchable.includes(deferredKeyword)
  })

  const categoryChips = overview?.categories || []
  const providerOptions = overview?.providers || []

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background: 'linear-gradient(180deg, #edf4ff 0%, #f5f7fb 42%, #fefcf7 100%)',
        py: 4,
      }}
    >
      <Container maxWidth="xl">
        <Paper
          elevation={0}
          sx={{
            p: { xs: 2.5, md: 3.5 },
            borderRadius: 5,
            mb: 3,
            background:
              'linear-gradient(140deg, rgba(9,46,96,0.98) 0%, rgba(12,85,137,0.96) 50%, rgba(31,122,104,0.94) 100%)',
            color: 'white',
            boxShadow: '0 24px 48px rgba(22,50,92,0.16)',
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: { xs: 'flex-start', md: 'center' },
              justifyContent: 'space-between',
              gap: 2,
              flexDirection: { xs: 'column', md: 'row' },
            }}
          >
            <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-start' }}>
              <IconButton
                onClick={() => navigate('/home')}
                sx={{
                  color: 'white',
                  backgroundColor: 'rgba(255,255,255,0.12)',
                  mt: 0.25,
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.2)' },
                }}
              >
                <ArrowBackIcon />
              </IconButton>
              <Box>
                <Typography variant="h4" sx={{ fontWeight: 800, letterSpacing: '0.04em' }}>
                  模型档案中心
                </Typography>
                <Typography variant="body1" sx={{ mt: 1, color: 'rgba(255,255,255,0.84)' }}>
                  统一整理项目已接入模型，并按“核心档案、接口配置、Prompt 路由、部署接入”四层知识结构展示。
                </Typography>
                <Typography variant="body2" sx={{ mt: 1.25, color: 'rgba(255,255,255,0.72)' }}>
                  默认按模型配置变化智能校验：已校验且未更新的模型自动跳过，需要时可手动强制刷新。
                </Typography>
              </Box>
            </Box>

            <Button
                variant="contained"
                onClick={() => void performSync({ forceRefresh: true })}
                startIcon={syncing ? <CircularProgress color="inherit" size={16} /> : <SyncIcon />}
                disabled={syncing}
                sx={{
                  minWidth: 140,
                  backgroundColor: '#f7c873',
                  color: '#1c2430',
                  fontWeight: 700,
                  '&:hover': { backgroundColor: '#f2bc57' },
                }}
              >
                {syncing ? '校验中...' : '全量校验'}
              </Button>
          </Box>
        </Paper>

        <Grid container spacing={2.5} sx={{ mb: 3 }}>
          {[
            { label: '模型总数', value: overview?.total_entries ?? '--', icon: <HubIcon color="primary" /> },
            { label: '已验证', value: overview?.verified_entries ?? '--', icon: <VerifiedIcon color="success" /> },
            { label: '部分验证', value: overview?.partial_entries ?? '--', icon: <WarningAmberIcon color="warning" /> },
            { label: '验证失败', value: overview?.failed_entries ?? '--', icon: <ErrorOutlineIcon color="error" /> },
          ].map((item) => (
            <Grid item xs={12} sm={6} lg={3} key={item.label}>
              <Paper
                variant="outlined"
                sx={{
                  p: 2.25,
                  borderRadius: 4,
                  height: '100%',
                  borderColor: 'rgba(15,76,129,0.12)',
                  background: 'rgba(255,255,255,0.9)',
                }}
              >
                <Stack direction="row" spacing={1.5} alignItems="center">
                  {item.icon}
                  <Box>
                    <Typography variant="body2" color="text.secondary">
                      {item.label}
                    </Typography>
                    <Typography variant="h5" sx={{ fontWeight: 800 }}>
                      {item.value}
                    </Typography>
                  </Box>
                </Stack>
              </Paper>
            </Grid>
          ))}
        </Grid>

        <Paper
          variant="outlined"
          sx={{
            p: 2.5,
            borderRadius: 4,
            mb: 3,
            background: 'rgba(255,255,255,0.9)',
            borderColor: 'rgba(15,76,129,0.12)',
          }}
        >
          <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 0.75 }}>
            外部选型导航
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            这里放的是能力对比、模型库与文档入口，适合快速选型；具体接入仍以档案详情里的官方来源和项目配置为准。
          </Typography>
          <Grid container spacing={1.5}>
            {EXTERNAL_HUBS.map((hub) => (
              <Grid item xs={12} md={6} xl={3} key={hub.url}>
                <Paper variant="outlined" sx={{ p: 1.75, borderRadius: 3, height: '100%' }}>
                  <Link
                    href={hub.url}
                    target="_blank"
                    rel="noreferrer"
                    underline="hover"
                    sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, fontWeight: 700 }}
                  >
                    {hub.label} <OpenInNewIcon fontSize="inherit" />
                  </Link>
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.8, lineHeight: 1.7 }}>
                    {hub.description}
                  </Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>
        </Paper>

        <Paper
          variant="outlined"
          sx={{
            p: 2.5,
            borderRadius: 4,
            mb: 3,
            background: 'rgba(255,255,255,0.88)',
            borderColor: 'rgba(15,76,129,0.12)',
          }}
        >
          <Grid container spacing={2}>
            <Grid item xs={12} lg={4}>
              <TextField
                fullWidth
                label="搜索模型 / 标签 / 摘要"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="例如：qwen、语音合成、长上下文"
              />
            </Grid>
            <Grid item xs={12} sm={6} lg={4}>
              <TextField
                select
                fullWidth
                SelectProps={{ native: true }}
                label="提供商"
                value={selectedProvider}
                onChange={(event) => setSelectedProvider(event.target.value)}
              >
                <option value="all">全部提供商</option>
                {providerOptions.map((provider) => (
                  <option key={provider.key} value={provider.key}>
                    {provider.key} ({provider.count})
                  </option>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6} lg={4}>
              <TextField
                select
                fullWidth
                SelectProps={{ native: true }}
                label="校验状态"
                value={selectedStatus}
                onChange={(event) => setSelectedStatus(event.target.value as 'all' | VerificationStatus)}
              >
                <option value="all">全部状态</option>
                <option value="verified">已验证</option>
                <option value="partial">部分验证</option>
                <option value="failed">验证失败</option>
                <option value="pending">待验证</option>
              </TextField>
            </Grid>
          </Grid>

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
            <Chip
              label={`全部 (${entries.length})`}
              color={selectedCategory === 'all' ? 'primary' : 'default'}
              variant={selectedCategory === 'all' ? 'filled' : 'outlined'}
              onClick={() => setSelectedCategory('all')}
            />
            {categoryChips.map((category) => (
              <Chip
                key={category.key}
                label={`${CATEGORY_LABELS[category.key] || category.key} (${category.count})`}
                color={selectedCategory === category.key ? 'primary' : 'default'}
                variant={selectedCategory === category.key ? 'filled' : 'outlined'}
                onClick={() => setSelectedCategory(normalizeCategoryFilter(category.key))}
              />
            ))}
          </Stack>

          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            最近同步：{formatDateTime(overview?.last_synced_at)} | 最近校验：{formatDateTime(overview?.last_verified_at)}
          </Typography>
        </Paper>

        {error ? (
          <Alert
            severity="error"
            sx={{ mb: 3 }}
            action={
              <Button color="inherit" size="small" onClick={() => void fetchCatalog(false)}>
                重试
              </Button>
            }
          >
            {error}
          </Alert>
        ) : null}

        {syncSummary ? (
          <Alert severity="success" sx={{ mb: 3 }}>
            {syncSummary}
          </Alert>
        ) : null}

        {loading ? (
          <Paper
            variant="outlined"
            sx={{
              borderRadius: 4,
              p: 6,
              display: 'flex',
              justifyContent: 'center',
              background: 'rgba(255,255,255,0.88)',
            }}
          >
            <CircularProgress />
          </Paper>
        ) : visibleEntries.length === 0 ? (
          <Paper
            variant="outlined"
            sx={{
              borderRadius: 4,
              p: 5,
              textAlign: 'center',
              background: 'rgba(255,255,255,0.88)',
            }}
          >
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              当前筛选条件下没有模型档案
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
              可以放宽筛选条件，或重新执行一次联网校验同步。
            </Typography>
            <Button sx={{ mt: 2 }} variant="outlined" onClick={() => void performSync({ forceRefresh: true })}>
              全量校验
            </Button>
          </Paper>
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
                    borderColor: 'rgba(15,76,129,0.12)',
                    transition: 'transform 0.2s ease, box-shadow 0.2s ease',
                    '&:hover': {
                      transform: 'translateY(-3px)',
                      boxShadow: '0 18px 32px rgba(17,48,88,0.08)',
                    },
                  }}
                  onClick={() => void openEntryDetail(entry.model_key)}
                >
                  <Stack spacing={1.5} sx={{ height: '100%' }}>
                    <Box
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        gap: 1,
                        alignItems: 'flex-start',
                      }}
                    >
                      <Box>
                        <Typography variant="h6" sx={{ fontWeight: 800, wordBreak: 'break-word' }}>
                          {entry.name}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {entry.model_key}
                        </Typography>
                      </Box>
                      <Chip
                        size="small"
                        label={STATUS_META[entry.verification_status].label}
                        color={STATUS_META[entry.verification_status].color}
                      />
                    </Box>

                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      <Chip size="small" variant="outlined" label={entry.category_label} />
                      {entry.subcategory ? (
                        <Chip size="small" variant="outlined" color="primary" label={entry.subcategory} />
                      ) : null}
                      <Chip size="small" variant="outlined" label={entry.provider} />
                    </Stack>

                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{
                        lineHeight: 1.7,
                        display: '-webkit-box',
                        WebkitLineClamp: 3,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {entry.summary || '暂无摘要'}
                    </Typography>

                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {(entry.project_modules || []).slice(0, 2).map((module) => (
                        <Chip key={module} size="small" color="secondary" variant="outlined" label={module} />
                      ))}
                      {(entry.tooling_badges || []).slice(0, 3).map((badge) => (
                        <Chip key={badge} size="small" variant="outlined" label={badge} />
                      ))}
                    </Stack>

                    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                      {(entry.primary_strengths || []).slice(0, 2).map((strength) => (
                        <Chip key={strength} size="small" color="success" variant="outlined" label={strength} />
                      ))}
                    </Stack>

                    <Divider sx={{ my: 0.5 }} />

                    <Grid container spacing={1}>
                      <Grid item xs={6}>
                        <Typography variant="caption" color="text.secondary">
                          校验评分
                        </Typography>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          {(entry.verification_score * 100).toFixed(0)} / 100
                        </Typography>
                      </Grid>
                      <Grid item xs={6}>
                        <Typography variant="caption" color="text.secondary">
                          可达来源
                        </Typography>
                        <Typography variant="body2" sx={{ fontWeight: 700 }}>
                          {entry.reachable_source_count} / {entry.total_source_count}
                        </Typography>
                      </Grid>
                    </Grid>

                    <Typography variant="caption" color="text.secondary" sx={{ mt: 'auto' }}>
                      最近校验：{formatDateTime(entry.last_verified_at)}
                    </Typography>
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        )}

        <Dialog open={Boolean(selectedModelKey)} onClose={() => setSelectedModelKey(null)} maxWidth="lg" fullWidth>
          <DialogTitle sx={{ fontWeight: 800 }}>
            {selectedEntry?.name || selectedModelKey || '模型详情'}
          </DialogTitle>
          <DialogContent dividers>
            {detailLoading ? (
              <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
              </Box>
            ) : detailError ? (
              <Alert severity="error">{detailError}</Alert>
            ) : selectedEntry ? (
              <Stack spacing={2.5}>
                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Stack spacing={1.5}>
                    <Box
                      sx={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        gap: 1,
                        flexWrap: 'wrap',
                        alignItems: 'center',
                      }}
                    >
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        <Chip label={selectedEntry.category_label} color="primary" />
                        {selectedEntry.subcategory ? <Chip label={selectedEntry.subcategory} variant="outlined" /> : null}
                        <Chip label={selectedEntry.provider} variant="outlined" />
                        <Chip
                          label={STATUS_META[selectedEntry.verification_status].label}
                          color={STATUS_META[selectedEntry.verification_status].color}
                        />
                      </Stack>

                      {selectedEntry.documentation_url ? (
                        <Link
                          href={selectedEntry.documentation_url}
                          target="_blank"
                          rel="noreferrer"
                          underline="hover"
                          sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
                        >
                          官方文档 <OpenInNewIcon fontSize="inherit" />
                        </Link>
                      ) : null}
                    </Box>

                    <Typography variant="body1" sx={{ lineHeight: 1.9 }}>
                      {selectedEntry.summary || '暂无摘要'}
                    </Typography>

                    <Grid container spacing={1.5}>
                      <Grid item xs={12} md={4}>
                        <Typography variant="caption" color="text.secondary">
                          归档来源
                        </Typography>
                        <Typography variant="body2">{selectedEntry.config_source}</Typography>
                      </Grid>
                      <Grid item xs={12} md={4}>
                        <Typography variant="caption" color="text.secondary">
                          最近同步
                        </Typography>
                        <Typography variant="body2">{formatDateTime(selectedEntry.last_synced_at)}</Typography>
                      </Grid>
                      <Grid item xs={12} md={4}>
                        <Typography variant="caption" color="text.secondary">
                          校验范围
                        </Typography>
                        <Typography variant="body2">{selectedEntry.verification_scope || '暂无'}</Typography>
                      </Grid>
                    </Grid>

                    <Typography variant="body2" color="text.secondary">
                      {selectedEntry.verification_notes}
                    </Typography>

                    {selectedEntry.verification_status === 'partial' ? (
                      <Alert severity="warning" variant="outlined">
                        当前条目已验证提供商与能力范围，但官方来源未出现与项目内部 ID 完全一致的模型名。
                        这通常意味着它是项目内部别名、降级位或版本包装名。
                      </Alert>
                    ) : null}
                  </Stack>
                </Paper>

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
                    一层：核心模型档案
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    这一层回答“它是什么、擅长什么、在项目里负责什么”。
                  </Typography>
                  <Grid container spacing={2.5}>
                    <Grid item xs={12}>
                      <Alert severity="info" variant="outlined">
                        {selectedEntry.identity_profile?.core_positioning || selectedEntry.summary || '暂无定位说明'}
                      </Alert>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <LabeledValueSection
                        title="身份与谱系"
                        items={selectedEntry.identity_profile?.model_lineage || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <LabeledValueSection
                        title="上下文与版本"
                        items={selectedEntry.identity_profile?.context_window || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <BulletSection
                        title="强项象限"
                        items={selectedEntry.identity_profile?.capability_quadrants?.strengths || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <BulletSection
                        title="弱项与边界"
                        items={selectedEntry.identity_profile?.capability_quadrants?.weaknesses || selectedEntry.limitations || []}
                      />
                    </Grid>
                    <Grid item xs={12}>
                      <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3 }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                          项目适配场景
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.25 }}>
                          {(selectedEntry.identity_profile?.project_fit?.modules || selectedEntry.project_modules || []).map((item) => (
                            <Chip key={item} color="primary" variant="outlined" label={item} />
                          ))}
                          {(selectedEntry.identity_profile?.capability_quadrants?.modalities || []).map((item) => (
                            <Chip key={item} variant="outlined" label={item} />
                          ))}
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                          {selectedEntry.identity_profile?.project_fit?.role_summary || '暂无项目角色说明'}
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {(selectedEntry.identity_profile?.project_fit?.task_types || selectedEntry.project_task_labels || []).map((item) => (
                            <Chip key={item} size="small" color="success" variant="outlined" label={item} />
                          ))}
                        </Stack>
                      </Paper>
                    </Grid>
                  </Grid>
                </Paper>

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
                    二层：编程接口与配置标准
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    这一层回答“AI 编程工具如何识别它、项目里该怎么调它、环境变量怎么配”。
                  </Typography>
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
                    <Grid item xs={12}>
                      <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3 }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                          AI 编程工具识别标签
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.25 }}>
                          {(selectedEntry.integration_profile?.tooling_badges || selectedEntry.tooling_badges || []).map((item) => (
                            <Chip key={item} variant="outlined" label={item} />
                          ))}
                        </Stack>
                        <Alert severity="success" variant="outlined">
                          {selectedEntry.integration_profile?.recommended_wrapper ||
                            '建议通过统一封装层屏蔽不同供应商 API 差异。'}
                        </Alert>
                      </Paper>
                    </Grid>
                    <Grid item xs={12} lg={6}>
                      <CodeSnippetSection
                        title="Python 统一调用模板"
                        language="python"
                        code={selectedEntry.integration_profile?.sdk_templates?.python}
                      />
                    </Grid>
                    <Grid item xs={12} lg={6}>
                      <CodeSnippetSection
                        title="JavaScript / SDK 模板"
                        language="javascript"
                        code={selectedEntry.integration_profile?.sdk_templates?.javascript}
                      />
                    </Grid>
                  </Grid>
                </Paper>

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
                    三层：Prompt 工程与路由策略
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    这一层回答“该怎么给它下指令、什么任务该命中它、失败后如何回退”。
                  </Typography>
                  <Stack spacing={2}>
                    <Alert severity="info" variant="outlined">
                      {selectedEntry.prompt_router_profile?.system_role || '暂无系统角色建议'}
                    </Alert>

                    <Grid container spacing={2.5}>
                      {(selectedEntry.prompt_router_profile?.prompt_patterns || []).map((item) => (
                        <Grid item xs={12} md={4} key={item.title}>
                          <CodeSnippetSection title={item.title} language="prompt" code={item.template} />
                        </Grid>
                      ))}
                    </Grid>

                    <Grid container spacing={2.5}>
                      <Grid item xs={12} md={7}>
                        <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                            智能路由规则
                          </Typography>
                          <Stack spacing={1.2}>
                            {(selectedEntry.prompt_router_profile?.router_rules || []).length > 0 ? (
                              selectedEntry.prompt_router_profile?.router_rules?.map((rule) => (
                                <Paper key={`${rule.when}-${rule.action}`} variant="outlined" sx={{ p: 1.4, borderRadius: 2 }}>
                                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                    触发：{rule.when}
                                  </Typography>
                                  <Typography variant="body2" sx={{ mt: 0.6 }}>
                                    动作：{rule.action}
                                  </Typography>
                                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.6 }}>
                                    原因：{rule.reason}
                                  </Typography>
                                </Paper>
                              ))
                            ) : (
                              <Typography variant="body2" color="text.secondary">
                                暂无显式路由规则。
                              </Typography>
                            )}
                          </Stack>
                        </Paper>
                      </Grid>
                      <Grid item xs={12} md={5}>
                        <BulletSection
                          title="最佳实践"
                          items={selectedEntry.prompt_router_profile?.best_practice_tips || []}
                        />
                      </Grid>
                    </Grid>

                    {(selectedEntry.prompt_router_profile?.fallback_chain || []).length > 0 ? (
                      <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3 }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                          回退链路
                        </Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {selectedEntry.prompt_router_profile?.fallback_chain?.map((item) => (
                            <Chip key={item} color="warning" variant="outlined" label={item} />
                          ))}
                        </Stack>
                      </Paper>
                    ) : null}
                  </Stack>
                </Paper>

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 2 }}>
                    四层：部署接入与外部导航
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    这一层回答“如何做代理、如何走统一入口、需要去哪里继续查文档和比对”。
                  </Typography>
                  <Grid container spacing={2.5}>
                    <Grid item xs={12} md={6}>
                      <LabeledValueSection
                        title="接入拓扑"
                        items={selectedEntry.deployment_profile?.access_topology || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <LabeledValueSection
                        title="项目入口建议"
                        items={selectedEntry.deployment_profile?.project_entrypoints || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <LabeledValueSection
                        title="部署环境约定"
                        items={selectedEntry.deployment_profile?.environment_convention || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                          本地部署与替代建议
                        </Typography>
                        <Typography variant="body2" sx={{ lineHeight: 1.8 }}>
                          {selectedEntry.deployment_profile?.local_deployment_note || '暂无本地部署说明'}
                        </Typography>
                      </Paper>
                    </Grid>
                    <Grid item xs={12}>
                      <CodeSnippetSection
                        title="统一代理示例"
                        language="nginx"
                        code={selectedEntry.deployment_profile?.proxy_snippet}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <ResourceLinkSection
                        title="官方来源与补充文档"
                        items={selectedEntry.resource_navigation?.official_sources || []}
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <ResourceLinkSection
                        title="能力对比与模型库"
                        items={[
                          ...(selectedEntry.resource_navigation?.selection_hubs || []),
                          ...(selectedEntry.resource_navigation?.model_hubs || []),
                          ...(selectedEntry.resource_navigation?.provider_portals || []),
                        ]}
                      />
                    </Grid>
                  </Grid>
                </Paper>

                <Grid container spacing={2.5}>
                  <Grid item xs={12} md={6}>
                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3, height: '100%' }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                        推荐场景
                      </Typography>
                      <Stack spacing={1}>
                        {selectedEntry.recommended_scenarios.length > 0 ? (
                          selectedEntry.recommended_scenarios.map((item) => (
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
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3, height: '100%' }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                        已知限制
                      </Typography>
                      <Stack spacing={1}>
                        {selectedEntry.limitations.length > 0 ? (
                          selectedEntry.limitations.map((item) => (
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
                  </Grid>
                </Grid>

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                    集成说明
                  </Typography>
                  <Stack spacing={1}>
                    {selectedEntry.integration_notes.length > 0 ? (
                      selectedEntry.integration_notes.map((item) => (
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

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                    能力标签
                  </Typography>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {(selectedEntry.capabilities || []).map((capability, index) => {
                      const label =
                        capability.name ||
                        capability.label ||
                        capability.description ||
                        `capability-${index}`
                      return (
                        <Chip
                          key={`${label}-${index}`}
                          label={capability.level ? `${label} · ${capability.level}` : label}
                          variant="outlined"
                        />
                      )
                    })}
                    {selectedEntry.capabilities.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">
                        暂无
                      </Typography>
                    ) : null}
                  </Stack>
                </Paper>

                <Grid container spacing={2.5}>
                  <Grid item xs={12} lg={4}>
                    <DetailKvSection title="约束与输入限制" data={selectedEntry.constraints || {}} />
                  </Grid>
                  <Grid item xs={12} lg={4}>
                    <DetailKvSection title="性能与成本信息" data={selectedEntry.performance || {}} />
                  </Grid>
                  <Grid item xs={12} lg={4}>
                    <DetailKvSection
                      title="路由与默认参数"
                      data={{ ...(selectedEntry.routing || {}), default_params: selectedEntry.default_params || {} }}
                    />
                  </Grid>
                </Grid>

                {selectedEntry.detailed_specs && Object.keys(selectedEntry.detailed_specs).length > 0 && (
                  <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                      详细能力规格
                    </Typography>
                    <Stack spacing={2}>
                      {selectedEntry.detailed_specs.voice_synthesis && (
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>
                            语音合成规格
                          </Typography>
                          {selectedEntry.detailed_specs.voice_synthesis.voice_catalog && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                音色目录（共 {selectedEntry.detailed_specs.voice_synthesis.voice_catalog.total_count || '若干'} 种）
                              </Typography>
                              <Grid container spacing={1.5}>
                                {(selectedEntry.detailed_specs.voice_synthesis.voice_catalog.categories || []).map((category: any) => (
                                  <Grid item xs={12} key={category.name}>
                                    <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                                      {category.name}
                                    </Typography>
                                    <Grid container spacing={1}>
                                      {(category.voices || []).map((voice: any) => (
                                        <Grid item xs={12} sm={6} md={4} key={voice.id}>
                                          <Paper
                                            variant="outlined"
                                            sx={{
                                              p: 1.5,
                                              borderRadius: 2,
                                              borderColor: 'rgba(15,76,129,0.2)',
                                              '&:hover': { borderColor: 'primary.main' },
                                            }}
                                          >
                                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                                {voice.name}
                                              </Typography>
                                              <Chip
                                                label={voice.gender === 'female' ? '女声' : '男声'}
                                                size="small"
                                                color={voice.gender === 'female' ? 'error' : 'info'}
                                                sx={{ fontSize: '0.7rem' }}
                                              />
                                            </Box>
                                            <Typography variant="caption" color="text.secondary">
                                              {voice.description}
                                            </Typography>
                                            {voice.emotion_tags && voice.emotion_tags.length > 0 && (
                                              <Box sx={{ mt: 0.5, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                                                {voice.emotion_tags.slice(0, 3).map((tag: string) => (
                                                  <Chip key={tag} label={tag} size="small" variant="outlined" sx={{ fontSize: '0.65rem', height: 20 }} />
                                                ))}
                                              </Box>
                                            )}
                                          </Paper>
                                        </Grid>
                                      ))}
                                    </Grid>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                          {selectedEntry.detailed_specs.voice_synthesis.instruct_control && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                情绪控制（Instruct）
                              </Typography>
                              <Grid container spacing={1}>
                                {(selectedEntry.detailed_specs.voice_synthesis.instruct_control.supported_emotions || []).map((emotion: any) => (
                                  <Grid item xs={6} sm={4} md={3} key={emotion.tag}>
                                    <Paper variant="outlined" sx={{ p: 1, borderRadius: 2 }}>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {emotion.label}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {emotion.description}
                                      </Typography>
                                    </Paper>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                        </Box>
                      )}
                      {selectedEntry.detailed_specs.video_generation && (
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>
                            视频生成规格
                          </Typography>
                          
                          {selectedEntry.detailed_specs.video_generation.core_function && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                                核心功能
                              </Typography>
                              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                                {selectedEntry.detailed_specs.video_generation.core_function.description}
                              </Typography>
                              {selectedEntry.detailed_specs.video_generation.core_function.key_features && (
                                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                                  {selectedEntry.detailed_specs.video_generation.core_function.key_features.map((feature: string, idx: number) => (
                                    <Chip key={idx} label={feature} size="small" color="primary" variant="outlined" />
                                  ))}
                                </Box>
                              )}
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.input_modalities && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                输入模态
                              </Typography>
                              <Grid container spacing={1}>
                                {selectedEntry.detailed_specs.video_generation.input_modalities.map((modality: any) => (
                                  <Grid item xs={12} sm={4} key={modality.id}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                          {modality.name}
                                        </Typography>
                                        {modality.required && (
                                          <Chip label="必需" size="small" color="error" sx={{ fontSize: '0.65rem', height: 18 }} />
                                        )}
                                      </Box>
                                      <Typography variant="caption" color="text.secondary">
                                        {modality.description}
                                      </Typography>
                                    </Paper>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.output_format && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                输出格式
                              </Typography>
                              <Grid container spacing={1}>
                                <Grid item xs={6} sm={3}>
                                  <Paper variant="outlined" sx={{ p: 1, borderRadius: 2, textAlign: 'center' }}>
                                    <Typography variant="caption" color="text.secondary">容器</Typography>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {selectedEntry.detailed_specs.video_generation.output_format.container || 'MP4'}
                                    </Typography>
                                  </Paper>
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <Paper variant="outlined" sx={{ p: 1, borderRadius: 2, textAlign: 'center' }}>
                                    <Typography variant="caption" color="text.secondary">视频编码</Typography>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {selectedEntry.detailed_specs.video_generation.output_format.video_codec || 'H.264'}
                                    </Typography>
                                  </Paper>
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <Paper variant="outlined" sx={{ p: 1, borderRadius: 2, textAlign: 'center' }}>
                                    <Typography variant="caption" color="text.secondary">音频编码</Typography>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {selectedEntry.detailed_specs.video_generation.output_format.audio_codec || 'AAC'}
                                    </Typography>
                                  </Paper>
                                </Grid>
                                <Grid item xs={6} sm={3}>
                                  <Paper variant="outlined" sx={{ p: 1, borderRadius: 2, textAlign: 'center' }}>
                                    <Typography variant="caption" color="text.secondary">帧率</Typography>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      {selectedEntry.detailed_specs.video_generation.output_format.frame_rate || 30} fps
                                    </Typography>
                                  </Paper>
                                </Grid>
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.basic_params && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                基础参数
                              </Typography>
                              <Grid container spacing={1}>
                                {selectedEntry.detailed_specs.video_generation.basic_params.duration && (
                                  <Grid item xs={12} sm={6}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Typography variant="caption" color="text.secondary">视频时长</Typography>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {selectedEntry.detailed_specs.video_generation.basic_params.duration.min_seconds || 2}-{selectedEntry.detailed_specs.video_generation.basic_params.duration.max_seconds || 15} 秒
                                      </Typography>
                                      {selectedEntry.detailed_specs.video_generation.basic_params.duration.note && (
                                        <Typography variant="caption" color="text.secondary">
                                          {selectedEntry.detailed_specs.video_generation.basic_params.duration.note}
                                        </Typography>
                                      )}
                                    </Paper>
                                  </Grid>
                                )}
                                {selectedEntry.detailed_specs.video_generation.basic_params.resolution && (
                                  <Grid item xs={12} sm={6}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Typography variant="caption" color="text.secondary">分辨率</Typography>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {(selectedEntry.detailed_specs.video_generation.basic_params.resolution.options || []).join(' / ')}
                                      </Typography>
                                      {selectedEntry.detailed_specs.video_generation.basic_params.resolution.recommended && (
                                        <Typography variant="caption" color="text.secondary">
                                          推荐：{selectedEntry.detailed_specs.video_generation.basic_params.resolution.recommended}
                                        </Typography>
                                      )}
                                    </Paper>
                                  </Grid>
                                )}
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.advanced_features && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                高级功能
                              </Typography>
                              <Grid container spacing={1}>
                                {selectedEntry.detailed_specs.video_generation.advanced_features.map((feature: any) => (
                                  <Grid item xs={12} sm={6} md={4} key={feature.id}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {feature.name}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {feature.description}
                                      </Typography>
                                      {feature.version_support && (
                                        <Chip label={feature.version_support} size="small" variant="outlined" sx={{ mt: 0.5, fontSize: '0.65rem', height: 18 }} />
                                      )}
                                    </Paper>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.reference_input && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                参考输入
                              </Typography>
                              <Grid container spacing={2}>
                                {selectedEntry.detailed_specs.video_generation.reference_input.reference_images && (
                                  <Grid item xs={12} md={6}>
                                    <Alert severity="info" variant="outlined" sx={{ mb: 1 }}>
                                      参考图：最多 {selectedEntry.detailed_specs.video_generation.reference_input.reference_images.max_count} 张
                                    </Alert>
                                    <Typography variant="caption" color="text.secondary">
                                      格式：{(selectedEntry.detailed_specs.video_generation.reference_input.reference_images.input_spec?.formats || []).join(', ')}
                                    </Typography>
                                    {selectedEntry.detailed_specs.video_generation.reference_input.reference_images.weight_control?.enabled && (
                                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                                        支持权重控制（{(selectedEntry.detailed_specs.video_generation.reference_input.reference_images.weight_control.range || [0, 1]).join('-')}）
                                      </Typography>
                                    )}
                                  </Grid>
                                )}
                                {selectedEntry.detailed_specs.video_generation.reference_input.reference_videos && (
                                  <Grid item xs={12} md={6}>
                                    <Alert severity="info" variant="outlined" sx={{ mb: 1 }}>
                                      参考视频：最多 {selectedEntry.detailed_specs.video_generation.reference_input.reference_videos.max_count} 个
                                    </Alert>
                                    <Typography variant="caption" color="text.secondary">
                                      时长：{selectedEntry.detailed_specs.video_generation.reference_input.reference_videos.input_spec?.duration_range?.min}-{selectedEntry.detailed_specs.video_generation.reference_input.reference_videos.input_spec?.duration_range?.max}秒
                                    </Typography>
                                  </Grid>
                                )}
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.frame_control && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                首尾帧控制
                              </Typography>
                              <Grid container spacing={2}>
                                <Grid item xs={12} md={6}>
                                  <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      首帧控制
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      {selectedEntry.detailed_specs.video_generation.frame_control.first_frame?.description}
                                    </Typography>
                                  </Paper>
                                </Grid>
                                <Grid item xs={12} md={6}>
                                  <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                      尾帧控制
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                      {selectedEntry.detailed_specs.video_generation.frame_control.last_frame?.description}
                                    </Typography>
                                  </Paper>
                                </Grid>
                              </Grid>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.camera_control && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                镜头控制
                              </Typography>
                              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                                {(selectedEntry.detailed_specs.video_generation.camera_control.preset_movements || []).map((movement: any) => (
                                  <Chip
                                    key={movement.id}
                                    label={`${movement.name}：${movement.description}`}
                                    size="small"
                                    variant="outlined"
                                  />
                                ))}
                              </Box>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.prompt_examples && selectedEntry.detailed_specs.video_generation.prompt_examples.length > 0 && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                提示词范例
                              </Typography>
                              <Stack spacing={1.5}>
                                {selectedEntry.detailed_specs.video_generation.prompt_examples.map((example: any, idx: number) => (
                                  <Paper
                                    key={idx}
                                    variant="outlined"
                                    sx={{
                                      p: 2,
                                      borderRadius: 2,
                                      backgroundColor: 'rgba(15,76,129,0.04)',
                                      borderLeft: '4px solid',
                                      borderColor: 'primary.main',
                                    }}
                                  >
                                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
                                      {example.title}
                                    </Typography>
                                    {example.description && (
                                      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                                        {example.description}
                                      </Typography>
                                    )}
                                    <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: '0.8rem' }}>
                                      {example.content}
                                    </Typography>
                                  </Paper>
                                ))}
                              </Stack>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.best_practices && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                最佳实践
                              </Typography>
                              <Stack spacing={0.5}>
                                {(selectedEntry.detailed_specs.video_generation.best_practices.tips || []).map((tip: string, idx: number) => (
                                  <Typography key={idx} variant="body2" color="text.secondary">
                                    • {tip}
                                  </Typography>
                                ))}
                              </Stack>
                            </Box>
                          )}
                          
                          {selectedEntry.detailed_specs.video_generation.limitations && selectedEntry.detailed_specs.video_generation.limitations.length > 0 && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                限制说明
                              </Typography>
                              <Stack spacing={0.5}>
                                {selectedEntry.detailed_specs.video_generation.limitations.map((limitation: string, idx: number) => (
                                  <Typography key={idx} variant="body2" color="warning.main">
                                    ⚠ {limitation}
                                  </Typography>
                                ))}
                              </Stack>
                            </Box>
                          )}
                        </Box>
                      )}
                      {selectedEntry.detailed_specs.image_editing && (
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>
                            图像编辑规格
                          </Typography>
                          {selectedEntry.detailed_specs.image_editing.edit_instructions && (
                            <Box sx={{ mb: 2 }}>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                支持的编辑类型
                              </Typography>
                              <Grid container spacing={1}>
                                {(selectedEntry.detailed_specs.image_editing.edit_instructions.edit_types || []).map((editType: any) => (
                                  <Grid item xs={12} sm={6} key={editType.type}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {editType.type}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {editType.description}
                                      </Typography>
                                    </Paper>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                        </Box>
                      )}
                      {selectedEntry.detailed_specs.music_generation && (
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>
                            音乐生成规格
                          </Typography>
                          <Grid container spacing={2}>
                            {selectedEntry.detailed_specs.music_generation.style_control && (
                              <Grid item xs={12} md={6}>
                                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                  预设风格
                                </Typography>
                                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                                  {(selectedEntry.detailed_specs.music_generation.style_control.preset_styles || []).map((style: any) => (
                                    <Chip key={style.id} label={style.name} size="small" variant="outlined" />
                                  ))}
                                </Box>
                              </Grid>
                            )}
                            {selectedEntry.detailed_specs.music_generation.mood_control && (
                              <Grid item xs={12} md={6}>
                                <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                  支持的情绪
                                </Typography>
                                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                                  {(selectedEntry.detailed_specs.music_generation.mood_control.supported_moods || []).map((mood: any) => (
                                    <Chip key={mood.tag} label={mood.label} size="small" variant="outlined" />
                                  ))}
                                </Box>
                              </Grid>
                            )}
                          </Grid>
                        </Box>
                      )}
                      {selectedEntry.detailed_specs.audio_generation && (
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1, color: 'primary.main' }}>
                            音效生成规格
                          </Typography>
                          {selectedEntry.detailed_specs.audio_generation.audio_types && (
                            <Box>
                              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                                音效类型
                              </Typography>
                              <Grid container spacing={1}>
                                {(selectedEntry.detailed_specs.audio_generation.audio_types || []).map((audioType: any) => (
                                  <Grid item xs={12} sm={4} key={audioType.type}>
                                    <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                        {audioType.type}
                                      </Typography>
                                      <Typography variant="caption" color="text.secondary">
                                        {audioType.description}
                                      </Typography>
                                    </Paper>
                                  </Grid>
                                ))}
                              </Grid>
                            </Box>
                          )}
                        </Box>
                      )}
                    </Stack>
                  </Paper>
                )}

                {selectedEntry.usage_guide && selectedEntry.usage_guide.sections && selectedEntry.usage_guide.sections.length > 0 && (
                  <UsageGuideSection
                    title={selectedEntry.usage_guide.title || '使用指南'}
                    sections={selectedEntry.usage_guide.sections}
                  />
                )}

                <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
                    联网验证来源
                  </Typography>
                  <Stack spacing={1.5}>
                    {(selectedEntry.sources || []).map((source) => (
                      <Paper
                        key={source.url}
                        variant="outlined"
                        sx={{
                          p: 2,
                          borderRadius: 3,
                          background: source.verified ? 'rgba(236,253,245,0.7)' : 'rgba(255,251,235,0.7)',
                          borderColor: source.verified ? 'rgba(34,197,94,0.26)' : 'rgba(245,158,11,0.26)',
                        }}
                      >
                        <Stack spacing={1}>
                          <Box
                            sx={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              gap: 1,
                              flexWrap: 'wrap',
                              alignItems: 'center',
                            }}
                          >
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                              <Chip size="small" label={source.source_type} variant="outlined" />
                              <Chip
                                size="small"
                                color={source.verified ? 'success' : source.reachable ? 'warning' : 'error'}
                                label={source.verified ? '强匹配' : source.reachable ? '弱匹配' : '不可达'}
                              />
                              {source.http_status ? <Chip size="small" variant="outlined" label={`HTTP ${source.http_status}`} /> : null}
                            </Stack>
                            <Link
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                              underline="hover"
                              sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
                            >
                              打开来源 <OpenInNewIcon fontSize="inherit" />
                            </Link>
                          </Box>

                          <Typography variant="body2" sx={{ fontWeight: 700 }}>
                            {source.page_title || source.source_domain || source.url}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {source.page_excerpt || source.verification_note || '暂无摘录'}
                          </Typography>
                          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                            {(source.matched_keywords || []).map((matchedKeyword) => (
                              <Chip key={matchedKeyword} size="small" variant="outlined" label={matchedKeyword} />
                            ))}
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            校验时间：{formatDateTime(source.fetched_at)}
                          </Typography>
                        </Stack>
                      </Paper>
                    ))}
                  </Stack>
                </Paper>
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
