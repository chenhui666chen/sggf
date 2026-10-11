import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Paper,
  Typography,
} from '@mui/material'

import ActiveProjectTasksAlert from './ActiveProjectTasksAlert'
import TaskStageDetails from './TaskStageDetails'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type {
  AudioEngineMode,
  StageConfig,
  StageInfo,
  TaskStatus,
} from './types'

interface AudiobookProgressStepProps {
  activeProjectTasks: TaskStatus[]
  activeTaskId?: string | null
  progressTaskStatus: TaskStatus
  engineMode?: AudioEngineMode | null
  pauseResuming: boolean
  getTaskLabel: (task: TaskStatus) => string
  onFocusTask: (task: TaskStatus) => void
  onOpenStageMetrics: (stage: StageConfig, stageInfo: StageInfo) => void
  onOpenScriptReview: () => void
  onBack: () => void
  onPauseTask: () => void
  onResumeTask: () => void
}

const AudiobookProgressStep = ({
  activeProjectTasks,
  activeTaskId = null,
  progressTaskStatus,
  engineMode = null,
  pauseResuming,
  getTaskLabel,
  onFocusTask,
  onOpenStageMetrics,
  onOpenScriptReview,
  onBack,
  onPauseTask,
  onResumeTask,
}: AudiobookProgressStepProps) => {
  const { t } = useTranslation()
  const taskStatus = progressTaskStatus.status
  const isPaused = taskStatus === 'paused'
  const isPauseRequested = taskStatus === 'pause_requested'
  const canPause = taskStatus === 'running' || taskStatus === 'pending'

  return (
  <Paper sx={{ p: 4, backgroundColor: audiobookColors.surfacePaper }}>
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2, gap: 1.5, flexWrap: 'wrap' }}>
      <Button
        size="small"
        startIcon={<ArrowBackIcon />}
        onClick={onBack}
        sx={audiobookButtonSx.neutralOutlined}
        variant="outlined"
      >
        {t('audiobook.audiobookProgressStep.backToConfig')}
      </Button>
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
        {isPaused || isPauseRequested ? (
          <Button
            variant="contained"
            size="small"
            startIcon={<PlayCircleOutlineIcon />}
            onClick={onResumeTask}
            disabled={pauseResuming}
            sx={audiobookButtonSx.brandContained}
          >
            {pauseResuming
              ? t('audiobook.audiobookProgressStep.resuming')
              : t('audiobook.audiobookProgressStep.resumeLabel')}
          </Button>
        ) : (
          <Button
            variant="outlined"
            size="small"
            startIcon={<PauseCircleOutlineIcon />}
            onClick={onPauseTask}
            disabled={!canPause || isPauseRequested}
            sx={audiobookButtonSx.warningOutlined}
          >
            {isPauseRequested
              ? t('audiobook.audiobookProgressStep.pausing')
              : t('audiobook.audiobookProgressStep.pauseLabel')}
          </Button>
        )}
      </Box>
    </Box>

    {isPaused && (
      <Typography variant="body2" sx={{ mb: 2, color: 'warning.main' }}>
        {t('audiobook.audiobookProgressStep.pausedHint')}
      </Typography>
    )}
    {isPauseRequested && (
      <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
        {t('audiobook.audiobookProgressStep.pauseRequestedHint')}
      </Typography>
    )}

    {activeProjectTasks.length > 0 && (
      <ActiveProjectTasksAlert
        tasks={activeProjectTasks}
        title={t('audiobook.audiobookProgressStep.restoredTasksTitle', { total: activeProjectTasks.length })}
        description={t('audiobook.audiobookProgressStep.focusedTaskDescription')}
        mode="progress"
        focusedTaskId={activeTaskId}
        getTaskLabel={getTaskLabel}
        onFocusTask={onFocusTask}
      />
    )}

    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: 'text.primary' }}>
        {t('audiobook.audiobookProgressStep.currentStageTitle')}
      </Typography>
      <TaskStageDetails
        taskStatus={progressTaskStatus}
        engineMode={engineMode}
        onOpenStageMetrics={onOpenStageMetrics}
      />
      {progressTaskStatus.stages?.quality_review?.status === 'completed' && (
        <Box sx={{ mt: 3, textAlign: 'center' }}>
          <Button
            variant="outlined"
            size="medium"
            onClick={onOpenScriptReview}
            sx={audiobookButtonSx.brandOutlined}
          >
            {t('audiobook.audiobookProgressStep.viewReviewDetails')}
          </Button>
        </Box>
      )}
    </Box>

    <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mt: 1, color: 'text.secondary' }}>
      {t('audiobook.audiobookProgressStep.backgroundHint')}
    </Typography>
  </Paper>
  )
}

export default AudiobookProgressStep
