import {
  Alert,
  Box,
  LinearProgress,
  Paper,
  Typography,
} from '@mui/material'

import type {
  StageConfig,
  StageInfo,
  StageStatus,
  TaskStatus,
} from './types'
import { audiobookColorRoles, audiobookColors } from './audiobookTheme'
import { getStageConfigForTask } from './utils'

interface TaskStageDetailsProps {
  taskStatus: TaskStatus
  onOpenStageMetrics: (stage: StageConfig, stageInfo: StageInfo) => void
}

const STAGE_STATUS_COLORS: Record<StageStatus, { bg: string; border: string; text: string }> = {
  pending: audiobookColorRoles.taskStatus.pending,
  running: audiobookColorRoles.taskStatus.running,
  completed: audiobookColorRoles.taskStatus.completed,
  failed: audiobookColorRoles.taskStatus.failed,
  paused: audiobookColorRoles.taskStatus.paused,
  pause_requested: audiobookColorRoles.taskStatus.pause_requested,
}

const DEFAULT_PENDING_STAGE_INFO: StageInfo = {
  status: 'pending',
  progress: 0,
}

const formatStageStatusText = (stageInfo: StageInfo): string => {
  if (stageInfo.status === 'running') {
    return `进行中 ${Math.round(stageInfo.progress * 100)}%`
  }
  if (stageInfo.status === 'completed') {
    return '已完成'
  }
  if (stageInfo.status === 'failed') {
    return '失败'
  }
  return '等待中'
}

const formatMetricPreviewValue = (value: unknown): string => {
  const preview = typeof value === 'object'
    ? JSON.stringify(value)
    : String(value)
  return (preview ?? '').slice(0, 20)
}

const TaskStageDetails = ({ taskStatus, onOpenStageMetrics }: TaskStageDetailsProps) => {
  const stageConfig = getStageConfigForTask(taskStatus)
  const stageValues = Object.values(taskStatus.stages || {})
  const hasLiveProgress = stageValues.some((stage) => stage?.status && stage.status !== 'pending')

  return (
    <Box>
      {!hasLiveProgress && (
        <Alert severity="info" sx={{ mb: 2 }}>
          正在等待后台任务启动，阶段详情准备就绪后会自动更新。如需查看以往结果，可打开右上角「历史记录」。
        </Alert>
      )}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            sm: 'repeat(2, minmax(0, 1fr))',
            lg: 'repeat(3, minmax(0, 1fr))',
          },
          gap: 2,
        }}
      >
        {stageConfig.map((stage) => {
          const stageInfo = taskStatus.stages[stage.key] || DEFAULT_PENDING_STAGE_INFO
          const colors = STAGE_STATUS_COLORS[stageInfo.status]
          const isActive = stageInfo.status === 'running'
          const isDone = stageInfo.status === 'completed'
          const metricsEntries = stageInfo.metrics ? Object.entries(stageInfo.metrics) : []
          const canOpen = isDone && metricsEntries.length > 0

          return (
            <Paper
              key={stage.key}
              elevation={isActive ? 4 : 1}
              onClick={canOpen ? () => onOpenStageMetrics(stage, stageInfo) : undefined}
              sx={{
                p: 2,
                border: `2px solid ${colors.border}`,
                backgroundColor: colors.bg,
                transition: 'all 0.3s ease',
                transform: isActive ? 'scale(1.02)' : 'scale(1)',
                position: 'relative',
                overflow: 'hidden',
                cursor: canOpen ? 'pointer' : 'default',
                '&::before': isActive
                  ? {
                      content: '""',
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      background: `linear-gradient(135deg, transparent 0%, ${colors.border}15 100%)`,
                      pointerEvents: 'none',
                    }
                  : {},
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                  <Typography variant="h6" sx={{ fontSize: '1.5rem' }}>
                    {stage.icon}
                  </Typography>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: colors.text }}>
                      {stage.name}
                    </Typography>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', fontSize: '0.7rem' }}
                    >
                      {stage.desc}
                    </Typography>
                  </Box>
                </Box>
                {isDone && (
                  <Box
                    sx={{
                      width: 24,
                      height: 24,
                      flex: '0 0 auto',
                      borderRadius: '50%',
                      backgroundColor: audiobookColorRoles.taskStatus.completed.chipBg,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'white',
                      fontSize: '0.9rem',
                    }}
                  >
                    ✓
                  </Box>
                )}
              </Box>

              <LinearProgress
                variant="determinate"
                value={stageInfo.progress * 100}
                sx={{
                  height: 4,
                  borderRadius: 2,
                  backgroundColor: audiobookColors.surfaceBorder,
                  '& .MuiLinearProgress-bar': {
                    backgroundColor: colors.border,
                    borderRadius: 2,
                  },
                }}
              />

              <Typography
                variant="caption"
                sx={{
                  display: 'block',
                  mt: 0.5,
                  textAlign: 'right',
                  color: colors.text,
                  fontWeight: 500,
                  fontSize: '0.7rem',
                }}
              >
                {formatStageStatusText(stageInfo)}
              </Typography>

              {metricsEntries.length > 0 && (
                <Box sx={{ mt: 1, pt: 1, borderTop: `1px dashed ${audiobookColors.surfaceBorder}` }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem', lineHeight: 1.3 }}>
                    {metricsEntries.slice(0, 2).map(([key, value]) => (
                      <Box key={key} component="span" sx={{ display: 'block' }}>
                        {key}: {formatMetricPreviewValue(value)}
                      </Box>
                    ))}
                  </Typography>
                </Box>
              )}
            </Paper>
          )
        })}
      </Box>
    </Box>
  )
}

export default TaskStageDetails
