import {
  Box,
} from '@mui/material'

import ScriptReviewDimensions from './ScriptReviewDimensions'
import ScriptReviewIssueList from './ScriptReviewIssueList'
import ScriptReviewMetricSections from './ScriptReviewMetricSections'
import ScriptReviewSuggestions from './ScriptReviewSuggestions'
import ScriptReviewSummary from './ScriptReviewSummary'
import type { ScriptReviewDetail } from './types'
import {
  getExtraReviewIssueCount,
} from './scriptReviewReportUtils'

interface ScriptReviewReportProps {
  review: ScriptReviewDetail | null
  selectedIssueIndex?: number | null
  onSelectIssue?: (index: number | null) => void
}

const ScriptReviewReport = ({
  review,
  selectedIssueIndex = null,
  onSelectIssue,
}: ScriptReviewReportProps) => {
  if (!review) return null
  const scriptQuality = review.script_quality || {}
  const audioBalance = review.audio_balance || {}
  const pacing = review.pacing || {}
  const issues = review.issues || []
  const suggestions = review.revision_suggestions || []
  const issueCount = review.issues_count ?? issues.length ?? 0
  const extraIssues = getExtraReviewIssueCount({
    issuesCount: review.issues_count,
    issueLength: issues.length,
  })

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <ScriptReviewSummary
        review={review}
        issueCount={issueCount}
        suggestions={suggestions}
      />
      <ScriptReviewMetricSections
        scriptQuality={scriptQuality}
        audioBalance={audioBalance}
        pacing={pacing}
      />
      <ScriptReviewDimensions llmDimensions={review.llm_dimensions} />
      <ScriptReviewIssueList
        issues={issues}
        extraIssues={extraIssues}
        selectedIssueIndex={selectedIssueIndex}
        onSelectIssue={onSelectIssue}
      />
      <ScriptReviewSuggestions suggestions={suggestions} />
    </Box>
  )
}

export default ScriptReviewReport
