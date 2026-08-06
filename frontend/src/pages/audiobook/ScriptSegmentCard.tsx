import { memo } from 'react'
import {
  Box,
  ListItem,
  TextField,
  Typography,
} from '@mui/material'

import type {
  PendingSegmentRegeneration,
  PreviewType,
  ScriptSegment,
  SegmentSourceMode,
} from './types'
import {
  formatScriptSegmentSummary,
} from './scriptSegmentCardUtils'
import ScriptSegmentActions from './ScriptSegmentActions'
import ScriptSegmentDetailsPanel from './ScriptSegmentDetailsPanel'

interface ScriptSegmentCardProps {
  segment: ScriptSegment
  index: number
  detailsOpen: boolean
  selected?: boolean
  reviewMode: boolean
  review?: { quality_score?: number; needs_regenerate?: boolean }
  previewingType: PreviewType | null
  audioUrl?: string
  pendingRegeneration?: Partial<Record<PreviewType, PendingSegmentRegeneration>>
  regenerating: boolean
  voiceRecording: boolean
  voiceRecordingDisabled: boolean
  onChangeText: (index: number, value: string) => void
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
  onUpdateSegment: (index: number, patch: Partial<ScriptSegment>) => void
  onSelect?: (index: number) => void
}

const ScriptSegmentCard = ({
  segment,
  index,
  detailsOpen,
  selected = false,
  reviewMode,
  review,
  previewingType,
  audioUrl,
  pendingRegeneration,
  regenerating,
  voiceRecording,
  voiceRecordingDisabled,
  onChangeText,
  onPreviewAudio,
  onRegenerate,
  onStartVoiceRecording,
  onStopVoiceRecording,
  onApplyRegeneration,
  onDiscardRegeneration,
  onReview,
  onToggleDetails,
  onUpdateSegment,
  onSelect,
}: ScriptSegmentCardProps) => {
  return (
    <ListItem
      alignItems="flex-start"
      onFocusCapture={() => onSelect?.(index)}
      onClickCapture={() => onSelect?.(index)}
      sx={{
        mb: 1,
        border: '1px solid',
        borderColor: selected ? 'primary.main' : 'transparent',
        borderRadius: 1,
        bgcolor: selected ? 'rgba(37, 99, 235, 0.06)' : '#ffffff',
        contentVisibility: 'auto',
        containIntrinsicSize: '220px',
        transition: 'background-color 120ms ease, border-color 120ms ease',
      }}
    >
      <Box sx={{ width: '100%' }}>
        <Typography variant="caption" color="text.secondary">
          {formatScriptSegmentSummary(segment, index)}
        </Typography>
        <TextField
          fullWidth
          multiline
          minRows={2}
          margin="dense"
          value={segment.text || ''}
          onChange={(event) => onChangeText(index, event.target.value)}
        />
        <ScriptSegmentActions
          segment={segment}
          index={index}
          detailsOpen={detailsOpen}
          reviewMode={reviewMode}
          review={review}
          pendingRegeneration={pendingRegeneration}
          previewingType={previewingType}
          regenerating={regenerating}
          voiceRecording={voiceRecording}
          voiceRecordingDisabled={voiceRecordingDisabled}
          onPreviewAudio={onPreviewAudio}
          onRegenerate={onRegenerate}
          onStartVoiceRecording={onStartVoiceRecording}
          onStopVoiceRecording={onStopVoiceRecording}
          onApplyRegeneration={onApplyRegeneration}
          onDiscardRegeneration={onDiscardRegeneration}
          onReview={onReview}
          onToggleDetails={onToggleDetails}
        />

        {detailsOpen && (
          <ScriptSegmentDetailsPanel
            segment={segment}
            index={index}
            onUpdateSegment={onUpdateSegment}
          />
        )}

        {audioUrl && (
          <Box sx={{ mt: 1 }}>
            <audio controls src={audioUrl} />
          </Box>
        )}
      </Box>
    </ListItem>
  )
}

export default memo(ScriptSegmentCard)
