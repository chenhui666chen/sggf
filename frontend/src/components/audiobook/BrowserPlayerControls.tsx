import { Box, IconButton, Slider, Typography } from '@mui/material'
import {
  Pause,
  PlayArrow,
  SkipNext,
  SkipPrevious,
  VolumeUp,
} from '@mui/icons-material'

import { formatBrowserPlayerTime } from './browserPlayerUtils'

interface BrowserPlayerControlsProps {
  currentTime: number
  duration: number
  volume: number
  isPlaying: boolean
  currentChapterIndex: number
  chapterCount: number
  onSeek: (event: Event, value: number | number[]) => void
  onPrevious: () => void
  onPlayPause: () => void
  onNext: () => void
  onVolumeChange: (event: Event, value: number | number[]) => void
}

const BrowserPlayerControls: React.FC<BrowserPlayerControlsProps> = ({
  currentTime,
  duration,
  volume,
  isPlaying,
  currentChapterIndex,
  chapterCount,
  onSeek,
  onPrevious,
  onPlayPause,
  onNext,
  onVolumeChange,
}) => (
  <Box sx={{ mt: 'auto' }}>
    <Slider
      value={currentTime}
      max={duration || 100}
      onChange={onSeek}
      sx={{ mb: 1 }}
    />
    <Box display="flex" alignItems="center" gap={2}>
      <Typography variant="caption" sx={{ minWidth: 50 }}>
        {formatBrowserPlayerTime(currentTime)}
      </Typography>
      <IconButton onClick={onPrevious} disabled={currentChapterIndex === 0}>
        <SkipPrevious />
      </IconButton>
      <IconButton onClick={onPlayPause} size="large">
        {isPlaying ? <Pause fontSize="large" /> : <PlayArrow fontSize="large" />}
      </IconButton>
      <IconButton onClick={onNext} disabled={currentChapterIndex >= chapterCount - 1}>
        <SkipNext />
      </IconButton>
      <Typography variant="caption" sx={{ minWidth: 50, textAlign: 'right' }}>
        {formatBrowserPlayerTime(duration)}
      </Typography>
      <Box display="flex" alignItems="center" gap={0.5} sx={{ ml: 'auto' }}>
        <VolumeUp fontSize="small" />
        <Slider
          value={volume}
          step={0.01}
          max={1}
          onChange={onVolumeChange}
          sx={{ width: 100 }}
        />
      </Box>
    </Box>
  </Box>
)

export default BrowserPlayerControls
