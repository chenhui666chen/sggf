import {
  Box,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'

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
}) => (
  <Box width={280} sx={{ overflowY: 'auto', borderRight: 1, borderColor: 'divider', pr: 2 }}>
    <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
      章节列表
    </Typography>
    <List dense>
      {chapters.map((chapter, index) => (
        <ListItem key={chapter.chapter_id} disablePadding sx={{ mb: 0.5 }}>
          <ListItemButton
            selected={currentChapterIndex === index}
            onClick={() => onSelectChapter(index)}
          >
            <ListItemText
              primary={`第${chapter.chapter_number || index + 1}章`}
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

export default BrowserPlayerChapterList
