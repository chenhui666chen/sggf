import type { TFunction } from 'i18next'

import type { StoryExpansionResult } from '@/types/storyExpansion'

export const STORY_EXPANSION_MODE_LABELS: Record<string, string> = {
  total: '常规协同',
  epic_framework: '长篇框架协同',
  volume_detail: '单卷细化协同',
}

export const STORY_EXPANSION_MODE_LABEL_KEYS: Record<string, string> = {
  total: 'storyExpansion.mode.total',
  epic_framework: 'storyExpansion.mode.epicFramework',
  volume_detail: 'storyExpansion.mode.volumeDetail',
}

export const STORY_EXPANSION_STRATEGY_LABELS: Record<string, string> = {
  auto: '自动协同',
  balanced: '均衡推进',
  plot_first: '剧情优先',
  character_first: '人物优先',
}

export const STORY_EXPANSION_STRATEGY_LABEL_KEYS: Record<string, string> = {
  auto: 'storyExpansion.strategy.auto',
  balanced: 'storyExpansion.strategy.balanced',
  plot_first: 'storyExpansion.strategy.plotFirst',
  character_first: 'storyExpansion.strategy.characterFirst',
}

export const STORY_EXPANSION_INTENT_LABELS: Record<string, string> = {
  auto: '自动判断',
  outline_led: '大纲主导',
  character_led: '人物主导',
  balanced: '均衡协同',
}

export const STORY_EXPANSION_INTENT_LABEL_KEYS: Record<string, string> = {
  auto: 'storyExpansion.intent.auto',
  outline_led: 'storyExpansion.intent.outlineLed',
  character_led: 'storyExpansion.intent.characterLed',
  balanced: 'storyExpansion.intent.balanced',
}

export const STORY_PRESERVE_WRITTEN_MODE_LABELS: Record<string, string> = {
  extract_extend: '提取后扩展',
  preserve_written: '仅保护正文',
  regenerate_all: '忽略已写正文',
}

export const STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS: Record<string, string> = {
  extract_extend: 'storyExpansion.preserve.extractExtend',
  preserve_written: 'storyExpansion.preserve.preserveWritten',
  regenerate_all: 'storyExpansion.preserve.regenerateAll',
}

export const STORY_EXPANSION_EXECUTION_MODE_LABELS: Record<string, string> = {
  delta: '单轮增量',
  iterative: '分轮协同',
  epic: '长篇框架',
  volume_detail: '单卷细化',
  repair: '定向修复',
}

export const STORY_EXPANSION_EXECUTION_MODE_LABEL_KEYS: Record<string, string> = {
  delta: 'storyExpansion.execution.delta',
  iterative: 'storyExpansion.execution.iterative',
  epic: 'storyExpansion.execution.epic',
  volume_detail: 'storyExpansion.execution.volumeDetail',
  repair: 'storyExpansion.execution.repair',
}

function resolveLabelKey(
  labelKeys: Record<string, string>,
  value: string | null | undefined,
): string | null {
  return labelKeys[value || ''] || null
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
  t?: TFunction,
): string {
  if (t) {
    const key = resolveLabelKey(STORY_EXPANSION_EXECUTION_MODE_LABEL_KEYS, value)
    if (key) {
      return t(key)
    }
  }
  return resolveLabel(STORY_EXPANSION_EXECUTION_MODE_LABELS, value, fallback)
}

export function getStoryExpansionIntentLabel(
  value: string | null | undefined,
  fallback = '自动判断',
  t?: TFunction,
): string {
  return resolveLabelWithT(STORY_EXPANSION_INTENT_LABELS, STORY_EXPANSION_INTENT_LABEL_KEYS, value, fallback, t)
}

export function getStoryExpansionStrategyLabel(
  value: string | null | undefined,
  fallback = '自动协同',
  t?: TFunction,
): string {
  return resolveLabelWithT(STORY_EXPANSION_STRATEGY_LABELS, STORY_EXPANSION_STRATEGY_LABEL_KEYS, value, fallback, t)
}

export function getStoryExpansionModeLabel(
  value: string | null | undefined,
  fallback = '常规协同',
  t?: TFunction,
): string {
  return resolveLabelWithT(STORY_EXPANSION_MODE_LABELS, STORY_EXPANSION_MODE_LABEL_KEYS, value, fallback, t)
}

export function getStoryExpansionPreserveWrittenModeLabel(
  value: string | null | undefined,
  fallback = '未知模式',
  t?: TFunction,
): string {
  return resolveLabelWithT(STORY_PRESERVE_WRITTEN_MODE_LABELS, STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS, value, fallback, t)
}

export interface StoryExpansionResultLabels {
  expansionModeLabel: string
  strategyLabel: string
  intentLabel: string
  preserveWrittenModeLabel: string
  writtenContextLabel: string
}

function resolveLabelWithT(
  labels: Record<string, string>,
  labelKeys: Record<string, string>,
  value: string | null | undefined,
  fallback: string,
  t?: TFunction,
): string {
  if (t) {
    const key = resolveLabelKey(labelKeys, value)
    if (key) {
      return t(key)
    }
  }
  return resolveLabel(labels, value, fallback)
}

export function getStoryExpansionResultLabels(
  result: StoryExpansionResult | null | undefined,
  t?: TFunction,
): StoryExpansionResultLabels {
  const preserveWrittenModeLabel = resolveLabelWithT(
    STORY_PRESERVE_WRITTEN_MODE_LABELS,
    STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS,
    result?.story_preserve_written_mode,
    '提取后扩展',
    t,
  )
  const writtenContextValue = result?.written_chapter_context?.applied
    ? (
      result?.written_chapter_context?.preserve_written_mode
      || result?.story_preserve_written_mode
      || ''
    )
    : ''

  return {
    expansionModeLabel: resolveLabelWithT(
      STORY_EXPANSION_MODE_LABELS,
      STORY_EXPANSION_MODE_LABEL_KEYS,
      result?.story_expansion_mode,
      '常规协同',
      t,
    ),
    strategyLabel: resolveLabelWithT(
      STORY_EXPANSION_STRATEGY_LABELS,
      STORY_EXPANSION_STRATEGY_LABEL_KEYS,
      result?.story_strategy,
      '自动协同',
      t,
    ),
    intentLabel: resolveLabelWithT(
      STORY_EXPANSION_INTENT_LABELS,
      STORY_EXPANSION_INTENT_LABEL_KEYS,
      result?.story_intent,
      '自动判断',
      t,
    ),
    preserveWrittenModeLabel,
    writtenContextLabel: writtenContextValue
      ? resolveLabelWithT(
        STORY_PRESERVE_WRITTEN_MODE_LABELS,
        STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS,
        writtenContextValue,
        preserveWrittenModeLabel,
        t,
      )
      : '',
  }
}
