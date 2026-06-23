import { useCallback, useMemo, useState, useEffect, useRef } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  Dialog,
  DialogContent,
  IconButton,
  LinearProgress,
  Slider,
  Stack,
  TextField,
  Tooltip,
  Typography,
  Tabs,
  Tab,
  InputAdornment,
  Badge,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import KeyboardArrowLeftIcon from '@mui/icons-material/KeyboardArrowLeft'
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import MicIcon from '@mui/icons-material/Mic'
import TextSnippetIcon from '@mui/icons-material/TextSnippet'
import TuneIcon from '@mui/icons-material/Tune'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'
import SearchIcon from '@mui/icons-material/Search'
import LockIcon from '@mui/icons-material/Lock'
import VolumeOffIcon from '@mui/icons-material/VolumeOff'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ContentPasteIcon from '@mui/icons-material/ContentPaste'
import CloseIcon from '@mui/icons-material/Close'
import ClearIcon from '@mui/icons-material/Clear'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  PreviewType,
  ScriptEditorDialogProps,
  ScriptSegment,
} from './types'
import ScriptReviewReport from './ScriptReviewReport'
import ScriptEditorConflictNotice from './ScriptEditorConflictNotice'
import ScriptSegmentActions from './ScriptSegmentActions'
import ScriptSegmentDetailsPanel from './ScriptSegmentDetailsPanel'
import SmartChunkPreviewPanel from './SmartChunkPreviewPanel'
import {
  formatScriptSegmentSummary,
  getScriptSegmentSpeakerLabel,
  getScriptSegmentTypeLabel,
  getMusicCueInputValue,
  getSoundEffectsInputValue,
} from './scriptSegmentCardUtils'
import {
  adjustTimelineClipEdit,
  applyTimelineEdits,
  buildTimelineModel,
  isTimelineClipEditable,
  resolveTimelineSeekSegmentOffsetRatio,
  resolveTimelineSeekSegmentIndex,
  TIMELINE_MIN_EDIT_DURATION_UNITS,
  type TimelineClip,
  type TimelineClipEditOperation,
  type TimelineTrackKey,
} from './scriptEditorTimelineUtils'

const TIMELINE_SCALE_OPTIONS = [0.8, 1, 1.35]
const TIMELINE_SCALE_MARKS = TIMELINE_SCALE_OPTIONS.map((value) => ({ value }))

type FilterType = 'all' | 'sfx' | 'music' | 'review' | 'warning'

const TIMELINE_LABEL_WIDTH = 104
const TIMELINE_RULER_HEIGHT = 28
const TIMELINE_PRIMARY_TRACK_HEIGHT = 54
const TIMELINE_AUDIO_TRACK_HEIGHT = 36
const TIMELINE_SIDE_PADDING = 12
const TIMELINE_MIN_CONTENT_WIDTH = 720
const EDITOR_BOTTOM_SAFE_AREA = 24

const EDITOR_SURFACE_COLORS = {
  app: '#080a0d',
  shell: '#0b0d10',
  toolbar: '#090a0d',
  workspace: '#101319',
  panel: '#17191f',
  panelRaised: '#1f222a',
  panelSoft: '#12161d',
  field: '#0f131a',
  timeline: '#0b0d10',
  timelineTrack: '#10141c',
  border: 'rgba(255,255,255,0.08)',
  borderStrong: 'rgba(255,255,255,0.14)',
  text: '#f4f7fb',
  muted: '#9aa4b2',
  faint: '#697386',
  accent: '#10d7e2',
  accentSoft: 'rgba(16,215,226,0.16)',
  scriptBlue: '#2f6df6',
  sfxOrange: '#ff8a2a',
  musicPurple: '#8b5cf6',
  success: '#31d095',
  warning: '#fbbf24',
  danger: '#ff5c70',
  playhead: '#ef4444',
} as const

const EDITOR_TRACK_COLORS = {
  scriptVoice: EDITOR_SURFACE_COLORS.scriptBlue,
  sfx: EDITOR_SURFACE_COLORS.sfxOrange,
  music: EDITOR_SURFACE_COLORS.musicPurple,
} as const

