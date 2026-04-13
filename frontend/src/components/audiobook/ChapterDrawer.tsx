import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import PauseIcon from '@mui/icons-material/Pause'
import PlayIcon from '@mui/icons-material/PlayArrow'
import SwapVertIcon from '@mui/icons-material/SwapVert'
import MiniPlayer from './MiniPlayer'
import type {
  AudiobookProjectSummary,
  Chapter,
  ChapterAudio,
  ChapterAudioDeleteCandidate,
  MergedChapterAudioRef,
  Project,
} from '@/types/audiobook'

export default function ChapterDrawer({
  open,
  project,
  audiobookProject,
  loading,
  error,
  chapters,
  mergedChapterAudiosByNumber,
  chapterSortOrder,
  formatTime,
  playerIsPlaying,
  playerCurrentTime,
  playerDuration,
  playingChapterNumber,
  onClose,
  onPlayChapter,
  onToggleSortOrder,
  onSeekPreview,
  onSeekCommit,
  onRequestDeleteAudiobook,
  onRequestDeleteChapterAudio,
}: {
  open: boolean
  project: Project | null
  audiobookProject: AudiobookProjectSummary | null
  loading: boolean
  error: string | null
  chapters: Chapter[]
  mergedChapterAudiosByNumber: Record<number, MergedChapterAudioRef>
  chapterSortOrder: 'asc' | 'desc'
  formatTime: (seconds: number) => string
  playerIsPlaying: boolean
  playerCurrentTime: number
  playerDuration: number
  playingChapterNumber: number | null
  onClose: () => void
  onPlayChapter: (chapterNumber: number) => Promise<void>
  onToggleSortOrder: () => void
  onSeekPreview: (nextTime: number) => void
  onSeekCommit: (nextTime: number) => void
  onRequestDeleteAudiobook: (project: Project, audiobookProject: AudiobookProjectSummary) => void
  onRequestDeleteChapterAudio: (candidate: ChapterAudioDeleteCandidate) => void
}) {
  const sortedChapters = useMemo(() => {
    const next = [...chapters]
    next.sort((a, b) => {
      const diff = a.chapter_number - b.chapter_number
      return chapterSortOrder === 'asc' ? diff : -diff
    })
    return next
  }, [chapters, chapterSortOrder])

  const [drawerMenuAnchorEl, setDrawerMenuAnchorEl] = useState<null | HTMLElement>(null)
  const [chapterMenuAnchorEl, setChapterMenuAnchorEl] = useState<null | HTMLElement>(null)
  const [chapterAudioToDelete, setChapterAudioToDelete] = useState<ChapterAudioDeleteCandidate | null>(null)

  const handleOpenDrawerMenu = (event: React.MouseEvent<HTMLElement>) => {
    event.stopPropagation()
    setDrawerMenuAnchorEl(event.currentTarget)
  }
  const handleCloseDrawerMenu = () => setDrawerMenuAnchorEl(null)

  const handleRequestDeleteAudiobook = () => {
    handleCloseDrawerMenu()
    if (!project || !audiobookProject) return
    onRequestDeleteAudiobook(project, audiobookProject)
  }

  const handleOpenChapterMenu = (
    event: React.MouseEvent<HTMLElement>,
    chapter: Chapter,
    chapterAudio: ChapterAudio | undefined,
  ) => {
    event.stopPropagation()
    if (!chapterAudio) return
    setChapterMenuAnchorEl(event.currentTarget)
    setChapterAudioToDelete({
      ...chapterAudio,
      chapterTitle: chapter.title,
      chapterNumber: chapter.chapter_number,
    })
  }

  const handleCloseChapterMenu = () => setChapterMenuAnchorEl(null)

  const handleRequestDeleteChapterAudio = () => {
    handleCloseChapterMenu()
    if (!chapterAudioToDelete) return
    onRequestDeleteChapterAudio(chapterAudioToDelete)
  }

  return (
    <>
      <Drawer anchor="right" open={open} onClose={onClose}>
        <Box
          sx={{
            width: { xs: '100vw', sm: 420 },
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                章节目录
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  color: 'text.secondary',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: 260,
                }}
              >
                {project?.title || ''}
              </Typography>
              <Typography variant="caption" sx={{ mt: 1, display: 'block', color: 'text.secondary' }}>
                音频来源：跨生成记录合并（按章节编号取最新音频）
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Tooltip title={chapterSortOrder === 'asc' ? '切换为倒序' : '切换为正序'}>
                <IconButton size="small" onClick={onToggleSortOrder}>
                  <SwapVertIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <IconButton size="small" onClick={handleOpenDrawerMenu} disabled={!audiobookProject}>
                <MoreVertIcon fontSize="small" />
              </IconButton>
              <IconButton size="small" onClick={onClose}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>
          </Box>
          <Divider />

          {loading ? (
            <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
              <CircularProgress size={24} />
            </Box>
          ) : error ? (
            <Box sx={{ p: 2 }}>
              <Alert severity="info">{error}</Alert>
            </Box>
          ) : (
            <Box sx={{ flex: 1, overflow: 'auto' }}>
              <List disablePadding>
                {sortedChapters.map((chapter) => {
                  const mergedRef = mergedChapterAudiosByNumber[chapter.chapter_number]
                  const canPlay = Boolean(mergedRef?.chapterAudio?.audio_path)
                  const isActive = playingChapterNumber === chapter.chapter_number
                  const isPlaying = isActive && playerIsPlaying

                  return (
                    <ListItem
                      key={chapter.id}
                      disablePadding
                      secondaryAction={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Tooltip title={canPlay ? (isPlaying ? '暂停' : '播放') : '未生成音频'}>
                            <span>
                              <IconButton
                                size="small"
                                onClick={() => void onPlayChapter(chapter.chapter_number)}
                                disabled={!canPlay}
                              >
                                {isPlaying ? <PauseIcon fontSize="small" /> : <PlayIcon fontSize="small" />}
                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title="章节操作">
                            <span>
                              <IconButton
                                size="small"
                                onClick={(e) => handleOpenChapterMenu(e, chapter, mergedRef?.chapterAudio)}
                                disabled={!mergedRef?.chapterAudio}
                              >
                                <MoreVertIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Box>
                      }
                    >
                      <ListItemButton
                        onClick={() => void onPlayChapter(chapter.chapter_number)}
                        disabled={!canPlay}
                        sx={{
                          alignItems: 'flex-start',
                          py: 1.25,
                          ...(isActive ? { backgroundColor: 'rgba(156, 39, 176, 0.06)' } : null),
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                              <Typography
                                variant="body2"
                                sx={{ fontWeight: 800, color: isActive ? '#7b1fa2' : 'text.primary', flexShrink: 0 }}
                              >
                                第{chapter.chapter_number}章
                              </Typography>
                              <Typography
                                variant="body2"
                                sx={{
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                  color: isActive ? '#7b1fa2' : 'text.primary',
                                }}
                              >
                                {chapter.title}
                              </Typography>
                            </Box>
                          }
                          secondary={
                            isActive ? (
                              <Box sx={{ mt: 0.75 }}>
                                <LinearProgress
                                  variant="determinate"
                                  value={playerDuration > 0 ? (playerCurrentTime / playerDuration) * 100 : 0}
                                  sx={{
                                    height: 4,
                                    borderRadius: 999,
                                    backgroundColor: 'rgba(156, 39, 176, 0.10)',
                                    '& .MuiLinearProgress-bar': { backgroundColor: '#9c27b0' },
                                  }}
                                />
                                <Box sx={{ mt: 0.5, display: 'flex', justifyContent: 'space-between' }}>
                                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                    {formatTime(playerCurrentTime)}
                                  </Typography>
                                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                    {formatTime(playerDuration)}
                                  </Typography>
                                </Box>
                              </Box>
                            ) : null
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  )
                })}
              </List>
            </Box>
          )}

          {playingChapterNumber !== null && (
            <MiniPlayer
              currentTime={playerCurrentTime}
              duration={playerDuration}
              formatTime={formatTime}
              onSeekPreview={onSeekPreview}
              onSeekCommit={onSeekCommit}
            />
          )}
        </Box>
      </Drawer>

      <Menu
        anchorEl={drawerMenuAnchorEl}
        open={Boolean(drawerMenuAnchorEl)}
        onClose={handleCloseDrawerMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MenuItem onClick={handleRequestDeleteAudiobook} sx={{ color: '#f44336' }}>
          <DeleteIcon sx={{ mr: 1 }} />
          删除整本有声书
        </MenuItem>
      </Menu>

      <Menu
        anchorEl={chapterMenuAnchorEl}
        open={Boolean(chapterMenuAnchorEl)}
        onClose={handleCloseChapterMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MenuItem onClick={handleRequestDeleteChapterAudio} sx={{ color: '#f44336' }}>
          <DeleteIcon sx={{ mr: 1 }} />
          删除本章音频
        </MenuItem>
      </Menu>
    </>
  )
}
