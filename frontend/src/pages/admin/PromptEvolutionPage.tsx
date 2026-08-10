/**
 * 提示词进化优化页面
 * 管理控制台内部页面，用于自动优化"降低 AI 痕迹"的提示词
 */
import { useState, useEffect, useCallback } from 'react'
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
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { AI_TRACE_GENRES } from '../aiTraceGenre'
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

const REVIEW_DIMENSIONS: Array<[string, keyof NonNullable<PromptDetail['evaluation_results'][number]['llm_review']>]> = [
  ['语义保真', 'semantic_fidelity'],
  ['事实一致', 'fact_consistency'],
  ['信息完整', 'information_completeness'],
  ['可读性', 'readability'],
  ['文笔自然', 'writing_naturalness'],
  ['题材一致', 'genre_consistency'],
]

function QualityReviewSummary({ sample }: { sample: PromptDetail['evaluation_results'][number] }) {
  const review = sample.llm_review
  const local = sample.rewritten_multi_score
  return (
    <Box sx={{ py: 1 }}>
      <Typography variant="subtitle2" gutterBottom>大模型智能评审</Typography>
      {!review?.available ? (
        <Alert severity="warning">{review?.error || '该历史结果没有智能评审数据'}</Alert>
      ) : (
        <>
          <Grid container spacing={1}>
            {REVIEW_DIMENSIONS.map(([label, key]) => {
              const dimension = review[key] as ReviewDimension | undefined
              return (
                <Grid item xs={12} sm={6} md={4} key={key}>
                  <Box sx={{ borderBottom: 1, borderColor: 'divider', pb: 1, minHeight: 76 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="body2" fontWeight={600}>{label}</Typography>
                      <Chip size="small" label={dimension ? dimension.score.toFixed(0) : '-'} color={dimension && dimension.score >= 85 ? 'success' : dimension && dimension.score >= 70 ? 'warning' : 'error'} />
                    </Box>
                    <Typography variant="caption" color="text.secondary">{dimension?.reason || '无评语'}</Typography>
                    {dimension?.issues?.map((issue, issueIndex) => (
                      <Typography key={issueIndex} variant="caption" color="error" display="block">{issue}</Typography>
                    ))}
                  </Box>
                </Grid>
              )
            })}
          </Grid>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
            <Chip size="small" label={`过度改写：${review.over_rewrite_risk || '-'}`} color={review.over_rewrite_risk === 'high' ? 'error' : review.over_rewrite_risk === 'medium' ? 'warning' : 'success'} />
            <Chip size="small" label={`置信度：${review.confidence != null ? `${(review.confidence * 100).toFixed(0)}%` : '-'}`} variant="outlined" />
            {review.hard_fail && <Chip size="small" label={review.hard_fail_reasons?.join('；') || '智能评审未通过'} color="error" />}
          </Box>
          {review.over_rewrite_reason && (
            <Typography variant="caption" color={review.over_rewrite_risk === 'high' ? 'error' : 'text.secondary'} display="block" sx={{ mt: 1 }}>
              过度改写判断：{review.over_rewrite_reason}
            </Typography>
          )}
        </>
      )}
      <Divider sx={{ my: 1.5 }} />
      <Typography variant="subtitle2" gutterBottom>本地规则</Typography>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
        <Chip size="small" label={`词汇成本 ${local?.vocabulary_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`句式成本 ${local?.sentence_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`标点成本 ${local?.punctuation_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`情感成本 ${local?.emotion_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`对话成本 ${local?.dialogue_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`结构成本 ${local?.structure_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`文笔成本 ${local?.writing_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`规则可读性 ${local?.readability_score?.toFixed(0) ?? '-'}`} variant="outlined" />
        <Chip size="small" label={`字面保真 ${local?.fidelity_score != null ? (100 - local.fidelity_score).toFixed(0) : '-'}`} variant="outlined" />
        <Chip size="small" label={`混合成本 ${local?.composite_score?.toFixed(1) ?? '-'}`} color="primary" variant="outlined" />
      </Box>
    </Box>
  )
}

interface ApprovedPrompt {
  version_id: string
  evolution_id: string
  prompt_text: string
  avg_ai_score: number
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
      setMessage({ type: 'success', text: '进化任务已启动' })
      setStartDialogOpen(false)
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '启动失败') })
    } finally { setLoading(false) }
  }

  const handleStop = async () => {
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/stop')
      setMessage({ type: 'info', text: '任务已停止' })
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '停止失败') })
    }
  }

  const handleViewDetail = async (evolutionId: string) => {
    setLoading(true)
    try {
      const res = await apiClient.client.get(`/api/v1/prompt-evolution/history/${evolutionId}`)
      setSelectedDetail(res.data)
      setDetailDialogOpen(true)
    } catch (e) {
      setMessage({ type: 'error', text: '获取详情失败' })
    } finally { setLoading(false) }
  }

  const handleViewPrompt = async (evolutionId: string, versionId: string) => {
    setLoading(true)
    try {
      const res = await apiClient.client.get(`/api/v1/prompt-evolution/history/${evolutionId}/prompt/${versionId}`)
      setSelectedPrompt(res.data)
      setPromptDialogOpen(true)
    } catch (e) {
      setMessage({ type: 'error', text: '获取提示词失败' })
    } finally { setLoading(false) }
  }

  const handleToggleApproval = async (evolutionId: string, versionId: string, isCurrentlyApproved: boolean) => {
    setLoading(true)
    try {
      if (isCurrentlyApproved) {
        await apiClient.client.post('/api/v1/prompt-evolution/revoke', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'info', text: '已取消批准' })
      } else {
        await apiClient.client.post('/api/v1/prompt-evolution/approve', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'success', text: '提示词已批准！' })
      }
      await handleViewDetail(evolutionId)
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '操作失败') })
    } finally { setLoading(false) }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setMessage({ type: 'success', text: '已复制到剪贴板' })
  }

  const handleDelete = async (evolutionId: string) => {
    if (!confirm('确定要删除这条历史记录吗？')) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/history/${evolutionId}`)
      setMessage({ type: 'success', text: '删除成功' })
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '删除失败') })
    }
  }

  const handleCleanup = async () => {
    if (!confirm('确定要自动清理历史记录吗？\n\n将保留：\n- 最近 10 个记录\n- 得分最好的 5 个记录\n- 已批准的记录')) return
    try {
      const res = await apiClient.client.post('/api/v1/prompt-evolution/history/cleanup')
      setMessage({ type: 'success', text: res.data.message })
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '清理失败') })
    }
  }

  const handleResume = async (evolutionId: string) => {
    try {
      setMessage({ type: 'info', text: '正在恢复进化任务...' })
      const res = await apiClient.client.post('/api/v1/prompt-evolution/resume', {
        evolution_id: evolutionId,
        additional_iterations: 5,
      })
      setMessage({ type: 'success', text: res.data.message || '已恢复进化任务' })
      fetchStatus()
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '恢复失败') })
    }
  }

  const handleOpenApprovedDialog = async () => {
    await fetchApprovedPrompts()
    setApprovedDialogOpen(true)
  }

  const handleRemoveApproved = async (versionId: string) => {
    if (!confirm('确定要从已批准列表中移除这个提示词吗？')) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/approved/${versionId}`)
      setMessage({ type: 'success', text: '已从批准列表中移除' })
      fetchApprovedPrompts()
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '移除失败') })
    }
  }

  const handleSetActiveModel = async (modelId: string | null) => {
    try {
      await apiClient.client.post('/api/v1/ai-trace/model-config', { model_id: modelId })
      setMessage({ type: 'success', text: modelId ? '活跃模型已设置' : '已切换为自动最优' })
      fetchModels()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '设置失败') })
    }
  }

  const handleEvaluateModels = async () => {
    if (!evalText.trim() || evalText.trim().length < 50) {
      setMessage({ type: 'error', text: '请输入至少50字的测试文本' })
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
      setMessage({ type: 'success', text: `评测完成：${res.data.total_models_success}/${res.data.total_models_tried} 个模型成功` })
      fetchModels()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '评测失败') })
    } finally { setEvaluating(false) }
  }

  const handleAddSample = async () => {
    if (!newSampleText.trim() || newSampleText.trim().length < 50) {
      setMessage({ type: 'error', text: '样本文本至少50字' })
      return
    }
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/samples', {
        text: newSampleText,
        genre: newSampleGenre,
      })
      setMessage({ type: 'success', text: '样本已添加' })
      setAddSampleOpen(false)
      setNewSampleText('')
      setNewSampleGenre('其他')
      fetchSamples()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '添加失败') })
    }
  }

  const handleDeleteSample = async (sampleId: string) => {
    if (!confirm('确定删除此样本？')) return
    try {
      await apiClient.client.delete(`/api/v1/prompt-evolution/samples/${sampleId}`)
      setMessage({ type: 'success', text: '样本已删除' })
      fetchSamples()
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '删除失败') })
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
        setMessage({ type: 'error', text: res.data.error || '生成失败' })
      }
    } catch (e: any) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(e, '生成失败') })
    } finally { setGenerating(false) }
  }

  const getScoreColor = (score: number) => score <= 30 ? 'success.main' : score <= 50 ? 'warning.main' : 'error.main'

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <ScienceIcon color="primary" sx={{ fontSize: 32 }} />
          <Typography variant="h5">提示词进化优化（实验性）</Typography>
        </Box>
        <Button startIcon={<RefreshIcon />} onClick={() => { fetchStatus(); fetchHistories() }}>刷新</Button>
      </Box>

      {message && <Alert severity={message.type} onClose={() => setMessage(null)} sx={{ mb: 2 }}>{message.text}</Alert>}

      <Card sx={{ mb: 3, bgcolor: 'info.dark', color: 'white' }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>🧪 这是什么？</Typography>
          <Typography variant="body2">
            利用 AI 检测接口作为反馈信号，自动迭代优化"降低 AI 痕迹"的提示词。
            <strong> 所有优化结果需要人工审核确认后才能使用。</strong>
          </Typography>
        </CardContent>
      </Card>

      <Grid container spacing={3}>
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom><PlayArrowIcon sx={{ mr: 1, verticalAlign: 'middle' }} />控制面板</Typography>
              <Divider sx={{ my: 2 }} />
              {status && (
                <Box sx={{ mb: 3 }}>
                  <Chip label={status.is_running ? '运行中' : '空闲'} color={status.is_running ? 'primary' : 'default'} size="small" />
                  {status.is_running && status.max_iterations != null && (
                    <Box sx={{ mt: 2 }}>
                      {status.queue_mode && (
                        <Box sx={{ mb: 1.5 }}>
                          <Typography variant="body2" fontWeight={600}>
                            当前题材：{status.current_genre || '准备中'}
                          </Typography>
                          <Typography variant="body2" color="text.secondary">
                            题材进度：{status.queue_current ?? 0} / {status.queue_total ?? 0}
                          </Typography>
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1 }}>
                            {status.completed_genres?.map((genre) => (
                              <Chip key={genre} size="small" color="success" label={`${genre} 已完成`} />
                            ))}
                            {status.failed_genres?.map((genre) => (
                              <Chip key={genre} size="small" color="error" label={`${genre} 失败`} />
                            ))}
                          </Box>
                        </Box>
                      )}
                      <Typography variant="body2">
                        当前题材迭代：{status.current_iteration ?? 0} / {status.max_iterations}
                      </Typography>
                      <LinearProgress
                        variant="determinate"
                        value={((status.current_iteration ?? 0) / (status.max_iterations || 10)) * 100}
                        sx={{ mt: 1 }}
                      />
                      {status.best_score != null && (
                        <Typography variant="body2" sx={{ mt: 1, color: getScoreColor(status.best_score) }}>
                          最佳得分：{status.best_score.toFixed(1)}
                        </Typography>
                      )}
                    </Box>
                  )}
                </Box>
              )}
              <Divider sx={{ my: 2 }} />
              {status?.is_running ? (
                <Button variant="contained" color="error" fullWidth startIcon={<StopIcon />} onClick={handleStop}>停止进化</Button>
              ) : (
                <Button
                  variant="contained"
                  color="primary"
                  fullWidth
                  startIcon={<PlayArrowIcon />}
                  onClick={() => setStartDialogOpen(true)}
                  disabled={backgroundStatus?.is_running}
                >启动进化优化</Button>
              )}
              <Button
                variant="outlined"
                color="success"
                fullWidth
                startIcon={<CheckCircleIcon />}
                onClick={handleOpenApprovedDialog}
                sx={{ mt: 2 }}
              >
                已批准提示词
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="h6"><HistoryIcon sx={{ mr: 1, verticalAlign: 'middle' }} />进化历史</Typography>
                {histories.length > 5 && (
                  <Button size="small" startIcon={<CleaningServicesIcon />} onClick={handleCleanup}>自动清理</Button>
                )}
              </Box>
              <Divider sx={{ my: 2 }} />
              {histories.length === 0 ? (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>暂无进化历史</Typography>
              ) : (
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>ID</TableCell>
                        <TableCell>题材</TableCell>
                        <TableCell>状态</TableCell>
                        <TableCell>综合评分</TableCell>
                        <TableCell>AI 分数</TableCell>
                        <TableCell>时间</TableCell>
                        <TableCell>操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {histories.map((h) => (
                        <TableRow key={h.evolution_id}>
                          <TableCell><Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{h.evolution_id?.substring(0, 8)}...</Typography></TableCell>
                          <TableCell><Chip label={h.genre || '通用'} size="small" variant="outlined" /></TableCell>
                          <TableCell><Chip label={h.status} color={h.status === 'completed' ? 'success' : h.status === 'running' ? 'primary' : h.status === 'interrupted' ? 'warning' : 'error'} size="small" /></TableCell>
                          <TableCell>{h.best_score != null ? <Typography sx={{ color: getScoreColor(h.best_score), fontWeight: 'bold' }}>{h.best_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell>{h.ai_score != null ? <Typography sx={{ color: getScoreColor(h.ai_score), fontWeight: 'bold' }}>{h.ai_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell><Typography variant="caption">{new Date(h.started_at).toLocaleDateString()}</Typography></TableCell>
                          <TableCell>
                            <Tooltip title="查看详情"><IconButton size="small" onClick={() => handleViewDetail(h.evolution_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                            {(h.status === 'interrupted' || h.status === 'failed') && (
                              <Tooltip title="恢复进化"><IconButton size="small" color="primary" onClick={() => handleResume(h.evolution_id)}><RestartAltIcon fontSize="small" /></IconButton></Tooltip>
                            )}
                            <Tooltip title="删除">
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
            <Typography variant="h6"><SmartToyIcon sx={{ mr: 1, verticalAlign: 'middle' }} />模型管理</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField
                select
                size="small"
                label="题材"
                value={modelGenre}
                onChange={(event) => setModelGenre(event.target.value)}
                sx={{ minWidth: 100 }}
              >
                {AI_TRACE_GENRES.map((option) => (
                  <MenuItem key={option} value={option}>{option}</MenuItem>
                ))}
              </TextField>
              {modelConfig?.admin_selected_model && (
                <Button size="small" variant="outlined" onClick={() => handleSetActiveModel(null)}>切换自动最优</Button>
              )}
              <Button size="small" variant="contained" startIcon={<RocketLaunchIcon />} onClick={() => setEvalDialogOpen(true)} disabled={backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}>全模型评测</Button>
              <Button size="small" startIcon={<RefreshIcon />} onClick={fetchModels}>刷新</Button>
            </Box>
          </Box>

          {modelConfig && (
            <Alert severity="info" sx={{ mb: 2 }}>
              当前活跃模型：<strong>{modelConfig.active_model_name || '默认路由'}</strong>
              {modelConfig.admin_selected_model ? ' （管理员选定）' : modelConfig.auto_best_model ? ' （自动最优）' : ''}
              {modelConfig.active_model_provider && ` · ${modelConfig.active_model_provider}`}
            </Alert>
          )}

          {evaluationMetrics && (
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
              <Chip label={`评测 ${evaluationMetrics.total} 次`} size="small" />
              <Chip label={`成功率 ${(evaluationMetrics.success_rate * 100).toFixed(1)}%`} size="small" color="success" variant="outlined" />
              <Chip label={`保真拒绝 ${(evaluationMetrics.fidelity_rejection_rate * 100).toFixed(1)}%`} size="small" color="warning" variant="outlined" />
              <Chip label={`超时 ${evaluationMetrics.timeout_count} 次`} size="small" color="error" variant="outlined" />
            </Box>
          )}

          {backgroundStatus && (
            <Alert severity={backgroundStatus.is_running ? 'warning' : 'info'} sx={{ mb: 2 }}>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                <strong>{backgroundStatus.is_running ? '后台任务运行中' : '后台任务空闲'}</strong>
                {backgroundStatus.task_type && <Chip size="small" label={`类型：${backgroundStatus.task_type}`} />}
                {backgroundStatus.genre && <Chip size="small" label={`题材：${backgroundStatus.genre}`} />}
                {backgroundStatus.started_at && <Chip size="small" label={`开始：${new Date(backgroundStatus.started_at * 1000).toLocaleTimeString()}`} />}
                <Chip size="small" label={`预算：${backgroundStatus.budget_used}/${backgroundStatus.daily_budget}`} />
                <Chip size="small" label={`剩余：${backgroundStatus.budget_remaining}`} />
                {(backgroundStatus.expected_models || 0) > 0 && (
                  <Chip size="small" label={`模型：${backgroundStatus.completed_models || 0}/${backgroundStatus.expected_models}`} />
                )}
                {(backgroundStatus.success_models || 0) > 0 && <Chip size="small" color="success" label={`成功：${backgroundStatus.success_models}`} />}
                {(backgroundStatus.failed_models || 0) > 0 && <Chip size="small" color="error" label={`失败：${backgroundStatus.failed_models}`} />}
                {!backgroundStatus.is_running && (backgroundStatus.cooldown_until || 0) * 1000 > Date.now() && (
                  <Chip size="small" color="warning" label={`冷却至：${new Date((backgroundStatus.cooldown_until || 0) * 1000).toLocaleTimeString()}`} />
                )}
              </Box>
            </Alert>
          )}

          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>模型</TableCell>
                  <TableCell>服务商</TableCell>
                  <TableCell align="center">评测次数</TableCell>
                  <TableCell align="center">平均AI分</TableCell>
                  <TableCell align="center">平均降分</TableCell>
                  <TableCell align="center">最佳AI分</TableCell>
                  <TableCell align="center">平均延迟</TableCell>
                  <TableCell align="center">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {[...models].sort((a, b) => {
                  const sa = a.performance?.avg_ai_score ?? 999
                  const sb = b.performance?.avg_ai_score ?? 999
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
                        {m.is_eliminated && <Chip label="已淘汰" size="small" color="default" sx={{ ml: 0.5 }} />}
                      </Box>
                    </TableCell>
                    <TableCell><Chip label={m.provider} size="small" variant="outlined" /></TableCell>
                    <TableCell align="center">{m.performance?.total_evaluations ?? 0}</TableCell>
                    <TableCell align="center">
                      {m.performance?.avg_ai_score != null ? (
                        <Typography variant="body2" sx={{ color: getScoreColor(m.performance.avg_ai_score), fontWeight: 'bold' }}>
                          {m.performance.avg_ai_score.toFixed(1)}
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
                      {m.performance?.best_ai_score != null && m.performance.best_ai_score < 100 ? (
                        <Typography variant="body2" sx={{ color: getScoreColor(m.performance.best_ai_score) }}>
                          {m.performance.best_ai_score}
                        </Typography>
                      ) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {m.performance?.avg_latency != null ? `${m.performance.avg_latency.toFixed(1)}s` : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {!m.is_active && (
                        <Tooltip title="设为活跃模型">
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

          <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>提示词与模型联合排行</Typography>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>提示词版本</TableCell><TableCell>模型</TableCell>
                <TableCell align="right">成功/样本</TableCell><TableCell align="right">AI分</TableCell>
                <TableCell align="right">保真度</TableCell><TableCell align="right">综合分</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {modelCombinations.slice(0, 20).map((item) => {
                  const qualification = item.is_current
                    ? '当前生产使用'
                    : item.evaluation_policy_version !== 'ai-trace-v2'
                    ? '策略已过期'
                    : item.total_success < 3
                      ? '数据不足'
                      : item.distinct_sample_count < 3
                        ? '样本不足'
                        : item.avg_fidelity_similarity < 70
                          ? '保真不合格'
                          : '可参与路由'
                  return (
                  <TableRow key={`${item.prompt_version_id}:${item.model_id}`}>
                    <TableCell>{item.prompt_version_id}</TableCell>
                    <TableCell>{item.model_name}</TableCell>
                    <TableCell align="right">{item.total_success}/{item.distinct_sample_count}</TableCell>
                    <TableCell align="right">{item.avg_ai_score.toFixed(1)}</TableCell>
                    <TableCell align="right">{item.avg_fidelity_similarity.toFixed(1)}%</TableCell>
                    <TableCell align="right">
                      {item.composite_score.toFixed(1)}
                      <Chip size="small" sx={{ ml: 1 }} color={qualification === '可参与路由' || qualification === '当前生产使用' ? 'success' : 'default'} label={qualification} />
                    </TableCell>
                  </TableRow>
                  )
                })}
                {modelCombinations.length === 0 && <TableRow><TableCell colSpan={6} align="center">暂无成熟联合评测数据</TableCell></TableRow>}
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
              <Typography variant="h6">📝 测试样本</Typography>
              {sampleSummary && (
                <Chip label={`共 ${sampleSummary.total_samples} 个`} size="small" variant="outlined" />
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" variant="contained" onClick={() => setAddSampleOpen(true)}>添加样本</Button>
              <Button size="small" variant="outlined" onClick={handleGenerateSamples} disabled={generating}>
                {generating ? <CircularProgress size={16} sx={{ mr: 0.5 }} /> : null}
                自动生成
              </Button>
              <Button size="small" startIcon={<RefreshIcon />} onClick={fetchSamples}>刷新</Button>
            </Box>
          </Box>

          {sampleSummary?.source_distribution && (
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              {Object.entries(sampleSummary.source_distribution as Record<string, number>).map(([src, cnt]) => (
                <Chip
                  key={src}
                  label={`${src === 'custom' ? '自定义' : src === 'auto' ? '自动生成' : '内置'}: ${cnt}`}
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
                  <TableCell>ID</TableCell>
                  <TableCell>题材</TableCell>
                  <TableCell>来源</TableCell>
                  <TableCell>文本预览</TableCell>
                  <TableCell align="center">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {samples.map((s) => (
                  <TableRow key={s.sample_id}>
                    <TableCell><Typography variant="caption" fontFamily="monospace">{s.sample_id.substring(0, 12)}</Typography></TableCell>
                    <TableCell><Chip label={s.genre} size="small" /></TableCell>
                    <TableCell>
                      <Chip
                        label={s.source === 'custom' ? '自定义' : s.source === 'auto' ? '自动' : '内置'}
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
                      <Tooltip title="删除">
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
        <DialogTitle>添加自定义测试样本</DialogTitle>
        <DialogContent>
          <TextField
            select
            fullWidth
            label="题材"
            value={newSampleGenre}
            onChange={(e) => setNewSampleGenre(e.target.value)}
            sx={{ mt: 2, mb: 2 }}
            SelectProps={{ native: true }}
          >
            {['玄幻', '都市', '言情', '悬疑', '科幻', '历史', '武侠', '其他'].map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </TextField>
          <TextField
            fullWidth
            multiline
            rows={5}
            label="样本文本（至少50字）"
            value={newSampleText}
            onChange={(e) => setNewSampleText(e.target.value)}
            helperText={`${newSampleText.length} 字`}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddSampleOpen(false)}>取消</Button>
          <Button variant="contained" onClick={handleAddSample} disabled={newSampleText.trim().length < 50}>添加</Button>
        </DialogActions>
      </Dialog>

      {/* 启动配置对话框 */}
      <Dialog open={startDialogOpen} onClose={() => setStartDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>配置进化参数</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography gutterBottom>优化范围</Typography>
            <ToggleButtonGroup
              exclusive
              fullWidth
              size="small"
              value={runAllGenres ? 'all' : 'single'}
              onChange={(_, value) => value && setRunAllGenres(value === 'all')}
              sx={{ mb: 2 }}
            >
              <ToggleButton value="single">当前题材</ToggleButton>
              <ToggleButton value="all">全部题材</ToggleButton>
            </ToggleButtonGroup>
            {runAllGenres ? (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mb: 2 }}>
                {AI_TRACE_GENRES.filter((genre) => genre !== '通用').map((genre) => (
                  <Chip key={genre} label={genre} size="small" variant="outlined" />
                ))}
              </Box>
            ) : (
              <Alert severity="info" sx={{ mb: 2 }}>
                当前选择：{modelGenre === '通用' ? '通用（运行时自动检测）' : modelGenre}
              </Alert>
            )}
            <Typography gutterBottom>目标 AI 率：{targetScore}</Typography>
            <Slider value={targetScore} onChange={(_, v) => setTargetScore(v as number)} min={0} max={50} step={5} marks valueLabelDisplay="auto" />
            <Typography gutterBottom>最大迭代次数：{maxIterations}</Typography>
            <Slider value={maxIterations} onChange={(_, v) => setMaxIterations(v as number)} min={3} max={20} step={1} marks valueLabelDisplay="auto" />
            <Typography gutterBottom sx={{ mt: 2 }}>每次测试样本数：{samplesPerIteration}</Typography>
            <Slider value={samplesPerIteration} onChange={(_, v) => setSamplesPerIteration(v as number)} min={1} max={5} step={1} marks valueLabelDisplay="auto" />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStartDialogOpen(false)}>取消</Button>
          <Button variant="contained" onClick={handleStart} disabled={loading}>{loading ? <CircularProgress size={20} /> : '启动'}</Button>
        </DialogActions>
      </Dialog>

      {/* 详情对话框 */}
      <Dialog open={detailDialogOpen} onClose={() => setDetailDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>进化详情</DialogTitle>
        <DialogContent>
          {selectedDetail && (
            <Box>
              <Typography variant="subtitle2" color="text.secondary">题材：{selectedDetail.genre || '通用'} | 状态：{selectedDetail.status} | 迭代：{selectedDetail.current_iteration}/{selectedDetail.max_iterations}</Typography>
              <Divider sx={{ my: 2 }} />
              <Typography variant="h6" gutterBottom>最佳提示词版本（前 5）</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>迭代</TableCell>
                      <TableCell>AI 得分</TableCell>
                      <TableCell>降分幅度</TableCell>
                      <TableCell>分析</TableCell>
                      <TableCell>操作</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedDetail.best_versions.map((v) => {
                      const isApproved = selectedDetail.approved_version_id === v.version_id
                      return (
                        <TableRow key={v.version_id} sx={{ bgcolor: isApproved ? 'success.light' : 'inherit' }}>
                          <TableCell>#{v.iteration}</TableCell>
                          <TableCell><Typography sx={{ color: getScoreColor(v.avg_ai_score), fontWeight: 'bold' }}>{v.avg_ai_score.toFixed(1)}</Typography></TableCell>
                          <TableCell>{v.avg_score_reduction.toFixed(1)}</TableCell>
                          <TableCell><Typography variant="caption" sx={{ maxWidth: 200, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.analysis}</Typography></TableCell>
                          <TableCell>
                            <Tooltip title="查看完整提示词"><IconButton size="small" onClick={() => handleViewPrompt(selectedDetail.evolution_id, v.version_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                            <Tooltip title={isApproved ? "取消批准" : "批准此版本"}>
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
        <DialogActions><Button onClick={() => setDetailDialogOpen(false)}>关闭</Button></DialogActions>
      </Dialog>

      {/* 提示词详情对话框 */}
      <Dialog open={promptDialogOpen} onClose={() => setPromptDialogOpen(false)} maxWidth="lg" fullWidth>
        <DialogTitle>提示词详情</DialogTitle>
        <DialogContent dividers>
          {selectedPrompt && (
            <Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                  <Chip label={`迭代 #${selectedPrompt.iteration}`} sx={{ mr: 1 }} />
                  <Chip label={`AI 得分：${selectedPrompt.avg_ai_score.toFixed(1)}`} color={selectedPrompt.avg_ai_score <= 30 ? 'success' : selectedPrompt.avg_ai_score <= 50 ? 'warning' : 'error'} />
                </Box>
                <Button startIcon={<ContentCopyIcon />} onClick={() => copyToClipboard(selectedPrompt.prompt_text)} size="small">复制</Button>
              </Box>
              <Alert severity="info" sx={{ mb: 2 }}>
                <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{selectedPrompt.prompt_text}</Typography>
              </Alert>
              <Typography variant="h6" gutterBottom>优化分析</Typography>
              <Alert severity={selectedPrompt.avg_score_reduction > 0 ? 'success' : 'warning'} sx={{ mb: 2 }}>
                {selectedPrompt.analysis}
              </Alert>
              <Typography variant="h6" gutterBottom>测试样本（{selectedPrompt.evaluation_results.length}个）</Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>样本 ID</TableCell>
                      <TableCell>原始得分</TableCell>
                      <TableCell>优化后得分</TableCell>
                      <TableCell>降分幅度</TableCell>
                      <TableCell>质量评审</TableCell>
                      <TableCell>状态</TableCell>
                      <TableCell>操作</TableCell>
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
                            <Chip size="small" label={`语义 ${sample.llm_review?.semantic_fidelity?.score?.toFixed(0) ?? '-'}`} variant="outlined" />
                            <Chip size="small" label={`可读 ${sample.llm_review?.readability?.score?.toFixed(0) ?? '-'}`} variant="outlined" />
                          </Box>
                        </TableCell>
                        <TableCell><Chip label={sample.success ? '成功' : '失败'} color={sample.success ? 'success' : 'error'} size="small" /></TableCell>
                        <TableCell>
                          <Tooltip title="查看原文"><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `original-${idx}` ? null : `original-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                          <Tooltip title="查看优化后"><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `rewritten-${idx}` ? null : `rewritten-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                          <Tooltip title="查看全部质量维度"><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `quality-${idx}` ? null : `quality-${idx}`) }}><LeaderboardIcon fontSize="small" /></IconButton></Tooltip>
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
                      <Typography variant="subtitle2" gutterBottom>原文：</Typography>
                      <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{sample.original_text}</Typography>
                    </Alert>
                  )}
                  {expandedPromptId === `rewritten-${idx}` && (
                    <Alert severity="success" sx={{ mt: 1 }}>
                      <Typography variant="subtitle2" gutterBottom>优化后：</Typography>
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
        <DialogActions><Button onClick={() => setPromptDialogOpen(false)}>关闭</Button></DialogActions>
      </Dialog>

      {/* 已批准提示词对话框 */}
      <Dialog open={approvedDialogOpen} onClose={() => setApprovedDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>已批准提示词列表</DialogTitle>
        <DialogContent>
          {approvedPrompts.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>暂无已批准的提示词</Typography>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>AI 得分</TableCell>
                    <TableCell>批准时间</TableCell>
                    <TableCell>操作</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {approvedPrompts.map((p) => (
                    <TableRow key={p.version_id}>
                      <TableCell><Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{p.version_id?.substring(0, 8)}...</Typography></TableCell>
                      <TableCell><Typography sx={{ color: getScoreColor(p.avg_ai_score), fontWeight: 'bold' }}>{p.avg_ai_score.toFixed(1)}</Typography></TableCell>
                      <TableCell><Typography variant="caption">{new Date(p.approved_at).toLocaleDateString()}</Typography></TableCell>
                      <TableCell>
                        <Tooltip title="查看"><IconButton size="small" onClick={() => handleViewPrompt(p.evolution_id, p.version_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                        <Tooltip title="移除">
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
        <DialogActions><Button onClick={() => setApprovedDialogOpen(false)}>关闭</Button></DialogActions>
      </Dialog>

      {/* 全模型评测对话框 */}
      <Dialog open={evalDialogOpen} onClose={() => { if (!evaluating) setEvalDialogOpen(false) }} maxWidth="md" fullWidth>
        <DialogTitle>全模型评测</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            输入测试文本，将同时调用所有 9 个模型进行改写并检测 AI 分数，结果自动更新排行榜。
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={4}
            label="测试文本（至少50字）"
            value={evalText}
            onChange={(e) => setEvalText(e.target.value)}
            disabled={evaluating}
            sx={{ mb: 2 }}
          />
          {evaluating && (
            <Box sx={{ mb: 2 }}>
              <LinearProgress />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                正在评测所有模型，预计需要 1-3 分钟…
              </Typography>
            </Box>
          )}
          {evalResults && (
            <Box>
              <Alert severity="success" sx={{ mb: 2 }}>
                评测完成：原始 AI 分数 {evalResults.original_ai_score}，
                {evalResults.total_models_success}/{evalResults.total_models_tried} 个模型成功，
                耗时 {evalResults.total_time_seconds?.toFixed(1)}s
              </Alert>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>#</TableCell>
                      <TableCell>模型</TableCell>
                      <TableCell align="center">AI分数</TableCell>
                      <TableCell align="center">降分幅度</TableCell>
                      <TableCell align="center">耗时</TableCell>
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
          <Button onClick={() => { setEvalDialogOpen(false); setEvalResults(null) }} disabled={evaluating}>关闭</Button>
          <Button variant="contained" onClick={handleEvaluateModels} disabled={evaluating || !evalText.trim() || backgroundStatus?.is_running || backgroundStatus?.budget_remaining === 0}>
            {evaluating ? <CircularProgress size={20} /> : '开始评测'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
