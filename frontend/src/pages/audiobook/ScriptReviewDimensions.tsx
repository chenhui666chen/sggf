import {
  Box,
  Chip,
  Divider,
  LinearProgress,
  Typography,
} from '@mui/material'

import type { LLMDimensionScore } from './types'
import {
  getDimensionScoreVisual,
  groupDimensionsByCategory,
} from './scriptReviewReportUtils'

interface ScriptReviewDimensionsProps {
  llmDimensions?: Record<string, LLMDimensionScore>
}

const ScriptReviewDimensions = ({ llmDimensions }: ScriptReviewDimensionsProps) => {
  if (!llmDimensions || Object.keys(llmDimensions).length === 0) return null

  const groups = groupDimensionsByCategory(llmDimensions)

  return (
    <>
      <Divider textAlign="left">LLM 维度评审</Divider>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {groups.map((group) => (
          <Box key={group.category}>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
              {group.categoryLabel}
            </Typography>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {group.items.map((item) => {
                const visual = getDimensionScoreVisual(item.score)
                return (
                  <Box key={item.key} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography
                      variant="body2"
                      sx={{ minWidth: 72, flexShrink: 0 }}
                    >
                      {item.label}
                    </Typography>
                    <LinearProgress
                      variant="determinate"
                      value={Math.max(0, Math.min(100, item.score * 10))}
                      sx={{
                        flex: 1,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: 'action.hover',
                        '& .MuiLinearProgress-bar': {
                          borderRadius: 4,
                          backgroundColor: visual.color,
                        },
                      }}
                    />
                    <Chip
                      label={item.score.toFixed(1)}
                      size="small"
                      sx={{
                        minWidth: 40,
                        fontWeight: 700,
                        backgroundColor: visual.backgroundColor,
                        color: visual.color,
                      }}
                    />
                  </Box>
                )
              })}
            </Box>
          </Box>
        ))}
      </Box>
    </>
  )
}

export default ScriptReviewDimensions
