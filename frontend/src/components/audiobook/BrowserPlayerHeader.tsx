import {
  Box,
  FormControl,
  IconButton,
  MenuItem,
  Select,
  Tooltip,
  Typography,
} from '@mui/material'
import SubtitlesIcon from '@mui/icons-material/Subtitles'
import { useTranslation } from 'react-i18next'

import {
  normalizeSubtitleFormat,
  type SubtitleFormat,
} from './browserPlayerUtils'

interface BrowserPlayerHeaderProps {
  projectTitle: string
  subtitleFormat: SubtitleFormat
  showSubtitles: boolean
  onSubtitleFormatChange: (subtitleFormat: SubtitleFormat) => void
  onToggleSubtitles: () => void
}

const BrowserPlayerHeader: React.FC<BrowserPlayerHeaderProps> = ({
  projectTitle,
  subtitleFormat,
  showSubtitles,
  onSubtitleFormatChange,
  onToggleSubtitles,
}) => {
  const { t } = useTranslation()
  return (
  <Box display="flex" justifyContent="space-between" alignItems="center">
    <Typography variant="h6">{projectTitle}</Typography>
    <Box display="flex" gap={1} alignItems="center">
      <FormControl size="small" sx={{ minWidth: 100 }}>
        <Select
          value={subtitleFormat}
          onChange={(event) => onSubtitleFormatChange(normalizeSubtitleFormat(event.target.value))}
        >
          <MenuItem value="srt">SRT</MenuItem>
          <MenuItem value="vtt">VTT</MenuItem>
          <MenuItem value="ass">ASS</MenuItem>
        </Select>
      </FormControl>
      <Tooltip title={showSubtitles ? t('audiobook.browserPlayer.hideSubtitles') : t('audiobook.browserPlayer.showSubtitles')}>
        <IconButton
          color={showSubtitles ? 'primary' : 'default'}
          onClick={onToggleSubtitles}
        >
          <SubtitlesIcon />
        </IconButton>
      </Tooltip>
    </Box>
  </Box>
  )
}

export default BrowserPlayerHeader
