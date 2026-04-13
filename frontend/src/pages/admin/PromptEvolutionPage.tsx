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
  IconButton, Tooltip, Divider, Slider, Grid,
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
import { apiClient, extractApiErrorMessage } from '@/services/api'

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
        target_score: 0,
        max_iterations: maxIterations,
        samples_per_iteration: samplesPerIteration,
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
                      <Typography variant="body2">
                        进度：{status.current_iteration ?? 0} / {status.max_iterations}
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
                        <TableCell>AI 分数</TableCell>
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

      {/* 启动配置对话框 */}
      <Dialog open={startDialogOpen} onClose={() => setStartDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>配置进化参数</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
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
              <Typography variant="subtitle2" color="text.secondary">状态：{selectedDetail.status} | 迭代：{selectedDetail.current_iteration}/{selectedDetail.max_iterations}</Typography>
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
                      <TableCell>状态</TableCell>
                      <TableCell>操作</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedPrompt.evaluation_results.map((sample, idx) => (
                      <TableRow key={sample.sample_id || idx}>
                        <TableCell><Typography variant="caption">{sample.sample_id?.substring(0, 8)}...</Typography></TableCell>
                        <TableCell><Typography sx={{ color: getScoreColor(sample.original_ai_score), fontWeight: 'bold' }}>{sample.original_ai_score.toFixed(1)}</Typography></TableCell>
                        <TableCell><Typography sx={{ color: getScoreColor(sample.rewritten_ai_score), fontWeight: 'bold' }}>{sample.rewritten_ai_score.toFixed(1)}</Typography></TableCell>
                        <TableCell><Typography sx={{ color: sample.score_reduction > 0 ? 'success.main' : 'error.main', fontWeight: 'bold' }}>{sample.score_reduction.toFixed(1)}</Typography></TableCell>
                        <TableCell><Chip label={sample.success ? '成功' : '失败'} color={sample.success ? 'success' : 'error'} size="small" /></TableCell>
                        <TableCell>
                          <Tooltip title="查看原文"><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `original-${idx}` ? null : `original-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
                          <Tooltip title="查看优化后"><IconButton size="small" onClick={() => { setExpandedPromptId(expandedPromptId === `rewritten-${idx}` ? null : `rewritten-${idx}`) }}><VisibilityIcon fontSize="small" /></IconButton></Tooltip>
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
    </Box>
  )
}
