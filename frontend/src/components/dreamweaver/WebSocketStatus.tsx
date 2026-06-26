import { Chip, Tooltip } from '@mui/material'
import SyncIcon from '@mui/icons-material/Sync'
import WifiIcon from '@mui/icons-material/Wifi'
import WifiOffIcon from '@mui/icons-material/WifiOff'

interface WebSocketStatusProps {
  isConnected: boolean
  isReconnecting: boolean
  reconnectAttempts: number
}

export function WebSocketStatus({
  isConnected,
  isReconnecting,
  reconnectAttempts,
}: WebSocketStatusProps) {
  const getStatusDisplay = () => {
    if (isConnected) {
      return {
        icon: <WifiIcon sx={{ fontSize: 16 }} />,
        label: '已连接',
        color: 'success' as const,
        tooltip: 'WebSocket 连接正常',
      }
    }
    if (isReconnecting) {
      return {
        icon: <SyncIcon sx={{ fontSize: 16, animation: 'spin 1s linear infinite', '@keyframes spin': { '0%': { transform: 'rotate(0deg)' }, '100%': { transform: 'rotate(360deg)' } } }} />,
        label: `重连中(${reconnectAttempts})`,
        color: 'warning' as const,
        tooltip: `正在尝试重新连接 (${reconnectAttempts}/5)`,
      }
    }
    return {
      icon: <WifiOffIcon sx={{ fontSize: 16 }} />,
      label: '已断开',
      color: 'error' as const,
      tooltip: 'WebSocket 连接已断开',
    }
  }

  const status = getStatusDisplay()

  return (
    <Tooltip title={status.tooltip} arrow>
      <Chip
        size="small"
        icon={status.icon}
        label={status.label}
        color={status.color}
        variant="outlined"
        sx={{
          '& .MuiChip-icon': {
            ml: 0.5,
          },
        }}
      />
    </Tooltip>
  )
}