const editorShellSx = {
  height: '100%',
  minHeight: 0,
  display: 'grid',
  gridTemplateRows: 'minmax(0, 1fr) auto',
  bgcolor: EDITOR_SURFACE_COLORS.shell,
  color: EDITOR_SURFACE_COLORS.text,
  boxSizing: 'border-box',
  pb: `calc(${EDITOR_BOTTOM_SAFE_AREA}px + env(safe-area-inset-bottom))`,
  '& *': {
    scrollbarWidth: 'thin',
    scrollbarColor: `rgba(154,164,178,0.45) ${EDITOR_SURFACE_COLORS.timeline}`,
  },
  '& *::-webkit-scrollbar': {
    width: 10,
    height: 10,
  },
  '& *::-webkit-scrollbar-track': {
    backgroundColor: EDITOR_SURFACE_COLORS.timeline,
  },
  '& *::-webkit-scrollbar-thumb': {
    backgroundColor: 'rgba(154,164,178,0.38)',
    border: `2px solid ${EDITOR_SURFACE_COLORS.timeline}`,
    borderRadius: 999,
  },
  '& *::-webkit-scrollbar-thumb:hover': {
    backgroundColor: 'rgba(16,215,226,0.56)',
  },
  '& *::-webkit-scrollbar-corner': {
    backgroundColor: EDITOR_SURFACE_COLORS.timeline,
  },
  '& .MuiTypography-colorTextSecondary': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiDivider-root': {
    borderColor: EDITOR_SURFACE_COLORS.border,
  },
  '& .MuiDivider-wrapper': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiListItemText-primary': {
    color: EDITOR_SURFACE_COLORS.text,
  },
  '& .MuiListItemText-secondary': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiButton-text': {
    color: EDITOR_SURFACE_COLORS.muted,
    '&:hover': {
      color: EDITOR_SURFACE_COLORS.text,
      backgroundColor: 'rgba(255,255,255,0.06)',
    },
  },
  '& .MuiButton-outlined': {
    color: EDITOR_SURFACE_COLORS.text,
    borderColor: EDITOR_SURFACE_COLORS.borderStrong,
    backgroundColor: 'rgba(255,255,255,0.03)',
    '&:hover': {
      borderColor: EDITOR_SURFACE_COLORS.accent,
      backgroundColor: EDITOR_SURFACE_COLORS.accentSoft,
    },
    '&.Mui-disabled': {
      color: EDITOR_SURFACE_COLORS.faint,
      borderColor: EDITOR_SURFACE_COLORS.border,
    },
  },
  '& .MuiIconButton-root': {
    color: EDITOR_SURFACE_COLORS.muted,
    borderRadius: 1,
    '&:hover': {
      color: EDITOR_SURFACE_COLORS.text,
      backgroundColor: 'rgba(255,255,255,0.07)',
    },
    '&.Mui-disabled': {
      color: EDITOR_SURFACE_COLORS.faint,
    },
  },
  '& .MuiInputLabel-root': {
    color: EDITOR_SURFACE_COLORS.muted,
    '&.Mui-focused': {
      color: EDITOR_SURFACE_COLORS.accent,
    },
  },
  '& .MuiOutlinedInput-root': {
    color: EDITOR_SURFACE_COLORS.text,
    backgroundColor: EDITOR_SURFACE_COLORS.field,
    borderRadius: 1,
    '& .MuiOutlinedInput-notchedOutline': {
      borderColor: EDITOR_SURFACE_COLORS.borderStrong,
    },
    '&:hover .MuiOutlinedInput-notchedOutline': {
      borderColor: 'rgba(16,215,226,0.5)',
    },
    '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
      borderColor: EDITOR_SURFACE_COLORS.accent,
    },
  },
  '& .MuiInputBase-input': {
    color: EDITOR_SURFACE_COLORS.text,
    '&::placeholder': {
      color: EDITOR_SURFACE_COLORS.muted,
      opacity: 1,
    },
  },
  '& .MuiFormHelperText-root': {
    color: EDITOR_SURFACE_COLORS.warning,
  },
  '& .MuiChip-root': {
    color: EDITOR_SURFACE_COLORS.muted,
    borderColor: EDITOR_SURFACE_COLORS.borderStrong,
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
  '& .MuiChip-label': {
    color: 'inherit',
  },
  '& .MuiChip-colorPrimary': {
    color: EDITOR_SURFACE_COLORS.accent,
    backgroundColor: EDITOR_SURFACE_COLORS.accentSoft,
    borderColor: 'rgba(16,215,226,0.45)',
  },
  '& .MuiChip-colorWarning': {
    color: EDITOR_SURFACE_COLORS.sfxOrange,
    backgroundColor: 'rgba(255,138,42,0.16)',
    borderColor: 'rgba(255,138,42,0.42)',
  },
  '& .MuiChip-colorSecondary': {
    color: EDITOR_SURFACE_COLORS.musicPurple,
    backgroundColor: 'rgba(139,92,246,0.16)',
    borderColor: 'rgba(139,92,246,0.42)',
  },
  '& .MuiChip-colorSuccess': {
    color: EDITOR_SURFACE_COLORS.success,
    backgroundColor: 'rgba(49,208,149,0.14)',
    borderColor: 'rgba(49,208,149,0.38)',
  },
  '& .MuiLinearProgress-root': {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  '& .MuiLinearProgress-bar': {
    backgroundColor: EDITOR_SURFACE_COLORS.accent,
  },
  '& .MuiBadge-badge': {
    color: '#061114',
    fontWeight: 800,
  },
  '& .MuiSlider-root': {
    color: EDITOR_SURFACE_COLORS.accent,
  },
  '& .MuiSlider-rail': {
    backgroundColor: 'rgba(154,164,178,0.24)',
    opacity: 1,
  },
  '& .MuiSlider-track': {
    backgroundColor: EDITOR_SURFACE_COLORS.accent,
    borderColor: EDITOR_SURFACE_COLORS.accent,
  },
  '& .MuiSlider-thumb': {
    backgroundColor: EDITOR_SURFACE_COLORS.accent,
    border: `2px solid ${EDITOR_SURFACE_COLORS.shell}`,
    boxShadow: '0 0 0 4px rgba(16,215,226,0.18)',
  },
  '& .MuiSlider-mark': {
    backgroundColor: 'rgba(244,247,251,0.45)',
  },
  '& .MuiSlider-markLabel': {
    color: EDITOR_SURFACE_COLORS.muted,
    fontSize: 11,
  },
  '& .MuiPaper-root': {
    color: EDITOR_SURFACE_COLORS.text,
    backgroundColor: EDITOR_SURFACE_COLORS.panelRaised,
    borderColor: EDITOR_SURFACE_COLORS.borderStrong,
  },
  '& .MuiAlert-root': {
    color: EDITOR_SURFACE_COLORS.text,
    border: `1px solid ${EDITOR_SURFACE_COLORS.borderStrong}`,
    '& .MuiAlert-message, & .MuiTypography-root': {
      color: 'inherit',
    },
  },
  '& .MuiAlert-standardInfo': {
    backgroundColor: 'rgba(16,215,226,0.12)',
    '& .MuiAlert-icon': {
      color: EDITOR_SURFACE_COLORS.accent,
    },
  },
  '& .MuiAlert-standardSuccess': {
    backgroundColor: 'rgba(49,208,149,0.12)',
    '& .MuiAlert-icon': {
      color: EDITOR_SURFACE_COLORS.success,
    },
  },
  '& .MuiAlert-standardWarning': {
    backgroundColor: 'rgba(251,191,36,0.12)',
    '& .MuiAlert-icon': {
      color: EDITOR_SURFACE_COLORS.warning,
    },
  },
  '& .MuiAlert-standardError': {
    backgroundColor: 'rgba(255,92,112,0.12)',
    '& .MuiAlert-icon': {
      color: EDITOR_SURFACE_COLORS.danger,
    },
  },
}

const editorMutedTextSx = {
  color: EDITOR_SURFACE_COLORS.muted,
} as const

const editorWorkspaceSx = {
  minHeight: 0,
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', lg: '270px minmax(0, 1fr) 350px' },
  gap: 0,
  overflow: 'hidden',
  bgcolor: EDITOR_SURFACE_COLORS.workspace,
  color: EDITOR_SURFACE_COLORS.text,
}

const segmentNavigatorSx = {
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  borderRight: { xs: 0, lg: '1px solid' },
  borderColor: EDITOR_SURFACE_COLORS.border,
  bgcolor: EDITOR_SURFACE_COLORS.panel,
  color: EDITOR_SURFACE_COLORS.text,
  overflow: 'hidden',
}

const focusSegmentPanelSx = {
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  bgcolor: EDITOR_SURFACE_COLORS.workspace,
  color: EDITOR_SURFACE_COLORS.text,
  overflow: 'hidden',
}

const focusSegmentCardSx = {
  minHeight: 0,
  m: 1.5,
  p: 2,
  display: 'flex',
  flexDirection: 'column',
  bgcolor: EDITOR_SURFACE_COLORS.panel,
  color: EDITOR_SURFACE_COLORS.text,
  border: '1px solid',
  borderColor: EDITOR_SURFACE_COLORS.border,
  borderRadius: 1,
  boxShadow: '0 18px 42px rgba(0, 0, 0, 0.24)',
  overflow: 'auto',
}

const segmentInspectorSx = {
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  bgcolor: EDITOR_SURFACE_COLORS.panel,
  color: EDITOR_SURFACE_COLORS.text,
  borderLeft: { xs: 0, lg: '1px solid' },
  borderColor: EDITOR_SURFACE_COLORS.border,
  overflow: 'hidden',
}

const panelHeaderSx = {
  px: 2,
  py: 1.25,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  borderBottom: '1px solid',
  borderColor: EDITOR_SURFACE_COLORS.border,
  bgcolor: EDITOR_SURFACE_COLORS.panelRaised,
  color: EDITOR_SURFACE_COLORS.text,
}

const timelinePanelSx = {
  borderTop: '1px solid',
  borderColor: EDITOR_SURFACE_COLORS.border,
  bgcolor: EDITOR_SURFACE_COLORS.timeline,
  color: EDITOR_SURFACE_COLORS.text,
  display: 'flex',
  flexDirection: 'column',
  minHeight: 0,
  overflow: 'hidden',
}

const trackLabelSx = {
  px: 1.25,
  height: '100%',
  display: 'flex',
  alignItems: 'center',
  gap: 0.75,
  flexShrink: 0,
  bgcolor: EDITOR_SURFACE_COLORS.panelSoft,
  color: EDITOR_SURFACE_COLORS.muted,
  fontSize: 12,
}

const timelineLabelsColumnSx = {
  width: TIMELINE_LABEL_WIDTH,
  flexShrink: 0,
  borderRight: '1px solid rgba(255,255,255,0.08)',
}

const timelineRulerContentSx = {
  position: 'relative',
  height: TIMELINE_RULER_HEIGHT,
}

const timelineTrackContentSx = {
  position: 'relative',
  borderTop: `1px solid ${EDITOR_SURFACE_COLORS.border}`,
  backgroundColor: EDITOR_SURFACE_COLORS.timelineTrack,
}

const editorSearchBarSx = {
  px: 1,
  py: 0.75,
  borderBottom: '1px solid',
  borderColor: EDITOR_SURFACE_COLORS.border,
  bgcolor: EDITOR_SURFACE_COLORS.panelSoft,
}

const editorTabsSx = {
  borderBottom: '1px solid',
  borderColor: EDITOR_SURFACE_COLORS.border,
  bgcolor: EDITOR_SURFACE_COLORS.panelRaised,
  minHeight: 38,
  '& .MuiTab-root': {
    minHeight: 38,
    color: EDITOR_SURFACE_COLORS.muted,
    fontSize: 12,
    '&.Mui-selected': {
      color: EDITOR_SURFACE_COLORS.accent,
    },
  },
  '& .MuiTabs-indicator': {
    height: 2,
    backgroundColor: EDITOR_SURFACE_COLORS.accent,
  },
}

const editorInlinePanelSx = {
  p: 1.25,
  borderRadius: 1,
  bgcolor: EDITOR_SURFACE_COLORS.panelSoft,
  color: EDITOR_SURFACE_COLORS.text,
  border: `1px solid ${EDITOR_SURFACE_COLORS.border}`,
}

const editorCuePanelSx = (accentColor: string) => ({
  ...editorInlinePanelSx,
  borderLeft: `3px solid ${accentColor}`,
})

const editorMetricPanelSx = (accentColor: string) => ({
  ...editorInlinePanelSx,
  borderColor: `color-mix(in srgb, ${accentColor} 42%, transparent)`,
  backgroundColor: `color-mix(in srgb, ${accentColor} 12%, ${EDITOR_SURFACE_COLORS.panelSoft})`,
})

const editorFilterChipSx = (active: boolean, accentColor: string) => ({
  height: 24,
  color: active ? EDITOR_SURFACE_COLORS.text : EDITOR_SURFACE_COLORS.muted,
  borderColor: active ? accentColor : EDITOR_SURFACE_COLORS.borderStrong,
  backgroundColor: active ? `color-mix(in srgb, ${accentColor} 18%, transparent)` : 'rgba(255,255,255,0.04)',
  '&:hover': {
    borderColor: accentColor,
    backgroundColor: `color-mix(in srgb, ${accentColor} 22%, transparent)`,
  },
})

const editorPrimaryActionSx = {
  bgcolor: EDITOR_SURFACE_COLORS.accent,
  color: '#041114',
  fontWeight: 800,
  '&:hover': {
    bgcolor: '#2eeaf3',
  },
  '&.Mui-disabled': {
    color: EDITOR_SURFACE_COLORS.faint,
    bgcolor: 'rgba(255,255,255,0.08)',
  },
}

const editorDetailsPanelSx = {
  bgcolor: EDITOR_SURFACE_COLORS.panelSoft,
  borderColor: EDITOR_SURFACE_COLORS.borderStrong,
  color: EDITOR_SURFACE_COLORS.text,
  '& .MuiTypography-root': {
    color: EDITOR_SURFACE_COLORS.text,
  },
  '& .MuiTypography-colorTextSecondary': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiDivider-root': {
    borderColor: EDITOR_SURFACE_COLORS.border,
  },
}

const editorFloatingPaperSx = {
  bgcolor: EDITOR_SURFACE_COLORS.panelRaised,
  color: EDITOR_SURFACE_COLORS.text,
  border: `1px solid ${EDITOR_SURFACE_COLORS.borderStrong}`,
  boxShadow: '0 18px 40px rgba(0,0,0,0.42)',
  '& .MuiMenuItem-root, & .MuiAutocomplete-option': {
    color: EDITOR_SURFACE_COLORS.text,
    '&:hover, &.Mui-focused': {
      backgroundColor: EDITOR_SURFACE_COLORS.accentSoft,
    },
    '&.Mui-disabled': {
      color: EDITOR_SURFACE_COLORS.faint,
    },
  },
  '& .MuiListItemIcon-root': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiListItemText-primary': {
    color: EDITOR_SURFACE_COLORS.text,
  },
  '& .MuiListItemText-secondary': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiTypography-root': {
    color: 'inherit',
  },
  '& .MuiChip-root': {
    color: EDITOR_SURFACE_COLORS.muted,
    borderColor: EDITOR_SURFACE_COLORS.borderStrong,
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
}

