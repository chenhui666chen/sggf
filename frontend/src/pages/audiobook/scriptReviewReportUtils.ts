import type { ScriptReviewIssue } from './types'
import { audiobookColorRoles } from './audiobookTheme'
import {
  ISSUE_DISPLAY_LIMIT,
  categoryLabelMap,
  severityColorMap,
  severityLabelMap,
} from './utils'

export const getReviewScoreVisual = (score?: number | null) => {
  const normalizedScore = typeof score === 'number' ? score : 0
  if (normalizedScore >= 8) {
    return {
      backgroundColor: audiobookColorRoles.reviewRisk.good.bg,
      color: audiobookColorRoles.reviewRisk.good.text,
    }
  }
  if (normalizedScore >= 6) {
    return {
      backgroundColor: audiobookColorRoles.reviewRisk.warning.bg,
      color: audiobookColorRoles.reviewRisk.warning.text,
    }
  }
  return {
    backgroundColor: audiobookColorRoles.reviewRisk.danger.bg,
    color: audiobookColorRoles.reviewRisk.danger.text,
  }
}

export const formatReviewScore = (score?: number | null): string =>
  typeof score === 'number' ? score.toFixed(1) : '—'

export const getExtraReviewIssueCount = ({
  issuesCount,
  issueLength,
  displayLimit = ISSUE_DISPLAY_LIMIT,
}: {
  issuesCount?: number | null
  issueLength: number
  displayLimit?: number
}): number => {
  const totalIssues = issuesCount || issueLength || 0
  return totalIssues > displayLimit ? totalIssues - displayLimit : 0
}

export const getReviewIssueDisplay = (issue: ScriptReviewIssue) => {
  const severityKey = (issue.severity || '').toLowerCase()
  const categoryKey = (issue.category || '').toLowerCase()

  return {
    color: severityColorMap[severityKey] || 'default',
    severityLabel: severityLabelMap[severityKey] || issue.severity || '未分级',
    categoryLabel: categoryLabelMap[categoryKey] || issue.category || '其他',
    description: issue.description || '未提供描述',
    suggestion: issue.suggestion,
  }
}
