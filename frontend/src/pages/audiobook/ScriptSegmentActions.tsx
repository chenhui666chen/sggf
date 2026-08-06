import { useState, type MouseEvent } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Rating,
  Tooltip,
  Typography,
} from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'
import CancelIcon from '@mui/icons-material/Cancel'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import MicIcon from '@mui/icons-material/Mic'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import StopCircleIcon from '@mui/icons-material/StopCircle'
import SurroundSoundIcon from '@mui/icons-material/SurroundSound'

import type {
  PendingSegmentRegeneration,
  PreviewType,
  ScriptSegment,
  SegmentSourceMode,
} from './types'

const previewOptions: Array<{
  type: PreviewType
  label: string
  icon: JSX.Element
}> = [
  { type: 'voice', label: '人声', icon: <PlayArrowIcon fontSize="small" /> },
  { type: 'sfx', label: '音效', icon: <GraphicEqIcon fontSize="small" /> },
  { type: 'bgm', label: '配乐', icon: <LibraryMusicIcon fontSize="small" /> },
  { type: 'mix', label: '融合', icon: <SurroundSoundIcon fontSize="small" /> },
]

const regenerateOptions: Array<{
  key: string
  type: PreviewType
  label: string
  icon: JSX.Element
  sourceMode?: SegmentSourceMode
}> = [
  { key: 'voice', type: 'voice', label: '人声', icon: <MicIcon fontSize="small" /> },
  {
    key: 'sfx-library',
    type: 'sfx',
    label: '音效重新生成（从库匹配）',
    icon: <GraphicEqIcon fontSize="small" />,
    sourceMode: 'library',
  },
  {
    key: 'sfx-ai',
    type: 'sfx',
    label: '音效 AI 重新生成',
    icon: <AutoAwesomeIcon fontSize="small" />,
    sourceMode: 'ai_generate',
  },
  {
    key: 'bgm-library',
    type: 'bgm',
    label: '配乐重新生成（从库匹配）',
    icon: <LibraryMusicIcon fontSize="small" />,
    sourceMode: 'library',
  },
  {
    key: 'bgm-ai',
    type: 'bgm',
    label: '配乐 AI 重新生成',
    icon: <AutoAwesomeIcon fontSize="small" />,
    sourceMode: 'ai_generate',
  },
  { key: 'mix', type: 'mix', label: '融合', icon: <SurroundSoundIcon fontSize="small" /> },
]

interface ScriptSegmentActionsProps {
  segment: ScriptSegment
  index: number
  detailsOpen: boolean
  reviewMode: boolean
  review?: { quality_score?: number; needs_regenerate?: boolean }
  pendingRegeneration?: Partial<Record<PreviewType, PendingSegmentRegeneration>>
  previewingType: PreviewType | null
  regenerating: boolean
  voiceRecording: boolean
  voiceRecordingDisabled: boolean
  chapterAudioAvailable?: boolean
  onPreviewAudio: (index: number, segment: ScriptSegment, previewType: PreviewType) => void
  onRegenerate: (
    index: number,
    segment: ScriptSegment,
    previewType: PreviewType,
    sourceMode?: SegmentSourceMode,
  ) => void
  onStartVoiceRecording: (index: number, segment: ScriptSegment) => void
  onStopVoiceRecording: () => void
  onApplyRegeneration: (index: number, previewType: PreviewType) => void
  onDiscardRegeneration: (index: number, previewType: PreviewType) => void
  onReview: (index: number, score: number) => void
  onToggleDetails: (index: number) => void
  menuPaperSx?: SxProps<Theme>
  mutedTextColor?: string
}

const hasSavedAudioForType = (segment: ScriptSegment, previewType: PreviewType) => {
  if (previewType === 'voice') return Boolean(segment.audio_path)
  if (previewType === 'sfx') return Boolean(segment.sfx_audio_path)
  if (previewType === 'bgm') return Boolean(segment.bgm_audio_path)
  return Boolean(segment.mix_audio_path)
}

