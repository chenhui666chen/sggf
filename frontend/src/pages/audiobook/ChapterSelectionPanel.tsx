import type { MouseEvent } from 'react'

import {
  Box,
  Button,
  Checkbox,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
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
    <Box
      sx={{
        mb: 1.5,
        display: 'flex',
        justifyContent: 'space-between',
        gap: 1,
        alignItems: 'center',
        flexWrap: 'wrap',
      }}
    >
      <Chip
        size="small"
        variant="outlined"
        label={`${selectedChapters.length}/${chapters.length} 已选`}
        color={selectedChapters.length > 0 ? 'primary' : 'default'}
      />
      <Button
        variant="outlined"
        size="small"
        onClick={onToggleAll}
        sx={audiobookButtonSx.neutralOutlined}
      >
        {selectedChapters.length === chapters.length ? '取消全选' : '全选'}
      </Button>
    </Box>

    <Box
      sx={{
        maxHeight: { xs: 360, lg: 430 },
        overflow: 'auto',
        borderRadius: 1.5,
        border: `1px solid ${audiobookColors.surfaceBorder}`,
        backgroundColor: 'rgba(255,255,255,0.7)',
      }}
    >
      <List disablePadding>
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
              py: 1,
              px: 1.25,
              borderBottom: `1px solid ${audiobookColors.surfaceBorder}`,
              '&:last-of-type': {
                borderBottom: 0,
              },
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
              primaryTypographyProps={{
                sx: {
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  pr: 1,
                },
              }}
              secondaryTypographyProps={{
                sx: {
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  pr: 1,
                },
              }}
            />
          </ListItem>
        ))}
      </List>
    </Box>
  </>
)

export default ChapterSelectionPanel
