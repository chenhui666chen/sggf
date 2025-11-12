import { useEffect, useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
  Box,
  Chip,
  CircularProgress,
  Alert,
  Paper,
  Divider,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DeleteIcon from '@mui/icons-material/Delete'
import { generationService } from '@/services/generation'

export interface GenerationHistoryItem {
  id: number
  project_id: number
  chapter_id?: number
  task_type: string
  task_id: string
  prompt: string
  result: string
  status: string
  quality_score?: number
  created_at: string
  completed_at?: string
}

interface GenerationHistoryDialogProps {
  open: boolean
  projectId: number
  chapterId?: number
  onClose: () => void
  onSelect?: (history: GenerationHistoryItem) => void
}

export default function GenerationHistoryDialog({
  open,
  projectId,
  chapterId,
  onClose,
  onSelect,
}: GenerationHistoryDialogProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [histories, setHistories] = useState<GenerationHistoryItem[]>([])
  const [selectedHistory, setSelectedHistory] = useState<GenerationHistoryItem | null>(null)

  useEffect(() => {
    if (open) {
      loadHistory()
    }
  }, [open, projectId, chapterId])

  const loadHistory = async () => {
    try {
      setLoading(true)
      setError(null)

      // 如果有章节ID，获取章节的历史；否则获取项目的历史
      const resourceType = chapterId ? 'chapter' : 'project'
      const resourceId = chapterId || projectId

      const data = await generationService.getGenerationHistory(resourceType, resourceId)
      setHistories(data.histories || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history')
    } finally {
      setLoading(false)
    }
  }

  const handleCopyResult = (result: string) => {
    navigator.clipboard.writeText(result)
  }

  const handleSelectHistory = (history: GenerationHistoryItem) => {
    setSelectedHistory(history)
    if (onSelect) {
      onSelect(history)
    }
  }

  const getTaskTypeLabel = (taskType: string) => {
    const labels: Record<string, string> = {
      concept: '项目概念',
      world: '世界观',
      character: '人物',
      plot: '情节',
      chapter: '章节',
      workflow: '工作流程',
    }
    return labels[taskType] || taskType
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'success'
      case 'running':
        return 'info'
      case 'pending':
        return 'default'
      case 'failed':
        return 'error'
      default:
        return 'default'
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>📚 生成历史</DialogTitle>
      <DialogContent sx={{ minHeight: 400 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 300 }}>
            <CircularProgress />
          </Box>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : histories.length === 0 ? (
          <Alert severity="info">暂无生成历史</Alert>
        ) : (
          <Box sx={{ display: 'flex', gap: 2, height: '100%' }}>
            {/* 历史列表 */}
            <Box sx={{ flex: 1, minWidth: 250 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                历史记录 ({histories.length})
              </Typography>
              <List sx={{ maxHeight: 350, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 1 }}>
                {histories.map((history) => (
                  <ListItem key={history.id} disablePadding>
                    <ListItemButton
                      selected={selectedHistory?.id === history.id}
                      onClick={() => handleSelectHistory(history)}
                    >
                      <ListItemText
                        primary={getTaskTypeLabel(history.task_type)}
                        secondary={
                          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5 }}>
                            <Chip
                              label={history.status}
                              size="small"
                              color={getStatusColor(history.status) as any}
                            />
                            <Typography variant="caption" color="textSecondary">
                              {new Date(history.created_at).toLocaleDateString()}
                            </Typography>
                          </Box>
                        }
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            </Box>

            {/* 详情面板 */}
            {selectedHistory && (
              <Box sx={{ flex: 1, minWidth: 300 }}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  详情
                </Typography>
                <Paper sx={{ p: 2, backgroundColor: '#f5f5f5' }}>
                  {/* 基本信息 */}
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="caption" color="textSecondary">
                      任务类型
                    </Typography>
                    <Typography variant="body2">
                      {getTaskTypeLabel(selectedHistory.task_type)}
                    </Typography>
                  </Box>

                  <Divider sx={{ my: 1 }} />

                  <Box sx={{ mb: 2 }}>
                    <Typography variant="caption" color="textSecondary">
                      状态
                    </Typography>
                    <Box sx={{ mt: 0.5 }}>
                      <Chip
                        label={selectedHistory.status}
                        color={getStatusColor(selectedHistory.status) as any}
                        size="small"
                      />
                    </Box>
                  </Box>

                  <Divider sx={{ my: 1 }} />

                  {selectedHistory.quality_score && (
                    <>
                      <Box sx={{ mb: 2 }}>
                        <Typography variant="caption" color="textSecondary">
                          质量评分
                        </Typography>
                        <Typography variant="body2">
                          {selectedHistory.quality_score.toFixed(1)} / 10
                        </Typography>
                      </Box>
                      <Divider sx={{ my: 1 }} />
                    </>
                  )}

                  <Box sx={{ mb: 2 }}>
                    <Typography variant="caption" color="textSecondary">
                      创建时间
                    </Typography>
                    <Typography variant="body2">
                      {new Date(selectedHistory.created_at).toLocaleString()}
                    </Typography>
                  </Box>

                  {/* 提示词 */}
                  {selectedHistory.prompt && (
                    <>
                      <Divider sx={{ my: 1 }} />
                      <Box sx={{ mb: 2 }}>
                        <Typography variant="caption" color="textSecondary">
                          提示词
                        </Typography>
                        <Paper sx={{ p: 1, mt: 0.5, backgroundColor: '#fff', maxHeight: 100, overflow: 'auto' }}>
                          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                            {selectedHistory.prompt}
                          </Typography>
                        </Paper>
                      </Box>
                    </>
                  )}

                  {/* 生成结果 */}
                  {selectedHistory.result && (
                    <>
                      <Divider sx={{ my: 1 }} />
                      <Box sx={{ mb: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <Typography variant="caption" color="textSecondary">
                          生成结果
                        </Typography>
                        <Button
                          size="small"
                          startIcon={<ContentCopyIcon />}
                          onClick={() => handleCopyResult(selectedHistory.result)}
                        >
                          复制
                        </Button>
                      </Box>
                      <Paper sx={{ p: 1, backgroundColor: '#fff', maxHeight: 150, overflow: 'auto' }}>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                          {selectedHistory.result}
                        </Typography>
                      </Paper>
                    </>
                  )}
                </Paper>
              </Box>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}

