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
): string {
  const stageLabel = toTrimmedString(analysis?.auto_supplement?.character_plan?.stage_label) || '首轮'
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
    parts.push(`${stageLabel}先补到 ${stageTarget} 人`)
    parts.push(`本次任务预计补到 ${taskTarget} 人`)
  } else if (chapterDelta != null && chapterDelta > 0) {
    parts.push(`系统会自动补足 ${chapterDelta} 个承接章节`)
  }

  if (chapterDelta != null && chapterDelta > 0 && isPhasedCharacterPlan) {
    parts.push(`自动补足 ${chapterDelta} 个承接章节`)
  }

  if (estimatedRounds != null && estimatedRounds > 1) {
    parts.push(`预计执行 ${estimatedRounds} 轮`)
  }

  if (parts.length <= 0) {
    return ''
  }

  if (isPhasedCharacterPlan || (estimatedRounds != null && estimatedRounds > 1)) {
    return `当前按分轮协同推进：${parts.join('，')}。`
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

export function formatStoryExpansionDurationMinutes(minutes: number): string {
  const normalized = Math.max(1, Math.trunc(minutes))
  if (normalized < 60) {
    return `${normalized} 分钟`
  }

  const hours = Math.floor(normalized / 60)
  const remainMinutes = normalized % 60
  if (remainMinutes === 0) {
    return `${hours} 小时`
  }
  return `${hours} 小时 ${remainMinutes} 分钟`
}

export function formatStoryExpansionDurationRange(
  minMinutes: number | null | undefined,
  maxMinutes: number | null | undefined,
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
    return formatStoryExpansionDurationMinutes(start)
  }

  return `${formatStoryExpansionDurationMinutes(start)} - ${formatStoryExpansionDurationMinutes(end)}`
}

export function formatStoryExpansionElapsedDuration(elapsedMs: number): string {
  const normalizedMs = Math.max(0, Math.trunc(elapsedMs))
  if (normalizedMs < 60_000) {
    return '不到 1 分钟'
  }

  const totalMinutes = Math.floor(normalizedMs / 60_000)
  return formatStoryExpansionDurationMinutes(totalMinutes)
}
