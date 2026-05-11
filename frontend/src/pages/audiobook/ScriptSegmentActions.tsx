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
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import MusicNoteIcon from '@mui/icons-material/MusicNote'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver'
import SurroundSoundIcon from '@mui/icons-material/SurroundSound'

import type {
  PreviewType,
  ScriptSegment,
} from './types'
import {
  hasPreviewableMusicCue,
  hasPreviewableSoundEffects,
} from './scriptSegmentCardUtils'

interface ScriptSegmentActionsProps {
  segment: ScriptSegment
  index: number
  detailsOpen: boolean
  reviewMode: boolean
  review?: { quality_score?: number; needs_regenerate?: boolean }
  previewingType: PreviewType | null
  regenerating: boolean
  onPreviewAudio: (index: number, segment: ScriptSegment, previewType: PreviewType) => void
  onRegenerate: (index: number, segment: ScriptSegment) => void
  onReview: (index: number, score: number) => void
  onToggleDetails: (index: number) => void
}

const ScriptSegmentActions = ({
  segment,
  index,
  detailsOpen,
  reviewMode,
  review,
  previewingType,
  regenerating,
  onPreviewAudio,
  onRegenerate,
  onReview,
  onToggleDetails,
}: ScriptSegmentActionsProps) => {
  const [previewMenuAnchor, setPreviewMenuAnchor] = useState<HTMLElement | null>(null)
  const isBusy = previewingType !== null
  const hasText = Boolean(segment.text?.trim())
  const isPreviewing = (type: PreviewType) => previewingType === type
  const previewMenuOpen = Boolean(previewMenuAnchor)
  const soundEffectsAvailable = hasPreviewableSoundEffects(segment)
  const musicCueAvailable = hasPreviewableMusicCue(segment)

  const handleOpenPreviewMenu = (event: MouseEvent<HTMLButtonElement>) => {
    setPreviewMenuAnchor(event.currentTarget)
  }

  const handleClosePreviewMenu = () => {
    setPreviewMenuAnchor(null)
  }

  const handlePreview = (previewType: PreviewType) => {
    handleClosePreviewMenu()
    onPreviewAudio(index, segment, previewType)
  }

  const previewOptions: Array<{
    type: PreviewType
    label: string
    icon: JSX.Element
    disabled: boolean
  }> = [
    {
      type: 'voice',
      label: '人声试听',
      icon: <RecordVoiceOverIcon fontSize="small" />,
      disabled: !hasText,
    },
    {
      type: 'sfx',
      label: '音效试听',
      icon: <GraphicEqIcon fontSize="small" />,
      disabled: !hasText || !soundEffectsAvailable,
    },
    {
      type: 'bgm',
      label: '配乐试听',
      icon: <MusicNoteIcon fontSize="small" />,
      disabled: !hasText || !musicCueAvailable,
    },
    {
      type: 'mix',
      label: '融合试听',
      icon: <SurroundSoundIcon fontSize="small" />,
      disabled: !hasText,
    },
  ]

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}>
      <Button
        size="small"
        variant="text"
        onClick={() => onToggleDetails(index)}
      >
        {detailsOpen ? '收起详情' : '查看详情'}
      </Button>

      <Tooltip title={hasText ? '选择试听类型' : '片段文本为空，无法试听'}>
        <span>
          <Button
            size="small"
            variant="outlined"
            onClick={handleOpenPreviewMenu}
            disabled={isBusy || !hasText}
            startIcon={isBusy ? <CircularProgress size={14} /> : <PlayArrowIcon fontSize="small" />}
          >
            {isBusy ? '生成中...' : '试听'}
          </Button>
        </span>
      </Tooltip>
      <Menu
        anchorEl={previewMenuAnchor}
        open={previewMenuOpen}
        onClose={handleClosePreviewMenu}
      >
        {previewOptions.map((option) => (
          <MenuItem
            key={option.type}
            onClick={() => handlePreview(option.type)}
            disabled={option.disabled || isBusy}
          >
            <ListItemIcon>
              {isPreviewing(option.type) ? <CircularProgress size={18} /> : option.icon}
            </ListItemIcon>
            <ListItemText>{option.label}</ListItemText>
          </MenuItem>
        ))}
      </Menu>

      {reviewMode && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
          <Typography variant="caption" color="text.secondary">
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
      <Button
        size="small"
        variant="outlined"
        color="warning"
        onClick={() => onRegenerate(index, segment)}
        disabled={regenerating || !hasText}
        startIcon={regenerating ? <CircularProgress size={14} /> : undefined}
      >
        {regenerating ? '重新生成中...' : '重新生成'}
      </Button>
    </Box>
  )
}

export default ScriptSegmentActions
