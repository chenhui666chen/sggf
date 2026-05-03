import type { Ref } from 'react'
import { Box, Chip, Paper } from '@mui/material'
import { styled } from '@mui/material/styles'

import type { BrowserPlayerSegment } from './browserPlayerTypes'

const HighlightedText = styled('span')<{ active: boolean }>(({ theme, active }) => ({
  padding: '2px 4px',
  borderRadius: 4,
  transition: 'all 0.3s',
  backgroundColor: active ? theme.palette.primary.light + '40' : 'transparent',
  color: active ? theme.palette.primary.main : 'inherit',
  fontWeight: active ? 600 : 400,
}))

interface BrowserPlayerSubtitlePanelProps {
  segments: BrowserPlayerSegment[]
  highlightedSegmentIndex: number | null
  textContainerRef: Ref<HTMLDivElement>
}

const BrowserPlayerSubtitlePanel: React.FC<BrowserPlayerSubtitlePanelProps> = ({
  segments,
  highlightedSegmentIndex,
  textContainerRef,
}) => (
  <Paper
    ref={textContainerRef}
    sx={{ p: 2, mb: 2, flex: 1, overflowY: 'auto', minHeight: 200 }}
  >
    <Box>
      {segments.map((segment, index) => (
        <Box
          key={index}
          data-segment-index={index}
          sx={{ mb: 1, p: 0.5, borderRadius: 1 }}
        >
          {segment.type === 'dialogue' && segment.character && (
            <Chip
              label={segment.character}
              size="small"
              sx={{ mb: 0.5, mr: 1 }}
              color="primary"
              variant="outlined"
            />
          )}
          <HighlightedText active={highlightedSegmentIndex === index}>
            {segment.text || ''}
          </HighlightedText>
        </Box>
      ))}
    </Box>
  </Paper>
)

export default BrowserPlayerSubtitlePanel
