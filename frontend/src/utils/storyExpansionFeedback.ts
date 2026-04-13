import type { StoryExpansionResult } from '@/types/storyExpansion'
import { coerceStoryExpansionResult } from './storyExpansionResultModel'

function collectUniqueStringItems(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return []
  }

  return Array.from(
    new Set(
      values
        .filter((item: unknown): item is string => typeof item === 'string' && item.trim().length > 0)
        .map((item: string) => item.trim()),
    ),
  )
}

function truncateText(text: string, maxLength = 88): string {
  const value = text.trim()
  if (value.length <= maxLength) {
    return value
  }

  return `${value.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`
}

function getStoryExpansionCharacterPhasePlanText(
  result: StoryExpansionResult | null | undefined,
): string {
  const normalized = coerceStoryExpansionResult(result)
  const characterPlan = normalized?.expansion_analysis?.auto_supplement?.character_plan
  const recommendedRangeText =
    typeof characterPlan?.recommended_range_text === 'string'
      ? characterPlan.recommended_range_text.trim()
      : ''
  const stageLabel =
    typeof characterPlan?.stage_label === 'string'
      ? characterPlan.stage_label.trim()
      : ''
  const stageTarget =
    typeof characterPlan?.stage_target_characters === 'number'
      ? Math.max(0, characterPlan.stage_target_characters)
      : 0
  const taskTarget =
    typeof characterPlan?.task_target_characters === 'number'
      ? Math.max(0, characterPlan.task_target_characters)
      : 0
  const taskTargetIncrement =
    typeof characterPlan?.task_target_increment === 'number'
      ? Math.max(0, characterPlan.task_target_increment)
      : 0
  const remainingToFloor =
    typeof characterPlan?.remaining_to_recommended_min === 'number'
      ? Math.max(0, characterPlan.remaining_to_recommended_min)
      : 0
  const followUpPhase =
    typeof characterPlan?.follow_up_phase === 'string'
      ? characterPlan.follow_up_phase.trim()
      : ''

  if (!recommendedRangeText || !stageLabel || stageTarget <= 0) {
    return ''
  }

  const parts = [`全书建议规模约为 ${recommendedRangeText} 人，${stageLabel}先补到 ${stageTarget} 人`]
  if (taskTarget > stageTarget) {
    parts.push('点击一次开始后，系统会自动连续执行多轮，首轮人物数不是整次任务上限')
    parts.push(
      taskTargetIncrement > 0
        ? `本次自动协同预计补到 ${taskTarget} 人（约新增 ${taskTargetIncrement} 人）`
        : `本次自动协同预计补到 ${taskTarget} 人`,
    )
  }
  if (remainingToFloor > 0 && followUpPhase) {
    parts.push(`剩余约 ${remainingToFloor} 人会在${followUpPhase}继续补齐`)
  }
  return parts.join('；')
}

export function getStoryExpansionSignals(result: StoryExpansionResult | null | undefined): {
  repairedMessages: string[]
  advisoryMessages: string[]
} {
  const normalized = coerceStoryExpansionResult(result)
  const repairedMessages = collectUniqueStringItems(normalized?.alignment_repairs)
  const advisoryMessages = collectUniqueStringItems([
    ...(Array.isArray(normalized?.alignment_warnings) ? normalized.alignment_warnings : []),
    ...(Array.isArray(normalized?.expansion_analysis?.warnings) ? normalized.expansion_analysis.warnings : []),
  ])

  return {
    repairedMessages,
    advisoryMessages,
  }
}

export function getStoryExpansionSignalCounts(result: StoryExpansionResult | null | undefined): {
  repairCount: number
  advisoryCount: number
} {
  const { repairedMessages, advisoryMessages } = getStoryExpansionSignals(result)

  return {
    repairCount: repairedMessages.length,
    advisoryCount: advisoryMessages.length,
  }
}

export function getStoryExpansionSummary(
  result: StoryExpansionResult | null | undefined,
): { label: string; text: string } | null {
  const normalized = coerceStoryExpansionResult(result)
  const characterPhasePlanText = getStoryExpansionCharacterPhasePlanText(normalized)

  const coordinationSummary =
    typeof normalized?.coordination_summary === 'string'
      ? normalized.coordination_summary.trim()
      : ''
  if (coordinationSummary) {
    return { label: '协同摘要', text: coordinationSummary }
  }

  const analysisSummary =
    typeof normalized?.expansion_analysis?.analysis_summary === 'string'
      ? normalized.expansion_analysis.analysis_summary.trim()
      : ''
  if (analysisSummary) {
    return { label: '协同摘要', text: analysisSummary }
  }

  const { repairedMessages, advisoryMessages } = getStoryExpansionSignals(normalized)
  if (repairedMessages.length > 0 && advisoryMessages.length <= 0) {
    return { label: '协同修复', text: repairedMessages.join('；') }
  }
  if (advisoryMessages.length > 0) {
    const parts = [advisoryMessages.join('；')]
    if (repairedMessages.length > 0) {
      parts.push(`系统已自动修复：${repairedMessages.join('；')}`)
    }
    return { label: '协同提醒', text: parts.join('；') }
  }

  if (characterPhasePlanText) {
    return { label: '人物计划', text: characterPhasePlanText }
  }

  return null
}

export function buildStoryExpansionCompletionMessage(
  baseMessage: string,
  result: StoryExpansionResult | null | undefined,
): string {
  const { repairCount, advisoryCount } = getStoryExpansionSignalCounts(result)
  const summary = getStoryExpansionSummary(result)
  const characterPhasePlanText = getStoryExpansionCharacterPhasePlanText(result)
  const statusParts: string[] = []

  if (repairCount > 0) {
    statusParts.push(`已自动修复 ${repairCount} 处人物承接`)
  }
  if (advisoryCount > 0) {
    statusParts.push(`仍有 ${advisoryCount} 条协同提醒`)
  }

  if (!summary && !characterPhasePlanText && statusParts.length <= 0) {
    return baseMessage
  }

  const parts = [baseMessage]
  if (statusParts.length > 0) {
    parts.push(statusParts.join('；'))
  }
  if (characterPhasePlanText && summary?.label !== '人物计划') {
    parts.push(`人物计划：${truncateText(characterPhasePlanText, 72)}`)
  }
  if (summary) {
    parts.push(`${summary.label}：${truncateText(summary.text)}`)
  }

  return parts.join(' ')
}
