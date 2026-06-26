import { Box, IconButton, Slider, Tooltip, Typography } from '@mui/material'
import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import SkipNextIcon from '@mui/icons-material/SkipNext'
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious'
import VolumeUpIcon from '@mui/icons-material/VolumeUp'

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
}) => {
  const previousDisabled = currentChapterIndex === 0
  const nextDisabled = currentChapterIndex >= chapterCount - 1

  return (
    <Box sx={{ mt: 'auto' }}>
      <Slider
        value={currentTime}
        max={duration || 100}
        onChange={onSeek}
        sx={{ mb: 1 }}
      />
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: { xs: 1, sm: 2 },
          flexWrap: 'wrap',
        }}
      >
        <Typography variant="caption" sx={{ minWidth: 50 }}>
          {formatBrowserPlayerTime(currentTime)}
        </Typography>
        <Tooltip title={previousDisabled ? '当前已经是第一章' : '上一章'}>
          <span>
            <IconButton onClick={onPrevious} disabled={previousDisabled}>
              <SkipPreviousIcon />
            </IconButton>
          </span>
        </Tooltip>
        <IconButton onClick={onPlayPause} size="large">
          {isPlaying ? <PauseIcon fontSize="large" /> : <PlayArrowIcon fontSize="large" />}
        </IconButton>
        <Tooltip title={nextDisabled ? '当前已经是最后一章' : '下一章'}>
          <span>
            <IconButton onClick={onNext} disabled={nextDisabled}>
              <SkipNextIcon />
            </IconButton>
          </span>
        </Tooltip>
        <Typography variant="caption" sx={{ minWidth: 50, textAlign: 'right' }}>
          {formatBrowserPlayerTime(duration)}
        </Typography>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            ml: { xs: 0, sm: 'auto' },
            width: { xs: '100%', sm: 'auto' },
            minWidth: { xs: 180, sm: 0 },
          }}
        >
          <VolumeUpIcon fontSize="small" />
          <Slider
            value={volume}
            step={0.01}
            max={1}
            onChange={onVolumeChange}
            sx={{ width: { xs: '100%', sm: 100 } }}
          />
        </Box>
      </Box>
    </Box>
  )
}

export default BrowserPlayerControls
