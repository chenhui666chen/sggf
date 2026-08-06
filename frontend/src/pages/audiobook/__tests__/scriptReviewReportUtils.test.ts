import { describe, expect, it } from 'vitest'

import {
  formatReviewScore,
  getDimensionLabel,
  getDimensionScoreVisual,
  getExtraReviewIssueCount,
  getFixTypeLabel,
  getReviewIssueDisplay,
  getReviewScoreVisual,
  groupDimensionsByCategory,
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

  it('shows dimension and fix_type labels on issues', () => {
    const display = getReviewIssueDisplay({
      severity: 'major',
      category: 'llm_quality',
      description: '对白生硬',
      dimension: 'dialogue_naturalness',
      fix_type: 'llm_rewrite',
    })
    expect(display.dimensionLabel).toBe('对白自然')
    expect(display.fixTypeLabel).toBe('LLM改写')
    expect(display.categoryLabel).toBe('LLM维度')
  })

  it('maps dimension keys to Chinese labels', () => {
    expect(getDimensionLabel('semantic_coherence')).toBe('语义连贯')
    expect(getDimensionLabel('speakability')).toBe('可播讲性')
    expect(getDimensionLabel('unknown_key')).toBe('unknown_key')
    expect(getDimensionLabel(undefined)).toBe('未分类')
  })

  it('maps fix_type keys to labels', () => {
    expect(getFixTypeLabel('deterministic')).toBe('规则修复')
    expect(getFixTypeLabel('llm_rewrite')).toBe('LLM改写')
    expect(getFixTypeLabel('none')).toBe('仅提示')
    expect(getFixTypeLabel(undefined)).toBe('')
  })

  it('provides dimension score visuals', () => {
    expect(getDimensionScoreVisual(8.5).color).toBe('#2e7d32')
    expect(getDimensionScoreVisual(6.5).color).toBe('#f57c00')
    expect(getDimensionScoreVisual(4).color).toBe('#c62828')
  })

  it('groups dimensions by category', () => {
    const groups = groupDimensionsByCategory({
      semantic_coherence: { score: 8, label: '语义连贯', category: 'content_narrative', comment: '' },
      dialogue_naturalness: { score: 7, label: '对白自然', category: 'character_dialogue', comment: '' },
      speakability: { score: 9, label: '可播讲', category: 'audio_production', comment: '' },
    })

    expect(groups).toHaveLength(3)
    const contentGroup = groups.find((g) => g.category === 'content_narrative')
    expect(contentGroup?.categoryLabel).toBe('内容与叙事')
    expect(contentGroup?.items).toHaveLength(1)
    expect(contentGroup?.items[0].label).toBe('语义连贯')
  })

  it('returns empty array for missing dimensions', () => {
    expect(groupDimensionsByCategory(undefined)).toEqual([])
    expect(groupDimensionsByCategory({})).toEqual([])
  })
})
