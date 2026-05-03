import { useState, type MouseEvent } from 'react'

import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/Edit'
import LibraryAddIcon from '@mui/icons-material/LibraryAdd'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import PauseIcon from '@mui/icons-material/Pause'
import PlayIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'

import {
  formatChapterAudioButtonLabel,
  formatResumeCheckpointChipLabel,
  resolveAudioStatusChip,
  resolveScriptStatusChip,
} from './chapterAudioResultUtils'
import { audiobookColors } from './audiobookTheme'
import type { Chapter, ChapterAudio, GenerationCheckpoint } from './types'

interface ChapterAudioResultItemProps {
  chapterAudio: ChapterAudio
  chapter?: Chapter
  isPlaying: boolean
  isCollecting: boolean
  collectDisabled: boolean
  resumeCheckpoint?: GenerationCheckpoint
  generating: boolean
  resumingChapterId: number | null
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
}

const chipSx = (chip: { backgroundColor: string; color: string }) => ({
  backgroundColor: chip.backgroundColor,
  color: chip.color,
  fontSize: '0.75rem',
  height: 22,
})

const ChapterAudioResultItem = ({
  chapterAudio,
  chapter,
  isPlaying,
  isCollecting,
  collectDisabled,
  resumeCheckpoint,
  generating,
  resumingChapterId,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onResumeChapterGeneration,
}: ChapterAudioResultItemProps) => {
  const [menuAnchorEl, setMenuAnchorEl] = useState<HTMLElement | null>(null)
  const canResume = Boolean(resumeCheckpoint?.can_resume)
  const scriptChip = resolveScriptStatusChip(chapterAudio)
  const audioChip = resolveAudioStatusChip(chapterAudio)
  const menuOpen = Boolean(menuAnchorEl)

  const handleOpenMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setMenuAnchorEl(event.currentTarget)
  }

  const handleCloseMenu = () => {
    setMenuAnchorEl(null)
  }

  const handleOpenScriptEditor = () => {
    handleCloseMenu()
    onOpenScriptEditor(chapterAudio.chapter_id)
  }

  const handleResumeChapterGeneration = () => {
    handleCloseMenu()
    onResumeChapterGeneration(chapterAudio.chapter_id)
  }

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        p: 1.25,
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        backgroundColor: 'background.paper',
      }}
    >
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <Tooltip title={isPlaying ? '暂停播放' : '在线播放'}>
          <Button
            variant="outlined"
            size="small"
            startIcon={isPlaying ? <PauseIcon /> : <PlayIcon />}
            onClick={() => onPlayAudio(chapterAudio.chapter_id)}
            sx={{
              borderColor: isPlaying ? audiobookColors.danger : audiobookColors.brand,
              color: isPlaying ? audiobookColors.danger : audiobookColors.brand,
              '&:hover': {
                borderColor: isPlaying ? audiobookColors.dangerDark : audiobookColors.brandDark,
                backgroundColor: isPlaying ? audiobookColors.dangerSoft : audiobookColors.brandSoft,
              },
            }}
          >
            {formatChapterAudioButtonLabel(chapterAudio, chapter)}
          </Button>
        </Tooltip>

        <Tooltip title="下载音频">
          <IconButton
            size="small"
            onClick={() => onDownloadAudio(chapterAudio.chapter_id)}
            sx={{
              color: audiobookColors.brand,
              '&:hover': {
                backgroundColor: audiobookColors.brandSoft,
              },
            }}
          >
            <DownloadIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Tooltip title="收录到用户资产">
          <span>
          <IconButton
            size="small"
            onClick={() => onCollectChapterAudio(chapterAudio)}
            disabled={collectDisabled}
            sx={{
              color: audiobookColors.collect,
              '&:hover': {
                backgroundColor: audiobookColors.collectSoft,
              },
            }}
          >
            {isCollecting ? <CircularProgress size={18} color="inherit" /> : <LibraryAddIcon fontSize="small" />}
          </IconButton>
          </span>
        </Tooltip>

        <Tooltip title="更多操作">
          <IconButton
            size="small"
            onClick={handleOpenMenu}
            aria-label="更多章节操作"
            aria-controls={menuOpen ? `chapter-audio-menu-${chapterAudio.id}` : undefined}
            aria-haspopup="menu"
            aria-expanded={menuOpen ? 'true' : undefined}
            sx={{
              color: audiobookColors.neutral,
              '&:hover': {
                backgroundColor: audiobookColors.neutralSoft,
              },
            }}
          >
            <MoreVertIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        <Menu
          id={`chapter-audio-menu-${chapterAudio.id}`}
          anchorEl={menuAnchorEl}
          open={menuOpen}
          onClose={handleCloseMenu}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        >
          <MenuItem onClick={handleOpenScriptEditor}>
            <ListItemIcon>
              <EditIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="编辑剧本/提示词" />
          </MenuItem>
          {canResume && (
            <MenuItem
              onClick={handleResumeChapterGeneration}
              disabled={generating || resumingChapterId !== null}
            >
              <ListItemIcon>
                {resumingChapterId === chapterAudio.chapter_id
                  ? <CircularProgress size={18} color="inherit" />
                  : <ReplayIcon fontSize="small" />}
              </ListItemIcon>
              <ListItemText
                primary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : '继续生成'}
              />
            </MenuItem>
          )}
        </Menu>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
        <Chip label={scriptChip.label} size="small" sx={chipSx(scriptChip)} />
        {canResume && (
          <Chip
            label={formatResumeCheckpointChipLabel(resumeCheckpoint)}
            size="small"
            sx={{
              backgroundColor: audiobookColors.warningSoft,
              color: audiobookColors.warning,
              fontSize: '0.75rem',
              height: 22,
            }}
          />
        )}
        <Chip label={audioChip.label} size="small" sx={chipSx(audioChip)} />
      </Box>
    </Box>
  )
}

export default ChapterAudioResultItem
