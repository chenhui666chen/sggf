import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import { formatBrowserPlayerTime } from './browserPlayerUtils'
import type { BrowserPlayerChapter } from './browserPlayerTypes'

interface BrowserPlayerChapterListProps {
  chapters: BrowserPlayerChapter[]
  currentChapterIndex: number
  onSelectChapter: (chapterIndex: number) => void
}

const BrowserPlayerChapterList: React.FC<BrowserPlayerChapterListProps> = ({
  chapters,
  currentChapterIndex,
  onSelectChapter,
}) => {
  const { t } = useTranslation()
  return (
  <Box
    sx={{
      width: { xs: '100%', md: 280 },
      flexShrink: 0,
      maxHeight: { xs: 220, md: 'none' },
      overflowY: 'auto',
      borderRight: { xs: 0, md: 1 },
      borderBottom: { xs: 1, md: 0 },
      borderColor: 'divider',
      pr: { xs: 0, md: 2 },
      pb: { xs: 1.5, md: 0 },
    }}
  >
    <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
      {t('audiobook.browserPlayer.chapterListTitle')}
    </Typography>
    <List dense>
      {chapters.map((chapter, index) => (
        <ListItem key={chapter.chapter_id} disablePadding sx={{ mb: 0.5 }}>
          <ListItemButton
            selected={currentChapterIndex === index}
            onClick={() => onSelectChapter(index)}
          >
            <ListItemText
              primary={t('audiobook.chapterNumber', { number: chapter.chapter_number || index + 1 })}
              secondary={chapter.chapter_title || ''}
              primaryTypographyProps={{
                variant: 'body2',
                sx: { fontWeight: currentChapterIndex === index ? 600 : 400 },
              }}
              secondaryTypographyProps={{
                variant: 'caption',
              }}
            />
            <Typography variant="caption" color="text.secondary">
              {formatBrowserPlayerTime(chapter.duration || 0)}
            </Typography>
          </ListItemButton>
        </ListItem>
      ))}
    </List>
  </Box>
  )
}

export default BrowserPlayerChapterList
