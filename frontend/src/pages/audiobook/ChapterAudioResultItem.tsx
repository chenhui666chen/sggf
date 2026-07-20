import { useState, type MouseEvent } from 'react'

import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Rating,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DownloadIcon from '@mui/icons-material/Download'
import EditIcon from '@mui/icons-material/Edit'
import FactCheckIcon from '@mui/icons-material/FactCheck'
import LibraryAddIcon from '@mui/icons-material/LibraryAdd'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import PauseIcon from '@mui/icons-material/Pause'
import PlayIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import StarIcon from '@mui/icons-material/Star'
import SummarizeIcon from '@mui/icons-material/Summarize'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import {
  formatChapterAudioButtonLabel,
  formatResumeCheckpointChipLabel,
  resolveAudioStatusChip,
  resolveScriptStatusChip,
} from './chapterAudioResultUtils'
import { audiobookButtonSx, audiobookColorRoles } from './audiobookTheme'
import PromptAudioManualReviewPanel from './PromptAudioManualReviewPanel'
import type { Chapter, ChapterAudio, GenerationCheckpoint, TtsModel } from './types'

interface ChapterAudioResultItemProps {
  chapterAudio: ChapterAudio
  chapter?: Chapter
  isPlaying: boolean
  isCollecting: boolean
  collectDisabled: boolean
  resumeCheckpoint?: GenerationCheckpoint
  generating: boolean
  resumingChapterId: number | null
  ttsModel?: TtsModel
  projectId?: number
  audiobookProjectId?: number
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
  onOpenScriptReview?: (audiobookProjectId: number, chapterId: number) => void
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
  ttsModel,
  projectId,
  audiobookProjectId,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onResumeChapterGeneration,
  onOpenScriptReview,
}: ChapterAudioResultItemProps) => {
  const [menuAnchorEl, setMenuAnchorEl] = useState<HTMLElement | null>(null)
  const [showRating, setShowRating] = useState(false)
  const [ratingValue, setRatingValue] = useState<number | null>(null)
  const [ratingComment, setRatingComment] = useState('')
  const [ratingSubmitting, setRatingSubmitting] = useState(false)
  const [ratingSubmitted, setRatingSubmitted] = useState(false)
  const [ratingError, setRatingError] = useState<string | null>(null)
  const [showPromptAudioReview, setShowPromptAudioReview] = useState(false)
  const canResume = Boolean(resumeCheckpoint?.can_resume)
  const scriptChip = resolveScriptStatusChip(chapterAudio)
  const audioChip = resolveAudioStatusChip(chapterAudio)
  const menuOpen = Boolean(menuAnchorEl)
  const hasPromptAudioReviewModels = Boolean(chapterAudio.prompt_audio_quality)
  const collectTooltipTitle = isCollecting
    ? '正在收录到用户资产'
    : collectDisabled
      ? '该章节音频已收录或暂不可收录'
      : '收录到用户资产'

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
            sx={isPlaying ? audiobookButtonSx.dangerOutlined : audiobookButtonSx.brandOutlined}
          >
            {formatChapterAudioButtonLabel(chapterAudio, chapter)}
          </Button>
        </Tooltip>

        <Tooltip title="下载音频">
          <IconButton
            size="small"
            onClick={() => onDownloadAudio(chapterAudio.chapter_id)}
            sx={audiobookButtonSx.brandIcon}
          >
            <DownloadIcon fontSize="small" />
          </IconButton>
        </Tooltip>

        <Tooltip title={collectTooltipTitle}>
          <span>
          <IconButton
            size="small"
            onClick={() => onCollectChapterAudio(chapterAudio)}
            disabled={collectDisabled}
            sx={audiobookButtonSx.collectIcon}
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
            sx={audiobookButtonSx.neutralIcon}
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
          <MenuItem
            onClick={() => {
              handleCloseMenu()
              if (audiobookProjectId && onOpenScriptReview) {
                onOpenScriptReview(audiobookProjectId, chapterAudio.chapter_id)
              }
            }}
            disabled={!audiobookProjectId || !onOpenScriptReview}
          >
            <ListItemIcon>
              <SummarizeIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="查看审核报告" />
          </MenuItem>
          <MenuItem onClick={() => { handleCloseMenu(); setShowRating(true) }}>
            <ListItemIcon>
              <StarIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="评价生成质量" />
          </MenuItem>
          <MenuItem
            onClick={() => {
              handleCloseMenu()
              setShowPromptAudioReview(true)
            }}
            disabled={!hasPromptAudioReviewModels}
          >
            <ListItemIcon>
              <FactCheckIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText
              primary="Prompt/Audio 验收"
              secondary={hasPromptAudioReviewModels ? undefined : '暂无质量回写'}
            />
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
                primary="继续生成"
                secondary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : undefined}
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
              backgroundColor: audiobookColorRoles.notice.warning.bg,
              color: audiobookColorRoles.notice.warning.text,
              fontSize: '0.75rem',
              height: 22,
            }}
          />
        )}
        <Chip label={audioChip.label} size="small" sx={chipSx(audioChip)} />
        {chapterAudio.generation_time != null && chapterAudio.generation_time > 0 && (
          <Chip
            label={`${chapterAudio.generation_time.toFixed(1)}s`}
            size="small"
            variant="outlined"
            sx={{ fontSize: '0.75rem', height: 22 }}
          />
        )}
        {chapterAudio.tts_cost != null && chapterAudio.tts_cost > 0 && (
          <Chip
            label={`￥${chapterAudio.tts_cost.toFixed(2)}`}
            size="small"
            variant="outlined"
            sx={{ fontSize: '0.75rem', height: 22 }}
          />
        )}
      </Box>

      <Collapse in={showRating}>
        <Box sx={{ mt: 1, p: 1, backgroundColor: 'action.hover', borderRadius: 1 }}>
          {ratingSubmitted ? (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <StarIcon sx={{ color: 'gold', fontSize: 18 }} />
              <Typography variant="caption" color="text.secondary">
                已评分 {ratingValue} 星，感谢反馈！
              </Typography>
            </Box>
          ) : (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="caption" color="text.secondary">评分：</Typography>
                <Rating
                  size="small"
                  value={ratingValue}
                  onChange={(_, v) => setRatingValue(v)}
                />
                <Button
                  size="small"
                  variant="text"
                  disabled={ratingSubmitting || ratingValue === null}
                  onClick={async () => {
                    if (!ratingValue) return
                    setRatingSubmitting(true)
                    setRatingError(null)
                    try {
                      await apiClient.submitUserRating({
                        model_id: ttsModel || 'unknown',
                        task_type: 'audiobook_chapter',
                        rating: ratingValue,
                        comment: ratingComment || undefined,
                        project_id: projectId,
                      })
                      setRatingSubmitted(true)
                    } catch (err: unknown) {
                      setRatingError(await extractApiErrorMessage(err, '提交评分失败'))
                    } finally {
                      setRatingSubmitting(false)
                    }
                  }}
                >
                  {ratingSubmitting ? '提交中...' : '提交'}
                </Button>
                <Button size="small" variant="text" onClick={() => setShowRating(false)}>
                  取消
                </Button>
              </Box>
              <TextField
                size="small"
                fullWidth
                multiline
                minRows={1}
                maxRows={2}
                placeholder="可选：写下你的反馈..."
                value={ratingComment}
                onChange={(e) => setRatingComment(e.target.value)}
                sx={{ mt: 0.5 }}
              />
              {ratingError && (
                <Typography variant="caption" color="error" sx={{ mt: 0.5 }}>
                  {ratingError}
                </Typography>
              )}
            </>
          )}
        </Box>
      </Collapse>

      <Collapse in={showPromptAudioReview}>
        <PromptAudioManualReviewPanel
          chapterAudio={chapterAudio}
          onCollapse={() => setShowPromptAudioReview(false)}
        />
      </Collapse>
    </Box>
  )
}

export default ChapterAudioResultItem