const ScriptSegmentActions = ({
  segment,
  index,
  detailsOpen,
  reviewMode,
  review,
  pendingRegeneration,
  previewingType,
  regenerating,
  voiceRecording,
  voiceRecordingDisabled,
  chapterAudioAvailable = false,
  onPreviewAudio,
  onRegenerate,
  onStartVoiceRecording,
  onStopVoiceRecording,
  onApplyRegeneration,
  onDiscardRegeneration,
  onReview,
  onToggleDetails,
  menuPaperSx,
  mutedTextColor,
}: ScriptSegmentActionsProps) => {
  const [previewMenuAnchor, setPreviewMenuAnchor] = useState<HTMLElement | null>(null)
  const [regenerateMenuAnchor, setRegenerateMenuAnchor] = useState<HTMLElement | null>(null)
  const isBusy = previewingType !== null
  const hasText = Boolean(segment.text?.trim())
  const hasPendingRegenerations = Boolean(pendingRegeneration && Object.keys(pendingRegeneration).length > 0)

  const handleOpenPreviewMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setPreviewMenuAnchor(event.currentTarget)
  }

  const handleOpenRegenerateMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setRegenerateMenuAnchor(event.currentTarget)
  }

  const handleClosePreviewMenu = () => {
    setPreviewMenuAnchor(null)
  }

  const handleCloseRegenerateMenu = () => {
    setRegenerateMenuAnchor(null)
  }

  const handlePreview = (option: { type: PreviewType }) => {
    handleClosePreviewMenu()
    onPreviewAudio(index, segment, option.type)
  }

  const handleRegenerate = (option: { type: PreviewType; sourceMode?: SegmentSourceMode }) => {
    handleCloseRegenerateMenu()
    onRegenerate(index, segment, option.type, option.sourceMode)
  }

  const handleVoiceRecordingClick = () => {
    if (voiceRecording) {
      onStopVoiceRecording()
      return
    }
    onStartVoiceRecording(index, segment)
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}>
      <Button
        size="small"
        variant="text"
        onClick={() => onToggleDetails(index)}
      >
        {detailsOpen ? '收起详情' : '查看详情'}
      </Button>

      <Tooltip title="选择单轨或融合试听">
        <span>
          <Button
            size="small"
            variant="outlined"
            onClick={handleOpenPreviewMenu}
            disabled={isBusy}
            startIcon={isBusy ? <CircularProgress size={14} /> : <PlayArrowIcon fontSize="small" />}
            endIcon={<KeyboardArrowDownIcon fontSize="small" />}
          >
            {isBusy ? '播放中...' : '试听'}
          </Button>
        </span>
      </Tooltip>
      <Menu
        anchorEl={previewMenuAnchor}
        open={Boolean(previewMenuAnchor)}
        onClose={handleClosePreviewMenu}
        PaperProps={{ sx: menuPaperSx }}
      >
        {previewOptions.map((option) => {
          const canPlay = Boolean(pendingRegeneration?.[option.type])
            || hasSavedAudioForType(segment, option.type)
            || (option.type === 'mix' && chapterAudioAvailable)
          return (
            <MenuItem
              key={option.type}
              onClick={() => handlePreview(option)}
              disabled={!canPlay || isBusy}
            >
              <ListItemIcon>
                {previewingType === option.type ? <CircularProgress size={18} /> : option.icon}
              </ListItemIcon>
              <ListItemText>{option.label}</ListItemText>
            </MenuItem>
          )
        })}
      </Menu>

      <Tooltip title="选择单轨或融合重新生成">
        <span>
          <Button
            size="small"
            variant="outlined"
            color="warning"
            onClick={handleOpenRegenerateMenu}
            disabled={regenerating || !hasText}
            startIcon={regenerating ? <CircularProgress size={14} /> : <ReplayIcon fontSize="small" />}
            endIcon={<KeyboardArrowDownIcon fontSize="small" />}
          >
            {regenerating ? '重新生成中...' : '重新生成'}
          </Button>
        </span>
      </Tooltip>
      <Menu
        anchorEl={regenerateMenuAnchor}
        open={Boolean(regenerateMenuAnchor)}
        onClose={handleCloseRegenerateMenu}
        PaperProps={{ sx: menuPaperSx }}
      >
        {regenerateOptions.map((option) => (
          <MenuItem
            key={option.key}
            onClick={() => handleRegenerate(option)}
            disabled={regenerating || !hasText}
          >
            <ListItemIcon>{option.icon}</ListItemIcon>
            <ListItemText>{option.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>

      <Tooltip title={voiceRecording ? '结束真人配音录制并上传候选' : '真人直接配音，录完后生成候选版本'}>
        <span>
          <Button
            size="small"
            variant={voiceRecording ? 'contained' : 'outlined'}
            color={voiceRecording ? 'error' : 'primary'}
            onClick={handleVoiceRecordingClick}
            disabled={!voiceRecording && (voiceRecordingDisabled || regenerating)}
            startIcon={voiceRecording ? <StopCircleIcon fontSize="small" /> : <MicIcon fontSize="small" />}
          >
            {voiceRecording ? '结束配音' : '配音'}
          </Button>
        </span>
      </Tooltip>

      {hasPendingRegenerations && previewOptions.map((option) => {
        const pending = pendingRegeneration?.[option.type]
        if (!pending) return null
        return (
          <Box key={option.type} sx={{ display: 'flex', gap: 0.75, alignItems: 'center' }}>
            <Button
              size="small"
              variant="contained"
              color="success"
              onClick={() => onApplyRegeneration(index, option.type)}
              disabled={regenerating}
              startIcon={<CheckCircleIcon fontSize="small" />}
            >
              保存{option.label}
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => onDiscardRegeneration(index, option.type)}
              disabled={regenerating}
              startIcon={<CancelIcon fontSize="small" />}
            >
              取消{option.label}
            </Button>
          </Box>
        )
      })}

      {reviewMode && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
          <Typography variant="caption" sx={{ color: mutedTextColor || 'text.secondary' }}>
            评分：
          </Typography>
          <Rating
            size="small"
            value={review?.quality_score || 0}
            onChange={(_, newValue) => {
              if (newValue) onReview(index, newValue)
            }}
          />
        </Box>
      )}
    </Box>
  )
}

export default ScriptSegmentActions
