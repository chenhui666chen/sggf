import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Paper,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material'

import TaskPointsPrecheckAlert from '../../components/common/TaskPointsPrecheckAlert'
import type { TaskPointsPrecheckErrorDetail } from '../../services/api'
import ActiveProjectTasksAlert from './ActiveProjectTasksAlert'
import ResumableChaptersAlert from './ResumableChaptersAlert'
import type { TaskStatus } from './types'
import type { AudioEngineMode } from './types'
import type { ResumableChapterEntry } from './useAudiobookResumeCheckpoints'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'

interface AudiobookWorkflowStatusProps {
  activeStep: number
  lastGenerationMode: 'full' | 'script_only'
  audioEngineMode: AudioEngineMode
  hasChapterAudios: boolean
  taskPointsPrecheckError: TaskPointsPrecheckErrorDetail | null
  activeProjectTasks: TaskStatus[]
  generating: boolean
  resumableChapterEntries: ResumableChapterEntry[]
  resumingChapterId: number | null
  resumeCheckpointLoading: boolean
  audiobookProjectId: number
  pausedProjectTasks: TaskStatus[]
  pauseResuming: boolean
  getTaskLabel: (task: TaskStatus) => string
  onCloseTaskPointsPrecheck: () => void
  onFocusActiveTask: (task: TaskStatus) => void
  onResumeChapterGeneration: (chapterId: number) => void
  onResumePausedTask: (taskId: string) => void
}

const AudiobookWorkflowStatus = ({
  activeStep,
  lastGenerationMode,
  audioEngineMode,
  hasChapterAudios,
  taskPointsPrecheckError,
  activeProjectTasks,
  generating,
  resumableChapterEntries,
  resumingChapterId,
  resumeCheckpointLoading,
  audiobookProjectId,
  pausedProjectTasks,
  pauseResuming,
  getTaskLabel,
  onCloseTaskPointsPrecheck,
  onFocusActiveTask,
  onResumeChapterGeneration,
  onResumePausedTask,
}: AudiobookWorkflowStatusProps) => {
  const { t } = useTranslation()
  // 已有可播放章节音频时（剧本先行流程生成/混音完成），
  // 步骤条同步展示音频流程，避免停留在“审阅场景剧本”误导用户
  const steps = lastGenerationMode === 'script_only' && !hasChapterAudios
    ? ['audiobook.workflowStatus.stepChapterVoice', 'audiobook.workflowStatus.stepGenerateScript', 'audiobook.workflowStatus.stepReviewScript']
    : audioEngineMode === 'seed_scene'
      ? ['audiobook.workflowStatus.stepScriptApproved', 'audiobook.workflowStatus.stepGenerateAudio', 'audiobook.workflowStatus.stepAudioComplete']
      : ['audiobook.workflowStatus.stepScriptApproved', 'audiobook.workflowStatus.stepGenerateStems', 'audiobook.workflowStatus.stepAudioComplete']

  return (
    <>
    <Paper sx={{ p: 3, mb: 3, backgroundColor: audiobookColors.surfacePaper }}>
      <Stepper activeStep={activeStep}>
        {steps.map((labelKey) => (
          <Step key={labelKey}>
            <StepLabel>{t(labelKey)}</StepLabel>
          </Step>
        ))}
      </Stepper>
    </Paper>

    {taskPointsPrecheckError && (
      <TaskPointsPrecheckAlert
        detail={taskPointsPrecheckError}
        onClose={onCloseTaskPointsPrecheck}
        sx={{ mb: 3 }}
      />
    )}

    {activeProjectTasks.length > 0 && activeStep !== 1 && (
      <ActiveProjectTasksAlert
        tasks={activeProjectTasks}
        title={t('audiobook.workflowStatus.activeTasksTitle', { count: activeProjectTasks.length })}
        description={t('audiobook.workflowStatus.activeTasksDescription')}
        mode="background"
        getTaskLabel={getTaskLabel}
        onFocusTask={onFocusActiveTask}
      />
    )}

    {pausedProjectTasks.length > 0 && (
      <Alert severity="warning" sx={{ mb: 3, alignItems: 'flex-start' }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {t('audiobook.workflowStatus.pausedTasksTitle', { count: pausedProjectTasks.length })}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('audiobook.workflowStatus.pausedTasksCaption')}
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {pausedProjectTasks.map((task) => (
              <Button
                key={task.task_id}
                size="small"
                variant="contained"
                disabled={pauseResuming || task.status === 'pause_requested'}
                onClick={() => onResumePausedTask(task.task_id)}
                sx={audiobookButtonSx.brandContained}
              >
                {task.status === 'pause_requested' ? t('audiobook.workflowStatus.pausing') : t('audiobook.workflowStatus.resumeTask', { task: getTaskLabel(task) })}
              </Button>
            ))}
          </Box>
        </Box>
      </Alert>
    )}

    {!generating && resumableChapterEntries.length > 0 && (
      <ResumableChaptersAlert
        entries={resumableChapterEntries}
        resumingChapterId={resumingChapterId}
        resumeCheckpointLoading={resumeCheckpointLoading}
        audiobookProjectId={audiobookProjectId}
        onResumeChapterGeneration={onResumeChapterGeneration}
      />
    )}
    </>
  )
}

export default AudiobookWorkflowStatus
