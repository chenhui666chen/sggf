/**
 * 提示词进化优化页面
 * 管理控制台内部页面，用于自动优化"降低 AI 痕迹"的提示词
 */
import { useState, useEffect, useCallback } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import {
  Box, Card, CardContent, Button, Typography, Alert,
  CircularProgress, LinearProgress, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Paper,
  IconButton, Tooltip, Divider, Slider, Grid, TextField,
  MenuItem, ToggleButton, ToggleButtonGroup,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StopIcon from '@mui/icons-material/Stop'
import RefreshIcon from '@mui/icons-material/Refresh'
import ScienceIcon from '@mui/icons-material/Science'
import HistoryIcon from '@mui/icons-material/History'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import VisibilityIcon from '@mui/icons-material/Visibility'
import ThumbUpIcon from '@mui/icons-material/ThumbUp'
import DeleteIcon from '@mui/icons-material/Delete'
import CleaningServicesIcon from '@mui/icons-material/CleaningServices'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import LeaderboardIcon from '@mui/icons-material/Leaderboard'
import StarIcon from '@mui/icons-material/Star'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import { useFormats } from '@/i18n'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { AI_TRACE_GENRES, AI_TRACE_GENRE_LABEL_KEYS, AI_TRACE_SAMPLE_GENRES, type AITraceGenreValue } from '../aiTraceGenre'
import { formatScore } from '@/utils/promptEvolutionScore'

interface EvolutionStatus {
  is_running: boolean
  evolution_id?: string
  status?: string
  current_iteration?: number
  max_iterations?: number
  best_score?: number
  queue_mode?: boolean
  current_genre?: string
  queue_current?: number
  queue_total?: number
  completed_genres?: string[]
  failed_genres?: string[]
}

interface PromptVersion {
  version_id: string
  iteration: number
  /** 真实适应度：确定AI段落占比（0-1，越低越好） */
  avg_ai_ratio?: number
  /** 诊断项：改写区间恒为 100，无比较价值 */
  avg_ai_score: number
  avg_score_reduction: number
  analysis: string
  created_at: string
}

interface EvolutionDetail {
  evolution_id: string
  status: string
  target_score: number
  current_iteration: number
  max_iterations: number
  approval_status: string
  approved_version_id?: string
  best_versions: PromptVersion[]
  started_at: string
  completed_at?: string
  error_message?: string
  genre?: string
}

interface PromptDetail {
  version_id: string
  iteration: number
  prompt_text: string
  avg_ai_score: number
  /** 真实适应度：确定AI段落占比（0-1，越低越好） */
  avg_ai_ratio?: number
  avg_score_reduction: number
  analysis: string
  evaluation_results: Array<{
    sample_id: string
    original_ai_score: number
    rewritten_ai_score: number
    score_reduction: number
    original_text: string
    rewritten_text: string
    success: boolean
    error?: string
    rewritten_multi_score?: {
      vocabulary_score?: number
      sentence_score?: number
      punctuation_score?: number
      emotion_score?: number
      dialogue_score?: number
      structure_score?: number
      writing_score?: number
      readability_score?: number
      fidelity_score?: number
      composite_score?: number
      readability_warnings?: string[]
    }
    llm_review?: {
      available: boolean
      semantic_fidelity?: ReviewDimension
      fact_consistency?: ReviewDimension
      information_completeness?: ReviewDimension
      readability?: ReviewDimension
      writing_naturalness?: ReviewDimension
      genre_consistency?: ReviewDimension
      over_rewrite_risk?: 'low' | 'medium' | 'high'
      over_rewrite_reason?: string
      confidence?: number
      hard_fail?: boolean
      hard_fail_reasons?: string[]
      error?: string
    }
  }>
  created_at: string
}

interface ReviewDimension {
  score: number
  reason: string
  issues: string[]
}

function getReviewDimensions(t: TFunction): Array<[string, keyof NonNullable<PromptDetail['evaluation_results'][number]['llm_review']>]> {
  return [
    [t('admin.promptEvolution.review.dimSemantic'), 'semantic_fidelity'],
    [t('admin.promptEvolution.review.dimFact'), 'fact_consistency'],
    [t('admin.promptEvolution.review.dimComplete'), 'information_completeness'],
    [t('admin.promptEvolution.review.dimReadable'), 'readability'],
    [t('admin.promptEvolution.review.dimNatural'), 'writing_naturalness'],
    [t('admin.promptEvolution.review.dimGenre'), 'genre_consistency'],
  ]
}
function QualityReviewSummary({ sample }: { sample: PromptDetail['evaluation_results'][number] }) {
  const { t } = useTranslation()
  const review = sample.llm_review
  const local = sample.rewritten_multi_score
  const reviewDimensions = getReviewDimensions(t)
  return (
    <Box sx={{ py: 1 }}>
      <Typography variant="subtitle2" gutterBottom>{t('admin.promptEvolution.review.title')}</Typography>
      {!review?.available ? (
        <Alert severity="warning">{review?.error || t('admin.promptEvolution.review.noData')}</Alert>
      ) : (
        <>
          <Grid container spacing={1}>
            {reviewDimensions.map(([label, key]) => {
              const dimension = review[key] as ReviewDimension | undefined
              return (
                <Grid item xs={12} sm={6} md={4} key={key}>
                  <Box sx={{ borderBottom: 1, borderColor: 'divider', pb: 1, minHeight: 76 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" fontWeight={600}>{label}</Typography>
                      <Chip size="small" label={dimension ? dimension.score.toFixed(0) : '-'} color={dimension && dimension.score >= 85 ? 'success' : dimension && dimension.score >= 70 ? 'warning' : 'error'} />
                    </Box>
                    <Typography variant="caption" color="text.secondary">{dimension?.reason || t('admin.promptEvolution.review.noComment')}</Typography>
                    {dimension?.issues?.map((issue, issueIndex) => (
                      <Typography key={issueIndex} variant="caption" color="error" display="block">{issue}</Typography>
                    ))}
                  </Box>
                </Grid>
              )
            })}
          </Grid>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
            <Chip size="small" label={t('admin.promptEvolution.review.overRewrite', { risk: review.over_rewrite_risk || '-' })} color={review.over_rewrite_risk === 'high' ? 'error' : review.over_rewrite_risk === 'medium' ? 'warning' : 'success'} />
            <Chip size="small" label={t('admin.promptEvolution.review.confidence', { value: review.confidence != null ? `${(review.confidence * 100).toFixed(0)}%` : '-' })} variant="outlined" />
            {review.hard_fail && <Chip size="small" label={review.hard_fail_reasons?.join('；') || t('admin.promptEvolution.review.hardFail')} color="error" />}
          </Box>
          {review.over_rewrite_reason && (
            <Typography variant="caption" color={review.over_rewrite_risk === 'high' ? 'error' : 'text.secondary'} display="block" sx={{ mt: 1 }}>
              {t('admin.promptEvolution.review.overRewriteReason', { reason: review.over_rewrite_reason })}
            </Typography>
          )}
        </>
      )}
      <Divider sx={{ my: 1.5 }} />
      <Typography variant="subtitle2" gutterBottom>{t('admin.promptEvolution.review.localRuleTitle')}</Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        <Chip size="small" label={t('admin.promptEvolution.review.vocabCost', { score: local?.vocabulary_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.sentenceCost', { score: local?.sentence_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.punctuationCost', { score: local?.punctuation_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.emotionCost', { score: local?.emotion_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.dialogueCost', { score: local?.dialogue_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.structureCost', { score: local?.structure_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.writingCost', { score: local?.writing_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.readabilityCost', { score: local?.readability_score?.toFixed(0) ?? '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.fidelityCost', { score: local?.fidelity_score != null ? (100 - local.fidelity_score).toFixed(0) : '-' })} variant="outlined" />
        <Chip size="small" label={t('admin.promptEvolution.review.compositeCost', { score: local?.composite_score?.toFixed(1) ?? '-' })} color="primary" variant="outlined" />
      </Box>
    </Box>
  )
}

interface ApprovedPrompt {
  version_id: string
  evolution_id: string
  prompt_text: string
  avg_ai_score: number
  /** 真实适应度：确定AI段落占比（0-1，越低越好） */
  avg_ai_ratio?: number
  avg_composite_score?: number
  avg_readability?: number
  avg_writing?: number
  approved_at: string
  status: string
}

interface ModelInfo {
  model_id: string
  name: string
  provider: string
  quality_score: number
  cost_per_1k_input: number
  cost_per_1k_output: number
  avg_latency: number
  is_active: boolean
  is_eliminated: boolean
  performance: {
    total_evaluations: number
    /** 确定AI段落占比（0-1，越低越好）；选型/淘汰主项 */
    avg_ai_ratio: number | null
    ai_ratio_stddev: number | null
    best_ai_ratio: number | null
    /** 诊断项：改写区间恒为 100，无比较价值 */
    avg_ai_score: number | null
    avg_improvement: number | null
    best_ai_score: number | null
    avg_latency: number | null
  } | null
}

interface ModelConfig {
  admin_selected_model: string | null
  auto_best_model: string | null
  active_model_id: string | null
  active_model_name: string | null
  active_model_provider: string | null
  updated_at: string
}

interface ModelCombination {
  prompt_version_id: string
  model_id: string
  model_name: string
  total_success: number
  distinct_sample_count: number
  avg_ai_score: number
  /** 确定AI段落占比（0-1，越低越好）；排序主项。旧记录可能缺省 */
  avg_ai_ratio?: number
  avg_fidelity_similarity: number
  composite_score: number
  evaluation_policy_version: string
  is_current: boolean
}

interface EvaluationMetrics {
  total: number
  success_rate: number
  fidelity_rejection_rate: number
  timeout_count: number
}

interface BackgroundOptimizationStatus {
  is_running: boolean
  task_type?: string
  genre?: string
  started_at?: number
  completed_at?: number
  cooldown_until?: number
  expected_models?: number
  completed_models?: number
  success_models?: number
  failed_models?: number
  daily_budget: number
  budget_used: number
  budget_remaining: number
}

export default function PromptEvolutionPage() {
  const { t } = useTranslation()
  const { formatDate, formatTime } = useFormats()
  const genreLabel = (genre: unknown) => {
    const value = (String(genre ?? '').trim() || '通用') as AITraceGenreValue
    return AI_TRACE_GENRE_LABEL_KEYS[value] ? t(AI_TRACE_GENRE_LABEL_KEYS[value]) : value
  }
  const [status, setStatus] = useState<EvolutionStatus | null>(null)
  const [histories, setHistories] = useState<any[]>([])
  const [selectedDetail, setSelectedDetail] = useState<EvolutionDetail | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
  
  const [targetScore, setTargetScore] = useState(25)
  const [maxIterations, setMaxIterations] = useState(6)
  const [samplesPerIteration, setSamplesPerIteration] = useState(4)
  const [runAllGenres, setRunAllGenres] = useState(false)
  
  const [startDialogOpen, setStartDialogOpen] = useState(false)
  const [detailDialogOpen, setDetailDialogOpen] = useState(false)
  const [promptDialogOpen, setPromptDialogOpen] = useState(false)
  const [approvedDialogOpen, setApprovedDialogOpen] = useState(false)
  const [approvedPrompts, setApprovedPrompts] = useState<ApprovedPrompt[]>([])
  const [expandedPromptId, setExpandedPromptId] = useState<string | null>(null)

  // 模型管理状态
  const [models, setModels] = useState<ModelInfo[]>([])
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [evaluating, setEvaluating] = useState(false)
  const [evalText, setEvalText] = useState('')
  const [evalDialogOpen, setEvalDialogOpen] = useState(false)
  const [evalResults, setEvalResults] = useState<any>(null)
  const [modelGenre, setModelGenre] = useState('通用')
  const [modelCombinations, setModelCombinations] = useState<ModelCombination[]>([])
  // 当前评测口径版本由后端下发；不要硬编码版本号——历史上写死 'ai-trace-v2'，
  // 后端升版后管理页长期把有效记录误判为"已过期"
  const [currentPolicyVersion, setCurrentPolicyVersion] = useState<string>('')
  const [evaluationMetrics, setEvaluationMetrics] = useState<EvaluationMetrics | null>(null)
  const [backgroundStatus, setBackgroundStatus] = useState<BackgroundOptimizationStatus | null>(null)

  // 测试样本状态
  const [samples, setSamples] = useState<any[]>([])
  const [sampleSummary, setSampleSummary] = useState<any>(null)
  const [addSampleOpen, setAddSampleOpen] = useState(false)
  const [newSampleText, setNewSampleText] = useState('')
  const [newSampleGenre, setNewSampleGenre] = useState('其他')
  const [generating, setGenerating] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/status')
      setStatus(res.data)
    } catch { /* 获取状态失败 */ }
  }, [])

  const fetchHistories = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/history')
      setHistories(res.data)
    } catch { /* 获取历史失败 */ }
  }, [])

  const fetchApprovedPrompts = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/approved')
      setApprovedPrompts(res.data.approved_prompts || [])
    } catch { /* 获取已批准提示词失败 */ }
  }, [])

  const fetchModels = useCallback(async () => {
    try {
      const [modelsRes, configRes, combinationsRes, metricsRes, backgroundRes] = await Promise.all([
        apiClient.client.get('/api/v1/ai-trace/available-models', { params: { genre: modelGenre } }),
        apiClient.client.get('/api/v1/ai-trace/model-config', { params: { genre: modelGenre } }),
        apiClient.client.get('/api/v1/ai-trace/model-combinations', { params: { genre: modelGenre } }),
        apiClient.client.get('/api/v1/ai-trace/evaluation-metrics', { params: { genre: modelGenre } }),
        apiClient.client.get('/api/v1/ai-trace/background-status'),
      ])
      setModels(modelsRes.data.models || [])
      setModelConfig(configRes.data)
      setModelCombinations(combinationsRes.data.combinations || [])
      setCurrentPolicyVersion(combinationsRes.data.current_policy_version || '')
      setEvaluationMetrics(metricsRes.data.metrics || null)
      setBackgroundStatus(backgroundRes.data)
    } catch { /* 获取模型数据失败 */ }
  }, [modelGenre])

  const fetchSamples = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/samples')
      setSamples(res.data.samples || [])
      setSampleSummary(res.data.summary || null)
    } catch { /* 获取样本失败 */ }
  }, [])

  const fetchBackgroundStatus = useCallback(async () => {
    try {
      const response = await apiClient.client.get('/api/v1/ai-trace/background-status')
      setBackgroundStatus(response.data)
    } catch { /* 获取统一后台状态失败 */ }
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchHistories()
    fetchModels()
    fetchSamples()
    fetchBackgroundStatus()
  }, [fetchStatus, fetchHistories, fetchModels, fetchSamples, fetchBackgroundStatus])

  useEffect(() => {
    const interval = setInterval(fetchBackgroundStatus, 3000)
    return () => clearInterval(interval)
  }, [fetchBackgroundStatus])

  useEffect(() => {
    if (!status?.is_running) return
    const interval = setInterval(fetchStatus, 5000)
    return () => clearInterval(interval)
  }, [status?.is_running, fetchStatus])

  const handleStart = async () => {
    setLoading(true)
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/start', {
        target_score: targetScore,
        max_iterations: maxIterations,
        samples_per_iteration: samplesPerIteration,
        genre: runAllGenres || modelGenre === '通用' ? null : modelGenre,
        run_all_genres: runAllGenres,
      })
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.taskStarted') })
      setStartDialogOpen(false)
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.startFailed')) })
    } finally { setLoading(false) }
  }

  const handleStop = async () => {
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/stop')
      setMessage({ type: 'info', text: t('admin.promptEvolution.snack.taskStopped') })
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.stopFailed')) })
    }
  }

  const handleViewDetail = async (evolutionId: string) => {
    setLoading(true)
    try {
      const res = await apiClient.client.get(`/api/v1/prompt-evolution/history/${evolutionId}`)
      setSelectedDetail(res.data)
      setDetailDialogOpen(true)
    } catch (e) {
      setMessage({ type: 'error', text: t('admin.promptEvolution.snack.detailFailed') })
    } finally { setLoading(false) }
  }

  const handleViewPrompt = async (evolutionId: string, versionId: string) => {
    setLoading(true)
    try {
      const res = await apiClient.client.get(`/api/v1/prompt-evolution/history/${evolutionId}/prompt/${versionId}`)
      setSelectedPrompt(res.data)
      setPromptDialogOpen(true)
    } catch (e) {
      setMessage({ type: 'error', text: t('admin.promptEvolution.snack.promptFetchFailed') })
    } finally { setLoading(false) }
  }

  const handleToggleApproval = async (evolutionId: string, versionId: string, isCurrentlyApproved: boolean) => {
    setLoading(true)
    try {
      if (isCurrentlyApproved) {
        await apiClient.client.post('/api/v1/prompt-evolution/revoke', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'info', text: t('admin.promptEvolution.snack.revoked') })
      } else {
        await apiClient.client.post('/api/v1/prompt-evolution/approve', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'success', text: t('admin.promptEvolution.snack.approved') })
      }
      await handleViewDetail(evolutionId)
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.operationFailed')) })
    } finally { setLoading(false) }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setMessage({ type: 'success', text: t('admin.promptEvolution.snack.copied') })
  }

  const handleDelete = async (evolutionId: string) => {
    if (!confirm(t('admin.promptEvolution.confirm.deleteHistory'))) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/history/${evolutionId}`)
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.deleteSuccess') })
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.deleteFailed')) })
    }
  }

  const handleCleanup = async () => {
    if (!confirm(t('admin.promptEvolution.confirm.cleanup'))) return
    try {
      const res = await apiClient.client.post('/api/v1/prompt-evolution/history/cleanup')
      setMessage({ type: 'success', text: res.data.message })
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.cleanupFailed')) })
    }
  }

  const handleResume = async (evolutionId: string) => {
    try {
      setMessage({ type: 'info', text: t('admin.promptEvolution.snack.resuming') })
      const res = await apiClient.client.post('/api/v1/prompt-evolution/resume', {
        evolution_id: evolutionId,
        additional_iterations: 5,
      })
      setMessage({ type: 'success', text: res.data.message || t('admin.promptEvolution.snack.resumed') })
      fetchStatus()
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.resumeFailed')) })
    }
  }

  const handleOpenApprovedDialog = async () => {
    await fetchApprovedPrompts()
    setApprovedDialogOpen(true)
  }

  const handleRemoveApproved = async (versionId: string) => {
    if (!confirm(t('admin.promptEvolution.confirm.removeApproved'))) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/approved/${versionId}`)
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.removedFromApproved') })
      fetchApprovedPrompts()
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.removeFailed')) })
    }
  }

  const handleSetActiveModel = async (modelId: string | null) => {
    try {
      await apiClient.client.post('/api/v1/ai-trace/model-config', { model_id: modelId })
      setMessage({ type: 'success', text: modelId ? t('admin.promptEvolution.snack.modelSet') : t('admin.promptEvolution.snack.modelAutoBest') })
      fetchModels()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.modelSetFailed')) })
    }
  }

  const handleEvaluateModels = async () => {
    if (!evalText.trim() || evalText.trim().length < 50) {
      setMessage({ type: 'error', text: t('admin.promptEvolution.snack.evalTextTooShort') })
      return
    }
    setEvaluating(true)
    setEvalResults(null)
    try {
      const res = await apiClient.client.post('/api/v1/ai-trace/evaluate-models', {
        text: evalText,
        intensity: 'medium',
        genre: modelGenre,
      }, { timeout: 300000 })
      setEvalResults(res.data)
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.evalDone', { success: res.data.total_models_success, tried: res.data.total_models_tried }) })
      fetchModels()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.evalFailed')) })
    } finally { setEvaluating(false) }
  }

  const handleAddSample = async () => {
    if (!newSampleText.trim() || newSampleText.trim().length < 50) {
      setMessage({ type: 'error', text: t('admin.promptEvolution.snack.sampleTextTooShort') })
      return
    }
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/samples', {
        text: newSampleText,
        genre: newSampleGenre,
      })
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.sampleAdded') })
      setAddSampleOpen(false)
      setNewSampleText('')
      setNewSampleGenre('其他')
      fetchSamples()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.sampleAddFailed')) })
    }
  }

  const handleDeleteSample = async (sampleId: string) => {
    if (!confirm(t('admin.promptEvolution.confirm.deleteSample'))) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/samples/${sampleId}`)
      setMessage({ type: 'success', text: t('admin.promptEvolution.snack.sampleDeleted') })
      fetchSamples()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.deleteFailed')) })
    }
  }

  const handleGenerateSamples = async () => {
    setGenerating(true)
    try {
      const res = await apiClient.client.post('/api/v1/prompt-evolution/samples/generate', {}, { timeout: 300000 })
      if (res.data.success) {
        setMessage({ type: 'success', text: res.data.message })
        fetchSamples()
      } else {
        setMessage({ type: 'error', text: res.data.error || t('admin.promptEvolution.snack.generateFailed') })
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, t('admin.promptEvolution.snack.generateFailed')) })
    } finally { setGenerating(false) }
  }

  const getScoreColor = (score: number) => score <= 30 ? 'success.main' : score <= 50 ? 'warning.main' : 'error.main'

  // 🔧 2026-10-08：版本层的真实适应度是 avg_ai_ratio（确定AI段落占比，0-1）。
  // avg_ai_score 在改写区间恒为 100，只能作为旧记录缺省时的回退显示。
  const ratioToScore = (ratio: number | undefined, fallbackScore: number) =>
    ratio != null ? ratio * 100 : fallbackScore
  const formatRatio = (ratio: number | undefined, fallbackScore: number) =>
    ratio != null ? `${(ratio * 100).toFixed(1)}%` : fallbackScore.toFixed(1)

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <ScienceIcon color="primary" sx={{ fontSize: 32 }} />
          <Typography variant="h5">{t('admin.promptEvolution.title')}</Typography>
        </Box>
        <Button startIcon={<RefreshIcon />} onClick={() => { fetchStatus(); fetchHistories() }}>{t('admin.common.refresh')}</Button>
      </Box>

      {message && <Alert severity={message.type} onClose={() => setMessage(null)} sx={{ mb: 2 }}>{message.text}</Alert>}

      <Card sx={{ mb: 3, bgcolor: 'info.dark', color: 'white' }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>{t('admin.promptEvolution.whatIsTitle')}</Typography>
          <Typography variant="body2">
            {t('admin.promptEvolution.whatIsBody')}
            <strong>{t('admin.promptEvolution.whatIsStrong')}</strong>
          </Typography>
        </CardContent>
      </Card>

      <Grid container spacing={3}>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom><PlayArrowIcon sx={{ mr: 1, verticalAlign: 'middle' }} />{t('admin.promptEvolution.controlPanel')}</Typography>
              <Divider sx={{ my: 2 }} />
              {status && (
                <Box sx={{ mb: 3 }}>
                  <Chip label={status.is_running ? t('admin.common.running') : t('admin.common.idle')} color={status.is_running ? 'primary' : 'default'} size="small" />
                  {status.is_running && status.max_iterations != null && (
                    <Box sx={{ mt: 2 }}>
                      {status.queue_mode && (
                        <Box sx={{ mb: 1.5 }}>
                          <Typography variant="body2" fontWeight={600}>
                            {t('admin.promptEvolution.currentGenre', { genre: status.current_genre || t('admin.promptEvolution.preparing') })}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            {t('admin.promptEvolution.genreProgress', { current: status.queue_current ?? 0, total: status.queue_total ?? 0 })}
                          </Typography>
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1 }}>
                            {status.completed_genres?.map((genre) => (
                              <Chip key={genre} size="small" color="success" label={t('admin.promptEvolution.genreCompleted', { genre })} />
                            ))}
                            {status.failed_genres?.map((genre) => (
                              <Chip key={genre} size="small" color="error" label={t('admin.promptEvolution.genreFailed', { genre })} />
                            ))}
                          </Box>
                        </Box>
                      )}
                      <Typography variant="body2">
                        {t('admin.promptEvolution.genreIteration', { current: status.current_iteration ?? 0, max: status.max_iterations })}
                      </Typography>
                      <LinearProgress
                        variant="determinate"
                        value={((status.current_iteration ?? 0) / (status.max_iterations || 10)) * 100}
                        sx={{ mt: 1 }}
                      />
                      {status.best_score != null && (
                        <Typography variant="body2" sx={{ mt: 1, color: getScoreColor(status.best_score) }}>
                          {t('admin.promptEvolution.bestScore', { score: status.best_score.toFixed(1) })}
                        </Typography>
                      )}
                    </Box>
                  )}
                </Box>
              )}
              <Divider sx={{ my: 2 }} />
              {status?.is_running ? (
                <Button variant="contained" color="error" fullWidth startIcon={<StopIcon />} onClick={handleStop}>{t('admin.promptEvolution.stopBtn')}</Button>
              ) : (
                <Button
                  variant="contained"
                  color="primary"
                  fullWidth
                  startIcon={<PlayArrowIcon />}
                  onClick={() => setStartDialogOpen(true)}
                  disabled={backgroundStatus?.is_running}
                >{t('admin.promptEvolution.startBtn')}</Button>
              )}
              <Button
                variant="outlined"
                color="success"
                fullWidth
                startIcon={<CheckCircleIcon />}
                onClick={handleOpenApprovedDialog}
                sx={{ mt: 2 }}
              >
                {t('admin.promptEvolution.approvedBtn')}
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h6"><HistoryIcon sx={{ mr: 1, verticalAlign: 'middle' }} />{t('admin.promptEvolution.historyTitle')}</Typography>
                {histories.length > 5 && (
                  <Button size="small" startIcon={<CleaningServicesIcon />} onClick={handleCleanup}>{t('admin.promptEvolution.autoCleanup')}</Button>
                )}
              </Box>
              <Divider sx={{ my: 2 }} />
              {histories.length === 0 ? (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>{t('admin.promptEvolution.historyEmpty')}</Typography>
              ) : (
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t('admin.common.id')}</TableCell>
                        <TableCell>{t('admin.common.genre')}</TableCell>
                        <TableCell>{t('admin.common.status')}</TableCell>
                        <TableCell>{t('admin.promptEvolution.colScore')}</TableCell>
                        <TableCell>{t('admin.promptEvolution.colAiScore')}</TableCell>
                        <TableCell>{t('admin.common.time')}</TableCell>
                        <TableCell>{t('admin.common.actions')}</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {histories.map((h) => (
                        <TableRow key={h.evolution_id}>
                          <TableCell><Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{h.evolution_id?.substring(0, 8)}...</Typography></TableCell>
                          <TableCell><Chip label={genreLabel(h.genre)} size="small" variant="outlined" /></TableCell>
                          <TableCell><Chip label={h.status} color={h.status === 'completed' ? 'success' : h.status === 'running' ? 'primary' : h.status === 'interrupted' ? 'warning' : 'error'} size="small" /></TableCell>
                          <TableCell>{h.best_score != null ? <Typography sx={{ color: getScoreColor(h.best_score), fontWeight: 'bold' }}>{h.best_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell>{h.ai_score != null ? <Typography sx={{ color: getScoreColor(h.ai_score), fontWeight: 'bold' }}>{h.ai_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell><Typography variant="caption">{formatDate(h.started_at)}</Typography></TableCell>
                          <TableCell>
                            <Tooltip title={t('admin.common.viewDetail')}><IconButton size="small" onClick={() => handleViewDetail(h.evolution_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                            {(h.status === 'interrupted' || h.status === 'failed') && (
                              <Tooltip title={t('admin.common.resume')}><IconButton size="small" color="primary" onClick={() => handleResume(h.evolution_id)}><RestartAltIcon fontSize="small" /></IconButton></Tooltip>
                            )}
                            <Tooltip title={t('admin.common.delete')}>
                              <span>
                                <IconButton size="small" color="error" onClick={() => handleDelete(h.evolution_id)} disabled={h.status === 'running'}><DeleteIcon fontSize="small" /></IconButton>
                              </span>
                            </Tooltip>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* 模型管理面板 */}
      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6"><SmartToyIcon sx={{ mr: 1, verticalAlign: 'middle' }} />{t('admin.promptEvolution.modelSection.title')}</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField
                select
                size="small"
                label={t('admin.promptEvolution.modelSection.genreLabel')}
                value={modelGenre}
                onChange={(event) => setModelGenre(event.target.value)}
                sx={{ minWidth: 100 }}
              >
                {AI_TRACE_GENRES.map((option) => (
                  <MenuItem key={option} value={option}>{genreLabel(option)}</MenuItem>
                ))}
              </TextField>
              {modelConfig?.admin_selected_model && (
                <Button size="small" variant="outlined" onClick={() => handleSetActiveModel(null)}>{t('admin.promptEvolution.modelSection.switchAutoBest')}</Button>
              )}
              <Button size="small" variant="contained" startIcon={<RocketLaunchIcon />} onClick={() => setEvalDialogOpen(true)} disabled={backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}>{t('admin.promptEvolution.modelSection.fullEval')}</Button>
              <Button size="small" startIcon={<RefreshIcon />} onClick={fetchModels}>{t('admin.common.refresh')}</Button>
            </Box>
          </Box>

          {modelConfig && (
            <Alert severity="info" sx={{ mb: 2 }}>
              {t('admin.promptEvolution.modelSection.activeModelPrefix')}<strong>{modelConfig.active_model_name || t('admin.promptEvolution.modelSection.defaultRoute')}</strong>
              {modelConfig.admin_selected_model ? t('admin.promptEvolution.modelSection.adminSelected') : modelConfig.auto_best_model ? t('admin.promptEvolution.modelSection.autoBest') : ''}
              {modelConfig.active_model_provider && ` · ${modelConfig.active_model_provider}`}
            </Alert>
          )}

          {evaluationMetrics && (
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
              <Chip label={t('admin.promptEvolution.modelSection.evalCount', { count: evaluationMetrics.total })} size="small" />
              <Chip label={t('admin.promptEvolution.modelSection.successRate', { rate: (evaluationMetrics.success_rate * 100).toFixed(1) })} size="small" color="success" variant="outlined" />
              <Chip label={t('admin.promptEvolution.modelSection.fidelityReject', { rate: (evaluationMetrics.fidelity_rejection_rate * 100).toFixed(1) })} size="small" color="warning" variant="outlined" />
              <Chip label={t('admin.promptEvolution.modelSection.timeoutCount', { count: evaluationMetrics.timeout_count })} size="small" color="error" variant="outlined" />
            </Box>
          )}

          {backgroundStatus && (
            <Alert severity={backgroundStatus.is_running ? 'warning' : 'info'} sx={{ mb: 2 }}>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                <strong>{backgroundStatus.is_running ? t('admin.promptEvolution.modelSection.bgRunning') : t('admin.promptEvolution.modelSection.bgIdle')}</strong>
                {backgroundStatus.task_type && <Chip size="small" label={t('admin.promptEvolution.modelSection.bgType', { type: backgroundStatus.task_type })} />}
                {backgroundStatus.genre && <Chip size="small" label={t('admin.promptEvolution.modelSection.bgGenre', { genre: backgroundStatus.genre })} />}
                {backgroundStatus.started_at && <Chip size="small" label={t('admin.promptEvolution.modelSection.bgStarted', { time: formatTime(backgroundStatus.started_at * 1000) })} />}
                <Chip size="small" label={t('admin.promptEvolution.modelSection.budget', { used: backgroundStatus.budget_used, total: backgroundStatus.daily_budget })} />
                <Chip size="small" label={t('admin.promptEvolution.modelSection.remaining', { count: backgroundStatus.budget_remaining })} />
                {(backgroundStatus.expected_models || 0) > 0 && (
                  <Chip size="small" label={t('admin.promptEvolution.modelSection.bgModels', { done: backgroundStatus.completed_models || 0, expected: backgroundStatus.expected_models })} />
                )}
                {(backgroundStatus.success_models || 0) > 0 && <Chip size="small" color="success" label={t('admin.promptEvolution.modelSection.bgSuccess', { count: backgroundStatus.success_models })} />}
                {(backgroundStatus.failed_models || 0) > 0 && <Chip size="small" color="error" label={t('admin.promptEvolution.modelSection.bgFailed', { count: backgroundStatus.failed_models })} />}
                {!backgroundStatus.is_running && (backgroundStatus.cooldown_until || 0) * 1000 > Date.now() && (
                  <Chip size="small" color="warning" label={t('admin.promptEvolution.modelSection.cooldownUntil', { time: formatTime((backgroundStatus.cooldown_until || 0) * 1000) })} />
                )}
              </Box>
            </Alert>
          )}

          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.promptEvolution.modelSection.colModel')}</TableCell>
                  <TableCell>{t('admin.promptEvolution.modelSection.colProvider')}</TableCell>
                  <TableCell align="center">{t('admin.promptEvolution.modelSection.colEvalCount')}</TableCell>
                  <TableCell align="center">{t('admin.promptEvolution.modelSection.colAvgAi')}</TableCell>
                  <TableCell align="center">{t('admin.promptEvolution.modelSection.colAvgDrop')}</TableCell>
                  <TableCell align="center">{t('admin.promptEvolution.modelSection.colBestAi')}</TableCell>
                  <TableCell align="center">{t('admin.promptEvolution.modelSection.colAvgLatency')}</TableCell>
                  <TableCell align="center">{t('admin.common.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {[...models].sort((a, b) => {
                  // 🔧 排序主项为确定AI段落占比（越低越好）。avg_ai_score 在改写区间
                  // 恒为 100，按它排序等价于按常数排序。
                  const sa = a.performance?.avg_ai_ratio ?? 999
                  const sb = b.performance?.avg_ai_ratio ?? 999
                  return sa - sb
                }).map((m) => (
                  <TableRow key={m.model_id} sx={{
                    bgcolor: m.is_active ? 'action.selected' : m.is_eliminated ? 'action.disabledBackground' : 'inherit',
                    opacity: m.is_eliminated ? 0.6 : 1,
                  }}>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        {m.is_active && <StarIcon sx={{ fontSize: 16, color: 'warning.main' }} />}
                        <Typography variant="body2" fontWeight={m.is_active ? 'bold' : 'normal'}>{m.name}</Typography>
                        {m.is_eliminated && <Chip label={t('admin.promptEvolution.modelSection.eliminated')} size="small" color="default" sx={{ ml: 0.5 }} />}
                      </Box>
                    </TableCell>
                    <TableCell><Chip label={m.provider} size="small" variant="outlined" /></TableCell>
                    <TableCell align="center">{m.performance?.total_evaluations ?? 0}</TableCell>
                    <TableCell align="center">
                      {m.performance?.avg_ai_ratio != null ? (
                        <Typography variant="body2" sx={{ color: getScoreColor(m.performance.avg_ai_ratio * 100), fontWeight: 'bold' }}>
                          {(m.performance.avg_ai_ratio * 100).toFixed(1)}%
                        </Typography>
                      ) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {m.performance?.avg_improvement != null ? (
                        <Typography variant="body2" sx={{ color: m.performance.avg_improvement > 0 ? 'success.main' : 'text.secondary' }}>
                          {m.performance.avg_improvement > 0 ? '+' : ''}{m.performance.avg_improvement.toFixed(1)}
                        </Typography>
                      ) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {m.performance?.best_ai_ratio != null && m.performance.best_ai_ratio < 1 ? (
                        <Typography variant="body2" sx={{ color: getScoreColor(m.performance.best_ai_ratio * 100) }}>
                          {(m.performance.best_ai_ratio * 100).toFixed(1)}%
                        </Typography>
                      ) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {m.performance?.avg_latency != null ? `${m.performance.avg_latency.toFixed(1)}s` : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {!m.is_active && (
                        <Tooltip title={t('admin.promptEvolution.modelSection.setActive')}>
                          <IconButton size="small" color="primary" onClick={() => handleSetActiveModel(m.model_id)}>
                            <LeaderboardIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>{t('admin.promptEvolution.combo.title')}</Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>{t('admin.promptEvolution.combo.colPromptVer')}</TableCell><TableCell>{t('admin.promptEvolution.combo.colModel')}</TableCell>
                <TableCell align="right">{t('admin.promptEvolution.combo.colSuccessSample')}</TableCell><TableCell align="right">{t('admin.promptEvolution.combo.colAi')}</TableCell>
                <TableCell align="right">{t('admin.promptEvolution.combo.colFidelity')}</TableCell><TableCell align="right">{t('admin.promptEvolution.combo.colComposite')}</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {modelCombinations.slice(0, 20).map((item) => {
                  const qualification = item.is_current
                    ? t('admin.promptEvolution.combo.qualCurrent')
                    : !!currentPolicyVersion && item.evaluation_policy_version !== currentPolicyVersion
                    ? t('admin.promptEvolution.combo.qualExpired')
                    : item.total_success < 3
                      ? t('admin.promptEvolution.combo.qualNoData')
                      : item.distinct_sample_count < 3
                        ? t('admin.promptEvolution.combo.qualNoSample')
                        : item.avg_fidelity_similarity < 70
                          ? t('admin.promptEvolution.combo.qualFidelityFail')
                          : t('admin.promptEvolution.combo.qualEligible')
                  return (
                  <TableRow key={`${item.prompt_version_id}:${item.model_id}`}>
                    <TableCell>{item.prompt_version_id}</TableCell>
                    <TableCell>{item.model_name}</TableCell>
                    <TableCell align="right">{item.total_success}/{item.distinct_sample_count}</TableCell>
                    {/* 展示排序主项「确定AI段落占比」（越低越好）；avg_ai_score 在改写区间恒为 100，无信息量 */}
                    <TableCell align="right">{`${((item.avg_ai_ratio ?? 1) * 100).toFixed(1)}%`}</TableCell>
                    <TableCell align="right">{item.avg_fidelity_similarity.toFixed(1)}%</TableCell>
                    <TableCell align="right">
                      {item.composite_score.toFixed(1)}
                      <Chip size="small" sx={{ ml: 1 }} color={qualification === t('admin.promptEvolution.combo.qualEligible') || qualification === t('admin.promptEvolution.combo.qualCurrent') ? 'success' : 'default'} label={qualification} />
                    </TableCell>
                  </TableRow>
                  )
                })}
                {modelCombinations.length === 0 && <TableRow><TableCell colSpan={6} align="center">{t('admin.promptEvolution.combo.empty')}</TableCell></TableRow>}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* 测试样本管理面板 */}
      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="h6">{t('admin.promptEvolution.samples.title')}</Typography>
              {sampleSummary && (
                <Chip label={t('admin.promptEvolution.samples.totalCount', { count: sampleSummary.total_samples })} size="small" variant="outlined" />
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" variant="contained" onClick={() => setAddSampleOpen(true)}>{t('admin.promptEvolution.samples.add')}</Button>
              <Button size="small" variant="outlined" onClick={handleGenerateSamples} disabled={generating}>
                {generating ? <CircularProgress size={16} sx={{ mr: 0.5 }} /> : null}
                {t('admin.promptEvolution.samples.autoGenerate')}
              </Button>
              <Button size="small" startIcon={<RefreshIcon />} onClick={fetchSamples}>{t('admin.common.refresh')}</Button>
            </Box>
          </Box>

          {sampleSummary?.source_distribution && (
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              {Object.entries(sampleSummary.source_distribution as Record<string, number>).map(([src, cnt]) => (
                <Chip
                  key={src}
                  label={t('admin.promptEvolution.samples.sourceDist', { label: src === 'custom' ? t('admin.promptEvolution.samples.custom') : src === 'auto' ? t('admin.promptEvolution.samples.autoGen') : t('admin.promptEvolution.samples.builtin'), count: cnt })}
                  size="small"
                  color={src === 'custom' ? 'primary' : src === 'auto' ? 'secondary' : 'default'}
                  variant="outlined"
                />
              ))}
            </Box>
          )}

          <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 320 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.common.id')}</TableCell>
                  <TableCell>{t('admin.common.genre')}</TableCell>
                  <TableCell>{t('admin.promptEvolution.samples.colSource')}</TableCell>
                  <TableCell>{t('admin.promptEvolution.samples.colPreview')}</TableCell>
                  <TableCell align="center">{t('admin.common.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {samples.map((s) => (
                  <TableRow key={s.sample_id}>
                    <TableCell><Typography variant="caption" fontFamily="monospace">{s.sample_id.substring(0, 12)}</Typography></TableCell>
                    <TableCell><Chip label={s.genre} size="small" /></TableCell>
                    <TableCell>
                      <Chip
                        label={s.source === 'custom' ? t('admin.promptEvolution.samples.custom') : s.source === 'auto' ? t('admin.promptEvolution.samples.auto') : t('admin.promptEvolution.samples.builtin')}
                        size="small"
                        color={s.source === 'custom' ? 'primary' : s.source === 'auto' ? 'secondary' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.text}
                      </Typography>
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title={t('admin.common.delete')}>
                        <IconButton size="small" color="error" onClick={() => handleDeleteSample(s.sample_id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* 添加样本对话框 */}
      <Dialog open={addSampleOpen} onClose={() => setAddSampleOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.samples.addDialogTitle')}</DialogTitle>
        <DialogContent>
          <TextField
            select
            fullWidth
            label={t('admin.common.genre')}
            value={newSampleGenre}
            onChange={(e) => setNewSampleGenre(e.target.value)}
            sx={{ mt: 2, mb: 2 }}
            SelectProps={{ native: true }}
          >
            {AI_TRACE_SAMPLE_GENRES.map((g) => (
              <option key={g} value={g}>{genreLabel(g)}</option>
            ))}
          </TextField>
          <TextField
            fullWidth
            multiline
            rows={5}
            label={t('admin.promptEvolution.samples.sampleTextLabel')}
            value={newSampleText}
            onChange={(e) => setNewSampleText(e.target.value)}
            helperText={t('admin.promptEvolution.samples.charCount', { count: newSampleText.length })}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddSampleOpen(false)}>{t('action.cancel')}</Button>
          <Button variant="contained" onClick={handleAddSample} disabled={newSampleText.trim().length < 50}>{t('admin.common.add')}</Button>
        </DialogActions>
      </Dialog>

      {/* 启动配置对话框 */}
      <Dialog open={startDialogOpen} onClose={() => setStartDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.config.title')}</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography gutterBottom>{t('admin.promptEvolution.config.scope')}</Typography>
            <ToggleButtonGroup
              exclusive
              fullWidth
              size="small"
              value={runAllGenres ? 'all' : 'single'}
              onChange={(_, value) => value && setRunAllGenres(value === 'all')}
              sx={{ mb: 2 }}
            >
              <ToggleButton value="single">{t('admin.promptEvolution.config.currentOnly')}</ToggleButton>
              <ToggleButton value="all">{t('admin.promptEvolution.config.allGenres')}</ToggleButton>
            </ToggleButtonGroup>
            {runAllGenres ? (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: 2 }}>
                {AI_TRACE_GENRES.filter((genre) => genre !== '通用').map((genre) => (
                  <Chip key={genre} label={genreLabel(genre)} size="small" variant="outlined" />
                ))}
              </Box>
            ) : (
              <Alert severity="info" sx={{ mb: 2 }}>
                {t('admin.promptEvolution.config.currentSelection', { genre: modelGenre === '通用' ? t('admin.promptEvolution.config.generalAutoDetect') : genreLabel(modelGenre) })}
              </Alert>
            )}
            <Typography gutterBottom>{t('admin.promptEvolution.config.targetAiRate', { score: targetScore })}</Typography>
            <Slider value={targetScore} onChange={(_, v) => setTargetScore(v as number)} min={0} max={50} step={5} marks valueLabelDisplay="auto" />
            <Typography gutterBottom>{t('admin.promptEvolution.config.maxIterations', { count: maxIterations })}</Typography>
            <Slider value={maxIterations} onChange={(_, v) => setMaxIterations(v as number)} min={3} max={20} step={1} marks valueLabelDisplay="auto" />
            <Typography gutterBottom sx={{ mt: 2 }}>{t('admin.promptEvolution.config.samplesPerIteration', { count: samplesPerIteration })}</Typography>
            <Slider value={samplesPerIteration} onChange={(_, v) => setSamplesPerIteration(v as number)} min={1} max={5} step={1} marks valueLabelDisplay="auto" />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStartDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button variant="contained" onClick={handleStart} disabled={loading}>{loading ? <CircularProgress size={20} /> : t('admin.common.start')}</Button>
        </DialogActions>
      </Dialog>

      {/* 详情对话框 */}
      <Dialog open={detailDialogOpen} onClose={() => setDetailDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.detail.title')}</DialogTitle>
        <DialogContent>
          {selectedDetail && (
            <Box>
              <Typography variant="subtitle2" color="text.secondary">{t('admin.promptEvolution.detail.meta', { genre: genreLabel(selectedDetail.genre), status: selectedDetail.status, current: selectedDetail.current_iteration, max: selectedDetail.max_iterations })}</Typography>
              <Divider sx={{ my: 2 }} />
              <Typography variant="h6" gutterBottom>{t('admin.promptEvolution.detail.bestVersions')}</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('admin.promptEvolution.detail.colIter')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.detail.colAiScore')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.detail.colDrop')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.detail.colAnalysis')}</TableCell>
                      <TableCell>{t('admin.common.actions')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedDetail.best_versions.map((v) => {
                      const isApproved = selectedDetail.approved_version_id === v.version_id
                      return (
                        <TableRow key={v.version_id} sx={{ bgcolor: isApproved ? 'success.light' : 'inherit' }}>
                          <TableCell>#{v.iteration}</TableCell>
                          <TableCell><Typography sx={{ color: getScoreColor(ratioToScore(v.avg_ai_ratio, v.avg_ai_score)), fontWeight: 'bold' }}>{formatRatio(v.avg_ai_ratio, v.avg_ai_score)}</Typography></TableCell>
                          <TableCell>{v.avg_score_reduction.toFixed(1)}</TableCell>
                          <TableCell><Typography variant="caption" sx={{ maxWidth: 200, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.analysis}</Typography></TableCell>
                          <TableCell>
                            <Tooltip title={t('admin.promptEvolution.detail.viewFullPrompt')}><IconButton size="small" onClick={() => handleViewPrompt(selectedDetail.evolution_id, v.version_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                            <Tooltip title={isApproved ? t('admin.promptEvolution.detail.revokeApproval') : t('admin.promptEvolution.detail.approveVersion')}>
                              <IconButton
                                size="small"
                                onClick={() => handleToggleApproval(selectedDetail.evolution_id, v.version_id, isApproved)}
                                sx={{
                                  color: isApproved ? 'success.main' : 'grey.400',
                                  '&:hover': { color: isApproved ? 'warning.main' : 'success.main' }
                                }}
                              >
                                <ThumbUpIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setDetailDialogOpen(false)}>{t('action.close')}</Button></DialogActions>
      </Dialog>

      {/* 提示词详情对话框 */}
      <Dialog open={promptDialogOpen} onClose={() => setPromptDialogOpen(false)} maxWidth="lg" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.prompt.title')}</DialogTitle>
        <DialogContent dividers>
          {selectedPrompt && (
            <Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                  <Chip label={t('admin.promptEvolution.prompt.iterBadge', { iteration: selectedPrompt.iteration })} sx={{ mr: 1 }} />
                  <Chip label={t('admin.promptEvolution.prompt.aiScoreBadge', { score: formatRatio(selectedPrompt.avg_ai_ratio, selectedPrompt.avg_ai_score) })} color={ratioToScore(selectedPrompt.avg_ai_ratio, selectedPrompt.avg_ai_score) <= 30 ? 'success' : ratioToScore(selectedPrompt.avg_ai_ratio, selectedPrompt.avg_ai_score) <= 50 ? 'warning' : 'error'} />
                </Box>
                <Button startIcon={<ContentCopyIcon />} onClick={() => copyToClipboard(selectedPrompt.prompt_text)} size="small">{t('admin.common.copy')}</Button>
              </Box>
              <Alert severity="info" sx={{ mb: 2 }}>
                <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{selectedPrompt.prompt_text}</Typography>
              </Alert>
              <Typography variant="h6" gutterBottom>{t('admin.promptEvolution.prompt.analysisTitle')}</Typography>
              <Alert severity={selectedPrompt.avg_score_reduction > 0 ? 'success' : 'warning'} sx={{ mb: 2 }}>
                {selectedPrompt.analysis}
              </Alert>
              <Typography variant="h6" gutterBottom>{t('admin.promptEvolution.prompt.evalSamples', { count: selectedPrompt.evaluation_results.length })}</Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('admin.promptEvolution.prompt.colSampleId')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.prompt.colOrigScore')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.prompt.colRewrittenScore')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.prompt.colDrop')}</TableCell>
                      <TableCell>{t('admin.promptEvolution.prompt.colQuality')}</TableCell>
                      <TableCell>{t('admin.common.status')}</TableCell>
                      <TableCell>{t('admin.common.actions')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedPrompt.evaluation_results.map((sample, idx) => (
                      <TableRow key={sample.sample_id || idx}>
                        <TableCell><Typography variant="caption">{sample.sample_id?.substring(0, 8)}...</Typography></TableCell>
                        <TableCell>{sample.original_ai_score != null ? <Typography sx={{ color: getScoreColor(sample.original_ai_score), fontWeight: 'bold' }}>{formatScore(sample.original_ai_score)}</Typography> : '-'}</TableCell>
                        <TableCell>{sample.rewritten_ai_score != null ? <Typography sx={{ color: getScoreColor(sample.rewritten_ai_score), fontWeight: 'bold' }}>{formatScore(sample.rewritten_ai_score)}</Typography> : '-'}</TableCell>
                        <TableCell><Typography sx={{ color: sample.score_reduction > 0 ? 'success.main' : 'error.main', fontWeight: 'bold' }}>{sample.score_reduction.toFixed(1)}</Typography></TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', minWidth: 132 }}>
                            <Chip size="small" label={t('admin.promptEvolution.prompt.semanticScore', { score: sample.llm_review?.semantic_fidelity?.score?.toFixed(0) ?? '-' })} variant="outlined" />
                            <Chip size="small" label={t('admin.promptEvolution.prompt.readabilityScore', { score: sample.llm_review?.readability?.score?.toFixed(0) ?? '-' })} variant="outlined" />
                          </Box>
                        </TableCell>
                        <TableCell><Chip label={sample.success ? t('admin.common.success') : t('admin.common.fail')} color={sample.success ? 'success' : 'error'} size="small" /></TableCell>
                        <TableCell>
                          <Tooltip title={t('admin.promptEvolution.prompt.viewOriginal')}><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `original-${idx}` ? null : `original-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                          <Tooltip title={t('admin.promptEvolution.prompt.viewRewritten')}><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `rewritten-${idx}` ? null : `rewritten-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                          <Tooltip title={t('admin.promptEvolution.prompt.viewAllQuality')}><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `quality-${idx}` ? null : `quality-${idx}`) }}><LeaderboardIcon fontSize="small" /></IconButton></Tooltip>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              {selectedPrompt.evaluation_results.map((sample, idx) => (
                <Box key={`original-${idx}`} sx={{ mt: 2 }}>
                  {expandedPromptId === `original-${idx}` && (
                    <Alert severity="info" sx={{ mt: 1 }}>
                      <Typography variant="subtitle2" gutterBottom>{t('admin.promptEvolution.prompt.originalLabel')}</Typography>
                      <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{sample.original_text}</Typography>
                    </Alert>
                  )}
                  {expandedPromptId === `rewritten-${idx}` && (
                    <Alert severity="success" sx={{ mt: 1 }}>
                      <Typography variant="subtitle2" gutterBottom>{t('admin.promptEvolution.prompt.rewrittenLabel')}</Typography>
                      <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{sample.rewritten_text}</Typography>
                    </Alert>
                  )}
                  {expandedPromptId === `quality-${idx}` && (
                    <QualityReviewSummary sample={sample} />
                  )}
                </Box>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setPromptDialogOpen(false)}>{t('action.close')}</Button></DialogActions>
      </Dialog>

      {/* 已批准提示词对话框 */}
      <Dialog open={approvedDialogOpen} onClose={() => setApprovedDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.approved.title')}</DialogTitle>
        <DialogContent>
          {approvedPrompts.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>{t('admin.promptEvolution.approved.empty')}</Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('admin.common.id')}</TableCell>
                    <TableCell>{t('admin.promptEvolution.detail.colAiScore')}</TableCell>
                    <TableCell>{t('admin.promptEvolution.approved.colApprovedAt')}</TableCell>
                    <TableCell>{t('admin.common.actions')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {approvedPrompts.map((p) => (
                    <TableRow key={p.version_id}>
                      <TableCell><Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{p.version_id?.substring(0, 8)}...</Typography></TableCell>
                      <TableCell><Typography sx={{ color: getScoreColor(ratioToScore(p.avg_ai_ratio, p.avg_ai_score)), fontWeight: 'bold' }}>{formatRatio(p.avg_ai_ratio, p.avg_ai_score)}</Typography></TableCell>
                      <TableCell><Typography variant="caption">{formatDate(p.approved_at)}</Typography></TableCell>
                      <TableCell>
                        <Tooltip title={t('admin.common.view')}><IconButton size="small" onClick={() => handleViewPrompt(p.evolution_id, p.version_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                        <Tooltip title={t('admin.common.remove')}>
                          <IconButton size="small" color="error" onClick={() => handleRemoveApproved(p.version_id)}><DeleteIcon fontSize="small" /></IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setApprovedDialogOpen(false)}>{t('action.close')}</Button></DialogActions>
      </Dialog>

      {/* 全模型评测对话框 */}
      <Dialog open={evalDialogOpen} onClose={() => { if (!evaluating) setEvalDialogOpen(false) }} maxWidth="md" fullWidth>
        <DialogTitle>{t('admin.promptEvolution.eval.title')}</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('admin.promptEvolution.eval.hint')}
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={4}
            label={t('admin.promptEvolution.eval.textLabel')}
            value={evalText}
            onChange={(e) => setEvalText(e.target.value)}
            disabled={evaluating}
            sx={{ mb: 2 }}
          />
          {evaluating && (
            <Box sx={{ mb: 2 }}>
              <LinearProgress />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                {t('admin.promptEvolution.eval.progress')}
              </Typography>
            </Box>
          )}
          {evalResults && (
            <Box>
              <Alert severity="success" sx={{ mb: 2 }}>
                {t('admin.promptEvolution.eval.done', { original: evalResults.original_ai_score, success: evalResults.total_models_success, tried: evalResults.total_models_tried, seconds: evalResults.total_time_seconds?.toFixed(1) })}
              </Alert>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t('admin.promptEvolution.eval.colRank')}</TableCell>
                      <TableCell>{t('admin.common.model')}</TableCell>
                      <TableCell align="center">{t('admin.promptEvolution.eval.colAi')}</TableCell>
                      <TableCell align="center">{t('admin.promptEvolution.detail.colDrop')}</TableCell>
                      <TableCell align="center">{t('admin.promptEvolution.eval.colLatency')}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {evalResults.results?.map((r: any, idx: number) => (
                      <TableRow key={r.model_id} sx={{ bgcolor: idx === 0 ? 'success.light' : 'inherit' }}>
                        <TableCell>{idx + 1}</TableCell>
                        <TableCell>{r.model_name}</TableCell>
                        <TableCell align="center">
                          <Typography sx={{ color: getScoreColor(r.ai_score), fontWeight: 'bold' }}>{r.ai_score}</Typography>
                        </TableCell>
                        <TableCell align="center">
                          <Typography sx={{ color: r.improvement > 0 ? 'success.main' : 'error.main' }}>
                            {r.improvement > 0 ? '+' : ''}{r.improvement}
                          </Typography>
                        </TableCell>
                        <TableCell align="center">{r.latency_seconds}s</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEvalDialogOpen(false); setEvalResults(null) }} disabled={evaluating}>{t('action.close')}</Button>
          <Button variant="contained" onClick={handleEvaluateModels} disabled={evaluating || !evalText.trim() || backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}>
            {evaluating ? <CircularProgress size={20} /> : t('admin.promptEvolution.eval.startBtn')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
