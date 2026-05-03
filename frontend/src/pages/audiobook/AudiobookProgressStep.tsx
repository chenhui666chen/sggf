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
  StageConfig,
  StageInfo,
  TaskStatus,
} from './types'

interface AudiobookProgressStepProps {
  activeProjectTasks: TaskStatus[]
  activeTaskId?: string | null
  progressTaskStatus: TaskStatus
  getTaskLabel: (task: TaskStatus) => string
  onFocusTask: (task: TaskStatus) => void
  onOpenStageMetrics: (stage: StageConfig, stageInfo: StageInfo) => void
  onOpenScriptReview: () => void
}

const AudiobookProgressStep = ({
  activeProjectTasks,
  activeTaskId = null,
  progressTaskStatus,
  getTaskLabel,
  onFocusTask,
  onOpenStageMetrics,
  onOpenScriptReview,
}: AudiobookProgressStepProps) => (
  <Paper sx={{ p: 4, backgroundColor: audiobookColors.surfacePaper }}>
    {activeProjectTasks.length > 0 && (
      <ActiveProjectTasksAlert
        tasks={activeProjectTasks}
        title={`已恢复 ${activeProjectTasks.length} 个进行中的任务`}
        description="当前展示的是焦点任务，你可以在这里切换查看不同章节或不同批次任务的阶段进度。"
        mode="progress"
        focusedTaskId={activeTaskId}
        getTaskLabel={getTaskLabel}
        onFocusTask={onFocusTask}
      />
    )}

    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: 'text.primary' }}>
        当前阶段进度
      </Typography>
      <TaskStageDetails
        taskStatus={progressTaskStatus}
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
            查看剧本评审详情
          </Button>
        </Box>
      )}
    </Box>

    <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mt: 1, color: 'text.secondary' }}>
      请耐心等待，生成中请勿关闭页面...
    </Typography>
  </Paper>
)

export default AudiobookProgressStep
