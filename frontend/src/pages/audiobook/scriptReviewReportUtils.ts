import type { TranslateFn } from './audioLibraryDisplay'
import type { LLMDimensionScore, ScriptReviewIssue } from './types'
import { audiobookColorRoles } from './audiobookTheme'
import {
  ISSUE_DISPLAY_LIMIT,
  categoryLabelMap,
  severityColorMap,
  severityLabelMap,
} from './utils'

// LLM 维度标签映射（中文值作为无 t 场景回退，UI 展示统一走 dimensionLabelKeys）
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

// LLM 维度标签 i18n key 映射
const dimensionLabelKeys: Record<string, string> = {
  semantic_coherence: 'audiobook.scriptReviewReportUtils.semanticCoherence',
  narrative_pacing: 'audiobook.scriptReviewReportUtils.narrativePacing',
  atmosphere_imagery: 'audiobook.scriptReviewReportUtils.atmosphereImagery',
  characterization: 'audiobook.scriptReviewReportUtils.characterization',
  dialogue_naturalness: 'audiobook.scriptReviewReportUtils.dialogueNaturalness',
  emotion_expression: 'audiobook.scriptReviewReportUtils.emotionExpression',
  audio_cue_relevance: 'audiobook.scriptReviewReportUtils.audioCueRelevance',
  speakability: 'audiobook.scriptReviewReportUtils.speakability',
}

// 维度分类标签（中文值作为无 t 场景回退，UI 展示统一走 dimensionCategoryLabelKeys）
export const dimensionCategoryLabelMap: Record<string, string> = {
  content_narrative: '内容与叙事',
  character_dialogue: '角色与对白',
  audio_production: '听觉制作',
}

// 维度分类标签 i18n key 映射
const dimensionCategoryLabelKeys: Record<string, string> = {
  content_narrative: 'audiobook.scriptReviewReportUtils.contentNarrative',
  character_dialogue: 'audiobook.scriptReviewReportUtils.characterDialogue',
  audio_production: 'audiobook.scriptReviewReportUtils.audioProduction',
}

// fix_type 标签（中文值作为无 t 场景回退，UI 展示统一走 fixTypeLabelKeys）
export const fixTypeLabelMap: Record<string, string> = {
  deterministic: '规则修复',
  llm_rewrite: 'LLM改写',
  none: '仅提示',
}

// fix_type 标签 i18n key 映射
const fixTypeLabelKeys: Record<string, string> = {
  deterministic: 'audiobook.scriptReviewReportUtils.deterministic',
  llm_rewrite: 'audiobook.scriptReviewReportUtils.llmRewrite',
  none: 'audiobook.scriptReviewReportUtils.none',
}

// 严重度标签 i18n key 映射
const severityLabelKeys: Record<string, string> = {
  critical: 'audiobook.scriptReviewReportUtils.critical',
  major: 'audiobook.scriptReviewReportUtils.major',
  minor: 'audiobook.scriptReviewReportUtils.minor',
}

// 问题分类标签 i18n key 映射
const categoryLabelKeys: Record<string, string> = {
  script: 'audiobook.scriptReviewReportUtils.script',
  audio: 'audiobook.scriptReviewReportUtils.audio',
  audio_assets: 'audiobook.scriptReviewReportUtils.audioAssets',
  pacing: 'audiobook.scriptReviewReportUtils.pacing',
  llm_quality: 'audiobook.scriptReviewReportUtils.llmQuality',
}

export const getDimensionLabel = (dimensionKey?: string, t?: TranslateFn): string => {
  const key = dimensionKey || ''
  if (t) {
    const labelKey = dimensionLabelKeys[key]
    return labelKey ? t(labelKey) : (key || t('audiobook.scriptReviewReportUtils.uncategorized'))
  }
  return dimensionLabelMap[key] || key || '未分类'
}

export const getFixTypeLabel = (fixType?: string, t?: TranslateFn): string => {
  const key = fixType || ''
  if (t) {
    const labelKey = fixTypeLabelKeys[key]
    return labelKey ? t(labelKey) : key
  }
  return fixTypeLabelMap[key] || key || ''
}

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
  t?: TranslateFn,
): Array<{ category: string; categoryLabel: string; items: Array<{ key: string; label: string; score: number; comment: string }> }> => {
  if (!llmDimensions) return []
  const groups: Record<string, Array<{ key: string; label: string; score: number; comment: string }>> = {}
  for (const [key, dim] of Object.entries(llmDimensions)) {
    const category = dim.category || 'other'
    if (!groups[category]) groups[category] = []
    groups[category].push({
      key,
      label: t
        ? (dimensionLabelKeys[key] ? t(dimensionLabelKeys[key]) : (dim.label || key))
        : (dim.label || dimensionLabelMap[key] || key),
      score: typeof dim.score === 'number' ? dim.score : 0,
      comment: dim.comment || '',
    })
  }
  return Object.entries(groups).map(([category, items]) => ({
    category,
    categoryLabel: t
      ? (dimensionCategoryLabelKeys[category] ? t(dimensionCategoryLabelKeys[category]) : category)
      : (dimensionCategoryLabelMap[category] || category),
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

export const getReviewIssueDisplay = (issue: ScriptReviewIssue, t?: TranslateFn) => {
  const severityKey = (issue.severity || '').toLowerCase()
  const categoryKey = (issue.category || '').toLowerCase()

  const severityLabel = t
    ? (severityLabelKeys[severityKey] ? t(severityLabelKeys[severityKey]) : (issue.severity || t('audiobook.scriptReviewReportUtils.ungraded')))
    : (severityLabelMap[severityKey] || issue.severity || '未分级')
  const categoryLabel = t
    ? (categoryLabelKeys[categoryKey] ? t(categoryLabelKeys[categoryKey]) : (issue.category || t('audiobook.scriptReviewReportUtils.other')))
    : (categoryLabelMap[categoryKey] || issue.category || '其他')

  return {
    color: severityColorMap[severityKey] || 'default',
    severityLabel,
    categoryLabel,
    description: issue.description || (t ? t('audiobook.scriptReviewReportUtils.noDescription') : '未提供描述'),
    suggestion: issue.suggestion,
    dimensionLabel: issue.dimension ? getDimensionLabel(issue.dimension, t) : undefined,
    fixTypeLabel: issue.fix_type ? getFixTypeLabel(issue.fix_type, t) : undefined,
  }
}
