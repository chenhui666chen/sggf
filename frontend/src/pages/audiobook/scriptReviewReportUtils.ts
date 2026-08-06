import type { LLMDimensionScore, ScriptReviewIssue } from './types'
import { audiobookColorRoles } from './audiobookTheme'
import {
  ISSUE_DISPLAY_LIMIT,
  categoryLabelMap,
  severityColorMap,
  severityLabelMap,
} from './utils'

// LLM 维度标签映射
export const dimensionLabelMap: Record<string, string> = {
  semantic_coherence: '语义连贯',
  narrative_pacing: '叙事节奏',
  atmosphere_imagery: '氛围画面',
  characterization: '角色贴合',
  dialogue_naturalness: '对白自然',
  emotion_expression: '情感表达',
  audio_cue_relevance: '音效契合',
  speakability: '可播讲性',
}

// 维度分类标签
export const dimensionCategoryLabelMap: Record<string, string> = {
  content_narrative: '内容与叙事',
  character_dialogue: '角色与对白',
  audio_production: '听觉制作',
}

// fix_type 标签
export const fixTypeLabelMap: Record<string, string> = {
  deterministic: '规则修复',
  llm_rewrite: 'LLM改写',
  none: '仅提示',
}

export const getDimensionLabel = (dimensionKey?: string): string =>
  dimensionLabelMap[dimensionKey || ''] || dimensionKey || '未分类'

export const getFixTypeLabel = (fixType?: string): string =>
  fixTypeLabelMap[fixType || ''] || fixType || ''

export const getDimensionScoreVisual = (score?: number) => {
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

export const groupDimensionsByCategory = (
  llmDimensions?: Record<string, LLMDimensionScore>,
): Array<{ category: string; categoryLabel: string; items: Array<{ key: string; label: string; score: number; comment: string }> }> => {
  if (!llmDimensions) return []
  const groups: Record<string, Array<{ key: string; label: string; score: number; comment: string }>> = {}
  for (const [key, dim] of Object.entries(llmDimensions)) {
    const category = dim.category || 'other'
    if (!groups[category]) groups[category] = []
    groups[category].push({
      key,
      label: dim.label || dimensionLabelMap[key] || key,
      score: typeof dim.score === 'number' ? dim.score : 0,
      comment: dim.comment || '',
    })
  }
  return Object.entries(groups).map(([category, items]) => ({
    category,
    categoryLabel: dimensionCategoryLabelMap[category] || category,
    items,
  }))
}

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
    dimensionLabel: issue.dimension ? getDimensionLabel(issue.dimension) : undefined,
    fixTypeLabel: issue.fix_type ? getFixTypeLabel(issue.fix_type) : undefined,
  }
}
