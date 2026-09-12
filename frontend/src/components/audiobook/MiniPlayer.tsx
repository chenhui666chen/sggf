import { Box, Slider, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

import { audiobookColors } from '../../pages/audiobook/audiobookTheme'

export default function MiniPlayer({
  currentTime,
  duration,
  formatTime,
  onSeekPreview,
  onSeekCommit,
}: {
  currentTime: number
  duration: number
  formatTime: (seconds: number) => string
  onSeekPreview: (nextTime: number) => void
  onSeekCommit: (nextTime: number) => void
}) {
  const { t } = useTranslation()
  return (
    <Box sx={{ px: 2, py: 1.5, borderTop: `1px solid ${audiobookColors.surfaceBorder}` }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {t('audiobook.browserPlayer.playbackProgress')}
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {formatTime(currentTime)} / {formatTime(duration)}
        </Typography>
      </Box>
      <Slider
        size="small"
        min={0}
        max={duration || 0}
        step={1}
        value={Math.min(currentTime, duration || 0)}
        onChange={(_, value) => {
          const next = Array.isArray(value) ? value[0] : value
          onSeekPreview(next)
        }}
        onChangeCommitted={(_, value) => {
          const next = Array.isArray(value) ? value[0] : value
          onSeekCommit(next)
        }}
        disabled={!duration}
      />
    </Box>
  )
}
