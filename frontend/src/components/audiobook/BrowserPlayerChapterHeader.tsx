import { Box, Button, Chip, Typography } from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import { useTranslation } from 'react-i18next'

import type { SubtitleFormat } from './browserPlayerUtils'
import type { BrowserPlayerChapter } from './browserPlayerTypes'

interface BrowserPlayerChapterHeaderProps {
  currentChapter?: BrowserPlayerChapter
  currentChapterIndex: number
  usingLocalAsset: boolean
  subtitleFormat: SubtitleFormat
  onDownloadSubtitle: () => void
  onDownloadAudacityLabels: () => void
}

const BrowserPlayerChapterHeader: React.FC<BrowserPlayerChapterHeaderProps> = ({
  currentChapter,
  currentChapterIndex,
  usingLocalAsset,
  subtitleFormat,
  onDownloadSubtitle,
  onDownloadAudacityLabels,
}) => {
  const { t } = useTranslation()
  return (
  <Box sx={{ mb: 2 }}>
    <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
      <Typography variant="h6">
        {t('audiobook.browserPlayer.chapterHeaderTitle', { number: currentChapter?.chapter_number || currentChapterIndex + 1, title: currentChapter?.chapter_title || '' })}
      </Typography>
      {usingLocalAsset && <Chip label={t('audiobook.browserPlayer.localAudio')} size="small" color="success" variant="outlined" />}
    </Box>
    {(currentChapter?.has_subtitle || currentChapter?.audacity_labels_url) && (
      <Box display="flex" gap={1} flexWrap="wrap" sx={{ mt: 0.5 }}>
        {currentChapter?.has_subtitle && (
          <Button
            size="small"
            startIcon={<DownloadIcon />}
            onClick={onDownloadSubtitle}
          >
            {t('audiobook.browserPlayer.downloadSubtitle', { format: subtitleFormat.toUpperCase() })}
          </Button>
        )}
        {currentChapter?.audacity_labels_url && (
          <Button
            size="small"
            startIcon={<DownloadIcon />}
            onClick={onDownloadAudacityLabels}
          >
            {t('audiobook.browserPlayer.downloadLabels')}
          </Button>
        )}
      </Box>
    )}
  </Box>
  )
}

export default BrowserPlayerChapterHeader
