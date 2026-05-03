import type { ReactNode } from 'react'

import {
  Alert,
  Box,
  Button,
  Typography,
} from '@mui/material'

import { audiobookButtonSx } from './audiobookTheme'
import type { TaskStatus } from './types'

type ActiveProjectTasksAlertMode = 'background' | 'progress'

interface ActiveProjectTasksAlertProps {
  tasks: TaskStatus[]
  title: ReactNode
  description: ReactNode
  mode: ActiveProjectTasksAlertMode
  focusedTaskId?: string | null
  getTaskLabel: (task: TaskStatus) => string
  onFocusTask: (task: TaskStatus) => void
}

const getButtonVariant = (
  mode: ActiveProjectTasksAlertMode,
  isFocused: boolean,
) => {
  if (mode === 'progress' && isFocused) {
    return 'contained'
  }
  return 'outlined'
}

const getButtonSx = (
  mode: ActiveProjectTasksAlertMode,
  isFocused: boolean,
) => {
  if (mode === 'background') {
    return audiobookButtonSx.primaryOutlined
  }
  return isFocused ? audiobookButtonSx.brandContained : audiobookButtonSx.brandOutlined
}

const ActiveProjectTasksAlert = ({
  tasks,
  title,
  description,
  mode,
  focusedTaskId = null,
  getTaskLabel,
  onFocusTask,
}: ActiveProjectTasksAlertProps) => (
  <Alert severity="info" sx={{ mb: 3, alignItems: 'flex-start' }}>
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {description}
        </Typography>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {tasks.map((task) => {
          const isFocused = task.task_id === focusedTaskId
          return (
            <Button
              key={task.task_id}
              size="small"
              variant={getButtonVariant(mode, isFocused)}
              onClick={() => onFocusTask(task)}
              sx={getButtonSx(mode, isFocused)}
            >
              {getTaskLabel(task)}
            </Button>
          )
        })}
      </Box>
    </Box>
  </Alert>
)

export default ActiveProjectTasksAlert
