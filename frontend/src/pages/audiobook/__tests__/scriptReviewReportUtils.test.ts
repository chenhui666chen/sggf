import { describe, expect, it } from 'vitest'

import {
  formatReviewScore,
  getExtraReviewIssueCount,
  getReviewIssueDisplay,
  getReviewScoreVisual,
} from '../scriptReviewReportUtils'

describe('scriptReviewReportUtils', () => {
  it('formats review scores and visual tones', () => {
    expect(formatReviewScore(8.25)).toBe('8.3')
    expect(formatReviewScore(null)).toBe('—')
    expect(getReviewScoreVisual(8)).toEqual({
      backgroundColor: 'rgba(76, 175, 80, 0.15)',
      color: '#2e7d32',
    })
    expect(getReviewScoreVisual(6)).toEqual({
      backgroundColor: 'rgba(255, 152, 0, 0.15)',
      color: '#f57c00',
    })
    expect(getReviewScoreVisual(5.9)).toEqual({
      backgroundColor: 'rgba(244, 67, 54, 0.15)',
      color: '#c62828',
    })
  })

  it('calculates hidden issue counts from reported totals', () => {
    expect(getExtraReviewIssueCount({ issuesCount: 25, issueLength: 20, displayLimit: 20 })).toBe(5)
    expect(getExtraReviewIssueCount({ issuesCount: undefined, issueLength: 22, displayLimit: 20 })).toBe(2)
    expect(getExtraReviewIssueCount({ issuesCount: 3, issueLength: 20, displayLimit: 20 })).toBe(0)
  })

  it('normalizes review issue display labels', () => {
    expect(getReviewIssueDisplay({
      severity: 'critical',
      category: 'script',
      description: '对白生硬',
      suggestion: '改成口语',
    })).toMatchObject({
      color: 'error',
      severityLabel: '严重',
      categoryLabel: '剧本',
      description: '对白生硬',
      suggestion: '改成口语',
    })

    expect(getReviewIssueDisplay({})).toMatchObject({
      color: 'default',
      severityLabel: '未分级',
      categoryLabel: '其他',
      description: '未提供描述',
    })
  })
})
