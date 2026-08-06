import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline'
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline'
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
  pauseResuming,
  getTaskLabel,
  onFocusTask,
  onOpenStageMetrics,
  onOpenScriptReview,
  onBack,
  onPauseTask,
  onResumeTask,
}: AudiobookProgressStepProps) => {
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
        返回配置
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
            {pauseResuming ? '继续中...' : '继续生成'}
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
            {isPauseRequested ? '暂停中...' : '暂停生成'}
          </Button>
        )}
      </Box>
    </Box>

    {isPaused && (
      <Typography variant="body2" sx={{ mb: 2, color: 'warning.main' }}>
        任务已暂停，已完成章节的进度已保存。点击“恢复生成”将从暂停处继续。
      </Typography>
    )}
    {isPauseRequested && (
      <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
        已请求暂停：当前模型或语音请求完成后会立即停止。点击“继续生成”可撤销暂停请求。
      </Typography>
    )}

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
      生成任务在后台运行，您可以随时返回或关闭页面，任务会继续执行。
    </Typography>
  </Paper>
  )
}

export default AudiobookProgressStep
