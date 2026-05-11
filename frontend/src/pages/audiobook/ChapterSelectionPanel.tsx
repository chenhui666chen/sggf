import type { MouseEvent } from 'react'

import {
  Box,
  Button,
  Checkbox,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Paper,
  Typography,
} from '@mui/material'
import MoreVertIcon from '@mui/icons-material/MoreVert'

import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type { Chapter } from './types'

interface ChapterSelectionPanelProps {
  chapters: Chapter[]
  selectedChapters: number[]
  onToggleAll: () => void
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
}

const ChapterSelectionPanel = ({
  chapters,
  selectedChapters,
  onToggleAll,
  onToggleChapter,
  onOpenChapterMenu,
}: ChapterSelectionPanelProps) => (
  <>
    <Typography variant="subtitle1" sx={{ mb: 1 }}>
      章节选择
    </Typography>

    <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
      <Button
        variant="outlined"
        size="small"
        onClick={onToggleAll}
        sx={audiobookButtonSx.neutralOutlined}
      >
        {selectedChapters.length === chapters.length ? '取消全选' : '全选'}
      </Button>
    </Box>

    <Paper
      variant="outlined"
      sx={{
        maxHeight: 400,
        overflow: 'auto',
      }}
    >
      <List>
        {chapters.map((chapter) => (
          <ListItem
            key={chapter.id}
            component="div"
            onClick={() => onToggleChapter(chapter.id)}
            secondaryAction={
              <IconButton
                edge="end"
                size="small"
                onClick={(event) => onOpenChapterMenu(event, chapter)}
                sx={audiobookButtonSx.neutralIcon}
              >
                <MoreVertIcon fontSize="small" />
              </IconButton>
            }
            sx={{
              cursor: 'pointer',
              '&:hover': {
                backgroundColor: audiobookColors.brandSoft,
              },
            }}
          >
            <Checkbox
              edge="start"
              checked={selectedChapters.includes(chapter.id)}
              tabIndex={-1}
              disableRipple
              color="primary"
            />
            <ListItemText
              primary={`第${chapter.chapter_number}章 - ${chapter.title}`}
              secondary={chapter.content ? `${chapter.content.slice(0, 50)}...` : '暂无内容'}
            />
          </ListItem>
        ))}
      </List>
    </Paper>
  </>
)

export default ChapterSelectionPanel
