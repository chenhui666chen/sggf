import {
  Box,
  Typography,
  LinearProgress,
  Chip,
  Paper,
  Tooltip,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import PlayCircleIcon from '@mui/icons-material/PlayCircle'
import { Agent } from '@/store/slices/workflowSlice'

interface AgentStatusIndicatorProps {
  agent: Agent
}

export default function AgentStatusIndicator({ agent }: AgentStatusIndicatorProps) {
  const getStatusIcon = () => {
    switch (agent.status) {
      case 'completed':
        return <CheckCircleIcon sx={{ fontSize: 20, color: 'success.main' }} />
      case 'error':
        return <ErrorIcon sx={{ fontSize: 20, color: 'error.main' }} />
      case 'working':
        return <HourglassEmptyIcon sx={{ fontSize: 20, color: 'warning.main' }} />
      case 'idle':
        return <PlayCircleIcon sx={{ fontSize: 20, color: 'action.disabled' }} />
      default:
        return null
    }
  }

  const getStatusColor = () => {
    switch (agent.status) {
      case 'completed':
        return 'success'
      case 'error':
        return 'error'
      case 'working':
        return 'warning'
      case 'idle':
        return 'default'
      default:
        return 'default'
    }
  }

  const getStatusLabel = () => {
    switch (agent.status) {
      case 'completed':
        return '已完成'
      case 'error':
        return '错误'
      case 'working':
        return '工作中'
      case 'idle':
        return '就绪'
      default:
        return '未知'
    }
  }

  return (
    <Paper sx={{ p: 2, mb: 2, bgcolor: 'grey.50' }}>
      {/* Agent名称和状态 */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {getStatusIcon()}
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {agent.name}
          </Typography>
        </Box>
        <Tooltip title={agent.message || getStatusLabel()}>
          <Chip
            label={getStatusLabel()}
            size="small"
            color={getStatusColor() as any}
            variant="outlined"
          />
        </Tooltip>
      </Box>

      {/* 进度条 */}
      {agent.status === 'working' && (
        <Box sx={{ mb: 1 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
            <Typography variant="caption" color="textSecondary">
              进度
            </Typography>
            <Typography variant="caption" color="textSecondary">
              {agent.progress}%
            </Typography>
          </Box>
          <LinearProgress variant="determinate" value={agent.progress} size="small" />
        </Box>
      )}

      {/* 消息 */}
      {agent.message && (
        <Typography
          variant="caption"
          color="textSecondary"
          sx={{
            display: 'block',
            mt: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {agent.message}
        </Typography>
      )}
    </Paper>
  )
}

