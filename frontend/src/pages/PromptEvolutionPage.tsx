/**
 * 提示词进化优化页面
 * 独立的实验性功能，用于自动优化"降低AI痕迹"的提示词
 */
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Container, Box, Card, CardContent, Button, Typography, Alert,
  CircularProgress, LinearProgress, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Paper,
  IconButton, Tooltip, Divider, Slider, Grid,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { apiClient } from '@/services/api'

interface EvolutionStatus {
  is_running: boolean
  evolution_id?: string
  status?: string
  current_iteration?: number
  max_iterations?: number
  best_score?: number
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
  }>
  created_at: string
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

export default function PromptEvolutionPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<EvolutionStatus | null>(null)
  const [histories, setHistories] = useState<any[]>([])
  const [selectedDetail, setSelectedDetail] = useState<EvolutionDetail | null>(null)
  const [selectedPrompt, setSelectedPrompt] = useState<PromptDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null)
  
  const [maxIterations, setMaxIterations] = useState(10)
  const [samplesPerIteration, setSamplesPerIteration] = useState(3)
  
  const [startDialogOpen, setStartDialogOpen] = useState(false)
  const [detailDialogOpen, setDetailDialogOpen] = useState(false)
  const [promptDialogOpen, setPromptDialogOpen] = useState(false)
  const [approvedDialogOpen, setApprovedDialogOpen] = useState(false)
  const [approvedPrompts, setApprovedPrompts] = useState<ApprovedPrompt[]>([])
  const [expandedPromptId, setExpandedPromptId] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/status')
      setStatus(res.data)
    } catch (e) { console.error(e) }
  }, [])

  const fetchHistories = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/history')
      setHistories(res.data)
    } catch (e) { console.error(e) }
  }, [])

  const fetchApprovedPrompts = useCallback(async () => {
    try {
      const res = await apiClient.client.get('/api/v1/prompt-evolution/approved')
      setApprovedPrompts(res.data.approved_prompts || [])
    } catch (e) { console.error(e) }
  }, [])

  useEffect(() => {
    fetchStatus()
    fetchHistories()
  }, [fetchStatus, fetchHistories])

  useEffect(() => {
    if (!status?.is_running) return
    const interval = setInterval(fetchStatus, 5000)
    return () => clearInterval(interval)
  }, [status?.is_running, fetchStatus])

  const handleStart = async () => {
    setLoading(true)
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/start', {
        target_score: 0,  // 得分越低越好，默认目标为0
        max_iterations: maxIterations,
        samples_per_iteration: samplesPerIteration,
      })
      setMessage({ type: 'success', text: '进化任务已启动' })
      setStartDialogOpen(false)
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: e.response?.data?.detail || '启动失败' })
    } finally { setLoading(false) }
  }

  const handleStop = async () => {
    try {
      await apiClient.client.post('/api/v1/prompt-evolution/stop')
      setMessage({ type: 'info', text: '任务已停止' })
      fetchStatus()
    } catch (e: any) {
      setMessage({ type: 'error', text: e.response?.data?.detail || '停止失败' })
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
        // 取消批准
        await apiClient.client.post('/api/v1/prompt-evolution/revoke', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'info', text: '已取消批准' })
      } else {
        // 批准
        await apiClient.client.post('/api/v1/prompt-evolution/approve', { evolution_id: evolutionId, version_id: versionId })
        setMessage({ type: 'success', text: '提示词已批准！' })
      }
      // 刷新详情数据
      await handleViewDetail(evolutionId)
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: e.response?.data?.detail || '操作失败' })
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
      setMessage({ type: 'error', text: e.response?.data?.detail || '删除失败' })
    }
  }

  const handleCleanup = async () => {
    if (!confirm('确定要自动清理历史记录吗？\n\n将保留：\n- 最近10个记录\n- 得分最好的5个记录\n- 已批准的记录')) return
    try {
      const res = await apiClient.client.post('/api/v1/prompt-evolution/history/cleanup')
      setMessage({ type: 'success', text: res.data.message })
      fetchHistories()
    } catch (e: any) {
      setMessage({ type: 'error', text: e.response?.data?.detail || '清理失败' })
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
      setMessage({ type: 'error', text: e.response?.data?.detail || '移除失败' })
    }
  }

  const getScoreColor = (score: number) => score <= 30 ? 'success.main' : score <= 50 ? 'warning.main' : 'error.main'

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/dashboard')}>返回</Button>
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
            利用AI检测接口作为反馈信号，自动迭代优化"降低AI痕迹"的提示词。
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
                      <Typography variant="body2">
                        进度: {status.current_iteration ?? 0} / {status.max_iterations}
                      </Typography>
                      <LinearProgress
                        variant="determinate"
                        value={((status.current_iteration ?? 0) / (status.max_iterations || 10)) * 100}
                        sx={{ mt: 1 }}
                      />
                      {status.best_score != null && (
                        <Typography variant="body2" sx={{ mt: 1, color: getScoreColor(status.best_score) }}>
                          最佳得分: {status.best_score.toFixed(1)}
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
                <Button variant="contained" color="primary" fullWidth startIcon={<PlayArrowIcon />} onClick={() => setStartDialogOpen(true)}>启动进化优化</Button>
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
                        <TableCell>状态</TableCell>
                        <TableCell>综合评分</TableCell>
                        <TableCell>AI分数</TableCell>
                        <TableCell>时间</TableCell>
                        <TableCell>操作</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {histories.map((h) => (
                        <TableRow key={h.evolution_id}>
                          <TableCell><Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{h.evolution_id?.substring(0, 8)}...</Typography></TableCell>
                          <TableCell><Chip label={h.status} color={h.status === 'completed' ? 'success' : h.status === 'running' ? 'primary' : 'error'} size="small" /></TableCell>
                          <TableCell>{h.best_score != null ? <Typography sx={{ color: getScoreColor(h.best_score), fontWeight: 'bold' }}>{h.best_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell>{h.ai_score != null ? <Typography sx={{ color: getScoreColor(h.ai_score), fontWeight: 'bold' }}>{h.ai_score.toFixed(1)}</Typography> : '-'}</TableCell>
                          <TableCell><Typography variant="caption">{new Date(h.started_at).toLocaleDateString()}</Typography></TableCell>
                          <TableCell>
                            <Tooltip title="查看详情"><IconButton size="small" onClick={() => handleViewDetail(h.evolution_id)}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                            <Tooltip title="删除"><IconButton size="small" color="error" onClick={() => handleDelete(h.evolution_id)} disabled={h.status === 'running'}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
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

      {/* 启动配置对话框 */}
      <Dialog open={startDialogOpen} onClose={() => setStartDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>配置进化参数</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <Typography gutterBottom>最大迭代次数: {maxIterations}</Typography>
            <Slider value={maxIterations} onChange={(_, v) => setMaxIterations(v as number)} min={3} max={20} step={1} marks valueLabelDisplay="auto" />
            <Typography gutterBottom sx={{ mt: 2 }}>每次测试样本数: {samplesPerIteration}</Typography>
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
              <Typography variant="subtitle2" color="text.secondary">状态: {selectedDetail.status} | 迭代: {selectedDetail.current_iteration}/{selectedDetail.max_iterations}</Typography>
              <Divider sx={{ my: 2 }} />
              <Typography variant="h6" gutterBottom>最佳提示词版本（前5）</Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>迭代</TableCell>
                      <TableCell>AI得分</TableCell>
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
        <DialogTitle>
          提示词详情
          {selectedPrompt && <Chip label={`得分: ${selectedPrompt.avg_ai_score.toFixed(1)}`} color="primary" size="small" sx={{ ml: 2 }} />}
        </DialogTitle>
        <DialogContent>
          {selectedPrompt && (
            <Box>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6">提示词内容</Typography>
                <Button startIcon={<ContentCopyIcon />} onClick={() => copyToClipboard(selectedPrompt.prompt_text)}>复制</Button>
              </Box>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50', maxHeight: 300, overflow: 'auto', border: '1px solid', borderColor: 'grey.300' }}>
                <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12, color: 'grey.800' }}>{selectedPrompt.prompt_text}</Typography>
              </Paper>
              <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>改写效果示例</Typography>
              {selectedPrompt.evaluation_results.map((r, i) => (
                <Paper key={i} variant="outlined" sx={{ p: 2, mb: 2 }}>
                  <Box sx={{ display: 'flex', gap: 2, mb: 1 }}>
                    <Chip label={`原始: ${r.original_ai_score}`} color="error" size="small" />
                    <Chip label={`改写后: ${r.rewritten_ai_score}`} color="success" size="small" />
                    <Chip label={`降低: ${r.score_reduction.toFixed(1)}`} size="small" />
                  </Box>
                  <Grid container spacing={2}>
                    <Grid item xs={6}>
                      <Typography variant="caption" color="text.secondary">原文</Typography>
                      <Typography variant="body2" sx={{ maxHeight: 150, overflow: 'auto' }}>{r.original_text}</Typography>
                    </Grid>
                    <Grid item xs={6}>
                      <Typography variant="caption" color="text.secondary">改写后</Typography>
                      <Typography variant="body2" sx={{ maxHeight: 150, overflow: 'auto' }}>{r.rewritten_text}</Typography>
                    </Grid>
                  </Grid>
                </Paper>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions><Button onClick={() => setPromptDialogOpen(false)}>关闭</Button></DialogActions>
      </Dialog>

      {/* 已批准提示词管理对话框 */}
      <Dialog open={approvedDialogOpen} onClose={() => setApprovedDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <CheckCircleIcon color="success" />
            已批准提示词管理
            <Chip label={`共 ${approvedPrompts.length} 个`} size="small" sx={{ ml: 1 }} />
          </Box>
        </DialogTitle>
        <DialogContent>
          {approvedPrompts.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography color="text.secondary">暂无已批准的提示词</Typography>
              <Typography variant="caption" color="text.secondary">在进化详情中批准提示词后，它们会显示在这里</Typography>
            </Box>
          ) : (
            <Box sx={{ mt: 1 }}>
              {approvedPrompts.map((prompt, index) => (
                <Paper key={prompt.version_id} variant="outlined" sx={{ p: 2, mb: 2, bgcolor: index === approvedPrompts.length - 1 ? 'success.light' : 'inherit' }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                    <Box>
                      <Typography variant="subtitle2" sx={{ fontFamily: 'monospace' }}>
                        版本: {prompt.version_id}
                        {index === approvedPrompts.length - 1 && <Chip label="最新" size="small" color="success" sx={{ ml: 1 }} />}
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                        <Chip
                          label={`AI分数: ${prompt.avg_ai_score?.toFixed(1) ?? '-'}`}
                          size="small"
                          color="primary"
                          variant="outlined"
                        />
                        <Chip
                          label={`综合评分: ${
                            prompt.avg_composite_score != null && prompt.avg_composite_score < 100
                              ? prompt.avg_composite_score.toFixed(1)
                              : (prompt.avg_ai_score?.toFixed(1) ?? '-')
                          }`}
                          size="small"
                          color="secondary"
                          variant="outlined"
                          title={prompt.avg_composite_score != null && prompt.avg_composite_score < 100
                            ? '多维度综合评分'
                            : '综合评分使用AI分数（默认）'}
                        />
                        <Chip label={`批准: ${new Date(prompt.approved_at).toLocaleString()}`} size="small" variant="outlined" />
                      </Box>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Tooltip title="复制提示词">
                        <IconButton size="small" onClick={() => copyToClipboard(prompt.prompt_text)}>
                          <ContentCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="从批准列表中移除">
                        <IconButton size="small" color="error" onClick={() => handleRemoveApproved(prompt.version_id)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                  </Box>
                  <Box sx={{ mt: 1 }}>
                    <Button
                      size="small"
                      startIcon={expandedPromptId === prompt.version_id ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                      onClick={() => setExpandedPromptId(expandedPromptId === prompt.version_id ? null : prompt.version_id)}
                    >
                      {expandedPromptId === prompt.version_id ? '收起内容' : '查看完整内容'}
                    </Button>
                    {expandedPromptId === prompt.version_id ? (
                      <Paper variant="outlined" sx={{ p: 2, mt: 1, bgcolor: 'grey.50', maxHeight: 300, overflow: 'auto' }}>
                        <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 11 }}>
                          {prompt.prompt_text}
                        </Typography>
                      </Paper>
                    ) : (
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {prompt.prompt_text.substring(0, 100)}...
                      </Typography>
                    )}
                  </Box>
                </Paper>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setApprovedDialogOpen(false)}>关闭</Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

