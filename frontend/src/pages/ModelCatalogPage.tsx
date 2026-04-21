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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'

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
                color={item.supported ? 'success' : 'default'}
                label={item.supported ? '支持' : '不支持'}
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

function CodeSnippetSection({ title, language, code }: { title: string; language: string; code?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.25, borderRadius: 3, height: '100%' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
        {title}
      </Typography>
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
  const [expandedVerification, setExpandedVerification] = useState(false)

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

      const nextOverview = overviewResponse.data as CatalogOverview
      const nextEntries = (entriesResponse.data?.items || []) as CatalogEntry[]

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
    setExpandedVerification(false)

    try {
      const response = await apiClient.getModelCatalogEntry(modelKey)
      setSelectedEntry(response.data as CatalogEntry)
    } catch (e) {
      setDetailError(await extractApiErrorMessage(e, '加载模型详情失败'))
    } finally {
      setDetailLoading(false)
    }
  }

  const filteredEntries = entries.filter((entry) => {
    const matchKeyword =
      deferredKeyword === '' ||
      entry.name.toLowerCase().includes(deferredKeyword) ||
      entry.provider.toLowerCase().includes(deferredKeyword) ||
      entry.model_key.toLowerCase().includes(deferredKeyword)

    const matchCategory = selectedCategory === 'all' || entry.category === selectedCategory
    const matchProvider = selectedProvider === 'all' || entry.provider === selectedProvider
    const matchStatus = selectedStatus === 'all' || entry.verification_status === selectedStatus

    return matchKeyword && matchCategory && matchProvider && matchStatus
  })

  const visibleEntries = filteredEntries

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
                      {entry.name}
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
                          待手动验证 · 来源信息已清理
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
            {selectedEntry?.name || selectedModelKey || '模型详情'}
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
              <Tab label="Prompt与路由" />
              <Tab label="部署" />
              <Tab label="验证来源" />
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
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>推荐场景</Typography>
                      <Grid container spacing={2}>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>适用场景</Typography>
                          <Stack spacing={0.8}>
                            {(selectedEntry.recommended_scenarios.length > 0 ? selectedEntry.recommended_scenarios : ['暂无']).map((item) => (
                              <Typography key={item} variant="body2">• {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>项目模块适配</Typography>
                          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                            {(selectedEntry.identity_profile?.project_fit?.modules || selectedEntry.project_modules || []).map((item) => (
                              <Chip key={item} label={item} variant="outlined" size="small" />
                            ))}
                          </Stack>
                          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                            {(selectedEntry.identity_profile?.project_fit?.task_types || selectedEntry.project_task_labels || []).map((item) => (
                              <Chip key={item} label={item} size="small" color="success" variant="outlined" />
                            ))}
                          </Stack>
                        </Grid>
                      </Grid>
                    </Paper>

                    <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                      <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>约束与限制</Typography>
                      <Grid container spacing={2}>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>弱项与边界</Typography>
                          <Stack spacing={0.8}>
                            {(selectedEntry.identity_profile?.capability_quadrants?.weaknesses || selectedEntry.limitations || ['暂无']).map((item) => (
                              <Typography key={item} variant="body2" color="text.secondary">• {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                        <Grid item xs={12} md={6}>
                          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>已知限制</Typography>
                          <Stack spacing={0.8}>
                            {(selectedEntry.limitations.length > 0 ? selectedEntry.limitations : ['暂无']).map((item) => (
                              <Typography key={item} variant="body2" color="warning.main">⚠ {item}</Typography>
                            ))}
                          </Stack>
                        </Grid>
                      </Grid>
                      {selectedEntry.constraints_summary && (
                        <Box sx={{ mt: 2 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>技术参数约束</Typography>
                          <Grid container spacing={1}>
                            {selectedEntry.constraints_summary.duration && (
                              <Grid item xs={12} sm={4}>
                                <Typography variant="caption" color="text.secondary">视频时长</Typography>
                                <Typography variant="body2">
                                  {selectedEntry.constraints_summary.duration.min_seconds}s ~ {selectedEntry.constraints_summary.duration.max_seconds}s
                                </Typography>
                              </Grid>
                            )}
                            {selectedEntry.constraints_summary.max_prompt_length && (
                              <Grid item xs={12} sm={4}>
                                <Typography variant="caption" color="text.secondary">最大提示词长度</Typography>
                                <Typography variant="body2">{selectedEntry.constraints_summary.max_prompt_length} 字符</Typography>
                              </Grid>
                            )}
                            {selectedEntry.constraints_summary.pricing && (
                              <Grid item xs={12} sm={4}>
                                <Typography variant="caption" color="text.secondary">参考价格</Typography>
                                <Typography variant="body2">
                                  {selectedEntry.constraints_summary.pricing.currency} {selectedEntry.constraints_summary.pricing.price} / {selectedEntry.constraints_summary.pricing.unit}
                                </Typography>
                              </Grid>
                            )}
                          </Grid>
                        </Box>
                      )}
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
                            {selectedEntry.detailed_specs.voice_synthesis.voice_catalog && (
                              <Typography variant="body2">
                                音色总数：{selectedEntry.detailed_specs.voice_synthesis.voice_catalog.total_count || '-'}
                              </Typography>
                            )}
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
                    {selectedEntry.prompt_router_profile?.best_practice_tips && selectedEntry.prompt_router_profile.best_practice_tips.length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                        <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>最佳实践</Typography>
                        <Stack spacing={0.8}>
                          {selectedEntry.prompt_router_profile.best_practice_tips.map((tip, idx) => (
                            <Typography key={idx} variant="body2">• {tip}</Typography>
                          ))}
                        </Stack>
                      </Paper>
                    )}
                    {(selectedEntry.prompt_router_profile?.fallback_chain || []).length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                        <Typography variant="h6" sx={{ fontWeight: 700, mb: 1.5 }}>回退链路</Typography>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          {selectedEntry.prompt_router_profile?.fallback_chain?.map((item) => (
                            <Chip key={item} label={item} color="warning" variant="outlined" />
                          ))}
                        </Stack>
                      </Paper>
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

                {/* Tab 3: Prompt与路由 */}
                {detailTab === 3 && (
                  <Stack spacing={2.5}>
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
                          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>智能路由规则</Typography>
                          <Stack spacing={1.2}>
                            {(selectedEntry.prompt_router_profile?.router_rules || []).length > 0 ? (
                              selectedEntry.prompt_router_profile?.router_rules?.map((rule) => (
                                <Paper key={`${rule.when}-${rule.action}`} variant="outlined" sx={{ p: 1.4, borderRadius: 2 }}>
                                  <Typography variant="body2" sx={{ fontWeight: 700 }}>触发：{rule.when}</Typography>
                                  <Typography variant="body2" sx={{ mt: 0.6 }}>动作：{rule.action}</Typography>
                                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.6 }}>原因：{rule.reason}</Typography>
                                </Paper>
                              ))
                            ) : (
                              <Typography variant="body2" color="text.secondary">暂无显式路由规则。</Typography>
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
                  </Stack>
                )}

                {/* Tab 4: 部署 */}
                {detailTab === 4 && (
                  <Stack spacing={2.5}>
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
                          <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>本地部署与替代建议</Typography>
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
                  </Stack>
                )}

                {/* Tab 5: 验证来源 */}
                {detailTab === 5 && (
                  <Stack spacing={2.5}>
                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3 }}>
                      {selectedEntry.verification_status === 'pending' ? (
                        <Alert severity="info" variant="outlined">
                          来源验证信息已清理，当前状态为待手动验证。全量校验功能已移除，模型信息将通过手动方式维护。
                        </Alert>
                      ) : (
                        <Grid container spacing={2} alignItems="center">
                          <Grid item xs={12} sm={4}>
                            <Typography variant="caption" color="text.secondary">校验分数</Typography>
                            <Typography variant="h6">{(selectedEntry.verification_score * 100).toFixed(0)}%</Typography>
                          </Grid>
                          <Grid item xs={12} sm={4}>
                            <Typography variant="caption" color="text.secondary">来源验证</Typography>
                            <Typography variant="body2">{selectedEntry.verified_source_count} / {selectedEntry.total_source_count}</Typography>
                          </Grid>
                          <Grid item xs={12} sm={4}>
                            <Typography variant="caption" color="text.secondary">最近同步</Typography>
                            <Typography variant="body2">{formatDateTime(selectedEntry.last_synced_at)}</Typography>
                          </Grid>
                        </Grid>
                      )}
                      {selectedEntry.verification_status === 'partial' && (
                        <Alert severity="warning" variant="outlined" sx={{ mt: 1.5 }}>
                          官方来源未出现与项目内部 ID 完全一致的模型名，可能是项目内部别名或版本包装名。
                        </Alert>
                      )}
                    </Paper>

                    {(selectedEntry.sources || []).length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>联网验证来源</Typography>
                          <Button
                            size="small"
                            endIcon={expandedVerification ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                            onClick={() => setExpandedVerification(!expandedVerification)}
                          >
                            {expandedVerification ? '收起' : '展开全部'}
                          </Button>
                        </Stack>
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
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                                    <Chip size="small" label={source.source_type} variant="outlined" />
                                    <Chip
                                      size="small"
                                      color={source.verified ? 'success' : source.reachable ? 'warning' : 'error'}
                                      label={source.verified ? '强匹配' : source.reachable ? '弱匹配' : '不可达'}
                                    />
                                    {source.http_status ? <Chip size="small" variant="outlined" label={`HTTP ${source.http_status}`} /> : null}
                                  </Stack>
                                  <Link href={source.url} target="_blank" rel="noreferrer" underline="hover" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                                    打开来源 <OpenInNewIcon fontSize="inherit" />
                                  </Link>
                                </Box>

                                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                  {source.page_title || source.source_domain || source.url}
                                </Typography>
                                {expandedVerification && (
                                  <>
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
                                  </>
                                )}
                              </Stack>
                            </Paper>
                          ))}
                        </Stack>
                      </Paper>
                    )}

                    {selectedEntry.capability_provenance && selectedEntry.capability_provenance.length > 0 && (
                      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 3 }}>
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>能力溯源</Typography>
                        <Stack spacing={1.5}>
                          {selectedEntry.capability_provenance.map((cap) => (
                            <Paper key={cap.capability_name} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                                <Typography variant="body2" sx={{ fontWeight: 600 }}>{cap.capability_label}</Typography>
                                <Chip
                                  size="small"
                                  label={cap.confidence === 'high' ? '高置信' : cap.confidence === 'medium' ? '中置信' : '低置信'}
                                  color={cap.confidence === 'high' ? 'success' : cap.confidence === 'medium' ? 'warning' : 'error'}
                                />
                              </Stack>
                              <Typography variant="caption" color="text.secondary">{cap.description}</Typography>
                            </Paper>
                          ))}
                        </Stack>
                      </Paper>
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
