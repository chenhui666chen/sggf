import type { TFunction } from 'i18next'

import type {
  StoryExpansionAnalysis,
  StoryExpansionDurationEstimate,
  StoryExpansionTaskMeta,
} from '@/types/storyExpansion'

function toPositiveInteger(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null
  }

  const normalized = Math.trunc(value)
  return normalized > 0 ? normalized : null
}

function toTrimmedString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

export function getStoryExpansionDurationEstimate(
  analysis: StoryExpansionAnalysis | null | undefined,
): StoryExpansionDurationEstimate | null {
  const minMinutes = toPositiveInteger(analysis?.estimated_duration_minutes_min)
  const maxMinutes = toPositiveInteger(analysis?.estimated_duration_minutes_max)

  if (minMinutes == null && maxMinutes == null) {
    return null
  }

  if (minMinutes != null && maxMinutes != null) {
    return {
      estimated_duration_minutes_min: Math.min(minMinutes, maxMinutes),
      estimated_duration_minutes_max: Math.max(minMinutes, maxMinutes),
    }
  }

  return {
    estimated_duration_minutes_min: minMinutes ?? maxMinutes,
    estimated_duration_minutes_max: maxMinutes ?? minMinutes,
  }
}

export function getStoryExpansionWaitHint(
  analysis: StoryExpansionAnalysis | null | undefined,
  t?: TFunction,
): string {
  const stageLabel = toTrimmedString(analysis?.auto_supplement?.character_plan?.stage_label)
    || (t ? t('storyExpansion.timing.firstRound') : '首轮')
  const stageTarget = toPositiveInteger(analysis?.auto_supplement?.character_plan?.stage_target_characters)
  const taskTarget = toPositiveInteger(analysis?.auto_supplement?.character_plan?.task_target_characters)
  const chapterDelta = toPositiveInteger(analysis?.auto_supplement?.chapter_delta)
  const estimatedRounds = toPositiveInteger(
    analysis?.estimated_rounds ?? analysis?.model_plan?.estimated_rounds,
  )

  const parts: string[] = []
  const isPhasedCharacterPlan = (
    stageTarget != null
    && taskTarget != null
    && taskTarget > stageTarget
  )

  if (isPhasedCharacterPlan) {
    parts.push(t
      ? t('storyExpansion.timing.stageReachCharacters', { stage: stageLabel, target: stageTarget })
      : `${stageLabel}先补到 ${stageTarget} 人`)
    parts.push(t
      ? t('storyExpansion.timing.taskEstimatedReachCharacters', { target: taskTarget })
      : `本次任务预计补到 ${taskTarget} 人`)
  } else if (chapterDelta != null && chapterDelta > 0) {
    parts.push(t
      ? t('storyExpansion.timing.autoSupplementChapters', { count: chapterDelta })
      : `系统会自动补足 ${chapterDelta} 个承接章节`)
  }

  if (chapterDelta != null && chapterDelta > 0 && isPhasedCharacterPlan) {
    parts.push(t
      ? t('storyExpansion.timing.autoSupplementChaptersShort', { count: chapterDelta })
      : `自动补足 ${chapterDelta} 个承接章节`)
  }

  if (estimatedRounds != null && estimatedRounds > 1) {
    parts.push(t
      ? t('storyExpansion.timing.estimatedRounds', { count: estimatedRounds })
      : `预计执行 ${estimatedRounds} 轮`)
  }

  if (parts.length <= 0) {
    return ''
  }

  if (isPhasedCharacterPlan || (estimatedRounds != null && estimatedRounds > 1)) {
    return t
      ? t('storyExpansion.timing.phasedCollaborationPrefix', { parts: parts.join('，') })
      : `当前按分轮协同推进：${parts.join('，')}。`
  }

  return `${parts.join('，')}。`
}

export function getStoryExpansionTaskMeta(
  analysis: StoryExpansionAnalysis | null | undefined,
): StoryExpansionTaskMeta | null {
  const estimate = getStoryExpansionDurationEstimate(analysis)
  const waitHint = getStoryExpansionWaitHint(analysis)

  if (!estimate && !waitHint) {
    return null
  }

  return {
    ...(estimate ?? {}),
    wait_hint: waitHint || undefined,
  }
}

export function formatStoryExpansionDurationMinutes(minutes: number, t?: TFunction): string {
  const normalized = Math.max(1, Math.trunc(minutes))
  if (normalized < 60) {
    return t ? t('storyExpansion.timing.minutes', { count: normalized }) : `${normalized} 分钟`
  }

  const hours = Math.floor(normalized / 60)
  const remainMinutes = normalized % 60
  if (remainMinutes === 0) {
    return t ? t('storyExpansion.timing.hours', { count: hours }) : `${hours} 小时`
  }
  return t
    ? t('storyExpansion.timing.hoursMinutes', { hours, minutes: remainMinutes })
    : `${hours} 小时 ${remainMinutes} 分钟`
}

export function formatStoryExpansionDurationRange(
  minMinutes: number | null | undefined,
  maxMinutes: number | null | undefined,
  t?: TFunction,
): string {
  const normalizedMin = toPositiveInteger(minMinutes)
  const normalizedMax = toPositiveInteger(maxMinutes)

  if (normalizedMin == null && normalizedMax == null) {
    return ''
  }

  const start = normalizedMin ?? normalizedMax
  const end = normalizedMax ?? normalizedMin
  if (start == null || end == null) {
    return ''
  }

  if (start >= end) {
    return formatStoryExpansionDurationMinutes(start, t)
  }

  return `${formatStoryExpansionDurationMinutes(start, t)} - ${formatStoryExpansionDurationMinutes(end, t)}`
}

export function formatStoryExpansionElapsedDuration(elapsedMs: number, t?: TFunction): string {
  const normalizedMs = Math.max(0, Math.trunc(elapsedMs))
  if (normalizedMs < 60_000) {
    return t ? t('storyExpansion.timing.lessThanMinute') : '不到 1 分钟'
  }

  const totalMinutes = Math.floor(normalizedMs / 60_000)
  return formatStoryExpansionDurationMinutes(totalMinutes, t)
}
