/**
 * 生成进度对话框组件
 * 显示AI生成任务的进度和结果
 */

import { useState, useEffect } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  LinearProgress,
  Typography,
  Alert,
  Paper,
  Divider,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import { GenerationTask } from '@/services/generation'

interface GenerationProgressDialogProps {
  open: boolean
  taskType: string
  task: GenerationTask | null
  onClose: () => void
  onRetry?: () => void
}

export default function GenerationProgressDialog({
  open,
  taskType,
  task,
  onClose,
  onRetry,
}: GenerationProgressDialogProps) {
  const [displayResult, setDisplayResult] = useState('')

  useEffect(() => {
    if (task?.result) {
      setDisplayResult(task.result)
    }
  }, [task?.result])

  const getTaskTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      concept: '项目概念生成',
      world: '世界观生成',
      character: '人物生成',
      plot: '情节生成',
      chapter: '章节生成',
    }
    return labels[type] || type
  }

  const getStatusIcon = () => {
    if (!task) return null

    switch (task.status) {
      case 'completed':
        return <CheckCircleIcon sx={{ color: 'success.main', fontSize: 40 }} />
      case 'failed':
        return <ErrorIcon sx={{ color: 'error.main', fontSize: 40 }} />
      case 'running':
      case 'pending':
        return <HourglassEmptyIcon sx={{ color: 'info.main', fontSize: 40 }} />
      default:
        return null
    }
  }

  const getStatusText = () => {
    if (!task) return ''

    switch (task.status) {
      case 'pending':
        return '等待处理中...'
      case 'running':
        return '正在生成中...'
      case 'completed':
        return '生成完成！'
      case 'failed':
        return '生成失败'
      default:
        return ''
    }
  }

  const isLoading = task?.status === 'pending' || task?.status === 'running'
  const isCompleted = task?.status === 'completed'
  const isFailed = task?.status === 'failed'

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          {getStatusIcon()}
          <Box>
            <Typography variant="h6">{getTaskTypeLabel(taskType)}</Typography>
            <Typography variant="body2" color="textSecondary">
              {getStatusText()}
            </Typography>
          </Box>
        </Box>
      </DialogTitle>

      <DialogContent sx={{ minHeight: 300 }}>
        {/* 进度条 */}
        {isLoading && (
          <Box sx={{ mb: 3 }}>
            <LinearProgress />
            <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
              任务ID: {task?.task_id}
            </Typography>
          </Box>
        )}

        {/* 错误提示 */}
        {isFailed && task?.error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>
              生成失败
            </Typography>
            <Typography variant="body2">{task.error}</Typography>
          </Alert>
        )}

        {/* 生成结果 */}
        {isCompleted && displayResult && (
          <Box>
            <Alert severity="success" sx={{ mb: 2 }}>
              内容已成功生成！
            </Alert>
            <Paper
              sx={{
                p: 2,
                backgroundColor: '#f5f5f5',
                maxHeight: 400,
                overflow: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              <Typography variant="body2" component="div">
                {displayResult}
              </Typography>
            </Paper>
          </Box>
        )}

        {/* 任务信息 */}
        {task && (
          <Box sx={{ mt: 3 }}>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>
              任务信息
            </Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  任务ID
                </Typography>
                <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                  {task.task_id}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  状态
                </Typography>
                <Typography variant="body2">{task.status}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  创建时间
                </Typography>
                <Typography variant="body2">
                  {new Date(task.created_at).toLocaleString()}
                </Typography>
              </Box>
              {task.completed_at && (
                <Box>
                  <Typography variant="caption" color="textSecondary">
                    完成时间
                  </Typography>
                  <Typography variant="body2">
                    {new Date(task.completed_at).toLocaleString()}
                  </Typography>
                </Box>
              )}
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ p: 2 }}>
        {isFailed && onRetry && (
          <Button variant="contained" color="primary" onClick={onRetry}>
            重试
          </Button>
        )}
        {isCompleted && (
          <Button
            variant="contained"
            color="primary"
            onClick={() => {
              // 复制结果到剪贴板
              if (displayResult) {
                navigator.clipboard.writeText(displayResult)
                alert('已复制到剪贴板')
              }
            }}
          >
            复制结果
          </Button>
        )}
        <Button variant="outlined" onClick={onClose}>
          {isLoading ? '最小化' : '关闭'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

