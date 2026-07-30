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
import type { AudioEngineMode } from './types'
import type { ResumableChapterEntry } from './useAudiobookResumeCheckpoints'
import { audiobookColors } from './audiobookTheme'

interface AudiobookWorkflowStatusProps {
  activeStep: number
  lastGenerationMode: 'full' | 'script_only'
  audioEngineMode: AudioEngineMode
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
  lastGenerationMode,
  audioEngineMode,
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
}: AudiobookWorkflowStatusProps) => {
  const steps = lastGenerationMode === 'script_only'
    ? ['章节与声音', '生成场景剧本', '审阅场景剧本']
    : audioEngineMode === 'seed_scene'
      ? ['剧本已批准', '生成场景音频', '音频完成']
      : ['剧本已批准', '生成分轨音频', '音频完成']

  return (
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
}

export default AudiobookWorkflowStatus
