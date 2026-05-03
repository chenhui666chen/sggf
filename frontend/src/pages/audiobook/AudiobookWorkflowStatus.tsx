import {
  Paper,
  Step,
  StepLabel,
  Stepper,
} from '@mui/material'

import TaskPointsPrecheckAlert from '../../components/common/TaskPointsPrecheckAlert'
import type { TaskPointsPrecheckErrorDetail } from '../../services/api'
import ActiveProjectTasksAlert from './ActiveProjectTasksAlert'
import ResumableChaptersAlert from './ResumableChaptersAlert'
import type { TaskStatus } from './types'
import type { ResumableChapterEntry } from './useAudiobookResumeCheckpoints'
import { audiobookColors } from './audiobookTheme'

const steps = ['配置音色', '生成有声书', '完成']

interface AudiobookWorkflowStatusProps {
  activeStep: number
  taskPointsPrecheckError: TaskPointsPrecheckErrorDetail | null
  activeProjectTasks: TaskStatus[]
  generating: boolean
  resumableChapterEntries: ResumableChapterEntry[]
  resumingChapterId: number | null
  resumeCheckpointLoading: boolean
  getTaskLabel: (task: TaskStatus) => string
  onCloseTaskPointsPrecheck: () => void
  onFocusActiveTask: (task: TaskStatus) => void
  onResumeChapterGeneration: (chapterId: number) => void
}

const AudiobookWorkflowStatus = ({
  activeStep,
  taskPointsPrecheckError,
  activeProjectTasks,
  generating,
  resumableChapterEntries,
  resumingChapterId,
  resumeCheckpointLoading,
  getTaskLabel,
  onCloseTaskPointsPrecheck,
  onFocusActiveTask,
  onResumeChapterGeneration,
}: AudiobookWorkflowStatusProps) => (
  <>
    <Paper sx={{ p: 3, mb: 3, backgroundColor: audiobookColors.surfacePaper }}>
      <Stepper activeStep={activeStep}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
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
        title={`当前项目下有 ${activeProjectTasks.length} 个任务仍在后台运行`}
        description="刷新后这些任务会继续被自动发现与轮询。你可以随时切回进度页查看任一任务。"
        mode="background"
        getTaskLabel={getTaskLabel}
        onFocusTask={onFocusActiveTask}
      />
    )}

    {!generating && resumableChapterEntries.length > 0 && (
      <ResumableChaptersAlert
        entries={resumableChapterEntries}
        resumingChapterId={resumingChapterId}
        resumeCheckpointLoading={resumeCheckpointLoading}
        onResumeChapterGeneration={onResumeChapterGeneration}
      />
    )}
  </>
)

export default AudiobookWorkflowStatus
