import { useEffect, useRef, type MouseEvent } from 'react'

import {
  Box,
  Chip,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Radio,
  Tooltip,
  Typography,
} from '@mui/material'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import MoreVertIcon from '@mui/icons-material/MoreVert'

import { audiobookButtonSx, audiobookColors, audiobookColorRoles } from './audiobookTheme'
import type { Chapter } from './types'

interface ChapterSelectionPanelProps {
  chapters: Chapter[]
  selectedChapters: number[]
  generatedChapterIds: ReadonlySet<number>
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
}

const ChapterSelectionPanel = ({
  chapters,
  selectedChapters,
  generatedChapterIds,
  onToggleChapter,
  onOpenChapterMenu,
}: ChapterSelectionPanelProps) => {
  const listContainerRef = useRef<HTMLDivElement | null>(null)
  const selectedChapterId = selectedChapters[0]
  const generatedCount = chapters.filter((chapter) => generatedChapterIds.has(chapter.id)).length
  const availableCount = chapters.length - generatedCount

  useEffect(() => {
    const container = listContainerRef.current
    if (!container || !selectedChapterId) return
    const selectedRow = container.querySelector<HTMLElement>(`[data-chapter-id="${selectedChapterId}"]`)
    if (!selectedRow) return
    container.scrollTop = Math.max(
      0,
      selectedRow.offsetTop - (container.clientHeight - selectedRow.offsetHeight) / 2,
    )
  }, [selectedChapterId])

  return <>
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
        label={selectedChapterId
          ? `已选第 ${chapters.find((chapter) => chapter.id === selectedChapterId)?.chapter_number ?? '-'} 章`
          : '未选择章节'}
        color={selectedChapterId ? 'primary' : 'default'}
      />
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" color="text.secondary">
          可生成 {availableCount} 章
        </Typography>
        <Chip
          size="small"
          variant="outlined"
          icon={<LockOutlinedIcon />}
          label={`已生成 ${generatedCount}`}
          sx={{ height: 24 }}
        />
      </Box>
    </Box>

    <Box
      ref={listContainerRef}
      sx={{
        height: { xs: 340, lg: 370 },
        overflow: 'auto',
        borderRadius: 1.5,
        border: `1px solid ${audiobookColors.surfaceBorder}`,
        backgroundColor: 'rgba(255,255,255,0.7)',
        scrollBehavior: 'smooth',
      }}
    >
      <List disablePadding sx={{ minHeight: '100%', display: 'flex', flexDirection: 'column', justifyContent: chapters.length <= 3 ? 'center' : 'flex-start' }}>
        {chapters.map((chapter) => {
          const generated = generatedChapterIds.has(chapter.id)
          const selected = selectedChapterId === chapter.id
          return (
            <ListItem
              key={chapter.id}
              data-chapter-id={chapter.id}
              component="div"
              aria-disabled={generated}
              onClick={generated ? undefined : () => onToggleChapter(chapter.id)}
              secondaryAction={(
                <Tooltip title="章节操作">
                  <IconButton
                    edge="end"
                    size="small"
                    aria-label={`第${chapter.chapter_number}章操作`}
                    onClick={(event) => onOpenChapterMenu(event, chapter)}
                    sx={audiobookButtonSx.neutralIcon}
                  >
                    <MoreVertIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              sx={{
                cursor: generated ? 'default' : 'pointer',
                minHeight: 74,
                py: 1,
                px: 1.25,
                pr: 6,
                borderBottom: `1px solid ${audiobookColors.surfaceBorder}`,
                borderLeft: selected ? `3px solid ${audiobookColors.brand}` : '3px solid transparent',
                backgroundColor: selected
                  ? audiobookColors.brandSoft
                  : generated
                    ? 'rgba(100, 116, 139, 0.06)'
                    : 'transparent',
                opacity: generated ? 0.72 : 1,
                '&:last-of-type': {
                  borderBottom: 0,
                },
                '&:hover': {
                  backgroundColor: generated
                    ? 'rgba(100, 116, 139, 0.06)'
                    : audiobookColors.brandSoft,
                },
              }}
            >
              <Radio
                edge="start"
                checked={selected}
                disabled={generated}
                tabIndex={-1}
                disableRipple
                color="primary"
                inputProps={{ 'aria-label': `选择第${chapter.chapter_number}章` }}
              />
              <ListItemText
                primary={(
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        minWidth: 0,
                        flex: 1,
                        fontWeight: 700,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      第{chapter.chapter_number}章 · {chapter.title}
                    </Typography>
                    {generated && (
                      <Chip
                        size="small"
                        icon={<LockOutlinedIcon />}
                        label="已生成"
                        sx={{
                          height: 23,
                          flexShrink: 0,
                          color: audiobookColorRoles.taskStatus.completed.text,
                          backgroundColor: audiobookColorRoles.taskStatus.completed.bg,
                        }}
                      />
                    )}
                  </Box>
                )}
                secondary={chapter.content ? chapter.content.slice(0, 64) : '暂无内容'}
                secondaryTypographyProps={{
                  sx: {
                    mt: 0.35,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  },
                }}
              />
            </ListItem>
          )
        })}
      </List>
    </Box>
  </>
}

export default ChapterSelectionPanel