const editorEmbeddedContentSx = {
  color: EDITOR_SURFACE_COLORS.text,
  '& .MuiTypography-caption, & .MuiTypography-body2, & .MuiTypography-subtitle2': {
    color: 'inherit',
  },
  '& .MuiListItemText-primary': {
    color: EDITOR_SURFACE_COLORS.text,
  },
  '& .MuiListItemText-secondary': {
    color: EDITOR_SURFACE_COLORS.muted,
  },
  '& .MuiListItemButton-root': {
    color: EDITOR_SURFACE_COLORS.text,
    '&:hover': {
      backgroundColor: 'rgba(255,255,255,0.06)',
    },
    '&.Mui-selected': {
      backgroundColor: EDITOR_SURFACE_COLORS.accentSoft,
      '&:hover': {
        backgroundColor: 'rgba(16,215,226,0.22)',
      },
    },
  },
}

const TimelineTrack = ({
  color,
  clips,
  contentWidth,
  height,
  compact = false,
  selectedIndex,
  scale,
  onSelectClip,
  onAdjustClip,
  locked = false,
  muted = false,
}: {
  color: string
  clips: TimelineClip[]
  contentWidth: number
  height: number
  compact?: boolean
  selectedIndex: number
  scale: number
  onSelectClip: (index: number) => void
  onAdjustClip: (
    clip: TimelineClip,
    operation: TimelineClipEditOperation,
    deltaUnits: number,
    baseEdit: { startUnit: number; durationUnits: number },
  ) => void
  locked?: boolean
  muted?: boolean
}) => (
  <Box sx={{ ...timelineTrackContentSx, width: contentWidth, height }}>
    {clips.map((clip) => {
      const clipLeft = TIMELINE_SIDE_PADDING + Math.round(clip.startUnit * scale)
      const clipWidth = Math.max(24, Math.round(clip.durationUnits * scale))
      const clipHeight = compact ? 22 : 40
      const clipTop = Math.max(6, Math.round((height - clipHeight) / 2))
      const selected =
        selectedIndex >= clip.segmentIndex && selectedIndex <= clip.endSegmentIndex
      const editable = !locked && !muted && isTimelineClipEditable(clip)
      const handlePointerEdit = (
        event: React.PointerEvent<HTMLDivElement>,
        operation: TimelineClipEditOperation,
      ) => {
        if (!editable) return
        event.preventDefault()
        event.stopPropagation()

        const startClientX = event.clientX
        const target = event.currentTarget
        const baseEdit = {
          startUnit: clip.startUnit,
          durationUnits: clip.durationUnits,
        }
        target.setPointerCapture(event.pointerId)

        const handlePointerMove = (moveEvent: PointerEvent) => {
          const deltaUnits = Math.round((moveEvent.clientX - startClientX) / scale)
          onAdjustClip(clip, operation, deltaUnits, baseEdit)
        }
        const cleanup = () => {
          target.releasePointerCapture(event.pointerId)
          window.removeEventListener('pointermove', handlePointerMove)
          window.removeEventListener('pointerup', cleanup)
          window.removeEventListener('pointercancel', cleanup)
        }

        window.addEventListener('pointermove', handlePointerMove)
        window.addEventListener('pointerup', cleanup)
        window.addEventListener('pointercancel', cleanup)
      }

      return (
        <Tooltip
          key={clip.key}
          title={
            <Box sx={{ maxWidth: 300 }}>
              <Typography variant="caption" sx={{ fontWeight: 600 }}>
                {clip.segmentIndex === clip.endSegmentIndex
                  ? `片段 #${clip.segmentIndex + 1}`
                  : `片段 #${clip.segmentIndex + 1}-#${clip.endSegmentIndex + 1}`}
              </Typography>
              <Typography variant="caption" sx={{ display: 'block', mt: 0.5, whiteSpace: 'pre-wrap' }}>
                {clip.textPreview || clip.label}
              </Typography>
              {clip.speakerLabel && (
                <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'rgba(255,255,255,0.72)' }}>
                  {clip.speakerLabel} · {clip.emotionLabel || '未标注'}
                </Typography>
              )}
            </Box>
          }
          arrow
        >
          <Box
            role="button"
            tabIndex={0}
            aria-label={`${clip.label}${editable ? '，可拖动调整' : ''}`}
            onClick={() => !locked && onSelectClip(clip.segmentIndex)}
            onDoubleClick={() => !locked && onSelectClip(clip.segmentIndex)}
            onPointerDown={(event) => handlePointerEdit(event, 'move')}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (!locked) {
                  onSelectClip(clip.segmentIndex)
                }
              }
            }}
            sx={{
              position: 'absolute',
              left: clipLeft,
              top: clipTop,
              width: clipWidth,
              height: clipHeight,
              borderRadius: 0.75,
              bgcolor: muted
                ? 'rgba(148, 163, 184, 0.12)'
                : clip.enabled
                  ? color
                  : 'rgba(148, 163, 184, 0.18)',
              border: '1px solid',
              borderColor: selected
                ? EDITOR_SURFACE_COLORS.text
                : clip.enabled
                  ? 'rgba(255,255,255,0.25)'
                  : 'rgba(148,163,184,0.14)',
              boxShadow: selected
                ? '0 0 0 2px rgba(16,215,226,0.34), 0 8px 18px rgba(0,0,0,0.28)'
                : '0 1px 4px rgba(0,0,0,0.18)',
              color: clip.enabled && !muted ? '#ffffff' : EDITOR_SURFACE_COLORS.muted,
              cursor: locked ? 'not-allowed' : editable ? 'grab' : 'pointer',
              touchAction: editable ? 'none' : 'auto',
              fontSize: 10,
              lineHeight: compact ? '20px' : 1.2,
              textAlign: compact ? 'center' : 'left',
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              px: compact ? 0 : 0.75,
              py: compact ? 0 : 0.45,
              transition: 'all 150ms ease',
              opacity: muted ? 0.5 : 1,
              '&:hover': {
                transform: locked ? 'none' : 'translateY(-2px)',
                borderColor: locked ? 'rgba(148,163,184,0.14)' : EDITOR_SURFACE_COLORS.accent,
                boxShadow: locked ? 'none' : '0 8px 16px rgba(0,0,0,0.28)',
              },
              '&:active': {
                cursor: editable ? 'grabbing' : locked ? 'not-allowed' : 'pointer',
              },
              '&::after': selected
                ? {
                    content: '""',
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    borderRadius: 0.75,
                    background: 'linear-gradient(135deg, rgba(255,255,255,0.15) 0%, transparent 100%)',
                  }
                : {},
            }}
          >
            {compact ? (
              clip.label
            ) : (
              <>
                <Typography
                  component="span"
                  sx={{
                    display: 'block',
                    color: 'inherit',
                    fontSize: 10,
                    fontWeight: 800,
                    lineHeight: 1.1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {clip.label}
                </Typography>
                <Typography
                  component="span"
                  sx={{
                    display: 'block',
                    mt: 0.25,
                    color: 'rgba(255,255,255,0.78)',
                    fontSize: 10,
                    lineHeight: 1.15,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {clip.textPreview}
                </Typography>
              </>
            )}
            {editable && (
              <>
                <Box
                  onPointerDown={(event) => handlePointerEdit(event, 'resize-start')}
                  sx={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 7,
                    cursor: 'ew-resize',
                    bgcolor: 'rgba(255,255,255,0.18)',
                    borderTopLeftRadius: 3,
                    borderBottomLeftRadius: 3,
                  }}
                />
                <Box
                  onPointerDown={(event) => handlePointerEdit(event, 'resize-end')}
                  sx={{
                    position: 'absolute',
                    right: 0,
                    top: 0,
                    bottom: 0,
                    width: 7,
                    cursor: 'ew-resize',
                    bgcolor: 'rgba(255,255,255,0.18)',
                    borderTopRightRadius: 3,
                    borderBottomRightRadius: 3,
                  }}
                />
              </>
            )}
          </Box>
        </Tooltip>
      )
    })}
  </Box>
)

