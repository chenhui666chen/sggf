import {
  Alert,
  Box,
  Typography,
} from '@mui/material'

import type { ScriptReviewDetail } from './types'
import {
  formatReviewScore,
  getReviewScoreVisual,
} from './scriptReviewReportUtils'

interface ScriptReviewSummaryProps {
  review: ScriptReviewDetail
  issueCount: number
  suggestions: string[]
}

const ScriptReviewSummary = ({
  review,
  issueCount,
  suggestions,
}: ScriptReviewSummaryProps) => {
  const scoreVisual = getReviewScoreVisual(review.overall_score)

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
        总体评分
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 70,
            height: 70,
            borderRadius: '50%',
            backgroundColor: scoreVisual.backgroundColor,
          }}
        >
          <Typography
            variant="h5"
            sx={{
              fontWeight: 600,
              color: scoreVisual.color,
            }}
          >
            {formatReviewScore(review.overall_score)}
          </Typography>
        </Box>
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 500 }}>
            等级：{review.overall_grade || 'N/A'}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            问题数：{issueCount}
          </Typography>
        </Box>
      </Box>
      {suggestions.length > 0 && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {suggestions[0]}
          {suggestions.length > 1 && (
            <Typography variant="caption" component="div">
              其余建议在下方详列
            </Typography>
          )}
        </Alert>
      )}
    </Box>
  )
}

export default ScriptReviewSummary
