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
import { useTranslation } from 'react-i18next'
import { useFormats } from '@/i18n'
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
  const { t } = useTranslation()
  const { formatDateTime } = useFormats()
  const [displayResult, setDisplayResult] = useState('')

  useEffect(() => {
    if (task?.result) {
      setDisplayResult(task.result)
    }
  }, [task?.result])

  const getTaskTypeLabel = (type: string) => {
    const labelKeys: Record<string, string> = {
      concept: 'workflow.generationProgress.taskTypeConcept',
      world: 'workflow.generationProgress.taskTypeWorld',
      character: 'workflow.generationProgress.taskTypeCharacter',
      plot: 'workflow.generationProgress.taskTypePlot',
      chapter: 'workflow.generationProgress.taskTypeChapter',
    }
    return labelKeys[type] ? t(labelKeys[type]) : type
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
        return t('workflow.generationProgress.statusPending')
      case 'running':
        return t('workflow.generationProgress.statusRunning')
      case 'completed':
        return t('workflow.generationProgress.statusCompleted')
      case 'failed':
        return t('workflow.generationProgress.statusFailed')
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
              {t('workflow.generationProgress.taskIdPrefix', { id: task?.task_id })}
            </Typography>
          </Box>
        )}

        {/* 错误提示 */}
        {isFailed && task?.error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>
              {t('workflow.generationProgress.statusFailed')}
            </Typography>
            <Typography variant="body2">{task.error}</Typography>
          </Alert>
        )}

        {/* 生成结果 */}
        {isCompleted && displayResult && (
          <Box>
            <Alert severity="success" sx={{ mb: 2 }}>
              {t('workflow.generationProgress.generatedSuccess')}
            </Alert>
            <Paper
              sx={{
                p: 2,
                backgroundColor: 'grey.100',
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
              {t('workflow.generationProgress.taskInfo')}
            </Typography>
            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  {t('workflow.generationProgress.taskId')}
                </Typography>
                <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                  {task.task_id}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  {t('workflow.generationProgress.statusLabel')}
                </Typography>
                <Typography variant="body2">{task.status}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="textSecondary">
                  {t('workflow.generationProgress.createdAt')}
                </Typography>
                <Typography variant="body2">
                  {formatDateTime(task.created_at)}
                </Typography>
              </Box>
              {task.completed_at && (
                <Box>
                  <Typography variant="caption" color="textSecondary">
                    {t('workflow.generationProgress.completedAt')}
                  </Typography>
                  <Typography variant="body2">
                    {formatDateTime(task.completed_at)}
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
            {t('workflow.generationProgress.retry')}
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
                alert(t('workflow.generationProgress.copied'))
              }
            }}
          >
            {t('workflow.generationProgress.copyResult')}
          </Button>
        )}
        <Button variant="outlined" onClick={onClose}>
          {isLoading ? t('workflow.generationProgress.minimize') : t('action.close')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

