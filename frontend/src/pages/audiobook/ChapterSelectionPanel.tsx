import { useEffect, useRef, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'

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
import type { TranslateFn } from './audioLibraryDisplay'
import type { Chapter, ChapterRenderState } from './types'
import { CHAPTER_RENDER_STATUS } from './types'

interface ChapterSelectionPanelProps {
  chapters: Chapter[]
  selectedChapters: number[]
  generatedChapterIds: ReadonlySet<number>
  chapterStateById?: Record<number, ChapterRenderState>
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
  onOpenGeneratedChapter: (chapterId: number) => void
}

// 进行中执行态（GUIDE §2.3 章节状态表：执行中 execution_status 优先展示）
const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'pending', 'running', 'pause_requested'])

interface ChapterStateChipMeta {
  label: string
  color: string
  backgroundColor: string
}

const resolveChapterStateChipMeta = (state: ChapterRenderState, t: TranslateFn): ChapterStateChipMeta => {
  if (state.executionStatus && ACTIVE_EXECUTION_STATUSES.has(state.executionStatus)) {
    return {
      label: t('audiobook.chapterSelectionPanel.runningChip'),
      color: audiobookColorRoles.taskStatus.running.text,
      backgroundColor: audiobookColorRoles.taskStatus.running.bg,
    }
  }
  switch (state.renderStatus) {
    case CHAPTER_RENDER_STATUS.RENDERED_ALL_SEED:
      return {
        label: t('audiobook.chapterSelectionPanel.renderedChip'),
        color: audiobookColorRoles.taskStatus.completed.text,
        backgroundColor: audiobookColorRoles.taskStatus.completed.bg,
      }
    case CHAPTER_RENDER_STATUS.RENDERED_WITH_FALLBACK:
      return {
        label: t('audiobook.chapterSelectionPanel.fallbackChip'),
        color: audiobookColorRoles.reviewRisk.warning.text,
        backgroundColor: audiobookColorRoles.reviewRisk.warning.bg,
      }
    case CHAPTER_RENDER_STATUS.STALE:
      return {
        label: t('audiobook.chapterSelectionPanel.staleChip'),
        color: 'text.secondary',
        backgroundColor: 'action.hover',
      }
    case CHAPTER_RENDER_STATUS.MANUAL_REVIEW_REQUIRED:
      return {
        label: t('audiobook.chapterSelectionPanel.reviewChip'),
        color: audiobookColorRoles.reviewRisk.warning.text,
        backgroundColor: audiobookColorRoles.reviewRisk.warning.bg,
      }
    case CHAPTER_RENDER_STATUS.FAILED:
      return {
        label: t('audiobook.chapterSelectionPanel.failedChip'),
        color: audiobookColorRoles.taskStatus.failed.text,
        backgroundColor: audiobookColorRoles.taskStatus.failed.bg,
      }
    default:
      // render_status 为空：历史产物（legacy_unverified），回退旧完成条件
      return {
        label: t('audiobook.chapterSelectionPanel.legacyChip'),
        color: 'text.secondary',
        backgroundColor: 'action.hover',
      }
  }
}

const ChapterSelectionPanel = ({
  chapters,
  selectedChapters,
  generatedChapterIds,
  chapterStateById,
  onToggleChapter,
  onOpenChapterMenu,
  onOpenGeneratedChapter,
}: ChapterSelectionPanelProps) => {
  const { t } = useTranslation()
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
          ? t('audiobook.chapterSelectionPanel.selectedChapterChip', {
              number: chapters.find((chapter) => chapter.id === selectedChapterId)?.chapter_number ?? '-',
            })
          : t('audiobook.chapterSelectionPanel.noSelectionChip')}
        color={selectedChapterId ? 'primary' : 'default'}
      />
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.chapterSelectionPanel.availableCount', { total: availableCount })}
        </Typography>
        <Chip
          size="small"
          variant="outlined"
          icon={<LockOutlinedIcon />}
          label={t('audiobook.chapterSelectionPanel.generatedCount', { total: generatedCount })}
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
        backgroundColor: audiobookColors.surfaceRaised,
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
              onClick={() => {
                if (generated) {
                  // 已生成章节不可勾选，但点击整行直接进入该章工作台
                  onOpenGeneratedChapter(chapter.id)
                  return
                }
                onToggleChapter(chapter.id)
              }}
              secondaryAction={(
                <Tooltip title={t('audiobook.chapterSelectionPanel.chapterMenuTooltip')}>
                  <IconButton
                    edge="end"
                    size="small"
                    aria-label={t('audiobook.chapterSelectionPanel.chapterMenuAria', { number: chapter.chapter_number })}
                    onClick={(event) => onOpenChapterMenu(event, chapter)}
                    sx={audiobookButtonSx.neutralIcon}
                  >
                    <MoreVertIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              )}
              sx={{
                cursor: 'pointer',
                minHeight: 74,
                py: 1,
                px: 1.25,
                pr: 6,
                borderBottom: `1px solid ${audiobookColors.surfaceBorder}`,
                borderLeft: selected ? `3px solid ${audiobookColors.brand}` : '3px solid transparent',
                backgroundColor: selected
                  ? audiobookColors.brandSoft
                  : generated
                    ? audiobookColors.neutralSoft
                    : 'transparent',
                opacity: generated ? 0.72 : 1,
                '&:last-of-type': {
                  borderBottom: 0,
                },
                '&:hover': {
                  backgroundColor: generated
                    ? audiobookColors.neutralChip
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
                inputProps={{ 'aria-label': t('audiobook.chapterSelectionPanel.selectChapterAria', { number: chapter.chapter_number }) }}
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
                      {t('audiobook.chapterSelectionPanel.chapterTitle', {
                        number: chapter.chapter_number,
                        title: chapter.title,
                      })}
                    </Typography>
                    {generated && (() => {
                      const state = chapterStateById?.[chapter.id]
                      const chipMeta = state
                        ? resolveChapterStateChipMeta(state, t)
                        : {
                            label: t('audiobook.chapterSelectionPanel.renderedChip'),
                            color: audiobookColorRoles.taskStatus.completed.text,
                            backgroundColor: audiobookColorRoles.taskStatus.completed.bg,
                          }
                      return (
                        <Chip
                          size="small"
                          icon={<LockOutlinedIcon />}
                          label={chipMeta.label}
                          sx={{
                            height: 23,
                            flexShrink: 0,
                            color: chipMeta.color,
                            backgroundColor: chipMeta.backgroundColor,
                          }}
                        />
                      )
                    })()}
                  </Box>
                )}
                secondary={chapter.content ? chapter.content.slice(0, 64) : t('audiobook.chapterSelectionPanel.noContent')}
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
