import type { StoryExpansionResult } from '@/types/storyExpansion'

export const STORY_EXPANSION_MODE_LABELS: Record<string, string> = {
  total: '常规协同',
  epic_framework: '长篇框架协同',
  volume_detail: '单卷细化协同',
}

export const STORY_EXPANSION_STRATEGY_LABELS: Record<string, string> = {
  auto: '自动协同',
  balanced: '均衡推进',
  plot_first: '剧情优先',
  character_first: '人物优先',
}

export const STORY_EXPANSION_INTENT_LABELS: Record<string, string> = {
  auto: '自动判断',
  outline_led: '大纲主导',
  character_led: '人物主导',
  balanced: '均衡协同',
}

export const STORY_PRESERVE_WRITTEN_MODE_LABELS: Record<string, string> = {
  extract_extend: '提取后扩展',
  preserve_written: '仅保护正文',
  regenerate_all: '忽略已写正文',
}

export const STORY_EXPANSION_EXECUTION_MODE_LABELS: Record<string, string> = {
  delta: '单轮增量',
  iterative: '分轮协同',
  epic: '长篇框架',
  volume_detail: '单卷细化',
  repair: '定向修复',
}

function resolveLabel(
  labels: Record<string, string>,
  value: string | null | undefined,
  fallback: string,
): string {
  return labels[value || ''] || value || fallback
}

export function getStoryExpansionExecutionModeLabel(
  value: string | null | undefined,
  fallback = '自动协同',
): string {
  return resolveLabel(STORY_EXPANSION_EXECUTION_MODE_LABELS, value, fallback)
}

export interface StoryExpansionResultLabels {
  expansionModeLabel: string
  strategyLabel: string
  intentLabel: string
  preserveWrittenModeLabel: string
  writtenContextLabel: string
}

export function getStoryExpansionResultLabels(
  result: StoryExpansionResult | null | undefined,
): StoryExpansionResultLabels {
  const preserveWrittenModeLabel = resolveLabel(
    STORY_PRESERVE_WRITTEN_MODE_LABELS,
    result?.story_preserve_written_mode,
    '提取后扩展',
  )
  const writtenContextValue = result?.written_chapter_context?.applied
    ? (
      result?.written_chapter_context?.preserve_written_mode
      || result?.story_preserve_written_mode
      || ''
    )
    : ''

  return {
    expansionModeLabel: resolveLabel(
      STORY_EXPANSION_MODE_LABELS,
      result?.story_expansion_mode,
      '常规协同',
    ),
    strategyLabel: resolveLabel(
      STORY_EXPANSION_STRATEGY_LABELS,
      result?.story_strategy,
      '自动协同',
    ),
    intentLabel: resolveLabel(
      STORY_EXPANSION_INTENT_LABELS,
      result?.story_intent,
      '自动判断',
    ),
    preserveWrittenModeLabel,
    writtenContextLabel: writtenContextValue
      ? resolveLabel(STORY_PRESERVE_WRITTEN_MODE_LABELS, writtenContextValue, preserveWrittenModeLabel)
      : '',
  }
}
