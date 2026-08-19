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

const resolveChapterStateChipMeta = (state: ChapterRenderState): ChapterStateChipMeta => {
  if (state.executionStatus && ACTIVE_EXECUTION_STATUSES.has(state.executionStatus)) {
    return {
      label: '生成中 · 点击进入工作台',
      color: audiobookColorRoles.taskStatus.running.text,
      backgroundColor: audiobookColorRoles.taskStatus.running.bg,
    }
  }
  switch (state.renderStatus) {
    case CHAPTER_RENDER_STATUS.RENDERED_ALL_SEED:
      return {
        label: '已生成 · 点击进入工作台',
        color: audiobookColorRoles.taskStatus.completed.text,
        backgroundColor: audiobookColorRoles.taskStatus.completed.bg,
      }
    case CHAPTER_RENDER_STATUS.RENDERED_WITH_FALLBACK:
      return {
        label: '含回退场景 · 点击进入工作台',
        color: audiobookColorRoles.reviewRisk.warning.text,
        backgroundColor: audiobookColorRoles.reviewRisk.warning.bg,
      }
    case CHAPTER_RENDER_STATUS.STALE:
      return {
        label: '已过期 · 点击进入工作台',
        color: 'text.secondary',
        backgroundColor: 'action.hover',
      }
    case CHAPTER_RENDER_STATUS.MANUAL_REVIEW_REQUIRED:
      return {
        label: '待人工评审 · 点击进入工作台',
        color: audiobookColorRoles.reviewRisk.warning.text,
        backgroundColor: audiobookColorRoles.reviewRisk.warning.bg,
      }
    case CHAPTER_RENDER_STATUS.FAILED:
      return {
        label: '生成失败 · 点击进入工作台',
        color: audiobookColorRoles.taskStatus.failed.text,
        backgroundColor: audiobookColorRoles.taskStatus.failed.bg,
      }
    default:
      // render_status 为空：历史产物（legacy_unverified），回退旧完成条件
      return {
        label: '历史产物 · 点击进入工作台',
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
              onClick={() => {
                if (generated) {
                  // 已生成章节不可勾选，但点击整行直接进入该章工作台
                  onOpenGeneratedChapter(chapter.id)
                  return
                }
                onToggleChapter(chapter.id)
              }}
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
                    ? 'rgba(100, 116, 139, 0.06)'
                    : 'transparent',
                opacity: generated ? 0.72 : 1,
                '&:last-of-type': {
                  borderBottom: 0,
                },
                '&:hover': {
                  backgroundColor: generated
                    ? 'rgba(100, 116, 139, 0.14)'
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
                    {generated && (() => {
                      const state = chapterStateById?.[chapter.id]
                      const chipMeta = state
                        ? resolveChapterStateChipMeta(state)
                        : {
                            label: '已生成 · 点击进入工作台',
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
