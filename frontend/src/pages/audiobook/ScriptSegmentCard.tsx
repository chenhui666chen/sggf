import { memo } from 'react'
import {
  Box,
  ListItem,
  TextField,
  Typography,
} from '@mui/material'

import type {
  PreviewType,
  ScriptSegment,
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
  reviewMode: boolean
  review?: { quality_score?: number; needs_regenerate?: boolean }
  previewingType: PreviewType | null
  audioUrl?: string
  regenerating: boolean
  onChangeText: (index: number, value: string) => void
  onPreviewAudio: (index: number, segment: ScriptSegment, previewType: PreviewType) => void
  onRegenerate: (index: number, segment: ScriptSegment) => void
  onReview: (index: number, score: number) => void
  onToggleDetails: (index: number) => void
  onUpdateSegment: (index: number, patch: Partial<ScriptSegment>) => void
}

const ScriptSegmentCard = ({
  segment,
  index,
  detailsOpen,
  reviewMode,
  review,
  previewingType,
  audioUrl,
  regenerating,
  onChangeText,
  onPreviewAudio,
  onRegenerate,
  onReview,
  onToggleDetails,
  onUpdateSegment,
}: ScriptSegmentCardProps) => {
  return (
    <ListItem alignItems="flex-start" sx={{ mb: 1 }}>
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
          previewingType={previewingType}
          regenerating={regenerating}
          onPreviewAudio={onPreviewAudio}
          onRegenerate={onRegenerate}
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
