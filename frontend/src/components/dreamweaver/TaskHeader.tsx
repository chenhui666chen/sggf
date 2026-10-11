import { Box, Chip, Stack, Typography } from '@mui/material'
import { getStageDisplayName } from '@/utils/timeEstimate'
import { estimateRemainingTime, formatEstimatedTime } from '@/utils/timeEstimate'
import { isTerminalStage, isWaitingStage } from '@/constants/dreamweaver'
import { useTranslation } from 'react-i18next'

interface TaskHeaderProps {
  runId: string | null
  taskStage: string | null
  taskState: string | null
  taskProgress: number | null
  taskStatus: string | null
  waitingApproval: boolean
}

export function TaskHeader({
  runId,
  taskStage,
  taskState,
  taskProgress,
  taskStatus,
  waitingApproval,
}: TaskHeaderProps) {
  const { t } = useTranslation()
  const estimate = estimateRemainingTime(taskStage, taskProgress)
  const stageDisplay = getStageDisplayName(taskStage || '', t)
  const isTerminal = isTerminalStage(taskStage)
  const isWaiting = isWaitingStage(taskStage)

  const progressPercent = typeof taskProgress === 'number' ? Math.round(taskProgress) : null

  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        {runId && (
          <Chip
            size="small"
            label={`${t('dreamweaverTaskHeader.runIdLabel')}: ${runId.slice(0, 8)}...`}
            variant="outlined"
          />
        )}

        <Chip
          size="small"
          label={`${t('dreamweaverTaskHeader.stageLabel')}: ${stageDisplay}`}
          variant="outlined"
          color={isTerminal ? 'success' : isWaiting ? 'warning' : 'primary'}
        />

        {taskState && (
          <Chip
            size="small"
            label={`${t('dreamweaverTaskHeader.stateLabel')}: ${taskState}`}
            variant="outlined"
          />
        )}

        {progressPercent !== null && progressPercent > 0 && (
          <Chip
            size="small"
            label={`${t('dreamweaverTaskHeader.progressLabel')}: ${progressPercent}%`}
            variant="outlined"
          />
        )}

        {estimate && estimate.estimatedMinutes > 0 && !isTerminal && (
          <Chip
            size="small"
            label={`${t('dreamweaverTaskHeader.estimatedRemainingLabel')}: ${formatEstimatedTime(estimate.estimatedMinutes, t)}`}
            variant="outlined"
            color={estimate.confidence === 'high' ? 'success' : estimate.confidence === 'low' ? 'warning' : 'default'}
          />
        )}

        {waitingApproval && (
          <Chip
            size="small"
            label={t('dreamweaverTaskHeader.waitingApproval')}
            color="warning"
          />
        )}

        {taskStatus && (
          <Typography variant="caption" color="text.secondary">
            {t('dreamweaverTaskHeader.taskStatusLabel')}: {taskStatus}
          </Typography>
        )}
      </Stack>
    </Box>
  )
}