const ScriptEditorDialog = ({
  open,
  loading,
  chapter,
  data,
  onClose,
  onChangeSegmentText,
  onSaveScript,
  onPreviewSegmentAudio,
  onRegenerateSegment,
  onStartSegmentVoiceRecording,
  onStopSegmentVoiceRecording,
  onApplySegmentRegeneration,
  onDiscardSegmentRegeneration,
  onReviewSegment,
  segmentReviews,
  pendingSegmentRegenerations,
  recordingSegmentIndex,
  segmentPreviewingIndex,
  segmentPreviewingType,
  segmentAudioUrls,
  segmentDetailsOpen,
  onToggleSegmentDetails,
  onUpdateSegment,
  timelineEdits,
  onChangeTimelineEdits,
  reviewMode,
  onToggleReviewMode,
  regeneratingSegments,
  smartChunkPreview,
  smartChunkPreviewLoading,
  onPreviewSmartChunking,
  editorConflict,
  editorConflictTimeLabel,
  editorConflictPreview,
  visibleEditorConflictSegmentDiffs = [],
  hiddenEditorConflictSegmentDiffCount = 0,
  onApplyIncomingDraft,
  onKeepLocalDraft,
  projectId,
}: ScriptEditorDialogProps) => {
  const [consistencyChecking, setConsistencyChecking] = useState(false)
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(0)
  const [timelineScale, setTimelineScale] = useState(1)
  const [timelineSeeking, setTimelineSeeking] = useState(false)
  const timelineContentRef = useRef<HTMLDivElement | null>(null)
  const [trackLocks, setTrackLocks] = useState<Record<TimelineTrackKey, boolean>>({
    scriptVoice: false,
    sfx: false,
    music: false,
  })
  const [trackMutes, setTrackMutes] = useState<Record<TimelineTrackKey, boolean>>({
    scriptVoice: false,
    sfx: false,
    music: false,
  })
  const [searchQuery, setSearchQuery] = useState('')
  const [filterType, setFilterType] = useState<FilterType>('all')
  const [inspectorTab, setInspectorTab] = useState<'overview' | 'review' | 'consistency' | 'diagnosis'>('overview')
  const [collapsedPanels, setCollapsedPanels] = useState<{ voice: boolean; sfx: boolean; music: boolean }>({
    voice: false,
    sfx: false,
    music: false,
  })
  const [copiedText, setCopiedText] = useState<string | null>(null)
  const [consistencyResult, setConsistencyResult] = useState<{
    is_consistent: boolean
    consistency_score: number
    analysis_summary: string
  } | null>(null)
  const [consistencyError, setConsistencyError] = useState<string | null>(null)
  const scriptSegments = data?.scriptSegments || []
  const safeSelectedSegmentIndex = scriptSegments.length
    ? Math.min(selectedSegmentIndex, scriptSegments.length - 1)
    : 0
  const selectedSegment = scriptSegments[safeSelectedSegmentIndex] || null

  // 提前定义基础导航函数（供后续useEffect使用）
  const handleSelectSegment = useCallback((index: number) => {
    if (!scriptSegments.length) return
    setSelectedSegmentIndex(Math.max(0, Math.min(index, scriptSegments.length - 1)))
  }, [scriptSegments.length])

  const handlePreviousSegment = useCallback(() => {
    setSelectedSegmentIndex((current) => Math.max(0, current - 1))
  }, [])

  const handleNextSegment = useCallback(() => {
    setSelectedSegmentIndex((current) => Math.min(scriptSegments.length - 1, current + 1))
  }, [scriptSegments.length])

  const selectedSegmentSfx = useMemo(
    () => (selectedSegment ? getSoundEffectsInputValue(selectedSegment) : ''),
    [selectedSegment],
  )
  const selectedSegmentMusic = useMemo(
    () => (selectedSegment ? getMusicCueInputValue(selectedSegment) : ''),
    [selectedSegment],
  )
  const selectedSegmentTextLength = String(selectedSegment?.text || '').trim().length
  const selectedSegmentSfxCount = selectedSegmentSfx
    ? selectedSegmentSfx.split(',').map((item) => item.trim()).filter(Boolean).length
    : 0
  const selectedSegmentProgress = scriptSegments.length
    ? `${safeSelectedSegmentIndex + 1} / ${scriptSegments.length}`
    : '0 / 0'
  const selectedSegmentEmotion = selectedSegment
    ? selectedSegment.emotion || selectedSegment.voice_params?.emotion || '未标注'
    : '未选择'
  const reviewedCount = useMemo(() => Object.keys(segmentReviews).length, [segmentReviews])
  const chapterAudioAvailable = data?.chapterAudioAvailable === true
  const visibleSegmentCards = useMemo(
    () => scriptSegments.map((segment, index) => {
      const sfx = getSoundEffectsInputValue(segment)
      const music = getMusicCueInputValue(segment)
      const text = String(segment.text || '').trim()
      return {
        index,
        summary: formatScriptSegmentSummary(segment, index),
        textPreview: text || '空片段',
        hasSfx: sfx.length > 0,
        hasMusic: music.length > 0,
        reviewed: Boolean(segmentReviews[index]),
      }
    }),
    [scriptSegments, segmentReviews],
  )
  const audioCueStats = useMemo(() => {
    let sfxCueCount = 0
    let musicCueCount = 0
    let totalTextLength = 0

    for (const segment of scriptSegments) {
      totalTextLength += String(segment.text || '').trim().length
      if (getSoundEffectsInputValue(segment).length > 0) {
        sfxCueCount += 1
      }
      if (getMusicCueInputValue(segment).length > 0) {
        musicCueCount += 1
      }
    }

    return { sfxCueCount, musicCueCount, totalTextLength }
  }, [scriptSegments])
  const timelineModel = useMemo(
    () => buildTimelineModel(scriptSegments),
    [scriptSegments],
  )
  const editedTimelineModel = useMemo(
    () => applyTimelineEdits(timelineModel, timelineEdits),
    [timelineModel, timelineEdits],
  )
  const timelineContentWidth = Math.max(
    TIMELINE_MIN_CONTENT_WIDTH,
    Math.round(editedTimelineModel.totalUnits * timelineScale) + TIMELINE_SIDE_PADDING * 2,
  )
  const playheadLeft = scriptSegments.length > 0
    ? TIMELINE_SIDE_PADDING
      + Math.round((editedTimelineModel.segmentOffsets[safeSelectedSegmentIndex] ?? 0) * timelineScale)
    : TIMELINE_SIDE_PADDING

  const resolveTimelineSeekPlaybackType = useCallback((seekIndex: number): PreviewType => {
    const segment = scriptSegments[seekIndex]
    const pending = pendingSegmentRegenerations[seekIndex]

    if (pending?.mix || segment?.mix_audio_path) return 'mix'
    if (chapterAudioAvailable) return 'mix'
    if (pending?.voice || segment?.audio_path) return 'voice'
    if (pending?.sfx || segment?.sfx_audio_path) return 'sfx'
    if (pending?.bgm || segment?.bgm_audio_path) return 'bgm'
    return 'voice'
  }, [chapterAudioAvailable, pendingSegmentRegenerations, scriptSegments])

  const getTimelineSeekUnitFromClientX = useCallback((clientX: number): number => {
    const container = timelineContentRef.current
    if (!container || timelineScale <= 0) return 0

    const rect = container.getBoundingClientRect()
    const relativeX = clientX - rect.left - TIMELINE_SIDE_PADDING
    return Math.round(Math.max(
      0,
      Math.min(editedTimelineModel.totalUnits, relativeX / timelineScale),
    ))
  }, [editedTimelineModel.totalUnits, timelineScale])

  const handleTimelineSeekAtClientX = useCallback((clientX: number, play = false) => {
    if (!scriptSegments.length) return

    const seekUnit = getTimelineSeekUnitFromClientX(clientX)
    const seekIndex = resolveTimelineSeekSegmentIndex(editedTimelineModel, seekUnit)
    setSelectedSegmentIndex(seekIndex)

    if (play && scriptSegments[seekIndex]) {
      onPreviewSegmentAudio(seekIndex, scriptSegments[seekIndex], resolveTimelineSeekPlaybackType(seekIndex), {
        startRatio: resolveTimelineSeekSegmentOffsetRatio(editedTimelineModel, seekIndex, seekUnit),
      })
    }
  }, [
    editedTimelineModel,
    getTimelineSeekUnitFromClientX,
    onPreviewSegmentAudio,
    resolveTimelineSeekPlaybackType,
    scriptSegments,
  ])

  const handleTimelineSeekPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!scriptSegments.length) return

    event.preventDefault()
    event.stopPropagation()

    const target = event.currentTarget
    const pointerId = event.pointerId
    setTimelineSeeking(true)
    handleTimelineSeekAtClientX(event.clientX)
    target.setPointerCapture(pointerId)

    function cleanup() {
      if (target.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId)
      }
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerCancel)
    }

    function handlePointerMove(moveEvent: PointerEvent) {
      handleTimelineSeekAtClientX(moveEvent.clientX)
    }

    function handlePointerUp(upEvent: PointerEvent) {
      handleTimelineSeekAtClientX(upEvent.clientX, true)
      setTimelineSeeking(false)
      cleanup()
    }

    function handlePointerCancel() {
      setTimelineSeeking(false)
      cleanup()
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerCancel)
  }, [handleTimelineSeekAtClientX, scriptSegments.length])

  const timelineTracks: Array<{
    key: TimelineTrackKey
    label: string
    icon: JSX.Element
    color: string
    height: number
    compact: boolean
  }> = [
    {
      key: 'scriptVoice',
      label: '脚本/人声',
      icon: <MicIcon sx={{ fontSize: 16 }} />,
      color: EDITOR_TRACK_COLORS.scriptVoice,
      height: TIMELINE_PRIMARY_TRACK_HEIGHT,
      compact: false,
    },
    {
      key: 'sfx',
      label: '音效轨',
      icon: <GraphicEqIcon sx={{ fontSize: 16 }} />,
      color: EDITOR_TRACK_COLORS.sfx,
      height: TIMELINE_AUDIO_TRACK_HEIGHT,
      compact: true,
    },
    {
      key: 'music',
      label: '配乐轨',
      icon: <LibraryMusicIcon sx={{ fontSize: 16 }} />,
      color: EDITOR_TRACK_COLORS.music,
      height: TIMELINE_AUDIO_TRACK_HEIGHT,
      compact: true,
    },
  ]
  const timelineTracksHeight = timelineTracks.reduce((total, track) => total + track.height, 0)

  const handleAdjustTimelineClip = useCallback((
    clip: TimelineClip,
    operation: TimelineClipEditOperation,
    deltaUnits: number,
    baseEdit: { startUnit: number; durationUnits: number },
  ) => {
    if (!isTimelineClipEditable(clip)) return

    onChangeTimelineEdits((current) => {
      const nextEdit = adjustTimelineClipEdit(baseEdit, {
        operation,
        deltaUnits,
        totalUnits: Math.max(editedTimelineModel.totalUnits, baseEdit.startUnit + baseEdit.durationUnits),
        minDurationUnits: TIMELINE_MIN_EDIT_DURATION_UNITS,
      })

      return {
        ...current,
        [clip.key]: nextEdit,
      }
    })
  }, [editedTimelineModel.totalUnits, onChangeTimelineEdits])

  const handleCheckConsistency = async () => {
    if (!data?.scriptSegments?.length) return
    setConsistencyChecking(true)
    setConsistencyError(null)
    try {
      const segmentsText = data.scriptSegments
        .map((s: ScriptSegment, i: number) => `[${i + 1}] ${s.text || ''}`)
        .join('\n')
      const res = await apiClient.checkConsistency({
        world_settings: [{ type: '剧本', name: chapter?.title || '当前章节', content: segmentsText }],
        new_content: segmentsText,
        project_id: projectId,
      })
      setConsistencyResult({
        is_consistent: res.data.is_consistent,
        consistency_score: res.data.consistency_check.consistency_score,
        analysis_summary: res.data.consistency_check.analysis_summary,
      })
    } catch (err: unknown) {
      setConsistencyError(await extractApiErrorMessage(err, '一致性检查失败'))
    } finally {
      setConsistencyChecking(false)
    }
  }

  // 键盘快捷键支持
  useEffect(() => {
    const handleKeyPress = (event: KeyboardEvent) => {
      // 只在对话框打开时生效
      if (!open) return

      // Ctrl/Cmd + 箭头键：快速切换片段
      if ((event.ctrlKey || event.metaKey) && event.key === 'ArrowLeft') {
        event.preventDefault()
        handlePreviousSegment()
      } else if ((event.ctrlKey || event.metaKey) && event.key === 'ArrowRight') {
        event.preventDefault()
        handleNextSegment()
      }

      // Escape：关闭对话框
      if (event.key === 'Escape' && !loading) {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyPress)
    return () => window.removeEventListener('keydown', handleKeyPress)
  }, [open, loading, onClose, handlePreviousSegment, handleNextSegment])

  // 过滤片段列表
  const filteredSegmentCards = useMemo(() => {
    let result = visibleSegmentCards

    // 文本搜索
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      result = result.filter((item) =>
        item.textPreview.toLowerCase().includes(query) ||
        item.summary.toLowerCase().includes(query)
      )
    }

    // 类型过滤
    if (filterType === 'sfx') {
      result = result.filter((item) => item.hasSfx)
    } else if (filterType === 'music') {
      result = result.filter((item) => item.hasMusic)
    } else if (filterType === 'review') {
      result = result.filter((item) => item.reviewed)
    } else if (filterType === 'warning') {
      // TODO: 根据实际警告逻辑过滤
      result = result.filter((item) => !item.reviewed)
    }

    return result
  }, [visibleSegmentCards, searchQuery, filterType])

  // 复制文本到剪贴板
  const handleCopyText = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedText(text)
      setTimeout(() => setCopiedText(null), 2000)
    } catch (err) {
      console.error('复制失败:', err)
    }
  }, [])

  // 粘贴文本
  const handlePasteText = useCallback(async (segmentIndex: number) => {
    try {
      const text = await navigator.clipboard.readText()
      onChangeSegmentText(segmentIndex, text)
    } catch (err) {
      console.error('粘贴失败:', err)
    }
  }, [onChangeSegmentText])

  // 清空文本
  const handleClearText = useCallback((segmentIndex: number) => {
    onChangeSegmentText(segmentIndex, '')
  }, [onChangeSegmentText])

  // 切换轨道锁定状态
  const toggleTrackLock = useCallback((track: keyof typeof trackLocks) => {
    setTrackLocks((prev) => ({ ...prev, [track]: !prev[track] }))
  }, [])

  // 切换轨道静音状态
  const toggleTrackMute = useCallback((track: keyof typeof trackMutes) => {
    setTrackMutes((prev) => ({ ...prev, [track]: !prev[track] }))
  }, [])

  // 切换面板折叠状态
  const togglePanelCollapse = useCallback((panel: keyof typeof collapsedPanels) => {
    setCollapsedPanels((prev) => ({ ...prev, [panel]: !prev[panel] }))
  }, [])

  return (
  <Dialog
    open={open}
    onClose={onClose}
    fullScreen
    PaperProps={{
      sx: {
        width: '100vw',
        maxWidth: '100vw',
        height: '100dvh',
        maxHeight: '100dvh',
        m: 0,
        borderRadius: 0,
        display: 'grid',
        gridTemplateRows: 'minmax(0, 1fr)',
        overflow: 'hidden',
        bgcolor: EDITOR_SURFACE_COLORS.app,
      },
    }}
  >
    <DialogContent dividers sx={{ p: 0, overflow: 'hidden', minHeight: 0, borderColor: EDITOR_SURFACE_COLORS.border }}>
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={28} />
        </Box>
      ) : !data ? (
        <Typography variant="body2" sx={editorMutedTextSx}>
          暂无剧本数据，请先生成剧本。
        </Typography>
      ) : (
        <Box sx={editorShellSx}>
          {editorConflict && (
            <ScriptEditorConflictNotice
              timeLabel={editorConflictTimeLabel}
              preview={editorConflictPreview}
              visibleSegmentDiffs={visibleEditorConflictSegmentDiffs}
              hiddenSegmentDiffCount={hiddenEditorConflictSegmentDiffCount}
              onApplyIncomingDraft={onApplyIncomingDraft}
              onKeepLocalDraft={onKeepLocalDraft}
            />
          )}

          <Box sx={editorWorkspaceSx}>
            <Box sx={segmentNavigatorSx}>
              <Box sx={panelHeaderSx}>
                <Box sx={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Tooltip title="关闭编辑器">
                    <span>
                      <IconButton
                        size="small"
                        aria-label="关闭编辑器"
                        onClick={onClose}
                        disabled={loading}
                        sx={{
                          flexShrink: 0,
                          width: 34,
                          height: 34,
                          color: EDITOR_SURFACE_COLORS.danger,
                          border: '1px solid',
                          borderColor: 'rgba(255,92,112,0.46)',
                          bgcolor: 'rgba(255,92,112,0.13)',
                          '&:hover': {
                            color: '#fff',
                            borderColor: EDITOR_SURFACE_COLORS.danger,
                            bgcolor: 'rgba(255,92,112,0.28)',
                          },
                        }}
                      >
                        <CloseIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      variant="subtitle1"
                      sx={{ fontWeight: 800, lineHeight: 1.25, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                    >
                      {chapter?.title || '章节剪辑'}
                    </Typography>
                    <Typography variant="caption" sx={editorMutedTextSx}>
                      {filteredSegmentCards.length} / {scriptSegments.length} 段 · {audioCueStats.totalTextLength} 字
                    </Typography>
                  </Box>
                </Box>
              </Box>

              {/* 搜索框 */}
              <Box sx={editorSearchBarSx}>
                <TextField
                  fullWidth
                  size="small"
                  placeholder="搜索片段内容..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <SearchIcon sx={{ fontSize: 16, color: EDITOR_SURFACE_COLORS.muted }} />
                      </InputAdornment>
                    ),
                  }}
                  sx={{ mb: 0.75 }}
                />

                {/* 过滤按钮 */}
                <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                  <Tooltip title="显示全部片段">
                    <Chip
                      size="small"
                      label={`全部 (${scriptSegments.length})`}
                      onClick={() => setFilterType('all')}
                      variant={filterType === 'all' ? 'filled' : 'outlined'}
                      sx={editorFilterChipSx(filterType === 'all', EDITOR_SURFACE_COLORS.accent)}
                    />
                  </Tooltip>
                  <Tooltip title="有音效的片段">
                    <Chip
                      size="small"
                      label={`音效 (${audioCueStats.sfxCueCount})`}
                      onClick={() => setFilterType('sfx')}
                      variant={filterType === 'sfx' ? 'filled' : 'outlined'}
                      sx={editorFilterChipSx(filterType === 'sfx', EDITOR_TRACK_COLORS.sfx)}
                    />
                  </Tooltip>
                  <Tooltip title="有配乐的片段">
                    <Chip
                      size="small"
                      label={`配乐 (${audioCueStats.musicCueCount})`}
                      onClick={() => setFilterType('music')}
                      variant={filterType === 'music' ? 'filled' : 'outlined'}
                      sx={editorFilterChipSx(filterType === 'music', EDITOR_TRACK_COLORS.music)}
                    />
                  </Tooltip>
                  {reviewMode && (
                    <Tooltip title="已评审的片段">
                      <Chip
                        size="small"
                        label={`已评 (${reviewedCount})`}
                        onClick={() => setFilterType('review')}
                        variant={filterType === 'review' ? 'filled' : 'outlined'}
                        sx={editorFilterChipSx(filterType === 'review', EDITOR_SURFACE_COLORS.success)}
                      />
                    </Tooltip>
                  )}
                </Stack>
              </Box>

              <Box sx={{ minHeight: 0, overflow: 'auto', p: 1 }}>
                {filteredSegmentCards.length === 0 ? (
                  <Box sx={{ p: 2, textAlign: 'center' }}>
                    <Typography variant="body2" sx={editorMutedTextSx}>
                      未找到匹配的片段
                    </Typography>
                  </Box>
                ) : (
                  <Stack spacing={0.75}>
                    {filteredSegmentCards.map((item) => {
                      const selected = item.index === safeSelectedSegmentIndex
                      return (
                        <Box
                          key={item.index}
                          role="button"
                          tabIndex={0}
                          onClick={() => handleSelectSegment(item.index)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              handleSelectSegment(item.index)
                            }
                          }}
                          sx={{
                            p: 1,
                            border: '1px solid',
                            borderColor: selected ? EDITOR_SURFACE_COLORS.accent : EDITOR_SURFACE_COLORS.border,
                            borderRadius: 1,
                            bgcolor: selected ? EDITOR_SURFACE_COLORS.accentSoft : EDITOR_SURFACE_COLORS.panelSoft,
                            cursor: 'pointer',
                            transition: 'all 120ms ease',
                            boxShadow: selected ? 'inset 3px 0 0 #10d7e2, 0 10px 20px rgba(0,0,0,0.2)' : 'none',
                            '&:hover': {
                              bgcolor: selected ? 'rgba(16,215,226,0.2)' : 'rgba(255,255,255,0.06)',
                              borderColor: selected ? EDITOR_SURFACE_COLORS.accent : EDITOR_SURFACE_COLORS.borderStrong,
                              transform: 'translateY(-1px)',
                              boxShadow: '0 8px 18px rgba(0,0,0,0.22)',
                            },
                          }}
                        >
                          <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: selected ? EDITOR_SURFACE_COLORS.accent : EDITOR_SURFACE_COLORS.text }}>
                              #{item.index + 1}
                            </Typography>
                            <Typography variant="caption" sx={editorMutedTextSx}>
                              {item.textPreview.length} 字
                            </Typography>
                          </Stack>
                          <Typography
                            variant="caption"
                            sx={{ ...editorMutedTextSx, display: 'block', mt: 0.25, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                          >
                            {item.summary}
                          </Typography>
                          <Stack direction="row" spacing={0.5} sx={{ mt: 0.75, flexWrap: 'wrap', rowGap: 0.5 }}>
                            <Badge badgeContent={item.hasSfx ? null : 0} color="warning">
                              <Chip size="small" label="音效" color={item.hasSfx ? 'warning' : 'default'} />
                            </Badge>
                            <Badge badgeContent={item.hasMusic ? null : 0} color="secondary">
                              <Chip size="small" label="配乐" color={item.hasMusic ? 'secondary' : 'default'} />
                            </Badge>
                            {reviewMode && (
                              <Chip
                                size="small"
                                label={item.reviewed ? '✓ 已评' : '待评'}
                                color={item.reviewed ? 'success' : 'default'}
                                sx={{ fontWeight: item.reviewed ? 600 : 400 }}
                              />
                            )}
                          </Stack>
                        </Box>
                      )
                    })}
                  </Stack>
                )}
              </Box>
            </Box>

            <Box sx={focusSegmentPanelSx}>
              <Box sx={panelHeaderSx}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                    单片段工作台
                  </Typography>
                  <Typography variant="caption" sx={editorMutedTextSx}>
                    当前位置：{selectedSegmentProgress}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={0.75} alignItems="center">
                  <Tooltip title="上一段">
                    <span>
                      <IconButton
                        size="small"
                        onClick={handlePreviousSegment}
                        disabled={safeSelectedSegmentIndex <= 0}
                      >
                        <KeyboardArrowLeftIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Tooltip title="下一段">
                    <span>
                      <IconButton
                        size="small"
                        onClick={handleNextSegment}
                        disabled={safeSelectedSegmentIndex >= scriptSegments.length - 1}
                      >
                        <KeyboardArrowRightIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Stack>
              </Box>

              {selectedSegment ? (
                <Box sx={focusSegmentCardSx}>
                  <Stack direction={{ xs: 'column', md: 'row' }} spacing={1} justifyContent="space-between" sx={{ mb: 1.5 }}>
                    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
                      <Stack direction="row" spacing={0.75} alignItems="center" sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
                        <Chip size="small" label={`#${safeSelectedSegmentIndex + 1}`} color="primary" />
                        <Chip size="small" label={getScriptSegmentTypeLabel(selectedSegment)} />
                        <Chip size="small" label={getScriptSegmentSpeakerLabel(selectedSegment)} />
                        <Chip size="small" label={`情绪 ${selectedSegmentEmotion}`} />
                      </Stack>
                      <Typography variant="caption" sx={editorMutedTextSx}>
                        字数 {selectedSegmentTextLength} · 音效 {selectedSegmentSfxCount} · 配乐 {selectedSegmentMusic ? '已配置' : '未配置'}
                      </Typography>
                    </Stack>
                    <Box sx={{ width: { xs: '100%', md: 220 } }}>
                      <LinearProgress
                        variant="determinate"
                        value={scriptSegments.length ? ((safeSelectedSegmentIndex + 1) / scriptSegments.length) * 100 : 0}
                        sx={{ height: 8, borderRadius: 1, mt: { xs: 0, md: 0.5 } }}
                      />
                    </Box>
                  </Stack>

                  {/* 文本编辑器头部工具栏 */}
                  <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                      片段文本
                    </Typography>
                    <Stack direction="row" spacing={0.5}>
                      <Tooltip title={`复制${copiedText === selectedSegment.text ? '成功！' : ''}`}>
                        <IconButton
                          size="small"
                          onClick={() => handleCopyText(selectedSegment.text || '')}
                          disabled={!selectedSegment.text}
                        >
                          <ContentCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="粘贴文本">
                        <IconButton
                          size="small"
                          onClick={() => handlePasteText(safeSelectedSegmentIndex)}
                        >
                          <ContentPasteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="清空文本">
                        <IconButton
                          size="small"
                          onClick={() => handleClearText(safeSelectedSegmentIndex)}
                          disabled={!selectedSegment.text}
                        >
                          <ClearIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </Stack>

                  <TextField
                    fullWidth
                    multiline
                    minRows={7}
                    maxRows={14}
                    label="片段文本"
                    value={selectedSegment.text || ''}
                    onChange={(event) => onChangeSegmentText(safeSelectedSegmentIndex, event.target.value)}
                    InputProps={{
                      endAdornment: (
                        <InputAdornment position="end">
                          <Typography
                            variant="caption"
                            sx={{
                              color: selectedSegmentTextLength > 500 ? EDITOR_SURFACE_COLORS.danger : EDITOR_SURFACE_COLORS.muted,
                              fontWeight: selectedSegmentTextLength > 500 ? 600 : 400,
                            }}
                          >
                            {selectedSegmentTextLength} 字
                          </Typography>
                        </InputAdornment>
                      ),
                    }}
                    helperText={selectedSegmentTextLength > 500 ? '文本长度超过建议值（500字）' : ''}
                  />

                  {/* 可折叠的提示面板 */}
                  <Box
                    sx={{
                      display: 'grid',
                      gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' },
                      gap: 1,
                      mt: 1.5,
                    }}
                  >
                    {/* 人声提示面板 */}
                    <Box sx={editorCuePanelSx(EDITOR_TRACK_COLORS.scriptVoice)}>
                      <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <TextSnippetIcon sx={{ fontSize: 17, color: EDITOR_TRACK_COLORS.scriptVoice }} />
                          <Typography variant="caption" sx={{ fontWeight: 700 }}>人声提示</Typography>
                        </Stack>
                        <IconButton
                          size="small"
                          onClick={() => togglePanelCollapse('voice')}
                          sx={{ p: 0.25 }}
                        >
                          {collapsedPanels.voice ? <ExpandMoreIcon sx={{ fontSize: 16 }} /> : <ExpandLessIcon sx={{ fontSize: 16 }} />}
                        </IconButton>
                      </Stack>
                      {!collapsedPanels.voice && (
                        <Typography variant="caption" sx={editorMutedTextSx}>
                          {selectedSegment.performance_notes || selectedSegmentEmotion}
                        </Typography>
                      )}
                    </Box>

                    {/* 音效提示面板 */}
                    <Box sx={editorCuePanelSx(EDITOR_TRACK_COLORS.sfx)}>
                      <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <GraphicEqIcon sx={{ fontSize: 17, color: EDITOR_TRACK_COLORS.sfx }} />
                          <Typography variant="caption" sx={{ fontWeight: 700 }}>音效提示</Typography>
                        </Stack>
                        <IconButton
                          size="small"
                          onClick={() => togglePanelCollapse('sfx')}
                          sx={{ p: 0.25 }}
                        >
                          {collapsedPanels.sfx ? <ExpandMoreIcon sx={{ fontSize: 16 }} /> : <ExpandLessIcon sx={{ fontSize: 16 }} />}
                        </IconButton>
                      </Stack>
                      {!collapsedPanels.sfx && (
                        <>
                          <Typography variant="caption" sx={{ ...editorMutedTextSx, display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {selectedSegmentSfx || '未配置'}
                          </Typography>
                          {selectedSegmentSfxCount > 0 && (
                            <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap' }}>
                              {selectedSegmentSfx.split(',').map((sfx, idx) => {
                                const trimmed = sfx.trim()
                                return trimmed ? (
                                  <Chip key={idx} size="small" label={trimmed} sx={{ height: 20, fontSize: 10 }} />
                                ) : null
                              })}
                            </Stack>
                          )}
                        </>
                      )}
                    </Box>

                    {/* 配乐提示面板 */}
                    <Box sx={editorCuePanelSx(EDITOR_TRACK_COLORS.music)}>
                      <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between" sx={{ mb: 0.5 }}>
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <LibraryMusicIcon sx={{ fontSize: 17, color: EDITOR_TRACK_COLORS.music }} />
                          <Typography variant="caption" sx={{ fontWeight: 700 }}>配乐提示</Typography>
                        </Stack>
                        <IconButton
                          size="small"
                          onClick={() => togglePanelCollapse('music')}
                          sx={{ p: 0.25 }}
                        >
                          {collapsedPanels.music ? <ExpandMoreIcon sx={{ fontSize: 16 }} /> : <ExpandLessIcon sx={{ fontSize: 16 }} />}
                        </IconButton>
                      </Stack>
                      {!collapsedPanels.music && (
                        <Typography variant="caption" sx={{ ...editorMutedTextSx, display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {selectedSegmentMusic || '未配置'}
                        </Typography>
                      )}
                    </Box>
                  </Box>

                  <ScriptSegmentActions
                    segment={selectedSegment}
                    index={safeSelectedSegmentIndex}
                    detailsOpen={Boolean(segmentDetailsOpen[safeSelectedSegmentIndex])}
                    reviewMode={reviewMode}
                    review={segmentReviews[safeSelectedSegmentIndex]}
                    pendingRegeneration={pendingSegmentRegenerations[safeSelectedSegmentIndex]}
                    previewingType={segmentPreviewingIndex === safeSelectedSegmentIndex ? segmentPreviewingType : null}
                    regenerating={regeneratingSegments.has(safeSelectedSegmentIndex)}
                    voiceRecording={recordingSegmentIndex === safeSelectedSegmentIndex}
                    voiceRecordingDisabled={recordingSegmentIndex !== null && recordingSegmentIndex !== safeSelectedSegmentIndex}
                    chapterAudioAvailable={chapterAudioAvailable}
                    onPreviewAudio={onPreviewSegmentAudio}
                    onRegenerate={onRegenerateSegment}
                    onStartVoiceRecording={onStartSegmentVoiceRecording}
                    onStopVoiceRecording={onStopSegmentVoiceRecording}
                    onApplyRegeneration={onApplySegmentRegeneration}
                    onDiscardRegeneration={onDiscardSegmentRegeneration}
                    onReview={onReviewSegment}
                    onToggleDetails={onToggleSegmentDetails}
                    menuPaperSx={editorFloatingPaperSx}
                    mutedTextColor={EDITOR_SURFACE_COLORS.muted}
                  />

                  {segmentDetailsOpen[safeSelectedSegmentIndex] && (
                    <ScriptSegmentDetailsPanel
                      segment={selectedSegment}
                      index={safeSelectedSegmentIndex}
                      onUpdateSegment={onUpdateSegment}
                      sx={editorDetailsPanelSx}
                      audioPickerPaperSx={editorFloatingPaperSx}
                      mutedTextColor={EDITOR_SURFACE_COLORS.muted}
                    />
                  )}

                  {segmentAudioUrls[safeSelectedSegmentIndex] && (
                    <Box sx={{ mt: 1.5 }}>
                      <audio controls src={segmentAudioUrls[safeSelectedSegmentIndex]} style={{ width: '100%' }} />
                    </Box>
                  )}
                </Box>
              ) : (
                <Box sx={{ p: 2 }}>
                  <Typography variant="body2" sx={editorMutedTextSx}>
                    暂无可编辑片段。
                  </Typography>
                </Box>
              )}
            </Box>

            <Box sx={segmentInspectorSx}>
              <Box sx={panelHeaderSx}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                    属性检查器
                  </Typography>
                  <Typography variant="caption" sx={editorMutedTextSx}>
                    评审、诊断与一致性状态
                  </Typography>
                </Box>
                <Button
                  size="small"
                  variant={reviewMode ? 'contained' : 'outlined'}
                  startIcon={<TuneIcon fontSize="small" />}
                  onClick={onToggleReviewMode}
                  sx={reviewMode ? editorPrimaryActionSx : undefined}
                >
                  {reviewMode ? '退出标注' : '评审标注'}
                </Button>
              </Box>

              {/* Tab页签 */}
              <Tabs
                value={inspectorTab}
                onChange={(_, newValue) => setInspectorTab(newValue)}
                variant="fullWidth"
                sx={editorTabsSx}
              >
                <Tab label="概览" value="overview" />
                <Tab label="评审报告" value="review" />
                <Tab label="一致性" value="consistency" />
                <Tab label="诊断" value="diagnosis" />
              </Tabs>

              <Box sx={{ minHeight: 0, overflow: 'auto', p: 1.5 }}>
                {/* 概览标签页 */}
                {inspectorTab === 'overview' && (
                  <>
                    <Box sx={{ ...editorInlinePanelSx, mb: 1.5 }}>
                      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                          当前片段
                        </Typography>
                        <Typography variant="caption" sx={editorMutedTextSx}>
                          {selectedSegment ? `#${safeSelectedSegmentIndex + 1}` : '未选择'}
                        </Typography>
                      </Stack>
                      {selectedSegment ? (
                        <Stack spacing={0.75}>
                          <Typography variant="body2">
                            {getScriptSegmentTypeLabel(selectedSegment)} · {getScriptSegmentSpeakerLabel(selectedSegment)}
                          </Typography>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            当前位置：{selectedSegmentProgress}
                          </Typography>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            情绪：{selectedSegmentEmotion}
                          </Typography>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            字数 {selectedSegmentTextLength} · 音效 {selectedSegmentSfxCount} · 配乐 {selectedSegmentMusic ? '已配置' : '未配置'}
                          </Typography>
                        </Stack>
                      ) : (
                        <Typography variant="body2" sx={editorMutedTextSx}>
                          暂无可检查的片段。
                        </Typography>
                      )}
                    </Box>

                    {reviewMode && (
                      <Box sx={{ mb: 1.5 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            审查进度
                          </Typography>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            {reviewedCount} / {scriptSegments.length || 0}
                          </Typography>
                        </Box>
                        <LinearProgress
                          variant="determinate"
                          value={scriptSegments.length ? (reviewedCount / scriptSegments.length) * 100 : 0}
                          sx={{ height: 6, borderRadius: 1 }}
                        />
                      </Box>
                    )}

                    {/* 快速统计卡片 */}
                    <Stack spacing={1}>
                      <Box sx={editorMetricPanelSx(EDITOR_SURFACE_COLORS.accent)}>
                        <Typography variant="caption" sx={{ fontWeight: 600, color: EDITOR_SURFACE_COLORS.muted }}>
                          总片段数
                        </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: EDITOR_SURFACE_COLORS.accent }}>
                          {scriptSegments.length}
                        </Typography>
                      </Box>
                      <Box sx={editorMetricPanelSx(EDITOR_TRACK_COLORS.sfx)}>
                        <Typography variant="caption" sx={{ fontWeight: 600, color: EDITOR_SURFACE_COLORS.muted }}>
                          音效提示词
                        </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: EDITOR_TRACK_COLORS.sfx }}>
                          {audioCueStats.sfxCueCount}
                        </Typography>
                      </Box>
                      <Box sx={editorMetricPanelSx(EDITOR_TRACK_COLORS.music)}>
                        <Typography variant="caption" sx={{ fontWeight: 600, color: EDITOR_SURFACE_COLORS.muted }}>
                          配乐提示词
                        </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: EDITOR_TRACK_COLORS.music }}>
                          {audioCueStats.musicCueCount}
                        </Typography>
                      </Box>
                    </Stack>
                  </>
                )}

                {/* 评审标签页 */}
                {inspectorTab === 'review' && (
                  <>
                    {reviewMode && (
                      <Box sx={{ mb: 1.5 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            审查进度
                          </Typography>
                          <Typography variant="caption" sx={editorMutedTextSx}>
                            {reviewedCount} / {scriptSegments.length || 0}
                          </Typography>
                        </Box>
                        <LinearProgress
                          variant="determinate"
                          value={scriptSegments.length ? (reviewedCount / scriptSegments.length) * 100 : 0}
                          sx={{ height: 6, borderRadius: 1 }}
                        />
                      </Box>
                    )}

                    <Typography variant="subtitle2" sx={{ fontWeight: 800, mb: 1 }}>
                      评审报告
                    </Typography>
                    {data.scriptReview ? (
                      <Box sx={editorEmbeddedContentSx}>
                        <ScriptReviewReport review={data.scriptReview} />
                      </Box>
                    ) : (
                      <Typography variant="body2" sx={editorMutedTextSx}>
                        暂无评审数据。
                      </Typography>
                    )}
                  </>
                )}

                {/* 一致性标签页 */}
                {inspectorTab === 'consistency' && (
                  <>
                    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                        一致性检查
                      </Typography>
                      <Button
                        size="small"
                        variant="outlined"
                        startIcon={consistencyChecking ? <CircularProgress size={14} /> : <VerifiedUserIcon />}
                        onClick={handleCheckConsistency}
                        disabled={consistencyChecking || !scriptSegments.length}
                      >
                        {consistencyChecking ? '检查中...' : '重新检查'}
                      </Button>
                    </Stack>

                    <Collapse in={Boolean(consistencyResult || consistencyError)} unmountOnExit>
                      <Box sx={{ mb: 1 }}>
                        {consistencyError && <Alert severity="error">{consistencyError}</Alert>}
                        {consistencyResult && (
                          <Alert
                            severity={consistencyResult.is_consistent ? 'success' : 'warning'}
                            icon={consistencyResult.is_consistent ? <CheckCircleIcon /> : <ErrorIcon />}
                          >
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              {consistencyResult.is_consistent ? '未发现一致性问题' : '发现潜在不一致'}
                              {consistencyResult.consistency_score > 0 && (
                                <>（评分：{(consistencyResult.consistency_score * 100).toFixed(0)}%）</>
                              )}
                            </Typography>
                            {consistencyResult.analysis_summary && (
                              <Typography variant="caption" sx={{ display: 'block', mt: 0.5, whiteSpace: 'pre-wrap' }}>
                                {consistencyResult.analysis_summary}
                              </Typography>
                            )}
                          </Alert>
                        )}
                      </Box>
                    </Collapse>
                    {!consistencyResult && !consistencyError && (
                      <Typography variant="body2" sx={editorMutedTextSx}>
                        尚未执行检查。点击"重新检查"开始分析。
                      </Typography>
                    )}
                  </>
                )}

                {/* 诊断标签页 */}
                {inspectorTab === 'diagnosis' && (
                  <>
                    <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                        分块诊断
                      </Typography>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={onPreviewSmartChunking}
                        disabled={smartChunkPreviewLoading}
                      >
                        {smartChunkPreviewLoading ? '诊断中...' : '重新诊断'}
                      </Button>
                    </Stack>

                    {smartChunkPreview ? (
                      <SmartChunkPreviewPanel
                        preview={smartChunkPreview}
                        mutedTextColor={EDITOR_SURFACE_COLORS.muted}
                        dangerTextColor={EDITOR_SURFACE_COLORS.danger}
                      />
                    ) : (
                      <Typography variant="body2" sx={editorMutedTextSx}>
                        暂无诊断结果。点击"重新诊断"开始分析。
                      </Typography>
                    )}
                  </>
                )}

                <Typography
                  variant="caption"
                  sx={{
                    display: 'block',
                    mt: 1.5,
                    pt: 1.5,
                    color: EDITOR_SURFACE_COLORS.muted,
                    borderTop: '1px solid',
                    borderColor: EDITOR_SURFACE_COLORS.border,
                  }}
                >
                  💡 提示：修改剧本后，建议重新生成该章节音频以保证文本与音频一致。
                </Typography>
              </Box>
            </Box>
          </Box>

          <Box sx={timelinePanelSx}>
            {/* 时间线头部控制栏 */}
            <Box
              sx={{
                px: 1.5,
                py: 0.75,
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) auto minmax(136px, 160px) auto' },
                gap: 1,
                alignItems: 'center',
                borderBottom: `1px solid ${EDITOR_SURFACE_COLORS.border}`,
                bgcolor: EDITOR_SURFACE_COLORS.panelRaised,
              }}
            >
              <Box>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, color: EDITOR_SURFACE_COLORS.text }}>
                    剪辑工作台
                  </Typography>
                  <Chip
                    size="small"
                    label={`#${safeSelectedSegmentIndex + 1}`}
                    sx={{
                      height: 20,
                      fontSize: 10,
                      bgcolor: EDITOR_SURFACE_COLORS.accentSoft,
                      color: EDITOR_SURFACE_COLORS.accent,
                      borderColor: 'rgba(16,215,226,0.42)',
                    }}
                  />
                </Stack>
                <Typography variant="caption" sx={{ color: EDITOR_SURFACE_COLORS.muted, mt: 0.25 }}>
                  主轨 {editedTimelineModel.clipsByTrack.scriptVoice.length} · 音效 {editedTimelineModel.clipsByTrack.sfx.length} · 配乐 {editedTimelineModel.clipsByTrack.music.length}
                  {Object.keys(timelineEdits).length > 0 && ` · 已调整 ${Object.keys(timelineEdits).length}`}
                </Typography>
              </Box>

              {/* 轨道控制按钮 */}
              <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 0.5 }}>
                {timelineTracks.map((track, index) => (
                  <Stack key={track.key} direction="row" spacing={0.5} alignItems="center">
                    {index > 0 && (
                      <Divider orientation="vertical" flexItem sx={{ borderColor: 'rgba(255,255,255,0.15)', mx: 0.5 }} />
                    )}
                    <Tooltip title={trackLocks[track.key] ? `解锁${track.label}` : `锁定${track.label}`}>
                      <IconButton
                        size="small"
                        onClick={() => toggleTrackLock(track.key)}
                        sx={{
                          color: trackLocks[track.key] ? EDITOR_SURFACE_COLORS.danger : EDITOR_SURFACE_COLORS.muted,
                          bgcolor: trackLocks[track.key] ? 'rgba(248,113,113,0.15)' : 'transparent',
                        }}
                      >
                        {trackLocks[track.key] ? <LockIcon sx={{ fontSize: 16 }} /> : track.icon}
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={trackMutes[track.key] ? `取消静音${track.label}` : `静音${track.label}`}>
                      <IconButton
                        size="small"
                        onClick={() => toggleTrackMute(track.key)}
                        sx={{
                          color: trackMutes[track.key] ? EDITOR_SURFACE_COLORS.warning : EDITOR_SURFACE_COLORS.muted,
                          bgcolor: trackMutes[track.key] ? 'rgba(251,191,36,0.15)' : 'transparent',
                        }}
                      >
                        {trackMutes[track.key] ? <VolumeOffIcon sx={{ fontSize: 16 }} /> : track.icon}
                      </IconButton>
                    </Tooltip>
                  </Stack>
                ))}
              </Stack>

              {/* 缩放控制 */}
              <Box sx={{ display: 'grid', gridTemplateColumns: '36px minmax(0, 1fr)', gap: 1, alignItems: 'center', minWidth: 0 }}>
                <Typography variant="caption" sx={{ color: EDITOR_SURFACE_COLORS.muted }}>
                  缩放
                </Typography>
                <Slider
                  size="small"
                  aria-label="时间线缩放"
                  value={timelineScale}
                  min={0.8}
                  max={1.35}
                  step={null}
                  marks={TIMELINE_SCALE_MARKS}
                  valueLabelDisplay="auto"
                  valueLabelFormat={(value) => `${value}x`}
                  onChange={(_, value) => setTimelineScale(Array.isArray(value) ? value[0] : value)}
                  sx={{ color: EDITOR_SURFACE_COLORS.accent }}
                />
              </Box>

              <Stack direction="row" spacing={1} sx={{ justifyContent: 'flex-end', flexWrap: 'wrap', rowGap: 0.75 }}>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
                  disabled={loading || !data}
                >
                  保存
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  onClick={() => onSaveScript({ nextStatus: 'approved', generateAudio: true })}
                  disabled={loading || !data}
                  sx={editorPrimaryActionSx}
                >
                  生成音频
                </Button>
              </Stack>
            </Box>

            {/* 时间尺、播放头和共享横向滚动区 */}
            <Box
              sx={{
                display: 'flex',
                flex: '0 0 auto',
                height: TIMELINE_RULER_HEIGHT + timelineTracksHeight + 10,
                overflow: 'hidden',
              }}
            >
              <Box sx={timelineLabelsColumnSx}>
                <Box sx={{ ...trackLabelSx, height: TIMELINE_RULER_HEIGHT }}>
                  时间尺
                </Box>
                {timelineTracks.map((track) => {
                  const locked = trackLocks[track.key]
                  const muted = trackMutes[track.key]

                  return (
                    <Box
                      key={track.key}
                      sx={{
                        ...trackLabelSx,
                        height: track.height,
                        borderTop: `1px solid ${EDITOR_SURFACE_COLORS.border}`,
                        opacity: muted ? 0.5 : 1,
                      }}
                    >
                      {track.icon}
                      <Typography
                        variant="caption"
                        sx={{
                          minWidth: 0,
                          display: 'flex',
                          alignItems: 'center',
                          fontWeight: locked || muted ? 400 : 600,
                        }}
                      >
                        {locked && <LockIcon sx={{ fontSize: 12, mr: 0.5 }} />}
                        {muted && <VolumeOffIcon sx={{ fontSize: 12, mr: 0.5 }} />}
                        {track.label}
                      </Typography>
                    </Box>
                  )
                })}
              </Box>
              <Box sx={{ minWidth: 0, flex: '1 1 auto', overflowX: 'auto', overflowY: 'hidden' }}>
                <Box
                  ref={timelineContentRef}
                  sx={{ position: 'relative', width: timelineContentWidth, minWidth: '100%' }}
                >
                  {/* 播放头指示器 */}
                  {scriptSegments.length > 0 && (
                    <Box
                      role="slider"
                      tabIndex={0}
                      aria-label="拖动播放头定位播放"
                      aria-valuemin={1}
                      aria-valuemax={scriptSegments.length}
                      aria-valuenow={safeSelectedSegmentIndex + 1}
                      onPointerDown={handleTimelineSeekPointerDown}
                      sx={{
                        position: 'absolute',
                        left: playheadLeft,
                        top: 0,
                        bottom: 0,
                        width: 14,
                        transform: 'translateX(-6px)',
                        bgcolor: 'transparent',
                        zIndex: 20,
                        pointerEvents: 'auto',
                        cursor: timelineSeeking ? 'grabbing' : 'grab',
                        touchAction: 'none',
                        outline: 'none',
                        '&::before': {
                          content: '""',
                          position: 'absolute',
                          top: 0,
                          left: 2,
                          width: 0,
                          height: 0,
                          borderLeft: '5px solid transparent',
                          borderRight: '5px solid transparent',
                          borderTop: `7px solid ${EDITOR_SURFACE_COLORS.playhead}`,
                        },
                        '&::after': {
                          content: '""',
                          position: 'absolute',
                          top: 0,
                          bottom: 0,
                          left: 6,
                          width: 2,
                          bgcolor: EDITOR_SURFACE_COLORS.playhead,
                          boxShadow: '0 0 0 1px rgba(239,68,68,0.18)',
                        },
                        '&:focus-visible::after': {
                          boxShadow: '0 0 0 3px rgba(239,68,68,0.28)',
                        },
                      }}
                    />
                  )}

                  <Box
                    onPointerDown={handleTimelineSeekPointerDown}
                    sx={{
                      ...timelineRulerContentSx,
                      width: timelineContentWidth,
                      cursor: timelineSeeking ? 'grabbing' : 'pointer',
                      touchAction: 'none',
                    }}
                  >
                    {editedTimelineModel.ticks.map((tick) => {
                      const selected = tick.segmentIndex === safeSelectedSegmentIndex

                      return (
                        <Typography
                          key={tick.key}
                          variant="caption"
                          sx={{
                            position: 'absolute',
                            left: TIMELINE_SIDE_PADDING + Math.round(tick.startUnit * timelineScale),
                            top: 6,
                            width: 48,
                            color: selected ? EDITOR_SURFACE_COLORS.text : EDITOR_SURFACE_COLORS.muted,
                            fontSize: 10,
                            fontWeight: selected ? 700 : 400,
                            transform: tick.segmentIndex === 0 ? 'none' : 'translateX(-50%)',
                          }}
                        >
                          {tick.label}
                        </Typography>
                      )
                    })}
                  </Box>

                  {timelineTracks.map((track) => (
                    <TimelineTrack
                      key={track.key}
                      color={track.color}
                      clips={editedTimelineModel.clipsByTrack[track.key]}
                      contentWidth={timelineContentWidth}
                      height={track.height}
                      compact={track.compact}
                      selectedIndex={safeSelectedSegmentIndex}
                      scale={timelineScale}
                      onSelectClip={handleSelectSegment}
                      onAdjustClip={handleAdjustTimelineClip}
                      locked={trackLocks[track.key]}
                      muted={trackMutes[track.key]}
                    />
                  ))}
                </Box>
              </Box>
            </Box>
          </Box>
        </Box>
      )}
    </DialogContent>
  </Dialog>
  )
}

export default ScriptEditorDialog
