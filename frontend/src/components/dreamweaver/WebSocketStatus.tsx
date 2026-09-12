import { Chip, Tooltip } from '@mui/material'
import SyncIcon from '@mui/icons-material/Sync'
import WifiIcon from '@mui/icons-material/Wifi'
import WifiOffIcon from '@mui/icons-material/WifiOff'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
  const getStatusDisplay = () => {
    if (isConnected) {
      return {
        icon: <WifiIcon sx={{ fontSize: 16 }} />,
        label: t('dreamweaverWs.statusConnected'),
        color: 'success' as const,
        tooltip: t('dreamweaverWs.statusConnectedTooltip'),
      }
    }
    if (isReconnecting) {
      return {
        icon: <SyncIcon sx={{ fontSize: 16, animation: 'spin 1s linear infinite', '@keyframes spin': { '0%': { transform: 'rotate(0deg)' }, '100%': { transform: 'rotate(360deg)' } } }} />,
        label: t('dreamweaverWs.statusReconnecting', { attempts: reconnectAttempts }),
        color: 'warning' as const,
        tooltip: t('dreamweaverWs.statusReconnectingTooltip', { attempts: reconnectAttempts }),
      }
    }
    return {
      icon: <WifiOffIcon sx={{ fontSize: 16 }} />,
      label: t('dreamweaverWs.statusDisconnected'),
      color: 'error' as const,
      tooltip: t('dreamweaverWs.statusDisconnectedTooltip'),
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
